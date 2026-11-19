"""决策审批 API：列表/详情/批准/驳回/批量。

职责：HTTP 解析与响应序列化、分页参数钳制、服务调用与事务兜底。
依赖：FastAPI、app.core.deps、app.services.decision。
边界：不做业务规则判定；RBAC 与越权语义由服务层收敛。

权限矩阵（服务层强制，路由层不做二次 403，保证越权语义统一）：
- 管理端读/写：super_admin、league_officer 全部可操作；
  counselor 仅 L1/L2 且限本班（越界 404）；security_officer 仅 L1/L2；
  其余角色（含 student/auditor）一律按无资源处理。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query

from app.core.deps import CurrentUserDep, DbSession
from app.models.decision import Decision as DecisionModel
from app.models.decision import ReviewLog as ReviewLogModel
from app.repositories.decision import DecisionRepository, ReviewLogRepository
from app.schemas.decision import (
    ApproveBody,
    BatchApproveBody,
    BatchApproveItem,
    DecisionDetailResponse,
    DecisionListItem,
    RejectBody,
)
from app.services.decision.review import ReviewService
from app.services.decision.review_detail import ReviewDetailService

router = APIRouter(prefix="/api/v1/admin", tags=["decision-admin"])

_LEVELS = ("L0", "L1", "L2", "L3", "L4")
# 排序白名单：只允许这三项，非法值回退默认。
_SORTS = ("created_at/desc", "confidence/desc", "level/asc")
_STATUSES = (
    "PENDING_REVIEW",
    "APPROVED",
    "REJECTED",
    "ADJUSTED",
    "AUTO_APPROVED",
    "APPEALING",
    "APPEAL_UPHELD",
    "APPEAL_REJECTED",
    "EXPIRED",
)

READ_ROLES = frozenset({"super_admin", "league_officer", "counselor", "security_officer"})


def _page_params(page: int, page_size: int) -> tuple[int, int]:
    """钳制分页参数。"""
    return max(1, page), min(max(1, page_size), 100)


def _parse_dt(value: str | None) -> datetime | None:
    """解析 ISO 时间过滤参数；非法返回 None（由调用方忽略）。"""
    if not value:
        return None
    try:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        moment = datetime.fromisoformat(text)
        return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    except ValueError:
        return None


def _require_read(role: str) -> None:
    """读权限：非管理角色按无资源处理（由服务层抛 NotFoundError 映射 404）。"""
    from app.core.errors import NotFoundError

    if role not in READ_ROLES:
        raise NotFoundError("请求的资源不存在")


def _serialize_list(row: DecisionModel) -> dict[str, object]:
    """ORM 行转列表项字典。"""
    item = DecisionListItem.model_validate(row)
    return item.model_dump(mode="json")


def _serialize_detail(row: DecisionModel, logs: Sequence[ReviewLogModel]) -> dict[str, object]:
    """ORM 行 + 审批轨迹转详情字典。"""
    payload = DecisionDetailResponse.model_validate(row)
    dumped = payload.model_dump(mode="json")
    dumped["review_logs"] = [
        {
            "id": item.id,
            "action": item.action,
            "from_status": item.from_status,
            "to_status": item.to_status,
            "from_level": item.from_level,
            "to_level": item.to_level,
            "note": item.note,
            "operator": item.operator,
            "created_at": (
                item.created_at.isoformat() if isinstance(item.created_at, datetime) else None
            ),
        }
        for item in logs
    ]
    return dumped


@router.get("/decisions")
def list_decisions(
    session: DbSession,
    user: CurrentUserDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, max_length=32),
    student_id: str | None = Query(None, max_length=64),
    level: str | None = Query(None, max_length=8),
    start: str | None = Query(None, max_length=64),
    end: str | None = Query(None, max_length=64),
    point_id: str | None = Query(None, max_length=64),
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
    sort: str = Query("created_at/desc", max_length=32),
) -> dict[str, object]:
    """决策列表（多维筛选：状态/学生/档位/时间/点位/最低置信度）。

    排序为白名单：`created_at/desc`、`confidence/desc`、`level/asc`；
    非法值回退到创建时间倒序。
    """
    _require_read(user.role or "")
    safe_page, safe_size = _page_params(page, page_size)
    safe_sort = sort if sort in _SORTS else "created_at/desc"
    repo = DecisionRepository(session)
    safe_status = status if status in _STATUSES else None
    safe_level = level if level in _LEVELS else None
    start_at = _parse_dt(start)
    end_at = _parse_dt(end)
    rows = repo.list_with_filters(
        status=safe_status,
        student_id=student_id,
        level=safe_level,
        start=start_at,
        end=end_at,
        point_id=point_id,
        min_confidence=min_confidence,
        sort=safe_sort,
        limit=safe_size,
        offset=(safe_page - 1) * safe_size,
    )
    total = repo.count_with_filters(
        status=safe_status,
        student_id=student_id,
        level=safe_level,
        start=start_at,
        end=end_at,
        point_id=point_id,
        min_confidence=min_confidence,
    )
    return {
        "items": [_serialize_list(row) for row in rows],
        "total": total,
        "page": safe_page,
        "page_size": safe_size,
    }


@router.get("/decisions/pending-count")
def get_pending_count(session: DbSession, user: CurrentUserDep) -> dict[str, object]:
    """待审批决策数（顶栏徽标与轮询用）。"""
    _require_read(user.role or "")
    repo = DecisionRepository(session)
    return {"pending": repo.count_with_filters(status="PENDING_REVIEW")}


@router.get("/decisions/{decision_id}")
def get_decision_detail(
    decision_id: str, session: DbSession, user: CurrentUserDep
) -> dict[str, object]:
    """决策详情（含因子/证据/审批历史/事件/身份/学生/风险提示）。"""
    _require_read(user.role or "")
    repo = DecisionRepository(session)
    row = repo.get_by_id(decision_id)
    if row is None:
        from app.core.errors import NotFoundError

        raise NotFoundError("请求的资源不存在")
    logs = ReviewLogRepository(session).list_by_decision(decision_id)
    detail = _serialize_detail(row, logs)
    # 追加聚合载荷：事件 / 身份 / 学生 / 风险提示（审批页一站式取齐）。
    review_logs = detail.get("review_logs")
    log_list: list[dict[str, Any]] = review_logs if isinstance(review_logs, list) else []
    aggregate = ReviewDetailService(session).build_detail(row, log_list)
    detail["event"] = aggregate["event"]
    detail["identity_resolution"] = aggregate["identity_resolution"]
    detail["student"] = aggregate["student"]
    # 证据引用：合并检测框与原图尺寸（前端据此渲染「证据帧 + 检测框叠加」）。
    detail["evidence_refs"] = aggregate["evidence_refs"]
    detail["risk_hints"] = aggregate["risk_hints"]
    return detail


@router.post("/decisions/{decision_id}/approve", status_code=200)
def approve_decision(
    decision_id: str,
    body: ApproveBody,
    session: DbSession,
    user: CurrentUserDep,
) -> dict[str, object]:
    """批准决策（可降档，只降不升）。

    事务由服务层收敛（成功提交/失败回滚），路由层只做参数校验与响应序列化。
    """
    service = ReviewService(session)
    decided = service.approve(
        decision_id,
        user.subject,
        user.role or "",
        level=body.level,
        note=body.note,
    )
    logs = ReviewLogRepository(session).list_by_decision(decision_id)
    return _serialize_detail(decided, logs)


@router.post("/decisions/{decision_id}/reject", status_code=200)
def reject_decision(
    decision_id: str,
    body: RejectBody,
    session: DbSession,
    user: CurrentUserDep,
) -> dict[str, object]:
    """驳回决策（理由必填，同步回流训练集）。

    事务由服务层收敛（成功提交/失败回滚），路由层只做参数校验与响应序列化。
    """
    service = ReviewService(session)
    decided = service.reject(decision_id, user.subject, user.role or "", body.reason)
    logs = ReviewLogRepository(session).list_by_decision(decision_id)
    return _serialize_detail(decided, logs)


@router.post("/decisions/batch-approve", status_code=200)
def batch_approve_decisions(
    body: BatchApproveBody, session: DbSession, user: CurrentUserDep
) -> dict[str, object]:
    """批量批准；单条失败不影响整批（逐条返回成功/失败）。"""
    service = ReviewService(session)
    results = service.batch_approve(
        list(body.decision_ids), user.subject, user.role or "", note=body.note
    )
    items = [
        BatchApproveItem(
            decision_id=str(item.get("decision_id")),
            ok=bool(item.get("ok")),
            status=str(item["status"]) if item.get("status") is not None else None,
            error=str(item["error"]) if item.get("error") is not None else None,
        ).model_dump(mode="json")
        for item in results
    ]
    return {"items": items, "total": len(items)}


__all__ = ["router"]

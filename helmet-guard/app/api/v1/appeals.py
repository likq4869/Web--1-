"""申诉 API：管理端裁决 + 学生端提交/查询。

职责：HTTP 解析与响应序列化、事务兜底、学生本人绑定。
依赖：FastAPI、app.core.deps、app.services.appeal。
边界：不做业务规则判定；权限与归属由服务层收敛。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.deps import CurrentUserDep, DbSession
from app.core.errors import NotFoundError
from app.models.identity import Student
from app.repositories.appeal import AppealRepository
from app.repositories.decision import DecisionRepository
from app.repositories.student import StudentRepository
from app.schemas.decision import (
    AppealResolveBody,
    AppealResponse,
    AppealSubmitBody,
    DecisionListItem,
)
from app.schemas.me import MeOverviewOut
from app.services.appeal.service import AppealService
from app.services.me.service import MeOverviewService

admin_router = APIRouter(prefix="/api/v1/admin", tags=["appeal-admin"])
me_router = APIRouter(prefix="/api/v1/me", tags=["appeal-me"])

ADMIN_RESOLVE_ROLES = frozenset({"super_admin", "league_officer"})


def _serialize(row: object) -> dict[str, object]:
    """申诉 ORM 行转字典（含 attachments 归一化）。"""
    payload = AppealResponse.model_validate(row)
    dumped = payload.model_dump(mode="json")
    attachments = getattr(row, "attachments", None)
    if isinstance(attachments, list):
        dumped["attachments"] = [
            item if isinstance(item, str) else str(item) for item in attachments
        ]
    elif attachments is None:
        dumped["attachments"] = []
    return dumped


def _resolve_student_id(session: DbSession, user: CurrentUserDep) -> str:
    """按登录主体解析学号：student 角色按 user_id 反查 students 表。

    Returns:
        学号。

    Raises:
        NotFoundError: 非学生角色或未绑定学号。
    """
    if (user.role or "") != "student":
        raise NotFoundError("请求的资源不存在")
    row = StudentRepository(session).find_by(user_id=user.subject)
    if row is None:
        # 回退：subject 本身即学号（测试与种子直连场景）。
        fallback = session.get(Student, user.subject)
        if fallback is None:
            raise NotFoundError("请求的资源不存在")
        return str(fallback.student_id)
    return str(row.student_id)


@admin_router.get("/appeals")
def list_appeals(
    session: DbSession,
    user: CurrentUserDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, max_length=32),
) -> dict[str, object]:
    """申诉列表（管理端多维筛选）。"""
    if (user.role or "") not in ADMIN_RESOLVE_ROLES and (user.role or "") != "auditor":
        raise NotFoundError("请求的资源不存在")
    safe_page = max(1, page)
    safe_size = min(max(1, page_size), 100)
    repo = AppealRepository(session)
    total = repo.count_all(status=status)
    rows = repo.list_all(
        status=status, limit=safe_size, offset=(safe_page - 1) * safe_size
    )
    return {
        "items": [_serialize(row) for row in rows],
        "total": total,
        "page": safe_page,
        "page_size": safe_size,
    }


@admin_router.post("/appeals/{appeal_id}/resolve", status_code=200)
def resolve_appeal(
    appeal_id: str,
    body: AppealResolveBody,
    session: DbSession,
    user: CurrentUserDep,
) -> dict[str, object]:
    """申诉裁决（成立冲正 / 驳回）。

    事务由服务层收敛（成功提交/失败回滚），路由层只做参数校验与响应序列化。
    """
    service = AppealService(session)
    resolved = service.resolve(
        appeal_id, user.subject, user.role or "",
        upheld=body.upheld, note=body.note,
    )
    return _serialize(resolved)


@me_router.get("/records")
def list_my_records(
    session: DbSession,
    user: CurrentUserDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, object]:
    """学生端违规记录（仅本人决策，按时间倒序）。"""
    student_id = _resolve_student_id(session, user)
    repo = DecisionRepository(session)
    safe_page = max(1, page)
    safe_size = min(max(1, page_size), 100)
    rows = repo.list_with_filters(
        student_id=student_id,
        limit=safe_size,
        offset=(safe_page - 1) * safe_size,
    )
    total = repo.count_with_filters(student_id=student_id)

    return {
        "items": [
            DecisionListItem.model_validate(row).model_dump(mode="json")
            for row in rows
        ],
        "total": total,
        "page": safe_page,
        "page_size": safe_size,
    }


@me_router.get("/overview")
def get_my_overview(
    session: DbSession, user: CurrentUserDep
) -> dict[str, object]:
    """学生端首页总览（一屏聚合，只读）。

    聚合积分卡 / 待确认提醒 / 近期记录与申诉计数，供小程序首页渲染。
    """
    service = MeOverviewService(session)
    overview = service.get_overview(user.subject, user.role or "")
    return MeOverviewOut.model_validate(overview).model_dump(mode="json")


@me_router.post("/appeals", status_code=200)
def submit_my_appeal(
    body: AppealSubmitBody, session: DbSession, user: CurrentUserDep
) -> dict[str, object]:
    """学生发起申诉（本人校验由服务层收敛）。

    事务由服务层收敛（成功提交/失败回滚），路由层只做参数校验与响应序列化。
    """
    student_id = _resolve_student_id(session, user)
    service = AppealService(session)
    appeal = service.submit(
        body.decision_id, student_id, body.reason, body.attachments
    )
    return _serialize(appeal)


@me_router.get("/appeals")
def list_my_appeals(
    session: DbSession,
    user: CurrentUserDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, object]:
    """我的申诉列表（仅本人）。"""
    student_id = _resolve_student_id(session, user)
    safe_page = max(1, page)
    safe_size = min(max(1, page_size), 100)
    repo = AppealRepository(session)
    rows = repo.list_by_student(
        student_id, limit=safe_size, offset=(safe_page - 1) * safe_size
    )
    total = repo.count_by_student(student_id)
    return {
        "items": [_serialize(row) for row in rows],
        "total": total,
        "page": safe_page,
        "page_size": safe_size,
    }


__all__ = ["admin_router", "me_router"]

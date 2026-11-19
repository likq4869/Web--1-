"""运维管理 API：模型版本 / 审计日志 / 用户管理。

职责：HTTP 解析与响应序列化、分页参数钳制、白名单回退、服务调用。
依赖：FastAPI、app.core.deps、app.services.ops.admin、app.schemas.ops。
边界：不做业务规则判定；CSV 导出无；只读接口不写库；
越权语义由服务层收敛（非授权角色一律 404）。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.deps import CurrentUserDep, DbSession
from app.schemas.ops import (
    AdminUserResponse,
    AdminUserUpdateBody,
    AuditLogResponse,
    FeedbackStatsResponse,
    ModelVersionResponse,
    PasswordResetBody,
    PasswordResetResponse,
)
from app.services.ops.admin import OpsAdminService

router = APIRouter(prefix="/api/v1/admin/ops", tags=["ops-admin"])

_MODEL_TASKS = ("detect", "plate", "head_cls", "reid")
_USER_ROLES = (
    "student",
    "counselor",
    "security_officer",
    "league_officer",
    "super_admin",
    "auditor",
    "admin",
    "reviewer",
    "observer",
)
_USER_STATUSES = ("active", "disabled")


def _page_params(page: int, page_size: int) -> tuple[int, int]:
    """钳制分页参数。"""
    return max(1, page), min(max(1, page_size), 100)


@router.get("/models")
def list_models(
    session: DbSession,
    user: CurrentUserDep,
    task: str | None = Query(None, max_length=32),
) -> dict[str, object]:
    """模型版本列表（激活优先；非法 task 视为不限）。"""
    service = OpsAdminService(session)
    rows = service.list_models(user.role or "", task=task if task in _MODEL_TASKS else None)
    items = [
        ModelVersionResponse.model_validate(row, from_attributes=True).model_dump(
            mode="json"
        )
        for row in rows
    ]
    return {"items": items, "total": len(items)}


@router.get("/models/feedback-stats")
def feedback_stats(session: DbSession, user: CurrentUserDep) -> dict[str, object]:
    """回流样本统计（只读，供模型管理页展示闭环水位）。"""
    service = OpsAdminService(session)
    payload = service.feedback_stats(user.role or "")
    return FeedbackStatsResponse.model_validate(payload).model_dump(mode="json")


@router.post("/models/{model_id}/activate")
def activate_model(
    model_id: str, session: DbSession, user: CurrentUserDep
) -> dict[str, object]:
    """激活指定模型版本（同任务互斥；二次确认由前端承担）。

    事务由服务层收敛（成功提交/失败回滚），路由层只做参数校验与响应序列化。
    """
    service = OpsAdminService(session)
    row = service.activate_model(user.role or "", user.subject, model_id)
    return ModelVersionResponse.model_validate(row, from_attributes=True).model_dump(
        mode="json"
    )


@router.get("/audit-logs")
def list_audit_logs(
    session: DbSession,
    user: CurrentUserDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    actor: str | None = Query(None, max_length=64),
    action: str | None = Query(None, max_length=64),
    start: str | None = Query(None, max_length=64),
    end: str | None = Query(None, max_length=64),
) -> dict[str, object]:
    """审计日志列表（只读；后端不提供任何修改入口）。

    排序固定创建时间倒序；action 为前缀匹配。
    """
    safe_page, safe_size = _page_params(page, page_size)
    service = OpsAdminService(session)
    items, total = service.list_audit_logs(
        user.role or "",
        actor=actor,
        action=action,
        start=start,
        end=end,
        page=safe_page,
        page_size=safe_size,
    )
    rows = [AuditLogResponse.model_validate(item).model_dump(mode="json") for item in items]
    return {"items": rows, "total": total, "page": safe_page, "page_size": safe_size}


@router.get("/users")
def list_users(
    session: DbSession,
    user: CurrentUserDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=64),
    role: str | None = Query(None, max_length=32),
    status: str | None = Query(None, max_length=32),
) -> dict[str, object]:
    """用户列表（仅超管；绝不返回密码哈希）。"""
    safe_page, safe_size = _page_params(page, page_size)
    service = OpsAdminService(session)
    items, total = service.list_users(
        user.role or "",
        keyword=keyword,
        role_filter=role if role in _USER_ROLES else None,
        status=status if status in _USER_STATUSES else None,
        page=safe_page,
        page_size=safe_size,
    )
    rows = [AdminUserResponse.model_validate(item).model_dump(mode="json") for item in items]
    return {"items": rows, "total": total, "page": safe_page, "page_size": safe_size}


@router.put("/users/{user_id}")
def update_user(
    user_id: str,
    body: AdminUserUpdateBody,
    session: DbSession,
    user: CurrentUserDep,
) -> dict[str, object]:
    """更新用户角色/状态（至少一项；写审计）。

    事务由服务层收敛（成功提交/失败回滚），路由层只做参数校验与响应序列化。
    """
    service = OpsAdminService(session)
    payload = service.update_user(user.role or "", user.subject, user_id, body)
    return AdminUserResponse.model_validate(payload).model_dump(mode="json")


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: str,
    body: PasswordResetBody,
    session: DbSession,
    user: CurrentUserDep,
) -> dict[str, object]:
    """重置用户密码（哈希落库，明文绝不记审计）。

    事务由服务层收敛（成功提交/失败回滚），路由层只做参数校验与响应序列化。
    """
    service = OpsAdminService(session)
    payload = service.reset_password(user.role or "", user.subject, user_id, body.new_password)
    return PasswordResetResponse.model_validate(payload).model_dump(mode="json")


__all__ = ["router"]

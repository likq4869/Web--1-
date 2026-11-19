"""运维管理服务：模型版本 / 审计日志 / 用户管理。

职责：收敛 P3-3b 子批次 ③ 三件套的 RBAC、分页钳制、审计写入、事务收敛。
依赖：sqlalchemy 会话、模型/审计/用户仓储、回流样本仓储、密码哈希。
边界：不做 HTTP 解析与响应序列化；密码明文只经哈希落库，绝不记审计明细。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.core.security import hash_password
from app.models.identity import USER_ROLE_VALUES, USER_STATUS_VALUES
from app.models.model_registry import ModelVersion
from app.repositories.audit import AuditRepository
from app.repositories.decision import FeedbackSampleRepository
from app.repositories.model_registry import ModelVersionRepository
from app.repositories.user import UserRepository
from app.schemas.ops import AdminUserUpdateBody

# 模型读：与总览页一致的宽口径；激活写：仅规则管理员三角色。
MODEL_READ_ROLES: frozenset[str] = frozenset(
    {
        "super_admin",
        "league_officer",
        "counselor",
        "security_officer",
        "auditor",
        "admin",
        "reviewer",
        "observer",
    }
)
MODEL_WRITE_ROLES: frozenset[str] = frozenset({"super_admin", "league_officer", "admin"})
# 审计读：审计链路相关角色；写入口不存在（只读）。
AUDIT_READ_ROLES: frozenset[str] = frozenset({"super_admin", "auditor", "admin"})
# 用户管理：最高敏操作，仅超管可读可写，避免提权。
USER_MANAGE_ROLES: frozenset[str] = frozenset({"super_admin"})

PAGE_SIZE_MAX = 100
MODEL_TASKS = ("detect", "plate", "head_cls", "reid")


def _require(role: str, allowed: frozenset[str]) -> None:
    """越权统一 404（隐藏资源存在性）。"""
    if role not in allowed:
        raise NotFoundError("请求的资源不存在")


def _clamp_page(page: int, page_size: int) -> tuple[int, int]:
    """钳制分页参数。"""
    return max(1, page), min(max(1, page_size), PAGE_SIZE_MAX)


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


def _model_to_dict(row: ModelVersion) -> dict[str, Any]:
    """模型版本 ORM 行投影为字典。"""
    metrics = row.metrics if isinstance(row.metrics, dict) else None
    return {
        "model_id": str(row.model_id),
        "task": str(row.task),
        "version": str(row.version),
        "weight_path": str(row.weight_path),
        "metrics": metrics,
        "dataset_id": str(row.dataset_id) if row.dataset_id else None,
        "is_active": bool(row.is_active),
        "deployed_at": row.deployed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


class OpsAdminService:
    """运维管理服务（绑定单个会话）。"""

    def __init__(self, session: Session) -> None:
        """初始化服务。

        Args:
            session: 数据库会话。
        """
        self.session = session

    # ------------------------------------------------------------------
    # 模型版本
    # ------------------------------------------------------------------

    def list_models(self, role: str, *, task: str | None = None) -> list[ModelVersion]:
        """列出模型版本（激活优先，其次创建时间倒序）。

        Args:
            role: 调用方角色。
            task: 任务类型过滤；非法值视为不限。

        Returns:
            模型版本行列表。
        """
        _require(role, MODEL_READ_ROLES)
        safe_task = task if task in MODEL_TASKS else None
        return ModelVersionRepository(self.session).list_all(task=safe_task)

    def feedback_stats(self, role: str) -> dict[str, Any]:
        """回流样本统计（只读，供模型管理页展示闭环水位）。

        Args:
            role: 调用方角色.

        Returns:
            `{"total", "pending_train", "by_source"}`。
        """
        _require(role, MODEL_READ_ROLES)
        repo = FeedbackSampleRepository(self.session)
        pending = repo.list_pending_train(limit=100000)
        by_source: dict[str, int] = {}
        # 全量来源分布：分来源计数（数据量小，直接三次计数保证口径清晰）。
        from sqlalchemy import func, select

        from app.models.decision import FeedbackSample

        total = int(
            self.session.execute(
                select(func.count()).select_from(FeedbackSample)
            ).scalar_one()
        )
        rows = self.session.execute(
            select(FeedbackSample.source, func.count())
            .group_by(FeedbackSample.source)
            .order_by(FeedbackSample.source.asc())
        ).all()
        for source, count in rows:
            by_source[str(source)] = int(count)
        return {
            "total": total,
            "pending_train": len(pending),
            "by_source": by_source,
        }

    def activate_model(self, role: str, subject: str, model_id: str) -> ModelVersion:
        """激活指定模型版本（同任务互斥，有二次确认由前端承担）。

        Args:
            role: 调用方角色。
            subject: 操作人。
            model_id: 模型 ID。

        Returns:
            激活后的模型行。

        Raises:
            NotFoundError: 模型不存在。
        """
        _require(role, MODEL_WRITE_ROLES)
        repo = ModelVersionRepository(self.session)
        row = repo.get_by_id(model_id)
        if row is None:
            raise NotFoundError("请求的资源不存在")
        try:
            if not row.is_active:
                repo.deactivate_task(str(row.task))
                row.is_active = True
                row.deployed_at = datetime.now(UTC)
                self.session.flush()
            AuditRepository(self.session).log(
                actor=subject,
                role=role,
                action="model.activate",
                object_type="model_version",
                object_id=str(row.model_id),
                result="ok",
                detail=f"model={row.model_id} task={row.task}",
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        refreshed = repo.get_by_id(model_id)
        assert refreshed is not None
        return refreshed

    # ------------------------------------------------------------------
    # 审计日志（只读）
    # ------------------------------------------------------------------

    def list_audit_logs(
        self,
        role: str,
        *,
        actor: str | None = None,
        action: str | None = None,
        start: str | None = None,
        end: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页列出审计日志（创建时间倒序，只读无写入口）。

        Args:
            role: 调用方角色。
            actor: 操作人精确匹配。
            action: 动作前缀匹配。
            start: 创建时间起点（ISO 字符串）。
            end: 创建时间终点（ISO 字符串）。
            page: 页码。
            page_size: 每页条数。

        Returns:
            (审计字典列表, 总数) 二元组。
        """
        _require(role, AUDIT_READ_ROLES)
        safe_page, safe_size = _clamp_page(page, page_size)
        repo = AuditRepository(self.session)
        rows = repo.list_with_filters(
            actor=actor or None,
            action=action or None,
            start=_parse_dt(start),
            end=_parse_dt(end),
            limit=safe_size,
            offset=(safe_page - 1) * safe_size,
        )
        total = repo.count_with_filters(
            actor=actor or None,
            action=action or None,
            start=_parse_dt(start),
            end=_parse_dt(end),
        )
        items = [
            {
                "id": int(row.id),
                "actor": str(row.actor),
                "role": str(row.role),
                "action": str(row.action),
                "object_type": str(row.object_type) if row.object_type else None,
                "object_id": str(row.object_id) if row.object_id else None,
                "ip": str(row.ip) if row.ip else None,
                "result": str(row.result),
                "detail": str(row.detail) if row.detail else None,
                "created_at": row.created_at,
            }
            for row in rows
        ]
        return items, total

    # ------------------------------------------------------------------
    # 用户管理（仅超管）
    # ------------------------------------------------------------------

    def list_users(
        self,
        role: str,
        *,
        keyword: str | None = None,
        role_filter: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页列出账号（user_id 升序，绝不返回密码哈希）。

        Args:
            role: 调用方角色。
            keyword: 模糊匹配用户名/手机号/用户 ID。
            role_filter: 角色精确匹配；非法值视为不限。
            status: 状态精确匹配；非法值视为不限。
            page: 页码。
            page_size: 每页条数。

        Returns:
            (用户字典列表, 总数) 二元组。
        """
        _require(role, USER_MANAGE_ROLES)
        safe_page, safe_size = _clamp_page(page, page_size)
        safe_role = role_filter if role_filter in USER_ROLE_VALUES else None
        safe_status = status if status in USER_STATUS_VALUES else None
        repo = UserRepository(self.session)
        rows = repo.list_with_filters(
            keyword=keyword or None,
            role=safe_role,
            status=safe_status,
            limit=safe_size,
            offset=(safe_page - 1) * safe_size,
        )
        total = repo.count_with_filters(
            keyword=keyword or None,
            role=safe_role,
            status=safe_status,
        )
        items = [
            {
                "user_id": str(row.user_id),
                "username": str(row.username) if row.username else None,
                "role": str(row.role),
                "status": str(row.status),
                "phone": str(row.phone) if row.phone else None,
                "last_login_at": row.last_login_at,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]
        return items, total

    def update_user(
        self,
        role: str,
        subject: str,
        user_id: str,
        body: AdminUserUpdateBody,
    ) -> dict[str, Any]:
        """更新账号角色/状态（至少一项，写审计）。

        Args:
            role: 调用方角色。
            subject: 操作人。
            user_id: 目标用户 ID。
            body: 更新体。

        Returns:
            更新后的用户字典。

        Raises:
            NotFoundError: 用户不存在。
            ValidationError: 空更新 / 禁用自己 / 移除最后一个超管。
        """
        _require(role, USER_MANAGE_ROLES)
        if body.role is None and body.status is None:
            raise ValidationError("请至少指定角色或状态")
        repo = UserRepository(self.session)
        row = repo.get_by_id(user_id)
        if row is None:
            raise NotFoundError("请求的资源不存在")
        if subject == user_id and body.status == "disabled":
            raise ValidationError("不能停用当前登录账号")
        try:
            if body.role is not None:
                if (
                    str(row.role) == "super_admin"
                    and body.role != "super_admin"
                    and self._count_active_super_admins() <= 1
                ):
                    raise ValidationError("至少保留一个启用的超管账号")
                row.role = body.role
            if body.status is not None:
                if (
                    str(row.role) == "super_admin"
                    and body.status == "disabled"
                    and self._count_active_super_admins() <= 1
                ):
                    raise ValidationError("至少保留一个启用的超管账号")
                row.status = body.status
            self.session.flush()
            AuditRepository(self.session).log(
                actor=subject,
                role=role,
                action="user.update",
                object_type="user",
                object_id=str(row.user_id),
                result="ok",
                detail=f"user={row.user_id}",
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return {
            "user_id": str(row.user_id),
            "username": str(row.username) if row.username else None,
            "role": str(row.role),
            "status": str(row.status),
            "phone": str(row.phone) if row.phone else None,
            "last_login_at": row.last_login_at,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def reset_password(
        self, role: str, subject: str, user_id: str, new_password: str
    ) -> dict[str, Any]:
        """重置账号密码（哈希落库，明文绝不记审计）。

        Args:
            role: 调用方角色。
            subject: 操作人。
            user_id: 目标用户 ID。
            new_password: 新密码明文（长度已由 Schema 校验）。

        Returns:
            `{"user_id", "username"}`。

        Raises:
            NotFoundError: 用户不存在。
        """
        _require(role, USER_MANAGE_ROLES)
        repo = UserRepository(self.session)
        row = repo.get_by_id(user_id)
        if row is None:
            raise NotFoundError("请求的资源不存在")
        try:
            row.password_hash = hash_password(new_password)
            self.session.flush()
            AuditRepository(self.session).log(
                actor=subject,
                role=role,
                action="user.reset_password",
                object_type="user",
                object_id=str(row.user_id),
                result="ok",
                detail=f"user={row.user_id}",
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return {
            "user_id": str(row.user_id),
            "username": str(row.username) if row.username else None,
        }

    def _count_active_super_admins(self) -> int:
        """统计启用中的超管数（删除/降级最后一人的护栏）。"""
        return UserRepository(self.session).count_with_filters(
            role="super_admin", status="active"
        )


__all__ = [
    "AUDIT_READ_ROLES",
    "MODEL_READ_ROLES",
    "MODEL_WRITE_ROLES",
    "OpsAdminService",
    "USER_MANAGE_ROLES",
]

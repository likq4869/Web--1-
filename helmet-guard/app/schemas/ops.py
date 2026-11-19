"""运维管理 Pydantic 出入参：模型版本 / 审计日志 / 用户管理。

职责：提供 P3-3b 子批次 ③ 三件套的 API 请求/响应模型。
依赖：pydantic。
边界：只描述数据结构与校验规则；不含业务逻辑，不依赖数据库。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ModelTask = Literal["detect", "plate", "head_cls", "reid"]
AdminRole = Literal[
    "student",
    "counselor",
    "security_officer",
    "league_officer",
    "super_admin",
    "auditor",
    "admin",
    "reviewer",
    "observer",
]
AccountStatus = Literal["active", "disabled"]


class ModelVersionResponse(BaseModel):
    """模型版本响应（含激活态与指标摘要）。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    model_id: str
    task: str
    version: str
    weight_path: str
    metrics: dict[str, Any] | None = None
    dataset_id: str | None = None
    is_active: bool
    deployed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FeedbackStatsResponse(BaseModel):
    """回流样本统计（只读，供模型管理页展示闭环水位）。"""

    model_config = ConfigDict(extra="forbid")

    total: int = 0
    pending_train: int = 0
    by_source: dict[str, int] = Field(default_factory=dict)


class AuditLogResponse(BaseModel):
    """审计日志响应（只读，后端不提供任何修改入口）。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    actor: str
    role: str
    action: str
    object_type: str | None = None
    object_id: str | None = None
    ip: str | None = None
    result: str
    detail: str | None = None
    created_at: datetime | None = None


class AdminUserResponse(BaseModel):
    """管理端用户响应（绝不含 password_hash）。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    user_id: str
    username: str | None = None
    role: str
    status: str
    phone: str | None = None
    last_login_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AdminUserUpdateBody(BaseModel):
    """用户更新请求体（角色分配 / 启停用，至少一项）。"""

    model_config = ConfigDict(extra="forbid")

    role: AdminRole | None = None
    status: AccountStatus | None = None


class PasswordResetBody(BaseModel):
    """密码重置请求体（明文仅经 HTTPS 到后端即哈希，绝不落库）。"""

    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=8, max_length=128, description="新密码")


class PasswordResetResponse(BaseModel):
    """密码重置响应（只回显账号标识，不回显密码）。"""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    username: str | None = None


__all__ = [
    "AccountStatus",
    "AdminRole",
    "AdminUserResponse",
    "AdminUserUpdateBody",
    "AuditLogResponse",
    "FeedbackStatsResponse",
    "ModelTask",
    "ModelVersionResponse",
    "PasswordResetBody",
    "PasswordResetResponse",
]

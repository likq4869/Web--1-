"""模型注册表 ORM 映射：模型版本与部署状态。

职责：把说明书 §7.2（model_versions）映射为 SQLAlchemy 2.0 ORM 模型，
供 Alembic 迁移与仓储层使用。
依赖：sqlalchemy、app.models.base。
边界：只描述表结构与约束；不含业务规则，不执行 I/O。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# 任务类型：与说明书 model_versions.task 一致。
MODEL_TASK_VALUES = ("detect", "plate", "head_cls", "reid")


class ModelVersion(Base):
    """模型版本注册表（一行一版本，仅一行为激活态）。

    对应说明书 `model_versions`：task/version/weight_path/metrics/
    dataset_id/is_active/deployed_at。
    """

    __tablename__ = "model_versions"
    __table_args__ = (
        Index("ix_model_task", "task"),
        Index("ix_model_active", "is_active"),
    )

    model_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(255), nullable=False)
    weight_path: Mapped[str] = mapped_column(String(255), nullable=False)
    metrics: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    dataset_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    deployed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


__all__ = ["MODEL_TASK_VALUES", "ModelVersion"]

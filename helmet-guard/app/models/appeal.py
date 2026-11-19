"""申诉域 ORM 映射：学生申诉记录。

职责：把 P2-3 任务的 appeals 表映射为 SQLAlchemy 2.0 ORM 模型。
依赖：sqlalchemy、app.models.base。
边界：只描述表结构与约束；不含业务规则，不执行 I/O。

状态机：pending（已提交）→ upheld（成立）/ rejected（不成立）；
为兼容说明书 `submitted/processing` 历史值，枚举同时收敛两者，
新写入一律使用 pending/upheld/rejected。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

APPEAL_STATUS_VALUES = ("pending", "submitted", "processing", "upheld", "rejected")


class Appeal(Base):
    """申诉记录表（一事一申诉，decision_id 唯一约束保证幂等复用）。"""

    __tablename__ = "appeals"
    __table_args__ = (
        Index("ix_appeals_student", "student_id"),
        Index("ix_appeals_status", "status"),
        Index("ix_appeals_decision", "decision_id"),
    )

    appeal_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(255), nullable=False)
    student_id: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    attachments: Mapped[object | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(*APPEAL_STATUS_VALUES, name="appeal_status", native_enum=True,
             validate_strings=True),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    handler: Mapped[str | None] = mapped_column(String(255), nullable=True)
    handle_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )


__all__ = ["APPEAL_STATUS_VALUES", "Appeal"]

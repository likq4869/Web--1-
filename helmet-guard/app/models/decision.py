"""决策域 ORM 映射：决策、审批日志、误判回流样本。

职责：把 P2-3 任务的 decisions / review_logs / feedback_samples 映射为
SQLAlchemy 2.0 ORM 模型，供 Alembic 迁移与仓储层使用。
依赖：sqlalchemy、app.models.base。
边界：只描述表结构与约束；不含业务规则，不执行 I/O。

与说明书 §7.2 的差异（工程化增强，迁移中同步落地）：
1. 时间列统一为 `DateTime(timezone=True)` + `server_default=func.now()`；
2. 枚举列统一用 `Enum(..., native_enum=True)`：PG 落为原生 ENUM，
   SQLite 自动退化为 VARCHAR + CHECK；
3. factors / evidence_refs 用 `JSON`（PG 为 JSON，SQLite 存为 TEXT）；
4. feedback_samples 在说明书字段基础上补齐 P2-3 任务字段
   （decision_id / appeal_id / original_label / corrected_label / reason），
   与说明书 `label/model_pred/snapshot_id/used_for_train` 并存，保证回流闭环可查。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# 决策档位：与 app.domain.decision.DecisionLevel 一一对应。
DECISION_LEVEL_VALUES = ("L0", "L1", "L2", "L3", "L4")
# 决策动作：与 app.domain.decision.DecisionAction 一一对应。
DECISION_ACTION_VALUES = ("none", "remind", "deduct_score", "notify", "report", "award")
# 审批状态机：任务 5.3 约定 9 态；统一大写，下划线分隔。
DECISION_STATUS_VALUES = (
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
# 审批动作：approve/reject/adjust/auto/batch/expire/escalate/appeal。
REVIEW_ACTION_VALUES = (
    "approve",
    "reject",
    "adjust",
    "auto",
    "batch",
    "expire",
    "escalate",
    "appeal",
    "simulate",
)
# 回流来源：驳回 / 申诉成立 / 人工标注。
FEEDBACK_SOURCE_VALUES = ("review_reject", "appeal_upheld", "manual")


class Decision(Base):
    """AI 决策记录表（审批状态机载体）。

    对应说明书 `decisions`：一条事件最多一条有效决策（event_id 唯一索引
    保证幂等，重复编排直接返回既有行）。
    """

    __tablename__ = "decisions"
    __table_args__ = (
        Index("ix_decisions_status", "status"),
        Index("ix_decisions_student", "student_id"),
        Index("ix_decisions_due", "due_at"),
        Index("ix_decisions_event", "event_id", unique=True),
        Index("ix_decisions_created", "created_at"),
    )

    decision_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    student_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    level: Mapped[str] = mapped_column(
        Enum(*DECISION_LEVEL_VALUES, name="decision_level", native_enum=True,
             validate_strings=True),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(
        Enum(*DECISION_ACTION_VALUES, name="decision_action", native_enum=True,
             validate_strings=True),
        nullable=False,
    )
    score_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reason_code: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    factors: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    evidence_refs: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(*DECISION_STATUS_VALUES, name="decision_status", native_enum=True,
             validate_strings=True),
        nullable=False,
        default="PENDING_REVIEW",
        server_default="PENDING_REVIEW",
    )
    auto_approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_level: Mapped[str | None] = mapped_column(String(255), nullable=True)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )


class ReviewLog(Base):
    """审批审计轨迹表（只增不改）。

    对应说明书 `review_logs`：每次状态流转 exactly-one 行，含 from/to 便于回放。
    """

    __tablename__ = "review_logs"
    __table_args__ = (Index("ix_review_decision", "decision_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(
        Enum(*REVIEW_ACTION_VALUES, name="review_action", native_enum=True,
             validate_strings=True),
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    from_level: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_level: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operator: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FeedbackSample(Base):
    """误判回流训练集（模型迭代闭环）。

    说明书字段（event_id/snapshot_id/label/model_pred/used_for_train）与
    P2-3 任务字段（decision_id/appeal_id/source/image_path/
    original_label/corrected_label/reason）并存，写入方按来源填充。
    """

    __tablename__ = "feedback_samples"
    __table_args__ = (Index("ix_feedback_train", "used_for_train"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    appeal_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_pred: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    corrected_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(
        Enum(*FEEDBACK_SOURCE_VALUES, name="feedback_source", native_enum=True,
             validate_strings=True),
        nullable=False,
    )
    used_for_train: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "DECISION_ACTION_VALUES",
    "DECISION_LEVEL_VALUES",
    "DECISION_STATUS_VALUES",
    "FEEDBACK_SOURCE_VALUES",
    "REVIEW_ACTION_VALUES",
    "Decision",
    "FeedbackSample",
    "ReviewLog",
]

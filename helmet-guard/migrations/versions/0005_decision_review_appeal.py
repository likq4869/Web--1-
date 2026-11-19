"""决策审批与申诉迁移：decisions / review_logs / appeals / feedback_samples。

Revision ID: 0005_decision_review_appeal
Revises: 0004_scoring_domain
Create Date: 2026-11-16

来源：说明书 §7.2（decisions/review_logs/appeals/feedback_samples）与 P2-3 任务。
工程化增强：时间列统一 DateTime(timezone=True)+server_default=func.now()；
枚举列用原生 Enum（PG 落为 ENUM，SQLite 退化为 VARCHAR+CHECK）；
JSON 列用 JSON 类型；decisions.event_id 唯一索引保证一事件一决策幂等。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_decision_review_appeal"
down_revision: str | None = "0004_scoring_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DECISION_LEVEL = sa.Enum(
    "L0", "L1", "L2", "L3", "L4",
    name="decision_level", native_enum=True, validate_strings=True,
)
DECISION_ACTION = sa.Enum(
    "none", "remind", "deduct_score", "notify", "report", "award",
    name="decision_action", native_enum=True, validate_strings=True,
)
DECISION_STATUS = sa.Enum(
    "PENDING_REVIEW", "APPROVED", "REJECTED", "ADJUSTED", "AUTO_APPROVED",
    "APPEALING", "APPEAL_UPHELD", "APPEAL_REJECTED", "EXPIRED",
    name="decision_status", native_enum=True, validate_strings=True,
)
REVIEW_ACTION = sa.Enum(
    "approve", "reject", "adjust", "auto", "batch", "expire", "escalate",
    "appeal", "simulate",
    name="review_action", native_enum=True, validate_strings=True,
)
APPEAL_STATUS = sa.Enum(
    "pending", "submitted", "processing", "upheld", "rejected",
    name="appeal_status", native_enum=True, validate_strings=True,
)
FEEDBACK_SOURCE = sa.Enum(
    "review_reject", "appeal_upheld", "manual",
    name="feedback_source", native_enum=True, validate_strings=True,
)


def upgrade() -> None:
    """创建决策域 4 张表及高频索引。"""
    op.create_table(
        "decisions",
        sa.Column("decision_id", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("student_id", sa.String(), nullable=True),
        sa.Column("level", DECISION_LEVEL, nullable=False),
        sa.Column("action", DECISION_ACTION, nullable=False),
        sa.Column("score_delta", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reason_code", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("factors", sa.JSON(), nullable=True),
        sa.Column("evidence_refs", sa.JSON(), nullable=True),
        sa.Column("policy_version", sa.String(), nullable=True),
        sa.Column("status", DECISION_STATUS, server_default="PENDING_REVIEW",
                  nullable=False),
        sa.Column("auto_approved", sa.Boolean(), server_default=sa.false(),
                  nullable=False),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(), nullable=True),
        sa.Column("original_level", sa.String(), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("decision_id", name="pk_decisions"),
    )
    op.create_index("ix_decisions_status", "decisions", ["status"], unique=False)
    op.create_index("ix_decisions_student", "decisions", ["student_id"], unique=False)
    op.create_index("ix_decisions_due", "decisions", ["due_at"], unique=False)
    op.create_index("ix_decisions_event", "decisions", ["event_id"], unique=True)
    op.create_index("ix_decisions_created", "decisions", ["created_at"], unique=False)

    op.create_table(
        "review_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("decision_id", sa.String(), nullable=False),
        sa.Column("action", REVIEW_ACTION, nullable=False),
        sa.Column("from_status", sa.String(), nullable=True),
        sa.Column("to_status", sa.String(), nullable=True),
        sa.Column("from_level", sa.String(), nullable=True),
        sa.Column("to_level", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("operator", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_review_logs"),
    )
    op.create_index("ix_review_decision", "review_logs", ["decision_id"], unique=False)

    op.create_table(
        "appeals",
        sa.Column("appeal_id", sa.String(), nullable=False),
        sa.Column("decision_id", sa.String(), nullable=False),
        sa.Column("student_id", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=True),
        sa.Column("status", APPEAL_STATUS, server_default="pending", nullable=False),
        sa.Column("handler", sa.String(), nullable=True),
        sa.Column("handle_note", sa.String(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("appeal_id", name="pk_appeals"),
    )
    op.create_index("ix_appeals_student", "appeals", ["student_id"], unique=False)
    op.create_index("ix_appeals_status", "appeals", ["status"], unique=False)
    op.create_index("ix_appeals_decision", "appeals", ["decision_id"], unique=False)

    op.create_table(
        "feedback_samples",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("decision_id", sa.String(), nullable=True),
        sa.Column("appeal_id", sa.String(), nullable=True),
        sa.Column("snapshot_id", sa.String(), nullable=True),
        sa.Column("image_path", sa.String(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("model_pred", sa.String(), nullable=True),
        sa.Column("original_label", sa.String(), nullable=True),
        sa.Column("corrected_label", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("source", FEEDBACK_SOURCE, nullable=False),
        sa.Column("used_for_train", sa.Boolean(), server_default=sa.false(),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_feedback_samples"),
    )
    op.create_index("ix_feedback_train", "feedback_samples", ["used_for_train"],
                    unique=False)


def downgrade() -> None:
    """逆序删除决策域 4 张表（枚举类型同步清理）。"""
    op.drop_index("ix_feedback_train", table_name="feedback_samples")
    op.drop_table("feedback_samples")
    op.drop_index("ix_appeals_decision", table_name="appeals")
    op.drop_index("ix_appeals_status", table_name="appeals")
    op.drop_index("ix_appeals_student", table_name="appeals")
    op.drop_table("appeals")
    op.drop_index("ix_review_decision", table_name="review_logs")
    op.drop_table("review_logs")
    op.drop_index("ix_decisions_created", table_name="decisions")
    op.drop_index("ix_decisions_event", table_name="decisions")
    op.drop_index("ix_decisions_due", table_name="decisions")
    op.drop_index("ix_decisions_student", table_name="decisions")
    op.drop_index("ix_decisions_status", table_name="decisions")
    op.drop_table("decisions")
    for enum_type in (
        FEEDBACK_SOURCE,
        APPEAL_STATUS,
        REVIEW_ACTION,
        DECISION_STATUS,
        DECISION_ACTION,
        DECISION_LEVEL,
    ):
        enum_type.drop(op.get_bind(), checkfirst=True)

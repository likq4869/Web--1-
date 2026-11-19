"""积分域迁移：积分账户、积分台账（只增不改）、积分规则。

Revision ID: 0004_scoring_domain
Revises: 0003_identity_admin
Create Date: 2026-11-16

来源：说明书 §7.2（score_accounts/score_ledger/score_rules）与 P2-1 任务。
工程化增强：时间列统一 DateTime(timezone=True)+server_default=func.now()；
枚举列用原生 Enum（PG 落为 ENUM，SQLite 退化为 VARCHAR+CHECK）；
台账表不提供更新/删除路径（应用层约束，此处仅建表）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_scoring_domain"
down_revision: str | None = "0003_identity_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCORE_LEVEL = sa.Enum(
    "S",
    "A",
    "B",
    "C",
    "D",
    name="score_level",
    native_enum=True,
    validate_strings=True,
)
SCORE_RULE_TYPE = sa.Enum(
    "deduct",
    "award",
    "streak",
    name="score_rule_type",
    native_enum=True,
    validate_strings=True,
)


def upgrade() -> None:
    """创建积分域 3 张表及高频索引。"""
    op.create_table(
        "score_accounts",
        sa.Column("student_id", sa.String(), nullable=False),
        sa.Column("balance", sa.Integer(), server_default="100", nullable=False),
        sa.Column("total_deducted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_awarded", sa.Integer(), server_default="0", nullable=False),
        sa.Column("level", SCORE_LEVEL, server_default="B", nullable=False),
        sa.Column("streak_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "compliance_rate", sa.Float(), server_default="1.0", nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("student_id", name="pk_score_accounts"),
    )

    op.create_table(
        "score_ledger",
        sa.Column("ledger_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("student_id", sa.String(), nullable=False),
        sa.Column("change", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(), nullable=False),
        sa.Column("reason_text", sa.String(), nullable=True),
        sa.Column("event_id", sa.String(), nullable=True),
        sa.Column("decision_id", sa.String(), nullable=True),
        sa.Column("operator", sa.String(), nullable=True),
        sa.Column(
            "effective_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.student_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("ledger_id", name="pk_score_ledger"),
    )
    op.create_index("ix_ledger_student", "score_ledger", ["student_id"], unique=False)
    op.create_index("ix_ledger_time", "score_ledger", ["effective_at"], unique=False)
    op.create_index("ix_ledger_event", "score_ledger", ["event_id"], unique=False)

    op.create_table(
        "score_rules",
        sa.Column("rule_id", sa.String(), nullable=False),
        sa.Column("rule_type", SCORE_RULE_TYPE, server_default="deduct", nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("condition_json", sa.JSON(), nullable=False),
        sa.Column("score_change", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("rule_id", name="pk_score_rules"),
    )
    op.create_index("ix_rule_enabled", "score_rules", ["enabled"], unique=False)


def downgrade() -> None:
    """逆序删除积分域 3 张表（枚举类型同步清理）。"""
    op.drop_index("ix_rule_enabled", table_name="score_rules")
    op.drop_table("score_rules")
    op.drop_index("ix_ledger_event", table_name="score_ledger")
    op.drop_index("ix_ledger_time", table_name="score_ledger")
    op.drop_index("ix_ledger_student", table_name="score_ledger")
    op.drop_table("score_ledger")
    op.drop_table("score_accounts")
    for enum_type in (SCORE_RULE_TYPE, SCORE_LEVEL):
        enum_type.drop(op.get_bind(), checkfirst=True)

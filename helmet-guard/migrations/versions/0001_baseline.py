"""基线迁移：现有 6 张表的建表语句。

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-15

本迁移把 `app/db.py` 中已有的 6 张表固化为迁移体系的第一条基线，
供新环境建库使用。字段、可空性、默认值、CHECK 与 UNIQUE 约束与原生建表语句一致。

之后每条迁移只做增量变更，不修改本基线。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建现有 6 张表。"""
    op.create_table(
        "sources",
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="online", nullable=False),
        sa.Column("last_seen", sa.String(), nullable=True),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("source_id", name="pk_sources"),
    )
    op.create_table(
        "passes",
        sa.Column("pass_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.String(), nullable=False),
        sa.Column("rider_status", sa.String(), nullable=False),
        sa.Column("model_raw", sa.String(), server_default="", nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("pass_id", name="pk_passes"),
        sa.UniqueConstraint(
            "source_id",
            "run_id",
            "pass_id",
            name="uq_passes_source_run_pass",
        ),
        sa.CheckConstraint(
            "rider_status IN ('helmeted','bare','unknown')",
            name="ck_passes_rider_status",
        ),
    )
    op.create_table(
        "events",
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("pass_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("model_label", sa.String(), server_default="", nullable=False),
        sa.Column("reason", sa.String(), server_default="", nullable=False),
        sa.Column("reviewer", sa.String(), server_default="", nullable=False),
        sa.Column("reviewed_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("event_id", name="pk_events"),
        sa.UniqueConstraint("pass_id", name="uq_events_pass_id"),
        sa.CheckConstraint(
            "status IN ('pending','confirmed','dismissed')",
            name="ck_events_status",
        ),
    )
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), server_default="", nullable=False),
        sa.Column("operator", sa.String(), server_default="", nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_reviews"),
        sa.CheckConstraint(
            "decision IN ('confirmed','dismissed')",
            name="ck_reviews_decision",
        ),
    )
    op.create_index("idx_reviews_event", "reviews", ["event_id"], unique=False)
    op.create_table(
        "heartbeats",
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), server_default="", nullable=False),
        sa.Column("mode", sa.String(), server_default="", nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("source_id", name="pk_heartbeats"),
    )
    op.create_table(
        "alerts",
        sa.Column("alert_id", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="queued", nullable=False),
        sa.Column("note", sa.String(), server_default="", nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("alert_id", name="pk_alerts"),
        sa.UniqueConstraint("event_id", name="uq_alerts_event_id"),
        sa.CheckConstraint(
            "status IN ('queued','played','expired','silent')",
            name="ck_alerts_status",
        ),
    )


def downgrade() -> None:
    """按依赖逆序删除 6 张表。"""
    op.drop_table("alerts")
    op.drop_table("heartbeats")
    op.drop_index("idx_reviews_event", table_name="reviews")
    op.drop_table("reviews")
    op.drop_table("events")
    op.drop_table("passes")
    op.drop_table("sources")

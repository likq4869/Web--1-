"""点位标定表：camera_points（ROI/计数线/提醒区覆盖）。

Revision ID: 0009_camera_points
Revises: 0008_model_registry
Create Date: 2026-11-17

来源：逐项实现计划 §5.2 PointConfig（ROI 拖拽标定 + 归一化存储）。
工程约束：仅新增一张表，不动既有表；无行时服务层回退内存默认，
保证老库开箱可用。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_camera_points"
down_revision: str | None = "0008_model_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 camera_points 表。"""
    op.create_table(
        "camera_points",
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("roi_x1", sa.Float(), nullable=False, server_default="0.05"),
        sa.Column("roi_y1", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("roi_x2", sa.Float(), nullable=False, server_default="0.95"),
        sa.Column("roi_y2", sa.Float(), nullable=False, server_default="0.95"),
        sa.Column("count_line_y", sa.Float(), nullable=False, server_default="0.6"),
        sa.Column("zone_x1", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("zone_y1", sa.Float(), nullable=False, server_default="0.3"),
        sa.Column("zone_x2", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("zone_y2", sa.Float(), nullable=False, server_default="0.9"),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("source_id", name="pk_camera_points"),
    )


def downgrade() -> None:
    """移除点位标定表。"""
    op.drop_table("camera_points")

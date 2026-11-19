"""模型注册表迁移：model_versions 表。

Revision ID: 0008_model_registry
Revises: 0007_auth
Create Date: 2026-11-17

来源：说明书 §7.2（model_versions）与逐项实现计划 §4.3 子批次 ③。
工程约束：仅新增一张表，不动既有表；预置一条基线版本行，
保证模型管理页开箱有数据（权重路径与 .env.example 一致）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_model_registry"
down_revision: str | None = "0007_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 model_versions 表及索引，并预置基线版本行。"""
    op.create_table(
        "model_versions",
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("task", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("weight_path", sa.String(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("dataset_id", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("model_id", name="pk_model_versions"),
    )
    op.create_index("ix_model_task", "model_versions", ["task"], unique=False)
    op.create_index("ix_model_active", "model_versions", ["is_active"], unique=False)

    # 预置基线行：与 .env.example 默认权重一致，开箱即有一条激活版本。
    op.execute(
        sa.text(
            "INSERT INTO model_versions "
            "(model_id, task, version, weight_path, metrics, dataset_id, "
            "is_active, deployed_at, created_at, updated_at) "
            "VALUES "
            "('helmet-v2-baseline', 'detect', 'v2-baseline', "
            "'runs/detect/helmet-v2-baseline/weights/best.pt', "
            "'{\"precision\": 0.696, \"recall\": 0.425, "
            "\"note\": \"基线权重，recall偏低需持续回流\"}', "
            "'ebike_helmet_v2+roboflow_motorcycle', 1, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )


def downgrade() -> None:
    """逆序删除模型注册表。"""
    op.drop_index("ix_model_active", table_name="model_versions")
    op.drop_index("ix_model_task", table_name="model_versions")
    op.drop_table("model_versions")

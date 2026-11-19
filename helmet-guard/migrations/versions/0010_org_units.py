"""组织单元与学籍扩展：org_units 表 + students 补 school/major。

Revision ID: 0010_org_units
Revises: 0009_camera_points
Create Date: 2026-11-18

来源：小程序微信登录四步（微信直登→手机号→学籍级联→知情同意）。
工程约束：只新增一张表 + students 加两列（可空，向后兼容），
不动既有数据；SQLite 用 batch_alter 加列保证可逆。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_org_units"
down_revision: str | None = "0009_camera_points"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORG_UNIT_TYPE = sa.Enum(
    "school",
    "college",
    "grade",
    "major",
    "class",
    name="org_unit_type",
    native_enum=True,
    validate_strings=True,
)


def upgrade() -> None:
    """创建 org_units 表，students 补 school/major 列。"""
    op.create_table(
        "org_units",
        sa.Column("unit_id", sa.String(), nullable=False),
        sa.Column("unit_type", ORG_UNIT_TYPE, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
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
        sa.ForeignKeyConstraint(["parent_id"], ["org_units.unit_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("unit_id", name="pk_org_units"),
    )
    op.create_index("ix_org_parent", "org_units", ["parent_id"], unique=False)
    op.create_index("ix_org_type", "org_units", ["unit_type"], unique=False)

    with op.batch_alter_table("students") as batch:
        batch.add_column(sa.Column("school", sa.String(), nullable=True))
        batch.add_column(sa.Column("major", sa.String(), nullable=True))


def downgrade() -> None:
    """逆序移除学籍扩展。"""
    with op.batch_alter_table("students") as batch:
        batch.drop_column("major")
        batch.drop_column("school")
    op.drop_index("ix_org_type", table_name="org_units")
    op.drop_index("ix_org_parent", table_name="org_units")
    op.drop_table("org_units")
    ORG_UNIT_TYPE.drop(op.get_bind(), checkfirst=True)

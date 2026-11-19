"""身份管理支撑迁移：审计日志与辅导员班级映射。

Revision ID: 0003_identity_admin
Revises: 0002_identity_domain
Create Date: 2026-11-16

来源：P1-6 任务要求——所有写操作写 audit_logs；counselor 角色只能看所带班级。
工程约束：audit_logs 只增不改（不提供更新/删除接口）；辅导员映射用复合主键，
支持一人多班；索引覆盖高频查询。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_identity_admin"
down_revision: str | None = "0002_identity_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 audit_logs 与 counselor_assignments 表及索引。"""
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=True),
        sa.Column("object_id", sa.String(), nullable=True),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column("result", sa.String(), nullable=False, server_default="ok"),
        sa.Column("detail", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index("ix_audit_actor", "audit_logs", ["actor"], unique=False)
    op.create_index("ix_audit_created", "audit_logs", ["created_at"], unique=False)

    op.create_table(
        "counselor_assignments",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("class_name", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "class_name", name="pk_counselor_assignments"),
    )
    op.create_index(
        "ix_counselor_user", "counselor_assignments", ["user_id"], unique=False
    )


def downgrade() -> None:
    """逆序删除 P1-6 新增表。"""
    op.drop_index("ix_counselor_user", table_name="counselor_assignments")
    op.drop_table("counselor_assignments")
    op.drop_index("ix_audit_created", table_name="audit_logs")
    op.drop_index("ix_audit_actor", table_name="audit_logs")
    op.drop_table("audit_logs")

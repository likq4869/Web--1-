"""身份域迁移：新增用户/学生/车辆/身份判定 6 张表。

Revision ID: 0002_identity_domain
Revises: 0001_baseline
Create Date: 2026-11-16

来源：说明书 §7.2（users/students）与 §4.7（vehicles/identity_resolutions/
pending_identities/vehicle_cooccurrence）。工程化增强：时间列统一
DateTime(timezone=True)+server_default=func.now()；枚举列用原生 Enum
（PG 落为 ENUM，SQLite 退化为 VARCHAR+CHECK）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_identity_domain"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_ROLE = sa.Enum(
    "student",
    "counselor",
    "security_officer",
    "league_officer",
    "super_admin",
    "auditor",
    name="user_role",
    native_enum=True,
    validate_strings=True,
)
USER_STATUS = sa.Enum(
    "active", "disabled", name="user_status", native_enum=True, validate_strings=True
)
STUDENT_STATUS = sa.Enum(
    "active",
    "graduated",
    "suspended",
    name="student_status",
    native_enum=True,
    validate_strings=True,
)
PLATE_TYPE = sa.Enum(
    "blue",
    "school",
    "university",
    "none",
    name="plate_type",
    native_enum=True,
    validate_strings=True,
)
OWNER_BIND_TYPE = sa.Enum(
    "registered",
    "qr",
    "nfc",
    "appearance",
    "cooccur",
    "manual",
    name="owner_bind_type",
    native_enum=True,
    validate_strings=True,
)
VEHICLE_STATUS = sa.Enum(
    "active", "unbound", "blocked", name="vehicle_status", native_enum=True, validate_strings=True
)
IDENTITY_METHOD = sa.Enum(
    "plate",
    "qr",
    "nfc",
    "appearance",
    "cooccur",
    "manual",
    "none",
    name="identity_method",
    native_enum=True,
    validate_strings=True,
)
PENDING_STATUS = sa.Enum(
    "pending", "resolved", "ignored", name="pending_status", native_enum=True, validate_strings=True
)


def upgrade() -> None:
    """创建身份域 6 张表及高频索引。"""
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("openid", sa.String(), nullable=True),
        sa.Column("unionid", sa.String(), nullable=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("role", USER_ROLE, server_default="student", nullable=False),
        sa.Column("status", USER_STATUS, server_default="active", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_users"),
        sa.UniqueConstraint("openid", name="uq_users_openid"),
    )
    op.create_index("ix_users_phone", "users", ["phone"], unique=False)
    op.create_index("ix_users_role", "users", ["role"], unique=False)

    op.create_table(
        "students",
        sa.Column("student_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("gender", sa.String(), nullable=True),
        sa.Column("college", sa.String(), nullable=True),
        sa.Column("class_name", sa.String(), nullable=True),
        sa.Column("grade", sa.String(), nullable=True),
        sa.Column("dorm_id", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("avatar", sa.String(), nullable=True),
        sa.Column("status", STUDENT_STATUS, server_default="active", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("student_id", name="pk_students"),
        sa.UniqueConstraint("user_id", name="uq_students_user_id"),
    )
    op.create_index("ix_students_class", "students", ["class_name"], unique=False)

    op.create_table(
        "vehicles",
        sa.Column("vehicle_id", sa.String(), nullable=False),
        sa.Column("plate_no", sa.String(), nullable=True),
        sa.Column("plate_type", PLATE_TYPE, nullable=True),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("owner_bind_type", OWNER_BIND_TYPE, nullable=True),
        sa.Column("confidence", sa.Float(), server_default="0", nullable=False),
        sa.Column("color_hist", sa.JSON(), nullable=True),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", VEHICLE_STATUS, server_default="active", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["students.student_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("vehicle_id", name="pk_vehicles"),
        sa.UniqueConstraint("plate_no", name="uq_vehicles_plate_no"),
    )
    op.create_index("ix_vehicles_owner", "vehicles", ["owner_id"], unique=False)
    op.create_index("ix_vehicles_plate", "vehicles", ["plate_no"], unique=False)

    op.create_table(
        "identity_resolutions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("vehicle_id", sa.String(), nullable=True),
        sa.Column("subject_id", sa.String(), nullable=True),
        sa.Column("method", IDENTITY_METHOD, nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("plate_conf", sa.Float(), server_default="0", nullable=False),
        sa.Column("appearance_conf", sa.Float(), server_default="0", nullable=False),
        sa.Column("cooccur_conf", sa.Float(), server_default="0", nullable=False),
        sa.Column("matched_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("snapshot_id", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_identity_resolutions"),
    )
    op.create_index("ix_identity_event", "identity_resolutions", ["event_id"], unique=False)
    op.create_index("ix_identity_subject", "identity_resolutions", ["subject_id"], unique=False)
    op.create_index("ix_identity_vehicle", "identity_resolutions", ["vehicle_id"], unique=False)

    op.create_table(
        "pending_identities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("vehicle_id", sa.String(), nullable=False),
        sa.Column("pass_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("snapshot_id", sa.String(), nullable=True),
        sa.Column("status", PENDING_STATUS, server_default="pending", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pending_identities"),
    )
    op.create_index("ix_pending_status", "pending_identities", ["status"], unique=False)

    op.create_table(
        "vehicle_cooccurrence",
        sa.Column("vehicle_a", sa.String(), nullable=False),
        sa.Column("vehicle_b", sa.String(), nullable=False),
        sa.Column("window_count", sa.Integer(), nullable=False),
        sa.Column("jaccard", sa.Float(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("vehicle_a", "vehicle_b", name="pk_vehicle_cooccurrence"),
    )


def downgrade() -> None:
    """逆序删除身份域 6 张表（枚举类型同步清理，PG 可重复升降级）。"""
    op.drop_table("vehicle_cooccurrence")
    op.drop_index("ix_pending_status", table_name="pending_identities")
    op.drop_table("pending_identities")
    op.drop_index("ix_identity_vehicle", table_name="identity_resolutions")
    op.drop_index("ix_identity_subject", table_name="identity_resolutions")
    op.drop_index("ix_identity_event", table_name="identity_resolutions")
    op.drop_table("identity_resolutions")
    op.drop_index("ix_vehicles_plate", table_name="vehicles")
    op.drop_index("ix_vehicles_owner", table_name="vehicles")
    op.drop_table("vehicles")
    op.drop_index("ix_students_class", table_name="students")
    op.drop_table("students")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_phone", table_name="users")
    op.drop_table("users")
    for enum_type in (
        PENDING_STATUS,
        IDENTITY_METHOD,
        VEHICLE_STATUS,
        OWNER_BIND_TYPE,
        PLATE_TYPE,
        STUDENT_STATUS,
        USER_STATUS,
        USER_ROLE,
    ):
        enum_type.drop(op.get_bind(), checkfirst=True)

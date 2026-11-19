"""身份域 ORM 映射：用户、学生、车辆、身份判定、待绑定池、共现矩阵。

职责：把说明书 §7.2（用户与组织）与 §4.7（身份部分）的 6 张表映射为
SQLAlchemy 2.0 ORM 模型，供 Alembic 迁移与仓储层使用。
依赖：sqlalchemy、app.models.base。
边界：只描述表结构与约束；不含业务规则，不执行 I/O。

与说明书 SQL 的差异（工程化增强，迁移中同步落地）：
1. 时间列统一为 `DateTime(timezone=True)` + `server_default=func.now()`，
   而非说明书的 TEXT——PG 可用时钟函数，SQLite 存为 CURRENT_TIMESTAMP；
2. 枚举列统一用 `Enum(..., native_enum=True)`：PG 落为原生 ENUM，
   SQLite 自动退化为 VARCHAR + CHECK（与任务要求的双库策略一致）；
3. `users.openid` 保持 UNIQUE（微信登录幂等），`students.user_id` 保持 UNIQUE；
4. `vehicles.embedding` 用 `LargeBinary`（128 维外观特征的序列化字节），
   `color_hist` 用 `JSON`（PG 为 JSON，SQLite 存为 TEXT）；
5. 索引在说明书基础上补齐任务要求的 6 个高频索引。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# 说明书枚举取值：与 §7.2 / §4.7 建表注释一一对应。
# admin / reviewer / observer 为管理后台所需角色，由迁移 0007 补入，
# 使后端枚举与前端 `UserRole`（9 值）完全对齐。
USER_ROLE_VALUES = (
    "student",
    "counselor",
    "security_officer",
    "league_officer",
    "super_admin",
    "auditor",
    "admin",
    "reviewer",
    "observer",
)
USER_STATUS_VALUES = ("active", "disabled")
STUDENT_STATUS_VALUES = ("active", "graduated", "suspended")
ORG_UNIT_TYPE_VALUES = ("school", "college", "grade", "major", "class")
PLATE_TYPE_VALUES = ("blue", "school", "university", "none")
OWNER_BIND_TYPE_VALUES = ("registered", "qr", "nfc", "appearance", "cooccur", "manual")
VEHICLE_STATUS_VALUES = ("active", "unbound", "blocked")
IDENTITY_METHOD_VALUES = ("plate", "qr", "nfc", "appearance", "cooccur", "manual", "none")
PENDING_STATUS_VALUES = ("pending", "resolved", "ignored")


class User(Base):
    """登录账号表。

    对应说明书 `users`：微信 openid 唯一，role 走 RBAC 矩阵（§5.3）。
    """

    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_phone", "phone"),
        Index("ix_users_role", "role"),
    )

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    openid: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    unionid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    wechat_session_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(
        Enum(*USER_ROLE_VALUES, name="user_role", native_enum=True, validate_strings=True),
        nullable=False,
        default="student",
        server_default="student",
    )
    status: Mapped[str] = mapped_column(
        Enum(*USER_STATUS_VALUES, name="user_status", native_enum=True, validate_strings=True),
        nullable=False,
        default="active",
        server_default="active",
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Student(Base):
    """学生档案表。

    对应说明书 `students`：主键为学号，`user_id` 唯一关联登录账号。
    """

    __tablename__ = "students"
    __table_args__ = (Index("ix_students_class", "class_name"),)

    student_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        String(255), ForeignKey("users.user_id", ondelete="SET NULL"), unique=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    gender: Mapped[str | None] = mapped_column(String(255), nullable=True)
    school: Mapped[str | None] = mapped_column(String(255), nullable=True)
    college: Mapped[str | None] = mapped_column(String(255), nullable=True)
    major: Mapped[str | None] = mapped_column(String(255), nullable=True)
    class_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dorm_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(
            *STUDENT_STATUS_VALUES,
            name="student_status",
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        default="active",
        server_default="active",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Vehicle(Base):
    """车辆档案表。

    对应说明书 §4.7 `vehicles`：`owner_id` 为空即待绑定车辆。
    `embedding` 存 128 维外观特征的 float32 字节（`numpy.tobytes()`），
    查询时由仓储层在 Python 层做余弦相似度（SQLite 无向量索引，
    生产切换 pgvector 时替换 `find_similar_by_embedding` 实现即可）。
    """

    __tablename__ = "vehicles"
    __table_args__ = (
        Index("ix_vehicles_owner", "owner_id"),
        Index("ix_vehicles_plate", "plate_no"),
    )

    vehicle_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    plate_no: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    plate_type: Mapped[str | None] = mapped_column(
        Enum(*PLATE_TYPE_VALUES, name="plate_type", native_enum=True, validate_strings=True),
        nullable=True,
    )
    owner_id: Mapped[str | None] = mapped_column(
        String(255), ForeignKey("students.student_id", ondelete="SET NULL"), nullable=True
    )
    owner_bind_type: Mapped[str | None] = mapped_column(
        Enum(
            *OWNER_BIND_TYPE_VALUES,
            name="owner_bind_type",
            native_enum=True,
            validate_strings=True,
        ),
        nullable=True,
    )
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    color_hist: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(
            *VEHICLE_STATUS_VALUES,
            name="vehicle_status",
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        default="active",
        server_default="active",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class IdentityResolution(Base):
    """每次通行的身份判定结果（含各证据分值，用于可解释展示）。"""

    __tablename__ = "identity_resolutions"
    __table_args__ = (
        Index("ix_identity_event", "event_id"),
        Index("ix_identity_subject", "subject_id"),
        Index("ix_identity_vehicle", "vehicle_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    vehicle_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    method: Mapped[str | None] = mapped_column(
        Enum(
            *IDENTITY_METHOD_VALUES,
            name="identity_method",
            native_enum=True,
            validate_strings=True,
        ),
        nullable=True,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    plate_conf: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    appearance_conf: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    cooccur_conf: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    matched_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    snapshot_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PendingIdentity(Base):
    """待绑定车辆池（人工登记队列）。"""

    __tablename__ = "pending_identities"
    __table_args__ = (Index("ix_pending_status", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[str] = mapped_column(String(255), nullable=False)
    pass_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(
            *PENDING_STATUS_VALUES,
            name="pending_status",
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VehicleCooccurrence(Base):
    """车辆共现矩阵（离线批量计算，复合主键）。"""

    __tablename__ = "vehicle_cooccurrence"

    vehicle_a: Mapped[str] = mapped_column(String(255), primary_key=True)
    vehicle_b: Mapped[str] = mapped_column(String(255), primary_key=True)
    window_count: Mapped[int] = mapped_column(Integer, nullable=False)
    jaccard: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AuditLog(Base):
    """操作审计日志（只增不改，由服务层写入，无更新/删除接口）。

    对应 P1-6 要求：所有写操作留痕（操作人/角色/动作/对象/IP/结果）。
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_actor", "actor"),
        Index("ix_audit_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    object_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result: Mapped[str] = mapped_column(
        String(255), nullable=False, default="ok", server_default="ok"
    )
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CounselorAssignment(Base):
    """辅导员班级映射（一人可带多班，复合主键）。

    P1-6 越权防护基础：counselor 角色的学生查询/绑审范围由此表限定。
    """

    __tablename__ = "counselor_assignments"
    __table_args__ = (Index("ix_counselor_user", "user_id"),)

    user_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    class_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OrgUnit(Base):
    """组织单元：学校 / 二级学院 / 年级 / 专业 / 班级五级级联。

    职责：支撑小程序学籍绑定页的级联选择（学校→学院→年级→专业→班级）。
    `parent_id` 自引用形成树；同级 `name` 唯一由服务层保证（防乱填）。
    说明书 §7.2 `org_units` 的工程落地：unit_type 取值锁定五级，
    不再保留开放式的 dorm/other，避免前端级联口径发散。
    """

    __tablename__ = "org_units"
    __table_args__ = (
        Index("ix_org_parent", "parent_id"),
        Index("ix_org_type", "unit_type"),
    )

    unit_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    unit_type: Mapped[str] = mapped_column(
        Enum(*ORG_UNIT_TYPE_VALUES, name="org_unit_type", native_enum=True, validate_strings=True),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        String(255), ForeignKey("org_units.unit_id", ondelete="CASCADE"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(
        String(255), nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


__all__ = [
    "AuditLog",
    "CounselorAssignment",
    "IDENTITY_METHOD_VALUES",
    "ORG_UNIT_TYPE_VALUES",
    "OWNER_BIND_TYPE_VALUES",
    "PENDING_STATUS_VALUES",
    "PLATE_TYPE_VALUES",
    "STUDENT_STATUS_VALUES",
    "USER_ROLE_VALUES",
    "USER_STATUS_VALUES",
    "VEHICLE_STATUS_VALUES",
    "IdentityResolution",
    "OrgUnit",
    "PendingIdentity",
    "User",
    "Student",
    "Vehicle",
    "VehicleCooccurrence",
]

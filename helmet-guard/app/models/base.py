"""ORM 基座：声明式基类与通用 Mixin。

职责：提供 SQLAlchemy 2.0 声明式基类、时间戳 Mixin 与统一元数据。
依赖：sqlalchemy。
边界：只定义映射基础设施；不含业务查询，不执行 I/O。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 统一命名约定，保证 Alembic 生成的迁移与 ORM 元数据一致。
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """创建/更新时间 Mixin。

    现有 6 张表中只有部分表带 `updated_at`，因此该 Mixin 仅提供
    `created_at` / `updated_at` 列工厂，由各模型按需选择使用。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class IdMixin:
    """自增主键 Mixin。"""

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

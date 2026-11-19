"""Alembic 迁移环境。

职责：提供离线（SQL 脚本）与在线（真实连接）两种迁移模式。
依赖：alembic、sqlalchemy、app.core.config、app.models。
边界：数据库 URL 统一从 `Settings` 读取，不在配置文件中硬编码路径。
"""

from __future__ import annotations

from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool

from app.core.config import get_settings
from app.models import Base

# Alembic 注入的上下文对象。
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ORM 元数据：Alembic 依据它生成增量迁移。
target_metadata = Base.metadata


def get_url() -> str:
    """返回迁移使用的数据库 URL。

    优先级：
    1. Alembic 配置中的 `sqlalchemy.url`（显式设置时优先，测试与工具链依赖）；
    2. `DATABASE_URL` 环境变量；
    3. `Settings.resolved_database_url`（按模式推导 SQLite 路径）。

    三者都不含硬编码的绝对路径，路径一律来自配置或环境变量。

    Returns:
        SQLAlchemy 可用的数据库 URL。
    """
    configured = config.get_main_option("sqlalchemy.url", "") or ""
    if configured.strip():
        return configured.strip()
    settings = get_settings()
    return settings.resolved_database_url


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 脚本，不建立数据库连接。"""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """在给定连接上执行迁移。

    Args:
        connection: 已建立的数据库连接。
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：建立连接并执行迁移。"""
    section: dict[str, Any] = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        do_run_migrations(connection)
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

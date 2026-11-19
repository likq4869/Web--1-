"""FastAPI 依赖注入工厂：数据库会话、当前用户与角色校验。

职责：提供可复用的依赖项，统一鉴权失败语义。
依赖：fastapi、sqlalchemy、app.core.security。
边界：只做会话生命周期管理与身份/角色校验；不包含业务查询与业务规则。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import PermissionDeniedError
from app.core.security import CurrentUser, resolve_current_user

_bearer_scheme = HTTPBearer(auto_error=False)


def _enable_sqlite_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
    """为每个 SQLite 连接启用外键约束。

    SQLite 默认关闭外键约束；显式开启可保证 ORM 与原生连接语义一致。

    Args:
        dbapi_connection: DBAPI 连接对象。
        _connection_record: SQLAlchemy 连接记录（未使用）。
    """
    execute = getattr(dbapi_connection, "execute", None)
    if execute is None:
        return
    execute("PRAGMA foreign_keys=ON")


def build_engine(settings: Settings | None = None) -> Engine:
    """按配置创建 SQLAlchemy Engine。

    Args:
        settings: 应用配置；缺省读取单例。

    Returns:
        已配置的 Engine；SQLite 启用外键约束以保持与原生连接一致，
        MySQL 开启连接保活（小皮 phpStudy 长连接防 `MySQL server has gone away`）。
    """
    cfg = settings or get_settings()
    url = cfg.resolved_database_url
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    if url.startswith("mysql"):
        # phpStudy 本地 MySQL：连接保活 + 回收，避免 wait_timeout 断连。
        return create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            pool_recycle=3600,
            connect_args={"charset": "utf8mb4"},
        )
    engine = create_engine(url, future=True, connect_args=connect_args)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def get_db_session(request: Request) -> Iterator[Session]:
    """提供请求级数据库会话。

    Args:
        request: 当前请求；用于在应用已持有 Engine 时复用。

    Yields:
        事务内 Session；请求结束或异常时自动关闭。
    """
    engine: Engine | None = getattr(request.app.state, "db_engine", None)
    if engine is None:
        engine = build_engine()
    session = Session(engine, future=True)
    try:
        yield session
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db_session)]


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> CurrentUser:
    """解析当前认证主体.

    Args:
        request: 当前请求。
        credentials: Bearer 凭据。

    Returns:
        当前用户。

    Raises:
        AuthenticationError: 未登录或令牌无效（401，前端据此触发刷新/重登录）。
    """
    return resolve_current_user(request, credentials)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_roles(*roles: str) -> Callable[[CurrentUser], CurrentUser]:
    """构造角色校验依赖。

    Args:
        *roles: 允许访问的角色；传 `"*"` 表示允许任意已登录用户。

    Returns:
        可作为 FastAPI 依赖使用的校验函数。
    """
    allowed = {role.strip() for role in roles if role.strip()}

    def _dependency(current_user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        """校验当前用户是否具备所需角色。

        Args:
            current_user: 当前认证主体。

        Returns:
            通过校验的当前用户。

        Raises:
            PermissionDeniedError: 角色不匹配时抛出。
        """
        if "*" in allowed:
            return current_user
        if current_user.role not in allowed:
            raise PermissionDeniedError("你没有访问该资源的权限")
        return current_user

    return _dependency

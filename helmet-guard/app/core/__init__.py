"""核心基座：配置、日志、异常、安全、中间件与依赖注入。

职责：对外暴露工程基座的稳定入口。
依赖：本包内各模块。
边界：仅做导入导出；导入本包不得触发数据库连接或模型加载。
"""

from app.core.config import Settings, get_settings
from app.core.deps import (
    CurrentUserDep,
    DbSession,
    build_engine,
    get_current_user,
    get_db_session,
    require_roles,
)
from app.core.errors import (
    AppError,
    ConflictError,
    ExternalServiceError,
    ModelNotReadyError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ValidationError,
    status_code_for,
)
from app.core.logging import configure_logging, get_logger
from app.core.middleware import (
    ErrorHandlerMiddleware,
    RequestContextMiddleware,
    install_middlewares,
    register_error_handlers,
)
from app.core.security import (
    CurrentUser,
    TokenPayload,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

__all__ = [
    "AppError",
    "ConflictError",
    "CurrentUser",
    "CurrentUserDep",
    "DbSession",
    "ErrorHandlerMiddleware",
    "ExternalServiceError",
    "ModelNotReadyError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "RequestContextMiddleware",
    "Settings",
    "TokenPayload",
    "ValidationError",
    "build_engine",
    "configure_logging",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "get_current_user",
    "get_db_session",
    "get_logger",
    "get_settings",
    "hash_password",
    "install_middlewares",
    "register_error_handlers",
    "require_roles",
    "status_code_for",
    "verify_password",
]

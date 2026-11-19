"""结构化日志：生产 JSON、开发 Console，并自动携带请求上下文。

职责：初始化 structlog / stdlib logging，提供带上下文的日志入口。
依赖：structlog、标准库 logging。
边界：只负责日志格式化与上下文绑定；不负责业务判断，也不主动记录敏感字段。
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.core.config import Settings

_CONFIGURED = False


def configure_logging(settings: Settings) -> None:
    """按配置初始化日志系统。

    Args:
        settings: 应用配置；`log_format` 决定 JSON 或 Console 输出。

    Raises:
        ValueError: `log_level` 不是标准日志级别名时抛出。
    """
    global _CONFIGURED

    level_name = settings.log_level.strip().upper()
    level = logging.getLevelNamesMapping().get(level_name)
    if level is None:
        raise ValueError(f"未知日志级别：{settings.log_level}")

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
        force=True,
    )
    # 第三方库日志统一降到 WARNING，避免结构化输出被噪音淹没。
    for noisy in ("uvicorn.access", "uvicorn.error", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if settings.log_format == "json" or settings.is_production:
        processors.append(structlog.processors.JSONRenderer(ensure_ascii=False))
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str) -> Any:
    """返回带模块名的结构化日志器。

    Args:
        name: 日志来源名称，通常传 `__name__`。

    Returns:
        已绑定 `logger` 字段的 structlog 日志器。
    """
    if not _CONFIGURED:
        configure_logging(_fallback_settings())
    return structlog.get_logger(name)


def _fallback_settings() -> Settings:
    """日志尚未初始化时构造最小可用配置。

    仅用于日志系统自身启动阶段，避免 `get_logger` 与配置初始化互相依赖。
    """
    from app.core.config import get_settings

    return get_settings()


def bind_request_context(**context: Any) -> None:
    """把请求级上下文绑定到当前协程上下文。

    Args:
        **context: 上下文键值对，例如 `request_id`、`trace_id`。
    """
    structlog.contextvars.bind_contextvars(**context)


def unbind_request_context(*keys: str) -> None:
    """解除指定请求上下文绑定。

    Args:
        *keys: 需要解除绑定的键名。
    """
    structlog.contextvars.unbind_contextvars(*keys)

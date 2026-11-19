"""HTTP 中间件：请求上下文追踪与领域异常统一响应。

职责：生成 trace_id、记录请求耗时、把领域异常转换为统一 JSON 响应。
依赖：starlette、fastapi、app.core.errors。
边界：只处理横切关注点；不包含任何业务规则，也不吞掉业务异常语义。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.errors import AppError, status_code_for
from app.core.logging import bind_request_context, get_logger, unbind_request_context

REQUEST_ID_HEADER = "X-Request-ID"
TRACE_ID_HEADER = "X-Trace-ID"

_logger = get_logger(__name__)


def error_payload(exc: AppError, trace_id: str) -> dict[str, Any]:
    """构造统一的错误响应载荷。

    载荷同时满足两套读取方：
      - `error` 嵌套结构：后端内部调试与既有测试依赖；
      - 顶层 `code` / `message` / `trace_id`：前端 `admin-web/src/api/types.ts`
        的 `ErrorResponse` 契约（原先后端只返回 `error` 嵌套，导致前端
        `body?.message` 恒为 undefined，错误提示退化为 axios 通用文案）。

    Args:
        exc: 领域异常。
        trace_id: 链路追踪 ID。

    Returns:
        可序列化的错误载荷。
    """
    payload: dict[str, Any] = exc.to_dict()
    return {
        "code": payload["code"],
        "message": payload["message"],
        "data": None,
        "error": payload,
        "trace_id": trace_id,
    }


class RequestContextMiddleware(BaseHTTPMiddleware):
    """注入请求级上下文：trace_id、request_id 与耗时日志。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """为每个请求建立追踪上下文。

        Args:
            request: 当前请求。
            call_next: 后续处理链。

        Returns:
            带 `X-Request-ID` 与 `X-Trace-ID` 响应头的响应。
        """
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        trace_id = request.headers.get(TRACE_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        bind_request_context(request_id=request_id, trace_id=trace_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            _logger.info(
                "request.completed",
                method=request.method,
                path=request.url.path,
                elapsed_ms=round(elapsed_ms, 2),
            )
            unbind_request_context("request_id", "trace_id")
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[TRACE_ID_HEADER] = trace_id
        return response


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """把领域异常转换为统一 JSON 错误响应。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """捕获领域异常并输出统一错误结构。

        Args:
            request: 当前请求。
            call_next: 后续处理链。

        Returns:
            统一错误响应；非领域异常交由上层默认处理器处理。
        """
        try:
            return await call_next(request)
        except AppError as exc:
            trace_id = getattr(request.state, "trace_id", "")
            _logger.warning(
                "request.domain_error",
                code=exc.code,
                status_code=status_code_for(exc),
                path=request.url.path,
                trace_id=trace_id,
            )
            return JSONResponse(
                status_code=status_code_for(exc),
                content=error_payload(exc, trace_id),
                headers={TRACE_ID_HEADER: trace_id} if trace_id else None,
            )


def register_error_handlers(app: FastAPI) -> None:
    """在 FastAPI 应用上注册领域异常处理器。

    Args:
        app: 目标应用。
    """

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        """将领域异常转换为统一错误响应。"""
        trace_id = getattr(request.state, "trace_id", "")
        _logger.warning(
            "request.domain_error",
            code=exc.code,
            status_code=status_code_for(exc),
            path=request.url.path,
            trace_id=trace_id,
        )
        return JSONResponse(
            status_code=status_code_for(exc),
            content=error_payload(exc, trace_id),
            headers={TRACE_ID_HEADER: trace_id} if trace_id else None,
        )


def install_middlewares(app: FastAPI) -> None:
    """按正确顺序安装中间件。

    Args:
        app: 目标应用。

    说明:
        `add_middleware` 按注册顺序反向执行，因此先注册错误处理再注册请求上下文，
        可保证异常发生时上下文已建立、trace_id 可用。
    """
    app.add_middleware(ErrorHandlerMiddleware)
    app.add_middleware(RequestContextMiddleware)


def build_error_payload(
    code: str,
    message: str,
    trace_id: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造统一错误载荷，供测试与文档参考。

    Args:
        code: 机器可读错误码。
        message: 用户可读消息。
        trace_id: 追踪 ID。
        details: 可选补充信息。

    Returns:
        可 JSON 序列化的错误载荷。
    """
    payload: dict[str, Any] = {"code": code, "message": message, "trace_id": trace_id}
    if details:
        payload["details"] = details
    return payload


__all__ = [
    "ErrorHandlerMiddleware",
    "RequestContextMiddleware",
    "TRACE_ID_HEADER",
    "build_error_payload",
    "install_middlewares",
    "register_error_handlers",
]

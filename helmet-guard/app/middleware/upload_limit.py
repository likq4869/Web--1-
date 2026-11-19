"""自查上传体限制中间件（第一层）。

职责：在 multipart 解析前累计请求体并设限，超限直接 413，
完整体只重放一次给下游路由。

由 B-2 从 `app/main.py` 拆出，行为逐字等价；应用装配仍保留在 `main.py`。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.types import Message


async def selfcheck_body_limit(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """自查上传 multipart 解析前的请求体上限（第一层）。

    在解析前累计请求体并设限（SELFCHECK_BODY_LIMIT = 10MiB 文件 + 2MiB 包裹余量，
    为整个请求体上限，含 multipart 包裹开销；单文件上限另为 MAX_BYTES=10MiB，
    见 read_upload_limited 第二层），超限直接 413（字符串 detail），
    不进入 multipart 解析。
    正常完整上传：请求体只重放一次给下游路由，后续 receive 继续走原始通道，
    以便仍能收到断开（http.disconnect）等消息。
    上传读取异常、或请求体未结束就收到断开等消息时，直接在此结束处理
    （400 字符串 detail），不把残缺 body 伪装成完整体交路由。
    缺 file 字段由路由校验返回 422（FastAPI 默认校验格式，detail 为列表，
    非字符串）；此处只拦超限体（413，字符串 detail）。
    chunked 无 Content-Length 同样受本层累计保护。
    """
    if request.url.path == "/api/v1/self-check" and request.method == "POST":
        try:
            from app.selfcheck import SELFCHECK_BODY_LIMIT
        except ImportError:
            # 降级兜底：模块常量不可用时用等值的本地上限，
            # 保证请求体上限判定始终生效（宁可可导入失败也不能无限制收包）
            body_limit = 12 * 1024 * 1024
        else:
            body_limit = SELFCHECK_BODY_LIMIT
        # 快路径：Content-Length 已超限直接拒收，避免读体
        raw = request.headers.get("content-length", "")
        try:
            size = int(str(raw).strip()) if str(raw).strip() else -1
        except ValueError:
            size = -1
        if size >= 0 and size > body_limit:
            return JSONResponse(
                status_code=413,
                content={"detail": "图片过大（请求体超过上限），请压缩到 10MB 以内后重试"},
            )
        # 慢路径：累计读体（含 chunked），超限即停并 413；完整体才重放，不影响解析。
        # 重放只做一次：首次 receive 返回完整体，后续 receive 继续走原始通道，
        # 以便下游仍能收到断开（http.disconnect）等消息，不吞事件。
        # 上传读取异常、或请求体未结束就收到断开等消息时，直接在此结束处理
        # （400 字符串 detail），不把残缺 body 交路由。
        recv = request.receive
        chunks: list[bytes] = []
        total = 0
        try:
            while True:
                msg = await recv()
                if msg.get("type") != "http.request":
                    # 请求体未结束就断开：直接结束，不交残缺体。
                    return JSONResponse(
                        status_code=400,
                        content={"detail": "上传中断，请重新拍摄后上传"},
                    )
                part = msg.get("body", b"") or b""
                total += len(part)
                if total > body_limit:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "图片过大（请求体超过上限），请压缩到 10MB 以内后重试"},
                    )
                chunks.append(part)
                if not msg.get("more_body", False):
                    break
        except (OSError, RuntimeError, ValueError):
            # 上传读取异常：直接结束处理，不伪装完整体交路由。
            return JSONResponse(
                status_code=400,
                content={"detail": "图片读取失败，请重新拍摄后上传"},
            )
        body = b"".join(chunks)
        state = {"replayed": False}

        async def _replay() -> Message:
            if not state["replayed"]:
                state["replayed"] = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await recv()

        # Starlette 的 Request._receive 是内部属性，官方未提供类型化 setter。
        # 替换 receive 是 ASGI 层的标准重放手法（见 starlette 自身实现）。
        request._receive = _replay
    return await call_next(request)


__all__ = ["selfcheck_body_limit"]

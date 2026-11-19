"""自查路由：模型预检与手机拍照单张推理。

职责：HTTP 解析与响应序列化；照片仅用于本次推理，不写业务库。
依赖：FastAPI、app.selfcheck、app.core.health。
边界：路径与响应形状必须逐字保持（`miniprogram/src/utils/selfcheck.ts`
的 `sanitizeSelfCheckResult` 依赖）；两层上传限流语义不变。

由 B-2 从 `app/main.py` 拆出，行为逐字等价。
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.health import ApiResponse

router = APIRouter(tags=["selfcheck"])


@router.get("/api/v1/self-check/status")
def self_check_status() -> ApiResponse:
    """自查模型预检：权重缺失显示未就绪，前端保留页面联调。"""
    from app.selfcheck import model_status

    info = model_status()
    code = 200 if info["ready"] else 503
    if code != 200:
        raise HTTPException(status_code=code, detail=info["reason"])
    return info


@router.post("/api/v1/self-check")
async def self_check(file: UploadFile = File(...)) -> ApiResponse:
    """手机拍照自查：单张图片推理。上传字段名必须为 file。

    成功返回 status（helmeted/bare/unknown）、reason_code、model_version、
    inference_ms、image_width/height、boxes（label/confidence/归一化 xyxy）。
    照片仅用于本次推理，不写入校门通行与统计。

    上传边界（两层）：中间件在 multipart 解析前累计整个请求体并设限
    （SELFCHECK_BODY_LIMIT = 10MiB 单文件上限 + 2MiB 包裹余量），超限直接 413
    字符串 detail，不进入解析；完整体通过后只重放一次、后续 receive 走原始通道；
    解析后单文件读取仍受 MAX_BYTES=10MiB 约束
    （第二层，见 read_upload_limited，按剩余限额控制单次读取，
    最大读取量严格为 MAX_BYTES + 1）。
    缺 file 字段由路由校验返回 422（FastAPI 默认校验格式，detail 为列表）；
    中间件只拦超限体（413，字符串 detail）。
    上传读取异常、请求体未结束就断开时中间件直接结束处理（400 字符串 detail），
    不把残缺体交路由。
    模型 pin：首次成功加载后当前进程一直复用同一实例与版本
    （预检与推理共用，见 _ensure_model），仅无模型时才检查文件并加载；
    配置路径变化或原文件被移走不切换实例，预检提示重启，推理无配置变更 503 分支。
    模型 pin：首次成功加载后当前进程一直复用同一实例与版本
    （预检与推理共用，见 _ensure_model），配置变更只提示重启。
    解码前先做宽/高/像素总量预检，保留 EXIF 旋转。
    并发：解码+YOLO 同步推理经工作线程执行，不占 ASGI 事件循环；单进程 CPU
    开发配置同时只允许一个推理名额，繁忙返回 429 可重试；名额所有权移交
    工作线程，只由工作线程在实际结束时释放。排队等待时取消与开始后取消
    均不由事件循环侧释放（shield 隔离，工作线程继续占位到结束并释放），
    仅任务提交失败（线程永不执行）由事件循环侧释放，避免泄漏。
    """
    import asyncio as _asyncio

    from app.selfcheck import (
        ImageTooLarge,
        _infer_sync,
        read_upload_limited,
        release_infer,
        try_acquire_infer,
    )

    if file is None or not file.filename:
        raise HTTPException(status_code=400, detail="请上传图片（字段名 file）")
    ctype = (file.content_type or "").lower()
    if ctype and not (ctype.startswith("image/") or ctype == "application/octet-stream"):
        raise HTTPException(
            status_code=400, detail=f"文件类型不支持：{file.content_type}，请上传图片"
        )
    try:
        try:
            data = await read_upload_limited(file)
        except ImageTooLarge as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"图片读取失败：{exc}") from exc
        if not data:
            raise HTTPException(status_code=400, detail="图片为空，请重新拍摄或选择有效图片")
        if not try_acquire_infer():
            raise HTTPException(
                status_code=429, detail="当前推理繁忙（同一时间只处理一张照片），请稍后重试"
            )

        # 名额移交工作线程：只由工作线程 finally 释放。
        # shield 隔离取消：排队时取消 / 开始后取消都不由本侧释放，
        # 工作线程继续执行到实际结束并释放；仅提交失败才由本侧释放。
        def _run() -> dict[str, Any]:
            try:
                return _infer_sync(data)
            finally:
                release_infer()

        try:
            _loop = _asyncio.get_running_loop()
            _fut: _asyncio.Future[dict[str, Any]] = _loop.run_in_executor(None, _run)
        except (RuntimeError, OSError) as exc:
            release_infer()
            raise HTTPException(
                status_code=503, detail=f"推理任务提交失败，请稍后重试：{exc}"
            ) from exc
        try:
            result = await _asyncio.shield(_fut)
        except _asyncio.CancelledError:
            # 排队时取消与开始后取消：工作线程仍占位到结束并释放，本侧不释放。
            raise
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return result
    finally:
        # 关闭失败不掩盖主流程结果（此时已准备返回推理结果或异常）
        with suppress(Exception):
            await file.close()


__all__ = ["router"]

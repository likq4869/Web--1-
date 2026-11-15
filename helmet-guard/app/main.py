"""FastAPI 入口：健康检查、点位、统计、事件查询、人工复核。

建表只在应用启动（lifespan）执行；查询接口只做只读检查，
表缺失时返回 503，不再重复建库。
/health 的模型与采集状态来自采集进程上报的心跳（模型加载、首帧、运行/停止）。
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.types import Message

from . import (
    ALERT_TEXT,
    EVENTS_PAGE_SIZE_MAX,
    get_db_path,
    get_heartbeat_expire_seconds,
    get_mode,
    resolve_weights,
)
from .db import connect, init_db, tables_exist
from .store import apply_review

# 心跳行的解析结果：source_id/run_id/mode/updated_at + detail_parsed
Heartbeat = dict[str, Any]
# 模型状态：ready/reason/weights(/run_id)
ModelInfo = dict[str, Any]
# 点位采集状态：fps/stage 等
CaptureInfo = dict[str, Any]
# 统一 API 响应体
ApiResponse = dict[str, Any]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # 应用启动建表：保留启动建表，查询接口不再建库
    init_db()
    yield


app = FastAPI(title="头盔守护者后端", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def _selfcheck_body_limit(
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
            from .selfcheck import SELFCHECK_BODY_LIMIT
        except Exception:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001
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


def _hb_detail(row: sqlite3.Row) -> dict[str, Any]:
    try:
        parsed = json.loads(row["detail"] or "{}")
    except Exception:  # noqa: BLE001
        return {}
    # 心跳 detail 是采集进程写入的 JSON 对象；非对象时按空对象处理
    return parsed if isinstance(parsed, dict) else {}


def _all_heartbeats(conn: sqlite3.Connection) -> list[Heartbeat]:
    rows = conn.execute("SELECT source_id,run_id,mode,updated_at,detail FROM heartbeats").fetchall()
    out: list[Heartbeat] = []
    for r in rows:
        d = dict(r)
        d["detail_parsed"] = _hb_detail(r)
        out.append(d)
    return out


def _model_status(latest: Heartbeat | None) -> ModelInfo:
    mode = get_mode()
    if mode == "demo":
        return {"ready": True, "reason": "demo 模式使用合成事件，无需专用权重", "weights": None}
    # live：以采集进程上报的模型加载状态为准
    if latest is None:
        weights = str(resolve_weights(os.getenv("HELMET_GUARD_WEIGHTS", "weights/helmet_best.pt")))
        return {
            "ready": False,
            "reason": f"live 无采集心跳，需启动检测进程（期望权重 {weights}）",
            "weights": weights,
        }
    detail = latest.get("detail_parsed", {}) or {}
    weights = str(
        detail.get("weights")
        or resolve_weights(os.getenv("HELMET_GUARD_WEIGHTS", "weights/helmet_best.pt"))
    )
    if detail.get("stage") == "model_failed":
        return {
            "ready": False,
            "reason": f"模型加载失败：{detail.get('error', '未知错误')}",
            "weights": weights,
            "run_id": latest.get("run_id"),
        }
    if not detail.get("model_loaded"):
        return {
            "ready": False,
            "reason": "模型尚未加载（采集进程未报告就绪）",
            "weights": weights,
            "run_id": latest.get("run_id"),
        }
    if not detail.get("model_ok", False):
        return {
            "ready": False,
            "reason": f"权重被拒绝：{detail.get('model_info', '')}",
            "weights": weights,
            "run_id": latest.get("run_id"),
        }
    return {
        "ready": True,
        "reason": f"采集进程已加载模型：{detail.get('model_info', '')}",
        "weights": weights,
        "run_id": latest.get("run_id"),
    }


def _capture_status(latest: Heartbeat | None, rows: list[Heartbeat]) -> CaptureInfo:
    mode = get_mode()
    if latest is None:
        if mode == "demo":
            return {"ready": False, "reason": "demo 模式无实时采集", "heartbeats": []}
        return {"ready": False, "reason": "live 无采集心跳，需启动检测进程", "heartbeats": []}
    detail = latest.get("detail_parsed", {}) or {}
    hb_mode = latest.get("mode", "")
    # camera_check 心跳：仅预览，不做业务采集
    if hb_mode.startswith("camera_check"):
        return {
            "ready": False,
            "reason": f"camera_check 预览中（run={latest.get('run_id')}），"
            "仅显示 person 等类别，不写业务数据",
            "heartbeats": rows,
        }
    if mode == "demo" and not hb_mode.startswith("live"):
        return {"ready": False, "reason": "demo 模式无实时采集", "heartbeats": rows}
    stage = detail.get("stage", "")
    frames = detail.get("frames", 0)
    if stage == "stopped" or hb_mode.endswith("-stopped"):
        return {
            "ready": False,
            "reason": f"采集已停止 run={latest.get('run_id')} frames={frames}",
            "heartbeats": rows,
        }
    if stage == "model_failed":
        return {
            "ready": False,
            "reason": f"模型加载失败，未开始采集：{detail.get('error', '')}",
            "heartbeats": rows,
        }
    if not detail.get("had_first_frame") or frames <= 0:
        return {
            "ready": False,
            "reason": f"无首帧 run={latest.get('run_id')} 采集进程尚未收到有效画面",
            "heartbeats": rows,
        }
    # 心跳过期检查
    try:
        latest_dt = datetime.fromisoformat(latest["updated_at"])
        if latest_dt.tzinfo is None:
            latest_dt = latest_dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
        age = (datetime.now().astimezone() - latest_dt).total_seconds()
    except Exception:  # noqa: BLE001
        age = 1e9
    expire = get_heartbeat_expire_seconds()
    if age > expire:
        return {"ready": False, "reason": f"心跳过期 {age:.0f}s>{expire}s", "heartbeats": rows}
    return {
        "ready": True,
        "reason": f"采集中 run={latest.get('run_id')} frames={frames}",
        "heartbeats": rows,
    }


def _db_status() -> tuple[dict[str, Any], sqlite3.Connection | None]:
    """只读检查：不建库。返回 (db_info, conn_or_None)。"""
    path = get_db_path()
    try:
        conn = connect()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"数据库不可用：{exc}", "path": str(path)}, None
    try:
        if not tables_exist(conn):
            conn.close()
            return {
                "ok": False,
                "reason": "数据库未初始化：请先启动应用或运行种子",
                "path": str(path),
            }, None
        conn.execute("SELECT 1").fetchone()
        return {"ok": True, "path": str(path)}, conn
    except Exception as exc:  # noqa: BLE001
        # 关闭失败不应掩盖原始异常（此时正要返回数据库错误原因）
        with suppress(Exception):
            conn.close()
        return {"ok": False, "reason": str(exc), "path": str(path)}, None


def _require_db() -> sqlite3.Connection:
    db, conn = _db_status()
    if conn is None:
        raise HTTPException(status_code=503, detail=db.get("reason", "数据库未就绪"))
    return conn


@app.get("/health")
def health() -> ApiResponse:
    db, conn = _db_status()
    if conn is None:
        return {
            "mode": get_mode(),
            "db": db,
            "model": _model_status(None),
            "capture": _capture_status(None, []),
            "api": "ok",
        }
    try:
        rows = _all_heartbeats(conn)
    finally:
        conn.close()
    latest = max(rows, key=lambda r: r["updated_at"]) if rows else None
    return {
        "mode": get_mode(),
        "db": db,
        "model": _model_status(latest),
        "capture": _capture_status(latest, rows),
        "api": "ok",
    }


@app.get("/api/v1/sources")
def list_sources() -> ApiResponse:
    conn = _require_db()
    try:
        rows = conn.execute(
            "SELECT source_id,name,status,last_seen,updated_at FROM sources ORDER BY source_id"
        ).fetchall()
    finally:
        conn.close()
    return {"mode": get_mode(), "sources": [dict(r) for r in rows]}


@app.get("/api/v1/stats")
def stats(
    source_id: str | None = None,
    run_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> ApiResponse:
    conn = _require_db()
    sql = "SELECT rider_status,COUNT(*) c FROM passes WHERE 1=1"
    args: list[str] = []
    if source_id:
        sql += " AND source_id=?"
        args.append(source_id)
    if run_id:
        sql += " AND run_id=?"
        args.append(run_id)
    if start:
        sql += " AND occurred_at>=?"
        args.append(start)
    if end:
        sql += " AND occurred_at<=?"
        args.append(end)
    sql += " GROUP BY rider_status"
    try:
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()
    counts = {"helmeted": 0, "bare": 0, "unknown": 0}
    for r in rows:
        counts[r["rider_status"]] = r["c"]
    total = sum(counts.values())
    judged = counts["helmeted"] + counts["bare"]
    wearing = counts["helmeted"] / judged if judged else None
    coverage = judged / total if total else None
    return {
        "mode": get_mode(),
        "source_id": source_id,
        "run_id": run_id,
        "total": total,
        "counts": counts,
        "wearing_rate": wearing,
        "coverage": coverage,
    }


@app.get("/api/v1/events")
def list_events(
    source_id: str | None = None,
    status: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(20, ge=1, le=EVENTS_PAGE_SIZE_MAX),
    offset: int = Query(0, ge=0),
) -> ApiResponse:
    if status and status not in ("pending", "confirmed", "dismissed"):
        raise HTTPException(status_code=400, detail="status 非法")
    conn = _require_db()
    sql = (
        "SELECT event_id,pass_id,source_id,run_id,occurred_at,status,"
        "model_label,reason,reviewer,reviewed_at,created_at FROM events WHERE 1=1"
    )
    count_sql = "SELECT COUNT(*) n FROM events WHERE 1=1"
    args: list[str] = []
    if source_id:
        sql += " AND source_id=?"
        count_sql += " AND source_id=?"
        args.append(source_id)
    if status:
        sql += " AND status=?"
        count_sql += " AND status=?"
        args.append(status)
    if start:
        sql += " AND occurred_at>=?"
        count_sql += " AND occurred_at>=?"
        args.append(start)
    if end:
        sql += " AND occurred_at<=?"
        count_sql += " AND occurred_at<=?"
        args.append(end)
    sql += " ORDER BY occurred_at DESC LIMIT ? OFFSET ?"
    try:
        total = conn.execute(count_sql, args).fetchone()["n"]
        rows = conn.execute(sql, args + [limit, offset]).fetchall()
    finally:
        conn.close()
    return {
        "mode": get_mode(),
        "total": total,
        "limit": limit,
        "offset": offset,
        "events": [dict(r) for r in rows],
    }


class ReviewBody(BaseModel):
    decision: Literal["confirmed", "dismissed"]
    reason: str = Field(default="", max_length=500)
    operator: str = Field(default="", max_length=64)


@app.post("/api/v1/events/{event_id}/review")
def review_event(event_id: str, body: ReviewBody) -> ApiResponse:
    conn = _require_db()
    try:
        result, code = apply_review(conn, event_id, body.decision, body.reason, body.operator)
    finally:
        conn.close()
    if code == 404:
        raise HTTPException(status_code=404, detail="事件不存在")
    if code == 409:
        raise HTTPException(status_code=409, detail="已有不同复核结论")
    conn2 = _require_db()
    try:
        row = conn2.execute(
            "SELECT event_id,status,reason,reviewer,reviewed_at FROM events WHERE event_id=?",
            (event_id,),
        ).fetchone()
    finally:
        conn2.close()
    return {"mode": get_mode(), "result": result, "event": dict(row)}


@app.get("/api/v1/alerts")
def list_alerts() -> ApiResponse:
    conn = _require_db()
    try:
        rows = conn.execute(
            "SELECT alert_id,event_id,source_id,status,note,created_at,"
            "updated_at FROM alerts ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    finally:
        conn.close()
    return {"mode": get_mode(), "alert_text": ALERT_TEXT, "alerts": [dict(r) for r in rows]}


@app.get("/api/v1/self-check/status")
def self_check_status() -> ApiResponse:
    """自查模型预检：权重缺失显示未就绪，前端保留页面联调。"""
    from .selfcheck import model_status

    info = model_status()
    code = 200 if info["ready"] else 503
    if code != 200:
        raise HTTPException(status_code=code, detail=info["reason"])
    return info


@app.post("/api/v1/self-check")
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

    from .selfcheck import (
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
        except Exception as exc:  # noqa: BLE001
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
        except Exception as exc:  # noqa: BLE001
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

"""实时监控 API：点位健康、违规流、WS 实时推送。

职责：HTTP 解析与响应序列化、分页钳制、服务调用、WS 鉴权与连接管理。
依赖：FastAPI、app.core.deps、app.services.monitor、app.services.realtime。
边界：不做业务规则判定；WS 推送只做过滤分发，不做业务组装；
counselor 按 auth 的 source_ids 过滤。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session as OrmSession

from app.core.config import get_settings
from app.core.deps import CurrentUserDep, DbSession, build_engine
from app.core.security import decode_token
from app.repositories.user import UserRepository
from app.schemas.monitor import (
    PointConfigBody,
    PointConfigResponse,
    PointSnapshotResponse,
    PointStreamResponse,
)
from app.services.monitor.service import MonitorService
from app.services.realtime.hub import hub

router = APIRouter(tags=["monitor-admin"])

WS_CLOSE_UNAUTHORIZED = 4401
WS_CLOSE_FORBIDDEN = 4403

# WS 读权限：与监控 REST 一致（含 observer，方便大屏值班）。
WS_READ_ROLES = frozenset(
    {
        "super_admin",
        "league_officer",
        "counselor",
        "security_officer",
        "auditor",
        "admin",
        "reviewer",
        "observer",
    }
)


@router.get("/api/v1/admin/monitor/points")
def list_monitor_points(session: DbSession, user: CurrentUserDep) -> dict[str, Any]:
    """点位健康列表（counselor 仅限名下点位）。"""
    service = MonitorService(session)
    items = service.list_points(user.role or "", user.subject)
    return {"items": items, "total": len(items)}


@router.get("/api/v1/admin/monitor/points/{point_id}")
def get_monitor_point(
    point_id: str, session: DbSession, user: CurrentUserDep
) -> dict[str, Any]:
    """单点位健康 + 最近一条事件摘要（无真实视频源，不编造视频地址）。"""
    service = MonitorService(session)
    return service.get_point(user.role or "", user.subject, point_id)


@router.get("/api/v1/admin/monitor/points/{point_id}/snapshot")
def get_monitor_snapshot(
    point_id: str, session: DbSession, user: CurrentUserDep
) -> dict[str, Any]:
    """单点位快照：健康 + 最近事件 + 最近通行证据帧。

    证据复用 passes.boxes / image_width / image_height（与审批详情同口径）；
    无通行记录时 evidence 为 None，前端按离线降级展示。
    """
    service = MonitorService(session)
    payload = service.get_snapshot(user.role or "", user.subject, point_id)
    return PointSnapshotResponse.model_validate(payload).model_dump(mode="json")


@router.get("/api/v1/admin/monitor/points/{point_id}/stream")
def get_monitor_stream(
    point_id: str, session: DbSession, user: CurrentUserDep
) -> dict[str, Any]:
    """单点位流状态：当前无真实视频源，一律不可用（诚实降级）。

    不编造 stream_url；前端据此只展示检测叠加与违规流。
    """
    service = MonitorService(session)
    payload = service.get_stream(user.role or "", user.subject, point_id)
    return PointStreamResponse.model_validate(payload).model_dump(mode="json")


@router.get("/api/v1/admin/monitor/points/{point_id}/config")
def get_monitor_config(
    point_id: str, session: DbSession, user: CurrentUserDep
) -> dict[str, Any]:
    """读取点位标定配置（无行回退内存默认，开箱可用）。"""
    service = MonitorService(session)
    payload = service.get_config(user.role or "", user.subject, point_id)
    return PointConfigResponse.model_validate(payload).model_dump(mode="json")


@router.put("/api/v1/admin/monitor/points/{point_id}/config")
def update_monitor_config(
    point_id: str,
    body: PointConfigBody,
    session: DbSession,
    user: CurrentUserDep,
) -> dict[str, Any]:
    """覆盖点位标定配置（归一化校验 + 事务 + 审计）。

    事务由服务层收敛（成功提交/失败回滚），路由层只做参数校验与响应序列化。
    """
    service = MonitorService(session)
    payload = service.update_config(
        user.role or "",
        user.subject,
        point_id,
        roi=body.roi,
        count_line_y=body.count_line_y,
        alert_zone=body.alert_zone,
    )
    return PointConfigResponse.model_validate(payload).model_dump(mode="json")


@router.get("/api/v1/admin/monitor/feed")
def get_monitor_feed(
    session: DbSession,
    user: CurrentUserDep,
    point_id: str | None = Query(None, max_length=64),
    limit: int = Query(20, ge=1, le=50),
) -> dict[str, Any]:
    """实时违规流初始数据（最近 bare 事件倒序，最多 50 条）。"""
    service = MonitorService(session)
    items = service.recent_feed(user.role or "", user.subject, point_id=point_id, limit=limit)
    return {"items": items, "total": len(items)}


@router.websocket("/api/v1/admin/ws/live")
async def live_websocket(websocket: WebSocket) -> None:
    """实时推送通道（查询参数 ``?token=<access_token>`` 鉴权）。

    浏览器 WebSocket 无法自定义 Authorization 头，故走 query token；
    服务端用现有 ``decode_token`` 校验，失败 4401 关闭，无权限 4403 关闭。
    连接后服务端只推送可见点位消息；客户端可发 ``ping`` 保活，服务端回 ``pong``。
    """
    token = websocket.query_params.get("token", "")
    if not token:
        await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
        return
    try:
        payload = decode_token(token, settings=get_settings())
    except Exception:
        await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
        return
    if payload.role not in WS_READ_ROLES:
        await websocket.close(code=WS_CLOSE_FORBIDDEN)
        return
    source_ids: list[str] = []
    if payload.role == "counselor":
        try:
            engine = build_engine(get_settings())
            with OrmSession(engine, future=True) as session:
                source_ids = UserRepository(session).list_source_ids(payload.subject)
        except Exception:
            source_ids = []
    await websocket.accept()
    await hub.connect(websocket, role=payload.role, source_ids=source_ids)
    try:
        while True:
            try:
                message = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except Exception:
                break
            if message.strip().lower() == "ping":
                try:
                    await websocket.send_text("pong")
                except Exception:
                    break
    finally:
        await hub.disconnect(websocket)


__all__ = ["router"]

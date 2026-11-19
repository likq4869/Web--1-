"""P3-4 实时监控测试：点位健康 / 违规流 / WS 鉴权 / 连接过滤。

职责：覆盖监控 REST 的 RBAC 收敛、counselor 按 source_ids 过滤、
WS query-token 鉴权与 hub 按点位过滤广播。
依赖：FastAPI TestClient（含 websocket）、SQLAlchemy。
边界：不测前端渲染；视频地址不在后端编造，不做断言。
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.core.deps import get_current_user
from app.core.security import CurrentUser, create_access_token


def _auth_override(subject: str, role: str):  # type: ignore[no-untyped-def]
    """构造鉴权覆盖函数."""

    def _dep() -> CurrentUser:
        return CurrentUser(subject=subject, role=role, claims={})

    return _dep


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """绑定临时库的 TestClient，并预置点位/心跳/事件/决策种子."""
    db_path = tmp_path / "monitor-api.db"
    monkeypatch.setenv("HELMET_GUARD_DB", str(db_path))
    monkeypatch.setenv("HELMET_GUARD_MODE", "demo")
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-for-production")
    monkeypatch.setenv("REDIS_URL", "")

    import app.main as main_mod

    importlib.reload(main_mod)
    from app.core.config import get_settings as _get_settings

    _get_settings.cache_clear()

    now = datetime.now(UTC).replace(tzinfo=None)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    fresh_ts = now.isoformat()

    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        engine = client.app.state.db_engine  # type: ignore[attr-defined]
        with Session(engine, future=True) as session:
            from app.models.decision import Decision
            from app.models.entities import Event, Heartbeat, Pass, Source
            from app.models.identity import Student

            session.add(
                Source(
                    source_id="gate-east",
                    name="东校门",
                    status="online",
                    last_seen=fresh_ts,
                    updated_at=fresh_ts,
                )
            )
            session.add(
                Heartbeat(
                    source_id="gate-east",
                    run_id="run-1",
                    mode="live",
                    updated_at=fresh_ts,
                    detail='{"stage": "running", "fps": 15.0}',
                )
            )
            session.add(
                Student(
                    student_id="S001",
                    name="张三",
                    status="active",
                    college="计算机学院",
                    class_name="计科2201",
                )
            )
            session.add(
                Pass(
                    pass_id="p-m1",
                    source_id="gate-east",
                    run_id="run-1",
                    occurred_at=(today + timedelta(hours=8)).isoformat(),
                    rider_status="bare",
                    model_raw="",
                    boxes='[{"label": "no helmet", "confidence": 0.9, '
                    '"xyxy": [0.1, 0.1, 0.3, 0.3]}]',
                    image_width=640,
                    image_height=480,
                    created_at=(today + timedelta(hours=8)).isoformat(),
                )
            )
            session.add(
                Event(
                    event_id="e-m1",
                    pass_id="p-m1",
                    source_id="gate-east",
                    run_id="run-1",
                    occurred_at=(today + timedelta(hours=8)).isoformat(),
                    status="pending",
                    model_label="no helmet",
                    reason="测试",
                    created_at=today.isoformat(),
                )
            )
            session.add(
                Decision(
                    decision_id="dec-m1",
                    event_id="e-m1",
                    student_id="S001",
                    level="L2",
                    action="deduct_score",
                    score_delta=-1,
                    reason_code="REPEAT_WITHIN_30D",
                    message="测试",
                    confidence=0.9,
                    status="PENDING_REVIEW",
                )
            )
            session.commit()
        yield client


def test_monitor_requires_auth(api_client: TestClient) -> None:
    """未登录访问监控接口被拒（401）."""
    response = api_client.get("/api/v1/admin/monitor/points")
    assert response.status_code == 401


def test_monitor_forbidden_role_returns_404(api_client: TestClient) -> None:
    """学生角色访问监控按无资源处理（404）."""
    api_client.app.dependency_overrides[get_current_user] = _auth_override("S001", "student")
    try:
        response = api_client.get("/api/v1/admin/monitor/points")
        assert response.status_code == 404
    finally:
        api_client.app.dependency_overrides.clear()


def test_monitor_points_and_feed_shape(api_client: TestClient) -> None:
    """点位健康与违规流返回约定字段（含关联决策档位）."""
    api_client.app.dependency_overrides[get_current_user] = _auth_override(
        "admin1", "super_admin"
    )
    try:
        points = api_client.get("/api/v1/admin/monitor/points")
        assert points.status_code == 200, points.text
        body = points.json()
        assert body["total"] == 1
        assert body["items"][0]["source_id"] == "gate-east"
        assert body["items"][0]["status"] == "online"

        single = api_client.get("/api/v1/admin/monitor/points/gate-east")
        assert single.status_code == 200, single.text
        payload = single.json()
        assert payload["point"]["source_id"] == "gate-east"
        assert payload["last_event"]["event_id"] == "e-m1"

        missing = api_client.get("/api/v1/admin/monitor/points/no-such-point")
        assert missing.status_code == 404

        feed = api_client.get("/api/v1/admin/monitor/feed")
        assert feed.status_code == 200, feed.text
        items = feed.json()["items"]
        assert len(items) == 1
        assert items[0]["event_id"] == "e-m1"
        assert items[0]["decision_level"] == "L2"
        assert items[0]["point_name"] == "东校门"
    finally:
        api_client.app.dependency_overrides.clear()


def test_counselor_without_sources_sees_empty(api_client: TestClient) -> None:
    """无名下点位的 counselor 收不到点位事件（过滤语义）."""
    api_client.app.dependency_overrides[get_current_user] = _auth_override(
        "counselor1", "counselor"
    )
    try:
        points = api_client.get("/api/v1/admin/monitor/points")
        assert points.status_code == 200, points.text
        assert points.json()["total"] == 0
        single = api_client.get("/api/v1/admin/monitor/points/gate-east")
        assert single.status_code == 404
        feed = api_client.get("/api/v1/admin/monitor/feed")
        assert feed.status_code == 200, feed.text
        assert feed.json()["items"] == []
    finally:
        api_client.app.dependency_overrides.clear()


def _make_token(subject: str, role: str) -> str:
    """用测试密钥签发访问令牌（WS 鉴权用）."""
    from app.core.config import get_settings as _get_settings

    return create_access_token(subject, role, _get_settings())


def test_ws_rejects_missing_and_bad_token(api_client: TestClient) -> None:
    """WS 无 token 与坏 token 被关闭（握手失败直接抛断开异常）."""
    with pytest.raises(WebSocketDisconnect), api_client.websocket_connect(
        "/api/v1/admin/ws/live"
    ):
        pass
    with pytest.raises(WebSocketDisconnect), api_client.websocket_connect(
        "/api/v1/admin/ws/live?token=bad-token"
    ):
        pass


def test_ws_ping_pong(api_client: TestClient) -> None:
    """WS 合法 token 可建连；ping 回 pong（保活语义）."""
    token = _make_token("admin1", "super_admin")
    with api_client.websocket_connect(f"/api/v1/admin/ws/live?token={token}") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


def test_monitor_snapshot_stream_and_config(api_client: TestClient) -> None:
    """快照复用通行证据 / 流诚实不可用 / 标定读写闭环."""
    api_client.app.dependency_overrides[get_current_user] = _auth_override(
        "admin1", "super_admin"
    )
    try:
        snapshot = api_client.get("/api/v1/admin/monitor/points/gate-east/snapshot")
        assert snapshot.status_code == 200, snapshot.text
        payload = snapshot.json()
        assert payload["point"]["source_id"] == "gate-east"
        assert payload["evidence"] is not None
        assert payload["evidence"]["pass_id"] == "p-m1"
        assert payload["evidence"]["image_width"] == 640
        assert payload["evidence"]["boxes"][0]["label"] == "no helmet"

        stream = api_client.get("/api/v1/admin/monitor/points/gate-east/stream")
        assert stream.status_code == 200, stream.text
        stream_body = stream.json()
        assert stream_body["available"] is False
        assert stream_body["stream_url"] is None

        config = api_client.get("/api/v1/admin/monitor/points/gate-east/config")
        assert config.status_code == 200, config.text
        assert config.json()["roi"] == [0.05, 0.2, 0.95, 0.95]

        updated = api_client.put(
            "/api/v1/admin/monitor/points/gate-east/config",
            json={
                "roi": [0.1, 0.2, 0.8, 0.9],
                "count_line_y": 0.55,
                "alert_zone": [0.2, 0.3, 0.8, 0.9],
            },
        )
        assert updated.status_code == 200, updated.text
        body = updated.json()
        assert body["roi"] == [0.1, 0.2, 0.8, 0.9]
        assert body["updated_by"] == "admin1"

        reread = api_client.get("/api/v1/admin/monitor/points/gate-east/config")
        assert reread.status_code == 200, reread.text
        assert reread.json()["count_line_y"] == 0.55

        bad = api_client.put(
            "/api/v1/admin/monitor/points/gate-east/config",
            json={
                "roi": [0.9, 0.9, 0.1, 0.1],
                "count_line_y": 0.55,
                "alert_zone": [0.2, 0.3, 0.8, 0.9],
            },
        )
        assert bad.status_code == 422
    finally:
        api_client.app.dependency_overrides.clear()


def test_monitor_config_write_forbidden(api_client: TestClient) -> None:
    """学生写标定按无资源处理（404，不泄露接口存在性）."""
    api_client.app.dependency_overrides[get_current_user] = _auth_override("S001", "student")
    try:
        response = api_client.put(
            "/api/v1/admin/monitor/points/gate-east/config",
            json={
                "roi": [0.1, 0.2, 0.8, 0.9],
                "count_line_y": 0.55,
                "alert_zone": [0.2, 0.3, 0.8, 0.9],
            },
        )
        assert response.status_code == 404
    finally:
        api_client.app.dependency_overrides.clear()


def test_hub_filters_by_point() -> None:
    """hub 按点位过滤：counselor 连接只收到名下点位消息."""
    import anyio

    from app.services.realtime.hub import ConnectionManager

    class _FakeSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send_json(self, message: dict[str, object]) -> None:
            self.sent.append(message)

    async def _scenario() -> tuple[_FakeSocket, _FakeSocket]:
        manager = ConnectionManager()
        sock_all = _FakeSocket()
        sock_counselor = _FakeSocket()
        await manager.connect(sock_all, role="super_admin")  # type: ignore[arg-type]
        await manager.connect(  # type: ignore[arg-type]
            sock_counselor, role="counselor", source_ids=["gate-east"]
        )
        sent = await manager.broadcast({"type": "stats_update"}, point_id="gate-west")
        assert sent == 1
        assert sock_all.sent != []
        assert sock_counselor.sent == []
        sent2 = await manager.broadcast({"type": "stats_update"}, point_id="gate-east")
        assert sent2 == 2
        return sock_all, sock_counselor

    anyio.run(_scenario)

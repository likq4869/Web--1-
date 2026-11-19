"""P3-1 总览 API 测试：鉴权、聚合口径、趋势、点位健康、缓存。

职责：覆盖 3 个总览端点的 RBAC 收敛、佩戴率口径（unknown 不计入分母）、
趋势序列补齐、点位在线判定与缓存命中。
依赖：FastAPI TestClient、SQLAlchemy。
边界：不测前端渲染；不测真实采集进程。
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.security import CurrentUser
from app.models.decision import Decision
from app.models.entities import Event, Heartbeat, Pass, Source
from app.models.identity import Student


def _auth_override(subject: str, role: str):  # type: ignore[no-untyped-def]
    """构造鉴权覆盖函数。"""

    def _dep() -> CurrentUser:
        return CurrentUser(subject=subject, role=role, claims={})

    return _dep


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """绑定临时库的 TestClient，并预置总览所需种子数据。"""
    db_path = tmp_path / "dashboard-api.db"
    monkeypatch.setenv("HELMET_GUARD_DB", str(db_path))
    monkeypatch.setenv("HELMET_GUARD_MODE", "demo")
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-for-production")
    # 禁用 Redis：测试走进程内缓存，避免依赖外部服务。
    monkeypatch.setenv("REDIS_URL", "")

    import app.main as main_mod

    importlib.reload(main_mod)
    from app.core.config import get_settings as _get_settings

    _get_settings.cache_clear()

    now = datetime.now(UTC).replace(tzinfo=None)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # 心跳必须新鲜（过期阈值 30s），否则按语义判定为离线。
    fresh_ts = now.isoformat()

    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        engine = client.app.state.db_engine  # type: ignore[attr-defined]
        with Session(engine, future=True) as session:
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
            for index, status in enumerate(["helmeted", "helmeted", "bare", "unknown"]):
                ts = (today + timedelta(hours=8, minutes=index)).isoformat()
                session.add(
                    Pass(
                        pass_id=f"p-{index}",
                        source_id="gate-east",
                        run_id="run-1",
                        occurred_at=ts,
                        rider_status=status,
                        model_raw="",
                        created_at=ts,
                    )
                )
            session.add(
                Event(
                    event_id="e-1",
                    pass_id="p-2",
                    source_id="gate-east",
                    run_id="run-1",
                    occurred_at=(today + timedelta(hours=8, minutes=2)).isoformat(),
                    status="pending",
                    model_label="no helmet",
                    reason="测试",
                    created_at=today.isoformat(),
                )
            )
            session.add(
                Decision(
                    decision_id="dec-1",
                    event_id="e-1",
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


def test_overview_requires_auth(api_client: TestClient) -> None:
    """未登录访问总览被拒（未认证 → 401，前端据此触发刷新/重登录）。"""
    response = api_client.get("/api/v1/admin/dashboard/overview")
    assert response.status_code == 401


def test_overview_forbidden_role_returns_404(api_client: TestClient) -> None:
    """学生角色访问总览按无资源处理（404，不泄露接口存在性）。"""
    api_client.app.dependency_overrides[get_current_user] = _auth_override("S001", "student")
    try:
        response = api_client.get("/api/v1/admin/dashboard/overview")
        assert response.status_code == 404
    finally:
        api_client.app.dependency_overrides.clear()


def test_overview_returns_expected_shape(api_client: TestClient) -> None:
    """总览返回统一包络与约定字段。"""
    api_client.app.dependency_overrides[get_current_user] = _auth_override(
        "admin1", "super_admin"
    )
    try:
        response = api_client.get("/api/v1/admin/dashboard/overview")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["message"] == ""
        data = body["data"]
        assert set(data.keys()) >= {
            "today", "trends", "pending_reviews", "points", "students",
            "comparison", "point_health",
        }
        assert data["today"]["passes"] == 4
        assert data["today"]["violations"] == 1
        # 佩戴率分母只算 helmeted+bare = 3，unknown 不计入。
        assert data["today"]["wear_rate"] == pytest.approx(66.7, abs=0.1)
        assert data["pending_reviews"] == 1
        assert data["points"]["total"] == 1
        assert data["points"]["online"] == 1
        assert len(data["trends"]["wear_rate"]) == 30
        assert len(data["trends"]["violations_by_hour"]) == 24
    finally:
        api_client.app.dependency_overrides.clear()


def test_point_health_reports_fps_and_events(api_client: TestClient) -> None:
    """点位健康返回 FPS、最近心跳与今日事件数。"""
    api_client.app.dependency_overrides[get_current_user] = _auth_override(
        "admin1", "super_admin"
    )
    try:
        response = api_client.get("/api/v1/admin/dashboard/point-health")
        assert response.status_code == 200
        items = response.json()["data"]["items"]
        assert len(items) == 1
        item = items[0]
        assert item["source_id"] == "gate-east"
        assert item["name"] == "东校门"
        assert item["status"] == "online"
        assert item["fps"] == 15.0
        assert item["today_events"] == 1
        assert item["today_passes"] == 4
    finally:
        api_client.app.dependency_overrides.clear()


def test_trends_supports_metrics(api_client: TestClient) -> None:
    """趋势接口支持佩戴率 / 违规数 / 通行数三种指标。"""
    api_client.app.dependency_overrides[get_current_user] = _auth_override(
        "admin1", "super_admin"
    )
    try:
        for metric in ("wear_rate", "violations", "passes"):
            response = api_client.get(
                "/api/v1/admin/dashboard/trends",
                params={"metric": metric, "granularity": "day", "days": 7},
            )
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["metric"] == metric
            assert len(data["points"]) == 7
        hourly = api_client.get(
            "/api/v1/admin/dashboard/trends",
            params={"metric": "violations", "granularity": "hour"},
        )
        assert hourly.status_code == 200
        assert len(hourly.json()["data"]["points"]) == 24
    finally:
        api_client.app.dependency_overrides.clear()


def test_trends_rejects_invalid_metric(api_client: TestClient) -> None:
    """非法指标返回 422。"""
    api_client.app.dependency_overrides[get_current_user] = _auth_override(
        "admin1", "super_admin"
    )
    try:
        response = api_client.get(
            "/api/v1/admin/dashboard/trends", params={"metric": "unknown"}
        )
        assert response.status_code == 422
    finally:
        api_client.app.dependency_overrides.clear()


def test_overview_cache_returns_same_payload(api_client: TestClient) -> None:
    """第二次请求命中缓存，返回相同载荷。"""
    api_client.app.dependency_overrides[get_current_user] = _auth_override(
        "admin1", "super_admin"
    )
    try:
        first = api_client.get("/api/v1/admin/dashboard/overview").json()["data"]
        second = api_client.get("/api/v1/admin/dashboard/overview").json()["data"]
        assert first["today"] == second["today"]
        assert first["point_health"] == second["point_health"]
    finally:
        api_client.app.dependency_overrides.clear()


def test_wear_rate_excludes_unknown_from_denominator() -> None:
    """佩戴率分母排除 unknown（保守原则：不把不可判定算作合规）。"""
    from app.services.dashboard.service import _wear_rate

    assert _wear_rate(3, 1) == 75.0
    assert _wear_rate(0, 0) == 0.0
    assert _wear_rate(2, 2) == 50.0

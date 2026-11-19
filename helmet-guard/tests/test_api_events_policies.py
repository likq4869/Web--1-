"""P3-3b① 事件管理与策略配置 API 测试：筛选/详情/导出/读写/模拟与 RBAC。

职责：覆盖事件列表多维筛选与白名单回退、详情证据聚合、CSV 导出、
策略读写版本递增与审计、模拟只推演不写库、越权 404。
依赖：FastAPI TestClient、SQLAlchemy。
边界：不测前端渲染。
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.security import CurrentUser, hash_password
from app.models.decision import Decision
from app.models.entities import Event, Pass

TEST_PASSWORD = "Test-Pass-2026"


def _auth_override(subject: str, role: str):  # type: ignore[no-untyped-def]
    """构造鉴权覆盖函数。"""

    def _dep() -> CurrentUser:
        return CurrentUser(subject=subject, role=role, claims={})

    return _dep


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """绑定临时库并预置事件/通行/决策与账号。"""
    project_dir = Path(__file__).resolve().parent.parent
    db_path = tmp_path / "events-policies.db"
    alembic_config = Config(str(project_dir / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(project_dir / "migrations"))
    alembic_config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(alembic_config, "head")

    monkeypatch.setenv("HELMET_GUARD_DB", str(db_path))
    monkeypatch.setenv("HELMET_GUARD_MODE", "demo")
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-for-production")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")

    import app.core.config as config_mod

    config_mod.get_settings.cache_clear()
    import app.main as main_mod

    importlib.reload(main_mod)

    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        engine = client.app.state.db_engine  # type: ignore[attr-defined]
        with Session(engine, future=True) as session:
            from app.models.identity import User

            session.add(
                User(
                    user_id="u_admin",
                    username="admin1",
                    password_hash=hash_password(TEST_PASSWORD),
                    role="super_admin",
                    status="active",
                )
            )
            session.add(
                User(
                    user_id="u_student",
                    username="stu_one",
                    password_hash=hash_password(TEST_PASSWORD),
                    role="student",
                    status="active",
                )
            )
            boxes_json = json.dumps(
                [{"label": "no helmet", "confidence": 0.93, "xyxy": [0.2, 0.1, 0.4, 0.5]}],
                ensure_ascii=False,
            )
            session.add(
                Pass(
                    pass_id="p-ev-1",
                    source_id="gate-east",
                    run_id="run-1",
                    occurred_at="2026-11-10T08:00:00",
                    rider_status="bare",
                    model_raw="no helmet",
                    boxes=boxes_json,
                    image_width=1280,
                    image_height=720,
                    created_at="2026-11-10T08:00:01",
                )
            )
            session.add(
                Pass(
                    pass_id="p-ev-2",
                    source_id="gate-west",
                    run_id="run-1",
                    occurred_at="2026-11-10T09:00:00",
                    rider_status="helmeted",
                    model_raw="helmet",
                    boxes=None,
                    image_width=None,
                    image_height=None,
                    created_at="2026-11-10T09:00:01",
                )
            )
            session.add(
                Event(
                    event_id="ev-1",
                    pass_id="p-ev-1",
                    source_id="gate-east",
                    run_id="run-1",
                    occurred_at="2026-11-10T08:00:00",
                    status="pending",
                    model_label="no helmet",
                    reason="检测到未佩戴头盔",
                    created_at="2026-11-10T08:00:02",
                )
            )
            session.add(
                Event(
                    event_id="ev-2",
                    pass_id="p-ev-2",
                    source_id="gate-west",
                    run_id="run-1",
                    occurred_at="2026-11-10T09:00:00",
                    status="confirmed",
                    model_label="helmet",
                    reason="",
                    created_at="2026-11-10T09:00:02",
                )
            )
            session.add(
                Decision(
                    decision_id="dec-ev-1",
                    event_id="ev-1",
                    student_id=None,
                    level="L1",
                    action="remind",
                    score_delta=0,
                    reason_code="FIRST_OFFENSE",
                    message="提醒",
                    confidence=0.9,
                    factors=[],
                    evidence_refs={},
                    policy_version="decision-policy-v1",
                    status="PENDING_REVIEW",
                )
            )
            session.commit()
        yield client


def _login(client: TestClient, role: str = "super_admin") -> None:
    client.app.dependency_overrides[get_current_user] = _auth_override("admin1", role)


def test_events_list_filter_and_sort_fallback(api_client: TestClient) -> None:
    """事件列表按状态筛选；非法排序回退默认仍返回总数。"""
    _login(api_client)
    try:
        resp = api_client.get("/api/v1/admin/events", params={"status": "pending"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["event_id"] == "ev-1"
        fallback = api_client.get("/api/v1/admin/events", params={"sort": "nope/drop"})
        assert fallback.status_code == 200, fallback.text
        assert fallback.json()["total"] == 2
    finally:
        api_client.app.dependency_overrides.clear()


def test_events_detail_contains_boxes_and_decision(api_client: TestClient) -> None:
    """事件详情含检测框/原图尺寸与关联决策摘要。"""
    _login(api_client)
    try:
        resp = api_client.get("/api/v1/admin/events/ev-1")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["boxes"][0]["xyxy"] == [0.2, 0.1, 0.4, 0.5]
        assert body["image_width"] == 1280
        assert body["decision_id"] == "dec-ev-1"
        assert body["decision_level"] == "L1"
    finally:
        api_client.app.dependency_overrides.clear()


def test_events_export_csv(api_client: TestClient) -> None:
    """CSV 导出含表头与两行数据。"""
    _login(api_client)
    try:
        resp = api_client.get("/api/v1/admin/events/export")
        assert resp.status_code == 200, resp.text
        text = resp.text
        assert "event_id" in text.splitlines()[0]
        assert "ev-1" in text and "ev-2" in text
    finally:
        api_client.app.dependency_overrides.clear()


def test_policies_read_update_simulate(api_client: TestClient) -> None:
    """策略读取/更新版本递增/模拟只推演。"""
    _login(api_client)
    try:
        got = api_client.get("/api/v1/admin/policies/default")
        assert got.status_code == 200, got.text
        version_before = got.json()["version"]
        assert "min_model_confidence" in got.json()["policy"]
        updated = api_client.put(
            "/api/v1/admin/policies/default",
            json={"policy": {"l2_score": -2}},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["version"] != version_before
        assert updated.json()["policy"]["l2_score"] == -2
        bad = api_client.put(
            "/api/v1/admin/policies/default",
            json={"policy": {"min_model_confidence": 5.0}},
        )
        assert bad.status_code == 422, bad.text
        sim = api_client.post(
            "/api/v1/admin/policies/default/simulate",
            json={"model_confidence": 0.9, "identity_confidence": 0.9, "limit": 1},
        )
        assert sim.status_code == 200, sim.text
        assert sim.json()["note"] == "此操作仅推演，不会真实生效"
    finally:
        api_client.app.dependency_overrides.clear()


def test_events_and_policies_student_forbidden(api_client: TestClient) -> None:
    """学生角色访问事件与策略一律 404。"""
    _login(api_client, "student")
    try:
        assert api_client.get("/api/v1/admin/events").status_code == 404
        assert api_client.get("/api/v1/admin/policies/default").status_code == 404
    finally:
        api_client.app.dependency_overrides.clear()

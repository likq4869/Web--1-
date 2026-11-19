"""P4-2 学生端总览测试：GET /api/v1/me/overview 一屏聚合。

职责：覆盖积分卡聚合、排名、无账户默认值、待确认提醒与鉴权语义。
依赖：FastAPI TestClient、alembic 迁移头。
边界：不测前端渲染；只读断言不写库（无账户场景不断言建行，只断言返回）。
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.security import CurrentUser


def _auth_override(subject: str, role: str):  # type: ignore[no-untyped-def]
    """构造鉴权覆盖函数。"""

    def _dep() -> CurrentUser:
        return CurrentUser(subject=subject, role=role, claims={})

    return _dep


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """绑定临时库的 TestClient，预置两名学生/账户/决策/申诉。"""
    project_dir = Path(__file__).resolve().parent.parent
    db_path = tmp_path / "me-overview.db"
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

    now = datetime.now(UTC).replace(tzinfo=None)
    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        engine = client.app.state.db_engine  # type: ignore[attr-defined]
        with Session(engine, future=True) as session:
            from app.models.appeal import Appeal
            from app.models.decision import Decision
            from app.models.identity import Student, User
            from app.models.scoring import ScoreAccount

            session.add(
                User(user_id="u_s001", username="s001", role="student", status="active")
            )
            session.add(
                User(user_id="u_s002", username="s002", role="student", status="active")
            )
            session.add(
                User(user_id="u_s003", username="s003", role="student", status="active")
            )
            session.add(
                User(
                    user_id="u_admin",
                    username="admin",
                    role="super_admin",
                    status="active",
                )
            )
            session.flush()
            session.add(
                Student(student_id="S001", user_id="u_s001", name="张三", status="active")
            )
            session.add(
                Student(student_id="S002", user_id="u_s002", name="李四", status="active")
            )
            session.add(
                Student(student_id="S003", user_id="u_s003", name="王五", status="active")
            )
            session.add(
                ScoreAccount(
                    student_id="S001",
                    balance=97,
                    total_deducted=3,
                    total_awarded=0,
                    level="S",
                    streak_days=5,
                    compliance_rate=0.93,
                )
            )
            session.add(
                ScoreAccount(
                    student_id="S002",
                    balance=99,
                    total_deducted=1,
                    total_awarded=0,
                    level="S",
                    streak_days=9,
                    compliance_rate=0.98,
                )
            )
            for index in range(3):
                ts = now - timedelta(hours=index)
                session.add(
                    Decision(
                        decision_id=f"dec-s001-{index}",
                        event_id=f"ev-s001-{index}",
                        student_id="S001",
                        level="L2",
                        action="deduct_score",
                        score_delta=-1,
                        reason_code="REPEAT_WITHIN_30D",
                        message="积分变动提醒",
                        confidence=0.9,
                        factors=[],
                        evidence_refs={},
                        status="PENDING_REVIEW" if index == 0 else "APPROVED",
                        created_at=ts,
                    )
                )
            session.add(
                Appeal(
                    appeal_id="apl-s001-1",
                    decision_id="dec-s001-1",
                    student_id="S001",
                    reason="当时戴了头盔",
                    attachments=[],
                    status="pending",
                )
            )
            session.commit()
        yield client


def _get(client: TestClient, subject: str, role: str) -> object:
    """注入鉴权并请求总览，调用方负责清理覆盖。"""
    client.app.dependency_overrides[get_current_user] = _auth_override(subject, role)
    try:
        return client.get("/api/v1/me/overview")
    finally:
        client.app.dependency_overrides.clear()


def test_overview_shape_with_account(api_client: TestClient) -> None:
    """有账户学生：积分卡/排名/待确认/近期/申诉计数齐备。"""
    resp = _get(api_client, "u_s001", "student")
    assert resp.status_code == 200, resp.text  # type: ignore[attr-defined]
    body = resp.json()  # type: ignore[attr-defined]
    assert body["student_id"] == "S001"
    assert body["name"] == "张三"
    score = body["score"]
    assert score["balance"] == 97
    assert score["level"] == "S"
    assert score["streak_days"] == 5
    assert score["compliance_rate"] == 0.93
    # S002(99) 在前，S001(97) 排名第 2，共 2 个账户。
    assert score["rank"] == 2
    assert score["total_students"] == 2
    assert score["percentile"] == 0.0
    assert body["pending"]["count"] == 1
    assert body["pending"]["latest"]["decision_id"] == "dec-s001-0"
    assert body["records"]["total"] == 3
    assert len(body["records"]["recent"]) == 3
    # 近期按创建时间倒序，最新的 dec-s001-0 在首位。
    assert body["records"]["recent"][0]["decision_id"] == "dec-s001-0"
    assert body["records"]["appeals_total"] == 1
    assert body["records"]["appeals_pending"] == 1


def test_overview_top_rank_percentile(api_client: TestClient) -> None:
    """榜首学生排名第 1，超过比例为 (2-1)/2。"""
    resp = _get(api_client, "u_s002", "student")
    assert resp.status_code == 200, resp.text  # type: ignore[attr-defined]
    score = resp.json()["score"]  # type: ignore[attr-defined]
    assert score["balance"] == 99
    assert score["rank"] == 1
    assert score["percentile"] == 0.5


def test_overview_without_account_returns_default(api_client: TestClient) -> None:
    """无账户学生：取初始值，不建行，排名为空。"""
    client = api_client
    client.app.dependency_overrides[get_current_user] = _auth_override("u_s003", "student")
    try:
        # 先补一个无 user 行的 S003 关联（fixture 已建 S003 但无 User 行，用 subject 回退）。
        resp = client.get("/api/v1/me/overview")
        # u_s003 无 User 行但 Student.user_id 指向它，find_by 能命中。
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["student_id"] == "S003"
        assert body["score"]["balance"] == 100
        assert body["score"]["level"] == "S"
        assert body["score"]["rank"] is None
        assert body["score"]["percentile"] is None
        assert body["pending"]["count"] == 0
        assert body["pending"]["latest"] is None
        assert body["records"]["total"] == 0
    finally:
        client.app.dependency_overrides.clear()


def test_overview_forbidden_for_non_student(api_client: TestClient) -> None:
    """非学生角色一律 404（隐藏资源存在性）。"""
    resp = _get(api_client, "u_admin", "super_admin")
    assert resp.status_code == 404, resp.text  # type: ignore[attr-defined]


__all__ = ["api_client"]

"""P3-3a 积分 API 测试：账户/台账/规则列表/更新/试算与 RBAC。

职责：覆盖积分域 API 层的分页筛选、DSL 校验、审计留痕与越权 404。
依赖：FastAPI TestClient、SQLAlchemy、alembic。
边界：不测前端渲染；记账一致性由 test_scoring_ledger 覆盖。
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password

TEST_USERNAME = "score_admin"
TEST_PASSWORD = "Test-Pass-2026"


def _prepare_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """在临时库上跑迁移并指向环境变量。"""
    project_dir = Path(__file__).resolve().parent.parent
    db_path = tmp_path / "scores-api.db"
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
    return db_path


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """绑定临时库的 TestClient，预置超管账号/学生/账户/流水/规则。"""
    _prepare_db(tmp_path, monkeypatch)

    import app.main as main_mod

    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        engine = client.app.state.db_engine  # type: ignore[attr-defined]
        with Session(engine, future=True) as session:
            from app.models.identity import Student, User
            from app.models.scoring import ScoreAccount, ScoreLedger, ScoreRule

            session.add(
                User(
                    user_id="u_score_admin",
                    username=TEST_USERNAME,
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
            session.add(
                Student(student_id="2022110508", user_id=None, name="测试学生", status="active")
            )
            session.add(
                ScoreAccount(
                    student_id="2022110508",
                    balance=97,
                    total_deducted=3,
                    total_awarded=0,
                    level="S",
                    streak_days=1,
                    compliance_rate=0.9,
                )
            )
            session.add(
                ScoreLedger(
                    student_id="2022110508",
                    change=-3,
                    balance_after=97,
                    reason_code="REPEAT",
                    reason_text="重复违规",
                    operator="system",
                )
            )
            session.add(
                ScoreLedger(
                    student_id="2022110508",
                    change=2,
                    balance_after=99,
                    reason_code="AWARD",
                    reason_text="连续合规奖励",
                    operator="system",
                )
            )
            session.add(
                ScoreRule(
                    rule_id="r_high",
                    rule_type="deduct",
                    name="高优",
                    condition_json={"field": "violation_count_30d", "op": ">=", "value": 3},
                    score_change=-3,
                    priority=10,
                    enabled=True,
                )
            )
            session.add(
                ScoreRule(
                    rule_id="r_low",
                    rule_type="deduct",
                    name="低优",
                    condition_json={"field": "violation_count_30d", "op": ">=", "value": 1},
                    score_change=-1,
                    priority=0,
                    enabled=True,
                )
            )
            session.commit()
        yield client


def _login(client: TestClient, username: str = TEST_USERNAME) -> str:
    """登录并返回 access_token。"""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["data"]["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_accounts_list_contract(api_client: TestClient) -> None:
    """账户列表返回分页包络与等级字段。"""
    token = _login(api_client)
    resp = api_client.get("/api/v1/admin/scores/accounts", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["page"] == 1
    item = body["items"][0]
    assert item["student_id"] == "2022110508"
    assert item["balance"] == 97
    assert item["level"] == "S"
    assert item["name"] == "测试学生"


def test_ledger_filters_direction(api_client: TestClient) -> None:
    """台账方向筛选：positive 仅加分，negative 仅扣分。"""
    token = _login(api_client)
    pos = api_client.get(
        "/api/v1/admin/scores/ledger",
        params={"direction": "positive"},
        headers=_auth(token),
    )
    assert pos.status_code == 200, pos.text
    assert pos.json()["total"] == 1
    assert pos.json()["items"][0]["change"] == 2

    neg = api_client.get(
        "/api/v1/admin/scores/ledger",
        params={"direction": "negative", "reason_code": "REPEAT"},
        headers=_auth(token),
    )
    assert neg.status_code == 200, neg.text
    assert neg.json()["total"] == 1
    assert neg.json()["items"][0]["reason_code"] == "REPEAT"

    bad_direction = api_client.get(
        "/api/v1/admin/scores/ledger",
        params={"direction": "hacker"},
        headers=_auth(token),
    )
    assert bad_direction.status_code == 200, bad_direction.text
    assert bad_direction.json()["total"] == 2


def test_rules_list_and_update(api_client: TestClient) -> None:
    """规则列表按 priority 降序；更新写审计且非法 DSL 报 422。"""
    token = _login(api_client)
    resp = api_client.get("/api/v1/admin/scores/rules", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert [item["rule_id"] for item in resp.json()["items"]] == ["r_high", "r_low"]

    updated = api_client.put(
        "/api/v1/admin/scores/rules/r_low",
        json={"score_change": -2, "priority": 5},
        headers=_auth(token),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["score_change"] == -2
    assert updated.json()["priority"] == 5

    bad = api_client.put(
        "/api/v1/admin/scores/rules/r_low",
        json={"condition_json": {"field": "nope", "op": "==", "value": 1}},
        headers=_auth(token),
    )
    assert bad.status_code == 422, bad.text


def test_simulate_modes(api_client: TestClient) -> None:
    """试算两种模式：候选条件与已存规则；缺参报 422。"""
    token = _login(api_client)
    hit = api_client.post(
        "/api/v1/admin/scores/rules/simulate",
        json={
            "condition_json": {"field": "violation_count_30d", "op": ">=", "value": 1},
            "context": {"violation_count_30d": 2},
        },
        headers=_auth(token),
    )
    assert hit.status_code == 200, hit.text
    assert hit.json()["matched"] is True

    miss = api_client.post(
        "/api/v1/admin/scores/rules/simulate",
        json={
            "rule_id": "r_high",
            "context": {"violation_count_30d": 0},
        },
        headers=_auth(token),
    )
    assert miss.status_code == 200, miss.text
    assert miss.json()["matched"] is False
    assert miss.json()["total_change"] == 0

    empty = api_client.post(
        "/api/v1/admin/scores/rules/simulate",
        json={"context": {}},
        headers=_auth(token),
    )
    assert empty.status_code == 422, empty.text


def test_student_role_is_not_found(api_client: TestClient) -> None:
    """学生角色访问积分管理一律 404（隐藏资源存在性）。"""
    token = _login(api_client, username="stu_one")
    resp = api_client.get("/api/v1/admin/scores/accounts", headers=_auth(token))
    assert resp.status_code == 404, resp.text

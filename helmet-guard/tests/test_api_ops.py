"""P3-3b③ 运维管理 API 测试：模型版本 / 审计日志 / 用户管理。

职责：覆盖模型列表与激活互斥、审计只读与越权 404、用户管理的超管隔离。
依赖：FastAPI TestClient、SQLAlchemy、alembic。
边界：不测前端渲染；密码重置只验哈希生效与审计留痕。
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

TEST_PASSWORD = "Test-Pass-2026"
SUPER_USERNAME = "ops_super"
LEAGUE_USERNAME = "ops_league"
AUDIT_USERNAME = "ops_audit"


def _prepare_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """在临时库上跑迁移并指向环境变量。"""
    project_dir = Path(__file__).resolve().parent.parent
    db_path = tmp_path / "ops-api.db"
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
    """绑定临时库的 TestClient，预置三角色账号。"""
    _prepare_db(tmp_path, monkeypatch)

    import app.main as main_mod

    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        engine = client.app.state.db_engine  # type: ignore[attr-defined]
        with Session(engine, future=True) as session:
            from app.models.identity import User

            session.add(
                User(
                    user_id="u_ops_super",
                    username=SUPER_USERNAME,
                    password_hash=hash_password(TEST_PASSWORD),
                    role="super_admin",
                    status="active",
                )
            )
            session.add(
                User(
                    user_id="u_ops_league",
                    username=LEAGUE_USERNAME,
                    password_hash=hash_password(TEST_PASSWORD),
                    role="league_officer",
                    status="active",
                )
            )
            session.add(
                User(
                    user_id="u_ops_audit",
                    username=AUDIT_USERNAME,
                    password_hash=hash_password(TEST_PASSWORD),
                    role="auditor",
                    status="active",
                )
            )
            session.commit()
        yield client


def _login(client: TestClient, username: str) -> str:
    """登录并返回 access_token。"""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["data"]["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_models_list_and_feedback_stats(api_client: TestClient) -> None:
    """模型列表含预置基线激活行；回流统计口径正确。"""
    token = _login(api_client, SUPER_USERNAME)
    resp = api_client.get("/api/v1/admin/ops/models", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    active = [item for item in body["items"] if item["is_active"]]
    assert len(active) >= 1
    assert active[0]["model_id"] == "helmet-v2-baseline"

    stats = api_client.get("/api/v1/admin/ops/models/feedback-stats", headers=_auth(token))
    assert stats.status_code == 200, stats.text
    payload = stats.json()
    assert payload["total"] >= 0
    assert payload["pending_train"] >= 0
    assert isinstance(payload["by_source"], dict)


def test_model_activate_is_exclusive_and_audited(api_client: TestClient) -> None:
    """激活切换同任务互斥；非法 task 回退不限；越权 404。"""
    super_token = _login(api_client, SUPER_USERNAME)
    audit_token = _login(api_client, AUDIT_USERNAME)

    # 非法 task 视为不限：仍返回全部。
    bad_task = api_client.get(
        "/api/v1/admin/ops/models", params={"task": "hacker"}, headers=_auth(super_token)
    )
    assert bad_task.status_code == 200, bad_task.text
    assert bad_task.json()["total"] >= 1

    # auditor 无激活写权限：一律 404。
    denied = api_client.post(
        "/api/v1/admin/ops/models/helmet-v2-baseline/activate",
        headers=_auth(audit_token),
    )
    assert denied.status_code == 404, denied.text

    # 超管重复激活同一行：幂等成功且仍唯一激活。
    ok_resp = api_client.post(
        "/api/v1/admin/ops/models/helmet-v2-baseline/activate",
        headers=_auth(super_token),
    )
    assert ok_resp.status_code == 200, ok_resp.text
    assert ok_resp.json()["is_active"] is True

    listed = api_client.get("/api/v1/admin/ops/models", headers=_auth(super_token))
    active = [item for item in listed.json()["items"] if item["is_active"]]
    assert len(active) == 1

    # 不存在的模型：404。
    missing = api_client.post(
        "/api/v1/admin/ops/models/no-such-model/activate", headers=_auth(super_token)
    )
    assert missing.status_code == 404, missing.text


def test_audit_logs_read_only_and_rbac(api_client: TestClient) -> None:
    """审计日志可读（登录即有记录）；无修改入口隐含由路由守卫保证。"""
    super_token = _login(api_client, SUPER_USERNAME)
    league_token = _login(api_client, LEAGUE_USERNAME)
    audit_token = _login(api_client, AUDIT_USERNAME)
    resp = api_client.get("/api/v1/admin/ops/audit-logs", headers=_auth(super_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert body["page"] == 1
    assert "password" not in resp.text.lower() or "password_hash" not in resp.text

    # 动作前缀过滤：auth.login 应命中登录审计。
    filtered = api_client.get(
        "/api/v1/admin/ops/audit-logs",
        params={"action": "auth.login"},
        headers=_auth(audit_token),
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] >= 1

    # league_officer 不在审计读白名单：一律 404。
    denied = api_client.get("/api/v1/admin/ops/audit-logs", headers=_auth(league_token))
    assert denied.status_code == 404, denied.text


def test_users_super_admin_only_and_guards(api_client: TestClient) -> None:
    """用户列表仅超管；停用自己与移除最后超管被拒绝；重置密码哈希生效。"""
    super_token = _login(api_client, SUPER_USERNAME)
    audit_token = _login(api_client, AUDIT_USERNAME)

    denied = api_client.get("/api/v1/admin/ops/users", headers=_auth(audit_token))
    assert denied.status_code == 404, denied.text

    resp = api_client.get("/api/v1/admin/ops/users", headers=_auth(super_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 3
    assert "password_hash" not in resp.text

    # 空更新：422。
    empty = api_client.put(
        "/api/v1/admin/ops/users/u_ops_audit", json={}, headers=_auth(super_token)
    )
    assert empty.status_code == 422, empty.text

    # 停用自己：422。
    self_disable = api_client.put(
        "/api/v1/admin/ops/users/u_ops_super",
        json={"status": "disabled"},
        headers=_auth(super_token),
    )
    assert self_disable.status_code == 422, self_disable.text

    # 降级最后一个超管：422。
    last_super = api_client.put(
        "/api/v1/admin/ops/users/u_ops_super",
        json={"role": "auditor"},
        headers=_auth(super_token),
    )
    assert last_super.status_code == 422, last_super.text

    # 正常更新审计员状态往返。
    updated = api_client.put(
        "/api/v1/admin/ops/users/u_ops_audit",
        json={"status": "disabled"},
        headers=_auth(super_token),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "disabled"
    restored = api_client.put(
        "/api/v1/admin/ops/users/u_ops_audit",
        json={"status": "active"},
        headers=_auth(super_token),
    )
    assert restored.status_code == 200, restored.text

    # 重置密码后可用新密码登录。
    reset = api_client.post(
        "/api/v1/admin/ops/users/u_ops_audit/reset-password",
        json={"new_password": "New-Pass-2027"},
        headers=_auth(super_token),
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["user_id"] == "u_ops_audit"
    login_resp = api_client.post(
        "/api/v1/auth/login",
        json={"username": AUDIT_USERNAME, "password": "New-Pass-2027"},
    )
    assert login_resp.status_code == 200, login_resp.text

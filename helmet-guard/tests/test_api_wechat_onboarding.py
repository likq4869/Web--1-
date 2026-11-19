"""P4-1 微信快捷登录四步链路测试：wechat-login/bind-phone/profile + org 级联。

职责：覆盖 Mock 模式（未配置 AppID/Secret，不出网）全链路与越权语义。
依赖：FastAPI TestClient、alembic 迁移头。
边界：不测真实微信接口；真机联调由人工验收覆盖。

链路：wx.login code → openid 幂等建号 → 手机号绑定 → 学籍 upsert。
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient


def _prepare_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """临时库跑迁移并指向环境变量（Mock 模式：不设 WECHAT_*）。"""
    project_dir = Path(__file__).resolve().parent.parent
    db_path = tmp_path / "wechat-onboarding.db"
    alembic_config = Config(str(project_dir / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(project_dir / "migrations"))
    alembic_config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(alembic_config, "head")

    monkeypatch.setenv("HELMET_GUARD_DB", str(db_path))
    monkeypatch.setenv("HELMET_GUARD_MODE", "demo")
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-for-production")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    # Settings 会读 helmet-guard/.env（本地已配真 AppID）；测试必须显式置空
    # 才能进 Mock（delenv 删不掉 .env 文件里的值，只置空才会被判定为 Mock）。
    monkeypatch.setenv("WECHAT_APPID", "")
    monkeypatch.setenv("WECHAT_SECRET", "")

    import app.core.config as config_mod

    config_mod.get_settings.cache_clear()
    import app.main as main_mod

    importlib.reload(main_mod)


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """绑定临时库的 TestClient（Mock 微信模式）。"""
    _prepare_db(tmp_path, monkeypatch)
    import app.main as main_mod

    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        yield client


def _wechat_login(client: TestClient, code: str = "test-code-001") -> dict[str, object]:
    """执行一次微信登录，返回 data（含双令牌）。"""
    resp = client.post("/api/v1/auth/wechat-login", json={"code": code})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["code"] == 0
    data = payload["data"]
    assert isinstance(data, dict)
    return data


def _auth_header(token: object) -> dict[str, str]:
    assert isinstance(token, str)
    return {"Authorization": f"Bearer {token}"}


def test_wechat_login_is_idempotent_by_code(api_client: TestClient) -> None:
    """同一 code 两次登录落到同一账号（openid 确定性派生，幂等）。"""
    first = _wechat_login(api_client)
    second = _wechat_login(api_client)
    assert first["user"]["id"] == second["user"]["id"]  # type: ignore[index]


def test_wechat_login_persists_session_key(api_client: TestClient) -> None:
    """Mock 登录落库 session_key（checkSessionKey 自检的前置条件）。"""
    from sqlalchemy.orm import Session

    from app.models.identity import User

    data = _wechat_login(api_client, code="session-key-001")
    user_id = data["user"]["id"]
    assert isinstance(user_id, str)
    engine = api_client.app.state.db_engine  # type: ignore[attr-defined]
    with Session(engine, future=True) as session:
        user = session.get(User, user_id)
        assert user is not None
        assert user.wechat_session_key == "mock-session"

    # 再次登录顶替旧值仍为 mock-session（覆盖写不断言旧值残留）。
    _wechat_login(api_client, code="session-key-001")
    with Session(engine, future=True) as session:
        user = session.get(User, user_id)
        assert user is not None
        assert user.wechat_session_key == "mock-session"


def test_check_session_mock_returns_valid(api_client: TestClient) -> None:
    """Mock 模式 check-session 固定有效（不出网，便于联调断言）。"""
    data = _wechat_login(api_client, code="check-session-001")
    headers = _auth_header(data["access_token"])
    resp = api_client.get("/api/v1/auth/check-session", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body == {"wechat_valid": True, "mock": True}


def test_check_session_requires_auth(api_client: TestClient) -> None:
    """未携带令牌调 check-session 一律 401（与 /me 语义一致）。"""
    assert api_client.get("/api/v1/auth/check-session").status_code == 401


def test_wechat_login_rejects_empty_code(api_client: TestClient) -> None:
    """空 code 被参数校验拒绝（422），不进 Mock 派生。"""
    resp = api_client.post("/api/v1/auth/wechat-login", json={"code": ""})
    assert resp.status_code == 422


def test_full_onboarding_chain(api_client: TestClient) -> None:
    """全链路：微信登录 → 绑手机号（Mock 直传）→ 学籍 upsert → 进度查询。"""
    data = _wechat_login(api_client, code="onboard-001")
    headers = _auth_header(data["access_token"])

    # 1. 初始档案：无手机、无学籍。
    resp = api_client.get("/api/v1/auth/profile", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["has_phone"] is False
    assert resp.json()["data"]["has_profile"] is False

    # 2. 绑手机号（Mock 直传 phone）。
    resp = api_client.post(
        "/api/v1/auth/bind-phone", json={"phone": "13800001111"}, headers=headers
    )
    assert resp.status_code == 200, resp.text

    # 3. 非法手机号被拒绝（422）。
    bad = api_client.post(
        "/api/v1/auth/bind-phone", json={"phone": "123"}, headers=headers
    )
    assert bad.status_code == 422

    # 4. 学籍补全（upsert 新建）。
    profile = {
        "school": "示范大学",
        "college": "计算机学院",
        "grade": "2024 级",
        "major": "软件工程",
        "class_name": "计科 2401",
        "student_id": "20240001",
        "name": "陈晓",
    }
    resp = api_client.post("/api/v1/auth/profile", json=profile, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["student"]["has_profile"] is True

    # 5. 进度查询：手机与学籍均已就绪。
    resp = api_client.get("/api/v1/auth/profile", headers=headers)
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["has_phone"] is True
    assert body["has_profile"] is True
    assert body["phone"] == "13800001111"
    assert body["student_id"] == "20240001"


def test_org_units_empty_without_seed(api_client: TestClient) -> None:
    """空库时级联返回空列表（前端降级为手动填写，不 404）。"""
    data = _wechat_login(api_client, code="org-empty-001")
    headers = _auth_header(data["access_token"])
    resp = api_client.get("/api/v1/org/units", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []

    # 未携带令牌一律 401（与 /me 语义一致）。
    assert api_client.get("/api/v1/org/units").status_code == 401


def test_org_units_cascade_with_seed(api_client: TestClient) -> None:
    """写入一级学校 + 二级学院后，逐级级联可查（parent_id 透传）。"""
    engine = api_client.app.state.db_engine  # type: ignore[attr-defined]
    from sqlalchemy.orm import Session

    from app.models.identity import OrgUnit

    with Session(engine, future=True) as session:
        session.add(
            OrgUnit(
                unit_id="org-school-demo",
                unit_type="school",  # type: ignore[arg-type]
                name="示范大学",
                parent_id=None,
                sort_order=1,
                status="active",
            )
        )
        session.add(
            OrgUnit(
                unit_id="org-college-cs",
                unit_type="college",  # type: ignore[arg-type]
                name="计算机学院",
                parent_id="org-school-demo",
                sort_order=1,
                status="active",
            )
        )
        session.commit()

    data = _wechat_login(api_client, code="org-seed-001")
    headers = _auth_header(data["access_token"])

    top = api_client.get("/api/v1/org/units", headers=headers)
    assert top.status_code == 200
    assert [i["unit_id"] for i in top.json()["data"]["items"]] == ["org-school-demo"]

    children = api_client.get(
        "/api/v1/org/units", params={"parent_id": "org-school-demo"}, headers=headers
    )
    assert children.status_code == 200
    assert [i["name"] for i in children.json()["data"]["items"]] == ["计算机学院"]

    typed = api_client.get(
        "/api/v1/org/units",
        params={"parent_id": "org-school-demo", "unit_type": "college"},
        headers=headers,
    )
    assert typed.status_code == 200
    assert len(typed.json()["data"]["items"]) == 1


__all__ = ["api_client"]

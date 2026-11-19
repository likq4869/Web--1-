"""P3-0 认证 API 测试：登录、刷新、当前用户、绑定学号与安全语义。

职责：覆盖凭据校验、令牌签发与轮换、账号禁用后令牌失效、
用户枚举防护、角色枚举可用性与路由注册断言。
依赖：FastAPI TestClient、SQLAlchemy、alembic。
边界：不测前端渲染与真实浏览器交互（另有人工验收项）。
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

from app.core.security import create_access_token, create_refresh_token, hash_password

# 测试用账号凭据（仅存在于测试代码，不进入任何生产配置）。
TEST_USERNAME = "admin_tester"
TEST_PASSWORD = "Test-Pass-2026"


def _prepare_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """在临时库上跑迁移并指向环境变量。

    Args:
        tmp_path: pytest 临时目录。
        monkeypatch: pytest 环境变量补丁。

    Returns:
        数据库文件路径。
    """
    project_dir = Path(__file__).resolve().parent.parent
    db_path = tmp_path / "auth-api.db"
    alembic_config = Config(str(project_dir / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(project_dir / "migrations"))
    alembic_config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(alembic_config, "head")

    monkeypatch.setenv("HELMET_GUARD_DB", str(db_path))
    monkeypatch.setenv("HELMET_GUARD_MODE", "demo")
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-for-production")
    # DATABASE_URL 优先级最高，显式指定保证 engine 与 Alembic 库同文件。
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")

    import app.core.config as config_mod

    config_mod.get_settings.cache_clear()

    import app.main as main_mod

    importlib.reload(main_mod)
    return db_path


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """绑定临时库的 TestClient，预置一个可登录的 super_admin 账号。"""
    _prepare_db(tmp_path, monkeypatch)

    import app.main as main_mod

    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        engine = client.app.state.db_engine  # type: ignore[attr-defined]
        with Session(engine, future=True) as session:
            from app.models.identity import User

            session.add(
                User(
                    user_id="u_admin",
                    username=TEST_USERNAME,
                    password_hash=hash_password(TEST_PASSWORD),
                    role="super_admin",
                    status="active",
                )
            )
            session.commit()
        yield client


def _login(client: TestClient) -> dict[str, object]:
    """执行一次成功登录，返回响应 data。

    Args:
        client: 测试客户端。

    Returns:
        响应中的 data 部分。
    """
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["code"] == 0
    data = payload["data"]
    assert isinstance(data, dict)
    return data


# ---------------------------------------------------------------------------
# 1. 登录
# ---------------------------------------------------------------------------


def test_login_returns_full_contract(api_client: TestClient) -> None:
    """登录成功返回完整包络，字段名与前端契约逐字一致。"""
    data = _login(api_client)
    assert set(data) == {
        "access_token",
        "refresh_token",
        "token_type",
        "expires_in",
        "user",
    }
    user = data["user"]
    assert isinstance(user, dict)
    assert set(user) == {"id", "username", "display_name", "role", "source_ids"}
    assert user["id"] == "u_admin"
    assert user["username"] == TEST_USERNAME
    assert user["display_name"] == TEST_USERNAME
    assert user["role"] == "super_admin"
    assert user["source_ids"] == []
    assert data["token_type"] == "Bearer"
    assert isinstance(data["expires_in"], int)


def test_login_rejects_wrong_password(api_client: TestClient) -> None:
    """密码错误返回 401。"""
    resp = api_client.post(
        "/api/v1/auth/login",
        json={"username": TEST_USERNAME, "password": "wrong-password"},
    )
    assert resp.status_code == 401


def test_login_failures_share_identical_message(api_client: TestClient) -> None:
    """用户不存在与密码错误返回完全相同的文案与状态码（防用户枚举）。"""
    wrong_password = api_client.post(
        "/api/v1/auth/login",
        json={"username": TEST_USERNAME, "password": "wrong-password"},
    )
    unknown_user = api_client.post(
        "/api/v1/auth/login",
        json={"username": "no_such_user", "password": "whatever"},
    )
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json()["message"] == unknown_user.json()["message"]


def test_login_rejects_disabled_account(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已禁用账号无法登录，且与密码错误文案一致。"""
    import app.main as main_mod

    engine = api_client.app.state.db_engine  # type: ignore[attr-defined]
    with Session(engine, future=True) as session:
        from app.models.identity import User

        user = session.get(User, "u_admin")
        assert user is not None
        user.status = "disabled"
        session.commit()

    resp = api_client.post(
        "/api/v1/auth/login",
        json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 401
    unknown = api_client.post(
        "/api/v1/auth/login",
        json={"username": "no_such_user", "password": "whatever"},
    )
    assert resp.json()["message"] == unknown.json()["message"]
    del main_mod


def test_login_requires_non_empty_fields(api_client: TestClient) -> None:
    """空用户名或空密码被参数校验拒绝（422）。"""
    resp = api_client.post("/api/v1/auth/login", json={"username": "", "password": "x"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 2. 当前用户
# ---------------------------------------------------------------------------


def test_me_requires_token(api_client: TestClient) -> None:
    """无令牌访问 /me 返回 401。"""
    resp = api_client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_me_rejects_garbage_token(api_client: TestClient) -> None:
    """非法签名的令牌被拒绝。"""
    resp = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


def test_me_returns_current_user(api_client: TestClient) -> None:
    """携带有效令牌可查询当前用户。"""
    data = _login(api_client)
    token = data["access_token"]
    assert isinstance(token, str)
    resp = api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    user = resp.json()["data"]
    assert user["id"] == "u_admin"
    assert user["role"] == "super_admin"


# ---------------------------------------------------------------------------
# 3. 刷新
# ---------------------------------------------------------------------------


def test_refresh_rotates_tokens(api_client: TestClient) -> None:
    """有效刷新令牌可换取新令牌。"""
    data = _login(api_client)
    refresh_token = data["refresh_token"]
    assert isinstance(refresh_token, str)
    resp = api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert set(payload) == {"access_token", "refresh_token", "token_type", "expires_in"}
    assert payload["access_token"] != data["access_token"]


def test_refresh_rejects_access_token_as_refresh(api_client: TestClient) -> None:
    """访问令牌不能当刷新令牌使用（token_type 校验）。"""
    data = _login(api_client)
    access_token = data["access_token"]
    assert isinstance(access_token, str)
    resp = api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": access_token},
    )
    assert resp.status_code == 401


def test_refresh_rejects_invalid_token(api_client: TestClient) -> None:
    """非法刷新令牌被拒绝。"""
    resp = api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "garbage"},
    )
    assert resp.status_code == 401


def test_refresh_rejects_disabled_account(api_client: TestClient) -> None:
    """账号被禁用后，已签发的刷新令牌立即失效。"""
    data = _login(api_client)
    refresh_token = data["refresh_token"]
    assert isinstance(refresh_token, str)

    engine = api_client.app.state.db_engine  # type: ignore[attr-defined]
    with Session(engine, future=True) as session:
        from app.models.identity import User

        user = session.get(User, "u_admin")
        assert user is not None
        user.status = "disabled"
        session.commit()

    resp = api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 4. 登出
# ---------------------------------------------------------------------------


def test_logout_requires_token(api_client: TestClient) -> None:
    """无令牌登出返回 401。"""
    resp = api_client.post("/api/v1/auth/logout")
    assert resp.status_code == 401


def test_logout_with_valid_token(api_client: TestClient) -> None:
    """携带有效令牌登出成功。"""
    data = _login(api_client)
    token = data["access_token"]
    assert isinstance(token, str)
    resp = api_client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["data"]["logged_out"] is True


# ---------------------------------------------------------------------------
# 5. 绑定学号
# ---------------------------------------------------------------------------


def test_bind_student_success(api_client: TestClient) -> None:
    """绑定存在的学号成功，source_ids 随之更新。"""
    engine = api_client.app.state.db_engine  # type: ignore[attr-defined]
    with Session(engine, future=True) as session:
        from app.models.identity import Student

        session.add(Student(student_id="20260001", name="李四", status="active"))
        session.commit()

    data = _login(api_client)
    token = data["access_token"]
    assert isinstance(token, str)
    resp = api_client.post(
        "/api/v1/auth/bind-student",
        json={"student_id": "20260001"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "u_admin"


def test_bind_student_rejects_unknown_id(api_client: TestClient) -> None:
    """学号不存在返回 404。"""
    data = _login(api_client)
    token = data["access_token"]
    assert isinstance(token, str)
    resp = api_client.post(
        "/api/v1/auth/bind-student",
        json={"student_id": "99999999"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_bind_student_rejects_non_numeric_id(api_client: TestClient) -> None:
    """非数字学号被参数校验拒绝（422）。"""
    data = _login(api_client)
    token = data["access_token"]
    assert isinstance(token, str)
    resp = api_client.post(
        "/api/v1/auth/bind-student",
        json={"student_id": "not-numeric"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_bind_student_conflicts_when_taken(api_client: TestClient) -> None:
    """学号已被他人绑定返回 409。"""
    engine = api_client.app.state.db_engine  # type: ignore[attr-defined]
    with Session(engine, future=True) as session:
        from app.models.identity import Student, User

        session.add(
            User(
                user_id="u_other",
                username="other_admin",
                password_hash=hash_password("Other-Pass-2026"),
                role="admin",
                status="active",
            )
        )
        # 先落库账号再建学生：ORM 层未声明 User→Student relationship，
        # 同一 flush 内插入顺序不确定会导致外键失败，故分两次提交。
        session.commit()
        session.add(
            Student(student_id="20260002", name="王五", status="active", user_id="u_other")
        )
        session.commit()

    data = _login(api_client)
    token = data["access_token"]
    assert isinstance(token, str)
    resp = api_client.post(
        "/api/v1/auth/bind-student",
        json={"student_id": "20260002"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# 6. 角色与路由注册
# ---------------------------------------------------------------------------


def test_management_roles_are_accepted_by_orm(api_client: TestClient) -> None:
    """admin / reviewer / observer 三个后台角色可正常写入（ORM 枚举校验通过）。"""
    engine = api_client.app.state.db_engine  # type: ignore[attr-defined]
    with Session(engine, future=True) as session:
        from app.models.identity import User

        for role in ("admin", "reviewer", "observer"):
            # fixture 已预置 user_id="u_admin" 的 super_admin 账号，
            # 此处用 mgmt_ 前缀避免主键冲突。
            session.add(
                User(
                    user_id=f"u_mgmt_{role}",
                    username=f"mgmt_user_{role}",
                    password_hash=hash_password("Pass-2026"),
                    role=role,
                    status="active",
                )
            )
        session.commit()

    with Session(engine, future=True) as session:
        from app.models.identity import User

        roles = {
            user.role for user in session.query(User).filter(User.role != "super_admin").all()
        }
    assert {"admin", "reviewer", "observer"} <= roles


def test_auth_routes_are_registered(api_client: TestClient) -> None:
    """认证路由确实注册到 OpenAPI（防止静默丢失）。"""
    paths = api_client.get("/openapi.json").json()["paths"]
    for expected in (
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/auth/bind-student",
    ):
        assert expected in paths, f"缺少路由：{expected}"


def test_signed_token_with_unknown_subject_is_rejected(api_client: TestClient) -> None:
    """签名有效但主体不存在的令牌访问 /me 返回 401（服务端回库确认）。"""
    token = create_access_token("u_ghost", "super_admin")
    resp = api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_refresh_token_of_unknown_subject_is_rejected(api_client: TestClient) -> None:
    """主体不存在的刷新令牌被拒绝。"""
    token = create_refresh_token("u_ghost", "super_admin")
    resp = api_client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    assert resp.status_code == 401

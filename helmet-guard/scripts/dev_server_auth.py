"""本地联调启动器：以固定管理员身份启动后端，便于前端端到端验证。

用途：P3 认证 API（`/api/v1/auth/*`）尚未实现，前端无法通过真实登录
拿到令牌。此脚本用与既有测试一致的 `dependency_overrides` 手法注入固定
super_admin，并附加两个仅联调用的最小认证路由，使前端能建立会话。

边界：
- 只在开发期手动运行，不参与生产启动流程；
- 不写业务库，不改配置，不触碰任何密钥；
- 认证依赖被完全覆盖，路由只返回固定主体信息。
"""

from __future__ import annotations

import os

os.environ.setdefault("HELMET_GUARD_DB", "data/helmet_demo.db")
os.environ.setdefault("HELMET_GUARD_MODE", "demo")
os.environ.setdefault("JWT_SECRET", "local-dev-only-not-production")

from fastapi import APIRouter  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.core.deps import get_current_user  # noqa: E402
from app.core.security import CurrentUser  # noqa: E402

DEV_USER_ID = "dev-admin"
DEV_USERNAME = "dev-admin"
DEV_ROLE = "super_admin"


def _fake_current_user() -> CurrentUser:
    """返回固定的 super_admin 主体。"""
    return CurrentUser(subject=DEV_USER_ID, role=DEV_ROLE, claims={})


class _LoginBody(BaseModel):
    """登录请求体（字段被忽略，仅保持前端契约）。"""

    username: str = ""
    password: str = ""


def _dev_user_payload() -> dict[str, object]:
    """返回与前端 `CurrentUser` 契约一致的主体载荷。"""
    return {
        "id": 1,
        "username": DEV_USERNAME,
        "display_name": "联调管理员",
        "role": DEV_ROLE,
        "source_ids": [],
    }


def _install_dev_auth_routes(app: object) -> None:
    """附加联调用的最小认证路由。

    Args:
        app: FastAPI 应用实例。
    """
    router = APIRouter(prefix="/api/v1/auth", tags=["auth-dev"])

    @router.post("/login")
    def dev_login(body: _LoginBody) -> dict[str, object]:
        """联调登录：返回固定主体与占位令牌。"""
        del body
        return {
            "code": 0,
            "data": {
                "access_token": "dev-access-token",
                "refresh_token": "dev-refresh-token",
                "token_type": "bearer",
                "expires_in": 7200,
                "user": _dev_user_payload(),
            },
            "message": "",
        }

    @router.get("/me")
    def dev_me() -> dict[str, object]:
        """联调获取当前主体。"""
        return {"code": 0, "data": _dev_user_payload(), "message": ""}

    @router.post("/refresh")
    def dev_refresh() -> dict[str, object]:
        """联调刷新令牌：返回同一组占位令牌。"""
        return {
            "code": 0,
            "data": {
                "access_token": "dev-access-token",
                "refresh_token": "dev-refresh-token",
                "token_type": "bearer",
                "expires_in": 7200,
            },
            "message": "",
        }

    @router.post("/logout")
    def dev_logout() -> dict[str, object]:
        """联调登出。"""
        return {"code": 0, "data": None, "message": ""}

    app.include_router(router)  # type: ignore[attr-defined]


def main() -> None:
    """启动联调用后端。"""
    import app.main as main_mod

    main_mod.app.dependency_overrides[get_current_user] = _fake_current_user
    _install_dev_auth_routes(main_mod.app)
    import uvicorn

    uvicorn.run(main_mod.app, host="127.0.0.1", port=8100, log_level="warning")


if __name__ == "__main__":
    main()

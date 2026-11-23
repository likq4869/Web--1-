"""OpenAPI 元信息测试：分组标签、鉴权标注与中文摘要。

覆盖 `app.core.openapi_meta` 的三个关键契约：
1. 每个路由模块的 tag 都能在 API_TAGS 中找到分组说明（否则文档分组失效）；
2. 公开接口不带 `security`，其余接口标注 Bearer 鉴权；
3. 接口摘要取中文描述首句，而非 FastAPI 自动生成的英文函数名。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.openapi_meta import (
    API_TAGS,
    PUBLIC_ENDPOINTS,
    build_openapi,
    install_openapi,
)
from app.main import app


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    """生成 OpenAPI 规格（模块级复用，避免重复构造）。"""
    return build_openapi(app)


def test_api_tags_cover_all_route_tags(schema: dict[str, Any]) -> None:
    """所有路由用到的 tag 都有分组说明文案。"""
    declared = {tag["name"] for tag in API_TAGS}
    used: set[str] = set()
    for operations in schema["paths"].values():
        for operation in operations.values():
            used.update(operation.get("tags") or [])
    assert used, "规格中应至少包含一个带 tag 的接口"
    assert used <= declared, f"缺少分组说明的 tag: {sorted(used - declared)}"


def test_security_scheme_registered(schema: dict[str, Any]) -> None:
    """Bearer 鉴权方案已注册到 components。"""
    schemes = schema["components"]["securitySchemes"]
    assert "HTTPBearer" in schemes
    assert schemes["HTTPBearer"]["scheme"] == "bearer"
    assert schemes["HTTPBearer"]["bearerFormat"] == "JWT"


@pytest.mark.parametrize(("path", "method"), sorted(PUBLIC_ENDPOINTS))
def test_public_endpoints_have_no_security(
    schema: dict[str, Any], path: str, method: str
) -> None:
    """公开接口不要求携带令牌。"""
    operation = schema["paths"][path][method]
    assert "security" not in operation


def test_protected_endpoints_require_bearer(schema: dict[str, Any]) -> None:
    """非公开接口都标注了 Bearer 鉴权。"""
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if (path, method) in PUBLIC_ENDPOINTS:
                continue
            assert operation.get("security") == [{"HTTPBearer": []}], f"{method.upper()} {path}"


def test_summaries_are_chinese_not_function_names(schema: dict[str, Any]) -> None:
    """接口摘要是中文描述首句，而非英文函数名。"""
    login = schema["paths"]["/api/v1/auth/login"]["post"]
    assert login["summary"] == "用户名密码登录，返回访问令牌与刷新令牌"
    # FastAPI 默认会生成 "Login"，此处必须已被中文摘要覆盖。
    assert login["summary"] != "Login"


def test_summary_truncated_to_readable_length(schema: dict[str, Any]) -> None:
    """超长描述的摘要被截断，不撑爆文档侧边栏。"""
    for operations in schema["paths"].values():
        for operation in operations.values():
            assert len(operation.get("summary", "")) <= 41


def test_install_openapi_overrides_app_factory() -> None:
    """挂载后 app.openapi() 返回带安全方案的规格。"""
    from fastapi import FastAPI

    probe = FastAPI(title="probe", version="0.0.1")

    @probe.get("/api/v1/probe")
    def probe_handler() -> dict[str, str]:
        """探测接口。"""
        return {"ok": "yes"}

    install_openapi(probe)
    generated = probe.openapi()
    assert generated["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    assert generated["paths"]["/api/v1/probe"]["get"]["summary"] == "探测接口"


def test_info_metadata_populated(schema: dict[str, Any]) -> None:
    """标题、版本与总说明已注入。"""
    info = schema["info"]
    assert info["title"] == "头盔守护者后端 API"
    assert info["version"]
    assert "统一响应包络" in info["description"]

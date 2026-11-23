"""OpenAPI 元信息配置：接口文档的描述、分组标签与安全方案。

职责：集中声明 API 标题、说明、标签分组文案与鉴权方案，
     并提供自定义 OpenAPI 生成函数（统一公开接口的安全要求覆盖）。
依赖：fastapi.types.Tags、fastapi.openapi.utils.get_openapi。
边界：不含任何业务逻辑；不修改路由、不参与请求处理。
"""

from __future__ import annotations

from typing import Any

from fastapi.openapi.utils import get_openapi

API_TITLE = "头盔守护者后端 API"
API_VERSION = "1.0.0"

API_DESCRIPTION = """
校园头盔检测提醒助手后端接口文档。

**核心链路**：边缘侧 YOLOv8 检测骑行者头盔佩戴状态 → 后端完成身份绑定与 AI 分级决策
→ 管理员审批后生效 → 学生在小程序查看积分、申诉与奖励。

### 统一响应包络

除健康检查等遗留路由外，所有接口返回统一包络：

```json
{ "code": 0, "data": { }, "message": "" }
```

- `code`：`0` 表示成功；非 `0` 为业务错误码。
- `data`：业务数据对象。
- `message`：错误描述，成功时为空字符串。

### 鉴权方式

除登录、注册、健康检查等公开接口外，需在请求头携带访问令牌：

```
Authorization: Bearer <access_token>
```

令牌由 `POST /api/v1/auth/login` 或 `POST /api/v1/auth/wechat-login` 获取。
令牌为无状态 JWT，默认有效期较短，失效后用 `POST /api/v1/auth/refresh` 换取新令牌。

### 权限模型

- **学生端**（`/api/v1/auth`、`/api/v1/me`、`/api/v1/self-check`）：仅能访问本人数据。
- **管理端**（`/api/v1/admin/**`）：需具备对应角色，越权返回 `403`。

### 设计约束（阅读接口时请注意）

1. **三态保守**：头盔检测结果只有 `helmeted` / `bare` / `unknown`，证据不足一律 `unknown`。
2. **身份不足不惩罚**：身份置信度低于 0.60 的事件只进待识别池，不进入处罚决策。
3. **人工兜底**：AI 决策全部进入审批队列，需管理员审批后生效。
4. **学生可申诉**：每条处罚都有申诉入口，申诉需人工二次处理。
"""

# 标签分组说明文案。key 必须与各路由模块的 `tags=[...]` 完全一致，
# 否则分组说明不会生效。
_TAG_DESCRIPTIONS: dict[str, str] = {
    "auth": "**认证与会话** — 登录、刷新令牌、登出、当前用户、学号绑定、"
    "微信快捷登录与手机号绑定。",
    "org": "**组织机构** — 院系、班级等组织单元查询，供管理端筛选与统计使用。",
    "identity-admin": "**身份管理（管理端）** — 待识别池、车辆与学生档案、"
    "身份绑定/忽略、Excel 批量导入。",
    "decision-admin": "**AI 决策与审批** — 决策列表、待审计数、单条审批/驳回与批量审批。"
    "决策必须人工确认后生效。",
    "event-admin": "**事件管理（管理端）** — 检测事件列表、详情与导出。",
    "policy-admin": "**策略配置** — 决策阈值与评分规则的查询、修改与模拟试算。",
    "score-admin": "**积分与账户** — 积分账户、流水账本、规则管理与规则模拟。",
    "appeal-admin": "**申诉处理（管理端）** — 申诉列表、受理与仲裁。",
    "appeal-me": "**申诉（学生端）** — 本人申诉的提交与进度查询。",
    "dashboard-admin": "**数据看板** — 总览指标、趋势分析与积分健康度。",
    "ops-admin": "**运维管理** — 模型版本管理与激活、反馈统计、审计日志、用户管理。",
    "monitor-admin": "**监控点管理** — 采集监控点、实时快照、事件流与采集参数配置。",
    "selfcheck": "**头盔自查（学生端）** — 上传照片自查佩戴状态与自查任务状态查询。",
    "system-legacy": "**系统与健康检查** — 健康检查、数据源列表与总体统计"
    "（遗留原生 SQL 路由）。",
    "events-legacy": "**事件与提醒（遗留路由）** — 采集事件查询、人工复核与提醒列表，"
    "路径与响应保持向后兼容。",
}

# 标签分组：用 dict 而非 fastapi.types.Tags，兼容不支持该类型的 FastAPI 版本。
API_TAGS: list[dict[str, Any]] = [
    {"name": name, "description": description}
    for name, description in _TAG_DESCRIPTIONS.items()
]

# 安全方案：与 `app.core.deps._bearer_scheme` 的 HTTPBearer 对应。
# 公开接口在各自的路由上通过 `security=[]` 覆盖。
API_SECURITY_SCHEMES = {
    "HTTPBearer": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": (
            "访问令牌。获取方式：`POST /api/v1/auth/login` 或 `POST /api/v1/auth/wechat-login`，"
            "随后在请求头携带 `Authorization: Bearer <access_token>`。"
        ),
    }
}

# 公开接口清单：(路径, HTTP 方法)。这些接口无需携带令牌即可访问，
# 在生成的 OpenAPI 中移除 `security` 要求，避免文档误导调用方。
PUBLIC_ENDPOINTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("/api/v1/auth/login", "post"),
        ("/api/v1/auth/refresh", "post"),
        ("/api/v1/auth/wechat-login", "post"),
        ("/health", "get"),
    }
)


def build_openapi(app: Any) -> dict[str, Any]:
    """生成带完整元信息的 OpenAPI 规格。

    在 FastAPI 默认生成的基础上做两处增强：
    1. 注入 Bearer 安全方案，并为需要鉴权的操作标注 `security`；
    2. 公开接口移除 `security` 要求，文档上明确标注「无需鉴权」。

    Args:
        app: FastAPI 应用实例。

    Returns:
        OpenAPI 规格字典。
    """
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
        servers=[{"url": "/", "description": "当前服务"}],
    )

    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    # FastAPI 已为 HTTPBearer 依赖自动注册同名方案，此处合并补充
    # bearerFormat 与使用说明，避免 setdefault 导致描述缺失。
    bearer = security_schemes.setdefault("HTTPBearer", {})
    for key, value in API_SECURITY_SCHEMES["HTTPBearer"].items():
        bearer.setdefault(key, value)

    for path, operations in schema.get("paths", {}).items():
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "delete", "patch", "head", "options"}:
                continue
            if (path, method) in PUBLIC_ENDPOINTS:
                operation.pop("security", None)
            else:
                operation.setdefault("security", [{"HTTPBearer": []}])
            _apply_chinese_summary(operation)

    return schema


def _apply_chinese_summary(operation: dict[str, Any]) -> None:
    """用接口中文描述的首句覆盖英文自动摘要。

    FastAPI 默认把 Python 函数名转成 Title Case 作为 summary（如 `List Events`），
    对中文调用方不友好。此处取 description 首句去掉句末标点作为摘要，
    docstring 变更时摘要自动同步，无需维护额外映射表。

    Args:
        operation: OpenAPI 中的单个操作对象（原地修改）。
    """
    description = (operation.get("description") or "").strip()
    if not description:
        return
    first_line = description.splitlines()[0].strip()
    if not first_line:
        return
    summary = first_line.rstrip("。.!！")
    if not summary:
        return
    # 描述过长时截断到可读长度，避免文档侧边栏撑爆。
    if len(summary) > 40:
        summary = summary[:40] + "…"
    operation["summary"] = summary


def install_openapi(app: Any) -> None:
    """把自定义 OpenAPI 生成函数挂到 FastAPI 实例上。

    FastAPI 的 `setup()` 会将 `self.openapi` 覆写为内置工厂，因此这里在
    应用构造完成后（路由全部注册）再挂载，覆盖内置实现。

    Args:
        app: FastAPI 应用实例。
    """
    app.openapi = lambda: build_openapi(app)


__all__ = [
    "API_DESCRIPTION",
    "API_SECURITY_SCHEMES",
    "API_TAGS",
    "API_TITLE",
    "API_VERSION",
    "PUBLIC_ENDPOINTS",
    "build_openapi",
    "install_openapi",
]

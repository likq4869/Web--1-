"""FastAPI 入口：应用装配（路由注册 + 中间件挂载）。

职责：lifespan 建表、基座中间件装配、业务路由显式注册。
依赖：app.api.v1.*、app.core.*、app.db、app.middleware.upload_limit。
边界：不含任何业务逻辑与原生 SQL；健康检查与遗留路由已拆至
`app/api/v1/system.py`、`app/api/v1/events_legacy.py`、`app/api/v1/selfcheck.py`，
纯逻辑在 `app/core/health.py`，上传限流在 `app/middleware/upload_limit.py`。

B-2：565 行 → < 200 行；B-1：全部路由显式注册，禁止 suppress 静默吞异常。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.appeals import admin_router as _appeal_admin_router
from app.api.v1.appeals import me_router as _appeal_me_router
from app.api.v1.auth import router as _auth_router
from app.api.v1.dashboard import router as _dashboard_router
from app.api.v1.decisions import router as _decision_router
from app.api.v1.events_admin import router as _events_admin_router
from app.api.v1.events_legacy import router as _events_legacy_router
from app.api.v1.identity import router as _identity_router
from app.api.v1.monitor import router as _monitor_router
from app.api.v1.ops import router as _ops_router
from app.api.v1.org import router as _org_router
from app.api.v1.policies import router as _policies_router
from app.api.v1.scores import router as _scores_router
from app.api.v1.selfcheck import router as _selfcheck_router
from app.api.v1.system import router as _system_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import install_middlewares, register_error_handlers
from app.db import init_db
from app.middleware.upload_limit import selfcheck_body_limit


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """应用启动建表：保留启动建表，查询接口不再建库。

    双库兼容：SQLite 模式保留 `init_db()` 建 `sources/passes/...` 六表；
    MySQL 模式跳过 SQLite 建表（`Sql/helmet_guard_mysql.sql` 为建库来源，
    不在此处建表），仅做 ORM 幂等建表兜底。
    """
    from app.core.config import get_settings as _get_settings

    _use_mysql = _get_settings().resolved_database_url.startswith("mysql")
    if not _use_mysql:
        init_db()
    # 身份域 ORM 表（users/students/vehicles/.../audit_logs）：幂等建表，
    # 保证新库直接可用；既有库 checkfirst=True 不会重建。
    _engine = None
    try:
        from app.core.deps import build_engine as _build_engine
        from app.models import Base as _Base

        _engine = _build_engine()
        _Base.metadata.create_all(_engine, checkfirst=True)
        _app.state.db_engine = _engine
    except Exception:
        _engine = None
    try:
        yield
    finally:
        # 关闭时释放连接池，否则 Windows 下 SQLite 文件被占用导致删库失败。
        if _engine is not None:
            with suppress(Exception):
                _engine.dispose()
        _app.state.db_engine = None


app = FastAPI(title="头盔守护者后端", version="0.1.0", lifespan=lifespan)

# 核心基座接入：初始化结构化日志、注册领域异常处理器与请求追踪中间件。
configure_logging(get_settings())
register_error_handlers(app)
install_middlewares(app)

settings = get_settings()
if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# 自查上传限流中间件（第一层）：保持两层限流语义，行为与拆分前逐字等价。
app.middleware("http")(selfcheck_body_limit)

# 业务路由显式注册：任一导入失败必须让服务启动失败，
# 否则会出现「服务正常但前端 404」的静默故障。
app.include_router(_auth_router)
app.include_router(_org_router)
app.include_router(_identity_router)
app.include_router(_decision_router)
app.include_router(_events_admin_router)
app.include_router(_policies_router)
app.include_router(_dashboard_router)
app.include_router(_appeal_admin_router)
app.include_router(_appeal_me_router)
app.include_router(_scores_router)
app.include_router(_ops_router)
app.include_router(_monitor_router)
# 遗留原生 SQL 路由（采集高频写入路径，保留原生实现，路径与响应逐字不变）。
app.include_router(_system_router)
app.include_router(_events_legacy_router)
# 小程序自查路由（路径与响应形状逐字不变，selfcheck.ts 依赖）。
app.include_router(_selfcheck_router)


__all__ = ["app", "lifespan"]

"""总览 API：Dashboard 指标、趋势与点位健康。

职责：HTTP 解析与响应序列化、RBAC 收敛、30s 响应缓存编排。
依赖：FastAPI、app.core.deps、app.services.dashboard。
边界：不做业务规则判定与聚合计算（全部在服务层）；非管理角色按无
资源处理（404），避免接口存在性泄露。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.core.deps import CurrentUserDep, DbSession
from app.core.errors import NotFoundError, ValidationError
from app.services.dashboard.cache import ResponseCache
from app.services.dashboard.service import CACHE_TTL_SECONDS, DashboardService

router = APIRouter(prefix="/api/v1/admin/dashboard", tags=["dashboard-admin"])

# 可读角色：与前端 `dashboard:read` 权限对齐。
READ_ROLES = frozenset(
    {
        "super_admin",
        "league_officer",
        "counselor",
        "security_officer",
        "auditor",
        "admin",
        "reviewer",
        "observer",
    }
)

CACHE_PREFIX = "hg:dashboard:"


def _require_read(role: str) -> None:
    """读权限：非授权角色按无资源处理。

    Args:
        role: 当前用户角色。

    Raises:
        NotFoundError: 角色无权访问（统一 404，不泄露接口存在性）。
    """
    if role not in READ_ROLES:
        raise NotFoundError("请求的资源不存在")


def _envelope(data: Any) -> dict[str, Any]:
    """构造统一响应包络（与前端 Axios 拦截器对齐）。"""
    return {"code": 0, "data": data, "message": ""}


@router.get("/overview")
def get_overview(session: DbSession, user: CurrentUserDep) -> dict[str, Any]:
    """总览指标 + 趋势 + 点位健康（30s 缓存）。"""
    _require_read(user.role or "")
    cache = ResponseCache()
    cache_key = f"{CACHE_PREFIX}overview"
    cached = cache.get(cache_key)
    if cached is not None:
        return _envelope(cached)
    payload = DashboardService(session).overview()
    cache.set(cache_key, payload, CACHE_TTL_SECONDS)
    return _envelope(payload)


@router.get("/trends")
def get_trends(
    session: DbSession,
    user: CurrentUserDep,
    metric: str = Query("wear_rate", max_length=32),
    granularity: str = Query("day", max_length=16),
    days: int = Query(30, ge=1, le=90),
) -> dict[str, Any]:
    """趋势序列（佩戴率 / 违规数 / 通行数，日粒度或小时粒度）。"""
    _require_read(user.role or "")
    try:
        payload = DashboardService(session).trends(
            metric=metric, granularity=granularity, days=days
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    cache = ResponseCache()
    cache_key = f"{CACHE_PREFIX}trends:{metric}:{granularity}:{days}"
    cached = cache.get(cache_key)
    if cached is not None:
        return _envelope(cached)
    cache.set(cache_key, payload, CACHE_TTL_SECONDS)
    return _envelope(payload)


@router.get("/point-health")
def get_point_health(session: DbSession, user: CurrentUserDep) -> dict[str, Any]:
    """点位健康度列表（状态 / FPS / 最近心跳 / 今日事件数）。"""
    _require_read(user.role or "")
    cache = ResponseCache()
    cache_key = f"{CACHE_PREFIX}point-health"
    cached = cache.get(cache_key)
    if cached is not None:
        return _envelope(cached)
    payload = {"items": DashboardService(session).point_health()}
    cache.set(cache_key, payload, CACHE_TTL_SECONDS)
    return _envelope(payload)


__all__ = ["router"]

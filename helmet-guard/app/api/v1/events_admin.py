"""事件管理 API：多维筛选列表、详情聚合与 CSV 导出。

职责：HTTP 解析与响应序列化、分页钳制、排序/状态白名单回退、服务调用。
依赖：FastAPI、app.core.deps、app.services.event.admin、app.schemas.event_admin。
边界：不做业务规则判定；CSV 导出只读不写库；越权语义由服务层收敛。
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.core.deps import CurrentUserDep, DbSession
from app.schemas.event_admin import EventDetailResponse, EventListItem
from app.services.event.admin import EVENT_SORTS, EventAdminService

router = APIRouter(prefix="/api/v1/admin/events", tags=["event-admin"])

_STATUSES = ("pending", "confirmed", "dismissed")
_RIDER_STATUSES = ("helmeted", "bare", "unknown")


def _page_params(page: int, page_size: int) -> tuple[int, int]:
    """钳制分页参数。"""
    return max(1, page), min(max(1, page_size), 100)


def _optional_bool(value: str | None) -> bool | None:
    """解析三态布尔查询参数：true/false/空（非法视为空）。"""
    if value is None or value == "":
        return None
    normalized = value.strip().lower()
    if normalized in ("true", "1", "yes"):
        return True
    if normalized in ("false", "0", "no"):
        return False
    return None


@router.get("")
def list_events(
    session: DbSession,
    user: CurrentUserDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source_id: str | None = Query(None, max_length=64),
    status: str | None = Query(None, max_length=32),
    run_id: str | None = Query(None, max_length=64),
    start: str | None = Query(None, max_length=64),
    end: str | None = Query(None, max_length=64),
    rider_status: str | None = Query(None, max_length=32),
    has_evidence: str | None = Query(None, max_length=8),
    has_decision: str | None = Query(None, max_length=8),
    sort: str = Query("occurred_at/desc", max_length=32),
) -> dict[str, object]:
    """事件列表（多维筛选：点位/状态/运行/时间/头盔状态/证据/决策）。

    排序为白名单：`occurred_at/desc`、`occurred_at/asc`、
    `created_at/desc`、`status/asc`；非法值回退默认。
    状态与三态非法值视为不限（回退为空）。
    """
    safe_page, safe_size = _page_params(page, page_size)
    safe_sort = sort if sort in EVENT_SORTS else "occurred_at/desc"
    service = EventAdminService(session)
    rows, total = service.list_events(
        user.role or "",
        source_id=source_id,
        status=status if status in _STATUSES else None,
        run_id=run_id,
        start=start,
        end=end,
        rider_status=rider_status if rider_status in _RIDER_STATUSES else None,
        has_evidence=_optional_bool(has_evidence),
        has_decision=_optional_bool(has_decision),
        sort=safe_sort,
        page=safe_page,
        page_size=safe_size,
    )
    items = [EventListItem.model_validate(row).model_dump(mode="json") for row in rows]
    return {"items": items, "total": total, "page": safe_page, "page_size": safe_size}


@router.get("/export")
def export_events(
    session: DbSession,
    user: CurrentUserDep,
    source_id: str | None = Query(None, max_length=64),
    status: str | None = Query(None, max_length=32),
    run_id: str | None = Query(None, max_length=64),
    start: str | None = Query(None, max_length=64),
    end: str | None = Query(None, max_length=64),
    rider_status: str | None = Query(None, max_length=32),
    has_evidence: str | None = Query(None, max_length=8),
    has_decision: str | None = Query(None, max_length=8),
    sort: str = Query("occurred_at/desc", max_length=32),
) -> Response:
    """导出事件 CSV（与列表共用筛选口径，上限 5000 行）。

    纯读接口：只做查询与文本拼接，不写库。
    """
    safe_sort = sort if sort in EVENT_SORTS else "occurred_at/desc"
    service = EventAdminService(session)
    text = service.export_csv(
        user.role or "",
        source_id=source_id,
        status=status if status in _STATUSES else None,
        run_id=run_id,
        start=start,
        end=end,
        rider_status=rider_status if rider_status in _RIDER_STATUSES else None,
        has_evidence=_optional_bool(has_evidence),
        has_decision=_optional_bool(has_decision),
        sort=safe_sort,
    )
    filename = "events-export.csv"
    return Response(
        content="\ufeff" + text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{event_id}")
def get_event_detail(event_id: str, session: DbSession, user: CurrentUserDep) -> dict[str, object]:
    """事件详情（含通行证据 boxes/原图尺寸与关联决策摘要）。"""
    service = EventAdminService(session)
    payload = service.get_detail(user.role or "", event_id)
    return EventDetailResponse.model_validate(payload).model_dump(mode="json")


__all__ = ["router"]

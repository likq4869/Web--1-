"""组织单元 API：学校/学院/年级/专业/班级五级级联（只读）。

职责：HTTP 解析与响应包络；任意登录用户可查（学籍绑定页用）。
依赖：FastAPI、app.core.deps、app.services.org、app.schemas.org。
边界：只读不写审计；空库返回空列表，前端降级为手动填写。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.core.deps import CurrentUserDep, DbSession
from app.schemas.org import OrgUnitListOut, OrgUnitOut
from app.services.org import list_units

router = APIRouter(prefix="/api/v1/org", tags=["org"])


@router.get("/units")
def list_org_units(
    session: DbSession,
    user: CurrentUserDep,
    parent_id: str | None = Query(default=None, max_length=64),
    unit_type: str | None = Query(default=None, max_length=16),
) -> dict[str, Any]:
    """列出子级组织单元（parent 为空查顶层学校）。

    Args:
        parent_id: 父单元 ID；为空查顶层。
        unit_type: 类型过滤；非法值按不限处理。
    """
    _ = user
    items = [
        OrgUnitOut.model_validate(row).model_dump(mode="json")
        for row in list_units(session, parent_id=parent_id, unit_type=unit_type)
    ]
    payload = OrgUnitListOut(
        items=[OrgUnitOut(**item) for item in items],
        parent_id=(parent_id or "").strip() or None,
    )
    return {"code": 0, "data": payload.model_dump(mode="json"), "message": ""}


__all__ = ["router"]

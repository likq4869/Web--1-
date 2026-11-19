"""组织单元服务：五级级联查询（只读，任意登录用户可用）。

职责：封装 org_units 的层级查询；空库时返回空列表（前端降级为手动填写）。
依赖：sqlalchemy 会话、仓储层、审计（只读不写审计）。
边界：不做写入；参数归一化在服务层收敛。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.identity import ORG_UNIT_TYPE_VALUES
from app.repositories.org_unit import OrgUnitRepository

_VALID_TYPES = frozenset(ORG_UNIT_TYPE_VALUES)


def list_units(
    session: Session,
    *,
    parent_id: str | None = None,
    unit_type: str | None = None,
) -> list[dict[str, object]]:
    """列出子级组织单元（启用中，按排序返回）。

    Args:
        session: 数据库会话。
        parent_id: 父单元 ID；空字符串按顶层处理。
        unit_type: 类型过滤；非法值按不限处理（前端容错）。

    Returns:
        单元字典列表（unit_id/unit_type/name/parent_id/sort_order）。
    """
    normalized_parent = (parent_id or "").strip() or None
    normalized_type = (unit_type or "").strip() or None
    if normalized_type is not None and normalized_type not in _VALID_TYPES:
        normalized_type = None
    repo = OrgUnitRepository(session)
    rows = repo.list_children(normalized_parent, normalized_type)
    return [
        {
            "unit_id": str(row.unit_id),
            "unit_type": str(row.unit_type),
            "name": str(row.name),
            "parent_id": str(row.parent_id) if row.parent_id else None,
            "sort_order": int(row.sort_order or 0),
        }
        for row in rows
    ]


__all__ = ["list_units"]

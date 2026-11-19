"""组织单元仓储：学校/学院/年级/专业/班级五级级联查询。

职责：封装 org_units 表的读取与创建。
依赖：sqlalchemy、app.models.identity。
边界：只做数据访问；层级合法性由服务层校验。
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models.identity import OrgUnit
from app.repositories.base import BaseRepository


class OrgUnitRepository(BaseRepository[OrgUnit]):
    """组织单元仓储。"""

    model = OrgUnit
    id_field = "unit_id"

    def list_children(self, parent_id: str | None, unit_type: str | None = None) -> list[OrgUnit]:
        """按父节点列出子级（根级 parent_id 为 None 时查顶层学校）。

        Args:
            parent_id: 父单元 ID；None 表示顶层。
            unit_type: 按类型过滤；None 表示不限。

        Returns:
            按 sort_order/unit_id 排序的子单元列表。
        """
        statement = select(OrgUnit).where(OrgUnit.status == "active")
        if parent_id is None:
            statement = statement.where(OrgUnit.parent_id.is_(None))
        else:
            statement = statement.where(OrgUnit.parent_id == parent_id)
        if unit_type:
            statement = statement.where(OrgUnit.unit_type == unit_type)
        statement = statement.order_by(OrgUnit.sort_order.asc(), OrgUnit.unit_id.asc())
        return list(self.session.execute(statement).scalars().all())

    def get_by_id(self, unit_id: str) -> OrgUnit | None:  # type: ignore[override]
        """按主键获取组织单元。

        Args:
            unit_id: 单元 ID。

        Returns:
            组织单元；不存在时返回 None。
        """
        return self.session.get(OrgUnit, unit_id)

    def count_active(self) -> int:
        """统计启用中的单元数（空库引导用）。"""
        statement = select(func.count()).select_from(OrgUnit).where(OrgUnit.status == "active")
        return int(self.session.execute(statement).scalar_one())

"""申诉仓储：申诉记录的数据访问。

职责：封装 appeals 表的写入与查询。
依赖：sqlalchemy、app.models.appeal。
边界：只做数据访问；状态机由服务层负责。
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.appeal import Appeal
from app.repositories.base import BaseRepository


class AppealRepository(BaseRepository[Appeal]):
    """申诉仓储。"""

    model = Appeal
    id_field = "appeal_id"

    def get_by_decision(self, decision_id: str) -> Appeal | None:
        """按决策读取申诉（一事一申诉幂等）。

        Args:
            decision_id: 决策 ID。

        Returns:
            既有申诉；无记录时返回 None。
        """
        statement = select(Appeal).where(Appeal.decision_id == decision_id).limit(1)
        return self.session.execute(statement).scalar_one_or_none()

    def list_by_student(
        self, student_id: str, *, limit: int = 20, offset: int = 0
    ) -> list[Appeal]:
        """列出某学生的申诉（按主键倒序）。"""
        statement = (
            select(Appeal)
            .where(Appeal.student_id == student_id)
            .order_by(Appeal.appeal_id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.execute(statement).scalars().all())

    def count_by_student(self, student_id: str) -> int:
        """统计某学生的申诉总数。"""
        statement = select(Appeal).where(Appeal.student_id == student_id)
        return len(list(self.session.execute(statement).scalars().all()))

    def count_pending_by_student(self, student_id: str) -> int:
        """统计某学生待处理的申诉数（pending 口径，只读）。

        Args:
            student_id: 学号。

        Returns:
            待处理申诉数。
        """
        statement = select(Appeal).where(
            Appeal.student_id == student_id, Appeal.status == "pending"
        )
        return len(list(self.session.execute(statement).scalars().all()))

    def list_all(
        self, *, status: str | None = None, limit: int = 20, offset: int = 0
    ) -> list[Appeal]:
        """管理端分页列出申诉（按主键倒序，可按状态筛选）。

        Args:
            status: 状态精确匹配；None 表示不限。
            limit: 最大返回条数。
            offset: 跳过的记录数。

        Returns:
            申诉列表。
        """
        statement = select(Appeal).order_by(Appeal.appeal_id.desc())
        if status:
            statement = statement.where(Appeal.status == status)
        statement = statement.limit(limit).offset(offset)
        return list(self.session.execute(statement).scalars().all())

    def count_all(self, *, status: str | None = None) -> int:
        """统计管理端申诉总数（与 `list_all` 同一筛选语义）。

        Args:
            status: 状态精确匹配；None 表示不限。

        Returns:
            匹配的申诉总数。
        """
        statement = select(Appeal)
        if status:
            statement = statement.where(Appeal.status == status)
        return len(list(self.session.execute(statement).scalars().all()))

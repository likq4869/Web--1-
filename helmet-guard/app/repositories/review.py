"""复核仓储：人工复核记录的写入与查询。

职责：封装 reviews 表的追加与审计查询。
依赖：sqlalchemy、app.models.entities。
边界：只做数据访问；复核结论的状态机由领域逻辑控制。
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.entities import Review
from app.repositories.base import BaseRepository


class ReviewRepository(BaseRepository[Review]):
    """复核仓储。"""

    model = Review
    id_field = "id"

    def list_by_event(self, event_id: str) -> list[Review]:
        """读取某事件的全部复核记录。

        Args:
            event_id: 事件 ID。

        Returns:
            按创建时间升序排列的复核记录列表。
        """
        statement = select(Review).where(Review.event_id == event_id).order_by(Review.created_at)
        result = self.session.execute(statement)
        return list(result.scalars().all())

    def count_by_event(self, event_id: str) -> int:
        """统计某事件的复核记录条数。

        Args:
            event_id: 事件 ID。

        Returns:
            复核记录数量。
        """
        statement = select(Review).where(Review.event_id == event_id)
        result = self.session.execute(statement)
        return len(result.scalars().all())

    def latest_by_event(self, event_id: str) -> Review | None:
        """读取某事件最近一条复核记录。

        Args:
            event_id: 事件 ID。

        Returns:
            最近一条复核记录；无记录时返回 None。
        """
        statement = (
            select(Review)
            .where(Review.event_id == event_id)
            .order_by(Review.created_at.desc())
            .limit(1)
        )
        return self.session.execute(statement).scalar_one_or_none()

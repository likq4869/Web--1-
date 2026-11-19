"""提醒仓储：现场提醒记录的写入与状态流转。

职责：封装 alerts 表的入队、状态更新与查询。
依赖：sqlalchemy、app.models.entities。
边界：只做数据访问；提醒判定规则属于领域层。
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from app.models.entities import Alert
from app.repositories.base import BaseRepository


class AlertRepository(BaseRepository[Alert]):
    """提醒仓储。"""

    model = Alert
    id_field = "alert_id"

    def list_recent(self, limit: int = 100) -> list[Alert]:
        """读取最近的提醒记录。

        Args:
            limit: 最大返回条数。

        Returns:
            按创建时间倒序排列的提醒记录列表。
        """
        statement = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
        result = self.session.execute(statement)
        return list(result.scalars().all())

    def get_by_event(self, event_id: str) -> Alert | None:
        """按事件 ID 读取提醒记录。

        Args:
            event_id: 事件 ID。

        Returns:
            提醒记录；不存在时返回 None。
        """
        statement = select(Alert).where(Alert.event_id == event_id)
        return self.session.execute(statement).scalar_one_or_none()

    def mark_played(self, event_id: str, updated_at: str) -> int:
        """把提醒标记为已播放。

        Args:
            event_id: 事件 ID。
            updated_at: 更新时间戳。

        Returns:
            受影响的记录数。
        """
        statement = (
            update(Alert)
            .where(Alert.event_id == event_id)
            .values(status="played", updated_at=updated_at)
        )
        result = self.session.execute(statement)
        if isinstance(result, CursorResult):
            return int(result.rowcount or 0)
        return 0

    def list_by_source(self, source_id: str, limit: int = 100) -> list[Alert]:
        """按点位读取提醒记录。

        Args:
            source_id: 点位 ID。
            limit: 最大返回条数。

        Returns:
            按创建时间倒序排列的提醒记录列表。
        """
        statement = (
            select(Alert)
            .where(Alert.source_id == source_id)
            .order_by(Alert.created_at.desc())
            .limit(limit)
        )
        result = self.session.execute(statement)
        return list(result.scalars().all())

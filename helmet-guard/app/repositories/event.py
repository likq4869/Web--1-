"""事件仓储：违规候选事件的查询与状态流转。

职责：封装 events 表的读取、过滤与复核状态更新。
依赖：sqlalchemy、app.models.entities、app.models.decision。
边界：只做数据访问；复核的并发安全语义由 `apply_review` 负责。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult

from app.models.entities import Event, Pass
from app.repositories.base import BaseRepository

# 事件列表排序白名单：非法值回退默认。
EVENT_SORTS: dict[str, Any] = {
    "occurred_at/desc": Event.occurred_at.desc(),
    "occurred_at/asc": Event.occurred_at.asc(),
    "created_at/desc": Event.created_at.desc(),
    "status/asc": Event.status.asc(),
}


class EventRepository(BaseRepository[Event]):
    """事件仓储。"""

    model = Event
    id_field = "event_id"

    @staticmethod
    def _sort_expression(sort: str) -> Any:
        """返回排序表达式；非法 sort 回退到发生时间倒序。"""
        return EVENT_SORTS.get(sort, Event.occurred_at.desc())

    def _apply_filters(
        self,
        statement: Any,
        *,
        source_id: str | None = None,
        status: str | None = None,
        run_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        rider_status: str | None = None,
        has_evidence: bool | None = None,
        has_decision: bool | None = None,
    ) -> Any:
        """把事件筛选条件应用到查询语句（列表与计数共用，避免口径漂移）。"""
        if source_id:
            statement = statement.where(Event.source_id == source_id)
        if status:
            statement = statement.where(Event.status == status)
        if run_id:
            statement = statement.where(Event.run_id == run_id)
        if start:
            statement = statement.where(Event.occurred_at >= start)
        if end:
            statement = statement.where(Event.occurred_at <= end)
        needs_pass = rider_status is not None or has_evidence is not None
        if needs_pass:
            statement = statement.join(Pass, Pass.pass_id == Event.pass_id)
            if rider_status:
                statement = statement.where(Pass.rider_status == rider_status)
            if has_evidence is True:
                statement = statement.where(Pass.boxes.is_not(None))
            elif has_evidence is False:
                statement = statement.where(Pass.boxes.is_(None))
        if has_decision is not None:
            from app.models.decision import Decision as DecisionModel

            subquery = select(DecisionModel.event_id)
            if has_decision:
                statement = statement.where(Event.event_id.in_(subquery))
            else:
                statement = statement.where(~Event.event_id.in_(subquery))
        return statement

    def list_with_filters(
        self,
        *,
        source_id: str | None = None,
        status: str | None = None,
        run_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        rider_status: str | None = None,
        has_evidence: bool | None = None,
        has_decision: bool | None = None,
        sort: str = "occurred_at/desc",
        limit: int = 20,
        offset: int = 0,
    ) -> list[Event]:
        """按过滤条件查询事件列表。

        Args:
            source_id: 点位 ID 精确匹配。
            status: 复核状态精确匹配。
            run_id: 采集运行 ID 精确匹配。
            start: 发生时间下界（含）。
            end: 发生时间上界（含）。
            rider_status: 通行三态（helmeted/bare/unknown，需 join passes）。
            has_evidence: 是否有检测框证据（passes.boxes 非空）。
            has_decision: 是否已生成决策（decisions 有对应行）。
            sort: 排序白名单；非法值回退默认。
            limit: 最大返回条数。
            offset: 跳过的记录数。

        Returns:
            排序后的事件列表。
        """
        statement = select(Event)
        statement = self._apply_filters(
            statement,
            source_id=source_id,
            status=status,
            run_id=run_id,
            start=start,
            end=end,
            rider_status=rider_status,
            has_evidence=has_evidence,
            has_decision=has_decision,
        )
        statement = statement.order_by(self._sort_expression(sort))
        statement = statement.limit(limit).offset(offset)
        result = self.session.execute(statement)
        return list(result.scalars().all())

    def count_with_filters(
        self,
        *,
        source_id: str | None = None,
        status: str | None = None,
        run_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        rider_status: str | None = None,
        has_evidence: bool | None = None,
        has_decision: bool | None = None,
    ) -> int:
        """统计符合过滤条件的事件数量（与列表共用过滤口径）。

        Args:
            source_id: 点位 ID 精确匹配。
            status: 复核状态精确匹配。
            run_id: 采集运行 ID 精确匹配。
            start: 发生时间下界（含）。
            end: 发生时间上界（含）。
            rider_status: 通行三态。
            has_evidence: 是否有检测框证据。
            has_decision: 是否已生成决策。

        Returns:
            匹配的事件总数。
        """
        statement = select(func.count()).select_from(Event)
        statement = self._apply_filters(
            statement,
            source_id=source_id,
            status=status,
            run_id=run_id,
            start=start,
            end=end,
            rider_status=rider_status,
            has_evidence=has_evidence,
            has_decision=has_decision,
        )
        return int(self.session.execute(statement).scalar_one())

    def get_status(self, event_id: str) -> str | None:
        """读取事件当前状态。

        Args:
            event_id: 事件 ID。

        Returns:
            状态值；事件不存在时返回 None。
        """
        statement = select(Event.status).where(Event.event_id == event_id)
        result = self.session.execute(statement)
        return result.scalar_one_or_none()

    def claim_pending(self, event_id: str, **values: Any) -> int:
        """以条件更新方式抢占处于 `pending` 的事件。

        条件 `status='pending'` 是并发安全的核心：并发复核中只有一个
        能命中并更新成功，其余请求因影响行数为 0 而判定为幂等或冲突。

        Args:
            event_id: 事件 ID。
            **values: 待更新的列名与新值。

        Returns:
            受影响的记录数（1 表示抢占成功，0 表示已被他人抢先）。
        """
        statement = (
            update(Event)
            .where(Event.event_id == event_id, Event.status == "pending")
            .values(**values)
        )
        result = self.session.execute(statement)
        if isinstance(result, CursorResult):
            return int(result.rowcount or 0)
        return 0

    def order_by_field(self, fields: Sequence[Any]) -> list[Event]:
        """按给定表达式排序读取全部事件。

        Args:
            fields: 排序表达式序列。

        Returns:
            排序后的事件列表。
        """
        statement = select(Event).order_by(*fields)
        result = self.session.execute(statement)
        return list(result.scalars().all())

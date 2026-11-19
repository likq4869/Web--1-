"""通行仓储：通行记录的写入与统计。

职责：封装 passes 表的写入、查询与佩戴率统计。
依赖：sqlalchemy、app.models.entities。
边界：只做数据访问；不包含判定规则（判定属于领域层）。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select

from app.models.entities import Pass
from app.repositories.base import BaseRepository

# 三态统计的完整取值集合，保证统计结果始终包含全部状态。
RIDER_STATUS_KEYS = ("helmeted", "bare", "unknown")


class PassRepository(BaseRepository[Pass]):
    """通行仓储。"""

    model = Pass
    id_field = "pass_id"

    def list_with_filters(
        self,
        *,
        source_id: str | None = None,
        run_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Pass]:
        """按过滤条件查询通行记录。

        Args:
            source_id: 点位 ID 精确匹配。
            run_id: 采集运行 ID 精确匹配。
            start: 发生时间下界（含）。
            end: 发生时间上界（含）。
            limit: 最大返回条数。
            offset: 跳过的记录数。

        Returns:
            按发生时间倒序排列的通行记录列表。
        """
        statement = select(Pass)
        if source_id:
            statement = statement.where(Pass.source_id == source_id)
        if run_id:
            statement = statement.where(Pass.run_id == run_id)
        if start:
            statement = statement.where(Pass.occurred_at >= start)
        if end:
            statement = statement.where(Pass.occurred_at <= end)
        statement = statement.order_by(Pass.occurred_at.desc()).limit(limit).offset(offset)
        result = self.session.execute(statement)
        return list(result.scalars().all())

    def count_by_status(
        self,
        *,
        source_id: str | None = None,
        run_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, int]:
        """按三态统计通行数量。

        Args:
            source_id: 点位 ID 精确匹配。
            run_id: 采集运行 ID 精确匹配。
            start: 发生时间下界（含）。
            end: 发生时间上界（含）。

        Returns:
            `helmeted` / `bare` / `unknown` 三态计数字典，缺失状态补 0。
        """
        statement = select(Pass.rider_status, func.count(Pass.pass_id))
        if source_id:
            statement = statement.where(Pass.source_id == source_id)
        if run_id:
            statement = statement.where(Pass.run_id == run_id)
        if start:
            statement = statement.where(Pass.occurred_at >= start)
        if end:
            statement = statement.where(Pass.occurred_at <= end)
        statement = statement.group_by(Pass.rider_status)
        rows = self.session.execute(statement).all()
        counts = dict.fromkeys(RIDER_STATUS_KEYS, 0)
        for status, count in rows:
            counts[str(status)] = int(count)
        return counts

    def list_by_run(self, run_id: str) -> list[Pass]:
        """按采集运行读取全部通行记录。

        Args:
            run_id: 采集运行 ID。

        Returns:
            该运行下的通行记录列表。
        """
        statement = select(Pass).where(Pass.run_id == run_id).order_by(Pass.occurred_at)
        result = self.session.execute(statement)
        return list(result.scalars().all())

    def order_by_field(self, fields: Sequence[str]) -> list[Pass]:
        """按给定列名排序读取全部通行记录。

        Args:
            fields: 排序列名序列。

        Returns:
            排序后的通行记录列表。
        """
        statement = select(Pass).order_by(*(getattr(Pass, field) for field in fields))
        result = self.session.execute(statement)
        return list(result.scalars().all())

"""车辆共现仓储：共现矩阵的写入与查询。

职责：封装 vehicle_cooccurrence 表的 upsert 与查询。
依赖：sqlalchemy、app.models.identity。
边界：只做数据访问；统计计算由领域层负责。
"""

from __future__ import annotations

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.engine import CursorResult

from app.models.identity import VehicleCooccurrence
from app.repositories.base import BaseRepository


def normalize_pair(first: str, second: str) -> tuple[str, str]:
    """规范化车辆对顺序（字典序），保证 (a,b) 唯一键。

    Args:
        first: 车辆 A。
        second: 车辆 B。

    Returns:
        (较小的车辆, 较大的车辆)。

    Raises:
        ValueError: 两车相同或为空。
    """
    if not first or not second:
        raise ValueError("车辆 ID 不能为空")
    if first == second:
        raise ValueError("共现对的两车不能相同")
    return (first, second) if first <= second else (second, first)


class VehicleCooccurrenceRepository(BaseRepository[VehicleCooccurrence]):
    """共现矩阵仓储（复合主键，覆盖基类的单主键假设）。"""

    model = VehicleCooccurrence
    id_field = "vehicle_a"

    def get_pair(self, first: str, second: str) -> VehicleCooccurrence | None:
        """按车辆对查询共现记录（顺序不限，内部自动规范化）。

        Args:
            first: 车辆 A。
            second: 车辆 B。

        Returns:
            共现记录；无记录或同车查询时返回 None。
        """
        if first == second:
            return None
        vehicle_a, vehicle_b = normalize_pair(first, second)
        statement = (
            select(VehicleCooccurrence)
            .where(
                VehicleCooccurrence.vehicle_a == vehicle_a,
                VehicleCooccurrence.vehicle_b == vehicle_b,
            )
            .limit(1)
        )
        return self.session.execute(statement).scalar_one_or_none()

    def upsert(
        self, first: str, second: str, *, window_count: int, jaccard: float
    ) -> VehicleCooccurrence:
        """新增或更新一条共现记录（幂等入口）。

        Args:
            first: 车辆 A（顺序不限）。
            second: 车辆 B（顺序不限）。
            window_count: 共同出现的窗口数。
            jaccard: Jaccard 相似度。

        Returns:
            更新或新建后的共现记录。

        Raises:
            ValueError: 参数非法（同车/空 ID/负数/越界）。
        """
        vehicle_a, vehicle_b = normalize_pair(first, second)
        if window_count < 0:
            raise ValueError(f"window_count 不能为负，实际 {window_count}")
        if not 0.0 <= jaccard <= 1.0:
            raise ValueError(f"jaccard 必须在 [0, 1] 内，实际 {jaccard}")
        existing = self.get_pair(vehicle_a, vehicle_b)
        if existing is not None:
            existing.window_count = window_count
            existing.jaccard = jaccard
            existing.updated_at = func.now()
            self.session.flush()
            return existing
        row = VehicleCooccurrence(
            vehicle_a=vehicle_a,
            vehicle_b=vehicle_b,
            window_count=window_count,
            jaccard=jaccard,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_for_vehicle(self, vehicle_id: str) -> list[VehicleCooccurrence]:
        """列出与某车相关的全部共现记录（两侧均查）。

        Args:
            vehicle_id: 车辆 ID。

        Returns:
            按 jaccard 倒序排列的共现记录列表。
        """
        statement = (
            select(VehicleCooccurrence)
            .where(
                (VehicleCooccurrence.vehicle_a == vehicle_id)
                | (VehicleCooccurrence.vehicle_b == vehicle_id)
            )
            .order_by(VehicleCooccurrence.jaccard.desc())
        )
        return list(self.session.execute(statement).scalars().all())

    def list_all(self) -> list[VehicleCooccurrence]:
        """列出全部共现记录（按车辆对排序，保证确定性）。

        Returns:
            全部共现记录。
        """
        statement = select(VehicleCooccurrence).order_by(
            VehicleCooccurrence.vehicle_a, VehicleCooccurrence.vehicle_b
        )
        return list(self.session.execute(statement).scalars().all())

    def delete_all(self) -> int:
        """清空共现矩阵（全量重算前调用）。

        Returns:
            删除的记录数。
        """
        result = self.session.execute(sa_delete(VehicleCooccurrence))
        if isinstance(result, CursorResult):
            return int(result.rowcount or 0)
        return 0

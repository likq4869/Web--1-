"""车辆仓储：车辆档案的查询、绑定与外观特征相似检索。

职责：封装 vehicles 表的 CRUD、车牌/车主查询与绑定更新。
依赖：sqlalchemy、struct/math、app.models.identity。
边界：只做数据访问；绑定决策（阈值、证据融合）由领域层负责。

SQLite 说明：SQLite 没有向量索引，`find_similar_by_embedding`
在 Python 层计算余弦相似度（全表扫描 + struct 解码）。
生产切换 pgvector 时，只需替换该方法为
`ORDER BY embedding <=> :query` 查询，其余方法不变。
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from numpy.typing import NDArray
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult

from app.models.identity import Vehicle
from app.repositories.base import BaseRepository


def decode_embedding(blob: bytes | None) -> tuple[float, ...] | None:
    """把 LargeBinary 字节解码为 float32 向量（公开，供服务层复用）。"""
    if not blob:
        return None
    count = len(blob) // 4
    if count == 0 or len(blob) % 4 != 0:
        return None
    return struct.unpack(f"<{count}f", blob)


def _decode_embedding(blob: bytes | None) -> tuple[float, ...] | None:
    """把 LargeBinary 字节解码为 float32 向量（内部别名，兼容既有调用）。"""
    return decode_embedding(blob)


def _encode_embedding(vector: Sequence[float]) -> bytes:
    """把 128 维向量编码为 float32 字节。

    Raises:
        ValueError: 维度不是 128 或含非有限值。
    """
    values = [float(v) for v in vector]
    if len(values) != 128:
        raise ValueError(f"embedding 必须为 128 维，实际 {len(values)}")
    if not all(math.isfinite(v) for v in values):
        raise ValueError("embedding 含非有限值")
    return struct.pack("<128f", *values)


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """计算余弦相似度；维度不一致或零向量时返回 0。"""
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class VehicleRepository(BaseRepository[Vehicle]):
    """车辆仓储。"""

    model = Vehicle
    id_field = "vehicle_id"

    def get_by_plate(self, plate_no: str) -> Vehicle | None:
        """按车牌号精确查询车辆（车牌 UNIQUE）。

        Args:
            plate_no: 车牌号。

        Returns:
            车辆档案；无匹配时返回 None。
        """
        statement = select(Vehicle).where(Vehicle.plate_no == plate_no).limit(1)
        return self.session.execute(statement).scalar_one_or_none()

    def list_by_owner(self, owner_id: str) -> list[Vehicle]:
        """列出某学生的全部绑定车辆。

        Args:
            owner_id: 学号。

        Returns:
            该学生的车辆档案列表。
        """
        statement = select(Vehicle).where(Vehicle.owner_id == owner_id).order_by(Vehicle.vehicle_id)
        result = self.session.execute(statement)
        return list(result.scalars().all())

    def update_owner(
        self,
        vehicle_id: str,
        owner_id: str | None,
        *,
        bind_type: str | None = None,
        confidence: float | None = None,
    ) -> int:
        """更新车辆的绑定关系（人工登记/证据绑定共用）。

        Args:
            vehicle_id: 车辆档案 ID。
            owner_id: 新绑定的学号；解绑时传 None。
            bind_type: 绑定方式；为 None 时保持不变。
            confidence: 绑定置信度；为 None 时保持不变。

        Returns:
            受影响的记录数。
        """
        values: dict[str, object] = {"owner_id": owner_id}
        if bind_type is not None:
            values["owner_bind_type"] = bind_type
        if confidence is not None:
            values["confidence"] = confidence
        values["updated_at"] = func.now()
        statement = update(Vehicle).where(Vehicle.vehicle_id == vehicle_id).values(**values)
        result = self.session.execute(statement)
        if isinstance(result, CursorResult):
            return int(result.rowcount or 0)
        return 0

    def touch_seen(self, vehicle_id: str, seen_at: datetime) -> int:
        """刷新车辆的最近出现时间。

        Args:
            vehicle_id: 车辆档案 ID。
            seen_at: 本次出现时间。

        Returns:
            受影响的记录数。
        """
        statement = (
            update(Vehicle)
            .where(Vehicle.vehicle_id == vehicle_id)
            .values(last_seen=seen_at, updated_at=func.now())
        )
        result = self.session.execute(statement)
        if isinstance(result, CursorResult):
            return int(result.rowcount or 0)
        return 0

    def find_similar_by_embedding(
        self,
        query: Sequence[float],
        *,
        threshold: float = 0.82,
        limit: int = 5,
    ) -> list[tuple[Vehicle, float]]:
        """按外观特征向量检索相似车辆（Python 层余弦相似度）。

        Args:
            query: 查询向量（128 维外观特征）。
            threshold: 相似度下限；低于此值的候选被过滤。
            limit: 最多返回的候选数。

        Returns:
            (车辆, 相似度) 二元组列表，按相似度降序排列。
        """
        statement = select(Vehicle).where(Vehicle.embedding.is_not(None))
        candidates = list(self.session.execute(statement).scalars().all())
        scored: list[tuple[Vehicle, float]] = []
        for vehicle in candidates:
            blob = vehicle.embedding
            assert blob is None or isinstance(blob, bytes)
            vector = _decode_embedding(blob)
            if vector is None:
                continue
            score = _cosine_similarity(query, vector)
            if score >= threshold:
                scored.append((vehicle, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    def list_embeddings_by_owner(self, owner_id: str) -> list[tuple[str, NDArray[Any]]]:
        """列出某车主名下全部带 embedding 的车辆。

        多样本说明：`embedding` 列只存"当前代表向量"（首次登记样本或
        历史均值）；本方法返回解码后的 float64 向量，供匹配时取用。

        Args:
            owner_id: 学号。

        Returns:
            (vehicle_id, 128 维向量) 列表；无 embedding 的车辆跳过。
        """
        import numpy as np  # noqa: PLC0415  # 局部导入：仅本方法需要数值解码。
        from numpy.typing import NDArray as NDArrayType  # noqa: PLC0415

        statement = (
            select(Vehicle)
            .where(Vehicle.owner_id == owner_id, Vehicle.embedding.is_not(None))
            .order_by(Vehicle.vehicle_id)
        )
        rows = list(self.session.execute(statement).scalars().all())
        result: list[tuple[str, NDArrayType[Any]]] = []
        for vehicle in rows:
            vector = _decode_embedding(vehicle.embedding)
            if vector is None or len(vector) != 128:
                continue
            result.append((vehicle.vehicle_id, np.array(vector, dtype=np.float64)))
        return result

    def update_embedding(self, vehicle_id: str, embedding: Sequence[float]) -> int:
        """整体替换车辆的外观向量（重登记/纠错场景）。

        Args:
            vehicle_id: 车辆档案 ID。
            embedding: 128 维外观向量。

        Returns:
            受影响的记录数。

        Raises:
            ValueError: 向量维度非法。
        """
        blob = _encode_embedding(embedding)
        statement = (
            update(Vehicle)
            .where(Vehicle.vehicle_id == vehicle_id)
            .values(embedding=blob, updated_at=func.now())
        )
        result = self.session.execute(statement)
        if isinstance(result, CursorResult):
            return int(result.rowcount or 0)
        return 0

    def add_embedding_sample(self, vehicle_id: str, embedding: Sequence[float]) -> int:
        """追加一个外观样本：与现存向量取平均后写回。

        渐进学习语义（说明书 §4.3.3 正反馈）："连续多次通行匹配到同一车 →
        逐步学习该学生的车辆特征"。均值更新让代表向量随样本增多而稳定，
        单帧噪声被平均稀释；`color_hist` 同步更新为最新样本直方图需由
        调用方另行处理，本方法只管 embedding 列。

        Args:
            vehicle_id: 车辆档案 ID。
            embedding: 本次通行的 128 维向量。

        Returns:
            受影响的记录数（0 表示车辆不存在）。

        Raises:
            ValueError: 向量维度非法。
        """
        values = [float(v) for v in embedding]
        if len(values) != 128:
            raise ValueError(f"embedding 必须为 128 维，实际 {len(values)}")
        vehicle = self.session.get(Vehicle, vehicle_id)
        if vehicle is None:
            return 0
        existing = _decode_embedding(vehicle.embedding)
        if existing is None or len(existing) != 128:
            merged = values
        else:
            merged = [(a + b) / 2.0 for a, b in zip(existing, values, strict=True)]
        vehicle.embedding = _encode_embedding(merged)
        # updated_at 由 ORM 列的 onupdate=func.now() 在 flush 时自动刷新。
        self.session.flush()
        return 1

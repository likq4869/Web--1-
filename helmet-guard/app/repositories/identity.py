"""身份判定仓储：身份判定与待绑定池的数据访问。

职责：封装 identity_resolutions / pending_identities 表的写入与查询。
依赖：sqlalchemy、app.models.identity。
边界：只做数据访问；证据融合与阈值决策由领域层负责。
"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult

from app.models.identity import IdentityResolution, PendingIdentity
from app.repositories.base import BaseRepository


class IdentityRepository(BaseRepository[IdentityResolution]):
    """身份判定仓储（主模型为单次通行判定，待绑定池为附属操作）。"""

    model = IdentityResolution
    id_field = "id"

    def create_resolution(self, resolution: IdentityResolution) -> IdentityResolution:
        """新增一条身份判定记录。

        Args:
            resolution: 待持久化的判定实例。

        Returns:
            持久化后的同一实例。
        """
        return self.create(resolution)

    def get_by_event(self, event_id: str) -> IdentityResolution | None:
        """按事件读取最新的身份判定。

        Args:
            event_id: 事件 ID。

        Returns:
            最新判定；无记录时返回 None。
        """
        statement = (
            select(IdentityResolution)
            .where(IdentityResolution.event_id == event_id)
            .order_by(IdentityResolution.id.desc())
            .limit(1)
        )
        return self.session.execute(statement).scalar_one_or_none()

    def list_by_subject(
        self,
        subject_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[IdentityResolution]:
        """列出某学生的身份判定历史。

        Args:
            subject_id: 学号。
            limit: 最大返回条数。
            offset: 跳过的记录数。

        Returns:
            按主键倒序排列的判定列表。
        """
        statement = (
            select(IdentityResolution)
            .where(IdentityResolution.subject_id == subject_id)
            .order_by(IdentityResolution.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = self.session.execute(statement)
        return list(result.scalars().all())

    def upsert_pending(
        self,
        vehicle_id: str,
        *,
        location: str | None = None,
        snapshot_id: str | None = None,
    ) -> PendingIdentity:
        """待绑定池计数递增或首建（幂等入口）。

        同一 vehicle_id 多次通行只累加 pass_count 并刷新 last_seen，
        不产生重复行；该语义是待绑定池去重的基础。

        Args:
            vehicle_id: 车辆档案 ID。
            location: 最近出现点位。
            snapshot_id: 证据帧 ID。

        Returns:
            更新或新建后的待绑定记录。
        """
        statement = select(PendingIdentity).where(
            PendingIdentity.vehicle_id == vehicle_id,
            PendingIdentity.status == "pending",
        ).limit(1)
        existing = self.session.execute(statement).scalar_one_or_none()
        if existing is not None:
            existing.pass_count = int(existing.pass_count) + 1
            existing.last_seen = func.now()
            if location is not None:
                existing.location = location
            if snapshot_id is not None:
                existing.snapshot_id = snapshot_id
            self.session.flush()
            return existing
        pending = PendingIdentity(
            vehicle_id=vehicle_id,
            pass_count=1,
            first_seen=None,
            last_seen=None,
            location=location,
            snapshot_id=snapshot_id,
            status="pending",
        )
        self.session.add(pending)
        self.session.flush()
        return pending

    def list_pending(
        self,
        *,
        status: str = "pending",
        limit: int = 20,
        offset: int = 0,
    ) -> list[PendingIdentity]:
        """按状态列出待绑定池记录。

        Args:
            status: 待处理状态过滤。
            limit: 最大返回条数。
            offset: 跳过的记录数。

        Returns:
            按通行次数倒序排列的待绑定列表。
        """
        statement = (
            select(PendingIdentity)
            .where(PendingIdentity.status == status)
            .order_by(PendingIdentity.pass_count.desc(), PendingIdentity.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = self.session.execute(statement)
        return list(result.scalars().all())

    def resolve_pending(self, pending_id: int, *, status: str) -> int:
        """终结一条待绑定记录（resolved/ignored）。

        条件更新保证只有 pending 行能被终结，已处理的重复调用返回 0，
        调用方可据此实现幂等。

        Args:
            pending_id: 待绑定记录主键。
            status: 目标状态（resolved/ignored）。

        Returns:
            受影响的记录数。
        """
        statement = (
            update(PendingIdentity)
            .where(PendingIdentity.id == pending_id, PendingIdentity.status == "pending")
            .values(status=status)
        )
        result = self.session.execute(statement)
        if isinstance(result, CursorResult):
            return int(result.rowcount or 0)
        return 0

    def resolve_pending_by_vehicle(self, vehicle_id: str, *, status: str) -> int:
        """按车辆终结全部 pending 行（绑定/忽略共用）。

        Args:
            vehicle_id: 车辆档案 ID。
            status: 目标状态（resolved/ignored）。

        Returns:
            受影响的记录数。
        """
        statement = (
            update(PendingIdentity)
            .where(
                PendingIdentity.vehicle_id == vehicle_id,
                PendingIdentity.status == "pending",
            )
            .values(status=status)
        )
        result = self.session.execute(statement)
        if isinstance(result, CursorResult):
            return int(result.rowcount or 0)
        return 0

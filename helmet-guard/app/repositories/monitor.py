"""点位标定仓储：camera_points 的读取与覆盖写入。

职责：封装 camera_points 表的按点位读取与幂等覆盖。
依赖：sqlalchemy、app.models.monitor。
边界：只做数据访问；几何校验与 RBAC 由服务层负责。
"""

from __future__ import annotations

from app.models.monitor import CameraPoint
from app.repositories.base import BaseRepository


class CameraPointRepository(BaseRepository[CameraPoint]):
    """点位标定仓储。"""

    model = CameraPoint
    id_field = "source_id"

    def get_by_source(self, source_id: str) -> CameraPoint | None:
        """按点位读取标定覆盖行。

        Args:
            source_id: 点位 ID。

        Returns:
            覆盖行；无标定时返回 None（调用方回退内存默认）。
        """
        return self.session.get(CameraPoint, source_id)

    def upsert(
        self,
        *,
        source_id: str,
        roi: list[float],
        count_line_y: float,
        alert_zone: list[float],
        updated_by: str | None = None,
    ) -> CameraPoint:
        """幂等覆盖点位标定（不存在则建，有则更）。

        Args:
            source_id: 点位 ID。
            roi: 归一化 ROI 四元组。
            count_line_y: 归一化计数线高度。
            alert_zone: 归一化提醒区四元组。
            updated_by: 操作人。

        Returns:
            持久化后的标定行。
        """
        existing = self.session.get(CameraPoint, source_id)
        if existing is None:
            row = CameraPoint(
                source_id=source_id,
                roi_x1=roi[0],
                roi_y1=roi[1],
                roi_x2=roi[2],
                roi_y2=roi[3],
                count_line_y=count_line_y,
                zone_x1=alert_zone[0],
                zone_y1=alert_zone[1],
                zone_x2=alert_zone[2],
                zone_y2=alert_zone[3],
                updated_by=updated_by,
            )
            self.session.add(row)
            self.session.flush()
            return row
        existing.roi_x1 = roi[0]
        existing.roi_y1 = roi[1]
        existing.roi_x2 = roi[2]
        existing.roi_y2 = roi[3]
        existing.count_line_y = count_line_y
        existing.zone_x1 = alert_zone[0]
        existing.zone_y1 = alert_zone[1]
        existing.zone_x2 = alert_zone[2]
        existing.zone_y2 = alert_zone[3]
        existing.updated_by = updated_by
        self.session.flush()
        return existing


__all__ = ["CameraPointRepository"]

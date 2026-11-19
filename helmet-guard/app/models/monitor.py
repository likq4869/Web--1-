"""监控点位配置 ORM 映射：camera_points（ROI/计数线/提醒区持久化）。

职责：把点位标定配置映射为 SQLAlchemy 2.0 ORM 模型，供迁移与仓储使用。
依赖：sqlalchemy、app.models.base。
边界：只描述表结构；几何合法性由 domain.monitor_config 校验，不在 DB 约束里做。

设计说明：
- 无行 = 使用 `app.config.PointConfig` 默认值（内存默认 + 环境覆盖）；
  有行 = 管理员标定后的覆盖值。服务层读取时合并，保证老库开箱可用。
- 坐标全部归一化 0~1，与前端容器百分比坐标系一致。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CameraPoint(Base):
    """点位标定覆盖行（一行一点位，主键为 source_id）。"""

    __tablename__ = "camera_points"

    source_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    roi_x1: Mapped[float] = mapped_column(Float, nullable=False, default=0.05)
    roi_y1: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    roi_x2: Mapped[float] = mapped_column(Float, nullable=False, default=0.95)
    roi_y2: Mapped[float] = mapped_column(Float, nullable=False, default=0.95)
    count_line_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    zone_x1: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    zone_y1: Mapped[float] = mapped_column(Float, nullable=False, default=0.3)
    zone_x2: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    zone_y2: Mapped[float] = mapped_column(Float, nullable=False, default=0.9)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


__all__ = ["CameraPoint"]

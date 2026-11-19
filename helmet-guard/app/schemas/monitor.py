"""监控域 Pydantic 出入参：快照 / 流状态 / 点位标定。

职责：提供 P3-4 收尾的快照证据、流可用性与 ROI 标定读写模型。
依赖：pydantic。
边界：只描述数据结构与校验规则；几何合法性由 domain 兜底复核。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PointSnapshotEvidence(BaseModel):
    """快照证据：最近通行帧的归一化检测框与原图尺寸。"""

    model_config = ConfigDict(extra="forbid")

    pass_id: str
    occurred_at: str
    rider_status: str
    boxes: list[dict[str, object]] = Field(default_factory=list)
    image_width: int | None = None
    image_height: int | None = None


class PointSnapshotResponse(BaseModel):
    """单点位快照：健康 + 最近事件 + 证据帧（无真实视频，不编造 URL）。"""

    model_config = ConfigDict(extra="forbid")

    point: dict[str, object]
    last_event: dict[str, object] | None = None
    evidence: PointSnapshotEvidence | None = None


class PointStreamResponse(BaseModel):
    """单点位流状态：当前无真实视频源，一律不可用（诚实降级）。"""

    model_config = ConfigDict(extra="forbid")

    point_id: str
    available: bool = False
    stream_url: str | None = None
    reason: str = "暂无实时视频源，仅展示检测叠加与违规流"


class PointConfigResponse(BaseModel):
    """点位标定配置：归一化 ROI / 计数线 / 提醒区。"""

    model_config = ConfigDict(extra="forbid")

    point_id: str
    roi: list[float]
    count_line_y: float
    alert_zone: list[float]
    updated_by: str | None = None
    updated_at: str | None = None


class PointConfigBody(BaseModel):
    """点位标定写入体：四元数组 + 计数线高度。"""

    model_config = ConfigDict(extra="forbid")

    roi: list[float] = Field(min_length=4, max_length=4)
    count_line_y: float
    alert_zone: list[float] = Field(min_length=4, max_length=4)


__all__ = [
    "PointConfigBody",
    "PointConfigResponse",
    "PointSnapshotEvidence",
    "PointSnapshotResponse",
    "PointStreamResponse",
]

"""事件管理 Pydantic 出入参模型。

职责：提供管理端事件列表/详情/导出的请求与响应模型。
依赖：pydantic。
边界：只描述数据结构与校验规则；不含业务逻辑，不依赖数据库。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EventListItem(BaseModel):
    """事件列表项（管理端多维筛选视图）。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    event_id: str
    pass_id: str
    source_id: str
    run_id: str
    occurred_at: str
    status: str
    model_label: str
    reason: str | None = None
    reviewer: str | None = None
    reviewed_at: str | None = None
    created_at: str


class EventDetailResponse(BaseModel):
    """事件详情（含通行证据与关联决策摘要）。"""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    pass_id: str
    source_id: str
    run_id: str
    occurred_at: str
    status: str
    model_label: str
    reason: str | None = None
    reviewer: str | None = None
    reviewed_at: str | None = None
    created_at: str
    rider_status: str | None = None
    boxes: list[dict[str, object]] = Field(default_factory=list)
    image_width: int | None = None
    image_height: int | None = None
    decision_id: str | None = None
    decision_level: str | None = None
    decision_status: str | None = None


__all__ = ["EventDetailResponse", "EventListItem"]

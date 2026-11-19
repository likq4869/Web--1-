"""决策与申诉 Pydantic 出入参模型。

职责：提供决策列表/详情、审批、申诉的 API 请求/响应模型。
依赖：pydantic。
边界：只描述数据结构与校验规则；不含业务逻辑，不依赖数据库。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FactorResponse(BaseModel):
    """可解释因子响应。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: float
    weight: float
    evidence: str


class DecisionListItem(BaseModel):
    """决策列表项。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    decision_id: str
    event_id: str
    student_id: str | None = None
    level: str
    action: str
    score_delta: int
    reason_code: str
    confidence: float | None = None
    status: str
    auto_approved: bool = False
    created_at: datetime | None = None
    due_at: datetime | None = None


class DecisionDetailResponse(BaseModel):
    """决策详情（含因子/证据/审批历史）。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    decision_id: str
    event_id: str
    student_id: str | None = None
    level: str
    action: str
    score_delta: int
    reason_code: str
    message: str | None = None
    confidence: float | None = None
    factors: list[FactorResponse] | list[dict[str, Any]] | None = None
    evidence_refs: dict[str, Any] | None = None
    policy_version: str | None = None
    status: str
    auto_approved: bool = False
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    original_level: str | None = None
    effective_at: datetime | None = None
    due_at: datetime | None = None
    created_at: datetime | None = None
    review_logs: list[dict[str, Any]] = Field(default_factory=list)


class ApproveBody(BaseModel):
    """批准请求体（可降档）。"""

    model_config = ConfigDict(extra="forbid")

    level: str | None = Field(default=None, max_length=8)
    note: str = Field(default="", max_length=500)


class RejectBody(BaseModel):
    """驳回请求体（理由必填）。"""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class BatchApproveBody(BaseModel):
    """批量批准请求体。"""

    model_config = ConfigDict(extra="forbid")

    decision_ids: list[str] = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=500)


class BatchApproveItem(BaseModel):
    """批量批准逐条结果。"""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    ok: bool
    status: str | None = None
    error: str | None = None


class AppealSubmitBody(BaseModel):
    """学生发起申诉请求体。"""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)
    attachments: list[str] = Field(default_factory=list)


class AppealResponse(BaseModel):
    """申诉响应。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    appeal_id: str
    decision_id: str
    student_id: str
    reason: str
    attachments: list[str] | list[dict[str, Any]] | None = None
    status: str
    handler: str | None = None
    handle_note: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime | None = None


class AppealResolveBody(BaseModel):
    """申诉裁决请求体。"""

    model_config = ConfigDict(extra="forbid")

    upheld: bool
    note: str = Field(default="", max_length=500)


__all__ = [
    "AppealResolveBody",
    "AppealResponse",
    "AppealSubmitBody",
    "ApproveBody",
    "BatchApproveBody",
    "BatchApproveItem",
    "DecisionDetailResponse",
    "DecisionListItem",
    "FactorResponse",
    "RejectBody",
]

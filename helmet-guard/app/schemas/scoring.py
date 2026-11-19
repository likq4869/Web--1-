"""积分域 Pydantic 出入参模型。

职责：提供积分账户/台账/规则的 API 请求/响应模型。
依赖：pydantic。
边界：只描述数据结构与校验规则；不含业务逻辑，不依赖数据库。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DirectionFilter = Literal["all", "positive", "negative"]
RuleType = Literal["deduct", "award", "streak"]


class ScoreAccountResponse(BaseModel):
    """积分账户响应（含学生展示名，便于台账联查）。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    student_id: str
    name: str | None = None
    balance: int
    level: str
    total_deducted: int = 0
    total_awarded: int = 0
    streak_days: int = 0
    compliance_rate: float = 1.0
    updated_at: datetime | None = None


class ScoreLedgerResponse(BaseModel):
    """积分流水响应（只读，余额变动用正负号展示）。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    ledger_id: int
    student_id: str
    change: int
    balance_after: int
    reason_code: str
    reason_text: str | None = None
    event_id: str | None = None
    decision_id: str | None = None
    operator: str | None = None
    effective_at: datetime | None = None
    created_at: datetime | None = None


class ScoreRuleResponse(BaseModel):
    """积分规则响应（condition_json 为受限 DSL，见 domain.scoring）。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    rule_id: str
    rule_type: str
    name: str
    condition_json: dict[str, Any]
    score_change: int
    priority: int = 0
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RuleUpdateBody(BaseModel):
    """规则更新请求体（结构化编辑，禁止自由表达式字符串）。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    condition_json: dict[str, Any] | None = None
    score_change: int | None = Field(default=None, ge=-100, le=100)
    priority: int | None = Field(default=None, ge=0, le=1000)
    enabled: bool | None = None
    rule_type: RuleType | None = None


class RuleSimulateBody(BaseModel):
    """规则试算请求体：用给定事实上下文求值，不写库。"""

    model_config = ConfigDict(extra="forbid")

    condition_json: dict[str, Any] | None = None
    rule_id: str | None = Field(default=None, max_length=64)
    context: dict[str, Any] = Field(default_factory=dict)


class RuleSimulateResponse(BaseModel):
    """规则试算响应（只推演，不会真实生效）。"""

    model_config = ConfigDict(extra="forbid")

    matched: bool
    total_change: int = 0
    matched_rule_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


__all__ = [
    "DirectionFilter",
    "RuleSimulateBody",
    "RuleSimulateResponse",
    "RuleType",
    "RuleUpdateBody",
    "ScoreAccountResponse",
    "ScoreLedgerResponse",
    "ScoreRuleResponse",
]

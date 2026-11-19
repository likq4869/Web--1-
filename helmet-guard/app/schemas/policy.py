"""策略配置 Pydantic 出入参模型。

职责：提供决策策略全字段读写、熔断阈值、规则注册表与模拟器的出入参。
依赖：pydantic。
边界：只描述数据结构与校验规则；阈值合法性由服务层经领域构造器校验。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DecisionPolicyBody(BaseModel):
    """决策策略全字段（读写共用，更新时全部可选）。"""

    model_config = ConfigDict(extra="forbid")

    min_model_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    min_identity_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    l1_score: int | None = Field(default=None, ge=-100, le=100)
    l2_score: int | None = Field(default=None, ge=-100, le=100)
    l3_score: int | None = Field(default=None, ge=-100, le=100)
    award_score: int | None = Field(default=None, ge=-100, le=100)
    l3_violation_30d: int | None = Field(default=None, ge=1, le=1000)
    l3_violation_7d: int | None = Field(default=None, ge=1, le=1000)
    l3_same_point_1h: int | None = Field(default=None, ge=1, le=1000)
    l2_violation_30d: int | None = Field(default=None, ge=1, le=1000)
    l2_violation_7d: int | None = Field(default=None, ge=1, le=1000)
    streak_award_days: int | None = Field(default=None, ge=1, le=3650)
    confidence_model_weight: float | None = Field(default=None, ge=0.01, le=100.0)
    confidence_identity_weight: float | None = Field(default=None, ge=0.01, le=100.0)
    max_auto_score_delta: int | None = Field(default=None, ge=0, le=100)


class BreakerThresholdsBody(BaseModel):
    """熔断阈值全字段（更新时全部可选）。"""

    model_config = ConfigDict(extra="forbid")

    max_daily_punishments: int | None = Field(default=None, ge=1, le=100000)
    min_student_daily_delta: int | None = Field(default=None, ge=-1000, le=0)
    min_model_map: float | None = Field(default=None, ge=0.0, le=1.0)
    max_dismiss_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    min_identity_bind_rate: float | None = Field(default=None, ge=0.0, le=1.0)


class PolicyResponse(BaseModel):
    """策略当前值（含版本、熔断阈值、规则注册表摘要）。"""

    model_config = ConfigDict(extra="forbid")

    policy_id: str = "default"
    version: str
    policy: dict[str, Any]
    thresholds: dict[str, Any]
    rules: list[dict[str, str]]


class PolicyUpdateBody(BaseModel):
    """策略更新请求体（两段各自独立可选）。"""

    model_config = ConfigDict(extra="forbid")

    policy: DecisionPolicyBody | None = None
    thresholds: BreakerThresholdsBody | None = None


class PolicySimulateBody(BaseModel):
    """策略模拟请求体：候选策略 + 假设事实，只推演不写库。"""

    model_config = ConfigDict(extra="forbid")

    policy: DecisionPolicyBody | None = None
    thresholds: BreakerThresholdsBody | None = None
    model_confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    identity_confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    violation_count_30d: int = Field(default=0, ge=0, le=10000)
    violation_count_7d: int = Field(default=0, ge=0, le=10000)
    violation_count_1h_same_point: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=20, ge=1, le=100)


class PolicySimulateResponse(BaseModel):
    """策略模拟响应（只推演，不会真实生效）。"""

    model_config = ConfigDict(extra="forbid")

    policy_id: str = "default"
    simulated: int
    changed: int
    diffs: list[dict[str, Any]]
    note: str = "此操作仅推演，不会真实生效"


__all__ = [
    "BreakerThresholdsBody",
    "DecisionPolicyBody",
    "PolicyResponse",
    "PolicySimulateBody",
    "PolicySimulateResponse",
    "PolicyUpdateBody",
]

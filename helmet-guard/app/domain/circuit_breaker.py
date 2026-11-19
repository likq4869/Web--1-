"""自动通道熔断器：任一条件触发即关闭自动通道（纯函数，零 I/O）。

职责：按说明书 §8.8 的 5 条规则判定是否熔断，全部转人工。
依赖：仅标准库（dataclasses）；零 I/O，纯函数。
边界：不读库、不写库、不读时钟；阈值全部由调用方传入。

规则表（与说明书 §8.8 一一对应）::

    daily_total_exceeds   单日全校处罚 > 50 条 → 暂停自动通道
    single_student_daily  同一学生单日扣分 < -5 → 全部转人工
    model_quality_drop    模型 mAP < 0.80 → 自动通道只允许 L0/L1
    high_dismiss_rate     人工驳回率 > 0.30 → 收紧（模型/策略疑似失效）
    identity_miss_rate    身份绑定率 < 0.50 → 身份质量告警，转人工

特别注意 high_dismiss_rate：人工驳回率过高说明模型/策略正在失效，
此时必须收紧而不是继续自动（说明书原话）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BreakerRule = Literal[
    "daily_total_exceeds",
    "single_student_daily",
    "model_quality_drop",
    "high_dismiss_rate",
    "identity_miss_rate",
]


@dataclass(frozen=True)
class BreakerState:
    """熔断器输入状态（调用方负责组装，绝不读时钟/读库）。

    Attributes:
        today_punishments: 单日全校处罚事件数。
        max_student_daily_delta: 同一学生单日最大扣分（负数，如 -6）。
        active_model_map: 当前线上模型 mAP。
        recent_dismiss_rate: 近 7 天人工驳回率，[0, 1]。
        identity_bind_rate: 身份自动绑定率，[0, 1]。
    """

    today_punishments: int = 0
    max_student_daily_delta: int = 0
    active_model_map: float = 1.0
    recent_dismiss_rate: float = 0.0
    identity_bind_rate: float = 1.0


@dataclass(frozen=True)
class BreakerThresholds:
    """熔断阈值：全部可注入，便于模拟器调参。"""

    max_daily_punishments: int = 50
    min_student_daily_delta: int = -5
    min_model_map: float = 0.80
    max_dismiss_rate: float = 0.30
    min_identity_bind_rate: float = 0.50


@dataclass(frozen=True)
class BreakerVerdict:
    """熔断判定结果。"""

    tripped: bool
    rule: BreakerRule | None
    reason: str


_BREAKER_REASONS: dict[BreakerRule, str] = {
    "daily_total_exceeds": "单日全校处罚事件过多，暂停自动通道，全部转人工",
    "single_student_daily": "同一学生单日扣分过多，全部转人工",
    "model_quality_drop": "模型 mAP 下降，自动通道只允许提醒（L0/L1）",
    "high_dismiss_rate": "人工驳回率过高，模型/策略疑似失效，收紧自动通道",
    "identity_miss_rate": "身份绑定率过低，转人工确认",
}


def evaluate(
    state: BreakerState,
    thresholds: BreakerThresholds | None = None,
) -> BreakerVerdict:
    """按顺序评估 5 条熔断规则，首条命中即返回（纯函数）。

    Args:
        state: 当前状态快照。
        thresholds: 熔断阈值；为 None 时用默认阈值。

    Returns:
        熔断结论；未命中时 tripped=False、rule=None。

    Raises:
        ValueError: 输入取值非法（负数/概率越界）。
    """
    active = thresholds if thresholds is not None else BreakerThresholds()
    for name in (
        "today_punishments",
        "max_student_daily_delta",
    ):
        value = getattr(state, name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} 必须为整数，实际 {value!r}")
    if state.today_punishments < 0:
        raise ValueError("today_punishments 不能为负数")
    for name in ("active_model_map", "recent_dismiss_rate", "identity_bind_rate"):
        value = getattr(state, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} 必须为数字，实际 {value!r}")
        if "rate" in name and not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"{name} 必须在 [0, 1] 内，实际 {value!r}")

    checks: list[tuple[BreakerRule, bool, str]] = [
        (
            "daily_total_exceeds",
            state.today_punishments > active.max_daily_punishments,
            f"单日处罚 {state.today_punishments} 条，超过上限 {active.max_daily_punishments} 条",
        ),
        (
            "single_student_daily",
            state.max_student_daily_delta < active.min_student_daily_delta,
            f"单学生单日扣分 {state.max_student_daily_delta} 分，低于下限 "
            f"{active.min_student_daily_delta} 分",
        ),
        (
            "model_quality_drop",
            float(state.active_model_map) < active.min_model_map,
            f"模型 mAP {float(state.active_model_map):.2f}，低于下限 {active.min_model_map:.2f}",
        ),
        (
            "high_dismiss_rate",
            float(state.recent_dismiss_rate) > active.max_dismiss_rate,
            f"人工驳回率 {float(state.recent_dismiss_rate):.2f}，高于上限 "
            f"{active.max_dismiss_rate:.2f}，模型/策略疑似失效",
        ),
        (
            "identity_miss_rate",
            float(state.identity_bind_rate) < active.min_identity_bind_rate,
            f"身份绑定率 {float(state.identity_bind_rate):.2f}，低于下限 "
            f"{active.min_identity_bind_rate:.2f}",
        ),
    ]
    for rule, hit, detail in checks:
        if hit:
            reason = f"{_BREAKER_REASONS[rule]}：{detail}"
            return BreakerVerdict(tripped=True, rule=rule, reason=reason)
    return BreakerVerdict(tripped=False, rule=None, reason="5 条熔断规则均未命中，自动通道保持开放")


__all__ = [
    "BreakerRule",
    "BreakerState",
    "BreakerThresholds",
    "BreakerVerdict",
    "evaluate",
]

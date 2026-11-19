"""AI 决策引擎领域层：确定性规则决策（纯函数，零 I/O）。

职责：把事实层原子事实映射为分级自治档位（L0~L4），输出动作、
分值、原因码、可解释因子与话术，阈值全部来自可注入的决策策略。
依赖：仅标准库（math、dataclasses、enum）；零 I/O，纯函数。
边界：不读库、不写库、不读时钟、不做网络调用；输入输出均为可序列化
plain data；同样的输入永远得到同样的输出。

判定顺序（严格执行，每一步都写入 factors）::

    1. 风险闸门（先于一切）：非 bare → L0/NOT_BARE；
       身份置信度不足 → L0/IDENTITY_UNCERTAIN；
       模型置信度不足 → L0/LOW_CONFIDENCE。
    2. 档位判定（仅 bare）：30d≥阈值3 或 7d≥阈值2 或 同点位1h≥阈值2
       → L3/REPORT；30d≥1 或 7d≥1 → L2/DEDUCT_SCORE；否则 → L1/REMIND。
    3. 奖励判定（与违规互斥，仅合规时）：连续合规≥30 天 → L4/AWARD，
       否则 → L0/NO_TARGET。
    4. 因子计算：非 L0 固定输出 4 个因子（模型 0.35 / 身份 0.30 /
       历史 0.25 / 情境 0.10，权重和恒为 1.0）；L0 输出单个闸门因子。
    5. 置信度：模型与身份置信度的加权几何平均（权重来自策略）。

取值依据：闸门阈值默认 0.60（说明书 §8.4）；分值 L2=-1/L3=-3/奖励=+2
（说明书 §3.2）；熔断与审批路由见 circuit_breaker 模块。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

# 概率钳制边界：加权几何平均在 p=0/1 处对数发散，钳制后再计算。
_PROB_CLAMP_EPS = 1e-6


class DecisionLevel(StrEnum):
    """分级自治档位。与说明书 §3.2 L0~L4 一一对应。"""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class DecisionAction(StrEnum):
    """决策动作。"""

    NONE = "none"
    REMIND = "remind"
    DEDUCT_SCORE = "deduct_score"
    NOTIFY = "notify"
    REPORT = "report"
    AWARD = "award"


class ReasonCode(StrEnum):
    """原因码：机器可读，话术与审计共用。"""

    NO_TARGET = "NO_TARGET"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    NOT_BARE = "NOT_BARE"
    IDENTITY_UNCERTAIN = "IDENTITY_UNCERTAIN"
    FIRST_OFFENSE = "FIRST_OFFENSE"
    REPEAT_WITHIN_30D = "REPEAT_WITHIN_30D"
    REPEAT_WITHIN_7D = "REPEAT_WITHIN_7D"
    REPEAT_SAME_POINT = "REPEAT_SAME_POINT"
    HIGH_FREQUENCY = "HIGH_FREQUENCY"
    STREAK_BONUS = "STREAK_BONUS"
    AWARD_EXCELLENT = "AWARD_EXCELLENT"


@dataclass(frozen=True)
class Fact:
    """事实层暴露给规则引擎的原子事实（时间由调用方传入，绝不读时钟）。

    Attributes:
        model_confidence: 模型置信度，[0, 1]。
        identity_confidence: 身份置信度，[0, 1]。
        helmet_status: helmeted|bare|unknown。
        violation_count_30d: 近 30 天违规次数。
        violation_count_7d: 近 7 天违规次数。
        violation_count_1h_same_point: 同点位 1 小时内违规次数。
        total_passes_30d: 近 30 天通行总数。
        streak_days: 连续合规天数。
        score_balance: 当前积分。
        peak_hour: 是否高峰时段。
        repeat_same_point: 是否同点位重复。
        appeal_history_upheld: 历史申诉成立次数。
        appeal_history_total: 历史申诉提交次数。
    """

    model_confidence: float = 0.0
    identity_confidence: float = 0.0
    helmet_status: str = "unknown"
    violation_count_30d: int = 0
    violation_count_7d: int = 0
    violation_count_1h_same_point: int = 0
    total_passes_30d: int = 0
    streak_days: int = 0
    score_balance: int = 100
    peak_hour: bool = False
    repeat_same_point: bool = False
    appeal_history_upheld: int = 0
    appeal_history_total: int = 0


@dataclass(frozen=True)
class Factor:
    """可解释因子：直接展示给管理员的人话证据。

    Attributes:
        name: 因子名（如"模型置信度"）。
        value: 因子取值（原始数值）。
        weight: 因子权重，(0, 1]；非 L0 结果的权重和恒为 1.0。
        evidence: 可读中文证据文本。
    """

    name: str
    value: float
    weight: float
    evidence: str


@dataclass(frozen=True)
class DecisionResult:
    """单次决策结果（可序列化，可审计，可回放）。"""

    level: DecisionLevel
    action: DecisionAction
    score_delta: int
    reason_code: ReasonCode
    confidence: float
    factors: tuple[Factor, ...]
    message: str
    needs_human_review: bool


@dataclass(frozen=True)
class DecisionPolicy:
    """决策策略：全部阈值可注入，便于调参与模拟器。

    Attributes:
        min_model_confidence: 模型置信度闸门。
        min_identity_confidence: 身份置信度闸门（身份不足不惩罚）。
        l1_score: L1 分值（提醒不扣分，恒为 0）。
        l2_score: L2 分值（默认 -1）。
        l3_score: L3 分值（默认 -3）。
        award_score: L4 奖励分值（默认 +2）。
        l3_violation_30d: L3 的 30 天阈值（默认 3）。
        l3_violation_7d: L3 的 7 天阈值（默认 2）。
        l3_same_point_1h: L3 的同点位 1 小时阈值（默认 2）。
        l2_violation_30d: L2 的 30 天阈值（默认 1）。
        l2_violation_7d: L2 的 7 天阈值（默认 1）。
        streak_award_days: L4 连击阈值（默认 30 天）。
        confidence_model_weight: 置信度融合中模型的权重。
        confidence_identity_weight: 置信度融合中身份的权重。
        require_human_review_levels: 必须人工审批的档位。
        auto_approve_levels: 可自动生效的档位。
        max_auto_score_delta: 自动通道允许的最大扣分绝对值（默认 0，绝不自动扣分）。
    """

    min_model_confidence: float = 0.60
    min_identity_confidence: float = 0.60
    l1_score: int = 0
    l2_score: int = -1
    l3_score: int = -3
    award_score: int = 2
    l3_violation_30d: int = 3
    l3_violation_7d: int = 2
    l3_same_point_1h: int = 2
    l2_violation_30d: int = 1
    l2_violation_7d: int = 1
    streak_award_days: int = 30
    confidence_model_weight: float = 0.5
    confidence_identity_weight: float = 0.5
    require_human_review_levels: tuple[DecisionLevel, ...] = (
        DecisionLevel.L2,
        DecisionLevel.L3,
        DecisionLevel.L4,
    )
    auto_approve_levels: tuple[DecisionLevel, ...] = (
        DecisionLevel.L0,
        DecisionLevel.L1,
    )
    max_auto_score_delta: int = 0


@dataclass(frozen=True)
class ReplayDiff:
    """决策回放差异：策略模拟器输出。"""

    original: DecisionResult
    replayed: DecisionResult
    changed: bool
    diff_reason: str


def _clamp_probability(prob: float) -> float:
    """把概率钳制到 [eps, 1-eps]，防止对数发散。"""
    return min(max(prob, _PROB_CLAMP_EPS), 1.0 - _PROB_CLAMP_EPS)


def combined_confidence(
    model_confidence: float,
    identity_confidence: float,
    *,
    model_weight: float = 0.5,
    identity_weight: float = 0.5,
) -> float:
    """加权几何平均：exp((w_m·ln p_m + w_i·ln p_i) / (w_m + w_i))。

    Args:
        model_confidence: 模型置信度。
        identity_confidence: 身份置信度。
        model_weight: 模型权重（须 > 0）。
        identity_weight: 身份权重（须 > 0）。

    Returns:
        [0, 1] 内的综合置信度。

    Raises:
        ValueError: 权重非正或置信度超出 [0, 1]。
    """
    for name, value in (("model", model_confidence), ("identity", identity_confidence)):
        if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"{name} 置信度必须在 [0, 1] 内，实际 {value!r}")
    if model_weight <= 0 or identity_weight <= 0:
        raise ValueError("置信度权重必须为正数")
    total = model_weight + identity_weight
    log_sum = model_weight * math.log(_clamp_probability(float(model_confidence)))
    log_sum += identity_weight * math.log(_clamp_probability(float(identity_confidence)))
    return float(math.exp(log_sum / total))


def _validate_fact(fact: Fact) -> None:
    """校验 Fact 取值范围；非法一律 ValueError（不猜测、不截断）。"""
    for name in ("model_confidence", "identity_confidence"):
        value = getattr(fact, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} 必须为数字，实际 {value!r}")
        if not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"{name} 必须在 [0, 1] 内，实际 {value!r}")
    if fact.helmet_status not in ("helmeted", "bare", "unknown"):
        raise ValueError(f"helmet_status 非法：{fact.helmet_status!r}")
    for name in (
        "violation_count_30d",
        "violation_count_7d",
        "violation_count_1h_same_point",
        "total_passes_30d",
        "streak_days",
        "score_balance",
        "appeal_history_upheld",
        "appeal_history_total",
    ):
        value = getattr(fact, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} 必须为非负整数，实际 {value!r}")
    for name in ("peak_hour", "repeat_same_point"):
        if not isinstance(getattr(fact, name), bool):
            raise ValueError(f"{name} 必须为布尔值")


def _validate_policy(policy: DecisionPolicy) -> None:
    """校验策略阈值单调性；非法一律 ValueError。"""
    if not 0.0 <= policy.min_model_confidence <= 1.0:
        raise ValueError("min_model_confidence 必须在 [0, 1] 内")
    if not 0.0 <= policy.min_identity_confidence <= 1.0:
        raise ValueError("min_identity_confidence 必须在 [0, 1] 内")
    if policy.l2_violation_30d > policy.l3_violation_30d:
        raise ValueError("L2 的 30 天阈值不得高于 L3")
    if policy.l2_violation_7d > policy.l3_violation_7d:
        raise ValueError("L2 的 7 天阈值不得高于 L3")
    for name in (
        "l3_violation_30d",
        "l3_violation_7d",
        "l3_same_point_1h",
        "l2_violation_30d",
        "l2_violation_7d",
        "streak_award_days",
    ):
        if getattr(policy, name) < 1:
            raise ValueError(f"{name} 必须 ≥ 1")


def _gate_factor(name: str, value: float, evidence: str) -> Factor:
    """构造闸门因子（L0 单因子，权重恒为 1.0）。"""
    return Factor(name=name, value=value, weight=1.0, evidence=evidence)


def _scored_factors(fact: Fact) -> tuple[Factor, ...]:
    """构造非 L0 的 4 个解释因子（权重和恒为 1.0）。

    权重分配：模型 0.35 / 身份 0.30 / 历史 0.25 / 情境 0.10。
    历史因子取 30 天违规数；情境因子取同点位重复（是=1/否=0）并在
    证据中注明是否高峰时段。
    """
    history = Factor(
        name="历史违规次数",
        value=float(fact.violation_count_30d),
        weight=0.25,
        evidence=f"近30天违规 {fact.violation_count_30d} 次，近7天 {fact.violation_count_7d} 次",
    )
    model = Factor(
        name="模型置信度",
        value=float(fact.model_confidence),
        weight=0.35,
        evidence=f"未戴盔检测置信度 {fact.model_confidence:.2f}",
    )
    identity = Factor(
        name="身份置信度",
        value=float(fact.identity_confidence),
        weight=0.30,
        evidence=f"身份综合置信度 {fact.identity_confidence:.2f}",
    )
    slot = "高峰时段" if fact.peak_hour else "平峰时段"
    repeat = "同点位重复" if fact.repeat_same_point else "非同点位重复"
    context = Factor(
        name="情境因子",
        value=1.0 if fact.repeat_same_point else 0.0,
        weight=0.10,
        evidence=f"{slot}，{repeat}，1小时同点位 {fact.violation_count_1h_same_point} 次",
    )
    return (model, identity, history, context)


def _message_for(
    level: DecisionLevel,
    reason: ReasonCode,
    fact: Fact,
    score_delta: int,
) -> str:
    """按档位生成学生话术（模板兜底，LLM 仅可选增强，不参与决策）。"""
    if level is DecisionLevel.L0:
        if reason is ReasonCode.NOT_BARE:
            return "本次通行已佩戴头盔或画面不清未予判定，请继续保持规范骑行。"
        if reason is ReasonCode.IDENTITY_UNCERTAIN:
            return "本次疑似未戴盔但身份无法确认，已记录待识别，不做处罚。"
        return "本次检测置信度不足，已记录不做处罚，请注意佩戴头盔。"
    if level is DecisionLevel.L1:
        return "检测到您本次骑行未佩戴头盔，已给予温柔提醒，不扣分。请佩戴头盔后再上路。"
    if level is DecisionLevel.L2:
        return (
            f"检测到您本次未佩戴头盔，近30天内第{fact.violation_count_30d + 1}次，"
            f"扣除文明积分{abs(score_delta)}分。申诉入口：我的-处罚记录-申诉。"
        )
    if level is DecisionLevel.L3:
        return (
            f"检测到您多次未佩戴头盔骑行（近30天{fact.violation_count_30d + 1}次），"
            f"扣除文明积分{abs(score_delta)}分并通报。请立即整改，可申诉。"
        )
    if reason is ReasonCode.AWARD_EXCELLENT:
        return (
            f"您已连续合规骑行{fact.streak_days}天，奖励文明积分{score_delta}分，"
            "感谢您的坚持，请继续保持。"
        )
    return f"您已连续合规骑行{fact.streak_days}天，奖励文明积分{score_delta}分，请继续保持。"


def _needs_review(level: DecisionLevel, score_delta: int, policy: DecisionPolicy) -> bool:
    """判定是否需要人工审批：档位在 require 集合中，或超出自动通道容忍。"""
    if level in policy.require_human_review_levels:
        return True
    if level not in policy.auto_approve_levels:
        return True
    return abs(score_delta) > abs(policy.max_auto_score_delta)


def decide(fact: Fact, policy: DecisionPolicy | None = None) -> DecisionResult:
    """执行确定性决策：同样的输入永远得到同样的输出（纯函数）。

    Args:
        fact: 原子事实（调用方负责从检测/身份/积分层组装）。
        policy: 决策策略；为 None 时用默认策略。

    Returns:
        决策结果（含档位/动作/分值/原因码/置信度/因子/话术/是否需审批）。

    Raises:
        ValueError: Fact 或 Policy 取值非法。
    """
    active = policy if policy is not None else DecisionPolicy()
    _validate_fact(fact)
    _validate_policy(active)
    confidence = combined_confidence(
        fact.model_confidence,
        fact.identity_confidence,
        model_weight=active.confidence_model_weight,
        identity_weight=active.confidence_identity_weight,
    )

    # —— 1. 风险闸门（先于一切）——
    if fact.helmet_status != "bare":
        return DecisionResult(
            level=DecisionLevel.L0,
            action=DecisionAction.NONE,
            score_delta=0,
            reason_code=ReasonCode.NOT_BARE,
            confidence=confidence,
            factors=(
                _gate_factor("头盔状态", 0.0, f"本次判定为 {fact.helmet_status}，不进入处罚"),
            ),
            message=_message_for(DecisionLevel.L0, ReasonCode.NOT_BARE, fact, 0),
            needs_human_review=False,
        )
    if fact.identity_confidence < active.min_identity_confidence:
        return DecisionResult(
            level=DecisionLevel.L0,
            action=DecisionAction.NONE,
            score_delta=0,
            reason_code=ReasonCode.IDENTITY_UNCERTAIN,
            confidence=confidence,
            factors=(
                _gate_factor(
                    "身份置信度",
                    float(fact.identity_confidence),
                    f"身份置信度 {fact.identity_confidence:.2f} 低于阈值 "
                    f"{active.min_identity_confidence:.2f}，不惩罚",
                ),
            ),
            message=_message_for(DecisionLevel.L0, ReasonCode.IDENTITY_UNCERTAIN, fact, 0),
            needs_human_review=False,
        )
    if fact.model_confidence < active.min_model_confidence:
        return DecisionResult(
            level=DecisionLevel.L0,
            action=DecisionAction.NONE,
            score_delta=0,
            reason_code=ReasonCode.LOW_CONFIDENCE,
            confidence=confidence,
            factors=(
                _gate_factor(
                    "模型置信度",
                    float(fact.model_confidence),
                    f"模型置信度 {fact.model_confidence:.2f} 低于阈值 "
                    f"{active.min_model_confidence:.2f}，不惩罚",
                ),
            ),
            message=_message_for(DecisionLevel.L0, ReasonCode.LOW_CONFIDENCE, fact, 0),
            needs_human_review=False,
        )

    # —— 2. 档位判定（有序，先命中先返回）——
    factors = _scored_factors(fact)
    if (
        fact.violation_count_30d >= active.l3_violation_30d
        or fact.violation_count_7d >= active.l3_violation_7d
        or fact.violation_count_1h_same_point >= active.l3_same_point_1h
    ):
        if fact.violation_count_1h_same_point >= active.l3_same_point_1h:
            reason = ReasonCode.REPEAT_SAME_POINT
        else:
            reason = ReasonCode.HIGH_FREQUENCY
        delta = active.l3_score
        return DecisionResult(
            level=DecisionLevel.L3,
            action=DecisionAction.REPORT,
            score_delta=delta,
            reason_code=reason,
            confidence=confidence,
            factors=factors,
            message=_message_for(DecisionLevel.L3, reason, fact, delta),
            needs_human_review=_needs_review(DecisionLevel.L3, delta, active),
        )
    if (
        fact.violation_count_30d >= active.l2_violation_30d
        or fact.violation_count_7d >= active.l2_violation_7d
    ):
        if fact.violation_count_7d >= active.l2_violation_7d and fact.violation_count_30d < (
            active.l2_violation_30d
        ):
            reason = ReasonCode.REPEAT_WITHIN_7D
        else:
            reason = ReasonCode.REPEAT_WITHIN_30D
        delta = active.l2_score
        return DecisionResult(
            level=DecisionLevel.L2,
            action=DecisionAction.DEDUCT_SCORE,
            score_delta=delta,
            reason_code=reason,
            confidence=confidence,
            factors=factors,
            message=_message_for(DecisionLevel.L2, reason, fact, delta),
            needs_human_review=_needs_review(DecisionLevel.L2, delta, active),
        )

    # —— 3. 首次违规（从宽提醒）——
    delta = active.l1_score
    return DecisionResult(
        level=DecisionLevel.L1,
        action=DecisionAction.REMIND,
        score_delta=delta,
        reason_code=ReasonCode.FIRST_OFFENSE,
        confidence=confidence,
        factors=factors,
        message=_message_for(DecisionLevel.L1, ReasonCode.FIRST_OFFENSE, fact, delta),
        needs_human_review=_needs_review(DecisionLevel.L1, delta, active),
    )


def decide_award(fact: Fact, policy: DecisionPolicy | None = None) -> DecisionResult:
    """奖励判定（与违规互斥，仅合规时调用）：连续合规达标 → L4/AWARD。

    Args:
        fact: 原子事实（合规场景：helmet_status 非 bare）。
        policy: 决策策略；为 None 时用默认策略。

    Returns:
        达标时 L4/AWARD，未达标时 L0/NO_TARGET。
    """
    active = policy if policy is not None else DecisionPolicy()
    _validate_fact(fact)
    _validate_policy(active)
    confidence = combined_confidence(
        fact.model_confidence,
        fact.identity_confidence,
        model_weight=active.confidence_model_weight,
        identity_weight=active.confidence_identity_weight,
    )
    if fact.streak_days >= active.streak_award_days:
        delta = active.award_score
        reason = (
            ReasonCode.AWARD_EXCELLENT if fact.streak_days >= active.streak_award_days * 2
            else ReasonCode.STREAK_BONUS
        )
        return DecisionResult(
            level=DecisionLevel.L4,
            action=DecisionAction.AWARD,
            score_delta=delta,
            reason_code=reason,
            confidence=confidence,
            factors=_scored_factors(fact),
            message=_message_for(DecisionLevel.L4, reason, fact, delta),
            needs_human_review=_needs_review(DecisionLevel.L4, delta, active),
        )
    return DecisionResult(
        level=DecisionLevel.L0,
        action=DecisionAction.NONE,
        score_delta=0,
        reason_code=ReasonCode.NO_TARGET,
        confidence=confidence,
        factors=(_gate_factor("连续合规", float(fact.streak_days),
                              f"连续合规 {fact.streak_days} 天，未达奖励线 "
                              f"{active.streak_award_days} 天"),),
        message=_message_for(DecisionLevel.L0, ReasonCode.NO_TARGET, fact, 0),
        needs_human_review=False,
    )


def replay_decision(
    original: DecisionResult,
    new_fact: Fact,
    new_policy: DecisionPolicy | None = None,
) -> ReplayDiff:
    """用新事实/新策略重放历史决策，输出差异报告（策略模拟器用）。

    Args:
        original: 历史决策结果。
        new_fact: 重建后的事实（或假设事实）。
        new_policy: 当前策略；为 None 时用默认策略。

    Returns:
        回放差异：original / replayed / changed / diff_reason 人话。
    """
    active = new_policy if new_policy is not None else DecisionPolicy()
    # 奖励原结果用奖励路径重放，其余用违规路径，保证语义对称。
    if original.level is DecisionLevel.L4:
        replayed = decide_award(new_fact, active)
    else:
        replayed = decide(new_fact, active)
    changed = (
        replayed.level is not original.level
        or replayed.action is not original.action
        or replayed.score_delta != original.score_delta
        or replayed.reason_code is not original.reason_code
    )
    if not changed:
        return ReplayDiff(
            original=original,
            replayed=replayed,
            changed=False,
            diff_reason="策略与事实未导致档位变化，重放一致",
        )
    parts: list[str] = []
    if replayed.level is not original.level:
        parts.append(f"档位 {original.level.value}→{replayed.level.value}")
    if replayed.action is not original.action:
        parts.append(f"动作 {original.action.value}→{replayed.action.value}")
    if replayed.score_delta != original.score_delta:
        parts.append(f"分值 {original.score_delta:+d}→{replayed.score_delta:+d}")
    if replayed.reason_code is not original.reason_code:
        parts.append(f"原因 {original.reason_code.value}→{replayed.reason_code.value}")
    return ReplayDiff(
        original=original,
        replayed=replayed,
        changed=True,
        diff_reason="；".join(parts),
    )


__all__ = [
    "DecisionAction",
    "DecisionLevel",
    "DecisionPolicy",
    "DecisionResult",
    "Fact",
    "Factor",
    "ReasonCode",
    "ReplayDiff",
    "combined_confidence",
    "decide",
    "decide_award",
    "replay_decision",
]

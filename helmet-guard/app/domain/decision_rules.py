"""决策规则注册表：可视化展示当前启用的规则（纯函数，零 I/O）。

职责：把 `decision.decide` 内部的判定顺序暴露为具名规则三元组
(name, predicate, factor_builder)，供后台"策略配置页"展示与单测复用。
依赖：仅标准库与 `app.domain.decision`；零 I/O，纯函数。
边界：不做决策执行（执行仍由 `decide`/`decide_award` 负责）；本模块只做
规则描述与命中解释，保证注册表与引擎语义一致（单测交叉断言）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.domain.decision import DecisionPolicy, Fact, Factor

# 规则谓词签名：(fact, policy) -> 是否命中。
PredicateFn = Callable[[Fact, DecisionPolicy], bool]
# 因子构造签名：(fact, policy) -> 命中时的解释因子。
FactorBuilderFn = Callable[[Fact, DecisionPolicy], Factor]


@dataclass(frozen=True)
class DecisionRule:
    """单条可展示规则。

    Attributes:
        name: 规则唯一名（英文蛇形，供前端 key）。
        title: 中文标题（展示用）。
        predicate: 命中判定（纯函数）。
        factor_builder: 命中时的因子构造（纯函数）。
    """

    name: str
    title: str
    predicate: PredicateFn
    factor_builder: FactorBuilderFn


def _evidence_confidence(fact: Fact, policy: DecisionPolicy) -> str:
    """共用证据：双置信度与阈值对照。"""
    return (
        f"模型 {fact.model_confidence:.2f}（线 {policy.min_model_confidence:.2f}）/"
        f"身份 {fact.identity_confidence:.2f}（线 {policy.min_identity_confidence:.2f}）"
    )


def _is_bare(fact: Fact, _policy: DecisionPolicy) -> bool:
    """是否未戴盔（处罚前置）。"""
    return fact.helmet_status == "bare"


def _gate_identity_ok(fact: Fact, policy: DecisionPolicy) -> bool:
    """身份置信度是否达标。"""
    return fact.identity_confidence >= policy.min_identity_confidence


def _gate_model_ok(fact: Fact, policy: DecisionPolicy) -> bool:
    """模型置信度是否达标。"""
    return fact.model_confidence >= policy.min_model_confidence


def _hit_l3(fact: Fact, policy: DecisionPolicy) -> bool:
    """是否达到 L3 高频线（任一子条件成立）。"""
    return (
        fact.violation_count_30d >= policy.l3_violation_30d
        or fact.violation_count_7d >= policy.l3_violation_7d
        or fact.violation_count_1h_same_point >= policy.l3_same_point_1h
    )


def _hit_l2(fact: Fact, policy: DecisionPolicy) -> bool:
    """是否达到 L2 重复线（30 天或 7 天）。"""
    return (
        fact.violation_count_30d >= policy.l2_violation_30d
        or fact.violation_count_7d >= policy.l2_violation_7d
    )


def _hit_streak_award(fact: Fact, policy: DecisionPolicy) -> bool:
    """是否达到 L4 连击奖励线。"""
    return fact.streak_days >= policy.streak_award_days


RULE_REGISTRY: tuple[DecisionRule, ...] = (
    DecisionRule(
        name="gate_not_bare",
        title="风险闸门：非 bare 直接 L0",
        predicate=lambda fact, _policy: fact.helmet_status != "bare",
        factor_builder=lambda fact, _policy: Factor(
            name="头盔状态",
            value=0.0,
            weight=1.0,
            evidence=f"本次判定为 {fact.helmet_status}，不进入处罚",
        ),
    ),
    DecisionRule(
        name="gate_identity",
        title="风险闸门：身份不足不惩罚",
        predicate=lambda fact, policy: _is_bare(fact, policy)
        and not _gate_identity_ok(fact, policy),
        factor_builder=lambda fact, policy: Factor(
            name="身份置信度",
            value=float(fact.identity_confidence),
            weight=1.0,
            evidence=f"身份置信度 {fact.identity_confidence:.2f} 低于阈值 "
            f"{policy.min_identity_confidence:.2f}，不惩罚",
        ),
    ),
    DecisionRule(
        name="gate_model",
        title="风险闸门：模型不足不惩罚",
        predicate=lambda fact, policy: _is_bare(fact, policy)
        and _gate_identity_ok(fact, policy)
        and not _gate_model_ok(fact, policy),
        factor_builder=lambda fact, policy: Factor(
            name="模型置信度",
            value=float(fact.model_confidence),
            weight=1.0,
            evidence=f"模型置信度 {fact.model_confidence:.2f} 低于阈值 "
            f"{policy.min_model_confidence:.2f}，不惩罚",
        ),
    ),
    DecisionRule(
        name="l3_high_frequency",
        title="L3：高频/同点位拒戴",
        predicate=lambda fact, policy: _is_bare(fact, policy)
        and _gate_identity_ok(fact, policy)
        and _gate_model_ok(fact, policy)
        and _hit_l3(fact, policy),
        factor_builder=lambda fact, _policy: Factor(
            name="历史违规次数",
            value=float(fact.violation_count_30d),
            weight=0.25,
            evidence=f"近30天违规 {fact.violation_count_30d} 次，"
            f"近7天 {fact.violation_count_7d} 次，"
            f"1小时同点位 {fact.violation_count_1h_same_point} 次",
        ),
    ),
    DecisionRule(
        name="l2_repeat",
        title="L2：30 天/7 天重复",
        predicate=lambda fact, policy: _is_bare(fact, policy)
        and _gate_identity_ok(fact, policy)
        and _gate_model_ok(fact, policy)
        and not _hit_l3(fact, policy)
        and _hit_l2(fact, policy),
        factor_builder=lambda fact, _policy: Factor(
            name="历史违规次数",
            value=float(fact.violation_count_30d),
            weight=0.25,
            evidence=(
                f"近30天违规 {fact.violation_count_30d} 次，"
                f"近7天 {fact.violation_count_7d} 次"
            ),
        ),
    ),
    DecisionRule(
        name="l1_first_offense",
        title="L1：首次违规提醒",
        predicate=lambda fact, policy: _is_bare(fact, policy)
        and _gate_identity_ok(fact, policy)
        and _gate_model_ok(fact, policy)
        and not _hit_l3(fact, policy)
        and not _hit_l2(fact, policy),
        factor_builder=lambda fact, policy: Factor(
            name="历史违规次数",
            value=float(fact.violation_count_30d),
            weight=0.25,
            evidence=(
                f"首次违规（近30天 {fact.violation_count_30d} 次）；"
                f"{_evidence_confidence(fact, policy)}"
            ),
        ),
    ),
    DecisionRule(
        name="l4_streak_award",
        title="L4：连续合规奖励",
        predicate=_hit_streak_award,
        factor_builder=lambda fact, policy: Factor(
            name="连续合规",
            value=float(fact.streak_days),
            weight=0.25,
            evidence=f"连续合规 {fact.streak_days} 天，达标线 {policy.streak_award_days} 天",
        ),
    ),
)


def list_rules() -> tuple[DecisionRule, ...]:
    """返回当前启用的规则注册表（供后台可视化展示）。

    Returns:
        规则三元组序列（顺序即判定顺序）。
    """
    return RULE_REGISTRY


__all__ = ["DecisionRule", "FactorBuilderFn", "PredicateFn", "RULE_REGISTRY", "list_rules"]

"""AI 决策引擎测试：决策矩阵、闸门边界、因子完整性、熔断器、回放、零 I/O。"""

from __future__ import annotations

import random
from pathlib import Path

from app.domain import circuit_breaker as breaker_mod
from app.domain.circuit_breaker import BreakerState, BreakerThresholds
from app.domain.decision import (
    DecisionAction,
    DecisionLevel,
    DecisionPolicy,
    Fact,
    ReasonCode,
    combined_confidence,
    decide,
    decide_award,
    replay_decision,
)
from app.domain.decision_rules import RULE_REGISTRY, list_rules

POLICY = DecisionPolicy()


def _fact(**overrides: object) -> Fact:
    """构造默认高置信 bare 事实，调用方按需覆盖。"""
    base: dict[str, object] = {
        "model_confidence": 0.93,
        "identity_confidence": 0.88,
        "helmet_status": "bare",
        "violation_count_30d": 0,
        "violation_count_7d": 0,
        "violation_count_1h_same_point": 0,
        "total_passes_30d": 20,
        "streak_days": 5,
        "score_balance": 95,
        "peak_hour": True,
        "repeat_same_point": False,
        "appeal_history_upheld": 0,
        "appeal_history_total": 0,
    }
    base.update(overrides)
    return Fact(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 说明书 §13.2 决策引擎 9 用例（6 行矩阵 + L4 奖励 + 阈值边界 + 同点位）
# ---------------------------------------------------------------------------


def test_matrix_first_offense_l1() -> None:
    """首次违规：count_30d=0 → L1/remind/0 分。"""
    result = decide(_fact(), POLICY)
    assert result.level is DecisionLevel.L1
    assert result.action is DecisionAction.REMIND
    assert result.score_delta == 0
    assert result.reason_code is ReasonCode.FIRST_OFFENSE
    assert result.needs_human_review is False


def test_matrix_second_offense_l2() -> None:
    """二次违规：count_30d=1 → L2/deduct/-1。"""
    result = decide(_fact(violation_count_30d=1), POLICY)
    assert result.level is DecisionLevel.L2
    assert result.action is DecisionAction.DEDUCT_SCORE
    assert result.score_delta == -1
    assert result.reason_code is ReasonCode.REPEAT_WITHIN_30D
    assert result.needs_human_review is True


def test_matrix_fourth_offense_l3() -> None:
    """四次违规：count_30d=3 → L3/report/-3。"""
    result = decide(_fact(violation_count_30d=3), POLICY)
    assert result.level is DecisionLevel.L3
    assert result.action is DecisionAction.REPORT
    assert result.score_delta == -3
    assert result.reason_code is ReasonCode.HIGH_FREQUENCY
    assert result.needs_human_review is True


def test_matrix_identity_insufficient_l0() -> None:
    """身份不足：identity_conf=0.5 → L0/none（关键：不惩罚）。"""
    result = decide(_fact(identity_confidence=0.5), POLICY)
    assert result.level is DecisionLevel.L0
    assert result.action is DecisionAction.NONE
    assert result.score_delta == 0
    assert result.reason_code is ReasonCode.IDENTITY_UNCERTAIN


def test_matrix_model_insufficient_l0() -> None:
    """模型不足：model_conf=0.4 → L0/none。"""
    result = decide(_fact(model_confidence=0.4), POLICY)
    assert result.level is DecisionLevel.L0
    assert result.action is DecisionAction.NONE
    assert result.reason_code is ReasonCode.LOW_CONFIDENCE


def test_matrix_non_bare_l0() -> None:
    """非 bare：helmeted → L0/none。"""
    result = decide(_fact(helmet_status="helmeted"), POLICY)
    assert result.level is DecisionLevel.L0
    assert result.action is DecisionAction.NONE
    assert result.reason_code is ReasonCode.NOT_BARE


def test_matrix_repeat_7d_and_same_point_l3() -> None:
    """7 天重复与同点位 1 小时均可触发 L3。"""
    seven = decide(_fact(violation_count_7d=2), POLICY)
    assert seven.level is DecisionLevel.L3
    assert seven.reason_code is ReasonCode.HIGH_FREQUENCY
    same_point = decide(_fact(violation_count_1h_same_point=2, repeat_same_point=True), POLICY)
    assert same_point.level is DecisionLevel.L3
    assert same_point.reason_code is ReasonCode.REPEAT_SAME_POINT


def test_matrix_award_l4() -> None:
    """连续合规 30 天 → L4/award/+2；60 天升级为 AWARD_EXCELLENT。"""
    award = decide_award(_fact(helmet_status="helmeted", streak_days=30))
    assert award.level is DecisionLevel.L4
    assert award.action is DecisionAction.AWARD
    assert award.score_delta == 2
    assert award.reason_code is ReasonCode.STREAK_BONUS
    excellent = decide_award(_fact(helmet_status="helmeted", streak_days=60))
    assert excellent.reason_code is ReasonCode.AWARD_EXCELLENT
    no_target = decide_award(_fact(helmet_status="helmeted", streak_days=5))
    assert no_target.level is DecisionLevel.L0
    assert no_target.reason_code is ReasonCode.NO_TARGET


def test_matrix_repeat_within_7d_reason() -> None:
    """仅 7 天重复（30 天未达标）→ L2 且原因为 REPEAT_WITHIN_7D。"""
    policy = DecisionPolicy(l2_violation_30d=2, l2_violation_7d=1)
    result = decide(_fact(violation_count_30d=1, violation_count_7d=1), policy)
    assert result.level is DecisionLevel.L2
    assert result.reason_code is ReasonCode.REPEAT_WITHIN_7D


# ---------------------------------------------------------------------------
# 闸门与边界
# ---------------------------------------------------------------------------


def test_gate_threshold_boundary_is_inclusive() -> None:
    """置信度恰好等于阈值时放行（不触发闸门）。"""
    result = decide(_fact(model_confidence=0.60, identity_confidence=0.60), POLICY)
    assert result.level is DecisionLevel.L1


def test_count_boundaries() -> None:
    """count_30d 恰为 1 进 L2、恰为 3 进 L3；2 仍为 L2。"""
    assert decide(_fact(violation_count_30d=1), POLICY).level is DecisionLevel.L2
    assert decide(_fact(violation_count_30d=2), POLICY).level is DecisionLevel.L2
    assert decide(_fact(violation_count_30d=3), POLICY).level is DecisionLevel.L3


def test_unknown_status_goes_l0() -> None:
    """unknown 状态同样走 NOT_BARE 闸门（证据不足不惩罚）。"""
    result = decide(_fact(helmet_status="unknown"), POLICY)
    assert (result.level, result.reason_code) == (DecisionLevel.L0, ReasonCode.NOT_BARE)


def test_invalid_fact_rejected() -> None:
    """非法 Fact 取值一律 ValueError。"""
    for bad in (
        _fact(model_confidence=1.5),
        _fact(helmet_status="maybe"),
        _fact(violation_count_30d=-1),
        _fact(peak_hour="yes"),  # type: ignore[arg-type]
    ):
        try:
            decide(bad, POLICY)
        except ValueError:
            continue
        raise AssertionError(f"非法 Fact 未被拒绝：{bad!r}")


def test_policy_monotonicity_rejected() -> None:
    """L2 阈值高于 L3 时拒绝策略（防止配错）。"""
    bad = DecisionPolicy(l2_violation_30d=5, l3_violation_30d=3)
    try:
        decide(_fact(), bad)
    except ValueError:
        return
    raise AssertionError("非法策略未被拒绝")


# ---------------------------------------------------------------------------
# 因子完整性与置信度
# ---------------------------------------------------------------------------


def test_non_l0_has_factors_and_weights_sum_to_one() -> None:
    """每个非 L0 结果至少 1 个因子，权重和恒为 1.0，证据为中文。"""
    cases = [
        decide(_fact(), POLICY),
        decide(_fact(violation_count_30d=1), POLICY),
        decide(_fact(violation_count_30d=3), POLICY),
        decide_award(_fact(helmet_status="helmeted", streak_days=30)),
    ]
    for result in cases:
        assert len(result.factors) >= 1
        total = sum(item.weight for item in result.factors)
        assert abs(total - 1.0) < 1e-9, f"权重和异常：{total}"
        for item in result.factors:
            assert item.evidence and any("\u4e00" <= ch <= "\u9fff" for ch in item.evidence)
            assert any(
                key in item.evidence
                for key in ("线", "次", "天", "置信度", "时段", "重复", "判定")
            )
        assert result.message and len(result.message) >= 10


def test_combined_confidence_geometric_mean() -> None:
    """加权几何平均：双 0.9 约为 0.9；单侧拉低整体。"""
    assert abs(combined_confidence(0.9, 0.9) - 0.9) < 1e-9
    low = combined_confidence(0.9, 0.5)
    assert 0.5 < low < 0.9


def test_decide_is_pure_function() -> None:
    """纯函数：同样输入两次输出完全一致。"""
    fact = _fact(violation_count_30d=2, peak_hour=False)
    first = decide(fact, POLICY)
    second = decide(fact, POLICY)
    assert first == second


# ---------------------------------------------------------------------------
# 熔断器 5 条规则
# ---------------------------------------------------------------------------


def test_breaker_all_five_rules_trip() -> None:
    """5 条熔断规则各自独立触发。"""
    cases: list[tuple[BreakerState, str]] = [
        (BreakerState(today_punishments=51), "daily_total_exceeds"),
        (BreakerState(max_student_daily_delta=-6), "single_student_daily"),
        (BreakerState(active_model_map=0.79), "model_quality_drop"),
        (BreakerState(recent_dismiss_rate=0.31), "high_dismiss_rate"),
        (BreakerState(identity_bind_rate=0.49), "identity_miss_rate"),
    ]
    for state, rule in cases:
        verdict = breaker_mod.evaluate(state, BreakerThresholds())
        assert verdict.tripped is True
        assert verdict.rule == rule
        assert verdict.reason


def test_breaker_quiet_when_healthy() -> None:
    """健康状态不熔断；边界值（恰好等于阈值）不触发。"""
    verdict = breaker_mod.evaluate(BreakerState(), BreakerThresholds())
    assert verdict.tripped is False
    assert verdict.rule is None
    boundary = BreakerState(
        today_punishments=50,
        max_student_daily_delta=-5,
        active_model_map=0.80,
        recent_dismiss_rate=0.30,
        identity_bind_rate=0.50,
    )
    assert breaker_mod.evaluate(boundary, BreakerThresholds()).tripped is False


# ---------------------------------------------------------------------------
# 回放 diff
# ---------------------------------------------------------------------------


def test_replay_detects_policy_change() -> None:
    """策略加严（L3 线下调）导致档位变化时正确产出 diff。"""
    fact = _fact(violation_count_30d=2)
    original = decide(fact, POLICY)
    assert original.level is DecisionLevel.L2
    strict = DecisionPolicy(l3_violation_30d=2)
    diff = replay_decision(original, fact, strict)
    assert diff.changed is True
    assert diff.replayed.level is DecisionLevel.L3
    assert "L2→L3" in diff.diff_reason


def test_replay_no_change_when_same_policy() -> None:
    """同策略同事实回放一致。"""
    fact = _fact(violation_count_30d=1)
    original = decide(fact, POLICY)
    diff = replay_decision(original, fact, POLICY)
    assert diff.changed is False
    assert "一致" in diff.diff_reason


def test_replay_award_path() -> None:
    """L4 原结果用奖励路径重放：连击不再达标时变为 L0。"""
    original = decide_award(_fact(helmet_status="helmeted", streak_days=30))
    diff = replay_decision(original, _fact(helmet_status="helmeted", streak_days=1), POLICY)
    assert diff.changed is True
    assert diff.replayed.level is DecisionLevel.L0


# ---------------------------------------------------------------------------
# 规则注册表与引擎一致性
# ---------------------------------------------------------------------------


def test_rule_registry_matches_engine_order() -> None:
    """注册表 7 条规则，顺序即判定顺序；每条谓词可独立求值。"""
    rules = list_rules()
    assert len(rules) == 7
    assert [item.name for item in rules] == [
        "gate_not_bare",
        "gate_identity",
        "gate_model",
        "l3_high_frequency",
        "l2_repeat",
        "l1_first_offense",
        "l4_streak_award",
    ]
    assert RULE_REGISTRY is not None
    # L3 事实仅命中 l3 规则，不命中 l2/l1。
    fact = _fact(violation_count_30d=3)
    hits = {
        rule.name
        for rule in rules
        if rule.name.startswith("l") and rule.predicate(fact, POLICY)
    }
    assert hits == {"l3_high_frequency"}


# ---------------------------------------------------------------------------
# 属性测试 + 零 I/O 校验
# ---------------------------------------------------------------------------


def test_property_random_facts_stay_in_range() -> None:
    """随机 Fact 下 level 合法、score_delta ∈ [-3, +2]。"""
    rng = random.Random(20261116)
    for _ in range(300):
        fact = Fact(
            model_confidence=round(rng.uniform(0, 1), 3),
            identity_confidence=round(rng.uniform(0, 1), 3),
            helmet_status=rng.choice(["helmeted", "bare", "unknown"]),
            violation_count_30d=rng.randint(0, 8),
            violation_count_7d=rng.randint(0, 5),
            violation_count_1h_same_point=rng.randint(0, 4),
            total_passes_30d=rng.randint(0, 60),
            streak_days=rng.randint(0, 60),
            score_balance=rng.randint(0, 100),
            peak_hour=rng.choice([True, False]),
            repeat_same_point=rng.choice([True, False]),
            appeal_history_upheld=rng.randint(0, 3),
            appeal_history_total=rng.randint(0, 5),
        )
        result = decide(fact, POLICY)
        assert isinstance(result.level.value, str)
        assert result.level in (
            DecisionLevel.L0,
            DecisionLevel.L1,
            DecisionLevel.L2,
            DecisionLevel.L3,
        )
        assert -3 <= result.score_delta <= 2
        award = decide_award(fact, POLICY)
        assert award.level in (DecisionLevel.L0, DecisionLevel.L4)
        assert 0 <= award.score_delta <= 2


def test_domain_has_no_io_imports() -> None:
    """领域层零 I/O：decision 系列模块不得 import 数据库/网络模块。"""
    forbidden = (
        "sqlalchemy",
        "redis",
        "httpx",
        "requests",
        "minio",
        "celery",
        "fastapi",
        "sqlite3",
        "socket",
        "datetime",
    )
    for name in ("decision.py", "decision_rules.py", "circuit_breaker.py"):
        source = (Path(__file__).resolve().parent.parent / "app" / "domain" / name).read_text(
            encoding="utf-8"
        )
        for mod in forbidden:
            assert f"import {mod}" not in source, f"{name} 引入了 I/O 模块 {mod}"

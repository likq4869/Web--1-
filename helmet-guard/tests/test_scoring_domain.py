"""积分域测试：纯函数、DSL 安全边界、规则应用。"""

from __future__ import annotations

import pytest

from app.domain.scoring import (
    RuleSpec,
    apply_rules,
    compliance_rate,
    compute_streak,
    evaluate_condition,
    level_from_score,
)


def test_level_boundaries() -> None:
    """等级边界：恰好命中上界归入更高档。"""
    assert level_from_score(100) == "S"
    assert level_from_score(96) == "S"
    assert level_from_score(95) == "A"
    assert level_from_score(90) == "A"
    assert level_from_score(89) == "B"
    assert level_from_score(80) == "B"
    assert level_from_score(79) == "C"
    assert level_from_score(60) == "C"
    assert level_from_score(59) == "D"
    assert level_from_score(-5) == "D"
    with pytest.raises(ValueError):
        level_from_score(True)  # type: ignore[arg-type]


def test_compute_streak_counts_trailing_true() -> None:
    """连续合规天数只数尾部连续 True。"""
    assert compute_streak([]) == 0
    assert compute_streak([True, True, True]) == 3
    assert compute_streak([True, True, False, True, True]) == 2
    assert compute_streak([True, False, False]) == 0
    with pytest.raises(ValueError):
        compute_streak([1])  # type: ignore[list-item]


def test_compliance_rate_basic_and_empty() -> None:
    """佩戴率：正常比例与零通行时视为全勤。"""
    assert compliance_rate(9, 1, 30) == pytest.approx(0.9)
    assert compliance_rate(0, 0, 30) == 1.0
    with pytest.raises(ValueError):
        compliance_rate(-1, 0, 30)
    with pytest.raises(ValueError):
        compliance_rate(1, 0, 0)


def _rule(
    rule_id: str,
    condition: dict[str, object],
    change: int,
    priority: int = 0,
    enabled: bool = True,
) -> RuleSpec:
    """构造测试规则。"""
    return RuleSpec(
        rule_id=rule_id,
        rule_type="deduct",
        name=f"规则{rule_id}",
        condition=condition,
        score_change=change,
        priority=priority,
        enabled=enabled,
    )


def test_dsl_single_condition() -> None:
    """单条件命中与未命中。"""
    cond = {"field": "violation_count_30d", "op": ">=", "value": 1}
    assert evaluate_condition(cond, {"violation_count_30d": 2}) is True
    assert evaluate_condition(cond, {"violation_count_30d": 0}) is False


def test_dsl_all_any_combination() -> None:
    """任务示例：all 组合必须全部成立；any 任一成立即可。"""
    cond = {
        "field": "violation_count_30d",
        "op": ">=",
        "value": 1,
        "all": [{"field": "model_confidence", "op": ">=", "value": 0.7}],
    }
    assert evaluate_condition(cond, {"violation_count_30d": 2, "model_confidence": 0.9}) is True
    assert evaluate_condition(cond, {"violation_count_30d": 2, "model_confidence": 0.5}) is False
    assert evaluate_condition(cond, {"violation_count_30d": 0, "model_confidence": 0.9}) is False

    combo = {
        "any": [
            {"field": "helmet_status", "op": "==", "value": "bare"},
            {"field": "violation_count_7d", "op": ">=", "value": 3},
        ]
    }
    assert evaluate_condition(combo, {"helmet_status": "helmeted", "violation_count_7d": 5}) is True
    assert (
        evaluate_condition(combo, {"helmet_status": "helmeted", "violation_count_7d": 0}) is False
    )


def test_dsl_missing_field_is_false_not_error() -> None:
    """上下文缺失字段视为不成立（不抛错、不猜测）。"""
    cond = {"field": "identity_confidence", "op": ">=", "value": 0.8}
    assert evaluate_condition(cond, {}) is False


@pytest.mark.parametrize(
    "bad",
    [
        {"field": "__class__", "op": "==", "value": 1},
        {"field": "violation_count_30d", "op": "__import__", "value": 1},
        {"field": "violation_count_30d", "op": ">=", "value": 1, "drop": "table"},
        {"field": "violation_count_30d", "op": ">="},
        {"field": "helmet_status", "op": ">=", "value": "bare"},
        {"field": "peak_hour", "op": "==", "value": 1},
        {"field": "violation_count_30d", "op": "in", "value": 1},
        {"field": "violation_count_30d", "op": ">=", "value": {"$gt": 1}},
        "violation_count_30d >= 1",
        {"all": "violation_count_30d"},
        {},
    ],
)
def test_dsl_malicious_or_invalid_rejected(bad: object) -> None:
    """恶意/非法 DSL 一律 ValueError（附带白名单，无 eval）。"""
    with pytest.raises(ValueError):
        evaluate_condition(bad, {"violation_count_30d": 99})


def test_dsl_in_operator_and_type_mismatch_false() -> None:
    """in/not in 正常工作；数字与字符串混比返回 False。"""
    assert evaluate_condition(
        {"field": "helmet_status", "op": "in", "value": ["bare", "unknown"]},
        {"helmet_status": "bare"},
    ) is True
    assert (
        evaluate_condition(
            {"field": "violation_count_30d", "op": ">=", "value": 1},
            {"violation_count_30d": "many"},
        )
        is False
    )


def test_apply_rules_priority_order_and_disabled() -> None:
    """规则按 priority 降序、rule_id 升序求值；禁用规则跳过。"""
    rules = [
        _rule("r2", {"field": "violation_count_30d", "op": ">=", "value": 1}, -1, priority=0),
        _rule("r1", {"field": "violation_count_30d", "op": ">=", "value": 1}, -3, priority=10),
        _rule("r0", {"field": "violation_count_30d", "op": ">=", "value": 1}, -5, priority=10,
              enabled=False),
    ]
    effect = apply_rules(rules, {"violation_count_30d": 2})
    assert effect.total_change == -4
    assert effect.matched_rule_ids == ("r1", "r2")
    assert len(effect.reasons) == 2

    empty = apply_rules(rules, {"violation_count_30d": 0})
    assert empty.total_change == 0
    assert empty.matched_rule_ids == ()


def test_apply_rules_bad_dsl_fast_fail() -> None:
    """坏规则快速失败，不静默跳过。"""
    bad = _rule("bad", {"field": "nope", "op": "==", "value": 1}, -1)
    with pytest.raises(ValueError):
        apply_rules([bad], {})

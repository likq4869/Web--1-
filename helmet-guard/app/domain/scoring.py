"""积分域领域层：等级、连击、佩戴率与安全的规则 DSL 求值器。

职责：提供无 I/O 的纯函数，供积分服务与决策引擎复用。
依赖：仅标准库（dataclasses、typing）；零 I/O，纯函数。
边界：不读库、不写库；输入输出均为可序列化 plain data。

等级线（见 level_from_score）：
- S ≥ 96、A ≥ 90、B ≥ 80、C ≥ 60、D < 60。
- 取值依据：小程序首页 mock（95 分展示为 A），故 S 线定在 96，
  保证 mock 与领域函数一致；满分 100 恒为 S。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

ScoreLevel = Literal["S", "A", "B", "C", "D"]

# 积分上下限：与 score_accounts.balance 的业务约束一致。
SCORE_MIN_BALANCE = 0
SCORE_MAX_BALANCE = 100
SCORE_INITIAL_BALANCE = 100

# DSL 白名单字段：与说明书 §8.3 事实层原子事实一一对应。
ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "model_confidence",
        "identity_confidence",
        "helmet_status",
        "violation_count_30d",
        "violation_count_7d",
        "total_passes_30d",
        "streak_days",
        "score_balance",
        "peak_hour",
        "repeat_same_point",
        "appeal_history_upheld",
    }
)
# DSL 白名单操作符：只允许比较与成员判断，绝不接受函数调用与表达式字符串。
ALLOWED_OPS: frozenset[str] = frozenset(
    {"==", "!=", ">", ">=", "<", "<=", "in", "not in"}
)

_NUMERIC_FIELDS: frozenset[str] = frozenset(
    {
        "model_confidence",
        "identity_confidence",
        "violation_count_30d",
        "violation_count_7d",
        "total_passes_30d",
        "streak_days",
        "score_balance",
        "appeal_history_upheld",
    }
)
_STR_FIELDS: frozenset[str] = frozenset({"helmet_status"})
_BOOL_FIELDS: frozenset[str] = frozenset({"peak_hour", "repeat_same_point"})


def level_from_score(score: int) -> ScoreLevel:
    """按分数映射等级（含边界：恰好命中上界归入更高档）。

    Args:
        score: 积分余额。

    Returns:
        S（≥96）/ A（≥90）/ B（≥80）/ C（≥60）/ D（<60）。

    Raises:
        ValueError: 分数不是整数。
    """
    if isinstance(score, bool) or not isinstance(score, int):
        raise ValueError(f"积分必须为整数，实际 {score!r}")
    if score >= 96:
        return "S"
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def compute_streak(daily_compliance: list[bool]) -> int:
    """计算连续合规天数：从最近一个已判定日往前数连续 True。

    调用约定：列表按时间从旧到新排列；今天还没判定时调用方只传到昨天，
    本函数不对"今天"做任何猜测，只数尾部连续 True。

    Args:
        daily_compliance: 每日是否合规（True=合规）。

    Returns:
        尾部连续 True 的个数；空列表返回 0。

    Raises:
        ValueError: 元素不是布尔值。
    """
    for item in daily_compliance:
        if not isinstance(item, bool):
            raise ValueError(f"合规序列元素必须为布尔值，实际 {item!r}")
    streak = 0
    for day in reversed(daily_compliance):
        if not day:
            break
        streak += 1
    return streak


def compliance_rate(passes: int, violations: int, window_days: int) -> float:
    """计算滚动佩戴率：合规通行 / 全部通行，无通行时视为全勤 1.0。

    Args:
        passes: 窗口内合规通行数。
        violations: 窗口内违规数。
        window_days: 窗口天数（仅做合法性校验与口径声明，暂不参与加权）。

    Returns:
        [0, 1] 内的佩戴率。

    Raises:
        ValueError: 任一参数为负或 window_days 非正。
    """
    for name, value in (("passes", passes), ("violations", violations)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} 必须为非负整数，实际 {value!r}")
    if isinstance(window_days, bool) or not isinstance(window_days, int) or window_days <= 0:
        raise ValueError(f"window_days 必须为正整数，实际 {window_days!r}")
    total = passes + violations
    if total == 0:
        return 1.0
    return min(max(passes / total, 0.0), 1.0)


def _ensure_scalar(value: object) -> None:
    """校验 DSL 值只能是标量或标量列表（拒绝 dict/set 等嵌套结构）。"""
    if isinstance(value, (str, bool, int, float)):
        return
    if isinstance(value, list) and all(
        isinstance(item, (str, bool, int, float)) and not isinstance(item, dict)
        for item in value
    ):
        return
    raise ValueError(f"DSL value 非法：只允许标量或标量列表，实际 {value!r}")


def _validate_node(node: object) -> None:
    """递归校验单个 DSL 节点；非法结构一律 ValueError。"""
    if not isinstance(node, dict):
        raise ValueError(f"DSL 节点必须为字典，实际 {node!r}")
    allowed_keys = {"field", "op", "value", "all", "any"}
    for key in node:
        if key not in allowed_keys:
            raise ValueError(f"DSL 非法键 {key!r}（防原型链/注入键）")
    has_leaf = "field" in node or "op" in node or "value" in node
    if has_leaf:
        for key in ("field", "op", "value"):
            if key not in node:
                raise ValueError(f"DSL 叶子缺少 {key!r}：{node!r}")
        field = node["field"]
        op = node["op"]
        if field not in ALLOWED_FIELDS:
            raise ValueError(f"DSL 非法字段 {field!r}")
        if op not in ALLOWED_OPS:
            raise ValueError(f"DSL 非法操作符 {op!r}")
        value = node["value"]
        is_membership = op in ("in", "not in")
        if (
            field in _NUMERIC_FIELDS
            and not isinstance(value, (int, float))
            and not (is_membership and isinstance(value, list))
        ):
            raise ValueError(f"DSL 数值字段 {field} 的 value 必须为数字：{node!r}")
        if field in _STR_FIELDS and not isinstance(value, str | list):
            raise ValueError(f"DSL 字符字段 {field} 的 value 必须为字符串：{node!r}")
        if field in _BOOL_FIELDS and not isinstance(value, bool | list):
            raise ValueError(f"DSL 布尔字段 {field} 的 value 必须为布尔值：{node!r}")
        if is_membership and not isinstance(value, list):
            raise ValueError(f"DSL 操作符 {op} 的 value 必须为列表：{node!r}")
        if (field in _STR_FIELDS or field in _BOOL_FIELDS) and op not in (
            "==",
            "!=",
            "in",
            "not in",
        ):
            raise ValueError(f"DSL 字段 {field} 不支持操作符 {op!r}")
        _ensure_scalar(node["value"])
    for key in ("all", "any"):
        if key in node:
            children = node[key]
            if not isinstance(children, list):
                raise ValueError(f"DSL {key} 必须为列表：{node!r}")
            for child in children:
                _validate_node(child)
    if not has_leaf and "all" not in node and "any" not in node:
        raise ValueError(f"DSL 空节点（既无叶子也无 all/any）：{node!r}")


def _compare(op: str, actual: Any, expected: Any) -> bool:
    """执行单次白名单比较；类型不兼容时返回 False（不抛错、不猜测）。"""
    if op == "==":
        return bool(actual == expected)
    if op == "!=":
        return bool(actual != expected)
    if op == "in":
        return isinstance(expected, list) and actual in expected
    if op == "not in":
        return isinstance(expected, list) and actual not in expected
    # 排序比较仅允许数字对数字（布尔已在校验层排除）。
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        return False
    if isinstance(expected, bool) or not isinstance(expected, (int, float)):
        return False
    if op == ">":
        return bool(actual > expected)
    if op == ">=":
        return bool(actual >= expected)
    if op == "<":
        return bool(actual < expected)
    if op == "<=":
        return bool(actual <= expected)
    return False  # pragma: no cover - 白名单已保证不可达。


def evaluate_condition(condition: object, context: Mapping[str, Any]) -> bool:
    """求值受限 DSL 条件（白名单字段 + 白名单操作符，绝无 eval）。

    语义：叶子（field/op/value）与 all（全部成立）与 any（任一成立，
    为空时视为 True）三者取合取；纯组合节点可省略叶子。

    Args:
        condition: DSL 字典（或其嵌套）。
        context: 事实上下文（缺失字段视为不成立，不抛错）。

    Returns:
        条件是否成立。

    Raises:
        ValueError: DSL 结构非法（未知字段/操作符/键、类型错误）。
    """
    _validate_node(condition)
    assert isinstance(condition, dict)
    if "field" in condition and condition["field"] not in context:
        return False
    leaf_ok = True
    if "field" in condition:
        leaf_ok = _compare(condition["op"], context[condition["field"]], condition["value"])
    all_ok = all(evaluate_condition(child, context) for child in condition.get("all", []))
    any_children = condition.get("any", [])
    any_ok = True if not any_children else any(
        evaluate_condition(child, context) for child in any_children
    )
    return bool(leaf_ok and all_ok and any_ok)


@dataclass(frozen=True)
class RuleSpec:
    """领域层规则视图（ORM ScoreRule 的纯数据投影，便于单测构造）。"""

    rule_id: str
    rule_type: str
    name: str
    condition: Mapping[str, Any]
    score_change: int
    priority: int = 0
    enabled: bool = True


@dataclass(frozen=True)
class ScoreEffect:
    """规则应用结果：总分变动 + 命中的规则 + 人话理由。"""

    total_change: int
    matched_rule_ids: tuple[str, ...]
    reasons: tuple[str, ...]


def apply_rules(
    rules: Sequence[RuleSpec], context: Mapping[str, Any]
) -> ScoreEffect:
    """应用全部启用规则：按 priority 降序、rule_id 升序求值并累加分值。

    Args:
        rules: 待评估的规则序列。
        context: 事实上下文。

    Returns:
        累加后的总分变动与命中明细；无命中时 total_change 为 0。

    Raises:
        ValueError: 任一规则 DSL 非法（快速失败，不静默跳过坏规则）。
    """
    ordered = sorted(rules, key=lambda item: (-item.priority, item.rule_id))
    total = 0
    matched: list[str] = []
    reasons: list[str] = []
    for rule in ordered:
        if not rule.enabled:
            continue
        if evaluate_condition(rule.condition, context):
            total += rule.score_change
            matched.append(rule.rule_id)
            reasons.append(f"{rule.name}({rule.rule_id})：{rule.score_change:+d}分")
    return ScoreEffect(
        total_change=total,
        matched_rule_ids=tuple(matched),
        reasons=tuple(reasons),
    )

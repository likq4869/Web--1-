"""决策话术提示词：系统提示词 + 脱敏输入构造（PII 永不入提示词）。

职责：提供说明书 §8.5 约束下的 SYSTEM_PROMPT，以及仅含脱敏
结构化字段的用户输入构造器。
依赖：仅标准库 json。
边界：输入只允许 level / action / score_delta / factors(name/value) /
streak_days / score_balance / appeal_count；调用方不得传入姓名、
电话、学号、身份证等任何身份信息（构造器不接收此类参数，
从签名层面杜绝 PII）。
"""

from __future__ import annotations

import json

SYSTEM_PROMPT = """你是校园安全教育助手。
给定一条处罚决策及其结构化因子，生成一句面向学生的话术。要求：
1. 客观陈述事实，不指责人格；
2. 指出可改进的具体行为；
3. 给出正向出口（如何快速恢复积分）；
4. 语气平和，60 字以内；
5. 不出现任何“罚款”“扣钱”“处罚个人”表述；
6. 不承诺任何超出系统权限的承诺。
只输出话术正文，不要输出解释、前后缀或 JSON。"""


def build_user_payload(
    *,
    level: str,
    action: str,
    score_delta: int,
    factors: list[dict[str, object]],
    streak_days: int,
    score_balance: int,
    appeal_count: int,
) -> str:
    """构造用户输入 JSON（仅脱敏结构化字段）。

    Args:
        level: 决策档位（L0~L4）。
        action: 决策动作。
        score_delta: 分值变动。
        factors: 因子摘要列表，每项仅含 name/value。
        streak_days: 连续合规天数。
        score_balance: 当前积分。
        appeal_count: 历史申诉提交次数。

    Returns:
        JSON 字符串（中文，键顺序稳定，便于日志与测试断言）。
    """
    slim_factors = [
        {"name": str(item.get("name", "")), "value": item.get("value", 0)}
        for item in factors
    ]
    payload = {
        "level": level,
        "action": action,
        "score_delta": score_delta,
        "factors": slim_factors,
        "streak_days": streak_days,
        "score_balance": score_balance,
        "appeal_count": appeal_count,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


__all__ = ["SYSTEM_PROMPT", "build_user_payload"]

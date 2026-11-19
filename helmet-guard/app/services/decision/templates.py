"""决策话术模板库：按档位 × 场景分类（默认链路，零外部依赖）。

职责：提供 20+ 条预置模板，风格为客观陈述事实 + 具体改进建议 +
正向出口，不指责人格；每条 ≤80 字。
依赖：仅标准库。
边界：纯数据 + 纯选择函数；不做网络调用，不含任何 PII 占位符。
"""

from __future__ import annotations

# 模板键：(level, scenario)。scenario 与原因码/事实场景对应，
# 由 message.py 的选择函数映射，不向 LLM 或前端暴露内部编号。
TEMPLATES: dict[tuple[str, str], str] = {
    ("L0", "not_bare"): "本次通行已佩戴头盔或画面不清未予判定，请继续保持规范骑行。",
    ("L0", "identity_uncertain"): "本次疑似未戴盔但身份无法确认，已记入待识别，不做处罚。",
    ("L0", "low_confidence"): "本次检测置信度不足，已记录不做处罚，出行请佩戴头盔。",
    ("L0", "no_target"): "本次通行合规，继续保持即可累积连续合规天数。",
    ("L1", "first"): "检测到您本次骑行未佩戴头盔，已提醒一次，不扣分。请戴盔后再上路。",
    ("L1", "reminder"): "本次未佩戴头盔，已记录提醒。佩戴头盔可保持积分，下次出行请提前戴好。",
    ("L1", "peak"): "早晚高峰骑行请务必佩戴头盔，本次仅提醒，平安出行最重要。",
    ("L1", "night"): "夜间视线不佳，本次未戴盔仅作提醒，请佩戴头盔保障安全。",
    ("L2", "repeat_30d"): "本次未佩戴头盔，近30天内再次发生，扣1分。戴盔出行即可止损，可申诉。",
    ("L2", "repeat_7d"): "近7天内再次未戴盔骑行，扣1分。连续合规可逐步恢复积分。",
    ("L2", "same_point"): "您在同一路段再次未戴盔，扣1分。建议固定位置备一顶头盔。",
    ("L2", "streak_keep"): "本次未戴盔扣1分，您此前连续合规表现不错，重新戴盔即可延续好记录。",
    ("L2", "appeal_hint"): "本次未戴盔扣1分，如有误判可在我的-处罚记录中申诉，我们会复核。",
    ("L3", "high_frequency"): "近30天多次未戴盔骑行，扣3分。请立即整改，持续合规可恢复积分。",
    ("L3", "same_point_severe"): "同路段多次未戴盔，扣3分。请在该路段出行前确认佩戴，可申诉。",
    ("L3", "report"): "多次未戴盔已上报，扣3分。即日起坚持戴盔，积分将随合规逐步恢复。",
    ("L3", "correct"): "本次判定为高频违规，扣3分。现在开始每次戴盔，是恢复信用的最快方式。",
    ("L3", "final_warn"): "违规频次已达较严重程度，扣3分。请务必整改，避免进一步措施。",
    ("L4", "streak"): "您已连续合规骑行，加2分奖励。感谢坚持，请继续保持。",
    ("L4", "excellent"): "您已长期坚持合规骑行，加2分奖励。您是校园安全骑行的榜样。",
    ("L4", "keep"): "合规记录持续累积中，继续佩戴头盔即可解锁更高奖励。",
    ("L4", "share"): "坚持戴盔的您值得点赞，欢迎带动身边同学一起安全骑行。",
}

DEFAULT_TEMPLATE = "本次通行记录已生成，请佩戴头盔安全骑行，感谢配合。"


def select_template(level: str, scenario: str) -> str:
    """按档位 × 场景取模板；缺失时回退同档首条或默认文案。

    Args:
        level: 档位（L0~L4）。
        scenario: 场景键（如 first/repeat_30d/high_frequency）。

    Returns:
        模板正文（恒非空）。
    """
    direct = TEMPLATES.get((level, scenario))
    if direct:
        return direct
    for (item_level, _), text in TEMPLATES.items():
        if item_level == level:
            return text
    return DEFAULT_TEMPLATE


def all_templates() -> dict[tuple[str, str], str]:
    """返回模板全集的浅拷贝（供测试与运营盘点）。"""
    return dict(TEMPLATES)


__all__ = ["DEFAULT_TEMPLATE", "TEMPLATES", "all_templates", "select_template"]

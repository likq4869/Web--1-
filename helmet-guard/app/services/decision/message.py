"""决策话术服务：模板优先，LLM 仅做解释增强（永不参与决策）。

职责：为已确定的 (Fact, DecisionResult) 生成面向学生的展示文案；
默认走本地模板库；仅在显式开启且配置齐备时才调 LLM，且输出
必须通过长度/敏感词/联系方式校验，否则回退模板。
依赖：app.domain.decision（Fact/Result 类型）、app.ai。
边界：只读 Fact/Result 的脱敏字段；绝不接收学号/姓名/电话等 PII；
LLM 失败一律回退模板，不抛异常，不影响主流程。
"""

from __future__ import annotations

import re
from typing import Any

from app.ai.llm_client import LLMClient, LLMConfig
from app.ai.prompts.decision_message import SYSTEM_PROMPT, build_user_payload
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.domain.decision import DecisionResult, Fact
from app.services.decision.templates import select_template

_LOGGER = get_logger(__name__)

# 展示文案上限：LLM 输出 ≤120 字（任务约束）；模板库保证 ≤80 字。
MAX_MESSAGE_CHARS = 120
# 模板库上限（运营约束，测试中强制断言）。
MAX_TEMPLATE_CHARS = 80

# 敏感词表：出现任一即判不合格，回退模板。
SENSITIVE_WORDS = (
    "罚款",
    "罚钱",
    "扣钱",
    "处罚",
    "记过",
    "处分",
    "通报批评",
    "开除",
    "拘留",
)

_URL_RE = re.compile(r"(https?://|www\.)", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 外部联系方式：11 位手机号、400/座机形态、连续 7+ 位数字（QQ/电话）。
_PHONE_RE = re.compile(
    r"(1\d{10}|400\d{7}|0\d{2,3}-?\d{7,8}|\d{7,11})"
)


def scenario_for(fact: Fact, result: DecisionResult) -> str:
    """按档位 × 事实映射模板场景键（纯函数，可单测）。

    Args:
        fact: 原子事实。
        result: 已确定的决策结果（只读 level/reason）。

    Returns:
        模板场景键。
    """
    level = result.level.value if hasattr(result.level, "value") else str(result.level)
    reason = (
        result.reason_code.value
        if hasattr(result.reason_code, "value")
        else str(result.reason_code)
    )
    if level == "L0":
        if reason == "NOT_BARE":
            return "not_bare"
        if reason == "IDENTITY_UNCERTAIN":
            return "identity_uncertain"
        if reason == "LOW_CONFIDENCE":
            return "low_confidence"
        return "no_target"
    if level == "L1":
        if fact.peak_hour:
            return "peak"
        if fact.violation_count_30d <= 0:
            return "first"
        return "reminder"
    if level == "L2":
        if fact.repeat_same_point or fact.violation_count_1h_same_point >= 2:
            return "same_point"
        if fact.violation_count_7d >= 1:
            return "repeat_7d"
        if fact.appeal_history_total > 0:
            return "appeal_hint"
        if fact.streak_days >= 7:
            return "streak_keep"
        return "repeat_30d"
    if level == "L3":
        if fact.repeat_same_point or fact.violation_count_1h_same_point >= 2:
            return "same_point_severe"
        if reason == "HIGH_FREQUENCY":
            return "high_frequency"
        if fact.violation_count_30d >= 5:
            return "final_warn"
        return "correct"
    # L4 及未知：一律走奖励模板。
    if fact.streak_days >= 60:
        return "excellent"
    if fact.streak_days >= 45:
        return "share"
    if fact.streak_days >= 30:
        return "streak"
    return "keep"


def validate_message(text: str) -> tuple[bool, str]:
    """校验 LLM 输出；返回 (是否通过, 原因)。

    Args:
        text: 待校验文案。

    Returns:
        (通过与否, 原因说明)。
    """
    stripped = text.strip()
    if not stripped:
        return False, "empty"
    if len(stripped) > MAX_MESSAGE_CHARS:
        return False, f"too_long:{len(stripped)}"
    for word in SENSITIVE_WORDS:
        if word in stripped:
            return False, f"sensitive:{word}"
    if _URL_RE.search(stripped):
        return False, "url_forbidden"
    if _EMAIL_RE.search(stripped):
        return False, "email_forbidden"
    if _PHONE_RE.search(stripped):
        return False, "phone_forbidden"
    return True, "ok"


def should_use_llm(settings: Settings | None = None) -> bool:
    """判定是否允许调用 LLM（显式开启 + 三件套齐备）。

    Args:
        settings: 应用配置；缺省读单例。

    Returns:
        允许调用返回 True，否则 False（默认 False，走模板）。
    """
    cfg = settings or get_settings()
    enabled = bool(getattr(cfg, "llm_enabled", False))
    if not enabled:
        return False
    return bool(
        cfg.llm_base_url.strip()
        and cfg.llm_model.strip()
        and cfg.resolved_llm_api_key.strip()
    )


def build_llm_client(settings: Settings | None = None) -> LLMClient | None:
    """按配置构造 LLM 客户端；条件不足返回 None（调用方回退模板）。

    Args:
        settings: 应用配置；缺省读单例。
    """
    cfg = settings or get_settings()
    if not should_use_llm(cfg):
        return None
    return LLMClient(
        LLMConfig(
            api_key=cfg.resolved_llm_api_key,
            base_url=cfg.llm_base_url.strip(),
            model=cfg.llm_model.strip(),
        )
    )


def generate_message(
    fact: Fact,
    result: DecisionResult,
    *,
    client: LLMClient | None = None,
    settings: Settings | None = None,
) -> str:
    """生成展示文案：模板优先，LLM 可选增强，失败回退模板。

    Args:
        fact: 原子事实（仅读脱敏字段）。
        result: 决策结果（只读 level/action/delta/factors）。
        client: 可注入的 LLM 客户端（测试用假客户端；缺省按配置构造）。
        settings: 可注入的配置（测试用）。

    Returns:
        展示文案（恒非空；默认即模板，LLM 仅在显式开启时尝试）。
    """
    level = result.level.value if hasattr(result.level, "value") else str(result.level)
    template = select_template(level, scenario_for(fact, result))
    active_client = client if client is not None else build_llm_client(settings)
    if active_client is None:
        return template
    try:
        payload = build_user_payload(
            level=level,
            action=(
                result.action.value
                if hasattr(result.action, "value")
                else str(result.action)
            ),
            score_delta=int(result.score_delta),
            factors=[
                {"name": f.name, "value": f.value}
                for f in result.factors
            ],
            streak_days=int(fact.streak_days),
            score_balance=int(fact.score_balance),
            appeal_count=int(fact.appeal_history_total),
        )
    except Exception as exc:  # noqa: BLE001  # 输入异常直接回退模板。
        _LOGGER.warning("message.payload_failed", error=str(exc)[:200])
        return template
    text: str | None
    try:
        text = active_client.generate(SYSTEM_PROMPT, payload)
    except Exception as exc:  # noqa: BLE001  # 任何客户端异常都回退模板。
        _LOGGER.warning("message.llm_failed", error=str(exc)[:200])
        return template
    if text is None:
        return template
    ok, reason = validate_message(text)
    if not ok:
        _LOGGER.warning("message.validation_failed", reason=reason)
        return template
    return text.strip()


def describe_plan(fact: Fact, result: DecisionResult) -> dict[str, Any]:
    """返回话术决策计划（供日志与测试断言，不含 PII）。

    Args:
        fact: 原子事实。
        result: 决策结果。
    """
    level = result.level.value if hasattr(result.level, "value") else str(result.level)
    scenario = scenario_for(fact, result)
    return {
        "level": level,
        "scenario": scenario,
        "template": select_template(level, scenario),
        "max_chars": MAX_MESSAGE_CHARS,
    }


__all__ = [
    "MAX_MESSAGE_CHARS",
    "MAX_TEMPLATE_CHARS",
    "SENSITIVE_WORDS",
    "build_llm_client",
    "describe_plan",
    "generate_message",
    "scenario_for",
    "should_use_llm",
    "validate_message",
]

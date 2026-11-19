"""P2-4 LLM 话术测试：模板覆盖、校验、降级、PII 隔离、决策隔离。"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import SecretStr

from app.ai.llm_client import LLMConfig
from app.ai.prompts.decision_message import SYSTEM_PROMPT, build_user_payload
from app.core.config import Settings
from app.domain.decision import (
    DecisionAction,
    DecisionLevel,
    DecisionPolicy,
    DecisionResult,
    Fact,
    ReasonCode,
    decide,
)
from app.services.decision.message import (
    MAX_MESSAGE_CHARS,
    SENSITIVE_WORDS,
    generate_message,
    scenario_for,
    should_use_llm,
    validate_message,
)
from app.services.decision.templates import TEMPLATES, select_template


def _fact(**overrides: object) -> Fact:
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


def _result_for(fact: Fact) -> DecisionResult:
    return decide(fact, DecisionPolicy())


class _FakeClient:
    """可注入的假 LLM 客户端：捕获提示词，返回预设文本。"""

    def __init__(self, text: str | None, *, explode: bool = False) -> None:
        self.text = text
        self.explode = explode
        self.captured_system: str | None = None
        self.captured_user: str | None = None
        self.calls = 0

    def generate(self, system_prompt: str, user_payload: str) -> str | None:
        self.calls += 1
        self.captured_system = system_prompt
        self.captured_user = user_payload
        if self.explode:
            raise RuntimeError("boom")
        return self.text


class _NoneClient:
    """模拟 LLM 不可用（返回 None）。"""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, system_prompt: str, user_payload: str) -> str | None:
        self.calls += 1
        return None


def _settings_disabled() -> Settings:
    return Settings(
        app_env="test", jwt_secret=SecretStr("s"), llm_enabled=False
    )


def test_templates_cover_all_levels_and_length() -> None:
    assert len(TEMPLATES) >= 20
    levels = {level for level, _ in TEMPLATES}
    assert {"L0", "L1", "L2", "L3", "L4"} <= levels
    for key, text in TEMPLATES.items():
        assert text and len(text) <= 80, f"{key} 超长或为空：{text!r}"


def test_default_path_uses_template_without_llm() -> None:
    fact = _fact()
    result = _result_for(fact)
    expected = select_template(result.level.value, scenario_for(fact, result))
    assert generate_message(fact, result, settings=_settings_disabled()) == expected


def test_sensitive_word_fallback_to_template() -> None:
    fact = _fact(violation_count_30d=1)
    result = _result_for(fact)
    template = select_template(result.level.value, scenario_for(fact, result))
    fake = _FakeClient(f"本次扣分{SENSITIVE_WORDS[0]}请注意")
    assert generate_message(fact, result, client=fake) == template  # type: ignore[arg-type]
    assert fake.calls == 1


def test_too_long_output_rejected() -> None:
    fact = _fact()
    result = _result_for(fact)
    template = select_template(result.level.value, scenario_for(fact, result))
    fake = _FakeClient("好" * (MAX_MESSAGE_CHARS + 1))
    assert generate_message(fact, result, client=fake) == template  # type: ignore[arg-type]


def test_contact_info_rejected() -> None:
    fact = _fact()
    result = _result_for(fact)
    template = select_template(result.level.value, scenario_for(fact, result))
    for bad in (
        "请访问 https://example.com 申诉",
        "联系 admin@example.com 处理",
        "拨打 13800001111 咨询",
    ):
        fake = _FakeClient(bad)
        got = generate_message(fact, result, client=fake)  # type: ignore[arg-type]
        assert got == template, f"联系方式未被拦截：{bad!r}"


def test_llm_unavailable_falls_back() -> None:
    fact = _fact()
    result = _result_for(fact)
    template = select_template(result.level.value, scenario_for(fact, result))
    none_client = _NoneClient()
    assert generate_message(fact, result, client=none_client) == template  # type: ignore[arg-type]
    boom = _FakeClient("ok", explode=True)
    assert generate_message(fact, result, client=boom) == template  # type: ignore[arg-type]


def test_valid_llm_output_accepted() -> None:
    fact = _fact()
    result = _result_for(fact)
    good = "本次未戴盔已提醒，请佩戴头盔后再上路，连续合规可累积奖励。"
    fake = _FakeClient(good)
    assert generate_message(fact, result, client=fake) == good  # type: ignore[arg-type]


def test_prompt_contains_no_pii() -> None:
    fact = _fact()
    result = _result_for(fact)
    good = "本次未戴盔已提醒，请佩戴头盔，感谢配合。"
    fake = _FakeClient(good)
    generate_message(fact, result, client=fake)  # type: ignore[arg-type]
    assert fake.captured_system == SYSTEM_PROMPT
    assert fake.captured_user is not None
    payload = json.loads(fake.captured_user)
    assert set(payload.keys()) == {
        "level", "action", "score_delta", "factors",
        "streak_days", "score_balance", "appeal_count",
    }
    blob = fake.captured_user
    for pii in ("张三", "138", "S001", "2024000001", "身份证", "510100"):
        assert pii not in blob
    for item in payload["factors"]:
        assert set(item.keys()) == {"name", "value"}


def test_should_use_llm_gating() -> None:
    assert should_use_llm(_settings_disabled()) is False
    missing = Settings(
        app_env="test", jwt_secret=SecretStr("s"), llm_enabled=True,
        llm_base_url="", llm_model="", llm_api_key=SecretStr(""),
    )
    assert should_use_llm(missing) is False
    ready = Settings(
        app_env="test", jwt_secret=SecretStr("s"), llm_enabled=True,
        llm_base_url="https://llm.test/v1", llm_model="m",
        llm_api_key=SecretStr("k"),
    )
    assert should_use_llm(ready) is True


def test_system_prompt_matches_spec() -> None:
    for line in (
        "客观陈述事实，不指责人格",
        "指出可改进的具体行为",
        "给出正向出口",
        "语气平和，60 字以内",
        "不出现任何“罚款”",
        "不承诺任何超出系统权限的承诺",
    ):
        assert line in SYSTEM_PROMPT


def test_user_payload_only_slim_fields() -> None:
    payload = build_user_payload(
        level="L2", action="deduct_score", score_delta=-1,
        factors=[{"name": "历史", "value": 1, "evidence": "x", "weight": 0.5}],
        streak_days=12, score_balance=95, appeal_count=0,
    )
    data = json.loads(payload)
    assert data["factors"] == [{"name": "历史", "value": 1}]


def test_domain_does_not_import_ai() -> None:
    domain_dir = Path(__file__).resolve().parent.parent / "app" / "domain"
    for name in ("decision.py", "decision_rules.py", "circuit_breaker.py"):
        source = (domain_dir / name).read_text(encoding="utf-8")
        assert "app.ai" not in source
        assert "app/ai" not in source
        assert "app.services" not in source
        assert "LLMClient" not in source


def test_llm_config_defaults_timeout() -> None:
    cfg = LLMConfig(api_key="k", base_url="https://x/v1", model="m")
    assert cfg.timeout_seconds == 10.0


def test_validate_message_rules() -> None:
    assert validate_message("")[0] is False
    assert validate_message("x" * 121)[0] is False
    assert validate_message("正常提醒，请戴盔。")[0] is True
    assert validate_message("含罚款字样")[0] is False


def test_award_and_l0_templates_selected() -> None:
    l4_fact = _fact(helmet_status="helmeted", streak_days=30)
    l4_result = DecisionResult(
        level=DecisionLevel.L4, action=DecisionAction.AWARD, score_delta=2,
        reason_code=ReasonCode.STREAK_BONUS, confidence=0.9, factors=(),
        message="t", needs_human_review=True,
    )
    assert generate_message(
        l4_fact, l4_result, settings=_settings_disabled()
    )
    l0_fact = _fact(helmet_status="helmeted")
    l0_result = decide(l0_fact, DecisionPolicy())
    assert l0_result.level is DecisionLevel.L0
    assert generate_message(
        l0_fact, l0_result, settings=_settings_disabled()
    )

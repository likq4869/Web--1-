"""LLM 客户端：OpenAI 兼容 API 封装（只做解释，不做决策）。

职责：收敛所有外部 LLM 调用，提供超时 + 重试 + 降级语义。
依赖：httpx、tenacity、app.core.logging。
边界：只收发脱敏的结构化提示词；绝不接收/发送姓名、手机、
学号、身份证等 PII；失败一律返回 None，不向调用方抛异常。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.logging import get_logger

_LOGGER = get_logger(__name__)

# 任务约束：超时 10s、最多重试 2 次（即最多 3 次尝试）、指数退避。
LLM_TIMEOUT_SECONDS = 10.0
LLM_MAX_ATTEMPTS = 3
LLM_RETRY_MIN_WAIT = 1.0
LLM_RETRY_MAX_WAIT = 4.0


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """LLM 连接配置（全部来自 Settings，不含任何 PII）。

    Attributes:
        api_key: API 密钥（仅内存持有，绝不写入日志）。
        base_url: OpenAI 兼容接口地址。
        model: 模型名称。
        timeout_seconds: 单次请求超时（默认 10s）。
    """

    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = LLM_TIMEOUT_SECONDS


class LLMClient:
    """OpenAI 兼容 API 客户端（同步，带降级）。

    调用失败（超时/网络/非 2xx/空回复）一律返回 None，由调用方
    回退模板，保证主流程不受影响。
    """

    def __init__(self, config: LLMConfig) -> None:
        """初始化客户端。

        Args:
            config: 连接配置。
        """
        self._config = config

    @property
    def model(self) -> str:
        """返回模型名称。"""
        return self._config.model

    def generate(self, system_prompt: str, user_payload: str) -> str | None:
        """生成话术（失败返回 None，不抛异常）。

        Args:
            system_prompt: 系统提示词（脱敏，见 prompts 模块）。
            user_payload: 用户输入 JSON 字符串（仅结构化脱敏字段）。

        Returns:
            模型输出文本；失败时返回 None。
        """
        try:
            return self._generate_with_retry(system_prompt, user_payload)
        except Exception as exc:  # noqa: BLE001  # 降级语义：任何异常都吞并回退。
            _LOGGER.warning(
                "llm.generate_failed",
                model=self._config.model,
                error=str(exc)[:200],
            )
            return None

    @retry(
        stop=stop_after_attempt(LLM_MAX_ATTEMPTS),
        wait=wait_exponential(
            min=LLM_RETRY_MIN_WAIT, max=LLM_RETRY_MAX_WAIT
        ),
        retry=retry_if_exception_type((httpx.HTTPError, ValueError)),
        reraise=True,
    )
    def _generate_with_retry(
        self, system_prompt: str, user_payload: str
    ) -> str | None:
        """带重试的单次生成（重试耗尽后抛给外层降级）。"""
        url = self._config.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
            "temperature": 0.7,
            "max_tokens": 200,
        }
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        # 结构化日志：只记长度与模型，不记正文（正文可能含业务因子，
        # 且为后续审计保留最小面；调用方如需审计可另行落库脱敏字段）。
        _LOGGER.info(
            "llm.request",
            model=self._config.model,
            system_len=len(system_prompt),
            user_len=len(user_payload),
        )
        with httpx.Client(timeout=self._config.timeout_seconds) as client:
            response = client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            _LOGGER.warning(
                "llm.bad_status",
                model=self._config.model,
                status=response.status_code,
                body=response.text[:200],
            )
            raise ValueError(f"LLM 接口异常：{response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            _LOGGER.warning("llm.bad_json", model=self._config.model,
                            error=str(exc)[:200])
            raise
        text = self._extract_text(data)
        if not text:
            _LOGGER.warning("llm.empty_response", model=self._config.model)
            raise ValueError("LLM 返回为空")
        _LOGGER.info(
            "llm.response",
            model=self._config.model,
            response_len=len(text),
        )
        return text

    @staticmethod
    def _extract_text(data: Any) -> str | None:
        """从 OpenAI 兼容响应中提取正文；结构不符返回 None。"""
        try:
            choices = data.get("choices") if isinstance(data, dict) else None
            if not choices:
                return None
            message = choices[0].get("message", {})
            content = message.get("content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
            return None
        except (AttributeError, IndexError, KeyError):
            return None


__all__ = [
    "LLM_MAX_ATTEMPTS",
    "LLM_TIMEOUT_SECONDS",
    "LLMClient",
    "LLMConfig",
]

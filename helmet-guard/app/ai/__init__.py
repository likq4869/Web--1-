"""AI 能力包：LLM 客户端与提示词（仅做解释，不做决策）。

职责：收敛所有对外部 LLM 的调用与提示词构造；领域层绝不导入本包。
依赖：httpx、tenacity、structlog（经 app.core.logging）。
边界：只生成自然语言解释；不输出 level/action/score_delta，
不接收任何个人身份信息（PII）。
"""

from app.ai.llm_client import LLMClient

__all__ = ["LLMClient"]

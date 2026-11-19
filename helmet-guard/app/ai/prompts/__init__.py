"""话术提示词包（脱敏输入，PII 永不入提示词）。"""

from app.ai.prompts.decision_message import (
    SYSTEM_PROMPT,
    build_user_payload,
)

__all__ = ["SYSTEM_PROMPT", "build_user_payload"]

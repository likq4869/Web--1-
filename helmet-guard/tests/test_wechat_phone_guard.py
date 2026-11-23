"""手机号解析安全守卫测试（真实模式禁直传 phone）。

职责：锁定 `WechatClient.resolve_phone` 的两条分支语义——
- 真实模式（配置了 AppID/Secret）：直传 phone 必须被拒（防手机号伪造 / 身份冒用）；
- Mock 模式（未配置 AppID/Secret）：直传 phone 放行（开发联调）。

边界：不触网、不打微信接口；只验证守卫分支与异常类型。
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.auth.wechat_client import WechatClient


def _client(*, real: bool) -> WechatClient:
    """构造 WechatClient：real=True 时配齐 AppID/Secret（真实模式）。"""
    settings = Settings(
        wechat_appid="wxd98e743255dc4cae" if real else "",
        wechat_secret="test-secret-not-for-production" if real else "",
    )
    return WechatClient(settings)


def test_real_mode_rejects_raw_phone() -> None:
    """真实模式：直传 phone 必须被拒（不返回号码）。"""
    client = _client(real=True)
    assert client.is_mock is False

    with pytest.raises(Exception) as exc:
        client.resolve_phone(None, "13800138000")

    assert "生产环境不接受直传手机号" in str(exc.value)


def test_real_mode_accepts_phone_code_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实模式：带 phone_code 时走微信解析分支（此处打桩避免触网）。"""
    client = _client(real=True)

    called: list[str] = []

    def _fake_phone_by_code(self: WechatClient, code: str) -> str:
        called.append(code)
        return "13800138000"

    # WechatClient 是 frozen dataclass，实例与属性都不可赋值；只能打桩类级方法。
    monkeypatch.setattr(WechatClient, "_phone_by_code", _fake_phone_by_code)

    assert client.resolve_phone("  phone-code-123 ", None) == "13800138000"
    assert called == ["phone-code-123"]


def test_mock_mode_allows_raw_phone() -> None:
    """Mock 模式：直传 phone 放行（开发联调通道保留）。"""
    client = _client(real=False)
    assert client.is_mock is True

    assert client.resolve_phone(None, " 13800138000 ") == "13800138000"


def test_mock_mode_rejects_phone_code_only() -> None:
    """Mock 模式：只给 code 无法解出真实号码，必须给出可执行的引导错误。"""
    client = _client(real=False)

    with pytest.raises(Exception) as exc:
        client.resolve_phone("phone-code-123", None)

    assert "Mock 模式无法通过 code 解析手机号" in str(exc.value)


def test_missing_credentials_rejected() -> None:
    """两种模式都缺凭证时一律拒绝（不返回空串）。"""
    for real in (True, False):
        client = _client(real=real)
        with pytest.raises(Exception) as exc:
            client.resolve_phone(None, None)
        assert "缺少手机号凭证" in str(exc.value)


__all__ = [
    "test_real_mode_rejects_raw_phone",
    "test_real_mode_accepts_phone_code_path",
    "test_mock_mode_allows_raw_phone",
    "test_mock_mode_rejects_phone_code_only",
    "test_missing_credentials_rejected",
]

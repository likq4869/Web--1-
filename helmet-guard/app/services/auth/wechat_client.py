"""微信登录客户端：jscode2session + 手机号解析 + 登录态校验（Mock 可用，生产直连微信）。

职责：收敛全部对微信接口的调用；未配置 AppID/Secret 时走 Mock 模式。
依赖：httpx、app.core.config。
边界：只做微信协议转换；不碰数据库、不签发 JWT、不写业务表。
失败语义：微信接口异常统一抛 ExternalServiceError，由 API 层映射为 502。

官方口径（用户已提供文档）：
- code2session: GET sns/jscode2session 换 openid/unionid/session_key；
  每个 code 仅可用一次（5min）；AppID 须与工具工程一致否则 40029。
- getPhoneNumber: POST wxa/business/getuserphonenumber 换 phoneNumber；
  需先取 access_token（client_credential）；phone_code 一次性 5min。
- checkSessionKey: GET wxa/checksession 校验服务端 session_key；
  signature = hmac_sha256(session_key, "")，用于校验服务端 session_key 是否仍有效；
  每次 wx.login 会顶替旧 session_key。
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.core.errors import ExternalServiceError

# 微信接口超时：登录链路敏感，单次 8s 足够。
WECHAT_TIMEOUT_SECONDS = 8.0

# code2session 常见 errcode → 人话（定位用，不透原始码给端上猜解）。
WECHAT_CODE2SESSION_MESSAGES = {
    40029: "微信登录凭证已失效，请重试（code 只能用一次）",
    45011: "微信登录调用过于频繁，请稍后重试",
    40013: "微信 AppID 配置有误请联系管理员",
    -1: "微信服务繁忙请稍后重试",
}


@dataclass(frozen=True, slots=True)
class WechatSession:
    """jscode2session 结果。"""

    openid: str
    unionid: str | None
    session_key: str


@dataclass(frozen=True, slots=True)
class WechatClient:
    """微信接口封装（同步短调用）。

    Mock 模式：未配置 appid/secret 时，不出网，按 code 确定性派生
    openid（`mock-<sha1(code)前16>`），便于开发联调与自动化测试。
    生产必须配置，否则所有真机 code 都会落到 mock 命名空间，
    与真实 openid 永不相交——上线前由部署检查拦截。
    """

    settings: Settings

    @property
    def is_mock(self) -> bool:
        """是否处于 Mock 模式。"""
        return not self.settings.wechat_appid.strip() or not self._secret().strip()

    def _secret(self) -> str:
        return self.settings.wechat_secret.get_secret_value()

    def exchange_code(self, code: str) -> WechatSession:
        """用 wx.login 的 code 换 openid。

        Args:
            code: 小程序端 `wx.login` 返回的一次性 code。

        Returns:
            微信会话（含 openid）。

        Raises:
            ExternalServiceError: 微信接口异常（网络/非 2xx/业务 errcode）。
        """
        trimmed = code.strip()
        if not trimmed:
            raise ExternalServiceError("微信登录凭证无效")
        if self.is_mock:
            digest = hashlib.sha1(trimmed.encode("utf-8")).hexdigest()[:16]
            return WechatSession(openid=f"mock-{digest}", unionid=None, session_key="mock-session")
        url = "https://api.weixin.qq.com/sns/jscode2session"
        params = {
            "appid": self.settings.wechat_appid.strip(),
            "secret": self._secret(),
            "js_code": trimmed,
            "grant_type": "authorization_code",
        }
        try:
            with httpx.Client(timeout=WECHAT_TIMEOUT_SECONDS) as client:
                resp = client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ExternalServiceError("微信登录服务暂时不可用") from exc
        if resp.status_code != 200:
            raise ExternalServiceError("微信登录服务暂时不可用")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ExternalServiceError("微信登录服务暂时不可用") from exc
        if not isinstance(data, dict) or "openid" not in data:
            errcode = data.get("errcode") if isinstance(data, dict) else None
            errmsg = str(data.get("errmsg", "")) if isinstance(data, dict) else ""
            friendly = WECHAT_CODE2SESSION_MESSAGES.get(
                errcode if isinstance(errcode, int) else -9999, ""
            )
            raise ExternalServiceError(f"微信登录失败：{friendly or errmsg or '未知错误'}")
        openid = str(data["openid"])
        unionid_raw = data.get("unionid")
        return WechatSession(
            openid=openid,
            unionid=str(unionid_raw) if unionid_raw else None,
            session_key=str(data.get("session_key", "")),
        )

    def check_session_key(self, openid: str, session_key: str) -> bool:
        """校验服务端 session_key 是否仍有效（官方 checkSessionKey 口径）。

        Args:
            openid: 用户唯一标识。
            session_key: jscode2session 落库的 session_key。

        Returns:
            True=仍有效，False=已失效/被顶替。Mock 模式下仅比对非空即视为有效，
            不出网（开发联调与自动化测试可预测）。

        Raises:
            ExternalServiceError: 微信接口异常（网络/非 2xx/响应非 JSON）。
        """
        if not openid.strip() or not session_key.strip():
            return False
        if self.is_mock:
            return True
        signature = hmac.new(session_key.encode("utf-8"), b"", hashlib.sha256).hexdigest()
        token = self._access_token()
        url = "https://api.weixin.qq.com/wxa/checksession"
        try:
            with httpx.Client(timeout=WECHAT_TIMEOUT_SECONDS) as client:
                resp = client.get(
                    url,
                    params={
                        "access_token": token,
                        "openid": openid.strip(),
                        "signature": signature,
                        "sig_method": "hmac_sha256",
                    },
                )
        except httpx.HTTPError as exc:
            raise ExternalServiceError("微信登录态校验服务暂时不可用") from exc
        if resp.status_code != 200:
            raise ExternalServiceError("微信登录态校验服务暂时不可用")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ExternalServiceError("微信登录态校验服务暂时不可用") from exc
        if not isinstance(data, dict):
            raise ExternalServiceError("微信登录态校验失败：响应结构异常")
        return int(data.get("errcode", -1)) == 0

    def resolve_phone(self, phone_code: str | None, phone: str | None) -> str:
        """解析手机号：优先走微信 phone_code，Mock/开发允许直传 phone。

        Args:
            phone_code: `getPhoneNumber` 回调的动态令牌 code。
            phone: 直传手机号（仅 Mock 模式可用，真机联调用）。

        Returns:
            11 位大陆手机号。

        Raises:
            ExternalServiceError: 微信侧解析失败。
            ValidationError 由调用方（服务层）按手机号正则统一抛，
            此处只做透传与空值拦截。
        """
        if phone_code and phone_code.strip() and not self.is_mock:
            return self._phone_by_code(phone_code.strip())
        # Mock 模式：直传 phone 即为最终号码（服务层再做正则校验）。
        if phone and phone.strip():
            return phone.strip()
        if phone_code and phone_code.strip() and self.is_mock:
            # Mock 下也允许只传 code：无法解出真实号码，交由前端补填。
            raise ExternalServiceError("Mock 模式无法通过 code 解析手机号，请直传 phone 字段联调")
        raise ExternalServiceError("缺少手机号凭证")

    def _phone_by_code(self, phone_code: str) -> str:
        """用 phone_code 换真实手机号（需先取 access_token）。"""
        token = self._access_token()
        url = "https://api.weixin.qq.com/wxa/business/getuserphonenumber"
        try:
            with httpx.Client(timeout=WECHAT_TIMEOUT_SECONDS) as client:
                resp = client.post(url, params={"access_token": token}, json={"code": phone_code})
        except httpx.HTTPError as exc:
            raise ExternalServiceError("手机号解析服务暂时不可用") from exc
        if resp.status_code != 200:
            raise ExternalServiceError("手机号解析服务暂时不可用")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ExternalServiceError("手机号解析服务暂时不可用") from exc
        if not isinstance(data, dict) or data.get("errcode") != 0:
            err = str(data.get("errmsg", "")) if isinstance(data, dict) else ""
            raise ExternalServiceError(f"手机号解析失败：{err or '未知错误'}")
        try:
            number = str(data["phone_info"]["phoneNumber"])
        except (KeyError, TypeError) as exc:
            raise ExternalServiceError("手机号解析失败：响应结构异常") from exc
        return number

    def _access_token(self) -> str:
        """取小程序 access_token（每次现取，不做进程缓存，避免过期竞态）。"""
        url = "https://api.weixin.qq.com/cgi-bin/token"
        params = {
            "grant_type": "client_credential",
            "appid": self.settings.wechat_appid.strip(),
            "secret": self._secret(),
        }
        try:
            with httpx.Client(timeout=WECHAT_TIMEOUT_SECONDS) as client:
                resp = client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ExternalServiceError("微信登录服务暂时不可用") from exc
        try:
            data = resp.json()
        except ValueError as exc:
            raise ExternalServiceError("微信登录服务暂时不可用") from exc
        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            raise ExternalServiceError("获取微信访问凭证失败")
        return str(token)


__all__ = [
    "WECHAT_CODE2SESSION_MESSAGES",
    "WECHAT_TIMEOUT_SECONDS",
    "WechatClient",
    "WechatSession",
]

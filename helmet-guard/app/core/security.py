"""安全基座：密码哈希、JWT 签发与校验、当前用户解析。

职责：提供与认证相关的纯安全能力。
依赖：bcrypt、python-jose、fastapi。
边界：不查询用户数据、不判定业务角色范围；只做令牌签发/校验与凭据比对。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import bcrypt
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError, ValidationError

ACCESS_TOKEN_TYPE: Final = "access"
REFRESH_TOKEN_TYPE: Final = "refresh"

# bcrypt 只处理前 72 字节，超长密码会被拒绝。
# 校验侧必须使用同一规则截断，否则长密码永远无法通过验证。
BCRYPT_MAX_BYTES: Final = 72

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """已校验的令牌载荷。

    Attributes:
        subject: 主体标识（用户 ID）。
        role: 角色标识。
        token_type: 令牌类型（access / refresh）。
        jti: 令牌唯一标识，便于吊销与审计。
        expires_at: 过期时间。
    """

    subject: str
    role: str
    token_type: str
    jti: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """当前请求的认证主体。

    Attributes:
        subject: 用户 ID。
        role: 角色标识。
        claims: 原始令牌声明，便于后续扩展。
    """

    subject: str
    role: str
    claims: dict[str, Any]


def _truncate_password(password: str) -> bytes:
    """按 bcrypt 规则截断密码字节。

    Args:
        password: 明文密码。

    Returns:
        最长 72 字节的 UTF-8 密码。
    """
    return password.encode("utf-8")[:BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """计算密码哈希。

    Args:
        password: 明文密码。

    Returns:
        bcrypt 哈希串。
    """
    hashed: bytes = bcrypt.hashpw(_truncate_password(password), bcrypt.gensalt())
    return hashed.decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """校验明文密码与哈希是否匹配。

    Args:
        password: 明文密码。
        password_hash: 已存储的哈希。

    Returns:
        匹配返回 True，否则返回 False。
    """
    try:
        verified: bool = bcrypt.checkpw(
            _truncate_password(password),
            password_hash.encode("ascii"),
        )
    except (ValueError, UnicodeEncodeError):
        # 非法哈希格式不应导致 500；按校验失败处理。
        return False
    return verified


def _encode(
    subject: str,
    role: str,
    token_type: str,
    expires_delta: timedelta,
    settings: Settings,
) -> str:
    """签发 JWT。

    Args:
        subject: 主体标识。
        role: 角色标识。
        token_type: 令牌类型。
        expires_delta: 有效期。
        settings: 应用配置。

    Returns:
        编码后的 JWT 字符串。

    Raises:
        ValidationError: 未配置 JWT 密钥时抛出。
    """
    if not settings.has_jwt_secret:
        raise ValidationError("服务未配置 JWT 密钥，无法签发令牌")
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": f"{subject}-{token_type}-{int(now.timestamp() * 1000)}",
    }
    return str(
        jwt.encode(
            payload,
            settings.resolved_jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
    )


def create_access_token(subject: str, role: str, settings: Settings | None = None) -> str:
    """签发访问令牌。

    Args:
        subject: 用户 ID。
        role: 角色标识。
        settings: 应用配置；缺省读取单例。

    Returns:
        JWT 字符串。
    """
    cfg = settings or get_settings()
    return _encode(
        subject,
        role,
        ACCESS_TOKEN_TYPE,
        timedelta(minutes=cfg.access_token_expire_minutes),
        cfg,
    )


def create_refresh_token(subject: str, role: str, settings: Settings | None = None) -> str:
    """签发刷新令牌。

    Args:
        subject: 用户 ID。
        role: 角色标识。
        settings: 应用配置；缺省读取单例。

    Returns:
        JWT 字符串。
    """
    cfg = settings or get_settings()
    return _encode(
        subject,
        role,
        REFRESH_TOKEN_TYPE,
        timedelta(days=cfg.refresh_token_expire_days),
        cfg,
    )


def decode_token(
    token: str,
    expected_type: str = ACCESS_TOKEN_TYPE,
    settings: Settings | None = None,
) -> TokenPayload:
    """解码并校验 JWT。

    Args:
        token: JWT 字符串。
        expected_type: 期望的令牌类型。
        settings: 应用配置；缺省读取单例。

    Returns:
        校验通过的令牌载荷。

    Raises:
        AuthenticationError: 令牌缺失、过期、签名错误或类型不符。
    """
    cfg = settings or get_settings()
    if not cfg.has_jwt_secret:
        raise AuthenticationError("服务未配置 JWT 密钥，无法校验令牌")
    try:
        claims = jwt.decode(
            token,
            cfg.resolved_jwt_secret,
            algorithms=[cfg.jwt_algorithm],
        )
    except JWTError as exc:
        raise AuthenticationError("登录状态无效或已过期，请重新登录") from exc

    subject = claims.get("sub")
    token_type = claims.get("type")
    if not isinstance(subject, str) or not subject:
        raise AuthenticationError("登录状态无效，请重新登录")
    if token_type != expected_type:
        raise AuthenticationError("令牌类型不正确，请重新登录")
    jti = claims.get("jti")
    expires_at = datetime.fromtimestamp(int(claims.get("exp", 0)), tz=UTC)
    role = claims.get("role")
    return TokenPayload(
        subject=subject,
        role=role if isinstance(role, str) else "",
        token_type=token_type,
        jti=jti if isinstance(jti, str) else "",
        expires_at=expires_at,
    )


def resolve_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> CurrentUser:
    """从请求头解析当前用户。

    Args:
        request: 当前请求，用于读取请求级上下文。
        credentials: 已解析的 Bearer 凭据。

    Returns:
        当前认证主体。

    Raises:
        AuthenticationError: 缺少凭据或令牌无效。
    """
    del request  # 预留：后续接入吊销名单等请求级状态时使用
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("请先登录后再访问")
    payload = decode_token(credentials.credentials, ACCESS_TOKEN_TYPE)
    # TokenPayload 是 slots dataclass，没有 __dict__，必须用 dataclasses.asdict 取字段。
    return CurrentUser(subject=payload.subject, role=payload.role, claims=asdict(payload))

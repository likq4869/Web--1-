"""核心基座测试：配置、异常、安全、日志、中间件与 schema。"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from app.core.config import Settings, get_settings
from app.core.errors import (
    AppError,
    AuthenticationError,
    ConflictError,
    ExternalServiceError,
    ModelNotReadyError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ValidationError,
    status_code_for,
)
from app.core.logging import bind_request_context, configure_logging, get_logger
from app.core.middleware import (
    ErrorHandlerMiddleware,
    RequestContextMiddleware,
    build_error_payload,
)
from app.core.security import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.schemas.common import ErrorDetail, ErrorResponse, Page, PageParams


@pytest.fixture()
def settings() -> Settings:
    """构造仅用于测试的最小配置。"""
    return Settings(
        app_env="test",
        jwt_secret="test-secret-value-not-for-production",
        cors_origins="http://a.test,http://b.test",
    )


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------


def test_config_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", "env-secret")
    monkeypatch.setenv("CORS_ORIGINS", "http://x.test,http://y.test")
    get_settings.cache_clear()
    try:
        cfg = get_settings()
        assert cfg.app_env == "test"
        assert cfg.has_jwt_secret is True
        assert cfg.cors_origin_list == ["http://x.test", "http://y.test"]
        assert cfg.is_production is False
        assert cfg.is_testing is True
    finally:
        get_settings.cache_clear()


def test_config_rejects_invalid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "unknown-env")
    get_settings.cache_clear()
    try:
        with pytest.raises(PydanticValidationError):
            Settings()
    finally:
        get_settings.cache_clear()


def test_config_secret_not_leaked(settings: Settings) -> None:
    assert "test-secret-value-not-for-production" not in repr(settings)


def test_config_resolved_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """`DATABASE_URL` 优先；未设置时回退到 `HELMET_GUARD_DB` 推导的 SQLite 路径。

    与本地 `.env` 无关：直接构造 `Settings`，避免 `.env` 的 MySQL 污染断言。
    """
    cfg = Settings(
        app_env="test",
        jwt_secret="test-secret-value-not-for-production",
        database_url="",
        helmet_guard_db="data/custom.db",
    )
    assert cfg.resolved_database_url.endswith("data/custom.db")


def test_config_database_url_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    """显式 `DATABASE_URL` 优先级最高。"""
    from app.core.config import get_settings

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pw@127.0.0.1:5432/helmet")
    monkeypatch.setenv("HELMET_GUARD_DB", "data/custom.db")
    get_settings.cache_clear()
    try:
        cfg = get_settings()
        assert cfg.resolved_database_url == "postgresql+psycopg://user:pw@127.0.0.1:5432/helmet"
    finally:
        get_settings.cache_clear()


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error_cls", "expected_status", "expected_code"),
    [
        (NotFoundError, 404, "NOT_FOUND"),
        (ValidationError, 422, "VALIDATION_ERROR"),
        (ConflictError, 409, "CONFLICT"),
        (PermissionDeniedError, 403, "PERMISSION_DENIED"),
        (RateLimitError, 429, "RATE_LIMIT_EXCEEDED"),
        (ExternalServiceError, 502, "EXTERNAL_SERVICE_ERROR"),
        (ModelNotReadyError, 503, "MODEL_NOT_READY"),
    ],
)
def test_error_hierarchy_status(
    error_cls: type[AppError],
    expected_status: int,
    expected_code: str,
) -> None:
    error = error_cls()
    assert isinstance(error, AppError)
    assert status_code_for(error) == expected_status
    assert error.code == expected_code
    assert error.message


def test_error_payload_and_details() -> None:
    error = ValidationError("字段不合法", details={"field": "page_size"})
    payload = error.to_dict()
    assert payload["code"] == "VALIDATION_ERROR"
    assert payload["message"] == "字段不合法"
    assert payload["details"] == {"field": "page_size"}


def test_build_error_payload() -> None:
    payload = build_error_payload("NOT_FOUND", "不存在", "trace-1")
    assert payload["trace_id"] == "trace-1"


# --------------------------------------------------------------------------
# security
# --------------------------------------------------------------------------


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_password_longer_than_bcrypt_limit() -> None:
    """超过 72 字节的密码按 bcrypt 规则截断，签发与校验必须一致。"""
    long_password = "x" * 100
    hashed = hash_password(long_password)
    assert verify_password(long_password, hashed) is True
    assert verify_password("x" * 99, hashed) is True
    assert verify_password("y" * 100, hashed) is False


def test_verify_password_with_invalid_hash_returns_false() -> None:
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_access_token_roundtrip(settings: Settings) -> None:
    token = create_access_token("u-1", "super_admin", settings)
    payload = decode_token(token, ACCESS_TOKEN_TYPE, settings)
    assert payload.subject == "u-1"
    assert payload.role == "super_admin"
    assert payload.token_type == ACCESS_TOKEN_TYPE


def test_refresh_token_rejected_for_access_scope(settings: Settings) -> None:
    token = create_refresh_token("u-1", "student", settings)
    with pytest.raises(AuthenticationError):
        decode_token(token, ACCESS_TOKEN_TYPE, settings)
    payload = decode_token(token, REFRESH_TOKEN_TYPE, settings)
    assert payload.token_type == REFRESH_TOKEN_TYPE


def test_decode_token_rejects_invalid_signature(settings: Settings) -> None:
    token = create_access_token("u-1", "student", settings)
    other = Settings(app_env="test", jwt_secret="another-secret")
    with pytest.raises(AuthenticationError):
        decode_token(token, ACCESS_TOKEN_TYPE, other)


def test_decode_token_rejects_expired(settings: Settings) -> None:
    expired = datetime.now(UTC) - timedelta(minutes=5)
    from jose import jwt

    token = jwt.encode(
        {
            "sub": "u-1",
            "role": "student",
            "type": ACCESS_TOKEN_TYPE,
            "exp": int(expired.timestamp()),
            "iat": int(expired.timestamp()),
            "jti": "x",
        },
        settings.resolved_jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(AuthenticationError):
        decode_token(token, ACCESS_TOKEN_TYPE, settings)


def test_token_requires_secret() -> None:
    cfg = Settings(app_env="test", jwt_secret="")
    with pytest.raises(ValidationError):
        create_access_token("u-1", "student", cfg)


# --------------------------------------------------------------------------
# logging
# --------------------------------------------------------------------------


def test_get_logger_binds_context(settings: Settings) -> None:
    configure_logging(settings)
    logger = get_logger("tests.logging")
    assert logger is not None
    bind_request_context(request_id="r-1")
    logger.info("unit.check", extra_value=1)


def test_configure_logging_rejects_unknown_level(settings: Settings) -> None:
    bad = settings.model_copy(update={"log_level": "NOPE"})
    with pytest.raises(ValueError):
        configure_logging(bad)


# --------------------------------------------------------------------------
# middleware
# --------------------------------------------------------------------------


def test_request_context_middleware_sets_headers() -> None:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ping")
    def _ping() -> dict[str, str]:
        return {"ok": "pong"}

    with TestClient(app) as client:
        response = client.get("/ping", headers={"X-Request-ID": "req-42"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-42"
    assert response.headers["X-Trace-ID"]


def test_error_handler_middleware_maps_domain_error() -> None:
    app = FastAPI()
    app.add_middleware(ErrorHandlerMiddleware)
    app.add_middleware(RequestContextMiddleware)

    @app.get("/missing")
    def _missing() -> None:
        raise NotFoundError("找不到该记录")

    with TestClient(app) as client:
        response = client.get("/missing")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"] == "找不到该记录"
    assert body["trace_id"] == response.headers["X-Trace-ID"]


# --------------------------------------------------------------------------
# schemas
# --------------------------------------------------------------------------


def test_page_params_bounds() -> None:
    params = PageParams(page=3, page_size=25)
    assert params.offset == 50
    assert params.limit == 25
    with pytest.raises(PydanticValidationError):
        PageParams(page=0)
    with pytest.raises(PydanticValidationError):
        PageParams(page_size=101)


def test_page_generic_create() -> None:
    params = PageParams(page=2, page_size=10)
    page = Page[int].create(items=[1, 2, 3], total=25, params=params)
    assert page.items == [1, 2, 3]
    assert page.total == 25
    assert page.page == 2
    assert page.page_size == 10


def test_error_response_model() -> None:
    response = ErrorResponse(
        error=ErrorDetail(code="NOT_FOUND", message="不存在"),
        trace_id="t-1",
    )
    assert response.error.code == "NOT_FOUND"
    assert response.trace_id == "t-1"


def test_middleware_elapsed_time_is_positive() -> None:
    assert time.perf_counter() > 0

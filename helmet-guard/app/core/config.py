"""应用配置：集中管理环境变量与派生属性。

职责：把环境变量读取与校验集中到一处，为其它核心模块提供单一配置来源。
依赖：pydantic-settings。
边界：仅做配置解析；不访问数据库、不执行外部调用、不承载业务规则。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import PROJECT_ROOT, db_path_for_mode

Environment = Literal["demo", "test", "live"]
LogFormat = Literal["json", "console"]


class Settings(BaseSettings):
    """应用配置。

    字段按 App / Database / Redis / JWT / CORS / Storage / LLM / Model 分组。
    环境变量与字段名同名（不设别名），便于运维统一使用大写下划线命名。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- App ----
    app_env: Environment = "demo"
    app_debug: bool = False
    app_name: str = "校园头盔检测提醒助手"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    log_format: LogFormat = "json"

    # ---- Database ----
    database_url: str = ""
    helmet_guard_mode: Environment = "demo"
    helmet_guard_db: str = ""
    helmet_guard_weights: str = "runs/detect/helmet-v2-baseline/weights/best.pt"
    helmet_guard_selfcheck_weights: str = ""
    helmet_guard_heartbeat_expire: int = Field(default=30, ge=1, le=3600)
    helmet_guard_alerts_enabled: bool = False

    # ---- Redis ----
    redis_url: str = "redis://127.0.0.1:6379/0"

    # ---- JWT ----
    jwt_secret: SecretStr = SecretStr("")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=120, ge=1, le=1440)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=90)

    # ---- CORS ----
    # 声明为原始字符串：pydantic-settings 对复杂类型会先尝试 JSON 解码，
    # 逗号分隔写法在校验器之前就报错。解析结果由 `cors_origin_list` 提供。
    cors_origins: str = ""

    # ---- Storage ----
    minio_endpoint: str = ""
    minio_access_key: SecretStr = SecretStr("")
    minio_secret_key: SecretStr = SecretStr("")
    minio_bucket: str = "helmet-evidence"
    minio_secure: bool = False

    # ---- LLM ----
    # 话术增强总开关：默认关闭（走本地模板）；开启后仍需三件套齐备才调 LLM，
    # 且 LLM 只做解释、失败自动回退模板，不影响主流程。
    llm_enabled: bool = False
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = ""
    llm_model: str = ""

    # ---- WeChat ----
    # 小程序登录三件套：未配置时走 Mock 模式（开发联调可用，
    # openid 按 code 确定性派生，不调微信接口；生产必须配置）。
    # Secret 只能走环境变量 / .env，禁止写死在代码里。
    wechat_appid: str = ""
    wechat_secret: SecretStr = SecretStr("")

    # ---- Model ----
    model_confidence_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    model_image_size: int = Field(default=640, ge=32, le=4096)

    @property
    def cors_origin_list(self) -> list[str]:
        """返回解析后的 CORS 白名单。

        支持逗号分隔与 JSON 数组两种写法，便于运维配置与容器环境注入。
        """
        stripped = self.cors_origins.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return []
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
            return []
        return [item.strip() for item in stripped.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        """是否运行于生产环境。

        生产环境必须显式提供密钥，且禁用调试输出。
        """
        return self.app_env == "live"

    @property
    def is_testing(self) -> bool:
        """是否运行于测试环境。"""
        return self.app_env == "test"

    @property
    def resolved_database_url(self) -> str:
        """解析实际使用的数据库 URL。

        优先使用显式 `DATABASE_URL`；否则按现有模式推导 SQLite 路径，
        保持与 `app.get_db_path()` 的语义一致。

        MySQL 兼容：`mysql://` 自动归一化为 `mysql+pymysql://`，
        小皮 phpStudy 用户可直接写 `mysql://root:口令@127.0.0.1:3306/helmet_guard`。
        """
        raw = self.database_url.strip()
        if raw:
            if raw.startswith("mysql://"):
                return "mysql+pymysql://" + raw[len("mysql://"):]
            return raw
        if self.helmet_guard_db.strip():
            return f"sqlite:///{Path(self.helmet_guard_db).as_posix()}"
        return f"sqlite:///{db_path_for_mode(self.helmet_guard_mode).as_posix()}"

    @property
    def resolved_jwt_secret(self) -> str:
        """返回 JWT 密钥明文；仅供签发与校验内部使用，不应写入日志。"""
        return self.jwt_secret.get_secret_value()

    @property
    def has_jwt_secret(self) -> bool:
        """是否已配置 JWT 密钥。"""
        return bool(self.jwt_secret.get_secret_value())

    @property
    def resolved_minio_access_key(self) -> str:
        """返回 MinIO access key 明文，供 SDK 初始化使用。"""
        return self.minio_access_key.get_secret_value()

    @property
    def resolved_minio_secret_key(self) -> str:
        """返回 MinIO secret key 明文，供 SDK 初始化使用。"""
        return self.minio_secret_key.get_secret_value()

    @property
    def resolved_llm_api_key(self) -> str:
        """返回 LLM API key 明文，供客户端初始化使用。"""
        return self.llm_api_key.get_secret_value()

    @property
    def project_root(self) -> Path:
        """项目根目录，便于配置相对路径。"""
        return PROJECT_ROOT


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回进程内单例配置。

    使用 `lru_cache` 保证配置只解析一次，避免每次请求重复读取环境变量。
    测试可通过 `get_settings.cache_clear()` 清理缓存。
    """
    return Settings()

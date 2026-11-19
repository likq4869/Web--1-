"""响应缓存：Redis 优先，Redis 不可用时自动降级为进程内 TTL 缓存。

职责：为 Dashboard 聚合结果提供 30s TTL 缓存，降低聚合查询压力。
依赖：redis（可选依赖，缺失时降级）。
边界：只缓存可 JSON 序列化的只读统计结果；绝不缓存含个人身份明细；
缓存键必须包含全部查询参数。Redis 故障绝不影响主流程。
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

_LOGGER = get_logger(__name__)

# 进程内降级缓存的容量上限（防止无 Redis 环境内存膨胀）。
_LOCAL_MAX_ENTRIES = 64


class ResponseCache:
    """带 TTL 的响应缓存（Redis → 进程内降级）。"""

    def __init__(self, settings: Settings | None = None) -> None:
        """初始化缓存。

        Args:
            settings: 应用配置；缺省读单例。
        """
        self.settings = settings or get_settings()
        self._client: Any | None = None
        self._redis_failed = False
        self._local: dict[str, tuple[float, str]] = {}

    def _get_client(self) -> Any | None:
        """惰性创建 Redis 客户端；不可用时返回 None（走进程内缓存）。"""
        if self._redis_failed:
            return None
        if self._client is not None:
            return self._client
        url = (self.settings.redis_url or "").strip()
        if not url:
            self._redis_failed = True
            return None
        try:
            import redis

            client = redis.Redis.from_url(
                url, socket_connect_timeout=1.0, socket_timeout=1.0
            )
            client.ping()
        except Exception as exc:  # noqa: BLE001  # Redis 不可用属预期降级路径。
            _LOGGER.info("dashboard.cache_redis_unavailable", error=str(exc)[:200])
            self._redis_failed = True
            self._client = None
            return None
        self._client = client
        return client

    def get(self, key: str) -> Any | None:
        """按键读取缓存；未命中或出错返回 None。

        Args:
            key: 缓存键。

        Returns:
            反序列化后的值；未命中为 None。
        """
        client = self._get_client()
        if client is not None:
            try:
                raw = client.get(key)
                if raw is None:
                    return None
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                return json.loads(raw)
            except Exception as exc:  # noqa: BLE001  # 缓存故障不得影响主流程。
                _LOGGER.info("dashboard.cache_get_failed", error=str(exc)[:200])
        entry = self._local.get(key)
        if entry is None:
            return None
        expires_at, raw = entry
        if expires_at <= time.monotonic():
            self._local.pop(key, None)
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            self._local.pop(key, None)
            return None

    def set(self, key: str, value: Any, ttl: int) -> None:
        """写入缓存。

        Args:
            key: 缓存键。
            value: 可 JSON 序列化的值。
            ttl: 存活秒数。
        """
        try:
            raw = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            _LOGGER.info("dashboard.cache_skip_unserializable", error=str(exc)[:200])
            return
        client = self._get_client()
        if client is not None:
            try:
                client.setex(key, ttl, raw)
                return
            except Exception as exc:  # noqa: BLE001  # 写缓存失败降级为本地缓存。
                _LOGGER.info("dashboard.cache_set_failed", error=str(exc)[:200])
        if len(self._local) >= _LOCAL_MAX_ENTRIES:
            self._local.clear()
        self._local[key] = (time.monotonic() + ttl, raw)

    def invalidate_prefix(self, prefix: str) -> None:
        """按前缀清空本地缓存（Redis 侧不做全量扫描，避免阻塞）。

        Args:
            prefix: 缓存键前缀。
        """
        for key in [k for k in self._local if k.startswith(prefix)]:
            self._local.pop(key, None)


__all__ = ["ResponseCache"]

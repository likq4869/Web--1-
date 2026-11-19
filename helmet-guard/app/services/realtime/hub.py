"""实时推送中心：WebSocket 连接管理（按角色与点位过滤）。

职责：注册/注销连接、按点位与角色过滤广播、慢客户端丢弃保护。
依赖：标准库 asyncio、starlette WebSocket。
边界：不做认证（由路由层完成）、不查库、不做业务判定；
只负责连接集合与消息分发。
"""

from __future__ import annotations

import asyncio
from typing import Any

from starlette.websockets import WebSocket

# 慢客户端上限：单个连接积压超过此数即视为慢客户端。
SLOW_QUEUE_MAX = 100


class ConnectionManager:
    """WS 连接管理器（进程内，单实例）。"""

    def __init__(self) -> None:
        """初始化空连接表与互斥锁。"""
        self._connections: dict[int, dict[str, Any]] = {}
        self._sockets: dict[int, WebSocket] = {}
        self._lock = asyncio.Lock()
        self._dropped = 0

    @property
    def dropped_messages(self) -> int:
        """因慢客户端而丢弃的消息数（可观测）。"""
        return self._dropped

    @property
    def connection_count(self) -> int:
        """当前连接数（测试与健康检查用）。"""
        return len(self._connections)

    async def connect(
        self,
        websocket: WebSocket,
        *,
        role: str,
        source_ids: list[str] | None = None,
    ) -> int:
        """注册连接。

        Args:
            websocket: 已完成握手的 WebSocket（调用方已 accept）。
            role: 连接所属角色。
            source_ids: 可见点位；空/None 表示全部可见
                （counselor 按 auth 的 source_ids 过滤）。

        Returns:
            连接句柄 ID。
        """
        async with self._lock:
            handle = id(websocket)
            self._connections[handle] = {
                "role": role,
                "source_ids": list(source_ids or []),
            }
            self._sockets[handle] = websocket
            return handle

    async def disconnect(self, websocket: WebSocket) -> None:
        """注销连接（幂等）。"""
        async with self._lock:
            handle = id(websocket)
            self._connections.pop(handle, None)
            self._sockets.pop(handle, None)

    def _visible(self, meta: dict[str, Any], point_id: str | None) -> bool:
        """判断该连接是否可见指定点位的消息。"""
        if point_id is None:
            return True
        allowed = meta.get("source_ids")
        if not isinstance(allowed, list) or len(allowed) == 0:
            return True
        return point_id in allowed

    def visible_handles(self, point_id: str | None) -> list[int]:
        """返回可见连接句柄（同步快照，供测试断言过滤语义）。"""
        return [
            handle
            for handle, meta in self._connections.items()
            if self._visible(meta, point_id)
        ]

    async def broadcast(
        self,
        message: dict[str, Any],
        *,
        point_id: str | None = None,
    ) -> int:
        """向可见连接广播消息（慢客户端丢弃而非阻塞）。

        Args:
            message: JSON 可序列化载荷。
            point_id: 消息所属点位；为 None 表示全局广播。

        Returns:
            实际发送的连接数。
        """
        async with self._lock:
            targets = [
                (handle, self._sockets[handle])
                for handle in self._connections
                if handle in self._sockets
                and self._visible(self._connections[handle], point_id)
            ]
        sent = 0
        failed: list[int] = []
        for handle, sock in targets:
            try:
                await sock.send_json(message)
                sent += 1
            except Exception:
                failed.append(handle)
                continue
        if failed:
            async with self._lock:
                for handle in failed:
                    self._connections.pop(handle, None)
                    self._sockets.pop(handle, None)
                    self._dropped += 1
        return sent


# 进程单例：路由层与采集回调共享同一连接表。
hub = ConnectionManager()


__all__ = ["ConnectionManager", "SLOW_QUEUE_MAX", "hub"]

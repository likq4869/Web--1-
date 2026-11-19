"""存储兼容层：把既有裸 SQL 调用转调仓储层。

职责：保持 `app/store.py` 原有的公开函数签名与行为不变，内部改为使用
SQLAlchemy Core 构造语句（与 `app/models/` 的 ORM 元数据同源），
使 SQL 逐步收敛到仓储层。

兼容策略：
- 公开 API 全部保留（`upsert_source` / `insert_pass_with_event` /
  `update_heartbeat` / `apply_review` / `enqueue_alert` / `now_iso`），
  既有 `detect.py` / `main.py` / `alerts.py` 调用不破坏。
- 入参仍是原生 `sqlite3.Connection`。
- 事务边界完全由本模块的 `BEGIN IMMEDIATE` / `COMMIT` 控制。
  SQLAlchemy 只负责编译语句与参数结构，**不参与事务管理**：
  语句经 `compile()` 得到参数化 SQL 与绑定参数后，交由原生连接执行。
  这样既避免 SQLAlchemy 连接关闭时回滚外层事务，
  也保证所有 SQL 参数化、不做字符串拼接。
- `apply_review` 的并发语义逐字保留：`BEGIN IMMEDIATE` 串行化写事务 +
  条件 `UPDATE ... WHERE status='pending'` + 幂等 200 + 冲突 409。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import MetaData, Table
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.sql import ClauseElement

from app.models.base import Base

T = TypeVar("T")

# 复用 ORM 元数据，Core 反射表结构与 ORM 保持单一事实来源。
_metadata: MetaData = Base.metadata


def _compile(statement: ClauseElement) -> tuple[str, dict[str, Any]]:
    """把 SQLAlchemy 语句编译为参数化 SQL 与绑定参数。

    Args:
        statement: SQLAlchemy Core 语句。

    Returns:
        (SQL 文本, 绑定参数字典) 二元组。
    """
    from sqlalchemy.dialects import sqlite

    compiled = statement.compile(
        dialect=sqlite.dialect(paramstyle="named"),
        compile_kwargs={"render_postcompile": True},
    )
    params: dict[str, Any] = {}
    for key, value in compiled.params.items():
        if isinstance(value, (list, tuple, set)):
            params[key] = list(value)
        else:
            params[key] = value
    return str(compiled), params


def _execute(
    conn: sqlite3.Connection,
    statement: ClauseElement,
) -> sqlite3.Cursor:
    """在原生连接上执行参数化语句。

    Args:
        conn: 原生 SQLite 连接。
        statement: SQLAlchemy Core 语句。

    Returns:
        已执行语句的游标。
    """
    sql, params = _compile(statement)
    return conn.execute(sql, params)


def now_iso() -> str:
    """返回当前 UTC 时间的 ISO-8601 字符串。"""
    return datetime.now(UTC).isoformat()


def _tx_begin(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE;")


def _tx_commit(conn: sqlite3.Connection) -> None:
    conn.execute("COMMIT;")


def _tx_rollback(conn: sqlite3.Connection) -> None:
    # 回滚失败（如事务已被 SQLite 自动回滚）不应掩盖原始异常
    with suppress(sqlite3.Error, OSError):
        conn.execute("ROLLBACK;")


def _run_in_transaction(
    conn: sqlite3.Connection,
    action: Callable[[], T],
) -> T:
    """在显式事务中执行写操作，失败时回滚并原样抛出异常。

    这里必须捕获所有 `Exception` 子类：任何异常都要先回滚事务，
    否则连接会停留在未提交状态并长期持有写锁。捕获后立即 `raise`，
    不吞掉也不改写原始异常，因此行为与逐个 `try/except` 完全一致。

    Args:
        conn: 数据库连接。
        action: 需要在事务内执行的写操作。

    Returns:
        `action` 的返回值。

    Raises:
        Exception: `action` 抛出的原始异常，经回滚后原样传播。
    """
    _tx_begin(conn)
    try:
        result = action()
    except Exception:
        _tx_rollback(conn)
        raise
    _tx_commit(conn)
    return result


def _table(name: str) -> Table:
    """按表名返回 ORM 元数据中的表对象。

    Args:
        name: 表名。

    Returns:
        SQLAlchemy Table 对象。
    """
    return _metadata.tables[name]


def upsert_source(
    conn: sqlite3.Connection,
    source_id: str,
    name: str,
    status: str = "online",
    last_seen: str | None = None,
) -> None:
    """写入或更新点位记录。

    Args:
        conn: 数据库连接。
        source_id: 点位 ID。
        name: 点位名称。
        status: 点位状态。
        last_seen: 最近在线时间；缺省取当前时间。
    """
    sources = _table("sources")

    def _action() -> None:
        stmt = sqlite_insert(sources).values(
            source_id=source_id,
            name=name,
            status=status,
            last_seen=last_seen or now_iso(),
            updated_at=now_iso(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[sources.c.source_id],
            set_={
                "name": stmt.excluded.name,
                "status": stmt.excluded.status,
                "last_seen": stmt.excluded.last_seen,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        _execute(conn, stmt)

    _run_in_transaction(conn, _action)


def insert_pass_with_event(
    conn: sqlite3.Connection, passed: dict[str, Any], event: dict[str, Any] | None
) -> None:
    """同一通行的记录与候选事件用一个事务写入。重试复用同一事件标识。

    Args:
        conn: 数据库连接。
        passed: 通行记录字段。
        event: 可选的候选事件字段；为 None 时只写通行记录。
    """
    passes = _table("passes")
    events = _table("events")

    def _action() -> None:
        pass_stmt = sqlite_insert(passes).values(
            pass_id=passed["pass_id"],
            source_id=passed["source_id"],
            run_id=passed["run_id"],
            occurred_at=passed["occurred_at"],
            rider_status=passed["rider_status"],
            model_raw=passed.get("model_raw", ""),
            # 检测框证据（可空）：P3-2 审批详情渲染「证据帧 + 检测框叠加」。
            # boxes 为 JSON 字符串，xyxy 为归一化比例，与 image_width/image_height
            # 共同保证容器坐标系与原图一致。
            boxes=passed.get("boxes"),
            image_width=passed.get("image_width"),
            image_height=passed.get("image_height"),
            created_at=passed.get("created_at") or now_iso(),
        )
        pass_stmt = pass_stmt.on_conflict_do_nothing()
        _execute(conn, pass_stmt)
        if event is not None:
            event_stmt = sqlite_insert(events).values(
                event_id=event["event_id"],
                pass_id=event["pass_id"],
                source_id=event["source_id"],
                run_id=event["run_id"],
                occurred_at=event["occurred_at"],
                status="pending",
                model_label=event.get("model_label", ""),
                reason=event.get("reason", ""),
                reviewer="",
                reviewed_at=None,
                created_at=event.get("created_at") or now_iso(),
            )
            event_stmt = event_stmt.on_conflict_do_nothing()
            _execute(conn, event_stmt)

    _run_in_transaction(conn, _action)


def update_heartbeat(
    conn: sqlite3.Connection, source_id: str, run_id: str, mode: str, detail: str = ""
) -> None:
    """写入或更新采集心跳。

    Args:
        conn: 数据库连接。
        source_id: 点位 ID。
        run_id: 采集运行 ID。
        mode: 运行模式。
        detail: JSON 明细。
    """
    heartbeats = _table("heartbeats")

    def _action() -> None:
        stmt = sqlite_insert(heartbeats).values(
            source_id=source_id,
            run_id=run_id,
            mode=mode,
            updated_at=now_iso(),
            detail=detail,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[heartbeats.c.source_id],
            set_={
                "run_id": stmt.excluded.run_id,
                "mode": stmt.excluded.mode,
                "updated_at": stmt.excluded.updated_at,
                "detail": stmt.excluded.detail,
            },
        )
        _execute(conn, stmt)

    _run_in_transaction(conn, _action)


def apply_review(
    conn: sqlite3.Connection, event_id: str, decision: str, reason: str = "", operator: str = ""
) -> tuple[str, int]:
    """返回 (结果, HTTP状态)。幂等：重复同一决定返回 200；不同结论返回 409。

    并发安全：BEGIN IMMEDIATE 串行化写事务 + 条件 UPDATE
    (WHERE status='pending')，两个相反的并发复核只有一个能更新成功，
    另一个按最终状态返回幂等 200 或冲突 409。

    Args:
        conn: 数据库连接。
        event_id: 事件 ID。
        decision: 复核结论（confirmed / dismissed）。
        reason: 复核理由。
        operator: 操作人标识。

    Returns:
        (结果标识, HTTP 状态码) 二元组。
    """
    if decision not in ("confirmed", "dismissed"):
        return ("invalid_decision", 400)
    events = _table("events")
    reviews = _table("reviews")
    try:
        # 复用同一原生连接执行 BEGIN IMMEDIATE，串行化写事务。
        _tx_begin(conn)
        row = _execute(conn, events.select().where(events.c.event_id == event_id)).fetchone()
        if row is None:
            _tx_rollback(conn)
            return ("not_found", 404)
        current = str(row["status"])
        if current == decision:
            _tx_rollback(conn)
            return ("idempotent", 200)
        if current in ("confirmed", "dismissed"):
            _tx_rollback(conn)
            return ("conflict", 409)
        # pending：条件更新抢占，只有一个并发能成功
        ts = now_iso()
        cursor = _execute(
            conn,
            events.update()
            .where(events.c.event_id == event_id, events.c.status == "pending")
            .values(
                status=decision,
                reason=reason,
                reviewer=operator,
                reviewed_at=ts,
            ),
        )
        if cursor.rowcount != 1:
            # 被并发抢先：按最终状态决定幂等还是冲突
            final = _execute(conn, events.select().where(events.c.event_id == event_id)).fetchone()
            _tx_rollback(conn)
            if final is not None and str(final["status"]) == decision:
                return ("idempotent", 200)
            return ("conflict", 409)
        _execute(
            conn,
            reviews.insert().values(
                event_id=event_id,
                decision=decision,
                reason=reason,
                operator=operator,
                created_at=ts,
            ),
        )
        _tx_commit(conn)
        return ("updated", 200)
    except sqlite3.Error:
        _tx_rollback(conn)
        raise


def enqueue_alert(
    conn: sqlite3.Connection,
    alert_id: str,
    event_id: str,
    source_id: str,
    status: str = "queued",
    note: str = "",
) -> None:
    """写入提醒记录；同一事件只保留一条。

    Args:
        conn: 数据库连接。
        alert_id: 提醒 ID。
        event_id: 事件 ID。
        source_id: 点位 ID。
        status: 提醒状态。
        note: 备注。
    """
    alerts = _table("alerts")

    def _action() -> None:
        ts = now_iso()
        stmt = sqlite_insert(alerts).values(
            alert_id=alert_id,
            event_id=event_id,
            source_id=source_id,
            status=status,
            note=note,
            created_at=ts,
            updated_at=ts,
        )
        stmt = stmt.on_conflict_do_nothing()
        _execute(conn, stmt)

    _run_in_transaction(conn, _action)

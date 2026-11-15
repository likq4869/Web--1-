"""通行 / 事件 / 复核 / 心跳 / 提醒的存储操作。短事务 + 参数化 SQL。"""

from __future__ import annotations

import sqlite3
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _tx_begin(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE;")


def _tx_commit(conn: sqlite3.Connection) -> None:
    conn.execute("COMMIT;")


def _tx_rollback(conn: sqlite3.Connection) -> None:
    # 回滚失败（如事务已被 SQLite 自动回滚）不应掩盖原始异常
    with suppress(Exception):
        conn.execute("ROLLBACK;")


def upsert_source(
    conn: sqlite3.Connection,
    source_id: str,
    name: str,
    status: str = "online",
    last_seen: str | None = None,
) -> None:
    _tx_begin(conn)
    try:
        conn.execute(
            "INSERT INTO sources(source_id,name,status,last_seen,updated_at)"
            " VALUES(?,?,?,?,?)"
            " ON CONFLICT(source_id) DO UPDATE SET name=excluded.name,"
            " status=excluded.status,last_seen=excluded.last_seen,"
            " updated_at=excluded.updated_at",
            (source_id, name, status, last_seen or now_iso(), now_iso()),
        )
        _tx_commit(conn)
    except Exception:
        _tx_rollback(conn)
        raise


def insert_pass_with_event(
    conn: sqlite3.Connection, passed: dict[str, Any], event: dict[str, Any] | None
) -> None:
    """同一通行的记录与候选事件用一个事务写入。重试复用同一事件标识。"""
    _tx_begin(conn)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO passes(pass_id,source_id,run_id,occurred_at,"
            "rider_status,model_raw,created_at) VALUES(?,?,?,?,?,?,?)",
            (
                passed["pass_id"],
                passed["source_id"],
                passed["run_id"],
                passed["occurred_at"],
                passed["rider_status"],
                passed.get("model_raw", ""),
                passed.get("created_at") or now_iso(),
            ),
        )
        if event is not None:
            conn.execute(
                "INSERT OR IGNORE INTO events(event_id,pass_id,source_id,run_id,"
                "occurred_at,status,model_label,reason,reviewer,reviewed_at,"
                "created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event["event_id"],
                    event["pass_id"],
                    event["source_id"],
                    event["run_id"],
                    event["occurred_at"],
                    "pending",
                    event.get("model_label", ""),
                    event.get("reason", ""),
                    "",
                    None,
                    event.get("created_at") or now_iso(),
                ),
            )
        _tx_commit(conn)
    except Exception:
        _tx_rollback(conn)
        raise


def update_heartbeat(
    conn: sqlite3.Connection, source_id: str, run_id: str, mode: str, detail: str = ""
) -> None:
    _tx_begin(conn)
    try:
        conn.execute(
            "INSERT INTO heartbeats(source_id,run_id,mode,updated_at,detail)"
            " VALUES(?,?,?,?,?)"
            " ON CONFLICT(source_id) DO UPDATE SET run_id=excluded.run_id,"
            " mode=excluded.mode,updated_at=excluded.updated_at,"
            " detail=excluded.detail",
            (source_id, run_id, mode, now_iso(), detail),
        )
        _tx_commit(conn)
    except Exception:
        _tx_rollback(conn)
        raise


def apply_review(
    conn: sqlite3.Connection, event_id: str, decision: str, reason: str = "", operator: str = ""
) -> tuple[str, int]:
    """返回 (结果, HTTP状态)。幂等：重复同一决定返回 200；不同结论返回 409。

    并发安全：BEGIN IMMEDIATE 串行化写事务 + 条件 UPDATE
    (WHERE status='pending')，两个相反的并发复核只有一个能更新成功，
    另一个按最终状态返回幂等 200 或冲突 409。
    """
    if decision not in ("confirmed", "dismissed"):
        return ("invalid_decision", 400)
    _tx_begin(conn)
    try:
        row = conn.execute("SELECT status FROM events WHERE event_id=?", (event_id,)).fetchone()
        if row is None:
            _tx_rollback(conn)
            return ("not_found", 404)
        current = row["status"]
        if current == decision:
            _tx_rollback(conn)
            return ("idempotent", 200)
        if current in ("confirmed", "dismissed"):
            _tx_rollback(conn)
            return ("conflict", 409)
        # pending：条件更新抢占，只有一个并发能成功
        ts = now_iso()
        cur = conn.execute(
            "UPDATE events SET status=?,reason=?,reviewer=?,reviewed_at=? "
            "WHERE event_id=? AND status='pending'",
            (decision, reason, operator, ts, event_id),
        )
        if cur.rowcount != 1:
            # 被并发抢先：按最终状态决定幂等还是冲突
            final = conn.execute(
                "SELECT status FROM events WHERE event_id=?", (event_id,)
            ).fetchone()
            _tx_rollback(conn)
            if final is not None and final["status"] == decision:
                return ("idempotent", 200)
            return ("conflict", 409)
        conn.execute(
            "INSERT INTO reviews(event_id,decision,reason,operator,created_at) VALUES(?,?,?,?,?)",
            (event_id, decision, reason, operator, ts),
        )
        _tx_commit(conn)
        return ("updated", 200)
    except Exception:
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
    ts = now_iso()
    _tx_begin(conn)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO alerts(alert_id,event_id,source_id,status,"
            "note,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (alert_id, event_id, source_id, status, note, ts, ts),
        )
        _tx_commit(conn)
    except Exception:
        _tx_rollback(conn)
        raise

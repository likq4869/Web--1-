"""SQLite 连接与表结构。参数化 SQL、唯一约束、短事务。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import get_db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'online',
    last_seen TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS passes (
    pass_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    rider_status TEXT NOT NULL CHECK (rider_status IN ('helmeted','bare','unknown')),
    model_raw TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (source_id, run_id, pass_id)
);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    pass_id TEXT NOT NULL UNIQUE,
    source_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','confirmed','dismissed')),
    model_label TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    reviewer TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('confirmed','dismissed')),
    reason TEXT NOT NULL DEFAULT '',
    operator TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_event ON reviews(event_id);
CREATE TABLE IF NOT EXISTS heartbeats (
    source_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    source_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued','played','expired','silent')),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def init_db(db_path: Path | None = None) -> Path:
    path = Path(db_path) if db_path else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        # executescript 会隐式提交（自动提交模式下），无需显式 BEGIN/COMMIT；
        # CREATE TABLE IF NOT EXISTS 本身幂等，适配并发初始化。
        conn.executescript(SCHEMA)
    finally:
        conn.close()
    return path


def tables_exist(conn: sqlite3.Connection) -> bool:
    """只读检查业务表是否存在。查询接口只做只读检查，不建库。"""
    row = conn.execute(
        "SELECT COUNT(*) n FROM sqlite_master WHERE type='table' "
        "AND name IN ('sources','passes','events','reviews',"
        "'heartbeats','alerts')"
    ).fetchone()
    # fetchone() 在无匹配行时返回 None；此处表一定存在，缺失说明库损坏。
    return row is not None and int(row["n"]) == 6

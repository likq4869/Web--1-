"""系统路由：健康检查、点位列表、通行统计（遗留路径）。

职责：HTTP 解析与响应序列化；只读检查不建库。
依赖：FastAPI、app.core.health、仓储层（MySQL）。
边界：SQLite 保留原生 SQL（采集高频写入路径，行为逐字等价）；
MySQL 改走 SQLAlchemy 仓储只读，避免 `?` 占位符与 `sqlite_master` 方言报错。

由 B-2 从 `app/main.py` 拆出；MySQL 分支为 phpStudy 落地新增。
"""

from __future__ import annotations

import contextlib

from fastapi import APIRouter

from app import get_mode
from app.core.health import (
    ApiResponse,
    Heartbeat,
    all_heartbeats,
    all_heartbeats_mysql,
    capture_status,
    db_status,
    is_mysql_mode,
    model_status,
    require_db,
)

router = APIRouter(tags=["system-legacy"])


def _mysql_heartbeats() -> list[Heartbeat]:
    """MySQL 心跳只读（仓储层，不建库）。

    Returns:
        心跳字典列表（含 `detail_parsed`）。
    """
    from sqlalchemy.orm import Session

    from app.core.deps import build_engine

    engine = build_engine()
    try:
        with Session(engine, future=True) as session:
            rows = all_heartbeats_mysql(session)
            return [dict(r) for r in rows]
    finally:
        with contextlib.suppress(Exception):
            engine.dispose()


def _heartbeat_updated_at(row: Heartbeat) -> str:
    """心跳排序键：缺失时间按空字符串排最后。"""
    value = row.get("updated_at")
    return str(value) if value is not None else ""


def _mysql_sources() -> list[dict[str, object]]:
    """MySQL 点位列表（ORM 只读，形状与 SQLite 分支一致）。"""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.core.deps import build_engine
    from app.models.entities import Source

    engine = build_engine()
    try:
        with Session(engine, future=True) as session:
            rows = (
                session.execute(select(Source).order_by(Source.source_id)).scalars().all()
            )
            return [
                {
                    "source_id": str(r.source_id),
                    "name": str(r.name),
                    "status": str(r.status),
                    "last_seen": r.last_seen,
                    "updated_at": r.updated_at,
                }
                for r in rows
            ]
    finally:
        with contextlib.suppress(Exception):
            engine.dispose()


def _mysql_pass_counts(
    source_id: str | None,
    run_id: str | None,
    start: str | None,
    end: str | None,
) -> dict[str, int]:
    """MySQL 通行三态计数（仓储只读）。"""
    from sqlalchemy.orm import Session

    from app.core.deps import build_engine
    from app.repositories.pass_record import PassRepository

    engine = build_engine()
    try:
        with Session(engine, future=True) as session:
            return PassRepository(session).count_by_status(
                source_id=source_id, run_id=run_id, start=start, end=end
            )
    finally:
        with contextlib.suppress(Exception):
            engine.dispose()


@router.get("/health")
def health() -> ApiResponse:
    """健康检查：数据库 / 模型 / 采集三态。"""
    db, conn = db_status()
    if conn is None:
        if is_mysql_mode():
            if not db.get("ok"):
                return {
                    "mode": get_mode(),
                    "db": db,
                    "model": model_status(None),
                    "capture": capture_status(None, []),
                    "api": "ok",
                }
            rows = _mysql_heartbeats()
            latest = max(rows, key=_heartbeat_updated_at) if rows else None
            return {
                "mode": get_mode(),
                "db": db,
                "model": model_status(latest),
                "capture": capture_status(latest, rows),
                "api": "ok",
            }
        return {
            "mode": get_mode(),
            "db": db,
            "model": model_status(None),
            "capture": capture_status(None, []),
            "api": "ok",
        }
    try:
        rows = all_heartbeats(conn)
    finally:
        conn.close()
    latest = max(rows, key=lambda r: r["updated_at"]) if rows else None
    return {
        "mode": get_mode(),
        "db": db,
        "model": model_status(latest),
        "capture": capture_status(latest, rows),
        "api": "ok",
    }


@router.get("/api/v1/sources")
def list_sources() -> ApiResponse:
    """点位列表（只读；MySQL 走 ORM，SQLite 走原生 SQL）。"""
    if is_mysql_mode():
        return {"mode": get_mode(), "sources": _mysql_sources()}
    conn = require_db()
    try:
        rows = conn.execute(
            "SELECT source_id,name,status,last_seen,updated_at FROM sources ORDER BY source_id"
        ).fetchall()
    finally:
        conn.close()
    return {"mode": get_mode(), "sources": [dict(r) for r in rows]}


@router.get("/api/v1/stats")
def stats(
    source_id: str | None = None,
    run_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> ApiResponse:
    """通行统计（只读；MySQL 走仓储，SQLite 走原生 SQL）。"""
    if is_mysql_mode():
        counts = _mysql_pass_counts(source_id, run_id, start, end)
    else:
        conn = require_db()
        sql = "SELECT rider_status,COUNT(*) c FROM passes WHERE 1=1"
        args: list[str] = []
        if source_id:
            sql += " AND source_id=?"
            args.append(source_id)
        if run_id:
            sql += " AND run_id=?"
            args.append(run_id)
        if start:
            sql += " AND occurred_at>=?"
            args.append(start)
        if end:
            sql += " AND occurred_at<=?"
            args.append(end)
        sql += " GROUP BY rider_status"
        try:
            rows = conn.execute(sql, args).fetchall()
        finally:
            conn.close()
        counts = {"helmeted": 0, "bare": 0, "unknown": 0}
        for r in rows:
            counts[r["rider_status"]] = r["c"]
    total = sum(counts.values())
    judged = counts["helmeted"] + counts["bare"]
    wearing = counts["helmeted"] / judged if judged else None
    coverage = judged / total if total else None
    return {
        "mode": get_mode(),
        "source_id": source_id,
        "run_id": run_id,
        "total": total,
        "counts": counts,
        "wearing_rate": wearing,
        "coverage": coverage,
    }


__all__ = ["router"]

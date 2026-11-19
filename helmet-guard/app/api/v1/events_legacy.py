"""遗留事件路由：事件查询、人工复核、告警列表（遗留路径）。

职责：HTTP 解析与响应序列化；只读检查不建库。
依赖：FastAPI、app.core.health、app.store（SQLite）、仓储层（MySQL）。
边界：SQLite 保留原生 SQL（采集高频写入路径，行为逐字等价）；
MySQL 改走仓储层，避免 `?` 占位符方言报错。

由 B-2 从 `app/main.py` 拆出；MySQL 分支为 phpStudy 落地新增。
"""

from __future__ import annotations

import contextlib
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import EVENTS_PAGE_SIZE_MAX, get_mode
from app.core.health import ApiResponse, is_mysql_mode, require_db
from app.store import apply_review

router = APIRouter(tags=["events-legacy"])


class ReviewBody(BaseModel):
    """人工复核请求体（confirmed / dismissed）。"""

    decision: Literal["confirmed", "dismissed"]
    reason: str = Field(default="", max_length=500)
    operator: str = Field(default="", max_length=64)


def _mysql_list_events(
    source_id: str | None,
    status: str | None,
    start: str | None,
    end: str | None,
    limit: int,
    offset: int,
) -> tuple[int, list[dict[str, object]]]:
    """MySQL 事件列表（仓储只读，形状与 SQLite 分支一致）。"""
    from sqlalchemy.orm import Session

    from app.core.deps import build_engine
    from app.repositories.event import EventRepository

    engine = build_engine()
    try:
        with Session(engine, future=True) as session:
            repo = EventRepository(session)
            rows = repo.list_with_filters(
                source_id=source_id,
                status=status,
                start=start,
                end=end,
                limit=limit,
                offset=offset,
            )
            total = repo.count_with_filters(
                source_id=source_id, status=status, start=start, end=end
            )
            items: list[dict[str, object]] = [
                {
                    "event_id": str(r.event_id),
                    "pass_id": str(r.pass_id),
                    "source_id": str(r.source_id),
                    "run_id": str(r.run_id),
                    "occurred_at": str(r.occurred_at),
                    "status": str(r.status),
                    "model_label": str(r.model_label),
                    "reason": str(r.reason),
                    "reviewer": str(r.reviewer),
                    "reviewed_at": r.reviewed_at,
                    "created_at": str(r.created_at),
                }
                for r in rows
            ]
            return total, items
    finally:
        with contextlib.suppress(Exception):
            engine.dispose()


def _mysql_review_event(
    event_id: str, decision: str, reason: str, operator: str
) -> tuple[str, int]:
    """MySQL 人工复核（条件 UPDATE + 幂等，语义与 `apply_review` 对齐）。

    Returns:
        (结果标识, HTTP 状态) 二元组。
    """
    from sqlalchemy.orm import Session

    from app.core.deps import build_engine
    from app.models.entities import Review as ReviewModel
    from app.repositories.event import EventRepository
    from app.store import now_iso

    engine = build_engine()
    try:
        with Session(engine, future=True) as session:
            repo = EventRepository(session)
            current = repo.get_status(event_id)
            if current is None:
                return ("not_found", 404)
            if current == decision:
                return ("idempotent", 200)
            if current in ("confirmed", "dismissed"):
                return ("conflict", 409)
            ts = now_iso()
            affected = repo.claim_pending(
                event_id,
                status=decision,
                reason=reason,
                reviewer=operator,
                reviewed_at=ts,
            )
            if affected != 1:
                session.rollback()
                final = repo.get_status(event_id)
                if final == decision:
                    return ("idempotent", 200)
                return ("conflict", 409)
            session.add(
                ReviewModel(
                    event_id=event_id,
                    decision=decision,
                    reason=reason,
                    operator=operator,
                    created_at=ts,
                )
            )
            session.commit()
            return ("updated", 200)
    finally:
        with contextlib.suppress(Exception):
            engine.dispose()


def _mysql_event_row(event_id: str) -> dict[str, object] | None:
    """MySQL 单事件读取（复核回显用）。"""
    from sqlalchemy.orm import Session

    from app.core.deps import build_engine
    from app.repositories.event import EventRepository

    engine = build_engine()
    try:
        with Session(engine, future=True) as session:
            row = EventRepository(session).find_by(event_id=event_id)
            if row is None:
                return None
            return {
                "event_id": str(row.event_id),
                "status": str(row.status),
                "reason": str(row.reason),
                "reviewer": str(row.reviewer),
                "reviewed_at": row.reviewed_at,
            }
    finally:
        with contextlib.suppress(Exception):
            engine.dispose()


def _mysql_alerts() -> list[dict[str, object]]:
    """MySQL 告警列表（最近 100 条，形状与 SQLite 分支一致）。"""
    from sqlalchemy.orm import Session

    from app.core.deps import build_engine
    from app.repositories.alert import AlertRepository

    engine = build_engine()
    try:
        with Session(engine, future=True) as session:
            return [
                {
                    "alert_id": str(r.alert_id),
                    "event_id": str(r.event_id),
                    "source_id": str(r.source_id),
                    "status": str(r.status),
                    "note": str(r.note),
                    "created_at": str(r.created_at),
                    "updated_at": str(r.updated_at),
                }
                for r in AlertRepository(session).list_recent(100)
            ]
    finally:
        with contextlib.suppress(Exception):
            engine.dispose()


@router.get("/api/v1/events")
def list_events(
    source_id: str | None = None,
    status: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(20, ge=1, le=EVENTS_PAGE_SIZE_MAX),
    offset: int = Query(0, ge=0),
) -> ApiResponse:
    """事件列表（遗留路径；MySQL 走仓储，SQLite 走原生 SQL）。"""
    if status and status not in ("pending", "confirmed", "dismissed"):
        raise HTTPException(status_code=400, detail="status 非法")
    if is_mysql_mode():
        total, items = _mysql_list_events(source_id, status, start, end, limit, offset)
        return {
            "mode": get_mode(),
            "total": total,
            "limit": limit,
            "offset": offset,
            "events": items,
        }
    conn = require_db()
    sql = (
        "SELECT event_id,pass_id,source_id,run_id,occurred_at,status,"
        "model_label,reason,reviewer,reviewed_at,created_at FROM events WHERE 1=1"
    )
    count_sql = "SELECT COUNT(*) n FROM events WHERE 1=1"
    args: list[str] = []
    if source_id:
        sql += " AND source_id=?"
        count_sql += " AND source_id=?"
        args.append(source_id)
    if status:
        sql += " AND status=?"
        count_sql += " AND status=?"
        args.append(status)
    if start:
        sql += " AND occurred_at>=?"
        count_sql += " AND occurred_at>=?"
        args.append(start)
    if end:
        sql += " AND occurred_at<=?"
        count_sql += " AND occurred_at<=?"
        args.append(end)
    sql += " ORDER BY occurred_at DESC LIMIT ? OFFSET ?"
    try:
        total = conn.execute(count_sql, args).fetchone()["n"]
        rows = conn.execute(sql, args + [limit, offset]).fetchall()
    finally:
        conn.close()
    return {
        "mode": get_mode(),
        "total": total,
        "limit": limit,
        "offset": offset,
        "events": [dict(r) for r in rows],
    }


@router.post("/api/v1/events/{event_id}/review")
def review_event(event_id: str, body: ReviewBody) -> ApiResponse:
    """人工复核单个事件（条件 UPDATE + 幂等）。"""
    if is_mysql_mode():
        result, code = _mysql_review_event(
            event_id, body.decision, body.reason, body.operator
        )
        if code == 404:
            raise HTTPException(status_code=404, detail="事件不存在")
        if code == 409:
            raise HTTPException(status_code=409, detail="已有不同复核结论")
        return {"mode": get_mode(), "result": result, "event": _mysql_event_row(event_id)}
    conn = require_db()
    try:
        result, code = apply_review(conn, event_id, body.decision, body.reason, body.operator)
    finally:
        conn.close()
    if code == 404:
        raise HTTPException(status_code=404, detail="事件不存在")
    if code == 409:
        raise HTTPException(status_code=409, detail="已有不同复核结论")
    conn2 = require_db()
    try:
        row = conn2.execute(
            "SELECT event_id,status,reason,reviewer,reviewed_at FROM events WHERE event_id=?",
            (event_id,),
        ).fetchone()
    finally:
        conn2.close()
    return {"mode": get_mode(), "result": result, "event": dict(row)}


@router.get("/api/v1/alerts")
def list_alerts() -> ApiResponse:
    """告警列表（遗留路径，最近 100 条）。"""
    from app import ALERT_TEXT

    if is_mysql_mode():
        return {"mode": get_mode(), "alert_text": ALERT_TEXT, "alerts": _mysql_alerts()}
    conn = require_db()
    try:
        rows = conn.execute(
            "SELECT alert_id,event_id,source_id,status,note,created_at,"
            "updated_at FROM alerts ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    finally:
        conn.close()
    return {"mode": get_mode(), "alert_text": ALERT_TEXT, "alerts": [dict(r) for r in rows]}


__all__ = ["ReviewBody", "router"]

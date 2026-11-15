"""阶段 1 测试：种子幂等、复核落库与重启可查、幂等/冲突、统计分母为零。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("HELMET_GUARD_DB", str(db))
    monkeypatch.setenv("HELMET_GUARD_MODE", "demo")
    os.environ["HELMET_GUARD_DB"] = str(db)
    os.environ["HELMET_GUARD_MODE"] = "demo"
    from app import seed_demo
    from app.main import app

    seed_demo.seed(db)
    return TestClient(app), db


def test_seed_idempotent(client):
    c, db = client
    from app import seed_demo

    seed_demo.seed(db)  # 重复执行
    r = c.get("/api/v1/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 10
    assert body["counts"] == {"helmeted": 7, "bare": 2, "unknown": 1}
    # 7/9 佩戴率，覆盖率 0.9
    assert abs(body["wearing_rate"] - 7 / 9) < 1e-9
    assert abs(body["coverage"] - 0.9) < 1e-9
    ev = c.get("/api/v1/events")
    assert ev.json()["total"] == 2


def test_review_persist_and_idempotent(client):
    c, db = client
    eid = "evt-demo-pass-003"
    r1 = c.post(
        f"/api/v1/events/{eid}/review",
        json={"decision": "confirmed", "reason": "人工确认", "operator": "duty1"},
    )
    assert r1.status_code == 200
    # 重复提交同一决定幂等
    r2 = c.post(
        f"/api/v1/events/{eid}/review",
        json={"decision": "confirmed", "reason": "人工确认", "operator": "duty1"},
    )
    assert r2.status_code == 200
    # 不同结论冲突
    r3 = c.post(f"/api/v1/events/{eid}/review", json={"decision": "dismissed", "reason": "改判"})
    assert r3.status_code == 409
    # 落库：直接查库验证重启可查
    import sqlite3

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT status,reviewer FROM events WHERE event_id=?", (eid,)).fetchone()
    conn.close()
    assert row["status"] == "confirmed" and row["reviewer"] == "duty1"


def test_review_not_found_and_validation(client):
    c, _ = client
    r = c.post("/api/v1/events/evt-missing/review", json={"decision": "confirmed"})
    assert r.status_code == 404
    r = c.post("/api/v1/events/evt-demo-pass-008/review", json={"decision": "maybe"})
    assert r.status_code == 422


def test_stats_zero_denominator(tmp_path, monkeypatch):
    db = tmp_path / "empty.db"
    monkeypatch.setenv("HELMET_GUARD_DB", str(db))
    monkeypatch.setenv("HELMET_GUARD_MODE", "demo")
    os.environ["HELMET_GUARD_DB"] = str(db)
    from app.db import init_db
    from app.main import app

    init_db(db)
    c = TestClient(app)
    body = c.get("/api/v1/stats").json()
    assert body["total"] == 0
    assert body["wearing_rate"] is None
    assert body["coverage"] is None


def test_health_and_sources(client):
    c, _ = client
    h = c.get("/health").json()
    assert h["mode"] == "demo" and h["api"] == "ok" and h["db"]["ok"] is True
    s = c.get("/api/v1/sources").json()
    assert s["mode"] == "demo"
    assert any(x["source_id"] == "gate-east" for x in s["sources"])
    ev = c.get("/api/v1/events", params={"status": "pending", "limit": 1})
    assert ev.json()["total"] == 2

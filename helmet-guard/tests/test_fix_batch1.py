"""第一批修复回归测试：demo/live 隔离、启动建表、健康状态、并发复核（临时库）。

本轮更新：查询接口不再重复建库，未初始化时返回 503；
/health 模型与采集状态来自采集心跳。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient


def _fresh_client(db: Path, monkeypatch, mode: str = "demo") -> TestClient:
    monkeypatch.setenv("HELMET_GUARD_DB", str(db))
    monkeypatch.setenv("HELMET_GUARD_MODE", mode)
    os.environ["HELMET_GUARD_DB"] = str(db)
    os.environ["HELMET_GUARD_MODE"] = mode
    import importlib

    from app import main as main_mod

    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def test_demo_live_db_paths_isolated(monkeypatch, tmp_path):
    from app import db_path_for_mode, get_db_path

    monkeypatch.delenv("HELMET_GUARD_DB", raising=False)
    monkeypatch.setenv("HELMET_GUARD_MODE", "demo")
    demo = get_db_path()
    assert demo == db_path_for_mode("demo")
    assert demo.name == "helmet_demo.db"
    monkeypatch.setenv("HELMET_GUARD_MODE", "live")
    live = get_db_path()
    assert live == db_path_for_mode("live")
    assert live.name == "helmet_live.db"
    assert demo != live
    monkeypatch.setenv("HELMET_GUARD_DB", str(tmp_path / "x.db"))
    assert get_db_path() == tmp_path / "x.db"


def test_demo_live_data_isolated(monkeypatch, tmp_path):
    """两个临时库分别代表 demo/live：写 demo 不污染 live。"""
    from app import seed_demo
    from app.db import connect, init_db

    demo_db, live_db = tmp_path / "demo.db", tmp_path / "live.db"
    seed_demo.seed(demo_db)
    init_db(live_db)
    c_demo = connect(demo_db)
    c_live = connect(live_db)
    try:
        n_demo = c_demo.execute("SELECT COUNT(*) n FROM passes").fetchone()["n"]
        n_live = c_live.execute("SELECT COUNT(*) n FROM passes").fetchone()["n"]
    finally:
        c_demo.close()
        c_live.close()
    assert n_demo == 10 and n_live == 0


def test_startup_creates_tables_but_queries_do_not_rebuild(monkeypatch, tmp_path):
    from app.db import connect

    db = tmp_path / "fresh.db"
    assert not db.exists()
    monkeypatch.setenv("HELMET_GUARD_DB", str(db))
    monkeypatch.setenv("HELMET_GUARD_MODE", "demo")
    os.environ["HELMET_GUARD_DB"] = str(db)
    os.environ["HELMET_GUARD_MODE"] = "demo"
    from app.main import app

    with TestClient(app) as c:
        r = c.get("/health")
        assert r.status_code == 200
        assert r.json()["db"]["ok"] is True
    conn = connect(db)
    try:
        tables = {
            x["name"]
            for x in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        conn.close()
    assert {"sources", "passes", "events", "reviews", "heartbeats", "alerts"} <= tables
    # 库文件被删后查询接口不再重复建库：返回 503，且不重建表
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db) + suffix) if suffix else db
        if p.exists():
            p.unlink()
    c2 = TestClient(app)
    r2 = c2.get("/api/v1/stats")
    assert r2.status_code == 503
    # 未建库：health 报告 db 未就绪，但 API 本身 200
    r3 = c2.get("/health")
    assert r3.status_code == 200
    assert r3.json()["db"]["ok"] is False


def test_health_status_demo_and_live_heartbeat(monkeypatch, tmp_path):
    """健康状态来自采集心跳：无心跳时 live 模型/采集均未就绪。"""
    from app import seed_demo

    db = tmp_path / "h.db"
    seed_demo.seed(db)
    c = _fresh_client(db, monkeypatch, "demo")
    h = c.get("/health").json()
    assert h["mode"] == "demo" and h["db"]["ok"] is True
    assert h["model"]["ready"] is True
    assert h["capture"]["ready"] is False
    assert "无实时采集" in h["capture"]["reason"]

    c_live = _fresh_client(db, monkeypatch, "live")
    h2 = c_live.get("/health").json()
    assert h2["mode"] == "live"
    # 无心跳：模型未就绪（需启动检测进程），采集未就绪
    assert h2["model"]["ready"] is False
    assert "无采集心跳" in h2["model"]["reason"]
    assert h2["capture"]["ready"] is False


def test_concurrent_opposite_reviews_single_winner(monkeypatch, tmp_path):
    """两个相反的并发复核：一个 200，另一个 409。临时库。"""
    from app import seed_demo

    db = tmp_path / "race.db"
    seed_demo.seed(db)
    monkeypatch.setenv("HELMET_GUARD_DB", str(db))
    monkeypatch.setenv("HELMET_GUARD_MODE", "demo")
    os.environ["HELMET_GUARD_DB"] = str(db)
    os.environ["HELMET_GUARD_MODE"] = "demo"
    from app.main import app

    eid = "evt-demo-pass-003"
    barrier = threading.Barrier(2)

    def hit(decision: str) -> int:
        barrier.wait(timeout=10)
        with TestClient(app) as client:
            r = client.post(
                f"/api/v1/events/{eid}/review",
                json={"decision": decision, "reason": f"并发-{decision}", "operator": "duty-race"},
            )
            return r.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_c = pool.submit(hit, "confirmed")
        fut_d = pool.submit(hit, "dismissed")
        codes = sorted([fut_c.result(timeout=30), fut_d.result(timeout=30)])
    assert codes == [200, 409], f"期望一胜一冲突，实际={codes}"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT status FROM events WHERE event_id=?", (eid,)).fetchone()
        n = conn.execute("SELECT COUNT(*) n FROM reviews WHERE event_id=?", (eid,)).fetchone()["n"]
    finally:
        conn.close()
    assert row["status"] in ("confirmed", "dismissed")
    assert n == 1


def test_alerts_stay_silent_by_default(monkeypatch, tmp_path):
    from app import seed_demo
    from app.config import get_point_config

    db = tmp_path / "silent.db"
    seed_demo.seed(db)
    monkeypatch.delenv("HELMET_GUARD_ALERTS_ENABLED", raising=False)
    os.environ.pop("HELMET_GUARD_ALERTS_ENABLED", None)
    assert get_point_config().alert_enabled is False
    c = _fresh_client(db, monkeypatch, "demo")
    body = c.get("/api/v1/alerts").json()
    assert body["alerts"] == []
    monkeypatch.setenv("HELMET_GUARD_DB", str(db))
    os.environ["HELMET_GUARD_DB"] = str(db)
    from app.alerts import request_alert

    ok, why = request_alert("evt-demo-pass-003", "gate-east", "demo-run-001", alert_enabled=False)
    assert ok is False and why.startswith("silent")
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT status FROM alerts WHERE event_id=?", ("evt-demo-pass-003",)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None and row["status"] == "silent"

"""本轮回归：模式与库路径统一、健康读采集心跳、查询不再重复建库（临时库）。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


def _client_for(db: Path, monkeypatch, mode: str = "demo") -> TestClient:
    monkeypatch.setenv("HELMET_GUARD_DB", str(db))
    monkeypatch.setenv("HELMET_GUARD_MODE", mode)
    import importlib

    from app import main as main_mod
    from app.core.config import get_settings as _get_settings

    _get_settings.cache_clear()

    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def _beat(conn, source_id="gate-east", run_id="live-run-1", mode="live", **detail) -> None:
    from app.store import update_heartbeat

    base = {
        "weights": "weights/helmet_best.pt",
        "model_loaded": True,
        "model_ok": True,
        "model_info": "ok",
        "had_first_frame": True,
        "frames": 10,
        "stage": "running",
        "error": "",
    }
    base.update(detail)
    update_heartbeat(conn, source_id, run_id, mode, json.dumps(base))


def test_cli_live_overrides_demo_env(monkeypatch, tmp_path):
    """--mode live 配合 demo 环境变量：有效模式为 live，走 live 库。"""
    from app import (
        apply_effective_mode,
        db_path_for_mode,
        get_db_path,
        get_mode,
        resolve_effective_mode,
    )

    monkeypatch.delenv("HELMET_GUARD_DB", raising=False)
    monkeypatch.setenv("HELMET_GUARD_MODE", "demo")
    assert resolve_effective_mode("live") == "live"
    assert resolve_effective_mode(None) == "demo"
    assert resolve_effective_mode("bogus") == "demo"
    effective = apply_effective_mode("live")
    assert effective == "live"
    assert get_mode() == "live"
    assert get_db_path() == db_path_for_mode("live")
    assert get_db_path().name == "helmet_live.db"
    # camera_check / demo 映射回 demo 库
    assert apply_effective_mode("camera_check") == "camera_check"
    assert get_mode() == "demo"
    assert get_db_path().name == "helmet_demo.db"


def test_live_seed_refused_without_explicit_db(monkeypatch, tmp_path):
    """live 环境误跑演示种子：默认库拒绝；显式临时库放行。"""
    import pytest

    from app import seed_demo

    monkeypatch.delenv("HELMET_GUARD_DB", raising=False)
    monkeypatch.setenv("HELMET_GUARD_MODE", "live")
    with pytest.raises(SystemExit):
        seed_demo.seed()
    # 显式临时库放行（测试隔离）
    tmp_db = tmp_path / "live-tmp.db"
    monkeypatch.setenv("HELMET_GUARD_DB", str(tmp_db))
    info = seed_demo.seed(str(tmp_db))
    assert Path(info["db"]) == tmp_db
    # 传参 db_path 同样放行
    tmp_db2 = tmp_path / "live-tmp2.db"
    info2 = seed_demo.seed(tmp_db2)
    assert Path(info2["db"]) == tmp_db2


def test_health_model_failed_weight(monkeypatch, tmp_path):
    from app import seed_demo
    from app.db import connect

    db = tmp_path / "hb-bad.pt.db"
    seed_demo.seed(db)
    conn = connect(db)
    try:
        _beat(
            conn,
            run_id="live-run-bad",
            mode="live",
            model_loaded=False,
            model_ok=False,
            stage="model_failed",
            error="broken file",
            had_first_frame=False,
            frames=0,
        )
    finally:
        conn.close()
    c = _client_for(db, monkeypatch, "live")
    h = c.get("/health").json()
    assert h["model"]["ready"] is False
    assert "模型加载失败" in h["model"]["reason"]
    assert h["capture"]["ready"] is False


def test_health_no_first_frame(monkeypatch, tmp_path):
    from app import seed_demo
    from app.db import connect

    db = tmp_path / "hb-noframe.db"
    seed_demo.seed(db)
    conn = connect(db)
    try:
        _beat(
            conn,
            run_id="live-run-nf",
            mode="live",
            stage="no_first_frame",
            had_first_frame=False,
            frames=0,
        )
    finally:
        conn.close()
    c = _client_for(db, monkeypatch, "live")
    h = c.get("/health").json()
    assert h["capture"]["ready"] is False
    assert "无首帧" in h["capture"]["reason"]


def test_health_stopped_run(monkeypatch, tmp_path):
    from app import seed_demo
    from app.db import connect

    db = tmp_path / "hb-stopped.db"
    seed_demo.seed(db)
    conn = connect(db)
    try:
        _beat(
            conn,
            run_id="live-run-stop",
            mode="live-stopped",
            stage="stopped",
            had_first_frame=True,
            frames=42,
        )
    finally:
        conn.close()
    c = _client_for(db, monkeypatch, "live")
    h = c.get("/health").json()
    assert h["capture"]["ready"] is False
    assert "已停止" in h["capture"]["reason"]
    assert "42" in h["capture"]["reason"]


def test_health_camera_check_heartbeat(monkeypatch, tmp_path):
    from app import seed_demo
    from app.db import connect

    db = tmp_path / "hb-cc.db"
    seed_demo.seed(db)
    conn = connect(db)
    try:
        _beat(
            conn,
            run_id="camera_check-run-1",
            mode="camera_check",
            model_ok=False,
            model_info="COCO 通用权重",
            had_first_frame=True,
            frames=5,
        )
    finally:
        conn.close()
    c = _client_for(db, monkeypatch, "demo")
    h = c.get("/health").json()
    assert h["capture"]["ready"] is False
    assert "camera_check" in h["capture"]["reason"]


def test_health_live_running_ok(monkeypatch, tmp_path):
    from app import seed_demo
    from app.db import connect

    db = tmp_path / "hb-ok.db"
    seed_demo.seed(db)
    conn = connect(db)
    try:
        _beat(
            conn,
            run_id="live-run-ok",
            mode="live",
            model_info="专用权重已就绪",
            had_first_frame=True,
            frames=7,
        )
    finally:
        conn.close()
    c = _client_for(db, monkeypatch, "live")
    h = c.get("/health").json()
    assert h["model"]["ready"] is True
    assert h["capture"]["ready"] is True
    assert "live-run-ok" in h["capture"]["reason"]


def test_queries_do_not_rebuild_missing_db(monkeypatch, tmp_path):
    """查询接口不再重复建库：未初始化返回 503，文件不被重建。"""
    db = tmp_path / "missing.db"
    assert not db.exists()
    c = _client_for(db, monkeypatch, "demo")
    r = c.get("/api/v1/stats")
    assert r.status_code == 503
    r2 = c.get("/api/v1/events")
    assert r2.status_code == 503
    r3 = c.post("/api/v1/events/evt-x/review", json={"decision": "confirmed"})
    assert r3.status_code == 503
    # 查询只读不建表：即使连接产生空库文件，业务表也不应被创建
    import sqlite3 as _sqlite

    conn = _sqlite.connect(str(db))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            " AND name IN ('sources','passes','events','reviews',"
            "'heartbeats','alerts')"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 0
    h = c.get("/health").json()
    assert h["db"]["ok"] is False

"""自查接口回归：有效图 / 损坏图 / 无目标 / 缺模型 / 字段名。照片不写库。"""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image


def _client_for(db, monkeypatch, mode: str = "demo") -> TestClient:
    monkeypatch.setenv("HELMET_GUARD_DB", str(db))
    monkeypatch.setenv("HELMET_GUARD_MODE", mode)
    import importlib

    from app import main as main_mod

    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def _valid_bytes() -> bytes:
    from app import PROJECT_ROOT

    imgs = sorted((PROJECT_ROOT / "dataset" / "ebike_helmet_v2" / "valid" / "images").glob("*.jpg"))
    assert imgs, "缺少验证集样本"
    return imgs[1].read_bytes()


def test_selfcheck_valid_image(tmp_path, monkeypatch):
    from app import seed_demo

    db = tmp_path / "sc-valid.db"
    seed_demo.seed(db)
    c = _client_for(db, monkeypatch, "demo")
    r = c.post("/api/v1/self-check", files={"file": ("valid.jpg", _valid_bytes(), "image/jpeg")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] in ("helmeted", "bare", "unknown")
    assert "model_version" in body and "inference_ms" in body
    assert "boxes" in body and isinstance(body["boxes"], list)
    for b in body["boxes"]:
        assert {"label", "confidence", "xyxy"} <= set(b.keys())
        x1, y1, x2, y2 = b["xyxy"]
        assert 0.0 <= x1 <= x2 <= 1.0 and 0.0 <= y1 <= y2 <= 1.0
    # 照片不写库：passes 仍为种子 10 条
    assert c.get("/api/v1/stats").json()["total"] == 10


def test_selfcheck_corrupt_image(tmp_path, monkeypatch):
    from app import seed_demo

    db = tmp_path / "sc-corrupt.db"
    seed_demo.seed(db)
    c = _client_for(db, monkeypatch, "demo")
    r = c.post("/api/v1/self-check", files={"file": ("bad.jpg", b"not-an-image", "image/jpeg")})
    assert r.status_code == 400


def test_selfcheck_no_target(tmp_path, monkeypatch):
    from app import seed_demo

    db = tmp_path / "sc-blank.db"
    seed_demo.seed(db)
    c = _client_for(db, monkeypatch, "demo")
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), "white").save(buf, format="JPEG")
    r = c.post("/api/v1/self-check", files={"file": ("blank.jpg", buf.getvalue(), "image/jpeg")})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unknown" and body["reason_code"] == "no_target"


def test_selfcheck_missing_weights(tmp_path, monkeypatch):
    from app import seed_demo

    db = tmp_path / "sc-noweight.db"
    seed_demo.seed(db)
    monkeypatch.setenv("HELMET_GUARD_SELFCHECK_WEIGHTS", str(tmp_path / "missing.pt"))
    c = _client_for(db, monkeypatch, "demo")
    r = c.post("/api/v1/self-check", files={"file": ("v.jpg", _valid_bytes(), "image/jpeg")})
    assert r.status_code == 503
    r2 = c.get("/api/v1/self-check/status")
    assert r2.status_code == 503


def test_selfcheck_wrong_field(tmp_path, monkeypatch):
    from app import seed_demo

    db = tmp_path / "sc-field.db"
    seed_demo.seed(db)
    c = _client_for(db, monkeypatch, "demo")
    r = c.post("/api/v1/self-check", files={"wrong": ("v.jpg", _valid_bytes(), "image/jpeg")})
    assert r.status_code == 422

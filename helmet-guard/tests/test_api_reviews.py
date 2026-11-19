"""P3-2 审批中心后端测试：筛选、详情聚合、pending-count、批量 note。

职责：覆盖决策列表多维筛选（点位/置信度/排序白名单）、详情聚合载荷
（事件/身份/学生/风险提示）、待审批计数与批量批准的 note 透传。
依赖：FastAPI TestClient、SQLAlchemy。
边界：不测前端渲染与快捷键。
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.security import CurrentUser
from app.models.appeal import Appeal
from app.models.decision import Decision
from app.models.entities import Event, Pass, Source
from app.models.identity import IdentityResolution, Student
from app.models.scoring import ScoreAccount


def _auth_override(subject: str, role: str):  # type: ignore[no-untyped-def]
    """构造鉴权覆盖函数。"""

    def _dep() -> CurrentUser:
        return CurrentUser(subject=subject, role=role, claims={})

    return _dep


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """绑定临时库的 TestClient，并预置多档位决策与关联数据。"""
    project_dir = Path(__file__).resolve().parent.parent
    db_path = tmp_path / "review-api.db"
    alembic_config = Config(str(project_dir / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(project_dir / "migrations"))
    alembic_config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(alembic_config, "head")

    monkeypatch.setenv("HELMET_GUARD_DB", str(db_path))
    monkeypatch.setenv("HELMET_GUARD_MODE", "demo")
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-for-production")

    # 只清 settings 单例缓存，不 reload config/deps 模块 ——
    # reload 会让路由依赖的 get_current_user 与 dependency_overrides 引用
    # 不同函数对象，导致覆盖失效（403）。DATABASE_URL 优先级最高，
    # 显式指定可保证 engine 与 Alembic 库指向同一文件。
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")

    import app.core.config as config_mod

    config_mod.get_settings.cache_clear()

    import app.main as main_mod

    importlib.reload(main_mod)

    now = datetime.now(UTC).replace(tzinfo=None)
    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        engine = client.app.state.db_engine  # type: ignore[attr-defined]
        with Session(engine, future=True) as session:
            session.add(
                Source(
                    source_id="gate-east",
                    name="东校门",
                    status="online",
                    last_seen=now.isoformat(),
                    updated_at=now.isoformat(),
                )
            )
            session.add(
                Student(
                    student_id="S001",
                    name="张三",
                    status="active",
                    college="计算机学院",
                    class_name="计科2201",
                )
            )
            session.add(
                ScoreAccount(
                    student_id="S001",
                    balance=97,
                    total_deducted=3,
                    total_awarded=0,
                    level="B",
                    streak_days=5,
                    compliance_rate=0.93,
                )
            )
            session.add(
                Appeal(
                    appeal_id="ap-1",
                    decision_id="dec-old",
                    student_id="S001",
                    reason="当时戴了头盔",
                    attachments=[],
                    status="upheld",
                )
            )
            for index, (level, point, confidence) in enumerate(
                [("L3", "gate-east", 0.91), ("L2", "gate-west", 0.88), ("L1", "gate-east", 0.72)]
            ):
                event_id = f"e-{index}"
                pass_id = f"p-{index}"
                ts = (now - timedelta(hours=index)).isoformat()
                # 仅第一条带检测框证据（其余保持 None，验证缺失时降级正常）。
                boxes_json = (
                    json.dumps(
                        [
                            {
                                "label": "Cyclists",
                                "confidence": 0.97,
                                "xyxy": [0.12, 0.08, 0.48, 0.92],
                            },
                            {
                                "label": "no helmet",
                                "confidence": 0.93,
                                "xyxy": [0.2, 0.1, 0.32, 0.25],
                            },
                        ],
                        ensure_ascii=False,
                    )
                    if index == 0
                    else None
                )
                session.add(
                    Pass(
                        pass_id=pass_id,
                        source_id=point,
                        run_id="run-1",
                        occurred_at=ts,
                        rider_status="bare",
                        model_raw="no helmet",
                        boxes=boxes_json,
                        image_width=1920 if index == 0 else None,
                        image_height=1080 if index == 0 else None,
                        created_at=ts,
                    )
                )
                session.add(
                    Event(
                        event_id=event_id,
                        pass_id=pass_id,
                        source_id=point,
                        run_id="run-1",
                        occurred_at=ts,
                        status="pending",
                        model_label="no helmet",
                        reason="检测到未佩戴头盔",
                        created_at=ts,
                    )
                )
                session.add(
                    IdentityResolution(
                        event_id=event_id,
                        vehicle_id=f"veh-{index}",
                        subject_id="S001",
                        method="plate",
                        confidence=0.93,
                        plate_conf=0.95,
                        appearance_conf=0.5,
                        cooccur_conf=0.4,
                        matched_count=2,
                        snapshot_id=f"snap-{index}",
                    )
                )
                session.add(
                    Decision(
                        decision_id=f"dec-{index}",
                        event_id=event_id,
                        student_id="S001",
                        level=level,
                        action="deduct_score",
                        score_delta=-1,
                        reason_code="REPEAT_WITHIN_30D",
                        message="近 30 天第二次未佩戴头盔，建议保持佩戴。",
                        confidence=confidence,
                        factors=[
                            {
                                "name": "模型置信度",
                                "value": confidence,
                                "weight": 0.35,
                                "evidence": "检测框 no helmet 0.91",
                            }
                        ],
                        evidence_refs={"snapshot_id": f"snap-{index}"},
                        status="PENDING_REVIEW",
                    )
                )
            session.commit()
        yield client


def _login(client: TestClient, role: str = "super_admin") -> None:
    """注入鉴权覆盖。"""
    client.app.dependency_overrides[get_current_user] = _auth_override("admin1", role)


def test_list_filters_by_level(api_client: TestClient) -> None:
    """按档位筛选只返回匹配决策。"""
    _login(api_client)
    try:
        response = api_client.get("/api/v1/admin/decisions", params={"level": "L3"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["level"] == "L3"
    finally:
        api_client.app.dependency_overrides.clear()


def test_list_filters_by_point(api_client: TestClient) -> None:
    """按点位筛选生效（join events）。"""
    _login(api_client)
    try:
        response = api_client.get("/api/v1/admin/decisions", params={"point_id": "gate-west"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["event_id"] == "e-1"
    finally:
        api_client.app.dependency_overrides.clear()


def test_list_filters_by_min_confidence(api_client: TestClient) -> None:
    """按最低置信度筛选。"""
    _login(api_client)
    try:
        response = api_client.get(
            "/api/v1/admin/decisions", params={"min_confidence": 0.85}
        )
        assert response.status_code == 200
        assert response.json()["total"] == 2
    finally:
        api_client.app.dependency_overrides.clear()


def test_list_sort_white_list(api_client: TestClient) -> None:
    """排序白名单生效；非法排序回退默认（创建时间倒序）。"""
    _login(api_client)
    try:
        by_conf = api_client.get(
            "/api/v1/admin/decisions", params={"sort": "confidence/desc"}
        )
        assert by_conf.status_code == 200
        items = by_conf.json()["items"]
        confidences = [float(i["confidence"]) for i in items]
        assert confidences == sorted(confidences, reverse=True)
        fallback = api_client.get(
            "/api/v1/admin/decisions", params={"sort": "unknown/drop"}
        )
        assert fallback.status_code == 200
        assert fallback.json()["total"] == 3
    finally:
        api_client.app.dependency_overrides.clear()


def test_list_filters_by_status(api_client: TestClient) -> None:
    """按状态筛选（待审批）。"""
    _login(api_client)
    try:
        response = api_client.get(
            "/api/v1/admin/decisions", params={"status": "PENDING_REVIEW"}
        )
        assert response.status_code == 200
        assert response.json()["total"] == 3
    finally:
        api_client.app.dependency_overrides.clear()


def test_pending_count(api_client: TestClient) -> None:
    """待审批计数端点返回正确数量。"""
    _login(api_client)
    try:
        response = api_client.get("/api/v1/admin/decisions/pending-count")
        assert response.status_code == 200
        assert response.json()["pending"] == 3
    finally:
        api_client.app.dependency_overrides.clear()


def test_detail_contains_aggregate_payload(api_client: TestClient) -> None:
    """详情返回事件/身份/学生/风险提示聚合载荷。"""
    _login(api_client)
    try:
        response = api_client.get("/api/v1/admin/decisions/dec-0")
        assert response.status_code == 200
        data = response.json()
        assert data["decision_id"] == "dec-0"
        assert data["event"]["source_id"] == "gate-east"
        assert data["event"]["model_label"] == "no helmet"
        assert data["identity_resolution"]["method"] == "plate"
        assert data["identity_resolution"]["confidence"] == 0.93
        assert data["student"]["student_id"] == "S001"
        assert data["student"]["balance"] == 97
        assert data["student"]["streak_days"] == 5
        assert isinstance(data["risk_hints"], list)
        assert len(data["risk_hints"]) > 0
        # 因子仍是数组形态（可解释）。
        assert isinstance(data["factors"], list)
    finally:
        api_client.app.dependency_overrides.clear()


def test_detail_risk_hint_mentions_appeal_history(api_client: TestClient) -> None:
    """历史申诉成立的风险提示必须出现。"""
    _login(api_client)
    try:
        response = api_client.get("/api/v1/admin/decisions/dec-0")
        assert response.status_code == 200
        codes = [h["code"] for h in response.json()["risk_hints"]]
        assert "APPEAL_UPRELD_HISTORY" in codes
    finally:
        api_client.app.dependency_overrides.clear()


def test_detail_not_found(api_client: TestClient) -> None:
    """不存在的决策返回 404。"""
    _login(api_client)
    try:
        response = api_client.get("/api/v1/admin/decisions/does-not-exist")
        assert response.status_code == 404
    finally:
        api_client.app.dependency_overrides.clear()


def test_batch_approve_returns_per_item_status(api_client: TestClient) -> None:
    """批量批准逐条返回成功/失败统计。"""
    _login(api_client)
    try:
        response = api_client.post(
            "/api/v1/admin/decisions/batch-approve",
            json={"decision_ids": ["dec-0", "dec-1"], "note": "批量核验"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert all(item["ok"] for item in data["items"])
        assert all(item["status"] == "APPROVED" for item in data["items"])
    finally:
        api_client.app.dependency_overrides.clear()


def test_batch_approve_partial_failure(api_client: TestClient) -> None:
    """批量批准中单条失败不影响其他条目。"""
    _login(api_client)
    try:
        response = api_client.post(
            "/api/v1/admin/decisions/batch-approve",
            json={"decision_ids": ["dec-0", "missing-id"]},
        )
        assert response.status_code == 200
        items = response.json()["items"]
        assert items[0]["ok"] is True
        assert items[1]["ok"] is False
        assert items[1]["error"]
    finally:
        api_client.app.dependency_overrides.clear()


def test_list_requires_read_permission(api_client: TestClient) -> None:
    """学生角色访问决策列表按无资源处理（404）。"""
    _login(api_client, "student")
    try:
        response = api_client.get("/api/v1/admin/decisions")
        assert response.status_code == 404
    finally:
        api_client.app.dependency_overrides.clear()


def test_detail_contains_detection_boxes(api_client: TestClient) -> None:
    """详情返回检测框与原图尺寸（前端据此渲染证据叠加）。"""
    _login(api_client)
    try:
        response = api_client.get("/api/v1/admin/decisions/dec-0")
        assert response.status_code == 200
        refs = response.json()["evidence_refs"]
        assert refs["image_width"] == 1920
        assert refs["image_height"] == 1080
        boxes = refs["boxes"]
        assert len(boxes) == 2
        assert boxes[0]["label"] == "Cyclists"
        assert boxes[0]["confidence"] == 0.97
        # xyxy 为归一化坐标（0~1），保证与容器同坐标系。
        assert boxes[0]["xyxy"] == [0.12, 0.08, 0.48, 0.92]
    finally:
        api_client.app.dependency_overrides.clear()


def test_detail_evidence_degrades_when_boxes_missing(api_client: TestClient) -> None:
    """无检测框数据时降级为空列表，不影响详情其余内容。"""
    _login(api_client)
    try:
        response = api_client.get("/api/v1/admin/decisions/dec-1")
        assert response.status_code == 200
        data = response.json()
        assert data["evidence_refs"]["boxes"] == []
        assert data["evidence_refs"]["image_width"] is None
        # 降级不影响文本结论与因子。
        assert data["decision_id"] == "dec-1"
        assert data["student"]["student_id"] == "S001"
    finally:
        api_client.app.dependency_overrides.clear()

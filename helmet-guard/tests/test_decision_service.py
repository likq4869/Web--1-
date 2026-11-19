"""P2-3 决策服务测试：编排幂等、审批并发幂等、批量、逾期、RBAC、API。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any, cast

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.security import CurrentUser
from app.models.decision import Decision, FeedbackSample
from app.models.entities import Event, Pass
from app.models.identity import CounselorAssignment, IdentityResolution, Student, User
from app.models.scoring import ScoreAccount, ScoreLedger
from app.services.appeal.service import AppealService
from app.services.decision.engine import DecisionEngine
from app.services.decision.review import ReviewService

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _alembic_config(db_path: Path) -> Config:
    config = Config(str(PROJECT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return config


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "decision.db"
    command.upgrade(_alembic_config(path), "head")
    return path


def _engine_for(path: Path) -> Engine:
    return create_engine(f"sqlite:///{path.as_posix()}", future=True)


@pytest.fixture()
def session(db_path: Path) -> Iterator[Session]:
    engine = _engine_for(db_path)
    try:
        with Session(engine, future=True) as db_session:
            yield db_session
    finally:
        engine.dispose()


def _seed_student(session: Session, student_id: str = "S001",
                  class_name: str = "计科2401") -> None:
    if session.get(Student, student_id) is None:
        session.add(Student(student_id=student_id, user_id=None,
                            name=f"学生{student_id}", class_name=class_name,
                            status="active"))
        session.flush()
    if session.get(ScoreAccount, student_id) is None:
        session.add(ScoreAccount(student_id=student_id, balance=100,
                                 total_deducted=0, total_awarded=0,
                                 level="B", streak_days=0, compliance_rate=1.0))
        session.flush()


def _seed_event(session: Session, event_id: str, student_id: str | None,
                rider_status: str = "bare",
                identity_conf: float = 0.85) -> None:
    """预置通行 + 事件 + 身份判定（引擎编排的最小闭环）。"""
    if student_id:
        _seed_student(session, student_id)
    pass_id = f"p-{event_id}"
    session.add(Pass(pass_id=pass_id, source_id="gate-east", run_id="r1",
                     occurred_at=datetime.now(UTC).isoformat(),
                     rider_status=rider_status, model_raw="no helmet",
                     created_at="t"))
    session.add(Event(event_id=event_id, pass_id=pass_id, source_id="gate-east",
                      run_id="r1",
                      occurred_at=datetime.now(UTC).isoformat(),
                      status="pending", model_label="no helmet", reason="",
                      reviewer="", reviewed_at=None, created_at="t"))
    if student_id is not None:
        session.add(IdentityResolution(
            event_id=event_id, vehicle_id="veh-1", subject_id=student_id,
            method="plate", confidence=identity_conf, plate_conf=identity_conf,
            appearance_conf=0.0, cooccur_conf=0.0, matched_count=1,
            snapshot_id=None))
    session.flush()


def _make_pending(session: Session, decision_id: str = "dec-1",
                  event_id: str = "ev-1", student_id: str = "S001",
                  level: str = "L2", score_delta: int = -1,
                  due_future: bool = True) -> Decision:
    _seed_student(session, student_id)
    now = datetime.now(UTC)
    due = now + timedelta(days=7) if due_future else now - timedelta(days=1)
    row = Decision(decision_id=decision_id, event_id=event_id,
                   student_id=student_id, level=level,
                   action="deduct_score", score_delta=score_delta,
                   reason_code="REPEAT_WITHIN_30D", message="测试",
                   confidence=0.9, factors=[], evidence_refs={},
                   policy_version="v1", status="PENDING_REVIEW",
                   auto_approved=False, due_at=due)
    session.add(row)
    session.commit()
    session.expunge_all()
    fetched = session.get(Decision, decision_id)
    assert fetched is not None
    return fetched


# ------------------------------------------------------------------
# 引擎编排
# ------------------------------------------------------------------

def test_engine_first_offense_auto_approved(session: Session) -> None:
    _seed_event(session, "ev-auto", "S001", rider_status="bare", identity_conf=0.9)
    session.commit()
    outcome = DecisionEngine(session, now=datetime.now(UTC)).decide_for_event("ev-auto")
    assert outcome is not None
    assert outcome.decision.level == "L1"
    assert outcome.decision.status == "AUTO_APPROVED"
    assert outcome.auto_applied is True


def test_engine_second_offense_pending_and_idempotent(session: Session) -> None:
    now = datetime.now(UTC)
    _make_pending(session, decision_id="dec-prior", event_id="ev-prior",
                  student_id="S001", level="L2", score_delta=-1)
    # 将既有决策生效化，使其计入窗口统计。
    ReviewService(session).approve("dec-prior", "admin", "super_admin")
    _seed_event(session, "ev-new", "S001", rider_status="bare", identity_conf=0.9)
    session.commit()
    engine = DecisionEngine(session, now=now)
    first = engine.decide_for_event("ev-new")
    assert first is not None
    assert first.decision.level == "L2"
    assert first.decision.status == "PENDING_REVIEW"
    second = engine.decide_for_event("ev-new")
    assert second is not None
    assert second.decision.decision_id == first.decision.decision_id


def test_engine_missing_event_returns_none(session: Session) -> None:
    assert DecisionEngine(session).decide_for_event("missing") is None


def test_simulate_is_read_only(session: Session) -> None:
    from app.services.decision.engine import result_from_decision

    _make_pending(session, decision_id="dec-sim", event_id="ev-sim")
    from app.repositories.decision import DecisionRepository

    before = DecisionRepository(session).count_with_filters()
    row = session.get(Decision, "dec-sim")
    assert row is not None
    snapshot = result_from_decision(row)
    assert snapshot.level.value == "L2"
    after = DecisionRepository(session).count_with_filters()
    assert before == after


# ------------------------------------------------------------------
# 审批：批准 / 降档 / 幂等 / 并发
# ------------------------------------------------------------------

def test_approve_applies_ledger(session: Session) -> None:
    _make_pending(session, decision_id="dec-ap", event_id="ev-ap",
                  student_id="S001", level="L2", score_delta=-1)
    decided = ReviewService(session).approve("dec-ap", "admin", "super_admin")
    assert decided.status == "APPROVED"
    assert session.get(ScoreAccount, "S001") is not None
    account = session.get(ScoreAccount, "S001")
    assert account is not None and int(account.balance) == 99
    rows = session.query(ScoreLedger).filter(
        ScoreLedger.decision_id == "dec-ap").all()
    assert len(rows) == 1 and int(rows[0].change) == -1


def test_approve_downgrade_syncs_score_and_blocks_upgrade(session: Session) -> None:
    _make_pending(session, decision_id="dec-dg", event_id="ev-dg",
                  student_id="S001", level="L3", score_delta=-3)
    with pytest.raises(ValidationError):
        ReviewService(session).approve("dec-dg", "admin", "super_admin", level="L4")
    decided = ReviewService(session).approve("dec-dg", "admin", "super_admin", level="L2")
    assert decided.status == "ADJUSTED"
    assert decided.level == "L2"
    assert int(decided.score_delta) == -1
    assert decided.original_level == "L3"


def test_approve_idempotent(session: Session) -> None:
    _make_pending(session, decision_id="dec-idem", event_id="ev-idem")
    service = ReviewService(session)
    first = service.approve("dec-idem", "admin", "super_admin")
    second = service.approve("dec-idem", "admin", "super_admin")
    assert first.status == second.status == "APPROVED"
    rows = session.query(ScoreLedger).filter(
        ScoreLedger.decision_id == "dec-idem").all()
    assert len(rows) == 1


def test_concurrent_approve_single_ledger(db_path: Path) -> None:
    engine = _engine_for(db_path)
    try:
        with Session(engine, future=True) as setup:
            _make_pending(setup, decision_id="dec-cc", event_id="ev-cc")
        barrier = Barrier(2)

        def _hit() -> str:
            local_engine = _engine_for(db_path)
            try:
                with Session(local_engine, future=True) as local:
                    barrier.wait(timeout=15)
                    # SQLite 写锁竞争时重试：并发批准语义是幂等收敛，
                    # 瞬时 locked 不应计为失败。
                    last_error: Exception | None = None
                    for _ in range(5):
                        try:
                            decided = ReviewService(local).approve(
                                "dec-cc", "admin", "super_admin")
                            return str(decided.status)
                        except Exception as exc:  # noqa: BLE001
                            last_error = exc
                            if "locked" not in str(exc).lower():
                                raise
                            local.rollback()
                            import time as _time

                            _time.sleep(0.05)
                    raise last_error  # type: ignore[misc]
            finally:
                local_engine.dispose()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_hit), pool.submit(_hit)]
            results = sorted([future.result(timeout=60) for future in futures])
        assert results == ["APPROVED", "APPROVED"]
        with Session(engine, future=True) as check:
            rows = check.query(ScoreLedger).filter(
                ScoreLedger.decision_id == "dec-cc").all()
            assert len(rows) == 1
    finally:
        engine.dispose()


def test_reject_writes_feedback(session: Session) -> None:
    _make_pending(session, decision_id="dec-rj", event_id="ev-rj")
    decided = ReviewService(session).reject("dec-rj", "admin", "super_admin", "误判")
    assert decided.status == "REJECTED"
    samples = session.query(FeedbackSample).filter(
        FeedbackSample.decision_id == "dec-rj").all()
    assert len(samples) == 1
    assert samples[0].source == "review_reject"
    # 幂等：重复驳回返回同一行，不新增样本。
    again = ReviewService(session).reject("dec-rj", "admin", "super_admin", "误判")
    assert again.status == "REJECTED"
    assert session.query(FeedbackSample).filter(
        FeedbackSample.decision_id == "dec-rj").count() == 1


def test_batch_approve_partial_success(session: Session) -> None:
    _make_pending(session, decision_id="dec-b1", event_id="ev-b1")
    results = ReviewService(session).batch_approve(
        ["dec-b1", "missing"], "admin", "super_admin")
    assert results[0]["ok"] is True and results[0]["status"] == "APPROVED"
    assert results[1]["ok"] is False and results[1]["error"]


def test_expire_overdue_auto_escalate_expire(session: Session) -> None:
    _make_pending(session, decision_id="dec-l1", event_id="ev-l1",
                  level="L1", score_delta=0, due_future=False)
    _make_pending(session, decision_id="dec-l2", event_id="ev-l2",
                  level="L2", score_delta=-1, due_future=False)
    _make_pending(session, decision_id="dec-l3", event_id="ev-l3",
                  level="L3", score_delta=-3, due_future=False)
    _make_pending(session, decision_id="dec-l0", event_id="ev-l0",
                  level="L0", score_delta=0, due_future=False)
    counts = ReviewService(session).expire_overdue(now=datetime.now(UTC))
    assert counts == {"auto_approved": 2, "escalated": 1, "expired": 1}
    assert session.get(Decision, "dec-l1").status == "AUTO_APPROVED"  # type: ignore[union-attr]
    assert session.get(Decision, "dec-l2").status == "AUTO_APPROVED"  # type: ignore[union-attr]
    assert session.get(Decision, "dec-l3").status == "PENDING_REVIEW"  # type: ignore[union-attr]
    assert session.get(Decision, "dec-l0").status == "EXPIRED"  # type: ignore[union-attr]


# ------------------------------------------------------------------
# RBAC
# ------------------------------------------------------------------

def test_rbac_l3_requires_league_officer(session: Session) -> None:
    _make_pending(session, decision_id="dec-l3rb", event_id="ev-l3rb",
                  level="L3", score_delta=-3)
    with pytest.raises(PermissionDeniedError):
        ReviewService(session).approve("dec-l3rb", "c1", "counselor")
    with pytest.raises(PermissionDeniedError):
        ReviewService(session).approve("dec-l3rb", "sec", "security_officer")
    decided = ReviewService(session).approve(
        "dec-l3rb", "officer", "league_officer")
    assert decided.status == "APPROVED"


def test_rbac_counselor_scope_isolation(session: Session) -> None:
    session.add(User(user_id="c1", username="辅导员", role="counselor", status="active"))
    session.flush()
    session.add(CounselorAssignment(user_id="c1", class_name="计科2401"))
    session.flush()
    _seed_student(session, "SCOPE-IN", class_name="计科2401")
    _seed_student(session, "SCOPE-OUT", class_name="计科2402")
    session.commit()
    _make_pending(session, decision_id="dec-in", event_id="ev-in",
                  student_id="SCOPE-IN")
    _make_pending(session, decision_id="dec-out", event_id="ev-out",
                  student_id="SCOPE-OUT")
    ok_decision = ReviewService(session).approve("dec-in", "c1", "counselor")
    assert ok_decision.status == "APPROVED"
    with pytest.raises(NotFoundError):
        ReviewService(session).approve("dec-out", "c1", "counselor")


def test_approve_after_reject_conflicts(session: Session) -> None:
    _make_pending(session, decision_id="dec-cf", event_id="ev-cf")
    ReviewService(session).reject("dec-cf", "admin", "super_admin", "误判")
    with pytest.raises(ConflictError):
        ReviewService(session).approve("dec-cf", "admin", "super_admin")


# ------------------------------------------------------------------
# API 层（鉴权矩阵 + 端点语义）
# ------------------------------------------------------------------

def _auth_override(
    subject: str, role: str,
) -> Callable[[], CurrentUser]:
    def _dep() -> CurrentUser:
        return CurrentUser(subject=subject, role=role, claims={})
    return _dep


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    import importlib

    db_path = tmp_path / "decision-api.db"
    command.upgrade(_alembic_config(db_path), "head")
    monkeypatch.setenv("HELMET_GUARD_DB", str(db_path))
    monkeypatch.setenv("HELMET_GUARD_MODE", "demo")
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-for-production")
    import app.main as main_mod

    importlib.reload(main_mod)
    from app.core.config import get_settings as _get_settings

    _get_settings.cache_clear()
    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        engine = cast(Any, client.app).state.db_engine
        with Session(engine, future=True) as preset:
            preset.add(User(user_id="admin1", username="超管",
                            role="super_admin", status="active"))
            preset.add(User(user_id="c1", username="辅导员",
                            role="counselor", status="active"))
            preset.add(Student(student_id="S001", name="张三",
                               class_name="计科2401", status="active"))
            preset.flush()
            preset.add(CounselorAssignment(user_id="c1", class_name="计科2401"))
            preset.add(Decision(decision_id="dec-api-1", event_id="ev-api-1",
                                student_id="S001", level="L2",
                                action="deduct_score", score_delta=-1,
                                reason_code="REPEAT_WITHIN_30D", message="测试",
                                confidence=0.9, status="PENDING_REVIEW",
                                due_at=datetime.now(UTC) + timedelta(days=7)))
            preset.commit()
        yield client
        cast(Any, client.app).dependency_overrides.clear()


def _as(client: TestClient, subject: str, role: str) -> TestClient:
    cast(Any, client.app).dependency_overrides[get_current_user] = _auth_override(
        subject, role)
    return client


def test_api_list_detail_approve_reject_flow(api_client: TestClient) -> None:
    _as(api_client, "admin1", "super_admin")
    listing = api_client.get("/api/v1/admin/decisions")
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1
    detail = api_client.get("/api/v1/admin/decisions/dec-api-1")
    assert detail.status_code == 200
    assert detail.json()["decision_id"] == "dec-api-1"
    approved = api_client.post("/api/v1/admin/decisions/dec-api-1/approve", json={})
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    # 幂等：重复批准 200 同一终态。
    again = api_client.post("/api/v1/admin/decisions/dec-api-1/approve", json={})
    assert again.status_code == 200
    assert again.json()["status"] == "APPROVED"


def test_api_reject_requires_reason(api_client: TestClient) -> None:
    _as(api_client, "admin1", "super_admin")
    response = api_client.post("/api/v1/admin/decisions/dec-api-1/reject",
                               json={"reason": ""})
    assert response.status_code in (400, 422)


def test_api_batch_and_simulate(api_client: TestClient) -> None:
    _as(api_client, "admin1", "super_admin")
    engine = cast(Any, api_client.app).state.db_engine
    with Session(engine, future=True) as preset:
        preset.add(Decision(decision_id="dec-api-2", event_id="ev-api-2",
                            student_id="S001", level="L1",
                            action="remind", score_delta=0,
                            reason_code="FIRST_OFFENSE", message="测试",
                            confidence=0.9, status="PENDING_REVIEW",
                            due_at=datetime.now(UTC) + timedelta(days=7)))
        preset.commit()
    batch = api_client.post("/api/v1/admin/decisions/batch-approve",
                            json={"decision_ids": ["dec-api-2", "missing"]})
    assert batch.status_code == 200
    body = batch.json()
    assert body["items"][0]["ok"] is True
    assert body["items"][1]["ok"] is False
    # 模拟接口只读：调用前后总数不变。
    before = api_client.get("/api/v1/admin/decisions").json()["total"]
    simulated = api_client.post("/api/v1/admin/policies/v1/simulate")
    assert simulated.status_code == 200
    assert simulated.json()["note"]
    after = api_client.get("/api/v1/admin/decisions").json()["total"]
    assert before == after


def test_api_counselor_out_of_scope_404(api_client: TestClient) -> None:
    engine = cast(Any, api_client.app).state.db_engine
    with Session(engine, future=True) as preset:
        preset.add(Student(student_id="S002", name="李四",
                           class_name="计科2402", status="active"))
        preset.add(Decision(decision_id="dec-api-out", event_id="ev-api-out",
                            student_id="S002", level="L2",
                            action="deduct_score", score_delta=-1,
                            reason_code="REPEAT_WITHIN_30D", message="测试",
                            confidence=0.9, status="PENDING_REVIEW",
                            due_at=datetime.now(UTC) + timedelta(days=7)))
        preset.commit()
    _as(api_client, "c1", "counselor")
    response = api_client.post("/api/v1/admin/decisions/dec-api-out/approve", json={})
    assert response.status_code == 404


def test_appeal_upheld_reverts_ledger_and_feedback(session: Session) -> None:
    _make_pending(session, decision_id="dec-al", event_id="ev-al",
                  student_id="S001", level="L2", score_delta=-1)
    ReviewService(session).approve("dec-al", "admin", "super_admin")
    assert session.get(ScoreAccount, "S001") is not None
    before = int(session.get(ScoreAccount, "S001").balance)  # type: ignore[union-attr]
    appeal = AppealService(session).submit("dec-al", "S001", "我是被冤枉的")
    assert appeal.status == "pending"
    resolved = AppealService(session).resolve(
        str(appeal.appeal_id), "officer", "league_officer", upheld=True,
        note="证据不足")
    assert resolved.status == "upheld"
    assert int(session.get(ScoreAccount, "S001").balance) == before + 1  # type: ignore[union-attr]
    samples = session.query(FeedbackSample).filter(
        FeedbackSample.appeal_id == appeal.appeal_id).all()
    assert len(samples) == 1 and samples[0].source == "appeal_upheld"
    assert session.get(Decision, "dec-al").status == "APPEAL_UPHELD"  # type: ignore[union-attr]

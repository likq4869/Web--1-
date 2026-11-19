"""多证据身份融合测试：阈值/冲突/边界/端到端编排。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from alembic import command
from alembic.config import Config
from numpy.typing import NDArray
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.identity_fusion import (
    AUTO_BIND_THRESHOLD,
    SUGGEST_THRESHOLD,
    Evidence,
    EvidenceMethod,
    FusionPolicy,
    IdentityDecision,
    classify_confidence,
    explain_outcome,
    fuse_evidence,
)

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _ev(
    method: EvidenceMethod,
    conf: float,
    subject: str | None = "S001",
    vehicle: str | None = "veh_001",
    detail: str = "",
) -> Evidence:
    """构造单条证据的便捷工厂。"""
    return Evidence(
        method=method, confidence=conf, detail=detail, subject_id=subject, vehicle_id=vehicle
    )


def test_plate_only_binds() -> None:
    """仅车牌 0.95 → BIND（强证据一票主导）。"""
    outcome = fuse_evidence([_ev(EvidenceMethod.PLATE, 0.95, detail="车牌 皖A12345")])
    assert outcome.decision is IdentityDecision.BIND
    assert outcome.confidence >= AUTO_BIND_THRESHOLD
    assert outcome.subject_id == "S001"
    assert 0.0 <= outcome.confidence <= 1.0


def test_appearance_only_suggests() -> None:
    """仅外观 0.72 → SUGGEST（权重 0.8 打折后落入疑似区间）。"""
    outcome = fuse_evidence([_ev(EvidenceMethod.APPEARANCE, 0.72)])
    assert outcome.decision is IdentityDecision.SUGGEST
    assert SUGGEST_THRESHOLD <= outcome.confidence < AUTO_BIND_THRESHOLD


def test_cooccur_only_unbounds() -> None:
    """仅共现 0.45 → UNBOUND（弱证据单独无法达线）。"""
    outcome = fuse_evidence([_ev(EvidenceMethod.COOCCUR, 0.45)])
    assert outcome.decision is IdentityDecision.UNBOUND
    assert outcome.confidence < SUGGEST_THRESHOLD


def test_strong_plate_dominates_weak_appearance() -> None:
    """车牌 0.95 + 外观 0.3 → BIND（强证据主导，弱反对被淹没）。"""
    outcome = fuse_evidence(
        [_ev(EvidenceMethod.PLATE, 0.95), _ev(EvidenceMethod.APPEARANCE, 0.3)]
    )
    assert outcome.decision is IdentityDecision.BIND
    assert outcome.subject_id == "S001"


def test_conflicting_subjects_force_unbound() -> None:
    """车牌指 A + 外观指 B → UNBOUND（冲突，置信度仍返回供展示）。"""
    outcome = fuse_evidence(
        [
            _ev(EvidenceMethod.PLATE, 0.95, subject="S001", vehicle="veh_001"),
            _ev(EvidenceMethod.APPEARANCE, 0.90, subject="S002", vehicle="veh_002"),
        ]
    )
    assert outcome.decision is IdentityDecision.UNBOUND
    assert outcome.vehicle_id is None
    assert outcome.subject_id is None
    assert "不一致" in outcome.reason


def test_empty_evidence_unbounds_with_prior() -> None:
    """空证据列表 → UNBOUND，先验置信度 0.05。"""
    outcome = fuse_evidence([])
    assert outcome.decision is IdentityDecision.UNBOUND
    assert outcome.confidence == pytest.approx(0.05)
    assert outcome.method is EvidenceMethod.NONE


def test_probability_one_clamped_without_crash() -> None:
    """p=1.0 的证据不崩溃（钳制后综合置信度仍 ≤ 1）。"""
    outcome = fuse_evidence([_ev(EvidenceMethod.MANUAL, 1.0)])
    assert outcome.decision is IdentityDecision.BIND
    assert outcome.confidence <= 1.0
    outcome_zero = fuse_evidence([_ev(EvidenceMethod.COOCCUR, 0.0)])
    assert 0.0 <= outcome_zero.confidence <= 1.0


def test_invalid_confidence_rejected() -> None:
    """非法置信度（越界/NaN/inf）必须 ValueError。"""
    with pytest.raises(ValueError):
        fuse_evidence([_ev(EvidenceMethod.PLATE, 1.5)])
    with pytest.raises(ValueError):
        fuse_evidence([_ev(EvidenceMethod.PLATE, -0.1)])
    with pytest.raises(ValueError):
        fuse_evidence([_ev(EvidenceMethod.PLATE, float("nan"))])
    with pytest.raises(ValueError):
        fuse_evidence([_ev(EvidenceMethod.PLATE, float("inf"))])


def test_threshold_boundaries() -> None:
    """阈值边界：恰好 0.85 → BIND；0.5999 → UNBOUND。"""
    assert classify_confidence(0.85) is IdentityDecision.BIND
    assert classify_confidence(0.8499) is IdentityDecision.SUGGEST
    assert classify_confidence(0.60) is IdentityDecision.SUGGEST
    assert classify_confidence(0.5999) is IdentityDecision.UNBOUND
    assert classify_confidence(0.0) is IdentityDecision.UNBOUND
    assert classify_confidence(1.0) is IdentityDecision.BIND


def test_explain_outcome_readable() -> None:
    """解释函数输出人话：含判定、置信度、逐证据行。"""
    outcome = fuse_evidence(
        [
            _ev(EvidenceMethod.PLATE, 0.95, detail="车牌 皖A12345"),
            _ev(EvidenceMethod.APPEARANCE, 0.72, detail="外观相似度 0.72"),
        ]
    )
    text = explain_outcome(outcome)
    assert "综合置信度" in text
    assert "车牌识别" in text
    assert "外观特征" in text
    assert "皖A12345" in text


def _alembic_config(db_path: Path) -> Config:
    config = Config(str(PROJECT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return config


def _make_frame(
    color: tuple[int, int, int],
) -> tuple[NDArray[np.uint8], tuple[float, float, float, float]]:
    """构造仿真 BGR 帧：上部骑手灰 + 下部车身色。"""
    frame = np.zeros((200, 100, 3), dtype=np.uint8)
    frame[20:110] = np.array([200, 200, 200], dtype=np.uint8)
    frame[110:190] = np.array([color[2], color[1], color[0]], dtype=np.uint8)
    return frame, (10.0, 20.0, 90.0, 190.0)


def test_resolver_end_to_end_with_stub_plate(tmp_path: Path) -> None:
    """集成：stub 车牌 + 真实外观 → 端到端 BIND，且渐进学习写回 embedding。"""
    from app.models.identity import Vehicle
    from app.repositories.vehicle import VehicleRepository
    from app.services.identity.appearance import extract_vehicle_embedding
    from app.services.identity.protocols import PlateResult
    from app.services.identity.resolver import resolve_identity

    class StubPlateReader:
        def read(
            self,
            frame: NDArray[np.uint8],
            rider_box: tuple[float, float, float, float],
        ) -> PlateResult:
            return PlateResult(text="皖A12345", confidence=0.95, plate_type="blue")

    db_path = tmp_path / "resolver.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session:
            repo = VehicleRepository(session)
            frame, box = _make_frame((220, 30, 30))
            embedding = extract_vehicle_embedding(frame, box)
            repo.create(
                Vehicle(
                    vehicle_id="veh_001",
                    plate_no="皖A12345",
                    plate_type="blue",
                    owner_id="S001",
                    owner_bind_type="registered",
                    confidence=0.9,
                    color_hist=None,
                    embedding=None,
                    first_seen=None,
                    last_seen=None,
                    status="active",
                )
            )
            session.commit()
            assert repo.update_embedding("veh_001", [float(v) for v in embedding]) == 1
            session.commit()

            outcome = resolve_identity(
                "evt_001", frame, box, session, plate_reader=StubPlateReader()
            )
            assert outcome.decision is IdentityDecision.BIND
            assert outcome.subject_id == "S001"
            assert outcome.vehicle_id == "veh_001"
            stored = session.get(Vehicle, "veh_001")
            assert stored is not None and stored.embedding is not None
            session.commit()

            # 无证据路径：默认占位 OCR + 空库 → UNBOUND + NONE。
            empty_path = tmp_path / "resolver-empty.db"
            command.upgrade(_alembic_config(empty_path), "head")
            empty_engine = create_engine(f"sqlite:///{empty_path.as_posix()}", future=True)
            try:
                with Session(empty_engine, future=True) as empty_session:
                    empty_outcome = resolve_identity("evt_002", frame, box, empty_session)
                    assert empty_outcome.decision is IdentityDecision.UNBOUND
            finally:
                empty_engine.dispose()
    finally:
        engine.dispose()


def test_policy_injection_tunes_weights() -> None:
    """策略可注入：调高外观权重后，同一外观证据得分上升。"""
    custom = FusionPolicy(
        weights={
            EvidenceMethod.PLATE: 1.0,
            EvidenceMethod.APPEARANCE: 2.0,
            EvidenceMethod.COOCCUR: 0.5,
            EvidenceMethod.NONE: 0.0,
        }
    )
    default_outcome = fuse_evidence([_ev(EvidenceMethod.APPEARANCE, 0.72)])
    custom_outcome = fuse_evidence([_ev(EvidenceMethod.APPEARANCE, 0.72)], custom)
    assert custom_outcome.confidence > default_outcome.confidence

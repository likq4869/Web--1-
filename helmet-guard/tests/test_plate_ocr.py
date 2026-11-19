"""车牌 OCR 接入测试：领域纯函数 + 约束器 + 服务流水线 + resolver 集成。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from alembic import command
from alembic.config import Config
from numpy.typing import NDArray
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.identity_fusion import IdentityDecision
from app.domain.plate import (
    campus_plate_score,
    guess_plate_type,
    is_valid_plate,
    normalize_plate,
)
from app.models.identity import Vehicle
from app.services.identity.plate_ocr import (
    OCR_BORDER_PX,
    CampusPlateConstrainer,
    HeuristicPlateDetector,
    PlateCandidate,
    PlateOCRService,
    StubPlateRecognizer,
    mask_plate,
    preprocess_plate_crop,
    warp_plate_quad,
)
from app.services.identity.resolver import resolve_identity

PROJECT_DIR = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# 领域层：normalize_plate 脏输入
# --------------------------------------------------------------------------- #


def test_normalize_plate_strips_whitespace_and_uppercases() -> None:
    """去空格 + 大写。"""
    assert normalize_plate("  皖a12345 ") == "皖A12345"
    assert normalize_plate("东门 037") == "东门037"


def test_normalize_plate_converts_fullwidth_to_halfwidth() -> None:
    """全角字母数字转半角。"""
    assert normalize_plate("Ａ１２３４５") == "A12345"
    assert normalize_plate("ａｂ１２") == "AB12"


def test_normalize_plate_handles_empty_and_none_like_inputs() -> None:
    """空串与纯空白归一化为空串（非字符串抛 ValueError）。"""
    assert normalize_plate("") == ""
    assert normalize_plate("   ") == ""
    with pytest.raises(ValueError):
        normalize_plate(None)  # type: ignore[arg-type]


def test_normalize_plate_keeps_chinese() -> None:
    """中文保留（NFKC 不改汉字）。"""
    assert normalize_plate("东门037") == "东门037"
    assert normalize_plate("南门a12") == "南门A12"


# --------------------------------------------------------------------------- #
# 领域层：campus_plate_score
# --------------------------------------------------------------------------- #


def test_campus_plate_score_three_tiers_are_separated() -> None:
    """三档分离：东门037 > A12345 > XYZ。"""
    gate = campus_plate_score("东门037")
    short = campus_plate_score("A12345")
    noise = campus_plate_score("XYZ")
    assert gate > short > noise
    assert gate == pytest.approx(0.75)
    assert short == pytest.approx(0.60)
    assert noise == pytest.approx(0.20)


def test_campus_plate_score_pure_digits_and_province_plate() -> None:
    """纯 5 位数字与省牌均在 [0,1]，且高于噪声。"""
    assert 0.0 <= campus_plate_score("12345") <= 1.0
    assert 0.0 <= campus_plate_score("皖A12345") <= 1.0
    assert campus_plate_score("12345") > campus_plate_score("XYZ")
    assert campus_plate_score("皖A12345") > campus_plate_score("XYZ")


def test_campus_plate_score_empty_is_zero() -> None:
    """空串得 0 分。"""
    assert campus_plate_score("") == 0.0


# --------------------------------------------------------------------------- #
# 领域层：is_valid_plate 边界
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("东门037", True),
        ("南门A12", True),
        ("A12345", True),
        ("12345", True),
        ("皖A12345", True),
        ("XYZ", False),  # 无数字
        ("AB", False),  # 过短
        ("", False),
        ("1234567", False),  # 纯数字过长
        ("东门037!", False),  # 非法字符
    ],
)
def test_is_valid_plate_boundaries(text: str, expected: bool) -> None:
    """合法性边界矩阵。"""
    assert is_valid_plate(text) is expected


def test_is_valid_plate_accepts_dirty_input() -> None:
    """脏输入先归一化再判定。"""
    assert is_valid_plate("  东门 037 ") is True
    assert is_valid_plate("ａ１２３４５") is True


# --------------------------------------------------------------------------- #
# 领域层：guess_plate_type
# --------------------------------------------------------------------------- #


def test_guess_plate_type_variants() -> None:
    """类型猜测：校园门牌/纯数字 → school，省牌 → blue，含"校" → university，非法 → none。"""
    assert guess_plate_type("东门037") == "school"
    assert guess_plate_type("12345") == "school"
    assert guess_plate_type("A12345") == "school"
    assert guess_plate_type("皖A12345") == "blue"
    assert guess_plate_type("某某校车12") == "university"
    assert guess_plate_type("XYZ") == "none"


# --------------------------------------------------------------------------- #
# 服务层：约束器
# --------------------------------------------------------------------------- #


def test_constrainer_prefers_campus_pattern_over_noise() -> None:
    """约束生效：高置信噪声文本被低置信校园号牌反超。"""
    constrainer = CampusPlateConstrainer()
    best = constrainer.constrain(
        [
            PlateCandidate(text="XYZ", confidence=0.95),
            PlateCandidate(text="东门037", confidence=0.70),
        ]
    )
    assert best is not None
    assert best.candidate.text == "东门037"
    assert best.plate_type == "school"


def test_constrainer_filters_invalid_texts() -> None:
    """非法文本直接淘汰。"""
    constrainer = CampusPlateConstrainer()
    assert constrainer.constrain([PlateCandidate(text="XYZ", confidence=0.99)]) is None
    assert constrainer.constrain([PlateCandidate(text="!!", confidence=0.99)]) is None
    assert constrainer.constrain([]) is None


def test_constrainer_keeps_best_by_weighted_score() -> None:
    """同模式下按加权分排序取最优。"""
    constrainer = CampusPlateConstrainer()
    best = constrainer.constrain(
        [
            PlateCandidate(text="东门037", confidence=0.60),
            PlateCandidate(text="东门038", confidence=0.90),
        ]
    )
    assert best is not None
    assert best.candidate.text == "东门038"
    assert best.final_score > 0.5


def test_constrainer_rejects_low_score_candidate() -> None:
    """低于准入线的候选被丢弃（优雅降级为 None）。"""
    constrainer = CampusPlateConstrainer(min_score=0.95)
    assert constrainer.constrain([PlateCandidate(text="东门037", confidence=0.30)]) is None


# --------------------------------------------------------------------------- #
# 服务层：脱敏
# --------------------------------------------------------------------------- #


def test_mask_plate_keeps_head_and_tail() -> None:
    """保留前 2 后 2，中间打码。"""
    masked = mask_plate("皖A12345")
    assert masked.startswith("皖A")
    assert masked.endswith("45")
    assert "123" not in masked
    assert "*" in masked


def test_mask_plate_short_and_none() -> None:
    """短文本全打码；None 返回固定串。"""
    assert mask_plate("A12") == "***"
    assert mask_plate(None) == "****"
    assert mask_plate("") == "****"


# --------------------------------------------------------------------------- #
# 服务层：检测 / 预处理 / 矫正
# --------------------------------------------------------------------------- #


def _frame() -> NDArray[np.uint8]:
    """构造仿真 BGR 帧。"""
    frame = np.zeros((200, 100, 3), dtype=np.uint8)
    frame[:, :] = (120, 90, 60)
    return frame


def test_heuristic_detector_returns_band_inside_rider_box() -> None:
    """启发式裁剪返回骑行者框内部的一个条带。"""
    frame = _frame()
    box = (10.0, 20.0, 90.0, 190.0)
    boxes = HeuristicPlateDetector().detect(frame, box)
    assert len(boxes) == 1
    x1, y1, x2, y2 = boxes[0]
    assert box[0] <= x1 < x2 <= box[2]
    assert box[1] <= y1 < y2 <= box[3]


def test_heuristic_detector_invalid_input_returns_empty() -> None:
    """非法输入返回空列表，不抛异常。"""
    detector = HeuristicPlateDetector()
    assert detector.detect(_frame(), (50.0, 50.0, 50.0, 50.0)) == []
    assert detector.detect(_frame(), (90.0, 20.0, 10.0, 190.0)) == []
    assert detector.detect(np.zeros((10, 10), dtype=np.uint8), (0.0, 0.0, 5.0, 5.0)) == []


def test_preprocess_plate_crop_outputs_three_channels() -> None:
    """预处理输出保持 3 通道，并因留白边距而放大尺寸。"""
    crop = _frame()
    out = preprocess_plate_crop(crop)
    assert out.ndim == 3 and out.shape[2] == 3
    assert out.dtype == np.uint8
    # 四周留白使尺寸增加 OCR_BORDER_PX×2
    assert out.shape[0] == crop.shape[0] + 2 * OCR_BORDER_PX
    assert out.shape[1] == crop.shape[1] + 2 * OCR_BORDER_PX


def test_preprocess_plate_crop_rejects_invalid() -> None:
    """非法裁剪抛 ValueError。"""
    with pytest.raises(ValueError):
        preprocess_plate_crop(np.zeros((0, 10, 3), dtype=np.uint8))
    with pytest.raises(ValueError):
        preprocess_plate_crop(np.zeros((10, 10), dtype=np.uint8))  # type: ignore[arg-type]


def test_warp_plate_quad_produces_fixed_size() -> None:
    """透视矫正输出固定尺寸。"""
    out = warp_plate_quad(
        _frame(),
        ((10.0, 60.0), (90.0, 65.0), (90.0, 95.0), (10.0, 90.0)),
        out_width=160,
        out_height=48,
    )
    assert out.shape == (48, 160, 3)


# --------------------------------------------------------------------------- #
# 服务层：PlateOCRService 流水线
# --------------------------------------------------------------------------- #


class _FixedRecognizer:
    """返回固定候选的识别器（模拟 OCR）。"""

    def __init__(self, texts: list[tuple[str, float]]) -> None:
        self._texts = texts

    def recognize(self, crop: NDArray[np.uint8]) -> list[PlateCandidate]:
        """返回预设候选。"""
        _ = crop
        return [PlateCandidate(text=t, confidence=c) for t, c in self._texts]


class _RaisingDetector:
    """检测器抛异常（验证优雅降级）。"""

    def detect(
        self,
        frame: NDArray[np.uint8],
        rider_box: tuple[float, float, float, float],
    ) -> list[tuple[float, float, float, float]]:
        """总是抛异常。"""
        _ = (frame, rider_box)
        raise RuntimeError("detect failed")


def test_plate_ocr_service_returns_constrained_best() -> None:
    """约束后处理生效：返回最优校园号牌候选。"""
    service = PlateOCRService(
        recognizer=_FixedRecognizer([("XYZ", 0.95), ("东门037", 0.72)])
    )
    result = service.read(_frame(), (10.0, 20.0, 90.0, 190.0))
    assert result.text == "东门037"
    assert result.plate_type == "school"
    assert 0.0 <= result.confidence <= 1.0


def test_plate_ocr_service_graceful_degrade_on_detector_error() -> None:
    """检测异常 → 返回未识别，不抛异常。"""
    service = PlateOCRService(detector=_RaisingDetector())
    result = service.read(_frame(), (10.0, 20.0, 90.0, 190.0))
    assert result.text is None
    assert result.confidence == 0.0


def test_plate_ocr_service_default_recognizer_returns_empty() -> None:
    """默认空识别器 → 未识别（等价占位语义）。"""
    service = PlateOCRService()
    result = service.read(_frame(), (10.0, 20.0, 90.0, 190.0))
    assert result.text is None
    assert StubPlateRecognizer().recognize(_frame()) == []


def test_plate_ocr_service_invalid_frame_degrades() -> None:
    """非法帧 → 未识别，不抛异常。"""
    service = PlateOCRService(recognizer=_FixedRecognizer([("东门037", 0.9)]))
    result = service.read(np.zeros((10, 10), dtype=np.uint8), (0.0, 0.0, 5.0, 5.0))
    assert result.text is None


# --------------------------------------------------------------------------- #
# 集成：resolver 产出 plate 证据
# --------------------------------------------------------------------------- #


def _alembic_config(db_path: Path) -> Config:
    """构造指向临时库的 Alembic 配置。"""
    config = Config(str(PROJECT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return config


def test_resolver_produces_plate_evidence_and_masks_log(tmp_path: Path) -> None:
    """集成：PlateReader 返回结果 → plate 证据产出 + 命中登记车辆 + 日志脱敏。"""
    from app.services.identity.protocols import PlateResult

    class StubPlateReader:
        def read(
            self,
            frame: NDArray[np.uint8],
            rider_box: tuple[float, float, float, float],
        ) -> PlateResult:
            return PlateResult(text="皖A12345", confidence=0.95, plate_type="blue")

    db_path = tmp_path / "plate-resolver.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session:
            session.add(
                Vehicle(
                    vehicle_id="veh_plate_001",
                    plate_no="皖A12345",
                    plate_type="blue",
                    owner_id="2022110508",
                )
            )
            session.commit()

            outcome = resolve_identity(
                "evt_plate_001",
                _frame(),
                (10.0, 20.0, 90.0, 190.0),
                session,
                plate_reader=StubPlateReader(),
            )
            assert outcome.decision is IdentityDecision.BIND
            assert outcome.subject_id == "2022110508"
            assert outcome.vehicle_id == "veh_plate_001"

            plate_evidence = next(
                item for item in outcome.evidence if item.method.value == "plate"
            )
            # 日志脱敏：不出现完整车牌明文。
            assert "皖A12345" not in plate_evidence.detail
            assert "皖A" in plate_evidence.detail
            assert "45" in plate_evidence.detail
    finally:
        engine.dispose()


def test_resolver_normalizes_dirty_plate_before_lookup(tmp_path: Path) -> None:
    """集成：脏文本（空格/小写/全角）归一化后仍能命中登记车辆。"""
    from app.services.identity.protocols import PlateResult

    class DirtyPlateReader:
        def read(
            self,
            frame: NDArray[np.uint8],
            rider_box: tuple[float, float, float, float],
        ) -> PlateResult:
            return PlateResult(text="  皖a 12345 ", confidence=0.92, plate_type="blue")

    db_path = tmp_path / "plate-dirty.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session:
            session.add(
                Vehicle(
                    vehicle_id="veh_plate_002",
                    plate_no="皖A12345",
                    plate_type="blue",
                    owner_id="2022110509",
                )
            )
            session.commit()

            outcome = resolve_identity(
                "evt_plate_002",
                _frame(),
                (10.0, 20.0, 90.0, 190.0),
                session,
                plate_reader=DirtyPlateReader(),
            )
            assert outcome.vehicle_id == "veh_plate_002"
            assert outcome.subject_id == "2022110509"
    finally:
        engine.dispose()


def test_resolver_invalid_plate_text_produces_no_match(tmp_path: Path) -> None:
    """集成：非法车牌文本不命中任何车辆（证据仍产出但不绑定）。"""
    from app.services.identity.protocols import PlateResult

    class InvalidPlateReader:
        def read(
            self,
            frame: NDArray[np.uint8],
            rider_box: tuple[float, float, float, float],
        ) -> PlateResult:
            return PlateResult(text="XYZ", confidence=0.9, plate_type="none")

    db_path = tmp_path / "plate-invalid.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session:
            session.add(
                Vehicle(
                    vehicle_id="veh_plate_003",
                    plate_no="皖A12345",
                    plate_type="blue",
                    owner_id="2022110510",
                )
            )
            session.commit()

            outcome = resolve_identity(
                "evt_plate_003",
                _frame(),
                (10.0, 20.0, 90.0, 190.0),
                session,
                plate_reader=InvalidPlateReader(),
            )
            assert outcome.vehicle_id is None
            assert outcome.subject_id is None
    finally:
        engine.dispose()

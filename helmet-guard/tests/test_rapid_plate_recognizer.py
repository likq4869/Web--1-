"""真实车牌识别器测试：RapidOCR 适配层 + 端到端流水线（含模型推理）。

说明：真实推理测试依赖 rapidocr-onnxruntime（可选依赖 ocr 组）。
未安装时整组自动跳过，不影响主链路测试。
"""

from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from app.services.identity.plate_ocr import PlateOCRService

rapidocr = pytest.importorskip("rapidocr_onnxruntime", reason="未安装 OCR 可选依赖")

from app.services.identity.rapid_plate_recognizer import (  # noqa: E402
    MIN_OCR_HEIGHT,
    RapidPlateRecognizer,
    _upscale_for_ocr,
    build_default_recognizer,
)


def _synthetic_plate(text: str, width: int = 240, height: int = 100) -> NDArray[np.uint8]:
    """生成白底黑字的仿真车牌图（文字居中，四周留白）。"""
    import cv2

    img = np.full((height, width, 3), 255, dtype=np.uint8)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.6, 3)
    org = ((width - tw) // 2, (height + th) // 2)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 3)
    return img


def _frame_with_plate(plate: NDArray[np.uint8]) -> tuple[NDArray[np.uint8], tuple[float, ...]]:
    """把车牌放进仿真帧的骑行者框条带区，返回帧与框。"""
    height, width = 400, 400
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    box = (50.0, 40.0, 350.0, 360.0)
    # 复刻 HeuristicPlateDetector 的条带：垂直 45%~70%、水平 20%~80%
    y1 = int(box[1] + (box[3] - box[1]) * 0.45)
    y2 = int(box[1] + (box[3] - box[1]) * 0.70)
    x1 = int(box[0] + (box[2] - box[0]) * 0.20)
    x2 = int(box[0] + (box[2] - box[0]) * 0.80)
    ph, pw = min(plate.shape[0], y2 - y1), min(plate.shape[1], x2 - x1)
    frame[y1 : y1 + ph, x1 : x1 + pw] = plate[:ph, :pw]
    return frame, box


def test_upscale_enlarges_small_crop() -> None:
    """小图被放大到最小 OCR 高度。"""
    small = np.zeros((30, 80, 3), dtype=np.uint8)
    out = _upscale_for_ocr(small)
    assert out.shape[0] >= MIN_OCR_HEIGHT
    assert out.dtype == np.uint8


def test_upscale_keeps_large_crop_unchanged() -> None:
    """已足够大的图不再放大（避免无谓开销）。"""
    large = np.zeros((200, 300, 3), dtype=np.uint8)
    out = _upscale_for_ocr(large)
    assert out.shape == large.shape


def test_build_default_recognizer_returns_instance() -> None:
    """依赖已安装时构造出真实识别器。"""
    recognizer = build_default_recognizer()
    assert isinstance(recognizer, RapidPlateRecognizer)


def test_rapid_recognizer_reads_synthetic_plate() -> None:
    """真实推理：仿真车牌 'A12345' → 识别为含数字的合法车牌文本。"""
    recognizer = RapidPlateRecognizer()
    candidates = recognizer.recognize(_synthetic_plate("A12345"))
    assert candidates, "真实 OCR 应至少返回一个候选"
    best = candidates[0]
    assert best.confidence > 0.5
    # 允许个别字符识别偏差，但主体数字串应被识别出来
    assert any(ch.isdigit() for ch in best.text)
    assert len(best.text) >= 4


def test_rapid_recognizer_returns_empty_for_blank_image() -> None:
    """纯空白图识别不到内容 → 空候选（不抛异常）。"""
    recognizer = RapidPlateRecognizer()
    blank = np.full((120, 240, 3), 255, dtype=np.uint8)
    assert recognizer.recognize(blank) == []


def test_plate_ocr_service_end_to_end_with_real_engine() -> None:
    """端到端：帧 → 检测 → 矫正 → 真实识别 → 约束 → PlateResult。"""
    frame, box = _frame_with_plate(_synthetic_plate("A12345"))
    service = PlateOCRService()
    result = service.read(frame, box)
    assert result.text is not None, "端到端应识别出车牌文本"
    assert result.text.startswith("A") or result.text[0].isalpha()
    assert result.confidence > 0.5
    assert result.plate_type == "school"
    assert result.bbox is not None


def test_plate_ocr_service_graceful_on_blank_frame() -> None:
    """空白帧 → 未识别，不抛异常（优雅降级）。"""
    frame = np.zeros((300, 300, 3), dtype=np.uint8)
    service = PlateOCRService()
    result = service.read(frame, (50.0, 40.0, 250.0, 280.0))
    assert result.text is None
    assert result.confidence == 0.0

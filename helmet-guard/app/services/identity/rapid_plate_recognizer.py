"""车牌 OCR 识别器实现：RapidOCR（PP-OCRv3 ONNX 版）适配 PlateRecognizer 协议。

职责：把车牌裁剪图交给真实 OCR 引擎，输出 PlateCandidate 列表。
依赖：rapidocr_onnxruntime（ONNX Runtime，无需 paddlepaddle/torch）。
边界：模型初始化失败或推理异常时抛 RuntimeError，由调用方 PlateOCRService
统一捕获并降级为"未识别"，绝不中断采集。

选型说明（2026-11-16 实测）：
- 直接装 paddleocr 会连带 paddlepaddle（数百 MB，且 Python 3.14 尚无官方轮子），
  在本机不可行；
- rapidocr-onnxruntime 内置 PP-OCRv3 的 det/rec/cls 三套 ONNX 权重
  （随包分发，无需联网下载），单次识别延迟约 0.1~0.5s（CPU），
  是 PaddleOCR 同源模型的轻量可落地形态；
- 对接 PaddleOCR PP-OCRv4 时只需替换本类，协议不变、resolver 零改动。
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from app.services.identity.plate_ocr import PlateCandidate

# OCR 文本分数下限：低于该值的识别结果直接丢弃，避免噪声文本进入候选池。
# 依据：车牌字符序列需完整可读，0.5 是通用 OCR 的安全下限；
# 最终是否采用仍由 CampusPlateConstrainer 的加权分决定。
MIN_TEXT_SCORE = 0.5
# 送入 OCR 前的最小高度：车牌裁剪常仅 30~60px 高，RapidOCR 的 DBNet 检测
# 在过小图上会把字符切碎（实测 'A12345' 被切成 'A1'/'23'/'45' 三段）。
# 统一放大到该高度后再识别，可显著提升召回。
MIN_OCR_HEIGHT = 96
# 放大后的最大宽度：避免极端长条图拖慢推理。
MAX_OCR_WIDTH = 640


class RapidPlateRecognizer:
    """RapidOCR 识别器（实现 PlateRecognizer 协议）。

    单例语义：ONNX 会话与模型加载开销大，实例内部懒加载并复用；
    ONNX Runtime 推理本身是线程安全的，故同一实例可被多线程共享。

    Attributes:
        _engine: RapidOCR 引擎实例；懒加载。
        _min_score: 文本分数下限。
    """

    def __init__(self, *, min_score: float = MIN_TEXT_SCORE) -> None:
        """初始化识别器（不立即加载模型，首次识别时懒加载）。

        Args:
            min_score: 文本分数下限。
        """
        self._engine: Any | None = None
        self._min_score = min_score

    def _ensure_engine(self) -> Any:
        """懒加载并返回 OCR 引擎。

        Returns:
            RapidOCR 实例。

        Raises:
            RuntimeError: 依赖缺失或初始化失败。
        """
        if self._engine is not None:
            return self._engine
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:  # pragma: no cover - 依赖缺失路径
            raise RuntimeError(
                "rapidocr-onnxruntime 未安装，无法启用真实车牌识别"
            ) from exc
        try:
            self._engine = RapidOCR()
        except Exception as exc:  # pragma: no cover - 模型初始化失败路径
            raise RuntimeError(f"RapidOCR 初始化失败：{exc}") from exc
        return self._engine

    def recognize(self, crop: NDArray[np.uint8]) -> list[PlateCandidate]:
        """识别车牌裁剪图中的字符。

        识别前统一放大到最小高度（见 MIN_OCR_HEIGHT 注释）：车牌裁剪往往
        只有几十像素高，RapidOCR 的检测模型在小图上会把字符切碎，放大后
        才能完整识别出整串车牌。

        Args:
            crop: BGR 车牌裁剪图。

        Returns:
            候选列表；识别不到内容时返回空列表。

        Raises:
            RuntimeError: 引擎不可用或推理失败。
        """
        engine = self._ensure_engine()
        prepared = _upscale_for_ocr(crop)
        try:
            raw_result, _elapse = engine(prepared)
        except Exception as exc:
            raise RuntimeError(f"RapidOCR 推理失败：{exc}") from exc
        if not raw_result:
            return []
        candidates: list[PlateCandidate] = []
        for item in raw_result:
            # RapidOCR 返回 [box, text, score]；文本与分数在索引 1、2。
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            text = str(item[1]).strip()
            score = float(item[2])
            if not text or score < self._min_score:
                continue
            candidates.append(PlateCandidate(text=text, confidence=score))
        return candidates


def _upscale_for_ocr(crop: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """把车牌裁剪图放大到 OCR 友好尺寸。

    Args:
        crop: BGR 裁剪图。

    Returns:
        放大后的 BGR 图；输入非法时原样返回。
    """
    if not isinstance(crop, np.ndarray) or crop.ndim != 3 or crop.shape[0] == 0:
        return crop
    height, width = crop.shape[:2]
    scale = MIN_OCR_HEIGHT / float(height)
    if scale <= 1.0:
        return crop
    new_width = min(int(round(width * scale)), MAX_OCR_WIDTH)
    new_height = max(height, MIN_OCR_HEIGHT)
    if new_width < 1 or new_height < 1:
        return crop
    return np.asarray(
        cv2.resize(crop, (new_width, new_height), interpolation=cv2.INTER_CUBIC),
        dtype=np.uint8,
    )


def build_default_recognizer() -> RapidPlateRecognizer | None:
    """构造默认识别器；依赖缺失时返回 None（调用方走降级）。

    Returns:
        RapidPlateRecognizer 实例；不可用时为 None。
    """
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:  # pragma: no cover - 依赖缺失路径
        return None
    return RapidPlateRecognizer()

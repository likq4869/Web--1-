"""身份服务 OCR 解耦协议：车牌读取接口与默认实现。

职责：定义车牌 OCR 的 Protocol 接口，P1-4 接入真实 OCR 前由默认实现占位。
依赖：numpy（帧类型）、app.domain.identity_fusion（方法枚举复用）。
边界：只定义接口与占位实现；不做真实识别、不访问网络。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class PlateResult:
    """车牌读取结果。

    Attributes:
        text: 识别到的车牌文本；未识别时为 None。
        confidence: 本次识别置信度。
        plate_type: 车牌类型（blue/school/university/none），未识别时为 None。
        bbox: 车牌框 (x1, y1, x2, y2)，帧坐标系；未识别时为 None。
    """

    text: str | None
    confidence: float
    plate_type: str | None = None
    bbox: tuple[float, float, float, float] | None = None


class PlateReader(Protocol):
    """车牌读取器协议：输入帧与骑行者框，输出识别结果。

    P1-4 将提供 PaddleOCR/CRNN 真实实现；当前服务层只依赖本协议，
    测试可用 stub 注入任意结果。
    """

    def read(
        self,
        frame: NDArray[np.uint8],
        rider_box: tuple[float, float, float, float],
    ) -> PlateResult:
        """读取帧中指定框内的车牌。

        Args:
            frame: BGR uint8 帧图。
            rider_box: (x1, y1, x2, y2) 骑行者框。

        Returns:
            车牌读取结果。
        """
        ...  # pragma: no cover - 协议方法无实现


class DefaultPlateReader:
    """默认占位实现：恒返回未识别（P1-4 替换为真实 OCR）。

    语义：车牌证据缺席时融合层按"无该证据"处理，不产生虚假支持。
    """

    def read(
        self,
        _frame: NDArray[np.uint8],
        _rider_box: tuple[float, float, float, float],
    ) -> PlateResult:
        """恒返回未识别结果。"""
        return PlateResult(text=None, confidence=0.0, plate_type=None)

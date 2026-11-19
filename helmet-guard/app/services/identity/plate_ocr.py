"""车牌 OCR 服务：检测 → 矫正 → 识别 → 约束后处理（可插拔 + 优雅降级）。

职责：把 BGR 帧 + 骑行者框映射为车牌读取结果，供 resolver 的 plate 证据路径使用。
依赖：cv2、numpy、app.domain.plate（纯函数）、app.services.identity.protocols（接口）。
边界：识别失败恒返回"未识别"，绝不抛异常中断采集；原始 OCR 文本仅作候选，
最终文本必须经过约束后处理（合法性 + 校园模式打分）。

依赖可行性结论（2026-11-16 实测）：
当前 venv 仅有 torch/ultralytics/cv2/numpy/PIL，无 paddleocr/rapidocr/
easyocr/onnxruntime。PaddleOCR PP-OCRv4 体积大（~100MB+ 模型）且需额外
下载字库，在本机离线环境安装困难，故本模块采用"协议解耦 + 启发式降级"
路线：detector/recognizer 均为 Protocol，默认实现为启发式裁剪 + 空识别
（恒返回未识别，语义等同 DefaultPlateReader），生产替换为 PaddleOCR 实现
即可，resolver 侧零改动。差异说明见模块末尾注释。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np
from numpy.typing import NDArray

from app.domain.plate import (
    campus_plate_score,
    guess_plate_type,
    is_valid_plate,
)
from app.domain.plate import normalize_plate as normalize_plate_text
from app.services.identity.protocols import PlateResult

# 约束融合权重：最终排序分 = OCR 置信度 * OCR_WEIGHT + 校园模式分 * CAMPUS_WEIGHT。
# 取值依据：OCR 置信度是主信号（0.7），校园模式是先验加分（0.3）；
# 纯噪声文本（如 "XYZ"）即使 OCR 自信 0.9，加权后 0.69 仍低于真实号牌
# （如"东门037" OCR 0.8 → 0.8*0.7+0.75*0.3=0.785），保证约束生效。
OCR_WEIGHT = 0.7
CAMPUS_WEIGHT = 0.3
# 候选准入线：加权分低于该值直接丢弃，不进入证据路径。
CANDIDATE_MIN_SCORE = 0.45
# OCR 输入留白边距（像素）：文本检测模型会裁掉紧贴图像边缘的字符，
# 补白边后可完整识别整串车牌（实测 'A12345' 在无留白时被切成三段）。
OCR_BORDER_PX = 12


@dataclass(frozen=True)
class PlateCandidate:
    """单个 OCR 候选。

    Attributes:
        text: 归一化后的候选文本。
        confidence: OCR 原始置信度。
        bbox: 车牌框 (x1, y1, x2, y2)，帧坐标系。
    """

    text: str
    confidence: float
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class ScoredCandidate:
    """约束打分后的候选。

    Attributes:
        candidate: 原始候选。
        campus_score: 校园模式分。
        final_score: 加权最终分。
        plate_type: 猜测的车牌类型。
    """

    candidate: PlateCandidate
    campus_score: float
    final_score: float
    plate_type: str


def normalize_plate(text: str) -> str:
    """统一化车牌文本（服务层透传领域函数，保持单实现源）。

    Args:
        text: 原始 OCR 文本。

    Returns:
        归一化文本。
    """
    return normalize_plate_text(text)


def mask_plate(text: str | None) -> str:
    """车牌脱敏：保留前 2 后 2，中间打码；过短文本全打码。

    日志与 UI 展示必须用脱敏串，原始文本只存证据 detail 的受控字段。

    Args:
        text: 车牌文本；None 返回 "****"。

    Returns:
        脱敏字符串。
    """
    if not text:
        return "****"
    normalized = normalize_plate_text(text)
    if len(normalized) <= 4:
        return "*" * len(normalized) if normalized else "****"
    return f"{normalized[:2]}{'*' * (len(normalized) - 4)}{normalized[-2:]}"


class CampusPlateConstrainer:
    """校园号牌约束器：对 OCR 候选做合法性过滤 + 模式加分 + 排序。

    约束规则表（见 app.domain.plate._CAMPUS_PATTERNS）：
    gate_full（东门037类）+0.35 / gate_alpha（南门A12类）+0.35 /
    campus_word（含"校"）+0.30 / pure_digits（纯4-6位数字）+0.25 /
    short_code（A12345类）+0.20 / province_ebike（皖A12345类）+0.20 /
    province_standard（标准蓝牌）+0.20；基分 0.40，无数字 −0.20。
    """

    def __init__(
        self,
        *,
        ocr_weight: float = OCR_WEIGHT,
        campus_weight: float = CAMPUS_WEIGHT,
        min_score: float = CANDIDATE_MIN_SCORE,
    ) -> None:
        """初始化约束权重。

        Args:
            ocr_weight: OCR 置信度权重。
            campus_weight: 校园模式分权重。
            min_score: 候选准入线。
        """
        self._ocr_weight = ocr_weight
        self._campus_weight = campus_weight
        self._min_score = min_score

    def score(self, candidate: PlateCandidate) -> ScoredCandidate:
        """给单个候选打分。

        Args:
            candidate: OCR 候选。

        Returns:
            打分后候选。
        """
        campus = campus_plate_score(candidate.text)
        final = candidate.confidence * self._ocr_weight + campus * self._campus_weight
        return ScoredCandidate(
            candidate=candidate,
            campus_score=campus,
            final_score=final,
            plate_type=guess_plate_type(candidate.text),
        )

    def constrain(self, candidates: list[PlateCandidate]) -> ScoredCandidate | None:
        """约束后处理：过滤非法 → 打分排序 → 返回最优。

        非法文本（is_valid_plate=False）直接淘汰；剩余按 final_score 降序，
        低于准入线返回 None（识别失败，优雅降级）。

        Args:
            candidates: OCR 候选列表。

        Returns:
            最优打分候选；无可用候选时返回 None。
        """
        scored = [
            self.score(item) for item in candidates if is_valid_plate(item.text)
        ]
        if not scored:
            return None
        scored.sort(key=lambda item: item.final_score, reverse=True)
        best = scored[0]
        if best.final_score < self._min_score:
            return None
        return best


class PlateDetector(Protocol):
    """车牌区域检测器协议：输入帧与骑行者框，输出车牌框列表。

    生产实现为 YOLO 新增 `plate` 类（见说明书 §4.3.1）；当前默认实现为
    启发式裁剪（见 HeuristicPlateDetector）。
    """

    def detect(
        self,
        frame: NDArray[np.uint8],
        rider_box: tuple[float, float, float, float],
    ) -> list[tuple[float, float, float, float]]:
        """检测车牌区域。

        Args:
            frame: BGR 帧图。
            rider_box: 骑行者框。

        Returns:
            车牌框列表（帧坐标系，可为空）。
        """
        ...  # pragma: no cover - 协议方法无实现


class PlateRecognizer(Protocol):
    """车牌字符识别器协议：输入车牌裁剪图，输出候选列表。

    生产实现为 PaddleOCR PP-OCRv4（检测 DBNet + 识别 CRNN + 字符字典约束，
    见说明书 §4.3.1）；当前默认实现为空识别（见 StubPlateRecognizer）。
    """

    def recognize(self, crop: NDArray[np.uint8]) -> list[PlateCandidate]:
        """识别车牌裁剪图中的字符。

        Args:
            crop: BGR 车牌裁剪图。

        Returns:
            候选列表（可为空）。
        """
        ...  # pragma: no cover - 协议方法无实现


class HeuristicPlateDetector:
    """启发式车牌区域检测：基于 Cyclists 框的中央条带裁剪。

    原理：电动车牌多挂于车尾中部，在骑行者框内约位于垂直中部、
    水平居中的窄条带。本实现取框内垂直 45%~70%、水平 20%~80% 作为
    疑似车牌区，仅为无模型时的占位；YOLO `plate` 类接入后替换本类即可
    （预留点：YoloPlateDetector，接口同 PlateDetector）。
    """

    def detect(
        self,
        frame: NDArray[np.uint8],
        rider_box: tuple[float, float, float, float],
    ) -> list[tuple[float, float, float, float]]:
        """按启发式条带返回单个候选框；输入非法返回空列表。"""
        if not isinstance(frame, np.ndarray) or frame.ndim != 3:
            return []
        try:
            x1, y1, x2, y2 = (float(v) for v in rider_box)
        except (TypeError, ValueError):
            return []
        if x2 <= x1 or y2 <= y1:
            return []
        h, w = frame.shape[:2]
        px1 = max(0.0, x1 + (x2 - x1) * 0.20)
        px2 = min(float(w), x1 + (x2 - x1) * 0.80)
        py1 = max(0.0, y1 + (y2 - y1) * 0.45)
        py2 = min(float(h), y1 + (y2 - y1) * 0.70)
        if px2 <= px1 or py2 <= py1:
            return []
        return [(px1, py1, px2, py2)]


class StubPlateRecognizer:
    """空识别器：恒返回空候选（等价"未识别"，触发优雅降级）。"""

    def recognize(self, crop: NDArray[np.uint8]) -> list[PlateCandidate]:
        """恒返回空列表。"""
        _ = crop
        return []


def _default_recognizer() -> PlateRecognizer:
    """构造默认识别器：优先 RapidOCR，依赖缺失则降级为空识别器。

    降级原因：OCR 依赖属可选增强，缺失时须保证采集主链路不中断。
    延迟导入避免模块加载期强依赖。

    Returns:
        可用的识别器实例。
    """
    try:
        from app.services.identity.rapid_plate_recognizer import (
            build_default_recognizer,
        )
    except ImportError:  # pragma: no cover - 依赖缺失路径
        return StubPlateRecognizer()
    recognizer = build_default_recognizer()
    return recognizer if recognizer is not None else StubPlateRecognizer()


def preprocess_plate_crop(crop: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """车牌裁剪预处理：灰度 + CLAHE 增强 + 留白边距 + 尺寸归一。

    留白是必要环节：OCR 的文本检测模型会把贴近图像边缘的字符裁掉
    （实测紧贴边缘的 'A12345' 被切成 'A1'/'23'/'45'），四周补白边后
    才能完整识别出整串车牌。

    Args:
        crop: BGR 车牌裁剪图。

    Returns:
        预处理后的 BGR 图（保持 3 通道，兼容 OCR 输入）。

    Raises:
        ValueError: 输入非法或为空。
    """
    if not isinstance(crop, np.ndarray) or crop.ndim != 3 or crop.shape[2] != 3:
        raise ValueError("crop 必须为形状 (H, W, 3) 的数组")
    if crop.shape[0] == 0 or crop.shape[1] == 0:
        raise ValueError("crop 为空图")
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    bordered = cv2.copyMakeBorder(
        enhanced,
        OCR_BORDER_PX,
        OCR_BORDER_PX,
        OCR_BORDER_PX,
        OCR_BORDER_PX,
        cv2.BORDER_CONSTANT,
        value=255,
    )
    return np.asarray(cv2.cvtColor(bordered, cv2.COLOR_GRAY2BGR), dtype=np.uint8)


def warp_plate_quad(
    frame: NDArray[np.uint8],
    quad: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ],
    *,
    out_width: int = 160,
    out_height: int = 48,
) -> NDArray[np.uint8]:
    """四点透视矫正：把倾斜车牌拉正为标准矩形。

    Args:
        frame: BGR 帧图。
        quad: 四角点（左上/右上/右下/左下），帧坐标系。
        out_width: 输出宽。
        out_height: 输出高。

    Returns:
        矫正后的 BGR 图。

    Raises:
        ValueError: 输入非法。
    """
    if not isinstance(frame, np.ndarray) or frame.ndim != 3:
        raise ValueError("frame 必须为形状 (H, W, 3) 的数组")
    src = np.array(quad, dtype=np.float32)
    dst = np.array(
        [[0, 0], [out_width - 1, 0], [out_width - 1, out_height - 1], [0, out_height - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(frame, matrix, (out_width, out_height))
    return np.asarray(warped, dtype=np.uint8)


class PlateOCRService:
    """车牌 OCR 服务（实现 PlateReader 协议）：检测 → 矫正 → 识别 → 约束。

    流水线：HeuristicPlateDetector 框选 → 矩形裁剪（四点框走透视矫正，
    当前启发式为轴对齐框，直接裁剪）→ 预处理增强 → recognizer 识别 →
    CampusPlateConstrainer 约束 → PlateResult。任一步失败返回"未识别"，
    绝不抛异常。

    默认识别器为 RapidOCR（PP-OCRv3 ONNX 版，真实可用）；若该依赖缺失，
    自动降级为 StubPlateRecognizer（恒未识别），功能不中断。
    """

    def __init__(
        self,
        *,
        detector: PlateDetector | None = None,
        recognizer: PlateRecognizer | None = None,
        constrainer: CampusPlateConstrainer | None = None,
    ) -> None:
        """初始化服务（依赖均可注入，默认启发式检测 + RapidOCR 识别）。

        Args:
            detector: 车牌区域检测器。
            recognizer: 字符识别器；None 时优先用 RapidOCR，缺失则降级为空识别。
            constrainer: 约束后处理器。
        """
        self._detector: PlateDetector = (
            detector if detector is not None else HeuristicPlateDetector()
        )
        if recognizer is not None:
            self._recognizer: PlateRecognizer = recognizer
        else:
            self._recognizer = _default_recognizer()
        self._constrainer = constrainer if constrainer is not None else CampusPlateConstrainer()

    def read(
        self,
        frame: NDArray[np.uint8],
        rider_box: tuple[float, float, float, float],
    ) -> PlateResult:
        """读取车牌；失败返回未识别（不抛异常）。

        Args:
            frame: BGR 帧图。
            rider_box: 骑行者框。

        Returns:
            车牌读取结果（含 bbox，未识别时 text/bbox 为 None）。
        """
        try:
            boxes = self._detector.detect(frame, rider_box)
        except Exception:
            return PlateResult(text=None, confidence=0.0, plate_type=None)
        candidates: list[PlateCandidate] = []
        for box in boxes:
            try:
                x1, y1, x2, y2 = (float(v) for v in box)
                h, w = frame.shape[:2]
                ix1, iy1 = max(0, int(round(x1))), max(0, int(round(y1)))
                ix2, iy2 = min(w, int(round(x2))), min(h, int(round(y2)))
                if ix2 <= ix1 or iy2 <= iy1:
                    continue
                crop = preprocess_plate_crop(frame[iy1:iy2, ix1:ix2])
                for raw in self._recognizer.recognize(crop) or []:
                    text = normalize_plate_text(raw.text)
                    if not text:
                        continue
                    candidates.append(
                        PlateCandidate(
                            text=text,
                            confidence=min(max(raw.confidence, 0.0), 1.0),
                            bbox=(float(ix1), float(iy1), float(ix2), float(iy2)),
                        )
                    )
            except Exception:
                continue
        try:
            best = self._constrainer.constrain(candidates)
        except Exception:
            return PlateResult(text=None, confidence=0.0, plate_type=None)
        if best is None:
            return PlateResult(text=None, confidence=0.0, plate_type=None)
        return PlateResult(
            text=best.candidate.text,
            confidence=best.candidate.confidence,
            plate_type=best.plate_type,
            bbox=best.candidate.bbox,
        )


# 生产级 PaddleOCR 方案差异说明（切换时替换 detector/recognizer 即可）：
# 1. 检测：YOLO 新增 `plate` 类（需校内自采车牌数据训练），替代启发式条带；
# 2. 识别：PaddleOCR PP-OCRv4（DBNet 检测 + CRNN 识别 + 省份/字母数字字典约束），
#    替代 StubPlateRecognizer；置信度取字符均值 × 框置信度；
# 3. 后处理：本模块的归一化/合法性/校园约束/脱敏保持不变，原始 OCR 文本仍仅作参考；
# 4. 部署：OCR 放 GPU worker（推理服务），本 read() 改为异步调用或队列，
#    当前同步实现仅用于边缘盒低频触发。

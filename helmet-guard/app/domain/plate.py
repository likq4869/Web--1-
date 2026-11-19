"""车牌领域层纯函数：归一化、合法性、类型猜测、校园模式打分。

职责：提供无 I/O 的纯函数，供 OCR 服务后处理与解析编排复用。
依赖：仅标准库（re、unicodedata）；不得 import cv2/numpy。
边界：不读图、不碰库；输入输出均为普通字符串与浮点数。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

# 车牌类型：与 vehicles 表枚举一致（小写），任务书大写名映射如下：
# BLUE→blue（地方电动车牌）、SCHOOL→school（校园自编号牌）、
# UNIVERSITY→university（校内公务牌）、NONE→none（未知/非法）。
PlateType = Literal["blue", "school", "university", "none"]

# 允许字符：CJK 统一汉字 + 大写字母数字（归一化后统一为该集合）。
_ALLOWED_RE = re.compile(r"^[\u4e00-\u9fa5A-Z0-9]+$")
_HAS_DIGIT_RE = re.compile(r"\d")

# 校园模式正则集合（按说明书 §4.3.1，分类型处理）：
# gate_full 东门037 / gate_alpha 南门A12 / pure_digits 纯5位数字 /
# campus_word 含"校" / short_code A12345 / province_ebike 皖A12345类。
_CAMPUS_PATTERNS: tuple[tuple[str, re.Pattern[str], float], ...] = (
    ("gate_full", re.compile(r"^[东南西北]门\d{2,3}$"), 0.35),
    ("gate_alpha", re.compile(r"^[东南西北]门[A-Z]\d{1,3}$"), 0.35),
    ("campus_word", re.compile(r".*校.*"), 0.30),
    ("pure_digits", re.compile(r"^\d{4,6}$"), 0.25),
    ("short_code", re.compile(r"^[A-Z]\d{4,5}$"), 0.20),
    ("province_ebike", re.compile(r"^[\u4e00-\u9fa5][A-Z]\d{4,5}$"), 0.20),
    ("province_standard", re.compile(r"^[\u4e00-\u9fa5][A-Z][A-Z0-9]{5}$"), 0.20),
)


def normalize_plate(text: str) -> str:
    """统一化车牌文本：全角转半角、去全部空白、大写。

    Args:
        text: 原始 OCR 文本。

    Returns:
        归一化后的文本（可能为空字符串，由调用方按非法处理）。
    """
    if not isinstance(text, str):
        raise ValueError("车牌文本必须为字符串")
    normalized = unicodedata.normalize("NFKC", text)
    stripped = re.sub(r"\s+", "", normalized)
    return stripped.upper()


def is_valid_plate(text: str) -> bool:
    """判断归一化车牌文本是否合法。

    规则：长度 3~10、仅允许汉字/大写字母数字、必须含至少一位数字；
    纯数字仅接受 4~6 位（校园自编号）；其余须含数字。
    "XYZ" 因无数字被拒绝；"AB" 因过短被拒绝。

    Args:
        text: 待校验文本（内部先归一化，调用方可直接传原始 OCR 文本）。

    Returns:
        合法返回 True。
    """
    normalized = normalize_plate(text)
    if not 3 <= len(normalized) <= 10:
        return False
    if _ALLOWED_RE.match(normalized) is None:
        return False
    if normalized.isdigit():
        return 4 <= len(normalized) <= 6
    return _HAS_DIGIT_RE.search(normalized) is not None


def guess_plate_type(text: str) -> PlateType:
    """猜测车牌类型；非法输入返回 "none"。

    Args:
        text: 待判断文本（内部先归一化）。

    Returns:
        blue / school / university / none 之一。
    """
    normalized = normalize_plate(text)
    if not is_valid_plate(normalized):
        return "none"
    if "校" in normalized or "大学" in normalized:
        return "university"
    if "门" in normalized or normalized.isdigit():
        return "school"
    if re.match(r"^[A-Z]\d{4,5}$", normalized) is not None:
        return "school"
    if "\u4e00" <= normalized[0] <= "\u9fa5":
        return "blue"
    return "blue"


def campus_plate_score(text: str) -> float:
    """校园模式符合度打分（0~1），用于约束后处理的加分项。

    基分 0.40；命中任一校园模式叠加对应 bonus；无数字惩罚 0.20
    （色调无定义的噪声文本降权）。实测：东门037≈0.75、A12345≈0.60、
    XYZ≈0.20，三档分离。

    Args:
        text: 待打分文本（内部先归一化）。

    Returns:
        [0, 1] 内的模式分数。
    """
    normalized = normalize_plate(text)
    if not normalized:
        return 0.0
    score = 0.40
    for _, pattern, bonus in _CAMPUS_PATTERNS:
        if pattern.search(normalized) is not None:
            score += bonus
    if _HAS_DIGIT_RE.search(normalized) is None:
        score -= 0.20
    return min(max(score, 0.0), 1.0)

"""监控点位配置领域层：ROI/计数线/提醒区纯校验（零 I/O）。

职责：为 camera_points 提供归一化坐标校验与钳制，保证入库前合法。
依赖：仅标准库；不读库、不写库、不读时钟。
边界：只做几何合法性判定；持久化与 RBAC 由服务层负责。
"""

from __future__ import annotations

# ROI 最小边长：防止误触画出零面积框（归一化坐标系下）。
MIN_EDGE = 0.02


def _is_unit(value: object) -> bool:
    """判断是否为 [0, 1] 内的有限浮点数。"""
    return isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0


def validate_rect(values: object, *, field: str = "roi") -> list[float]:
    """校验归一化矩形 [x1, y1, x2, y2]。

    Args:
        values: 待校验值。
        field: 字段名（报错信息用）。

    Returns:
        归一化后的四元浮点列表。

    Raises:
        ValueError: 长度非 4、越界、x1>=x2、y1>=y2、边过小。
    """
    if not isinstance(values, (list, tuple)) or len(values) != 4:
        raise ValueError(f"{field} 必须为 [x1,y1,x2,y2] 四元数组")
    try:
        rect = [float(item) for item in values]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须为数字数组") from exc
    if not all(_is_unit(item) for item in rect):
        raise ValueError(f"{field} 坐标必须在 0~1 范围内")
    x1, y1, x2, y2 = rect
    if not (x1 < x2 and y1 < y2):
        raise ValueError(f"{field} 必须满足 x1<x2 且 y1<y2")
    if min(x2 - x1, y2 - y1) < MIN_EDGE:
        raise ValueError(f"{field} 边长过小，请重新框选")
    return rect


def validate_line_y(value: object, *, field: str = "count_line_y") -> float:
    """校验归一化计数线高度。

    Args:
        value: 待校验值。
        field: 字段名。

    Returns:
        归一化浮点数。

    Raises:
        ValueError: 非数字或越界。
    """
    if not isinstance(value, (int, float)):
        raise ValueError(f"{field} 必须为数字")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{field} 必须在 0~1 范围内")
    return result


__all__ = ["MIN_EDGE", "validate_line_y", "validate_rect"]

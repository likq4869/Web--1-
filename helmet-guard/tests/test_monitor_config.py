"""P3-4 收尾：ROI 几何校验纯函数测试（零 I/O）。

职责：覆盖归一化矩形/计数线的合法与非法分支。
依赖：pytest、app.domain.monitor_config。
边界：只测纯函数，不碰库。
"""

from __future__ import annotations

import pytest

from app.domain.monitor_config import validate_line_y, validate_rect


def test_validate_rect_accepts_unit_rect() -> None:
    """合法归一化矩形原样通过."""
    assert validate_rect([0.05, 0.2, 0.95, 0.95]) == [0.05, 0.2, 0.95, 0.95]


def test_validate_rect_rejects_bad_shapes() -> None:
    """长度非 4 / 非数字 / 越界一律拒绝."""
    with pytest.raises(ValueError):
        validate_rect([0.1, 0.1, 0.9])
    with pytest.raises(ValueError):
        validate_rect(["a", 0.1, 0.9, 0.9])
    with pytest.raises(ValueError):
        validate_rect([-0.1, 0.1, 0.9, 0.9])
    with pytest.raises(ValueError):
        validate_rect([0.9, 0.9, 0.1, 0.1])


def test_validate_rect_rejects_degenerate() -> None:
    """零面积 / 过小边拒绝（防误触）。"""
    with pytest.raises(ValueError):
        validate_rect([0.5, 0.5, 0.5, 0.9])
    with pytest.raises(ValueError):
        validate_rect([0.5, 0.5, 0.505, 0.9])


def test_validate_line_y_bounds() -> None:
    """计数线必须为 0~1 数字."""
    assert validate_line_y(0.6) == 0.6
    with pytest.raises(ValueError):
        validate_line_y(1.5)
    with pytest.raises(ValueError):
        validate_line_y("0.6")


__all__ = [
    "test_validate_line_y_bounds",
    "test_validate_rect_accepts_unit_rect",
    "test_validate_rect_rejects_bad_shapes",
    "test_validate_rect_rejects_degenerate",
]

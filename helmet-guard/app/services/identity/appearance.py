"""车辆外观服务：从帧图中提取 128 维车辆嵌入。

职责：把检测框映射为领域层可用的裁剪图与框坐标，串联直方图 + 形状签名。
依赖：cv2、numpy、app.domain.vehicle_appearance。
边界：只做特征提取；不做匹配决策、不访问数据库。
"""

from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray

from app.domain.vehicle_appearance import (
    compute_embedding,
    extract_color_histogram,
    extract_shape_signature,
)

# 车辆区域取 Cyclists 框下部比例：车身在框下部，上部多为骑行者躯干/头部。
# 取 60% 可覆盖车架与车轮，同时剔除骑行者衣物颜色对车身颜色的污染。
VEHICLE_CROP_RATIO = 0.60


def _crop_vehicle_region(
    frame: NDArray[np.uint8], rider_box: tuple[float, float, float, float]
) -> NDArray[np.uint8]:
    """从 Cyclists 框裁剪车辆区域（框下部 60%）。

    Args:
        frame: BGR uint8 帧图，形状 (H, W, 3)。
        rider_box: (x1, y1, x2, y2) 框坐标。

    Returns:
        RGB uint8 车辆裁剪图。

    Raises:
        ValueError: 输入非法或裁剪区域为空。
    """
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("frame 必须为形状 (H, W, 3) 的数组")
    if frame.dtype != np.uint8:
        raise ValueError("frame 必须为 uint8 类型")
    x1, y1, x2, y2 = (float(v) for v in rider_box)
    height = y2 - y1
    if height <= 0 or (x2 - x1) <= 0:
        raise ValueError("rider_box 宽高必须为正")
    cut_y = y1 + height * (1.0 - VEHICLE_CROP_RATIO)
    h, w = frame.shape[:2]
    ix1 = max(0, int(round(x1)))
    iy1 = max(0, int(round(cut_y)))
    ix2 = min(w, int(round(x2)))
    iy2 = min(h, int(round(y2)))
    if ix2 <= ix1 or iy2 <= iy1:
        raise ValueError("车辆裁剪区域为空（框超出画面或过小）")
    bgr_crop = frame[iy1:iy2, ix1:ix2]
    rgb_crop = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2RGB)
    return np.ascontiguousarray(rgb_crop)


def extract_vehicle_embedding(
    frame: NDArray[np.uint8], rider_box: tuple[float, float, float, float]
) -> NDArray[np.float64]:
    """从帧图与骑行者框提取 128 维 L2 归一化车辆嵌入。

    Args:
        frame: BGR uint8 帧图。
        rider_box: (x1, y1, x2, y2) 骑行者框。

    Returns:
        128 维 L2 归一化向量。
    """
    crop = _crop_vehicle_region(frame, rider_box)
    color_hist = extract_color_histogram(crop)
    shape_sig = extract_shape_signature(rider_box)
    return compute_embedding(color_hist, shape_sig)

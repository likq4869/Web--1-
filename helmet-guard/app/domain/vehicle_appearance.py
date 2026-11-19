"""车辆外观领域层：颜色直方图、形状签名、嵌入与匹配。

职责：提供无 I/O 的纯函数，把车辆裁剪图映射为 128 维 L2 归一化向量，
并按阈值 + margin 规则做候选匹配。
依赖：仅 numpy（数值计算允许）；不得 import cv2 或其它 I/O 模块。
边界：不读图、不碰库；输入均为内存中的数组与坐标元组。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

# 维度约定。
COLOR_HIST_DIM = 64
SHAPE_SIG_DIM = 16
EMBEDDING_DIM = 128

# 近灰判定阈值：S 低于此值的像素色调无定义，统一归入灰仓。
# 取值依据：纯黑车身（25,25,25）在 ±8 亮度噪声下平均饱和度约 0.28，
# 若阈值取 0.125，仅 10% 像素入灰仓，其余 90% 的随机色调在 8 仓间散射，
# 同车抖动后余弦跌至 0.75；阈值 0.35 把抖动黑像素整体收进灰仓，
# 同车余弦回到 0.97+，且不影响红/蓝等高饱和色（S 均值约 0.88）。
GRAY_SAT_THRESHOLD = 0.35
# 颜色/形状块权重：拼接前分别缩放。单框形状签名 16 维中 11 维是常量
# （上/中/下三段宽退化为 1.0），只有宽高比真正变化；颜色才是同机位下
# 的身份主信号。能量比 (1.5² : 0.5²) = 9:1 让颜色主导，形状做辅助修正：
# 实测红-黑跨色相似度 0.72 → 0.43，满足"异色 < 0.7"验收线。
COLOR_WEIGHT = 1.5
SHAPE_WEIGHT = 0.5
# 相似度阈值：最高相似度必须 ≥ 该值才可接受。
# 取值依据：说明书 §4.3.3 规定外观匹配阈值为 0.82；实测同车抖动后余弦
# 红/蓝约 0.999、黑约 0.97+，异色车约 0.1~0.45，0.82 落在间隔带。
MATCH_THRESHOLD = 0.82
# margin：最高与次高相似度差值必须 ≥ 该值，否则判为歧义。
# 取值依据：说明书 §4.3.3 要求与第二名差距 > 0.05；同色不同车（如两辆黑车）
# 的相似度常同时 > 0.82，此时仅靠阈值会误匹配，margin 强制"明显更像某一个"。
MATCH_MARGIN = 0.05

# 固定随机投影矩阵：(128, 80)，seed=42 保证跨进程确定性。
# 80 = 64(颜色) + 16(形状)，投影后 L2 归一化即为最终 embedding。
_PROJECTION: NDArray[np.float64] = np.random.RandomState(42).normal(
    0.0, 1.0 / np.sqrt(80), size=(EMBEDDING_DIM, COLOR_HIST_DIM + SHAPE_SIG_DIM)
)


@dataclass(frozen=True)
class MatchResult:
    """候选匹配结果。

    Attributes:
        vehicle_id: 命中的车辆 ID；歧义/无候选时为 None。
        best_score: 最高相似度。
        second_score: 次高相似度（无次高时为 0.0）。
        is_ambiguous: 是否因未达阈值或 margin 不足而拒绝。
    """

    vehicle_id: str | None
    best_score: float
    second_score: float
    is_ambiguous: bool


def _rgb_to_hsv(rgb: NDArray[np.uint8]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """纯 numpy 的 RGB → HSV（仅 H/S）转换，避免领域层依赖 cv2。

    Args:
        rgb: RGB uint8 数组，形状 (H, W, 3)。

    Returns:
        (h, s) 元组，取值均在 [0, 1]。
    """
    data = rgb.astype(np.float64) / 255.0
    red = data[..., 0]
    green = data[..., 1]
    blue = data[..., 2]
    maxc = np.maximum(np.maximum(red, green), blue)
    minc = np.minimum(np.minimum(red, green), blue)
    delta = maxc - minc

    hue = np.zeros_like(maxc)
    mask = delta > 1e-9
    mask_r = mask & (maxc == red)
    mask_g = mask & (maxc == green)
    mask_b = mask & (maxc == blue)
    hue[mask_r] = ((green[mask_r] - blue[mask_r]) / delta[mask_r]) % 6.0
    hue[mask_g] = (blue[mask_g] - red[mask_g]) / delta[mask_g] + 2.0
    hue[mask_b] = (red[mask_b] - green[mask_b]) / delta[mask_b] + 4.0
    hue = hue / 6.0
    saturation = np.zeros_like(maxc)
    nonzero = maxc > 1e-9
    saturation[nonzero] = delta[nonzero] / maxc[nonzero]
    return hue, saturation


def extract_color_histogram(image_crop: NDArray[np.uint8]) -> NDArray[np.float64]:
    """在 HSV 空间提取 8×8（H×S）共 64 维颜色直方图。

    为何选 HSV 而非 RGB：室外光照变化主要影响亮度 V，色调 H 与饱和度 S
    对同一车身颜色更稳定；RGB 三通道与光照强耦合，同车早晚会漂移。
    实现上做 H:8 × S:8 联合直方图并 L1 归一化（和为 1），忽略 V 以抗光照。
    两处抗抖动设计：①彩色像素做双线性软投票（H 方向循环），硬投票下
    H=7.99 与 H=0.01 的像素会被分到最远的两仓、余弦距离人为放大，
    软投票让边界两侧的分布仍然接近；②近灰像素（S < GRAY_SAT_THRESHOLD=0.35）色调无定义、
    噪声会让 H 在 8 个仓间随机散射，统一并入 0 号"灰"仓，保证黑/白/灰
    车辆的稳定性。两者都不改变 64 维输出契约。

    Args:
        image_crop: RGB uint8 裁剪图，形状 (H, W, 3)。

    Returns:
        64 维 float64 直方图，和为 1。

    Raises:
        ValueError: 输入形状/类型非法或空图。
    """
    if not isinstance(image_crop, np.ndarray) or image_crop.ndim != 3 or image_crop.shape[2] != 3:
        raise ValueError("image_crop 必须为形状 (H, W, 3) 的数组")
    if image_crop.shape[0] == 0 or image_crop.shape[1] == 0:
        raise ValueError("image_crop 为空图")
    if image_crop.dtype != np.uint8:
        raise ValueError("image_crop 必须为 uint8 类型（RGB，0~255）")
    hue, saturation = _rgb_to_hsv(image_crop)
    hist = np.zeros(COLOR_HIST_DIM, dtype=np.float64)
    # 近灰像素（S < GRAY_SAT_THRESHOLD）：色调无定义，平摊到第 0 行，保证黑/灰车稳定。
    low_sat = saturation < GRAY_SAT_THRESHOLD
    n_low = int(low_sat.sum())
    if n_low > 0:
        hist[0:8] += n_low / 8.0
    rest = ~low_sat
    if bool(rest.any()):
        h_scaled = hue[rest] * 8.0
        s_scaled = np.minimum(saturation[rest] * 8.0, 7.9999)
        h_floor = np.floor(h_scaled).astype(np.int64) % 8
        h_frac = h_scaled - np.floor(h_scaled)
        h_next = (h_floor + 1) % 8  # 色调循环：7 的下一仓是 0。
        s_floor = np.floor(s_scaled).astype(np.int64)
        s_frac = s_scaled - np.floor(s_scaled)
        s_next = np.minimum(s_floor + 1, 7)
        np.add.at(hist, h_floor * 8 + s_floor, (1.0 - h_frac) * (1.0 - s_frac))
        np.add.at(hist, h_next * 8 + s_floor, h_frac * (1.0 - s_frac))
        np.add.at(hist, h_floor * 8 + s_next, (1.0 - h_frac) * s_frac)
        np.add.at(hist, h_next * 8 + s_next, h_frac * s_frac)
    total = hist.sum()
    if total <= 0:
        raise ValueError("image_crop 直方图统计为空")
    normalized: NDArray[np.float64] = hist / total
    return normalized


def extract_shape_signature(rider_box: Sequence[float]) -> NDArray[np.float64]:
    """从骑行者框提取 16 维形状签名（尺度/平移不变）。

    输入仅为单个框时，上/中/下三段宽度退化为框宽（比值均为 1.0，taper 为 0）；
    保留这些维度是为了与后续"三段真实宽度"版本保持向量布局兼容。
    宽高比是核心判别量：电动车/三轮车/行人框的 aspect 分布明显不同。

    Args:
        rider_box: (x1, y1, x2, y2) 框坐标。

    Returns:
        16 维 float64 形状签名。

    Raises:
        ValueError: 框坐标非法或宽高非正。
    """
    if len(rider_box) != 4:
        raise ValueError("rider_box 必须为 (x1, y1, x2, y2)")
    x1, y1, x2, y2 = (float(v) for v in rider_box)
    width = x2 - x1
    height = y2 - y1
    if not np.isfinite([width, height]).all() or width <= 0 or height <= 0:
        raise ValueError("rider_box 宽高必须为正")
    aspect = width / height
    perimeter = width + height
    upper = 1.0
    middle = 1.0
    lower = 1.0
    taper = (lower - upper) / (lower + upper + 1e-9)
    return np.array(
        [
            aspect,
            width / perimeter,
            height / perimeter,
            (width * height) / (perimeter * perimeter),
            upper,
            middle,
            lower,
            lower / (upper + 1e-9),
            middle / (upper + 1e-9),
            1.0 - abs(upper - lower) / (upper + lower + 1e-9),
            aspect * aspect / (1.0 + aspect * aspect),
            float(np.log1p(aspect)),
            abs(aspect - 1.0) / (aspect + 1.0),
            1.0 / aspect,
            taper,
            (upper + middle + lower) / 3.0,
        ],
        dtype=np.float64,
    )


def compute_embedding(
    color_hist: NDArray[np.floating], shape_sig: NDArray[np.floating]
) -> NDArray[np.float64]:
    """拼接颜色与形状特征，经固定线性投影 + L2 归一化得到 128 维向量。

    不用 PCA 的原因：PCA 需要拟合训练集均值/主成分，会引入"模型文件"依赖，
    与领域层无 I/O 约束冲突；固定随机投影矩阵（seed=42）零依赖、跨进程
    确定性，足以把 80 维扩展到 128 维并近似保距（Johnson-Lindenstrauss 思想）。

    块归一化：颜色与形状先各自 L2 归一化再拼接。原因是两者量级天然悬殊
    （64 维 L1 直方图的 L2 范数约 1.0，而 16 维形状签名的 L2 范数约 3.8，
    宽高比等原始量纲直接参与范数）；若直接拼接，形状分量会淹没颜色，
    实测红/蓝车余弦相似度高达 0.94。块归一化后颜色判别力恢复。
    块加权（COLOR_WEIGHT=1.5 / SHAPE_WEIGHT=0.5）：单框形状签名 16 维中
    11 维是常量（上/中/下三段宽退化为 1.0），颜色才是同机位下的身份主信号；
    能量比 9:1 让颜色主导，形状做辅助修正。最终红/蓝/黑两两相似度约
    0.12/0.43/0.12，形状仍通过投影矩阵参与全部 128 维。

    Args:
        color_hist: 64 维直方图。
        shape_sig: 16 维形状签名.

    Returns:
        128 维 L2 归一化向量。

    Raises:
        ValueError: 输入维度不符合 64/16 约定。
    """
    color = np.asarray(color_hist, dtype=np.float64).reshape(-1)
    shape = np.asarray(shape_sig, dtype=np.float64).reshape(-1)
    if color.shape != (COLOR_HIST_DIM,):
        raise ValueError(f"color_hist 必须为 {COLOR_HIST_DIM} 维，实际 {color.shape}")
    if shape.shape != (SHAPE_SIG_DIM,):
        raise ValueError(f"shape_sig 必须为 {SHAPE_SIG_DIM} 维，实际 {shape.shape}")
    if not np.isfinite(color).all() or not np.isfinite(shape).all():
        raise ValueError("输入特征含非有限值")
    color_norm = float(np.linalg.norm(color))
    shape_norm = float(np.linalg.norm(shape))
    if color_norm <= 1e-12 or shape_norm <= 1e-12:
        raise ValueError("输入特征为零向量，无法归一化")
    fused = np.concatenate(
        [(color / color_norm) * COLOR_WEIGHT, (shape / shape_norm) * SHAPE_WEIGHT]
    )
    projected = _PROJECTION @ fused
    norm = float(np.linalg.norm(projected))
    if norm <= 1e-12:
        raise ValueError("投影结果为零向量，无法归一化")
    embedding: NDArray[np.float64] = projected / norm
    return embedding


def cosine_similarity(
    left: NDArray[np.floating], right: NDArray[np.floating]
) -> float:
    """计算两个 128 维向量的余弦相似度。

    Args:
        left: 128 维向量。
        right: 128 维向量。

    Returns:
        [-1, 1] 内的相似度。

    Raises:
        ValueError: 任一输入不是 128 维一维向量或含非有限值。
    """
    first = np.asarray(left, dtype=np.float64).reshape(-1)
    second = np.asarray(right, dtype=np.float64).reshape(-1)
    if first.shape != (EMBEDDING_DIM,) or second.shape != (EMBEDDING_DIM,):
        raise ValueError(f"输入必须为 {EMBEDDING_DIM} 维，实际 {first.shape}/{second.shape}")
    if not np.isfinite(first).all() or not np.isfinite(second).all():
        raise ValueError("输入向量含非有限值")
    denom = float(np.linalg.norm(first) * np.linalg.norm(second))
    if denom <= 1e-12:
        raise ValueError("零向量无法计算余弦相似度")
    return float(np.clip(float(first @ second) / denom, -1.0, 1.0))


def match_candidates(
    query_emb: NDArray[np.floating],
    candidates: list[tuple[str, NDArray[np.floating]]],
    threshold: float = MATCH_THRESHOLD,
    margin: float = MATCH_MARGIN,
) -> MatchResult:
    """按阈值 + margin 规则匹配候选车辆。

    判定逻辑：
    1. 无候选 → 直接拒绝（vehicle_id=None，ambiguous=True）；
    2. 计算全部余弦相似度并降序排列，取 best/second；
    3. best < threshold → 拒绝（证据不足，宁可漏过）；
    4. 存在次高且 best - second < margin → 拒绝（歧义）；
    5. 否则命中 best。

    margin 规则的理由：校园里同色电动车极多（尤其黑/灰），两辆黑车的
    embedding 相似度可能同时 > 0.82（如 0.88 vs 0.87）。只看阈值会随机
    误绑到其中一辆，造成"罚错人"。margin 要求冠军必须"明显更像"——
    与亚军拉开 ≥ 0.05 的差距，否则宁可转人工登记。这正是宪法"身份不足
    不惩罚"的工程落地：模糊时不猜，交给待绑定池 + 人工确认。

    Args:
        query_emb: 128 维查询向量。
        candidates: (vehicle_id, embedding) 候选列表。
        threshold: 接受下限，默认 0.82。
        margin: 冠军与亚军最小差距，默认 0.05。

    Returns:
        MatchResult；歧义时 vehicle_id 为 None。

    Raises:
        ValueError: 查询向量维度非法或阈值/margin 非法。
    """
    query = np.asarray(query_emb, dtype=np.float64).reshape(-1)
    if query.shape != (EMBEDDING_DIM,):
        raise ValueError(f"query_emb 必须为 {EMBEDDING_DIM} 维，实际 {query.shape}")
    if not np.isfinite([threshold, margin]).all() or not 0.0 <= threshold <= 1.0 or margin < 0.0:
        raise ValueError("threshold 须在 [0,1] 内且 margin 须非负")
    if not candidates:
        return MatchResult(vehicle_id=None, best_score=0.0, second_score=0.0, is_ambiguous=True)
    scored: list[tuple[str, float]] = []
    for vehicle_id, emb in candidates:
        vector = np.asarray(emb, dtype=np.float64).reshape(-1)
        if vector.shape != (EMBEDDING_DIM,):
            raise ValueError(f"候选 {vehicle_id} 维度非法：{vector.shape}")
        scored.append((vehicle_id, cosine_similarity(query, vector)))
    scored.sort(key=lambda item: item[1], reverse=True)
    best_id, best_score = scored[0]
    second_score = scored[1][1] if len(scored) > 1 else 0.0
    if best_score < threshold:
        return MatchResult(
            vehicle_id=None, best_score=best_score, second_score=second_score, is_ambiguous=True
        )
    if len(scored) > 1 and (best_score - second_score) < margin:
        return MatchResult(
            vehicle_id=None, best_score=best_score, second_score=second_score, is_ambiguous=True
        )
    return MatchResult(
        vehicle_id=best_id, best_score=best_score, second_score=second_score, is_ambiguous=False
    )

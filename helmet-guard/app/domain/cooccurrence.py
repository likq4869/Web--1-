"""车辆共现领域层：时间窗口划分、Jaccard 相似度、共现统计与图匹配。

职责：提供无 I/O 的纯函数，把"车辆在哪些时间窗口出现过"映射为
车辆归属推断（未知车 → 学号），作为车牌/二维码缺失时的软件兜底。
依赖：仅标准库 + datetime；scipy（匈牙利算法）为可选，按需延迟导入。
边界：不读库、不写库；输入均为内存中的集合与字典。

时间窗口策略（见 build_windows）：
- 窗口长度默认 5 分钟（同一宿舍楼/同班同学结伴出行的典型时间粒度；
  过短会把同行人拆散，过长会把前后脚的陌生人误判为同行）。
- 窗口索引 = floor(UTC 时间戳 / 窗口秒数)，天然对齐跨小时/跨天边界，
  无需特殊处理（2024-01-01 00:00 与 2023-12-31 23:59 落在相邻窗口）。
- naive 时间一律视为 UTC（SQLite 读出的 CURRENT_TIMESTAMP 即为此类）。

置信度公式（见 compute_cooccurrence）：
    conf(u, v) = jaccard(u, v) * min(1, shared / 3)
- jaccard 刻画"同行比例"（一起出现的窗口 / 任一出现的窗口）；
- min(1, shared/3) 为"次数饱和因子"：仅共现 1 次时即使 jaccard=1.0
  也只给 1/3 置信（偶然同行不采信）；共现 ≥3 次后饱和为 1。
- 上限天然 ≤1.0，且单独共现证据在 resolver 侧还会被钳制到
  [0.30, 0.55]（见 resolver.cooccur_confidence），保证共现
  自始至终只是"身份辅助"，单独无法 BIND。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

# 默认窗口长度（分钟）：结伴出行的典型时间粒度。
DEFAULT_WINDOW_MINUTES = 5
# 次数饱和阈值：共现达到该窗口数后，次数因子饱和为 1。
SHARED_COUNT_SATURATION = 3
# 图匹配默认准入线：低于该置信度的边不参与分配。
DEFAULT_MIN_CONFIDENCE = 0.60


@dataclass(frozen=True)
class CooccurrenceStats:
    """一对车辆的共现统计。

    Attributes:
        vehicle_a: 字典序较小的车辆 ID（规范序，保证 (a,b) 唯一键）。
        vehicle_b: 字典序较大的车辆 ID。
        shared_windows: 共同出现的窗口数（|A ∩ B|）。
        union_windows: 任一出现的窗口数（|A ∪ B|）。
        jaccard: Jaccard 相似度 shared/union。
        confidence: 综合置信度 = jaccard * min(1, shared/3)。
    """

    vehicle_a: str
    vehicle_b: str
    shared_windows: int
    union_windows: int
    jaccard: float
    confidence: float


def _as_utc(moment: datetime) -> datetime:
    """把时间统一为 UTC 有时区时间；naive 视为 UTC。"""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def build_windows(
    timestamps: list[datetime], window_minutes: int = DEFAULT_WINDOW_MINUTES
) -> list[int]:
    """把时间戳序列映射为窗口索引序列（与输入等长、一一对应）。

    窗口索引 = floor(UTC 纪元秒 / 窗口秒数)，天然对齐小时/天边界。

    Args:
        timestamps: 通行时间序列（顺序保留，输出与输入一一对应）。
        window_minutes: 窗口长度（分钟），必须为正整数。

    Returns:
        与输入等长的窗口索引列表。

    Raises:
        ValueError: window_minutes 非正。
    """
    if window_minutes <= 0:
        raise ValueError(f"window_minutes 必须为正整数，实际 {window_minutes}")
    span = window_minutes * 60
    return [int(_as_utc(moment).timestamp()) // span for moment in timestamps]


def jaccard(first: set[int], second: set[int]) -> float:
    """计算两窗口集合的 Jaccard 相似度 |∩|/|∪|。

    两集合皆空时分母为 0，按"无证据"返回 0.0（而非 1.0），
    避免两辆从未出现的车被误判为"完全共现"。

    Args:
        first: 车辆 A 的窗口集合。
        second: 车辆 B 的窗口集合。

    Returns:
        [0, 1] 内的相似度。
    """
    union = first | second
    if not union:
        return 0.0
    return len(first & second) / len(union)


def compute_cooccurrence(
    vehicle_windows: dict[str, set[int]],
) -> dict[tuple[str, str], CooccurrenceStats]:
    """计算全部车辆对的共现统计。

    Args:
        vehicle_windows: 车辆 ID → 出现窗口集合。

    Returns:
        (vehicle_a, vehicle_b) 规范序对 → 共现统计；不足两辆车时为空字典。
    """
    vehicles = sorted(vehicle_windows)
    result: dict[tuple[str, str], CooccurrenceStats] = {}
    for i, first in enumerate(vehicles):
        for second in vehicles[i + 1 :]:
            first_set = vehicle_windows[first]
            second_set = vehicle_windows[second]
            shared = len(first_set & second_set)
            union = len(first_set | second_set)
            similarity = (shared / union) if union else 0.0
            confidence = similarity * min(1.0, shared / SHARED_COUNT_SATURATION)
            result[(first, second)] = CooccurrenceStats(
                vehicle_a=first,
                vehicle_b=second,
                shared_windows=shared,
                union_windows=union,
                jaccard=similarity,
                confidence=confidence,
            )
    return result


def _profit_table(
    known: dict[str, str],
    cooc: dict[tuple[str, str], CooccurrenceStats],
) -> tuple[list[str], list[str], dict[tuple[str, str], float]]:
    """构建 未知车 × 学号 的利润表（取该未知车与该学号名下各已知车的最大共现置信度）。

    取最大而非平均的理由：共现是"同行"信号，一次强同行（如连续 5 天同窗口）
    的证据力高于多次弱同行的平均；平均会把强信号稀释掉。

    Returns:
        (未知车列表, 学号列表, (未知车, 学号) → 利润) 三元组；列表均已排序保证确定性。
    """
    # 规范化共现键（调用方可能传入任一顺序），冲突时取最大置信度。
    lookup: dict[tuple[str, str], float] = {}
    for (first, second), stats in cooc.items():
        key = (first, second) if first <= second else (second, first)
        confidence = float(stats.confidence)
        if key not in lookup or confidence > lookup[key]:
            lookup[key] = confidence
    # 学号 → 其名下已知车列表。
    owner_vehicles: dict[str, list[str]] = {}
    for vehicle_id, subject_id in known.items():
        owner_vehicles.setdefault(subject_id, []).append(vehicle_id)
    students = sorted(owner_vehicles)
    unknowns = sorted({v for pair in lookup for v in pair} - set(known))
    profits: dict[tuple[str, str], float] = {}
    for unknown in unknowns:
        for subject in students:
            best = 0.0
            for owned in owner_vehicles[subject]:
                key = (owned, unknown) if owned <= unknown else (unknown, owned)
                candidate = lookup.get(key, 0.0)
                if candidate > best:
                    best = candidate
            profits[(unknown, subject)] = best
    return unknowns, students, profits


def _greedy_assign(
    unknowns: list[str],
    students: list[str],
    profits: dict[tuple[str, str], float],
    min_conf: float,
) -> dict[str, tuple[str, float]]:
    """纯 Python 贪心分配：按利润降序依次指派（双方均未被占用才接受）。

    确定性保证：排序键为 (-利润, 未知车, 学号)，利润并列时字典序小的优先，
    跨进程/跨版本结果一致，可单测断言。
    """
    _ = (unknowns, students)  # 贪心只用边表；保留参数以与匈牙利版本签名对称。
    edges = [
        (profit, unknown, subject)
        for (unknown, subject), profit in profits.items()
        if profit >= min_conf
    ]
    edges.sort(key=lambda item: (-item[0], item[1], item[2]))
    assigned_unknowns: set[str] = set()
    assigned_students: set[str] = set()
    result: dict[str, tuple[str, float]] = {}
    for profit, unknown, subject in edges:
        if unknown in assigned_unknowns or subject in assigned_students:
            continue
        assigned_unknowns.add(unknown)
        assigned_students.add(subject)
        result[unknown] = (subject, profit)
    return result


def _hungarian_assign(
    unknowns: list[str],
    students: list[str],
    profits: dict[tuple[str, str], float],
    min_conf: float,
) -> dict[str, tuple[str, float]]:
    """匈牙利算法分配：带权二部图最大匹配（总利润最大），再按准入线过滤。

    过滤保持一对一：最优匹配的子集仍满足"一车一人、一人一车"。
    scipy 缺失时抛 ImportError，由调用方降级为贪心。

    Raises:
        ImportError: scipy 不可用。
    """
    import numpy as np  # noqa: PLC0415
    from scipy.optimize import linear_sum_assignment  # noqa: PLC0415

    if not unknowns or not students:
        return {}
    matrix = np.array(
        [[profits.get((u, s), 0.0) for s in students] for u in unknowns],
        dtype=np.float64,
    )
    rows, cols = linear_sum_assignment(-matrix)
    result: dict[str, tuple[str, float]] = {}
    for row, col in zip(rows, cols, strict=True):
        profit = float(matrix[row, col])
        if profit >= min_conf:
            result[unknowns[row]] = (students[col], profit)
    return result


def resolve_by_graph(
    known: dict[str, str],
    cooc: dict[tuple[str, str], CooccurrenceStats],
    min_conf: float = DEFAULT_MIN_CONFIDENCE,
    *,
    use_scipy: bool = True,
) -> dict[str, tuple[str, float]]:
    """用共现图把未知车分配给学号（保证一对一）。

    未知车 = 出现在共现对中但不在 known 里的车辆。分配满足：
    每辆未知车至多归属一个学号，每个学号至多认领一辆未知车；
    利润（该未知车与该学号名下已知车的最大共现置信度）低于
    min_conf 的边不参与分配。

    算法：scipy 可用时用匈牙利算法求总利润最大的匹配（`use_scipy=True`
    且导入失败时自动降级为贪心）；`use_scipy=False` 强制走纯 Python 贪心
    （scipy 未安装环境的唯一路径，单测覆盖）。

    Args:
        known: 已知车辆 → 学号。
        cooc: 车辆对 → 共现统计（键顺序不限，内部自动规范化）。
        min_conf: 准入线，必须在 [0, 1] 内。
        use_scipy: 是否尝试匈牙利算法；False 时强制贪心。

    Returns:
        未知车 → (学号, 置信度)；未分配的未知车不在结果中。

    Raises:
        ValueError: min_conf 越界。
    """
    if not 0.0 <= min_conf <= 1.0:
        raise ValueError(f"min_conf 必须在 [0, 1] 内，实际 {min_conf}")
    unknowns, students, profits = _profit_table(known, cooc)
    if not unknowns or not students:
        return {}
    if use_scipy:
        try:
            return _hungarian_assign(unknowns, students, profits, min_conf)
        except ImportError:
            pass
    return _greedy_assign(unknowns, students, profits, min_conf)

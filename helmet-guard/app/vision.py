"""权重检查与 ROI 几何：防止把 COCO 通用权重当头盔模型用。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# ultralytics 的 model.names 既可能是 {int: str} 映射，也可能是 list[str]；
# 两者都接受，语义上只关心「有哪些类别名」。
NamesInput = dict[Any, Any] | list[Any]


def normalize_names(names: NamesInput) -> list[str]:
    if isinstance(names, dict):
        return [str(v) for v in names.values()]
    return [str(v) for v in names]


def is_helmet_weights(names: NamesInput) -> tuple[bool, str]:
    labels = {n.strip().lower() for n in normalize_names(names)}
    has_helmet = "helmet" in labels
    has_no = "no helmet" in labels or "no-helmet" in labels or "no_helmet" in labels
    if has_helmet and has_no:
        if "cyclists" in labels:
            return True, "电瓶车 v2 类别：Cyclists/helmet/no helmet"
        return True, "头盔两类已就绪"
    if "person" in labels and not (has_helmet or has_no):
        return False, (
            "检测到 COCO 通用权重（含 person、无 helmet 类），"
            "不可做头盔业务判定，仅允许 camera_check 预览"
        )
    return False, f"权重类别缺少 helmet/no helmet，实际类别={sorted(labels)[:8]}"


def is_selfcheck_weights(names: NamesInput) -> tuple[bool, str]:
    """自查专用校验（预检与模型加载共用）：必须同时含骑行者与两种头部状态。

    要求 labels 同时包含 cyclists、helmet、no helmet（含 -/_ 变体）。
    电瓶车 v2 基线满足；COCO 通用权重与缺任一类的权重均拒绝。
    """
    labels = {n.strip().lower() for n in normalize_names(names)}
    has_rider = "cyclists" in labels
    has_helmet = "helmet" in labels
    has_no = "no helmet" in labels or "no-helmet" in labels or "no_helmet" in labels
    if has_rider and has_helmet and has_no:
        return True, "自查权重就绪：Cyclists/helmet/no helmet"
    missing = [
        k
        for k, v in (("Cyclists", has_rider), ("helmet", has_helmet), ("no helmet", has_no))
        if not v
    ]
    if "person" in labels and not (has_helmet or has_no):
        return False, "检测到 COCO 通用权重（含 person、无 helmet 类），不可做自查判定"
    return False, f"自查权重缺少类别：{missing}，实际类别={sorted(labels)[:8]}"


def inspect_weights_file(weights: Path) -> tuple[dict[int, str], str]:
    """返回 (names_dict, 说明)。文件缺失或加载失败抛 FileNotFoundError/RuntimeError。"""
    # ultralytics 未在 __all__ 中显式导出 YOLO，from-import 会触发
    # mypy attr-defined 误报；已在 pyproject 的 mypy overrides 中
    # 针对 ultralytics 模块单独放宽（仅放开导出检查，不影响其他检查）。
    import ultralytics

    p = Path(weights)
    if not p.is_file():
        raise FileNotFoundError(f"模型文件不存在：{p}")
    try:
        model = ultralytics.YOLO(str(p))
        names = dict(model.names)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError(f"权重加载失败：{p}，原因：{exc}") from exc
    ok, reason = is_helmet_weights(names)
    return names, ("ok: " + reason if ok else "reject: " + reason)


def in_rect(cx: float, cy: float, rect: list[float]) -> bool:
    x1, y1, x2, y2 = rect
    return x1 <= cx <= x2 and y1 <= cy <= y2


def crossed_line(prev_y: float | None, cur_y: float, line_y: float) -> bool:
    if prev_y is None:
        return False
    return (prev_y < line_y <= cur_y) or (prev_y > line_y >= cur_y)


def parse_yolo_label(line: str) -> tuple[int, float, float, float, float]:
    cls, cx, cy, w, h = line.strip().split()[:5]
    return int(cls), float(cx), float(cy), float(w), float(h)

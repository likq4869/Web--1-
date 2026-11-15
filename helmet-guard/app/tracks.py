"""骑行判定与去重：纯函数，可用合成序列测试，不依赖摄像头。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .vision import crossed_line, in_rect


@dataclass
class FrameEvidence:
    """单分析帧对单个目标的证据。"""

    riding: bool  # 人车几何 + 跨帧一致认为在骑行
    head: str | None = None  # 'helmet' / 'no helmet' / None（无证据/遮挡）


def decide_pass(evidences: list[FrameEvidence], min_frames: int, min_consistent: int) -> str:
    """返回 'excluded' | 'helmeted' | 'bare' | 'unknown'。

    - 先确认骑行：最近 min_frames 帧中 riding 帧数 < min_consistent -> excluded
      （行人、推车、关联不明，不计入已确认通行人次）。
    - 再看头部：bare 票数达标才报 bare；helmet 达标报 helmeted；否则 unknown。
    """
    window = evidences[-min_frames:] if len(evidences) >= min_frames else evidences
    riding_votes = sum(1 for e in window if e.riding)
    if riding_votes < min_consistent:
        return "excluded"
    bare_votes = sum(1 for e in window if e.riding and e.head == "no helmet")
    helmet_votes = sum(1 for e in window if e.riding and e.head == "helmet")
    if bare_votes >= min_consistent:
        return "bare"
    if helmet_votes >= min_consistent:
        return "helmeted"
    return "unknown"


def match_head_to_rider(rider_box: list[float], heads: list[tuple[str, list[float]]]) -> str | None:
    """rider_box 与头部框均为归一化 [x1,y1,x2,y2]。

    头部标签标在头部时，优先匹配骑手框上部；同一个头部只分配给一个骑手
    （调用方按顺序分配）。无明确证据返回 None（unknown）。
    """
    x1, y1, x2, y2 = rider_box
    top = [y1, y1 + (y2 - y1) * 0.45]  # 骑手框上部 45%
    best: str | None = None
    best_area = 0.0
    for label, hbox in heads:
        hx1, hy1, hx2, hy2 = hbox
        cx, cy = (hx1 + hx2) / 2, (hy1 + hy2) / 2
        # 头部中心需落在骑手框内且纵坐标在上部
        if not (x1 <= cx <= x2 and y1 <= cy <= y2):
            continue
        if not (top[0] <= cy <= top[1]):
            continue
        area = max(0.0, hx2 - hx1) * max(0.0, hy2 - hy1)
        if area > best_area:
            best_area = area
            best = label
    return best


@dataclass
class PassDeduper:
    """按（来源、运行、通过事件）去重。同一 track 在同一运行中只计一次。"""

    counted: set[tuple[str, str, str]] = field(default_factory=set)
    last_y: dict[tuple[str, str, str], float] = field(default_factory=dict)

    def check_crossing(
        self,
        source_id: str,
        run_id: str,
        track_id: str,
        cx: float,
        cy: float,
        roi: list[float],
        line_y: float,
    ) -> bool:
        """目标中心在 ROI 内且越过计数线、且本运行未计过 -> True（应计数）。"""
        key = (source_id, run_id, str(track_id))
        if key in self.counted:
            return False  # 重复越线去重
        if not in_rect(cx, cy, roi):
            self.last_y[key] = cy
            return False
        prev = self.last_y.get(key)
        self.last_y[key] = cy
        if crossed_line(prev, cy, line_y):
            self.counted.add(key)
            return True
        return False

    def pass_id(self, source_id: str, run_id: str, track_id: str) -> str:
        return f"{source_id}:{run_id}:trk-{track_id}"

    def event_id(self, source_id: str, run_id: str, track_id: str) -> str:
        return f"evt-{source_id}-{run_id}-trk-{track_id}"

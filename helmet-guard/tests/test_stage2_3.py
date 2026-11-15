"""阶段 2/3 测试：权重检查、判定、去重、提醒队列（纯合成，不碰摄像头）。"""

from __future__ import annotations

from app.alerts import should_alert
from app.tracks import FrameEvidence, PassDeduper, decide_pass, match_head_to_rider
from app.vision import crossed_line, in_rect, is_helmet_weights


def test_reject_coco_weights_for_live():
    ok, reason = is_helmet_weights({0: "person", 1: "bicycle", 2: "car"})
    assert ok is False
    assert "COCO" in reason


def test_accept_ebike_v2_weights():
    ok, reason = is_helmet_weights({0: "Cyclists", 1: "helmet", 2: "no helmet"})
    assert ok is True


def test_decide_bare_needs_stable_evidence():
    ev = [FrameEvidence(True, "no helmet")] * 3 + [FrameEvidence(True, None)] * 2
    assert decide_pass(ev, 5, 3) == "bare"


def test_decide_excludes_pedestrian_and_push():
    # 行人/推车：riding 不足 -> excluded，不计入通行人次
    ev = [FrameEvidence(False, None)] * 5
    assert decide_pass(ev, 5, 3) == "excluded"
    ev2 = [FrameEvidence(True, "helmet")] * 2 + [FrameEvidence(False, None)] * 3
    assert decide_pass(ev2, 5, 3) == "excluded"


def test_decide_unknown_when_head_occluded():
    ev = [FrameEvidence(True, None)] * 5
    assert decide_pass(ev, 5, 3) == "unknown"


def test_decide_helmeted():
    ev = [FrameEvidence(True, "helmet")] * 4 + [FrameEvidence(True, None)]
    assert decide_pass(ev, 5, 3) == "helmeted"


def test_head_matches_rider_top_only():
    rider = [0.4, 0.2, 0.6, 0.9]  # 上部 y in [0.2, 0.51]
    heads = [
        ("helmet", [0.45, 0.22, 0.55, 0.32]),  # 头顶附近 -> 命中
        ("no helmet", [0.45, 0.7, 0.55, 0.8]),
    ]  # 下半身 -> 忽略
    assert match_head_to_rider(rider, heads) == "helmet"
    far = [("no helmet", [0.0, 0.0, 0.1, 0.1])]
    assert match_head_to_rider(rider, far) is None


def test_deduper_counts_once_per_run():
    d = PassDeduper()
    roi = [0.0, 0.0, 1.0, 1.0]
    assert d.check_crossing("s", "run1", "7", 0.5, 0.4, roi, 0.6) is False
    assert d.check_crossing("s", "run1", "7", 0.5, 0.7, roi, 0.6) is True
    # 重复越线不再计数
    assert d.check_crossing("s", "run1", "7", 0.5, 0.4, roi, 0.6) is False
    assert d.check_crossing("s", "run1", "7", 0.5, 0.7, roi, 0.6) is False
    # 录像重跑 run2 可单独计数
    assert d.check_crossing("s", "run2", "7", 0.5, 0.4, roi, 0.6) is False
    assert d.check_crossing("s", "run2", "7", 0.5, 0.7, roi, 0.6) is True
    assert d.event_id("s", "run1", "7") == "evt-s-run1-trk-7"


def test_alert_default_silent_and_expiry():
    ok, why = should_alert(False, "e1", "s", True, True, True, 60)
    assert ok is False and why.startswith("silent")
    ok, why = should_alert(True, "e1", "s", False, True, True, 60)
    assert ok is False and why.startswith("expired")
    ok, why = should_alert(True, "e1", "s", True, False, True, 60)
    assert ok is False
    ok, why = should_alert(True, "e1", "s", True, True, False, 60)
    assert ok is False
    ok, why = should_alert(True, "e1", "s", True, True, True, 60)
    assert ok is True


def test_roi_and_line_helpers():
    assert in_rect(0.5, 0.5, [0.0, 0.0, 1.0, 1.0]) is True
    assert in_rect(1.5, 0.5, [0.0, 0.0, 1.0, 1.0]) is False
    assert crossed_line(0.4, 0.7, 0.6) is True
    assert crossed_line(None, 0.7, 0.6) is False
    assert crossed_line(0.4, 0.5, 0.6) is False

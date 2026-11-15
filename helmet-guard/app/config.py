"""点位配置：单个点位、方向、骑行 ROI、计数线、提醒区域、多帧参数。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class PointConfig:
    source_id: str = "gate-east"
    name: str = "东校门"
    direction: str = "in"  # 进校方向
    # 归一化坐标 [x1,y1,x2,y2]，骑行 ROI：只处理同向进入通道的目标
    roi: list[float] = field(default_factory=lambda: [0.05, 0.2, 0.95, 0.95])
    # 计数线：归一化 y（目标中心越过即计一次通过）
    count_line_y: float = 0.6
    # 提醒区域：目标中心在此区内才可提醒
    alert_zone: list[float] = field(default_factory=lambda: [0.2, 0.3, 0.8, 0.9])
    min_frames: int = 5  # 最近 N 个分析帧
    min_consistent: int = 3  # 其中至少 K 帧一致
    alert_cooldown_s: int = 60  # 按点位限频：同一秒级窗口内最多一次提醒
    alert_enabled: bool = False  # 默认静默，需人工触发


def get_point_config() -> PointConfig:
    cfg = PointConfig()
    if os.getenv("HELMET_GUARD_ALERTS_ENABLED", "0").strip() == "1":
        cfg.alert_enabled = True
    return cfg

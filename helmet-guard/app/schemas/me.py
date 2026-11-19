"""学生端总览出入参：首页积分卡 / 待确认提醒 / 近期记录。

职责：定义 GET /api/v1/me/overview 的响应模型。
依赖：pydantic。
边界：只描述结构与校验；排名与聚合由服务层计算。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MeScoreOut(BaseModel):
    """积分卡视图（无账户时取初始值，不建行）。"""

    model_config = ConfigDict(extra="forbid")

    balance: int = Field(description="当前积分余额")
    level: str = Field(description="等级 S/A/B/C/D")
    streak_days: int = Field(description="连续合规天数")
    compliance_rate: float = Field(description="30 天滚动佩戴率 [0,1]")
    rank: int | None = Field(default=None, description="全校排名（无账户时为空）")
    total_students: int = Field(default=0, description="参与排名的总人数")
    percentile: float | None = Field(
        default=None, description="超过全校比例 [0,1]，无账户时为空"
    )


class MePendingOut(BaseModel):
    """待确认提醒视图（只读，不做业务判定）。"""

    model_config = ConfigDict(extra="forbid")

    count: int = Field(description="待确认决策数（PENDING_REVIEW）")
    latest: dict[str, Any] | None = Field(
        default=None, description="最新一条决策摘要（无记录时为空）"
    )


class MeRecordsOut(BaseModel):
    """记录与申诉计数（含最近 5 条记录摘要）。"""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(description="安全记录总数")
    recent: list[dict[str, Any]] = Field(
        default_factory=list, description="最近记录摘要（按时间倒序，最多 5 条）"
    )
    appeals_total: int = Field(description="申诉总数")
    appeals_pending: int = Field(description="待处理申诉数")


class MeOverviewOut(BaseModel):
    """学生端总览（首页一屏聚合，只读）。"""

    model_config = ConfigDict(extra="forbid")

    student_id: str = Field(description="学号")
    name: str = Field(description="姓名")
    score: MeScoreOut
    pending: MePendingOut
    records: MeRecordsOut


__all__ = [
    "MeOverviewOut",
    "MePendingOut",
    "MeRecordsOut",
    "MeScoreOut",
]

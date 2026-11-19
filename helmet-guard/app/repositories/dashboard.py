"""总览域仓储：Dashboard 聚合查询（单条 SQL 条件聚合，无 N+1）。

职责：把 passes / events / decisions / sources / heartbeats 的统计口径
收敛为一次性聚合查询，供服务层组装总览、趋势与点位健康。
依赖：sqlalchemy、app.models.*。
边界：只做数据访问与聚合；不读时钟（时间锚点由调用方传入），
不做缓存，不做业务规则判定。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.decision import Decision
from app.models.entities import Event, Heartbeat, Pass, Source
from app.models.identity import Student
from app.models.scoring import ScoreAccount


class DashboardRepository:
    """总览聚合仓储。

    所有方法均为只读聚合；时间窗口由调用方以 naive datetime 传入
    （SQLite 的 DateTime 列读回为 naive，比较前统一由服务层转换）。
    """

    def __init__(self, session: Session) -> None:
        """初始化仓储。

        Args:
            session: 数据库会话；由调用方控制事务生命周期。
        """
        self.session = session

    # ------------------------------------------------------------------
    # 通行统计
    # ------------------------------------------------------------------

    def pass_summary(self, since: datetime, until: datetime) -> dict[str, int]:
        """统计时间窗内的通行总数与三态分布。

        Args:
            since: 窗口起点（含）。
            until: 窗口终点（不含）。

        Returns:
            ``{"total", "helmeted", "bare", "unknown"}``。
        """
        statement = select(
            func.count(),
            func.sum(case((Pass.rider_status == "helmeted", 1), else_=0)),
            func.sum(case((Pass.rider_status == "bare", 1), else_=0)),
            func.sum(case((Pass.rider_status == "unknown", 1), else_=0)),
        ).where(Pass.occurred_at >= since, Pass.occurred_at < until)
        row = self.session.execute(statement).one()
        return {
            "total": int(row[0] or 0),
            "helmeted": int(row[1] or 0),
            "bare": int(row[2] or 0),
            "unknown": int(row[3] or 0),
        }

    def pass_summary_by_day(self, since: datetime, until: datetime) -> dict[str, dict[str, int]]:
        """按天聚合通行与三态分布（佩戴率趋势用）。

        Args:
            since: 窗口起点（含）。
            until: 窗口终点（不含）。

        Returns:
            ``{"YYYY-MM-DD": {"total", "helmeted", "bare", "unknown"}}``。
        """
        day = func.substr(Pass.occurred_at, 1, 10)
        statement = (
            select(
                day.label("day"),
                func.count(),
                func.sum(case((Pass.rider_status == "helmeted", 1), else_=0)),
                func.sum(case((Pass.rider_status == "bare", 1), else_=0)),
                func.sum(case((Pass.rider_status == "unknown", 1), else_=0)),
            )
            .where(Pass.occurred_at >= since, Pass.occurred_at < until)
            .group_by(day)
            .order_by(day)
        )
        out: dict[str, dict[str, int]] = {}
        for key, total, helmeted, bare, unknown in self.session.execute(statement):
            out[str(key)] = {
                "total": int(total or 0),
                "helmeted": int(helmeted or 0),
                "bare": int(bare or 0),
                "unknown": int(unknown or 0),
            }
        return out

    def bare_summary_by_hour(self, since: datetime, until: datetime) -> dict[int, int]:
        """按小时聚合未戴盔通行数（今日时段柱状图用）。

        Args:
            since: 窗口起点（含）。
            until: 窗口终点（不含）。

        Returns:
            ``{0..23: 次数}``（缺省小时不出现在字典中）。
        """
        hour = func.substr(Pass.occurred_at, 12, 2)
        statement = (
            select(hour.label("hour"), func.count())
            .where(
                Pass.occurred_at >= since,
                Pass.occurred_at < until,
                Pass.rider_status == "bare",
            )
            .group_by(hour)
            .order_by(hour)
        )
        out: dict[int, int] = {}
        for key, count in self.session.execute(statement):
            try:
                out[int(key)] = int(count or 0)
            except (TypeError, ValueError):
                continue
        return out

    # ------------------------------------------------------------------
    # 决策与学生
    # ------------------------------------------------------------------

    def pending_decision_count(self) -> int:
        """统计待审批决策数。"""
        statement = select(func.count()).select_from(Decision).where(
            Decision.status == "PENDING_REVIEW"
        )
        return int(self.session.execute(statement).scalar_one())

    def decision_count_by_day(self, since: datetime, until: datetime) -> dict[str, int]:
        """按天聚合决策数（趋势图用）。

        Args:
            since: 窗口起点（含）。
            until: 窗口终点（不含）。

        Returns:
            ``{"YYYY-MM-DD": 数量}``。
        """
        day = func.substr(Decision.created_at, 1, 10)
        statement = (
            select(day.label("day"), func.count())
            .where(Decision.created_at >= since, Decision.created_at < until)
            .group_by(day)
            .order_by(day)
        )
        return {
            str(key): int(count or 0)
            for key, count in self.session.execute(statement)
        }

    def active_student_count(self, since: datetime) -> int:
        """统计窗口内有通行记录的去重学生数（活跃学生）。

        Args:
            since: 统计起点（含）。

        Returns:
            去重学号数量。
        """
        student_ids = select(Decision.student_id).where(
            Decision.student_id.is_not(None), Decision.created_at >= since
        )
        statement = select(func.count(func.distinct(student_ids.subquery().c.student_id)))
        return int(self.session.execute(statement).scalar_one())

    def total_student_count(self) -> int:
        """统计在册学生总数（status=active）。"""
        statement = select(func.count()).select_from(Student).where(
            Student.status == "active"
        )
        return int(self.session.execute(statement).scalar_one())

    def score_account_count(self) -> int:
        """统计已建积分账户的学生数。"""
        statement = select(func.count()).select_from(ScoreAccount)
        return int(self.session.execute(statement).scalar_one())

    # ------------------------------------------------------------------
    # 点位与心跳
    # ------------------------------------------------------------------

    def source_rows(self) -> list[dict[str, object]]:
        """读取全部点位（在线状态 + 最近在线时间）。"""
        statement = select(Source).order_by(Source.source_id)
        return [
            {
                "source_id": str(row.source_id),
                "name": str(row.name),
                "status": str(row.status),
                "last_seen": row.last_seen,
            }
            for row in self.session.execute(statement).scalars().all()
        ]

    def heartbeat_rows(self) -> list[dict[str, object]]:
        """读取全部采集心跳（最近心跳时间 + 明细 JSON）。"""
        statement = select(Heartbeat).order_by(Heartbeat.source_id)
        return [
            {
                "source_id": str(row.source_id),
                "run_id": str(row.run_id),
                "mode": str(row.mode),
                "updated_at": row.updated_at,
                "detail": str(row.detail or ""),
            }
            for row in self.session.execute(statement).scalars().all()
        ]

    def event_count_by_source_today(self, since: datetime, until: datetime) -> dict[str, int]:
        """按点位聚合今日违规事件数。

        Args:
            since: 窗口起点（含）。
            until: 窗口终点（不含）。

        Returns:
            ``{source_id: 数量}``。
        """
        statement = (
            select(Event.source_id, func.count())
            .where(Event.occurred_at >= since, Event.occurred_at < until)
            .group_by(Event.source_id)
        )
        return {
            str(key): int(count or 0)
            for key, count in self.session.execute(statement)
        }

    def last_event_at_by_source(self) -> dict[str, str]:
        """按点位取最后一条事件时间。

        Returns:
            ``{source_id: occurred_at}``。
        """
        statement = select(Event.source_id, func.max(Event.occurred_at)).group_by(
            Event.source_id
        )
        return {
            str(key): str(value)
            for key, value in self.session.execute(statement)
            if value is not None
        }

    def pass_count_by_source_today(self, since: datetime, until: datetime) -> dict[str, int]:
        """按点位聚合今日通行数。

        Args:
            since: 窗口起点（含）。
            until: 窗口终点（不含）。

        Returns:
            ``{source_id: 数量}``。
        """
        statement = (
            select(Pass.source_id, func.count())
            .where(Pass.occurred_at >= since, Pass.occurred_at < until)
            .group_by(Pass.source_id)
        )
        return {
            str(key): int(count or 0)
            for key, count in self.session.execute(statement)
        }

    def event_count_by_day(self, since: datetime, until: datetime) -> dict[str, int]:
        """按天聚合违规事件数（趋势图用）。

        Args:
            since: 窗口起点（含）。
            until: 窗口终点（不含）。

        Returns:
            ``{"YYYY-MM-DD": 数量}``。
        """
        day = func.substr(Event.occurred_at, 1, 10)
        statement = (
            select(day.label("day"), func.count())
            .where(Event.occurred_at >= since, Event.occurred_at < until)
            .group_by(day)
            .order_by(day)
        )
        return {
            str(key): int(count or 0)
            for key, count in self.session.execute(statement)
        }

    def filter_sources(self, source_id: str | None) -> list[dict[str, object]]:
        """按点位过滤（供趋势接口的 source 维度复用）。

        Args:
            source_id: 点位 ID；为 None 时返回全部。

        Returns:
            点位行列表。
        """
        rows = self.source_rows()
        if source_id is None:
            return rows
        return [row for row in rows if row["source_id"] == source_id]


__all__ = ["DashboardRepository"]

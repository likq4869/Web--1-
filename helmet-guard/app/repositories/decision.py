"""决策域仓储：决策、审批日志、回流样本的数据访问。

职责：封装 decisions / review_logs / feedback_samples 表的读写与聚合。
依赖：sqlalchemy、app.models.decision。
边界：只做数据访问；审批并发安全由条件 UPDATE 保证，状态机由服务层负责。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select, update
from sqlalchemy.engine import CursorResult

from app.models.decision import Decision, FeedbackSample, ReviewLog
from app.repositories.base import BaseRepository


class DecisionRepository(BaseRepository[Decision]):
    """决策仓储。"""

    model = Decision
    id_field = "decision_id"

    def get_by_event(self, event_id: str) -> Decision | None:
        """按事件读取决策（一事件一决策幂等）。

        Args:
            event_id: 事件 ID。

        Returns:
            既有决策；无记录时返回 None。
        """
        statement = select(Decision).where(Decision.event_id == event_id).limit(1)
        return self.session.execute(statement).scalar_one_or_none()

    def list_by_event_ids(self, event_ids: list[str]) -> list[Decision]:
        """按事件 ID 批量读取决策（监控流关联档位，避免 N+1）。

        Args:
            event_ids: 事件 ID 列表；为空时直接返回空列表。

        Returns:
            匹配的决策行列表。
        """
        if not event_ids:
            return []
        statement = select(Decision).where(Decision.event_id.in_(event_ids))
        return list(self.session.execute(statement).scalars().all())

    def list_with_filters(
        self,
        *,
        status: str | None = None,
        student_id: str | None = None,
        level: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        point_id: str | None = None,
        min_confidence: float | None = None,
        sort: str = "created_at/desc",
        limit: int = 20,
        offset: int = 0,
    ) -> list[Decision]:
        """按多维条件分页列出决策。

        Args:
            status: 审批状态。
            student_id: 学号。
            level: 决策档位。
            start: 创建时间起点（含）。
            end: 创建时间终点（含）。
            point_id: 点位 ID（按事件点位过滤，需 join events）。
            min_confidence: 最低置信度。
            sort: 排序表达式（白名单：``created_at/desc``、
                ``confidence/desc``、``level/asc``）；非法值回退默认。
            limit: 最大返回条数。
            offset: 跳过的条数。

        Returns:
            决策行列表。
        """
        statement = select(Decision)
        statement = self._apply_filters(
            statement,
            status=status,
            student_id=student_id,
            level=level,
            start=start,
            end=end,
            point_id=point_id,
            min_confidence=min_confidence,
        )
        statement = statement.order_by(self._sort_expression(sort))
        statement = statement.limit(limit).offset(offset)
        return list(self.session.execute(statement).scalars().all())

    def _apply_filters(
        self,
        statement: Any,
        *,
        status: str | None = None,
        student_id: str | None = None,
        level: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        point_id: str | None = None,
        min_confidence: float | None = None,
    ) -> Any:
        """把筛选条件应用到查询语句（列表与计数共用，避免口径漂移）。"""
        if status:
            statement = statement.where(Decision.status == status)
        if student_id:
            statement = statement.where(Decision.student_id == student_id)
        if level:
            statement = statement.where(Decision.level == level)
        if start is not None:
            statement = statement.where(Decision.created_at >= start)
        if end is not None:
            statement = statement.where(Decision.created_at <= end)
        if min_confidence is not None:
            statement = statement.where(Decision.confidence >= min_confidence)
        if point_id:
            from app.models.entities import Event as EventModel

            statement = statement.join(
                EventModel, EventModel.event_id == Decision.event_id
            ).where(EventModel.source_id == point_id)
        return statement

    @staticmethod
    def _sort_expression(sort: str) -> Any:
        """返回排序表达式；非法 sort 回退到默认的创建时间倒序。

        档位排序按字符串序（L0 < L1 < L2 < L3 < L4），与档位语义一致。
        """
        mapping = {
            "created_at/desc": Decision.created_at.desc(),
            "confidence/desc": Decision.confidence.desc(),
            "level/asc": Decision.level.asc(),
        }
        return mapping.get(sort, Decision.created_at.desc())

    def count_with_filters(
        self,
        *,
        status: str | None = None,
        student_id: str | None = None,
        level: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        point_id: str | None = None,
        min_confidence: float | None = None,
    ) -> int:
        """统计符合条件的决策数。"""
        statement = select(func.count()).select_from(Decision)
        statement = self._apply_filters(
            statement,
            status=status,
            student_id=student_id,
            level=level,
            start=start,
            end=end,
            point_id=point_id,
            min_confidence=min_confidence,
        )
        return int(self.session.execute(statement).scalar_one())

    def count_windows_for_student(
        self,
        student_id: str,
        *,
        now: datetime,
        source_id: str | None = None,
        current_event_id: str | None = None,
    ) -> dict[str, int]:
        """一次性条件聚合查出 1h/7d/30d 违规窗口统计，避免 N+1。

        只统计已生效口径的决策（APPROVED/ADJUSTED/AUTO_APPROVED/APPEALING/
        APPEAL_REJECTED），驳回与申诉成立不计入复犯。

        Args:
            student_id: 学号。
            now: 当前时间（由调用方传入，仓储不读时钟）。
            source_id: 同点位 1h 统计的点位限定；为 None 时该项为 0。
            current_event_id: 组装 Fact 时的事件发生时间锚点（可选）。

        Returns:
            {"count_30d": ..., "count_7d": ..., "count_1h_same_point": ...}。
        """
        from datetime import timedelta

        from app.models.entities import Event as EventModel

        effective = (
            "APPROVED",
            "ADJUSTED",
            "AUTO_APPROVED",
            "APPEALING",
            "APPEAL_REJECTED",
        )
        day_ago_7 = now - timedelta(days=7)
        day_ago_30 = now - timedelta(days=30)
        hour_ago_1 = now - timedelta(hours=1)
        # SQLite 的 DateTime(timezone=True) 读回为 naive；比较前统一去时区，
        # 避免 aware/naive 混用导致窗口统计恒为 0 或抛错。
        if day_ago_30.tzinfo is not None:
            day_ago_30 = day_ago_30.replace(tzinfo=None)
            day_ago_7 = day_ago_7.replace(tzinfo=None)
            hour_ago_1 = hour_ago_1.replace(tzinfo=None)
        statement = select(
            func.sum(case((Decision.created_at >= day_ago_30, 1), else_=0)).label(
                "c30"
            ),
            func.sum(case((Decision.created_at >= day_ago_7, 1), else_=0)).label(
                "c7"
            ),
        ).where(Decision.student_id == student_id, Decision.status.in_(effective))
        row = self.session.execute(statement).one()
        count_30d = int(row[0] or 0)
        count_7d = int(row[1] or 0)
        count_1h = 0
        if source_id:
            join_stmt = (
                select(func.count())
                .select_from(Decision)
                .join(EventModel, EventModel.event_id == Decision.event_id)
                .where(
                    Decision.student_id == student_id,
                    Decision.status.in_(effective),
                    Decision.created_at >= hour_ago_1,
                    EventModel.source_id == source_id,
                )
            )
            if current_event_id:
                join_stmt = join_stmt.where(Decision.event_id != current_event_id)
            count_1h = int(self.session.execute(join_stmt).scalar_one())
        _ = current_event_id  # 占位：跨点位语义稳定后可按事件锚点回溯。
        return {"count_30d": count_30d, "count_7d": count_7d,
                "count_1h_same_point": count_1h}

    def claim_pending(self, decision_id: str, **values: object) -> int:
        """条件更新抢占处于 PENDING_REVIEW 的决策（审批并发安全核心）。

        Args:
            decision_id: 决策 ID。
            **values: 待更新列。

        Returns:
            受影响行数（1 抢占成功，0 已被他人抢先）。
        """
        statement = (
            update(Decision)
            .where(Decision.decision_id == decision_id,
                   Decision.status == "PENDING_REVIEW")
            .values(**values)
        )
        result = self.session.execute(statement)
        if isinstance(result, CursorResult):
            return int(result.rowcount or 0)
        return 0

    def update_status_unconditional(
        self, decision_id: str, **values: object
    ) -> int:
        """无条件更新决策状态（申诉/过期等内部流转使用）。"""
        statement = (
            update(Decision).where(Decision.decision_id == decision_id).values(**values)
        )
        result = self.session.execute(statement)
        if isinstance(result, CursorResult):
            return int(result.rowcount or 0)
        return 0

    def count_created_since(self, since: datetime) -> int:
        """统计某时刻后创建的决策数（熔断器单日处罚输入）。"""
        statement = select(func.count()).select_from(Decision).where(
            Decision.created_at >= since
        )
        return int(self.session.execute(statement).scalar_one())

    def max_student_daily_delta(self, student_id: str, since: datetime) -> int:
        """统计某学生单日累计分变最小值（熔断器 single_student_daily 输入）。"""
        statement = select(
            func.coalesce(func.sum(Decision.score_delta), 0)
        ).select_from(Decision).where(
            Decision.student_id == student_id, Decision.created_at >= since
        )
        return int(self.session.execute(statement).scalar_one())


class ReviewLogRepository(BaseRepository[ReviewLog]):
    """审批日志仓储（只增不改）。"""

    model = ReviewLog
    id_field = "id"

    def list_by_decision(self, decision_id: str) -> list[ReviewLog]:
        """读取某决策的全部审批轨迹（按主键升序）。"""
        statement = (
            select(ReviewLog)
            .where(ReviewLog.decision_id == decision_id)
            .order_by(ReviewLog.id.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def dismiss_rate_since(self, since: datetime) -> float:
        """统计某时刻后的驳回率（熔断器 high_dismiss_rate 输入）。"""
        total_stmt = select(func.count()).select_from(ReviewLog).where(
            ReviewLog.created_at >= since,
            ReviewLog.action.in_(("approve", "adjust", "reject")),
        )
        total = int(self.session.execute(total_stmt).scalar_one())
        if total == 0:
            return 0.0
        rejected_stmt = select(func.count()).select_from(ReviewLog).where(
            ReviewLog.created_at >= since, ReviewLog.action == "reject"
        )
        rejected = int(self.session.execute(rejected_stmt).scalar_one())
        return rejected / total


class FeedbackSampleRepository(BaseRepository[FeedbackSample]):
    """回流样本仓储（只增不改）。"""

    model = FeedbackSample
    id_field = "id"

    def list_pending_train(self, *, limit: int = 100) -> list[FeedbackSample]:
        """列出尚未用于训练的样本（按主键升序）。"""
        statement = (
            select(FeedbackSample)
            .where(FeedbackSample.used_for_train == False)  # noqa: E712
            .order_by(FeedbackSample.id.asc())
            .limit(limit)
        )
        return list(self.session.execute(statement).scalars().all())

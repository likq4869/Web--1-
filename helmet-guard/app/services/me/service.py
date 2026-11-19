"""学生端总览服务：首页一屏聚合（只读）。

职责：按登录主体解析学号，聚合积分卡 / 待确认提醒 / 近期记录与申诉计数。
依赖：sqlalchemy 会话、各域仓储、积分领域函数、学生端出入参模型。
边界：只读不写库（无账户时取初始值，不建行）；不做 HTTP 解析；
事务由调用方管理，本模块不提交不回滚。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.domain.scoring import SCORE_INITIAL_BALANCE, level_from_score
from app.models.identity import Student
from app.repositories.appeal import AppealRepository
from app.repositories.decision import DecisionRepository
from app.repositories.scoring import ScoreAccountRepository
from app.repositories.student import StudentRepository
from app.schemas.decision import DecisionListItem
from app.schemas.me import MeOverviewOut


def _decision_summary(row: object) -> dict[str, object]:
    """决策 ORM 行转摘要字典（与学生端记录列表同口径）。"""
    payload = DecisionListItem.model_validate(row)
    return dict(payload.model_dump(mode="json"))


class MeOverviewService:
    """学生端总览服务（绑定单个会话，只读）。"""

    def __init__(self, session: Session) -> None:
        """初始化服务。

        Args:
            session: 数据库会话；本服务只读，不提交不回滚。
        """
        self.session = session

    def get_overview(self, subject: str, role: str) -> MeOverviewOut:
        """聚合学生首页总览。

        Args:
            subject: 登录主体（users.user_id）。
            role: 登录角色；仅 student 允许访问。

        Returns:
            首页一屏聚合载荷。

        Raises:
            NotFoundError: 非学生角色或未绑定学号（隐藏资源存在性）。
        """
        if (role or "") != "student":
            raise NotFoundError("请求的资源不存在")
        student = StudentRepository(self.session).find_by(user_id=subject)
        if student is None:
            fallback = self.session.get(Student, subject)
            if fallback is None:
                raise NotFoundError("请求的资源不存在")
            student = fallback
        student_id = str(student.student_id)
        name = str(student.name)

        account_repo = ScoreAccountRepository(self.session)
        account = account_repo.get_by_id(student_id)
        total_accounts = account_repo.count_accounts()
        if account is not None:
            balance = int(account.balance)
            level = str(account.level or level_from_score(balance))
            streak_days = int(account.streak_days)
            compliance_rate = float(account.compliance_rate)
            higher = account_repo.count_higher_balance(balance)
            rank = higher + 1
            percentile: float | None = None
            if total_accounts > 0:
                percentile = (total_accounts - rank) / total_accounts
        else:
            balance = int(SCORE_INITIAL_BALANCE)
            level = str(level_from_score(balance))
            streak_days = 0
            compliance_rate = 1.0
            rank = None
            percentile = None

        decision_repo = DecisionRepository(self.session)
        pending_count = decision_repo.count_with_filters(
            student_id=student_id, status="PENDING_REVIEW"
        )
        pending_rows = decision_repo.list_with_filters(
            student_id=student_id, status="PENDING_REVIEW", limit=1, offset=0
        )
        pending_latest = _decision_summary(pending_rows[0]) if pending_rows else None

        records_total = decision_repo.count_with_filters(student_id=student_id)
        recent_rows = decision_repo.list_with_filters(
            student_id=student_id, limit=5, offset=0
        )
        recent = [_decision_summary(row) for row in recent_rows]

        appeal_repo = AppealRepository(self.session)
        appeals_total = appeal_repo.count_by_student(student_id)
        appeals_pending = appeal_repo.count_pending_by_student(student_id)

        return MeOverviewOut.model_validate(
            {
                "student_id": student_id,
                "name": name,
                "score": {
                    "balance": balance,
                    "level": level,
                    "streak_days": streak_days,
                    "compliance_rate": compliance_rate,
                    "rank": rank,
                    "total_students": total_accounts,
                    "percentile": percentile,
                },
                "pending": {"count": pending_count, "latest": pending_latest},
                "records": {
                    "total": records_total,
                    "recent": recent,
                    "appeals_total": appeals_total,
                    "appeals_pending": appeals_pending,
                },
            }
        )


__all__ = ["MeOverviewService"]

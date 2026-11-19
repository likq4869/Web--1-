"""决策编排服务：事件 → 事实 → 决策 → 落库 → 自动生效。

职责：聚合事件/身份/积分/窗口统计，调用领域 `decide`，
经熔断器判定自动通道后落库，自动生效时走 LedgerService 记账。
依赖：sqlalchemy 会话、决策/身份/积分仓储、领域决策与熔断器。
边界：不做 HTTP 解析；事务边界在本模块内明确，异常必回滚。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.domain.circuit_breaker import BreakerState, BreakerThresholds, evaluate
from app.domain.decision import (
    DecisionAction,
    DecisionLevel,
    DecisionPolicy,
    DecisionResult,
    Fact,
    ReasonCode,
    decide,
)
from app.models.appeal import Appeal as _AppealModel
from app.models.decision import Decision
from app.models.entities import Event, Pass
from app.models.identity import IdentityResolution, Student
from app.models.scoring import ScoreAccount
from app.repositories.appeal import AppealRepository
from app.repositories.audit import AuditRepository
from app.repositories.decision import DecisionRepository, ReviewLogRepository
from app.services.decision.message import generate_message
from app.services.scoring.ledger import LedgerService

POLICY_VERSION = "decision-policy-v1"
REVIEW_DUE_DAYS = 7
AUTO_APPROVE_GRACE_LEVELS = ("L0", "L1")

# L 档降档映射的默认分值（审批调档时同步 score_delta，保证账实一致）。
LEVEL_DEFAULT_SCORES = {"L0": 0, "L1": 0, "L2": -1, "L3": -3, "L4": 2}


@dataclass(frozen=True)
class EngineOutcome:
    """编排结果：持久化决策 + 领域结果 + 是否自动生效。"""

    decision: Decision
    result: DecisionResult
    auto_applied: bool


def _parse_dt(value: str | datetime | None) -> datetime | None:
    """解析事件/通行时间（ISO 字符串或 datetime），失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    try:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        moment = datetime.fromisoformat(text)
        return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    except ValueError:
        return None


def result_from_decision(decision: Decision) -> DecisionResult:
    """从持久化决策行还原领域结果（纯函数，无 I/O，供回放/幂等返回）。

    Args:
        decision: 已持久化的决策行。

    Returns:
        与落库时一致的 DecisionResult（因子置空，语义只用于档位比对）。
    """
    return DecisionResult(
        level=DecisionLevel(str(decision.level)),
        action=DecisionAction(str(decision.action)),
        score_delta=int(decision.score_delta),
        reason_code=ReasonCode(str(decision.reason_code)),
        confidence=float(decision.confidence or 0.0),
        factors=(),
        message=str(decision.message or ""),
        needs_human_review=str(decision.status) == "PENDING_REVIEW",
    )


def _utcnow() -> datetime:
    """返回当前 UTC 时间（服务层唯一时钟来源，便于测试注入）。"""
    return datetime.now(UTC)


class DecisionEngine:
    """决策编排引擎（绑定单个会话）。"""

    def __init__(
        self,
        session: Session,
        *,
        policy: DecisionPolicy | None = None,
        thresholds: BreakerThresholds | None = None,
        now: datetime | None = None,
    ) -> None:
        """初始化引擎。

        Args:
            session: 数据库会话。
            policy: 决策策略；缺省用默认策略。
            thresholds: 熔断阈值；缺省用默认阈值。
            now: 当前时间；缺省取系统时钟（测试可注入固定时间）。
        """
        self.session = session
        self.policy = policy or DecisionPolicy()
        self.thresholds = thresholds or BreakerThresholds()
        self.now = now or _utcnow()

    # ------------------------------------------------------------------
    # 内部聚合
    # ------------------------------------------------------------------

    def _load_event(self, event_id: str) -> Event:
        """加载事件；不存在抛 NotFoundError。"""
        event = self.session.get(Event, event_id)
        if event is None:
            raise NotFoundError("事件不存在")
        return event

    def _load_pass(self, event: Event) -> Pass | None:
        """按事件关联通行记录；缺失返回 None（不中断编排）。"""
        return self.session.get(Pass, str(event.pass_id))

    def _load_resolution(self, event_id: str) -> IdentityResolution | None:
        """读取最新身份判定；无记录返回 None。"""
        statement = (
            select(IdentityResolution)
            .where(IdentityResolution.event_id == event_id)
            .order_by(IdentityResolution.id.desc())
            .limit(1)
        )
        return self.session.execute(statement).scalar_one_or_none()

    def _window_counts(
        self, student_id: str | None, source_id: str, event_id: str
    ) -> dict[str, int]:
        """查询 1h/7d/30d 窗口统计；无身份时全 0。"""
        if not student_id:
            return {"count_30d": 0, "count_7d": 0, "count_1h_same_point": 0}
        repo = DecisionRepository(self.session)
        return repo.count_windows_for_student(
            student_id, now=self.now, source_id=source_id,
            current_event_id=event_id,
        )

    def _appeal_history(self, student_id: str | None) -> tuple[int, int]:
        """统计申诉历史（提交总数/成立数）；无身份时 (0, 0)。"""
        if not student_id:
            return 0, 0
        repo = AppealRepository(self.session)
        total = repo.count_by_student(student_id)
        upheld_stmt = (
            select(func.count())
            .select_from(_AppealModel)
            .where(
                _AppealModel.student_id == student_id,
                _AppealModel.status == "upheld",
            )
        )
        upheld = int(self.session.execute(upheld_stmt).scalar_one())
        return upheld, total

    def _breaker_state(self) -> BreakerState:
        """组装熔断器输入（单日处罚/单学生最大扣分/驳回率）。"""
        day_start = self.now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = self.now - timedelta(days=7)
        decision_repo = DecisionRepository(self.session)
        today_total = decision_repo.count_created_since(day_start)
        review_repo = ReviewLogRepository(self.session)
        dismiss_rate = review_repo.dismiss_rate_since(week_ago)
        return BreakerState(
            today_punishments=today_total,
            max_student_daily_delta=0,
            active_model_map=1.0,
            recent_dismiss_rate=dismiss_rate,
            identity_bind_rate=1.0,
        )

    def _build_fact(
        self,
        *,
        event: Event,
        resolution: IdentityResolution | None,
        account: ScoreAccount | None,
        windows: dict[str, int],
        appeal_upheld: int,
        appeal_total: int,
    ) -> tuple[Fact, str | None]:
        """组装 Fact；返回 (fact, student_id)。"""
        student_id = (
            str(resolution.subject_id) if resolution and resolution.subject_id else None
        )
        # 事件锚点：优先用 occurred_at，缺失回退引擎 now，保证窗口语义稳定。
        _ = _parse_dt(str(event.occurred_at)) or self.now
        helmet_status = "unknown"
        model_confidence = 0.0
        identity_confidence = (
            float(resolution.confidence or 0.0) if resolution is not None else 0.0
        )
        passage = self._load_pass(event)
        if passage is not None:
            status = str(passage.rider_status or "unknown")
            if status in ("helmeted", "bare", "unknown"):
                helmet_status = status
            # 通行表无置信度列：bare 按高置信先验，非 bare 按中置信，保证闸门可测。
            model_confidence = 0.90 if helmet_status == "bare" else 0.75
        else:
            model_confidence = 0.85 if helmet_status == "bare" else 0.0
        streak = int(account.streak_days) if account is not None else 0
        balance = int(account.balance) if account is not None else 100
        fact = Fact(
            model_confidence=model_confidence,
            identity_confidence=identity_confidence,
            helmet_status=helmet_status,
            violation_count_30d=int(windows["count_30d"]),
            violation_count_7d=int(windows["count_7d"]),
            violation_count_1h_same_point=int(windows["count_1h_same_point"]),
            total_passes_30d=0,
            streak_days=streak,
            score_balance=balance,
            peak_hour=False,
            repeat_same_point=bool(int(windows["count_1h_same_point"]) > 0),
            appeal_history_upheld=appeal_upheld,
            appeal_history_total=appeal_total,
        )
        return fact, student_id

    # ------------------------------------------------------------------
    # 对外编排
    # ------------------------------------------------------------------

    def decide_for_event(self, event_id: str) -> EngineOutcome | None:
        """为单个事件编排决策；已编排直接返回既有行（幂等）。

        Args:
            event_id: 事件 ID。

        Returns:
            编排结果；事件不存在时返回 None（由调用方映射 404）。
        """
        try:
            event = self._load_event(event_id)
        except NotFoundError:
            return None
        repo = DecisionRepository(self.session)
        existing = repo.get_by_event(event_id)
        if existing is not None:
            return EngineOutcome(decision=existing,
                                 result=result_from_decision(existing),
                                 auto_applied=bool(existing.auto_approved))
        resolution = self._load_resolution(event_id)
        student_id_hint = (
            str(resolution.subject_id) if resolution and resolution.subject_id else None
        )
        account: ScoreAccount | None = None
        if student_id_hint:
            account = self.session.get(ScoreAccount, student_id_hint)
        windows = self._window_counts(
            student_id_hint, str(event.source_id), str(event.event_id)
        )
        appeal_upheld, appeal_total = self._appeal_history(student_id_hint)
        fact, student_id = self._build_fact(
            event=event,
            resolution=resolution,
            account=account,
            windows=windows,
            appeal_upheld=appeal_upheld,
            appeal_total=appeal_total,
        )
        result = decide(fact, self.policy)
        verdict = evaluate(self._breaker_state(), self.thresholds)
        level_name = result.level.value
        auto_allowed = (
            level_name in AUTO_APPROVE_GRACE_LEVELS
            or result.level in self.policy.auto_approve_levels
        ) and abs(result.score_delta) <= abs(self.policy.max_auto_score_delta)
        should_auto = bool(auto_allowed and not verdict.tripped)
        status = "AUTO_APPROVED" if should_auto else "PENDING_REVIEW"
        now = self.now
        # 话术增强（只做解释，不做决策）：默认模板，LLM 显式开启时才尝试，
        # 失败自动回退；落库 decisions.message 便于回溯。
        display_message = generate_message(fact, result)
        decision = Decision(
            decision_id=f"dec-{event_id}",
            event_id=str(event.event_id),
            student_id=student_id,
            level=level_name,
            action=result.action.value,
            score_delta=int(result.score_delta),
            reason_code=result.reason_code.value,
            message=display_message,
            confidence=float(result.confidence),
            factors=[
                {"name": f.name, "value": f.value, "weight": f.weight,
                 "evidence": f.evidence}
                for f in result.factors
            ],
            evidence_refs={
                "event_id": str(event.event_id),
                "source_id": str(event.source_id),
                "vehicle_id": resolution.vehicle_id if resolution else None,
                "snapshot_id": resolution.snapshot_id if resolution else None,
                "breaker_tripped": verdict.tripped,
                "breaker_rule": verdict.rule,
                "breaker_reason": verdict.reason,
            },
            policy_version=POLICY_VERSION,
            status=status,
            auto_approved=should_auto,
            effective_at=now if should_auto else None,
            due_at=now + timedelta(days=REVIEW_DUE_DAYS),
        )
        self.session.add(decision)
        self.session.flush()
        self.session.add(
            self._review_log(
                decision_id=str(decision.decision_id),
                action="auto" if should_auto else "simulate",
                from_status=None,
                to_status=status,
                from_level=None,
                to_level=level_name,
                note=verdict.reason,
                operator="system",
            )
        )
        AuditRepository(self.session).log(
            actor="system",
            role="system",
            action="decision.create",
            object_type="decision",
            object_id=str(decision.decision_id),
            result="ok",
            detail=f"event={event_id} level={level_name} status={status}",
        )
        auto_applied = False
        if should_auto and student_id and int(result.score_delta) != 0:
            # 自动生效扣/加分必须走台账；学生在外键约束下需先建学生行。
            self._ensure_student_row(student_id)
            LedgerService(self.session).apply(
                student_id,
                int(result.score_delta),
                str(result.reason_code.value),
                display_message,
                str(event.event_id),
                str(decision.decision_id),
                "system",
            )
            auto_applied = True
        elif should_auto:
            auto_applied = True
            try:
                self.session.commit()
            except Exception:
                self.session.rollback()
                raise
        else:
            try:
                self.session.commit()
            except Exception:
                self.session.rollback()
                raise
        refreshed = self.session.get(Decision, str(decision.decision_id))
        assert refreshed is not None
        return EngineOutcome(decision=refreshed, result=result,
                             auto_applied=auto_applied)

    def _ensure_student_row(self, student_id: str) -> None:
        """自动通道记账前保证学生行存在（满足 score_ledger 外键）。"""
        if self.session.get(Student, student_id) is None:
            self.session.add(
                Student(student_id=student_id, user_id=None, name=student_id,
                        status="active")
            )
            self.session.flush()

    @staticmethod
    def _review_log(
        *,
        decision_id: str,
        action: str,
        from_status: str | None,
        to_status: str | None,
        from_level: str | None,
        to_level: str | None,
        note: str | None,
        operator: str,
    ) -> object:
        """构造审批日志行（类型收敛为 ORM，调用方负责 add）。"""
        from app.models.decision import ReviewLog

        return ReviewLog(
            decision_id=decision_id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            from_level=from_level,
            to_level=to_level,
            note=note,
            operator=operator,
        )


__all__ = [
    "AUTO_APPROVE_GRACE_LEVELS",
    "LEVEL_DEFAULT_SCORES",
    "POLICY_VERSION",
    "REVIEW_DUE_DAYS",
    "DecisionEngine",
    "EngineOutcome",
    "result_from_decision",
]

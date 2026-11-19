"""审批服务：批准/驳回/批量/逾期（条件 UPDATE 并发安全）。

职责：收敛审批状态机、RBAC、降档约束、台账调用与回流闭环。
依赖：sqlalchemy 会话、决策/申诉/学生仓储、台账服务、审计仓储。
边界：不做 HTTP 解析；积分变更一律走 LedgerService，不得直接改 balance。

并发安全：批准/驳回一律用 `DecisionRepository.claim_pending`
（`UPDATE ... WHERE status='PENDING_REVIEW'`），抢占成功行数为 1；
行数为 0 时按最终状态判定幂等（200）或冲突（409）。
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.models.decision import Decision, FeedbackSample, ReviewLog
from app.models.identity import Student
from app.models.scoring import ScoreLedger
from app.repositories.audit import AuditRepository, CounselorAssignmentRepository
from app.repositories.decision import DecisionRepository
from app.services.decision.engine import LEVEL_DEFAULT_SCORES
from app.services.scoring.ledger import LedgerService

# 档位顺序：只允许降档（索引减小），不允许升档。
_LEVEL_ORDER = ("L0", "L1", "L2", "L3", "L4")
_APPROVE_ALL_ROLES = frozenset({"super_admin", "league_officer"})
_TERMINAL_STATUSES = frozenset(
    {"APPROVED", "ADJUSTED", "AUTO_APPROVED", "REJECTED", "EXPIRED",
     "APPEALING", "APPEAL_UPHELD", "APPEAL_REJECTED"}
)


def _level_index(level: str) -> int:
    """返回档位顺序索引；未知档位抛 ValidationError。"""
    try:
        return _LEVEL_ORDER.index(level)
    except ValueError:
        raise ValidationError(f"未知档位：{level}") from None


def _utcnow() -> datetime:
    """返回当前 UTC 时间。"""
    return datetime.now(UTC)


def _as_aware(moment: datetime) -> datetime:
    """SQLite 读回 naive 时间 → 视为 UTC，保证与 aware 时间可比。"""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


class ReviewService:
    """审批服务（绑定单个会话，方法内管理事务）。"""

    def __init__(self, session: Session) -> None:
        """初始化服务。

        Args:
            session: 数据库会话。
        """
        self.session = session

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _get_decision(self, decision_id: str) -> Decision:
        """加载决策；不存在抛 NotFoundError（避免枚举）。"""
        decision = self.session.get(Decision, decision_id)
        if decision is None:
            raise NotFoundError("请求的资源不存在")
        return decision

    def _check_approve_role(
        self, role: str, subject: str, decision: Decision
    ) -> None:
        """审批 RBAC：L3 仅团委/超管；counselor 仅 L1/L2 且限本班。

        Args:
            role: 调用方角色。
            subject: 调用方用户 ID（counselor 范围校验用）。
            decision: 目标决策。

        Raises:
            PermissionDeniedError: 角色无权（L3 越权 → 403）。
            NotFoundError: 越出本班范围（404，避免存在性泄露）。
        """
        level = str(decision.level)
        if level == "L3":
            if role not in _APPROVE_ALL_ROLES:
                raise PermissionDeniedError("L3 决策需团委或超级管理员审批")
            return
        if role in _APPROVE_ALL_ROLES:
            return
        if role == "counselor":
            if level not in ("L1", "L2"):
                raise PermissionDeniedError("辅导员仅可处理 L1/L2 决策")
            student_id = str(decision.student_id) if decision.student_id else ""
            if not student_id:
                raise NotFoundError("请求的资源不存在")
            student = self.session.get(Student, student_id)
            if student is None:
                raise NotFoundError("请求的资源不存在")
            classes = CounselorAssignmentRepository(self.session).list_classes(subject)
            if not classes or str(student.class_name) not in classes:
                raise NotFoundError("请求的资源不存在")
            return
        if role == "security_officer":
            if level not in ("L1", "L2"):
                raise PermissionDeniedError("你没有审批该决策的权限")
            return
        raise PermissionDeniedError("你没有审批该决策的权限")

    def _check_reject_role(self, role: str, subject: str, decision: Decision) -> None:
        """驳回 RBAC：与批准一致（L3 仅团委/超管）。"""
        self._check_approve_role(role, subject, decision)

    def _resolve_target_level(
        self, decision: Decision, level: str | None
    ) -> tuple[str, int, str | None]:
        """解析目标档位与分值；校验只降不升。

        Returns:
            (目标档位, 目标分值, 原档位) 三元组；未调档时原档位为 None。
        """
        current = str(decision.level)
        if level is None or level == current:
            return current, int(decision.score_delta), None
        if level not in _LEVEL_ORDER:
            raise ValidationError(f"未知档位：{level}")
        if _level_index(level) > _level_index(current):
            raise ValidationError(f"档位只降不升：{current} 不能升到 {level}")
        return level, int(LEVEL_DEFAULT_SCORES.get(level, 0)), current

    def _write_logs(
        self,
        *,
        decision_id: str,
        action: str,
        from_status: str | None,
        to_status: str | None,
        from_level: str | None,
        to_level: str | None,
        note: str | None,
        operator: str,
        role: str,
    ) -> None:
        """写入审批轨迹 + 审计（与调用方同事务，flush 不提交）。"""
        self.session.add(
            ReviewLog(
                decision_id=decision_id,
                action=action,
                from_status=from_status,
                to_status=to_status,
                from_level=from_level,
                to_level=to_level,
                note=note,
                operator=operator,
            )
        )
        AuditRepository(self.session).log(
            actor=operator,
            role=role,
            action=f"decision.{action}",
            object_type="decision",
            object_id=decision_id,
            result="ok",
            detail=f"{from_status}->{to_status} {from_level}->{to_level} "
            f"{(note or '')[:60]}",
        )
        self.session.flush()

    def _ensure_student_row(self, student_id: str) -> None:
        """记账前保证学生行存在（满足 score_ledger 外键）。"""
        if self.session.get(Student, student_id) is None:
            self.session.add(
                Student(student_id=student_id, user_id=None, name=student_id,
                        status="active")
            )
            self.session.flush()

    def _apply_ledger_for_decision(
        self, decision: Decision, operator: str
    ) -> None:
        """批准生效时走台账记账（分值非 0 且有身份时）。"""
        delta = int(decision.score_delta)
        student_id = str(decision.student_id) if decision.student_id else ""
        if delta == 0 or not student_id:
            return
        self._ensure_student_row(student_id)
        LedgerService(self.session).apply(
            student_id,
            delta,
            str(decision.reason_code),
            str(decision.message) if decision.message else None,
            str(decision.event_id),
            str(decision.decision_id),
            operator,
        )

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def approve(
        self,
        decision_id: str,
        operator: str,
        role: str,
        level: str | None = None,
        note: str | None = None,
    ) -> Decision:
        """批准决策（可降档）；条件 UPDATE 保证并发安全。

        Args:
            decision_id: 决策 ID。
            operator: 操作人。
            role: 操作人角色（RBAC 用）。
            level: 目标档位；为 None 时保持原档。
            note: 审批备注。

        Returns:
            生效后的决策（幂等返回同一行）。

        Raises:
            NotFoundError: 决策不存在或越出本班范围。
            PermissionDeniedError: 角色无权。
            ValidationError: 升档等非法输入。
            ConflictError: 已终态（驳回/申诉中等）后再批准。
        """
        existing = self._get_decision(decision_id)
        self._check_approve_role(role, operator, existing)
        target_level, target_score, original_level = self._resolve_target_level(
            existing, level
        )
        to_status = "ADJUSTED" if original_level is not None else "APPROVED"
        now = _utcnow()
        repo = DecisionRepository(self.session)
        # 幂等 fast-path：已是目标终态且档位一致 → 直接返回。
        if str(existing.status) in _TERMINAL_STATUSES - {"REJECTED", "EXPIRED"} and str(
            existing.status
        ) in (to_status, "AUTO_APPROVED") and str(existing.level) == target_level:
            return existing
        affected = repo.claim_pending(
            decision_id,
            status=to_status,
            level=target_level,
            score_delta=target_score,
            original_level=original_level or existing.original_level,
            reviewed_by=operator,
            reviewed_at=now,
            review_note=note,
            effective_at=now,
            updated_at=now,
        )
        if affected == 1:
            self.session.flush()
            refreshed = self._get_decision(decision_id)
            action = "adjust" if original_level is not None else "approve"
            self._write_logs(
                decision_id=decision_id,
                action=action,
                from_status="PENDING_REVIEW",
                to_status=to_status,
                from_level=str(existing.level),
                to_level=target_level,
                note=note,
                operator=operator,
                role=role,
            )
            self._apply_ledger_for_decision(refreshed, operator)
            # 台账 apply 内部已 commit（含日志）；无台账时此处提交。
            if not self.session.in_transaction():
                pass
            else:
                try:
                    self.session.commit()
                except Exception:
                    self.session.rollback()
                    raise
            return self._get_decision(decision_id)
        # 抢占失败：按最终状态判定幂等或冲突。
        self.session.rollback()
        final = self._get_decision(decision_id)
        if str(final.status) in (to_status, "AUTO_APPROVED") and str(
            final.level
        ) == target_level:
            return final
        raise ConflictError("该决策已被他人处理，请刷新后重试")

    def reject(
        self,
        decision_id: str,
        operator: str,
        role: str,
        reason: str,
    ) -> Decision:
        """驳回决策；同步写入回流样本（模型迭代闭环）。

        Args:
            decision_id: 决策 ID。
            operator: 操作人。
            role: 操作人角色。
            reason: 驳回理由（必填）。

        Raises:
            ValidationError: 理由为空。
            NotFoundError / PermissionDeniedError / ConflictError: 同 approve。
        """
        if not reason or not reason.strip():
            raise ValidationError("驳回理由必填")
        existing = self._get_decision(decision_id)
        self._check_reject_role(role, operator, existing)
        now = _utcnow()
        repo = DecisionRepository(self.session)
        if str(existing.status) == "REJECTED":
            return existing
        affected = repo.claim_pending(
            decision_id,
            status="REJECTED",
            reviewed_by=operator,
            reviewed_at=now,
            review_note=reason.strip(),
            updated_at=now,
        )
        if affected != 1:
            self.session.rollback()
            final = self._get_decision(decision_id)
            if str(final.status) == "REJECTED":
                return final
            raise ConflictError("该决策已被他人处理，请刷新后重试")
        self.session.flush()
        self._write_logs(
            decision_id=decision_id,
            action="reject",
            from_status="PENDING_REVIEW",
            to_status="REJECTED",
            from_level=str(existing.level),
            to_level=str(existing.level),
            note=reason.strip(),
            operator=operator,
            role=role,
        )
        self.session.add(
            FeedbackSample(
                event_id=str(existing.event_id),
                decision_id=str(existing.decision_id),
                snapshot_id=None,
                image_path=None,
                label=str(existing.level),
                model_pred=str(existing.level),
                original_label=str(existing.level),
                corrected_label="L0",
                reason=reason.strip()[:500],
                source="review_reject",
                used_for_train=False,
            )
        )
        self.session.flush()
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return self._get_decision(decision_id)

    def batch_approve(
        self,
        decision_ids: list[str],
        operator: str,
        role: str,
        note: str | None = None,
    ) -> list[dict[str, object]]:
        """批量批准；单条失败不影响整批，返回逐条结果。

        Args:
            decision_ids: 决策 ID 列表。
            operator: 操作人。
            role: 操作人角色。
            note: 审批备注（写入每条审批轨迹）。

        Returns:
            每条 `{"decision_id": ..., "ok": bool, "status": ..., "error": ...}`。
        """
        results: list[dict[str, object]] = []
        for decision_id in decision_ids:
            try:
                decided = self.approve(decision_id, operator, role, note=note)
                results.append(
                    {"decision_id": decision_id, "ok": True,
                     "status": str(decided.status), "error": None}
                )
            except Exception as exc:  # noqa: BLE001  # 批量语义：逐条收敛错误。
                with contextlib.suppress(Exception):
                    self.session.rollback()
                results.append(
                    {"decision_id": decision_id, "ok": False,
                     "status": None, "error": str(exc)}
                )
        return results

    def expire_overdue(
        self, now: datetime | None = None, operator: str = "system",
        role: str = "system"
    ) -> dict[str, Literal["auto_approved", "escalated", "expired"] | int]:
        """逾期处理：L1/L2 自动通过（记账），L3 升级通知，L0 直接过期。

        Args:
            now: 当前时间；缺省取系统时钟。
            operator: 操作人（默认 system）。
            role: 操作人角色（审计用）。

        Returns:
            `{"auto_approved": n, "escalated": n, "expired": n}` 计数。
        """
        moment = now or _utcnow()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        repo = DecisionRepository(self.session)
        overdue = repo.list_with_filters(status="PENDING_REVIEW", limit=1000, offset=0)
        overdue = [
            d for d in overdue
            if d.due_at is not None and _as_aware(d.due_at) < moment
        ]
        auto_approved = 0
        escalated = 0
        expired = 0
        for decision in overdue:
            level = str(decision.level)
            decision_id = str(decision.decision_id)
            if level in ("L1", "L2"):
                affected = repo.claim_pending(
                    decision_id,
                    status="AUTO_APPROVED",
                    auto_approved=True,
                    reviewed_by=operator,
                    reviewed_at=moment,
                    review_note="逾期自动通过",
                    effective_at=moment,
                    updated_at=moment,
                )
                if affected == 1:
                    self.session.flush()
                    self._write_logs(
                        decision_id=decision_id,
                        action="auto",
                        from_status="PENDING_REVIEW",
                        to_status="AUTO_APPROVED",
                        from_level=level,
                        to_level=level,
                        note="逾期自动通过",
                        operator=operator,
                        role=role,
                    )
                    refreshed = self._get_decision(decision_id)
                    self._apply_ledger_for_decision(refreshed, operator)
                    if self.session.in_transaction():
                        try:
                            self.session.commit()
                        except Exception:
                            self.session.rollback()
                            raise
                    auto_approved += 1
                else:
                    with contextlib.suppress(Exception):
                        self.session.rollback()
            elif level == "L3":
                # L3 逾期不自动生效：写 escalate 轨迹 + 审计，状态保持待审。
                try:
                    self._write_logs(
                        decision_id=decision_id,
                        action="escalate",
                        from_status="PENDING_REVIEW",
                        to_status="PENDING_REVIEW",
                        from_level=level,
                        to_level=level,
                        note="L3 逾期未审，已升级通知",
                        operator=operator,
                        role=role,
                    )
                    self.session.commit()
                except Exception:
                    self.session.rollback()
                    raise
                escalated += 1
            else:
                affected = repo.claim_pending(
                    decision_id,
                    status="EXPIRED",
                    reviewed_by=operator,
                    reviewed_at=moment,
                    review_note="逾期自动失效",
                    updated_at=moment,
                )
                if affected == 1:
                    self.session.flush()
                    self._write_logs(
                        decision_id=decision_id,
                        action="expire",
                        from_status="PENDING_REVIEW",
                        to_status="EXPIRED",
                        from_level=level,
                        to_level=level,
                        note="逾期自动失效",
                        operator=operator,
                        role=role,
                    )
                    try:
                        self.session.commit()
                    except Exception:
                        self.session.rollback()
                        raise
                    expired += 1
                else:
                    with contextlib.suppress(Exception):
                        self.session.rollback()
        return {"auto_approved": auto_approved, "escalated": escalated,
                "expired": expired}

    def revert_for_appeal_upheld(self, decision: Decision, operator: str) -> None:
        """申诉成立时冲正：仅内部调用（调用方负责事务提交）。

        查找该决策的记账流水并反向冲正；无流水（0 分提醒）直接跳过。
        """
        student_id = str(decision.student_id) if decision.student_id else ""
        if not student_id or int(decision.score_delta) == 0:
            return
        statement_ledger = (
            select(ScoreLedger)
            .where(ScoreLedger.decision_id == str(decision.decision_id))
            .order_by(ScoreLedger.ledger_id.desc())
            .limit(1)
        )
        original = self.session.execute(statement_ledger).scalar_one_or_none()
        if original is None:
            return
        LedgerService(self.session).revert(
            int(original.ledger_id),
            f"申诉成立冲正 decision={decision.decision_id}",
            operator=operator,
        )


__all__ = ["ReviewService"]

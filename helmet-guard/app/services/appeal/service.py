"""申诉服务：学生提交、管理员裁决（成立冲正 + 回流闭环）。

职责：收敛申诉状态机、本人校验、裁决权限、台账冲正与回流写入。
依赖：sqlalchemy 会话、申诉/决策仓储、审批服务、台账服务、审计仓储。
边界：不做 HTTP 解析；积分变更一律走 LedgerService（经 ReviewService
冲正路径），不得直接改 balance。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.models.appeal import Appeal
from app.models.decision import Decision, FeedbackSample, ReviewLog
from app.repositories.appeal import AppealRepository
from app.repositories.audit import AuditRepository
from app.repositories.decision import DecisionRepository

_RESOLVE_ROLES = frozenset({"super_admin", "league_officer"})
# 允许发起申诉的决策终态：已生效（批准/调档/自动通过）与驳回后申诉。
_APPEALABLE_STATUSES = frozenset(
    {"APPROVED", "ADJUSTED", "AUTO_APPROVED", "REJECTED", "APPEAL_REJECTED"}
)


def _utcnow() -> datetime:
    """返回当前 UTC 时间。"""
    return datetime.now(UTC)


class AppealService:
    """申诉服务（绑定单个会话）。"""

    def __init__(self, session: Session) -> None:
        """初始化服务。

        Args:
            session: 数据库会话。
        """
        self.session = session

    def submit(
        self,
        decision_id: str,
        student_id: str,
        reason: str,
        attachments: list[str] | None = None,
    ) -> Appeal:
        """学生提交申诉（本人校验 + 一事一申诉幂等）。

        Args:
            decision_id: 决策 ID。
            student_id: 申诉学生学号（必须与决策归属一致）。
            reason: 申诉理由（必填，≤500 字）。
            attachments: 附件引用列表。

        Returns:
            申诉记录（重复提交返回既有行）。

        Raises:
            ValidationError: 理由为空或过长。
            NotFoundError: 决策不存在（避免枚举，归属不符也按不存在处理）。
            ConflictError: 决策状态不可申诉或已有终态申诉。
        """
        if not reason or not reason.strip():
            raise ValidationError("申诉理由必填")
        if len(reason.strip()) > 500:
            raise ValidationError("申诉理由不得超过 500 字")
        decision = self.session.get(Decision, decision_id)
        if decision is None:
            raise NotFoundError("请求的资源不存在")
        owner = str(decision.student_id) if decision.student_id else ""
        if not owner or owner != student_id:
            # 归属不符按不存在处理，避免枚举他人决策。
            raise NotFoundError("请求的资源不存在")
        if str(decision.status) not in _APPEALABLE_STATUSES:
            raise ConflictError("该决策当前状态不可申诉")
        # 一事一申诉：已有未终结申诉直接幂等返回。
        existing = AppealRepository(self.session).get_by_decision(decision_id)
        if existing is not None and str(existing.status) == "pending":
            return existing
        if existing is not None and str(existing.status) in ("upheld", "rejected"):
            raise ConflictError("该决策已有申诉结论，请勿重复提交")
        appeal = Appeal(
            appeal_id=f"apl-{decision_id}-{uuid.uuid4().hex[:8]}",
            decision_id=decision_id,
            student_id=student_id,
            reason=reason.strip(),
            attachments=list(attachments or []),
            status="pending",
        )
        self.session.add(appeal)
        self.session.flush()
        # 决策进入申诉中（无条件更新，内部流转）。
        DecisionRepository(self.session).update_status_unconditional(
            decision_id, status="APPEALING", updated_at=_utcnow()
        )
        self.session.flush()
        self.session.add(
            ReviewLog(
                decision_id=decision_id,
                action="appeal",
                from_status=str(decision.status),
                to_status="APPEALING",
                from_level=str(decision.level),
                to_level=str(decision.level),
                note=f"学生申诉 appeal={appeal.appeal_id}",
                operator=student_id,
            )
        )
        AuditRepository(self.session).log(
            actor=student_id,
            role="student",
            action="appeal.submit",
            object_type="appeal",
            object_id=str(appeal.appeal_id),
            result="ok",
            detail=f"decision={decision_id}",
        )
        self.session.flush()
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        refreshed = self.session.get(Appeal, str(appeal.appeal_id))
        assert refreshed is not None
        return refreshed

    def resolve(
        self, appeal_id: str, handler: str, role: str, upheld: bool, note: str = ""
    ) -> Appeal:
        """管理员裁决申诉（成立冲正 + 回流，驳回只改状态）。

        Args:
            appeal_id: 申诉 ID。
            handler: 处理人。
            role: 处理人角色（仅 super_admin / league_officer）。
            upheld: 是否成立。
            note: 处理说明。

        Returns:
            裁决后的申诉记录。

        Raises:
            PermissionDeniedError: 角色无权。
            NotFoundError: 申诉或决策不存在。
            ConflictError: 重复裁决。
        """
        if role not in _RESOLVE_ROLES:
            raise PermissionDeniedError("申诉裁决需团委或超级管理员处理")
        appeal = self.session.get(Appeal, appeal_id)
        if appeal is None:
            raise NotFoundError("请求的资源不存在")
        if str(appeal.status) in ("upheld", "rejected"):
            return appeal
        if str(appeal.status) != "pending":
            raise ConflictError("该申诉已被处理，请刷新后重试")
        decision = self.session.get(Decision, str(appeal.decision_id))
        if decision is None:
            raise NotFoundError("请求的资源不存在")
        now = _utcnow()
        to_status = "APPEAL_UPHELD" if upheld else "APPEAL_REJECTED"
        appeal.status = to_status.replace("APPEAL_", "").lower()
        appeal.handler = handler
        appeal.handle_note = note[:500] if note else None
        appeal.resolved_at = now
        appeal.updated_at = now
        if upheld:
            # 成立：冲正台账（有流水时）+ 决策改 APPEAL_UPHELD + 回流样本。
            from app.services.decision.review import ReviewService

            ReviewService(self.session).revert_for_appeal_upheld(decision, handler)
            DecisionRepository(self.session).update_status_unconditional(
                str(decision.decision_id),
                status="APPEAL_UPHELD",
                reviewed_by=handler,
                reviewed_at=now,
                review_note=(note[:200] if note else "申诉成立"),
                updated_at=now,
            )
            self.session.add(
                FeedbackSample(
                    event_id=str(decision.event_id),
                    decision_id=str(decision.decision_id),
                    appeal_id=str(appeal.appeal_id),
                    snapshot_id=None,
                    image_path=None,
                    label=str(decision.level),
                    model_pred=str(decision.level),
                    original_label=str(decision.level),
                    corrected_label="L0",
                    reason=(note.strip()[:500] if note and note.strip() else "申诉成立"),
                    source="appeal_upheld",
                    used_for_train=False,
                )
            )
        else:
            DecisionRepository(self.session).update_status_unconditional(
                str(decision.decision_id),
                status="APPEAL_REJECTED",
                reviewed_by=handler,
                reviewed_at=now,
                review_note=(note[:200] if note else "申诉不成立"),
                updated_at=now,
            )
        self.session.flush()
        self.session.add(
            ReviewLog(
                decision_id=str(decision.decision_id),
                action="appeal",
                from_status="APPEALING",
                to_status=to_status,
                from_level=str(decision.level),
                to_level=str(decision.level),
                note=(note[:200] if note else ("申诉成立" if upheld else "申诉不成立")),
                operator=handler,
            )
        )
        AuditRepository(self.session).log(
            actor=handler,
            role=role,
            action="appeal.resolve",
            object_type="appeal",
            object_id=str(appeal.appeal_id),
            result="ok",
            detail=f"upheld={int(upheld)} decision={appeal.decision_id}",
        )
        self.session.flush()
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        refreshed = self.session.get(Appeal, appeal_id)
        assert refreshed is not None
        return refreshed


__all__ = ["AppealService"]

"""策略配置管理服务：读写当前策略、熔断阈值与模拟推演。

职责：收敛策略域的读/写/模拟，RBAC 越权统一 404，写操作记审计。
依赖：sqlalchemy 会话、领域 decision / circuit_breaker / decision_rules、审计仓储。
边界：策略当前值保存在进程内存（单实例演示），写操作仅记审计后提交；
模拟只推演不写库、不调台账。
"""

from __future__ import annotations

import dataclasses
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.domain.circuit_breaker import BreakerState, BreakerThresholds
from app.domain.circuit_breaker import evaluate as _evaluate_breaker
from app.domain.decision import DecisionPolicy, Fact, replay_decision
from app.domain.decision import decide as _decide
from app.domain.decision_rules import RULE_REGISTRY
from app.repositories.audit import AuditRepository
from app.repositories.decision import DecisionRepository
from app.schemas.policy import BreakerThresholdsBody, DecisionPolicyBody
from app.services.decision.engine import POLICY_VERSION, result_from_decision

READ_ROLES: frozenset[str] = frozenset(
    {"super_admin", "league_officer", "counselor", "security_officer"}
)
WRITE_ROLES: frozenset[str] = frozenset({"super_admin", "league_officer", "admin"})

_CURRENT_POLICY: DecisionPolicy = DecisionPolicy()
_CURRENT_THRESHOLDS: BreakerThresholds = BreakerThresholds()
_VERSION_COUNTER = 1
_VERSION = POLICY_VERSION

_ALLOWED_POLICY_IDS = frozenset({"default", "v1"})


def _require_read(role: str) -> None:
    """读权限：非管理角色统一 404。"""
    if role not in READ_ROLES:
        raise NotFoundError("请求的资源不存在")


def _require_write(role: str) -> None:
    """写权限：仅策略管理员；其余一律 404。"""
    if role not in WRITE_ROLES:
        raise NotFoundError("请求的资源不存在")


def _require_policy_id(policy_id: str) -> None:
    """策略 ID 白名单：仅 default。"""
    if policy_id not in _ALLOWED_POLICY_IDS:
        raise NotFoundError("请求的资源不存在")


def _policy_to_dict(policy: DecisionPolicy) -> dict[str, Any]:
    """策略 dataclass 转可序列化字典（只含可调字段）。"""
    return {
        "min_model_confidence": float(policy.min_model_confidence),
        "min_identity_confidence": float(policy.min_identity_confidence),
        "l1_score": int(policy.l1_score),
        "l2_score": int(policy.l2_score),
        "l3_score": int(policy.l3_score),
        "award_score": int(policy.award_score),
        "l3_violation_30d": int(policy.l3_violation_30d),
        "l3_violation_7d": int(policy.l3_violation_7d),
        "l3_same_point_1h": int(policy.l3_same_point_1h),
        "l2_violation_30d": int(policy.l2_violation_30d),
        "l2_violation_7d": int(policy.l2_violation_7d),
        "streak_award_days": int(policy.streak_award_days),
        "confidence_model_weight": float(policy.confidence_model_weight),
        "confidence_identity_weight": float(policy.confidence_identity_weight),
        "max_auto_score_delta": int(policy.max_auto_score_delta),
    }


def _thresholds_to_dict(thresholds: BreakerThresholds) -> dict[str, Any]:
    """熔断阈值转可序列化字典。"""
    return {
        "max_daily_punishments": int(thresholds.max_daily_punishments),
        "min_student_daily_delta": int(thresholds.min_student_daily_delta),
        "min_model_map": float(thresholds.min_model_map),
        "max_dismiss_rate": float(thresholds.max_dismiss_rate),
        "min_identity_bind_rate": float(thresholds.min_identity_bind_rate),
    }


def _apply_policy_overrides(
    base: DecisionPolicy, body: DecisionPolicyBody | None
) -> DecisionPolicy:
    """把更新体非 None 字段合并到策略副本。"""
    if body is None:
        return base
    values = body.model_dump(exclude_none=True)
    if not values:
        return base
    try:
        return dataclasses.replace(base, **values)
    except TypeError as exc:
        raise ValidationError(str(exc)) from exc


def _apply_threshold_overrides(
    base: BreakerThresholds, body: BreakerThresholdsBody | None
) -> BreakerThresholds:
    """把更新体非 None 字段合并到阈值副本。"""
    if body is None:
        return base
    values = body.model_dump(exclude_none=True)
    if not values:
        return base
    try:
        return dataclasses.replace(base, **values)
    except TypeError as exc:
        raise ValidationError(str(exc)) from exc


def _validate_policy(policy: DecisionPolicy) -> None:
    """用一次最小决策触发领域校验；非法直接转 422。"""
    probe = Fact(model_confidence=0.9, identity_confidence=0.9, helmet_status="bare")
    try:
        _decide(probe, policy)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def _validate_thresholds(thresholds: BreakerThresholds) -> None:
    """阈值合法性校验；非法转 422。"""
    try:
        _evaluate_breaker(BreakerState(), thresholds)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


class PolicyAdminService:
    """策略配置服务（绑定单个会话，审计写入走事务）。"""

    def __init__(self, session: Session) -> None:
        """初始化服务。

        Args:
            session: 数据库会话（审计写入用）。
        """
        self.session = session

    def get_policy(self, role: str, policy_id: str) -> dict[str, Any]:
        """读取策略当前值（含版本、阈值、规则注册表摘要）。

        Args:
            role: 调用方角色。
            policy_id: 策略 ID（仅 default）。

        Returns:
            策略载荷字典。
        """
        _require_read(role)
        _require_policy_id(policy_id)
        return {
            "policy_id": policy_id,
            "version": _VERSION,
            "policy": _policy_to_dict(_CURRENT_POLICY),
            "thresholds": _thresholds_to_dict(_CURRENT_THRESHOLDS),
            "rules": [{"name": rule.name, "title": rule.title} for rule in RULE_REGISTRY],
        }

    def update_policy(
        self,
        role: str,
        subject: str,
        policy_id: str,
        policy_body: DecisionPolicyBody | None,
        thresholds_body: BreakerThresholdsBody | None,
    ) -> dict[str, Any]:
        """更新策略与阈值（结构化字段，非法转 422，写审计）。

        Args:
            role: 调用方角色。
            subject: 操作人。
            policy_id: 策略 ID。
            policy_body: 策略更新体。
            thresholds_body: 阈值更新体。

        Returns:
            更新后的策略载荷。
        """
        _require_write(role)
        _require_policy_id(policy_id)
        global _CURRENT_POLICY, _CURRENT_THRESHOLDS, _VERSION, _VERSION_COUNTER
        candidate_policy = _apply_policy_overrides(_CURRENT_POLICY, policy_body)
        candidate_thresholds = _apply_threshold_overrides(_CURRENT_THRESHOLDS, thresholds_body)
        _validate_policy(candidate_policy)
        _validate_thresholds(candidate_thresholds)
        try:
            _CURRENT_POLICY = candidate_policy
            _CURRENT_THRESHOLDS = candidate_thresholds
            _VERSION_COUNTER += 1
            _VERSION = f"decision-policy-v{_VERSION_COUNTER}"
            AuditRepository(self.session).log(
                actor=subject,
                role=role,
                action="policy.update",
                object_type="policy",
                object_id=policy_id,
                result="ok",
                detail=f"policy={policy_id} version={_VERSION}",
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return {
            "policy_id": policy_id,
            "version": _VERSION,
            "policy": _policy_to_dict(_CURRENT_POLICY),
            "thresholds": _thresholds_to_dict(_CURRENT_THRESHOLDS),
            "rules": [{"name": rule.name, "title": rule.title} for rule in RULE_REGISTRY],
        }

    def simulate(
        self,
        role: str,
        policy_id: str,
        *,
        policy_body: DecisionPolicyBody | None = None,
        thresholds_body: BreakerThresholdsBody | None = None,
        model_confidence: float = 0.85,
        identity_confidence: float = 0.85,
        violation_count_30d: int = 0,
        violation_count_7d: int = 0,
        violation_count_1h_same_point: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        """策略模拟：用候选策略重放历史决策，只推演不写库。

        Args:
            role: 调用方角色。
            policy_id: 策略 ID。
            policy_body: 候选策略覆盖。
            thresholds_body: 候选阈值覆盖（仅校验，不参与重放）。
            model_confidence: 假设事实模型置信度。
            identity_confidence: 假设事实身份置信度。
            violation_count_30d: 假设 30 天违规数。
            violation_count_7d: 假设 7 天违规数。
            violation_count_1h_same_point: 假设同点位 1 小时违规数。
            limit: 重放条数上限。

        Returns:
            ``{"policy_id", "simulated", "changed", "diffs", "note"}``。
        """
        _require_read(role)
        _require_policy_id(policy_id)
        candidate_policy = _apply_policy_overrides(_CURRENT_POLICY, policy_body)
        candidate_thresholds = _apply_threshold_overrides(_CURRENT_THRESHOLDS, thresholds_body)
        _validate_policy(candidate_policy)
        _validate_thresholds(candidate_thresholds)
        fact = Fact(
            model_confidence=float(model_confidence),
            identity_confidence=float(identity_confidence),
            helmet_status="bare",
            violation_count_30d=int(violation_count_30d),
            violation_count_7d=int(violation_count_7d),
            violation_count_1h_same_point=int(violation_count_1h_same_point),
        )
        repo = DecisionRepository(self.session)
        rows = repo.list_with_filters(limit=max(1, min(int(limit), 100)), offset=0)
        diffs: list[dict[str, Any]] = []
        for row in rows:
            snapshot = result_from_decision(row)
            diff = replay_decision(snapshot, fact, candidate_policy)
            diffs.append(
                {
                    "decision_id": str(row.decision_id),
                    "changed": bool(diff.changed),
                    "diff_reason": str(diff.diff_reason),
                    "original_level": str(diff.original.level.value),
                    "replayed_level": str(diff.replayed.level.value),
                }
            )
        changed = sum(1 for item in diffs if item["changed"])
        return {
            "policy_id": policy_id,
            "simulated": len(diffs),
            "changed": changed,
            "diffs": diffs,
            "note": "此操作仅推演，不会真实生效",
        }


__all__ = [
    "PolicyAdminService",
    "READ_ROLES",
    "WRITE_ROLES",
]

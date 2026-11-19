"""积分管理服务：账户/台账查询、规则更新与试算。

职责：收敛积分域管理端的 RBAC、分页与排序白名单、审计写入、DSL 校验。
依赖：sqlalchemy 会话、积分仓储、积分领域函数、审计仓储。
边界：不做 HTTP 解析与响应序列化；事务由本模块内收敛（成功提交/失败回滚）；
流水只读不写（记账统一走 LedgerService，避免旁路改余额）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.domain.scoring import RuleSpec, apply_rules, evaluate_condition
from app.models.identity import Student
from app.models.scoring import ScoreRule
from app.repositories.audit import AuditRepository
from app.repositories.scoring import (
    ScoreAccountRepository,
    ScoreLedgerRepository,
    ScoreRuleRepository,
)
from app.schemas.scoring import RuleUpdateBody

# 管理端读允许的角色；学生端角色一律视为无资源（404）。
READ_ROLES: frozenset[str] = frozenset(
    {
        "super_admin",
        "league_officer",
        "counselor",
        "security_officer",
        "auditor",
        "admin",
        "reviewer",
        "observer",
    }
)
# 规则写允许的角色（可调分值，影响生效口径）。
WRITE_ROLES: frozenset[str] = frozenset({"super_admin", "league_officer", "admin"})

PAGE_SIZE_MAX = 100


def _require_read(role: str) -> None:
    """读权限校验：非管理角色统一 404（隐藏资源存在性）。"""
    if role not in READ_ROLES:
        raise NotFoundError("请求的资源不存在")


def _require_write(role: str) -> None:
    """写权限校验：仅规则管理员；其余一律 404。"""
    if role not in WRITE_ROLES:
        raise NotFoundError("请求的资源不存在")


def _clamp_page(page: int, page_size: int) -> tuple[int, int]:
    """钳制分页参数。"""
    return max(1, page), min(max(1, page_size), PAGE_SIZE_MAX)


def _parse_dt(value: str | None) -> datetime | None:
    """解析 ISO 时间过滤参数；非法返回 None（由调用方忽略）。"""
    if not value:
        return None
    try:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        moment = datetime.fromisoformat(text)
        return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    except ValueError:
        return None


def _rule_to_spec(row: ScoreRule) -> RuleSpec:
    """把 ORM 规则行投影为领域层 RuleSpec（纯数据，便于复用求值器）。"""
    condition = row.condition_json
    if not isinstance(condition, dict):
        raise ValidationError(f"规则 {row.rule_id} 的 condition_json 非法")
    return RuleSpec(
        rule_id=str(row.rule_id),
        rule_type=str(row.rule_type),
        name=str(row.name),
        condition=condition,
        score_change=int(row.score_change),
        priority=int(row.priority),
        enabled=bool(row.enabled),
    )


class ScoringAdminService:
    """积分管理服务（绑定单个会话）。"""

    def __init__(self, session: Session) -> None:
        """初始化服务。

        Args:
            session: 数据库会话。
        """
        self.session = session

    # ------------------------------------------------------------------
    # 账户与台账（只读）
    # ------------------------------------------------------------------

    def list_accounts(
        self,
        role: str,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页列出积分账户（附学生姓名，便于台账联查）。

        Args:
            role: 调用方角色。
            page: 页码（从 1 起）。
            page_size: 每页条数。
            keyword: 模糊匹配学号。

        Returns:
            (账户字典列表, 总数) 二元组。
        """
        _require_read(role)
        safe_page, safe_size = _clamp_page(page, page_size)
        repo = ScoreAccountRepository(self.session)
        rows = repo.list_accounts(
            keyword=keyword,
            limit=safe_size,
            offset=(safe_page - 1) * safe_size,
        )
        total = repo.count_accounts(keyword=keyword)
        student_ids = [str(row.student_id) for row in rows]
        names: dict[str, str] = {}
        for student_id in student_ids:
            student = self.session.get(Student, student_id)
            if student is not None:
                names[student_id] = str(student.name)
        items: list[dict[str, Any]] = []
        for row in rows:
            items.append(
                {
                    "student_id": str(row.student_id),
                    "name": names.get(str(row.student_id)),
                    "balance": int(row.balance),
                    "level": str(row.level),
                    "total_deducted": int(row.total_deducted),
                    "total_awarded": int(row.total_awarded),
                    "streak_days": int(row.streak_days),
                    "compliance_rate": float(row.compliance_rate),
                    "updated_at": row.updated_at,
                }
            )
        return items, total

    def list_ledger(
        self,
        role: str,
        *,
        page: int = 1,
        page_size: int = 20,
        student_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        direction: str | None = None,
        reason_code: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页列出积分流水（多维筛选：学生/日期/方向/原因码）。

        Args:
            role: 调用方角色。
            page: 页码。
            page_size: 每页条数。
            student_id: 学号精确匹配。
            start: 生效时间起点（ISO 字符串）。
            end: 生效时间终点（ISO 字符串）。
            direction: `positive`/`negative`/`all`。
            reason_code: 原因码精确匹配。

        Returns:
            (流水字典列表, 总数) 二元组。
        """
        _require_read(role)
        safe_page, safe_size = _clamp_page(page, page_size)
        safe_direction: str | None = None
        if direction in ("positive", "negative"):
            safe_direction = direction
        repo = ScoreLedgerRepository(self.session)
        rows = repo.list_with_filters(
            student_id=student_id or None,
            start=_parse_dt(start),
            end=_parse_dt(end),
            direction=safe_direction,
            reason_code=reason_code or None,
            limit=safe_size,
            offset=(safe_page - 1) * safe_size,
        )
        total = repo.count_with_filters(
            student_id=student_id or None,
            start=_parse_dt(start),
            end=_parse_dt(end),
            direction=safe_direction,
            reason_code=reason_code or None,
        )
        items = [
            {
                "ledger_id": int(row.ledger_id),
                "student_id": str(row.student_id),
                "change": int(row.change),
                "balance_after": int(row.balance_after),
                "reason_code": str(row.reason_code),
                "reason_text": str(row.reason_text) if row.reason_text else None,
                "event_id": str(row.event_id) if row.event_id else None,
                "decision_id": str(row.decision_id) if row.decision_id else None,
                "operator": str(row.operator) if row.operator else None,
                "effective_at": row.effective_at,
                "created_at": row.created_at,
            }
            for row in rows
        ]
        return items, total

    # ------------------------------------------------------------------
    # 规则（读 + 写 + 试算）
    # ------------------------------------------------------------------

    def list_rules(self, role: str) -> list[ScoreRule]:
        """列出全部积分规则（含停用，按 priority 降序）。

        Args:
            role: 调用方角色.

        Returns:
            规则行列表。
        """
        _require_read(role)
        return ScoreRuleRepository(self.session).list_all()

    def update_rule(
        self,
        role: str,
        subject: str,
        rule_id: str,
        body: RuleUpdateBody,
    ) -> ScoreRule:
        """更新积分规则（结构化字段，禁止自由表达式字符串）。

        Args:
            role: 调用方角色。
            subject: 操作人。
            rule_id: 规则 ID。
            body: 更新请求体。

        Returns:
            更新后的规则行。

        Raises:
            NotFoundError: 规则不存在。
            ValidationError: DSL 非法。
        """
        _require_write(role)
        repo = ScoreRuleRepository(self.session)
        row = repo.get_by_id(rule_id)
        if row is None:
            raise NotFoundError("请求的资源不存在")
        if body.condition_json is not None:
            # 写前用领域求值器做一次空上下文校验：非法 DSL 直接 422。
            try:
                evaluate_condition(body.condition_json, {})
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
        try:
            if body.name is not None:
                row.name = body.name.strip()
            if body.score_change is not None:
                row.score_change = int(body.score_change)
            if body.priority is not None:
                row.priority = int(body.priority)
            if body.enabled is not None:
                row.enabled = bool(body.enabled)
            if body.rule_type is not None:
                row.rule_type = body.rule_type
            if body.condition_json is not None:
                row.condition_json = body.condition_json
            self.session.flush()
            AuditRepository(self.session).log(
                actor=subject,
                role=role,
                action="scoring.rule_update",
                object_type="score_rule",
                object_id=str(row.rule_id),
                result="ok",
                detail=f"rule={row.rule_id}",
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        refreshed = repo.get_by_id(rule_id)
        assert refreshed is not None
        return refreshed

    def simulate(
        self,
        role: str,
        *,
        rule_id: str | None = None,
        condition_json: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """试算规则命中（只推演不写库）。

        两种模式（二选一，`condition_json` 优先）：
        - 传入 `condition_json`：对单条候选条件求值；
        - 传入 `rule_id`：对该规则的已存条件求值。

        Args:
            role: 调用方角色。
            rule_id: 规则 ID（可选）。
            condition_json: 候选 DSL（可选）。
            context: 事实上下文。

        Returns:
            `{"matched", "total_change", "matched_rule_ids", "reasons"}`。

        Raises:
            ValidationError: 两种模式都没给，或 DSL 非法。
        """
        _require_read(role)
        facts: dict[str, Any] = dict(context or {})
        if condition_json is not None:
            try:
                matched = bool(evaluate_condition(condition_json, facts))
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            if not matched:
                return {
                    "matched": False,
                    "total_change": 0,
                    "matched_rule_ids": [],
                    "reasons": [],
                }
            # 单条件试算不涉及分值：只报告命中与否。
            return {
                "matched": True,
                "total_change": 0,
                "matched_rule_ids": [],
                "reasons": ["候选条件命中（试算不涉及分值）"],
            }
        if rule_id is not None:
            row = ScoreRuleRepository(self.session).get_by_id(rule_id)
            if row is None:
                raise NotFoundError("请求的资源不存在")
            try:
                spec = _rule_to_spec(row)
                effect = apply_rules([spec], facts)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            return {
                "matched": effect.total_change != 0,
                "total_change": effect.total_change,
                "matched_rule_ids": list(effect.matched_rule_ids),
                "reasons": list(effect.reasons),
            }
        raise ValidationError("试算需提供 rule_id 或 condition_json")


__all__ = [
    "READ_ROLES",
    "WRITE_ROLES",
    "ScoringAdminService",
]

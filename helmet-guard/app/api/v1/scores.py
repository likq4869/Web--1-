"""积分管理 API：账户、台账流水、规则列表/更新/试算。

职责：HTTP 解析与响应序列化、分页参数校验、服务调用。
依赖：FastAPI、app.core.deps、app.services.scoring.admin、app.schemas.scoring。
边界：不做业务规则判定；流水只读不写（记账统一走 LedgerService）；
越权语义由服务层收敛（非管理角色一律 404）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.core.deps import CurrentUserDep, DbSession
from app.schemas.scoring import (
    RuleSimulateBody,
    RuleSimulateResponse,
    RuleUpdateBody,
    ScoreAccountResponse,
    ScoreLedgerResponse,
    ScoreRuleResponse,
)
from app.services.scoring.admin import ScoringAdminService

router = APIRouter(prefix="/api/v1/admin/scores", tags=["score-admin"])

_LEDGER_SORTS = ("ledger_id/desc",)
_DIRECTIONS = ("all", "positive", "negative")


def _page_params(page: int, page_size: int) -> tuple[int, int]:
    """钳制分页参数。"""
    return max(1, page), min(max(1, page_size), 100)


@router.get("/accounts")
def list_accounts(
    session: DbSession,
    user: CurrentUserDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=64),
) -> dict[str, object]:
    """积分账户列表（按学号升序，附学生姓名）。"""
    safe_page, safe_size = _page_params(page, page_size)
    service = ScoringAdminService(session)
    rows, total = service.list_accounts(
        user.role or "",
        page=safe_page,
        page_size=safe_size,
        keyword=keyword,
    )
    items = [ScoreAccountResponse.model_validate(row).model_dump(mode="json") for row in rows]
    return {"items": items, "total": total, "page": safe_page, "page_size": safe_size}


@router.get("/ledger")
def list_ledger(
    session: DbSession,
    user: CurrentUserDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    student_id: str | None = Query(None, max_length=64),
    start: str | None = Query(None, max_length=64),
    end: str | None = Query(None, max_length=64),
    direction: str | None = Query(None, max_length=16),
    reason_code: str | None = Query(None, max_length=64),
) -> dict[str, object]:
    """积分流水台账（多维筛选：学生/日期/方向/原因码）。

    方向白名单：`all`/`positive`/`negative`；非法值回退为不限。
    """
    safe_page, safe_size = _page_params(page, page_size)
    safe_direction = direction if direction in _DIRECTIONS else None
    service = ScoringAdminService(session)
    rows, total = service.list_ledger(
        user.role or "",
        page=safe_page,
        page_size=safe_size,
        student_id=student_id,
        start=start,
        end=end,
        direction=safe_direction,
        reason_code=reason_code,
    )
    items = [ScoreLedgerResponse.model_validate(row).model_dump(mode="json") for row in rows]
    return {"items": items, "total": total, "page": safe_page, "page_size": safe_size}


@router.get("/rules")
def list_rules(session: DbSession, user: CurrentUserDep) -> dict[str, object]:
    """积分规则列表（含停用，按 priority 降序）。"""
    service = ScoringAdminService(session)
    rows = service.list_rules(user.role or "")
    items = [ScoreRuleResponse.model_validate(row).model_dump(mode="json") for row in rows]
    return {"items": items, "total": len(items)}


@router.put("/rules/{rule_id}")
def update_rule(
    rule_id: str,
    body: RuleUpdateBody,
    session: DbSession,
    user: CurrentUserDep,
) -> dict[str, Any]:
    """更新积分规则（结构化字段，禁止自由表达式字符串）。

    事务由服务层收敛（成功提交/失败回滚），路由层只做参数校验与响应序列化。
    """
    service = ScoringAdminService(session)
    row = service.update_rule(user.role or "", user.subject, rule_id, body)
    return ScoreRuleResponse.model_validate(row).model_dump(mode="json")


@router.post("/rules/simulate")
def simulate_rule(
    body: RuleSimulateBody,
    session: DbSession,
    user: CurrentUserDep,
) -> dict[str, Any]:
    """规则试算：用给定事实上下文求值，只推演不写库。

    两种模式（二选一，`condition_json` 优先）：
    - `condition_json` + `context`：对候选条件求值；
    - `rule_id` + `context`：对已存规则求值。
    """
    service = ScoringAdminService(session)
    payload = service.simulate(
        user.role or "",
        rule_id=body.rule_id,
        condition_json=body.condition_json,
        context=dict(body.context),
    )
    return RuleSimulateResponse.model_validate(payload).model_dump(mode="json")


__all__ = ["router"]

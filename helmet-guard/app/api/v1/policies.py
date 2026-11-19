"""策略配置 API：当前策略读取、结构化更新与模拟推演。

职责：HTTP 解析与响应序列化、服务调用；不做业务判定。
依赖：FastAPI、app.core.deps、app.services.decision.policy_admin、app.schemas.policy。
边界：只推演不写库（simulate）；写操作审计由服务层收敛。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUserDep, DbSession
from app.schemas.policy import (
    PolicyResponse,
    PolicySimulateBody,
    PolicySimulateResponse,
    PolicyUpdateBody,
)
from app.services.decision.policy_admin import PolicyAdminService

router = APIRouter(prefix="/api/v1/admin/policies", tags=["policy-admin"])


@router.get("/{policy_id}")
def get_policy(policy_id: str, session: DbSession, user: CurrentUserDep) -> dict[str, object]:
    """读取策略当前值（含版本、熔断阈值、规则注册表摘要）。"""
    service = PolicyAdminService(session)
    payload = service.get_policy(user.role or "", policy_id)
    return PolicyResponse.model_validate(payload).model_dump(mode="json")


@router.put("/{policy_id}")
def update_policy(
    policy_id: str,
    body: PolicyUpdateBody,
    session: DbSession,
    user: CurrentUserDep,
) -> dict[str, object]:
    """更新策略与阈值（结构化字段；非法转 422，写审计）。

    事务由服务层收敛（成功提交/失败回滚），路由层只做参数校验与响应序列化。
    """
    service = PolicyAdminService(session)
    payload = service.update_policy(
        user.role or "",
        user.subject,
        policy_id,
        body.policy,
        body.thresholds,
    )
    return PolicyResponse.model_validate(payload).model_dump(mode="json")


@router.post("/{policy_id}/simulate")
def simulate_policy(
    policy_id: str,
    session: DbSession,
    user: CurrentUserDep,
    body: PolicySimulateBody | None = None,
) -> dict[str, object]:
    """策略模拟：用候选策略重放历史决策，只推演不写库。

    纯读接口：全程不写库、不调台账；响应自带
    “此操作仅推演，不会真实生效”提示语。
    无请求体时用默认假设事实重放（兼容旧调用）。
    """
    service = PolicyAdminService(session)
    payload = service.simulate(
        user.role or "",
        policy_id,
        policy_body=body.policy if body else None,
        thresholds_body=body.thresholds if body else None,
        model_confidence=body.model_confidence if body else 0.85,
        identity_confidence=body.identity_confidence if body else 0.85,
        violation_count_30d=body.violation_count_30d if body else 0,
        violation_count_7d=body.violation_count_7d if body else 0,
        violation_count_1h_same_point=body.violation_count_1h_same_point if body else 0,
        limit=body.limit if body else 20,
    )
    return PolicySimulateResponse.model_validate(payload).model_dump(mode="json")


__all__ = ["router"]

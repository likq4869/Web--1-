"""B-1 路由显式注册守卫：禁止 suppress 静默吞异常的回归网。

职责：断言全部业务路由与遗留路由确实挂载到 OpenAPI，防止未来再次静默丢失。
依赖：app.main（显式导入，导入失败即测试失败，与生产启动语义一致）。
边界：只检查路径存在，不测业务语义。
"""

from __future__ import annotations

import app.main as main_mod


def test_all_routers_are_registered() -> None:
    """全部路由显式注册（B-1）：OpenAPI 必须包含 65 条路径。"""
    paths = main_mod.app.openapi()["paths"]
    expected = (
        # P3-0 认证（5）+ 微信快捷登录扩展（4 路径：wechat-login/bind-phone/profile/check-session）
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/auth/bind-student",
        "/api/v1/auth/wechat-login",
        "/api/v1/auth/bind-phone",
        "/api/v1/auth/profile",
        "/api/v1/auth/check-session",
        # P4-1 组织级联（1）
        "/api/v1/org/units",
        # P1-6 身份管理（10）
        "/api/v1/admin/identities/pending",
        "/api/v1/admin/identities/{vehicle_id}/bind",
        "/api/v1/admin/identities/{vehicle_id}/ignore",
        "/api/v1/admin/vehicles",
        "/api/v1/admin/vehicles/{vehicle_id}",
        "/api/v1/admin/students",
        "/api/v1/admin/students/template",
        "/api/v1/admin/students/import",
        "/api/v1/admin/students/import/tasks/{task_id}",
        "/api/v1/admin/students/{student_id}",
        # P2-3 决策审批（6）
        "/api/v1/admin/decisions",
        "/api/v1/admin/decisions/pending-count",
        "/api/v1/admin/decisions/{decision_id}",
        "/api/v1/admin/decisions/{decision_id}/approve",
        "/api/v1/admin/decisions/{decision_id}/reject",
        "/api/v1/admin/decisions/batch-approve",
        # P3-3b① 事件管理（3）
        "/api/v1/admin/events",
        "/api/v1/admin/events/export",
        "/api/v1/admin/events/{event_id}",
        # P3-3b① 策略配置（2，读写与模拟共用路径不重复计数）
        "/api/v1/admin/policies/{policy_id}",
        "/api/v1/admin/policies/{policy_id}/simulate",
        # P3-1 总览（3）
        "/api/v1/admin/dashboard/overview",
        "/api/v1/admin/dashboard/trends",
        "/api/v1/admin/dashboard/point-health",
        # P2-3 申诉（2+4）
        "/api/v1/admin/appeals",
        "/api/v1/admin/appeals/{appeal_id}/resolve",
        "/api/v1/me/records",
        "/api/v1/me/overview",
        # P3-3a 积分（5）
        "/api/v1/admin/scores/accounts",
        "/api/v1/admin/scores/ledger",
        "/api/v1/admin/scores/rules",
        "/api/v1/admin/scores/rules/{rule_id}",
        "/api/v1/admin/scores/rules/simulate",
        "/api/v1/me/appeals",
        # P3-3b③ 运维管理（7）
        "/api/v1/admin/ops/models",
        "/api/v1/admin/ops/models/feedback-stats",
        "/api/v1/admin/ops/models/{model_id}/activate",
        "/api/v1/admin/ops/audit-logs",
        "/api/v1/admin/ops/users",
        "/api/v1/admin/ops/users/{user_id}",
        "/api/v1/admin/ops/users/{user_id}/reset-password",
        # P3-4 实时监控（6，WS 不进 OpenAPI，只计 REST）
        "/api/v1/admin/monitor/points",
        "/api/v1/admin/monitor/points/{point_id}",
        "/api/v1/admin/monitor/points/{point_id}/snapshot",
        "/api/v1/admin/monitor/points/{point_id}/stream",
        "/api/v1/admin/monitor/points/{point_id}/config",
        "/api/v1/admin/monitor/feed",
        # 遗留原生 SQL（B-2 拆出，路径逐字不变）
        "/health",
        "/api/v1/sources",
        "/api/v1/stats",
        "/api/v1/events",
        "/api/v1/events/{event_id}/review",
        "/api/v1/alerts",
        "/api/v1/self-check",
        "/api/v1/self-check/status",
    )
    missing = [p for p in expected if p not in paths]
    assert not missing, f"路由静默丢失：{missing}"
    assert len(paths) == len(expected), f"路由数漂移：期望 {len(expected)}，实际 {len(paths)}"


__all__ = ["test_all_routers_are_registered"]

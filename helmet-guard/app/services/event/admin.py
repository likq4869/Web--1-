"""事件管理服务：管理端多维筛选、详情聚合与 CSV 导出。

职责：收敛事件域管理端的 RBAC、分页与排序白名单、证据聚合、导出。
依赖：sqlalchemy 会话、事件仓储、决策仓储。
边界：不做 HTTP 解析与响应序列化；只读不写库，不做复核状态流转。
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models.decision import Decision
from app.models.entities import Event, Pass
from app.repositories.decision import DecisionRepository
from app.repositories.event import EventRepository

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

PAGE_SIZE_MAX = 100
EXPORT_MAX_ROWS = 5000

EVENT_STATUSES = ("pending", "confirmed", "dismissed")
RIDER_STATUSES = ("helmeted", "bare", "unknown")
EVENT_SORTS = ("occurred_at/desc", "occurred_at/asc", "created_at/desc", "status/asc")


def _require_read(role: str) -> None:
    """读权限校验：非管理角色统一 404（隐藏资源存在性）。"""
    if role not in READ_ROLES:
        raise NotFoundError("请求的资源不存在")


def _clamp_page(page: int, page_size: int) -> tuple[int, int]:
    """钳制分页参数。"""
    return max(1, page), min(max(1, page_size), PAGE_SIZE_MAX)


def _parse_boxes(raw: str | None) -> list[dict[str, Any]]:
    """解析通行记录的检测框 JSON（归一化 xyxy，脏数据跳过该条）。

    Args:
        raw: JSON 字符串；为空或非法时返回空列表。

    Returns:
        检测框列表（仅含结构合法的项）。
    """
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    result: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        xyxy = item.get("xyxy")
        if not isinstance(xyxy, list) or len(xyxy) != 4:
            continue
        try:
            coords = [float(value) for value in xyxy]
        except (TypeError, ValueError):
            continue
        confidence = item.get("confidence")
        result.append(
            {
                "label": str(item.get("label", "目标")),
                "confidence": float(confidence) if isinstance(confidence, (int, float)) else None,
                "xyxy": coords,
            }
        )
    return result


def _event_to_item(event: Event) -> dict[str, Any]:
    """把事件 ORM 行投影为列表项字典。"""
    return {
        "event_id": str(event.event_id),
        "pass_id": str(event.pass_id),
        "source_id": str(event.source_id),
        "run_id": str(event.run_id),
        "occurred_at": str(event.occurred_at),
        "status": str(event.status),
        "model_label": str(event.model_label),
        "reason": str(event.reason) if event.reason else None,
        "reviewer": str(event.reviewer) if event.reviewer else None,
        "reviewed_at": str(event.reviewed_at) if event.reviewed_at else None,
        "created_at": str(event.created_at),
    }


class EventAdminService:
    """事件管理服务（绑定单个会话，只读）。"""

    def __init__(self, session: Session) -> None:
        """初始化服务。

        Args:
            session: 数据库会话。
        """
        self.session = session

    def list_events(
        self,
        role: str,
        *,
        source_id: str | None = None,
        status: str | None = None,
        run_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        rider_status: str | None = None,
        has_evidence: bool | None = None,
        has_decision: bool | None = None,
        sort: str = "occurred_at/desc",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页列出事件（多维筛选 + 排序白名单）。

        Args:
            role: 调用方角色。
            source_id: 点位 ID 精确匹配。
            status: 复核状态；非法值由调用方忽略（此处直接透传）。
            run_id: 采集运行 ID 精确匹配。
            start: 发生时间下界（含，ISO 字符串比较）。
            end: 发生时间上界（含）。
            rider_status: 通行三态。
            has_evidence: 是否有检测框证据。
            has_decision: 是否已生成决策。
            sort: 排序白名单；非法值回退默认。
            page: 页码。
            page_size: 每页条数。

        Returns:
            (事件字典列表, 总数) 二元组。
        """
        _require_read(role)
        safe_page, safe_size = _clamp_page(page, page_size)
        safe_sort = sort if sort in EVENT_SORTS else "occurred_at/desc"
        repo = EventRepository(self.session)
        rows = repo.list_with_filters(
            source_id=source_id or None,
            status=status or None,
            run_id=run_id or None,
            start=start or None,
            end=end or None,
            rider_status=rider_status or None,
            has_evidence=has_evidence,
            has_decision=has_decision,
            sort=safe_sort,
            limit=safe_size,
            offset=(safe_page - 1) * safe_size,
        )
        total = repo.count_with_filters(
            source_id=source_id or None,
            status=status or None,
            run_id=run_id or None,
            start=start or None,
            end=end or None,
            rider_status=rider_status or None,
            has_evidence=has_evidence,
            has_decision=has_decision,
        )
        return [_event_to_item(row) for row in rows], total

    def get_detail(self, role: str, event_id: str) -> dict[str, Any]:
        """读取事件详情（含通行证据与关联决策摘要）。

        Args:
            role: 调用方角色。
            event_id: 事件 ID。

        Returns:
            详情字典（含 boxes/image 尺寸/决策摘要）。

        Raises:
            NotFoundError: 事件不存在。
        """
        _require_read(role)
        event = self.session.get(Event, event_id)
        if event is None:
            raise NotFoundError("请求的资源不存在")
        payload = _event_to_item(event)
        passage = self.session.get(Pass, str(event.pass_id))
        if passage is None:
            payload.update(
                {
                    "rider_status": None,
                    "boxes": [],
                    "image_width": None,
                    "image_height": None,
                }
            )
        else:
            payload.update(
                {
                    "rider_status": str(passage.rider_status),
                    "boxes": _parse_boxes(passage.boxes),
                    "image_width": int(passage.image_width) if passage.image_width else None,
                    "image_height": int(passage.image_height) if passage.image_height else None,
                }
            )
        decision: Decision | None = DecisionRepository(self.session).get_by_event(
            str(event.event_id)
        )
        if decision is None:
            payload.update({"decision_id": None, "decision_level": None, "decision_status": None})
        else:
            payload.update(
                {
                    "decision_id": str(decision.decision_id),
                    "decision_level": str(decision.level),
                    "decision_status": str(decision.status),
                }
            )
        return payload

    def export_csv(
        self,
        role: str,
        *,
        source_id: str | None = None,
        status: str | None = None,
        run_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        rider_status: str | None = None,
        has_evidence: bool | None = None,
        has_decision: bool | None = None,
        sort: str = "occurred_at/desc",
    ) -> str:
        """导出符合筛选条件的事件 CSV（只读，上限 5000 行）。

        Args:
            role: 调用方角色。
            source_id: 点位 ID。
            status: 复核状态。
            run_id: 采集运行 ID。
            start: 发生时间下界。
            end: 发生时间上界。
            rider_status: 通行三态。
            has_evidence: 是否有证据。
            has_decision: 是否已生成决策。
            sort: 排序白名单。

        Returns:
            CSV 文本（含表头，UTF-8-SIG 由路由层编码）。
        """
        _require_read(role)
        safe_sort = sort if sort in EVENT_SORTS else "occurred_at/desc"
        repo = EventRepository(self.session)
        rows = repo.list_with_filters(
            source_id=source_id or None,
            status=status or None,
            run_id=run_id or None,
            start=start or None,
            end=end or None,
            rider_status=rider_status or None,
            has_evidence=has_evidence,
            has_decision=has_decision,
            sort=safe_sort,
            limit=EXPORT_MAX_ROWS,
            offset=0,
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "event_id",
                "pass_id",
                "source_id",
                "run_id",
                "occurred_at",
                "status",
                "model_label",
                "reason",
                "reviewer",
                "reviewed_at",
                "created_at",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.event_id,
                    row.pass_id,
                    row.source_id,
                    row.run_id,
                    row.occurred_at,
                    row.status,
                    row.model_label,
                    row.reason,
                    row.reviewer,
                    row.reviewed_at,
                    row.created_at,
                ]
            )
        return buffer.getvalue()


__all__ = [
    "EVENT_SORTS",
    "EventAdminService",
    "READ_ROLES",
]

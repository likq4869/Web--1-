"""实时监控服务：点位健康、实时违规流、单点位快照。

职责：收敛监控域的 RBAC、点位过滤、聚合组装；快照只读不写库，
标定写入走事务收敛并记审计。
依赖：sqlalchemy 会话、总览服务、事件/决策/用户/标定仓储、领域校验。
边界：不做 HTTP 解析与响应序列化；不推送 WS（推送由 hub 承担）；
counselor 按 auth 的 source_ids 过滤，无点位时收不到点位事件；
无真实视频源，流地址永不编造，一律不可用。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.config import PointConfig
from app.core.errors import NotFoundError, ValidationError
from app.domain.monitor_config import validate_line_y, validate_rect
from app.repositories.audit import AuditRepository
from app.repositories.decision import DecisionRepository
from app.repositories.event import EventRepository
from app.repositories.monitor import CameraPointRepository
from app.repositories.pass_record import PassRepository
from app.repositories.user import UserRepository
from app.services.dashboard.service import DashboardService

# 读权限：与总览页一致的宽口径（含 observer，方便大屏值班）。
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

FEED_LIMIT_MAX = 50

# 标定写入权限：与模型激活一致（仅规则管理员三角色）。
MONITOR_WRITE_ROLES: frozenset[str] = frozenset({"super_admin", "league_officer", "admin"})


def _require_read(role: str) -> None:
    """读权限：非授权角色按无资源处理（404，不泄露接口存在性）。"""
    if role not in READ_ROLES:
        raise NotFoundError("请求的资源不存在")


def _require_write(role: str) -> None:
    """标定写入权限：越权统一 404（隐藏资源存在性）。"""
    if role not in MONITOR_WRITE_ROLES:
        raise NotFoundError("请求的资源不存在")


def _parse_boxes(raw: str | None) -> list[dict[str, Any]]:
    """解析通行记录的检测框 JSON（归一化 xyxy，脏数据跳过该条）。"""
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
                "confidence": float(confidence)
                if isinstance(confidence, (int, float))
                else None,
                "xyxy": coords,
            }
        )
    return result


def _default_config() -> tuple[list[float], float, list[float]]:
    """返回内存默认标定（与 app.config.PointConfig 同源）。"""
    cfg = PointConfig()
    return list(cfg.roi), float(cfg.count_line_y), list(cfg.alert_zone)


def _config_to_dict(
    point_id: str,
    roi: list[float],
    count_line_y: float,
    alert_zone: list[float],
    *,
    updated_by: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """把标定三元组装成响应字典。"""
    return {
        "point_id": point_id,
        "roi": [float(value) for value in roi],
        "count_line_y": float(count_line_y),
        "alert_zone": [float(value) for value in alert_zone],
        "updated_by": updated_by,
        "updated_at": updated_at,
    }


class MonitorService:
    """监控只读服务（绑定单个会话）。"""

    def __init__(self, session: Session) -> None:
        """初始化服务。

        Args:
            session: 数据库会话。
        """
        self.session = session
        self.dashboard = DashboardService(session)

    def _allowed_sources(self, role: str, subject: str) -> list[str] | None:
        """返回 counselor 可见点位；其他角色返回 None（全部可见）。

        Args:
            role: 调用方角色。
            subject: 用户 ID。

        Returns:
            点位 ID 列表；None 表示不过滤。
        """
        if role != "counselor":
            return None
        return UserRepository(self.session).list_source_ids(subject)

    def list_points(self, role: str, subject: str) -> list[dict[str, Any]]:
        """列出点位健康（counselor 仅限名下点位）。

        Args:
            role: 调用方角色。
            subject: 用户 ID。

        Returns:
            点位健康列表。
        """
        _require_read(role)
        points = self.dashboard.point_health()
        allowed = self._allowed_sources(role, subject)
        if allowed is None:
            return points
        wanted = set(allowed)
        return [item for item in points if str(item.get("source_id")) in wanted]

    def get_point(self, role: str, subject: str, point_id: str) -> dict[str, Any]:
        """读取单点位健康 + 最近一条事件摘要。

        Args:
            role: 调用方角色。
            subject: 用户 ID。
            point_id: 点位 ID。

        Returns:
            点位健康与最近事件。

        Raises:
            NotFoundError: 点位不存在或无权查看。
        """
        _require_read(role)
        allowed = self._allowed_sources(role, subject)
        if allowed is not None and point_id not in allowed:
            raise NotFoundError("请求的资源不存在")
        points = {str(item.get("source_id")): item for item in self.dashboard.point_health()}
        point = points.get(point_id)
        if point is None:
            raise NotFoundError("请求的资源不存在")
        rows = EventRepository(self.session).list_with_filters(
            source_id=point_id, sort="occurred_at/desc", limit=1, offset=0
        )
        last_event: dict[str, Any] | None = None
        if rows:
            row = rows[0]
            last_event = {
                "event_id": str(row.event_id),
                "occurred_at": str(row.occurred_at),
                "status": str(row.status),
                "model_label": str(row.model_label),
            }
        return {"point": point, "last_event": last_event}

    def get_snapshot(self, role: str, subject: str, point_id: str) -> dict[str, Any]:
        """读取单点位快照：健康 + 最近事件 + 最近通行证据帧。

        证据复用 `passes.boxes / image_width / image_height`（与审批详情同口径）；
        无通行记录时 evidence 为 None，前端按离线降级展示。

        Args:
            role: 调用方角色。
            subject: 用户 ID。
            point_id: 点位 ID。

        Returns:
            快照字典（含 evidence 可能为 None）。

        Raises:
            NotFoundError: 点位不存在或无权查看。
        """
        base = self.get_point(role, subject, point_id)
        passes = PassRepository(self.session).list_with_filters(
            source_id=point_id, limit=1, offset=0
        )
        if not passes:
            return {**base, "evidence": None}
        row = passes[0]
        evidence: dict[str, Any] = {
            "pass_id": str(row.pass_id),
            "occurred_at": str(row.occurred_at),
            "rider_status": str(row.rider_status),
            "boxes": _parse_boxes(row.boxes),
            "image_width": int(row.image_width) if row.image_width else None,
            "image_height": int(row.image_height) if row.image_height else None,
        }
        return {**base, "evidence": evidence}

    def get_stream(self, role: str, subject: str, point_id: str) -> dict[str, Any]:
        """返回单点位流可用性：一律不可用（诚实降级，不编造 URL）。

        Args:
            role: 调用方角色。
            subject: 用户 ID。
            point_id: 点位 ID。

        Returns:
            流状态字典（available 恒为 False）。

        Raises:
            NotFoundError: 点位不存在或无权查看。
        """
        base = self.get_point(role, subject, point_id)
        _ = base
        return {
            "point_id": point_id,
            "available": False,
            "stream_url": None,
            "reason": "暂无实时视频源，仅展示检测叠加与违规流",
        }

    def get_config(self, role: str, subject: str, point_id: str) -> dict[str, Any]:
        """读取点位标定配置（无行回退内存默认）。

        Args:
            role: 调用方角色。
            subject: 用户 ID。
            point_id: 点位 ID。

        Returns:
            标定字典。

        Raises:
            NotFoundError: 点位不存在或无权查看。
        """
        base = self.get_point(role, subject, point_id)
        _ = base
        row = CameraPointRepository(self.session).get_by_source(point_id)
        if row is None:
            roi, line_y, zone = _default_config()
            return _config_to_dict(point_id, roi, line_y, zone)
        updated_at = row.updated_at
        return _config_to_dict(
            point_id,
            [float(row.roi_x1), float(row.roi_y1), float(row.roi_x2), float(row.roi_y2)],
            float(row.count_line_y),
            [
                float(row.zone_x1),
                float(row.zone_y1),
                float(row.zone_x2),
                float(row.zone_y2),
            ],
            updated_by=str(row.updated_by) if row.updated_by else None,
            updated_at=str(updated_at) if updated_at is not None else None,
        )

    def update_config(
        self,
        role: str,
        subject: str,
        point_id: str,
        *,
        roi: object,
        count_line_y: object,
        alert_zone: object,
    ) -> dict[str, Any]:
        """覆盖点位标定配置（归一化校验 + 事务收敛 + 审计）。

        Args:
            role: 调用方角色。
            subject: 操作人。
            point_id: 点位 ID。
            roi: ROI 四元数组。
            count_line_y: 计数线高度。
            alert_zone: 提醒区四元数组。

        Returns:
            更新后的标定字典。

        Raises:
            NotFoundError: 点位不存在、无权查看或无权写入。
            ValidationError: 几何非法。
        """
        _require_write(role)
        base = self.get_point(role, subject, point_id)
        _ = base
        try:
            safe_roi = validate_rect(roi, field="roi")
            safe_line = validate_line_y(count_line_y, field="count_line_y")
            safe_zone = validate_rect(alert_zone, field="alert_zone")
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        try:
            CameraPointRepository(self.session).upsert(
                source_id=point_id,
                roi=safe_roi,
                count_line_y=safe_line,
                alert_zone=safe_zone,
                updated_by=subject,
            )
            AuditRepository(self.session).log(
                actor=subject,
                role=role,
                action="monitor.config_update",
                object_type="camera_point",
                object_id=point_id,
                result="ok",
                detail=f"point={point_id} roi={safe_roi} line={safe_line}",
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        refreshed = CameraPointRepository(self.session).get_by_source(point_id)
        updated_at = refreshed.updated_at if refreshed is not None else None
        return _config_to_dict(
            point_id,
            safe_roi,
            safe_line,
            safe_zone,
            updated_by=subject,
            updated_at=str(updated_at) if updated_at is not None else None,
        )

    def recent_feed(
        self,
        role: str,
        subject: str,
        *,
        point_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """读取实时违规流初始数据（最近 bare 事件倒序，最多 50 条）。

        Args:
            role: 调用方角色。
            subject: 用户 ID。
            point_id: 点位过滤；非法点位对 counselor 直接 404。
            limit: 最大条数（钳制 1~50）。

        Returns:
            事件字典列表（含关联决策档位，无 N+1）。
        """
        _require_read(role)
        allowed = self._allowed_sources(role, subject)
        if allowed is not None:
            wanted = set(allowed)
            if point_id is not None and point_id not in wanted:
                raise NotFoundError("请求的资源不存在")
        safe_limit = max(1, min(int(limit), FEED_LIMIT_MAX))
        repo = EventRepository(self.session)
        if allowed is None or point_id is not None:
            rows = repo.list_with_filters(
                source_id=point_id,
                sort="occurred_at/desc",
                limit=safe_limit,
                offset=0,
            )
        else:
            # counselor 全点位视角：多取后按名下点位过滤（feed 上限 50，单次查询足够）。
            rows = repo.list_with_filters(
                sort="occurred_at/desc", limit=safe_limit, offset=0
            )
            wanted = set(allowed)
            rows = [row for row in rows if str(row.source_id) in wanted][:safe_limit]
        if not rows:
            return []
        event_ids = [str(row.event_id) for row in rows]
        decisions = DecisionRepository(self.session).list_by_event_ids(event_ids)
        level_by_event = {str(row.event_id): str(row.level) for row in decisions}
        status_by_event = {str(row.event_id): str(row.status) for row in decisions}
        names = {
            str(item.get("source_id")): str(item.get("name", ""))
            for item in self.dashboard.point_health()
        }
        items: list[dict[str, Any]] = []
        for row in rows:
            event_id = str(row.event_id)
            items.append(
                {
                    "event_id": event_id,
                    "source_id": str(row.source_id),
                    "point_name": names.get(str(row.source_id), str(row.source_id)),
                    "occurred_at": str(row.occurred_at),
                    "status": str(row.status),
                    "model_label": str(row.model_label),
                    "decision_level": level_by_event.get(event_id),
                    "decision_status": status_by_event.get(event_id),
                }
            )
        return items


__all__ = ["FEED_LIMIT_MAX", "MONITOR_WRITE_ROLES", "READ_ROLES", "MonitorService"]

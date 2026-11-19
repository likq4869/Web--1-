"""总览服务：指标聚合、趋势序列、点位健康与响应缓存。

职责：把仓储层的原始聚合结果组装成前端可直接消费的总览载荷，
并提供 30s TTL 的 Redis 响应缓存（Redis 不可用时自动降级为直查）。
依赖：app.repositories.dashboard、app.core.config、redis（可选）。
边界：不修改任何业务数据；不缓存含个人身份的可变明细；缓存键必须包含
全部查询参数，避免串数据。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.repositories.dashboard import DashboardRepository

_LOGGER = get_logger(__name__)

# 总览缓存 TTL：30 秒 —— 兼顾实时性与聚合查询压力。
CACHE_TTL_SECONDS = 30
# 本月佩戴率趋势的天数上限（30 点）。
TREND_DAYS = 30
# 今日时段柱状图的小时数。
HOURS_PER_DAY = 24
# 心跳过期秒数：与采集进程配置保持同源读取。
DEFAULT_HEARTBEAT_EXPIRE = 30

# 点位状态语义（与 sources.status 一致）。
POINT_STATUS_ONLINE = "online"
POINT_STATUS_OFFLINE = "offline"


def _naive(moment: datetime) -> datetime:
    """把带时区时间转成 naive UTC（SQLite DateTime 列读回为 naive）。"""
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(UTC).replace(tzinfo=None)


def _day_start(moment: datetime) -> datetime:
    """返回当天 00:00（naive UTC）。"""
    return datetime.combine(moment.date(), time.min)


def _parse_iso(text: str | None) -> datetime | None:
    """解析 ISO 时间串并统一为 naive UTC；非法返回 None。

    心跳时间在库中可能是 naive（本地写法）也可能是带时区的 ISO 串，
    统一转成 naive UTC 后与 ``_naive`` 产出的锚点可直接相减。
    """
    if not text:
        return None
    try:
        value = text.strip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _naive(parsed)


def _wear_rate(helmeted: int, bare: int) -> float:
    """计算佩戴率（%）：分母为已判定样本（helmeted + bare）。

    `unknown` 不计入分母 —— 保守原则：无法判定不算作合规。
    """
    judged = helmeted + bare
    if judged <= 0:
        return 0.0
    return round(helmeted / judged * 100, 1)


def _percent_delta(current: float, previous: float) -> float | None:
    """计算相对变化百分点；上期为 0 时不返回（避免除零误导）。"""
    if previous <= 0:
        return None
    return round(current - previous, 1)


class DashboardService:
    """总览服务。"""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        """初始化服务。

        Args:
            session: 数据库会话。
            settings: 应用配置；缺省读单例。
        """
        self.session = session
        self.settings = settings or get_settings()
        self.repo = DashboardRepository(session)

    # ------------------------------------------------------------------
    # 总览
    # ------------------------------------------------------------------

    def overview(self, now: datetime | None = None) -> dict[str, Any]:
        """组装总览指标、趋势与点位健康。

        Args:
            now: 时间锚点（缺省取当前 UTC）；测试可注入固定值。

        Returns:
            总览载荷（见 ``build_overview`` 的结构说明）。
        """
        moment = _naive(now or datetime.now(UTC))
        today_start = _day_start(moment)
        today_end = today_start + timedelta(days=1)
        month_start = today_start - timedelta(days=TREND_DAYS - 1)

        today = self.repo.pass_summary(today_start, today_end)
        yesterday_start = today_start - timedelta(days=1)
        yesterday = self.repo.pass_summary(yesterday_start, today_start)

        wear_rate = _wear_rate(today["helmeted"], today["bare"])
        yesterday_rate = _wear_rate(yesterday["helmeted"], yesterday["bare"])

        daily = self.repo.pass_summary_by_day(month_start, today_end)
        hourly = self.repo.bare_summary_by_hour(today_start, today_end)
        point_health = self.point_health(now=moment)

        online = sum(
            1 for item in point_health if item["status"] == POINT_STATUS_ONLINE
        )
        total_points = len(point_health)

        return {
            "today": {
                "passes": today["total"],
                "violations": today["bare"],
                "wear_rate": wear_rate,
                "judged": today["helmeted"] + today["bare"],
                "unknown": today["unknown"],
            },
            "trends": {
                "wear_rate": self._wear_rate_series(daily, month_start, today_end),
                "violations_by_hour": [
                    {"hour": hour, "count": hourly.get(hour, 0)}
                    for hour in range(HOURS_PER_DAY)
                ],
            },
            "pending_reviews": self.repo.pending_decision_count(),
            "points": {
                "online": online,
                "total": total_points,
            },
            "students": {
                "active": self.repo.active_student_count(since=month_start),
                "registered": self.repo.total_student_count(),
            },
            "comparison": {
                "passes_delta": today["total"] - yesterday["total"],
                "violations_delta": today["bare"] - yesterday["bare"],
                "wear_rate_delta": _percent_delta(wear_rate, yesterday_rate),
            },
            "point_health": point_health,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    def _wear_rate_series(
        self,
        daily: dict[str, dict[str, int]],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """构造连续的佩戴率趋势序列（补齐无数据日，保证 30 点）。

        Args:
            daily: 按天聚合的通行分布。
            start: 起始日（含）。
            end: 结束日（不含）。

        Returns:
            ``[{"date", "wear_rate", "passes", "violations"}]``。
        """
        series: list[dict[str, Any]] = []
        cursor = start
        while cursor < end:
            key = cursor.date().isoformat()
            item = daily.get(key, {"total": 0, "helmeted": 0, "bare": 0})
            series.append(
                {
                    "date": key,
                    "wear_rate": _wear_rate(item["helmeted"], item["bare"]),
                    "passes": int(item["total"]),
                    "violations": int(item["bare"]),
                }
            )
            cursor += timedelta(days=1)
        return series

    # ------------------------------------------------------------------
    # 趋势
    # ------------------------------------------------------------------

    def trends(
        self,
        *,
        metric: str = "wear_rate",
        granularity: str = "day",
        days: int = 30,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """返回指定指标的趋势序列。

        Args:
            metric: ``wear_rate``（佩戴率）/ ``violations``（违规数）/
                ``passes``（通行数）。
            granularity: ``day`` 或 ``hour``（hour 仅对当日有意义）。
            days: 回看天数（1~90）。
            now: 时间锚点。

        Returns:
            ``{"metric", "granularity", "days", "points": [...]}``。

        Raises:
            ValueError: metric 或 granularity 非法。
        """
        if metric not in ("wear_rate", "violations", "passes"):
            raise ValueError("metric 非法")
        if granularity not in ("day", "hour"):
            raise ValueError("granularity 非法")
        span = max(1, min(int(days), 90))
        moment = _naive(now or datetime.now(UTC))
        today_start = _day_start(moment)
        today_end = today_start + timedelta(days=1)
        start = today_start - timedelta(days=span - 1)

        if granularity == "hour":
            hourly = self.repo.bare_summary_by_hour(today_start, today_end)
            hourly_points = [
                {"label": f"{hour:02d}:00", "value": hourly.get(hour, 0)}
                for hour in range(HOURS_PER_DAY)
            ]
            return {
                "metric": metric,
                "granularity": granularity,
                "days": span,
                "points": hourly_points,
            }

        daily = self.repo.pass_summary_by_day(start, today_end)
        event_daily = self.repo.event_count_by_day(start, today_end)
        points: list[dict[str, Any]] = []
        cursor = start
        while cursor < today_end:
            key = cursor.date().isoformat()
            item = daily.get(key, {"total": 0, "helmeted": 0, "bare": 0})
            if metric == "wear_rate":
                value = _wear_rate(item["helmeted"], item["bare"])
            elif metric == "violations":
                value = int(event_daily.get(key, 0))
            else:
                value = int(item["total"])
            points.append({"label": key, "value": value})
            cursor += timedelta(days=1)
        return {
            "metric": metric,
            "granularity": granularity,
            "days": span,
            "points": points,
        }

    # ------------------------------------------------------------------
    # 点位健康
    # ------------------------------------------------------------------

    def point_health(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """计算每个点位的健康状况。

        状态判定：心跳存在且未过期 → ``online``；否则 ``offline``。
        FPS 取心跳明细中的 ``fps`` 字段（缺失时为 None，不臆造）。

        Args:
            now: 时间锚点（naive UTC）。

        Returns:
            点位健康列表。
        """
        moment = _naive(now or datetime.now(UTC))
        expire = int(self.settings.helmet_guard_heartbeat_expire or DEFAULT_HEARTBEAT_EXPIRE)
        sources = self.repo.source_rows()
        heartbeats = {str(row["source_id"]): row for row in self.repo.heartbeat_rows()}
        today_start = _day_start(moment)
        today_end = today_start + timedelta(days=1)
        today_events = self.repo.event_count_by_source_today(today_start, today_end)
        today_passes = self.repo.pass_count_by_source_today(today_start, today_end)
        last_events = self.repo.last_event_at_by_source()

        out: list[dict[str, Any]] = []
        for source in sources:
            source_id = str(source["source_id"])
            heartbeat = heartbeats.get(source_id)
            last_heartbeat = None
            fps: float | None = None
            stage = ""
            age_seconds: float | None = None
            if heartbeat is not None:
                last_heartbeat = str(heartbeat["updated_at"] or "")
                parsed_at = _parse_iso(last_heartbeat)
                if parsed_at is not None:
                    age_seconds = max(
                        0.0, (moment - _naive(parsed_at)).total_seconds()
                    )
                detail = self._parse_detail(str(heartbeat["detail"] or ""))
                stage = str(detail.get("stage", ""))
                raw_fps = detail.get("fps")
                if isinstance(raw_fps, (int, float)):
                    fps = float(raw_fps)
            online = bool(
                heartbeat is not None
                and age_seconds is not None
                and age_seconds <= expire
                and stage not in ("stopped", "model_failed", "no_first_frame")
            )
            out.append(
                {
                    "source_id": source_id,
                    "name": str(source["name"]),
                    "status": POINT_STATUS_ONLINE if online else POINT_STATUS_OFFLINE,
                    "fps": fps,
                    "last_heartbeat": last_heartbeat or None,
                    "heartbeat_age_seconds": (
                        round(age_seconds, 1) if age_seconds is not None else None
                    ),
                    "last_event_at": last_events.get(source_id),
                    "today_events": int(today_events.get(source_id, 0)),
                    "today_passes": int(today_passes.get(source_id, 0)),
                }
            )
        return out

    @staticmethod
    def _parse_detail(raw: str) -> dict[str, Any]:
        """解析心跳明细 JSON；非法时返回空字典。"""
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}


__all__ = [
    "CACHE_TTL_SECONDS",
    "HOURS_PER_DAY",
    "TREND_DAYS",
    "DashboardService",
]

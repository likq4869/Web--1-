"""车辆共现服务：增量更新与全量重算（I/O 层）。

职责：把 identity_resolutions 中的车辆出现历史映射为
vehicle_cooccurrence 矩阵，供 resolver 的共现证据路径使用。
依赖：sqlalchemy 会话、仓储层、领域层纯函数。
边界：只做 I/O 与编排；窗口划分、Jaccard、匹配决策由领域层负责。

数据流：
- 全量重算：identity_resolutions（vehicle_id + created_at）
  → 按车分组 → build_windows → compute_cooccurrence → upsert。
- 增量更新：本次通行车辆 + 同窗口内其他车辆配对，
  window_count +1（同窗口去重），jaccard 保持原值等夜间重算刷新。
  增量只保证计数单调准确，Jaccard 精确值由每日全量重算保证。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cooccurrence import (
    DEFAULT_WINDOW_MINUTES,
    CooccurrenceStats,
    build_windows,
    compute_cooccurrence,
)
from app.models.identity import IdentityResolution, Vehicle
from app.repositories.cooccurrence import VehicleCooccurrenceRepository
from app.services.identity.resolver import CooccurHint

# 增量更新的同窗口回看秒数：与窗口长度一致，保证"同窗口"语义。
LOOKBACK_SECONDS = DEFAULT_WINDOW_MINUTES * 60


def _parse_moment(value: datetime | str | None) -> datetime | None:
    """解析判定记录的时间（datetime 或 ISO 字符串），失败返回 None。

    naive 时间一律视为 UTC（与 SQLite 读出的 CURRENT_TIMESTAMP 一致，
    亦与领域层 build_windows 的约定对齐）。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    try:
        text = str(value).strip()
        if not text:
            return None
        # SQLite 的 CURRENT_TIMESTAMP 形如 "2026-11-16 12:00:00"，补 UTC。
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        moment = datetime.fromisoformat(text)
        if moment.tzinfo is None:
            return moment.replace(tzinfo=UTC)
        return moment
    except ValueError:
        return None


def _window_bounds(moment: datetime, window_minutes: int) -> tuple[datetime, datetime]:
    """计算某时刻所在窗口的起止（UTC 对齐）。"""
    span = window_minutes * 60
    epoch = int(moment.timestamp()) // span * span
    start = datetime.fromtimestamp(epoch, tz=UTC)
    return start, start + timedelta(seconds=span)


def collect_vehicle_windows(
    session: Session, *, window_minutes: int = DEFAULT_WINDOW_MINUTES
) -> dict[str, set[int]]:
    """从判定历史收集每辆车的出现窗口集合（全量重算用）。

    Args:
        session: 数据库会话。
        window_minutes: 窗口长度（分钟）。

    Returns:
        车辆 ID → 窗口索引集合；无判定记录时为空字典。
    """
    statement = select(
        IdentityResolution.vehicle_id, IdentityResolution.created_at
    ).where(IdentityResolution.vehicle_id.is_not(None))
    vehicle_times: dict[str, list[datetime]] = {}
    for vehicle_id, created_at in session.execute(statement).all():
        if vehicle_id is None:
            continue
        moment = _parse_moment(created_at)
        if moment is None:
            continue
        vehicle_times.setdefault(str(vehicle_id), []).append(moment)
    result: dict[str, set[int]] = {}
    for vehicle_id, moments in vehicle_times.items():
        result[vehicle_id] = set(build_windows(moments, window_minutes))
    return result


def rebuild_cooccurrence(
    session: Session, *, window_minutes: int = DEFAULT_WINDOW_MINUTES
) -> dict[tuple[str, str], CooccurrenceStats]:
    """全量重算共现矩阵（离线任务，每日凌晨调用）。

    先清空旧矩阵，再按当前判定历史逐对写入，保证与历史完全一致。

    Args:
        session: 数据库会话。
        window_minutes: 窗口长度（分钟）。

    Returns:
        本次计算的共现统计（与落库内容一致）。
    """
    vehicle_windows = collect_vehicle_windows(session, window_minutes=window_minutes)
    stats = compute_cooccurrence(vehicle_windows)
    repo = VehicleCooccurrenceRepository(session)
    repo.delete_all()
    for (first, second), item in stats.items():
        repo.upsert(first, second, window_count=item.shared_windows, jaccard=item.jaccard)
    return stats


def update_cooccurrence(
    session: Session,
    vehicle_id: str,
    occurred_at: datetime | None = None,
    *,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
) -> list[tuple[str, str]]:
    """增量更新共现矩阵（每次通行后调用）。

    把该车与同窗口内出现的其他车配对，window_count +1；
    jaccard 保持原值（精确值由夜间全量重算刷新）。
    同一窗口内重复调用只计数一次（按 updated_at 去重），
    避免同一窗口多条通行把 shared_windows 刷高。

    Args:
        session: 数据库会话。
        vehicle_id: 本次通行的车辆 ID。
        occurred_at: 通行时间；None 时用当前 UTC 时间。
        window_minutes: 窗口长度（分钟）。

    Returns:
        本次实际累加的车辆对列表（规范序）。
    """
    if not vehicle_id:
        raise ValueError("vehicle_id 不能为空")
    moment = occurred_at if occurred_at is not None else datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    window_start, window_end = _window_bounds(moment, window_minutes)
    current_window = build_windows([moment], window_minutes)[0]

    statement = select(IdentityResolution.vehicle_id, IdentityResolution.created_at).where(
        IdentityResolution.vehicle_id.is_not(None),
        IdentityResolution.vehicle_id != vehicle_id,
    )
    partners: set[str] = set()
    for other_id, created_at in session.execute(statement).all():
        if other_id is None:
            continue
        other_moment = _parse_moment(created_at)
        if other_moment is None:
            continue
        if build_windows([other_moment], window_minutes)[0] == current_window:
            partners.add(str(other_id))

    repo = VehicleCooccurrenceRepository(session)
    updated: list[tuple[str, str]] = []
    for partner in sorted(partners):
        first, second = (
            (vehicle_id, partner) if vehicle_id <= partner else (partner, vehicle_id)
        )
        existing = repo.get_pair(first, second)
        if existing is not None:
            # 同窗口去重：updated_at 存的是上次计数的事件时刻（见下），
            # 落在同一窗口说明本窗口已计数，跳过。
            last = _parse_moment(existing.updated_at)
            if last is not None and (
                build_windows([last], window_minutes)[0] == current_window
            ):
                continue
            row = repo.upsert(
                first,
                second,
                window_count=int(existing.window_count) + 1,
                jaccard=float(existing.jaccard),
            )
        else:
            row = repo.upsert(first, second, window_count=1, jaccard=0.0)
        # updated_at 存事件时刻而非墙钟时间：增量计数的去重基准是事件窗口，
        # 若用 func.now()（墙钟），同窗口重复调用永远判不中去重条件。
        # 精确的 updated_at 由夜间全量重算刷新，这里只保证窗口语义正确。
        row.updated_at = moment
        session.flush()
        updated.append((first, second))
    _ = (window_start, window_end)
    return updated


def hints_for_vehicle(
    session: Session, vehicle_id: str, *, limit: int = 5
) -> list[CooccurHint]:
    """为某车辆构造共现证据提示（供 resolver 的 cooccur_hints 参数使用）。

    取与该车共现 Jaccard 最高的若干对，映射到对方车辆的绑定学号；
    对方无绑定学号时跳过（无法指向任何学生，不产生证据）。

    Args:
        session: 数据库会话。
        vehicle_id: 待查询的车辆 ID。
        limit: 最多返回的提示数。

    Returns:
        共现提示列表（按 Jaccard 降序）。
    """
    repo = VehicleCooccurrenceRepository(session)
    hints: list[CooccurHint] = []
    for row in repo.list_for_vehicle(vehicle_id)[:limit]:
        other = row.vehicle_b if row.vehicle_a == vehicle_id else row.vehicle_a
        owner = session.get(Vehicle, other)
        subject = owner.owner_id if owner is not None else None
        if subject is None:
            continue
        hints.append(CooccurHint(vehicle_id=other, subject_id=subject, jaccard=float(row.jaccard)))
    return hints

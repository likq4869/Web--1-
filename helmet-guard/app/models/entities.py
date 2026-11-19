"""现有 6 张表的 ORM 映射。

职责：把现有 SQLite 表结构完整映射为 SQLAlchemy 2.0 ORM 模型。
依赖：sqlalchemy、app.models.base。
边界：只描述表结构；字段的可空性、默认值、CHECK 与 UNIQUE 约束必须与
`app/db.py` 的原生建表语句完全一致，不引入任何新表或新字段。

重要说明：原生表结构中**没有外键约束**（`passes.source_id` 等仅为普通
TEXT 列），因此本模块同样不声明 ForeignKey，也不建立 ORM relationship，
以保证迁移后的实际结构与既有 SQLite 库严格一致。
关联查询统一由仓储层通过显式条件表达式完成。
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# 三态判定取值，与 tracks.py / selfcheck.py 的领域语义一致。
RIDER_STATUS_VALUES = ("helmeted", "bare", "unknown")
# 事件复核状态。
EVENT_STATUS_VALUES = ("pending", "confirmed", "dismissed")
# 提醒记录状态。
ALERT_STATUS_VALUES = ("queued", "played", "expired", "silent")
# 复核结论。
REVIEW_DECISION_VALUES = ("confirmed", "dismissed")


class Source(Base):
    """采集点位表。

    对应原生表 `sources`：记录采集点位的标识、名称与最近在线状态。
    """

    __tablename__ = "sources"

    source_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="online",
        server_default="online",
    )
    last_seen: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[str] = mapped_column(String(255), nullable=False)


class Pass(Base):
    """通行记录表。

    对应原生表 `passes`：每次骑行通过的判定结果，保留原始模型输出便于追溯。
    """

    __tablename__ = "passes"
    __table_args__ = (
        UniqueConstraint("source_id", "run_id", "pass_id", name="uq_passes_source_run_pass"),
        CheckConstraint(
            "rider_status IN ('helmeted','bare','unknown')",
            name="rider_status",
        ),
    )

    pass_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[str] = mapped_column(String(255), nullable=False)
    rider_status: Mapped[str] = mapped_column(String(255), nullable=False)
    model_raw: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
    )
    # 检测框与原图尺寸：P3-2 审批详情渲染「证据帧 + 检测框叠加」所需。
    # boxes 为 JSON 字符串（[{label, confidence, xyxy:[x1,y1,x2,y2]}]），
    # xyxy 为归一化比例（0~1），与 image_width/image_height 共同保证
    # 容器坐标系与原图一致（横竖图不错位）。
    boxes: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(String(255), nullable=False)


class Event(Base):
    """违规候选事件表。

    对应原生表 `events`：仅记录 `bare` 判定形成的候选事件，
    最终结论由人工复核写入，状态机为 pending → confirmed/dismissed。
    """

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','confirmed','dismissed')",
            name="status",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    pass_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    model_label: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
    )
    reason: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
    )
    reviewer: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
    )
    reviewed_at: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[str] = mapped_column(String(255), nullable=False)


class Review(Base):
    """人工复核记录表。

    对应原生表 `reviews`：记录每一次复核动作，形成可审计的复核轨迹。
    """

    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('confirmed','dismissed')",
            name="decision",
        ),
        Index("idx_reviews_event", "event_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    decision: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
    )
    operator: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
    )
    created_at: Mapped[str] = mapped_column(String(255), nullable=False)


class Heartbeat(Base):
    """采集心跳表。

    对应原生表 `heartbeats`：每个采集源一行，保存最近一次心跳与 JSON 明细，
    是 `/health` 判断模型与采集状态的唯一依据。
    """

    __tablename__ = "heartbeats"

    source_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
    )
    mode: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
    )
    updated_at: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
    )


class Alert(Base):
    """现场提醒记录表。

    对应原生表 `alerts`：每个事件最多一条提醒，按状态流转。
    """

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','played','expired','silent')",
            name="status",
        ),
    )

    alert_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="queued",
        server_default="queued",
    )
    note: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
    )
    created_at: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(255), nullable=False)


__all__ = [
    "ALERT_STATUS_VALUES",
    "EVENT_STATUS_VALUES",
    "REVIEW_DECISION_VALUES",
    "RIDER_STATUS_VALUES",
    "Alert",
    "Base",
    "Event",
    "Heartbeat",
    "Pass",
    "Review",
    "Source",
]

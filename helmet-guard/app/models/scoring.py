"""积分域 ORM 映射：积分账户、积分台账（只增不改）、积分规则。

职责：把说明书 §7.2（score_accounts/score_ledger/score_rules）映射为
SQLAlchemy 2.0 ORM 模型，供 Alembic 迁移与仓储层使用。
依赖：sqlalchemy、app.models.base。
边界：只描述表结构与约束；不含业务规则，不执行 I/O。

与说明书 SQL 的差异（工程化增强，迁移中同步落地）：
1. 时间列统一为 `DateTime(timezone=True)` + `server_default=func.now()`；
2. 枚举列统一用 `Enum(..., native_enum=True)`：PG 落为原生 ENUM，
   SQLite 自动退化为 VARCHAR + CHECK；
3. 台账表主键用自增整数（说明书 TEXT ledger_id 在并发下难保证唯一，
   自增主键保证流水严格有序，幂等由 event_id/decision_id 业务键表达）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# 说明书枚举取值：与 §7.2 建表注释一一对应。
SCORE_LEVEL_VALUES = ("S", "A", "B", "C", "D")
SCORE_RULE_TYPE_VALUES = ("deduct", "award", "streak")


class ScoreAccount(Base):
    """积分账户表（一名学生一行，主键为学号）。

    对应说明书 `score_accounts`：当前余额、累计扣分/加分、等级、
    连续合规天数、30 天滚动佩戴率。
    """

    __tablename__ = "score_accounts"

    student_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    balance: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    total_deducted: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    total_awarded: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    level: Mapped[str] = mapped_column(
        Enum(*SCORE_LEVEL_VALUES, name="score_level", native_enum=True, validate_strings=True),
        nullable=False,
        default="B",
        server_default="B",
    )
    streak_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    compliance_rate: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ScoreLedger(Base):
    """积分流水表（只增不改，审计核心）。

    对应说明书 `score_ledger`：change 可正可负，balance_after 为该笔之后余额；
    **应用层禁止 UPDATE/DELETE**（仓储层不提供更新/删除方法）。
    """

    __tablename__ = "score_ledger"
    __table_args__ = (
        Index("ix_ledger_student", "student_id"),
        Index("ix_ledger_time", "effective_at"),
        Index("ix_ledger_event", "event_id"),
    )

    ledger_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False
    )
    change: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(255), nullable=False)
    reason_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decision_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ScoreRule(Base):
    """积分规则表（规则 DSL 的持久化形态）。

    对应说明书 `score_rules`：condition_json 为受限 DSL 的 JSON 形态，
    求值语义见 `app.domain.scoring.evaluate_condition`。
    """

    __tablename__ = "score_rules"
    __table_args__ = (Index("ix_rule_enabled", "enabled"),)

    rule_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    rule_type: Mapped[str] = mapped_column(
        Enum(
            *SCORE_RULE_TYPE_VALUES,
            name="score_rule_type",
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        default="deduct",
        server_default="deduct",
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    condition_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    score_change: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


__all__ = [
    "SCORE_LEVEL_VALUES",
    "SCORE_RULE_TYPE_VALUES",
    "ScoreAccount",
    "ScoreLedger",
    "ScoreRule",
]

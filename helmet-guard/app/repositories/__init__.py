"""仓储层包。

职责：对外提供各实体的仓储实现。
依赖：本包内各仓储模块。
边界：仅做数据访问抽象；不包含业务规则与事务管理。
"""

from app.repositories.alert import AlertRepository
from app.repositories.audit import AuditRepository, CounselorAssignmentRepository
from app.repositories.base import BaseRepository
from app.repositories.cooccurrence import (
    VehicleCooccurrenceRepository,
    normalize_pair,
)
from app.repositories.event import EventRepository
from app.repositories.identity import IdentityRepository
from app.repositories.pass_record import PassRepository
from app.repositories.review import ReviewRepository
from app.repositories.scoring import (
    ScoreAccountRepository,
    ScoreLedgerRepository,
    ScoreRuleRepository,
)
from app.repositories.vehicle import VehicleRepository

__all__ = [
    "AlertRepository",
    "AuditRepository",
    "BaseRepository",
    "CounselorAssignmentRepository",
    "EventRepository",
    "IdentityRepository",
    "PassRepository",
    "ReviewRepository",
    "ScoreAccountRepository",
    "ScoreLedgerRepository",
    "ScoreRuleRepository",
    "VehicleCooccurrenceRepository",
    "VehicleRepository",
    "normalize_pair",
]

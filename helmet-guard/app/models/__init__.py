"""ORM 模型包。

职责：汇总所有 ORM 映射并暴露统一的 `Base.metadata`。
依赖：app.models.base、app.models.entities。
边界：仅做模型导出；导入本包不得建立数据库连接。
"""

from app.models.appeal import APPEAL_STATUS_VALUES, Appeal
from app.models.base import Base, IdMixin, TimestampMixin
from app.models.decision import (
    DECISION_ACTION_VALUES,
    DECISION_LEVEL_VALUES,
    DECISION_STATUS_VALUES,
    FEEDBACK_SOURCE_VALUES,
    REVIEW_ACTION_VALUES,
    Decision,
    FeedbackSample,
    ReviewLog,
)
from app.models.entities import (
    Alert,
    Event,
    Heartbeat,
    Pass,
    Review,
    Source,
)
from app.models.identity import (
    ORG_UNIT_TYPE_VALUES,
    AuditLog,
    CounselorAssignment,
    IdentityResolution,
    OrgUnit,
    PendingIdentity,
    Student,
    User,
    Vehicle,
    VehicleCooccurrence,
)
from app.models.model_registry import MODEL_TASK_VALUES, ModelVersion
from app.models.monitor import CameraPoint
from app.models.scoring import (
    SCORE_LEVEL_VALUES,
    SCORE_RULE_TYPE_VALUES,
    ScoreAccount,
    ScoreLedger,
    ScoreRule,
)

__all__ = [
    "APPEAL_STATUS_VALUES",
    "CameraPoint",
    "DECISION_ACTION_VALUES",
    "DECISION_LEVEL_VALUES",
    "DECISION_STATUS_VALUES",
    "FEEDBACK_SOURCE_VALUES",
    "REVIEW_ACTION_VALUES",
    "Alert",
    "Appeal",
    "AuditLog",
    "Base",
    "CounselorAssignment",
    "Decision",
    "Event",
    "FeedbackSample",
    "Heartbeat",
    "IdMixin",
    "IdentityResolution",
    "MODEL_TASK_VALUES",
    "ModelVersion",
    "ORG_UNIT_TYPE_VALUES",
    "OrgUnit",
    "Pass",
    "PendingIdentity",
    "Review",
    "ReviewLog",
    "SCORE_LEVEL_VALUES",
    "SCORE_RULE_TYPE_VALUES",
    "ScoreAccount",
    "ScoreLedger",
    "ScoreRule",
    "Source",
    "Student",
    "TimestampMixin",
    "User",
    "Vehicle",
    "VehicleCooccurrence",
]

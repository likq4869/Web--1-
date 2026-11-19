"""审批详情组装：把决策、事件、身份、学生、申诉聚合成一份可审阅载荷。

职责：为审批中心详情接口一次性取齐所需信息（避免前端多次往返），
并派生风险提示（历史申诉成立次数、重复违规、身份置信度不足等）。
依赖：sqlalchemy 会话、app.models.*。
边界：只读；不做审批动作（由 ReviewService 负责）；不写库。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.appeal import Appeal
from app.models.decision import Decision
from app.models.entities import Event, Pass
from app.models.identity import IdentityResolution, Student
from app.models.scoring import ScoreAccount


def _as_utc(moment: datetime | None) -> datetime | None:
    """把 naive 时间视为 UTC。"""
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def _parse_boxes(raw: str | None) -> list[dict[str, Any]]:
    """解析持久化的检测框 JSON。

    落库格式为 `[{"label", "confidence", "xyxy":[x1,y1,x2,y2]}]`，
    xyxy 为归一化比例（0~1）。此处做容错解析：脏数据只丢弃该条，
    不让证据缺失拖垮整个详情接口。

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


class ReviewDetailService:
    """审批详情组装服务。"""

    def __init__(self, session: Session) -> None:
        """初始化服务。

        Args:
            session: 数据库会话。
        """
        self.session = session

    # ------------------------------------------------------------------
    # 各部分载荷
    # ------------------------------------------------------------------

    def event_payload(self, event_id: str) -> dict[str, Any] | None:
        """组装事件载荷（事件字段 + 证据引用）。

        Args:
            event_id: 事件 ID。

        Returns:
            事件字典；无对应事件时返回 None。
        """
        event = self.session.get(Event, event_id)
        if event is None:
            return None
        return {
            "event_id": str(event.event_id),
            "pass_id": str(event.pass_id),
            "source_id": str(event.source_id),
            "run_id": str(event.run_id),
            "occurred_at": event.occurred_at,
            "status": str(event.status),
            "model_label": str(event.model_label),
            "reason": str(event.reason),
            "reviewed_by": str(event.reviewer) if event.reviewer else None,
            "reviewed_at": event.reviewed_at,
            "created_at": event.created_at,
        }

    def evidence_payload(self, event_id: str) -> dict[str, Any]:
        """组装证据载荷（检测框 + 原图尺寸 + 证据引用）。

        审批详情的「证据帧 + 检测框叠加」依赖此载荷：
        检测框为归一化 xyxy（0~1），与 `image_width/image_height`
        共同决定前端容器坐标系，保证横竖图不错位。

        Args:
            event_id: 事件 ID。

        Returns:
            证据字典；无检测框时 boxes 为空列表、尺寸为 None。
        """
        event = self.session.get(Event, event_id)
        if event is None:
            return {"boxes": [], "image_width": None, "image_height": None}
        pass_row = self.session.get(Pass, str(event.pass_id))
        if pass_row is None:
            return {"boxes": [], "image_width": None, "image_height": None}
        return {
            "boxes": _parse_boxes(pass_row.boxes),
            "image_width": int(pass_row.image_width) if pass_row.image_width else None,
            "image_height": int(pass_row.image_height) if pass_row.image_height else None,
        }

    def identity_payload(self, event_id: str) -> dict[str, Any] | None:
        """组装身份判定载荷（方法 + 各证据置信度）。

        Args:
            event_id: 事件 ID。

        Returns:
            身份判定字典；无判定记录时返回 None。
        """
        statement = (
            select(IdentityResolution)
            .where(IdentityResolution.event_id == event_id)
            .order_by(IdentityResolution.id.desc())
            .limit(1)
        )
        row = self.session.execute(statement).scalar_one_or_none()
        if row is None:
            return None
        return {
            "method": str(row.method) if row.method else None,
            "confidence": float(row.confidence),
            "plate_confidence": float(row.plate_conf),
            "appearance_confidence": float(row.appearance_conf),
            "cooccur_confidence": float(row.cooccur_conf),
            "matched_count": int(row.matched_count),
            "vehicle_id": str(row.vehicle_id) if row.vehicle_id else None,
            "subject_id": str(row.subject_id) if row.subject_id else None,
            "snapshot_id": str(row.snapshot_id) if row.snapshot_id else None,
            "created_at": row.created_at,
        }

    def student_payload(self, student_id: str | None) -> dict[str, Any] | None:
        """组装学生载荷（基本信息 + 当前积分 + 30 天佩戴率 + 历史违规）。

        Args:
            student_id: 学号；为空时返回 None。

        Returns:
            学生字典；无该学生时返回 None。
        """
        if not student_id:
            return None
        student = self.session.get(Student, student_id)
        if student is None:
            return None
        account = self.session.get(ScoreAccount, student_id)
        stats = self._student_violation_stats(student_id)
        return {
            "student_id": str(student.student_id),
            "name": str(student.name),
            "college": str(student.college) if student.college else None,
            "class_name": str(student.class_name) if student.class_name else None,
            "grade": str(student.grade) if student.grade else None,
            "status": str(student.status),
            "balance": int(account.balance) if account is not None else None,
            "level": str(account.level) if account is not None else None,
            "streak_days": int(account.streak_days) if account is not None else None,
            "compliance_rate": (
                round(float(account.compliance_rate), 4)
                if account is not None
                else None
            ),
            "violation_count_30d": stats["violation_count_30d"],
            "violation_count_total": stats["violation_count_total"],
        }

    def _student_violation_stats(self, student_id: str) -> dict[str, int]:
        """统计学生 30 天内与累计违规数（已生效口径）。

        Args:
            student_id: 学号。

        Returns:
            ``{"violation_count_30d", "violation_count_total"}``。
        """
        effective = (
            "APPROVED",
            "ADJUSTED",
            "AUTO_APPROVED",
            "APPEALING",
            "APPEAL_REJECTED",
        )
        since = datetime.now(UTC) - timedelta(days=30)
        since_naive = since.replace(tzinfo=None)
        total_stmt = select(func.count()).select_from(Decision).where(
            Decision.student_id == student_id,
            Decision.status.in_(effective),
            Decision.level.in_(("L2", "L3")),
        )
        recent_stmt = select(func.count()).select_from(Decision).where(
            Decision.student_id == student_id,
            Decision.status.in_(effective),
            Decision.level.in_(("L2", "L3")),
            Decision.created_at >= since_naive,
        )
        return {
            "violation_count_30d": int(self.session.execute(recent_stmt).scalar_one()),
            "violation_count_total": int(self.session.execute(total_stmt).scalar_one()),
        }

    def appeal_stats(self, student_id: str | None) -> dict[str, int]:
        """统计学生申诉情况（成立次数 / 待处理数）。

        Args:
            student_id: 学号。

        Returns:
            ``{"upheld_count", "pending_count"}``。
        """
        if not student_id:
            return {"upheld_count": 0, "pending_count": 0}
        upheld_stmt = select(func.count()).select_from(Appeal).where(
            Appeal.student_id == student_id, Appeal.status == "upheld"
        )
        pending_stmt = select(func.count()).select_from(Appeal).where(
            Appeal.student_id == student_id,
            Appeal.status.in_(("pending", "submitted", "processing")),
        )
        return {
            "upheld_count": int(self.session.execute(upheld_stmt).scalar_one()),
            "pending_count": int(self.session.execute(pending_stmt).scalar_one()),
        }

    # ------------------------------------------------------------------
    # 风险提示
    # ------------------------------------------------------------------

    def risk_hints(
        self,
        decision: Decision,
        *,
        identity: dict[str, Any] | None,
        student: dict[str, Any] | None,
    ) -> list[dict[str, str]]:
        """派生风险提示（供审批人判断是否降档）。

        Args:
            decision: 决策行。
            identity: 身份判定载荷。
            student: 学生载荷。

        Returns:
            风险提示列表（``{"code", "text", "level"}``）。
        """
        hints: list[dict[str, str]] = []
        level = str(decision.level)

        appeal_stats = self.appeal_stats(
            str(decision.student_id) if decision.student_id else None
        )
        upheld = appeal_stats["upheld_count"]
        if upheld > 0:
            hints.append(
                {
                    "code": "APPEAL_UPRELD_HISTORY",
                    "text": f"该学生历史申诉成立 {upheld} 次，建议谨慎核定档位",
                    "level": "warning",
                }
            )

        if identity is not None:
            confidence = float(identity.get("confidence", 0.0))
            if confidence < 0.60:
                hints.append(
                    {
                        "code": "IDENTITY_LOW",
                        "text": f"身份置信度 {confidence:.2f} 低于 0.60 阈值，建议先核实身份",
                        "level": "danger",
                    }
                )
            elif confidence < 0.85:
                hints.append(
                    {
                        "code": "IDENTITY_MEDIUM",
                        "text": f"身份置信度 {confidence:.2f} 属中等，建议结合证据确认",
                        "level": "warning",
                    }
                )

        if student is not None:
            count_30d = int(student.get("violation_count_30d", 0))
            if count_30d >= 3 and level == "L3":
                hints.append(
                    {
                        "code": "HIGH_FREQUENCY",
                        "text": f"近 30 天已记录 {count_30d} 次扣分事件，档位与频次相符",
                        "level": "neutral",
                    }
                )
            elif count_30d == 0 and level in ("L2", "L3"):
                hints.append(
                    {
                        "code": "FIRST_OFFENSE",
                        "text": "近 30 天无扣分记录，属于首次出现，建议考虑降档",
                        "level": "warning",
                    }
                )

        decision_conf = decision.confidence
        if decision_conf is not None and float(decision_conf) < 0.60:
            hints.append(
                {
                    "code": "MODEL_LOW_CONFIDENCE",
                    "text": f"模型置信度 {float(decision_conf):.2f} 偏低，证据强度不足",
                    "level": "danger",
                }
            )

        if not hints:
            hints.append(
                {
                    "code": "NO_RISK",
                    "text": "未发现明显风险项，可按系统建议档位处理",
                    "level": "neutral",
                }
            )
        return hints

    # ------------------------------------------------------------------
    # 汇总
    # ------------------------------------------------------------------

    def build_detail(
        self, decision: Decision, review_logs: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """组装完整审批详情载荷。

        Args:
            decision: 决策行。
            review_logs: 审批轨迹。

        Returns:
            详情字典（decision/event/identity/student/risk_hints/review_logs）。
        """
        event_id = str(decision.event_id)
        identity = self.identity_payload(event_id)
        student = self.student_payload(
            str(decision.student_id) if decision.student_id else None
        )
        event = self.event_payload(event_id)
        evidence = self.evidence_payload(event_id)
        # 决策自身写入的 evidence_refs 与检测框证据合并：
        # 前者含 snapshot_id / 熔断器状态，后者含 boxes / 原图尺寸。
        base_refs = decision.evidence_refs if isinstance(decision.evidence_refs, dict) else {}
        merged_refs: dict[str, Any] = {**base_refs, **evidence}
        return {
            "decision": decision,
            "event": event,
            "identity_resolution": identity,
            "student": student,
            "evidence_refs": merged_refs,
            "risk_hints": self.risk_hints(
                decision, identity=identity, student=student
            ),
            "review_logs": review_logs,
        }


__all__ = ["ReviewDetailService"]

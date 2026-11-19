"""审计与辅导员仓储：只增审计写入与班级范围查询。

职责：封装 audit_logs / counselor_assignments 的数据访问。
依赖：sqlalchemy、app.models.identity。
边界：只做数据访问；权限判定由服务层负责。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from app.models.identity import AuditLog, CounselorAssignment
from app.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditLog]):
    """审计日志仓储（只增不改，不提供 update/delete）。"""

    model = AuditLog
    id_field = "id"

    def log(
        self,
        *,
        actor: str,
        role: str,
        action: str,
        object_type: str | None = None,
        object_id: str | None = None,
        ip: str | None = None,
        result: str = "ok",
        detail: str | None = None,
    ) -> AuditLog:
        """写入一条审计记录。

        Args:
            actor: 操作人 ID。
            role: 操作人角色。
            action: 动作标识（如 identities.bind）。
            object_type: 对象类型。
            object_id: 对象 ID。
            ip: 客户端 IP。
            result: 结果（ok/denied/error）。
            detail: 摘要（已脱敏，不得含密码与完整手机号）。

        Returns:
            持久化后的审计记录。
        """
        return self.create(
            AuditLog(
                actor=actor,
                role=role,
                action=action,
                object_type=object_type,
                object_id=object_id,
                ip=ip,
                result=result,
                detail=detail,
            )
        )

    def list_with_filters(
        self,
        *,
        actor: str | None = None,
        action: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[AuditLog]:
        """按条件分页列出审计日志（创建时间倒序，只读）。

        Args:
            actor: 操作人精确匹配。
            action: 动作前缀匹配（如 `scoring.` 查全域积分动作）。
            start: 创建时间起点（含）。
            end: 创建时间终点（含）。
            limit: 最大返回条数。
            offset: 跳过的记录数。

        Returns:
            审计记录列表。
        """
        statement = select(AuditLog)
        if actor:
            statement = statement.where(AuditLog.actor == actor)
        if action:
            statement = statement.where(AuditLog.action.like(f"{action}%"))
        if start is not None:
            statement = statement.where(AuditLog.created_at >= start)
        if end is not None:
            statement = statement.where(AuditLog.created_at <= end)
        statement = statement.order_by(AuditLog.id.desc()).limit(limit).offset(offset)
        return list(self.session.execute(statement).scalars().all())

    def count_with_filters(
        self,
        *,
        actor: str | None = None,
        action: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> int:
        """统计符合条件的审计记录数（与列表共用口径）。"""
        statement = select(func.count()).select_from(AuditLog)
        if actor:
            statement = statement.where(AuditLog.actor == actor)
        if action:
            statement = statement.where(AuditLog.action.like(f"{action}%"))
        if start is not None:
            statement = statement.where(AuditLog.created_at >= start)
        if end is not None:
            statement = statement.where(AuditLog.created_at <= end)
        return int(self.session.execute(statement).scalar_one())


class CounselorAssignmentRepository(BaseRepository[CounselorAssignment]):
    """辅导员班级映射仓储。"""

    model = CounselorAssignment
    id_field = "user_id"

    def list_classes(self, user_id: str) -> list[str]:
        """列出某辅导员所带班级。

        Args:
            user_id: 辅导员用户 ID。

        Returns:
            班级名列表（排序后，保证确定性）。
        """
        statement = (
            select(CounselorAssignment.class_name)
            .where(CounselorAssignment.user_id == user_id)
            .order_by(CounselorAssignment.class_name)
        )
        rows = self.session.execute(statement).all()
        return [str(row[0]) for row in rows]

    def assign(self, user_id: str, class_name: str) -> CounselorAssignment:
        """为辅导员分配一个班级（幂等：已存在则直接返回）。

        Args:
            user_id: 辅导员用户 ID。
            class_name: 班级名。

        Returns:
            映射记录。
        """
        existing = self.session.get(CounselorAssignment, (user_id, class_name))
        if existing is not None:
            return existing
        return self.create(
            CounselorAssignment(user_id=user_id, class_name=class_name)
        )

    def count_students_in_scope(self, user_id: str) -> int:
        """统计该辅导员所带班级的学生数（范围校验用）。

        Args:
            user_id: 辅导员用户 ID。

        Returns:
            学生总数。
        """
        from app.models.identity import Student

        classes = self.list_classes(user_id)
        if not classes:
            return 0
        statement = select(func.count()).select_from(Student).where(
            Student.class_name.in_(classes)
        )
        return int(self.session.execute(statement).scalar_one())

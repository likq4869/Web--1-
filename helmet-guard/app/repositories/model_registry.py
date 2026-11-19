"""模型注册仓储：模型版本的查询与激活切换。

职责：封装 model_versions 表的读取与激活态切换。
依赖：sqlalchemy、app.models.model_registry。
边界：只做数据访问；激活互斥与审计由服务层负责。
"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult

from app.models.model_registry import ModelVersion
from app.repositories.base import BaseRepository


class ModelVersionRepository(BaseRepository[ModelVersion]):
    """模型版本仓储。"""

    model = ModelVersion
    id_field = "model_id"

    def list_all(self, *, task: str | None = None) -> list[ModelVersion]:
        """列出全部模型版本（按创建时间倒序，激活行置顶由调用方排序）。

        Args:
            task: 任务类型过滤（detect/plate/head_cls/reid）；为空不限。

        Returns:
            模型版本列表（激活优先，其次创建时间倒序）。
        """
        statement = select(ModelVersion)
        if task:
            statement = statement.where(ModelVersion.task == task)
        statement = statement.order_by(
            ModelVersion.is_active.desc(), ModelVersion.created_at.desc()
        )
        return list(self.session.execute(statement).scalars().all())

    def count_all(self, *, task: str | None = None) -> int:
        """统计模型版本数（与列表共用过滤口径）。"""
        statement = select(func.count()).select_from(ModelVersion)
        if task:
            statement = statement.where(ModelVersion.task == task)
        return int(self.session.execute(statement).scalar_one())

    def deactivate_task(self, task: str) -> int:
        """关闭某任务下全部激活行（激活切换第一步）。

        Args:
            task: 任务类型。

        Returns:
            受影响行数。
        """
        statement = (
            update(ModelVersion)
            .where(ModelVersion.task == task, ModelVersion.is_active == True)  # noqa: E712
            .values(is_active=False)
        )
        result = self.session.execute(statement)
        if isinstance(result, CursorResult):
            return int(result.rowcount or 0)
        return 0

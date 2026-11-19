"""仓储层基座：通用 CRUD 与会话管理。

职责：为 ORM 模型提供参数化的通用数据访问能力。
依赖：sqlalchemy、app.models.base。
边界：只做数据访问；不包含业务规则，不自行提交事务（由调用方控制）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, Generic, TypeVar

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)

# 本模块的 `list` 方法名遮蔽了内置 list，这里用别名恢复类型注解能力。
ModelList = list[ModelT]


class BaseRepository(Generic[ModelT]):
    """通用仓储基类。

    提供 `get_by_id` / `list` / `create` / `update` / `delete` 等基础操作。
    所有查询均使用 SQLAlchemy 表达式，参数由驱动绑定，不做字符串拼接。
    """

    model: ClassVar[type[ModelT]]
    #: 主键列名；默认取模型第一个主键列。
    id_field: ClassVar[str] = "id"

    def __init__(self, session: Session) -> None:
        """初始化仓储。

        Args:
            session: 数据库会话；由调用方控制事务生命周期。
        """
        self.session = session

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_by_id(self, entity_id: object) -> ModelT | None:
        """按主键获取单条记录。

        Args:
            entity_id: 主键值。

        Returns:
            记录对象；不存在时返回 None。
        """
        return self.session.get(self.model, entity_id)

    def find_by(self, **filters: Any) -> ModelT | None:
        """按等值条件获取单条记录。

        Args:
            **filters: 列名 → 等值条件。

        Returns:
            第一条匹配记录；无匹配时返回 None。
        """
        statement = select(self.model).filter_by(**filters).limit(1)
        return self.session.execute(statement).scalar_one_or_none()

    def list(
        self,
        *,
        filters: dict[str, Any] | None = None,
        order_by: Sequence[Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> ModelList[ModelT]:
        """按条件查询多条记录。

        Args:
            filters: 等值条件字典。
            order_by: 排序表达式序列。
            limit: 最大返回条数。
            offset: 跳过的记录数。

        Returns:
            记录列表。
        """
        statement = select(self.model)
        if filters:
            statement = statement.filter_by(**filters)
        if order_by:
            statement = statement.order_by(*order_by)
        if offset:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        result = self.session.execute(statement)
        return list(result.scalars().all())

    def count(self, *, filters: dict[str, Any] | None = None) -> int:
        """统计符合条件的记录数。

        Args:
            filters: 等值条件字典。

        Returns:
            记录总数。
        """
        statement = select(func.count()).select_from(self.model)
        if filters:
            statement = statement.filter_by(**filters)
        result = self.session.execute(statement)
        return int(result.scalar_one())

    def exists(self, **filters: Any) -> bool:
        """判断是否存在符合条件的记录。

        Args:
            **filters: 列名 → 等值条件。

        Returns:
            存在返回 True。
        """
        statement = select(func.count()).select_from(self.model).filter_by(**filters).limit(1)
        result = self.session.execute(statement)
        return int(result.scalar_one()) > 0

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def create(self, entity: ModelT) -> ModelT:
        """新增一条记录。

        Args:
            entity: 待持久化的模型实例。

        Returns:
            持久化后的同一实例。
        """
        self.session.add(entity)
        self.session.flush()
        return entity

    def bulk_create(self, entities: Sequence[ModelT]) -> ModelList[ModelT]:
        """批量新增记录。

        Args:
            entities: 待持久化的模型实例序列。

        Returns:
            持久化后的实例列表。
        """
        items = list(entities)
        self.session.add_all(items)
        self.session.flush()
        return items

    def update(self, entity: ModelT, **values: Any) -> ModelT:
        """更新记录字段。

        Args:
            entity: 已持久化的模型实例。
            **values: 待更新的列名与新值。

        Returns:
            更新后的同一实例。
        """
        for key, value in values.items():
            setattr(entity, key, value)
        self.session.flush()
        return entity

    def bulk_update(self, filters: dict[str, Any], **values: Any) -> int:
        """按条件批量更新。

        Args:
            filters: 等值条件字典。
            **values: 待更新的列名与新值。

        Returns:
            受影响的记录数。
        """
        statement = sa_update(self.model).filter_by(**filters).values(**values)
        result = self.session.execute(statement)
        if isinstance(result, CursorResult):
            return int(result.rowcount or 0)
        return 0

    def delete(self, entity: ModelT) -> None:
        """删除一条记录。

        Args:
            entity: 待删除的模型实例。
        """
        self.session.delete(entity)
        self.session.flush()

    def delete_by(self, **filters: Any) -> int:
        """按条件批量删除。

        Args:
            **filters: 列名 → 等值条件。

        Returns:
            受影响的记录数。
        """
        statement = sa_delete(self.model).filter_by(**filters)
        result = self.session.execute(statement)
        if isinstance(result, CursorResult):
            return int(result.rowcount or 0)
        return 0

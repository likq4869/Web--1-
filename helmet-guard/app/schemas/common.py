"""通用 Pydantic 模型：分页响应、错误响应与分页查询参数。

职责：提供跨模块复用的请求/响应模型。
依赖：pydantic。
边界：只描述数据结构与校验规则；不含业务逻辑，不依赖数据库。
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    """错误详情。

    Attributes:
        code: 机器可读错误码。
        message: 面向用户的可读说明。
        details: 可选补充信息。
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=500)
    details: dict[str, str] | None = None


class ErrorResponse(BaseModel):
    """统一错误响应体。

    Attributes:
        error: 错误详情。
        trace_id: 请求追踪 ID，便于日志关联。
    """

    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail
    trace_id: str | None = Field(default=None, max_length=64)


class PageParams(BaseModel):
    """分页查询参数基类。

    Attributes:
        page: 页码，从 1 开始。
        page_size: 每页条数。
    """

    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        """返回 SQL OFFSET 值。"""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """返回 SQL LIMIT 值。"""
        return self.page_size


class Page(BaseModel, Generic[T]):
    """分页响应。

    Attributes:
        items: 当前页数据。
        total: 总条数。
        page: 当前页码。
        page_size: 每页条数。
    """

    model_config = ConfigDict(extra="forbid")

    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)

    @classmethod
    def create(
        cls,
        items: list[T],
        total: int,
        params: PageParams,
    ) -> Page[T]:
        """按分页参数构造响应。

        Args:
            items: 当前页数据。
            total: 总条数。
            params: 分页参数。

        Returns:
            分页响应实例。
        """
        return cls(items=items, total=total, page=params.page, page_size=params.page_size)

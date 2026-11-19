"""组织单元出入参：五级级联查询。

职责：定义学校/学院/年级/专业/班级级联接口的请求与响应模型。
依赖：pydantic。
边界：只做结构校验；层级合法性由服务层保证。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OrgUnitOut(BaseModel):
    """组织单元视图。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    unit_id: str = Field(description="单元 ID")
    unit_type: str = Field(description="类型：school/college/grade/major/class")
    name: str = Field(description="名称")
    parent_id: str | None = Field(default=None, description="父单元 ID（顶层为空）")
    sort_order: int = Field(default=0, description="同级排序")


class OrgUnitListOut(BaseModel):
    """级联子级列表。"""

    model_config = ConfigDict(extra="forbid")

    items: list[OrgUnitOut] = Field(default_factory=list, description="子单元列表")
    parent_id: str | None = Field(default=None, description="回显父 ID（顶层为空）")

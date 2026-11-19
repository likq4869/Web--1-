"""身份域 Pydantic 出入参模型。

职责：提供车辆档案、身份判定、待绑定池的 API 请求/响应模型。
依赖：pydantic。
边界：只描述数据结构与校验规则；不含业务逻辑，不依赖数据库。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PlateType = Literal["blue", "school", "university", "none"]
OwnerBindType = Literal["registered", "qr", "nfc", "appearance", "cooccur", "manual"]
VehicleStatus = Literal["active", "unbound", "blocked"]
IdentityMethod = Literal["plate", "qr", "nfc", "appearance", "cooccur", "manual", "none"]
PendingStatus = Literal["pending", "resolved", "ignored"]
UserRole = Literal[
    "student", "counselor", "security_officer", "league_officer", "super_admin", "auditor"
]


class VehicleCreateRequest(BaseModel):
    """新建车辆档案请求。

    Attributes:
        vehicle_id: 车辆档案 ID（如 veh_20261115_0001）。
        plate_no: 车牌号，可空（无牌车为空）。
        plate_type: 车牌类型。
        owner_id: 绑定的学生学号，可空（待绑定）。
        owner_bind_type: 绑定方式。
        confidence: 绑定置信度。
        color_hist: 64 维颜色直方图 JSON。
    """

    model_config = ConfigDict(extra="forbid")

    vehicle_id: str = Field(min_length=1, max_length=64)
    plate_no: str | None = Field(default=None, max_length=32)
    plate_type: PlateType | None = None
    owner_id: str | None = Field(default=None, max_length=64)
    owner_bind_type: OwnerBindType | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    color_hist: list[float] | dict[str, Any] | None = None


class VehicleResponse(BaseModel):
    """车辆档案响应。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    vehicle_id: str
    plate_no: str | None = None
    plate_type: PlateType | None = None
    owner_id: str | None = None
    owner_bind_type: OwnerBindType | None = None
    confidence: float
    color_hist: list[float] | dict[str, Any] | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    status: VehicleStatus
    created_at: datetime
    updated_at: datetime


class IdentityResolutionResponse(BaseModel):
    """单次通行身份判定响应（含各证据分值，用于可解释展示）。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    event_id: str
    vehicle_id: str | None = None
    subject_id: str | None = None
    method: IdentityMethod | None = None
    confidence: float
    plate_conf: float
    appearance_conf: float
    cooccur_conf: float
    matched_count: int
    snapshot_id: str | None = None
    created_at: datetime


class PendingIdentityResponse(BaseModel):
    """待绑定车辆池响应。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    vehicle_id: str
    pass_count: int
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    location: str | None = None
    snapshot_id: str | None = None
    status: PendingStatus
    created_at: datetime


class BindVehicleRequest(BaseModel):
    """车辆绑定请求：把车辆绑定到学生。

    Attributes:
        vehicle_id: 车辆档案 ID。
        student_id: 学号。
        method: 绑定方式（人工登记为 manual，其余为证据来源）。
        note: 备注（如登记凭证编号），仅透传不落库到身份域表。
    """

    model_config = ConfigDict(extra="forbid")

    vehicle_id: str = Field(min_length=1, max_length=64)
    student_id: str = Field(min_length=1, max_length=64)
    method: Literal["registered", "qr", "nfc", "appearance", "cooccur", "manual"] = "manual"
    note: str = Field(default="", max_length=500)


class BindVehicleBody(BaseModel):
    """绑定请求体（vehicle_id 取自路径，请求体只含学生与方式）。"""

    model_config = ConfigDict(extra="forbid")

    student_id: str = Field(min_length=1, max_length=64)
    method: Literal["registered", "qr", "nfc", "appearance", "cooccur", "manual"] = "manual"
    note: str = Field(default="", max_length=500)


class StudentResponse(BaseModel):
    """学生档案响应。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    student_id: str
    user_id: str | None = None
    name: str
    gender: str | None = None
    school: str | None = None
    college: str | None = None
    major: str | None = None
    class_name: str | None = None
    grade: str | None = None
    dorm_id: str | None = None
    phone: str | None = None
    avatar: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class StudentDetailResponse(BaseModel):
    """学生详情聚合响应。"""

    model_config = ConfigDict(extra="forbid")

    student: StudentResponse
    vehicles: list[VehicleResponse]
    resolutions: list[IdentityResolutionResponse]


class VehicleDetailResponse(BaseModel):
    """车辆详情聚合响应。"""

    model_config = ConfigDict(extra="forbid")

    vehicle: VehicleResponse
    resolutions: list[IdentityResolutionResponse]


class PendingListItem(BaseModel):
    """待识别池列表项（附候选学生提示）。"""

    model_config = ConfigDict(extra="forbid")

    pending: PendingIdentityResponse
    candidates: list[dict[str, str | float]] = Field(default_factory=list)


class ImportRowErrorResponse(BaseModel):
    """单行导入错误。"""

    model_config = ConfigDict(extra="forbid")

    row: int
    student_id: str
    message: str


class ImportReportResponse(BaseModel):
    """导入结果报告。"""

    model_config = ConfigDict(extra="forbid")

    total: int
    created: int
    updated: int
    errors: list[ImportRowErrorResponse] = Field(default_factory=list)


class ImportAcceptedResponse(BaseModel):
    """大文件异步受理响应。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    status: str = "running"


class ImportTaskResponse(BaseModel):
    """导入任务状态查询响应。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    status: str
    report: ImportReportResponse | None = None


__all__ = [
    "BindVehicleBody",
    "BindVehicleRequest",
    "IdentityMethod",
    "IdentityResolutionResponse",
    "ImportAcceptedResponse",
    "ImportReportResponse",
    "ImportRowErrorResponse",
    "ImportTaskResponse",
    "OwnerBindType",
    "PendingIdentityResponse",
    "PendingListItem",
    "PendingStatus",
    "PlateType",
    "StudentDetailResponse",
    "StudentResponse",
    "UserRole",
    "VehicleCreateRequest",
    "VehicleDetailResponse",
    "VehicleResponse",
    "VehicleStatus",
]

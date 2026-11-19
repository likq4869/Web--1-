"""Pydantic 出入参模型包。

职责：对外提供 API 请求/响应模型。
依赖：本包内各 schema 模块。
边界：仅做数据校验与序列化；不含业务规则与 I/O。
"""

from app.schemas.common import ErrorDetail, ErrorResponse, Page, PageParams
from app.schemas.decision import (
    AppealResolveBody,
    AppealResponse,
    AppealSubmitBody,
    ApproveBody,
    BatchApproveBody,
    BatchApproveItem,
    DecisionDetailResponse,
    DecisionListItem,
    FactorResponse,
    RejectBody,
)
from app.schemas.identity import (
    BindVehicleBody,
    BindVehicleRequest,
    IdentityMethod,
    IdentityResolutionResponse,
    ImportAcceptedResponse,
    ImportReportResponse,
    ImportRowErrorResponse,
    ImportTaskResponse,
    OwnerBindType,
    PendingIdentityResponse,
    PendingListItem,
    PendingStatus,
    PlateType,
    StudentDetailResponse,
    StudentResponse,
    UserRole,
    VehicleCreateRequest,
    VehicleDetailResponse,
    VehicleResponse,
    VehicleStatus,
)

__all__ = [
    "AppealResolveBody",
    "AppealResponse",
    "AppealSubmitBody",
    "ApproveBody",
    "BatchApproveBody",
    "BatchApproveItem",
    "BindVehicleBody",
    "BindVehicleRequest",
    "DecisionDetailResponse",
    "DecisionListItem",
    "ErrorDetail",
    "ErrorResponse",
    "FactorResponse",
    "IdentityMethod",
    "RejectBody",
    "IdentityResolutionResponse",
    "ImportAcceptedResponse",
    "ImportReportResponse",
    "ImportRowErrorResponse",
    "ImportTaskResponse",
    "OwnerBindType",
    "Page",
    "PageParams",
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

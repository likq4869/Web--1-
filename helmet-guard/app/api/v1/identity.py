"""身份管理 API：待识别池、车辆档案、学生档案与 Excel 导入。

职责：HTTP 解析与响应序列化、分页参数校验、ORM→Schema 转换、事务提交。
依赖：FastAPI、app.core.deps、app.services.identity.admin、app.schemas.identity。
边界：不做业务规则判定；RBAC 与越权 404 由服务层收敛（避免资源存在性泄露）。

权限矩阵（服务层强制，路由层不做二次 403，保证越权一律 404）：
- 读接口（pending/vehicles/students 列表与详情/模板下载/任务查询）：
  super_admin、league_officer、counselor、security_officer、auditor 可访问；
  其余角色（含 student）一律 404。
- 写接口（bind/ignore/import）：
  仅 super_admin、league_officer 可执行；其余一律 404。
- counselor 读学生时仅返回所带班级；详情越出班级返回 404。
- 所有写操作（bind/ignore/import 同步与异步受理）写入 audit_logs。
"""

from __future__ import annotations

from fastapi import APIRouter, File, Query, Request, Response, UploadFile

from app.core.deps import CurrentUserDep, DbSession
from app.core.errors import NotFoundError, ValidationError
from app.schemas.identity import (
    BindVehicleBody,
    IdentityResolutionResponse,
    ImportAcceptedResponse,
    ImportReportResponse,
    ImportRowErrorResponse,
    ImportTaskResponse,
    PendingIdentityResponse,
    PendingListItem,
    StudentDetailResponse,
    StudentResponse,
    VehicleDetailResponse,
    VehicleResponse,
)
from app.services.identity import admin as admin_service

router = APIRouter(prefix="/api/v1/admin", tags=["identity-admin"])

PENDING_SORTS = ("pass_count", "last_seen", "first_seen")
VEHICLE_SORTS = ("last_seen", "first_seen", "vehicle_id")
STUDENT_SORTS = ("student_id", "name", "class_name")

MAX_IMPORT_BYTES = 20 * 1024 * 1024


def _page_params(page: int, page_size: int) -> tuple[int, int]:
    """钳制分页参数（路由层先行校验，服务层二次钳制保证上限）。"""
    return max(1, page), min(max(1, page_size), admin_service.PAGE_SIZE_MAX)


def _order_param(order: str) -> str:
    """归一化排序方向，非法值回退 desc（读接口）由调用方指定默认。"""
    return "asc" if order == "asc" else "desc"


def _client_ip(request: Request) -> str | None:
    """提取客户端 IP（审计用，直连时取 client.host）。"""
    if request.client is not None:
        return request.client.host
    return None


@router.get("/identities/pending")
def list_pending(
    session: DbSession,
    user: CurrentUserDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("pass_count", max_length=32),
    order: str = Query("desc", max_length=8),
    keyword: str | None = Query(None, max_length=64),
    status: str = Query("pending", max_length=32),
) -> dict[str, object]:
    """待识别车辆池（分页+筛选，默认按通行次数倒序）。"""
    scoped = admin_service.to_scoped(user)
    safe_page, safe_size = _page_params(page, page_size)
    safe_sort = sort if sort in PENDING_SORTS else "pass_count"
    rows, total = admin_service.list_pending(
        session,
        scoped,
        page=safe_page,
        page_size=safe_size,
        sort=safe_sort,
        order=_order_param(order),
        keyword=keyword,
        status=status,
    )
    items = [
        PendingListItem(
            pending=PendingIdentityResponse.model_validate(row),
            candidates=[],
        ).model_dump(mode="json")
        for row in rows
    ]
    return {"items": items, "total": total, "page": safe_page, "page_size": safe_size}


@router.post("/identities/{vehicle_id}/bind", status_code=200)
def bind_vehicle(
    vehicle_id: str,
    body: BindVehicleBody,
    session: DbSession,
    user: CurrentUserDep,
    request: Request,
) -> dict[str, object]:
    """绑定车辆到学生（仅 super_admin / league_officer，其余 404）。

    事务由服务层收敛（成功提交/失败回滚），路由层只做参数校验与响应序列化。
    """
    scoped = admin_service.to_scoped(user)
    vehicle = admin_service.bind_vehicle(
        session,
        scoped,
        vehicle_id=vehicle_id,
        student_id=body.student_id,
        method=body.method,
        note=body.note,
        ip=_client_ip(request),
    )
    return {"vehicle": VehicleResponse.model_validate(vehicle).model_dump(mode="json")}


@router.post("/identities/{vehicle_id}/ignore", status_code=200)
def ignore_pending(
    vehicle_id: str,
    session: DbSession,
    user: CurrentUserDep,
    request: Request,
) -> dict[str, object]:
    """忽略待识别车辆（终结该车全部 pending 行）。

    事务由服务层收敛（成功提交/失败回滚），路由层只做参数校验与响应序列化。
    """
    scoped = admin_service.to_scoped(user)
    count = admin_service.ignore_pending(
        session, scoped, vehicle_id=vehicle_id, ip=_client_ip(request)
    )
    return {"vehicle_id": vehicle_id, "ignored": count}


@router.get("/vehicles")
def list_vehicles(
    session: DbSession,
    user: CurrentUserDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("last_seen", max_length=32),
    order: str = Query("desc", max_length=8),
    keyword: str | None = Query(None, max_length=64),
    status: str | None = Query(None, max_length=32),
) -> dict[str, object]:
    """车辆档案列表（默认按最近出现倒序）。"""
    scoped = admin_service.to_scoped(user)
    safe_page, safe_size = _page_params(page, page_size)
    safe_sort = sort if sort in VEHICLE_SORTS else "last_seen"
    rows, total = admin_service.list_vehicles(
        session,
        scoped,
        page=safe_page,
        page_size=safe_size,
        sort=safe_sort,
        order=_order_param(order),
        keyword=keyword,
        status=status,
    )
    items = [VehicleResponse.model_validate(row).model_dump(mode="json") for row in rows]
    return {"items": items, "total": total, "page": safe_page, "page_size": safe_size}


@router.get("/vehicles/{vehicle_id}")
def get_vehicle_detail(
    vehicle_id: str,
    session: DbSession,
    user: CurrentUserDep,
) -> dict[str, object]:
    """车辆详情（含匹配历史时间线）。"""
    scoped = admin_service.to_scoped(user)
    detail = admin_service.get_vehicle_detail(session, scoped, vehicle_id=vehicle_id)
    payload = VehicleDetailResponse(
        vehicle=VehicleResponse.model_validate(detail.vehicle),
        resolutions=[
            IdentityResolutionResponse.model_validate(item) for item in detail.resolutions
        ],
    )
    return payload.model_dump(mode="json")


@router.get("/students")
def list_students(
    session: DbSession,
    user: CurrentUserDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("student_id", max_length=32),
    order: str = Query("asc", max_length=8),
    keyword: str | None = Query(None, max_length=64),
    college: str | None = Query(None, max_length=64),
    status: str | None = Query(None, max_length=32),
) -> dict[str, object]:
    """学生列表（counselor 仅返回所带班级）。"""
    scoped = admin_service.to_scoped(user)
    safe_page, safe_size = _page_params(page, page_size)
    safe_sort = sort if sort in STUDENT_SORTS else "student_id"
    rows, total = admin_service.list_students(
        session,
        scoped,
        page=safe_page,
        page_size=safe_size,
        sort=safe_sort,
        order=_order_param(order),
        keyword=keyword,
        college=college,
        status=status,
    )
    items = [StudentResponse.model_validate(row).model_dump(mode="json") for row in rows]
    return {"items": items, "total": total, "page": safe_page, "page_size": safe_size}


@router.get("/students/template")
def download_import_template(
    session: DbSession,
    user: CurrentUserDep,
) -> Response:
    """下载学生导入模板（xlsx，8 列：学号/姓名/性别/学院/班级/年级/宿舍/手机号）。"""
    scoped = admin_service.to_scoped(user)
    # 模板下载同样需要读权限；非管理角色一律 404。
    admin_service.list_students(session, scoped, page=1, page_size=1)
    data = admin_service.build_import_template()
    headers = {"Content-Disposition": 'attachment; filename="students-template.xlsx"'}
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.get("/students/{student_id}")
def get_student_detail(
    student_id: str,
    session: DbSession,
    user: CurrentUserDep,
) -> dict[str, object]:
    """学生详情（越出辅导员班级返回 404，避免存在性泄露）。"""
    scoped = admin_service.to_scoped(user)
    detail = admin_service.get_student_detail(session, scoped, student_id=student_id)
    payload = StudentDetailResponse(
        student=StudentResponse.model_validate(detail.student),
        vehicles=[VehicleResponse.model_validate(v) for v in detail.vehicles],
        resolutions=[
            IdentityResolutionResponse.model_validate(item) for item in detail.resolutions
        ],
    )
    return payload.model_dump(mode="json")


@router.post("/students/import")
def import_students(
    session: DbSession,
    user: CurrentUserDep,
    request: Request,
    file: UploadFile = File(...),
) -> Response:
    """批量导入学生（Excel）：小文件同步返回逐行报告，大文件返回 task_id 轮询。

    判定规则：解析后总行数（有效+错误）> 500 走后台任务，前端用
    `GET /api/v1/admin/students/import/tasks/{task_id}` 轮询。

    事务由服务层收敛（成功提交/失败回滚），路由层只做参数校验与响应序列化。
    """
    scoped = admin_service.to_scoped(user)
    filename = (file.filename or "").lower()
    if not filename.endswith((".xlsx", ".xlsm")):
        raise ValidationError("仅支持 xlsx 格式，请下载模板后填写")
    try:
        data = file.file.read()
    except (OSError, ValueError) as exc:
        raise ValidationError(f"文件读取失败：{exc}") from exc
    if not data:
        raise ValidationError("文件为空，请选择填写好的模板")
    if len(data) > MAX_IMPORT_BYTES:
        raise ValidationError("文件超过 20MB 上限，请分批导入")
    if not isinstance(data, bytes):
        raise ValidationError("文件读取失败，请重新上传")
    result = admin_service.import_students(
        session, scoped, data, ip=_client_ip(request)
    )
    if isinstance(result, str):
        accepted = ImportAcceptedResponse(task_id=result, status="running")
        return Response(
            content=accepted.model_dump_json(),
            status_code=202,
            media_type="application/json",
        )
    payload = ImportReportResponse(
        total=result.total,
        created=result.created,
        updated=result.updated,
        errors=[
            ImportRowErrorResponse(row=e.row, student_id=e.student_id, message=e.message)
            for e in result.errors
        ],
    )
    return Response(content=payload.model_dump_json(), media_type="application/json")


@router.get("/students/import/tasks/{task_id}")
def get_import_task(
    task_id: str,
    user: CurrentUserDep,
) -> dict[str, object]:
    """查询大文件导入任务状态（running/done/failed，done 时附逐行报告）。"""
    scoped = admin_service.to_scoped(user)
    # 读权限校验（失败抛 404，不泄露任务存在性）。
    admin_service.require_read(scoped)
    task = admin_service.get_import_task(task_id)
    if task is None:
        raise NotFoundError("请求的资源不存在")
    status = str(task.get("status", "running"))
    report = task.get("report")
    if isinstance(report, admin_service.ImportReport):
        payload = ImportTaskResponse(
            task_id=task_id,
            status=status,
            report=ImportReportResponse(
                total=report.total,
                created=report.created,
                updated=report.updated,
                errors=[
                    ImportRowErrorResponse(
                        row=e.row, student_id=e.student_id, message=e.message
                    )
                    for e in report.errors
                ],
            ),
        )
        return payload.model_dump(mode="json")
    if isinstance(report, str) and status == "failed":
        payload = ImportTaskResponse(task_id=task_id, status="failed", report=None)
        dumped = payload.model_dump(mode="json")
        dumped["error"] = report
        return dumped
    return ImportTaskResponse(task_id=task_id, status=status).model_dump(mode="json")


__all__ = ["router"]

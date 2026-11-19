"""身份管理服务：待识别池、车辆档案、学生档案的业务编排。

职责：收敛 RBAC 与越权 404、分页与排序白名单、审计写入、Excel 校验。
依赖：sqlalchemy 会话、仓储层、领域常量、openpyxl。
边界：不做 HTTP 解析与响应序列化；SQL 只走仓储层；越权统一抛 NotFoundError
    （避免资源存在性泄露，调用方会映射为 404）。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from io import BytesIO
from threading import Thread

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.core.security import CurrentUser
from app.models.identity import IdentityResolution, PendingIdentity, Student, Vehicle
from app.repositories.audit import AuditRepository, CounselorAssignmentRepository
from app.repositories.identity import IdentityRepository
from app.repositories.student import StudentRepository
from app.repositories.vehicle import VehicleRepository

# 绑定/忽略允许的角色（P1-6 任务要求）。
BIND_ROLES: frozenset[str] = frozenset({"super_admin", "league_officer"})
# 管理端读允许的角色；学生端角色一律视为无资源（404）。
READ_ROLES: frozenset[str] = frozenset(
    {"super_admin", "league_officer", "counselor", "security_officer", "auditor"}
)

PAGE_SIZE_MAX = 100
DEFAULT_PAGE_SIZE = 20

# 学号格式：6-20 位数字（兼容本科/研究生/留学生纯数字学号）。
STUDENT_ID_PATTERN = re.compile(r"^\d{6,20}$")
# 手机号格式：大陆 11 位。
PHONE_PATTERN = re.compile(r"^1\d{10}$")
GENDER_ALLOWED = frozenset({"男", "女", "其他", ""})

# Excel 模板列（顺序固定，供模板生成与导入解析共用）。
TEMPLATE_HEADERS: tuple[str, ...] = (
    "学号",
    "姓名",
    "性别",
    "学院",
    "班级",
    "年级",
    "宿舍",
    "手机号",
)

# 排序白名单：对外 sort 参数 → ORM 列。
PENDING_SORTS = {
    "pass_count": PendingIdentity.pass_count,
    "last_seen": PendingIdentity.last_seen,
    "first_seen": PendingIdentity.first_seen,
}
VEHICLE_SORTS = {
    "last_seen": Vehicle.last_seen,
    "first_seen": Vehicle.first_seen,
    "vehicle_id": Vehicle.vehicle_id,
}
STUDENT_SORTS = {
    "student_id": Student.student_id,
    "name": Student.name,
    "class_name": Student.class_name,
}

# 大文件阈值：超过该行数走后台任务（返回 task_id，前端轮询）。
IMPORT_ASYNC_THRESHOLD = 500

# 导入任务注册表（进程内；生产切 Celery 时替换为任务队列）。
_IMPORT_TASKS: dict[str, dict[str, object]] = {}


@dataclass(frozen=True)
class ScopedUser:
    """服务层视角的调用方（仅保留鉴权所需字段，便于单测构造）。"""

    subject: str
    role: str


def to_scoped(user: CurrentUser) -> ScopedUser:
    """把认证主体收敛为服务层鉴权视图。"""
    return ScopedUser(subject=user.subject, role=user.role or "")


def _require_read(user: ScopedUser) -> None:
    """读权限校验：非管理角色统一 404（隐藏资源存在性）。"""
    if user.role not in READ_ROLES and user.role not in BIND_ROLES:
        raise NotFoundError("请求的资源不存在")


def require_read(user: ScopedUser) -> None:
    """读权限校验的公开别名（供 API 层复用，保持越权 404 语义）。"""
    _require_read(user)


def _require_bind(user: ScopedUser) -> None:
    """写权限校验：仅 super_admin / league_officer；其余一律 404。"""
    if user.role not in BIND_ROLES:
        raise NotFoundError("请求的资源不存在")


def counselor_scope(session: Session, user: ScopedUser) -> list[str] | None:
    """返回辅导员可见班级；非辅导员返回 None（不限）。

    Args:
        session: 数据库会话。
        user: 调用方。

    Returns:
        班级名列表；None 表示不限范围。
    """
    if user.role != "counselor":
        return None
    repo = CounselorAssignmentRepository(session)
    return repo.list_classes(user.subject)


def write_audit(
    session: Session,
    *,
    actor: str,
    role: str,
    action: str,
    object_type: str | None = None,
    object_id: str | None = None,
    ip: str | None = None,
    result: str = "ok",
    detail: str | None = None,
) -> None:
    """写入审计日志（调用方负责 commit）。"""
    AuditRepository(session).log(
        actor=actor,
        role=role,
        action=action,
        object_type=object_type,
        object_id=object_id,
        ip=ip,
        result=result,
        detail=detail,
    )


def _clamp_page(page: int, page_size: int) -> tuple[int, int]:
    """钳制分页参数，保证默认排序与分页上限。"""
    safe_page = max(1, page)
    safe_size = min(max(1, page_size), PAGE_SIZE_MAX)
    return safe_page, safe_size


def list_pending(
    session: Session,
    user: ScopedUser,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    sort: str = "pass_count",
    order: str = "desc",
    keyword: str | None = None,
    status: str = "pending",
) -> tuple[list[PendingIdentity], int]:
    """分页列出待识别车辆池。"""
    _require_read(user)
    safe_page, safe_size = _clamp_page(page, page_size)
    column = PENDING_SORTS.get(sort, PendingIdentity.pass_count)
    ordering = column.desc() if order != "asc" else column.asc()
    statement = select(PendingIdentity).where(PendingIdentity.status == status)
    count_stmt = select(func.count()).select_from(PendingIdentity).where(
        PendingIdentity.status == status
    )
    if keyword:
        like = f"%{keyword}%"
        statement = statement.where(PendingIdentity.vehicle_id.like(like))
        count_stmt = count_stmt.where(PendingIdentity.vehicle_id.like(like))
    total = int(session.execute(count_stmt).scalar_one())
    rows = list(
        session.execute(
            statement.order_by(ordering, PendingIdentity.id.desc())
            .limit(safe_size)
            .offset((safe_page - 1) * safe_size)
        )
        .scalars()
        .all()
    )
    return rows, total


def bind_vehicle(
    session: Session,
    user: ScopedUser,
    *,
    vehicle_id: str,
    student_id: str,
    method: str = "manual",
    note: str = "",
    ip: str | None = None,
) -> Vehicle:
    """绑定车辆到学生：车辆存在且学生存在时更新归属并终结待绑定池。

    事务由本函数收敛：成功提交，失败回滚后原样抛出（路由层不再管理事务）。
    """
    _require_bind(user)
    try:
        vehicle_repo = VehicleRepository(session)
        vehicle = vehicle_repo.get_by_id(vehicle_id)
        if vehicle is None:
            write_audit(
                session, actor=user.subject, role=user.role, action="identities.bind",
                object_type="vehicle", object_id=vehicle_id, ip=ip, result="denied",
                detail=f"车辆不存在 student={student_id}",
            )
            raise NotFoundError("请求的资源不存在")
        student = session.get(Student, student_id)
        if student is None:
            write_audit(
                session, actor=user.subject, role=user.role, action="identities.bind",
                object_type="vehicle", object_id=vehicle_id, ip=ip, result="denied",
                detail=f"学生不存在 student={student_id}",
            )
            raise NotFoundError("请求的资源不存在")
        vehicle_repo.update_owner(vehicle_id, student_id, bind_type=method, confidence=1.0)
        IdentityRepository(session).resolve_pending_by_vehicle(vehicle_id, status="resolved")
        write_audit(
            session, actor=user.subject, role=user.role, action="identities.bind",
            object_type="vehicle", object_id=vehicle_id, ip=ip, result="ok",
            detail=f"student={student_id} method={method} note={note[:60]}",
        )
        session.flush()
        updated = vehicle_repo.get_by_id(vehicle_id)
        assert updated is not None
        session.commit()
        return updated
    except Exception:
        session.rollback()
        raise


def ignore_pending(
    session: Session,
    user: ScopedUser,
    *,
    vehicle_id: str,
    ip: str | None = None,
) -> int:
    """忽略待识别车辆：终结该车全部 pending 行。

    事务由本函数收敛：成功提交，失败回滚后原样抛出（路由层不再管理事务）。
    """
    _require_bind(user)
    try:
        count = IdentityRepository(session).resolve_pending_by_vehicle(vehicle_id, status="ignored")
        if count == 0:
            write_audit(
                session, actor=user.subject, role=user.role, action="identities.ignore",
                object_type="vehicle", object_id=vehicle_id, ip=ip, result="denied",
                detail="无待处理记录",
            )
            raise NotFoundError("请求的资源不存在")
        write_audit(
            session, actor=user.subject, role=user.role, action="identities.ignore",
            object_type="vehicle", object_id=vehicle_id, ip=ip, result="ok",
            detail=f"ignored={count}",
        )
        session.flush()
        session.commit()
        return count
    except Exception:
        session.rollback()
        raise


def list_vehicles(
    session: Session,
    user: ScopedUser,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    sort: str = "last_seen",
    order: str = "desc",
    keyword: str | None = None,
    status: str | None = None,
) -> tuple[list[Vehicle], int]:
    """分页列出车辆档案。"""
    _require_read(user)
    safe_page, safe_size = _clamp_page(page, page_size)
    column = VEHICLE_SORTS.get(sort, Vehicle.last_seen)
    ordering = column.desc() if order != "asc" else column.asc()
    statement = select(Vehicle)
    count_stmt = select(func.count()).select_from(Vehicle)
    if status:
        statement = statement.where(Vehicle.status == status)
        count_stmt = count_stmt.where(Vehicle.status == status)
    if keyword:
        like = f"%{keyword}%"
        statement = statement.where(
            or_(Vehicle.vehicle_id.like(like), Vehicle.plate_no.like(like))
        )
        count_stmt = count_stmt.where(
            or_(Vehicle.vehicle_id.like(like), Vehicle.plate_no.like(like))
        )
    total = int(session.execute(count_stmt).scalar_one())
    rows = list(
        session.execute(
            statement.order_by(ordering, Vehicle.vehicle_id.asc())
            .limit(safe_size)
            .offset((safe_page - 1) * safe_size)
        )
        .scalars()
        .all()
    )
    return rows, total


@dataclass(frozen=True)
class VehicleDetail:
    """车辆详情聚合：档案 + 匹配历史 + 最近通行。"""

    vehicle: Vehicle
    resolutions: list[IdentityResolution] = field(default_factory=list)
    hints: list[dict[str, object]] = field(default_factory=list)


def get_vehicle_detail(
    session: Session, user: ScopedUser, *, vehicle_id: str
) -> VehicleDetail:
    """读取车辆详情（含匹配历史时间线与最近通行）。"""
    _require_read(user)
    vehicle = VehicleRepository(session).get_by_id(vehicle_id)
    if vehicle is None:
        raise NotFoundError("请求的资源不存在")
    resolutions = list(
        session.execute(
            select(IdentityResolution)
            .where(IdentityResolution.vehicle_id == vehicle_id)
            .order_by(IdentityResolution.id.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    return VehicleDetail(vehicle=vehicle, resolutions=resolutions)


def list_students(
    session: Session,
    user: ScopedUser,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    sort: str = "student_id",
    order: str = "asc",
    keyword: str | None = None,
    college: str | None = None,
    status: str | None = None,
) -> tuple[list[Student], int]:
    """分页列出学生；counselor 仅返回所带班级。"""
    _require_read(user)
    scope = counselor_scope(session, user)
    safe_page, safe_size = _clamp_page(page, page_size)
    column = STUDENT_SORTS.get(sort, Student.student_id)
    ordering = column.desc() if order == "desc" else column.asc()
    repo = StudentRepository(session)
    rows = repo.list_with_filters(
        keyword=keyword, class_names=scope, college=college, status=status,
        order_desc=(order == "desc" and sort == "student_id"),
        limit=safe_size, offset=(safe_page - 1) * safe_size,
    )
    # 通用排序：仓储默认按学号排序；非学号排序在此按内存排序兜底不现实，
    # 故当 sort 非 student_id 时走显式查询排序。
    if sort != "student_id":
        statement = select(Student)
        if scope is not None:
            statement = statement.where(Student.class_name.in_(scope))
        if college:
            statement = statement.where(Student.college == college)
        if status:
            statement = statement.where(Student.status == status)
        if keyword:
            like = f"%{keyword}%"
            statement = statement.where(
                or_(
                    Student.student_id.like(like),
                    Student.name.like(like),
                    Student.phone.like(like),
                )
            )
        rows = list(
            session.execute(
                statement.order_by(ordering, Student.student_id.asc())
                .limit(safe_size)
                .offset((safe_page - 1) * safe_size)
            )
            .scalars()
            .all()
        )
    total = repo.count_with_filters(
        keyword=keyword, class_names=scope, college=college, status=status
    )
    return rows, total


@dataclass(frozen=True)
class StudentDetail:
    """学生详情聚合：档案 + 名下车辆 + 近期判定。"""

    student: Student
    vehicles: list[Vehicle] = field(default_factory=list)
    resolutions: list[IdentityResolution] = field(default_factory=list)


def get_student_detail(
    session: Session, user: ScopedUser, *, student_id: str
) -> StudentDetail:
    """读取学生详情；counselor 越出所带班级时返回 404。"""
    _require_read(user)
    student = session.get(Student, student_id)
    if student is None:
        raise NotFoundError("请求的资源不存在")
    scope = counselor_scope(session, user)
    if scope is not None and student.class_name not in scope:
        raise NotFoundError("请求的资源不存在")
    vehicles = VehicleRepository(session).list_by_owner(student_id)
    resolutions = list(
        session.execute(
            select(IdentityResolution)
            .where(IdentityResolution.subject_id == student_id)
            .order_by(IdentityResolution.id.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    return StudentDetail(student=student, vehicles=vehicles, resolutions=resolutions)


# ---------------------------------------------------------------------------
# Excel 模板与导入
# ---------------------------------------------------------------------------


def build_import_template() -> bytes:
    """生成导入模板（openpyxl，二进制 xlsx）。

    Returns:
        xlsx 文件字节。
    """
    from openpyxl import Workbook  # noqa: PLC0415  # 可选依赖仅此处使用。
    from openpyxl.styles import Alignment, Font, PatternFill  # noqa: PLC0415

    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "学生导入"
    header_fill = PatternFill(start_color="F2F2F7", fill_type="solid")
    header_font = Font(bold=True)
    for index, title in enumerate(TEMPLATE_HEADERS, start=1):
        cell = sheet.cell(row=1, column=index, value=title)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = 16
    sheet.sheet_properties.pageSetUpPr = None
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@dataclass(frozen=True)
class ImportRowError:
    """单行校验错误。"""

    row: int
    student_id: str
    message: str


@dataclass(frozen=True)
class ImportReport:
    """导入结果报告。"""

    total: int
    created: int
    updated: int
    errors: list[ImportRowError] = field(default_factory=list)


def _validate_row(
    row_no: int, values: dict[str, str], seen: set[str]
) -> ImportRowError | None:
    """校验单行；返回错误或 None。"""
    student_id = values.get("学号", "").strip()
    name = values.get("姓名", "").strip()
    gender = values.get("性别", "").strip()
    phone = values.get("手机号", "").strip()
    if not student_id:
        return ImportRowError(row=row_no, student_id="", message="学号必填")
    if not STUDENT_ID_PATTERN.match(student_id):
        return ImportRowError(
            row=row_no, student_id=student_id, message="学号格式非法（应为6-20位数字）"
        )
    if not name:
        return ImportRowError(row=row_no, student_id=student_id, message="姓名必填")
    if len(name) > 32:
        return ImportRowError(row=row_no, student_id=student_id, message="姓名超长（≤32字）")
    if gender not in GENDER_ALLOWED:
        return ImportRowError(row=row_no, student_id=student_id, message="性别仅支持 男/女/其他")
    if phone and not PHONE_PATTERN.match(phone):
        return ImportRowError(
            row=row_no, student_id=student_id, message="手机号格式非法（应为11位大陆号码）"
        )
    if student_id in seen:
        return ImportRowError(row=row_no, student_id=student_id, message="文件内学号重复")
    return None


def parse_import_workbook(data: bytes) -> tuple[list[dict[str, str]], list[ImportRowError]]:
    """解析上传的 xlsx，返回（有效行，行错误）。

    Raises:
        ValidationError: 非 xlsx / 缺表头 / 空文件。
    """
    from openpyxl import load_workbook  # noqa: PLC0415

    try:
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise ValidationError(f"Excel 解析失败：{exc}") from exc
    sheet = workbook.active
    if sheet is None:
        raise ValidationError("Excel 缺少工作表")
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        raise ValidationError("Excel 为空文件")
    headers = [(str(cell).strip() if cell is not None else "") for cell in rows[0]]
    if headers[: len(TEMPLATE_HEADERS)] != list(TEMPLATE_HEADERS):
        raise ValidationError(f"表头不匹配，应为：{'/'.join(TEMPLATE_HEADERS)}")
    valid: list[dict[str, str]] = []
    errors: list[ImportRowError] = []
    seen: set[str] = set()
    for offset, raw in enumerate(rows[1:], start=2):
        if all(cell is None or str(cell).strip() == "" for cell in raw):
            continue
        values = {
            header: ("" if cell is None else str(cell).strip())
            for header, cell in zip(TEMPLATE_HEADERS, raw, strict=False)
        }
        error = _validate_row(offset, values, seen)
        if error is not None:
            errors.append(error)
            continue
        seen.add(values["学号"].strip())
        valid.append(values)
    return valid, errors


def apply_import_rows(
    session: Session, rows: list[dict[str, str]]
) -> tuple[int, int]:
    """把有效行写入 students 表（存在则更新，不存在则创建）。

    Returns:
        (created, updated)。
    """
    created = 0
    updated = 0
    for values in rows:
        student_id = values["学号"].strip()
        payload = {
            "name": values["姓名"].strip(),
            "gender": values["性别"].strip() or None,
            "college": values["学院"].strip() or None,
            "class_name": values["班级"].strip() or None,
            "grade": values["年级"].strip() or None,
            "dorm_id": values["宿舍"].strip() or None,
            "phone": values["手机号"].strip() or None,
            "status": "active",
        }
        existing = session.get(Student, student_id)
        if existing is None:
            session.add(Student(student_id=student_id, **payload))
            created += 1
        else:
            for key, value in payload.items():
                setattr(existing, key, value)
            updated += 1
        session.flush()
    return created, updated


def import_students(
    session: Session,
    user: ScopedUser,
    data: bytes,
    *,
    ip: str | None = None,
) -> ImportReport | str:
    """导入学生 Excel：小文件同步返回报告，大文件返回 task_id。

    事务由本函数收敛：成功提交，失败回滚后原样抛出（路由层不再管理事务）。
    大文件走后台线程写入，审计行由本函数提交，后台结果经任务表查询。

    Returns:
        小文件返回 ImportReport；大文件返回 task_id 字符串。
    """
    _require_bind(user)
    valid, errors = parse_import_workbook(data)
    if len(valid) + len(errors) > IMPORT_ASYNC_THRESHOLD:
        task_id = uuid.uuid4().hex
        _IMPORT_TASKS[task_id] = {"status": "running", "report": None}
        snapshot = list(valid)

        def _run() -> None:
            from sqlalchemy.orm import Session as OrmSession  # noqa: PLC0415

            # 后台线程复用同一 Engine（通过 session 绑定的 bind）。
            bind = session.get_bind()
            assert bind is not None
            # 仅支持 Engine 复用；若为 Connection 则回退同步逻辑标记失败。
            try:
                thread_session = OrmSession(bind, future=True)
            except Exception as exc:  # pragma: no cover - 防御性分支。
                _IMPORT_TASKS[task_id] = {"status": "failed", "report": str(exc)}
                return
            try:
                created, updated = apply_import_rows(thread_session, snapshot)
                thread_session.commit()
                _IMPORT_TASKS[task_id] = {
                    "status": "done",
                    "report": ImportReport(
                        total=len(snapshot) + len(errors),
                        created=created,
                        updated=updated,
                        errors=list(errors),
                    ),
                }
            except Exception as exc:
                thread_session.rollback()
                _IMPORT_TASKS[task_id] = {"status": "failed", "report": str(exc)}
            finally:
                thread_session.close()

        Thread(target=_run, daemon=True).start()
        write_audit(
            session, actor=user.subject, role=user.role, action="students.import_async",
            object_type="student", object_id=task_id, ip=ip, result="ok",
            detail=f"rows={len(valid) + len(errors)}",
        )
        try:
            session.flush()
            session.commit()
        except Exception:
            session.rollback()
            raise
        return task_id
    try:
        created, updated = apply_import_rows(session, valid)
        write_audit(
            session, actor=user.subject, role=user.role, action="students.import",
            object_type="student", object_id=None, ip=ip, result="ok",
            detail=(
                f"total={len(valid) + len(errors)} created={created} "
                f"updated={updated} errors={len(errors)}"
            ),
        )
        session.flush()
        report = ImportReport(
            total=len(valid) + len(errors), created=created, updated=updated, errors=errors
        )
        session.commit()
        return report
    except Exception:
        session.rollback()
        raise


def get_import_task(task_id: str) -> dict[str, object] | None:
    """查询后台导入任务状态。"""
    return _IMPORT_TASKS.get(task_id)

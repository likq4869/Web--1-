"""P1-6 身份管理 API 测试：认证、权限、越权 404、分页、导入。

职责：覆盖 9 个管理端点的鉴权矩阵、辅导员范围隔离、审计留痕与 Excel 导入。
依赖：FastAPI TestClient、SQLAlchemy、openpyxl。
边界：不测领域融合算法；只测 API 层的鉴权、分页与导入报告。
"""

from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.security import CurrentUser
from app.models.identity import CounselorAssignment, PendingIdentity, Student, User, Vehicle


def _auth_override(subject: str, role: str):  # type: ignore[no-untyped-def]
    """构造鉴权覆盖函数（供 dependency_overrides 使用）。"""

    def _dep() -> CurrentUser:
        return CurrentUser(subject=subject, role=role, claims={})

    return _dep


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """绑定到临时库的 TestClient，并预置身份域种子。"""
    import importlib

    db_path = tmp_path / "identity-api.db"
    monkeypatch.setenv("HELMET_GUARD_DB", str(db_path))
    monkeypatch.setenv("HELMET_GUARD_MODE", "demo")
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-for-production")
    import app.main as main_mod

    importlib.reload(main_mod)
    from app.core.config import get_settings as _get_settings

    _get_settings.cache_clear()
    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        engine = client.app.state.db_engine  # type: ignore[attr-defined]
        with Session(engine, future=True) as session:
            session.add_all(
                [
                    User(
                        user_id="admin1",
                        username="超管",
                        role="super_admin",
                        status="active",
                    ),
                    User(
                        user_id="officer1",
                        username="干事",
                        role="league_officer",
                        status="active",
                    ),
                    User(
                        user_id="c1",
                        username="辅导员",
                        role="counselor",
                        status="active",
                    ),
                    User(user_id="s1", username="学生", role="student", status="active"),
                ]
            )
            session.flush()
            session.add_all(
                [
                    Student(
                        student_id="2024000001",
                        name="张三",
                        class_name="计科2401",
                        status="active",
                    ),
                    Student(
                        student_id="2024000002",
                        name="李四",
                        class_name="计科2402",
                        status="active",
                    ),
                ]
            )
            session.flush()
            session.add_all(
                [
                    Vehicle(vehicle_id="veh_001", owner_id=None, status="unbound", confidence=0.0),
                    Vehicle(
                        vehicle_id="veh_002",
                        owner_id="2024000001",
                        owner_bind_type="manual",
                        status="active",
                        confidence=1.0,
                    ),
                ]
            )
            session.flush()
            session.add_all(
                [
                    PendingIdentity(
                        vehicle_id="veh_001",
                        pass_count=5,
                        location="东门",
                        status="pending",
                    ),
                    PendingIdentity(
                        vehicle_id="veh_009",
                        pass_count=2,
                        location="西门",
                        status="pending",
                    ),
                ]
            )
            session.flush()
            session.add(CounselorAssignment(user_id="c1", class_name="计科2401"))
            session.commit()
        yield client
        client.app.dependency_overrides.clear()


def _as(client: TestClient, subject: str, role: str) -> TestClient:
    """切换当前请求的认证主体。"""
    client.app.dependency_overrides[get_current_user] = _auth_override(subject, role)
    return client


def test_unauthenticated_is_403(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/admin/identities/pending")
    assert response.status_code == 401


def test_student_cannot_read_pending_returns_404(api_client: TestClient) -> None:
    _as(api_client, "s1", "student")
    response = api_client.get("/api/v1/admin/identities/pending")
    assert response.status_code == 404


def test_pending_list_pagination_and_sort_whitelist(api_client: TestClient) -> None:
    _as(api_client, "admin1", "super_admin")
    response = api_client.get(
        "/api/v1/admin/identities/pending",
        params={"page": 1, "page_size": 1, "sort": "nope", "order": "desc"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    # 非法 sort 回退默认 pass_count 倒序，首位应为 pass_count=5。
    assert body["items"][0]["pending"]["vehicle_id"] == "veh_001"


def test_bind_success_writes_audit_and_resolves_pending(api_client: TestClient) -> None:
    _as(api_client, "admin1", "super_admin")
    response = api_client.post(
        "/api/v1/admin/identities/veh_001/bind",
        json={"student_id": "2024000001", "method": "manual", "note": "登记"},
    )
    assert response.status_code == 200
    assert response.json()["vehicle"]["owner_id"] == "2024000001"
    # 待识别池终结：再次列出 pending 不再含 veh_001。
    pending = api_client.get("/api/v1/admin/identities/pending").json()
    assert {item["pending"]["vehicle_id"] for item in pending["items"]} == {"veh_009"}
    # 审计留痕。
    engine = api_client.app.state.db_engine  # type: ignore[attr-defined]
    with Session(engine, future=True) as session:
        from app.models.identity import AuditLog

        rows = session.query(AuditLog).filter(AuditLog.action == "identities.bind").all()
        assert len(rows) >= 1
        assert rows[0].actor == "admin1"


def test_bind_by_counselor_returns_404(api_client: TestClient) -> None:
    _as(api_client, "c1", "counselor")
    response = api_client.post(
        "/api/v1/admin/identities/veh_009/bind",
        json={"student_id": "2024000001"},
    )
    assert response.status_code == 404


def test_bind_missing_vehicle_returns_404(api_client: TestClient) -> None:
    _as(api_client, "officer1", "league_officer")
    response = api_client.post(
        "/api/v1/admin/identities/veh_missing/bind",
        json={"student_id": "2024000001"},
    )
    assert response.status_code == 404


def test_ignore_success(api_client: TestClient) -> None:
    _as(api_client, "officer1", "league_officer")
    response = api_client.post("/api/v1/admin/identities/veh_009/ignore")
    assert response.status_code == 200
    assert response.json()["ignored"] == 1
    pending = api_client.get("/api/v1/admin/identities/pending").json()
    assert all(item["pending"]["vehicle_id"] != "veh_009" for item in pending["items"])


def test_vehicles_list_and_detail(api_client: TestClient) -> None:
    _as(api_client, "admin1", "super_admin")
    listing = api_client.get("/api/v1/admin/vehicles").json()
    assert listing["total"] == 2
    detail = api_client.get("/api/v1/admin/vehicles/veh_002")
    assert detail.status_code == 200
    assert detail.json()["vehicle"]["vehicle_id"] == "veh_002"
    assert api_client.get("/api/v1/admin/vehicles/veh_missing").status_code == 404


def test_counselor_student_scope_and_cross_class_404(api_client: TestClient) -> None:
    _as(api_client, "c1", "counselor")
    listing = api_client.get("/api/v1/admin/students").json()
    assert listing["total"] == 1
    assert listing["items"][0]["class_name"] == "计科2401"
    # 越出所带班级的详情返回 404（而非 403，避免存在性泄露）。
    assert api_client.get("/api/v1/admin/students/2024000002").status_code == 404
    assert api_client.get("/api/v1/admin/students/2024000001").status_code == 200


def test_student_list_keyword_and_pagination(api_client: TestClient) -> None:
    _as(api_client, "admin1", "super_admin")
    body = api_client.get(
        "/api/v1/admin/students", params={"keyword": "张三", "page_size": 50}
    ).json()
    assert body["total"] == 1
    assert body["items"][0]["student_id"] == "2024000001"


def test_template_download_returns_xlsx(api_client: TestClient) -> None:
    _as(api_client, "admin1", "super_admin")
    response = api_client.get("/api/v1/admin/students/template")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml"
    )
    assert response.content[:2] == b"PK"


def _workbook_bytes(rows: list[list[object]]) -> bytes:
    """构造测试用 xlsx（含表头）。"""
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    headers = ["学号", "姓名", "性别", "学院", "班级", "年级", "宿舍", "手机号"]
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_import_sync_report_with_row_errors(api_client: TestClient) -> None:
    _as(api_client, "admin1", "super_admin")
    data = _workbook_bytes(
        [
            ["2024000010", "王五", "男", "计院", "计科2401", "2024", "1-101", "13800000000"],
            ["bad-id", "", "未知", "", "", "", "", "123"],
            ["2024000010", "重复", "男", "", "", "", "", ""],
        ]
    )
    response = api_client.post(
        "/api/v1/admin/students/import",
        files={"file": ("students.xlsx", data, "application/octet-stream")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["created"] == 1
    assert len(body["errors"]) == 2
    assert {error["row"] for error in body["errors"]} == {3, 4}


def test_import_rejects_bad_header(api_client: TestClient) -> None:
    _as(api_client, "admin1", "super_admin")
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["学号", "姓名"])
    buffer = BytesIO()
    workbook.save(buffer)
    response = api_client.post(
        "/api/v1/admin/students/import",
        files={"file": ("bad.xlsx", buffer.getvalue(), "application/octet-stream")},
    )
    assert response.status_code == 422


def test_import_forbidden_for_counselor(api_client: TestClient) -> None:
    _as(api_client, "c1", "counselor")
    data = _workbook_bytes([["2024000020", "赵六", "女", "", "", "", "", ""]])
    response = api_client.post(
        "/api/v1/admin/students/import",
        files={"file": ("s.xlsx", data, "application/octet-stream")},
    )
    assert response.status_code == 404

"""身份域测试：迁移往返、结构一致性、仓储 CRUD、相似检索。"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models import Base

PROJECT_DIR = Path(__file__).resolve().parent.parent

IDENTITY_TABLES = {
    "users",
    "students",
    "vehicles",
    "identity_resolutions",
    "pending_identities",
    "vehicle_cooccurrence",
}


def _alembic_config(db_path: Path) -> Config:
    """构造指向临时数据库的 Alembic 配置。"""
    config = Config(str(PROJECT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return config


def _pack(vector: list[float]) -> bytes:
    """把 float 向量打包为 embedding 字节。"""
    return struct.pack(f"<{len(vector)}f", *vector)


def test_identity_tables_created_by_migration(tmp_path: Path) -> None:
    """升级到 head 后身份域 6 张表全部存在。"""
    db_path = tmp_path / "identity.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert tables >= IDENTITY_TABLES


def test_identity_downgrade_removes_only_identity_tables(tmp_path: Path) -> None:
    """回滚 0002 后仅身份域表被清除，P0 基线表保留。"""
    db_path = tmp_path / "identity-rollback.db"
    config = _alembic_config(db_path)
    command.upgrade(config, "head")
    command.downgrade(config, "0001_baseline")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
    finally:
        engine.dispose()
    assert IDENTITY_TABLES.isdisjoint(tables)
    assert {"sources", "passes", "events", "reviews", "heartbeats", "alerts"} <= tables
    # 重新升级可恢复（可回滚且可重做）。
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert tables >= IDENTITY_TABLES


def test_identity_schema_matches_orm_models(tmp_path: Path) -> None:
    """身份域表结构（列/主键/可空）与 ORM 模型一致。"""
    db_path = tmp_path / "identity-schema.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        inspector = inspect(engine)
        for name in sorted(IDENTITY_TABLES):
            orm_table = Base.metadata.tables[name]
            actual_columns = {col["name"] for col in inspector.get_columns(name)}
            expected_columns = {col.name for col in orm_table.columns}
            assert actual_columns == expected_columns, f"{name} 列不一致"

            actual_pk = set(inspector.get_pk_constraint(name)["constrained_columns"])
            expected_pk = {col.name for col in orm_table.primary_key.columns}
            assert actual_pk == expected_pk, f"{name} 主键不一致"

            actual_notnull = {
                col["name"] for col in inspector.get_columns(name) if not col.get("nullable", True)
            }
            expected_notnull = {col.name for col in orm_table.columns if not col.nullable}
            assert actual_notnull == expected_notnull, f"{name} 可空性不一致"
    finally:
        engine.dispose()


def test_identity_required_indexes_exist(tmp_path: Path) -> None:
    """任务要求的 6 个高频索引全部存在。"""
    db_path = tmp_path / "identity-index.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        inspector = inspect(engine)
        index_names = {
            index["name"]
            for table in ("vehicles", "identity_resolutions", "pending_identities")
            for index in inspector.get_indexes(table)
        }
    finally:
        engine.dispose()
    assert {
        "ix_vehicles_owner",
        "ix_vehicles_plate",
        "ix_identity_event",
        "ix_identity_subject",
        "ix_identity_vehicle",
        "ix_pending_status",
    } <= index_names


def _session_for(db_path: Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as db_session:
            yield db_session
    finally:
        engine.dispose()


def test_vehicle_repository_crud_and_owner_flow(tmp_path: Path) -> None:
    """车辆仓储：建档、车牌查询、车主查询、绑定更新、seen 刷新。"""
    from app.models.identity import Student, User, Vehicle
    from app.repositories.vehicle import VehicleRepository

    db_path = tmp_path / "vehicle-repo.db"
    command.upgrade(_alembic_config(db_path), "head")
    for db_session in _session_for(db_path):
        db_session.add(User(user_id="u1", username="张三", role="student", status="active"))
        db_session.add(
            Student(student_id="2022110508", user_id="u1", name="张三", status="active")
        )
        db_session.commit()

        repo = VehicleRepository(db_session)
        repo.create(
            Vehicle(
                vehicle_id="veh_001",
                plate_no="合肥A12345",
                plate_type="blue",
                owner_id=None,
                owner_bind_type=None,
                confidence=0.0,
                color_hist=[0.1, 0.2],
                embedding=None,
                first_seen=None,
                last_seen=None,
                status="unbound",
            )
        )
        db_session.commit()

        assert repo.get_by_id("veh_001") is not None
        assert repo.get_by_plate("合肥A12345") is not None
        assert repo.get_by_plate("不存在") is None
        assert repo.list_by_owner("2022110508") == []

        assert (
            repo.update_owner("veh_001", "2022110508", bind_type="manual", confidence=0.95)
            == 1
        )
        db_session.commit()
        assert len(repo.list_by_owner("2022110508")) == 1
        assert repo.update_owner("missing", "2022110508") == 0

        seen_at = datetime(2026, 11, 16, 8, 0, 0, tzinfo=UTC)
        assert repo.touch_seen("veh_001", seen_at) == 1
        assert repo.touch_seen("missing", seen_at) == 0
        db_session.commit()


def test_vehicle_repository_find_similar_by_embedding(tmp_path: Path) -> None:
    """外观相似检索：余弦排序正确，阈值过滤生效。"""
    from app.models.identity import Vehicle
    from app.repositories.vehicle import VehicleRepository

    db_path = tmp_path / "vehicle-sim.db"
    command.upgrade(_alembic_config(db_path), "head")
    for db_session in _session_for(db_path):
        repo = VehicleRepository(db_session)
        repo.create(
            Vehicle(
                vehicle_id="veh_same",
                plate_no=None,
                plate_type=None,
                owner_id=None,
                owner_bind_type=None,
                confidence=0.0,
                color_hist=None,
                embedding=_pack([1.0, 0.0, 0.0, 0.0]),
                first_seen=None,
                last_seen=None,
                status="unbound",
            )
        )
        repo.create(
            Vehicle(
                vehicle_id="veh_orth",
                plate_no=None,
                plate_type=None,
                owner_id=None,
                owner_bind_type=None,
                confidence=0.0,
                color_hist=None,
                embedding=_pack([0.0, 1.0, 0.0, 0.0]),
                first_seen=None,
                last_seen=None,
                status="unbound",
            )
        )
        repo.create(
            Vehicle(
                vehicle_id="veh_noemb",
                plate_no=None,
                plate_type=None,
                owner_id=None,
                owner_bind_type=None,
                confidence=0.0,
                color_hist=None,
                embedding=None,
                first_seen=None,
                last_seen=None,
                status="unbound",
            )
        )
        db_session.commit()

        hits = repo.find_similar_by_embedding([1.0, 0.0, 0.0, 0.0], threshold=0.82)
        assert [vehicle.vehicle_id for vehicle, _ in hits] == ["veh_same"]
        assert hits[0][1] == 1.0

        relaxed = repo.find_similar_by_embedding([1.0, 0.0, 0.0, 0.0], threshold=0.0)
        assert [vehicle.vehicle_id for vehicle, _ in relaxed] == ["veh_same", "veh_orth"]
        assert relaxed[0][1] >= relaxed[1][1]
        db_session.commit()


def test_identity_repository_resolution_and_pending_flow(tmp_path: Path) -> None:
    """身份仓储：判定写入/查询 + 待绑定池幂等递增/终结。"""
    from app.models.identity import IdentityResolution
    from app.repositories.identity import IdentityRepository

    db_path = tmp_path / "identity-repo.db"
    command.upgrade(_alembic_config(db_path), "head")
    for db_session in _session_for(db_path):
        repo = IdentityRepository(db_session)
        repo.create_resolution(
            IdentityResolution(
                event_id="evt1",
                vehicle_id="veh_001",
                subject_id="2022110508",
                method="plate",
                confidence=0.91,
                plate_conf=0.93,
                appearance_conf=0.7,
                cooccur_conf=0.0,
                matched_count=0,
                snapshot_id="snap_1",
            )
        )
        repo.create_resolution(
            IdentityResolution(
                event_id="evt1",
                vehicle_id="veh_001",
                subject_id="2022110508",
                method="appearance",
                confidence=0.82,
                plate_conf=0.0,
                appearance_conf=0.82,
                cooccur_conf=0.0,
                matched_count=0,
                snapshot_id="snap_2",
            )
        )
        db_session.commit()

        latest = repo.get_by_event("evt1")
        assert latest is not None and latest.snapshot_id == "snap_2"
        assert repo.get_by_event("missing") is None
        assert len(repo.list_by_subject("2022110508")) == 2
        assert repo.list_by_subject("nobody") == []

        first = repo.upsert_pending("veh_001", location="东门", snapshot_id="snap_1")
        db_session.commit()
        assert first.pass_count == 1
        second = repo.upsert_pending("veh_001", location="东门", snapshot_id="snap_2")
        db_session.commit()
        assert second.id == first.id
        assert second.pass_count == 2

        assert len(repo.list_pending()) == 1
        assert repo.resolve_pending(int(first.id), status="resolved") == 1
        db_session.commit()
        # 重复终结返回 0（幂等）。
        assert repo.resolve_pending(int(first.id), status="resolved") == 0
        assert repo.list_pending() == []
        db_session.commit()

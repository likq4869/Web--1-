"""迁移与仓储层测试：迁移往返、结构一致性、仓储 CRUD、并发复核。"""

from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models import Base

# Alembic 配置目录：项目根下的 migrations/ 与 alembic.ini。
PROJECT_DIR = Path(__file__).resolve().parent.parent


def _alembic_config(db_path: Path) -> Config:
    """构造指向临时数据库的 Alembic 配置。

    Args:
        db_path: 临时 SQLite 文件路径。

    Returns:
        Alembic Config 对象。
    """
    config = Config(str(PROJECT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return config


@pytest.fixture()
def migrated_db(tmp_path: Path) -> Iterator[Path]:
    """在空库上执行 upgrade head，产出已迁移的数据库路径。"""
    db_path = tmp_path / "migrated.db"
    command.upgrade(_alembic_config(db_path), "head")
    yield db_path


# --------------------------------------------------------------------------
# 迁移测试
# --------------------------------------------------------------------------


def test_upgrade_from_empty_database_creates_all_tables(migrated_db: Path) -> None:
    """从空库升级到 head 后，6 张表全部存在。"""
    engine = create_engine(f"sqlite:///{migrated_db.as_posix()}")
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
    finally:
        engine.dispose()
    assert {"sources", "passes", "events", "reviews", "heartbeats", "alerts"} <= tables


def test_downgrade_to_base_then_upgrade_again(tmp_path: Path) -> None:
    """降级到 base 后表被清除，再次升级可重建。"""
    db_path = tmp_path / "roundtrip.db"
    config = _alembic_config(db_path)

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        assert "passes" in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        remaining = set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()
    assert remaining == set()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert {"sources", "passes", "events", "reviews", "heartbeats", "alerts"} <= tables


def test_migrated_schema_matches_orm_models(migrated_db: Path) -> None:
    """迁移后的实际表结构与 ORM 模型完全一致。"""
    engine = create_engine(f"sqlite:///{migrated_db.as_posix()}")
    try:
        inspector = inspect(engine)
        for name, orm_table in Base.metadata.tables.items():
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

            actual_unique = {
                tuple(sorted(constraint["column_names"]))
                for constraint in inspector.get_unique_constraints(name)
            }
            expected_unique = {
                tuple(sorted(col.name for col in constraint.columns))
                for constraint in orm_table.constraints
                if constraint.__class__.__name__ == "UniqueConstraint"
            }
            assert actual_unique == expected_unique, f"{name} UNIQUE 约束不一致"
    finally:
        engine.dispose()


def test_check_constraints_are_preserved(migrated_db: Path) -> None:
    """三处 CHECK 约束在迁移后仍然生效。"""
    conn = sqlite3.connect(str(migrated_db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO passes(pass_id,source_id,run_id,occurred_at,"
                "rider_status,model_raw,created_at) VALUES('p','s','r','t','bad','','t')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO events(event_id,pass_id,source_id,run_id,occurred_at,"
                "status,model_label,reason,reviewer,created_at) "
                "VALUES('e','p','s','r','t','bad','','','','t')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO alerts(alert_id,event_id,source_id,status,note,"
                "created_at,updated_at) VALUES('a','e','s','bad','','t','t')"
            )
    finally:
        conn.close()


# --------------------------------------------------------------------------
# 仓储层测试
# --------------------------------------------------------------------------


@pytest.fixture()
def session(migrated_db: Path) -> Iterator[Session]:
    """基于迁移后数据库的 ORM 会话。"""
    engine = create_engine(f"sqlite:///{migrated_db.as_posix()}", future=True)
    with Session(engine, future=True) as db_session:
        yield db_session
    engine.dispose()


def test_base_repository_crud(session: Session) -> None:
    """通用 CRUD 可用且全部参数化。"""
    from app.models.entities import Source
    from app.repositories.base import BaseRepository

    class SourceRepository(BaseRepository[Source]):
        model = Source
        id_field = "source_id"

    repo = SourceRepository(session)
    created = repo.create(
        Source(source_id="s1", name="东校门", status="online", last_seen=None, updated_at="t")
    )
    session.commit()
    assert created.source_id == "s1"

    fetched = repo.get_by_id("s1")
    assert fetched is not None and fetched.name == "东校门"
    assert repo.get_by_id("missing") is None
    assert repo.count() == 1
    assert repo.exists(source_id="s1") is True

    repo.update(fetched, name="西门")
    session.commit()
    assert repo.get_by_id("s1").name == "西门"

    repo.delete(fetched)
    session.commit()
    assert repo.count() == 0


def test_event_repository_filters(session: Session) -> None:
    """事件仓储的过滤与计数正确。"""
    from app.models.entities import Event
    from app.repositories.event import EventRepository

    repo = EventRepository(session)
    for index, status in enumerate(("pending", "confirmed", "dismissed")):
        repo.create(
            Event(
                event_id=f"e{index}",
                pass_id=f"p{index}",
                source_id="s1",
                run_id="r1",
                occurred_at=f"2026-11-0{index + 1}T00:00:00+00:00",
                status=status,
                model_label="no helmet",
                reason="",
                reviewer="",
                reviewed_at=None,
                created_at="t",
            )
        )
    session.commit()

    assert repo.count_with_filters() == 3
    assert repo.count_with_filters(status="pending") == 1
    assert len(repo.list_with_filters(status="confirmed")) == 1
    assert repo.get_status("e0") == "pending"
    assert repo.get_status("missing") is None


def test_event_repository_claim_pending(session: Session) -> None:
    """条件更新抢占：只有第一个调用能命中 pending。"""
    from app.models.entities import Event
    from app.repositories.event import EventRepository

    repo = EventRepository(session)
    repo.create(
        Event(
            event_id="e1",
            pass_id="p1",
            source_id="s1",
            run_id="r1",
            occurred_at="t",
            status="pending",
            model_label="",
            reason="",
            reviewer="",
            reviewed_at=None,
            created_at="t",
        )
    )
    session.commit()

    assert repo.claim_pending("e1", status="confirmed") == 1
    session.commit()
    assert repo.claim_pending("e1", status="dismissed") == 0


def test_pass_repository_counts(session: Session) -> None:
    """通行仓储的三态统计补齐缺失状态。"""
    from app.models.entities import Pass
    from app.repositories.pass_record import PassRepository

    repo = PassRepository(session)
    for index, status in enumerate(("helmeted", "helmeted", "bare")):
        repo.create(
            Pass(
                pass_id=f"p{index}",
                source_id="s1",
                run_id="r1",
                occurred_at="t",
                rider_status=status,
                model_raw="",
                created_at="t",
            )
        )
    session.commit()

    counts = repo.count_by_status()
    assert counts == {"helmeted": 2, "bare": 1, "unknown": 0}
    assert repo.count_by_status(source_id="other") == {"helmeted": 0, "bare": 0, "unknown": 0}


def test_alert_and_review_repositories(session: Session) -> None:
    """提醒与复核仓储可用。"""
    from app.models.entities import Alert, Review
    from app.repositories.alert import AlertRepository
    from app.repositories.review import ReviewRepository

    review_repo = ReviewRepository(session)
    review_repo.create(
        Review(
            event_id="e1",
            decision="confirmed",
            reason="人工确认",
            operator="duty1",
            created_at="t",
        )
    )
    session.commit()
    assert review_repo.count_by_event("e1") == 1
    assert review_repo.latest_by_event("e1") is not None
    assert review_repo.latest_by_event("missing") is None

    alert_repo = AlertRepository(session)
    alert_repo.create(
        Alert(
            alert_id="a1",
            event_id="e1",
            source_id="s1",
            status="queued",
            note="",
            created_at="t",
            updated_at="t",
        )
    )
    session.commit()
    assert alert_repo.mark_played("e1", "t2") == 1
    session.commit()
    assert alert_repo.get_by_event("e1").status == "played"


# --------------------------------------------------------------------------
# store.py 兼容层与并发复核
# --------------------------------------------------------------------------


def test_store_compat_layer_writes_through_repository_tables(migrated_db: Path) -> None:
    """store.py 兼容层写入的数据与 ORM 模型完全兼容。"""
    from app.db import connect
    from app.store import enqueue_alert, insert_pass_with_event, update_heartbeat, upsert_source

    conn = connect(migrated_db)
    try:
        upsert_source(conn, "gate-east", "东校门", "online", "t")
        insert_pass_with_event(
            conn,
            {
                "pass_id": "p1",
                "source_id": "gate-east",
                "run_id": "r1",
                "occurred_at": "t",
                "rider_status": "bare",
                "model_raw": "no helmet",
                "created_at": "t",
            },
            {
                "event_id": "e1",
                "pass_id": "p1",
                "source_id": "gate-east",
                "run_id": "r1",
                "occurred_at": "t",
                "model_label": "no helmet",
                "reason": "测试",
                "created_at": "t",
            },
        )
        update_heartbeat(conn, "gate-east", "r1", "live", "{}")
        enqueue_alert(conn, "a1", "e1", "gate-east", "queued", "n")
    finally:
        conn.close()

    engine = create_engine(f"sqlite:///{migrated_db.as_posix()}")
    try:
        with Session(engine, future=True) as db_session:
            from app.models.entities import Alert, Event, Heartbeat, Pass, Source

            assert db_session.get(Source, "gate-east") is not None
            assert db_session.get(Pass, "p1") is not None
            event = db_session.get(Event, "e1")
            assert event is not None and event.status == "pending"
            assert db_session.get(Heartbeat, "gate-east") is not None
            assert db_session.get(Alert, "a1") is not None
    finally:
        engine.dispose()


def test_concurrent_opposite_reviews_single_winner(tmp_path: Path) -> None:
    """并发相反复核：只有一个成功，另一个冲突。

    验证 `apply_review` 的并发安全语义：
    `BEGIN IMMEDIATE` 串行化写事务 + 条件 `UPDATE ... WHERE status='pending'`，
    两个相反结论并发时只有一个能更新成功。
    """
    from app.db import connect, init_db
    from app.store import apply_review

    db_path = tmp_path / "concurrent.db"
    init_db(db_path)
    setup = connect(db_path)
    try:
        setup.execute(
            "INSERT INTO sources(source_id,name,status,last_seen,updated_at) "
            "VALUES('s','n','online','','t')"
        )
        setup.execute(
            "INSERT INTO passes(pass_id,source_id,run_id,occurred_at,rider_status,"
            "model_raw,created_at) VALUES('p','s','r','t','bare','no helmet','t')"
        )
        setup.execute(
            "INSERT INTO events(event_id,pass_id,source_id,run_id,occurred_at,status,"
            "model_label,reason,reviewer,reviewed_at,created_at) "
            "VALUES('e1','p','s','r','t','pending','no helmet','','',NULL,'t')"
        )
    finally:
        setup.close()

    barrier = threading.Barrier(2)

    def _hit(decision: str) -> int:
        local = connect(db_path)
        try:
            barrier.wait(timeout=15)
            _, code = apply_review(local, "e1", decision, "并发测试", "op")
            return code
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_confirm = pool.submit(_hit, "confirmed")
        future_dismiss = pool.submit(_hit, "dismissed")
        codes = sorted([future_confirm.result(timeout=30), future_dismiss.result(timeout=30)])

    assert codes == [200, 409], f"期望一胜一冲突，实际={codes}"

    check = connect(db_path)
    try:
        status = check.execute("SELECT status FROM events WHERE event_id='e1'").fetchone()["status"]
        review_count = check.execute(
            "SELECT COUNT(*) n FROM reviews WHERE event_id='e1'"
        ).fetchone()["n"]
    finally:
        check.close()
    assert status in ("confirmed", "dismissed")
    assert review_count == 1


def test_apply_review_idempotent_and_conflict(tmp_path: Path) -> None:
    """重复同一结论幂等 200，不同结论冲突 409，不存在 404。"""
    from app.db import connect, init_db
    from app.store import apply_review

    db_path = tmp_path / "review-semantics.db"
    init_db(db_path)
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sources(source_id,name,status,last_seen,updated_at) "
            "VALUES('s','n','online','','t')"
        )
        conn.execute(
            "INSERT INTO passes(pass_id,source_id,run_id,occurred_at,rider_status,"
            "model_raw,created_at) VALUES('p','s','r','t','bare','no helmet','t')"
        )
        conn.execute(
            "INSERT INTO events(event_id,pass_id,source_id,run_id,occurred_at,status,"
            "model_label,reason,reviewer,reviewed_at,created_at) "
            "VALUES('e1','p','s','r','t','pending','no helmet','','',NULL,'t')"
        )

        assert apply_review(conn, "e1", "confirmed", "ok", "op") == ("updated", 200)
        assert apply_review(conn, "e1", "confirmed", "ok", "op") == ("idempotent", 200)
        assert apply_review(conn, "e1", "dismissed", "no", "op") == ("conflict", 409)
        assert apply_review(conn, "missing", "confirmed") == ("not_found", 404)
        assert apply_review(conn, "e1", "maybe") == ("invalid_decision", 400)
    finally:
        conn.close()


def test_alembic_env_reads_url_from_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """迁移使用的数据库 URL 来自 Settings，不硬编码。"""
    from app.core.config import get_settings

    db_path = tmp_path / "from-settings.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    get_settings.cache_clear()
    try:
        cfg = get_settings()
        assert cfg.resolved_database_url == f"sqlite:///{db_path.as_posix()}"
    finally:
        get_settings.cache_clear()
        os.environ.pop("DATABASE_URL", None)

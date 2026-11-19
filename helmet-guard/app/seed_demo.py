"""演示种子：可重复执行，确定性事件标识。7 戴盔、2 未戴盔、1 未知。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from .db import connect, init_db
from .store import insert_pass_with_event, upsert_source

SOURCE_ID = "gate-east"
RUN_ID = "demo-run-001"
BASE_TS = "2026-11-05T08:00:00+00:00"

# 10 条通行：7 helmeted / 2 bare / 1 unknown；bare 生成候选事件
PASSES: list[tuple[str, str]] = [
    ("demo-pass-001", "helmeted"),
    ("demo-pass-002", "helmeted"),
    ("demo-pass-003", "bare"),
    ("demo-pass-004", "helmeted"),
    ("demo-pass-005", "helmeted"),
    ("demo-pass-006", "unknown"),
    ("demo-pass-007", "helmeted"),
    ("demo-pass-008", "bare"),
    ("demo-pass-009", "helmeted"),
    ("demo-pass-010", "helmeted"),
]


def _engine_for_path(path: Path) -> Engine:
    """为给定 SQLite 文件建 Engine（测试/显式库路径用）。

    Args:
        path: SQLite 文件路径。

    Returns:
        指向该文件的 Engine。
    """
    from sqlalchemy import create_engine

    return create_engine(
        f"sqlite:///{path.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )


def _engine_for_seed(db_path: Path | None = None) -> tuple[Engine, bool]:
    """按优先级解析种子用 Engine：显式路径优先，否则走 DATABASE_URL。

    MySQL 兼容：未传 `db_path` 且 `DATABASE_URL` 为 `mysql(+pymysql)://`
    时直接复用 `build_engine()`，ORM 建表与超管/组织种子都落到 MySQL，
    不再建 SQLite 文件。显式传路径时保持原 SQLite 语义，测试隔离不受影响。

    Args:
        db_path: 显式 SQLite 路径；为 None 时走配置解析。

    Returns:
        (engine, is_mysql) 二元组。
    """
    if db_path is not None:
        return _engine_for_path(Path(db_path)), False
    from app.core.config import get_settings
    from app.core.deps import build_engine

    url = get_settings().resolved_database_url
    if url.startswith("mysql"):
        return build_engine(), True
    return build_engine(), False


def _seed_super_admin(engine: Engine) -> None:
    """幂等写入演示超管账号（`u_admin` / `admin`）。

    只写 bcrypt 哈希，**明文绝不入库、不写日志**；默认口令取自环境变量
    `HELMET_GUARD_SEED_ADMIN_PASSWORD`（缺省 `Admin-2026`）。已存在则跳过，
    保证种子可重复执行。传入 Engine，SQLite/MySQL 通用。

    Args:
        engine: SQLAlchemy Engine（已指向目标库）。
    """
    from sqlalchemy.orm import Session

    from app.core.security import hash_password
    from app.models import Base as _OrmBase
    from app.models.identity import User as _User

    try:
        _OrmBase.metadata.create_all(engine, checkfirst=True)
        with Session(engine, future=True) as session:
            if session.get(_User, "u_admin") is not None:
                return
            password = os.getenv("HELMET_GUARD_SEED_ADMIN_PASSWORD", "").strip()
            if not password:
                password = "Admin-2026"
            session.add(
                _User(
                    user_id="u_admin",
                    username="admin",
                    password_hash=hash_password(password),
                    role="super_admin",
                    status="active",
                )
            )
            session.commit()
    finally:
        # 调用方（MySQL 复用进程级 Engine 场景除外）负责 dispose；
        # 此处显式路径/临时 Engine 由各自调用方关闭，见 seed()。
        pass


def _seed_org_units(engine: Engine) -> None:
    """幂等写入演示组织树（学校→学院→年级→专业→班级）。

    供小程序学籍级联选择开箱即用；已存在任意启用单元则跳过，
    保证种子可重复执行且不覆盖管理员手工维护的数据。

    Args:
        engine: SQLAlchemy Engine（已指向目标库）。
    """
    from sqlalchemy.orm import Session

    from app.models import Base as _OrmBase
    from app.models.identity import OrgUnit as _OrgUnit

    # （unit_id, unit_type, name, parent_id, sort_order）
    rows: list[tuple[str, str, str, str | None, int]] = [
        ("org-school-demo", "school", "示范大学", None, 1),
        ("org-college-cs", "college", "计算机学院", "org-school-demo", 1),
        ("org-college-me", "college", "机械工程学院", "org-school-demo", 2),
        ("org-grade-2024", "grade", "2024 级", "org-college-cs", 1),
        ("org-grade-2025", "grade", "2025 级", "org-college-cs", 2),
        ("org-major-se", "major", "软件工程", "org-grade-2024", 1),
        ("org-major-cst", "major", "计算机科学与技术", "org-grade-2024", 2),
        ("org-class-2401", "class", "计科 2401", "org-major-se", 1),
        ("org-class-2402", "class", "计科 2402", "org-major-se", 2),
    ]
    try:
        _OrmBase.metadata.create_all(engine, checkfirst=True)
        with Session(engine, future=True) as session:
            existing = session.query(_OrgUnit).count()
            if existing > 0:
                return
            for unit_id, unit_type, name, parent_id, order in rows:
                session.add(
                    _OrgUnit(
                        unit_id=unit_id,
                        unit_type=unit_type,
                        name=name,
                        parent_id=parent_id,
                        sort_order=order,
                        status="active",
                    )
                )
            session.commit()
    finally:
        pass


def _seed_passes_mysql(engine: Engine) -> None:
    """MySQL 演示通行 + 候选事件（ORM 路径，避开 sqlite 原生事务）。

    SQLite 高频写入路径保留原生 SQL（`store.py`）；MySQL 种子走 ORM，
    避免 `sqlite_insert.on_conflict` 在 MySQL 方言下语义分叉。

    Args:
        engine: 已指向 MySQL 的 Engine。
    """
    from sqlalchemy.orm import Session

    from app.models.entities import Event as _OrmEvent
    from app.models.entities import Pass as _OrmPass
    from app.models.entities import Source as _OrmSource

    with Session(engine, future=True) as session:
        source = session.get(_OrmSource, SOURCE_ID)
        if source is None:
            session.add(
                _OrmSource(
                    source_id=SOURCE_ID,
                    name="东校门",
                    status="online",
                    last_seen=BASE_TS,
                    updated_at=BASE_TS,
                )
            )
        else:
            source.name = "东校门"
            source.status = "online"
            source.last_seen = BASE_TS
            source.updated_at = BASE_TS
        for i, (pass_id, status) in enumerate(PASSES):
            ts = BASE_TS.replace("08:00:00", f"08:{i:02d}:00")
            model_raw = {"helmeted": "helmet", "bare": "no helmet", "unknown": ""}[status]
            if session.get(_OrmPass, pass_id) is None:
                session.add(
                    _OrmPass(
                        pass_id=pass_id,
                        source_id=SOURCE_ID,
                        run_id=RUN_ID,
                        occurred_at=ts,
                        rider_status=status,
                        model_raw=model_raw,
                        created_at=ts,
                    )
                )
            if status == "bare":
                event_id = f"evt-{pass_id}"
                if session.get(_OrmEvent, event_id) is None:
                    session.add(
                        _OrmEvent(
                            event_id=event_id,
                            pass_id=pass_id,
                            source_id=SOURCE_ID,
                            run_id=RUN_ID,
                            occurred_at=ts,
                            status="pending",
                            model_label="no helmet",
                            reason="demo: 未戴盔候选",
                            reviewer="",
                            created_at=ts,
                        )
                    )
        session.commit()


def seed(db_path: Path | None = None) -> dict[str, Any]:
    from . import get_mode

    explicit_env = os.getenv("HELMET_GUARD_DB", "").strip() != ""
    explicit = explicit_env or db_path is not None
    if get_mode() == "live" and not explicit:
        raise SystemExit(
            "拒绝在 live 默认库执行演示种子："
            "live 环境误跑演示种子已拦截；"
            "如确需写入请设置 HELMET_GUARD_DB 指向临时库"
        )
    # MySQL 路径：未传显式路径且 DATABASE_URL 指向 MySQL 时走 ORM 全量种子。
    if db_path is None and not explicit_env:
        from app.core.config import get_settings

        if get_settings().resolved_database_url.startswith("mysql"):
            engine, _ = _engine_for_seed(None)
            try:
                _seed_super_admin(engine)
                _seed_org_units(engine)
                _seed_passes_mysql(engine)
            finally:
                engine.dispose()
            return {
                "db": get_settings().resolved_database_url,
                "passes": len(PASSES),
                "events": 2,
                "run_id": RUN_ID,
            }
    # SQLite 路径（默认 / 测试显式路径）：保持原原生 SQL 语义。
    path = init_db(db_path)
    engine, _ = _engine_for_seed(path)
    try:
        _seed_super_admin(engine)
        _seed_org_units(engine)
    finally:
        engine.dispose()
    conn = connect(path)
    try:
        upsert_source(conn, SOURCE_ID, "东校门", "online", BASE_TS)
        for i, (pass_id, status) in enumerate(PASSES):
            ts = BASE_TS.replace("08:00:00", f"08:{i:02d}:00")
            model_raw = {"helmeted": "helmet", "bare": "no helmet", "unknown": ""}[status]
            passed = {
                "pass_id": pass_id,
                "source_id": SOURCE_ID,
                "run_id": RUN_ID,
                "occurred_at": ts,
                "rider_status": status,
                "model_raw": model_raw,
                "created_at": ts,
            }
            event = None
            if status == "bare":
                event = {
                    "event_id": f"evt-{pass_id}",
                    "pass_id": pass_id,
                    "source_id": SOURCE_ID,
                    "run_id": RUN_ID,
                    "occurred_at": ts,
                    "model_label": "no helmet",
                    "reason": "demo: 未戴盔候选",
                    "created_at": ts,
                }
            insert_pass_with_event(conn, passed, event)
    finally:
        conn.close()
    return {"db": str(path), "passes": len(PASSES), "events": 2, "run_id": RUN_ID}


def main() -> None:
    info = seed()
    print(
        f"seed ok: db={info['db']} passes={info['passes']} "
        f"events={info['events']} run={info['run_id']}"
    )


if __name__ == "__main__":
    main()

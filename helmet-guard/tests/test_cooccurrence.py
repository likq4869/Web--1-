"""车辆共现与图匹配测试：领域纯函数 + 仓储 + 服务 + 集成推断。"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.cooccurrence import (
    CooccurrenceStats,
    build_windows,
    compute_cooccurrence,
    jaccard,
    resolve_by_graph,
)
from app.models.identity import IdentityResolution, Student, Vehicle
from app.repositories.cooccurrence import VehicleCooccurrenceRepository, normalize_pair

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _alembic_config(db_path: Path) -> Config:
    """构造指向临时库的 Alembic 配置。"""
    config = Config(str(PROJECT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return config


def _stats(conf: float) -> CooccurrenceStats:
    """构造指定置信度的共现统计（测试桩）。"""
    return CooccurrenceStats(
        vehicle_a="a",
        vehicle_b="b",
        shared_windows=3,
        union_windows=3,
        jaccard=1.0,
        confidence=conf,
    )


# --------------------------------------------------------------------------- #
# build_windows
# --------------------------------------------------------------------------- #


def test_build_windows_aligns_to_utc_epochs() -> None:
    """同一窗口内的时刻映射到同一索引，相邻窗口递增 1。"""
    base = datetime(2024, 1, 1, 8, 0, tzinfo=UTC)
    windows = build_windows(
        [base, base + timedelta(minutes=4, seconds=59), base + timedelta(minutes=5)],
        window_minutes=5,
    )
    assert windows[0] == windows[1]
    assert windows[2] == windows[0] + 1


def test_build_windows_cross_hour_and_cross_day() -> None:
    """跨小时与跨天无需特殊处理：纪元除法天然对齐边界。"""
    hour_edge = build_windows(
        [
            datetime(2024, 3, 10, 9, 59, 30, tzinfo=UTC),
            datetime(2024, 3, 10, 10, 0, 30, tzinfo=UTC),
        ],
        window_minutes=5,
    )
    assert hour_edge[1] == hour_edge[0] + 1
    day_edge = build_windows(
        [
            datetime(2024, 1, 1, 0, 4, 59, tzinfo=UTC),
            datetime(2024, 1, 1, 0, 5, 0, tzinfo=UTC),
        ],
        window_minutes=5,
    )
    assert day_edge[0] + 1 == day_edge[1]
    assert build_windows([], window_minutes=5) == []


def test_build_windows_rejects_non_positive_span() -> None:
    """非正窗口直接报错。"""
    with pytest.raises(ValueError):
        build_windows([datetime(2024, 1, 1, tzinfo=UTC)], window_minutes=0)


def test_build_windows_naive_treated_as_utc() -> None:
    """naive 时间视为 UTC（与 SQLite 读出的 CURRENT_TIMESTAMP 一致）。"""
    naive = datetime(2024, 1, 1, 8, 0)
    aware = datetime(2024, 1, 1, 8, 0, tzinfo=UTC)
    assert build_windows([naive]) == build_windows([aware])


# --------------------------------------------------------------------------- #
# jaccard
# --------------------------------------------------------------------------- #


def test_jaccard_basic_and_empty() -> None:
    """基础交并比；两空集返回 0（无证据而非完全相同）。"""
    assert jaccard({1, 2, 3}, {2, 3, 4}) == pytest.approx(0.5)
    assert jaccard({1}, {1}) == pytest.approx(1.0)
    assert jaccard(set(), set()) == 0.0
    assert jaccard({1}, set()) == 0.0


# --------------------------------------------------------------------------- #
# compute_cooccurrence
# --------------------------------------------------------------------------- #


def test_compute_cooccurrence_always_together_is_high() -> None:
    """两车总是一起出现 → Jaccard 1.0、置信度饱和到 1.0。"""
    stats = compute_cooccurrence({"v1": {1, 2, 3, 4}, "v2": {1, 2, 3, 4}})
    item = stats[("v1", "v2")]
    assert item.shared_windows == 4
    assert item.union_windows == 4
    assert item.jaccard == pytest.approx(1.0)
    assert item.confidence == pytest.approx(1.0)


def test_compute_cooccurrence_single_shared_is_discounted() -> None:
    """仅共现 1 次即使 Jaccard=1 也只给 1/3 置信（偶然同行不采信）。"""
    stats = compute_cooccurrence({"v1": {7}, "v2": {7}})
    item = stats[("v1", "v2")]
    assert item.jaccard == pytest.approx(1.0)
    assert item.confidence == pytest.approx(1.0 / 3.0)


def test_compute_cooccurrence_partial_overlap() -> None:
    """部分重叠：shared/union 与次数因子相乘。"""
    stats = compute_cooccurrence({"v1": {1, 2, 3}, "v2": {2, 3, 4, 5}})
    item = stats[("v1", "v2")]
    assert item.shared_windows == 2
    assert item.union_windows == 5
    assert item.jaccard == pytest.approx(0.4)
    assert item.confidence == pytest.approx(0.4 * 2 / 3)


def test_compute_cooccurrence_no_overlap_and_single_vehicle() -> None:
    """零交集 → 全零；不足两辆车 → 空字典。"""
    stats = compute_cooccurrence({"v1": {1}, "v2": {2}})
    item = stats[("v1", "v2")]
    assert item.jaccard == 0.0
    assert item.confidence == 0.0
    assert compute_cooccurrence({"solo": {1}}) == {}
    assert compute_cooccurrence({}) == {}


# --------------------------------------------------------------------------- #
# resolve_by_graph
# --------------------------------------------------------------------------- #


def _cooc(conf: float, first: str = "v_known", second: str = "v_unknown") -> dict:
    """构造两车共现字典桩。"""
    first_key, second_key = (
        (first, second) if first <= second else (second, first)
    )
    return {(first_key, second_key): _stats(conf)}


def test_resolve_by_graph_assigns_unknown_to_owner() -> None:
    """未知车与某学号名下已知车强共现 → 分配给该学号。"""
    result = resolve_by_graph(
        {"v1": "S001"}, _cooc(0.9, "v1", "vx"), min_conf=0.60
    )
    assert result == {"vx": ("S001", pytest.approx(0.9))}


def test_resolve_by_graph_one_vehicle_one_student() -> None:
    """一车不能分配给两个学生：利润低的边被一对一约束淘汰。"""
    cooc = {
        **_cooc(0.95, "v1", "vx"),
        **_cooc(0.90, "v2", "vx"),
    }
    result = resolve_by_graph({"v1": "S001", "v2": "S002"}, cooc, min_conf=0.60)
    assert result == {"vx": ("S001", pytest.approx(0.95))}
    subjects = list(result.values())
    assert len({subject for subject, _ in subjects}) == len(subjects)


def test_resolve_by_graph_one_student_one_vehicle() -> None:
    """一人不能认领两辆车：第二辆未知车落选。"""
    cooc = {
        **_cooc(0.95, "v1", "vx"),
        **_cooc(0.90, "v1", "vy"),
    }
    result = resolve_by_graph({"v1": "S001"}, cooc, min_conf=0.60)
    assert set(result) == {"vx"}
    assert result["vx"][0] == "S001"


def test_resolve_by_graph_three_way_competition() -> None:
    """三车互斥：总利润最大的全局分配胜出（匈牙利），而非局部贪心。"""
    cooc = {
        **_cooc(0.99, "v1", "vx"),
        **_cooc(0.98, "v1", "vy"),
        **_cooc(0.98, "v2", "vx"),
        **_cooc(0.60, "v2", "vy"),
    }
    result = resolve_by_graph(
        {"v1": "S001", "v2": "S002"}, cooc, min_conf=0.60
    )
    # 匈牙利选 (vx→S002 0.98, vy→S001 0.98)，总 1.96；
    # 贪心先取 (vx→S001 0.99) 会把 S001 占掉，只剩 (vy→S002 0.60)，总 1.59。
    assert result["vx"] == ("S002", pytest.approx(0.98))
    assert result["vy"] == ("S001", pytest.approx(0.98))


def test_resolve_by_graph_min_conf_filters_weak_edges() -> None:
    """低于准入线的边不参与分配。"""
    result = resolve_by_graph(
        {"v1": "S001"}, _cooc(0.59, "v1", "vx"), min_conf=0.60
    )
    assert result == {}


def test_resolve_by_graph_rejects_bad_threshold() -> None:
    """准入线越界直接报错。"""
    with pytest.raises(ValueError):
        resolve_by_graph({"v1": "S001"}, _cooc(0.9, "v1", "vx"), min_conf=1.5)


def test_resolve_by_graph_empty_inputs() -> None:
    """无已知车或无共现时返回空，不报错。"""
    assert resolve_by_graph({}, _cooc(0.9, "v1", "vx")) == {}
    assert resolve_by_graph({"v1": "S001"}, {}) == {}


def test_resolve_by_graph_normalizes_reversed_keys() -> None:
    """逆序共现键被规范化：(v1,vx) 与 (vx,v1) 冲突时取最大置信度。"""
    low = _cooc(0.70, "v1", "vx")
    sorted_key = ("v1", "vx") if "v1" <= "vx" else ("vx", "v1")
    assert sorted_key in low
    merged = dict(low)
    reversed_key = ("vx", "v1") if sorted_key == ("v1", "vx") else ("v1", "vx")
    merged[reversed_key] = _stats(0.95)
    result = resolve_by_graph({"v1": "S001"}, merged, min_conf=0.60)
    assert result == {"vx": ("S001", pytest.approx(0.95))}


def test_resolve_by_graph_greedy_fallback_matches_hungarian_on_simple_case() -> None:
    """scipy 缺失降级路径：强制贪心在简单场景下结果与匈牙利一致。"""
    cooc = _cooc(0.9, "v1", "vx")
    assert resolve_by_graph({"v1": "S001"}, cooc, use_scipy=False) == resolve_by_graph(
        {"v1": "S001"}, cooc, use_scipy=True
    )


def test_resolve_by_graph_import_error_falls_back_to_greedy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模拟 scipy 不可用：注入失败的导入 → 自动降级为贪心且结果正确。"""
    import builtins

    real_import = builtins.__import__

    def fake_import(
        name: str, *args: object, **kwargs: object
    ) -> object:
        if name.startswith("scipy"):
            raise ImportError("模拟 scipy 缺失")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # 同时屏蔽已缓存的 scipy 模块，确保走 except ImportError 分支。
    monkeypatch.delitem(sys.modules, "scipy.optimize", raising=False)
    monkeypatch.delitem(sys.modules, "scipy", raising=False)
    result = resolve_by_graph(
        {"v1": "S001"}, _cooc(0.9, "v1", "vx"), min_conf=0.60
    )
    assert result == {"vx": ("S001", pytest.approx(0.9))}


# --------------------------------------------------------------------------- #
# 仓储
# --------------------------------------------------------------------------- #


def test_normalize_pair_orders_and_rejects() -> None:
    """规范序保证 (a,b) 唯一；同车/空 ID 拒绝。"""
    assert normalize_pair("v2", "v1") == ("v1", "v2")
    with pytest.raises(ValueError):
        normalize_pair("v1", "v1")
    with pytest.raises(ValueError):
        normalize_pair("", "v1")


def test_cooccurrence_repository_upsert_and_query(tmp_path: Path) -> None:
    """仓储：upsert 幂等更新 + 双向查询 + 排序 + 清空。"""
    import contextlib

    db_path = tmp_path / "cooc-repo.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session:
            repo = VehicleCooccurrenceRepository(session)
            first = repo.upsert("v2", "v1", window_count=2, jaccard=0.5)
            session.commit()
            assert (first.vehicle_a, first.vehicle_b) == ("v1", "v2")
            # 逆序查询命中同一行；再次 upsert 覆盖而非新增。
            assert repo.get_pair("v1", "v2") is not None
            repo.upsert("v1", "v2", window_count=3, jaccard=0.8)
            session.commit()
            stored = repo.get_pair("v2", "v1")
            assert stored is not None
            assert stored.window_count == 3
            assert stored.jaccard == pytest.approx(0.8)
            assert repo.get_pair("v1", "v1") is None
            repo.upsert("v1", "v3", window_count=1, jaccard=0.2)
            session.commit()
            assert [r.vehicle_b for r in repo.list_for_vehicle("v1")] == ["v2", "v3"]
            assert len(repo.list_all()) == 2
            assert repo.delete_all() == 2
            session.commit()
            assert repo.list_all() == []
            with contextlib.suppress(Exception):
                session.rollback()
    finally:
        engine.dispose()


def test_cooccurrence_repository_rejects_bad_values(tmp_path: Path) -> None:
    """非法参数（负数/越界/同车）直接拒绝。"""
    db_path = tmp_path / "cooc-bad.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session:
            repo = VehicleCooccurrenceRepository(session)
            with pytest.raises(ValueError):
                repo.upsert("v1", "v2", window_count=-1, jaccard=0.5)
            with pytest.raises(ValueError):
                repo.upsert("v1", "v2", window_count=1, jaccard=1.5)
            with pytest.raises(ValueError):
                repo.upsert("v1", "v1", window_count=1, jaccard=0.5)
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- #
# 服务层：全量重算 / 增量更新 / 提示构造
# --------------------------------------------------------------------------- #


def _seed_vehicles(session: Session, specs: list[tuple[str, str | None]]) -> None:
    """写入车辆档案桩。"""
    for vehicle_id, owner_id in specs:
        session.add(
            Vehicle(
                vehicle_id=vehicle_id,
                plate_no=None,
                plate_type=None,
                owner_id=owner_id,
                owner_bind_type=None,
                confidence=0.0,
                color_hist=None,
                embedding=None,
                first_seen=None,
                last_seen=None,
                status="active",
            )
        )
    session.commit()


def _seed_resolutions(
    session: Session, rows: list[tuple[str, str, datetime]]
) -> None:
    """写入判定历史桩（事件/车辆/创建时间）。"""
    for event_id, vehicle_id, moment in rows:
        session.add(
            IdentityResolution(
                event_id=event_id,
                vehicle_id=vehicle_id,
                subject_id=None,
                method="appearance",
                confidence=0.7,
                plate_conf=0.0,
                appearance_conf=0.7,
                cooccur_conf=0.0,
                matched_count=0,
                snapshot_id=None,
                created_at=moment,
            )
        )
    session.commit()


def test_rebuild_cooccurrence_computes_and_persists(tmp_path: Path) -> None:
    """全量重算：两车同窗口 3 次 → 落库 jaccard=1.0，共现证据可用。"""
    from app.services.identity.cooccurrence import rebuild_cooccurrence

    db_path = tmp_path / "cooc-rebuild.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session:
            base = datetime(2024, 5, 6, 8, 0, tzinfo=UTC)
            _seed_resolutions(
                session,
                [
                    (f"e1{i}", "v1", base + timedelta(minutes=5 * i))
                    for i in range(3)
                ]
                + [
                    (f"e2{i}", "v2", base + timedelta(minutes=5 * i))
                    for i in range(3)
                ],
            )
            stats = rebuild_cooccurrence(session)
            session.commit()
            assert set(stats) == {("v1", "v2")}
            assert stats[("v1", "v2")].jaccard == pytest.approx(1.0)
            repo = VehicleCooccurrenceRepository(session)
            stored = repo.get_pair("v1", "v2")
            assert stored is not None
            assert stored.window_count == 3
            assert stored.jaccard == pytest.approx(1.0)
    finally:
        engine.dispose()


def test_update_cooccurrence_increments_within_window(tmp_path: Path) -> None:
    """增量更新：同窗口配对计数 +1；同窗口重复调用去重。"""
    from app.services.identity.cooccurrence import update_cooccurrence

    db_path = tmp_path / "cooc-incr.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session:
            moment = datetime(2024, 5, 6, 8, 2, tzinfo=UTC)
            _seed_resolutions(session, [("e1", "v2", moment)])
            updated = update_cooccurrence(session, "v1", moment)
            session.commit()
            assert updated == [("v1", "v2")]
            repo = VehicleCooccurrenceRepository(session)
            assert repo.get_pair("v1", "v2") is not None
            assert repo.get_pair("v1", "v2").window_count == 1  # type: ignore[union-attr]
            # 同窗口再次调用不重复计数。
            assert update_cooccurrence(session, "v1", moment) == []
            session.commit()
            assert repo.get_pair("v1", "v2").window_count == 1  # type: ignore[union-attr]
            # 下一窗口再次同行 → 计数 +1（需先落库同伴在该窗口的出现）。
            later = moment + timedelta(minutes=5)
            _seed_resolutions(session, [("e2", "v2", later)])
            assert update_cooccurrence(session, "v1", later) == [("v1", "v2")]
            session.commit()
            assert repo.get_pair("v1", "v2").window_count == 2  # type: ignore[union-attr]
    finally:
        engine.dispose()


def test_update_cooccurrence_rejects_empty_vehicle(tmp_path: Path) -> None:
    """空车辆 ID 直接拒绝。"""
    from app.services.identity.cooccurrence import update_cooccurrence

    db_path = tmp_path / "cooc-empty.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session, pytest.raises(ValueError):
            update_cooccurrence(session, "")
    finally:
        engine.dispose()


def test_hints_for_vehicle_skips_unbound_partners(tmp_path: Path) -> None:
    """提示构造：对方无绑定学号时跳过，只返回可指向学生的提示。"""
    from app.services.identity.cooccurrence import hints_for_vehicle

    db_path = tmp_path / "cooc-hints.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session:
            session.add(
                Student(
                    student_id="S001",
                    name="张三",
                    status="active",
                )
            )
            _seed_vehicles(session, [("v1", "S001"), ("v2", None), ("vx", None)])
            repo = VehicleCooccurrenceRepository(session)
            repo.upsert("vx", "v1", window_count=3, jaccard=1.0)
            repo.upsert("vx", "v2", window_count=3, jaccard=1.0)
            session.commit()
            hints = hints_for_vehicle(session, "vx")
            assert len(hints) == 1
            assert hints[0].vehicle_id == "v1"
            assert hints[0].subject_id == "S001"
            assert hints[0].jaccard == pytest.approx(1.0)
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- #
# 服务层：_parse_moment / _window_bounds / 空库行为
# --------------------------------------------------------------------------- #


def test_parse_moment_variants() -> None:
    """时间解析：datetime/ISO/Z后缀/naive/None/空串/非法串。"""
    from app.services.identity.cooccurrence import _parse_moment, _window_bounds

    assert _parse_moment(None) is None
    aware = datetime(2024, 5, 6, 8, 0, tzinfo=UTC)
    assert _parse_moment(aware) == aware
    naive = datetime(2024, 5, 6, 8, 0)
    assert _parse_moment(naive) == naive.replace(tzinfo=UTC)
    assert _parse_moment("2024-05-06T08:00:00+00:00") == aware
    assert _parse_moment("2024-05-06 08:00:00") == naive.replace(tzinfo=UTC)
    assert _parse_moment("2024-05-06T08:00:00Z") == aware
    assert _parse_moment("") is None
    assert _parse_moment("   ") is None
    assert _parse_moment("not-a-time") is None

    start, end = _window_bounds(aware, 5)
    assert (end - start) == timedelta(minutes=5)
    assert start <= aware < end


def test_update_cooccurrence_accepts_naive_occurred_at(tmp_path: Path) -> None:
    """naive 通行时间视为 UTC，不抛异常。"""
    from app.services.identity.cooccurrence import update_cooccurrence

    db_path = tmp_path / "cooc-naive.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session:
            moment = datetime(2024, 5, 6, 8, 2)
            _seed_resolutions(
                session, [("e1", "v2", moment.replace(tzinfo=UTC))]
            )
            assert update_cooccurrence(session, "v1", moment) == [("v1", "v2")]
            session.commit()
    finally:
        engine.dispose()


def test_collect_vehicle_windows_empty_db_returns_empty(tmp_path: Path) -> None:
    """空库全量重算返回空统计并清空矩阵，不报错。"""
    from app.services.identity.cooccurrence import (
        collect_vehicle_windows,
        rebuild_cooccurrence,
    )

    db_path = tmp_path / "cooc-empty-db.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session:
            assert collect_vehicle_windows(session) == {}
            assert rebuild_cooccurrence(session) == {}
            session.commit()
            assert VehicleCooccurrenceRepository(session).list_all() == []
    finally:
        engine.dispose()


def test_hints_for_vehicle_no_rows_returns_empty(tmp_path: Path) -> None:
    """无共现记录时提示为空。"""
    from app.services.identity.cooccurrence import hints_for_vehicle

    db_path = tmp_path / "cooc-nohints.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session:
            _seed_vehicles(session, [("vx", None)])
            assert hints_for_vehicle(session, "vx") == []
            assert hints_for_vehicle(session, "ghost") == []
    finally:
        engine.dispose()


def test_greedy_tie_break_is_deterministic() -> None:
    """利润并列时字典序小的优先，保证跨进程确定性。"""
    result = resolve_by_graph(
        {"v1": "S002", "v2": "S001"},
        {**_cooc(0.9, "v1", "vx"), **_cooc(0.9, "v2", "vx")},
        min_conf=0.60,
        use_scipy=False,
    )
    assert result == {"vx": ("S001", pytest.approx(0.9))}


# --------------------------------------------------------------------------- #
# 集成：3 学生各 1 车，其中 1 车无牌 → 共现推断归属
# --------------------------------------------------------------------------- #


def test_integration_three_students_unknown_plate_resolved(tmp_path: Path) -> None:
    """集成：S001/v1、S002/v2 已绑定，vx 无归属但与 v1 高频同行 → 推断 vx→S001。

    全链路：判定历史 → rebuild 落库 → hints 取提示 → resolve_by_graph 分配 →
    resolver.collect_cooccur_evidence 产出 COOCCUR 证据。
    """
    from app.services.identity.cooccurrence import hints_for_vehicle, rebuild_cooccurrence
    from app.services.identity.resolver import (
        CooccurHint,
        collect_cooccur_evidence,
        cooccur_confidence,
    )

    db_path = tmp_path / "cooc-integration.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as session:
            for number, name in (("S001", "张三"), ("S002", "李四"), ("S003", "王五")):
                session.add(Student(student_id=number, name=name, status="active"))
            _seed_vehicles(
                session,
                [("v1", "S001"), ("v2", "S002"), ("v3", "S003"), ("vx", None)],
            )
            base = datetime(2024, 5, 6, 8, 0, tzinfo=UTC)
            rows: list[tuple[str, str, datetime]] = []
            # vx 与 v1 连续 5 天同窗口出现；v2/v3 各自独立出现。
            for day in range(5):
                moment = base + timedelta(days=day)
                rows.append((f"evx{day}", "vx", moment))
                rows.append((f"ev1{day}", "v1", moment + timedelta(minutes=1)))
                rows.append((f"ev2{day}", "v2", moment + timedelta(hours=2)))
                rows.append((f"ev3{day}", "v3", moment + timedelta(hours=4)))
            _seed_resolutions(session, rows)
            stats = rebuild_cooccurrence(session)
            session.commit()
            assert stats[("v1", "vx")].shared_windows == 5
            assert stats[("v1", "vx")].confidence == pytest.approx(1.0)

            hints = hints_for_vehicle(session, "vx")
            assert hints, "应为无牌车产出共现提示"
            assert hints[0].subject_id == "S001"

            allocation = resolve_by_graph(
                {"v1": "S001", "v2": "S002", "v3": "S003"},
                stats,
                min_conf=0.60,
            )
            assert allocation["vx"][0] == "S001"

            evidence = collect_cooccur_evidence(
                [
                    CooccurHint(
                        vehicle_id=h.vehicle_id,
                        subject_id=h.subject_id,
                        jaccard=h.jaccard,
                    )
                    for h in hints
                ]
            )
            assert evidence is not None
            assert evidence.subject_id == "S001"
            assert evidence.confidence == pytest.approx(cooccur_confidence(1.0))
            # 共现单独无法 BIND：钳制上限 0.55 < SUGGEST 线 0.60。
            assert evidence.confidence < 0.60
    finally:
        engine.dispose()

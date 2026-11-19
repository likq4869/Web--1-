"""积分台账测试：迁移结构、仓储只增不改、台账一致性不变量与并发安全。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.models.identity import Student
from app.models.scoring import ScoreAccount
from app.repositories.scoring import (
    ScoreAccountRepository,
    ScoreLedgerRepository,
    ScoreRuleRepository,
)
from app.services.scoring.ledger import LedgerService

PROJECT_DIR = Path(__file__).resolve().parent.parent

SCORING_TABLES = {"score_accounts", "score_ledger", "score_rules"}


def _alembic_config(db_path: Path) -> Config:
    """构造指向临时库的 Alembic 配置。"""
    config = Config(str(PROJECT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return config


def _seed_student(db_session: Session, student_id: str = "2022110508") -> None:
    """预置学生行（满足 score_ledger 外键，幂等）。"""
    if db_session.get(Student, student_id) is None:
        db_session.add(
            Student(student_id=student_id, user_id=None, name="测试学生", status="active")
        )
        db_session.flush()


def _fresh_session(db_path: Path) -> Session:
    """为并发线程创建独立 Engine + Session（各线程独立连接）。"""
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    return Session(engine, future=True)


def test_scoring_tables_created_by_migration(tmp_path: Path) -> None:
    """升级到 head 后积分域 3 张表全部存在。"""
    db_path = tmp_path / "scoring.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert tables >= SCORING_TABLES


def test_scoring_downgrade_removes_only_scoring_tables(tmp_path: Path) -> None:
    """回滚 0004 后仅积分域表被清除，身份域与 P0 基线保留。"""
    db_path = tmp_path / "scoring-rollback.db"
    config = _alembic_config(db_path)
    command.upgrade(config, "head")
    command.downgrade(config, "0003_identity_admin")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert SCORING_TABLES.isdisjoint(tables)
    assert {"users", "students", "vehicles"} <= tables
    assert {"sources", "passes", "events"} <= tables
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert tables >= SCORING_TABLES


def test_ledger_repository_is_append_only(tmp_path: Path) -> None:
    """流水仓储禁用 UPDATE/DELETE（只增不改硬约束）。"""
    db_path = tmp_path / "append-only.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as db_session:
            _seed_student(db_session)
            db_session.commit()
            service = LedgerService(db_session)
            entry = service.apply("2022110508", -1, "LATE", "测试")
            assert entry.ledger_id is not None
            repo = ScoreLedgerRepository(db_session)
            with pytest.raises(RuntimeError):
                repo.update(entry, change=0)
            with pytest.raises(RuntimeError):
                repo.bulk_update({"student_id": "2022110508"}, change=0)
            with pytest.raises(RuntimeError):
                repo.delete(entry)
            with pytest.raises(RuntimeError):
                repo.delete_by(student_id="2022110508")
    finally:
        engine.dispose()


def test_balance_equals_sum_of_changes(tmp_path: Path) -> None:
    """任意流水序列后 balance == 初始余额 + sum(change)。"""
    db_path = tmp_path / "invariant.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as db_session:
            _seed_student(db_session)
            db_session.commit()
            service = LedgerService(db_session)
            service.apply("2022110508", -1, "R1", "第一次")
            service.apply("2022110508", -3, "R2", "第二次")
            service.apply("2022110508", 2, "AWARD", "奖励")

            account = db_session.get(ScoreAccount, "2022110508")
            assert account is not None
            repo = ScoreLedgerRepository(db_session)
            total = repo.sum_change_by_student("2022110508")
            assert total == -2
            assert int(account.balance) == 100 + total
            assert int(account.total_deducted) == 4
            assert int(account.total_awarded) == 2
            assert account.level == "S"
    finally:
        engine.dispose()


def test_revert_inserts_reversing_entry(tmp_path: Path) -> None:
    """revert 后余额回到原值，且流水条数 +1（原流水不动）。"""
    db_path = tmp_path / "revert.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as db_session:
            _seed_student(db_session)
            db_session.commit()
            service = LedgerService(db_session)
            original = service.apply("2022110508", -3, "REPEAT", "扣分")
            before = service.get_balance("2022110508")
            assert before == 97
            repo = ScoreLedgerRepository(db_session)
            count_before = repo.count_by_student("2022110508")

            reversed_entry = service.revert(int(original.ledger_id), "申诉成立")
            assert int(reversed_entry.change) == 3
            assert reversed_entry.reason_code == "REVERT"
            assert service.get_balance("2022110508") == 100
            assert repo.count_by_student("2022110508") == count_before + 1
            # 原流水原样保留。
            kept = db_session.get(type(original), int(original.ledger_id))
            assert kept is not None and int(kept.change) == -3

            with pytest.raises(NotFoundError):
                service.revert(999999, "不存在")
    finally:
        engine.dispose()


def test_balance_floor_and_ceiling(tmp_path: Path) -> None:
    """余额下限/上限触发业务异常，且失败不落流水。"""
    db_path = tmp_path / "bounds.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as db_session:
            _seed_student(db_session)
            db_session.commit()
            service = LedgerService(db_session)
            with pytest.raises(ValidationError):
                service.apply("2022110508", -101, "OVER", "超扣")
            with pytest.raises(ValidationError):
                service.apply("2022110508", 1, "OVER", "超发", max_balance=100)
            with pytest.raises(ValidationError):
                service.apply("2022110508", 0, "ZERO", "零变动")
            repo = ScoreLedgerRepository(db_session)
            assert repo.count_by_student("2022110508") == 0
            assert service.get_balance("2022110508") == 100
    finally:
        engine.dispose()


def test_concurrent_deductions_are_serialized(tmp_path: Path) -> None:
    """并发扣分 20 次 × -1：最终余额与流水条数一致，无丢失无负余额。"""
    db_path = tmp_path / "concurrent.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as db_session:
            _seed_student(db_session)
            db_session.commit()

        def _deduct_once(index: int) -> int:
            session = _fresh_session(db_path)
            try:
                service = LedgerService(session)
                entry = service.apply(
                    "2022110508",
                    -1,
                    "CONCURRENT",
                    f"并发{index}",
                    event_id=f"evt-{index}",
                )
                return int(entry.ledger_id)
            finally:
                session.close()
                session.get_bind().dispose()  # type: ignore[union-attr]

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_deduct_once, i) for i in range(20)]
            ledger_ids = sorted(f.result(timeout=60) for f in futures)

        assert len(set(ledger_ids)) == 20
        check_engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
        try:
            with Session(check_engine, future=True) as check:
                assert LedgerService(check).get_balance("2022110508") == 80
                repo = ScoreLedgerRepository(check)
                assert repo.count_by_student("2022110508") == 20
                assert repo.sum_change_by_student("2022110508") == -20
                rows, total = LedgerService(check).list_ledger(
                    "2022110508", page=1, page_size=10
                )
                assert total == 20
                assert len(rows) == 10
        finally:
            check_engine.dispose()
    finally:
        engine.dispose()


def test_score_rule_repository_lists_enabled_in_order(tmp_path: Path) -> None:
    """规则仓储：仅返回启用规则，按 priority 降序排列。"""
    from app.models.scoring import ScoreRule

    db_path = tmp_path / "rules.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    try:
        with Session(engine, future=True) as db_session:
            repo = ScoreRuleRepository(db_session)
            repo.create(
                ScoreRule(
                    rule_id="low",
                    rule_type="deduct",
                    name="低优",
                    condition_json={"field": "violation_count_30d", "op": ">=", "value": 1},
                    score_change=-1,
                    priority=0,
                    enabled=True,
                )
            )
            repo.create(
                ScoreRule(
                    rule_id="high",
                    rule_type="deduct",
                    name="高优",
                    condition_json={"field": "violation_count_30d", "op": ">=", "value": 3},
                    score_change=-3,
                    priority=10,
                    enabled=True,
                )
            )
            repo.create(
                ScoreRule(
                    rule_id="off",
                    rule_type="award",
                    name="关闭",
                    condition_json={"field": "streak_days", "op": ">=", "value": 30},
                    score_change=2,
                    priority=99,
                    enabled=False,
                )
            )
            db_session.commit()
            enabled = repo.list_enabled()
            assert [item.rule_id for item in enabled] == ["high", "low"]
            assert ScoreAccountRepository(db_session).get_or_create("2022110508") is not None
    finally:
        engine.dispose()

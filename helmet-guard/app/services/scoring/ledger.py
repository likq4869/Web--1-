"""积分台账服务：单事务记账、申诉冲正、余额查询。

职责：收敛积分变更的事务边界、余额上下限校验、等级重算与审计留痕。
依赖：sqlalchemy 会话、积分仓储、积分领域函数、审计仓储。
边界：不做 HTTP 解析；事务边界全部在本模块内明确，异常必回滚。

事务流程图（apply 一次记账）::

    调用方 -> LedgerService.apply()
      1. BEGIN（SQLite 下为 BEGIN IMMEDIATE，串行化写事务）
      2. SELECT score_accounts 行（PG 下 FOR UPDATE 行锁）
         不存在 -> 按初始余额建行
      3. 校验：balance_after ∈ [min_balance, max_balance]，否则回滚并抛错
      4. INSERT score_ledger 流水（只增不改）
      5. UPDATE score_accounts（balance / 累计 / level / updated_at）
      6. INSERT audit_logs（scoring.apply）
      7. COMMIT；异常 -> ROLLBACK 原样抛出

并发说明：PG 靠 SELECT ... FOR UPDATE 行锁串行化同一学生；
SQLite 无行锁，靠 BEGIN IMMEDIATE 持有保留锁 + 操作失败重试
（database is locked 时退避重做，最多 10 次）。
"""

from __future__ import annotations

import time

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.domain.scoring import (
    SCORE_INITIAL_BALANCE,
    SCORE_MAX_BALANCE,
    SCORE_MIN_BALANCE,
    level_from_score,
)
from app.models.scoring import ScoreAccount, ScoreLedger
from app.repositories.audit import AuditRepository
from app.repositories.scoring import ScoreLedgerRepository

# SQLite 锁冲突重试上限与退避基数（秒）。
_LOCK_RETRY_TIMES = 10
_LOCK_RETRY_BASE_SECONDS = 0.05


class LedgerService:
    """积分台账服务（绑定单个会话，事务由方法内部管理）。"""

    def __init__(self, session: Session) -> None:
        """初始化服务。

        Args:
            session: 数据库会话；事务由本服务的方法显式管理。
        """
        self.session = session

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _begin_immediate(self) -> None:
        """SQLite 下抢占保留锁；PG 下为空操作（靠 FOR UPDATE 行锁）。

        仅当会话尚未开启事务时执行，避免嵌套 BEGIN 报错。
        """
        bind = self.session.get_bind()
        dialect = getattr(getattr(bind, "dialect", None), "name", "sqlite")
        if dialect != "sqlite":
            return
        if self.session.in_transaction():
            return
        self.session.execute(text("BEGIN IMMEDIATE"))

    def _lock_account(self, student_id: str) -> ScoreAccount:
        """锁定并返回账户行；不存在则创建（调用方需处于事务内）。"""
        statement = (
            select(ScoreAccount)
            .where(ScoreAccount.student_id == student_id)
            .with_for_update()
        )
        try:
            account = self.session.execute(statement).scalar_one_or_none()
        except OperationalError:
            # PG 等不支持 FOR UPDATE 的方言降级为普通读（测试兼容）。
            account = self.session.get(ScoreAccount, student_id)
        if account is not None:
            return account
        created = ScoreAccount(
            student_id=student_id,
            balance=SCORE_INITIAL_BALANCE,
            total_deducted=0,
            total_awarded=0,
            level=level_from_score(SCORE_INITIAL_BALANCE),
            streak_days=0,
            compliance_rate=1.0,
        )
        self.session.add(created)
        self.session.flush()
        return created

    def _insert_ledger(
        self,
        *,
        student_id: str,
        change: int,
        balance_after: int,
        reason_code: str,
        reason_text: str | None,
        event_id: str | None,
        decision_id: str | None,
        operator: str | None,
    ) -> ScoreLedger:
        """插入一条流水并返回（不提交，由调用方控制事务）。"""
        entry = ScoreLedger(
            student_id=student_id,
            change=change,
            balance_after=balance_after,
            reason_code=reason_code,
            reason_text=reason_text,
            event_id=event_id,
            decision_id=decision_id,
            operator=operator,
        )
        self.session.add(entry)
        self.session.flush()
        return entry

    def _write_audit(
        self,
        *,
        operator: str,
        action: str,
        student_id: str,
        detail: str,
    ) -> None:
        """写入审计日志（与记账同事务，失败一起回滚）。"""
        AuditRepository(self.session).log(
            actor=operator,
            role="system",
            action=action,
            object_type="score_ledger",
            object_id=student_id,
            result="ok",
            detail=detail,
        )

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def apply(
        self,
        student_id: str,
        change: int,
        reason_code: str,
        reason_text: str | None = None,
        event_id: str | None = None,
        decision_id: str | None = None,
        operator: str | None = None,
        *,
        min_balance: int = SCORE_MIN_BALANCE,
        max_balance: int = SCORE_MAX_BALANCE,
    ) -> ScoreLedger:
        """记一笔积分变更（单个事务：锁行 → 校验 → 插流水 → 更新账户 → 审计）。

        Args:
            student_id: 学号。
            change: 变动分（正数为加分，负数为扣分；0 视为非法）。
            reason_code: 原因码。
            reason_text: 人话理由。
            event_id: 关联事件。
            decision_id: 关联决策。
            operator: 操作人（system 或管理员账号）。
            min_balance: 余额下限（默认 0）。
            max_balance: 余额上限（默认 100）。

        Returns:
            新插入的流水记录。

        Raises:
            ValidationError: change 为 0 / 非整数 / 越界（余额不足或超上限）。
        """
        if isinstance(change, bool) or not isinstance(change, int):
            raise ValidationError(f"积分变动必须为整数，实际 {change!r}")
        if change == 0:
            raise ValidationError("积分变动不能为 0")
        if not reason_code or not reason_code.strip():
            raise ValidationError("reason_code 必填")
        last_error: Exception | None = None
        for attempt in range(_LOCK_RETRY_TIMES):
            try:
                self._begin_immediate()
                account = self._lock_account(student_id)
                balance_after = int(account.balance) + change
                if balance_after < min_balance:
                    raise ValidationError(
                        f"余额不足：当前 {account.balance}，变动 {change:+d}，"
                        f"下限 {min_balance}",
                        details={"student_id": student_id, "balance": account.balance},
                    )
                if balance_after > max_balance:
                    raise ValidationError(
                        f"余额超上限：当前 {account.balance}，变动 {change:+d}，"
                        f"上限 {max_balance}",
                        details={"student_id": student_id, "balance": account.balance},
                    )
                entry = self._insert_ledger(
                    student_id=student_id,
                    change=change,
                    balance_after=balance_after,
                    reason_code=reason_code.strip(),
                    reason_text=reason_text,
                    event_id=event_id,
                    decision_id=decision_id,
                    operator=operator,
                )
                account.balance = balance_after
                if change < 0:
                    account.total_deducted = int(account.total_deducted) + abs(change)
                else:
                    account.total_awarded = int(account.total_awarded) + change
                account.level = level_from_score(balance_after)
                self.session.flush()
                self._write_audit(
                    operator=operator or "system",
                    action="scoring.apply",
                    student_id=student_id,
                    detail=(
                        f"change={change:+d} balance={balance_after} "
                        f"reason={reason_code.strip()}"
                    ),
                )
                self.session.commit()
                return entry
            except OperationalError as exc:
                self.session.rollback()
                last_error = exc
                if "locked" in str(exc).lower() and attempt < _LOCK_RETRY_TIMES - 1:
                    time.sleep(_LOCK_RETRY_BASE_SECONDS * (attempt + 1))
                    continue
                raise
            except Exception:
                self.session.rollback()
                raise
        assert last_error is not None  # pragma: no cover - 循环必抛或返回。
        raise last_error  # pragma: no cover - 同上。

    def revert(self, ledger_id: int, reason: str, *, operator: str = "system") -> ScoreLedger:
        """申诉成立时冲正：不修改原流水，插入一条反向流水。

        Args:
            ledger_id: 被冲正的原流水主键。
            reason: 冲正理由（写入新流水的 reason_text）。
            operator: 操作人。

        Returns:
            新插入的反向流水记录。

        Raises:
            NotFoundError: 原流水不存在。
            ValidationError: 冲正后余额越界。
        """
        if not reason or not reason.strip():
            raise ValidationError("冲正理由必填")
        original = self.session.get(ScoreLedger, ledger_id)
        if original is None:
            raise NotFoundError("原流水不存在")
        return self.apply(
            str(original.student_id),
            -int(original.change),
            "REVERT",
            reason.strip(),
            str(original.event_id) if original.event_id is not None else None,
            str(original.decision_id) if original.decision_id is not None else None,
            operator,
        )

    def get_balance(self, student_id: str) -> int:
        """查询当前余额；无账户时视为初始余额（不建行）。

        Args:
            student_id: 学号。

        Returns:
            当前余额。
        """
        account = self.session.get(ScoreAccount, student_id)
        if account is None:
            return SCORE_INITIAL_BALANCE
        return int(account.balance)

    def list_ledger(
        self,
        student_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ScoreLedger], int]:
        """分页列出某学生的流水（按主键倒序）。

        Args:
            student_id: 学号。
            page: 页码（从 1 起）。
            page_size: 每页条数（上限 100）。

        Returns:
            (流水列表, 总数) 二元组。
        """
        safe_page = max(1, page)
        safe_size = min(max(1, page_size), 100)
        repo = ScoreLedgerRepository(self.session)
        rows = repo.list_by_student(
            student_id,
            limit=safe_size,
            offset=(safe_page - 1) * safe_size,
        )
        return rows, repo.count_by_student(student_id)

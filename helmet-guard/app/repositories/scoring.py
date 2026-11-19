"""积分域仓储：账户、流水（只增不改）、规则的数据访问。

职责：封装 score_accounts / score_ledger / score_rules 表的读写。
依赖：sqlalchemy、app.models.scoring。
边界：只做数据访问；余额校验、等级计算与事务编排由服务层负责。

只增不改约束：ScoreLedgerRepository 显式禁用 update/delete 系列方法，
任何调用直接抛错，防止误改审计核心流水。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.sql.selectable import Select

from app.models.scoring import ScoreAccount, ScoreLedger, ScoreRule
from app.repositories.base import BaseRepository


class ScoreAccountRepository(BaseRepository[ScoreAccount]):
    """积分账户仓储（主键为学号）。"""

    model = ScoreAccount
    id_field = "student_id"

    def list_accounts(
        self,
        *,
        keyword: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ScoreAccount]:
        """分页列出积分账户（按学号升序，保证确定性）。

        Args:
            keyword: 模糊匹配学号；为空表示不限。
            limit: 最大返回条数。
            offset: 跳过的记录数.

        Returns:
            账户列表。
        """
        statement = select(ScoreAccount)
        if keyword:
            like = f"%{keyword}%"
            statement = statement.where(ScoreAccount.student_id.like(like))
        statement = statement.order_by(ScoreAccount.student_id.asc()).limit(limit).offset(offset)
        return list(self.session.execute(statement).scalars().all())

    def count_accounts(self, *, keyword: str | None = None) -> int:
        """统计符合条件的账户数（与列表共用过滤口径）。"""
        statement = select(func.count()).select_from(ScoreAccount)
        if keyword:
            statement = statement.where(ScoreAccount.student_id.like(f"%{keyword}%"))
        return int(self.session.execute(statement).scalar_one())

    def count_higher_balance(self, balance: int) -> int:
        """统计余额严格高于给定值的账户数（排名计算用）。

        Args:
            balance: 当前学生余额。

        Returns:
            余额更高的账户数；排名 = 该值 + 1。
        """
        statement = (
            select(func.count())
            .select_from(ScoreAccount)
            .where(ScoreAccount.balance > balance)
        )
        return int(self.session.execute(statement).scalar_one())

    def get_or_create(self, student_id: str, *, initial_balance: int = 100) -> ScoreAccount:
        """获取账户，不存在则创建（余额为初始值）。

        Args:
            student_id: 学号。
            initial_balance: 新账户初始余额。

        Returns:
            账户记录（新创建时已 flush，未 commit）。
        """
        existing = self.session.get(ScoreAccount, student_id)
        if existing is not None:
            return existing
        account = ScoreAccount(
            student_id=student_id,
            balance=initial_balance,
            total_deducted=0,
            total_awarded=0,
            level="B",
            streak_days=0,
            compliance_rate=1.0,
        )
        self.session.add(account)
        self.session.flush()
        return account


class ScoreLedgerRepository(BaseRepository[ScoreLedger]):
    """积分流水仓储（只增不改）。

    继承 BaseRepository 仅复用读与 create 能力；写保护通过重写
    update/delete 系列方法实现，误调用时快速失败。
    """

    model = ScoreLedger
    id_field = "ledger_id"

    # -- 读 --
    def list_by_student(
        self,
        student_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ScoreLedger]:
        """按学生分页列出流水（按主键倒序，保证确定性）。

        Args:
            student_id: 学号。
            limit: 最大返回条数。
            offset: 跳过的记录数。

        Returns:
            流水列表。
        """
        statement = (
            select(ScoreLedger)
            .where(ScoreLedger.student_id == student_id)
            .order_by(ScoreLedger.ledger_id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.execute(statement).scalars().all())

    def list_with_filters(
        self,
        *,
        student_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        direction: str | None = None,
        reason_code: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ScoreLedger]:
        """按多维条件分页列出流水（台账全局视图）。

        Args:
            student_id: 学号精确匹配；为空表示不限。
            start: 生效时间起点（含）；为空表示不限。
            end: 生效时间终点（含）；为空表示不限。
            direction: `positive`（加分）/`negative`（扣分）；为空表示不限。
            reason_code: 原因码精确匹配；为空表示不限。
            limit: 最大返回条数。
            offset: 跳过的记录数。

        Returns:
            流水列表（按主键倒序，保证确定性）。
        """
        statement = select(ScoreLedger)
        statement = self._apply_filters(
            statement,
            student_id=student_id,
            start=start,
            end=end,
            direction=direction,
            reason_code=reason_code,
        )
        statement = statement.order_by(ScoreLedger.ledger_id.desc()).limit(limit).offset(offset)
        return list(self.session.execute(statement).scalars().all())

    def count_with_filters(
        self,
        *,
        student_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        direction: str | None = None,
        reason_code: str | None = None,
    ) -> int:
        """统计符合条件的流水数（与列表共用过滤口径）。"""
        statement = select(func.count()).select_from(ScoreLedger)
        statement = self._apply_filters(
            statement,
            student_id=student_id,
            start=start,
            end=end,
            direction=direction,
            reason_code=reason_code,
        )
        return int(self.session.execute(statement).scalar_one())

    @staticmethod
    def _apply_filters(
        statement: Select[Any],
        *,
        student_id: str | None,
        start: datetime | None,
        end: datetime | None,
        direction: str | None,
        reason_code: str | None,
    ) -> Select[Any]:
        """把台账筛选条件应用到查询语句（列表与计数共用）。"""
        stmt = statement
        if student_id:
            stmt = stmt.where(ScoreLedger.student_id == student_id)
        if start is not None:
            stmt = stmt.where(ScoreLedger.effective_at >= start)
        if end is not None:
            stmt = stmt.where(ScoreLedger.effective_at <= end)
        if direction == "positive":
            stmt = stmt.where(ScoreLedger.change > 0)
        elif direction == "negative":
            stmt = stmt.where(ScoreLedger.change < 0)
        if reason_code:
            stmt = stmt.where(ScoreLedger.reason_code == reason_code)
        return stmt

    def count_by_student(self, student_id: str) -> int:
        """统计某学生的流水条数。

        Args:
            student_id: 学号。

        Returns:
            流水总数。
        """
        statement = (
            select(func.count())
            .select_from(ScoreLedger)
            .where(ScoreLedger.student_id == student_id)
        )
        return int(self.session.execute(statement).scalar_one())

    def sum_change_by_student(self, student_id: str) -> int:
        """汇总某学生的流水变动总额（一致性校验用）。

        Args:
            student_id: 学号。

        Returns:
            SUM(change)，无流水时为 0。
        """
        statement = (
            select(func.coalesce(func.sum(ScoreLedger.change), 0))
            .select_from(ScoreLedger)
            .where(ScoreLedger.student_id == student_id)
        )
        return int(self.session.execute(statement).scalar_one())

    # -- 写保护：禁止 UPDATE/DELETE --
    def update(self, entity: ScoreLedger, **values: Any) -> ScoreLedger:
        """禁用：流水禁止 UPDATE。"""
        _ = (entity, values)
        raise RuntimeError("score_ledger 只增不改，禁止 UPDATE")

    def bulk_update(self, filters: dict[str, Any], **values: Any) -> int:
        """禁用：流水禁止批量 UPDATE。"""
        _ = (filters, values)
        raise RuntimeError("score_ledger 只增不改，禁止 UPDATE")

    def delete(self, entity: ScoreLedger) -> None:
        """禁用：流水禁止 DELETE。"""
        _ = entity
        raise RuntimeError("score_ledger 只增不改，禁止 DELETE")

    def delete_by(self, **filters: Any) -> int:
        """禁用：流水禁止批量 DELETE。"""
        _ = filters
        raise RuntimeError("score_ledger 只增不改，禁止 DELETE")


class ScoreRuleRepository(BaseRepository[ScoreRule]):
    """积分规则仓储。"""

    model = ScoreRule
    id_field = "rule_id"

    def list_all(self) -> list[ScoreRule]:
        """列出全部规则（按 priority 降序、rule_id 升序）。

        Returns:
            规则列表（含启用与停用）。
        """
        statement = select(ScoreRule).order_by(
            ScoreRule.priority.desc(), ScoreRule.rule_id.asc()
        )
        return list(self.session.execute(statement).scalars().all())

    def list_enabled(self) -> list[ScoreRule]:
        """列出全部启用的规则（按 priority 降序、rule_id 升序）。

        Returns:
            启用的规则列表。
        """
        statement = (
            select(ScoreRule)
            .where(ScoreRule.enabled == True)  # noqa: E712  # SQLAlchemy 布尔比较写法。
            .order_by(ScoreRule.priority.desc(), ScoreRule.rule_id.asc())
        )
        return list(self.session.execute(statement).scalars().all())

"""认证基座：users 表新增密码列。

背景：
    P3-0 认证 API 需要用户名密码登录，但 `users` 表原先只有
    `openid / unionid / username / phone / role / status / last_login_at`，
    **没有任何密码列** —— 账号无法登录（AGENTS.md 隐私最小原则要求
    「身份靠车辆登记 + 账号绑定」，账号体系是整套后台的入口）。

    同时后端 `USER_ROLE_VALUES` 只有 6 个取值，而管理后台的 RBAC 矩阵
    （`require_roles`）与前端 `UserRole` 实际使用 9 个角色 ——
    `admin` / `reviewer` / `observer` 三个角色此前在 ORM 层无法写入
    （`Enum(validate_strings=True)` 会拒绝非枚举值）。

变更：
    users 新增一列（可空，向后兼容既有行）：
      - password_hash  VARCHAR：bcrypt 哈希串；明文密码绝不落库。

关于角色枚举的说明（实测结论，勿再重建表）：
    SQLite 上 SQLAlchemy 的 `Enum(native_enum=True)` **不生成 CHECK 约束**
    （实测：建表 SQL 中 role 列无 CHECK，插入任意字符串均不被数据库拒绝）。
    因此：
      - 数据库层原本就没有角色约束，**重建表改 Enum 不会带来任何约束收益**，
        只会增加数据搬迁风险；
      - 角色取值校验发生在 **ORM 层**（`validate_strings=True`），
        故只需扩展 `app.models.identity.USER_ROLE_VALUES` 常量即可，
        **不需要数据库迁移**。
    本迁移因此只做一件事：加密码列。

降级：
    password_hash 列可安全移除（账号退化为无法登录）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_auth"
down_revision = "0006_decision_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为 users 表新增密码列。"""
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("password_hash", sa.String(), nullable=True))


def downgrade() -> None:
    """移除密码列。"""
    with op.batch_alter_table("users") as batch:
        batch.drop_column("password_hash")

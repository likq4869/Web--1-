"""用户仓储：登录账号的查询与状态更新。

职责：封装 users / students 表的账号读取与绑定写入。
依赖：sqlalchemy、app.models.identity。
边界：只做数据访问；密码校验、令牌签发与归属判定由服务层负责。
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models.identity import Student, User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """登录账号仓储。"""

    model = User
    id_field = "user_id"

    def list_with_filters(
        self,
        *,
        keyword: str | None = None,
        role: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[User]:
        """分页列出账号（user_id 升序，保证确定性）。

        Args:
            keyword: 模糊匹配用户名/手机号/用户 ID。
            role: 角色精确匹配。
            status: 状态精确匹配。
            limit: 最大返回条数。
            offset: 跳过的记录数。

        Returns:
            账号列表。
        """
        statement = select(User)
        if keyword:
            like = f"%{keyword}%"
            statement = statement.where(
                (User.username.like(like))
                | (User.phone.like(like))
                | (User.user_id.like(like))
            )
        if role:
            statement = statement.where(User.role == role)
        if status:
            statement = statement.where(User.status == status)
        statement = statement.order_by(User.user_id.asc()).limit(limit).offset(offset)
        return list(self.session.execute(statement).scalars().all())

    def count_with_filters(
        self,
        *,
        keyword: str | None = None,
        role: str | None = None,
        status: str | None = None,
    ) -> int:
        """统计符合条件的账号数（与列表共用口径）。"""
        statement = select(func.count()).select_from(User)
        if keyword:
            like = f"%{keyword}%"
            statement = statement.where(
                (User.username.like(like))
                | (User.phone.like(like))
                | (User.user_id.like(like))
            )
        if role:
            statement = statement.where(User.role == role)
        if status:
            statement = statement.where(User.status == status)
        return int(self.session.execute(statement).scalar_one())

    def find_by_username(self, username: str) -> User | None:
        """按用户名查询账号。

        Args:
            username: 用户名。

        Returns:
            账号对象；不存在时返回 None。
        """
        statement = select(User).where(User.username == username).limit(1)
        return self.session.execute(statement).scalar_one_or_none()

    def find_by_openid(self, openid: str) -> User | None:
        """按微信 openid 查询账号（微信登录幂等入口）。

        Args:
            openid: 微信 openid（含 Mock 派生的 mock- 前缀）。

        Returns:
            账号对象；不存在时返回 None。
        """
        statement = select(User).where(User.openid == openid).limit(1)
        return self.session.execute(statement).scalar_one_or_none()

    def create_wechat_user(
        self, user_id: str, openid: str, unionid: str | None = None, session_key: str | None = None
    ) -> User:
        """创建微信登录账号（role 固定 student，状态 active）。

        Args:
            user_id: 新用户主键（调用方保证唯一）。
            openid: 微信 openid。
            unionid: 微信 unionid（可空）。
            session_key: jscode2session 返回的 session_key（可空，Mock 存 mock-session）。

        Returns:
            新建的账号对象。
        """
        user = User(
            user_id=user_id,
            openid=openid,
            unionid=unionid,
            wechat_session_key=session_key,
            username=None,
            password_hash=None,
            phone=None,
            role="student",
            status="active",
        )
        self.session.add(user)
        self.session.flush()
        return user

    def update_session_key(self, user: User, session_key: str) -> User:
        """更新微信登录态 session_key（每次 wx.login 顶替旧值，与官方语义一致）。

        Args:
            user: 账号对象。
            session_key: 新的 session_key（含 Mock 的 mock-session）。

        Returns:
            更新后的账号对象。
        """
        user.wechat_session_key = session_key
        self.session.flush()
        return user

    def set_phone(self, user: User, phone: str) -> User:
        """更新账号与名下学生档案的手机号（双写保持一致）。

        Args:
            user: 账号对象。
            phone: 11 位大陆手机号。

        Returns:
            更新后的账号对象。
        """
        user.phone = phone
        student = self.find_student_by_user(str(user.user_id))
        if student is not None:
            student.phone = phone
        self.session.flush()
        return user

    def find_student_by_user(self, user_id: str) -> Student | None:
        """查询某账号已绑定的学生档案。

        Args:
            user_id: 用户 ID。

        Returns:
            学生档案；未绑定时返回 None。
        """
        statement = select(Student).where(Student.user_id == user_id).limit(1)
        return self.session.execute(statement).scalar_one_or_none()

    def find_student_by_id(self, student_id: str) -> Student | None:
        """按学号查询学生档案。

        Args:
            student_id: 学号。

        Returns:
            学生档案；不存在时返回 None。
        """
        return self.session.get(Student, student_id)

    def bind_student(self, student: Student, user_id: str) -> Student:
        """将学生档案绑定到账号（唯一约束由数据库保证）。

        Args:
            student: 学生档案。
            user_id: 目标用户 ID。

        Returns:
            更新后的学生档案。
        """
        student.user_id = user_id
        self.session.flush()
        return student

    def touch_last_login(self, user: User, moment: object) -> User:
        """更新最后登录时间。

        Args:
            user: 账号对象。
            moment: 登录时刻（datetime）。

        Returns:
            更新后的账号对象。
        """
        user.last_login_at = moment  # type: ignore[assignment]
        self.session.flush()
        return user

    def list_source_ids(self, user_id: str) -> list[str]:
        """列出该账号名下学生出现过的采集点位。

        关联路径：users.user_id -> students.user_id（唯一外键）
        -> identity_resolutions.subject_id = students.student_id
        -> events.event_id = identity_resolutions.event_id
        -> events.pass_id = passes.pass_id -> passes.source_id。

        注意 `passes` 表没有 `event_id` 列，必须经 `events` 中转；
        `sources.source_id` 是字符串（如 `gate-east`），故返回 `list[str]`。

        Args:
            user_id: 用户 ID。

        Returns:
            去重排序后的点位 ID 列表。
        """
        from app.models.entities import Event, Pass
        from app.models.identity import IdentityResolution

        statement = (
            select(Pass.source_id)
            .join(Event, Event.pass_id == Pass.pass_id)
            .join(IdentityResolution, IdentityResolution.event_id == Event.event_id)
            .join(Student, Student.student_id == IdentityResolution.subject_id)
            .where(Student.user_id == user_id)
            .distinct()
            .order_by(Pass.source_id)
        )
        rows = self.session.execute(statement).all()
        return [str(row[0]) for row in rows]

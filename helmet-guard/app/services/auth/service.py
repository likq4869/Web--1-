"""认证服务：登录、令牌刷新、当前用户查询与学号绑定。

职责：封装账号校验、令牌签发与用户视图组装。
依赖：app.core.security（JWT + bcrypt）、app.repositories.user、app.repositories.audit。
边界：不做路由解析、不抛 HTTPException；失败一律抛 app.core.errors 中的领域异常。

安全约定：
    1. 用户不存在 / 密码错误 / 账号已禁用 —— 三者返回**同一文案与同一状态码**，
       避免通过响应差异枚举账号是否存在。
    2. 刷新与查询当前用户都要回库确认 `status == 'active'`，
       保证账号被禁用后已签发的令牌立即失效。
    3. 令牌为无状态 JWT，不落库；主动吊销能力后续由独立机制补充。
    4. 审计日志只记动作与结果，**绝不记密码或哈希**，手机号只记脱敏形式。
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.security import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models.identity import Student
from app.repositories.audit import AuditRepository
from app.repositories.user import UserRepository
from app.schemas.auth import (
    BindPhoneBody,
    BindStudentBody,
    CurrentUserOut,
    LoginBody,
    LoginResult,
    ProfileResult,
    RefreshBody,
    RefreshResult,
    StudentProfileBody,
    StudentProfileOut,
    WechatLoginBody,
    WechatSessionCheckOut,
)
from app.services.auth.wechat_client import WechatClient

# 三类登录失败统一文案（防用户枚举）。
_AUTH_FAIL_MESSAGE = "用户名或密码错误"

# 大陆 11 位手机号（与身份导入共用口径）。
_PHONE_PATTERN = re.compile(r"^1\d{10}$")


class AuthService:
    """认证服务（绑定单个会话，事务由方法内部管理）。"""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        """初始化服务。

        Args:
            session: 数据库会话。
            settings: 应用配置；缺省读取单例。
        """
        self.session = session
        self.settings = settings or get_settings()
        self.users = UserRepository(session)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def login(self, body: LoginBody) -> LoginResult:
        """用户名密码登录，签发访问令牌与刷新令牌。

        Args:
            body: 登录请求体。

        Returns:
            登录结果（含双令牌与用户快照）。

        Raises:
            PermissionDeniedError: 凭据无效或账号不可用。
        """
        user = self.users.find_by_username(body.username)
        if user is None or user.status != "active" or not user.password_hash:
            self._log_auth_event("auth.login", body.username, result="denied")
            raise AuthenticationError(_AUTH_FAIL_MESSAGE)
        if not verify_password(body.password, user.password_hash):
            self._log_auth_event("auth.login", body.username, result="denied")
            raise AuthenticationError(_AUTH_FAIL_MESSAGE)

        self.users.touch_last_login(user, datetime.now(UTC))
        self._log_auth_event("auth.login", user.user_id, result="ok")
        self.session.commit()
        return self._issue_tokens(user.user_id, user.role)

    def refresh(self, body: RefreshBody) -> RefreshResult:
        """用刷新令牌换取新的访问令牌（滚动刷新）。

        Args:
            body: 刷新请求体。

        Returns:
            新的双令牌。

        Raises:
            PermissionDeniedError: 令牌无效、类型不符、过期或账号已不可用。
        """
        payload = decode_token(body.refresh_token, REFRESH_TOKEN_TYPE, self.settings)
        user = self.users.get_by_id(payload.subject)
        if user is None or user.status != "active":
            self._log_auth_event("auth.refresh", payload.subject, result="denied")
            raise AuthenticationError("登录状态已失效，请重新登录")
        result = self._issue_tokens(user.user_id, user.role)
        self._log_auth_event("auth.refresh", user.user_id, result="ok")
        self.session.commit()
        return RefreshResult(
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            token_type=result.token_type,
            expires_in=result.expires_in,
        )

    def current_user(self, subject: str) -> CurrentUserOut:
        """按令牌主体组装当前用户视图。

        Args:
            subject: 令牌主体（用户 ID）。

        Returns:
            当前用户信息。

        Raises:
            PermissionDeniedError: 账号不存在或已不可用。
        """
        user = self.users.get_by_id(subject)
        if user is None or user.status != "active":
            raise AuthenticationError("登录状态已失效，请重新登录")
        return self._to_user_out(user)

    def bind_student(self, subject: str, body: BindStudentBody) -> CurrentUserOut:
        """把学号绑定到当前账号。

        Args:
            subject: 令牌主体（用户 ID）。
            body: 绑定请求体。

        Returns:
            绑定后的当前用户信息。

        Raises:
            NotFoundError: 学号不存在。
            ConflictError: 学号已被其他账号绑定。
            PermissionDeniedError: 账号不存在或已不可用。
        """
        user = self.users.get_by_id(subject)
        if user is None or user.status != "active":
            raise AuthenticationError("登录状态已失效，请重新登录")

        student = self.users.find_student_by_id(body.student_id)
        if student is None:
            raise NotFoundError("未找到该学号对应的学生档案")

        owner = self.users.find_student_by_user(subject)
        if owner is not None and owner.student_id != student.student_id:
            # 一个账号只能绑定一个学号：换绑需先解绑，避免静默覆盖。
            raise ConflictError("当前账号已绑定其他学号，请先解除绑定")

        if student.user_id is not None and student.user_id != subject:
            raise ConflictError("该学号已绑定其他账号")

        self.users.bind_student(student, subject)
        self._log_auth_event(
            "auth.bind_student",
            subject,
            result="ok",
            detail=f"student_id={student.student_id}",
        )
        self.session.commit()
        return self._to_user_out(user)

    # ------------------------------------------------------------------
    # 微信快捷登录（P4-1 扩展）
    # ------------------------------------------------------------------

    def wechat_login(self, body: WechatLoginBody) -> LoginResult:
        """微信快捷登录：code 换 openid，幂等建号并签发令牌。

        Mock 模式（未配置 AppID/Secret）按 code 确定性派生 openid，
        不出网，专供开发联调与自动化测试。

        Args:
            body: 微信登录请求体（含 wx.login code）。

        Returns:
            登录结果（含双令牌与用户快照）。
        """
        session = WechatClient(self.settings).exchange_code(body.code)
        user = self.users.find_by_openid(session.openid)
        if user is None:
            user = self.users.create_wechat_user(
                f"u_wx_{uuid.uuid4().hex[:12]}",
                session.openid,
                session.unionid,
                session.session_key or None,
            )
            self._log_auth_event(
                "auth.wechat_login", str(user.user_id), result="ok", detail="created=1"
            )
        elif user.status != "active":
            self._log_auth_event(
                "auth.wechat_login", str(user.user_id), result="denied", detail="disabled"
            )
            raise AuthenticationError("登录状态已失效，请重新登录")
        else:
            # 每次 wx.login 都会顶替旧 session_key（官方语义）：直接覆盖落库。
            if session.session_key:
                self.users.update_session_key(user, session.session_key)
            self._log_auth_event(
                "auth.wechat_login", str(user.user_id), result="ok", detail="created=0"
            )
        self.users.touch_last_login(user, datetime.now(UTC))
        self.session.commit()
        return self._issue_tokens(str(user.user_id), str(user.role))

    def bind_phone(self, subject: str, body: BindPhoneBody) -> CurrentUserOut:
        """绑定手机号：微信 getPhoneNumber 优先，Mock 允许直传。

        Args:
            subject: 令牌主体（用户 ID）。
            body: 手机号凭证。

        Returns:
            更新后的当前用户信息。

        Raises:
            AuthenticationError: 账号不存在或已不可用。
            ValidationError: 手机号格式非法。
        """
        user = self.users.get_by_id(subject)
        if user is None or user.status != "active":
            raise AuthenticationError("登录状态已失效，请重新登录")
        raw = WechatClient(self.settings).resolve_phone(body.phone_code, body.phone)
        if not _PHONE_PATTERN.match(raw):
            raise ValidationError("手机号格式不正确，应为 11 位大陆号码")
        self.users.set_phone(user, raw)
        self._log_auth_event(
            "auth.bind_phone", subject, result="ok", detail=f"phone=***{raw[-4:]}"
        )
        self.session.commit()
        return self._to_user_out(user)

    def check_wechat_session(self, subject: str) -> WechatSessionCheckOut:
        """校验当前账号服务端 session_key 是否仍有效（官方 checkSessionKey 口径）。

        Args:
            subject: 令牌主体（用户 ID）。

        Returns:
            自检结果；Mock 模式固定有效（不出网）。无 openid/session_key 时
            wechat_valid 为 False，前端应引导重新 wx.login。

        Raises:
            AuthenticationError: 账号不存在或已不可用。
        """
        user = self.users.get_by_id(subject)
        if user is None or user.status != "active":
            raise AuthenticationError("登录状态已失效，请重新登录")
        client = WechatClient(self.settings)
        if client.is_mock:
            return WechatSessionCheckOut(wechat_valid=True, mock=True)
        openid = str(user.openid or "")
        session_key = str(user.wechat_session_key or "")
        if not openid or not session_key:
            return WechatSessionCheckOut(wechat_valid=False, mock=False)
        valid = client.check_session_key(openid, session_key)
        return WechatSessionCheckOut(wechat_valid=valid, mock=False)

    def my_profile(self, subject: str) -> StudentProfileOut:
        """查询本人学籍档案（绑定进度判定用）。

        Args:
            subject: 令牌主体（用户 ID）。

        Returns:
            学籍档案视图；未绑定时返回空视图（has_* 均为 False）。
        """
        user = self.users.get_by_id(subject)
        if user is None or user.status != "active":
            raise AuthenticationError("登录状态已失效，请重新登录")
        student = self.users.find_student_by_user(subject)
        phone = str(user.phone or "") or (str(student.phone) if student and student.phone else "")
        if student is None:
            return StudentProfileOut(phone=phone or None, has_phone=bool(phone))
        return StudentProfileOut(
            student_id=student.student_id,
            name=student.name,
            school=student.school,
            college=student.college,
            grade=student.grade,
            major=student.major,
            class_name=student.class_name,
            phone=phone or None,
            avatar=student.avatar,
            has_phone=bool(phone),
            has_profile=bool(student.school and student.name and student.student_id),
        )

    def upsert_profile(self, subject: str, body: StudentProfileBody) -> ProfileResult:
        """学籍补全（自助新建/更新，upsert 语义）。

        策略（用户已选 upsert）：花名册存在则校验归属后更新，
        不存在则新建；一个账号只能绑定一个学号。

        Args:
            subject: 令牌主体（用户 ID）。
            body: 学籍表单。

        Returns:
            用户快照 + 学生档案。

        Raises:
            AuthenticationError: 账号不存在或已不可用。
            ConflictError: 学号被他人占用 / 账号已绑其他学号。
        """
        user = self.users.get_by_id(subject)
        if user is None or user.status != "active":
            raise AuthenticationError("登录状态已失效，请重新登录")
        owner = self.users.find_student_by_user(subject)
        if owner is not None and owner.student_id != body.student_id:
            raise ConflictError("当前账号已绑定其他学号，请先解除绑定")
        existing = self.users.find_student_by_id(body.student_id)
        if existing is not None:
            if existing.user_id is not None and existing.user_id != subject:
                raise ConflictError("该学号已绑定其他账号")
            existing.name = body.name.strip()
            existing.school = body.school.strip()
            existing.college = body.college.strip()
            existing.grade = body.grade.strip()
            existing.major = body.major.strip()
            existing.class_name = body.class_name.strip()
            existing.user_id = subject
            if user.phone and not existing.phone:
                existing.phone = user.phone
            if body.avatar and body.avatar.strip():
                existing.avatar = body.avatar.strip()[:512]
            self.session.flush()
            student = existing
        else:
            student = Student(
                student_id=body.student_id.strip(),
                user_id=subject,
                name=body.name.strip(),
                school=body.school.strip(),
                college=body.college.strip(),
                grade=body.grade.strip(),
                major=body.major.strip(),
                class_name=body.class_name.strip(),
                phone=user.phone,
                avatar=(body.avatar.strip()[:512] if body.avatar and body.avatar.strip() else None),
                status="active",
            )
            self.session.add(student)
            self.session.flush()
        self._log_auth_event(
            "auth.upsert_profile", subject, result="ok",
            detail=f"student_id={student.student_id}",
        )
        self.session.commit()
        return ProfileResult(user=self._to_user_out(user), student=self.my_profile(subject))

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def record_logout(self, subject: str) -> None:
        """记录登出审计。

        令牌为无状态 JWT，服务端不维护吊销名单；此方法只留审计埋点。

        Args:
            subject: 用户 ID。
        """
        self._log_auth_event("auth.logout", subject, result="ok")
        self.session.commit()

    def _issue_tokens(self, subject: str, role: str) -> LoginResult:
        """签发双令牌并组装登录结果。

        Args:
            subject: 用户 ID。
            role: 角色标识。

        Returns:
            登录结果。
        """
        access = create_access_token(subject, role, self.settings)
        refresh = create_refresh_token(subject, role, self.settings)
        return LoginResult(
            access_token=access,
            refresh_token=refresh,
            token_type="Bearer",
            expires_in=self.settings.access_token_expire_minutes * 60,
            user=self._to_user_out(self.users.get_by_id(subject)),
        )

    def _to_user_out(self, user: object) -> CurrentUserOut:
        """把账号对象转换为前端契约视图。

        `display_name` 由 `username` 派生（`users` 表无独立展示名列）；
        `source_ids` 取该账号名下学生出现过的采集点位。

        Args:
            user: 账号对象（`User`）。

        Returns:
            当前用户视图。
        """
        username = str(getattr(user, "username", "") or "")
        user_id = str(getattr(user, "user_id", ""))
        return CurrentUserOut(
            id=user_id,
            username=username,
            display_name=username,
            role=str(getattr(user, "role", "") or ""),
            source_ids=self.users.list_source_ids(user_id),
        )

    def _log_auth_event(
        self,
        action: str,
        actor: str,
        *,
        result: str,
        detail: str | None = None,
    ) -> None:
        """写认证审计日志（只记动作与结果，绝不记密码或哈希）。

        Args:
            action: 动作标识。
            actor: 操作人标识（用户名或用户 ID）。
            result: 结果（ok / denied）。
            detail: 补充说明（可空）。
        """
        AuditRepository(self.session).log(
            actor=actor,
            role="system",
            action=action,
            object_type="auth",
            object_id=actor,
            result=result,
            detail=detail,
        )

"""认证 API：登录、刷新、登出、当前用户、学号绑定与微信快捷登录。

职责：HTTP 解析、响应包络与服务调用。
依赖：FastAPI、app.core.deps、app.schemas.auth、app.services.auth。
边界：不做业务规则判定；凭据校验与归属判定全部在服务层。

响应统一包络 `{code, data, message}`，与前端 Axios 拦截器对齐。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.deps import CurrentUserDep, DbSession
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
from app.services.auth import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _envelope(data: Any) -> dict[str, Any]:
    """构造统一响应包络（与前端 Axios 拦截器对齐）。"""
    return {"code": 0, "data": data, "message": ""}


@router.post("/login")
def login(body: LoginBody, session: DbSession) -> dict[str, Any]:
    """用户名密码登录，返回访问令牌与刷新令牌。"""
    result: LoginResult = AuthService(session).login(body)
    return _envelope(result.model_dump(mode="json"))


@router.post("/refresh")
def refresh(body: RefreshBody, session: DbSession) -> dict[str, Any]:
    """用刷新令牌换取新的访问令牌。"""
    result: RefreshResult = AuthService(session).refresh(body)
    return _envelope(result.model_dump(mode="json"))


@router.post("/logout")
def logout(session: DbSession, user: CurrentUserDep) -> dict[str, Any]:
    """登出。

    令牌为无状态 JWT，服务端不维护吊销名单；此接口仅留作审计埋点与
    前端「显式登出」语义的落点，客户端负责丢弃本地令牌。
    """
    AuthService(session).record_logout(user.subject)
    return _envelope({"logged_out": True})


@router.get("/me")
def me(session: DbSession, user: CurrentUserDep) -> dict[str, Any]:
    """查询当前登录用户。"""
    current: CurrentUserOut = AuthService(session).current_user(user.subject)
    return _envelope(current.model_dump(mode="json"))


@router.post("/bind-student")
def bind_student(
    body: BindStudentBody,
    session: DbSession,
    user: CurrentUserDep,
) -> dict[str, Any]:
    """绑定学号（小程序首次登录使用）。"""
    current: CurrentUserOut = AuthService(session).bind_student(user.subject, body)
    return _envelope(current.model_dump(mode="json"))


@router.post("/wechat-login")
def wechat_login(body: WechatLoginBody, session: DbSession) -> dict[str, Any]:
    """微信快捷登录：小程序 wx.login 拿到的 code 换 openid 后签发本系统令牌。"""
    result: LoginResult = AuthService(session).wechat_login(body)
    return _envelope(result.model_dump(mode="json"))


@router.get("/check-session")
def check_session(session: DbSession, user: CurrentUserDep) -> dict[str, Any]:
    """校验服务端微信登录态是否仍有效（官方 checkSessionKey 口径）。

    Mock 模式固定返回有效；生产按落库 session_key 做 hmac 校验，
    失效时前端应重新 wx.login 再调 wechat-login 顶替旧值。
    """
    result: WechatSessionCheckOut = AuthService(session).check_wechat_session(user.subject)
    return _envelope(result.model_dump(mode="json"))


@router.post("/bind-phone")
def bind_phone(
    body: BindPhoneBody,
    session: DbSession,
    user: CurrentUserDep,
) -> dict[str, Any]:
    """快捷绑定手机号：微信 getPhoneNumber 的 phone_code 优先，直传仅限 Mock。"""
    current: CurrentUserOut = AuthService(session).bind_phone(user.subject, body)
    return _envelope(current.model_dump(mode="json"))


@router.get("/profile")
def get_profile(session: DbSession, user: CurrentUserDep) -> dict[str, Any]:
    """查询本人学籍档案（驱动小程序四步引导的进度判定）。"""
    profile: StudentProfileOut = AuthService(session).my_profile(user.subject)
    return _envelope(profile.model_dump(mode="json"))


@router.post("/profile")
def upsert_profile(
    body: StudentProfileBody,
    session: DbSession,
    user: CurrentUserDep,
) -> dict[str, Any]:
    """自助补全学籍档案（学校/学院/年级/专业/班级/学号/姓名）。"""
    result: ProfileResult = AuthService(session).upsert_profile(user.subject, body)
    return _envelope(result.model_dump(mode="json"))

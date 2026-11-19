"""认证出入参：登录、刷新、绑定学号与当前用户契约。

职责：定义 P3-0 认证接口的请求体与响应体。
依赖：pydantic。
边界：只做结构与取值范围校验；不查询数据、不签发令牌。

前端契约对齐：admin-web/src/api/types.ts 的
`LoginResult` / `CurrentUser` 字段名必须与此处逐字一致，
否则 Axios 解包后前端拿到 undefined。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoginBody(BaseModel):
    """登录请求体。"""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64, description="用户名")
    password: str = Field(min_length=1, max_length=128, description="登录密码")


class RefreshBody(BaseModel):
    """刷新令牌请求体。"""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1, max_length=2048, description="刷新令牌")


class BindStudentBody(BaseModel):
    """绑定学号请求体（小程序首次登录用）。"""

    model_config = ConfigDict(extra="forbid")

    student_id: str = Field(
        min_length=8,
        max_length=12,
        pattern=r"^\d+$",
        description="学号（8-12 位数字）",
    )


class WechatLoginBody(BaseModel):
    """微信快捷登录请求体（小程序 wx.login code）。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=128, description="wx.login 返回的一次性 code")


class WechatSessionCheckOut(BaseModel):
    """微信登录态自检结果（官方 checkSessionKey 口径）。"""

    model_config = ConfigDict(extra="forbid")

    wechat_valid: bool = Field(description="服务端 session_key 是否仍有效")
    mock: bool = Field(description="是否为 Mock 模式（未配置 AppID/Secret）")


class BindPhoneBody(BaseModel):
    """绑定手机号请求体（微信 getPhoneNumber 优先，Mock 允许直传）。"""

    model_config = ConfigDict(extra="forbid")

    phone_code: str | None = Field(
        default=None, max_length=128, description="getPhoneNumber 回调 code"
    )
    phone: str | None = Field(
        default=None, max_length=16, description="直传手机号（仅 Mock 联调用）"
    )


class StudentProfileBody(BaseModel):
    """学籍档案补全请求体（自助新建/更新，upsert 语义）。

    组织级联（学院/年级/专业/班级）允许为空：种子数据只覆盖部分分支，
    为避免死胡同卡死提交，仅要求学校/学号/姓名必填，其余缺省存空串。
    """

    model_config = ConfigDict(extra="forbid")

    school: str = Field(min_length=1, max_length=64, description="学校")
    college: str = Field(default="", max_length=64, description="二级学院（可空）")
    grade: str = Field(default="", max_length=16, description="年级（可空，如 2024 级）")
    major: str = Field(default="", max_length=64, description="专业（可空）")
    class_name: str = Field(default="", max_length=64, description="班级（可空）")
    student_id: str = Field(
        min_length=8, max_length=12, pattern=r"^\d+$", description="学号（8-12 位数字）"
    )
    name: str = Field(min_length=1, max_length=32, description="姓名")
    avatar: str | None = Field(
        default=None,
        max_length=512,
        description="头像地址（chooseAvatar 临时路径或远端 URL，仅展示用）",
    )


class StudentProfileOut(BaseModel):
    """本人学籍档案视图（绑定进度判定用）。"""

    model_config = ConfigDict(extra="forbid")

    student_id: str | None = None
    name: str | None = None
    school: str | None = None
    college: str | None = None
    grade: str | None = None
    major: str | None = None
    class_name: str | None = None
    phone: str | None = None
    avatar: str | None = None
    has_phone: bool = False
    has_profile: bool = False


class CurrentUserOut(BaseModel):
    """当前登录用户信息。

    与前端 `CurrentUser` 接口一一对应：
    - `id` 为字符串（`users.user_id` 主键即字符串，前端类型已同步修正）；
    - `display_name` 由 `username` 派生（`users` 表无独立展示名列）；
    - `source_ids` 为该用户名下学生出现过的采集点位（`sources.source_id` 是字符串）。
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="用户 ID")
    username: str = Field(description="用户名")
    display_name: str = Field(description="展示名")
    role: str = Field(description="角色标识")
    source_ids: list[str] = Field(default_factory=list, description="关联采集点位")


class ProfileResult(BaseModel):
    """学籍绑定结果：用户快照 + 学生档案。"""

    model_config = ConfigDict(extra="forbid")

    user: CurrentUserOut
    student: StudentProfileOut


class LoginResult(BaseModel):
    """登录响应体（含双令牌与用户快照）。"""

    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(description="访问令牌")
    refresh_token: str = Field(description="刷新令牌")
    token_type: str = Field(default="Bearer", description="令牌类型")
    expires_in: int = Field(description="访问令牌有效期（秒）")
    user: CurrentUserOut = Field(description="当前用户")


class RefreshResult(BaseModel):
    """刷新令牌响应体。"""

    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(description="新访问令牌")
    refresh_token: str = Field(description="新刷新令牌")
    token_type: str = Field(default="Bearer", description="令牌类型")
    expires_in: int = Field(description="访问令牌有效期（秒）")

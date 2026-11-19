"""领域异常层级：把业务失败表达为可分类、可追踪的异常。

职责：定义统一的领域异常及其 HTTP 语义映射。
依赖：标准库。
边界：只描述失败语义；不执行 I/O、不记录日志、不决定响应序列化格式。
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """领域异常基类。

    所有业务异常都继承本类，API 层据此统一转换为错误响应。
    `code` 为机器可读标识，`message` 为面向用户的可读说明。
    """

    code: str = "APP_ERROR"
    status_code: int = 500
    default_message: str = "服务暂时不可用，请稍后重试"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details: dict[str, Any] = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化的错误载荷（不含堆栈）。"""
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class NotFoundError(AppError):
    """目标资源不存在。"""

    code = "NOT_FOUND"
    status_code = 404
    default_message = "请求的资源不存在"


class ValidationError(AppError):
    """输入或状态不满足业务约束。"""

    code = "VALIDATION_ERROR"
    status_code = 422
    default_message = "提交的数据不符合要求，请检查后重试"


class ConflictError(AppError):
    """与当前资源状态冲突。"""

    code = "CONFLICT"
    status_code = 409
    default_message = "当前状态已发生变化，请刷新后重试"


class PermissionDeniedError(AppError):
    """调用方无权执行该操作。"""

    code = "PERMISSION_DENIED"
    status_code = 403
    default_message = "你没有执行该操作的权限"


class AuthenticationError(AppError):
    """身份未通过验证（凭据无效、令牌缺失/过期/类型不符）。

    与 `PermissionDeniedError`（403）严格区分：
      - 401 = 「你是谁」没验证通过 → 客户端应尝试刷新令牌或重新登录；
      - 403 = 「你是谁」已确认，但「你不能做这件事」→ 重试无意义。

    认证失败必须走 401，否则前端拦截器不会触发刷新令牌与重登录流程
    （admin-web/src/api/request.ts 依据 401 分支处理）。
    """

    code = "UNAUTHORIZED"
    status_code = 401
    default_message = "登录状态无效，请重新登录"


class RateLimitError(AppError):
    """请求频率或并发超过限制。"""

    code = "RATE_LIMIT_EXCEEDED"
    status_code = 429
    default_message = "请求过于频繁，请稍后重试"


class ExternalServiceError(AppError):
    """外部服务调用失败。"""

    code = "EXTERNAL_SERVICE_ERROR"
    status_code = 502
    default_message = "外部服务暂时不可用，请稍后重试"


class ModelNotReadyError(AppError):
    """模型未就绪，无法执行推理类操作。"""

    code = "MODEL_NOT_READY"
    status_code = 503
    default_message = "模型尚未就绪，请稍后重试"


ERROR_STATUS_MAP: dict[type[AppError], int] = {
    NotFoundError: NotFoundError.status_code,
    ValidationError: ValidationError.status_code,
    ConflictError: ConflictError.status_code,
    PermissionDeniedError: PermissionDeniedError.status_code,
    AuthenticationError: AuthenticationError.status_code,
    RateLimitError: RateLimitError.status_code,
    ExternalServiceError: ExternalServiceError.status_code,
    ModelNotReadyError: ModelNotReadyError.status_code,
}


def status_code_for(error: AppError) -> int:
    """返回领域异常对应的 HTTP 状态码。

    Args:
        error: 领域异常实例。

    Returns:
        HTTP 状态码；未知子类回退为 500。
    """
    return ERROR_STATUS_MAP.get(type(error), error.status_code)

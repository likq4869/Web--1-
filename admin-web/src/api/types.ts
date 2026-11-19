// ===========================================================================
// API 基础类型定义
// 业务接口类型从后端 OpenAPI 自动生成（scripts/gen-api-types.ts），
// 禁止手写与后端重复的实体类型。
// ===========================================================================

/** 后端统一响应包络 */
export interface ApiResponse<T> {
  code: number
  data: T
  message: string
}

/** 分页结果 */
export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

/** 分页查询参数 */
export interface PageQuery {
  page?: number
  page_size?: number
}

/** 业务错误码 */
export enum ApiErrorCode {
  /** 成功 */
  SUCCESS = 0,
  /** 参数校验失败 */
  VALIDATION_ERROR = 422,
  /** 未认证 */
  UNAUTHORIZED = 401,
  /** 无权限 */
  FORBIDDEN = 403,
  /** 资源不存在 */
  NOT_FOUND = 404,
  /** 冲突 */
  CONFLICT = 409,
  /** 限流 */
  RATE_LIMITED = 429,
  /** 服务端错误 */
  INTERNAL_ERROR = 500,
  /** 外部服务异常 */
  EXTERNAL_SERVICE_ERROR = 502,
  /** 模型未就绪 */
  MODEL_NOT_READY = 503,
}

/** 统一业务异常 —— 由拦截器抛出，页面只需 catch ApiError */
export class ApiError extends Error {
  /** HTTP 状态码 */
  readonly status: number
  /** 业务错误码 */
  readonly code: number
  /** 服务端返回的可读消息 */
  readonly serverMessage: string
  /** 链路追踪 ID —— 排查问题时报给后端 */
  readonly traceId?: string
  /** 字段级错误详情（422 场景） */
  readonly details?: ApiErrorDetail[]

  constructor(params: {
    status: number
    code: number
    message: string
    traceId?: string
    details?: ApiErrorDetail[]
  }) {
    super(params.message)
    this.name = 'ApiError'
    this.status = params.status
    this.code = params.code
    this.serverMessage = params.message
    this.traceId = params.traceId
    this.details = params.details
  }
}

/** 字段级错误详情 */
export interface ApiErrorDetail {
  loc: (string | number)[]
  msg: string
  type: string
}

/** 后端标准错误响应体 */
export interface ErrorResponse {
  code: number
  message: string
  data: null
  errors?: ApiErrorDetail[]
  trace_id?: string
}

/** 用户角色 —— 与后端权限体系对应 */
export type UserRole =
  | 'super_admin'
  | 'admin'
  | 'reviewer'
  | 'observer'
  | 'league_officer'
  | 'counselor'
  | 'security_officer'
  | 'auditor'
  | 'student'

/** 登录用户信息 */
export interface CurrentUser {
  id: string
  username: string
  display_name: string
  role: UserRole
  source_ids: string[]
}

/** 登录请求体 */
export interface LoginPayload {
  username: string
  password: string
}

/** 登录响应体 */
export interface LoginResult {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: CurrentUser
}

/** 刷新令牌响应体 */
export interface RefreshResult {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

/** 点位（监控点） */
export interface MonitoringPoint {
  id: number
  name: string
  location: string
  status: 'online' | 'offline' | 'maintenance'
}

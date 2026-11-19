// ===========================================================================
// 统一请求层
//
// 请求拦截器：
//   1. 注入 Authorization: Bearer <access_token>
//   2. 注入 X-Request-ID 便于后端链路追踪
//
// 响应拦截器：
//   1. 解包 { code, data, message } —— 统一取 data
//   2. 401 → 刷新令牌 → 重放原请求（并发 401 只触发一次刷新）
//   3. 403/404/409/422/429/5xx → 映射为 ApiError，携带 trace_id
//   4. 记录 trace_id 便于后端排障
// ===========================================================================

import axios, {
  type AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'
import { ElMessage } from 'element-plus'
import { ApiError, ApiErrorCode, type ApiResponse, type ErrorResponse } from './types'

/** 业务鉴权接口路径（仅此路径参与刷新重放逻辑） */
const REFRESH_PATH = '/api/v1/auth/refresh'

/** 令牌在内存中的缓存 —— auth store 会同步写入 */
let accessToken: string | null = null
let refreshToken: string | null = null

/** 正在进行的刷新 Promise —— 避免并发 401 触发多次刷新 */
let refreshingPromise: Promise<string> | null = null

/** 请求配置扩展：支持跳过鉴权与静默错误 */
export interface RequestOptions extends AxiosRequestConfig {
  /** 跳过自动刷新重放（登录/刷新接口自身使用） */
  skipAuthRefresh?: boolean
  /** 不弹全局错误提示（页面自行处理错误态时使用） */
  silent?: boolean
}

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function getAccessToken(): string | null {
  return accessToken
}

export function setRefreshToken(token: string | null): void {
  refreshToken = token
}

/** 读取存储中的 refresh token —— 刷新流程需要 */
export function getRefreshToken(): string | null {
  return refreshToken
}

const http: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api',
  timeout: 20_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ---------------------------------------------------------------------------
// 请求拦截器
// ---------------------------------------------------------------------------
http.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const options = config as InternalAxiosRequestConfig & RequestOptions

    if (!options.skipAuthRefresh && accessToken) {
      config.headers.set('Authorization', `Bearer ${accessToken}`)
    }

    // 请求 ID 便于前后端对账
    if (!config.headers.has('X-Request-ID')) {
      config.headers.set('X-Request-ID', crypto.randomUUID())
    }

    return config
  },
  (error: AxiosError) => Promise.reject(error),
)

// ---------------------------------------------------------------------------
// 响应拦截器
// ---------------------------------------------------------------------------
http.interceptors.response.use(
  (response: AxiosResponse) => {
    const options = response.config as InternalAxiosRequestConfig & RequestOptions

    // 二进制响应（导出/下载）不参与包络解包
    if (response.config.responseType === 'blob' || response.config.responseType === 'arraybuffer') {
      return response
    }

    const payload = response.data as ApiResponse<unknown> | undefined

    // 后端可能返回裸对象（未包络）；此时原样返回
    if (!payload || typeof payload !== 'object' || !('code' in payload)) {
      return response
    }

    // 业务错误码：HTTP 200 但 code != 0
    if (payload.code !== ApiErrorCode.SUCCESS) {
      const error = new ApiError({
        status: response.status,
        code: payload.code,
        message: payload.message || '请求失败',
        traceId: readTraceId(response),
      })
      if (!options.silent) {
        ElMessage.error(error.message)
      }
      return Promise.reject(error)
    }

    // 解包 data
    response.data = payload.data
    return response
  },
  async (error: AxiosError<ErrorResponse>) => {
    const options = (error.config ?? {}) as InternalAxiosRequestConfig & RequestOptions
    const status = error.response?.status ?? 0

    // ---- 401：尝试刷新令牌并重放 ----
    if (status === ApiErrorCode.UNAUTHORIZED && !options.skipAuthRefresh) {
      try {
        const newToken = await ensureRefreshed()
        options.headers = options.headers ?? ({} as never)
        options.headers.set('Authorization', `Bearer ${newToken}`)
        return await http.request(options)
      } catch {
        // 刷新失败 —— 清理登录态并跳转登录页
        clearAuthState()
        redirectToLogin()
        const apiError = new ApiError({
          status: ApiErrorCode.UNAUTHORIZED,
          code: ApiErrorCode.UNAUTHORIZED,
          message: '登录已过期，请重新登录',
        })
        if (!options.silent) {
          ElMessage.error(apiError.message)
        }
        return Promise.reject(apiError)
      }
    }

    const apiError = toApiError(error)
    if (!options.silent) {
      ElMessage.error(apiError.message)
    }
    return Promise.reject(apiError)
  },
)

// ---------------------------------------------------------------------------
// 辅助
// ---------------------------------------------------------------------------

function readTraceId(response: AxiosResponse): string | undefined {
  return (response.headers?.['x-trace-id'] as string | undefined) ?? undefined
}

function clearAuthState(): void {
  accessToken = null
  refreshToken = null
  localStorage.removeItem('hg.auth.tokens')
  localStorage.removeItem('hg.auth.user')
}

function redirectToLogin(): void {
  const current = window.location.pathname + window.location.search
  if (current.startsWith('/login')) return
  const redirect = encodeURIComponent(current)
  window.location.assign(`/login?redirect=${redirect}`)
}

/**
 * 确保令牌已刷新。
 * 并发调用共享同一个 Promise，避免刷新风暴。
 */
function ensureRefreshed(): Promise<string> {
  if (refreshingPromise) return refreshingPromise

  const token = getRefreshToken()
  if (!token) {
    return Promise.reject(new Error('无刷新令牌'))
  }

  refreshingPromise = axios
    .post<ApiResponse<{ access_token: string; refresh_token: string }>>(
      `${http.defaults.baseURL}${REFRESH_PATH}`,
      { refresh_token: token },
      { headers: { 'Content-Type': 'application/json' } },
    )
    .then((res) => {
      const body = res.data
      const data = body?.data ?? (body as unknown as { access_token: string })
      setAccessToken(data.access_token)
      setRefreshToken(data.refresh_token)
      persistTokens(data.access_token, data.refresh_token)
      return data.access_token
    })
    .finally(() => {
      refreshingPromise = null
    })

  return refreshingPromise
}

function persistTokens(access: string, refresh: string): void {
  localStorage.setItem(
    'hg.auth.tokens',
    JSON.stringify({ access_token: access, refresh_token: refresh }),
  )
}

/** 将 Axios 错误映射为统一业务错误 */
function toApiError(error: AxiosError<ErrorResponse>): ApiError {
  const status = error.response?.status ?? 0
  const body = error.response?.data
  const traceId = (error.response?.headers?.['x-trace-id'] as string | undefined) ?? body?.trace_id

  const defaultMessage = statusMessage(status)

  return new ApiError({
    status,
    code: body?.code ?? status,
    message: body?.message || error.message || defaultMessage,
    traceId,
    details: body?.errors,
  })
}

function statusMessage(status: number): string {
  switch (status) {
    case 0:
      return '网络异常，请检查连接后重试'
    case ApiErrorCode.UNAUTHORIZED:
      return '未登录或登录已过期'
    case ApiErrorCode.FORBIDDEN:
      return '没有访问权限'
    case ApiErrorCode.NOT_FOUND:
      return '资源不存在'
    case ApiErrorCode.CONFLICT:
      return '操作与当前状态冲突'
    case ApiErrorCode.VALIDATION_ERROR:
      return '提交的数据校验未通过'
    case ApiErrorCode.RATE_LIMITED:
      return '操作过于频繁，请稍后再试'
    case ApiErrorCode.INTERNAL_ERROR:
      return '服务器内部错误'
    case ApiErrorCode.EXTERNAL_SERVICE_ERROR:
      return '外部服务暂时不可用'
    case ApiErrorCode.MODEL_NOT_READY:
      return '模型尚未就绪'
    default:
      return '请求失败'
  }
}

// ---------------------------------------------------------------------------
// 对外 API
// ---------------------------------------------------------------------------

/** GET 请求 */
export async function get<T>(url: string, params?: unknown, options?: RequestOptions): Promise<T> {
  const res = await http.get<T>(url, { params, ...options })
  return res.data
}

/** POST 请求 */
export async function post<T>(url: string, data?: unknown, options?: RequestOptions): Promise<T> {
  const res = await http.post<T>(url, data, options)
  return res.data
}

/** PUT 请求 */
export async function put<T>(url: string, data?: unknown, options?: RequestOptions): Promise<T> {
  const res = await http.put<T>(url, data, options)
  return res.data
}

/** DELETE 请求 */
export async function del<T>(url: string, options?: RequestOptions): Promise<T> {
  const res = await http.delete<T>(url, options)
  return res.data
}

export default http

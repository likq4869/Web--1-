// ===========================================================================
// 认证相关 API —— 所有 URL 常量集中在此，组件中禁止硬编码路径
// ===========================================================================

import { get, post } from './request'
import type { CurrentUser, LoginPayload, LoginResult, RefreshResult } from './types'

const AUTH_BASE = '/v1/auth'

/** 登录 */
export function login(payload: LoginPayload): Promise<LoginResult> {
  return post<LoginResult>(`${AUTH_BASE}/login`, payload, { skipAuthRefresh: true })
}

/** 刷新令牌 */
export function refresh(refreshToken: string): Promise<RefreshResult> {
  return post<RefreshResult>(
    `${AUTH_BASE}/refresh`,
    { refresh_token: refreshToken },
    { skipAuthRefresh: true },
  )
}

/** 登出 */
export function logout(): Promise<void> {
  return post<void>(`${AUTH_BASE}/logout`, undefined, { silent: true })
}

/** 获取当前登录用户 */
export function fetchCurrentUser(): Promise<CurrentUser> {
  return get<CurrentUser>(`${AUTH_BASE}/me`)
}

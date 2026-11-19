// ===========================================================================
// 认证状态 —— token、用户信息、角色、登录/登出/刷新
// Token 同时缓存在 request.ts 的模块级变量中，供 Axios 拦截器同步读取。
// ===========================================================================

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as authApi from '@/api/auth'
import { setAccessToken, setRefreshToken, getAccessToken } from '@/api/request'
import type { CurrentUser, LoginPayload, UserRole } from '@/api/types'

const TOKENS_KEY = 'hg.auth.tokens'
const USER_KEY = 'hg.auth.user'

/** 角色权限矩阵 —— 与后端权限体系对齐 */
export const ROLE_PERMISSIONS: Record<UserRole, readonly string[]> = {
  super_admin: ['*'],
  league_officer: [
    'dashboard:read',
    'events:read',
    'decisions:review',
    'students:read',
    'identities:manage',
  ],
  counselor: ['dashboard:read', 'events:read', 'students:read'],
  security_officer: ['dashboard:read', 'events:read', 'students:read'],
  auditor: ['dashboard:read', 'events:read', 'students:read'],
  admin: ['dashboard:read', 'events:read', 'decisions:review', 'students:read', 'points:read'],
  reviewer: ['dashboard:read', 'events:read', 'decisions:review'],
  observer: ['dashboard:read', 'events:read'],
  student: [],
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<CurrentUser | null>(readUser())
  const loading = ref(false)

  /** 是否已登录 */
  const isAuthenticated = computed(() => user.value !== null && getAccessToken() !== null)

  /** 当前角色 */
  const role = computed<UserRole | null>(() => user.value?.role ?? null)

  /**
   * 判断当前用户是否拥有指定权限。
   * super_admin 拥有全部权限；未知角色一律拒绝。
   */
  function hasPermission(permission: string): boolean {
    const currentRole = role.value
    if (!currentRole) return false
    const permissions = ROLE_PERMISSIONS[currentRole]
    if (!permissions) return false
    return permissions.includes('*') || permissions.includes(permission)
  }

  /** 是否拥有指定角色之一 */
  function hasRole(...roles: UserRole[]): boolean {
    const currentRole = role.value
    return currentRole !== null && roles.includes(currentRole)
  }

  /** 登录 */
  async function login(payload: LoginPayload): Promise<void> {
    loading.value = true
    try {
      const result = await authApi.login(payload)
      applyTokens(result.access_token, result.refresh_token)
      user.value = result.user
      persistUser(result.user)
    } finally {
      loading.value = false
    }
  }

  /** 拉取当前用户（刷新页面后恢复会话） */
  async function fetchUser(): Promise<CurrentUser> {
    const current = await authApi.fetchCurrentUser()
    user.value = current
    persistUser(current)
    return current
  }

  /** 登出 —— 无论后端是否成功都清理本地状态 */
  async function logout(): Promise<void> {
    try {
      await authApi.logout()
    } catch {
      // 后端不可用不应阻塞登出
    } finally {
      clearSession()
    }
  }

  function clearSession(): void {
    setAccessToken(null)
    setRefreshToken(null)
    user.value = null
    localStorage.removeItem(TOKENS_KEY)
    localStorage.removeItem(USER_KEY)
  }

  /** 应用启动时恢复会话：从 localStorage 读 token 并校验 */
  async function restoreSession(): Promise<boolean> {
    const tokens = readTokens()
    if (!tokens) return false
    setAccessToken(tokens.access_token)
    setRefreshToken(tokens.refresh_token)
    try {
      await fetchUser()
      return true
    } catch {
      clearSession()
      return false
    }
  }

  return {
    user,
    loading,
    isAuthenticated,
    role,
    hasPermission,
    hasRole,
    login,
    logout,
    fetchUser,
    restoreSession,
    clearSession,
  }
})

function applyTokens(access: string, refresh: string): void {
  setAccessToken(access)
  setRefreshToken(refresh)
  localStorage.setItem(TOKENS_KEY, JSON.stringify({ access_token: access, refresh_token: refresh }))
}

function readTokens(): { access_token: string; refresh_token: string } | null {
  try {
    const raw = localStorage.getItem(TOKENS_KEY)
    if (!raw) return null
    return JSON.parse(raw) as { access_token: string; refresh_token: string }
  } catch {
    return null
  }
}

function readUser(): CurrentUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    if (!raw) return null
    return JSON.parse(raw) as CurrentUser
  } catch {
    return null
  }
}

function persistUser(value: CurrentUser): void {
  localStorage.setItem(USER_KEY, JSON.stringify(value))
}

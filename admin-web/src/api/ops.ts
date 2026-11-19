// ===========================================================================
// 运维管理 API —— 模型版本 / 审计日志 / 用户管理
// URL 常量集中在此，组件中禁止硬编码路径
// ===========================================================================

import { get, post, put } from './request'

const OPS_BASE = '/v1/admin/ops'

/** 模型版本（与后端 ModelVersionResponse 对齐） */
export interface ModelVersion {
  model_id: string
  task: string
  version: string
  weight_path: string
  metrics: Record<string, unknown> | null
  dataset_id: string | null
  is_active: boolean
  deployed_at: string | null
  created_at: string | null
  updated_at: string | null
}

/** 模型任务类型 */
export type ModelTask = 'detect' | 'plate' | 'head_cls' | 'reid' | ''

/** 回流样本统计（只读） */
export interface FeedbackStats {
  total: number
  pending_train: number
  by_source: Record<string, number>
}

/** 审计日志（只读，后端无修改入口） */
export interface AuditLog {
  id: number
  actor: string
  role: string
  action: string
  object_type: string | null
  object_id: string | null
  ip: string | null
  result: string
  detail: string | null
  created_at: string | null
}

/** 管理端用户（绝不含 password_hash） */
export interface AdminUser {
  user_id: string
  username: string | null
  role: string
  status: string
  phone: string | null
  last_login_at: string | null
  created_at: string | null
  updated_at: string | null
}

/** 后端分页包络（运维域：无 pages 字段） */
export interface OpsPage<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/** 审计查询参数 */
export interface AuditQuery {
  page?: number
  page_size?: number
  actor?: string
  action?: string
  start?: string
  end?: string
}

/** 用户查询参数 */
export interface AdminUserQuery {
  page?: number
  page_size?: number
  keyword?: string
  role?: string
  status?: string
}

/** 用户更新请求体 */
export interface AdminUserUpdatePayload {
  role?: string
  status?: 'active' | 'disabled'
}

/** 模型版本列表（激活优先；非法 task 由后端视为不限） */
export function listModels(task?: string): Promise<{ items: ModelVersion[]; total: number }> {
  const params: Record<string, unknown> = {}
  if (task !== undefined && task !== '') params.task = task
  return get<{ items: ModelVersion[]; total: number }>(`${OPS_BASE}/models`, params, {
    silent: true,
  })
}

/** 回流样本统计（只读） */
export function getFeedbackStats(): Promise<FeedbackStats> {
  return get<FeedbackStats>(`${OPS_BASE}/models/feedback-stats`, undefined, { silent: true })
}

/** 激活指定模型版本（同任务互斥；二次确认由调用方承担） */
export function activateModel(modelId: string): Promise<ModelVersion> {
  return post<ModelVersion>(
    `${OPS_BASE}/models/${encodeURIComponent(modelId)}/activate`,
    {},
    {
      silent: true,
    },
  )
}

/** 审计日志列表（只读） */
export function listAuditLogs(query: AuditQuery): Promise<OpsPage<AuditLog>> {
  const params: Record<string, unknown> = { ...query }
  if (params.actor === '') delete params.actor
  if (params.action === '') delete params.action
  if (params.start === '') delete params.start
  if (params.end === '') delete params.end
  return get<OpsPage<AuditLog>>(`${OPS_BASE}/audit-logs`, params, { silent: true })
}

/** 用户列表（仅超管） */
export function listUsers(query: AdminUserQuery): Promise<OpsPage<AdminUser>> {
  const params: Record<string, unknown> = { ...query }
  if (params.keyword === '') delete params.keyword
  if (params.role === '') delete params.role
  if (params.status === '') delete params.status
  return get<OpsPage<AdminUser>>(`${OPS_BASE}/users`, params, { silent: true })
}

/** 更新用户角色/状态 */
export function updateAdminUser(
  userId: string,
  payload: AdminUserUpdatePayload,
): Promise<AdminUser> {
  return put<AdminUser>(`${OPS_BASE}/users/${encodeURIComponent(userId)}`, payload, {
    silent: true,
  })
}

/** 重置用户密码 */
export function resetUserPassword(
  userId: string,
  newPassword: string,
): Promise<{ user_id: string; username: string | null }> {
  return post<{ user_id: string; username: string | null }>(
    `${OPS_BASE}/users/${encodeURIComponent(userId)}/reset-password`,
    { new_password: newPassword },
    { silent: true },
  )
}

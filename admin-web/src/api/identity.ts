// ===========================================================================
// 身份管理 API —— 待识别池 / 车辆档案
// URL 常量集中在此，组件中禁止硬编码路径
// ===========================================================================

import { get, post } from './request'

const ADMIN_BASE = '/v1/admin'

/** 后端分页包络（与后端 identity 路由一致：无 pages 字段） */
export interface IdentityPage<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/** 待识别池状态 */
export type PendingStatus = 'pending' | 'resolved' | 'ignored'

/** 待识别记录 */
export interface PendingIdentity {
  id: number
  vehicle_id: string
  pass_count: number
  first_seen: string | null
  last_seen: string | null
  location: string | null
  snapshot_id: string | null
  status: PendingStatus
  created_at: string
}

/** 待识别列表项（附候选提示，当前后端返回空数组占位） */
export interface PendingListItem {
  pending: PendingIdentity
  candidates: Array<Record<string, string | number>>
}

/** 车辆档案 */
export interface Vehicle {
  vehicle_id: string
  plate_no: string | null
  plate_type: 'blue' | 'school' | 'university' | 'none' | null
  owner_id: string | null
  owner_bind_type: string | null
  confidence: number
  color_hist: number[] | Record<string, unknown> | null
  first_seen: string | null
  last_seen: string | null
  status: string
  created_at: string
  updated_at: string
}

/** 单次通行身份判定 */
export interface IdentityResolution {
  id: number
  event_id: string
  vehicle_id: string | null
  subject_id: string | null
  method: string | null
  confidence: number
  plate_conf: number
  appearance_conf: number
  cooccur_conf: number
  matched_count: number
  snapshot_id: string | null
  created_at: string
}

/** 车辆详情 */
export interface VehicleDetail {
  vehicle: Vehicle
  resolutions: IdentityResolution[]
}

/** 待识别池查询参数 */
export interface PendingQuery {
  page?: number
  page_size?: number
  sort?: 'pass_count' | 'last_seen' | 'first_seen'
  order?: 'asc' | 'desc'
  keyword?: string
  status?: PendingStatus
}

/** 车辆档案查询参数 */
export interface VehicleQuery {
  page?: number
  page_size?: number
  sort?: 'last_seen' | 'first_seen' | 'vehicle_id'
  order?: 'asc' | 'desc'
  keyword?: string
  status?: string
}

/** 绑定请求体 */
export interface BindVehiclePayload {
  student_id: string
  method?: 'registered' | 'qr' | 'nfc' | 'appearance' | 'cooccur' | 'manual'
  note?: string
}

/** 绑定响应 */
export interface BindVehicleResult {
  vehicle: Vehicle
}

/** 忽略响应 */
export interface IgnorePendingResult {
  vehicle_id: string
  ignored: number
}

/** 待识别车辆池（分页+筛选） */
export function listPending(query: PendingQuery): Promise<IdentityPage<PendingListItem>> {
  return get<IdentityPage<PendingListItem>>(`${ADMIN_BASE}/identities/pending`, query, {
    silent: true,
  })
}

/** 绑定车辆到学生 */
export function bindVehicle(
  vehicleId: string,
  payload: BindVehiclePayload,
): Promise<BindVehicleResult> {
  return post<BindVehicleResult>(
    `${ADMIN_BASE}/identities/${encodeURIComponent(vehicleId)}/bind`,
    payload,
    { silent: true },
  )
}

/** 忽略待识别车辆 */
export function ignorePending(vehicleId: string): Promise<IgnorePendingResult> {
  return post<IgnorePendingResult>(
    `${ADMIN_BASE}/identities/${encodeURIComponent(vehicleId)}/ignore`,
    {},
    { silent: true },
  )
}

/** 车辆档案列表 */
export function listVehicles(query: VehicleQuery): Promise<IdentityPage<Vehicle>> {
  return get<IdentityPage<Vehicle>>(`${ADMIN_BASE}/vehicles`, query, { silent: true })
}

/** 车辆详情（含匹配历史） */
export function getVehicleDetail(vehicleId: string): Promise<VehicleDetail> {
  return get<VehicleDetail>(`${ADMIN_BASE}/vehicles/${encodeURIComponent(vehicleId)}`, undefined, {
    silent: true,
  })
}

// ===========================================================================
// 检测事件 API —— 多维筛选列表 / 详情 / CSV 导出
// URL 常量集中在此，组件中禁止硬编码路径
// ===========================================================================

import { get } from './request'
import http from './request'

const ADMIN_BASE = '/v1/admin/events'

/** 事件复核状态 */
export type EventStatus = 'pending' | 'confirmed' | 'dismissed'

/** 通行三态 */
export type RiderStatus = 'helmeted' | 'bare' | 'unknown'

/** 事件排序白名单（后端 EVENT_SORTS） */
export type EventSort = 'occurred_at/desc' | 'occurred_at/asc' | 'created_at/desc' | 'status/asc'

/** 事件列表项 */
export interface EventListItem {
  event_id: string
  pass_id: string
  source_id: string
  run_id: string
  occurred_at: string
  status: EventStatus | string
  model_label: string
  reason: string | null
  reviewer: string | null
  reviewed_at: string | null
  created_at: string
}

/** 事件列表包络 */
export interface EventPage {
  items: EventListItem[]
  total: number
  page: number
  page_size: number
}

/** 归一化检测框（xyxy，0~1） */
export interface EventBox {
  label: string
  confidence: number | null
  xyxy: [number, number, number, number]
}

/** 事件详情 */
export interface EventDetail extends EventListItem {
  rider_status: string | null
  boxes: EventBox[]
  image_width: number | null
  image_height: number | null
  decision_id: string | null
  decision_level: string | null
  decision_status: string | null
}

/** 事件查询参数 */
export interface EventQuery {
  page?: number
  page_size?: number
  source_id?: string
  status?: EventStatus | ''
  run_id?: string
  start?: string
  end?: string
  rider_status?: RiderStatus | ''
  has_evidence?: boolean | null
  has_decision?: boolean | null
  sort?: EventSort
}

/** 事件列表 */
export function listEvents(query: EventQuery): Promise<EventPage> {
  const params: Record<string, unknown> = { ...query }
  if (params.status === '') delete params.status
  if (params.rider_status === '') delete params.rider_status
  if (params.source_id === '') delete params.source_id
  if (params.run_id === '') delete params.run_id
  if (params.start === '') delete params.start
  if (params.end === '') delete params.end
  if (params.has_evidence === null || params.has_evidence === undefined) delete params.has_evidence
  if (params.has_decision === null || params.has_decision === undefined) delete params.has_decision
  return get<EventPage>(ADMIN_BASE, params, { silent: true })
}

/** 事件详情 */
export function getEventDetail(eventId: string): Promise<EventDetail> {
  return get<EventDetail>(`${ADMIN_BASE}/${encodeURIComponent(eventId)}`, undefined, {
    silent: true,
  })
}

/** 事件导出（带筛选参数，鉴权后以 Blob 下载；路由层直接返回 CSV 文本） */
export async function downloadEventsCsv(
  query: Omit<EventQuery, 'page' | 'page_size'>,
): Promise<Blob> {
  const params: Record<string, unknown> = { ...query }
  for (const key of Object.keys(params)) {
    const value = params[key]
    if (value === '' || value === null || value === undefined) delete params[key]
  }
  const response = await http.get(`${ADMIN_BASE}/export`, {
    params,
    responseType: 'blob',
    silent: true,
  })
  return response.data as Blob
}

/** 触发浏览器下载 Blob（与 students.ts saveBlob 同口径） */
export function saveEventsBlob(blob: Blob, filename = 'events-export.csv'): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

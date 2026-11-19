// ===========================================================================
// 实时监控 API —— 点位健康 / 违规流
// URL 常量集中在此，组件中禁止硬编码路径
// ===========================================================================

import { get, put } from './request'

const ADMIN_BASE = '/v1/admin/monitor'

/** 点位健康项 */
export interface MonitorPoint {
  source_id: string
  name: string
  status: string
  fps: number | null
  last_heartbeat: string | null
  heartbeat_age_seconds: number | null
  last_event_at: string | null
  today_events: number
  today_passes: number
}

/** 点位健康列表 */
export interface MonitorPointList {
  items: MonitorPoint[]
  total: number
}

/** 单点位快照 */
export interface MonitorPointDetail {
  point: MonitorPoint
  last_event: {
    event_id: string
    occurred_at: string
    status: string
    model_label: string
  } | null
}

/** 单点位快照证据帧（复用 passes 检测框，归一化 0~1） */
export interface MonitorSnapshotEvidenceBox {
  label: string
  confidence: number | null
  xyxy: [number, number, number, number]
}

export interface MonitorSnapshotEvidence {
  pass_id: string
  occurred_at: string
  rider_status: string
  boxes: MonitorSnapshotEvidenceBox[]
  image_width: number | null
  image_height: number | null
}

/** 单点位快照（含证据，无真实视频，不编造 URL） */
export interface MonitorSnapshot {
  point: MonitorPoint
  last_event: MonitorPointDetail['last_event']
  evidence: MonitorSnapshotEvidence | null
}

/** 单点位流状态（当前无真实视频源，一律不可用） */
export interface MonitorStream {
  point_id: string
  available: boolean
  stream_url: string | null
  reason: string
}

/** 点位标定配置（归一化 ROI / 计数线 / 提醒区） */
export interface MonitorConfig {
  point_id: string
  roi: [number, number, number, number]
  count_line_y: number
  alert_zone: [number, number, number, number]
  updated_by: string | null
  updated_at: string | null
}

/** 点位标定写入体 */
export interface UpdateMonitorConfigBody {
  roi: [number, number, number, number]
  count_line_y: number
  alert_zone: [number, number, number, number]
}

/** 实时违规流单条 */
export interface MonitorFeedItem {
  event_id: string
  source_id: string
  point_name: string
  occurred_at: string
  status: string
  model_label: string
  decision_level: string | null
  decision_status: string | null
}

/** 实时违规流 */
export interface MonitorFeed {
  items: MonitorFeedItem[]
  total: number
}

/** 推送消息类型（与说明书 §10.4 对齐） */
export type LiveMessageType =
  'violation_detected' | 'decision_created' | 'device_status' | 'stats_update' | 'point_alert'

/** 推送消息包络 */
export interface LiveMessage {
  type: LiveMessageType | string
  point_id?: string | null
  data?: Record<string, unknown>
}

/** 点位健康列表 */
export function listMonitorPoints(): Promise<MonitorPointList> {
  return get<MonitorPointList>(`${ADMIN_BASE}/points`, undefined, { silent: true })
}

/** 单点位快照 */
export function getMonitorPoint(pointId: string): Promise<MonitorPointDetail> {
  return get<MonitorPointDetail>(`${ADMIN_BASE}/points/${encodeURIComponent(pointId)}`, undefined, {
    silent: true,
  })
}

/** 实时违规流初始数据 */
export function getMonitorFeed(params?: {
  point_id?: string
  limit?: number
}): Promise<MonitorFeed> {
  const query: Record<string, unknown> = { ...(params ?? {}) }
  if (query.point_id === '' || query.point_id === undefined) delete query.point_id
  return get<MonitorFeed>(`${ADMIN_BASE}/feed`, query, { silent: true })
}

/** 单点位快照：健康 + 最近事件 + 最近通行证据帧（无真实视频） */
export function getMonitorSnapshot(pointId: string): Promise<MonitorSnapshot> {
  return get<MonitorSnapshot>(
    `${ADMIN_BASE}/points/${encodeURIComponent(pointId)}/snapshot`,
    undefined,
    {
      silent: true,
    },
  )
}

/** 单点位流状态：当前一律不可用（诚实降级，不编造 URL） */
export function getMonitorStream(pointId: string): Promise<MonitorStream> {
  return get<MonitorStream>(
    `${ADMIN_BASE}/points/${encodeURIComponent(pointId)}/stream`,
    undefined,
    {
      silent: true,
    },
  )
}

/** 读取点位标定配置（无行回退内存默认） */
export function getMonitorConfig(pointId: string): Promise<MonitorConfig> {
  return get<MonitorConfig>(
    `${ADMIN_BASE}/points/${encodeURIComponent(pointId)}/config`,
    undefined,
    {
      silent: true,
    },
  )
}

/** 覆盖点位标定配置（归一化校验 + 事务 + 审计） */
export function updateMonitorConfig(
  pointId: string,
  body: UpdateMonitorConfigBody,
): Promise<MonitorConfig> {
  return put<MonitorConfig>(`${ADMIN_BASE}/points/${encodeURIComponent(pointId)}/config`, body)
}

/** WS 地址：浏览器无法自定义 Authorization 头，走 query token */
export function buildLiveUrl(token: string): string {
  const base = import.meta.env.VITE_WS_BASE_URL as string | undefined
  const path = '/api/v1/admin/ws/live'
  const query = `token=${encodeURIComponent(token)}`
  if (base) return `${base.replace(/\/$/, '')}${path}?${query}`
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${path}?${query}`
}

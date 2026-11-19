// ===========================================================================
// 实时监控格式化 —— 点位状态、违规流时间、档位标签
// 纯函数，无 I/O，便于单元测试与组件复用
// ===========================================================================

import type { MonitorFeedItem, MonitorPoint } from '@/api/monitor'

/** 点位状态标签（在线 / 离线，中性表述） */
export function pointStatusLabel(status: string): string {
  const map: Record<string, string> = {
    online: '在线',
    offline: '离线',
    degraded: '降级',
  }
  return map[status] ?? status
}

/** 点位状态色调：在线绿、降级橙、离线中性（未知不标红） */
export function pointStatusTone(status: string): 'success' | 'warning' | 'neutral' {
  if (status === 'online') return 'success'
  if (status === 'degraded') return 'warning'
  return 'neutral'
}

/** FPS 展示：缺失不断言为 0，直接展示缺失符 */
export function formatFps(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toFixed(1)
}

/** 计数展示：缺失回退 0（后端聚合恒为数字，前端做防御） */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '0'
  return `${value}`
}

/** ISO 时间截取 HH:mm:ss，失败回退原串 */
export function formatFeedTime(value: string | null | undefined): string {
  if (!value) return '—'
  const matched = /T(\d{2}:\d{2}:\d{2})/.exec(value)
  if (matched) return matched[1]
  return value.slice(0, 19).replace('T', ' ')
}

/** ISO 日期截取 MM-DD HH:mm（违规流紧凑展示） */
export function formatFeedDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const matched = /(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(value)
  if (matched) return `${matched[1]}-${matched[2]} ${matched[3]}`
  return formatFeedTime(value)
}

/** 决策档位标签（与审批中心 LEVEL_LABELS 同口径） */
export function feedLevelLabel(level: string | null | undefined): string {
  const map: Record<string, string> = {
    L0: '无需处理',
    L1: '现场提醒',
    L2: '记分提醒',
    L3: '重点关注',
    L4: '正向激励',
  }
  if (!level) return '待定级'
  return map[level] ?? level
}

/** 违规流单条标题：点位名 + 事件编号后 6 位（避免长串撑开布局） */
export function feedItemTitle(item: MonitorFeedItem): string {
  const point = item.point_name || item.source_id
  const shortId = item.event_id.length > 8 ? item.event_id.slice(-6) : item.event_id
  return `${point} · ${shortId}`
}

/** 心跳年龄展示：秒级，过 60s 转分钟（只读展示，不做状态判定） */
export function formatHeartbeatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s 前`
  return `${Math.floor(seconds / 60)}min 前`
}

/** 今日佩戴率：passes / (passes + events)，无通行时回退缺失符 */
export function wearRateOf(points: MonitorPoint[]): string {
  const passes = points.reduce((sum, item) => sum + (item.today_passes ?? 0), 0)
  const events = points.reduce((sum, item) => sum + (item.today_events ?? 0), 0)
  const total = passes + events
  if (total <= 0) return '—'
  return `${((passes / total) * 100).toFixed(1)}%`
}

/** WS 包络最小结构（与后端 hub 广播载荷对齐） */
export interface LiveEnvelope {
  type: string
  point_id?: string | null
  data?: Record<string, unknown>
}

/** 从未知载荷中取字符串字段（缺失回退空串，不抛错） */
export function stringField(data: Record<string, unknown> | undefined, key: string): string {
  const value = data?.[key]
  return typeof value === 'string' ? value : ''
}

/** 从未知载荷中取数字字段（缺失回退 null，不臆造 0） */
export function numberField(data: Record<string, unknown> | undefined, key: string): number | null {
  const value = data?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

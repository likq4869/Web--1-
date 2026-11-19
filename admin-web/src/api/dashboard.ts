// ===========================================================================
// 总览 Dashboard API —— 指标总览、趋势序列、点位健康
// URL 常量集中在此，组件中禁止硬编码路径
// ===========================================================================

import { get } from './request'

const ADMIN_BASE = '/v1/admin/dashboard'

/** 今日核心指标 */
export interface TodayMetrics {
  /** 今日通行总数 */
  passes: number
  /** 今日未佩戴数 */
  violations: number
  /** 今日佩戴率（0~1） */
  wear_rate: number
  /** 已判定数（佩戴 + 未佩戴） */
  judged: number
  /** 证据不足数 */
  unknown: number
}

/** 佩戴率趋势单点 */
export interface WearRatePoint {
  /** 日期（ISO） */
  date: string
  /** 佩戴率（0~1） */
  wear_rate: number
  /** 通行数 */
  passes: number
  /** 未佩戴数 */
  violations: number
}

/** 按小时违规分布 */
export interface HourViolationPoint {
  /** 小时（0~23） */
  hour: number
  /** 数量 */
  count: number
}

/** 与昨日对比 */
export interface ComparisonMetrics {
  /** 通行数变化 */
  passes_delta: number
  /** 未佩戴数变化 */
  violations_delta: number
  /** 佩戴率变化（小数） */
  wear_rate_delta: number
}

/** 点位健康项 */
export interface PointHealthItem {
  /** 点位 ID */
  source_id: string
  /** 点位名称 */
  name: string
  /** 状态：online / offline / degraded */
  status: string
  /** 采集帧率 */
  fps: number | null
  /** 最近心跳时间 */
  last_seen: string | null
  /** 今日事件数 */
  today_events: number
  /** 最近错误 */
  last_error: string | null
}

/** 总览载荷 */
export interface DashboardOverview {
  today: TodayMetrics
  trends: {
    wear_rate: WearRatePoint[]
    violations_by_hour: HourViolationPoint[]
  }
  pending_reviews: number
  points: {
    online: number
    total: number
  }
  students: {
    active: number
    registered: number
  }
  comparison: ComparisonMetrics
  point_health: PointHealthItem[]
  generated_at: string
}

/** 趋势指标 */
export type TrendMetric = 'wear_rate' | 'violations' | 'passes'

/** 趋势粒度 */
export type TrendGranularity = 'day' | 'hour'

/** 趋势载荷 */
export interface TrendResult {
  metric: TrendMetric
  granularity: TrendGranularity
  days: number
  points: Array<Record<string, unknown>>
}

/** 点位健康载荷 */
export interface PointHealthResult {
  items: PointHealthItem[]
}

/** 总览 */
export function getOverview(): Promise<DashboardOverview> {
  return get<DashboardOverview>(`${ADMIN_BASE}/overview`, undefined, { silent: true })
}

/** 趋势序列 */
export function getTrends(
  metric: TrendMetric = 'wear_rate',
  granularity: TrendGranularity = 'day',
  days = 30,
): Promise<TrendResult> {
  return get<TrendResult>(`${ADMIN_BASE}/trends`, { metric, granularity, days }, { silent: true })
}

/** 点位健康 */
export function getPointHealth(): Promise<PointHealthResult> {
  return get<PointHealthResult>(`${ADMIN_BASE}/point-health`, undefined, { silent: true })
}

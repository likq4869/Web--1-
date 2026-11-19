// ===========================================================================
// 积分管理 API —— 账户 / 台账流水 / 规则更新与试算
// URL 常量集中在此，组件中禁止硬编码路径
// ===========================================================================

import { get, post, put } from './request'

const ADMIN_BASE = '/v1/admin/scores'

/** 积分账户 */
export interface ScoreAccount {
  student_id: string
  name: string | null
  balance: number
  level: string
  total_deducted: number
  total_awarded: number
  streak_days: number
  compliance_rate: number
  updated_at: string | null
}

/** 积分流水 */
export interface ScoreLedger {
  ledger_id: number
  student_id: string
  change: number
  balance_after: number
  reason_code: string
  reason_text: string | null
  event_id: string | null
  decision_id: string | null
  operator: string | null
  effective_at: string | null
  created_at: string | null
}

/** 积分规则 */
export interface ScoreRule {
  rule_id: string
  rule_type: string
  name: string
  condition_json: Record<string, unknown>
  score_change: number
  priority: number
  enabled: boolean
  created_at: string | null
  updated_at: string | null
}

/** 后端分页包络（积分域：无 pages 字段） */
export interface ScorePage<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/** 账户查询参数 */
export interface AccountQuery {
  page?: number
  page_size?: number
  keyword?: string
}

/** 台账方向 */
export type LedgerDirection = 'all' | 'positive' | 'negative'

/** 台账查询参数 */
export interface LedgerQuery {
  page?: number
  page_size?: number
  student_id?: string
  start?: string
  end?: string
  direction?: LedgerDirection
  reason_code?: string
}

/** 规则更新请求体（结构化字段，禁止自由表达式字符串） */
export interface RuleUpdatePayload {
  name?: string
  condition_json?: Record<string, unknown>
  score_change?: number
  priority?: number
  enabled?: boolean
  rule_type?: 'deduct' | 'award' | 'streak'
}

/** 规则试算请求体 */
export interface RuleSimulatePayload {
  rule_id?: string
  condition_json?: Record<string, unknown>
  context?: Record<string, unknown>
}

/** 规则试算响应 */
export interface RuleSimulateResult {
  matched: boolean
  total_change: number
  matched_rule_ids: string[]
  reasons: string[]
}

/** 积分账户列表 */
export function listAccounts(query: AccountQuery): Promise<ScorePage<ScoreAccount>> {
  const params = { ...query }
  if (params.keyword === '') delete params.keyword
  return get<ScorePage<ScoreAccount>>(`${ADMIN_BASE}/accounts`, params, { silent: true })
}

/** 积分台账流水 */
export function listLedger(query: LedgerQuery): Promise<ScorePage<ScoreLedger>> {
  const params: Record<string, unknown> = { ...query }
  if (params.student_id === '') delete params.student_id
  if (params.reason_code === '') delete params.reason_code
  if (params.start === '') delete params.start
  if (params.end === '') delete params.end
  if (params.direction === 'all') delete params.direction
  return get<ScorePage<ScoreLedger>>(`${ADMIN_BASE}/ledger`, params, { silent: true })
}

/** 积分规则列表 */
export function listRules(): Promise<{ items: ScoreRule[]; total: number }> {
  return get<{ items: ScoreRule[]; total: number }>(`${ADMIN_BASE}/rules`, undefined, {
    silent: true,
  })
}

/** 更新积分规则 */
export function updateRule(ruleId: string, payload: RuleUpdatePayload): Promise<ScoreRule> {
  return put<ScoreRule>(`${ADMIN_BASE}/rules/${encodeURIComponent(ruleId)}`, payload, {
    silent: true,
  })
}

/** 规则试算（只推演不写库） */
export function simulateRule(payload: RuleSimulatePayload): Promise<RuleSimulateResult> {
  return post<RuleSimulateResult>(`${ADMIN_BASE}/rules/simulate`, payload, { silent: true })
}

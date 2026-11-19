// ===========================================================================
// 策略配置 API —— 当前策略读取 / 结构化更新 / 模拟推演
// URL 常量集中在此，组件中禁止硬编码路径
// ===========================================================================

import { get, post, put } from './request'

const ADMIN_BASE = '/v1/admin/policies'

/** 决策策略全字段（读写共用，更新时全部可选） */
export interface DecisionPolicyBody {
  min_model_confidence?: number
  min_identity_confidence?: number
  l1_score?: number
  l2_score?: number
  l3_score?: number
  award_score?: number
  l3_violation_30d?: number
  l3_violation_7d?: number
  l3_same_point_1h?: number
  l2_violation_30d?: number
  l2_violation_7d?: number
  streak_award_days?: number
  confidence_model_weight?: number
  confidence_identity_weight?: number
  max_auto_score_delta?: number
}

/** 熔断阈值全字段（更新时全部可选） */
export interface BreakerThresholdsBody {
  max_daily_punishments?: number
  min_student_daily_delta?: number
  min_model_map?: number
  max_dismiss_rate?: number
  min_identity_bind_rate?: number
}

/** 规则注册表摘要项（与后端 RULE_REGISTRY 对齐：name/title） */
export interface PolicyRuleSummary {
  name: string
  title: string
}

/** 策略当前值 */
export interface PolicyResponse {
  policy_id: string
  version: string
  policy: Record<string, number>
  thresholds: Record<string, number>
  rules: PolicyRuleSummary[]
}

/** 策略更新请求体（两段各自独立可选） */
export interface PolicyUpdateBody {
  policy?: DecisionPolicyBody
  thresholds?: BreakerThresholdsBody
}

/** 策略模拟请求体：候选策略 + 假设事实，只推演不写库 */
export interface PolicySimulateBody extends PolicyUpdateBody {
  model_confidence?: number
  identity_confidence?: number
  violation_count_30d?: number
  violation_count_7d?: number
  violation_count_1h_same_point?: number
  limit?: number
}

/** 单条差异（与后端 replay_decision 对齐） */
export interface PolicySimulateDiff {
  decision_id: string
  changed: boolean
  diff_reason: string
  original_level: string
  replayed_level: string
}

/** 策略模拟响应（只推演，不会真实生效） */
export interface PolicySimulateResponse {
  policy_id: string
  simulated: number
  changed: number
  diffs: PolicySimulateDiff[]
  note: string
}

/** 读取策略当前值（含版本、熔断阈值、规则注册表摘要） */
export function getPolicy(policyId = 'default'): Promise<PolicyResponse> {
  return get<PolicyResponse>(`${ADMIN_BASE}/${encodeURIComponent(policyId)}`, undefined, {
    silent: true,
  })
}

/** 更新策略与阈值（结构化字段；事务由后端收敛） */
export function updatePolicy(policyId: string, body: PolicyUpdateBody): Promise<PolicyResponse> {
  return put<PolicyResponse>(`${ADMIN_BASE}/${encodeURIComponent(policyId)}`, body, {
    silent: true,
  })
}

/** 策略模拟：用候选策略重放历史决策，只推演不写库 */
export function simulatePolicy(
  policyId: string,
  body: PolicySimulateBody,
): Promise<PolicySimulateResponse> {
  return post<PolicySimulateResponse>(
    `${ADMIN_BASE}/${encodeURIComponent(policyId)}/simulate`,
    body,
    { silent: true },
  )
}

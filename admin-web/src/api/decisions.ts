// ===========================================================================
// 审批中心 API —— 决策列表 / 详情 / 审批动作
// URL 常量集中在此，组件中禁止硬编码路径
// ===========================================================================

import { get, post } from './request'

const ADMIN_BASE = '/v1/admin'

/** 决策档位 */
export type DecisionLevel = 'L0' | 'L1' | 'L2' | 'L3' | 'L4'

/** 审批状态 */
export type DecisionStatus =
  | 'PENDING_REVIEW'
  | 'APPROVED'
  | 'REJECTED'
  | 'ADJUSTED'
  | 'AUTO_APPROVED'
  | 'APPEALING'
  | 'APPEAL_UPHELD'
  | 'APPEAL_REJECTED'
  | 'EXPIRED'

/** 排序方式（后端白名单） */
export type DecisionSort = 'created_at/desc' | 'confidence/desc' | 'level/asc'

/** 决策列表项 */
export interface DecisionListItem {
  decision_id: string
  event_id: string
  student_id: string | null
  level: DecisionLevel
  action: string
  score_delta: number
  reason_code: string
  confidence: number | null
  status: DecisionStatus
  auto_approved: boolean
  created_at: string | null
  due_at: string | null
}

/** 决策列表响应 */
export interface DecisionPage {
  items: DecisionListItem[]
  total: number
  page: number
  page_size: number
}

/** 可解释因子 */
export interface DecisionFactor {
  name: string
  value: number
  weight: number
  evidence: string
}

/** 事件详情 */
export interface DecisionEvent {
  event_id: string
  pass_id: string
  source_id: string
  run_id: string
  occurred_at: string
  status: string
  model_label: string
  reason: string
  reviewed_by: string | null
  reviewed_at: string | null
  created_at: string
}

/** 身份判定结果 */
export interface IdentityResolution {
  method: string | null
  confidence: number
  plate_confidence: number
  appearance_confidence: number
  cooccur_confidence: number
  matched_count: number
  vehicle_id: string | null
  subject_id: string | null
  snapshot_id: string | null
  created_at: string
}

/** 学生档案 + 积分概况 */
export interface DecisionStudent {
  student_id: string
  name: string
  college: string | null
  class_name: string | null
  grade: string | null
  status: string
  balance: number | null
  level: string | null
  streak_days: number | null
  compliance_rate: number | null
  violation_count_30d: number
  violation_count_total: number
}

/** 风险提示 */
export interface RiskHintItem {
  code: string
  text: string
  level: 'warning' | 'danger' | 'neutral'
}

/** 审批轨迹 */
export interface ReviewLogItem {
  id: number
  action: string
  from_status: string | null
  to_status: string | null
  from_level: string | null
  to_level: string | null
  note: string | null
  operator: string
  created_at: string | null
}

/** 归一化检测框（xyxy，0~1；与 image_width/image_height 同坐标系） */
export interface DetectionBox {
  /** 类别名（如 Cyclists / helmet / no helmet） */
  label: string
  /** 置信度 0-1 */
  confidence: number | null
  /** 左上角与右下角坐标：[x1, y1, x2, y2] */
  xyxy: number[]
}

/** 证据引用 —— 支撑「证据帧 + 检测框叠加」 */
export interface EvidenceRefs {
  /** 事件 ID */
  event_id?: string
  /** 点位 ID */
  source_id?: string
  /** 车辆 ID */
  vehicle_id?: string | null
  /** 证据快照 ID */
  snapshot_id?: string | null
  /** 熔断器是否触发 */
  breaker_tripped?: boolean
  /** 熔断规则 */
  breaker_rule?: string | null
  /** 熔断原因 */
  breaker_reason?: string | null
  /** 检测框列表（归一化 xyxy） */
  boxes?: DetectionBox[]
  /** 原图宽度（像素） */
  image_width?: number | null
  /** 原图高度（像素） */
  image_height?: number | null
}

/** 决策详情 */
export interface DecisionDetail {
  decision_id: string
  event_id: string
  student_id: string | null
  level: DecisionLevel
  action: string
  score_delta: number
  reason_code: string
  message: string | null
  confidence: number | null
  factors: DecisionFactor[] | Record<string, unknown>[] | null
  evidence_refs: EvidenceRefs | null
  policy_version: string | null
  status: DecisionStatus
  auto_approved: boolean
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string | null
  original_level: DecisionLevel | null
  effective_at: string | null
  due_at: string | null
  created_at: string | null
  review_logs: ReviewLogItem[]
  event: DecisionEvent | null
  identity_resolution: IdentityResolution | null
  student: DecisionStudent | null
  risk_hints: RiskHintItem[]
}

/** 列表查询参数 */
export interface DecisionQuery {
  page?: number
  page_size?: number
  status?: DecisionStatus | ''
  level?: DecisionLevel | ''
  point_id?: string
  student_id?: string
  start?: string
  end?: string
  min_confidence?: number | null
  sort?: DecisionSort
}

/** 批量结果单条 */
export interface BatchApproveItem {
  decision_id: string
  ok: boolean
  status: string | null
  error: string | null
}

/** 批量结果 */
export interface BatchApproveResult {
  items: BatchApproveItem[]
  total: number
}

/** 决策列表 */
export function listDecisions(query: DecisionQuery): Promise<DecisionPage> {
  const params = { ...query }
  if (params.status === '') delete params.status
  if (params.level === '') delete params.level
  if (params.min_confidence === null) delete params.min_confidence
  return get<DecisionPage>(`${ADMIN_BASE}/decisions`, params, { silent: true })
}

/** 决策详情 */
export function getDecisionDetail(decisionId: string): Promise<DecisionDetail> {
  return get<DecisionDetail>(
    `${ADMIN_BASE}/decisions/${encodeURIComponent(decisionId)}`,
    undefined,
    {
      silent: true,
    },
  )
}

/** 待审批计数 */
export function getPendingCount(): Promise<{ pending: number }> {
  return get<{ pending: number }>(`${ADMIN_BASE}/decisions/pending-count`, undefined, {
    silent: true,
  })
}

/** 批准（可降档） */
export function approveDecision(
  decisionId: string,
  payload: { level?: string; note?: string } = {},
): Promise<DecisionDetail> {
  return post<DecisionDetail>(
    `${ADMIN_BASE}/decisions/${encodeURIComponent(decisionId)}/approve`,
    payload,
    { silent: true },
  )
}

/** 驳回（理由必填） */
export function rejectDecision(decisionId: string, reason: string): Promise<DecisionDetail> {
  return post<DecisionDetail>(
    `${ADMIN_BASE}/decisions/${encodeURIComponent(decisionId)}/reject`,
    { reason },
    { silent: true },
  )
}

/** 批量批准 */
export function batchApprove(decisionIds: string[], note?: string): Promise<BatchApproveResult> {
  return post<BatchApproveResult>(
    `${ADMIN_BASE}/decisions/batch-approve`,
    { decision_ids: decisionIds, note: note ?? '' },
    { silent: true },
  )
}

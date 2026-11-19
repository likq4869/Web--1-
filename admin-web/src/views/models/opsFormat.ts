// ===========================================================================
// 运维管理格式化 —— 模型任务/回流来源/审计动作/角色标签
// 纯函数，无 I/O，便于单元测试与组件复用
// ===========================================================================

/** 模型任务标签 */
export function modelTaskLabel(task: string): string {
  const map: Record<string, string> = {
    detect: '头盔检测',
    plate: '车牌识别',
    head_cls: '头部二分类',
    reid: '车辆重识别',
  }
  return map[task] ?? task
}

/** 模型激活徽章：激活 success / 未激活 info（中性，绝不用 danger） */
export function modelActiveBadge(isActive: boolean): string {
  return isActive ? 'success' : 'info'
}

/** 模型激活标签 */
export function modelActiveLabel(isActive: boolean): string {
  return isActive ? '激活中' : '未激活'
}

/** 回流来源标签 */
export function feedbackSourceLabel(source: string): string {
  const map: Record<string, string> = {
    review_reject: '审批驳回',
    appeal_upheld: '申诉成立',
    manual: '人工标注',
  }
  return map[source] ?? source
}

/** 账户状态徽章：启用 success / 停用 info */
export function accountStatusBadge(status: string): string {
  return status === 'active' ? 'success' : 'info'
}

/** 账户状态标签（去技术词） */
export function accountStatusLabel(status: string): string {
  const map: Record<string, string> = {
    active: '启用',
    disabled: '停用',
  }
  return map[status] ?? status
}

/** 角色标签（与后端 9 角色对齐） */
export function roleLabel(role: string): string {
  const map: Record<string, string> = {
    super_admin: '超级管理员',
    admin: '管理员',
    reviewer: '审批员',
    observer: '观察员',
    league_officer: '团委干事',
    counselor: '辅导员',
    security_officer: '保卫干事',
    auditor: '审计员',
    student: '学生',
  }
  return map[role] ?? role
}

/** ISO 时间截取 YYYY-MM-DD HH:mm，失败回退原串 */
export function formatOpsDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const matched = /(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(value)
  if (matched) return `${matched[1]} ${matched[2]}`
  return value.slice(0, 16).replace('T', ' ')
}

/** 指标摘要：precision/recall 截取两位小数，缺失回退占位 */
export function metricsSummary(metrics: Record<string, unknown> | null): string {
  if (!metrics) return '—'
  const parts: string[] = []
  const precision = metrics.precision
  const recall = metrics.recall
  if (typeof precision === 'number') parts.push(`P ${precision.toFixed(2)}`)
  if (typeof recall === 'number') parts.push(`R ${recall.toFixed(2)}`)
  if (parts.length > 0) return parts.join(' / ')
  const note = metrics.note
  if (typeof note === 'string' && note.trim() !== '') return note.slice(0, 24)
  return '—'
}

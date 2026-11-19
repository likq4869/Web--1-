// ===========================================================================
// 申诉处理格式化 —— 状态标签/徽章、附件计数、时间截取
// 纯函数，无 I/O，便于单元测试与组件复用
// ===========================================================================

import type { AppealListItem } from '@/api/appeals'

/** 申诉状态标签；历史 submitted/processing 收敛为「待处理」 */
export function appealStatusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '待处理',
    submitted: '待处理',
    processing: '待处理',
    upheld: '申诉成立',
    rejected: '申诉驳回',
  }
  return map[status] ?? status
}

/** 申诉状态徽章：待处理 warning / 成立 success / 驳回 info（未知中性，绝不用 danger 误导） */
export function appealStatusBadge(status: string): string {
  if (status === 'upheld') return 'success'
  if (status === 'rejected') return 'info'
  return 'warning'
}

/** 附件数量（数组 / 对象 / 空统一收敛为数字） */
export function attachmentCount(item: AppealListItem): number {
  if (Array.isArray(item.attachments)) return item.attachments.length
  return 0
}

/** 附件名列表（字符串原样，对象取 name/url 兜底序号） */
export function attachmentNames(item: AppealListItem): string[] {
  if (!Array.isArray(item.attachments)) return []
  return item.attachments.map((entry, index) => {
    if (typeof entry === 'string') return entry
    if (entry !== null && typeof entry === 'object') {
      const bag = entry as Record<string, unknown>
      const name = bag.name ?? bag.url ?? bag.snapshot_id
      if (typeof name === 'string' && name.trim() !== '') return name
    }
    return `附件 ${index + 1}`
  })
}

/** 是否终态（成立 / 驳回后不可再次裁决，后端幂等返回既有行） */
export function isAppealResolved(status: string): boolean {
  return status === 'upheld' || status === 'rejected'
}

/** ISO 时间截取 YYYY-MM-DD HH:mm，失败回退原串 */
export function formatAppealDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const matched = /(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(value)
  if (matched) return `${matched[1]} ${matched[2]}`
  return value.slice(0, 16).replace('T', ' ')
}

/** 处理人展示（未处理显示受理中占位，禁用「无数据」类技术词） */
export function handlerLabel(item: AppealListItem): string {
  if (item.handler && item.handler.trim() !== '') return item.handler
  return isAppealResolved(item.status) ? '系统' : '待受理'
}

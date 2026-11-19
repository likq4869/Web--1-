// ===========================================================================
// 事件列表格式化 —— 状态/三态标签、时间截取、归一化框转换
// 纯函数，无 I/O，便于单元测试与组件复用
// ===========================================================================

import type { EvidenceBox } from '@/components/EvidenceViewer.vue'
import type { EventBox, EventDetail } from '@/api/events'

/** 复核状态标签（面向管理员可用「违规」类准确表述） */
export function eventStatusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '待复核',
    confirmed: '已确认',
    dismissed: '已驳回',
  }
  return map[status] ?? status
}

/** 通行三态标签；unknown 用中性表述，绝不标红由徽章色调承担 */
export function riderStatusLabel(status: string | null): string {
  const map: Record<string, string> = {
    helmeted: '已佩戴',
    bare: '未佩戴',
    unknown: '证据不足',
  }
  if (status === null || status === '') return '证据不足'
  return map[status] ?? status
}

/** 三态徽章类型：unknown 必须中性，绝不用 danger */
export function riderStatusBadge(status: string | null): string {
  if (status === 'helmeted') return 'success'
  if (status === 'bare') return 'danger'
  return 'info'
}

/** 复核状态徽章类型 */
export function eventStatusBadge(status: string): string {
  if (status === 'confirmed') return 'danger'
  if (status === 'dismissed') return 'info'
  return 'warning'
}

/** ISO 时间截取 HH:mm:ss，失败回退原串 */
export function formatEventTime(value: string | null | undefined): string {
  if (!value) return '—'
  const matched = /T(\d{2}:\d{2}:\d{2})/.exec(value)
  if (matched) return matched[1]
  return value.slice(0, 19).replace('T', ' ')
}

/** ISO 日期截取 YYYY-MM-DD HH:mm，失败回退原串 */
export function formatEventDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const matched = /(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(value)
  if (matched) return `${matched[1]} ${matched[2]}`
  return value.slice(0, 16).replace('T', ' ')
}

/** 检测框配色与小程序 boxColor 一致：helmet 绿 / no helmet 红 / 其他蓝 */
export function eventBoxTone(label: string): 'success' | 'danger' | 'primary' {
  const normalized = label.trim().toLowerCase()
  if (normalized === 'helmet') return 'success'
  if (normalized === 'no helmet' || normalized === 'no-helmet' || normalized === 'no_helmet') {
    return 'danger'
  }
  return 'primary'
}

/** 后端归一化 xyxy → EvidenceViewer x/y/width/height（0~1） */
export function toEventEvidenceBoxes(boxes: EventBox[]): EvidenceBox[] {
  return boxes
    .filter((box) => Array.isArray(box.xyxy) && box.xyxy.length === 4)
    .map((box) => {
      const [x1, y1, x2, y2] = box.xyxy
      const left = Number.isFinite(x1) ? x1 : 0
      const top = Number.isFinite(y1) ? y1 : 0
      return {
        x: left,
        y: top,
        width: Math.max(0, (Number.isFinite(x2) ? x2 : left) - left),
        height: Math.max(0, (Number.isFinite(y2) ? y2 : top) - top),
        label: box.label,
        confidence: typeof box.confidence === 'number' ? box.confidence : undefined,
        tone: eventBoxTone(box.label),
      }
    })
}

/** 详情是否有证据图尺寸（横竖图对齐依据） */
export function hasEvidenceSize(detail: EventDetail | null): boolean {
  if (!detail) return false
  return (
    typeof detail.image_width === 'number' &&
    typeof detail.image_height === 'number' &&
    detail.image_width > 0 &&
    detail.image_height > 0
  )
}

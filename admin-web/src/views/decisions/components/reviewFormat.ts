import type { EvidenceBox } from '@/components/EvidenceViewer.vue'
import type { FactorItem } from '@/components/FactorList.vue'

/** 档位分值表（与后端 LEVEL_DEFAULT_SCORES 对齐） */
export const LEVEL_SCORES: Record<string, number> = {
  L0: 0,
  L1: 0,
  L2: -1,
  L3: -3,
  L4: 2,
}

export const LEVEL_LABELS: Record<string, string> = {
  L0: '无需处理',
  L1: '现场提醒',
  L2: '记分提醒',
  L3: '重点关注',
  L4: '正向激励',
}

/** 档位色调：L1 橙 / L2 橙深 / L3 红 / L4 绿 */
export function levelTone(level: string): string {
  switch (level) {
    case 'L1':
      return 'warning'
    case 'L2':
      return 'deep-warning'
    case 'L3':
      return 'danger'
    case 'L4':
      return 'success'
    default:
      return 'neutral'
  }
}

/** 配色规则与小程序 `boxColor` 一致：helmet=绿 / no helmet=红 / 其他=蓝 */
export function boxTone(label: string): 'success' | 'danger' | 'primary' {
  const normalized = label.toLowerCase()
  if (normalized === 'helmet') return 'success'
  if (normalized === 'no helmet' || normalized === 'no-helmet' || normalized === 'no_helmet') {
    return 'danger'
  }
  return 'primary'
}

export function methodLabel(method: string | null): string {
  const map: Record<string, string> = {
    plate: '车牌 OCR',
    qr: '二维码',
    nfc: 'NFC',
    appearance: '车辆外观',
    cooccur: '共现图谱',
    manual: '人工登记',
  }
  return method ? (map[method] ?? method) : '未绑定'
}

export function maskStudentId(studentId: string): string {
  if (studentId.length <= 4) return studentId
  return `${studentId.slice(0, 2)}****${studentId.slice(-2)}`
}

export function studentNameOf(studentId: string | null): string {
  return studentId ? maskStudentId(studentId) : '身份待确认'
}

export function formatConfidence(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—'
  return value.toFixed(2)
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${(value * 100).toFixed(1)}%`
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  const matched = /T(\d{2}:\d{2}:\d{2})/.exec(value)
  return matched ? matched[1] : value
}

/** 后端归一化 xyxy → 组件 x/y/width/height；坐标系与原图一致 */
export function toEvidenceBoxes(refs: unknown): EvidenceBox[] {
  if (!refs || typeof refs !== 'object') return []
  const boxes = (refs as { boxes?: unknown }).boxes
  if (!Array.isArray(boxes)) return []
  return boxes
    .filter((box): box is Record<string, unknown> => typeof box === 'object' && box !== null)
    .map((box) => {
      const label = String(box.label ?? '目标')
      const xyxy = Array.isArray(box.xyxy) ? box.xyxy.map(Number) : []
      const x1 = xyxy.length === 4 ? xyxy[0] : 0
      const y1 = xyxy.length === 4 ? xyxy[1] : 0
      const x2 = xyxy.length === 4 ? xyxy[2] : 0
      const y2 = xyxy.length === 4 ? xyxy[3] : 0
      return {
        x: x1,
        y: y1,
        width: Math.max(0, x2 - x1),
        height: Math.max(0, y2 - y1),
        label,
        confidence: typeof box.confidence === 'number' ? box.confidence : undefined,
        tone: boxTone(label),
        detail: typeof box.detail === 'string' ? box.detail : undefined,
      }
    })
}

/** 因子清洗：只保留有人话 name + 数值 value 的项 */
export function toFactors(raw: unknown): FactorItem[] {
  if (!Array.isArray(raw)) return []
  return raw.filter((item): item is FactorItem => {
    const f = item as Partial<FactorItem>
    return typeof f.name === 'string' && typeof f.value === 'number'
  })
}

export function evidenceSizeOf(refs: unknown): { width: number | null; height: number | null } {
  if (!refs || typeof refs !== 'object') return { width: null, height: null }
  const bag = refs as { image_width?: unknown; image_height?: unknown }
  const width = typeof bag.image_width === 'number' ? bag.image_width : null
  const height = typeof bag.image_height === 'number' ? bag.image_height : null
  return { width, height }
}

export function snapshotUrlOf(refs: unknown): string {
  if (!refs || typeof refs !== 'object') return ''
  const bag = refs as { snapshot_url?: unknown; snapshot_id?: unknown }
  if (typeof bag.snapshot_url === 'string') return bag.snapshot_url
  if (typeof bag.snapshot_id === 'string') return bag.snapshot_id
  return ''
}

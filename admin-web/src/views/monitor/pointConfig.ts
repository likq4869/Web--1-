// ===========================================================================
// 点位标定格式化 —— 归一化坐标校验、百分比换算、证据框映射
// 纯函数，无 I/O，便于单元测试与组件复用
// ===========================================================================

import type { OverlayBox } from '@/components/DetectionOverlay.vue'
import type { MonitorSnapshotEvidenceBox } from '@/api/monitor'

/** 归一化坐标钳制到 0~1（非数字回退 0） */
export function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(1, Math.max(0, value))
}

/** 归一化矩形转百分比样式（与容器同坐标系，横竖图不错位） */
export function rectToStyle(
  rect: readonly [number, number, number, number],
): Record<string, string> {
  const [x1, y1, x2, y2] = rect.map(clamp01)
  return {
    left: `${x1 * 100}%`,
    top: `${y1 * 100}%`,
    width: `${Math.max(0, x2 - x1) * 100}%`,
    height: `${Math.max(0, y2 - y1) * 100}%`,
  }
}

/** 计数线高度转百分比样式 */
export function lineToStyle(y: number): Record<string, string> {
  return { top: `${clamp01(y) * 100}%` }
}

/** 矩形合法性：四元 + 0~1 + x1<x2/y1<y2 + 最小边长 0.02（与后端 domain 同口径） */
export function rectError(rect: readonly number[], field = '选区'): string | null {
  if (!Array.isArray(rect) || rect.length !== 4) return `${field}必须为四元数组`
  if (!rect.every((item) => typeof item === 'number' && Number.isFinite(item))) {
    return `${field}必须为数字数组`
  }
  if (!rect.every((item) => item >= 0 && item <= 1)) return `${field}坐标必须在 0~1 范围内`
  const [x1, y1, x2, y2] = rect
  if (!(x1 < x2 && y1 < y2)) return `${field}必须满足 x1<x2 且 y1<y2`
  if (Math.min(x2 - x1, y2 - y1) < 0.02) return `${field}边长过小，请重新框选`
  return null
}

/** 计数线合法性 */
export function lineError(value: number): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '计数线必须为数字'
  if (value < 0 || value > 1) return '计数线必须在 0~1 范围内'
  return null
}

/** 归一化数值展示：保留 3 位小数（tabular 对齐） */
export function formatNorm(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return clamp01(value).toFixed(3)
}

/** 证据框映射为叠加层：xyxy → x/y/width/height，色调与 design.md §3.6 对齐 */
export function evidenceToOverlay(boxes: MonitorSnapshotEvidenceBox[]): OverlayBox[] {
  return boxes.slice(0, 12).map((box) => {
    const [x1, y1, x2, y2] = box.xyxy.map(clamp01)
    const label = box.label || '目标'
    let tone: OverlayBox['tone'] = 'warning'
    if (label.includes('no helmet') || label.includes('未佩戴')) tone = 'danger'
    else if (label.includes('helmet') || label.includes('佩戴')) tone = 'success'
    else if (label.includes('Cyclist') || label.includes('骑行')) tone = 'primary'
    return {
      x: x1,
      y: y1,
      width: Math.max(0.001, x2 - x1),
      height: Math.max(0.001, y2 - y1),
      label,
      confidence: typeof box.confidence === 'number' ? box.confidence : undefined,
      tone,
    }
  })
}

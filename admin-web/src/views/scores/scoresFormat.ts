// ===========================================================================
// 积分域格式化 —— 台账分值符号、规则类型标签、时间截取
// 纯函数，无 I/O，便于单元测试与组件复用
// ===========================================================================

/** 台账变动展示：正数补 + 号，零与负数原样 */
export function formatDelta(change: number): string {
  if (change > 0) return `+${change}`
  return `${change}`
}

/** 台账变动色调：加分绿 / 扣分红 / 零变动中性 */
export function deltaTone(change: number): 'success' | 'danger' | 'neutral' {
  if (change > 0) return 'success'
  if (change < 0) return 'danger'
  return 'neutral'
}

/** 规则类型标签 */
export function ruleTypeLabel(ruleType: string): string {
  const map: Record<string, string> = {
    deduct: '扣分',
    award: '加分',
    streak: '连续安全',
  }
  return map[ruleType] ?? ruleType
}

/** ISO 时间截取 HH:mm:ss，失败回退原串 */
export function formatTimeShort(value: string | null | undefined): string {
  if (!value) return '—'
  const matched = /T(\d{2}:\d{2}:\d{2})/.exec(value)
  if (matched) return matched[1]
  return value.slice(0, 19).replace('T', ' ')
}

/** 安全解析 JSON 文本，失败返回错误信息 */
export function parseJsonText(
  text: string,
): { ok: true; value: unknown } | { ok: false; error: string } {
  const trimmed = text.trim()
  if (trimmed === '') return { ok: true, value: null }
  try {
    return { ok: true, value: JSON.parse(trimmed) as unknown }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : 'JSON 格式不正确' }
  }
}

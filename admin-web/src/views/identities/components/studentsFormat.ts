export function maskPhone(value: string | null): string {
  if (value === null || value === '') return '—'
  if (value.length < 7) return value
  return `${value.slice(0, 3)}****${value.slice(-4)}`
}

export function formatDateTime(value: string | null): string {
  if (value === null || value === '') return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function formatConfidencePercent(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return `${(value * 100).toFixed(1)}%`
}

export function bindTypeLabel(value: string | null): string {
  const map: Record<string, string> = {
    registered: '登记',
    qr: '扫码',
    nfc: '刷卡',
    appearance: '外观',
    cooccur: '共现',
    manual: '人工',
  }
  if (value === null) return '—'
  return map[value] ?? value
}

export function identityMethodLabel(value: string | null): string {
  const map: Record<string, string> = {
    plate: '车牌',
    qr: '扫码',
    nfc: '刷卡',
    appearance: '外观',
    cooccur: '共现',
    manual: '人工',
    none: '未识别',
  }
  if (value === null) return '未知'
  return map[value] ?? value
}

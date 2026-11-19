// ===========================================================================
// 点位标定组合式逻辑 —— 数据加载、拖拽标定、校验保存
// 视图只做渲染，逻辑收敛于此，保证单文件 ≤400 行门禁
// ===========================================================================

import { computed, onMounted, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getMonitorConfig,
  getMonitorSnapshot,
  getMonitorStream,
  listMonitorPoints,
  updateMonitorConfig,
  type MonitorConfig,
  type MonitorPoint,
  type MonitorSnapshot,
  type MonitorSnapshotEvidence,
} from '@/api/monitor'
import type { OverlayBox } from '@/components/DetectionOverlay.vue'
import { ApiError } from '@/api/types'
import { evidenceToOverlay, lineError, rectError } from './pointConfig'

export type ConfigRect = [number, number, number, number]

/** usePointConfig 对外暴露的状态与动作（显式返回类型，满足门禁） */
export interface UsePointConfigResult {
  points: Ref<MonitorPoint[]>
  selectedPointId: Ref<string | null>
  evidence: ComputedRef<MonitorSnapshotEvidence | null>
  overlayBoxes: ComputedRef<OverlayBox[]>
  aspectRatio: ComputedRef<string>
  stageLabel: ComputedRef<string>
  streamReason: Ref<string>
  loading: Ref<boolean>
  loadError: Ref<string | null>
  hasData: ComputedRef<boolean>
  draftRoi: Ref<ConfigRect | null>
  draftZone: Ref<ConfigRect | null>
  draftLine: Ref<number>
  roiText: ComputedRef<string>
  zoneText: ComputedRef<string>
  updatedText: ComputedRef<string>
  formError: Ref<string | null>
  saveError: Ref<string | null>
  saving: Ref<boolean>
  canvasRef: Ref<HTMLElement | null>
  onHandleDown: (event: PointerEvent) => void
  onCanvasDown: (event: PointerEvent) => void
  onCanvasMove: (event: PointerEvent) => void
  onCanvasUp: () => void
  onRoiText: (value: string) => void
  onZoneText: (value: string) => void
  onLineNumber: (value: number | undefined) => void
  resetDraft: () => void
  onSave: () => Promise<void>
  reload: () => void
  onPointChange: (value: string | null) => void
}

export function usePointConfig(): UsePointConfigResult {
  const points = ref<MonitorPoint[]>([])
  const selectedPointId = ref<string | null>(null)
  const snapshot = ref<MonitorSnapshot | null>(null)
  const config = ref<MonitorConfig | null>(null)
  const streamReason = ref('')
  const loading = ref(false)
  const loadError = ref<string | null>(null)
  const saving = ref(false)
  const saveError = ref<string | null>(null)
  const formError = ref<string | null>(null)

  const draftRoi = ref<ConfigRect | null>(null)
  const draftZone = ref<ConfigRect | null>(null)
  const draftLine = ref(0.6)

  const canvasRef = ref<HTMLElement | null>(null)
  let dragMode: 'roi' | 'zone' | 'line' | 'create' | 'resize' | null = null
  let dragStart: {
    x: number
    y: number
    roi: ConfigRect | null
    zone: ConfigRect | null
    line: number
  } | null = null
  let fetchSeq = 0

  const hasData = computed(() => points.value.length > 0)
  const evidence = computed(() => snapshot.value?.evidence ?? null)
  const overlayBoxes = computed(() => evidenceToOverlay(evidence.value?.boxes ?? []))
  const aspectRatio = computed(() => {
    const w = evidence.value?.image_width
    const h = evidence.value?.image_height
    if (w && h && w > 0 && h > 0) return `${w} / ${h}`
    return '16 / 9'
  })
  const stageLabel = computed(() =>
    selectedPointId.value ? `点位 ${selectedPointId.value} 标定` : '点位标定',
  )
  const roiText = computed(() =>
    draftRoi.value ? draftRoi.value.map((v) => v.toFixed(3)).join(',') : '',
  )
  const zoneText = computed(() =>
    draftZone.value ? draftZone.value.map((v) => v.toFixed(3)).join(',') : '',
  )
  const updatedText = computed(() => {
    if (!config.value?.updated_at) return ''
    const by = config.value.updated_by ? ` · ${config.value.updated_by}` : ''
    return `上次保存 ${config.value.updated_at}${by}`
  })

  function toNorm(event: PointerEvent): { x: number; y: number } {
    const el = canvasRef.value
    if (!el) return { x: 0, y: 0 }
    const rect = el.getBoundingClientRect()
    return {
      x: Math.min(1, Math.max(0, (event.clientX - rect.left) / Math.max(1, rect.width))),
      y: Math.min(1, Math.max(0, (event.clientY - rect.top) / Math.max(1, rect.height))),
    }
  }

  function inside(rect: ConfigRect | null, x: number, y: number): boolean {
    if (!rect) return false
    return x >= rect[0] && x <= rect[2] && y >= rect[1] && y <= rect[3]
  }

  function nearLine(y: number): boolean {
    const el = canvasRef.value
    if (!el) return Math.abs(y - draftLine.value) < 0.03
    const rect = el.getBoundingClientRect()
    return Math.abs((y - draftLine.value) * rect.height) < 10
  }

  function snapshotDrag(p: { x: number; y: number }): void {
    dragStart = {
      x: p.x,
      y: p.y,
      roi: draftRoi.value ? ([...draftRoi.value] as ConfigRect) : null,
      zone: draftZone.value ? ([...draftZone.value] as ConfigRect) : null,
      line: draftLine.value,
    }
  }

  function onHandleDown(event: PointerEvent): void {
    dragMode = 'resize'
    snapshotDrag(toNorm(event))
    ;(event.target as HTMLElement).setPointerCapture?.(event.pointerId)
  }

  function onCanvasDown(event: PointerEvent): void {
    if (!(event.target instanceof HTMLElement)) return
    if (event.target.classList.contains('hg-config__handle')) return
    const p = toNorm(event)
    if (nearLine(p.y)) dragMode = 'line'
    else if (inside(draftRoi.value, p.x, p.y)) dragMode = 'roi'
    else if (inside(draftZone.value, p.x, p.y)) dragMode = 'zone'
    else dragMode = 'create'
    snapshotDrag(p)
  }

  function moveRect(origin: ConfigRect, dx: number, dy: number): ConfigRect {
    const [x1, y1, x2, y2] = origin
    const w = x2 - x1
    const h = y2 - y1
    const nx = Math.min(1 - w, Math.max(0, x1 + dx))
    const ny = Math.min(1 - h, Math.max(0, y1 + dy))
    return [nx, ny, nx + w, ny + h]
  }

  function onCanvasMove(event: PointerEvent): void {
    if (!dragMode || !dragStart) return
    const p = toNorm(event)
    const dx = p.x - dragStart.x
    const dy = p.y - dragStart.y
    if (dragMode === 'line') {
      draftLine.value = Math.min(1, Math.max(0, dragStart.line + dy))
    } else if (dragMode === 'roi' && dragStart.roi) {
      draftRoi.value = moveRect(dragStart.roi, dx, dy)
    } else if (dragMode === 'zone' && dragStart.zone) {
      draftZone.value = moveRect(dragStart.zone, dx, dy)
    } else if (dragMode === 'resize' && dragStart.roi) {
      const [x1, y1] = dragStart.roi
      draftRoi.value = [
        x1,
        y1,
        Math.min(1, Math.max(x1 + 0.02, p.x)),
        Math.min(1, Math.max(y1 + 0.02, p.y)),
      ]
    } else if (dragMode === 'create') {
      draftRoi.value = [
        Math.min(dragStart.x, p.x),
        Math.min(dragStart.y, p.y),
        Math.max(dragStart.x, p.x),
        Math.max(dragStart.y, p.y),
      ]
    }
    formError.value = null
  }

  function onCanvasUp(): void {
    dragMode = null
    dragStart = null
  }

  function parseRectText(text: string): ConfigRect | null {
    const parts = text.split(',').map((s) => Number(s.trim()))
    if (parts.length !== 4 || parts.some((v) => !Number.isFinite(v))) return null
    return [parts[0], parts[1], parts[2], parts[3]] as ConfigRect
  }

  function onRoiText(value: string): void {
    const parsed = parseRectText(value)
    if (parsed) {
      draftRoi.value = parsed
      formError.value = null
    }
  }

  function onZoneText(value: string): void {
    const parsed = parseRectText(value)
    if (parsed) {
      draftZone.value = parsed
      formError.value = null
    }
  }

  function onLineNumber(value: number | undefined): void {
    if (typeof value === 'number') draftLine.value = value
  }

  function resetDraft(): void {
    if (!config.value) return
    draftRoi.value = [...config.value.roi]
    draftZone.value = [...config.value.alert_zone]
    draftLine.value = config.value.count_line_y
    formError.value = null
    saveError.value = null
  }

  function validate(): boolean {
    if (!draftRoi.value || !draftZone.value) {
      formError.value = '请先框选检测区与提醒区'
      return false
    }
    const roiErr = rectError(draftRoi.value, '检测区')
    if (roiErr) {
      formError.value = roiErr
      return false
    }
    const zoneErr = rectError(draftZone.value, '提醒区')
    if (zoneErr) {
      formError.value = zoneErr
      return false
    }
    const lineErr = lineError(draftLine.value)
    if (lineErr) {
      formError.value = lineErr
      return false
    }
    formError.value = null
    return true
  }

  async function onSave(): Promise<void> {
    if (!selectedPointId.value || !draftRoi.value || !draftZone.value) return
    if (!validate()) return
    saving.value = true
    saveError.value = null
    try {
      const saved = await updateMonitorConfig(selectedPointId.value, {
        roi: draftRoi.value,
        count_line_y: draftLine.value,
        alert_zone: draftZone.value,
      })
      config.value = saved
      ElMessage.success('标定已保存')
    } catch (error) {
      saveError.value = error instanceof ApiError ? error.message : '标定保存失败'
    } finally {
      saving.value = false
    }
  }

  async function fetchAll(): Promise<void> {
    const seq = (fetchSeq += 1)
    loading.value = true
    loadError.value = null
    try {
      const list = await listMonitorPoints()
      if (seq !== fetchSeq) return
      points.value = list.items
      if (
        !selectedPointId.value ||
        !points.value.some((p) => p.source_id === selectedPointId.value)
      ) {
        selectedPointId.value = points.value[0]?.source_id ?? null
      }
      if (!selectedPointId.value) return
      const [snap, stream, cfg] = await Promise.all([
        getMonitorSnapshot(selectedPointId.value),
        getMonitorStream(selectedPointId.value),
        getMonitorConfig(selectedPointId.value),
      ])
      if (seq !== fetchSeq) return
      snapshot.value = snap
      streamReason.value = stream.reason
      config.value = cfg
      draftRoi.value = [...cfg.roi]
      draftZone.value = [...cfg.alert_zone]
      draftLine.value = cfg.count_line_y
    } catch (error) {
      if (seq !== fetchSeq) return
      loadError.value = error instanceof ApiError ? error.message : '点位标定加载失败'
    } finally {
      if (seq === fetchSeq) loading.value = false
    }
  }

  function reload(): void {
    void fetchAll()
  }

  function onPointChange(value: string | null): void {
    selectedPointId.value = value ?? null
    void fetchAll()
  }

  onMounted(() => {
    void fetchAll()
  })

  return {
    points,
    selectedPointId,
    evidence,
    overlayBoxes,
    aspectRatio,
    stageLabel,
    streamReason,
    loading,
    loadError,
    hasData,
    draftRoi,
    draftZone,
    draftLine,
    roiText,
    zoneText,
    updatedText,
    formError,
    saveError,
    saving,
    canvasRef,
    onHandleDown,
    onCanvasDown,
    onCanvasMove,
    onCanvasUp,
    onRoiText,
    onZoneText,
    onLineNumber,
    resetDraft,
    onSave,
    reload,
    onPointChange,
  }
}

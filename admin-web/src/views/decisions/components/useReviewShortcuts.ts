import { onBeforeUnmount, onMounted } from 'vue'
import type { Ref } from 'vue'

export interface ShortcutHint {
  keys: string
  desc: string
}

export const REVIEW_SHORTCUT_HINTS: ShortcutHint[] = [
  { keys: 'J / ↓', desc: '下一条' },
  { keys: 'K / ↑', desc: '上一条' },
  { keys: 'Enter', desc: '批准' },
  { keys: 'X', desc: '驳回' },
  { keys: 'D', desc: '降档' },
  { keys: '/', desc: '聚焦搜索' },
]

interface ReviewShortcutOptions {
  focusSearch: () => void
  canApprove: Ref<boolean> | { value: boolean }
  onMove: (delta: 1 | -1) => void
  onApprove: () => void
  onOpenReject: () => void
  onOpenAdjust: () => void
}

/** 输入框聚焦时禁用快捷键（避免与文本输入冲突） */
function isEditing(): boolean {
  const active = document.activeElement
  if (!active) return false
  const tag = active.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || (active as HTMLElement).isContentEditable === true
}

/**
 * 审批快捷键（J/K 移动、Enter 批准、X 驳回、D 降档、/ 聚焦搜索）。
 * 挂载时注册全局 keydown，卸载时移除。
 */
export function useReviewShortcuts(options: ReviewShortcutOptions): void {
  function onKeydown(event: KeyboardEvent): void {
    if (isEditing()) return
    const key = event.key

    if (key === 'j' || key === 'J' || key === 'ArrowDown') {
      event.preventDefault()
      options.onMove(1)
      return
    }
    if (key === 'k' || key === 'K' || key === 'ArrowUp') {
      event.preventDefault()
      options.onMove(-1)
      return
    }
    if (key === '/') {
      event.preventDefault()
      options.focusSearch()
      return
    }
    if (key === 'Enter') {
      if (!options.canApprove.value) return
      event.preventDefault()
      options.onApprove()
      return
    }
    if (key === 'x' || key === 'X') {
      if (!options.canApprove.value) return
      event.preventDefault()
      options.onOpenReject()
      return
    }
    if (key === 'd' || key === 'D') {
      if (!options.canApprove.value) return
      event.preventDefault()
      options.onOpenAdjust()
    }
  }

  onMounted(() => {
    window.addEventListener('keydown', onKeydown)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('keydown', onKeydown)
  })
}

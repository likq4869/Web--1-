// ===========================================================================
// 审批中心状态 —— 决策队列、详情、乐观更新与回滚
//
// 乐观更新语义：
//   1. 操作前先记住决策行的快照
//   2. 立即在本地把该行从待审队列移除（UI 响应零延迟）
//   3. 请求失败 → 用快照恢复，并把行放回原位置
//   4. 请求成功 → 以服务端返回的详情覆盖本地行
// ===========================================================================

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as decisionsApi from '@/api/decisions'
import type {
  DecisionDetail,
  DecisionListItem,
  DecisionLevel,
  DecisionQuery,
} from '@/api/decisions'

/** 新到达决策的高亮时长（毫秒） */
const FLASH_DURATION = 1200

export const useDecisionsStore = defineStore(
  'decisions',
  () => {
    // ---------- 队列 ----------
    const items = ref<DecisionListItem[]>([])
    const total = ref(0)
    const page = ref(1)
    const pageSize = ref(20)
    const loading = ref(false)
    const error = ref<string | null>(null)
    const pendingCount = ref(0)

    // ---------- 详情 ----------
    const detail = ref<DecisionDetail | null>(null)
    const detailLoading = ref(false)
    const detailError = ref<string | null>(null)

    // ---------- 筛选 ----------
    const filters = ref<DecisionQuery>({
      status: 'PENDING_REVIEW',
      level: '',
      point_id: '',
      student_id: '',
      min_confidence: null,
      sort: 'created_at/desc',
    })

    // ---------- 选中 ----------
    const selectedId = ref<string | null>(null)
    const selectedIndex = ref(0)

    // ---------- 操作中 ----------
    const acting = ref(false)
    const batchActing = ref(false)
    const batchResult = ref<decisionsApi.BatchApproveResult | null>(null)

    // ---------- 新到达高亮 ----------
    const flashIds = ref<string[]>([])

    const selectedItem = computed(
      () => items.value.find((item) => item.decision_id === selectedId.value) ?? null,
    )

    const hasItems = computed(() => items.value.length > 0)

    // ------------------------------------------------------------------
    // 队列加载
    // ------------------------------------------------------------------

    async function loadItems(): Promise<void> {
      loading.value = true
      error.value = null
      try {
        const result = await decisionsApi.listDecisions({
          ...filters.value,
          page: page.value,
          page_size: pageSize.value,
        })
        items.value = result.items
        total.value = result.total
        // 选中项失效（已处理或换页）时，自动落到第一条。
        if (!items.value.some((item) => item.decision_id === selectedId.value)) {
          selectedIndex.value = 0
          selectedId.value = items.value[0]?.decision_id ?? null
        }
      } catch (err) {
        error.value = err instanceof Error ? err.message : '决策列表加载失败'
      } finally {
        loading.value = false
      }
    }

    async function loadPendingCount(): Promise<void> {
      try {
        const result = await decisionsApi.getPendingCount()
        pendingCount.value = result.pending
      } catch {
        // 计数失败不阻断页面（顶部徽标可保留旧值）。
      }
    }

    // ------------------------------------------------------------------
    // 详情
    // ------------------------------------------------------------------

    async function loadDetail(decisionId: string): Promise<void> {
      detailLoading.value = true
      detailError.value = null
      try {
        detail.value = await decisionsApi.getDecisionDetail(decisionId)
      } catch (err) {
        detailError.value = err instanceof Error ? err.message : '决策详情加载失败'
        detail.value = null
      } finally {
        detailLoading.value = false
      }
    }

    function selectById(decisionId: string): void {
      selectedId.value = decisionId
      const index = items.value.findIndex((item) => item.decision_id === decisionId)
      if (index >= 0) selectedIndex.value = index
      void loadDetail(decisionId)
    }

    function selectByIndex(index: number): void {
      const item = items.value[index]
      if (!item) return
      selectedIndex.value = index
      selectedId.value = item.decision_id
      void loadDetail(item.decision_id)
    }

    function moveSelection(delta: number): void {
      if (items.value.length === 0) return
      const next = Math.min(Math.max(selectedIndex.value + delta, 0), items.value.length - 1)
      if (next === selectedIndex.value) return
      selectByIndex(next)
    }

    // ------------------------------------------------------------------
    // 乐观更新
    // ------------------------------------------------------------------

    /**
     * 从队列移除某行（返回快照用于回滚）。
     *
     * @param decisionId 决策 ID
     * @returns 原始行与索引；不存在时返回 null
     */
    function detachItem(decisionId: string): { item: DecisionListItem; index: number } | null {
      const index = items.value.findIndex((item) => item.decision_id === decisionId)
      if (index < 0) return null
      const item = items.value[index]
      items.value = items.value.filter((row) => row.decision_id !== decisionId)
      total.value = Math.max(0, total.value - 1)
      pendingCount.value = Math.max(0, pendingCount.value - 1)
      return { item, index }
    }

    /** 恢复被移除的行（失败回滚）。 */
    function restoreItem(snapshot: { item: DecisionListItem; index: number }): void {
      if (items.value.some((row) => row.decision_id === snapshot.item.decision_id)) return
      const next = [...items.value]
      next.splice(Math.min(snapshot.index, next.length), 0, snapshot.item)
      items.value = next
      total.value += 1
      pendingCount.value += 1
    }

    // ------------------------------------------------------------------
    // 审批动作
    // ------------------------------------------------------------------

    async function approve(
      decisionId: string,
      level?: DecisionLevel,
      note?: string,
    ): Promise<boolean> {
      acting.value = true
      const snapshot = detachItem(decisionId)
      try {
        const updated = await decisionsApi.approveDecision(decisionId, { level, note })
        if (detail.value?.decision_id === decisionId) {
          detail.value = { ...detail.value, ...updated }
        }
        return true
      } catch (err) {
        // 失败回滚：把行放回队列原位置。
        if (snapshot) restoreItem(snapshot)
        throw err
      } finally {
        acting.value = false
        if (snapshot) {
          // 队列已变化：重新落到合法位置。
          if (!items.value.some((row) => row.decision_id === selectedId.value)) {
            selectedIndex.value = Math.min(selectedIndex.value, Math.max(0, items.value.length - 1))
            selectedId.value = items.value[selectedIndex.value]?.decision_id ?? null
          }
        }
      }
    }

    async function reject(decisionId: string, reason: string): Promise<boolean> {
      acting.value = true
      const snapshot = detachItem(decisionId)
      try {
        const updated = await decisionsApi.rejectDecision(decisionId, reason)
        if (detail.value?.decision_id === decisionId) {
          detail.value = { ...detail.value, ...updated }
        }
        return true
      } catch (err) {
        if (snapshot) restoreItem(snapshot)
        throw err
      } finally {
        acting.value = false
        if (snapshot) {
          if (!items.value.some((row) => row.decision_id === selectedId.value)) {
            selectedIndex.value = Math.min(selectedIndex.value, Math.max(0, items.value.length - 1))
            selectedId.value = items.value[selectedIndex.value]?.decision_id ?? null
          }
        }
      }
    }

    async function batchApprove(
      decisionIds: string[],
      note?: string,
    ): Promise<decisionsApi.BatchApproveResult> {
      batchActing.value = true
      try {
        const result = await decisionsApi.batchApprove(decisionIds, note)
        batchResult.value = result
        // 成功的条目从队列移除；失败的保留。
        const succeeded = new Set(
          result.items.filter((item) => item.ok).map((item) => item.decision_id),
        )
        items.value = items.value.filter((row) => !succeeded.has(row.decision_id))
        total.value = Math.max(0, total.value - succeeded.size)
        pendingCount.value = Math.max(0, pendingCount.value - succeeded.size)
        await loadPendingCount()
        return result
      } finally {
        batchActing.value = false
      }
    }

    function clearBatchResult(): void {
      batchResult.value = null
    }

    // ------------------------------------------------------------------
    // 实时插入
    // ------------------------------------------------------------------

    /**
     * 把新到达的决策插到队列顶部并高亮闪烁。
     *
     * @param item 新决策
     */
    function insertIncoming(item: DecisionListItem): void {
      if (items.value.some((row) => row.decision_id === item.decision_id)) return
      items.value = [item, ...items.value]
      total.value += 1
      pendingCount.value += 1
      flashIds.value = [...flashIds.value, item.decision_id]
      window.setTimeout(() => {
        flashIds.value = flashIds.value.filter((id) => id !== item.decision_id)
      }, FLASH_DURATION)
    }

    function isFlashing(decisionId: string): boolean {
      return flashIds.value.includes(decisionId)
    }

    // ------------------------------------------------------------------
    // 筛选
    // ------------------------------------------------------------------

    async function applyFilters(next: Partial<DecisionQuery>): Promise<void> {
      filters.value = { ...filters.value, ...next }
      page.value = 1
      await loadItems()
    }

    async function resetFilters(): Promise<void> {
      filters.value = {
        status: 'PENDING_REVIEW',
        level: '',
        point_id: '',
        student_id: '',
        min_confidence: null,
        sort: 'created_at/desc',
      }
      page.value = 1
      await loadItems()
    }

    // ---------- 持久化 ----------
    // 只持久化「用户偏好」与「可离线复用的数据快照」，不持久化瞬时状态：
    //   持久化：筛选条件、分页、选中项、队列快照、批量选择
    //   不持久化：loading / error / acting 等瞬时态、详情对象（刷新后重新拉取）
    return {
      items,
      total,
      page,
      pageSize,
      loading,
      error,
      pendingCount,
      detail,
      detailLoading,
      detailError,
      filters,
      selectedId,
      selectedIndex,
      selectedItem,
      hasItems,
      acting,
      batchActing,
      batchResult,
      loadItems,
      loadPendingCount,
      loadDetail,
      selectById,
      selectByIndex,
      moveSelection,
      approve,
      reject,
      batchApprove,
      clearBatchResult,
      insertIncoming,
      isFlashing,
      applyFilters,
      resetFilters,
    }
  },
  {
    persist: {
      key: 'hg.decisions',
      storage: localStorage,
      // 仅持久化筛选与分页偏好；队列数据每次进入页面重新拉取，
      // 避免展示过期的待审列表（可能已被他人处理）。
      pick: ['filters', 'page', 'pageSize'],
    },
  },
)

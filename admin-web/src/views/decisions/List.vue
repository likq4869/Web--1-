<template>
  <div class="hg-review">
    <ReviewShortcuts
      :collapsed="shortcutsCollapsed"
      :hints="REVIEW_SHORTCUT_HINTS"
      @toggle="shortcutsCollapsed = !shortcutsCollapsed"
    />

    <div class="hg-review__body">
      <aside class="hg-review__queue">
        <ReviewFilters
          ref="filtersRef"
          :keyword="keyword"
          :level-filter="levelFilter"
          :point-filter="pointFilter"
          :sort-by="sortBy"
          :point-options="pointOptions"
          :level-tabs="levelTabs"
          @update:keyword="keyword = $event"
          @update:point-filter="pointFilter = $event"
          @update:sort-by="sortBy = $event"
          @submit-filters="submitFilters"
          @submit-search="submitSearch"
          @set-level="setLevel"
        />
        <ReviewQueue
          :items="store.items"
          :loading="store.loading"
          :error="store.error"
          :selected-id="store.selectedId"
          :has-active-filters="hasActiveFilters"
          :empty-title="emptyTitle"
          :empty-description="emptyDescription"
          :student-name-of="studentNameOf"
          :is-flashing="store.isFlashing"
          @select="store.selectById"
          @retry="reload"
          @clear-filters="clearFilters"
        />
      </aside>

      <ReviewDetail
        :detail="detail"
        :detail-loading="store.detailLoading"
        :detail-error="store.detailError"
        :detail-title="detailTitle"
        :evidence-boxes="evidenceBoxes"
        :evidence-size="evidenceSize"
        :snapshot-url="snapshotUrl"
        :factors="factors"
        :editable-message="editableMessage"
        :can-approve="canApprove"
        :acting="store.acting"
        :selected-id="store.selectedId"
        :adjust-disabled="adjustOptions.length === 0"
        :batch-count="selectedIds.length"
        :batch-result="store.batchResult"
        :batch-success="batchSuccessCount"
        :batch-fail="batchFailCount"
        :batch-failures="batchFailures"
        @retry="reloadDetail"
        @update:message="editableMessage = $event"
        @approve="onApprove"
        @open-adjust="openAdjust"
        @open-reject="rejectDialogVisible = true"
        @open-batch="batchDialogVisible = true"
        @clear-batch="store.clearBatchResult()"
      />
    </div>

    <ReviewDialogs
      :adjust-visible="adjustDialogVisible"
      :reject-visible="rejectDialogVisible"
      :batch-visible="batchDialogVisible"
      :detail-level="detail?.level ?? '—'"
      :adjust-options="adjustOptions"
      :target-level="targetLevel"
      :adjust-note="adjustNote"
      :reject-reason="rejectReason"
      :batch-note="batchNote"
      :selected-count="selectedIds.length"
      :acting="store.acting"
      :batch-acting="store.batchActing"
      @update:adjust-visible="adjustDialogVisible = $event"
      @update:reject-visible="rejectDialogVisible = $event"
      @update:batch-visible="batchDialogVisible = $event"
      @update:target-level="targetLevel = $event"
      @update:adjust-note="adjustNote = $event"
      @update:reject-reason="rejectReason = $event"
      @update:batch-note="batchNote = $event"
      @confirm-adjust="onAdjust"
      @confirm-reject="onReject"
      @confirm-batch="onBatchApprove"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import ReviewDetail from './components/ReviewDetail.vue'
import ReviewDialogs from './components/ReviewDialogs.vue'
import ReviewFilters from './components/ReviewFilters.vue'
import ReviewQueue from './components/ReviewQueue.vue'
import ReviewShortcuts from './components/ReviewShortcuts.vue'
import { REVIEW_SHORTCUT_HINTS, useReviewShortcuts } from './components/useReviewShortcuts'
import {
  LEVEL_LABELS,
  LEVEL_SCORES,
  evidenceSizeOf,
  snapshotUrlOf,
  studentNameOf as studentNameOfRaw,
  toEvidenceBoxes,
  toFactors,
} from './components/reviewFormat'
import { useAuthStore } from '@/stores/auth'
import { useDecisionsStore } from '@/stores/decisions'
import type { DecisionLevel, DecisionListItem } from '@/api/decisions'

const store = useDecisionsStore()
const auth = useAuthStore()

const keyword = ref('')
const levelFilter = ref<DecisionLevel | ''>('')
const pointFilter = ref('')
const sortBy = ref<'created_at/desc' | 'confidence/desc' | 'level/asc'>('created_at/desc')
const shortcutsCollapsed = ref(false)

const adjustDialogVisible = ref(false)
const rejectDialogVisible = ref(false)
const batchDialogVisible = ref(false)
const targetLevel = ref<DecisionLevel>('L2')
const adjustNote = ref('')
const rejectReason = ref('')
const batchNote = ref('')
const selectedIds = ref<string[]>([])
const editableMessage = ref('')

const filtersRef = ref<{ focusSearch: () => void } | null>(null)

const levelTabs = computed(() => [
  { value: '' as const, label: '全部' },
  { value: 'L1' as const, label: 'L1' },
  { value: 'L2' as const, label: 'L2' },
  { value: 'L3' as const, label: 'L3' },
])

const pointOptions = computed<{ value: string; label: string }[]>(() => [])

const detail = computed(() => store.detail)
const hasActiveFilters = computed(
  () =>
    levelFilter.value !== '' ||
    pointFilter.value !== '' ||
    keyword.value.trim() !== '' ||
    store.filters.min_confidence !== null,
)

const detailTitle = computed(() => {
  if (!detail.value) return ''
  const student = detail.value.student
  const point = detail.value.event?.source_id ?? '未知点位'
  if (student) return `${student.name} · ${point}`
  return `${point} · 身份待确认`
})

const factors = computed(() => toFactors(detail.value?.factors))
const evidenceBoxes = computed(() => toEvidenceBoxes(detail.value?.evidence_refs))
const evidenceSize = computed(() => evidenceSizeOf(detail.value?.evidence_refs))
const snapshotUrl = computed(() => snapshotUrlOf(detail.value?.evidence_refs))

const adjustOptions = computed(() => {
  const current = detail.value?.level ?? 'L3'
  const order: DecisionLevel[] = ['L0', 'L1', 'L2', 'L3', 'L4']
  const currentIndex = order.indexOf(current)
  return order
    .slice(0, Math.max(0, currentIndex))
    .reverse()
    .map((level) => ({
      level,
      label: LEVEL_LABELS[level] ?? level,
      scoreDelta: LEVEL_SCORES[level] ?? 0,
    }))
})

const batchSuccessCount = computed(
  () => store.batchResult?.items.filter((item) => item.ok).length ?? 0,
)
const batchFailCount = computed(
  () => store.batchResult?.items.filter((item) => !item.ok).length ?? 0,
)
const batchFailures = computed(() => store.batchResult?.items.filter((item) => !item.ok) ?? [])

const canApprove = computed(() => {
  const role = auth.role
  if (!role) return false
  return ['super_admin', 'admin', 'reviewer', 'league_officer'].includes(role)
})

const emptyTitle = computed(() => (hasActiveFilters.value ? '没有符合条件的决策' : '全部处理完毕'))
const emptyDescription = computed(() => {
  if (hasActiveFilters.value) return '当前筛选条件下没有待审决策，可清除筛选查看全部。'
  const total = store.total
  return total > 0 ? `当前没有待审批决策 · 今日已处理 ${total} 条。` : '当前没有待审批决策。'
})

function studentNameOf(item: DecisionListItem): string {
  return studentNameOfRaw(item.student_id)
}

function setLevel(level: DecisionLevel | ''): void {
  levelFilter.value = level
  submitFilters()
}

function submitFilters(): void {
  void store.applyFilters({
    level: levelFilter.value,
    point_id: pointFilter.value,
    sort: sortBy.value,
  })
}

function submitSearch(): void {
  void store.applyFilters({ student_id: keyword.value.trim() })
}

function clearFilters(): void {
  keyword.value = ''
  levelFilter.value = ''
  pointFilter.value = ''
  sortBy.value = 'created_at/desc'
  void store.resetFilters()
}

async function reload(): Promise<void> {
  await store.loadItems()
  await store.loadPendingCount()
}

async function reloadDetail(): Promise<void> {
  if (store.selectedId) await store.loadDetail(store.selectedId)
}

async function onApprove(): Promise<void> {
  if (!store.selectedId) return
  try {
    await store.approve(store.selectedId)
    ElMessage.success('已批准')
    await reload()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '批准失败，已回滚')
  }
}

function openAdjust(): void {
  const first = adjustOptions.value[0]
  if (first) targetLevel.value = first.level
  adjustDialogVisible.value = true
}

async function onAdjust(): Promise<void> {
  if (!store.selectedId || !targetLevel.value) return
  try {
    await store.approve(store.selectedId, targetLevel.value, adjustNote.value.trim())
    adjustDialogVisible.value = false
    adjustNote.value = ''
    ElMessage.success(`已降档至 ${targetLevel.value}`)
    await reload()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '降档失败，已回滚')
  }
}

async function onReject(): Promise<void> {
  if (!store.selectedId) return
  if (rejectReason.value.trim().length < 10) return
  try {
    await store.reject(store.selectedId, rejectReason.value.trim())
    rejectDialogVisible.value = false
    rejectReason.value = ''
    ElMessage.success('已驳回并回流训练集')
    await reload()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '驳回失败，已回滚')
  }
}

async function onBatchApprove(): Promise<void> {
  if (selectedIds.value.length === 0) return
  try {
    await store.batchApprove(selectedIds.value, batchNote.value.trim())
    batchDialogVisible.value = false
    batchNote.value = ''
    selectedIds.value = []
    await reload()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '批量批准失败')
  }
}

useReviewShortcuts({
  focusSearch: () => filtersRef.value?.focusSearch(),
  canApprove,
  onMove: (delta) => store.moveSelection(delta),
  onApprove: () => void onApprove(),
  onOpenReject: () => {
    rejectDialogVisible.value = true
  },
  onOpenAdjust: () => openAdjust(),
})

watch(
  () => store.selectedId,
  async (id) => {
    if (!id) {
      editableMessage.value = ''
      return
    }
    await store.loadDetail(id)
    editableMessage.value = store.detail?.message ?? ''
  },
)

onMounted(async () => {
  await reload()
  if (store.selectedId) {
    await store.loadDetail(store.selectedId)
    editableMessage.value = store.detail?.message ?? ''
  }
})
</script>

<style scoped lang="scss" src="./_styles/list.scss"></style>

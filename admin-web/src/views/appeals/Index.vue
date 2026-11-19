<template>
  <div>
    <PageHeader title="申诉处理" description="学生申诉复核，成立将撤销处罚并返还积分" />

    <div class="hg-appeals__filters">
      <ElInput
        :model-value="keyword"
        placeholder="按学号 / 申诉 / 决策筛选"
        clearable
        class="hg-appeals__search"
        @update:model-value="onKeywordInput"
        @clear="onKeywordClear"
      />
      <ElSelect
        :model-value="status"
        placeholder="处理状态"
        clearable
        class="hg-appeals__select"
        @update:model-value="onStatusChange"
      >
        <ElOption label="待处理" value="pending" />
        <ElOption label="申诉成立" value="upheld" />
        <ElOption label="申诉驳回" value="rejected" />
      </ElSelect>
      <div class="hg-appeals__actions">
        <ElButton :loading="loading" @click="reload">刷新</ElButton>
      </div>
    </div>

    <DataTable
      :rows="rows"
      :loading="loading"
      :error="loadError"
      :total="total"
      :current-page="page"
      :page-size="pageSize"
      :on-retry="reload"
      row-key="appeal_id"
      empty-title="暂无申诉"
      empty-description="当前筛选下没有待处理的申诉记录。"
      @update:current-page="onPageChange"
      @update:page-size="onSizeChange"
    >
      <ElTableColumn prop="appeal_id" label="申诉编号" min-width="170">
        <template #default="{ row }">
          <span class="tabular">{{ (row as AppealListItem).appeal_id }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="student_id" label="学号" min-width="120">
        <template #default="{ row }">
          <span class="tabular">{{ (row as AppealListItem).student_id }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="decision_id" label="关联决策" min-width="170">
        <template #default="{ row }">
          <span class="tabular">{{ (row as AppealListItem).decision_id }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="reason" label="申诉理由" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ (row as AppealListItem).reason }}</template>
      </ElTableColumn>
      <ElTableColumn label="状态" width="100">
        <template #default="{ row }">
          <ElTag :type="appealStatusBadge((row as AppealListItem).status)" size="small">
            {{ appealStatusLabel((row as AppealListItem).status) }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="附件" width="80">
        <template #default="{ row }">
          <span class="tabular">{{ attachmentCount(row as AppealListItem) }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作" width="110" fixed="right">
        <template #default="{ row }">
          <ElButton link type="primary" @click="openDetail(row as AppealListItem)"> 处理 </ElButton>
        </template>
      </ElTableColumn>
    </DataTable>

    <ElDrawer v-model="drawerOpen" title="申诉处理" size="720px" destroy-on-close>
      <div v-if="active" class="hg-appeals__layout">
        <div>
          <h3 class="hg-appeals__section-title">证据帧</h3>
          <div v-if="detailLoading" aria-busy="true">证据加载中…</div>
          <p v-else-if="detailError" role="alert">{{ detailError }}</p>
          <template v-else>
            <EvidenceViewer
              :image-url="snapshotUrl"
              :boxes="evidenceBoxes"
              :image-width="evidenceSize.width"
              :image-height="evidenceSize.height"
              alt="申诉关联证据帧"
            />
            <p v-if="!hasEvidence" class="hg-appeals__empty-hint">
              证据图不可用（可能已过 90 天保留期），请结合决策因子裁决。
            </p>
            <dl v-if="decision" class="hg-appeals__kv">
              <p class="hg-appeals__kv-row">
                <span>决策档位</span>
                <span class="tabular">{{ decision.level }} · {{ decision.action }}</span>
              </p>
              <p class="hg-appeals__kv-row">
                <span>分值变动</span>
                <span class="tabular">{{ decision.score_delta }} 分</span>
              </p>
              <p class="hg-appeals__kv-row">
                <span>决策状态</span>
                <span>{{ decision.status }}</span>
              </p>
            </dl>
          </template>
        </div>
        <div>
          <h3 class="hg-appeals__section-title">申诉理由</h3>
          <p class="hg-appeals__reason">{{ active.reason }}</p>
          <dl class="hg-appeals__kv">
            <p class="hg-appeals__kv-row">
              <span>提交时间</span>
              <span class="tabular">{{ formatAppealDateTime(active.created_at) }}</span>
            </p>
            <p class="hg-appeals__kv-row">
              <span>附件</span>
              <span class="tabular">{{ attachmentCount(active) }} 个</span>
            </p>
            <p class="hg-appeals__kv-row">
              <span>处理人</span>
              <span>{{ handlerLabel(active) }}</span>
            </p>
          </dl>
          <ul v-if="attachmentNames(active).length" class="hg-appeals__kv">
            <li v-for="name in attachmentNames(active)" :key="name" class="hg-appeals__kv-row">
              <span>{{ name }}</span>
            </li>
          </ul>
          <template v-if="!isAppealResolved(active.status)">
            <h3 class="hg-appeals__section-title">裁决</h3>
            <ElRadioGroup v-model="upheld" class="hg-appeals__kv">
              <ElRadio :value="true">成立（撤销处罚并返还积分）</ElRadio>
              <ElRadio :value="false">驳回（维持原决策）</ElRadio>
            </ElRadioGroup>
            <p v-if="upheld && decision" class="hg-appeals__warn" role="note">
              将撤销处罚并返还积分
              {{ Math.abs(decision.score_delta) }} 分，决策记为申诉成立并回流训练样本。
            </p>
            <ElInput
              ref="noteRef"
              v-model="note"
              type="textarea"
              :rows="3"
              maxlength="500"
              show-word-limit
              placeholder="处理意见（必填，将写入审批轨迹）"
            />
            <p v-if="resolveError" class="hg-appeals__error" role="alert">{{ resolveError }}</p>
            <p class="hg-appeals__actions">
              <ElButton type="primary" :loading="resolving" @click="onResolve(true)">
                确认成立
              </ElButton>
              <ElButton type="danger" plain :loading="resolving" @click="onResolve(false)">
                确认驳回
              </ElButton>
            </p>
          </template>
          <p v-else class="hg-appeals__empty-hint">
            该申诉已裁决（{{ appealStatusLabel(active.status) }}），处理意见：{{
              active.handle_note ?? '—'
            }}
          </p>
        </div>
      </div>
    </ElDrawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElButton,
  ElDrawer,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElRadio,
  ElRadioGroup,
  ElSelect,
  ElTableColumn,
  ElTag,
} from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import DataTable from '@/components/DataTable.vue'
import EvidenceViewer, { type EvidenceBox } from '@/components/EvidenceViewer.vue'
import { getDecisionDetail, type DecisionDetail } from '@/api/decisions'
import { listAppeals, resolveAppeal, type AppealListItem, type AppealStatus } from '@/api/appeals'
import { ApiError } from '@/api/types'
import {
  evidenceSizeOf,
  snapshotUrlOf,
  toEvidenceBoxes,
} from '@/views/decisions/components/reviewFormat'
import {
  appealStatusBadge,
  appealStatusLabel,
  attachmentCount,
  attachmentNames,
  formatAppealDateTime,
  handlerLabel,
  isAppealResolved,
} from './appealsFormat'

const route = useRoute()
const router = useRouter()

const rows = ref<AppealListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const loadError = ref<string | null>(null)

const keyword = ref('')
const status = ref<AppealStatus | ''>('')

const drawerOpen = ref(false)
const active = ref<AppealListItem | null>(null)
const decision = ref<DecisionDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref<string | null>(null)

const upheld = ref(true)
const note = ref('')
const resolving = ref(false)
const resolveError = ref<string | null>(null)
const noteRef = ref<{ focus: () => void } | null>(null)

let fetchSeq = 0
let keywordTimer: ReturnType<typeof setTimeout> | null = null

const evidenceBoxes = computed<EvidenceBox[]>(() => toEvidenceBoxes(decision.value?.evidence_refs))
const evidenceSize = computed(() => evidenceSizeOf(decision.value?.evidence_refs))
const snapshotUrl = computed(() => snapshotUrlOf(decision.value?.evidence_refs))
const hasEvidence = computed(() => snapshotUrl.value !== '')

function syncQueryToUrl(): void {
  void router.replace({
    query: {
      ...route.query,
      status: status.value === '' ? undefined : status.value,
      keyword: keyword.value.trim() === '' ? undefined : keyword.value.trim(),
      page: String(page.value),
    },
  })
}

async function fetchData(): Promise<void> {
  const seq = (fetchSeq += 1)
  loading.value = true
  loadError.value = null
  try {
    const result = await listAppeals({
      page: page.value,
      page_size: pageSize.value,
      status: status.value === '' ? undefined : status.value,
      keyword: keyword.value.trim() === '' ? undefined : keyword.value.trim(),
    })
    if (seq !== fetchSeq) return
    rows.value = result.items
    total.value = result.total
    syncQueryToUrl()
  } catch (error) {
    if (seq !== fetchSeq) return
    rows.value = []
    loadError.value = error instanceof ApiError ? error.message : '申诉列表加载失败'
  } finally {
    if (seq === fetchSeq) loading.value = false
  }
}

function reload(): void {
  void fetchData()
}

function onKeywordInput(value: string): void {
  keyword.value = value
  if (keywordTimer !== null) clearTimeout(keywordTimer)
  keywordTimer = setTimeout(() => {
    page.value = 1
    void fetchData()
  }, 300)
}

function onKeywordClear(): void {
  keyword.value = ''
  page.value = 1
  void fetchData()
}

function onStatusChange(value: AppealStatus | ''): void {
  status.value = value ?? ''
  page.value = 1
  void fetchData()
}

function onPageChange(next: number): void {
  page.value = next
  void fetchData()
}

function onSizeChange(size: number): void {
  pageSize.value = size
  page.value = 1
  void fetchData()
}

async function openDetail(row: AppealListItem): Promise<void> {
  active.value = row
  decision.value = null
  detailError.value = null
  note.value = ''
  resolveError.value = null
  upheld.value = true
  drawerOpen.value = true
  detailLoading.value = true
  try {
    decision.value = await getDecisionDetail(row.decision_id)
  } catch (error) {
    detailError.value = error instanceof ApiError ? error.message : '关联决策加载失败'
  } finally {
    detailLoading.value = false
  }
}

async function onResolve(next: boolean): Promise<void> {
  if (active.value === null) return
  upheld.value = next
  if (note.value.trim() === '') {
    resolveError.value = '处理意见必填，请说明裁决依据'
    noteRef.value?.focus()
    return
  }
  resolving.value = true
  resolveError.value = null
  try {
    const actionText = next ? '成立' : '驳回'
    const confirmText = next
      ? `确认申诉成立？将撤销处罚并返还积分 ${decision.value ? Math.abs(decision.value.score_delta) : 0} 分，该操作会写入审批轨迹。`
      : '确认驳回该申诉？该操作会写入审批轨迹。'
    try {
      await ElMessageBox.confirm(confirmText, `确认${actionText}`, {
        confirmButtonText: `确认${actionText}`,
        cancelButtonText: '取消',
        type: next ? 'warning' : 'error',
      })
    } catch {
      return
    }
    const updated = await resolveAppeal(active.value.appeal_id, {
      upheld: next,
      note: note.value.trim(),
    })
    active.value = updated
    ElMessage.success(next ? '申诉已成立，积分已返还' : '申诉已驳回')
    await fetchData()
  } catch (error) {
    resolveError.value = error instanceof ApiError ? error.message : '裁决失败，请重试'
  } finally {
    resolving.value = false
  }
}

onMounted(() => {
  const queryStatus = route.query.status
  if (queryStatus === 'pending' || queryStatus === 'upheld' || queryStatus === 'rejected') {
    status.value = queryStatus
  }
  const queryKeyword = route.query.keyword
  if (typeof queryKeyword === 'string') keyword.value = queryKeyword
  const queryPage = Number(route.query.page)
  if (Number.isFinite(queryPage) && queryPage >= 1) page.value = Math.floor(queryPage)
  void fetchData()
})
</script>

<style scoped lang="scss" src="./_styles/appeals.scss"></style>

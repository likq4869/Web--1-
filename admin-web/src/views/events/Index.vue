<template>
  <div>
    <PageHeader title="检测事件" description="边缘端上报的骑行检测记录与证据" />

    <div class="hg-events__filters">
      <ElInput
        :model-value="filters.source_id"
        placeholder="按点位筛选"
        clearable
        class="hg-events__search"
        @update:model-value="onSourceInput"
      />
      <ElSelect
        :model-value="filters.status"
        placeholder="复核状态"
        clearable
        class="hg-events__select"
        @update:model-value="onStatusChange"
      >
        <ElOption label="待复核" value="pending" />
        <ElOption label="已确认" value="confirmed" />
        <ElOption label="已驳回" value="dismissed" />
      </ElSelect>
      <ElSelect
        :model-value="filters.rider_status"
        placeholder="头盔状态"
        clearable
        class="hg-events__select"
        @update:model-value="onRiderChange"
      >
        <ElOption label="已佩戴" value="helmeted" />
        <ElOption label="未佩戴" value="bare" />
        <ElOption label="证据不足" value="unknown" />
      </ElSelect>
      <ElSelect
        :model-value="filters.sort"
        class="hg-events__select"
        @update:model-value="onSortChange"
      >
        <ElOption label="时间最新" value="occurred_at/desc" />
        <ElOption label="时间最早" value="occurred_at/asc" />
        <ElOption label="创建最新" value="created_at/desc" />
        <ElOption label="状态优先" value="status/asc" />
      </ElSelect>
      <ElButton link type="primary" @click="resetFilters">重置</ElButton>
      <div class="hg-events__actions">
        <ElButton :loading="exporting" @click="onExport">导出 CSV</ElButton>
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
      row-key="event_id"
      empty-title="暂无检测事件"
      empty-description="当前筛选下没有事件，可调整筛选后重试。"
      @update:current-page="onPageChange"
      @update:page-size="onSizeChange"
    >
      <ElTableColumn prop="event_id" label="事件编号" min-width="170">
        <template #default="{ row }">
          <span class="tabular">{{ (row as EventListItem).event_id }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="source_id" label="点位" min-width="120" />
      <ElTableColumn label="发生时间" min-width="150">
        <template #default="{ row }">
          <span class="tabular">{{ formatEventDateTime((row as EventListItem).occurred_at) }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="复核状态" width="100">
        <template #default="{ row }">
          <ElTag :type="eventStatusBadge((row as EventListItem).status)" size="small">
            {{ eventStatusLabel((row as EventListItem).status) }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="model_label" label="模型结论" min-width="120" />
      <ElTableColumn label="操作" width="110" fixed="right">
        <template #default="{ row }">
          <ElButton link type="primary" @click="openDetail(row as EventListItem)">
            查看详情
          </ElButton>
        </template>
      </ElTableColumn>
    </DataTable>

    <ElDrawer
      :model-value="drawerOpen"
      title="事件详情"
      size="560px"
      destroy-on-close
      @update:model-value="drawerOpen = $event"
    >
      <div v-if="detailLoading" aria-busy="true">证据加载中…</div>
      <p v-else-if="detailError" role="alert">{{ detailError }}</p>
      <div v-else-if="detail" class="hg-events__meta">
        <p class="hg-events__meta-row">
          <span>事件编号</span>
          <span class="tabular">{{ detail.event_id }}</span>
        </p>
        <p class="hg-events__meta-row">
          <span>点位 / 运行</span>
          <span class="tabular">{{ detail.source_id }} · {{ detail.run_id }}</span>
        </p>
        <p class="hg-events__meta-row">
          <span>发生时间</span>
          <span class="tabular">{{ formatEventDateTime(detail.occurred_at) }}</span>
        </p>
        <p class="hg-events__meta-row">
          <span>通行状态</span>
          <span>{{ riderStatusLabel(detail.rider_status) }}</span>
        </p>
        <EvidenceViewer
          image-url=""
          :boxes="evidenceBoxes"
          :image-width="detail.image_width"
          :image-height="detail.image_height"
          alt="检测事件证据图"
        />
        <p v-if="!hasEvidenceSize(detail)" class="hg-events__empty-hint">
          证据图不可用（可能已过 90 天保留期），仅展示检测框与关联结论。
        </p>
        <div class="hg-events__decision">
          <p class="hg-events__decision-title">关联决策</p>
          <p v-if="detail.decision_id" class="hg-events__decision-text">
            <span class="tabular">{{ detail.decision_id }}</span>
            · {{ detail.decision_level ?? '—' }} · {{ detail.decision_status ?? '—' }}
          </p>
          <p v-else class="hg-events__decision-text">暂无关联决策，仍在待识别池中。</p>
        </div>
      </div>
    </ElDrawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  ElButton,
  ElDrawer,
  ElInput,
  ElMessage,
  ElOption,
  ElSelect,
  ElTableColumn,
  ElTag,
} from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import DataTable from '@/components/DataTable.vue'
import EvidenceViewer from '@/components/EvidenceViewer.vue'
import {
  downloadEventsCsv,
  getEventDetail,
  listEvents,
  saveEventsBlob,
  type EventDetail,
  type EventListItem,
  type EventQuery,
  type EventSort,
  type EventStatus,
  type RiderStatus,
} from '@/api/events'
import { ApiError } from '@/api/types'
import {
  eventStatusBadge,
  eventStatusLabel,
  formatEventDateTime,
  hasEvidenceSize,
  riderStatusLabel,
  toEventEvidenceBoxes,
} from './eventsFormat'

const rows = ref<EventListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const loadError = ref<string | null>(null)
const exporting = ref(false)

const filters = ref<Required<Pick<EventQuery, 'source_id' | 'status' | 'rider_status' | 'sort'>>>({
  source_id: '',
  status: '' as EventStatus | '',
  rider_status: '' as RiderStatus | '',
  sort: 'occurred_at/desc' as EventSort,
})

const drawerOpen = ref(false)
const detail = ref<EventDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref<string | null>(null)

let fetchSeq = 0
let sourceTimer: ReturnType<typeof setTimeout> | null = null

const evidenceBoxes = computed(() => toEventEvidenceBoxes(detail.value?.boxes ?? []))

function currentQuery(): EventQuery {
  return {
    page: page.value,
    page_size: pageSize.value,
    source_id: filters.value.source_id.trim() === '' ? undefined : filters.value.source_id.trim(),
    status: filters.value.status === '' ? undefined : filters.value.status,
    rider_status: filters.value.rider_status === '' ? undefined : filters.value.rider_status,
    sort: filters.value.sort,
  }
}

async function fetchData(): Promise<void> {
  const seq = (fetchSeq += 1)
  loading.value = true
  loadError.value = null
  try {
    const result = await listEvents(currentQuery())
    if (seq !== fetchSeq) return
    rows.value = result.items
    total.value = result.total
  } catch (error) {
    if (seq !== fetchSeq) return
    rows.value = []
    loadError.value = error instanceof ApiError ? error.message : '检测事件加载失败'
  } finally {
    if (seq === fetchSeq) loading.value = false
  }
}

function reload(): void {
  void fetchData()
}

function onSourceInput(value: string): void {
  filters.value.source_id = value
  if (sourceTimer !== null) clearTimeout(sourceTimer)
  sourceTimer = setTimeout(() => {
    page.value = 1
    void fetchData()
  }, 300)
}

function onStatusChange(value: EventStatus | ''): void {
  filters.value.status = value ?? ''
  page.value = 1
  void fetchData()
}

function onRiderChange(value: RiderStatus | ''): void {
  filters.value.rider_status = value ?? ''
  page.value = 1
  void fetchData()
}

function onSortChange(value: EventSort): void {
  filters.value.sort = value
  page.value = 1
  void fetchData()
}

function resetFilters(): void {
  filters.value = {
    source_id: '',
    status: '',
    rider_status: '',
    sort: 'occurred_at/desc',
  }
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

async function onExport(): Promise<void> {
  exporting.value = true
  try {
    const query = currentQuery()
    const blob = await downloadEventsCsv({
      source_id: query.source_id,
      status: query.status,
      rider_status: query.rider_status,
      sort: query.sort,
    })
    saveEventsBlob(blob)
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '导出失败，请重试')
  } finally {
    exporting.value = false
  }
}

async function openDetail(row: EventListItem): Promise<void> {
  drawerOpen.value = true
  detail.value = null
  detailError.value = null
  detailLoading.value = true
  try {
    detail.value = await getEventDetail(row.event_id)
  } catch (error) {
    detailError.value = error instanceof ApiError ? error.message : '事件详情加载失败'
  } finally {
    detailLoading.value = false
  }
}

onMounted(() => {
  void fetchData()
})
</script>

<style scoped lang="scss" src="./_styles/events.scss"></style>

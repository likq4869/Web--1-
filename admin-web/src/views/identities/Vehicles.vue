<template>
  <div>
    <PageHeader title="车辆档案" description="已登记与待绑定车辆的归属、车牌与匹配历史" />

    <div class="hg-toolbar">
      <ElInput
        :model-value="keyword"
        placeholder="按车辆编号 / 车牌搜索"
        clearable
        class="hg-toolbar__search"
        @update:model-value="onKeywordInput"
        @clear="onClear"
      />
      <ElSelect :model-value="status" placeholder="全部状态" clearable @change="onStatusChange">
        <ElOption label="全部状态" value="" />
        <ElOption label="已绑定" value="active" />
        <ElOption label="未绑定" value="unbound" />
        <ElOption label="已停用" value="blocked" />
      </ElSelect>
      <ElButton :loading="loading" @click="reload">刷新</ElButton>
    </div>

    <DataTable
      :rows="rows"
      :loading="loading"
      :error="loadError"
      :total="total"
      :current-page="page"
      :page-size="pageSize"
      :on-retry="reload"
      row-key="vehicle_id"
      empty-title="暂无车辆档案"
      empty-description="车辆会在首次通行后自动建档。"
      @update:current-page="onPageChange"
      @update:page-size="onSizeChange"
    >
      <ElTableColumn prop="vehicle_id" label="车辆编号" min-width="170" />
      <ElTableColumn prop="plate_no" label="车牌" min-width="130">
        <template #default="{ row }">
          {{ (row as Vehicle).plate_no ?? '—' }}
        </template>
      </ElTableColumn>
      <ElTableColumn prop="owner_id" label="绑定学号" min-width="130">
        <template #default="{ row }">
          {{ (row as Vehicle).owner_id ?? '未绑定' }}
        </template>
      </ElTableColumn>
      <ElTableColumn prop="owner_bind_type" label="绑定方式" width="120">
        <template #default="{ row }">
          {{ bindTypeLabel((row as Vehicle).owner_bind_type) }}
        </template>
      </ElTableColumn>
      <ElTableColumn prop="confidence" label="置信度" width="100">
        <template #default="{ row }">
          <span class="tabular">{{ formatConfidence((row as Vehicle).confidence) }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="last_seen" label="最近出现" min-width="170">
        <template #default="{ row }">
          {{ formatTime((row as Vehicle).last_seen) }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作" width="110" fixed="right">
        <template #default="{ row }">
          <ElButton link type="primary" @click="openDetail(row as Vehicle)">详情</ElButton>
        </template>
      </ElTableColumn>
    </DataTable>

    <ElDrawer v-model="drawerOpen" title="车辆详情" size="560px" destroy-on-close>
      <div v-if="detailLoading" class="hg-detail-loading" aria-busy="true" aria-label="加载中">
        <ElSkeleton :rows="5" animated />
      </div>
      <p v-else-if="detailError" class="hg-detail-error" role="alert">
        {{ detailError }}
        <ElButton size="small" @click="fetchDetail">重试</ElButton>
      </p>
      <div v-else-if="detail" class="hg-detail">
        <section class="hg-detail__section">
          <h3 class="hg-detail__title">基本信息</h3>
          <dl class="hg-detail__grid">
            <div class="hg-detail__cell">
              <dt>车辆编号</dt>
              <dd class="tabular">{{ detail.vehicle.vehicle_id }}</dd>
            </div>
            <div class="hg-detail__cell">
              <dt>车牌</dt>
              <dd>{{ detail.vehicle.plate_no ?? '—' }}</dd>
            </div>
            <div class="hg-detail__cell">
              <dt>绑定学号</dt>
              <dd>{{ detail.vehicle.owner_id ?? '未绑定' }}</dd>
            </div>
            <div class="hg-detail__cell">
              <dt>绑定方式</dt>
              <dd>{{ bindTypeLabel(detail.vehicle.owner_bind_type) }}</dd>
            </div>
            <div class="hg-detail__cell">
              <dt>置信度</dt>
              <dd class="tabular">{{ formatConfidence(detail.vehicle.confidence) }}</dd>
            </div>
            <div class="hg-detail__cell">
              <dt>状态</dt>
              <dd>{{ statusLabel(detail.vehicle.status) }}</dd>
            </div>
          </dl>
        </section>
        <section class="hg-detail__section">
          <h3 class="hg-detail__title">匹配历史（{{ detail.resolutions.length }}）</h3>
          <EmptyState
            v-if="detail.resolutions.length === 0"
            title="暂无匹配历史"
            description="该车辆尚未产生身份判定记录。"
          />
          <ElTimeline v-else>
            <ElTimelineItem
              v-for="item in detail.resolutions"
              :key="item.id"
              :timestamp="formatTime(item.created_at)"
              placement="top"
            >
              <p class="hg-timeline__text">
                {{ item.subject_id ?? '未知学生' }} · {{ methodLabel(item.method) }} ·
                <span class="tabular">{{ formatConfidence(item.confidence) }}</span>
              </p>
              <p class="hg-timeline__sub tabular">事件 {{ item.event_id }}</p>
            </ElTimelineItem>
          </ElTimeline>
        </section>
      </div>
    </ElDrawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  ElButton,
  ElDrawer,
  ElInput,
  ElOption,
  ElSelect,
  ElSkeleton,
  ElTableColumn,
  ElTimeline,
  ElTimelineItem,
} from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import DataTable from '@/components/DataTable.vue'
import EmptyState from '@/components/EmptyState.vue'
import { getVehicleDetail, listVehicles, type Vehicle, type VehicleDetail } from '@/api/identity'
import { ApiError } from '@/api/types'

const rows = ref<Vehicle[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const status = ref('')
const loading = ref(false)
const loadError = ref<string | null>(null)

const drawerOpen = ref(false)
const activeId = ref('')
const detail = ref<VehicleDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref<string | null>(null)

let keywordTimer: ReturnType<typeof setTimeout> | null = null
let fetchSeq = 0

onMounted(() => {
  void fetchData()
})

function onKeywordInput(value: string): void {
  keyword.value = value
  if (keywordTimer !== null) clearTimeout(keywordTimer)
  keywordTimer = setTimeout(() => {
    page.value = 1
    void fetchData()
  }, 300)
}

function onClear(): void {
  keyword.value = ''
  page.value = 1
  void fetchData()
}

function onStatusChange(value: string): void {
  status.value = value
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

function reload(): void {
  void fetchData()
}

async function fetchData(): Promise<void> {
  const seq = (fetchSeq += 1)
  loading.value = true
  loadError.value = null
  try {
    const result = await listVehicles({
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim() === '' ? undefined : keyword.value.trim(),
      status: status.value === '' ? undefined : status.value,
      sort: 'last_seen',
      order: 'desc',
    })
    if (seq !== fetchSeq) return
    rows.value = result.items
    total.value = result.total
  } catch (error) {
    if (seq !== fetchSeq) return
    rows.value = []
    loadError.value = error instanceof ApiError ? error.message : '车辆档案加载失败'
  } finally {
    if (seq === fetchSeq) loading.value = false
  }
}

function openDetail(row: Vehicle): void {
  activeId.value = row.vehicle_id
  detail.value = null
  drawerOpen.value = true
  void fetchDetail()
}

async function fetchDetail(): Promise<void> {
  if (activeId.value === '') return
  detailLoading.value = true
  detailError.value = null
  try {
    detail.value = await getVehicleDetail(activeId.value)
  } catch (error) {
    detail.value = null
    detailError.value = error instanceof ApiError ? error.message : '车辆详情加载失败'
  } finally {
    detailLoading.value = false
  }
}

function formatTime(value: string | null): string {
  if (value === null || value === '') return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function formatConfidence(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return `${(value * 100).toFixed(1)}%`
}

function bindTypeLabel(value: string | null): string {
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

function statusLabel(value: string): string {
  const map: Record<string, string> = {
    active: '已绑定',
    unbound: '未绑定',
    blocked: '已停用',
  }
  return map[value] ?? value
}

function methodLabel(value: string | null): string {
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
</script>

<style scoped lang="scss">
.hg-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--card-gap);
}

.hg-toolbar__search {
  width: 260px;
}

.hg-detail-loading {
  padding: var(--space-2) 0;
}

.hg-detail-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-footnote-size);
  color: var(--color-danger);
  background-color: var(--color-danger-tint);
  border-radius: var(--radius-md);
}

.hg-detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.hg-detail__section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.hg-detail__title {
  margin: 0;
  font-size: var(--text-headline-size);
  font-weight: var(--text-headline-weight);
  color: var(--color-text);
}

.hg-detail__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  margin: 0;
}

.hg-detail__cell {
  padding: var(--space-3);
  background-color: var(--color-surface-2);
  border-radius: var(--radius-md);

  dt {
    font-size: var(--text-caption-size);
    color: var(--color-text-3);
  }

  dd {
    margin: var(--space-1) 0 0;
    font-size: var(--text-body-size);
    color: var(--color-text);
  }
}

.hg-timeline__text {
  margin: 0;
  font-size: var(--text-body-size);
  color: var(--color-text);
}

.hg-timeline__sub {
  margin: var(--space-1) 0 0;
  font-size: var(--text-footnote-size);
  color: var(--color-text-3);
}
</style>

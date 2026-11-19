<template>
  <div>
    <PageHeader
      title="待识别车辆池"
      description="多次出现但尚未绑定的车辆，绑定后自动终结待处理记录"
    />

    <div class="hg-toolbar">
      <ElInput
        :model-value="keyword"
        placeholder="按车辆编号搜索"
        clearable
        class="hg-toolbar__search"
        @update:model-value="onKeywordInput"
        @clear="onClear"
      />
      <ElButton :disabled="selectedIds.length === 0 || batchIgnoring" @click="onBatchIgnore">
        {{ batchIgnoring ? '忽略中' : `批量忽略（${selectedIds.length}）` }}
      </ElButton>
      <ElButton :loading="loading" @click="reload">刷新</ElButton>
    </div>

    <p v-if="actionError" class="hg-action-error" role="alert">{{ actionError }}</p>

    <DataTable
      :rows="rows"
      :loading="loading"
      :error="loadError"
      :total="total"
      :current-page="page"
      :page-size="pageSize"
      :on-retry="reload"
      row-key="id"
      empty-title="暂无待识别车辆"
      empty-description="所有多次出现的车辆均已绑定或忽略。"
      @update:current-page="onPageChange"
      @update:page-size="onSizeChange"
      @selection-change="onSelectionChange"
    >
      <ElTableColumn type="selection" width="48" />
      <ElTableColumn prop="vehicle_id" label="车辆编号" min-width="160">
        <template #default="{ row }">
          <span class="tabular">{{ (row as PendingListItem).pending.vehicle_id }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="出现次数" width="110">
        <template #default="{ row }">
          <span class="tabular">{{ (row as PendingListItem).pending.pass_count }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="首次出现" min-width="170">
        <template #default="{ row }">
          {{ formatTime((row as PendingListItem).pending.first_seen) }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="最近出现" min-width="170">
        <template #default="{ row }">
          {{ formatTime((row as PendingListItem).pending.last_seen) }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="最近点位" min-width="120">
        <template #default="{ row }">
          {{ (row as PendingListItem).pending.location ?? '—' }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <ElButton link type="primary" @click="openEvidence(row as PendingListItem)">
            查看证据
          </ElButton>
          <ElButton link type="primary" @click="openBind(row as PendingListItem)">
            绑定学生
          </ElButton>
          <ElButton link type="danger" @click="onIgnoreOne(row as PendingListItem)">
            忽略
          </ElButton>
        </template>
      </ElTableColumn>
      <template #empty>
        <ElButton @click="reload">重新加载</ElButton>
      </template>
    </DataTable>

    <!-- 证据抽屉 -->
    <ElDrawer v-model="evidenceOpen" title="通行证据" size="520px" destroy-on-close>
      <div v-if="active" class="hg-evidence-meta">
        <p class="hg-evidence-meta__row">
          <span>车辆编号</span>
          <span class="tabular">{{ active.pending.vehicle_id }}</span>
        </p>
        <p class="hg-evidence-meta__row">
          <span>出现次数</span>
          <span class="tabular">{{ active.pending.pass_count }}</span>
        </p>
        <p class="hg-evidence-meta__row">
          <span>最近点位</span>
          <span>{{ active.pending.location ?? '—' }}</span>
        </p>
        <p class="hg-evidence-meta__row">
          <span>证据帧</span>
          <span class="tabular">{{ active.pending.snapshot_id ?? '—' }}</span>
        </p>
      </div>
      <EvidenceViewer :image-url="evidenceImageUrl" :boxes="[]" alt="待识别车辆证据图" />
      <p class="hg-evidence-hint">证据图片由采集端按 snapshot_id 归档，此处按点位快照占位展示。</p>
    </ElDrawer>

    <!-- 绑定弹窗 -->
    <ElDialog v-model="bindOpen" title="绑定学生" width="480px" destroy-on-close>
      <p class="hg-bind-target">
        车辆 <span class="tabular">{{ active?.pending.vehicle_id }}</span> 将绑定到：
        <span v-if="pickedStudent" class="hg-bind-picked">
          {{ pickedStudent.name }}（{{ pickedStudent.student_id }}）
        </span>
        <span v-else>未选择</span>
      </p>
      <ElButton @click="pickerVisible = true">选择学生</ElButton>
      <template #footer>
        <ElButton @click="bindOpen = false">取消</ElButton>
        <ElButton
          type="primary"
          :loading="binding"
          :disabled="pickedStudent === null"
          @click="onBindConfirm"
        >
          {{ binding ? '绑定中' : '确认绑定' }}
        </ElButton>
      </template>
    </ElDialog>

    <StudentPicker
      v-model:visible="pickerVisible"
      v-model:model-value="pickedStudentId"
      @select="onStudentPicked"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElButton, ElDialog, ElDrawer, ElInput, ElTableColumn } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import DataTable from '@/components/DataTable.vue'
import EvidenceViewer from '@/components/EvidenceViewer.vue'
import StudentPicker from '@/components/StudentPicker.vue'
import { bindVehicle, ignorePending, listPending, type PendingListItem } from '@/api/identity'
import type { Student } from '@/api/students'
import { ApiError } from '@/api/types'

/** 表格行：后端列表项 + 顶层 id（供 ElTable row-key 使用） */
type PendingRow = PendingListItem & { id: number }

const rows = ref<PendingRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const loading = ref(false)
const loadError = ref<string | null>(null)
const actionError = ref<string | null>(null)

const selectedIds = ref<string[]>([])
const batchIgnoring = ref(false)

const active = ref<PendingListItem | null>(null)
const evidenceOpen = ref(false)
const evidenceImageUrl = ref('')
const bindOpen = ref(false)
const binding = ref(false)
const pickerVisible = ref(false)
const pickedStudent = ref<Student | null>(null)
const pickedStudentId = ref<string | null>(null)

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
    const result = await listPending({
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim() === '' ? undefined : keyword.value.trim(),
      sort: 'pass_count',
      order: 'desc',
      status: 'pending',
    })
    if (seq !== fetchSeq) return
    rows.value = result.items.map((item) => ({ ...item, id: item.pending.id }))
    total.value = result.total
    selectedIds.value = []
  } catch (error) {
    if (seq !== fetchSeq) return
    rows.value = []
    loadError.value = error instanceof ApiError ? error.message : '待识别池加载失败'
  } finally {
    if (seq === fetchSeq) loading.value = false
  }
}

function onSelectionChange(selection: PendingRow[]): void {
  selectedIds.value = selection.map((item) => item.pending.vehicle_id)
}

function formatTime(value: string | null): string {
  if (value === null || value === '') return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function openEvidence(item: PendingListItem): void {
  active.value = item
  evidenceImageUrl.value = ''
  evidenceOpen.value = true
}

function openBind(item: PendingListItem): void {
  active.value = item
  pickedStudent.value = null
  pickedStudentId.value = null
  actionError.value = null
  bindOpen.value = true
}

function onStudentPicked(student: Student): void {
  pickedStudent.value = student
  pickedStudentId.value = student.student_id
}

async function onBindConfirm(): Promise<void> {
  if (active.value === null || pickedStudent.value === null) return
  binding.value = true
  actionError.value = null
  try {
    await bindVehicle(active.value.pending.vehicle_id, {
      student_id: pickedStudent.value.student_id,
      method: 'manual',
    })
    bindOpen.value = false
    await fetchData()
  } catch (error) {
    actionError.value = error instanceof ApiError ? error.message : '绑定失败，请重试'
  } finally {
    binding.value = false
  }
}

async function onIgnoreOne(item: PendingListItem): Promise<void> {
  actionError.value = null
  try {
    await ignorePending(item.pending.vehicle_id)
    await fetchData()
  } catch (error) {
    actionError.value = error instanceof ApiError ? error.message : '忽略失败，请重试'
  }
}

async function onBatchIgnore(): Promise<void> {
  if (selectedIds.value.length === 0) return
  batchIgnoring.value = true
  actionError.value = null
  try {
    for (const vehicleId of selectedIds.value) {
      await ignorePending(vehicleId)
    }
    await fetchData()
  } catch (error) {
    actionError.value = error instanceof ApiError ? error.message : '批量忽略失败，请重试'
  } finally {
    batchIgnoring.value = false
  }
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

.hg-action-error {
  margin: 0 0 var(--space-2);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-footnote-size);
  color: var(--color-danger);
  background-color: var(--color-danger-tint);
  border-radius: var(--radius-md);
}

.hg-evidence-meta {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}

.hg-evidence-meta__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  margin: 0;
  font-size: var(--text-footnote-size);
  color: var(--color-text-2);
}

.hg-evidence-hint {
  margin-top: var(--space-3);
  font-size: var(--text-footnote-size);
  color: var(--color-text-3);
}

.hg-bind-target {
  font-size: var(--text-body-size);
  color: var(--color-text-2);
}

.hg-bind-picked {
  font-weight: var(--text-subhead-weight);
  color: var(--color-text);
}
</style>

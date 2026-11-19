<template>
  <div>
    <PageHeader title="审计日志" description="关键操作的只读留痕记录，不可修改或删除" />

    <p class="hg-audit__read-only">
      审计日志为只读数据，系统不提供修改或删除入口，访问行为本身也会留痕。
    </p>

    <div class="hg-audit__filters">
      <ElInput
        :model-value="actor"
        placeholder="按操作人筛选"
        clearable
        class="hg-audit__search"
        @update:model-value="onActorInput"
        @clear="onActorClear"
      />
      <ElInput
        :model-value="actionPrefix"
        placeholder="按动作前缀筛选，如 model."
        clearable
        class="hg-audit__search"
        @update:model-value="onActionInput"
        @clear="onActionClear"
      />
      <div class="hg-audit__actions">
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
      row-key="id"
      empty-title="暂无审计记录"
      empty-description="当前筛选下没有审计记录，可调整筛选后重试。"
      @update:current-page="onPageChange"
      @update:page-size="onSizeChange"
    >
      <ElTableColumn prop="id" label="编号" width="90">
        <template #default="{ row }">
          <span class="tabular">{{ (row as AuditLog).id }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="actor" label="操作人" min-width="140" />
      <ElTableColumn prop="role" label="角色" width="130">
        <template #default="{ row }">
          {{ roleLabel((row as AuditLog).role) }}
        </template>
      </ElTableColumn>
      <ElTableColumn prop="action" label="动作" min-width="170">
        <template #default="{ row }">
          <span class="tabular">{{ (row as AuditLog).action }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="result" label="结果" width="100">
        <template #default="{ row }">
          <ElTag :type="(row as AuditLog).result === 'ok' ? 'success' : 'info'" size="small">
            {{ (row as AuditLog).result }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="记录时间" min-width="150">
        <template #default="{ row }">
          <span class="tabular">{{ formatOpsDateTime((row as AuditLog).created_at) }}</span>
        </template>
      </ElTableColumn>
    </DataTable>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElButton, ElInput, ElTableColumn, ElTag } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import DataTable from '@/components/DataTable.vue'
import { listAuditLogs, type AuditLog } from '@/api/ops'
import { ApiError } from '@/api/types'
import { formatOpsDateTime, roleLabel } from '@/views/models/opsFormat'

const rows = ref<AuditLog[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const loadError = ref<string | null>(null)

const actor = ref('')
const actionPrefix = ref('')

let fetchSeq = 0
let actorTimer: ReturnType<typeof setTimeout> | null = null
let actionTimer: ReturnType<typeof setTimeout> | null = null

async function fetchData(): Promise<void> {
  const seq = (fetchSeq += 1)
  loading.value = true
  loadError.value = null
  try {
    const result = await listAuditLogs({
      page: page.value,
      page_size: pageSize.value,
      actor: actor.value.trim() === '' ? undefined : actor.value.trim(),
      action: actionPrefix.value.trim() === '' ? undefined : actionPrefix.value.trim(),
    })
    if (seq !== fetchSeq) return
    rows.value = result.items
    total.value = result.total
  } catch (error) {
    if (seq !== fetchSeq) return
    rows.value = []
    loadError.value = error instanceof ApiError ? error.message : '审计日志加载失败'
  } finally {
    if (seq === fetchSeq) loading.value = false
  }
}

function reload(): void {
  void fetchData()
}

function onActorInput(value: string): void {
  actor.value = value
  if (actorTimer !== null) clearTimeout(actorTimer)
  actorTimer = setTimeout(() => {
    page.value = 1
    void fetchData()
  }, 300)
}

function onActorClear(): void {
  actor.value = ''
  page.value = 1
  void fetchData()
}

function onActionInput(value: string): void {
  actionPrefix.value = value
  if (actionTimer !== null) clearTimeout(actionTimer)
  actionTimer = setTimeout(() => {
    page.value = 1
    void fetchData()
  }, 300)
}

function onActionClear(): void {
  actionPrefix.value = ''
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

onMounted(() => {
  void fetchData()
})
</script>

<style scoped lang="scss" src="./_styles/audit-logs.scss"></style>

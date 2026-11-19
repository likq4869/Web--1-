<template>
  <div>
    <PageHeader title="模型管理" description="版本注册、激活切换与误判回流闭环水位" />

    <div class="hg-models__filters">
      <ElSelect
        :model-value="task"
        placeholder="任务类型"
        clearable
        class="hg-models__select"
        @update:model-value="onTaskChange"
      >
        <ElOption label="头盔检测" value="detect" />
        <ElOption label="车牌识别" value="plate" />
        <ElOption label="头部二分类" value="head_cls" />
        <ElOption label="车辆重识别" value="reid" />
      </ElSelect>
      <div class="hg-models__actions">
        <ElButton :loading="loading" @click="reload">刷新</ElButton>
      </div>
    </div>

    <div v-if="stats" class="hg-models__stats" aria-label="回流样本水位">
      <div class="hg-models__stat">
        <span class="hg-models__stat-label">回流样本总数</span>
        <span class="hg-models__stat-value tabular">{{ stats.total }}</span>
      </div>
      <div class="hg-models__stat">
        <span class="hg-models__stat-label">待训练</span>
        <span class="hg-models__stat-value tabular">{{ stats.pending_train }}</span>
      </div>
      <div class="hg-models__stat">
        <span class="hg-models__stat-label">审批驳回</span>
        <span class="hg-models__stat-value tabular">{{ stats.by_source.review_reject ?? 0 }}</span>
      </div>
      <div class="hg-models__stat">
        <span class="hg-models__stat-label">申诉成立</span>
        <span class="hg-models__stat-value tabular">{{ stats.by_source.appeal_upheld ?? 0 }}</span>
      </div>
      <div class="hg-models__stat">
        <span class="hg-models__stat-label">人工标注</span>
        <span class="hg-models__stat-value tabular">{{ stats.by_source.manual ?? 0 }}</span>
      </div>
    </div>

    <DataTable
      :rows="rows"
      :loading="loading"
      :error="loadError"
      :total="total"
      :current-page="page"
      :page-size="pageSize"
      :show-pagination="false"
      :on-retry="reload"
      row-key="model_id"
      empty-title="暂无模型版本"
      empty-description="当前筛选下没有模型版本，可切换任务类型后重试。"
      @update:current-page="onPageChange"
      @update:page-size="onSizeChange"
    >
      <ElTableColumn prop="model_id" label="模型 ID" min-width="170">
        <template #default="{ row }">
          <span class="tabular">{{ (row as ModelVersion).model_id }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="任务" width="120">
        <template #default="{ row }">
          {{ modelTaskLabel((row as ModelVersion).task) }}
        </template>
      </ElTableColumn>
      <ElTableColumn prop="version" label="版本" width="110">
        <template #default="{ row }">
          <span class="tabular">{{ (row as ModelVersion).version }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="指标" min-width="150">
        <template #default="{ row }">
          <span class="tabular">{{ metricsSummary((row as ModelVersion).metrics) }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="状态" width="100">
        <template #default="{ row }">
          <ElTag :type="modelActiveBadge((row as ModelVersion).is_active)" size="small">
            {{ modelActiveLabel((row as ModelVersion).is_active) }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="部署时间" min-width="150">
        <template #default="{ row }">
          <span class="tabular">{{ formatOpsDateTime((row as ModelVersion).deployed_at) }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作" width="110" fixed="right">
        <template #default="{ row }">
          <ElButton
            link
            type="primary"
            :disabled="(row as ModelVersion).is_active || activating"
            @click="onActivate(row as ModelVersion)"
          >
            激活
          </ElButton>
        </template>
      </ElTableColumn>
    </DataTable>
    <p v-if="actionError" class="hg-models__error" role="alert">{{ actionError }}</p>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElButton,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElSelect,
  ElTableColumn,
  ElTag,
} from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import DataTable from '@/components/DataTable.vue'
import {
  activateModel,
  getFeedbackStats,
  listModels,
  type FeedbackStats,
  type ModelTask,
  type ModelVersion,
} from '@/api/ops'
import { ApiError } from '@/api/types'
import {
  formatOpsDateTime,
  metricsSummary,
  modelActiveBadge,
  modelActiveLabel,
  modelTaskLabel,
} from './opsFormat'

const route = useRoute()
const router = useRouter()

const rows = ref<ModelVersion[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const loadError = ref<string | null>(null)
const actionError = ref<string | null>(null)
const activating = ref(false)
const task = ref<ModelTask>('')
const stats = ref<FeedbackStats | null>(null)

let fetchSeq = 0

function syncQueryToUrl(): void {
  void router.replace({
    query: { ...route.query, task: task.value === '' ? undefined : task.value },
  })
}

async function fetchData(): Promise<void> {
  const seq = (fetchSeq += 1)
  loading.value = true
  loadError.value = null
  try {
    const [models, feedback] = await Promise.all([
      listModels(task.value === '' ? undefined : task.value),
      getFeedbackStats(),
    ])
    if (seq !== fetchSeq) return
    rows.value = models.items
    total.value = models.total
    stats.value = feedback
    syncQueryToUrl()
  } catch (error) {
    if (seq !== fetchSeq) return
    rows.value = []
    loadError.value = error instanceof ApiError ? error.message : '模型版本加载失败'
  } finally {
    if (seq === fetchSeq) loading.value = false
  }
}

function reload(): void {
  void fetchData()
}

function onTaskChange(value: ModelTask): void {
  task.value = value ?? ''
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

async function onActivate(row: ModelVersion): Promise<void> {
  actionError.value = null
  try {
    await ElMessageBox.confirm(
      `确认激活 ${row.model_id}（${row.version}）？同任务下其他版本将自动停用，该操作会写入审计。`,
      '激活模型版本',
      { confirmButtonText: '确认激活', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  activating.value = true
  try {
    await activateModel(row.model_id)
    ElMessage.success(`已激活 ${row.model_id}`)
    await fetchData()
  } catch (error) {
    actionError.value = error instanceof ApiError ? error.message : '激活失败，请重试'
  } finally {
    activating.value = false
  }
}

onMounted(() => {
  const queryTask = route.query.task
  if (
    queryTask === 'detect' ||
    queryTask === 'plate' ||
    queryTask === 'head_cls' ||
    queryTask === 'reid'
  ) {
    task.value = queryTask
  }
  void fetchData()
})
</script>

<style scoped lang="scss" src="./_styles/models.scss"></style>

<template>
  <div>
    <PageHeader
      title="学生档案"
      description="学生基本信息、名下车辆与导入管理（辅导员仅见所带班级）"
    >
      <template #actions>
        <ElButton :loading="templateDownloading" @click="onDownloadTemplate">下载模板</ElButton>
        <ElButton type="primary" @click="importOpen = true">批量导入</ElButton>
      </template>
    </PageHeader>

    <div class="hg-toolbar">
      <ElInput
        :model-value="keyword"
        placeholder="按学号 / 姓名 / 手机号搜索"
        clearable
        class="hg-toolbar__search"
        @update:model-value="onKeywordInput"
        @clear="onClear"
      />
      <ElInput
        :model-value="college"
        placeholder="按学院筛选"
        clearable
        class="hg-toolbar__search"
        @update:model-value="onCollegeInput"
        @clear="onCollegeClear"
      />
      <ElButton :loading="loading" @click="reload">刷新</ElButton>
    </div>

    <p class="hg-scope-hint">
      积分、等级、佩戴率与违规次数待积分域接入，当前以“—”占位，不影响档案管理。
    </p>

    <DataTable
      :rows="rows"
      :loading="loading"
      :error="loadError"
      :total="total"
      :current-page="page"
      :page-size="pageSize"
      :on-retry="reload"
      row-key="student_id"
      empty-title="暂无学生档案"
      empty-description="可通过批量导入创建学生档案。"
      @update:current-page="onPageChange"
      @update:page-size="onSizeChange"
    >
      <ElTableColumn prop="student_id" label="学号" min-width="140" />
      <ElTableColumn prop="name" label="姓名" min-width="100" />
      <ElTableColumn prop="class_name" label="班级" min-width="140">
        <template #default="{ row }">
          {{ (row as Student).class_name ?? '—' }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="积分" width="90">
        <template #default>—</template>
      </ElTableColumn>
      <ElTableColumn label="等级" width="90">
        <template #default>—</template>
      </ElTableColumn>
      <ElTableColumn label="近30天佩戴率" min-width="130">
        <template #default>—</template>
      </ElTableColumn>
      <ElTableColumn label="违规次数" width="100">
        <template #default>
          <span class="tabular">—</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="phone" label="手机号" min-width="140">
        <template #default="{ row }">
          {{ maskPhone((row as Student).phone) }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作" width="110" fixed="right">
        <template #default="{ row }">
          <ElButton link type="primary" @click="openDetail(row as Student)">详情</ElButton>
        </template>
      </ElTableColumn>
    </DataTable>

    <StudentDetailDrawer
      :open="drawerOpen"
      :detail="detail"
      :detail-loading="detailLoading"
      :detail-error="detailError"
      @update:open="drawerOpen = $event"
      @retry="fetchDetail"
    />

    <StudentImportDialog :open="importOpen" @update:open="importOpen = $event" @imported="reload" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElButton, ElInput, ElTableColumn } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import DataTable from '@/components/DataTable.vue'
import StudentDetailDrawer from './components/StudentDetailDrawer.vue'
import StudentImportDialog from './components/StudentImportDialog.vue'
import { maskPhone } from './components/studentsFormat'
import {
  downloadImportTemplate,
  getStudentDetail,
  listStudents,
  saveBlob,
  type Student,
  type StudentDetail,
} from '@/api/students'
import { ApiError } from '@/api/types'

const rows = ref<Student[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const college = ref('')
const loading = ref(false)
const loadError = ref<string | null>(null)

const drawerOpen = ref(false)
const activeId = ref('')
const detail = ref<StudentDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref<string | null>(null)

const importOpen = ref(false)
const templateDownloading = ref(false)

let keywordTimer: ReturnType<typeof setTimeout> | null = null
let collegeTimer: ReturnType<typeof setTimeout> | null = null
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

function onCollegeInput(value: string): void {
  college.value = value
  if (collegeTimer !== null) clearTimeout(collegeTimer)
  collegeTimer = setTimeout(() => {
    page.value = 1
    void fetchData()
  }, 300)
}

function onCollegeClear(): void {
  college.value = ''
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
    const result = await listStudents({
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim() === '' ? undefined : keyword.value.trim(),
      college: college.value.trim() === '' ? undefined : college.value.trim(),
      sort: 'student_id',
      order: 'asc',
    })
    if (seq !== fetchSeq) return
    rows.value = result.items
    total.value = result.total
  } catch (error) {
    if (seq !== fetchSeq) return
    rows.value = []
    loadError.value = error instanceof ApiError ? error.message : '学生档案加载失败'
  } finally {
    if (seq === fetchSeq) loading.value = false
  }
}

function openDetail(row: Student): void {
  activeId.value = row.student_id
  detail.value = null
  drawerOpen.value = true
  void fetchDetail()
}

async function fetchDetail(): Promise<void> {
  if (activeId.value === '') return
  detailLoading.value = true
  detailError.value = null
  try {
    detail.value = await getStudentDetail(activeId.value)
  } catch (error) {
    detail.value = null
    detailError.value = error instanceof ApiError ? error.message : '学生详情加载失败'
  } finally {
    detailLoading.value = false
  }
}

async function onDownloadTemplate(): Promise<void> {
  templateDownloading.value = true
  try {
    const blob = await downloadImportTemplate()
    saveBlob(blob, 'students-template.xlsx')
  } catch (error) {
    loadError.value = error instanceof ApiError ? error.message : '模板下载失败'
  } finally {
    templateDownloading.value = false
  }
}
</script>

<style scoped lang="scss" src="./_styles/students.scss"></style>

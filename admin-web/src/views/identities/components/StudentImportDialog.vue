<template>
  <ElDialog
    :model-value="open"
    title="批量导入学生"
    width="640px"
    destroy-on-close
    @update:model-value="emit('update:open', $event)"
    @closed="onImportClosed"
  >
    <ol class="hg-import-steps">
      <li>下载模板，按列填写：{{ templateColumns.join(' / ') }}。</li>
      <li>学号为 6-20 位数字，必填且文件内不重复；手机号为 11 位大陆号码（可空）。</li>
      <li>上传 xlsx；小文件即时返回逐行报告，大文件（&gt;500 行）返回任务 ID 自动轮询。</li>
    </ol>
    <ElUpload
      drag
      accept=".xlsx,.xlsm"
      :auto-upload="false"
      :show-file-list="false"
      :on-change="onFilePicked"
    >
      <ElIcon class="el-icon--upload"><UploadFilled /></ElIcon>
      <div class="el-upload__text">拖拽文件到此处，或 <em>点击选择</em></div>
      <template #tip>
        <div class="el-upload__tip">仅支持 xlsx / xlsm，最大 20MB。</div>
      </template>
    </ElUpload>
    <p v-if="pickedName" class="hg-import-file">
      已选择：{{ pickedName }}
      <ElButton link type="primary" :loading="importing" @click="onImportStart">开始上传</ElButton>
    </p>
    <div v-if="importing" class="hg-import-loading" aria-busy="true" aria-label="导入中">
      <ElSkeleton :rows="3" animated />
    </div>
    <p v-if="importError" class="hg-detail-error" role="alert">
      {{ importError }}
      <ElButton size="small" @click="onImportStart">重试</ElButton>
    </p>
    <div v-if="report" class="hg-report">
      <p class="hg-report__summary tabular">
        共 {{ report.total }} 行 · 新建 {{ report.created }} · 更新 {{ report.updated }} · 错误
        {{ report.errors.length }} 行
      </p>
      <p v-if="taskStatus !== ''" class="hg-report__task tabular">任务状态：{{ taskStatus }}</p>
      <EmptyState
        v-if="report.errors.length === 0"
        title="全部导入成功"
        description="无行级错误，学生档案已写入。"
      />
      <ElTable v-else :data="report.errors" class="hg-table" :stripe="false" row-key="row">
        <ElTableColumn prop="row" label="行号" width="90" />
        <ElTableColumn prop="student_id" label="学号" min-width="140" />
        <ElTableColumn prop="message" label="错误原因" min-width="220" />
      </ElTable>
    </div>
    <template #footer>
      <ElButton @click="emit('update:open', false)">关闭</ElButton>
    </template>
  </ElDialog>
</template>

<script setup lang="ts">
import {
  ElButton,
  ElDialog,
  ElIcon,
  ElSkeleton,
  ElTable,
  ElTableColumn,
  ElUpload,
} from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import { useStudentImport } from './useStudentImport'

defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  imported: []
}>()

const {
  pickedName,
  importing,
  importError,
  report,
  taskStatus,
  templateColumns,
  onFilePicked,
  onImportStart,
  onImportClosed,
} = useStudentImport({
  onImported: () => emit('imported'),
})
</script>

<style scoped lang="scss" src="../_styles/students.scss"></style>

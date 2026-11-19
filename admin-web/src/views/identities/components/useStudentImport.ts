import { onUnmounted, ref } from 'vue'
import type { Ref } from 'vue'
import {
  getImportTask,
  importStudents,
  IMPORT_TEMPLATE_COLUMNS,
  type ImportReport,
} from '@/api/students'
import type { UploadFile } from 'element-plus'
import { ApiError } from '@/api/types'

/** useStudentImport 对外暴露的状态与动作（显式返回类型，满足门禁） */
export interface UseStudentImportResult {
  pickedName: Ref<string>
  importing: Ref<boolean>
  importError: Ref<string | null>
  report: Ref<ImportReport | null>
  taskStatus: Ref<string>
  templateColumns: readonly string[]
  onFilePicked: (file: UploadFile) => void
  onImportStart: () => Promise<void>
  onImportClosed: () => void
}

export function useStudentImport(options: { onImported: () => void }): UseStudentImportResult {
  const pickedFile = ref<File | null>(null)
  const pickedName = ref('')
  const importing = ref(false)
  const importError = ref<string | null>(null)
  const report = ref<ImportReport | null>(null)
  const taskStatus = ref('')
  const templateColumns = IMPORT_TEMPLATE_COLUMNS

  let pollTimer: ReturnType<typeof setInterval> | null = null

  function stopPolling(): void {
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  function startPolling(taskId: string): void {
    stopPolling()
    pollTimer = setInterval(() => {
      void (async () => {
        try {
          const task = await getImportTask(taskId)
          taskStatus.value = task.status
          if (task.report !== undefined && task.report !== null) {
            report.value = task.report
          }
          if (task.status === 'done' || task.status === 'failed') {
            stopPolling()
            if (task.status === 'done') options.onImported()
            if (task.status === 'failed') {
              importError.value = task.error ?? '后台导入失败，请重试'
            }
          }
        } catch (error) {
          stopPolling()
          importError.value = error instanceof ApiError ? error.message : '任务查询失败'
        }
      })()
    }, 1500)
  }

  function onFilePicked(file: UploadFile): void {
    const raw = file.raw
    if (raw === undefined) return
    pickedFile.value = raw
    pickedName.value = raw.name
    importError.value = null
    report.value = null
    taskStatus.value = ''
  }

  async function onImportStart(): Promise<void> {
    if (pickedFile.value === null) {
      importError.value = '请先选择 xlsx 文件'
      return
    }
    importing.value = true
    importError.value = null
    report.value = null
    taskStatus.value = ''
    try {
      const result = await importStudents(pickedFile.value)
      if ('total' in result) {
        report.value = result
        taskStatus.value = 'done'
        options.onImported()
      } else {
        taskStatus.value = 'running'
        startPolling(result.task_id)
      }
    } catch (error) {
      importError.value = error instanceof ApiError ? error.message : '导入失败，请重试'
    } finally {
      importing.value = false
    }
  }

  function onImportClosed(): void {
    stopPolling()
    pickedFile.value = null
    pickedName.value = ''
    importing.value = false
    importError.value = null
    taskStatus.value = ''
  }

  onUnmounted(() => {
    stopPolling()
  })

  return {
    pickedName,
    importing,
    importError,
    report,
    taskStatus,
    templateColumns,
    onFilePicked,
    onImportStart,
    onImportClosed,
  }
}

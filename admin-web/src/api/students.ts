// ===========================================================================
// 学生档案 API —— 学生列表/详情/导入模板/批量导入
// URL 常量集中在此，组件中禁止硬编码路径
// ===========================================================================

import { get } from './request'
import http from './request'
import type { IdentityPage, IdentityResolution, Vehicle } from './identity'

const ADMIN_BASE = '/v1/admin'

/** 学生档案 */
export interface Student {
  student_id: string
  user_id: string | null
  name: string
  gender: string | null
  college: string | null
  class_name: string | null
  grade: string | null
  dorm_id: string | null
  phone: string | null
  avatar: string | null
  status: string
  created_at: string
  updated_at: string
}

/** 学生详情（含名下车辆与近期判定，复用 identity.ts 的 Vehicle 类型） */
export interface StudentDetail {
  student: Student
  vehicles: Vehicle[]
  resolutions: IdentityResolution[]
}

/** 学生查询参数（counselor 仅返回所带班级，由后端强制） */
export interface StudentQuery {
  page?: number
  page_size?: number
  sort?: 'student_id' | 'name' | 'class_name'
  order?: 'asc' | 'desc'
  keyword?: string
  college?: string
  status?: string
}

/** 单行导入错误 */
export interface ImportRowError {
  row: number
  student_id: string
  message: string
}

/** 导入结果报告 */
export interface ImportReport {
  total: number
  created: number
  updated: number
  errors: ImportRowError[]
}

/** 大文件异步受理响应 */
export interface ImportAccepted {
  task_id: string
  status: string
}

/** 导入任务状态 */
export interface ImportTask {
  task_id: string
  status: 'running' | 'done' | 'failed'
  report?: ImportReport | null
  error?: string
}

/** 模板列说明（与后端 TEMPLATE_HEADERS 严格一致） */
export const IMPORT_TEMPLATE_COLUMNS: readonly string[] = [
  '学号',
  '姓名',
  '性别',
  '学院',
  '班级',
  '年级',
  '宿舍',
  '手机号',
] as const

/** 学生列表 */
export function listStudents(query: StudentQuery): Promise<IdentityPage<Student>> {
  return get<IdentityPage<Student>>(`${ADMIN_BASE}/students`, query, { silent: true })
}

/** 学生详情 */
export function getStudentDetail(studentId: string): Promise<StudentDetail> {
  return get<StudentDetail>(`${ADMIN_BASE}/students/${encodeURIComponent(studentId)}`, undefined, {
    silent: true,
  })
}

/** 下载导入模板（xlsx 二进制） */
export async function downloadImportTemplate(): Promise<Blob> {
  const response = await http.get(`${ADMIN_BASE}/students/template`, {
    responseType: 'blob',
    silent: true,
  })
  return response.data as Blob
}

/** 批量导入（FormData 上传 xlsx；小文件直接返回报告，大文件返回 202 + task_id） */
export async function importStudents(file: File): Promise<ImportReport | ImportAccepted> {
  const form = new FormData()
  form.append('file', file, file.name)
  const response = await http.post(`${ADMIN_BASE}/students/import`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    silent: true,
  })
  const body = response.data as ImportReport | ImportAccepted
  return body
}

/** 查询大文件导入任务状态 */
export function getImportTask(taskId: string): Promise<ImportTask> {
  return get<ImportTask>(
    `${ADMIN_BASE}/students/import/tasks/${encodeURIComponent(taskId)}`,
    undefined,
    { silent: true },
  )
}

/** 触发浏览器下载 Blob */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

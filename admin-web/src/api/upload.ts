// ===========================================================================
// 上传请求实例 —— 独立封装，带进度回调与前置校验
// 与主实例共用鉴权，但响应不做 { code, data } 解包（返回原始响应体）
// ===========================================================================

import axios, { type AxiosProgressEvent, type AxiosInstance } from 'axios'
import { ApiError } from './types'
import { getAccessToken } from './request'

/** 单文件大小上限：20MB */
export const MAX_UPLOAD_SIZE = 20 * 1024 * 1024

/** 允许上传的图片类型 */
export const ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp'] as const

/** 上传前置校验结果 */
export interface UploadValidationResult {
  valid: boolean
  reason?: string
}

/**
 * 上传前校验：大小与类型。
 * 在发起请求前拦截，避免浪费带宽。
 */
export function validateUpload(
  file: File,
  allowedTypes: readonly string[] = ALLOWED_IMAGE_TYPES,
): UploadValidationResult {
  if (file.size > MAX_UPLOAD_SIZE) {
    return {
      valid: false,
      reason: `文件大小超过 ${Math.round(MAX_UPLOAD_SIZE / 1024 / 1024)}MB 上限`,
    }
  }
  if (!allowedTypes.includes(file.type)) {
    return { valid: false, reason: `不支持的文件类型：${file.type || '未知'}` }
  }
  return { valid: true }
}

const upload: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api',
  timeout: 120_000,
})

upload.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

upload.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status ?? 0
    const body = error.response?.data as { message?: string } | undefined
    return Promise.reject(
      new ApiError({
        status,
        code: status,
        message: body?.message ?? error.message ?? '上传失败',
        traceId: error.response?.headers?.['x-trace-id'] as string | undefined,
      }),
    )
  },
)

/**
 * 上传单文件。
 * @param url 上传地址
 * @param file 文件对象
 * @param onProgress 进度回调（0-100）
 */
export async function uploadFile<T>(
  url: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<T> {
  const validation = validateUpload(file)
  if (!validation.valid) {
    throw new ApiError({
      status: 0,
      code: ApiErrorCodeLocal.VALIDATION_ERROR,
      message: validation.reason ?? '文件校验未通过',
    })
  }

  const form = new FormData()
  form.append('file', file)

  const response = await upload.post<{ code: number; data: T; message: string }>(url, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (event: AxiosProgressEvent) => {
      if (!onProgress) return
      const percent = event.total ? Math.round((event.loaded / event.total) * 100) : 0
      onProgress(percent)
    },
  })

  return response.data.data
}

/** 本地错误码（避免与 ApiErrorCode 枚举耦合，语义相同） */
const ApiErrorCodeLocal = {
  VALIDATION_ERROR: 422,
} as const

export default upload

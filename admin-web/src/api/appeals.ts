// ===========================================================================
// 申诉处理 API —— 管理端列表 / 裁决（成立冲正 / 驳回）
// URL 常量集中在此，组件中禁止硬编码路径
// ===========================================================================

import { get, post } from './request'

const ADMIN_BASE = '/v1/admin/appeals'

/** 申诉状态（后端 Appeal.status 收敛为 pending / upheld / rejected，新写入只用三态） */
export type AppealStatus = 'pending' | 'submitted' | 'processing' | 'upheld' | 'rejected'

/** 申诉列表项（与后端 AppealResponse 对齐） */
export interface AppealListItem {
  appeal_id: string
  decision_id: string
  student_id: string
  reason: string
  attachments: string[] | Record<string, unknown>[] | null
  status: AppealStatus | string
  handler: string | null
  handle_note: string | null
  resolved_at: string | null
  created_at: string | null
}

/** 申诉列表包络 */
export interface AppealPage {
  items: AppealListItem[]
  total: number
  page: number
  page_size: number
}

/** 申诉查询参数（后端白名单：page / page_size / status） */
export interface AppealQuery {
  page?: number
  page_size?: number
  status?: AppealStatus | ''
  /** 仅前端本地过滤：按学号/申诉编号关键字筛选 */
  keyword?: string
}

/** 裁决请求体（处理意见必填由前端校验，后端允许空串兜底） */
export interface AppealResolvePayload {
  upheld: boolean
  note: string
}

/** 申诉列表（管理端多维筛选：状态服务端过滤，关键字前端本地过滤） */
export async function listAppeals(query: AppealQuery): Promise<AppealPage> {
  const params: Record<string, unknown> = {
    page: query.page,
    page_size: query.page_size,
  }
  if (query.status !== undefined && query.status !== '') params.status = query.status
  const page = await get<AppealPage>(ADMIN_BASE, params, { silent: true })
  const keyword = query.keyword?.trim() ?? ''
  if (keyword === '') return page
  const lower = keyword.toLowerCase()
  const filtered = page.items.filter(
    (item) =>
      item.student_id.toLowerCase().includes(lower) ||
      item.appeal_id.toLowerCase().includes(lower) ||
      item.decision_id.toLowerCase().includes(lower),
  )
  return { ...page, items: filtered, total: filtered.length }
}

/** 申诉裁决：成立冲正（返还积分 + 回流样本）/ 驳回（只改状态） */
export function resolveAppeal(
  appealId: string,
  payload: AppealResolvePayload,
): Promise<AppealListItem> {
  return post<AppealListItem>(`${ADMIN_BASE}/${encodeURIComponent(appealId)}/resolve`, payload, {
    silent: true,
  })
}

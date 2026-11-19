// ===========================================================================
// 总览状态 —— 指标、趋势、点位健康
//
// 缓存策略：
//   后端已有 30s 响应缓存；前端在 store 内再保留一份快照，
//   切换路由回来时先渲染快照（避免空白闪烁），再后台刷新。
//   快照持久化到 localStorage，刷新浏览器也能秒出内容。
// ===========================================================================

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as dashboardApi from '@/api/dashboard'
import type { DashboardOverview, PointHealthItem } from '@/api/dashboard'

export const useDashboardStore = defineStore(
  'dashboard',
  () => {
    // ---------- 数据 ----------
    const overview = ref<DashboardOverview | null>(null)
    const pointHealth = ref<PointHealthItem[]>([])
    const loading = ref(false)
    const error = ref<string | null>(null)
    const lastUpdated = ref<string | null>(null)

    // ---------- 派生 ----------
    const today = computed(() => overview.value?.today ?? null)
    const comparison = computed(() => overview.value?.comparison ?? null)
    const wearRateSeries = computed(() => overview.value?.trends.wear_rate ?? [])
    const violationsByHour = computed(() => overview.value?.trends.violations_by_hour ?? [])

    /** 头盔状态分布（环形图）：已佩戴 / 未佩戴 / 证据不足 */
    const helmetDistribution = computed(() => {
      const t = today.value
      if (!t) return []
      return [
        { name: '已佩戴', value: t.judged - t.violations, tone: 'success' },
        { name: '未佩戴', value: t.violations, tone: 'danger' },
        { name: '证据不足', value: t.unknown, tone: 'neutral' },
      ]
    })

    /** 是否有任何数据（用于区分「加载中」与「空」） */
    const hasData = computed(() => overview.value !== null)

    // ---------- 加载 ----------
    async function load(force = false): Promise<void> {
      // 已有新鲜快照且未强制刷新时跳过（后端有 30s 缓存）。
      if (!force && overview.value && !error.value) return
      loading.value = true
      error.value = null
      try {
        const result = await dashboardApi.getOverview()
        overview.value = result
        pointHealth.value = result.point_health
        lastUpdated.value = result.generated_at
      } catch (err) {
        error.value = err instanceof Error ? err.message : '总览数据加载失败'
      } finally {
        loading.value = false
      }
    }

    async function refresh(): Promise<void> {
      await load(true)
    }

    function clear(): void {
      overview.value = null
      pointHealth.value = []
      error.value = null
      lastUpdated.value = null
    }

    return {
      overview,
      pointHealth,
      loading,
      error,
      lastUpdated,
      today,
      comparison,
      wearRateSeries,
      violationsByHour,
      helmetDistribution,
      hasData,
      load,
      refresh,
      clear,
    }
  },
  {
    persist: {
      key: 'hg.dashboard',
      storage: localStorage,
      // 只持久化最近一次成功的快照：刷新页面先渲染缓存，
      // 再由 load() 静默刷新为最新数据。
      pick: ['overview', 'pointHealth', 'lastUpdated'],
    },
  },
)

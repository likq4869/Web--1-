<template>
  <div class="hg-dashboard">
    <PageHeader title="总览" description="校园骑行安全态势与关键指标">
      <template #actions>
        <ElButton :loading="store.loading" @click="store.refresh()">刷新</ElButton>
      </template>
    </PageHeader>

    <!-- ============ 错误态 ============ -->
    <div v-if="store.error && !store.hasData" class="hg-dashboard__error" role="alert">
      <p class="hg-dashboard__error-text">{{ store.error }}</p>
      <ElButton size="small" @click="store.refresh()">重试</ElButton>
    </div>

    <!-- ============ 加载态：骨架屏 ============ -->
    <template v-else-if="store.loading && !store.hasData">
      <div class="hg-dashboard__stats">
        <div v-for="n in 6" :key="n" class="hg-dashboard__skeleton-card" aria-busy="true">
          <span class="hg-dashboard__skeleton-bar hg-dashboard__skeleton-bar--label" />
          <span class="hg-dashboard__skeleton-bar hg-dashboard__skeleton-bar--value" />
          <span class="hg-dashboard__skeleton-bar" />
        </div>
      </div>
      <div class="hg-dashboard__grid">
        <div v-for="n in 4" :key="n" class="hg-dashboard__skeleton-panel" aria-busy="true" />
      </div>
    </template>

    <!-- ============ 数据态 ============ -->
    <template v-else-if="store.today">
      <!-- 指标卡：tone 决定趋势颜色，佩戴率↑ 为 success，违规↑ 为 danger -->
      <div class="hg-dashboard__stats">
        <StatCard
          label="今日通行"
          :value="formatInt(store.today.passes)"
          unit="人次"
          tone="primary"
          :trend="passesTrend"
        />
        <StatCard
          label="今日提醒"
          :value="formatInt(store.today.violations)"
          unit="人次"
          tone="danger"
          :trend="violationsTrend"
        />
        <StatCard
          label="头盔佩戴率"
          :value="formatPercent(store.today.wear_rate)"
          tone="success"
          :trend="wearRateTrend"
        />
        <StatCard
          label="待审批"
          :value="formatInt(store.overview?.pending_reviews ?? 0)"
          unit="条"
          tone="warning"
          description="需人工复核的决策"
        />
        <StatCard
          label="在线点位"
          :value="`${store.overview?.points.online ?? 0}/${store.overview?.points.total ?? 0}`"
          tone="neutral"
          description="采集设备在线情况"
        />
        <StatCard
          label="身份绑定率"
          :value="formatPercent(identityBindRate)"
          tone="success"
          :description="`活跃 ${formatInt(store.overview?.students.active ?? 0)} 人`"
        />
      </div>

      <!-- 图表区 -->
      <div class="hg-dashboard__grid">
        <!-- 佩戴率趋势（面积图） -->
        <section class="hg-dashboard__panel hg-dashboard__panel--wide">
          <header class="hg-dashboard__panel-head">
            <h2 class="hg-dashboard__panel-title">佩戴率趋势</h2>
            <span class="hg-dashboard__panel-sub">近 30 天</span>
          </header>
          <VChart
            v-if="wearRateOption"
            class="hg-dashboard__chart"
            :option="wearRateOption"
            autoresize
          />
          <EmptyState v-else title="暂无趋势数据" description="所选时间范围内还没有采集记录。" />
        </section>

        <!-- 头盔状态分布（环形图） -->
        <section class="hg-dashboard__panel">
          <header class="hg-dashboard__panel-head">
            <h2 class="hg-dashboard__panel-title">头盔状态分布</h2>
          </header>
          <VChart
            v-if="donutChartOption"
            class="hg-dashboard__chart"
            :option="donutChartOption"
            autoresize
          />
          <EmptyState v-else title="暂无分布数据" description="今日还没有判定记录。" />
          <ul v-if="store.helmetDistribution.length" class="hg-dashboard__legend">
            <li v-for="item in store.helmetDistribution" :key="item.name">
              <span class="hg-dashboard__legend-dot" :class="`is-${item.tone}`" />
              <span class="hg-dashboard__legend-name">{{ item.name }}</span>
              <span class="hg-dashboard__legend-value tabular">{{ item.value }}</span>
            </li>
          </ul>
        </section>

        <!-- 点位健康表 -->
        <section class="hg-dashboard__panel">
          <header class="hg-dashboard__panel-head">
            <h2 class="hg-dashboard__panel-title">点位健康</h2>
          </header>
          <table v-if="store.pointHealth.length" class="hg-dashboard__table">
            <thead>
              <tr>
                <th>点位</th>
                <th>状态</th>
                <th class="is-num">FPS</th>
                <th class="is-num">今日事件</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="point in store.pointHealth" :key="point.source_id">
                <td>{{ point.name || point.source_id }}</td>
                <td>
                  <span class="hg-dashboard__status" :class="`is-${point.status}`">
                    {{ pointStatusLabel(point.status) }}
                  </span>
                </td>
                <td class="is-num tabular">{{ point.fps ?? '—' }}</td>
                <td class="is-num tabular">{{ point.today_events }}</td>
              </tr>
            </tbody>
          </table>
          <EmptyState v-else title="暂无点位数据" description="尚未接入采集设备。" />
        </section>

        <!-- 违规时段分布（横向条形） -->
        <section class="hg-dashboard__panel">
          <header class="hg-dashboard__panel-head">
            <h2 class="hg-dashboard__panel-title">提醒时段分布</h2>
          </header>
          <VChart v-if="hourOption" class="hg-dashboard__chart" :option="hourOption" autoresize />
          <EmptyState v-else title="暂无时段数据" description="今日还没有提醒记录。" />
        </section>
      </div>
    </template>

    <!-- ============ 空态 ============ -->
    <EmptyState
      v-else
      title="暂无总览数据"
      description="接入采集设备后，这里会展示校园骑行安全态势与关键指标。"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { ElButton } from 'element-plus'
import VChart from 'vue-echarts'
import PageHeader from '@/components/PageHeader.vue'
import StatCard, { type StatTrend } from '@/components/StatCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import { useDashboardStore } from '@/stores/dashboard'
import { barOption, donutOption, lineAreaOption } from '@/charts/theme'
import type { EChartsOption } from 'echarts'

const store = useDashboardStore()

/** 身份绑定率 = 活跃学生 / 注册学生 */
const identityBindRate = computed(() => {
  const students = store.overview?.students
  if (!students || students.registered === 0) return null
  return students.active / students.registered
})

// ---------------- 指标卡趋势 ----------------

const passesTrend = computed<StatTrend | undefined>(() => {
  const delta = store.comparison?.passes_delta
  if (delta === undefined || delta === null) return undefined
  return {
    value: `${delta > 0 ? '+' : ''}${delta}`,
    direction: delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat',
    label: '较昨日',
  }
})

const violationsTrend = computed<StatTrend | undefined>(() => {
  const delta = store.comparison?.violations_delta
  if (delta === undefined || delta === null) return undefined
  return {
    value: `${delta > 0 ? '+' : ''}${delta}`,
    direction: delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat',
    label: '较昨日',
  }
})

const wearRateTrend = computed<StatTrend | undefined>(() => {
  const delta = store.comparison?.wear_rate_delta
  if (delta === undefined || delta === null) return undefined
  return {
    value: `${delta > 0 ? '+' : ''}${(delta * 100).toFixed(1)}%`,
    direction: delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat',
    label: '较昨日',
  }
})

// ---------------- 图表配置 ----------------

const wearRateOption = computed<EChartsOption | null>(() => {
  const series = store.wearRateSeries
  if (series.length === 0) return null
  return lineAreaOption({
    labels: series.map((point) => point.date.slice(5)),
    values: series.map((point) => Number((point.wear_rate * 100).toFixed(2))),
    valueFormatter: (value) => `${value.toFixed(1)}%`,
  })
})

const donutChartOption = computed<EChartsOption | null>(() => {
  const items = store.helmetDistribution
  if (items.length === 0) return null
  const palette = ['var(--color-success)', 'var(--color-danger)', 'var(--color-text-3)']
  const resolved = items.map((item, index) => ({
    name: item.name,
    value: item.value,
    color: resolveColor(palette[index] ?? palette[0]),
  }))
  const total = store.today?.judged ?? 0
  return donutOption({
    items: resolved,
    total,
    totalLabel: '今日已判定',
  })
})

const hourOption = computed<EChartsOption | null>(() => {
  const series = store.violationsByHour
  if (series.length === 0) return null
  // 只展示有记录的小时段，避免 24 根空条。
  const active = series.filter((point) => point.count > 0)
  if (active.length === 0) return null
  return barOption({
    categories: active.map((point) => `${point.hour} 时`),
    values: active.map((point) => point.count),
  })
})

/** 把 CSS 变量引用解析为实际色值（ECharts 不识别 var()） */
function resolveColor(value: string): string {
  if (!value.startsWith('var(')) return value
  const name = value.slice(4, -1).trim()
  const resolved = window.getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return resolved || '#8e8e93'
}

// ---------------- 格式化 ----------------

function formatInt(value: number): string {
  return Number.isFinite(value) ? value.toLocaleString('zh-CN') : '—'
}

function formatPercent(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—'
  return `${(value * 100).toFixed(1)}%`
}

function pointStatusLabel(status: string): string {
  const map: Record<string, string> = {
    online: '在线',
    offline: '离线',
    degraded: '降级',
  }
  return map[status] ?? status
}

onMounted(() => {
  // 有缓存快照时先渲染，load() 内部会跳过重复请求；
  // 无快照时静默拉取（错误由 store.error 承载）。
  void store.load()
})
</script>

<style scoped lang="scss" src="./_styles/index.scss"></style>

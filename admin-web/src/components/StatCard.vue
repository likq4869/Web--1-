<template>
  <article class="hg-stat-card" :class="`is-${tone}`">
    <header class="hg-stat-card__head">
      <span class="hg-stat-card__label">{{ label }}</span>
      <span v-if="icon" class="hg-stat-card__icon" aria-hidden="true">
        <slot name="icon">{{ icon }}</slot>
      </span>
    </header>

    <div class="hg-stat-card__value-row">
      <span class="hg-stat-card__value tabular">{{ value }}</span>
      <span v-if="unit" class="hg-stat-card__unit">{{ unit }}</span>
    </div>

    <footer v-if="trend" class="hg-stat-card__trend" :class="`is-${trendTone}`">
      <!-- 趋势同时以图标 + 文字表达，不依赖红绿区分 -->
      <span v-if="trend.direction === 'up'" class="hg-stat-card__trend-arrow" aria-hidden="true"
        >↑</span
      >
      <span
        v-else-if="trend.direction === 'down'"
        class="hg-stat-card__trend-arrow"
        aria-hidden="true"
        >↓</span
      >
      <span class="hg-stat-card__trend-text">
        {{ trend.value }}{{ trend.label ? ` ${trend.label}` : '' }}
      </span>
    </footer>

    <p v-else-if="description" class="hg-stat-card__desc">{{ description }}</p>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'

/** 趋势方向 */
export type TrendDirection = 'up' | 'down' | 'flat'

/** 趋势数据 */
export interface StatTrend {
  /** 数值，如 "+2.1%" 或 "5" */
  value: string
  /** 方向 */
  direction: TrendDirection
  /** 补充说明，如 "较昨日" */
  label?: string
}

/** 语义色调 —— 决定趋势颜色，避免滥用红色 */
export type StatTone = 'neutral' | 'primary' | 'success' | 'danger' | 'warning'

const props = withDefaults(
  defineProps<{
    /** 指标标签 */
    label: string
    /** 指标数值 */
    value: string | number
    /** 单位后缀 */
    unit?: string
    /** 趋势信息 */
    trend?: StatTrend
    /** 补充说明（无趋势时展示） */
    description?: string
    /** 图标（插槽或图标名） */
    icon?: string
    /** 卡片色调 */
    tone?: StatTone
  }>(),
  {
    unit: undefined,
    trend: undefined,
    description: undefined,
    icon: undefined,
    tone: 'neutral',
  },
)

/**
 * 趋势颜色由 tone 决定，而非方向。
 * 例如佩戴率上升是好事（success），违规数上升才是坏事（danger）。
 */
const trendTone = computed<StatTone>(() => {
  if (props.tone !== 'neutral') return props.tone
  if (!props.trend) return 'neutral'
  if (props.trend.direction === 'flat') return 'neutral'
  return props.trend.direction === 'up' ? 'success' : 'danger'
})
</script>

<style scoped lang="scss" src="./_styles/stat-card.scss"></style>

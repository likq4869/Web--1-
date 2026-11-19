<template>
  <div class="hg-factors">
    <div v-for="(factor, index) in factors" :key="index" class="hg-factors__item">
      <div class="hg-factors__head">
        <span class="hg-factors__name">{{ factor.name }}</span>
        <span class="hg-factors__value tabular">{{ formatValue(factor.value) }}</span>
      </div>

      <!-- 权重条：轨道浅色，填充主色；宽度按权重归一化 -->
      <div
        class="hg-factors__track"
        role="progressbar"
        :aria-label="`${factor.name} 权重`"
        :aria-valuenow="Math.round(normalizedWeight(factor) * 100)"
        aria-valuemin="0"
        aria-valuemax="100"
      >
        <div class="hg-factors__fill" :style="{ width: `${normalizedWeight(factor) * 100}%` }" />
      </div>

      <p v-if="factor.evidence" class="hg-factors__evidence">{{ factor.evidence }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

/** 决策因子 */
export interface FactorItem {
  /** 因子名称 */
  name: string
  /** 因子取值 */
  value: number
  /** 权重（0~1） */
  weight: number
  /** 人话证据说明 */
  evidence: string
}

const props = withDefaults(
  defineProps<{
    /** 因子列表 */
    factors?: FactorItem[]
  }>(),
  {
    factors: () => [],
  },
)

/** 最大权重（用于归一化宽度） */
const maxWeight = computed(() => {
  const values = props.factors.map((f) => Math.abs(f.weight)).filter((v) => v > 0)
  return values.length > 0 ? Math.max(...values) : 1
})

/** 归一化权重（0~1）：最大权重 = 100% */
function normalizedWeight(factor: FactorItem): number {
  if (maxWeight.value <= 0) return 0
  const ratio = Math.abs(factor.weight) / maxWeight.value
  return Math.min(1, Math.max(0, Number.isFinite(ratio) ? ratio : 0))
}

/** 格式化取值：0~1 显示百分比，其他按原值 */
function formatValue(value: number): string {
  if (!Number.isFinite(value)) return '—'
  if (Number.isInteger(value)) return String(value)
  if (Math.abs(value) <= 1) return value.toFixed(2)
  return value.toFixed(1)
}
</script>

<style scoped lang="scss">
.hg-factors {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.hg-factors__item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.hg-factors__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
}

.hg-factors__name {
  font-size: var(--text-body-size);
  font-weight: var(--text-subhead-weight);
  color: var(--color-text);
}

.hg-factors__value {
  font-size: var(--text-footnote-size);
  color: var(--color-text-2);
}

.hg-factors__track {
  height: var(--progress-height);
  background-color: var(--color-surface-2);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.hg-factors__fill {
  height: 100%;
  background-color: var(--color-primary);
  border-radius: var(--radius-full);
  // 权重条变化：200ms 线性过渡，克制不炫技。
  transition: width 200ms var(--ease-standard);
}

.hg-factors__evidence {
  margin: 0;
  font-size: var(--text-caption-size);
  line-height: var(--text-caption-line);
  color: var(--color-text-3);
}
</style>

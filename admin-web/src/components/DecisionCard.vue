<template>
  <button
    type="button"
    class="hg-dcard"
    :class="{ 'is-active': active, 'is-flash': flash }"
    :aria-current="active ? 'true' : undefined"
    @click="emit('select', decision.decision_id)"
  >
    <span class="hg-dcard__rail" :class="`is-${levelTone}`" aria-hidden="true" />

    <span class="hg-dcard__body">
      <span class="hg-dcard__top">
        <span class="hg-dcard__level" :class="`is-${levelTone}`">{{ decision.level }}</span>
        <span class="hg-dcard__level-label">{{ levelLabel }}</span>
        <span class="hg-dcard__conf tabular">{{ formatConfidence(decision.confidence) }}</span>
        <span class="hg-dcard__time tabular">{{ formatTime(decision.created_at) }}</span>
      </span>

      <span class="hg-dcard__meta">
        <span class="hg-dcard__point">{{ pointName }}</span>
        <span v-if="summary" class="hg-dcard__summary">{{ summary }}</span>
      </span>

      <span class="hg-dcard__foot">
        <span v-if="decision.student_id" class="hg-dcard__student">{{ studentName }}</span>
        <span v-if="decision.score_delta !== 0" class="hg-dcard__score tabular">
          {{ formatDelta(decision.score_delta) }} 分
        </span>
        <span v-else class="hg-dcard__score hg-dcard__score--zero">仅提醒</span>
      </span>
    </span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DecisionListItem } from '@/api/decisions'

/** 档位语义标签（避免学生端措辞；管理员端同样克制） */
const LEVEL_LABELS: Record<string, string> = {
  L0: '无需处理',
  L1: '现场提醒',
  L2: '记分提醒',
  L3: '重点关注',
  L4: '正向激励',
}

const props = withDefaults(
  defineProps<{
    /** 决策行 */
    decision: DecisionListItem
    /** 是否选中 */
    active?: boolean
    /** 新到达高亮（闪烁 2 次） */
    flash?: boolean
    /** 点位名称 */
    pointName?: string
    /** 学生显示名（脱敏） */
    studentName?: string
    /** 摘要（如「近 30 天第 4 次」） */
    summary?: string
  }>(),
  {
    active: false,
    flash: false,
    pointName: '',
    studentName: '',
    summary: '',
  },
)

const emit = defineEmits<{
  select: [decisionId: string]
}>()

/** 档位色调：L1 橙 / L2 橙深 / L3 红 / L4 绿 */
const levelTone = computed(() => {
  switch (props.decision.level) {
    case 'L1':
      return 'warning'
    case 'L2':
      return 'deep-warning'
    case 'L3':
      return 'danger'
    case 'L4':
      return 'success'
    default:
      return 'neutral'
  }
})

const levelLabel = computed(() => LEVEL_LABELS[props.decision.level] ?? props.decision.level)

function formatConfidence(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—'
  return value.toFixed(2)
}

function formatTime(value: string | null): string {
  if (!value) return ''
  const matched = /T(\d{2}:\d{2})/.exec(value)
  return matched ? matched[1] : ''
}

function formatDelta(delta: number): string {
  return delta > 0 ? `+${delta}` : String(delta)
}
</script>

<style scoped lang="scss" src="./_styles/decision-card.scss"></style>

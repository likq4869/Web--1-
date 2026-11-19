<template>
  <div class="hg-review-queue__wrap">
    <div v-if="loading" class="hg-review-queue__skeleton" aria-busy="true" aria-label="加载中">
      <div v-for="n in 5" :key="n" class="hg-review-queue__skeleton-item">
        <span class="hg-review-queue__bar hg-review-queue__bar--title" />
        <span class="hg-review-queue__bar" />
        <span class="hg-review-queue__bar hg-review-queue__bar--short" />
      </div>
    </div>

    <div v-else-if="error" class="hg-review-queue__error" role="alert">
      <p class="hg-review-queue__error-text">{{ error }}</p>
      <ElButton size="small" @click="emit('retry')">重试</ElButton>
    </div>

    <EmptyState v-else-if="items.length === 0" :title="emptyTitle" :description="emptyDescription">
      <template v-if="hasActiveFilters" #action>
        <ElButton size="small" @click="emit('clear-filters')">清除筛选</ElButton>
      </template>
    </EmptyState>

    <ul v-else class="hg-review-queue__list">
      <li v-for="item in items" :key="item.decision_id">
        <DecisionCard
          :decision="item"
          :active="item.decision_id === selectedId"
          :flash="isFlashing(item.decision_id)"
          :student-name="studentNameOf(item)"
          @select="emit('select', $event)"
        />
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { ElButton } from 'element-plus'
import DecisionCard from '@/components/DecisionCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { DecisionListItem } from '@/api/decisions'

defineProps<{
  items: DecisionListItem[]
  loading: boolean
  error: string | null
  selectedId: string | null
  hasActiveFilters: boolean
  emptyTitle: string
  emptyDescription: string
  studentNameOf: (item: DecisionListItem) => string
  isFlashing: (id: string) => boolean
}>()

const emit = defineEmits<{
  select: [decisionId: string]
  retry: []
  'clear-filters': []
}>()
</script>

<style scoped lang="scss">
.hg-review-queue__wrap {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.hg-review-queue__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}
.hg-review-queue__skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding-top: var(--space-3);
}
.hg-review-queue__skeleton-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
}
.hg-review-queue__bar {
  height: 12px;
  background-color: var(--color-surface-2);
  border-radius: var(--radius-sm);
  animation: review-pulse 1.4s var(--ease-standard) infinite;
  &--title {
    width: 45%;
    background-color: var(--color-surface-3);
  }
  &--short {
    width: 60%;
  }
}
@keyframes review-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}
.hg-review-queue__error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-8) var(--space-4);
}
.hg-review-queue__error-text {
  font-size: var(--text-body-size);
  color: var(--color-danger);
}
</style>

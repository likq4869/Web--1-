<template>
  <div class="hg-review-filters">
    <ElInput
      ref="searchInputRef"
      :model-value="keyword"
      placeholder="搜索学号"
      clearable
      size="small"
      @update:model-value="emit('update:keyword', $event)"
      @keyup.enter="emit('submit-search')"
      @clear="emit('submit-search')"
    >
      <template #prefix>
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" aria-hidden="true">
          <circle cx="11" cy="11" r="6.5" stroke="currentColor" stroke-width="1.6" />
          <path d="M16 16l4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
        </svg>
      </template>
    </ElInput>

    <div class="hg-review-filters__row">
      <ElSelect
        :model-value="pointFilter"
        placeholder="全部点位"
        size="small"
        clearable
        @update:model-value="emit('update:pointFilter', $event)"
        @change="emit('submit-filters')"
      >
        <ElOption v-for="p in pointOptions" :key="p.value" :label="p.label" :value="p.value" />
      </ElSelect>
      <ElSelect
        :model-value="sortBy"
        placeholder="排序"
        size="small"
        @update:model-value="emit('update:sortBy', $event)"
        @change="emit('submit-filters')"
      >
        <ElOption label="最新优先" value="created_at/desc" />
        <ElOption label="置信度高" value="confidence/desc" />
        <ElOption label="档位由低到高" value="level/asc" />
      </ElSelect>
    </div>

    <div class="hg-review-filters__tabs" role="tablist" aria-label="决策档位筛选">
      <button
        v-for="tab in levelTabs"
        :key="String(tab.value)"
        type="button"
        role="tab"
        class="hg-review-filters__tab"
        :class="{ 'is-active': levelFilter === tab.value }"
        :aria-selected="levelFilter === tab.value"
        @click="emit('set-level', tab.value)"
      >
        {{ tab.label }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElInput, ElOption, ElSelect } from 'element-plus'
import type { DecisionLevel } from '@/api/decisions'

export interface LevelTab {
  value: DecisionLevel | ''
  label: string
}

export interface PointOption {
  value: string
  label: string
}

defineProps<{
  keyword: string
  levelFilter: DecisionLevel | ''
  pointFilter: string
  sortBy: 'created_at/desc' | 'confidence/desc' | 'level/asc'
  pointOptions: PointOption[]
  levelTabs: LevelTab[]
}>()

const emit = defineEmits<{
  'update:keyword': [value: string]
  'update:pointFilter': [value: string]
  'update:sortBy': [value: 'created_at/desc' | 'confidence/desc' | 'level/asc']
  'submit-filters': []
  'submit-search': []
  'set-level': [value: DecisionLevel | '']
}>()

const searchInputRef = ref<InstanceType<typeof ElInput> | null>(null)

function focusSearch(): void {
  searchInputRef.value?.focus()
}

defineExpose({ focusSearch })
</script>

<style scoped lang="scss">
.hg-review-filters {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-bottom: var(--space-3);
  box-shadow: inset 0 -1px 0 var(--color-surface-2);
}
.hg-review-filters__row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-2);
}
.hg-review-filters__tabs {
  display: flex;
  gap: var(--space-1);
  padding: var(--space-1);
  background-color: var(--color-surface-2);
  border-radius: var(--radius-sm);
}
.hg-review-filters__tab {
  flex: 1;
  padding: var(--space-1) var(--space-2);
  font-size: var(--text-footnote-size);
  color: var(--color-text-2);
  background-color: transparent;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-standard);
  &.is-active {
    font-weight: var(--text-subhead-weight);
    color: var(--color-text);
    background-color: var(--color-surface);
  }
}
</style>

<template>
  <div class="hg-review-shortcuts">
    <button
      type="button"
      class="hg-review-shortcuts__toggle"
      :aria-expanded="!collapsed"
      @click="emit('toggle')"
    >
      <span class="hg-review-shortcuts__title">
        快捷键
        <span class="hg-review-shortcuts__hint">{{ collapsed ? '展开' : '收起' }}</span>
      </span>
    </button>
    <ul v-if="!collapsed" class="hg-review-shortcuts__list">
      <li v-for="item in hints" :key="item.keys">
        <kbd class="hg-review-shortcuts__kbd">{{ item.keys }}</kbd>
        <span class="hg-review-shortcuts__desc">{{ item.desc }}</span>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import type { ShortcutHint } from './useReviewShortcuts'

defineProps<{
  collapsed: boolean
  hints: ShortcutHint[]
}>()

const emit = defineEmits<{
  toggle: []
}>()
</script>

<style scoped lang="scss">
.hg-review-shortcuts {
  padding: var(--space-2) var(--space-4);
  background-color: var(--color-surface);
  border-radius: var(--radius-lg);
}
.hg-review-shortcuts__toggle {
  padding: 0;
  background: none;
  border: none;
  cursor: pointer;
}
.hg-review-shortcuts__title {
  font-size: var(--text-footnote-size);
  font-weight: var(--text-subhead-weight);
  color: var(--color-text-2);
}
.hg-review-shortcuts__hint {
  margin-left: var(--space-2);
  font-size: var(--text-caption-size);
  color: var(--color-text-3);
}
.hg-review-shortcuts__list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  margin: var(--space-2) 0 0;
  padding: 0;
  list-style: none;
}
.hg-review-shortcuts__kbd {
  display: inline-block;
  min-width: var(--space-6);
  margin-right: var(--space-1);
  padding: 1px var(--space-2);
  font-family: var(--font-family-mono);
  font-size: var(--text-caption-size);
  color: var(--color-text-2);
  background-color: var(--color-surface-2);
  border-radius: var(--radius-sm);
}
.hg-review-shortcuts__desc {
  font-size: var(--text-caption-size);
  color: var(--color-text-3);
}
</style>

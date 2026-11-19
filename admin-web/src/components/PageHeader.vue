<template>
  <header class="hg-page-header">
    <div class="hg-page-header__main">
      <h1 class="hg-page-header__title">{{ title }}</h1>
      <p v-if="description" class="hg-page-header__desc">{{ description }}</p>
    </div>

    <div v-if="$slots.actions" class="hg-page-header__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<script setup lang="ts">
defineProps<{
  /** 页面标题 */
  title: string
  /** 页面描述 */
  description?: string
}>()
</script>

<style scoped lang="scss">
.hg-page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--section-gap);
}

.hg-page-header__main {
  min-width: 0;
}

.hg-page-header__title {
  margin: 0;
  font-size: var(--text-title-size);
  line-height: var(--text-title-line);
  font-weight: var(--text-title-weight);
  letter-spacing: var(--text-title-spacing);
  color: var(--color-text);
}

.hg-page-header__desc {
  margin-top: var(--space-1);
  font-size: var(--text-footnote-size);
  line-height: var(--text-footnote-line);
  color: var(--color-text-2);
}

.hg-page-header__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}
</style>

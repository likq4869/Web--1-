<template>
  <div class="hg-empty" role="status">
    <!-- CSS 绘制的简单几何形图标（48px，--color-text-4），不使用 emoji -->
    <div class="hg-empty__icon" aria-hidden="true">
      <svg viewBox="0 0 48 48" width="48" height="48" fill="none">
        <rect
          x="10"
          y="14"
          width="28"
          height="22"
          rx="4"
          stroke="currentColor"
          stroke-width="1.5"
        />
        <path
          d="M17 22h14M17 28h9"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
        />
      </svg>
    </div>

    <p class="hg-empty__title">{{ title }}</p>
    <p v-if="description" class="hg-empty__desc">{{ description }}</p>

    <div v-if="$slots.action" class="hg-empty__action">
      <slot name="action" />
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    /** 主文案 */
    title?: string
    /** 补充说明 */
    description?: string
  }>(),
  {
    title: '暂无数据',
    description: undefined,
  },
)
</script>

<style scoped lang="scss">
.hg-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-12) var(--space-6);
  text-align: center;
}

.hg-empty__icon {
  color: var(--color-text-4);
  margin-bottom: var(--space-1);
}

.hg-empty__title {
  font-size: var(--text-body-size);
  font-weight: var(--text-subhead-weight);
  color: var(--color-text);
}

.hg-empty__desc {
  max-width: 420px;
  font-size: var(--text-footnote-size);
  line-height: var(--text-footnote-line);
  color: var(--color-text-2);
}

.hg-empty__action {
  margin-top: var(--space-3);
}
</style>

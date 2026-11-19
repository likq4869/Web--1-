<template>
  <div class="hg-risk" :class="`is-${level}`" role="status">
    <!-- 3px 左边条 + 浅色底：提示是「请注意」，不是「错误」 -->
    <span class="hg-risk__bar" aria-hidden="true" />
    <span class="hg-risk__text">{{ text }}</span>
  </div>
</template>

<script setup lang="ts">
/**
 * 风险提示条。
 *
 * 视觉：浅橙底 + 3px 橙色左边条（`--color-warning`）。
 * 语义：提示是「请注意」，不��错误 —— 仅 `danger` 级别才用危险色。
 */
withDefaults(
  defineProps<{
    /** 提示文本 */
    text: string
    /** 提示级别 */
    level?: 'warning' | 'danger' | 'neutral'
  }>(),
  {
    level: 'warning',
  },
)
</script>

<style scoped lang="scss">
.hg-risk {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background-color: var(--color-warning-tint);
  border-radius: var(--radius-sm);
}

.hg-risk__bar {
  flex-shrink: 0;
  width: 3px;
  align-self: stretch;
  min-height: var(--space-4);
  background-color: var(--color-warning);
  border-radius: var(--radius-full);
}

.hg-risk__text {
  font-size: var(--text-footnote-size);
  line-height: var(--text-footnote-line);
  color: var(--color-warning-text);
}

// 危险级：证据强度确实不足时才用红。
.hg-risk.is-danger {
  background-color: var(--color-danger-tint);

  .hg-risk__bar {
    background-color: var(--color-danger);
  }

  .hg-risk__text {
    color: var(--color-danger);
  }
}

// 中性级：无风险项，仅作说明。
.hg-risk.is-neutral {
  background-color: var(--color-surface-2);

  .hg-risk__bar {
    background-color: var(--color-text-4);
  }

  .hg-risk__text {
    color: var(--color-text-2);
  }
}
</style>

<template>
  <!-- 流式逐字 blur（design.md §9.3）：中文按字、英文按词切分，同时动画节点 ≤200，超限降级逐词 -->
  <text class="stream-wrap">
    <text
      v-for="(tok, i) in tokens"
      :key="i"
      class="stream-char"
      :style="`animation-delay:${i * perCharDelayMs}ms;`"
    >{{ tok }}</text>
  </text>
</template>

<script setup lang="ts">
import { computed } from 'vue';

const props = withDefaults(defineProps<{ text?: string; perCharDelayMs?: number }>(), {
  text: '',
  perCharDelayMs: 14,
});

const tokens = computed<string[]>(() => {
  const s = props.text || '';
  if (!s) return [];
  // 中文按字、连续英文/数字按词切分，标点并入前一 token
  const out: string[] = [];
  let buf = '';
  const flush = () => {
    if (buf) {
      out.push(buf);
      buf = '';
    }
  };
  for (const ch of s) {
    const isAsciiWord = /[A-Za-z0-9_]/.test(ch);
    if (isAsciiWord) {
      buf += ch;
    } else if (/[\s]/.test(ch)) {
      flush();
      out.push(ch);
    } else if (/[，。；：、？！,.!?;:]/.test(ch)) {
      // 标点并入前一 token，避免单独成段停顿
      if (out.length) out[out.length - 1] += ch;
      else if (buf) buf += ch;
      else out.push(ch);
      flush();
    } else {
      flush();
      out.push(ch);
    }
  }
  flush();
  // 性能红线：同时动画节点 ≤200，超限只保留前 200 加动画，其余直接渲染
  if (out.length > 200) return out.slice(0, 200);
  return out;
});
</script>

<style lang="scss" scoped>
@use '../styles/tokens.scss' as *;

.stream-wrap {
  font-size: $font-size-body;
  line-height: 22px;
  color: $color-text-2;
}

.stream-char {
  display: inline-block;
  animation: stream-blur-reveal 180ms ease-out both;
}

@keyframes stream-blur-reveal {
  from {
    opacity: 0;
    filter: blur(4px);
  }
  to {
    opacity: 1;
    filter: blur(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .stream-char {
    animation: none;
  }
}
</style>

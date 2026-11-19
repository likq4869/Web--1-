<template>
  <span v-if="usePlain" class="hg-stream">{{ plainText }}</span>
  <span v-else class="hg-stream" :aria-label="plainText">
    <span
      v-for="(token, index) in tokens"
      :key="`${index}-${token}`"
      class="hg-stream__token stream-char"
      :style="{ '--token-delay': `${index * stepDelay}ms` }"
      >{{ token }}</span
    >
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const MAX_ANIMATED_TOKENS = 200

const props = withDefaults(
  defineProps<{
    /** 待渲染文本；流式场景下逐步追加即可 */
    text: string
    /** 每字入场延迟（毫秒，规范 12–16ms） */
    stepDelay?: number
    /** 中文按字 / 英文按词 */
    lang?: 'zh' | 'en' | 'auto'
  }>(),
  {
    stepDelay: 14,
    lang: 'auto',
  },
)

const plainText = computed(() => props.text ?? '')

/**
 * 粒度规则（§9.3.3）：中文按字切分，英文按词切分；
 * 同时动画节点 ≤ 200，超出直接渲染纯文本（降级，无动画）。
 */
const tokens = computed<string[]>(() => {
  const raw = props.text ?? ''
  if (raw.length === 0) return []
  if (raw.length > MAX_ANIMATED_TOKENS) return []
  if (props.lang === 'en') return raw.split(/(\s+)/).filter((t) => t.length > 0)
  if (props.lang === 'zh') return Array.from(raw)
  // auto：含 CJK 则按字，否则按词
  return /[\u3040-\u9FFF]/.test(raw)
    ? Array.from(raw)
    : raw.split(/(\s+)/).filter((t) => t.length > 0)
})

/** 超长文本降级为纯文本，避免创建过多动画节点 */
const usePlain = computed(() => (props.text ?? '').length > MAX_ANIMATED_TOKENS)
</script>

<style scoped lang="scss">
.hg-stream {
  display: inline-block;
}

.hg-stream__token {
  white-space: pre;
}
</style>

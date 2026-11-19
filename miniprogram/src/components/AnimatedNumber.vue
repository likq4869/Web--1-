<template>
  <!-- 数字滚动（合规版）：tabular 锁死 + 300ms 内 count-up + 到位淡入；减弱动效时直接显示终值 -->
  <text class="num-anim"><text class="num">{{ display }}</text></text>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';

const props = withDefaults(defineProps<{ value?: number; decimals?: number }>(), {
  value: 0,
  decimals: 0,
});

const display = ref(format(props.value));

function format(v: number): string {
  if (!Number.isFinite(v)) return '--';
  return v.toFixed(props.decimals);
}

function animateTo(target: number): void {
  const from = 0;
  const start = Date.now();
  const dur = 300;
  let reduced = false;
  try {
    reduced =
      typeof window !== 'undefined' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch (_) {
    reduced = false;
  }
  if (reduced) {
    display.value = format(target);
    return;
  }
  const tick = () => {
    const t = Math.min(1, (Date.now() - start) / dur);
    // 过阻尼近似：快出慢收，一次到位无过冲
    const eased = 1 - Math.pow(1 - t, 3);
    display.value = format(from + (target - from) * eased);
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

watch(
  () => props.value,
  (v) => animateTo(typeof v === 'number' ? v : 0),
);

onMounted(() => animateTo(props.value));
</script>

<style lang="scss" scoped>
@use '../styles/tokens.scss' as *;

.num-anim {
  font-variant-numeric: tabular-nums;
  font-feature-settings: 'tnum' 1, 'lnum' 1;
  animation: hg-num-in $duration-fast $ease-overdamped both;
}

@keyframes hg-num-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .num-anim {
    animation: none;
  }
}
</style>

<template>
  <div class="hg-overlay" aria-hidden="false">
    <button
      v-for="(box, index) in visibleBoxes"
      :key="index"
      type="button"
      class="hg-overlay__box"
      :class="[`is-${box.tone ?? 'primary'}`, { 'is-selected': selectedIndex === index }]"
      :style="boxStyle(box)"
      :aria-label="`${box.label} ${formatConfidence(box.confidence)}`"
      @click="emit('select', index)"
    >
      <span class="hg-overlay__box-label">
        {{ box.label }} {{ formatConfidence(box.confidence) }}
      </span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

/** 归一化检测框（0~1），与容器同坐标系 */
export interface OverlayBox {
  x: number
  y: number
  width: number
  height: number
  label: string
  confidence?: number
  tone?: 'primary' | 'success' | 'danger' | 'warning'
}

const props = withDefaults(
  defineProps<{
    boxes?: OverlayBox[]
    selectedIndex?: number | null
    maxBoxes?: number
  }>(),
  {
    boxes: () => [],
    selectedIndex: null,
    maxBoxes: 12,
  },
)

const emit = defineEmits<{
  select: [index: number]
}>()

const visibleBoxes = computed(() => props.boxes.slice(0, props.maxBoxes))

function boxStyle(box: OverlayBox): Record<string, string> {
  const left = clamp(box.x)
  const top = clamp(box.y)
  return {
    left: `${left * 100}%`,
    top: `${top * 100}%`,
    width: `${clamp(box.width, 0.001, 1 - left) * 100}%`,
    height: `${clamp(box.height, 0.001, 1 - top) * 100}%`,
  }
}

function clamp(value: number, min = 0, max = 1): number {
  if (!Number.isFinite(value)) return min
  return Math.min(max, Math.max(min, value))
}

function formatConfidence(value?: number): string {
  if (value === undefined || !Number.isFinite(value)) return '—'
  return `${(value * 100).toFixed(1)}%`
}
</script>

<style scoped lang="scss" src="./_styles/detection-overlay.scss"></style>

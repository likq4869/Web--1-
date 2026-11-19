<template>
  <div class="hg-evidence">
    <!-- 图片区 + 检测框叠加 -->
    <div class="hg-evidence__stage" :style="stageStyle">
      <!-- 加载态：骨架占位，保持最终布局尺寸（不跳动） -->
      <div v-if="loading" class="hg-evidence__skeleton" aria-busy="true" aria-label="证据加载中">
        <span class="hg-evidence__skeleton-bar" />
        <span class="hg-evidence__skeleton-bar hg-evidence__skeleton-bar--short" />
      </div>

      <img
        v-if="imageUrl && !imageError"
        :src="imageUrl"
        :alt="alt"
        class="hg-evidence__image"
        @load="onImageLoad"
        @error="onImageError"
      />

      <div v-if="imageError" class="hg-evidence__placeholder">
        <span class="hg-evidence__placeholder-text">证据图片加载失败</span>
      </div>

      <!-- 检测框：归一化坐标叠加（与容器同坐标系） -->
      <button
        v-for="(box, index) in visibleBoxes"
        :key="index"
        type="button"
        class="hg-evidence__box"
        :class="[`is-${box.tone ?? 'primary'}`, { 'is-selected': selectedIndex === index }]"
        :style="boxStyle(box)"
        :aria-label="`${box.label} ${formatConfidence(box.confidence)}`"
        @click="selectBox(index)"
      >
        <span class="hg-evidence__box-label">
          {{ box.label }} {{ formatConfidence(box.confidence) }}
        </span>
      </button>

      <!-- 放大镜入口：点击查看原图 -->
      <button
        v-if="imageUrl && !imageError"
        type="button"
        class="hg-evidence__zoom"
        aria-label="查看原图"
        @click="zoomOpen = true"
      >
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true">
          <circle cx="11" cy="11" r="6.5" stroke="currentColor" stroke-width="1.6" />
          <path d="M16 16l4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
        </svg>
      </button>
    </div>

    <!-- 检测信息列表 -->
    <aside v-if="boxes.length" class="hg-evidence__panel">
      <h3 class="hg-evidence__panel-title">检测对象</h3>
      <ul class="hg-evidence__list">
        <li
          v-for="(box, index) in boxes"
          :key="index"
          class="hg-evidence__item"
          :class="{ 'is-selected': selectedIndex === index }"
          @click="selectBox(index)"
        >
          <span class="hg-evidence__item-swatch" :class="`is-${box.tone ?? 'primary'}`" />
          <span class="hg-evidence__item-label">{{ box.label }}</span>
          <span class="hg-evidence__item-conf tabular">{{ formatConfidence(box.confidence) }}</span>
        </li>
      </ul>

      <!-- 选中框详情 -->
      <div v-if="selectedBox" class="hg-evidence__detail">
        <p class="hg-evidence__detail-title">{{ selectedBox.label }}</p>
        <p class="hg-evidence__detail-text">
          置信度 {{ formatConfidence(selectedBox.confidence) }} · 位置
          {{ formatPercent(selectedBox.x) }}, {{ formatPercent(selectedBox.y) }}
        </p>
        <p v-if="selectedBox.detail" class="hg-evidence__detail-text">
          {{ selectedBox.detail }}
        </p>
      </div>
    </aside>

    <!-- 原图放大 -->
    <Teleport to="body">
      <div v-if="zoomOpen" class="hg-evidence__lightbox" @click.self="zoomOpen = false">
        <img :src="imageUrl" :alt="alt" class="hg-evidence__lightbox-image" />
        <button
          type="button"
          class="hg-evidence__lightbox-close"
          aria-label="关闭"
          @click="zoomOpen = false"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true">
            <path
              d="M6 6l12 12M18 6L6 18"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
            />
          </svg>
        </button>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

/** 检测框 —— 坐标为归一化值（0~1），与容器同坐标系 */
export interface EvidenceBox {
  /** 左边界比例 */
  x: number
  /** 上边界比例 */
  y: number
  /** 宽度比例 */
  width: number
  /** 高度比例 */
  height: number
  /** 标签文本 */
  label: string
  /** 置信度 0-1 */
  confidence?: number
  /** 语义色调 */
  tone?: 'primary' | 'success' | 'danger' | 'warning'
  /** 补充说明（选中时展示） */
  detail?: string
}

const props = withDefaults(
  defineProps<{
    /** 证据图片地址 */
    imageUrl: string
    /** 检测框列表 */
    boxes?: EvidenceBox[]
    /** 图片替代文本 */
    alt?: string
    /** 最大展示框数 —— 避免遮挡过多 */
    maxBoxes?: number
    /**
     * 原图宽度（像素）—— 与 `imageHeight` 共同决定容器宽高比。
     * 必须来自后端返回的原始图像尺寸，保证横竖图检测框不错位。
     */
    imageWidth?: number | null
    /**
     * 原图高度（像素）—— 与 `imageWidth` 共同决定容器宽高比。
     */
    imageHeight?: number | null
    /** 加载中 */
    loading?: boolean
  }>(),
  {
    boxes: () => [],
    alt: '检测证据图',
    maxBoxes: 12,
    imageWidth: null,
    imageHeight: null,
    loading: false,
  },
)

const imageError = ref(false)
const imageSize = ref<{ width: number; height: number } | null>(null)
const selectedIndex = ref<number | null>(null)
const zoomOpen = ref(false)

const visibleBoxes = computed(() => props.boxes.slice(0, props.maxBoxes))

/**
 * 容器宽高比。
 *
 * 坐标系一致性关键：检测框是归一化比例（0~1），容器必须与原图
 * **完全相同的宽高比**，否则横图/竖图的框都会整体偏移。
 * 优先用后端给的 `image_width / image_height`；缺失时退回图片
 * 实际渲染尺寸；再兜底 4:3 占位（避免布局跳动）。
 */
const stageStyle = computed(() => {
  if (props.imageWidth && props.imageHeight && props.imageWidth > 0 && props.imageHeight > 0) {
    return { aspectRatio: `${props.imageWidth} / ${props.imageHeight}` }
  }
  if (imageSize.value) {
    return { aspectRatio: `${imageSize.value.width} / ${imageSize.value.height}` }
  }
  return { aspectRatio: '4 / 3' }
})

const selectedBox = computed(() => {
  if (selectedIndex.value === null) return null
  return visibleBoxes.value[selectedIndex.value] ?? null
})

function boxStyle(box: EvidenceBox): Record<string, string> {
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

function formatPercent(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return `${(value * 100).toFixed(1)}%`
}

function selectBox(index: number): void {
  selectedIndex.value = selectedIndex.value === index ? null : index
}

function onImageLoad(event: Event): void {
  imageError.value = false
  const target = event.target as HTMLImageElement
  imageSize.value = { width: target.naturalWidth, height: target.naturalHeight }
}

function onImageError(): void {
  imageError.value = true
}

watch(
  () => props.imageUrl,
  () => {
    imageError.value = false
    imageSize.value = null
    selectedIndex.value = null
  },
)

watch(
  () => props.boxes,
  () => {
    selectedIndex.value = null
  },
)
</script>

<style scoped lang="scss" src="./_styles/evidence-viewer.scss"></style>

<style lang="scss">
// 原图放大层：Teleport 到 body，故用非 scoped 样式。
.hg-evidence__lightbox {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-8);
  background-color: var(--color-overlay);
}

.hg-evidence__lightbox-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: var(--radius-lg);
}

.hg-evidence__lightbox-close {
  position: absolute;
  top: var(--space-6);
  right: var(--space-6);
  display: flex;
  align-items: center;
  justify-content: center;
  width: var(--control-min-touch-target);
  height: var(--control-min-touch-target);
  color: var(--color-surface);
  background-color: transparent;
  border: none;
  border-radius: var(--radius-full);
  cursor: pointer;
}
</style>

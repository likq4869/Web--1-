<template>
  <div class="hg-config">
    <PageHeader title="点位标定" description="框选检测区域、计数线与提醒区，归一化存储">
      <template #actions>
        <ElSelect
          :model-value="selectedPointId"
          placeholder="选择点位"
          class="hg-config__select"
          @update:model-value="onPointChange"
        >
          <ElOption
            v-for="point in points"
            :key="point.source_id"
            :label="point.name || point.source_id"
            :value="point.source_id"
          />
        </ElSelect>
        <RouterLink class="hg-config__back" to="/monitor">返回实时监控</RouterLink>
      </template>
    </PageHeader>

    <div
      v-if="loading && !hasData"
      class="hg-config__skeleton"
      aria-busy="true"
      aria-label="加载中"
    />

    <div v-else-if="loadError && !hasData" class="hg-config__error" role="alert">
      <p class="hg-config__error-text">{{ loadError }}</p>
      <ElButton size="small" @click="reload">重试</ElButton>
    </div>

    <template v-else>
      <div class="hg-config__body">
        <section class="hg-config__stage" :aria-label="stageLabel">
          <div
            ref="canvasRef"
            class="hg-config__canvas"
            :style="{ aspectRatio: aspectRatio }"
            @pointerdown="onCanvasDown"
            @pointermove="onCanvasMove"
            @pointerup="onCanvasUp"
            @pointerleave="onCanvasUp"
          >
            <DetectionOverlay :boxes="overlayBoxes" />
            <div v-if="draftRoi" class="hg-config__roi" :style="rectToStyle(draftRoi)">
              <span class="hg-config__tag"
                >检测区 {{ formatNorm(draftRoi[0]) }} {{ formatNorm(draftRoi[1]) }}</span
              >
              <span class="hg-config__handle" @pointerdown.stop="onHandleDown" />
            </div>
            <div v-if="draftZone" class="hg-config__zone" :style="rectToStyle(draftZone)">
              <span class="hg-config__tag">提醒区</span>
            </div>
            <div class="hg-config__line" :style="lineToStyle(draftLine)">
              <span class="hg-config__tag">计数线 {{ formatNorm(draftLine) }}</span>
            </div>
            <div v-if="!evidence" class="hg-config__empty">
              <p class="hg-config__empty-title">暂无证据帧，仅展示标定底图</p>
              <p class="hg-config__empty-desc">标定仍可保存，生效后用于后续检测裁剪。</p>
            </div>
          </div>
          <p v-if="streamReason" class="hg-config__hint">{{ streamReason }}</p>
        </section>

        <section class="hg-config__panel" aria-label="标定数值">
          <h2 class="hg-config__panel-title">归一化坐标</h2>
          <div class="hg-config__grid">
            <label class="hg-config__field">
              <span>检测区 ROI</span>
              <ElInput
                :model-value="roiText"
                placeholder="x1,y1,x2,y2"
                @update:model-value="onRoiText"
              />
            </label>
            <label class="hg-config__field">
              <span>提醒区</span>
              <ElInput
                :model-value="zoneText"
                placeholder="x1,y1,x2,y2"
                @update:model-value="onZoneText"
              />
            </label>
            <label class="hg-config__field">
              <span>计数线高度</span>
              <ElInputNumber
                :model-value="draftLine"
                :min="0"
                :max="1"
                :step="0.01"
                @update:model-value="onLineNumber"
              />
            </label>
          </div>
          <p v-if="formError" class="hg-config__error-text" role="alert">{{ formError }}</p>
          <p v-if="saveError" class="hg-config__error-text" role="alert">{{ saveError }}</p>
          <div class="hg-config__row">
            <ElButton @click="resetDraft">重置</ElButton>
            <ElButton type="primary" :loading="saving" :disabled="!canEdit" @click="onSave">
              保存标定
            </ElButton>
          </div>
          <p v-if="!canEdit" class="hg-config__hint">当前角色仅可查看，保存需规则管理员三角色。</p>
          <p v-if="updatedText" class="hg-config__hint tabular">{{ updatedText }}</p>
        </section>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ElButton, ElInput, ElInputNumber, ElOption, ElSelect } from 'element-plus'
import DetectionOverlay from '@/components/DetectionOverlay.vue'
import PageHeader from '@/components/PageHeader.vue'
import { useAuthStore } from '@/stores/auth'
import { formatNorm, lineToStyle, rectToStyle } from './pointConfig'
import { usePointConfig } from './usePointConfig'

const auth = useAuthStore()
const canEdit = computed(() => auth.hasRole('super_admin', 'league_officer', 'admin'))

const config = usePointConfig()
const {
  points,
  selectedPointId,
  evidence,
  overlayBoxes,
  aspectRatio,
  stageLabel,
  streamReason,
  loading,
  loadError,
  hasData,
  draftRoi,
  draftZone,
  draftLine,
  roiText,
  zoneText,
  updatedText,
  formError,
  saveError,
  saving,
  canvasRef,
  onHandleDown,
  onCanvasDown,
  onCanvasMove,
  onCanvasUp,
  onRoiText,
  onZoneText,
  onLineNumber,
  resetDraft,
  onSave,
  reload,
  onPointChange,
} = config
</script>

<style scoped lang="scss" src="./_styles/point-config.scss"></style>

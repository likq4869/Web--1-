<template>
  <section class="hg-review-detail">
    <div v-if="detailLoading && !detail" class="hg-review-detail__skeleton" aria-busy="true">
      <span class="hg-review-detail__bar hg-review-detail__bar--block" />
      <span class="hg-review-detail__bar hg-review-detail__bar--block" />
      <span class="hg-review-detail__bar hg-review-detail__bar--block" />
    </div>

    <div v-else-if="detailError" class="hg-review-detail__error" role="alert">
      <p class="hg-review-detail__error-text">{{ detailError }}</p>
      <ElButton size="small" @click="emit('retry')">重试</ElButton>
    </div>

    <EmptyState
      v-else-if="!detail"
      title="请选择一条决策"
      description="从左侧队列选择待审决策，即可查看证据帧、决策因子与风险提示。"
    />

    <template v-else>
      <header class="hg-review-detail__head">
        <div class="hg-review-detail__title-row">
          <span class="hg-review-detail__level" :class="`is-${levelTone(detail.level)}`">
            {{ detail.level }}
          </span>
          <h2 class="hg-review-detail__title">{{ detailTitle }}</h2>
        </div>
        <p class="hg-review-detail__meta">
          {{ detail.event?.source_id ?? '—' }} · {{ formatTime(detail.event?.occurred_at) }} ·
          置信度 {{ formatConfidence(detail.confidence) }}
        </p>
      </header>

      <section class="hg-review-detail__section">
        <h3 class="hg-review-detail__section-title">证据帧</h3>
        <EvidenceViewer
          :image-url="snapshotUrl"
          :boxes="evidenceBoxes"
          :image-width="evidenceSize.width"
          :image-height="evidenceSize.height"
          :loading="detailLoading"
          alt="检测证据帧"
        />
      </section>

      <section v-if="factors.length" class="hg-review-detail__section">
        <h3 class="hg-review-detail__section-title">决策因子</h3>
        <FactorList :factors="factors" />
      </section>

      <section v-if="detail.identity_resolution" class="hg-review-detail__section">
        <h3 class="hg-review-detail__section-title">身份判定</h3>
        <dl class="hg-review-detail__kv">
          <div class="hg-review-detail__kv-row">
            <dt>判定方式</dt>
            <dd>{{ methodLabel(detail.identity_resolution.method) }}</dd>
          </div>
          <div class="hg-review-detail__kv-row">
            <dt>综合置信度</dt>
            <dd class="tabular">{{ formatPercent(detail.identity_resolution.confidence) }}</dd>
          </div>
          <div class="hg-review-detail__kv-row">
            <dt>车牌 / 外观 / 共现</dt>
            <dd class="tabular">
              {{ formatPercent(detail.identity_resolution.plate_confidence) }} /
              {{ formatPercent(detail.identity_resolution.appearance_confidence) }} /
              {{ formatPercent(detail.identity_resolution.cooccur_confidence) }}
            </dd>
          </div>
        </dl>
      </section>

      <section v-if="detail.student" class="hg-review-detail__section">
        <h3 class="hg-review-detail__section-title">学生概况</h3>
        <dl class="hg-review-detail__kv">
          <div class="hg-review-detail__kv-row">
            <dt>学号 / 姓名</dt>
            <dd>{{ maskStudentId(detail.student.student_id) }} · {{ detail.student.name }}</dd>
          </div>
          <div class="hg-review-detail__kv-row">
            <dt>学院 / 班级</dt>
            <dd>{{ detail.student.college ?? '—' }} / {{ detail.student.class_name ?? '—' }}</dd>
          </div>
          <div class="hg-review-detail__kv-row">
            <dt>当前积分</dt>
            <dd class="tabular">{{ detail.student.balance ?? '—' }} 分</dd>
          </div>
          <div class="hg-review-detail__kv-row">
            <dt>近 30 天佩戴率</dt>
            <dd class="tabular">{{ formatPercent(detail.student.compliance_rate) }}</dd>
          </div>
          <div class="hg-review-detail__kv-row">
            <dt>历史记分</dt>
            <dd class="tabular">
              近 30 天 {{ detail.student.violation_count_30d }} 次 · 累计
              {{ detail.student.violation_count_total }} 次
            </dd>
          </div>
        </dl>
      </section>

      <section v-if="detail.risk_hints?.length" class="hg-review-detail__section">
        <h3 class="hg-review-detail__section-title">风险提示</h3>
        <div class="hg-review-detail__risks">
          <RiskHint
            v-for="hint in detail.risk_hints"
            :key="hint.code"
            :text="hint.text"
            :level="hint.level"
          />
        </div>
      </section>

      <section class="hg-review-detail__section">
        <h3 class="hg-review-detail__section-title">建议话术（可编辑）</h3>
        <ElInput
          :model-value="editableMessage"
          type="textarea"
          :rows="2"
          maxlength="120"
          show-word-limit
          placeholder="学生端将展示这段说明"
          @update:model-value="emit('update:message', $event)"
        />
      </section>

      <footer v-if="canApprove" class="hg-review-detail__actions">
        <ElButton
          type="primary"
          :loading="acting"
          :disabled="acting || !selectedId"
          @click="emit('approve')"
        >
          批准
        </ElButton>
        <ElButton
          :loading="acting"
          :disabled="acting || !selectedId || adjustDisabled"
          @click="emit('open-adjust')"
        >
          降档
        </ElButton>
        <ElButton
          type="danger"
          plain
          :loading="acting"
          :disabled="acting || !selectedId"
          @click="emit('open-reject')"
        >
          驳回
        </ElButton>
        <ElButton :disabled="acting || batchCount === 0" @click="emit('open-batch')">
          批量批准{{ batchCount ? ` (${batchCount})` : '' }}
        </ElButton>
      </footer>

      <div v-if="batchResult" class="hg-review-detail__batch">
        <p class="hg-review-detail__batch-summary">
          批量处理完成：成功 {{ batchSuccess }} 条，失败 {{ batchFail }} 条
        </p>
        <ul v-if="batchFailures.length" class="hg-review-detail__batch-list">
          <li v-for="failure in batchFailures" :key="failure.decision_id">
            {{ failure.decision_id }}：{{ failure.error }}
          </li>
        </ul>
        <ElButton size="small" @click="emit('clear-batch')">关闭</ElButton>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { ElButton, ElInput } from 'element-plus'
import EmptyState from '@/components/EmptyState.vue'
import EvidenceViewer, { type EvidenceBox } from '@/components/EvidenceViewer.vue'
import FactorList, { type FactorItem } from '@/components/FactorList.vue'
import RiskHint from '@/components/RiskHint.vue'
import type { DecisionDetail } from '@/api/decisions'
import {
  formatConfidence,
  formatPercent,
  formatTime,
  levelTone,
  maskStudentId,
  methodLabel,
} from './reviewFormat'

defineProps<{
  detail: DecisionDetail | null
  detailLoading: boolean
  detailError: string | null
  detailTitle: string
  evidenceBoxes: EvidenceBox[]
  evidenceSize: { width: number | null; height: number | null }
  snapshotUrl: string
  factors: FactorItem[]
  editableMessage: string
  canApprove: boolean
  acting: boolean
  selectedId: string | null
  adjustDisabled: boolean
  batchCount: number
  batchResult: { items: { decision_id: string; ok: boolean; error: string | null }[] } | null
  batchSuccess: number
  batchFail: number
  batchFailures: { decision_id: string; ok: boolean; error: string | null }[]
}>()

const emit = defineEmits<{
  retry: []
  'update:message': [value: string]
  approve: []
  'open-adjust': []
  'open-reject': []
  'open-batch': []
  'clear-batch': []
}>()
</script>

<style scoped lang="scss" src="./_styles/review-detail.scss"></style>

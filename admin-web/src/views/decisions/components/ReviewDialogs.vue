<template>
  <div class="hg-review-dialogs">
    <ElDialog
      :model-value="adjustVisible"
      title="降档处理"
      width="420px"
      @update:model-value="emit('update:adjustVisible', $event)"
    >
      <p class="hg-review-dialogs__text">
        当前档位 <strong>{{ detailLevel }}</strong>，降档后分值将按下表变化（只降不升）。
      </p>
      <ul class="hg-review-dialogs__levels">
        <li v-for="option in adjustOptions" :key="option.level">
          <label class="hg-review-dialogs__option">
            <input
              :checked="targetLevel === option.level"
              type="radio"
              :value="option.level"
              name="target-level"
              @change="emit('update:targetLevel', option.level)"
            />
            <span class="hg-review-dialogs__option-text">
              {{ option.level }} · {{ option.label }} · {{ option.scoreDelta }} 分
            </span>
          </label>
        </li>
      </ul>
      <ElInput
        :model-value="adjustNote"
        type="textarea"
        :rows="2"
        maxlength="500"
        placeholder="降档说明（可选）"
        @update:model-value="emit('update:adjustNote', $event)"
      />
      <template #footer>
        <ElButton @click="emit('update:adjustVisible', false)">取消</ElButton>
        <ElButton type="primary" :loading="acting" @click="emit('confirm-adjust')"
          >确认降档</ElButton
        >
      </template>
    </ElDialog>

    <ElDialog
      :model-value="rejectVisible"
      title="驳回决策"
      width="420px"
      @update:model-value="emit('update:rejectVisible', $event)"
    >
      <p class="hg-review-dialogs__text">
        驳回理由将回流到误判训练集，请说明具体依据（至少 10 个字）。
      </p>
      <ElInput
        :model-value="rejectReason"
        type="textarea"
        :rows="3"
        maxlength="500"
        placeholder="例如：证据帧中骑行者佩戴头盔，模型误判"
        @update:model-value="emit('update:rejectReason', $event)"
      />
      <p
        v-if="rejectReason.length > 0 && rejectReason.trim().length < 10"
        class="hg-review-dialogs__error"
      >
        理由至少 10 个字
      </p>
      <template #footer>
        <ElButton @click="emit('update:rejectVisible', false)">取消</ElButton>
        <ElButton
          type="danger"
          :loading="acting"
          :disabled="rejectReason.trim().length < 10"
          @click="emit('confirm-reject')"
        >
          确认驳回
        </ElButton>
      </template>
    </ElDialog>

    <ElDialog
      :model-value="batchVisible"
      title="批量批准"
      width="420px"
      @update:model-value="emit('update:batchVisible', $event)"
    >
      <p class="hg-review-dialogs__text">
        将批准选中的 {{ selectedCount }} 条决策，单条失败不影响其他条目。
      </p>
      <ElInput
        :model-value="batchNote"
        type="textarea"
        :rows="2"
        maxlength="500"
        placeholder="批量备注（可选）"
        @update:model-value="emit('update:batchNote', $event)"
      />
      <template #footer>
        <ElButton @click="emit('update:batchVisible', false)">取消</ElButton>
        <ElButton type="primary" :loading="batchActing" @click="emit('confirm-batch')">
          确认批量批准
        </ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<script setup lang="ts">
import { ElButton, ElDialog, ElInput } from 'element-plus'
import type { DecisionLevel } from '@/api/decisions'

export interface AdjustOption {
  level: DecisionLevel
  label: string
  scoreDelta: number
}

defineProps<{
  adjustVisible: boolean
  rejectVisible: boolean
  batchVisible: boolean
  detailLevel: string
  adjustOptions: AdjustOption[]
  targetLevel: DecisionLevel | ''
  adjustNote: string
  rejectReason: string
  batchNote: string
  selectedCount: number
  acting: boolean
  batchActing: boolean
}>()

const emit = defineEmits<{
  'update:adjustVisible': [value: boolean]
  'update:rejectVisible': [value: boolean]
  'update:batchVisible': [value: boolean]
  'update:targetLevel': [value: DecisionLevel]
  'update:adjustNote': [value: string]
  'update:rejectReason': [value: string]
  'update:batchNote': [value: string]
  'confirm-adjust': []
  'confirm-reject': []
  'confirm-batch': []
}>()
</script>

<style scoped lang="scss">
.hg-review-dialogs__text {
  margin: 0 0 var(--space-3);
  font-size: var(--text-body-size);
  color: var(--color-text-2);
}
.hg-review-dialogs__levels {
  margin: 0 0 var(--space-3);
  padding: 0;
  list-style: none;
}
.hg-review-dialogs__option {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2);
  font-size: var(--text-body-size);
  cursor: pointer;
}
.hg-review-dialogs__option-text {
  color: var(--color-text);
}
.hg-review-dialogs__error {
  margin: var(--space-1) 0 0;
  font-size: var(--text-caption-size);
  color: var(--color-danger);
}
</style>

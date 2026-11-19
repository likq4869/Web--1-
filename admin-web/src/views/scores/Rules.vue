<template>
  <div>
    <PageHeader
      title="积分规则"
      description="扣分 / 加分 / 连续安全的条件与分值，只推演不直接写库"
    />

    <div class="hg-toolbar">
      <ElButton :loading="store.rulesLoading" @click="reload">刷新</ElButton>
      <RouterLink class="hg-scores__rules-link" to="/points">返回台账</RouterLink>
    </div>

    <DataTable
      :rows="store.rules"
      :loading="store.rulesLoading"
      :error="store.rulesError"
      :total="store.rules.length"
      :current-page="1"
      :page-size="pageSize"
      :show-pagination="false"
      :on-retry="reload"
      row-key="rule_id"
      empty-title="暂无积分规则"
      empty-description="规则为空时审批将回退默认口径，请联系管理员补配。"
    >
      <ElTableColumn prop="rule_id" label="规则 ID" min-width="140" />
      <ElTableColumn prop="name" label="名称" min-width="160" />
      <ElTableColumn label="类型" width="110">
        <template #default="{ row }">
          {{ ruleTypeLabel((row as ScoreRule).rule_type) }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="分值" width="90">
        <template #default="{ row }">
          <span class="tabular hg-delta" :data-tone="deltaTone((row as ScoreRule).score_change)">
            {{ formatDelta((row as ScoreRule).score_change) }}
          </span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="优先级" width="90">
        <template #default="{ row }">
          <span class="tabular">{{ (row as ScoreRule).priority }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="启用" width="90">
        <template #default="{ row }">
          <ElTag :type="(row as ScoreRule).enabled ? 'success' : 'info'" size="small">
            {{ (row as ScoreRule).enabled ? '启用' : '停用' }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作" width="170" fixed="right">
        <template #default="{ row }">
          <ElButton link type="primary" @click="openEdit(row as ScoreRule)">编辑</ElButton>
          <ElButton link type="primary" @click="openSimulate(row as ScoreRule)">试算</ElButton>
        </template>
      </ElTableColumn>
    </DataTable>

    <ElDrawer
      :model-value="editOpen"
      title="编辑规则"
      size="420px"
      @update:model-value="editOpen = $event"
    >
      <div v-if="editing" class="hg-rule-form">
        <ElInput
          :model-value="editing.name"
          placeholder="规则名称"
          @update:model-value="onEditName"
        />
        <ElSelect :model-value="editing.rule_type" @update:model-value="onEditType">
          <ElOption label="扣分" value="deduct" />
          <ElOption label="加分" value="award" />
          <ElOption label="连续安全" value="streak" />
        </ElSelect>
        <ElInputNumber
          :model-value="editing.score_change"
          :min="-100"
          :max="100"
          @update:model-value="onEditScore"
        />
        <ElInputNumber
          :model-value="editing.priority"
          :min="0"
          :max="1000"
          @update:model-value="onEditPriority"
        />
        <ElSwitch
          :model-value="editing.enabled"
          active-text="启用"
          @update:model-value="onEditEnabled"
        />
        <ElInput
          :model-value="conditionText"
          type="textarea"
          :rows="8"
          placeholder="条件 JSON，例如 helmet = bare"
          @update:model-value="conditionText = $event"
        />
        <p v-if="conditionError" class="hg-rule-form__error">{{ conditionError }}</p>
        <ElButton type="primary" :loading="store.ruleSaving" @click="onSave">保存</ElButton>
      </div>
    </ElDrawer>

    <ElDialog
      :model-value="simulateOpen"
      title="规则试算"
      width="480px"
      @update:model-value="simulateOpen = $event"
    >
      <p class="hg-rule-form__error">试算只推演不写库，不会真实生效。</p>
      <ElInput
        :model-value="contextText"
        type="textarea"
        :rows="6"
        placeholder="事实上下文 JSON，例如 helmet 与 confidence"
        @update:model-value="contextText = $event"
      />
      <p v-if="contextError" class="hg-rule-form__error">{{ contextError }}</p>
      <div v-if="store.simulateResult" class="hg-simulate-result">
        <p>命中：{{ store.simulateResult.matched ? '是' : '否' }}</p>
        <p>
          分值变化：<span class="tabular">{{ store.simulateResult.total_change }}</span>
        </p>
        <p>{{ store.simulateResult.reasons.join('；') || '无命中说明' }}</p>
      </div>
      <p v-if="store.simulateError" class="hg-rule-form__error">{{ store.simulateError }}</p>
      <template #footer>
        <ElButton @click="simulateOpen = false">关闭</ElButton>
        <ElButton type="primary" :loading="store.simulateLoading" @click="onSimulate">
          开始试算
        </ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  ElButton,
  ElDialog,
  ElDrawer,
  ElInput,
  ElInputNumber,
  ElMessage,
  ElOption,
  ElSelect,
  ElSwitch,
  ElTableColumn,
  ElTag,
} from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import DataTable from '@/components/DataTable.vue'
import { useScoresStore } from '@/stores/scores'
import type { RuleUpdatePayload, ScoreRule } from '@/api/scores'
import { deltaTone, formatDelta, parseJsonText, ruleTypeLabel } from './scoresFormat'

/** 可编辑的规则草稿（抽离响应式细节，提交时再收敛为请求体） */
interface RuleDraft {
  rule_id: string
  name: string
  rule_type: string
  score_change: number
  priority: number
  enabled: boolean
}

const store = useScoresStore()

const editOpen = ref(false)
const editing = ref<RuleDraft | null>(null)
const conditionText = ref('')
const conditionError = ref('')

const simulateOpen = ref(false)
const simulateRuleId = ref('')
const contextText = ref('{}')
const contextError = ref('')

const pageSize = computed(() => Math.max(1, store.rules.length))

onMounted(() => {
  void store.loadRules()
})

function reload(): void {
  void store.loadRules()
}

function openEdit(row: ScoreRule): void {
  editing.value = {
    rule_id: row.rule_id,
    name: row.name,
    rule_type: row.rule_type,
    score_change: row.score_change,
    priority: row.priority,
    enabled: row.enabled,
  }
  conditionText.value = JSON.stringify(row.condition_json, null, 2)
  conditionError.value = ''
  editOpen.value = true
}

function onEditName(value: string): void {
  if (editing.value) editing.value.name = value
}

function onEditType(value: string): void {
  if (editing.value) editing.value.rule_type = value
}

function onEditScore(value: number | undefined): void {
  if (editing.value) editing.value.score_change = value ?? 0
}

function onEditPriority(value: number | undefined): void {
  if (editing.value) editing.value.priority = value ?? 0
}

function onEditEnabled(value: boolean | string | number): void {
  if (editing.value) editing.value.enabled = value === true
}

async function onSave(): Promise<void> {
  if (!editing.value) return
  const parsed = parseJsonText(conditionText.value)
  if (!parsed.ok) {
    conditionError.value = parsed.error
    return
  }
  if (parsed.value !== null && typeof parsed.value !== 'object') {
    conditionError.value = '条件必须是 JSON 对象'
    return
  }
  conditionError.value = ''
  const draft = editing.value
  const payload: RuleUpdatePayload = {
    name: draft.name.trim() === '' ? undefined : draft.name.trim(),
    rule_type: draft.rule_type as RuleUpdatePayload['rule_type'],
    score_change: draft.score_change,
    priority: draft.priority,
    enabled: draft.enabled,
  }
  if (parsed.value !== null) {
    payload.condition_json = parsed.value as Record<string, unknown>
  }
  try {
    await store.saveRule(draft.rule_id, payload)
    ElMessage.success('规则已更新')
    editOpen.value = false
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '规则更新失败')
  }
}

function openSimulate(row: ScoreRule): void {
  simulateRuleId.value = row.rule_id
  contextText.value = '{}'
  contextError.value = ''
  store.clearSimulate()
  simulateOpen.value = true
}

async function onSimulate(): Promise<void> {
  const parsed = parseJsonText(contextText.value)
  if (!parsed.ok) {
    contextError.value = parsed.error
    return
  }
  contextError.value = ''
  try {
    await store.simulate({
      rule_id: simulateRuleId.value,
      context: parsed.value === null ? {} : (parsed.value as Record<string, unknown>),
    })
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '规则试算失败')
  }
}
</script>

<style scoped lang="scss" src="./_styles/scores.scss"></style>

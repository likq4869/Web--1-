<template>
  <div>
    <PageHeader title="策略配置" description="决策阈值与熔断上限，模拟只推演不写库" />

    <p class="hg-policy__warning" role="note">
      此操作仅推演，不会真实生效。保存才会更新版本并记审计。
    </p>

    <div v-if="loading">策略加载中…</div>
    <p v-else-if="loadError" role="alert" class="hg-policy__error">
      {{ loadError }} <ElButton link type="primary" @click="reload">重试</ElButton>
    </p>
    <template v-else>
      <section class="hg-policy__section" aria-label="决策阈值">
        <h2 class="hg-policy__section-title">决策阈值</h2>
        <p class="hg-policy__section-desc">
          当前版本 <span class="tabular">{{ policy?.version }}</span>，保存后版本递增。
        </p>
        <div class="hg-policy__grid">
          <div v-for="field in policyFields" :key="field.key">
            <p class="hg-policy__field-label">{{ field.label }}</p>
            <ElInputNumber
              :model-value="draftPolicy[field.key]"
              :min="field.min"
              :max="field.max"
              :step="field.step"
              @update:model-value="onPolicyInput(field.key, $event)"
            />
            <p class="hg-policy__field-hint">{{ field.hint }}</p>
          </div>
        </div>
      </section>

      <section class="hg-policy__section" aria-label="熔断阈值">
        <h2 class="hg-policy__section-title">熔断阈值（5 条）</h2>
        <p class="hg-policy__section-desc">任一条件触发即关闭自动通道，全部转人工。</p>
        <div class="hg-policy__grid">
          <div v-for="field in thresholdFields" :key="field.key">
            <p class="hg-policy__field-label">{{ field.label }}</p>
            <ElInputNumber
              :model-value="draftThresholds[field.key]"
              :min="field.min"
              :max="field.max"
              :step="field.step"
              @update:model-value="onThresholdInput(field.key, $event)"
            />
            <p class="hg-policy__field-hint">{{ field.hint }}</p>
          </div>
        </div>
      </section>

      <section class="hg-policy__section" aria-label="规则注册表">
        <h2 class="hg-policy__section-title">规则注册表</h2>
        <p class="hg-policy__section-desc">顺序即判定顺序，与后端 RULE_REGISTRY 一致。</p>
        <ol class="hg-policy__rules">
          <li v-for="rule in policy?.rules ?? []" :key="rule.name" class="hg-policy__rule">
            <span>{{ rule.title }}</span>
            <span class="tabular hg-policy__rule-name">{{ rule.name }}</span>
          </li>
        </ol>
      </section>

      <div class="hg-policy__actions">
        <ElButton type="primary" :loading="saving" @click="onSave">保存策略</ElButton>
        <ElButton @click="simulateOpen = true">打开模拟器</ElButton>
      </div>

      <ElDialog
        :model-value="simulateOpen"
        title="策略模拟器"
        width="560px"
        @update:model-value="simulateOpen = $event"
      >
        <p class="hg-policy__warning" role="note">此操作仅推演，不会真实生效。</p>
        <div class="hg-policy__simulate-form">
          <ElInputNumber
            :model-value="simulateFact.model_confidence"
            :min="0"
            :max="1"
            :step="0.05"
            @update:model-value="onSimFact('model_confidence', $event)"
          />
          <ElInputNumber
            :model-value="simulateFact.identity_confidence"
            :min="0"
            :max="1"
            :step="0.05"
            @update:model-value="onSimFact('identity_confidence', $event)"
          />
          <ElInputNumber
            :model-value="simulateFact.violation_count_30d"
            :min="0"
            :max="100"
            @update:model-value="onSimFact('violation_count_30d', $event)"
          />
          <ElInputNumber
            :model-value="simulateFact.violation_count_7d"
            :min="0"
            :max="100"
            @update:model-value="onSimFact('violation_count_7d', $event)"
          />
        </div>
        <div v-if="simulateResult" class="hg-policy__simulate-result">
          <p>重放 {{ simulateResult.simulated }} 条，变化 {{ simulateResult.changed }} 条</p>
          <p>{{ simulateResult.note }}</p>
          <ul>
            <li v-for="diff in simulateResult.diffs.slice(0, 20)" :key="diff.decision_id">
              <span class="tabular">{{ diff.decision_id }}</span>
              {{ diff.original_level }} → {{ diff.replayed_level }} ·
              {{ diff.changed ? '有变化' : '一致' }} · {{ diff.diff_reason }}
            </li>
          </ul>
        </div>
        <p v-if="simulateError" class="hg-policy__error">{{ simulateError }}</p>
        <template #footer>
          <ElButton @click="simulateOpen = false">关闭</ElButton>
          <ElButton type="primary" :loading="simulating" @click="onSimulate">开始推演</ElButton>
        </template>
      </ElDialog>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElButton, ElDialog, ElInputNumber, ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import {
  getPolicy,
  simulatePolicy,
  updatePolicy,
  type BreakerThresholdsBody,
  type DecisionPolicyBody,
  type PolicyResponse,
  type PolicySimulateResponse,
} from '@/api/policies'
import { ApiError } from '@/api/types'

interface NumericField<Key extends string> {
  key: Key
  label: string
  hint: string
  min: number
  max: number
  step: number
}

type PolicyKey = keyof DecisionPolicyBody & string
type ThresholdKey = keyof BreakerThresholdsBody & string

const policyFields: NumericField<PolicyKey>[] = [
  {
    key: 'min_model_confidence',
    label: '模型置信度闸门',
    hint: '低于此值不惩罚',
    min: 0,
    max: 1,
    step: 0.05,
  },
  {
    key: 'min_identity_confidence',
    label: '身份置信度闸门',
    hint: '身份不足不惩罚',
    min: 0,
    max: 1,
    step: 0.05,
  },
  { key: 'l1_score', label: 'L1 分值', hint: '提醒不扣分', min: -100, max: 100, step: 1 },
  { key: 'l2_score', label: 'L2 分值', hint: '默认 -1', min: -100, max: 100, step: 1 },
  { key: 'l3_score', label: 'L3 分值', hint: '默认 -3', min: -100, max: 100, step: 1 },
  { key: 'award_score', label: '奖励分值', hint: '默认 +2', min: -100, max: 100, step: 1 },
  { key: 'l3_violation_30d', label: 'L3 的 30 天线', hint: '默认 3', min: 1, max: 1000, step: 1 },
  { key: 'l3_violation_7d', label: 'L3 的 7 天线', hint: '默认 2', min: 1, max: 1000, step: 1 },
  {
    key: 'l3_same_point_1h',
    label: 'L3 同点位 1 小时线',
    hint: '默认 2',
    min: 1,
    max: 1000,
    step: 1,
  },
  { key: 'l2_violation_30d', label: 'L2 的 30 天线', hint: '默认 1', min: 1, max: 1000, step: 1 },
  { key: 'l2_violation_7d', label: 'L2 的 7 天线', hint: '默认 1', min: 1, max: 1000, step: 1 },
  {
    key: 'streak_award_days',
    label: '连续合规奖励线',
    hint: '默认 30 天',
    min: 1,
    max: 3650,
    step: 1,
  },
]

const thresholdFields: NumericField<ThresholdKey>[] = [
  {
    key: 'max_daily_punishments',
    label: '单日全校处罚上限',
    hint: '默认 50 条',
    min: 1,
    max: 100000,
    step: 1,
  },
  {
    key: 'min_student_daily_delta',
    label: '单学生单日扣分下限',
    hint: '默认 -5 分',
    min: -1000,
    max: 0,
    step: 1,
  },
  { key: 'min_model_map', label: '模型 mAP 下限', hint: '默认 0.80', min: 0, max: 1, step: 0.01 },
  {
    key: 'max_dismiss_rate',
    label: '人工驳回率上限',
    hint: '默认 0.30',
    min: 0,
    max: 1,
    step: 0.01,
  },
  {
    key: 'min_identity_bind_rate',
    label: '身份绑定率下限',
    hint: '默认 0.50',
    min: 0,
    max: 1,
    step: 0.01,
  },
]

const policy = ref<PolicyResponse | null>(null)
const draftPolicy = ref<Record<PolicyKey, number | undefined>>(
  {} as Record<PolicyKey, number | undefined>,
)
const draftThresholds = ref<Record<ThresholdKey, number | undefined>>(
  {} as Record<ThresholdKey, number | undefined>,
)
const loading = ref(false)
const loadError = ref<string | null>(null)
const saving = ref(false)

const simulateOpen = ref(false)
const simulating = ref(false)
const simulateError = ref<string | null>(null)
const simulateResult = ref<PolicySimulateResponse | null>(null)
const simulateFact = ref({
  model_confidence: 0.85,
  identity_confidence: 0.85,
  violation_count_30d: 0,
  violation_count_7d: 0,
})

function fillDrafts(source: PolicyResponse): void {
  const nextPolicy = {} as Record<PolicyKey, number | undefined>
  for (const field of policyFields) {
    const value = source.policy[field.key]
    nextPolicy[field.key] = typeof value === 'number' ? value : undefined
  }
  draftPolicy.value = nextPolicy
  const nextThresholds = {} as Record<ThresholdKey, number | undefined>
  for (const field of thresholdFields) {
    const value = source.thresholds[field.key]
    nextThresholds[field.key] = typeof value === 'number' ? value : undefined
  }
  draftThresholds.value = nextThresholds
}

async function reload(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    const result = await getPolicy('default')
    policy.value = result
    fillDrafts(result)
  } catch (error) {
    loadError.value = error instanceof ApiError ? error.message : '策略加载失败'
  } finally {
    loading.value = false
  }
}

function onPolicyInput(key: PolicyKey, value: number | undefined): void {
  draftPolicy.value[key] = value
}

function onThresholdInput(key: ThresholdKey, value: number | undefined): void {
  draftThresholds.value[key] = value
}

function onSimFact(key: keyof typeof simulateFact.value, value: number | undefined): void {
  simulateFact.value[key] = value ?? 0
}

async function onSave(): Promise<void> {
  saving.value = true
  try {
    const result = await updatePolicy('default', {
      policy: { ...draftPolicy.value },
      thresholds: { ...draftThresholds.value },
    })
    policy.value = result
    fillDrafts(result)
    ElMessage.success('策略已更新')
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '策略更新失败')
  } finally {
    saving.value = false
  }
}

async function onSimulate(): Promise<void> {
  simulating.value = true
  simulateError.value = null
  try {
    simulateResult.value = await simulatePolicy('default', {
      policy: { ...draftPolicy.value },
      thresholds: { ...draftThresholds.value },
      ...simulateFact.value,
      limit: 20,
    })
  } catch (error) {
    simulateError.value = error instanceof ApiError ? error.message : '策略推演失败'
  } finally {
    simulating.value = false
  }
}

onMounted(() => {
  void reload()
})
</script>

<style scoped lang="scss" src="./_styles/policy.scss"></style>

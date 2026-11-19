<template>
  <div>
    <PageHeader title="积分台账" description="加扣分流水，按学生 / 方向 / 原因码筛选" />

    <div class="hg-toolbar">
      <ElInput
        :model-value="keyword"
        placeholder="按学号筛选"
        clearable
        class="hg-toolbar__search"
        @update:model-value="onKeywordInput"
        @clear="onClear"
      />
      <ElSelect
        :model-value="direction"
        class="hg-toolbar__select"
        @update:model-value="onDirection"
      >
        <ElOption label="全部变动" value="all" />
        <ElOption label="加分" value="positive" />
        <ElOption label="扣分" value="negative" />
      </ElSelect>
      <ElInput
        :model-value="reasonCode"
        placeholder="按原因码筛选"
        clearable
        class="hg-toolbar__search"
        @update:model-value="onReasonInput"
        @clear="onReasonClear"
      />
      <ElButton :loading="store.ledgerLoading" @click="reload">刷新</ElButton>
      <RouterLink class="hg-scores__rules-link" to="/points/rules">规则配置</RouterLink>
    </div>

    <DataTable
      :rows="store.ledgerItems"
      :loading="store.ledgerLoading"
      :error="store.ledgerError"
      :total="store.ledgerTotal"
      :current-page="store.ledgerPage"
      :page-size="store.ledgerPageSize"
      :on-retry="reload"
      row-key="ledger_id"
      empty-title="暂无积分流水"
      empty-description="当前筛选下没有流水，可调整筛选后重试。"
      @update:current-page="onPageChange"
      @update:page-size="onSizeChange"
    >
      <ElTableColumn prop="ledger_id" label="流水号" width="100">
        <template #default="{ row }">
          <span class="tabular">{{ (row as ScoreLedger).ledger_id }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="student_id" label="学号" min-width="130" />
      <ElTableColumn label="变动" width="100">
        <template #default="{ row }">
          <span class="tabular hg-delta" :data-tone="deltaTone((row as ScoreLedger).change)">
            {{ formatDelta((row as ScoreLedger).change) }}
          </span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="变动后余额" width="120">
        <template #default="{ row }">
          <span class="tabular">{{ (row as ScoreLedger).balance_after }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="reason_code" label="原因码" min-width="130" />
      <ElTableColumn prop="reason_text" label="原因说明" min-width="180">
        <template #default="{ row }">
          {{ (row as ScoreLedger).reason_text ?? '—' }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="生效时间" min-width="160">
        <template #default="{ row }">
          <span class="tabular">{{ formatTimeShort((row as ScoreLedger).effective_at) }}</span>
        </template>
      </ElTableColumn>
    </DataTable>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElButton, ElInput, ElOption, ElSelect, ElTableColumn } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import DataTable from '@/components/DataTable.vue'
import { useScoresStore } from '@/stores/scores'
import type { LedgerDirection, ScoreLedger } from '@/api/scores'
import { deltaTone, formatDelta, formatTimeShort } from './scoresFormat'

const store = useScoresStore()

const keyword = ref(store.ledgerFilters.student_id ?? '')
const reasonCode = ref(store.ledgerFilters.reason_code ?? '')
const direction = ref<LedgerDirection>(store.ledgerFilters.direction ?? 'all')

let keywordTimer: ReturnType<typeof setTimeout> | null = null
let reasonTimer: ReturnType<typeof setTimeout> | null = null

onMounted(() => {
  void store.loadLedger()
})

function onKeywordInput(value: string): void {
  keyword.value = value
  if (keywordTimer !== null) clearTimeout(keywordTimer)
  keywordTimer = setTimeout(() => {
    store.ledgerPage = 1
    void store.applyLedgerFilters({ student_id: value.trim() })
  }, 300)
}

function onClear(): void {
  keyword.value = ''
  store.ledgerPage = 1
  void store.applyLedgerFilters({ student_id: '' })
}

function onDirection(value: LedgerDirection): void {
  direction.value = value
  store.ledgerPage = 1
  void store.applyLedgerFilters({ direction: value })
}

function onReasonInput(value: string): void {
  reasonCode.value = value
  if (reasonTimer !== null) clearTimeout(reasonTimer)
  reasonTimer = setTimeout(() => {
    store.ledgerPage = 1
    void store.applyLedgerFilters({ reason_code: value.trim() })
  }, 300)
}

function onReasonClear(): void {
  reasonCode.value = ''
  store.ledgerPage = 1
  void store.applyLedgerFilters({ reason_code: '' })
}

function onPageChange(next: number): void {
  store.ledgerPage = next
  void store.loadLedger()
}

function onSizeChange(size: number): void {
  store.ledgerPageSize = size
  store.ledgerPage = 1
  void store.loadLedger()
}

function reload(): void {
  void store.loadLedger()
}
</script>

<style scoped lang="scss" src="./_styles/scores.scss"></style>

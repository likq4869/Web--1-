// ===========================================================================
// 积分状态 —— 账户台账、流水筛选、规则更新与试算
//
// 持久化策略：
//   只持久化筛选偏好（台账筛选、分页），不持久化瞬时态（loading/error）
//   与试算结果（刷新后重新试算，避免展示过期推演）。
// ===========================================================================

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as scoresApi from '@/api/scores'
import type {
  AccountQuery,
  LedgerDirection,
  LedgerQuery,
  RuleSimulatePayload,
  RuleSimulateResult,
  ScoreAccount,
  ScoreLedger,
  ScoreRule,
} from '@/api/scores'

export const useScoresStore = defineStore(
  'scores',
  () => {
    // ---------- 台账 ----------
    const ledgerItems = ref<ScoreLedger[]>([])
    const ledgerTotal = ref(0)
    const ledgerPage = ref(1)
    const ledgerPageSize = ref(20)
    const ledgerLoading = ref(false)
    const ledgerError = ref<string | null>(null)

    // ---------- 账户 ----------
    const accounts = ref<ScoreAccount[]>([])
    const accountsTotal = ref(0)
    const accountsPage = ref(1)
    const accountsPageSize = ref(20)
    const accountsLoading = ref(false)
    const accountsError = ref<string | null>(null)

    // ---------- 筛选（持久化偏好） ----------
    const ledgerFilters = ref<LedgerQuery>({
      student_id: '',
      direction: 'all',
      reason_code: '',
      start: '',
      end: '',
    })
    const accountKeyword = ref('')

    // ---------- 规则 ----------
    const rules = ref<ScoreRule[]>([])
    const rulesLoading = ref(false)
    const rulesError = ref<string | null>(null)
    const ruleSaving = ref(false)

    // ---------- 试算 ----------
    const simulateResult = ref<RuleSimulateResult | null>(null)
    const simulateLoading = ref(false)
    const simulateError = ref<string | null>(null)

    /** 是否有活跃的台账筛选 */
    const hasActiveLedgerFilters = computed(
      () =>
        (ledgerFilters.value.student_id ?? '').trim() !== '' ||
        (ledgerFilters.value.reason_code ?? '').trim() !== '' ||
        (ledgerFilters.value.start ?? '').trim() !== '' ||
        (ledgerFilters.value.end ?? '').trim() !== '' ||
        (ledgerFilters.value.direction ?? 'all') !== 'all',
    )

    const hasLedgerItems = computed(() => ledgerItems.value.length > 0)

    // ------------------------------------------------------------------
    // 台账加载
    // ------------------------------------------------------------------

    async function loadLedger(): Promise<void> {
      ledgerLoading.value = true
      ledgerError.value = null
      try {
        const result = await scoresApi.listLedger({
          ...ledgerFilters.value,
          student_id:
            ledgerFilters.value.student_id?.trim() === ''
              ? undefined
              : ledgerFilters.value.student_id?.trim(),
          reason_code:
            ledgerFilters.value.reason_code?.trim() === ''
              ? undefined
              : ledgerFilters.value.reason_code?.trim(),
          start:
            ledgerFilters.value.start?.trim() === ''
              ? undefined
              : ledgerFilters.value.start?.trim(),
          end: ledgerFilters.value.end?.trim() === '' ? undefined : ledgerFilters.value.end?.trim(),
          direction: (ledgerFilters.value.direction ?? 'all') as LedgerDirection,
          page: ledgerPage.value,
          page_size: ledgerPageSize.value,
        })
        ledgerItems.value = result.items
        ledgerTotal.value = result.total
      } catch (err) {
        ledgerItems.value = []
        ledgerError.value = err instanceof Error ? err.message : '积分台账加载失败'
      } finally {
        ledgerLoading.value = false
      }
    }

    async function applyLedgerFilters(next: Partial<LedgerQuery>): Promise<void> {
      ledgerFilters.value = { ...ledgerFilters.value, ...next }
      ledgerPage.value = 1
      await loadLedger()
    }

    async function resetLedgerFilters(): Promise<void> {
      ledgerFilters.value = {
        student_id: '',
        direction: 'all',
        reason_code: '',
        start: '',
        end: '',
      }
      ledgerPage.value = 1
      await loadLedger()
    }

    // ------------------------------------------------------------------
    // 账户加载
    // ------------------------------------------------------------------

    async function loadAccounts(): Promise<void> {
      accountsLoading.value = true
      accountsError.value = null
      try {
        const params: AccountQuery = {
          page: accountsPage.value,
          page_size: accountsPageSize.value,
        }
        const keyword = accountKeyword.value.trim()
        if (keyword !== '') params.keyword = keyword
        const result = await scoresApi.listAccounts(params)
        accounts.value = result.items
        accountsTotal.value = result.total
      } catch (err) {
        accounts.value = []
        accountsError.value = err instanceof Error ? err.message : '积分账户加载失败'
      } finally {
        accountsLoading.value = false
      }
    }

    async function applyAccountKeyword(keyword: string): Promise<void> {
      accountKeyword.value = keyword
      accountsPage.value = 1
      await loadAccounts()
    }

    // ------------------------------------------------------------------
    // 规则
    // ------------------------------------------------------------------

    async function loadRules(): Promise<void> {
      rulesLoading.value = true
      rulesError.value = null
      try {
        const result = await scoresApi.listRules()
        rules.value = result.items
      } catch (err) {
        rules.value = []
        rulesError.value = err instanceof Error ? err.message : '积分规则加载失败'
      } finally {
        rulesLoading.value = false
      }
    }

    async function saveRule(
      ruleId: string,
      payload: scoresApi.RuleUpdatePayload,
    ): Promise<ScoreRule> {
      ruleSaving.value = true
      try {
        const updated = await scoresApi.updateRule(ruleId, payload)
        rules.value = rules.value.map((rule) => (rule.rule_id === ruleId ? updated : rule))
        return updated
      } finally {
        ruleSaving.value = false
      }
    }

    async function simulate(payload: RuleSimulatePayload): Promise<RuleSimulateResult> {
      simulateLoading.value = true
      simulateError.value = null
      try {
        const result = await scoresApi.simulateRule(payload)
        simulateResult.value = result
        return result
      } catch (err) {
        simulateResult.value = null
        simulateError.value = err instanceof Error ? err.message : '规则试算失败'
        throw err
      } finally {
        simulateLoading.value = false
      }
    }

    function clearSimulate(): void {
      simulateResult.value = null
      simulateError.value = null
    }

    return {
      ledgerItems,
      ledgerTotal,
      ledgerPage,
      ledgerPageSize,
      ledgerLoading,
      ledgerError,
      accounts,
      accountsTotal,
      accountsPage,
      accountsPageSize,
      accountsLoading,
      accountsError,
      ledgerFilters,
      accountKeyword,
      rules,
      rulesLoading,
      rulesError,
      ruleSaving,
      simulateResult,
      simulateLoading,
      simulateError,
      hasActiveLedgerFilters,
      hasLedgerItems,
      loadLedger,
      applyLedgerFilters,
      resetLedgerFilters,
      loadAccounts,
      applyAccountKeyword,
      loadRules,
      saveRule,
      simulate,
      clearSimulate,
    }
  },
  {
    persist: {
      key: 'hg.scores',
      storage: localStorage,
      // 仅持久化筛选与分页偏好；台账与规则数据每次进入页面重新拉取，
      // 避免展示过期余额（可能已被审批/记账变更）。
      pick: ['ledgerFilters', 'ledgerPage', 'ledgerPageSize', 'accountKeyword'],
    },
  },
)

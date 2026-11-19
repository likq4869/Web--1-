/** 积分总览：消费学生端一屏聚合 GET /api/v1/me/overview（P4-2）。
 * 后端契约（helmet-guard/app/schemas/me.py）：score / pending / records。
 * 无账户时后端取初始值（100/S），前端不补默认值，直接渲染。
 */
import { readonly, ref } from 'vue';
import { ME_BASE, MiniApiError, apiGet } from '../utils/api';

export interface HomeScore {
  balance: number;
  level: string;
  streak_days: number;
  compliance_rate: number;
  rank: number | null;
  total_students: number;
  percentile: number | null;
}

export interface HomePending {
  count: number;
  latest: Record<string, unknown> | null;
}

export interface HomeRecords {
  total: number;
  recent: Record<string, unknown>[];
  appeals_total: number;
  appeals_pending: number;
}

export interface HomeOverview {
  student_id: string;
  name: string;
  score: HomeScore;
  pending: HomePending;
  records: HomeRecords;
}

export interface ScoreOverview {
  recordCount: number;
  appealCount: number;
}

const overview = ref<HomeOverview | null>(null);
const loading = ref(false);
const error = ref('');

function isOverview(v: unknown): v is HomeOverview {
  if (!v || typeof v !== 'object') return false;
  const o = v as Record<string, unknown>;
  return typeof o.student_id === 'string' && typeof o.score === 'object' && typeof o.pending === 'object' && typeof o.records === 'object';
}

function emptyOverview(): HomeOverview {
  return {
    student_id: '',
    name: '',
    score: { balance: 100, level: 'S', streak_days: 0, compliance_rate: 1, rank: null, total_students: 0, percentile: null },
    pending: { count: 0, latest: null },
    records: { total: 0, recent: [], appeals_total: 0, appeals_pending: 0 },
  };
}

export function useScoreStore() {
  async function refresh(): Promise<void> {
    loading.value = true;
    error.value = '';
    try {
      const data = await apiGet<unknown>(`${ME_BASE}/overview`);
      overview.value = isOverview(data) ? (data as HomeOverview) : emptyOverview();
    } catch (e) {
      if (e instanceof MiniApiError && (e.status === 401 || e.status === 404)) {
        overview.value = emptyOverview();
        return;
      }
      error.value = e instanceof Error ? e.message : '加载失败，请重试';
    } finally {
      loading.value = false;
    }
  }

  return { overview: readonly(overview), loading: readonly(loading), error: readonly(error), refresh };
}

/** 通知状态：未读数取本人待处理申诉数，失败时归零不打断主流程。 */
import { readonly, ref } from 'vue';
import { ME_BASE, MiniApiError, apiGet } from '../utils/api';

const unread = ref(0);
const loading = ref(false);

export function useNoticeStore() {
  async function refresh(): Promise<void> {
    loading.value = true;
    try {
      const data = await apiGet<{ total: number }>(`${ME_BASE}/appeals`, { page: 1, page_size: 1 });
      unread.value = typeof data.total === 'number' ? data.total : 0;
    } catch (e) {
      if (e instanceof MiniApiError && e.status === 401) unread.value = 0;
      else unread.value = 0;
    } finally {
      loading.value = false;
    }
  }

  return { unread: readonly(unread), loading: readonly(loading), refresh };
}

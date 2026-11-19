<template>
  <scroll-view
    class="screen"
    scroll-y
    :refresher-enabled="true"
    :refresher-triggered="refreshing"
    refresher-background="#EDF1EC"
    @refresherrefresh="onPullRefresh"
  >
    <view class="content">
      <view class="topbar">
        <text class="greeting">{{ greeting }}，{{ displayName }}</text>
        <view class="bell pressable" @click="goNotices" aria-label="待确认提醒">
          <UniIcons type="notification" color="#1b2b22" size="20" />
          <text v-if="loggedIn && badgeCount > 0" class="bell-badge num">{{ badgeText }}</text>
        </view>
      </view>

      <view v-if="loading" class="card">
        <view class="sk-line wide skeleton-pulse" aria-hidden="true" />
        <view class="sk-line skeleton-pulse" aria-hidden="true" />
        <view class="sk-line short skeleton-pulse" aria-hidden="true" />
      </view>

      <view v-else-if="loadError" class="card">
        <text class="card-title">加载失败</text>
        <text class="body-text">请检查网络连接后重试。</text>
        <button class="quiet-btn pressable" @click="reload">重试</button>
      </view>

      <!-- 访客态：分数区置灰 + 快捷登录 CTA，自查工具仍可用 -->
      <view v-else-if="!loggedIn">
        <view class="card is-guest anim-rise">
          <text class="label">文明积分</text>
          <text class="score-num guest-mask num">***</text>
          <text class="score-sub">登录后查看你的积分、等级与排名</text>
          <view class="action-col">
            <button class="primary-btn pressable" @click="openSheet('登录后查看你的文明积分与安全记录', $event)">快捷登录</button>
          </view>
          <text class="tip">微信一键登录 · 首次使用自动创建账号</text>
        </view>

        <SectionHeader title="我的工具" />
        <ToolGrid :items="guestTools" @select="onTool" />

        <EmptyState
          title="还没有安全记录"
          description="登录后可查看本人安全记录，每条提醒都可申诉。"
          action-text="先去拍照自查"
          @action="goSelfCheck"
        />
      </view>

      <template v-else-if="data">
        <ScoreCard
          :balance="scoreBalance"
          :sub="scoreSub"
          :pct="scorePct"
          :streak-text="streakText"
          :cells="scoreCells"
        />

        <NoticeBanner
          v-if="pendingCount > 0"
          level="warning"
          :title="'您有 ' + String(pendingCount) + ' 条待确认提醒'"
          :subtitle="pendingSub"
          primary-text="查看详情"
          secondary-text="去申诉"
          @primary="goRecords"
          @secondary="goAppeal"
        />

        <SectionHeader title="我的工具" />
        <ToolGrid :items="authedTools" @select="onTool" />

        <SectionHeader title="近期记录" action-text="查看全部" @action="goRecords" />
        <EmptyState
          v-if="!recentRecords.length"
          title="还没有安全记录"
          description="完成一次拍照自查或安全骑行后，这里会生成记录。"
        />
        <view v-else class="card records anim-rise">
          <view
            v-for="(item, idx) in recentRecords"
            :key="String(item.decision_id)"
            class="record-row pressable"
            :class="{ 'is-last': idx === recentRecords.length - 1 }"
            @click="goRecords"
          >
            <view class="record-main">
              <text class="record-title">{{ recordTitle(item) }}</text>
              <text class="record-time num">{{ recordTime(item) }}</text>
            </view>
            <text class="record-delta num" :class="deltaClass(item)">{{ deltaText(item) }}</text>
          </view>
        </view>
      </template>
      <view class="bottom-space" />
    </view>
    <LoginSheet
      :show="sheetShow"
      :reason="sheetReason"
      :start-step="sheetStart"
      :origin="sheetOrigin"
      @close="sheetShow = false"
      @success="onLoginSuccess"
    />
  </scroll-view>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { onShow } from '@dcloudio/uni-app';
import UniIcons from '@dcloudio/uni-ui/lib/uni-icons/uni-icons.vue';
import LoginSheet from '../../components/LoginSheet.vue';
import SectionHeader from '../../components/SectionHeader.vue';
import ToolGrid from '../../components/ToolGrid.vue';
import type { ToolItem } from '../../components/ToolGrid.vue';
import NoticeBanner from '../../components/NoticeBanner.vue';
import EmptyState from '../../components/EmptyState.vue';
import ScoreCard from '../../components/ScoreCard.vue';
import type { ScoreCell } from '../../components/ScoreCard.vue';
import { useScoreStore } from '../../stores/useScoreStore';
import { useUserStore } from '../../stores/useUserStore';
import { isLoggedIn } from '../../utils/auth';
import type { StudentProfile } from '../../utils/auth';

const store = useScoreStore();
const userStore = useUserStore();
const loggedIn = ref(false);
const refreshing = ref(false);
const sheetShow = ref(false);
const sheetReason = ref('登录后查看你的文明积分与安全记录');
const sheetStart = ref<'wx' | 'phone'>('wx');
const sheetOrigin = ref('50% 100%');

const data = computed(() => store.overview.value);
const loading = computed(() => store.loading.value);
const loadError = computed(() => store.error.value.length > 0);

const guestTools: ToolItem[] = [
  { id: 'scan', label: '拍照自查', icon: 'scan', tone: 'primary' },
  { id: 'vehicle', label: '车辆绑定', icon: 'bike', tone: 'neutral' },
  { id: 'rank', label: '排行榜', icon: 'rank', tone: 'success' },
  { id: 'mall', label: '积分商城', icon: 'mall', tone: 'warning' },
];

const authedTools: ToolItem[] = [
  { id: 'scan', label: '拍照自查', icon: 'scan', tone: 'primary' },
  { id: 'vehicle', label: '车辆绑定', icon: 'bike', tone: 'neutral' },
  { id: 'rank', label: '排行榜', icon: 'rank', tone: 'success' },
  { id: 'mall', label: '积分商城', icon: 'mall', tone: 'warning' },
];

function overviewScore(): Record<string, unknown> {
  const o = data.value as unknown as Record<string, unknown> | null;
  if (!o || typeof o !== 'object') return {};
  const s = o.score as Record<string, unknown>;
  if (!s || typeof s !== 'object') return {};
  return s;
}

function overviewPending(): Record<string, unknown> {
  const o = data.value as unknown as Record<string, unknown> | null;
  if (!o || typeof o !== 'object') return {};
  const p = o.pending as Record<string, unknown>;
  if (!p || typeof p !== 'object') return {};
  return p;
}

function overviewRecords(): Record<string, unknown> {
  const o = data.value as unknown as Record<string, unknown> | null;
  if (!o || typeof o !== 'object') return {};
  const r = o.records as Record<string, unknown>;
  if (!r || typeof r !== 'object') return {};
  return r;
}

const displayName = computed(() => {
  if (!loggedIn.value) return '同学';
  const o = data.value as unknown as { name?: unknown } | null;
  const n = o && typeof o.name === 'string' ? o.name.trim() : '';
  return n.length > 0 ? n : '同学';
});

const greeting = computed(() => {
  const h = new Date().getHours();
  if (h < 6) return '夜深了';
  if (h < 12) return '早上好';
  if (h < 18) return '下午好';
  return '晚上好';
});

const pendingCount = computed(() => {
  const p = overviewPending();
  return typeof p.count === 'number' && Number.isFinite(p.count) ? p.count : 0;
});

const appealsPending = computed(() => {
  const r = overviewRecords();
  return typeof r.appeals_pending === 'number' && Number.isFinite(r.appeals_pending) ? (r.appeals_pending as number) : 0;
});

const badgeCount = computed(() => pendingCount.value + appealsPending.value);
const badgeText = computed(() => (badgeCount.value > 99 ? '99+' : String(badgeCount.value)));

const scoreBalance = computed(() => {
  const s = overviewScore();
  return typeof s.balance === 'number' && Number.isFinite(s.balance) ? (s.balance as number) : 0;
});

const scorePct = computed(() => {
  const b = scoreBalance.value;
  return Math.max(0, Math.min(100, b));
});

const scoreSub = computed(() => {
  const s = overviewScore();
  const level = typeof s.level === 'string' && s.level ? s.level : '—';
  const p = s.percentile;
  const pctText = typeof p === 'number' && !Number.isNaN(p) ? '超过全校 ' + String(Math.round(p * 100)) + '%' : '暂无排名';
  return '等级 ' + level + ' · ' + pctText;
});

const streakText = computed(() => {
  const s = overviewScore();
  const d = typeof s.streak_days === 'number' && Number.isFinite(s.streak_days) ? (s.streak_days as number) : 0;
  return d > 0 ? '连续安全骑行 ' + String(d) + ' 天' : '';
});

const rateText = computed(() => {
  const s = overviewScore();
  const r = s.compliance_rate;
  if (typeof r !== 'number' || Number.isNaN(r)) return '--';
  return (r * 100).toFixed(1) + '%';
});

const rankText = computed(() => {
  const s = overviewScore();
  return typeof s.rank === 'number' ? '第' + String(s.rank) + '名' : '暂无';
});

const scoreCells = computed<ScoreCell[]>(() => [
  { label: '30天佩戴率', value: rateText.value },
  { label: '本期排名', value: rankText.value },
]);

const pendingSub = computed(() => {
  const p = overviewPending();
  const latest = p.latest as Record<string, unknown> | null;
  if (!latest || typeof latest !== 'object') return '有一条新的安全提醒待确认';
  const raw = latest.created_at;
  const time = typeof raw === 'string' ? raw.slice(0, 16).replace('T', ' ') : '';
  return time ? time + ' 有一条新的安全提醒待确认' : '有一条新的安全提醒待确认';
});

const recentRecords = computed<Record<string, unknown>[]>(() => {
  const r = overviewRecords();
  const list = r.recent as unknown;
  if (!Array.isArray(list)) return [];
  return list.filter((x) => x && typeof x === 'object') as Record<string, unknown>[];
});

function recordTitle(item: Record<string, unknown>): string {
  const level = typeof item.level === 'string' ? item.level : '';
  const code = typeof item.reason_code === 'string' ? item.reason_code : '';
  if (level === 'L4') return '安全骑行奖励';
  if (code) return '安全记录 · 待确认';
  return '安全记录';
}

function recordTime(item: Record<string, unknown>): string {
  const raw = item.created_at;
  if (typeof raw !== 'string') return '';
  return raw.slice(0, 16).replace('T', ' ');
}

function deltaOf(item: Record<string, unknown>): number | null {
  const v = item.score_delta;
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function deltaText(item: Record<string, unknown>): string {
  const v = deltaOf(item);
  if (v === null) return '提醒';
  if (v > 0) return '+' + String(v) + ' 分';
  if (v < 0) return String(v) + ' 分';
  return '提醒';
}

function deltaClass(item: Record<string, unknown>): string {
  const v = deltaOf(item);
  if (v === null || v === 0) return 'is-neutral';
  return v > 0 ? 'is-plus' : 'is-minus';
}

function openSheet(reason: string, e?: unknown): void {
  sheetReason.value = reason;
  sheetStart.value = 'wx';
  sheetOrigin.value = originFromTap(e);
  sheetShow.value = true;
}

/** 点击处长出：取按钮中心 X 映射为 sheet 顶边 transform-origin（Y=0%），取不到回落 50%。 */
function originFromTap(e: unknown): string {
  try {
    const touch =
      (e as { touches?: Array<{ clientX?: number }>; changedTouches?: Array<{ clientX?: number }>; detail?: { x?: number } }) ?? {};
    const clientX =
      touch.touches?.[0]?.clientX ?? touch.changedTouches?.[0]?.clientX ?? touch.detail?.x;
    if (typeof clientX !== 'number' || !Number.isFinite(clientX)) return '50% 0%';
    const info = uni.getWindowInfo ? uni.getWindowInfo() : uni.getSystemInfoSync();
    const winW = Number(info.windowWidth) || 390;
    const sheetW = Math.min(winW, 480);
    const offsetLeft = (winW - sheetW) / 2;
    const pct = ((clientX - offsetLeft) / sheetW) * 100;
    const clamped = Math.min(90, Math.max(10, pct));
    return `${clamped.toFixed(1)}% 0%`;
  } catch (_) {
    return '50% 0%';
  }
}

function needLogin(reason: string): boolean {
  if (loggedIn.value) return true;
  openSheet(reason);
  return false;
}

async function checkLogin(): Promise<void> {
  if (!isLoggedIn()) {
    loggedIn.value = false;
    return;
  }
  try {
    const p = await userStore.refreshStudentProfile();
    loggedIn.value = true;
    if (p && p.has_phone && p.has_profile) {
      await store.refresh();
    }
  } catch (_) {
    loggedIn.value = false;
  }
}

async function onLoginSuccess(p: StudentProfile | null): Promise<void> {
  sheetShow.value = false;
  if (!p || !p.has_phone) {
    sheetReason.value = '绑定手机号后继续';
    sheetStart.value = 'phone';
    sheetShow.value = true;
    return;
  }
  if (!p.has_profile) {
    uni.navigateTo({ url: '/pages/auth/auth' });
    return;
  }
  await checkLogin();
}

async function reload(): Promise<void> {
  if (!loggedIn.value) {
    await checkLogin();
    return;
  }
  await store.refresh();
}

// 下拉刷新：原生 refresher + 状态机，不讲故事（design.md §9.8.3 拒绝下拉叙事）。
// 刷新中骨架 E 落位，松手回弹 F 由原生承载，内容到位后列表 H 渐显。
async function onPullRefresh(): Promise<void> {
  if (refreshing.value) return;
  refreshing.value = true;
  try {
    await checkLogin();
  } finally {
    refreshing.value = false;
  }
}

function goSelfCheck(): void {
  uni.switchTab({ url: '/pages/index/index' });
}

function goRecords(): void {
  if (!needLogin('登录后查看你的安全记录')) return;
  uni.showToast({ title: '安全记录页即将上线', icon: 'none' });
}

function goAppeal(): void {
  if (!needLogin('登录后可对提醒发起申诉')) return;
  uni.showToast({ title: '申诉页即将上线', icon: 'none' });
}

function goNotices(): void {
  if (!needLogin('登录后查看你的待确认提醒')) return;
  if (pendingCount.value > 0) goRecords();
  else uni.showToast({ title: '暂无新的提醒', icon: 'none' });
}

function needVehicle(): void {
  if (!needLogin('登录后绑定你的车辆')) return;
  uni.showToast({ title: '车辆绑定页即将上线', icon: 'none' });
}

function needRank(): void {
  if (!needLogin('登录后查看你的排名')) return;
  uni.showToast({ title: '排行榜即将上线', icon: 'none' });
}

function needMall(): void {
  if (!needLogin('登录后进入积分商城')) return;
  uni.showToast({ title: '积分商城即将上线', icon: 'none' });
}

function onTool(id: string): void {
  if (id === 'scan') {
    goSelfCheck();
    return;
  }
  if (id === 'vehicle') {
    needVehicle();
    return;
  }
  if (id === 'rank') {
    needRank();
    return;
  }
  needMall();
}

onShow(() => {
  checkLogin();
});

onMounted(async () => {
  await checkLogin();
});
</script>

<style lang="scss" scoped src="./home.scss"></style>

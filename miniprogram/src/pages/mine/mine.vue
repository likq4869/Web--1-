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
      <!-- 未登录访客态 -->
      <view v-if="!loggedIn" class="card guest">
        <view class="avatar">学</view>
        <text class="card-title">还没有登录</text>
        <text class="body-text">登录后查看本人档案、车辆与积分变动，安全记录仅本人可见。</text>
        <view class="action-col">
          <button class="primary-btn" @click="openSheet('登录后查看你的本人档案与安全记录', $event)">快捷登录</button>
        </view>
        <text class="tip">微信一键登录 · 首次使用自动创建账号</text>
      </view>

      <!-- 已登录档案卡 -->
      <view v-else class="card profile">
        <view class="profile-row">
          <image v-if="profileAvatar" class="avatar-img" :src="profileAvatar" mode="aspectFill" />
          <view v-else class="avatar is-login">{{ nameInitial }}</view>
          <view class="profile-main">
            <text class="profile-name">{{ profileName }}</text>
            <text class="profile-sub num">{{ profileSub }}</text>
          </view>
        </view>
        <text class="profile-meta" v-if="profileSchool">{{ profileSchool }}</text>
      </view>

      <!-- 功能列表 -->
      <view class="card list">
        <view class="row" @click="onVehicle">
          <text class="row-label">我的车辆</text>
          <UniIcons type="forward" color="#b9c4bc" size="16" />
        </view>
        <view class="row" @click="onExchange">
          <text class="row-label">兑换记录</text>
          <UniIcons type="forward" color="#b9c4bc" size="16" />
        </view>
        <view class="row no-line">
          <text class="row-label">待确认提醒通知</text>
          <!-- 微信订阅消息开关：占位 switch，真机联调时接 wx.requestSubscribeMessage -->
          <switch :checked="notifyOn" :disabled="!loggedIn" @change="onNotifyChange" color="#2f6b4f" />
        </view>
      </view>

      <view class="card list">
        <view class="row" @click="onPrivacy">
          <text class="row-label">隐私政策与知情同意书</text>
          <UniIcons type="forward" color="#b9c4bc" size="16" />
        </view>
        <view v-if="loggedIn" class="row no-line" @click="onLogout">
          <text class="row-label is-danger">退出登录</text>
        </view>
      </view>

      <text class="foot">安全记录仅本人可见 · 每条提醒均可申诉 · 证据 90 天自动删除</text>
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
import { computed, ref } from 'vue';
import { onShow } from '@dcloudio/uni-app';
import UniIcons from '@dcloudio/uni-ui/lib/uni-icons/uni-icons.vue';
import LoginSheet from '../../components/LoginSheet.vue';
import { useUserStore } from '../../stores/useUserStore';
import { isLoggedIn } from '../../utils/auth';
import type { StudentProfile } from '../../utils/auth';

const store = useUserStore();
const loggedIn = ref(false);
const refreshing = ref(false);
const profile = ref<StudentProfile | null>(null);
const notifyOn = ref(false);
const sheetShow = ref(false);
const sheetReason = ref('登录后查看你的本人档案与安全记录');
const sheetStart = ref<'wx' | 'phone'>('wx');
const sheetOrigin = ref('50% 0%');

try {
  notifyOn.value = uni.getStorageSync('hg_notify_on') === '1';
} catch (_) {}

const profileName = computed(() => {
  const n = (profile.value && profile.value.name) || '';
  return n.trim() ? n.trim() : '同学';
});

const profileAvatar = computed(() => {
  const a = (profile.value && profile.value.avatar) || '';
  return a.trim() ? a.trim() : '';
});

const nameInitial = computed(() => {
  const n = profileName.value.trim();
  return n ? n.slice(0, 1) : '学';
});

const profileSub = computed(() => {
  const parts: string[] = [];
  const sid = profile.value && profile.value.student_id ? String(profile.value.student_id) : '';
  if (sid) parts.push(`学号 ${sid}`);
  const phone = profile.value && profile.value.phone ? String(profile.value.phone) : '';
  if (phone && phone.replace(/\D/g, '').length === 11) {
    const d = phone.replace(/\D/g, '');
    parts.push(`${d.slice(0, 3)}****${d.slice(7)}`);
  }
  return parts.length ? parts.join(' · ') : '学籍信息待完善';
});

const profileSchool = computed(() => {
  if (!profile.value) return '';
  const s = profile.value.school || '';
  const c = profile.value.class_name || '';
  const t = [s, c].filter((x) => x && x.trim()).join(' · ');
  return t;
});

function openSheet(reason: string, e?: unknown): void {
  sheetReason.value = reason;
  sheetStart.value = 'wx';
  sheetOrigin.value = originFromTap(e);
  sheetShow.value = true;
}

/** 点击处长出：按钮中心 X 映射为 sheet 顶边 transform-origin（Y=0%），取不到回落 50%。 */
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

async function checkLogin(): Promise<void> {
  if (!isLoggedIn()) {
    loggedIn.value = false;
    profile.value = null;
    return;
  }
  try {
    const p = await store.refreshStudentProfile();
    loggedIn.value = true;
    profile.value = p;
  } catch (_) {
    loggedIn.value = false;
    profile.value = null;
  }
}

// 下拉刷新：原生 refresher + 状态机，不讲故事（design.md §9.8.3）。
async function onPullRefresh(): Promise<void> {
  if (refreshing.value) return;
  refreshing.value = true;
  try {
    await checkLogin();
  } finally {
    refreshing.value = false;
  }
}

async function onLoginSuccess(p: StudentProfile | null): Promise<void> {
  sheetShow.value = false;
  if (!p || !p.has_phone) {
    openSheet('绑定手机号后继续');
    sheetStart.value = 'phone';
    return;
  }
  if (!p.has_profile) {
    uni.navigateTo({ url: '/pages/auth/auth' });
    return;
  }
  await checkLogin();
}

function needLogin(reason: string): boolean {
  if (loggedIn.value) return true;
  openSheet(reason);
  return false;
}

function onVehicle(): void {
  if (!needLogin('登录后查看你的绑定车辆')) return;
  uni.showToast({ title: '车辆绑定页即将上线', icon: 'none' });
}

function onExchange(): void {
  if (!needLogin('登录后查看你的兑换记录')) return;
  uni.showToast({ title: '兑换记录即将上线', icon: 'none' });
}

function onNotifyChange(e: Event): void {
  const detail = (e as unknown as { detail?: { value?: boolean } }).detail;
  const v = detail && typeof detail.value === 'boolean' ? detail.value : false;
  notifyOn.value = v;
  try {
    uni.setStorageSync('hg_notify_on', v ? '1' : '0');
  } catch (_) {}
  if (v) uni.showToast({ title: '已开启本地提醒开关', icon: 'none' });
}

function onPrivacy(): void {
  uni.navigateTo({ url: '/pages/auth/auth?consent=1' });
}

async function onLogout(): Promise<void> {
  await store.logout();
  loggedIn.value = false;
  profile.value = null;
  uni.showToast({ title: '已退出登录', icon: 'none' });
}

onShow(() => {
  checkLogin();
});
</script>

<style lang="scss" scoped src="./mine.scss"></style>

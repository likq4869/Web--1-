<template>
  <!-- 快捷登录弹窗：只做微信一键 + 绑定手机；学籍/同意书走全页 auth -->
  <view v-if="show" class="sheet-mask" @click="onMaskClose">
    <view class="sheet" :style="{ '--sheet-origin': origin }" @click.stop="">
      <view class="grabber" aria-hidden="true" />
      <text class="sheet-title">{{ sheetTitle }}</text>
      <text class="sheet-sub">{{ reasonText }}</text>

      <text class="err-box" v-if="storeError">{{ storeError }}</text>
      <text class="err-box" v-if="autoTip">{{ autoTip }}</text>

      <!-- wx 步：官方四步第 1 步 —— wx.login 取 code → 后端换 openid → 签发双 token 存本地 -->
      <template v-if="innerStep === 'wx'">
        <view class="benefit-list">
          <view class="benefit-item">
            <UniIcons type="checkmarkempty" color="#2f6b4f" size="14" />
            <text class="benefit-text">免记密码，一点即进</text>
          </view>
          <view class="benefit-item">
            <UniIcons type="checkmarkempty" color="#2f6b4f" size="14" />
            <text class="benefit-text">记录仅本人可见</text>
          </view>
        </view>
        <view class="action-col">
          <button class="primary-btn with-icon" :disabled="busy" @click="onWechatLogin">
            <UniIcons type="weixin" color="#ffffff" size="20" />
            <text>{{ busy ? '登录中…' : '微信一键登录' }}</text>
          </button>
          <button class="quiet-btn" :disabled="busy" @click="showPassword = !showPassword">
            {{ showPassword ? '收起账号登录' : '使用账号密码登录' }}
          </button>
        </view>
        <view v-if="showPassword" class="pwd-block">
          <text class="field-label">用户名</text>
          <input v-model="username" class="field-input" placeholder="请输入用户名" />
          <text class="field-label gap">密码</text>
          <input v-model="password" class="field-input" placeholder="请输入密码" password />
          <text class="field-error" v-if="formError">{{ formError }}</text>
          <view class="action-col">
            <button class="primary-btn" :disabled="busy || !canSubmit" @click="onPasswordLogin">登录</button>
          </view>
          <text class="tip">忘记密码？请联系管理员重置。</text>
        </view>
      </template>

      <!-- phone 步：官方四步第 2 步 —— getPhoneNumber 取 code → 后端换号码 → 凭 token 绑定 -->
      <template v-else>
      <text class="masked-num num" v-if="boundMasked">{{ boundMasked }}</text>
      <text class="masked-hint">{{ boundMasked ? '已绑定号码 · 仅本人可见' : '微信不会自动填入号码 · 点下方按钮授权' }}</text>
      <view class="action-col">
        <!-- #ifdef MP-WEIXIN -->
        <button class="primary-btn with-icon" :disabled="busy" open-type="getPhoneNumber" @getphonenumber="onGetPhoneNumber">
          <UniIcons type="phone-filled" color="#ffffff" size="18" />
          <text>{{ busy ? '绑定中…' : '微信一键绑定' }}</text>
        </button>
        <!-- #endif -->
        <!-- #ifndef MP-WEIXIN -->
        <text class="tip">当前为 H5 预览，不支持微信一键取号，请用下方输入框联调。</text>
        <!-- #endif -->
      </view>
      <view class="divider"><text class="divider-text">或手动输入</text></view>
        <text class="field-label gap">开发联调手机号（仅联调使用）</text>
        <input v-model="phoneInput" class="field-input num" placeholder="11 位大陆号码" maxlength="11" />
        <text class="field-error" v-if="formError">{{ formError }}</text>
        <view class="action-col">
          <button class="quiet-btn" :disabled="busy || !canMockBind" @click="onMockBindPhone">使用该号码绑定</button>
        </view>
      </template>

      <text class="agreement-text">登录即代表同意《用户协议》与《隐私政策》 · 安全记录仅本人可见 · 每条提醒均可申诉</text>
      <view class="safe-pad" />
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import UniIcons from '@dcloudio/uni-ui/lib/uni-icons/uni-icons.vue';
import { useUserStore } from '../stores/useUserStore';
import { validatePhone, wxLoginCode } from '../utils/auth';
import type { StudentProfile } from '../utils/auth';

const props = withDefaults(defineProps<{ show: boolean; reason?: string; startStep?: 'wx' | 'phone'; origin?: string }>(), {
  reason: '登录后查看你的文明积分与安全记录',
  startStep: 'wx',
  origin: '50% 0%',
});
const emit = defineEmits<{ (e: 'close'): void; (e: 'success', p: StudentProfile | null): void }>();

const store = useUserStore();
const busy = ref(false);
const innerStep = ref<'wx' | 'phone'>(props.startStep);
const formError = ref('');
const autoTip = ref('');
const showPassword = ref(false);
const username = ref('');
const password = ref('');
const phoneInput = ref('');
let reqSeq = 0;

const storeError = computed(() => store.error.value);
const canSubmit = computed(() => username.value.trim().length > 0 && password.value.length > 0);
const canMockBind = computed(() => validatePhone(phoneInput.value) === null);
const sheetTitle = computed(() => (innerStep.value === 'wx' ? '快捷登录' : '绑定手机号'));
const reasonText = computed(() => props.reason);
/** 已绑才展示，未绑定不给假号码占位避免误以为自动识别。 */
const boundMasked = computed(() => {
  const raw = (store.profile.value?.phone || '').replace(/\D/g, '');
  if (raw.length === 11) return `${raw.slice(0, 3)}****${raw.slice(7)}`;
  return '';
});

watch(
  () => props.show,
  (v) => {
    if (v) {
      innerStep.value = props.startStep;
      formError.value = '';
      autoTip.value = '';
    }
  },
);

function onMaskClose(): void {
  if (!busy.value) emit('close');
}

async function afterAuth(): Promise<void> {
  try {
    const p = await store.refreshStudentProfile();
    if (!p || !p.has_phone) {
      innerStep.value = 'phone';
      return;
    }
    emit('success', p);
  } catch (_) {
    innerStep.value = 'phone';
  }
}

async function onWechatLogin(): Promise<void> {
  const my = ++reqSeq;
  formError.value = '';
  autoTip.value = '';
  busy.value = true;
  try {
    const code = await wxLoginCode();
    if (my !== reqSeq) return;
    if (!code) {
      autoTip.value = '未能获取微信登录凭证，请重试或使用账号密码登录';
      showPassword.value = true;
      return;
    }
    await store.wechatLogin(code);
    if (my !== reqSeq) return;
    await afterAuth();
  } catch (_) {
    if (my !== reqSeq) return;
    showPassword.value = true;
  } finally {
    if (my === reqSeq) busy.value = false;
  }
}

async function onPasswordLogin(): Promise<void> {
  formError.value = '';
  if (!canSubmit.value) {
    formError.value = '请输入用户名与密码';
    return;
  }
  busy.value = true;
  try {
    await store.login(username.value, password.value);
    password.value = '';
    await afterAuth();
  } catch (_) {
    // 文案由 store.error 展示
  } finally {
    busy.value = false;
  }
}

interface PhoneEvent {
  detail?: { code?: string; errMsg?: string };
}

async function onGetPhoneNumber(e: PhoneEvent): Promise<void> {
  const errMsg = e.detail?.errMsg ?? '';
  if (errMsg.includes('deny')) {
    formError.value = '你已拒绝手机号授权，可用下方输入框手动绑定';
    return;
  }
  const code = e.detail?.code ?? '';
  if (!code) {
    formError.value = '未获得手机号授权，请重试或用下方输入框绑定';
    return;
  }
  formError.value = '';
  busy.value = true;
  try {
    await store.bindPhone(code, undefined);
    const p = await store.refreshStudentProfile().catch(() => null);
    emit('success', p);
  } catch (err) {
    // Mock 联调环境（后端未配 AppID）必然走此分支：code 无法解出号码，引导手输。
    const msg = err instanceof Error ? err.message : '';
    if (msg.includes('Mock') || msg.includes('直传 phone') || msg.includes('手动')) {
      formError.value = '联调环境不支持微信一键取号（后端未配 AppID 属正常），请在下方输入 11 位手机号绑定';
      return;
    }
    // 其余文案由 store.error 展示
  } finally {
    busy.value = false;
  }
}

async function onMockBindPhone(): Promise<void> {
  const err = validatePhone(phoneInput.value);
  if (err) {
    formError.value = err;
    return;
  }
  formError.value = '';
  busy.value = true;
  try {
    await store.bindPhone(undefined, phoneInput.value.trim());
    const p = await store.refreshStudentProfile().catch(() => null);
    emit('success', p);
  } catch (_) {
    // 409 已被占用等由 request 层文案透出
  } finally {
    busy.value = false;
  }
}
</script>

<style lang="scss" scoped src="./LoginSheet.scss"></style>

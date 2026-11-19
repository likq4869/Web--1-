<template>
  <scroll-view class="screen" scroll-y>
    <view class="content">
      <!-- 步骤：单行不换行，短标签防挤压换行 -->
      <view class="steps" aria-hidden="true">
        <view v-for="(label, i) in stepLabels" :key="label" class="step-item">
          <text
            class="step-dot num"
            :class="{ 'is-done': stepIndex > i, 'is-current': stepIndex === i }"
          >{{ i + 1 }}</text>
          <text class="step-label" :class="{ 'is-current': stepIndex === i }">{{ label }}</text>
          <UniIcons v-if="i < stepLabels.length - 1" type="forward" color="#b9c4bc" size="12" />
        </view>
      </view>

      <!-- 1/4 微信快捷登录 -->
      <view class="card" v-if="step === 'wx'">
        <text class="card-title">微信快捷登录</text>
        <text class="body-text">使用微信一键登录，无需记住密码，首次使用会自动创建账号。</text>
        <text class="err-box" v-if="autoTip">{{ autoTip }}</text>
        <text class="err-box" v-if="storeError">{{ storeError }}</text>
        <!-- 微信新规：登录不再弹头像昵称，头像昵称移到学籍一步用 chooseAvatar 授权 -->
        <view class="benefit-list">
          <view class="benefit-item">
            <UniIcons type="checkmarkempty" color="#2f6b4f" size="14" />
            <text class="benefit-text">免记密码，一点即进</text>
          </view>
          <view class="benefit-item">
            <UniIcons type="checkmarkempty" color="#2f6b4f" size="14" />
            <text class="benefit-text">记录仅本人可见</text>
          </view>
          <view class="benefit-item">
            <UniIcons type="checkmarkempty" color="#2f6b4f" size="14" />
            <text class="benefit-text">证据 90 天自动删除</text>
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
      </view>

      <!-- 2/4 绑定手机号：微信隐私规范下不会自动显示号码，必须点按钮授权 -->
      <view class="card card-delay-1" v-if="step === 'phone'">
        <text class="card-title">绑定手机号</text>
        <text class="body-text">微信不会自动填入号码，需点下方按钮授权；仅用于找回与通知，不做他用。</text>
        <text class="err-box" v-if="storeError">{{ storeError }}</text>
        <text class="masked-num num" v-if="boundMasked">{{ boundMasked }}</text>
        <text class="masked-hint">{{ boundMasked ? '已绑定号码 · 仅本人可见' : '尚未绑定 · 点下方按钮授权' }}</text>
        <view class="action-col">
          <!-- #ifdef MP-WEIXIN -->
          <button class="primary-btn with-icon" :disabled="busy" open-type="getPhoneNumber" @getphonenumber="onGetPhoneNumber">
            <UniIcons type="phone-filled" color="#ffffff" size="18" />
            <text>{{ busy ? '绑定中…' : '微信一键绑定' }}</text>
          </button>
          <!-- #endif -->
          <!-- #ifndef MP-WEIXIN -->
          <text class="tip">当前为 H5 预览不支持微信一键取号请用下方输入框联调。</text>
          <!-- #endif -->
        </view>
        <view class="divider"><text class="divider-text">或手动输入</text></view>
        <text class="field-label">开发联调手机号（仅联调使用）</text>
        <input v-model="phoneInput" class="field-input num" placeholder="11 位大陆号码" maxlength="11" />
        <text class="field-error" v-if="formError">{{ formError }}</text>
        <view class="action-col">
          <button class="quiet-btn" :disabled="busy || !canMockBind" @click="onMockBindPhone">使用该号码绑定</button>
          <button class="quiet-btn" :disabled="busy" @click="onLogout">换个账号登录</button>
        </view>
      </view>

      <!-- 3/4 学籍信息：头像昵称 + 简化组织填写（种子只覆盖部分分支，级联缺省可空手填） -->
      <view class="card card-delay-1" v-if="step === 'profile'">
        <text class="card-title">完善学籍信息</text>
        <text class="body-text">头像昵称用于页面展示，学号姓名用于关联你的安全记录。</text>
        <text class="err-box" v-if="storeError">{{ storeError }}</text>
        <view class="avatar-row">
          <!-- #ifdef MP-WEIXIN -->
          <button class="avatar-btn" open-type="chooseAvatar" @chooseavatar="onChooseAvatar" aria-label="选择头像">
            <image v-if="avatarUrl" class="avatar-img" :src="avatarUrl" mode="aspectFill" />
            <view v-else class="avatar-placeholder"><UniIcons type="person" color="#8b9a90" size="26" /></view>
          </button>
          <!-- #endif -->
          <!-- #ifndef MP-WEIXIN -->
          <view class="avatar-placeholder"><UniIcons type="person" color="#8b9a90" size="26" /></view>
          <!-- #endif -->
          <view class="avatar-meta">
            <text class="avatar-title">微信头像</text>
            <text class="avatar-sub">点左图经微信授权更换 · 仅展示用</text>
          </view>
        </view>
        <text class="field-label">昵称</text>
        <!-- #ifdef MP-WEIXIN -->
        <input v-model="nickname" class="field-input" type="nickname" placeholder="微信昵称（自动填入姓名栏）" maxlength="32" @blur="onNicknameBlur" />
        <!-- #endif -->
        <!-- #ifndef MP-WEIXIN -->
        <input v-model="nickname" class="field-input" placeholder="昵称（自动填入姓名栏）" maxlength="32" @blur="onNicknameBlur" />
        <!-- #endif -->
        <view v-if="loadingOrg"><text class="tip">正在加载学校列表…</text></view>
        <view v-else>
          <text class="field-label gap">学校 *</text>
          <picker v-if="schools.length && !manualOrg" :range="schoolNames" :value="schoolIdx" @change="onSchoolChange"><view class="picker">{{ form.school || '请选择学校' }}</view></picker>
          <input v-else v-model="form.school" class="field-input" placeholder="如：示范大学" maxlength="64" />
          <text class="field-label gap">二级学院</text>
          <picker v-if="colleges.length" :range="collegeNames" :value="collegeIdx" @change="onCollegeChange"><view class="picker">{{ form.college || '请选择（可空）' }}</view></picker>
          <input v-else v-model="form.college" class="field-input" placeholder="如：计算机学院（可空）" maxlength="64" />
          <text class="field-label gap">年级</text>
          <picker v-if="grades.length" :range="gradeNames" :value="gradeIdx" @change="onGradeChange"><view class="picker">{{ form.grade || '请选择（可空）' }}</view></picker>
          <input v-else v-model="form.grade" class="field-input" placeholder="如：2024 级（可空）" maxlength="16" />
          <text class="field-label gap">专业</text>
          <picker v-if="majors.length" :range="majorNames" :value="majorIdx" @change="onMajorChange"><view class="picker">{{ form.major || '请选择（可空）' }}</view></picker>
          <input v-else v-model="form.major" class="field-input" placeholder="如：软件工程（可空）" maxlength="64" />
          <text class="field-label gap">班级</text>
          <picker v-if="classes.length" :range="classNames" :value="classIdx" @change="onClassChange"><view class="picker">{{ form.class_name || '请选择（可空）' }}</view></picker>
          <input v-else v-model="form.class_name" class="field-input" placeholder="如：计科 2401（可空）" maxlength="64" />
          <button v-if="schools.length" class="quiet-btn org-toggle" @click="manualOrg = !manualOrg">{{ manualOrg ? '返回级联选择' : '名单中没有？手动填写学校' }}</button>
        </view>
        <text class="field-label gap">学号 *</text>
        <input v-model="form.student_id" class="field-input num" placeholder="8-12 位数字" maxlength="12" />
        <text class="field-label gap">姓名 *</text>
        <input v-model="form.name" class="field-input" placeholder="请输入姓名" maxlength="32" />
        <text class="field-error" v-if="formError">{{ formError }}</text>
        <view class="action-col">
          <button class="primary-btn" :disabled="busy" @click="onSaveProfile">保存并继续</button>
          <button class="quiet-btn" :disabled="busy" @click="onLogout">换个账号登录</button>
        </view>
      </view>

      <!-- 4/4 知情同意：骑行环保卡片重做 -->
      <view class="card card-delay-2" v-if="step === 'consent'">
        <view class="consent-hero">
          <view class="consent-badge"><UniIcons type="auth" color="#2f6b4f" size="22" /></view>
          <view class="consent-hero-main">
            <text class="card-title no-gap">骑行安全监测知情同意书</text>
            <text class="consent-hero-sub">公开区域检测 · 不做人脸识别 · 全程可申诉</text>
          </view>
        </view>
        <view class="fact-row">
          <view class="fact"><UniIcons type="eye-slash" color="#2f6b4f" size="16" /><text class="fact-text">仅本人可见</text></view>
          <view class="fact"><UniIcons type="trash" color="#2f6b4f" size="16" /><text class="fact-text">证据 90 天删除</text></view>
          <view class="fact"><UniIcons type="help" color="#2f6b4f" size="16" /><text class="fact-text">每条可申诉</text></view>
        </view>
        <view class="consent-clauses">
          <view class="clause" v-for="(c, i) in consentClauses" :key="c.title">
            <text class="clause-num num">{{ i + 1 }}</text>
            <view class="clause-main">
              <text class="clause-title">{{ c.title }}</text>
              <text class="clause-body">{{ c.body }}</text>
            </view>
          </view>
        </view>
        <view class="consent-row" @click="agreed = !agreed">
          <view class="checkbox" :class="{ 'is-checked': agreed }"><text v-if="agreed" class="check-mark">✓</text></view>
          <text class="consent-confirm">我已阅读并同意上述内容</text>
        </view>
        <view class="action-col">
          <button class="primary-btn" :disabled="busy || !agreed" @click="onConsent">确认并进入首页</button>
        </view>
      </view>

      <view class="agreement">
        <text class="agreement-text">登录即代表同意《用户协议》与《隐私政策》 · 安全记录仅本人可见 · 每条提醒均可申诉</text>
      </view>
    </view>
  </scroll-view>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { onLoad } from '@dcloudio/uni-app';
import UniIcons from '@dcloudio/uni-ui/lib/uni-icons/uni-icons.vue';
import { useUserStore } from '../../stores/useUserStore';
import {
  isLoggedIn,
  validatePhone,
  validateProfileForm,
  wxLoginCode,
} from '../../utils/auth';
import type { OrgUnit, ProfileForm } from '../../utils/auth';

const store = useUserStore();
type Step = 'wx' | 'phone' | 'profile' | 'consent';
/* 短标签防换行：四个字以内，单行展示 */
const stepLabels = ['登录', '手机', '学籍', '同意'];
const step = ref<Step>('wx');
const stepIndex = computed(() => ({ wx: 0, phone: 1, profile: 2, consent: 3 })[step.value]);

const busy = ref(false);
const formError = ref('');
const autoTip = ref('');
const storeError = computed(() => store.error.value);
const showPassword = ref(false);
const username = ref('');
const password = ref('');
const phoneInput = ref('');
const agreed = ref(false);
/* 头像昵称：微信新规下登录不再弹头像，需用 chooseAvatar + nickname 授权 */
const avatarUrl = ref('');
const nickname = ref('');
let reqSeq = 0;

const canSubmit = computed(() => username.value.trim().length > 0 && password.value.length > 0);
const canMockBind = computed(() => validatePhone(phoneInput.value) === null);

/** 已绑号码才展示脱敏，未绑定不给假号码占位，避免误以为自动识别。 */
const boundMasked = computed(() => {
  const raw = (store.profile.value?.phone || '').replace(/\D/g, '');
  if (raw.length === 11) return `${raw.slice(0, 3)}****${raw.slice(7)}`;
  return '';
});

const consentClauses = [
  { title: '采集什么', body: '校门等公开区域骑行佩戴状态与车辆外观不做人脸识别不采无关信息。' },
  { title: '用来做什么', body: '仅用于本人查看、申诉与积分计算；管理只在审批复核内看证据帧。' },
  { title: '存多久', body: '证据加密存 90 天自动删除；统计数据脱敏保留。' },
  { title: '你的权利', body: '随时看本人记录、每条可申诉、可解绑学号申诉走人工二次处理。' },
];

const form = reactive<ProfileForm>({ school: '', college: '', grade: '', major: '', class_name: '', student_id: '', name: '', avatar: '' });
const schools = ref<OrgUnit[]>([]);
const colleges = ref<OrgUnit[]>([]);
const grades = ref<OrgUnit[]>([]);
const majors = ref<OrgUnit[]>([]);
const classes = ref<OrgUnit[]>([]);
const schoolIdx = ref(0);
const collegeIdx = ref(0);
const gradeIdx = ref(0);
const majorIdx = ref(0);
const classIdx = ref(0);
const manualOrg = ref(false);
const loadingOrg = ref(false);
let schoolId = '';
let collegeId = '';
let gradeId = '';
let majorId = '';

const schoolNames = computed(() => schools.value.map((u) => u.name));
const collegeNames = computed(() => colleges.value.map((u) => u.name));
const gradeNames = computed(() => grades.value.map((u) => u.name));
const majorNames = computed(() => majors.value.map((u) => u.name));
const classNames = computed(() => classes.value.map((u) => u.name));

function hasConsent(): boolean {
  try {
    return uni.getStorageSync('hg_consent_v1') === '1';
  } catch (_) {
    return false;
  }
}

function enterHome(): void {
  // home 已是 tabBar 页：用 switchTab 回首页（reLaunch 到 tab 页会被拦截）
  try {
    uni.switchTab({ url: '/pages/home/home' });
  } catch (_) {
    uni.reLaunch({ url: '/pages/home/home' });
  }
}

async function routeAfterAuth(profile: { has_phone: boolean; has_profile: boolean } | null): Promise<void> {
  if (!profile) {
    step.value = 'phone';
    return;
  }
  if (!profile.has_phone) {
    step.value = 'phone';
    return;
  }
  if (!profile.has_profile) {
    step.value = 'profile';
    await loadSchools();
    return;
  }
  if (hasConsent()) {
    enterHome();
    return;
  }
  step.value = 'consent';
}

async function refreshRouting(): Promise<void> {
  try {
    const p = await store.refreshStudentProfile();
    syncProfileToForm(p);
    await routeAfterAuth(p);
  } catch (_) {
    step.value = 'phone';
  }
}

/** 已有档案回填表单头像昵称避免重复填写。 */
function syncProfileToForm(p: { avatar?: string | null; name?: string | null } | null): void {
  if (!p) return;
  if (p.avatar) avatarUrl.value = p.avatar;
  if (p.name && !form.name) {
    form.name = p.name;
    if (!nickname.value) nickname.value = p.name;
  }
}

function onChooseAvatar(e: { detail?: { avatarUrl?: string } }): void {
  const url = e.detail?.avatarUrl ?? '';
  if (url) {
    avatarUrl.value = url;
    form.avatar = url;
  }
}

function onNicknameBlur(): void {
  const v = nickname.value.trim();
  if (v && !form.name.trim()) form.name = v.slice(0, 32);
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
      autoTip.value = '未能获取微信登录凭证请重试或使用账号密码登录';
      showPassword.value = true;
      return;
    }
    await store.wechatLogin(code);
    if (my !== reqSeq) return;
    await refreshRouting();
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
    await refreshRouting();
  } catch (_) {
    // 文案由 store.error 展示。
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
    formError.value = '未获得手机号授权请重试或用下方输入框绑定';
    return;
  }
  formError.value = '';
  busy.value = true;
  try {
    await store.bindPhone(code, undefined);
    step.value = 'profile';
    await loadSchools();
  } catch (err) {
    // Mock 联调环境（后端未配 AppID）必然走此分支：code 无法解出号码，引导手输。
    const msg = err instanceof Error ? err.message : '';
    if (msg.includes('Mock') || msg.includes('直传 phone')) {
      formError.value = '联调环境不支持微信一键取号（后端未配 AppID 属正常），请在下方输入 11 位手机号绑定';
      return;
    }
    // 其余文案由 store.error 展示。
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
    step.value = 'profile';
    await loadSchools();
  } catch (_) {
    // 409 已被占用等由 request 层文案透出。
  } finally {
    busy.value = false;
  }
}

async function loadSchools(): Promise<void> {
  loadingOrg.value = true;
  try {
    const items = await store.loadOrgUnits(undefined, 'school');
    schools.value = items.length ? items : await store.loadOrgUnits();
    if (!schools.value.length) manualOrg.value = true;
  } catch (_) {
    manualOrg.value = true;
  } finally {
    loadingOrg.value = false;
  }
}

function pickIndex(e: { detail?: { value?: number | string } }): number {
  const v = e.detail?.value;
  const n = typeof v === 'string' ? Number(v) : Number(v ?? 0);
  return Number.isFinite(n) && n >= 0 ? n : 0;
}

async function onSchoolChange(e: { detail?: { value?: number | string } }): Promise<void> {
  const i = pickIndex(e);
  const sel = schools.value[i];
  if (!sel) return;
  schoolIdx.value = i;
  form.school = sel.name;
  schoolId = sel.unit_id;
  form.college = '';
  form.grade = '';
  form.major = '';
  form.class_name = '';
  /* 缺省分支允许为空：不断言必须有下级，无下级就留空手填不卡死 */
  colleges.value = await store.loadOrgUnits(schoolId).catch(() => []);
  collegeIdx.value = 0;
  grades.value = [];
  majors.value = [];
  classes.value = [];
}

async function onCollegeChange(e: { detail?: { value?: number | string } }): Promise<void> {
  const i = pickIndex(e);
  const sel = colleges.value[i];
  if (!sel) return;
  collegeIdx.value = i;
  form.college = sel.name;
  collegeId = sel.unit_id;
  form.grade = '';
  form.major = '';
  form.class_name = '';
  grades.value = await store.loadOrgUnits(collegeId).catch(() => []);
  gradeIdx.value = 0;
  majors.value = [];
  classes.value = [];
}

async function onGradeChange(e: { detail?: { value?: number | string } }): Promise<void> {
  const i = pickIndex(e);
  const sel = grades.value[i];
  if (!sel) return;
  gradeIdx.value = i;
  form.grade = sel.name;
  gradeId = sel.unit_id;
  form.major = '';
  form.class_name = '';
  majors.value = await store.loadOrgUnits(gradeId).catch(() => []);
  majorIdx.value = 0;
  classes.value = [];
}

async function onMajorChange(e: { detail?: { value?: number | string } }): Promise<void> {
  const i = pickIndex(e);
  const sel = majors.value[i];
  if (!sel) return;
  majorIdx.value = i;
  form.major = sel.name;
  majorId = sel.unit_id;
  form.class_name = '';
  classes.value = await store.loadOrgUnits(majorId).catch(() => []);
  classIdx.value = 0;
}

function onClassChange(e: { detail?: { value?: number | string } }): void {
  const sel = classes.value[pickIndex(e)];
  if (!sel) return;
  classIdx.value = pickIndex(e);
  form.class_name = sel.name;
}

async function onSaveProfile(): Promise<void> {
  form.avatar = avatarUrl.value.trim();
  const err = validateProfileForm(form);
  if (err) {
    formError.value = err;
    return;
  }
  formError.value = '';
  busy.value = true;
  try {
    await store.saveProfile({ ...form });
    step.value = 'consent';
  } catch (_) {
    // 409 学号被占等由 request 层文案透出。
  } finally {
    busy.value = false;
  }
}

async function onLogout(): Promise<void> {
  busy.value = true;
  try {
    await store.logout();
    step.value = 'wx';
    agreed.value = false;
  } finally {
    busy.value = false;
  }
}

function onConsent(): void {
  if (!agreed.value) return;
  try {
    uni.setStorageSync('hg_consent_v1', '1');
  } catch (_) {}
  enterHome();
}

// 我的页隐私入口直达：?consent=1 时只展示同意书，不走路由判定
const consentOnly = ref(false);
onLoad((opts?: Record<string, string>) => {
  if (opts && opts.consent === '1') consentOnly.value = true;
});

onMounted(async () => {
  if (consentOnly.value) {
    step.value = 'consent';
    return;
  }
  const my = ++reqSeq;
  if (!isLoggedIn()) {
    step.value = 'wx';
    return;
  }
  busy.value = true;
  try {
    const p = await store.refreshStudentProfile();
    if (my !== reqSeq) return;
    syncProfileToForm(p);
    await routeAfterAuth(p);
  } catch (_) {
    if (my === reqSeq) step.value = 'wx';
  } finally {
    if (my === reqSeq) busy.value = false;
  }
});
</script>

<style lang="scss" src="./auth.scss"></style>

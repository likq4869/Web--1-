/**
 * 小程序认证封装：微信快捷登录 + 手机号绑定 + 学籍档案 + 组织级联。
 * 后端契约（helmet-guard/app/schemas/auth.py, app/schemas/org.py）：
 * - POST /api/v1/auth/wechat-login {code} → {access_token, refresh_token, user}
 * - POST /api/v1/auth/bind-phone {phone_code?, phone?} → CurrentUser
 * - GET /api/v1/auth/profile → StudentProfileOut {has_phone, has_profile, ...}
 * - POST /api/v1/auth/profile {school, college, grade, major, class_name, student_id, name}
 * - GET /api/v1/org/units?parent_id=&unit_type= → {items, parent_id}
 * 旧账号链路（用户名密码 / bind-student）保留为兜底，便于开发联调。
 */

import { AUTH_BASE, apiGet, apiPost, clearTokens, getAccessToken, saveTokens } from './api';
import type { MiniUser } from './api';

export type { MiniUser };

const USER_KEY = 'hg_user';

export interface StudentProfile {
  student_id: string | null;
  name: string | null;
  school: string | null;
  college: string | null;
  grade: string | null;
  major: string | null;
  class_name: string | null;
  phone: string | null;
  avatar: string | null;
  has_phone: boolean;
  has_profile: boolean;
}

export interface OrgUnit {
  unit_id: string;
  unit_type: string;
  name: string;
  parent_id: string | null;
  sort_order: number;
}

export interface ProfileForm {
  school: string;
  college: string;
  grade: string;
  major: string;
  class_name: string;
  student_id: string;
  name: string;
  avatar: string;
}

export function readStoredUser(): MiniUser | null {
  try {
    const raw = uni.getStorageSync(USER_KEY);
    if (typeof raw === 'string' && raw) {
      const parsed = JSON.parse(raw) as MiniUser;
      if (parsed && typeof parsed.id === 'string') return parsed;
    }
    if (raw && typeof raw === 'object') return raw as MiniUser;
  } catch (_) {}
  return null;
}

export function saveStoredUser(user: MiniUser | null): void {
  try {
    if (user) uni.setStorageSync(USER_KEY, JSON.stringify(user));
    else uni.removeStorageSync(USER_KEY);
  } catch (_) {}
}

export function isLoggedIn(): boolean {
  return getAccessToken().length > 0;
}

/** 调起微信登录拿 code（H5 无 wx 时返回空，由调用方降级为手动）。 */
export function wxLoginCode(): Promise<string> {
  return new Promise((resolve) => {
    try {
      uni.login({
        provider: 'weixin',
        success: (res: { code?: string }) => resolve(typeof res?.code === 'string' ? res.code : ''),
        fail: () => resolve(''),
      });
    } catch (_) {
      resolve('');
    }
  });
}

export async function loginWithWechat(code: string): Promise<MiniUser> {
  const trimmed = (code ?? '').trim();
  if (!trimmed) throw new Error('未能获取微信登录凭证，请重试');
  const data = await apiPost<{ access_token: string; refresh_token: string; user: MiniUser }>(
    `${AUTH_BASE}/wechat-login`,
    { code: trimmed },
    { skipAuthRefresh: true },
  );
  saveTokens(data.access_token, data.refresh_token);
  saveStoredUser(data.user);
  return data.user;
}

export async function loginWithPassword(username: string, password: string): Promise<MiniUser> {
  const data = await apiPost<{ access_token: string; refresh_token: string; user: MiniUser }>(
    `${AUTH_BASE}/login`,
    { username: username.trim(), password },
    { skipAuthRefresh: true },
  );
  saveTokens(data.access_token, data.refresh_token);
  saveStoredUser(data.user);
  return data.user;
}

export async function fetchProfile(): Promise<MiniUser> {
  const user = await apiGet<MiniUser>(`${AUTH_BASE}/me`);
  saveStoredUser(user);
  return user;
}

export async function fetchStudentProfile(): Promise<StudentProfile> {
  return apiGet<StudentProfile>(`${AUTH_BASE}/profile`);
}

export interface WechatSessionCheck {
  wechat_valid: boolean;
  mock: boolean;
}

export async function checkWechatSession(): Promise<WechatSessionCheck> {
  return apiGet<WechatSessionCheck>(`${AUTH_BASE}/check-session`);
}

export async function bindPhone(params: { phoneCode?: string; phone?: string }): Promise<MiniUser> {
  const body: Record<string, string> = {};
  if (params.phoneCode) body.phone_code = params.phoneCode;
  if (params.phone) body.phone = params.phone;
  const user = await apiPost<MiniUser>(`${AUTH_BASE}/bind-phone`, body);
  saveStoredUser(user);
  return user;
}

export async function upsertStudentProfile(form: ProfileForm): Promise<StudentProfile> {
  const data = await apiPost<{ user: MiniUser; student: StudentProfile }>(
    `${AUTH_BASE}/profile`,
    {
      school: form.school.trim(),
      college: form.college.trim(),
      grade: form.grade.trim(),
      major: form.major.trim(),
      class_name: form.class_name.trim(),
      student_id: form.student_id.trim(),
      name: form.name.trim(),
      avatar: form.avatar.trim() || undefined,
    },
  );
  saveStoredUser(data.user);
  return data.student;
}

export async function listOrgUnits(parentId?: string, unitType?: string): Promise<OrgUnit[]> {
  const query = [];
  if (parentId) query.push(`parent_id=${encodeURIComponent(parentId)}`);
  if (unitType) query.push(`unit_type=${encodeURIComponent(unitType)}`);
  const suffix = query.length ? `?${query.join('&')}` : '';
  const data = await apiGet<{ items: OrgUnit[] }>(`/api/v1/org/units${suffix}`);
  return Array.isArray(data.items) ? data.items : [];
}

export async function bindStudent(studentId: string): Promise<MiniUser> {
  const user = await apiPost<MiniUser>(`${AUTH_BASE}/bind-student`, { student_id: studentId.trim() });
  saveStoredUser(user);
  return user;
}

export async function logoutRemote(): Promise<void> {
  try {
    if (getAccessToken()) {
      await apiPost<{ logged_out: boolean }>(`${AUTH_BASE}/logout`, {});
    }
  } catch (_) {
    // 登出失败不阻塞本地清理：无状态 JWT 本地丢弃即等效退出。
  } finally {
    clearTokens();
    saveStoredUser(null);
  }
}

/** 学号校验：8-12 位纯数字（与后端 pattern ^\d+$ 一致）。 */
export function validateStudentId(value: string): string | null {
  const v = (value ?? '').trim();
  if (!v) return '请输入学号';
  if (!/^\d{8,12}$/.test(v)) return '学号为 8-12 位数字';
  return null;
}

/** 手机号校验：11 位大陆号码（与后端 _PHONE_PATTERN 一致）。 */
export function validatePhone(value: string): string | null {
  const v = (value ?? '').trim();
  if (!v) return '请输入手机号';
  if (!/^1\d{10}$/.test(v)) return '手机号格式不正确，应为 11 位大陆号码';
  return null;
}

/** 学籍表单校验：仅学校/学号/姓名必填，其余级联允许为空（种子只覆盖部分分支，避免死胡同）。 */
export function validateProfileForm(form: ProfileForm): string | null {
  if (!form.school.trim()) return '请选择学校';
  const idErr = validateStudentId(form.student_id);
  if (idErr) return idErr;
  if (!form.name.trim()) return '请输入姓名';
  if (form.name.trim().length > 32) return '姓名过长，请检查后重试';
  return null;
}

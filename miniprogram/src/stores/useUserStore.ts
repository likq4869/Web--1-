/** 用户状态（轻量 composable，不引入 Pinia，控包体）。 */
import { readonly, ref } from 'vue';
import {
  bindPhone as bindPhoneRemote,
  bindStudent as bindStudentRemote,
  fetchProfile,
  fetchStudentProfile,
  listOrgUnits,
  loginWithPassword,
  loginWithWechat,
  logoutRemote,
  readStoredUser,
  upsertStudentProfile,
} from '../utils/auth';
import type { MiniUser, OrgUnit, ProfileForm, StudentProfile } from '../utils/auth';

const user = ref<MiniUser | null>(readStoredUser());
const profile = ref<StudentProfile | null>(null);
const loading = ref(false);
const error = ref('');

export function useUserStore() {
  async function refresh(): Promise<void> {
    loading.value = true;
    error.value = '';
    try {
      user.value = await fetchProfile();
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载失败，请重试';
    } finally {
      loading.value = false;
    }
  }

  async function refreshStudentProfile(): Promise<StudentProfile | null> {
    loading.value = true;
    error.value = '';
    try {
      profile.value = await fetchStudentProfile();
      return profile.value;
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载失败，请重试';
      throw e;
    } finally {
      loading.value = false;
    }
  }

  async function wechatLogin(code: string): Promise<MiniUser> {
    loading.value = true;
    error.value = '';
    try {
      const next = await loginWithWechat(code);
      user.value = next;
      return next;
    } catch (e) {
      error.value = e instanceof Error ? e.message : '微信登录失败，请重试';
      throw e;
    } finally {
      loading.value = false;
    }
  }

  async function login(username: string, password: string): Promise<MiniUser> {
    loading.value = true;
    error.value = '';
    try {
      const next = await loginWithPassword(username, password);
      user.value = next;
      return next;
    } catch (e) {
      error.value = e instanceof Error ? e.message : '登录失败，请重试';
      throw e;
    } finally {
      loading.value = false;
    }
  }

  async function bindPhone(phoneCode?: string, phone?: string): Promise<MiniUser> {
    loading.value = true;
    error.value = '';
    try {
      const next = await bindPhoneRemote({ phoneCode, phone });
      user.value = next;
      return next;
    } catch (e) {
      error.value = e instanceof Error ? e.message : '手机号绑定失败，请重试';
      throw e;
    } finally {
      loading.value = false;
    }
  }

  async function saveProfile(form: ProfileForm): Promise<StudentProfile> {
    loading.value = true;
    error.value = '';
    try {
      const next = await upsertStudentProfile(form);
      profile.value = next;
      return next;
    } catch (e) {
      error.value = e instanceof Error ? e.message : '保存失败，请重试';
      throw e;
    } finally {
      loading.value = false;
    }
  }

  async function loadOrgUnits(parentId?: string, unitType?: string): Promise<OrgUnit[]> {
    loading.value = true;
    error.value = '';
    try {
      return await listOrgUnits(parentId, unitType);
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载组织列表失败，请重试';
      throw e;
    } finally {
      loading.value = false;
    }
  }

  async function bind(studentId: string): Promise<MiniUser> {
    loading.value = true;
    error.value = '';
    try {
      const next = await bindStudentRemote(studentId);
      user.value = next;
      return next;
    } catch (e) {
      error.value = e instanceof Error ? e.message : '绑定失败，请重试';
      throw e;
    } finally {
      loading.value = false;
    }
  }

  async function logout(): Promise<void> {
    await logoutRemote();
    user.value = null;
    profile.value = null;
  }

  return {
    user: readonly(user),
    profile: readonly(profile),
    loading: readonly(loading),
    error: readonly(error),
    refresh,
    refreshStudentProfile,
    wechatLogin,
    login,
    bindPhone,
    saveProfile,
    loadOrgUnits,
    bind,
    logout,
  };
}

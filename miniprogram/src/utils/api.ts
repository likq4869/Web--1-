/**
 * 小程序请求层：uni.request 封装（P4-1）。
 * 与后端契约对齐：
 * - 成功：HTTP 200 + `{code: 0, data, message}`，统一解包取 data；
 * - 失败：HTTP 状态码 + `{code: "STRING", message, data: null, trace_id}`，
 *   code 为字符串机器码（UNAUTHORIZED / NOT_FOUND / ...），与 numeric 业务码不同。
 * - 401 → 用 refresh token 静默刷新 → 只重放一次（防无限循环）；
 * - 并发刷新锁：多个请求同时 401 时只发一次刷新，其余等待同一 Promise。
 */

import { detailToText } from './selfcheck';

export const AUTH_BASE = '/api/v1/auth';
export const ME_BASE = '/api/v1/me';
const REQUEST_TIMEOUT_MS = 15000;

const ACCESS_KEY = 'hg_access_token';
const REFRESH_KEY = 'hg_refresh_token';

export interface MiniUser {
  id: string;
  username: string;
  display_name: string;
  role: string;
  source_ids: string[];
}

export class MiniApiError extends Error {
  readonly status: number;
  readonly code: string | number;
  readonly traceId?: string;

  constructor(params: { status: number; code: string | number; message: string; traceId?: string }) {
    super(params.message);
    this.name = 'MiniApiError';
    this.status = params.status;
    this.code = params.code;
    this.traceId = params.traceId;
  }
}

export interface RequestOptions {
  /** 登录/刷新接口自身使用：跳过自动刷新重放 */
  skipAuthRefresh?: boolean;
  /** 携带鉴权头（默认 true；登录页首屏探测可关闭） */
  withAuth?: boolean;
}

function readStored(key: string): string {
  try {
    const v = uni.getStorageSync(key);
    return typeof v === 'string' ? v : '';
  } catch (_) {
    return '';
  }
}

export function getAccessToken(): string {
  return readStored(ACCESS_KEY);
}

export function getRefreshToken(): string {
  return readStored(REFRESH_KEY);
}

export function saveTokens(access: string, refresh: string): void {
  try {
    uni.setStorageSync(ACCESS_KEY, access);
    uni.setStorageSync(REFRESH_KEY, refresh);
  } catch (_) {}
}

export function clearTokens(): void {
  try {
    uni.removeStorageSync(ACCESS_KEY);
    uni.removeStorageSync(REFRESH_KEY);
  } catch (_) {}
}

/** 自查页已有 BaseURL 逻辑（本地联调用 storage 覆盖），请求层复用，保持单点。 */
function getApiOrigin(): string {
  try {
    const mod = 'hg_selfcheck_base_url';
    const v = uni.getStorageSync(mod);
    if (typeof v === 'string' && v.trim()) return v.trim().replace(/\/$/, '');
  } catch (_) {}
  return 'http://127.0.0.1:8000';
}

/** 正在进行的刷新 Promise —— 并发 401 只触发一次刷新。 */
let refreshing: Promise<string> | null = null;

function statusMessage(status: number, serverMessage: string): string {
  if (serverMessage) return serverMessage;
  switch (status) {
    case 0:
      return '网络异常，请检查连接后重试';
    case 401:
      return '登录已过期，请重新登录';
    case 403:
      return '没有访问权限';
    case 404:
      return '请求的资源不存在';
    case 409:
      return '当前状态已发生变化，请刷新后重试';
    case 422:
      return '提交的数据不符合要求，请检查后重试';
    case 429:
      return '请求过于频繁，请稍后重试';
    case 503:
      return '模型尚未就绪，请稍后重试';
    default:
      return status ? `请求失败（${status}），请重试` : '请求失败，请重试';
  }
}

interface UniSuccess {
  statusCode: number;
  data: unknown;
}

function uniRequestRaw(options: {
  url: string;
  method: 'GET' | 'POST' | 'PUT' | 'DELETE';
  data?: unknown;
  header?: Record<string, string>;
}): Promise<UniSuccess> {
  return new Promise((resolve, reject) => {
    uni.request({
      url: options.url,
      method: options.method,
      data: (options.data ?? {}) as never,
      header: options.header,
      timeout: REQUEST_TIMEOUT_MS,
      success: (res) => {
        resolve({ statusCode: Number((res as { statusCode?: number }).statusCode ?? 0), data: (res as { data?: unknown }).data });
      },
      fail: (err) => {
        reject(new MiniApiError({ status: 0, code: 'NETWORK', message: `网络异常：${String((err as { errMsg?: string })?.errMsg ?? '请检查后端地址后重试')}` }));
      },
    });
  });
}

function unwrapSuccess(status: number, body: unknown, url: string): unknown {
  if (status !== 200) {
    const data = (body ?? {}) as Record<string, unknown>;
    const message = detailToText(data.detail ?? data.message ?? data);
    const traceId = typeof data.trace_id === 'string' ? data.trace_id : undefined;
    const code = typeof data.code === 'string' || typeof data.code === 'number' ? data.code : status;
    throw new MiniApiError({ status, code, message: statusMessage(status, message), traceId });
  }
  if (body !== null && typeof body === 'object' && 'code' in (body as Record<string, unknown>)) {
    const payload = body as { code: unknown; data: unknown; message: unknown };
    if (payload.code !== 0) {
      const message = detailToText((payload as { detail?: unknown }).detail ?? payload.message ?? '');
      throw new MiniApiError({ status, code: typeof payload.code === 'number' ? payload.code : status, message: statusMessage(status, message) });
    }
    return payload.data;
  }
  // 裸对象（未包络）：原样返回，调用方做 sanitize。
  void url;
  return body;
}

async function ensureRefreshed(): Promise<string> {
  if (refreshing) return refreshing;
  const token = getRefreshToken();
  if (!token) return Promise.reject(new MiniApiError({ status: 401, code: 'NO_REFRESH', message: '登录已过期，请重新登录' }));
  refreshing = (async () => {
    const res = await uniRequestRaw({
      url: `${getApiOrigin()}${AUTH_BASE}/refresh`,
      method: 'POST',
      data: { refresh_token: token },
      header: { 'Content-Type': 'application/json' },
    });
    const data = unwrapSuccess(res.statusCode, res.data, 'refresh') as { access_token?: unknown; refresh_token?: unknown };
    const access = typeof data?.access_token === 'string' ? data.access_token : '';
    const refresh = typeof data?.refresh_token === 'string' ? data.refresh_token : '';
    if (!access) throw new MiniApiError({ status: 401, code: 'REFRESH_FAILED', message: '登录已过期，请重新登录' });
    saveTokens(access, refresh || token);
    return access;
  })();
  try {
    return await refreshing;
  } finally {
    refreshing = null;
  }
}

async function doRequest<T>(method: 'GET' | 'POST' | 'PUT' | 'DELETE', path: string, data?: unknown, options?: RequestOptions): Promise<T> {
  const withAuth = options?.withAuth !== false;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = getAccessToken();
  if (withAuth && token) headers.Authorization = `Bearer ${token}`;
  const res = await uniRequestRaw({ url: `${getApiOrigin()}${path}`, method, data, header: headers });
  try {
    return unwrapSuccess(res.statusCode, res.data, path) as T;
  } catch (err) {
    if (err instanceof MiniApiError && err.status === 401 && !options?.skipAuthRefresh && withAuth) {
      const fresh = await ensureRefreshed();
      const retry = await uniRequestRaw({
        url: `${getApiOrigin()}${path}`,
        method,
        data,
        header: { ...headers, Authorization: `Bearer ${fresh}` },
      });
      return unwrapSuccess(retry.statusCode, retry.data, path) as T;
    }
    throw err;
  }
}

export function apiGet<T>(path: string, data?: unknown, options?: RequestOptions): Promise<T> {
  return doRequest<T>('GET', path, data, options);
}

export function apiPost<T>(path: string, data?: unknown, options?: RequestOptions): Promise<T> {
  return doRequest<T>('POST', path, data, options);
}

export function apiPut<T>(path: string, data?: unknown, options?: RequestOptions): Promise<T> {
  return doRequest<T>('PUT', path, data, options);
}

export function apiDelete<T>(path: string, options?: RequestOptions): Promise<T> {
  return doRequest<T>('DELETE', path, undefined, options);
}

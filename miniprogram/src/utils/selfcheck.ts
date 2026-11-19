/** 自查后端地址配置：微信开发者工具里 127.0.0.1 可用；真机必须改成电脑局域网 IP。 */
export const DEFAULT_BASE_URL = 'http://127.0.0.1:8000';
export const BASE_URL_KEY = 'hg_selfcheck_base_url';

export function getBaseUrl(): string {
  try {
    const v = uni.getStorageSync(BASE_URL_KEY);
    if (typeof v === 'string' && v.trim()) return v.trim().replace(/\/$/, '');
  } catch (_) {}
  return DEFAULT_BASE_URL;
}

export function setBaseUrl(url: string) {
  uni.setStorageSync(BASE_URL_KEY, url.trim().replace(/\/$/, ''));
}

export type TriState = 'helmeted' | 'bare' | 'unknown';

/** 页面集中状态：取景 → 确认照片 → 检测中 → 结果（重拍回到取景）。 */
export type Phase = 'capture' | 'confirm' | 'detecting' | 'result';

export interface SelfCheckBox {
  label: string;
  confidence: number;
  xyxy: [number, number, number, number];
}

export interface SelfCheckResult {
  status: TriState;
  reason_code: string;
  message: string;
  model_version: string;
  inference_ms: number;
  image_width: number;
  image_height: number;
  boxes: SelfCheckBox[];
}

/** 三态固定文案：已佩戴头盔 / 未佩戴头盔 / 暂时无法判断。 */
export const STATUS_TEXT: Record<TriState, string> = {
  helmeted: '已佩戴头盔',
  bare: '未佩戴头盔',
  unknown: '暂时无法判断',
};

export interface StatusMeta {
  title: string;
  /** 官方 uni-icons 字体图标 type（本地 ttf，非 SVG/手绘） */
  iconType: string;
  tint: string;
  tintBg: string;
}

/** iOS 原生式状态表达：文字 + 官方字体图标，克制用色。未知态用中性灰（非红色）。 */
export const STATUS_META: Record<TriState, StatusMeta> = {
  helmeted: { title: '已佩戴头盔', iconType: 'checkmarkempty', tint: '#1F9D46', tintBg: '#E5F6EA' },
  bare: { title: '未佩戴头盔', iconType: 'closeempty', tint: '#D92D20', tintBg: '#FDECEA' },
  unknown: { title: '暂时无法判断', iconType: 'help', tint: '#6E6E73', tintBg: '#F2F2F7' },
};

export function boxColor(label: string): string {
  const l = String(label ?? '').toLowerCase();
  if (l === 'helmet') return '#1F9D46';
  if (l === 'no helmet' || l === 'no-helmet' || l === 'no_helmet') return '#D92D20';
  return '#8E8E93';
}

/** 后端 detail 可能是字符串，也可能是 422 校验列表。统一转成一句可读文案。 */
export function detailToText(detail: unknown): string {
  if (detail == null || detail === '') return '';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => {
      if (typeof d === 'string') return d;
      if (d && typeof d === 'object') {
        const o = d as Record<string, unknown>;
        const loc = Array.isArray(o.loc) ? (o.loc as unknown[]).slice(1).join('.') : '';
        const msg = String(o.msg ?? '');
        return loc ? `${loc}：${msg}` : msg;
      }
      try {
        return JSON.stringify(d);
      } catch (_) {
        return String(d);
      }
    }).filter(Boolean);
    return parts.join('；') || '请求参数有误，请重拍后重试';
  }
  try {
    return JSON.stringify(detail);
  } catch (_) {
    return String(detail);
  }
}

/** uni.uploadFile 的 res.data 是字符串，按 JSON 尝试解析。 */
export function parseBody(raw: unknown): any {
  if (typeof raw !== 'string') return raw;
  try {
    return JSON.parse(raw);
  } catch (_) {
    return raw;
  }
}

/** 检测错误码统一文案：400 / 413 / 429 / 503 / 422（detail 为列表）。 */
export function detectErrorText(code: number, body: unknown): string {
  const data: any = parseBody(body);
  const detail = detailToText(data?.detail ?? data);
  if (code === 400) return detail ? `请求有误：${detail}` : '请求有误，请重拍后重试';
  if (code === 413) return detail ? `图片过大：${detail}` : '图片过大，请压缩到 10MB 以内后重试';
  if (code === 429) return detail ? `推理繁忙：${detail}，请稍后重试` : '推理繁忙，请稍后重试';
  if (code === 503) return detail ? `模型未就绪：${detail}` : '模型未就绪，请稍后重试';
  if (code === 422) return detail ? `参数校验未通过：${detail}` : '参数校验未通过，请重拍后重试';
  return detail ? `检测失败（${code}）：${detail}` : `检测失败（${code}），请重试`;
}

function isFiniteNum(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/** 单个检测框校验：归一化 xyxy 且落在 [0,1]、x1<x2、y1<y2。 */
function isValidBox(b: any): b is SelfCheckBox {
  if (!b || typeof b !== 'object') return false;
  if (typeof b.label !== 'string' || !b.label.trim()) return false;
  if (!isFiniteNum(b.confidence) || b.confidence < 0 || b.confidence > 1) return false;
  const xy = (b as any).xyxy;
  if (!Array.isArray(xy) || xy.length !== 4) return false;
  if (!xy.every((v) => isFiniteNum(v) && v >= 0 && v <= 1)) return false;
  const [x1, y1, x2, y2] = xy as number[];
  return x1 < x2 && y1 < y2;
}

/**
 * 成功响应校验 + 清洗：顶层字段缺失或类型非法判整包无效；
 * 单个框非法只过滤该框（保留有效框），有效框按置信度降序。
 * 返回 null 表示整包无效，调用方回到确认态保留预览供重试。
 */
export function sanitizeSelfCheckResult(data: any): SelfCheckResult | null {
  if (!data || typeof data !== 'object') return null;
  const { status, reason_code, message, model_version, inference_ms, image_width, image_height, boxes } = data as Record<string, any>;
  if (status !== 'helmeted' && status !== 'bare' && status !== 'unknown') return null;
  if (typeof reason_code !== 'string' || typeof message !== 'string' || !message.trim()) return null;
  if (typeof model_version !== 'string' || !model_version.trim()) return null;
  if (!isFiniteNum(inference_ms) || inference_ms < 0) return null;
  if (!isFiniteNum(image_width) || image_width <= 0) return null;
  if (!isFiniteNum(image_height) || image_height <= 0) return null;
  if (!Array.isArray(boxes)) return null;
  const clean: SelfCheckBox[] = boxes.filter(isValidBox).map((b) => ({
    label: String(b.label),
    confidence: Number(b.confidence),
    xyxy: [Number(b.xyxy[0]), Number(b.xyxy[1]), Number(b.xyxy[2]), Number(b.xyxy[3])] as [number, number, number, number],
  }));
  clean.sort((a, b) => b.confidence - a.confidence);
  return {
    status, reason_code, message, model_version,
    inference_ms: Number(inference_ms),
    image_width: Number(image_width), image_height: Number(image_height),
    boxes: clean,
  };
}

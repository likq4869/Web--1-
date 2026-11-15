<template>
  <scroll-view class="screen" scroll-y>
    <view class="content">
      <!-- 大标题 -->
      <view class="large-title-block">
        <text class="large-title">头盔自查</text>
        <text class="subtitle">停车后拍摄一位骑行者，让头部与车辆同时入镜。</text>
      </view>

      <!-- 步骤指示：取景 → 确认 → 检测 → 结果 -->
      <view class="steps">
        <text class="step" :class="{ active: phase === 'capture' }">取景</text>
        <text class="step-sep">›</text>
        <text class="step" :class="{ active: phase === 'confirm' }">确认照片</text>
        <text class="step-sep">›</text>
        <text class="step" :class="{ active: isDetecting }">检测</text>
        <text class="step-sep">›</text>
        <text class="step" :class="{ active: phase === 'result' }">结果</text>
      </view>

      <!-- 取景 -->
      <view class="capture-panel" v-if="phase === 'capture'">
        <view class="camera-wrap" v-if="!cameraDenied">
          <!-- #ifdef MP-WEIXIN -->
          <camera :key="cameraKey" class="camera" device-position="back" flash="off" @error="onCameraError" @initdone="onCameraReady" />
          <!-- #endif -->
          <!-- #ifndef MP-WEIXIN -->
          <view class="camera-fallback"><text>H5 不支持取景器，请用“从相册选取”联调。</text></view>
          <!-- #endif -->
          <cover-view class="framing-guide">
            <cover-view class="guide-corner top-left" />
            <cover-view class="guide-corner top-right" />
            <cover-view class="guide-corner bottom-left" />
            <cover-view class="guide-corner bottom-right" />
          </cover-view>
          <cover-view class="compose-hint">保持 1–2 米 · 头部清晰 · 避免逆光</cover-view>
        </view>
        <view class="denied" v-if="cameraDenied">
          <text class="denied-title">无法访问相机</text>
          <text class="denied-text">请在系统设置中允许摄像头权限后返回，或先用“从相册选取”联调。</text>
          <view class="secondary-row">
            <button class="quiet-btn half" @click="retryCamera">重试相机</button>
            <button class="quiet-btn half" :disabled="choosing" @click="chooseTestImage">从相册选取</button>
          </view>
        </view>
        <text class="err" v-if="errorMsg">{{ errorMsg }}</text>
        <view class="camera-controls" v-if="!cameraDenied">
          <button class="album-btn control-side" :disabled="taking || choosing" hover-class="quiet-pressed" @click="chooseTestImage">
            <view class="album-icon" />
            <text>{{ choosing ? '选取中…' : '相册' }}</text>
          </button>
          <view class="shutter-action">
          <!-- #ifdef MP-WEIXIN -->
            <button class="shutter-btn" :disabled="taking || choosing" aria-label="拍照" hover-class="shutter-pressed" @click="takePhoto">
              <view class="shutter-core" />
            </button>
            <text class="shutter-label">{{ taking ? '拍摄中…' : '拍照' }}</text>
          <!-- #endif -->
          <!-- #ifndef MP-WEIXIN -->
            <button class="primary-btn" :disabled="choosing" @click="chooseTestImage">选择照片</button>
          <!-- #endif -->
          </view>
          <view class="control-side" />
        </view>
        <text class="privacy-note">照片仅用于本次自查</text>
      </view>

      <!-- 确认照片 -->
      <view class="card" v-if="phase === 'confirm'">
        <text class="card-title">确认照片</text>
        <text class="body-text">确认头部清晰、无遮挡后再开始检测。</text>
        <view class="preview-wrap" :style="previewBoxStyle">
          <image class="preview" :src="previewPath" mode="aspectFit" @load="(e: any) => onPreviewLoad(e, previewPath)" />
        </view>
        <text class="err" v-if="errorMsg">{{ errorMsg }}</text>
        <view class="action-col">
          <button class="primary-btn" @click="startDetect">开始检测</button>
          <view class="secondary-row">
            <button class="quiet-btn half" :disabled="choosing" @click="chooseTestImage">换一张</button>
            <button class="quiet-btn half" @click="retake">重拍</button>
          </view>
        </view>
      </view>

      <!-- 检测中：保留预览，防止重复提交 -->
      <view class="card" v-if="isDetecting">
        <text class="card-title">检测中</text>
        <view class="preview-wrap dim" :style="previewBoxStyle">
          <image class="preview" :src="previewPath" mode="aspectFit" />
        </view>
        <view class="detecting-row">
          <text class="spinner" />
          <text class="detecting-text">正在检测，请稍候…</text>
        </view>
        <text class="tip">上传中请勿重复提交，超时后保留预览可重试。</text>
        <view class="action-col">
          <button class="primary-btn" disabled>检测中…</button>
        </view>
      </view>

      <!-- 结果 -->
      <view v-if="phase === 'result' && result">
        <view class="card status-card" :style="{ backgroundColor: statusMeta.tintBg }">
          <view class="status-row">
            <view class="status-icon" :style="{ backgroundColor: statusMeta.tint }">
              <text class="status-glyph">{{ statusMeta.icon }}</text>
            </view>
            <view class="status-texts">
              <text class="status-title" :style="{ color: statusMeta.tint }">{{ statusMeta.title }}</text>
              <text class="status-msg">{{ result.message }}</text>
            </view>
          </view>
        </view>

        <view class="card">
          <text class="card-title">结果照片</text>
          <view class="preview-wrap" :style="previewBoxStyle">
            <image class="preview" :src="previewPath" mode="aspectFit" />
            <view v-for="(b, i) in displayBoxes" :key="i" class="box" :style="boxStyle(b)">
              <text class="box-label" :style="{ backgroundColor: b.color }">{{ b.label }} {{ (b.confidence * 100).toFixed(1) }}%</text>
            </view>
          </view>
          <view class="action-col">
            <button class="primary-btn" @click="retake">重拍</button>
            <button class="quiet-btn" @click="showEvidence = !showEvidence">{{ showEvidence ? '收起识别依据' : '查看识别依据' }}</button>
          </view>
        </view>

        <view class="card" v-if="showEvidence">
          <text class="card-title">识别依据</text>
          <text class="body-text">以下为本次真实检测框，按置信度从高到低排列。</text>
          <view class="meta-list">
            <view class="meta-row"><text class="meta-k">模型版本</text><text class="meta-v mono">{{ result.model_version }}</text></view>
            <view class="meta-row"><text class="meta-k">推理耗时</text><text class="meta-v">{{ result.inference_ms }} ms（不含拍照上传）</text></view>
            <view class="meta-row last"><text class="meta-k">图像与目标</text><text class="meta-v">{{ result.image_width }}×{{ result.image_height }} · {{ result.boxes.length }} 个</text></view>
          </view>
          <view class="ev-list" v-if="result.boxes.length">
            <view class="ev-row" v-for="(b, i) in result.boxes" :key="i" :class="{ last: i === result.boxes.length - 1 }">
              <view class="ev-dot" :style="{ backgroundColor: boxColor(b.label) }" />
              <view class="ev-main">
                <text class="ev-label">{{ b.label }}</text>
                <text class="ev-box mono">{{ '[' + b.xyxy.map((v: number) => v.toFixed(3)).join(', ') + ']' }}</text>
              </view>
              <text class="ev-conf mono">{{ (b.confidence * 100).toFixed(1) }}%</text>
            </view>
          </view>
          <view class="ev-empty" v-else><text>无有效目标：建议只拍一位骑行者，让头部进入画面。</text></view>
          <text class="tip">分数为模型置信度；结果受拍摄角度和遮挡影响。</text>
        </view>
      </view>

      <!-- 次要连接设置 -->
      <view class="settings">
        <button class="settings-toggle" @click="showSettings = !showSettings">
          <text>连接设置</text><text class="settings-chevron">{{ showSettings ? '⌃' : '⌄' }}</text>
        </button>
        <view v-if="showSettings" class="settings-body">
          <text class="body-text">开发联调使用 http://127.0.0.1:8000；真机请改成电脑局域网 IP。</text>
          <view class="url-row">
            <input class="url-input" v-model="baseUrl" placeholder="http://127.0.0.1:8000" />
          </view>
          <view class="secondary-row">
            <button class="quiet-btn half" @click="saveBaseUrl">保存地址</button>
            <button class="quiet-btn half" @click="checkStatus">模型预检</button>
          </view>
          <view class="preflight" v-if="modelReady !== null">
            <text :class="modelReady ? 'ok' : 'bad'">{{ modelReady ? '● 模型就绪' : '● 模型未就绪（可继续联调，检测将返回 503）' }}</text>
            <text class="mono" v-if="modelInfo">{{ modelInfo }}</text>
          </view>
        </view>
      </view>

      <view class="bottom-space" />
    </view>
  </scroll-view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { onUnload } from '@dcloudio/uni-app';
import {
  BASE_URL_KEY, DEFAULT_BASE_URL, STATUS_META,
  boxColor, detectErrorText, detailToText, getBaseUrl, parseBody,
  sanitizeSelfCheckResult, setBaseUrl,
} from '../../utils/selfcheck';
import type { Phase, SelfCheckResult, TriState } from '../../utils/selfcheck';

// —— 集中页面状态：单 phase 驱动取景 → 确认 → 检测 → 结果 ——
// 忙碌由 phase 推导，不再另存 detecting 可变状态，避免两份状态打架。
const phase = ref<Phase>('capture');
const isDetecting = computed(() => phase.value === 'detecting');
const baseUrl = ref(getBaseUrl());
const previewPath = ref('');
const previewRatio = ref(4 / 3);
const taking = ref(false);
const choosing = ref(false);
const errorMsg = ref('');
const cameraDenied = ref(false);
const cameraKey = ref(0);
const result = ref<SelfCheckResult | null>(null);
const showEvidence = ref(false);
const showSettings = ref(false);
const modelReady = ref<boolean | null>(null);
const modelInfo = ref('');

// 请求序号：换图 / 重拍 / 重新检测时递增，旧请求的回调直接丢弃，避免覆盖新照片。
let reqSeq = 0;
// 选图序号：连续两次选图/拍照时，迟到回调不得覆盖新照片。
let photoSeq = 0;
// 预检序号：地址切换或页面卸载后，旧预检回调不得覆盖新状态。
let statusSeq = 0;

// 页面卸载：所有未回来的回调全部作废。
onUnload(() => {
  reqSeq += 1;
  photoSeq += 1;
  statusSeq += 1;
});

const statusMeta = computed(() => {
  const s: TriState = result.value ? result.value.status : 'unknown';
  return STATUS_META[s];
});

const previewBoxStyle = computed(() => ({ aspectRatio: String(previewRatio.value) }));

interface DisplayBox { label: string; confidence: number; left: number; top: number; width: number; height: number; color: string }
const displayBoxes = computed<DisplayBox[]>(() => {
  if (!result.value) return [];
  return result.value.boxes.map((b) => {
    const [x1, y1, x2, y2] = b.xyxy;
    return {
      label: b.label, confidence: b.confidence, color: boxColor(b.label),
      left: x1 * 100, top: y1 * 100, width: Math.max(0, (x2 - x1) * 100), height: Math.max(0, (y2 - y1) * 100),
    };
  });
});
function boxStyle(b: DisplayBox) {
  return `left:${b.left}%;top:${b.top}%;width:${b.width}%;height:${b.height}%;border-color:${b.color};`;
}

/** 进入确认态：清理旧结果与旧错误，旧检测请求序号作废。 */
function enterConfirm(path: string) {
  reqSeq += 1;
  result.value = null;
  showEvidence.value = false;
  errorMsg.value = '';
  previewPath.value = path;
  phase.value = 'confirm';
}

function onCameraError(e: any) {
  cameraDenied.value = true;
  errorMsg.value = '相机不可用：请检查小程序摄像头权限，或点“重试相机”，也可使用“从相册选取”联调。';
  console.warn('camera error', e);
}
function onCameraReady() { cameraDenied.value = false; }

/** 相机错误后的重试入口：重建 camera 组件。 */
function retryCamera() {
  errorMsg.value = '';
  cameraDenied.value = false;
  cameraKey.value += 1;
}

/**
 * 图片 load 回调核对当前照片：迟到的 load（旧图）不得改写新照片的比例，
 * 否则检测框坐标系与当前图片不一致。确认态用图片真实尺寸；
 * 结果态比例以后端 image_width/height 为准（见 startDetect）。
 */
function onPreviewLoad(e: any, src: string) {
  if (!src || src !== previewPath.value) return;
  if (phase.value === 'result') return;
  const w = e?.detail?.width || 0, h = e?.detail?.height || 0;
  if (w > 0 && h > 0) previewRatio.value = w / h;
}

function saveBaseUrl() {
  const v = (baseUrl.value || '').trim().replace(/\/$/, '') || DEFAULT_BASE_URL;
  baseUrl.value = v;
  setBaseUrl(v);
  // 地址切换：旧预检作废，上一地址的就绪态不清留。
  statusSeq += 1;
  modelReady.value = null;
  modelInfo.value = '';
  uni.showToast({ title: '已保存', icon: 'success' });
}

function checkStatus() {
  errorMsg.value = '';
  statusSeq += 1;
  const myStatus = statusSeq;
  const url = `${baseUrl.value}/api/v1/self-check/status`;
  uni.request({
    url,
    method: 'GET',
    success: (res: any) => {
      if (myStatus !== statusSeq) return;
      if (res.statusCode === 200) {
        modelReady.value = true;
        modelInfo.value = String(res.data?.version || res.data?.reason || '');
      } else {
        modelReady.value = false;
        modelInfo.value = detailToText(res.data?.detail) || '权重未就绪';
      }
    },
    fail: (err: any) => {
      if (myStatus !== statusSeq) return;
      modelReady.value = false;
      modelInfo.value = `后端不可达：${err?.errMsg || ''}`;
    },
  });
}

function takePhoto() {
  if (taking.value || choosing.value || isDetecting.value) return;
  errorMsg.value = '';
  photoSeq += 1;
  const myPhoto = photoSeq;
  taking.value = true;
  try {
    const ctx = uni.createCameraContext();
    ctx.takePhoto({
      quality: 'high',
      success: (res: any) => {
        if (myPhoto !== photoSeq) return;
        if (res?.tempImagePath) enterConfirm(res.tempImagePath);
      },
      fail: (err: any) => {
        if (myPhoto !== photoSeq) return;
        if (/auth|deny|permission/i.test(err?.errMsg || '')) cameraDenied.value = true;
        errorMsg.value = `拍摄失败：${err?.errMsg || '请重试'}`;
      },
      complete: () => {
        if (myPhoto === photoSeq) taking.value = false;
      },
    });
  } catch (e: any) {
    if (myPhoto === photoSeq) {
      taking.value = false;
      errorMsg.value = `相机不可用：${e?.message || e}`;
    }
  }
}

function chooseTestImage() {
  if (taking.value || choosing.value || isDetecting.value) return;
  errorMsg.value = '';
  photoSeq += 1;
  const myPhoto = photoSeq;
  choosing.value = true;
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: ['album'],
    success: (res: any) => {
      if (myPhoto !== photoSeq) return;
      const p = res?.tempFilePaths?.[0];
      if (p) enterConfirm(p);
    },
    fail: (err: any) => {
      if (myPhoto !== photoSeq) return;
      // 用户取消不打扰；真正失败才提示。
      if (!/cancel/i.test(err?.errMsg || '')) errorMsg.value = `选图失败：${err?.errMsg || '请重试'}`;
    },
    complete: () => {
      if (myPhoto === photoSeq) choosing.value = false;
    },
  });
}

/** 重拍：回到取景，清理照片、结果、错误，旧请求作废。 */
function retake() {
  reqSeq += 1;
  photoSeq += 1;
  taking.value = false;
  choosing.value = false;
  previewPath.value = '';
  result.value = null;
  showEvidence.value = false;
  errorMsg.value = '';
  phase.value = 'capture';
}

function startDetect() {
  if (!previewPath.value) { errorMsg.value = '请先拍照或选取照片'; return; }
  if (isDetecting.value) return; // 检测中防止重复提交（由 phase 推导）
  if (taking.value || choosing.value) return;
  // 重新检测先清理旧结果，避免旧结果残留。
  reqSeq += 1;
  const mySeq = reqSeq;
  const photoAtReq = previewPath.value;
  result.value = null;
  showEvidence.value = false;
  errorMsg.value = '';
  phase.value = 'detecting';
  uni.uploadFile({
    url: `${baseUrl.value}/api/v1/self-check`,
    filePath: photoAtReq,
    name: 'file',
    fileName: 'selfcheck.jpg',
    timeout: 60000,
    success: (res: any) => {
      if (mySeq !== reqSeq) return; // 旧请求覆盖保护：已换图则丢弃
      const code = res.statusCode;
      const data: any = parseBody(res.data);
      if (code === 200) {
        // 成功响应校验：整包非法则判无效，保留预览回到确认态，不展示脏数据。
        const clean = sanitizeSelfCheckResult(data);
        if (!clean) {
          errorMsg.value = '识别结果异常（字段缺失或非法），已保留照片，请重新检测。';
          phase.value = 'confirm';
          return;
        }
        // 坐标一致性：结果态容器比例改用后端 image_width/height，
        // 与归一化框同一坐标系，避免横竖图下预览比例与框错位。
        if (clean.image_width > 0 && clean.image_height > 0) {
          previewRatio.value = clean.image_width / clean.image_height;
        }
        result.value = clean;
        showEvidence.value = false;
        phase.value = 'result';
      } else {
        // 400 / 413 / 429 / 503 / 422（含 detail 列表）统一文案，保留预览回到确认态供重试。
        errorMsg.value = detectErrorText(code, data);
        phase.value = 'confirm';
      }
    },
    fail: (err: any) => {
      if (mySeq !== reqSeq) return;
      const msg: string = err?.errMsg || '';
      if (/timeout/i.test(msg)) errorMsg.value = '上传超时：已保留预览，请检查网络后重试。';
      else errorMsg.value = `上传失败：${msg || '请检查后端地址后重试'}`;
      phase.value = 'confirm'; // 失败保留预览供重试
    },
  });
}

try {
  const last = uni.getStorageSync(BASE_URL_KEY);
  if (typeof last === 'string' && last) baseUrl.value = last;
} catch (_) {}
</script>

<style>
.screen { width: 100%; min-height: 100vh; background: #F7F7F9; color: #1C1C1E; font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif; }
/* 普通留白始终生效，安全区只单独增强底部，避免兼容性影响整条 padding。 */
.content { width: 100%; box-sizing: border-box; padding: 20px 20px 24px; padding-bottom: calc(24px + constant(safe-area-inset-bottom)); padding-bottom: calc(24px + env(safe-area-inset-bottom)); }
/* 大标题：32px 系统字重，统一留白 */
.large-title-block { margin: 0 0 18px; }
.large-title { display: block; font-size: 32px; font-weight: 700; line-height: 40px; letter-spacing: -0.6px; }
.subtitle { display: block; max-width: 320px; margin-top: 8px; font-size: 14px; line-height: 22px; color: #6E6E73; }
/* 步骤：安静的次要信息 */
.steps { display: flex; align-items: center; gap: 10px; margin: 0 0 18px; }
.step { font-size: 12px; line-height: 18px; color: #8E8E93; }
.step.active { color: #1C1C1E; font-weight: 600; }
.step-sep { font-size: 13px; color: #C7C7CC; }
/* 卡片：纯白实心、无 harsh 边框、轻圆角 */
.card { box-sizing: border-box; background: #fff; border-radius: 18px; padding: 18px; margin-bottom: 14px; }
.card-title { font-size: 17px; font-weight: 600; color: #000; margin-bottom: 8px; display: block; }
.body-text { font-size: 14px; color: #3A3A3C; line-height: 20px; display: block; margin-bottom: 12px; }
.tip { font-size: 12px; color: #8E8E93; margin-top: 8px; display: block; line-height: 16px; }
.err { font-size: 13px; color: #D92D20; margin-top: 8px; display: block; line-height: 18px; }
/* 取景器主导 */
.capture-panel { width: 100%; }
.camera-wrap { position: relative; width: 100%; border-radius: 22px; overflow: hidden; background: #111315; }
.camera { display: block; width: 100%; height: calc(125vw - 50px); min-height: 280px; max-height: 480px; }
.camera-fallback { box-sizing: border-box; display: flex; align-items: center; justify-content: center; min-height: 280px; padding: 40px 24px; color: #D1D1D6; font-size: 14px; text-align: center; }
.framing-guide { position: absolute; top: 12%; right: 12%; bottom: 21%; left: 12%; }
.guide-corner { position: absolute; width: 26px; height: 26px; border-style: solid; border-color: rgba(255,255,255,.8); border-width: 0; }
.top-left { top: 0; left: 0; border-top-width: 2px; border-left-width: 2px; border-top-left-radius: 10px; }
.top-right { top: 0; right: 0; border-top-width: 2px; border-right-width: 2px; border-top-right-radius: 10px; }
.bottom-left { bottom: 0; left: 0; border-bottom-width: 2px; border-left-width: 2px; border-bottom-left-radius: 10px; }
.bottom-right { bottom: 0; right: 0; border-bottom-width: 2px; border-right-width: 2px; border-bottom-right-radius: 10px; }
.compose-hint { position: absolute; right: 0; bottom: 24px; left: 0; padding: 0 8px; color: #F2F2F7; font-size: 12px; line-height: 20px; text-align: center; }
.camera-controls { display: flex; align-items: center; justify-content: space-between; margin-top: 22px; }
.control-side { width: 72px; flex-shrink: 0; }
.album-btn { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; min-height: 72px; margin: 0; padding: 8px 0; background: transparent; color: #636366; font-size: 12px; line-height: 18px; border-radius: 12px; }
.album-icon { position: relative; width: 25px; height: 22px; box-sizing: border-box; border: 1.5px solid #636366; border-radius: 5px; }
.album-icon::before { content: ''; position: absolute; top: 4px; right: 4px; width: 4px; height: 4px; border-radius: 50%; background: #636366; }
.album-icon::after { content: ''; position: absolute; bottom: 3px; left: 5px; width: 9px; height: 9px; border-top: 1.5px solid #636366; border-left: 1.5px solid #636366; transform: rotate(45deg); }
.shutter-action { display: flex; flex: 1; min-width: 0; flex-direction: column; align-items: center; gap: 8px; }
.shutter-btn { display: flex; align-items: center; justify-content: center; width: 76px; height: 76px; box-sizing: border-box; margin: 0; padding: 5px; border: 2px solid #007AFF; border-radius: 50%; background: #F7F7F9; }
.shutter-core { width: 100%; height: 100%; border-radius: 50%; background: #007AFF; }
.shutter-label { color: #1C1C1E; font-size: 13px; line-height: 18px; font-weight: 500; }
.shutter-pressed { opacity: .75; }
.quiet-pressed { background: #EBEBF0; }
.shutter-btn[disabled], .album-btn[disabled] { opacity: .45; }
.privacy-note { display: block; margin-top: 20px; text-align: center; color: #8E8E93; font-size: 12px; line-height: 18px; }
.denied { background: #FDECEA; border-radius: 12px; padding: 12px; margin-bottom: 12px; }
.denied-title { font-weight: 600; font-size: 15px; color: #D92D20; display: block; margin-bottom: 4px; }
.denied-text { font-size: 13px; color: #7A2E0E; line-height: 18px; margin-bottom: 8px; display: block; }
/* 按钮层级：一主一次，主填充分割、次安静文字 */
.action-col { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; }
.primary-btn, .quiet-btn { display: flex; align-items: center; justify-content: center; width: 100%; box-sizing: border-box; margin: 0; padding: 0 16px; }
.primary-btn { background: #007AFF; color: #fff; font-size: 17px; font-weight: 600; border-radius: 14px; min-height: 50px; line-height: 24px; }
.primary-btn[disabled] { opacity: .5; }
.quiet-btn { background: #F2F2F7; color: #007AFF; font-size: 15px; border-radius: 14px; min-height: 44px; line-height: 22px; }
.quiet-btn[disabled] { opacity: .5; }
.secondary-row { display: flex; gap: 8px; }
.quiet-btn.half { flex: 1; width: auto; min-width: 0; }
/* 预览：黑色实心底，检测框真实叠加 */
.preview-wrap { position: relative; width: 100%; background: #000; border-radius: 12px; overflow: hidden; }
.preview-wrap.dim { opacity: .85; }
.preview { width: 100%; height: 100%; display: block; }
.box { position: absolute; border: 3px solid #1F9D46; box-sizing: border-box; }
/* 标签放框内顶部，避免顶部框标签被 overflow 裁切 */
.box-label { position: absolute; top: 0; left: 0; color: #fff; font-size: 11px; padding: 2px 6px; border-radius: 0 0 6px 0; white-space: nowrap; max-width: 100%; overflow: hidden; }
/* 检测中 */
.detecting-row { display: flex; align-items: center; gap: 8px; margin-top: 12px; }
.detecting-text { font-size: 14px; color: #3A3A3C; }
.spinner { width: 18px; height: 18px; border-radius: 50%; border: 2px solid #C7C7CC; border-top-color: #007AFF; animation: hg-spin 0.9s linear infinite; }
@keyframes hg-spin { to { transform: rotate(360deg); } }
/* 状态：文字 + 有意义图标，纯色底 */
.status-card { padding: 16px; }
.status-row { display: flex; gap: 12px; align-items: flex-start; }
.status-icon { width: 40px; height: 40px; border-radius: 20px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.status-glyph { color: #fff; font-size: 20px; font-weight: 700; }
.status-texts { flex: 1; }
.status-title { font-size: 20px; font-weight: 700; display: block; }
.status-msg { font-size: 14px; color: #3A3A3C; display: block; margin-top: 4px; line-height: 20px; }
/* iOS 列表节奏：只用分隔线 */
.meta-list { margin-top: 4px; margin-bottom: 8px; }
.meta-row { display: flex; justify-content: space-between; gap: 12px; padding: 10px 0; border-bottom: 1px solid #F2F2F7; }
.meta-row.last { border-bottom: none; }
.meta-k { font-size: 13px; color: #8E8E93; flex-shrink: 0; }
.meta-v { font-size: 13px; color: #000; text-align: right; flex: 1; word-break: break-all; }
.mono { font-family: monospace; }
/* 识别依据 */
.ev-list { margin-top: 4px; }
.ev-row { display: flex; align-items: flex-start; gap: 10px; padding: 10px 0; border-bottom: 1px solid #F2F2F7; }
.ev-row.last { border-bottom: none; }
.ev-dot { width: 10px; height: 10px; border-radius: 5px; margin-top: 5px; flex-shrink: 0; }
.ev-main { flex: 1; }
.ev-label { font-size: 15px; color: #000; display: block; }
.ev-box { font-size: 11px; color: #8E8E93; display: block; margin-top: 2px; word-break: break-all; }
.ev-conf { font-size: 13px; color: #000; flex-shrink: 0; }
.ev-empty { font-size: 13px; color: #8E8E93; padding: 8px 0; }
/* 次要设置 */
.settings { margin: 8px 0 0; }
.settings-toggle { display: flex; align-items: center; justify-content: center; gap: 6px; width: 100%; min-height: 44px; background: transparent; color: #6E6E73; font-size: 12px; padding: 0; margin: 0; line-height: 20px; }
.settings-chevron { color: #8E8E93; font-size: 15px; }
.settings-toggle::after { border: none; }
.settings-body { background: #fff; border-radius: 12px; padding: 16px; }
.url-row { margin: 8px 0; }
.url-input { background: #F2F2F7; border-radius: 8px; padding: 10px 12px; font-size: 13px; min-height: 44px; }
.preflight { margin-top: 8px; font-size: 13px; }
.ok { color: #1F9D46; }
.bad { color: #D92D20; }
.bottom-space { height: 4px; }
button::after { border: none; }
</style>

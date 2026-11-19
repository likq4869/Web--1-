<template>
  <div class="hg-live">
    <PageHeader title="实时监控" description="点位健康、实时违规流与推送通道">
      <template #actions>
        <ElSelect
          :model-value="selectedPointId"
          placeholder="全部点位"
          clearable
          class="hg-live__select"
          @update:model-value="onPointChange"
        >
          <ElOption
            v-for="point in points"
            :key="point.source_id"
            :label="point.name || point.source_id"
            :value="point.source_id"
          />
        </ElSelect>
        <ElButton :loading="loading" @click="reload">刷新</ElButton>
        <RouterLink class="hg-live__config" to="/monitor/config">点位标定</RouterLink>
      </template>
    </PageHeader>

    <!-- 加载态：骨架占位 -->
    <div
      v-if="loading && !hasData"
      class="hg-live__skeleton"
      aria-busy="true"
      aria-label="加载中"
    />

    <!-- 错误态 -->
    <div v-else-if="loadError && !hasData" class="hg-live__error" role="alert">
      <p class="hg-live__error-text">{{ loadError }}</p>
      <ElButton size="small" @click="reload">重试</ElButton>
    </div>

    <template v-else>
      <!-- 点位状态栏：在线 / 今日提醒 / 今日通行 / 佩戴率 -->
      <div class="hg-live__status" aria-label="点位状态">
        <div class="hg-live__stat">
          <span class="hg-live__stat-label">在线点位</span>
          <p class="hg-live__stat-value tabular">{{ onlineText }}</p>
        </div>
        <div class="hg-live__stat">
          <span class="hg-live__stat-label">今日提醒</span>
          <p class="hg-live__stat-value tabular">{{ formatCount(todayEvents) }}</p>
        </div>
        <div class="hg-live__stat">
          <span class="hg-live__stat-label">今日通行</span>
          <p class="hg-live__stat-value tabular">{{ formatCount(todayPasses) }}</p>
        </div>
        <div class="hg-live__stat">
          <span class="hg-live__stat-label">佩戴率</span>
          <p class="hg-live__stat-value tabular">{{ wearRate }}</p>
        </div>
      </div>

      <div class="hg-live__body">
        <!-- 视频区：无真实视频源，不编造地址；按在线/离线降级展示 -->
        <section class="hg-live__stage" :aria-label="stageLabel">
          <DetectionOverlay :boxes="overlayBoxes" />
          <div v-if="!stageOnline" class="hg-live__offline">
            <p class="hg-live__offline-title">{{ stageTitle }}</p>
            <p class="hg-live__offline-desc">{{ stageDesc }}</p>
          </div>
          <div v-else class="hg-live__offline">
            <p class="hg-live__offline-title">{{ stageTitle }}</p>
            <p class="hg-live__offline-desc">
              {{ stageDesc }}
              <span v-if="lastEventText" class="tabular">{{ lastEventText }}</span>
            </p>
          </div>
        </section>

        <!-- 实时违规流：顶部插入、单次淡入、上限 50、不自动滚动 -->
        <section class="hg-live__feed" aria-label="实时违规流">
          <header class="hg-live__feed-head">
            <h2 class="hg-live__feed-title">实时违规流</h2>
            <span class="hg-live__conn" :class="`is-${connTone}`">{{ connLabel }}</span>
          </header>
          <ul v-if="feed.length" class="hg-live__list">
            <li
              v-for="item in feed"
              :key="item.event_id"
              class="hg-live__item"
              :class="{ 'is-flash': flashId === item.event_id }"
            >
              <p class="hg-live__item-title">{{ feedItemTitle(item) }}</p>
              <p class="hg-live__item-meta tabular">
                {{ formatFeedDateTime(item.occurred_at) }} ·
                {{ feedLevelLabel(item.decision_level) }}
              </p>
            </li>
          </ul>
          <EmptyState
            v-else
            title="暂无实时提醒"
            description="当前时段还没有新的骑行提醒，稍后会自动推送。"
          />
        </section>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElButton, ElOption, ElSelect } from 'element-plus'
import DetectionOverlay from '@/components/DetectionOverlay.vue'
import EmptyState from '@/components/EmptyState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { useWebSocket } from '@/composables/useWebSocket'
import {
  buildLiveUrl,
  getMonitorFeed,
  getMonitorPoint,
  listMonitorPoints,
  type MonitorFeedItem,
  type MonitorPoint,
} from '@/api/monitor'
import { getAccessToken } from '@/api/request'
import { ApiError } from '@/api/types'
import { useDecisionsStore } from '@/stores/decisions'
import type { DecisionListItem } from '@/api/decisions'
import {
  feedItemTitle,
  feedLevelLabel,
  formatCount,
  formatFeedDateTime,
  stringField,
  wearRateOf,
  type LiveEnvelope,
} from './liveFormat'

/** 违规流上限：与后端 FEED_LIMIT_MAX 对齐 */
const FEED_MAX = 50

const points = ref<MonitorPoint[]>([])
const feed = ref<MonitorFeedItem[]>([])
const selectedPointId = ref<string | null>(null)
const loading = ref(false)
const loadError = ref<string | null>(null)
const lastEventAt = ref<string | null>(null)
const flashId = ref<string | null>(null)

const decisionsStore = useDecisionsStore()
let fetchSeq = 0
let flashTimer: ReturnType<typeof setTimeout> | null = null

const hasData = computed(() => points.value.length > 0 || feed.value.length > 0)
const visiblePoints = computed(() =>
  selectedPointId.value
    ? points.value.filter((p) => p.source_id === selectedPointId.value)
    : points.value,
)
const onlineCount = computed(() => visiblePoints.value.filter((p) => p.status === 'online').length)
const onlineText = computed(() => `${onlineCount.value}/${visiblePoints.value.length}`)
const todayEvents = computed(() =>
  visiblePoints.value.reduce((sum, p) => sum + (p.today_events ?? 0), 0),
)
const todayPasses = computed(() =>
  visiblePoints.value.reduce((sum, p) => sum + (p.today_passes ?? 0), 0),
)
const wearRate = computed(() => wearRateOf(visiblePoints.value))

const selectedPoint = computed(
  () => points.value.find((p) => p.source_id === selectedPointId.value) ?? null,
)
const stageOnline = computed(() =>
  selectedPoint.value ? selectedPoint.value.status === 'online' : points.value.length > 0,
)
const stageLabel = computed(() =>
  selectedPoint.value ? `点位 ${selectedPoint.value.name}` : '全部点位',
)
const stageTitle = computed(() => {
  if (!points.value.length) return '暂无点位'
  if (selectedPoint.value)
    return selectedPoint.value.status === 'online' ? selectedPoint.value.name : '设备离线'
  return onlineCount.value > 0 ? '点位运行中' : '设备离线'
})
const stageDesc = computed(() => {
  if (!points.value.length) return '尚未接入采集设备。'
  if (selectedPoint.value && selectedPoint.value.status !== 'online')
    return '该点位心跳超时，仅展示历史违规流。'
  return '暂无实时视频源，仅展示检测叠加与违规流。'
})
const lastEventText = computed(() => (lastEventAt.value ? `最近事件 ${lastEventAt.value}` : ''))
const overlayBoxes = computed(() => [])

/** WS 连接状态展示（不暴露技术细节给值班人口径） */
const ws = useWebSocket<LiveEnvelope>({
  url: () => {
    const token = getAccessToken()
    return token ? buildLiveUrl(token) : null
  },
  onMessage: handleLiveMessage,
})

const connTone = computed(() => {
  if (ws.status.value === 'open') return 'open'
  if (ws.status.value === 'error') return 'error'
  return 'idle'
})
const connLabel = computed(() => {
  if (ws.status.value === 'open') return '推送已连接'
  if (ws.status.value === 'connecting') return '推送连接中'
  if (ws.status.value === 'error') return ws.lastError.value ?? '推送异常，重连中'
  return '推送未连接'
})

function pushFeed(item: MonitorFeedItem): void {
  if (feed.value.some((row) => row.event_id === item.event_id)) return
  feed.value = [item, ...feed.value].slice(0, FEED_MAX)
  flashId.value = item.event_id
  if (flashTimer !== null) clearTimeout(flashTimer)
  flashTimer = setTimeout(() => {
    flashId.value = null
  }, 1200)
}

function handleLiveMessage(message: LiveEnvelope): void {
  if (!message || typeof message.type !== 'string') return
  const data = (message.data ?? {}) as Record<string, unknown>
  if (message.type === 'violation_detected') {
    const eventId = stringField(data, 'event_id')
    if (!eventId) return
    pushFeed({
      event_id: eventId,
      source_id: stringField(data, 'point_id') || message.point_id || '',
      point_name: stringField(data, 'point_name') || stringField(data, 'point_id'),
      occurred_at: stringField(data, 'occurred_at'),
      status: stringField(data, 'status') || 'pending',
      model_label: stringField(data, 'model_label') || stringField(data, 'status'),
      decision_level: null,
      decision_status: null,
    })
    return
  }
  if (message.type === 'decision_created') {
    const eventId = stringField(data, 'event_id')
    const decisionId = stringField(data, 'decision_id')
    const level = stringField(data, 'level')
    if (eventId) {
      pushFeed({
        event_id: eventId,
        source_id: stringField(data, 'point_id') || message.point_id || '',
        point_name: stringField(data, 'point_name') || stringField(data, 'point_id'),
        occurred_at: stringField(data, 'created_at') || stringField(data, 'occurred_at'),
        status: stringField(data, 'status') || 'pending',
        model_label: stringField(data, 'model_label'),
        decision_level: level || null,
        decision_status: stringField(data, 'decision_status') || null,
      })
    }
    if (decisionId && eventId && level) {
      const incoming: DecisionListItem = {
        decision_id: decisionId,
        event_id: eventId,
        student_id: null,
        level: level as DecisionListItem['level'],
        action: stringField(data, 'action'),
        score_delta: 0,
        reason_code: stringField(data, 'reason_code'),
        confidence: null,
        status: 'PENDING_REVIEW',
        auto_approved: false,
        created_at: stringField(data, 'created_at') || null,
        due_at: null,
      }
      decisionsStore.insertIncoming(incoming)
    }
    return
  }
  if (
    message.type === 'device_status' ||
    message.type === 'stats_update' ||
    message.type === 'point_alert'
  ) {
    void refreshPointsSilent()
  }
}

async function refreshPointsSilent(): Promise<void> {
  try {
    const result = await listMonitorPoints()
    points.value = result.items
  } catch {
    // 静默刷新失败不打断页面（下次心跳/手动刷新可恢复）
  }
}

async function fetchData(): Promise<void> {
  const seq = (fetchSeq += 1)
  loading.value = true
  loadError.value = null
  try {
    const [pointResult, feedResult] = await Promise.all([
      listMonitorPoints(),
      getMonitorFeed({ point_id: selectedPointId.value ?? undefined, limit: FEED_MAX }),
    ])
    if (seq !== fetchSeq) return
    points.value = pointResult.items
    feed.value = feedResult.items.slice(0, FEED_MAX)
    if (selectedPointId.value && !points.value.some((p) => p.source_id === selectedPointId.value)) {
      selectedPointId.value = null
    }
    const active = selectedPointId.value ?? points.value[0]?.source_id
    if (active) {
      try {
        const snapshot = await getMonitorPoint(active)
        if (seq !== fetchSeq) return
        lastEventAt.value = snapshot.last_event?.occurred_at ?? null
      } catch {
        lastEventAt.value = null
      }
    } else {
      lastEventAt.value = null
    }
  } catch (error) {
    if (seq !== fetchSeq) return
    points.value = []
    feed.value = []
    loadError.value = error instanceof ApiError ? error.message : '实时监控加载失败'
  } finally {
    if (seq === fetchSeq) loading.value = false
  }
}

function reload(): void {
  void fetchData()
}

function onPointChange(value: string | null): void {
  selectedPointId.value = value ?? null
  lastEventAt.value = null
  void fetchData()
}

onMounted(() => {
  void fetchData()
})
</script>

<style scoped lang="scss" src="./_styles/live.scss"></style>

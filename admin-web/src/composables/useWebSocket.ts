// ===========================================================================
// WebSocket 可复用组合式函数 —— 指数退避重连 + 心跳保活 + 可见性感知
// 纯前端连接管理，无业务判定；消息解析由调用方经 onMessage 完成。
// ===========================================================================

import { onBeforeUnmount, ref, watch } from 'vue'

/** 连接状态（页面据此渲染三态，不依赖文案猜测） */
export type WsStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error'

/** 重连退避：首 1s 起，每次翻倍，上限 30s */
export const WS_RECONNECT_BASE_MS = 1000
export const WS_RECONNECT_MAX_MS = 30000

/** 心跳间隔：30s 发一次 ping（后端回 pong 保活） */
export const WS_PING_INTERVAL_MS = 30000

export interface UseWebSocketOptions<T = unknown> {
  /** 建连地址；返回空时不建连（等 token / 点位就绪） */
  url: () => string | null
  /** 收到 JSON 消息后的回调 */
  onMessage?: (message: T) => void
  /** 是否立即建连 */
  autoConnect?: boolean
  /** 心跳内容，默认 "ping"（与后端约定） */
  pingPayload?: string
}

export interface UseWebSocketReturn {
  status: ReturnType<typeof ref<WsStatus>>
  lastError: ReturnType<typeof ref<string | null>>
  reconnectCount: ReturnType<typeof ref<number>>
  connect: () => void
  disconnect: () => void
  send: (payload: string) => void
}

/**
 * 通用 WS 连接：指数退避重连 + 30s ping + 切后台暂停心跳、回前台即时补 ping。
 * 卸载时自动清理定时器与连接，避免泄漏。
 */
export function useWebSocket<T = unknown>(options: UseWebSocketOptions<T>): UseWebSocketReturn {
  const status = ref<WsStatus>('idle')
  const lastError = ref<string | null>(null)
  const reconnectCount = ref(0)

  let socket: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let pingTimer: ReturnType<typeof setInterval> | null = null
  let disposed = false
  let manualClosed = false

  const pingPayload = options.pingPayload ?? 'ping'

  function clearTimers(): void {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (pingTimer !== null) {
      clearInterval(pingTimer)
      pingTimer = null
    }
  }

  function scheduleReconnect(): void {
    if (disposed || manualClosed) return
    const delay = Math.min(
      WS_RECONNECT_BASE_MS * 2 ** Math.min(reconnectCount.value, 5),
      WS_RECONNECT_MAX_MS,
    )
    reconnectCount.value += 1
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      openSocket()
    }, delay)
  }

  function startHeartbeat(): void {
    stopHeartbeat()
    pingTimer = setInterval(() => {
      if (document.visibilityState !== 'visible') return
      if (socket?.readyState === WebSocket.OPEN) {
        try {
          socket.send(pingPayload)
        } catch {
          // 发送失败走 onclose 重连，不在此抛错
        }
      }
    }, WS_PING_INTERVAL_MS)
  }

  function stopHeartbeat(): void {
    if (pingTimer !== null) {
      clearInterval(pingTimer)
      pingTimer = null
    }
  }

  function openSocket(): void {
    if (disposed) return
    const target = options.url()
    if (!target) {
      status.value = 'idle'
      return
    }
    manualClosed = false
    clearTimers()
    status.value = 'connecting'
    lastError.value = null
    try {
      socket = new WebSocket(target)
    } catch (error) {
      status.value = 'error'
      lastError.value = error instanceof Error ? error.message : '连接创建失败'
      scheduleReconnect()
      return
    }

    socket.onopen = () => {
      if (disposed) return
      status.value = 'open'
      reconnectCount.value = 0
      startHeartbeat()
    }

    socket.onmessage = (event: MessageEvent) => {
      if (event.data === 'pong') return
      if (typeof event.data !== 'string') return
      try {
        const parsed = JSON.parse(event.data) as T
        options.onMessage?.(parsed)
      } catch {
        // 非 JSON 心跳回显直接忽略，不污染错误态
      }
    }

    socket.onerror = () => {
      if (disposed) return
      status.value = 'error'
      lastError.value = '实时通道异常，正在重连'
    }

    socket.onclose = () => {
      stopHeartbeat()
      socket = null
      if (disposed || manualClosed) {
        if (!disposed) status.value = 'closed'
        return
      }
      status.value = 'closed'
      scheduleReconnect()
    }
  }

  function connect(): void {
    manualClosed = false
    openSocket()
  }

  function disconnect(): void {
    manualClosed = true
    clearTimers()
    if (socket) {
      try {
        socket.close()
      } catch {
        // 关闭失败无需处理，已清理定时器
      }
      socket = null
    }
    if (!disposed) status.value = 'closed'
  }

  function send(payload: string): void {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(payload)
    }
  }

  function onVisibility(): void {
    if (document.visibilityState === 'visible' && status.value === 'open') {
      send(pingPayload)
    }
  }

  document.addEventListener('visibilitychange', onVisibility)
  watch(
    () => options.url(),
    () => {
      if (!disposed && !manualClosed) openSocket()
    },
  )

  if (options.autoConnect !== false) openSocket()

  onBeforeUnmount(() => {
    disposed = true
    document.removeEventListener('visibilitychange', onVisibility)
    clearTimers()
    if (socket) {
      try {
        socket.close()
      } catch {
        // 卸载时关闭失败可忽略
      }
      socket = null
    }
  })

  return { status, lastError, reconnectCount, connect, disconnect, send }
}

// M3 播放器、队列和场次接口；状态由 /ws/player 统一推送。
import type { PlayerCommand, PlayerUpdate } from '@/Common/Types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...(init?.headers ?? {}) },
    signal: AbortSignal.timeout(30000),
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok) throw new Error(payload?.detail?.message ?? '播放器请求失败，请检查后端连接')
  return payload as T
}

const body = (value: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(value) })

export const fetchPlayerState = () => request<PlayerUpdate>('/api/player/state')
export const sendPlayerCommand = (command: PlayerCommand) => request<PlayerUpdate>('/api/player/command', body(command))
export const setAutoNext = (auto_next: boolean) => request<PlayerUpdate>('/api/player/settings', { method: 'PATCH', body: JSON.stringify({ auto_next }) })
export const enqueuePlayer = (song_id: number, position: 'end' | 'next') => request<PlayerUpdate>('/api/queue', body({ song_id, position }))
export const removeQueueItem = (item_id: string) => request<PlayerUpdate>(`/api/queue/${item_id}`, { method: 'DELETE' })
export const orderQueue = (item_ids: string[]) => request<PlayerUpdate>('/api/queue/order', { method: 'PUT', body: JSON.stringify({ item_ids }) })
export const clearQueue = () => request<PlayerUpdate>('/api/queue', { method: 'DELETE' })
export const startSession = () => request<PlayerUpdate>('/api/sessions', body({}))
export const endSession = () => request<PlayerUpdate>('/api/sessions/current/end', body({}))

/** 单条状态连接，掉线后重连；服务端空闲时每 15 秒发 ping，25 秒收不到任何消息就主动重连。 */
export function subscribePlayer(onUpdate: (update: PlayerUpdate) => void, onConnection: (open: boolean) => void): () => void {
  let socket: WebSocket | undefined
  let retry = 0
  let watchdog = 0
  let stopped = false

  function armWatchdog(timeout = 25000) {
    clearTimeout(watchdog)
    watchdog = window.setTimeout(() => socket?.close(), timeout)
  }

  function open() {
    if (stopped) return
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    socket = new WebSocket(`${protocol}//${location.host}/ws/player`)
    armWatchdog(10000)
    socket.onopen = () => { onConnection(true); armWatchdog() }
    socket.onmessage = (event) => {
      armWatchdog()
      try {
        const message = JSON.parse(event.data)
        if (message.type === 'player_state') onUpdate(message as PlayerUpdate)
      } catch {
        socket?.close()
      }
    }
    socket.onerror = () => socket?.close()
    socket.onclose = () => {
      clearTimeout(watchdog)
      onConnection(false)
      if (!stopped) retry = window.setTimeout(open, 1500)
    }
  }

  open()
  return () => {
    stopped = true
    clearTimeout(retry)
    clearTimeout(watchdog)
    socket?.close()
  }
}

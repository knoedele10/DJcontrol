// PPT 独立接入真实后端，歌曲模块仍可使用原有模拟数据。
import type { PptApp, PptCommand, PptUpdate } from '@/Common/Types'

async function request(path: string, body?: unknown, method?: string): Promise<PptUpdate> {
  const response = await fetch(`/api/ppt/${path}`, {
    method: method ?? (body === undefined ? 'GET' : 'POST'),
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(10000),
  })
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new Error(data?.detail?.message ?? 'PPT 请求失败，请检查后端连接')
  return data as PptUpdate
}

export const connectPpt = (app: PptApp) => request('connect', { app })
export const sendPptCommand = (command: PptCommand) => request('command', command)
export const fetchPptState = () => request('state')
export const setPptBinding = (slide: number, songId: number | null) => request(`bindings/${slide}`, { song_id: songId }, 'PUT')
export const setPptLinkMusic = (enabled: boolean) => request('settings', { link_music: enabled }, 'PATCH')
export const importPptBindings = (bindings: Record<string, Record<string, number | null>>) =>
  request('bindings/import', { bindings })

/** 单条状态连接，掉线后重连；不自动重试任何控制命令。 */
export function subscribePpt(
  onUpdate: (update: PptUpdate) => void,
  onConnection: (connected: boolean) => void,
): () => void {
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
    socket = new WebSocket(`${protocol}//${location.host}/ws/ppt`)
    armWatchdog(10000)
    socket.onopen = () => { onConnection(true); armWatchdog() }
    socket.onmessage = (event) => {
      armWatchdog()
      try {
        const message = JSON.parse(event.data)
        if (message.type === 'ppt_state') onUpdate(message as PptUpdate)
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

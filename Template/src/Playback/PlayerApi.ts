// M3 播放器、队列和场次接口；状态由 /ws/player 统一推送。
import type { PlayerCommand, PlayerUpdate, PlaylistState, PlaylistAddResult } from '@/Common/Types'
import { subscribeSocket } from '@/Common/Socket'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...(init?.headers ?? {}) },
    signal: AbortSignal.timeout(60000),
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok) throw new Error(payload?.detail?.message
    ?? (Array.isArray(payload?.detail) ? payload.detail[0]?.msg : undefined)
    ?? '播放器请求失败，请检查后端连接')
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

export const fetchPlaylist = () => request<PlaylistState>('/api/playlist')
export const refreshPlaylist = () => request<PlaylistState>('/api/playlist/refresh', body({}))
export const addPlaylistTrack = (song_id: number) => request<PlaylistAddResult>('/api/playlist/tracks', body({ song_id }))

export const subscribePlayer = (onUpdate: (update: PlayerUpdate) => void, onConnection: (open: boolean) => void) =>
  subscribeSocket<PlayerUpdate>('/ws/player', 'player_state', onUpdate, onConnection)

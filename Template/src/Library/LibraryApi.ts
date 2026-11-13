// M2 曲库和分组接口；组件只通过 stores/library.ts 调用这些函数。
import type { Category, EventGroup, SearchResponse, Song } from '@/Common/Types'
import { subscribeSocket } from '@/Common/Socket'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...(init?.headers ?? {}) },
    signal: AbortSignal.timeout(10000),
  })
  if (response.status === 204) return undefined as T
  const payload = await response.json().catch(() => null)
  if (!response.ok) throw new Error(payload?.detail?.message ?? '曲库请求失败，请检查后端连接')
  return payload as T
}

const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })

export const fetchSongs = () => request<Song[]>('/api/songs')
export const fetchGroups = () => request<EventGroup[]>('/api/groups')
export const fetchLibrarySearch = (query: string, source: 'library' | 'kugou', limit = 30) =>
  request<SearchResponse>(`/api/search?q=${encodeURIComponent(query)}&limit=${limit}&source=${source}`)

export const importKugouSong = (key: string) => request<Song>('/api/songs/from-kugou', json({ key }))

export const createGroup = (body: { name: string; color?: string }) => request<EventGroup>('/api/groups', json(body))
export const updateGroup = (id: string, body: Partial<Pick<EventGroup, 'name' | 'color'>>) =>
  request<EventGroup>(`/api/groups/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
export const deleteGroup = (id: string) => request<void>(`/api/groups/${id}`, { method: 'DELETE' })
export const reorderGroups = (group_ids: string[]) => request<void>('/api/groups/order', { method: 'PUT', body: JSON.stringify({ group_ids }) })

export const createCategory = (groupId: string, body: { name: string; color?: string; song_ids?: number[] }) =>
  request<Category>(`/api/groups/${groupId}/categories`, json(body))
export const updateCategory = (id: string, body: Partial<Pick<Category, 'name' | 'color'>>) =>
  request<Category>(`/api/categories/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
export const deleteCategory = (id: string) => request<void>(`/api/categories/${id}`, { method: 'DELETE' })
export const reorderCategories = (groupId: string, category_ids: string[]) =>
  request<void>(`/api/groups/${groupId}/categories/order`, { method: 'PUT', body: JSON.stringify({ category_ids }) })
export const addCategorySong = (categoryId: string, songId: number) =>
  request<Category>(`/api/categories/${categoryId}/songs`, json({ song_id: songId }))
export const removeCategorySong = (categoryId: string, songId: number) =>
  request<Category>(`/api/categories/${categoryId}/songs/${songId}`, { method: 'DELETE' })
export const replaceCategorySongs = (categoryId: string, song_ids: number[]) =>
  request<Category>(`/api/categories/${categoryId}/songs`, { method: 'PUT', body: JSON.stringify({ song_ids }) })

export const subscribeLibrary = (onChanged: (revision: number, scope: string) => void, onConnection: (open: boolean) => void) =>
  subscribeSocket<{ revision: number; scope: string }>(
    '/ws/library', 'library_changed', (message) => onChanged(Number(message.revision), String(message.scope)), onConnection, false,
  )

// 后端接口封装。后端未完成前，这里返回模拟数据；接入后只改这个文件。
import type { Capability, Diagnostics, KugouResult } from '@/Common/Types'
import { mockKugouCatalog } from '@/Common/MockData'


export const USE_MOCK = true

export function tokenize(query: string): string[] {
  return query.toLowerCase().split(/\s+/).filter(Boolean)
}

export function matchesTokens(text: string, tokens: string[]): boolean {
  const hay = text.toLowerCase()
  return tokens.every((t) => hay.includes(t))
}

/** 在酷狗里搜索歌曲（后端：GET /api/search?q=） */
export async function searchKugou(query: string): Promise<KugouResult[]> {
  const tokens = tokenize(query)
  if (!tokens.length) return []
  await new Promise((r) => setTimeout(r, 120))
  return mockKugouCatalog.filter((s) => matchesTokens(`${s.title} ${s.artist}`, tokens))
}

/** 诊断由后端返回，不在浏览器假设支持能力。 */
async function diagnosticsRequest(init?: RequestInit): Promise<Diagnostics> {
  const response = await fetch('/api/' + (init?.method === 'PUT' ? 'settings/controller' : 'diagnostics'), {
    ...init, headers: { 'Content-Type': 'application/json' }, signal: AbortSignal.timeout(20000),
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data?.detail?.message ?? '连接诊断失败')
  return data as Diagnostics
}
export const fetchDiagnostics = () => diagnosticsRequest()
export const selectController = (name: 'mock' | 'kugou') => diagnosticsRequest({ method: 'PUT', body: JSON.stringify({ name }) })
export const fetchCapabilities = async (): Promise<Capability[]> => (await fetchDiagnostics()).capabilities

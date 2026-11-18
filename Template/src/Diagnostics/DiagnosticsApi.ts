// 诊断接口封装；设置页只展示后端实时自检结果。
import type { BackendConnectionState, Diagnostics } from '@/Common/Types'

/** 诊断由后端返回，不在浏览器假设支持能力。 */
async function diagnosticsRequest(init?: RequestInit): Promise<Diagnostics> {
  const response = await fetch('/api/' + (init?.method === 'PUT' ? 'settings/controller' : 'diagnostics'), {
    ...init, headers: { 'Content-Type': 'application/json' }, signal: AbortSignal.timeout(60000),
  })
  const data = await response.json()
  if (!response.ok) {
    const message = data?.detail?.message
      ?? (Array.isArray(data?.detail) ? data.detail[0]?.msg : undefined)
      ?? '连接诊断失败'
    throw new Error(message)
  }
  return data as Diagnostics
}
export const fetchDiagnostics = () => diagnosticsRequest()
export const selectController = (name: 'mock' | 'kugou', playlist?: string) => diagnosticsRequest({ method: 'PUT', body: JSON.stringify({ name, ...(playlist === undefined ? {} : { playlist }) }) })

export async function fetchBackendConnection(): Promise<BackendConnectionState> {
  const response = await fetch('/api/connection', { signal: AbortSignal.timeout(5000) })
  const result = await response.json().catch(() => null)
  if (!response.ok || typeof result?.backend_connected !== 'boolean') throw new Error('无法检查控制服务连接，请确认网页与 Windows 后端已更新并启动')
  return result as BackendConnectionState
}

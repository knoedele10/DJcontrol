// 诊断接口封装；设置页只展示后端实时自检结果。
import type { Diagnostics } from '@/Common/Types'

/** 诊断由后端返回，不在浏览器假设支持能力。 */
async function diagnosticsRequest(init?: RequestInit): Promise<Diagnostics> {
  const response = await fetch('/api/' + (init?.method === 'PUT' ? 'settings/controller' : 'diagnostics'), {
    ...init, headers: { 'Content-Type': 'application/json' }, signal: AbortSignal.timeout(20000),
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
export const selectController = (name: 'mock' | 'kugou') => diagnosticsRequest({ method: 'PUT', body: JSON.stringify({ name }) })

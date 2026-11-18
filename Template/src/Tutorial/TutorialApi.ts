// 教程进度接口：看完的教程版本存在后端设置里，桌面版换端口、换浏览器打开都记得。

async function request(init?: RequestInit): Promise<number> {
  const response = await fetch('/api/settings/tutorial', {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    signal: AbortSignal.timeout(5000),
  })
  const payload = await response.json().catch(() => null)
  const version = payload?.completed_version
  if (!response.ok || !Number.isInteger(version) || version < 0) throw new Error('教程进度读写失败')
  return version
}

export const fetchTutorialVersion = () => request()
export const saveTutorialVersion = (version: number) =>
  request({ method: 'PUT', body: JSON.stringify({ completed_version: version }) })

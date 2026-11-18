import assert from 'node:assert/strict'
import { after, before, beforeEach, test } from 'node:test'
import { createServer } from 'vite'
import { createPinia, setActivePinia } from 'pinia'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'

let vite, useConnectionStore, usePlaybackStore, ConnectionBanner, SettingsPage
before(async () => {
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ useConnectionStore } = await vite.ssrLoadModule('/src/Diagnostics/ConnectionStore.ts'))
  ;({ usePlaybackStore } = await vite.ssrLoadModule('/src/Playback/PlaybackStore.ts'))
  ;({ default: ConnectionBanner } = await vite.ssrLoadModule('/src/Diagnostics/ConnectionBanner.vue'))
  ;({ default: SettingsPage } = await vite.ssrLoadModule('/src/Pages/Settings/SettingsPage.vue'))
})
beforeEach(() => setActivePinia(createPinia()))
after(async () => { await vite?.close() })
const response = state => ({ ok: true, json: async () => state })

test('container health does not hide a missing Windows control service', async () => {
  globalThis.fetch = async () => response({ mode: 'proxy', backend_connected: false,
    upstream: 'http://host.docker.internal:8081', message: 'Windows 控制服务未启动' })
  const store = useConnectionStore()
  await store.check()
  assert.equal(store.state.backend_connected, false)
  assert.match(store.state.message, /Windows/)
  assert.equal(store.checking, false)
})

test('a retry recovers the connection without reloading the page', async () => {
  const store = useConnectionStore()
  globalThis.fetch = async () => { throw new Error('无法连接控制服务') }
  await store.check()
  assert.equal(store.state.backend_connected, false)
  globalThis.fetch = async () => response({ mode: 'proxy', backend_connected: true, upstream: 'host', message: '已连接' })
  await store.check()
  assert.equal(store.state.backend_connected, true)
})

test('simultaneous monitor and self-check await the same connection result', async () => {
  let finish, requests = 0
  globalThis.fetch = () => { requests++; return new Promise(resolve => { finish = resolve }) }
  const store = useConnectionStore()
  const monitor = store.check()
  const manual = store.check()
  assert.equal(store.checking, true)
  assert.equal(requests, 1)
  let manualFinished = false
  void manual.then(() => { manualFinished = true })
  await Promise.resolve()
  assert.equal(manualFinished, false)
  finish(response({ mode: 'proxy', backend_connected: true, upstream: 'host', message: '已连接' }))
  await Promise.all([monitor, manual])
  assert.equal(store.state.backend_connected, true)
  assert.equal(store.checking, false)
})

test('an older backend missing the connection endpoint produces an actionable error', async () => {
  globalThis.fetch = async () => ({ ok: false, json: async () => ({ detail: 'Not Found' }) })
  const store = useConnectionStore()
  await store.check()
  assert.equal(store.state.backend_connected, false)
  assert.match(store.state.message, /更新并启动/)
})

test('offline HTML shows the Windows startup command and recovers without a stale warning', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useConnectionStore()
  store.state = { mode: 'proxy', backend_connected: false, upstream: 'host', message: 'Windows 控制服务未启动' }
  const app = createSSRApp(ConnectionBanner)
  app.use(pinia)
  const html = await renderToString(app)
  assert.match(html, /role="alert"/)
  assert.match(html, /StartDocker.ps1/)
  assert.match(html, /检查连接/)
  store.state.backend_connected = true
  const recovered = createSSRApp(ConnectionBanner)
  recovered.use(pinia)
  assert.doesNotMatch(await renderToString(recovered), /控制服务未连接/)
})

test('a pending playback command does not disable the read-only self-check button', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  usePlaybackStore().report('播放请求等待中', 'pending')
  const app = createSSRApp(SettingsPage)
  app.use(pinia)
  app.component('RouterLink', { setup(_props, { slots }) { return () => h('a', slots.default?.()) } })
  const html = await renderToString(app)
  const button = html.match(/<button[^>]*>重新检测<\/button>/)?.[0]
  assert.ok(button)
  assert.doesNotMatch(button, /disabled/)
})

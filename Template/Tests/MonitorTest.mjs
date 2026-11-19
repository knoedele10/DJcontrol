import assert from 'node:assert/strict'
import { after, before, beforeEach, test } from 'node:test'
import { createSSRApp, effectScope, h, ref } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'

let vite
let useMonitorStore
let MONITOR_DISPLAY_STORAGE_KEY
let useScreenStream
let SCREEN_CAPTURE_CONSTRAINTS
let PptPanel
let MonitorPage
let ScreenMonitor
let AppVue
let useConnectionStore
let useTutorialStore

const storage = new Map()

function makeDisplay(id, label, overrides = {}) {
  return {
    id,
    label,
    width: 1920,
    height: 1080,
    scaleFactor: 1,
    isPrimary: id === '1',
    isMainWindow: id === '1',
    ...overrides,
  }
}

function createMockBridge(initialDisplays = []) {
  let displays = initialDisplays
  let windowOpen = false
  let openShouldSucceed = true
  const displayListeners = new Set()
  const windowListeners = new Set()
  const selectedIds = []
  let openCalls = 0
  let closeCalls = 0

  const bridge = {
    isElectron: true,
    platform: 'win32',
    versions: { electron: '45.3.1', node: '22.0.0', chrome: '140.0.0' },
    getStatus: async () => ({}),
    retryStart: async () => {},
    restartBackend: async () => {},
    openLogsDir: async () => {},
    toggleFullscreen: async () => false,
    onStatus: () => () => {},
    monitor: {
      listDisplays: async () => displays,
      select: async (id) => {
        selectedIds.push(id)
        return Boolean(id && displays.some((d) => d.id === id))
      },
      openWindow: async () => {
        openCalls += 1
        if (!openShouldSucceed) return false
        windowOpen = true
        for (const fn of windowListeners) fn(true)
        return true
      },
      closeWindow: async () => {
        closeCalls += 1
        windowOpen = false
        for (const fn of windowListeners) fn(false)
      },
      onDisplaysChanged: (cb) => {
        displayListeners.add(cb)
        return () => displayListeners.delete(cb)
      },
      onWindowChanged: (cb) => {
        windowListeners.add(cb)
        return () => windowListeners.delete(cb)
      },
    },
    __emitDisplays(next) {
      displays = next
      for (const fn of displayListeners) fn(next)
    },
    __emitWindowOpen(open) {
      windowOpen = open
      for (const fn of windowListeners) fn(open)
    },
    __setOpenResult(ok) {
      openShouldSucceed = ok
    },
    __stats() {
      return { selectedIds, openCalls, closeCalls, windowOpen }
    },
  }
  return bridge
}

function flushMicrotasks() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

before(async () => {
  globalThis.localStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key),
  }

  vite = await createServer({
    server: { middlewareMode: true, hmr: false },
    appType: 'custom',
    optimizeDeps: { noDiscovery: true },
  })
  ;({ useMonitorStore, MONITOR_DISPLAY_STORAGE_KEY } = await vite.ssrLoadModule('/src/Monitor/MonitorStore.ts'))
  ;({ useScreenStream, SCREEN_CAPTURE_CONSTRAINTS } = await vite.ssrLoadModule('/src/Monitor/useScreenStream.ts'))
  PptPanel = (await vite.ssrLoadModule('/src/Ppt/PptPanel.vue')).default
  MonitorPage = (await vite.ssrLoadModule('/src/Monitor/MonitorPage.vue')).default
  ScreenMonitor = (await vite.ssrLoadModule('/src/Monitor/ScreenMonitor.vue')).default
  AppVue = (await vite.ssrLoadModule('/src/App.vue')).default
  ;({ useConnectionStore } = await vite.ssrLoadModule('/src/Diagnostics/ConnectionStore.ts'))
  ;({ useTutorialStore } = await vite.ssrLoadModule('/src/Tutorial/TutorialStore.ts'))
})

after(async () => {
  await vite?.close()
})

beforeEach(() => {
  storage.clear()
  setActivePinia(createPinia())
  globalThis.window = {
    location: { hash: '#/' },
    addEventListener: () => {},
    removeEventListener: () => {},
  }
})

test('MonitorStore disables cleanly when desktopApp.monitor is missing', async () => {
  const store = useMonitorStore()
  await store.init()
  assert.equal(store.supported, false)
  assert.equal(store.hasSecondScreen, false)
  assert.match(store.unavailableReason ?? '', /桌面版/)
})

test('MonitorStore remembers selected screen across disconnects and coordinates popup open/close', async () => {
  const d1 = makeDisplay('1', '主控屏', { isPrimary: true, isMainWindow: true })
  const d2 = makeDisplay('2', '大屏', { isMainWindow: false })
  const d3 = makeDisplay('3', '侧屏', { isMainWindow: false })
  const bridge = createMockBridge([d1, d2, d3])
  globalThis.window.desktopApp = bridge

  const store = useMonitorStore()
  await store.init()

  assert.equal(store.supported, true)
  assert.equal(store.hasSecondScreen, true)
  assert.equal(store.selectedDisplayId, '2')
  assert.equal(store.unavailableReason, null)

  store.selectDisplay('3')
  assert.equal(store.selectedDisplayId, '3')
  assert.equal(storage.get(MONITOR_DISPLAY_STORAGE_KEY), '3')

  // 拔掉侧屏后临时回退到仍在线的非主屏；重新接入后自动恢复记忆屏幕。
  bridge.__emitDisplays([d1, d2])
  assert.equal(store.selectedDisplayId, '2')
  assert.equal(storage.get(MONITOR_DISPLAY_STORAGE_KEY), '3')

  bridge.__emitDisplays([d1, d2, d3])
  assert.equal(store.selectedDisplayId, '3')

  assert.equal(await store.openPopup(), true)
  assert.equal(store.mode, 'live')
  assert.equal(store.windowOpen, true)

  bridge.__emitWindowOpen(false)
  assert.equal(store.windowOpen, false)

  // 单屏状态下给出明确原因
  bridge.__emitDisplays([d1])
  assert.equal(store.hasSecondScreen, false)
  assert.match(store.unavailableReason ?? '', /扩展/)

  store.dispose()
})

test('MonitorStore reverts windowOpen if openWindow returns false', async () => {
  const bridge = createMockBridge([
    makeDisplay('1', '主控屏'),
    makeDisplay('2', '大屏', { isMainWindow: false }),
  ])
  bridge.__setOpenResult(false)
  globalThis.window.desktopApp = bridge

  const store = useMonitorStore()
  await store.init()
  assert.equal(store.mode, 'preview')
  assert.equal(await store.openPopup(), false)
  assert.equal(store.windowOpen, false)
  assert.equal(store.mode, 'preview')
  store.dispose()
})

test('useScreenStream captures, handles manual stop vs unplug end, and cancels stale async captures', async () => {
  const active = ref(false)
  const displayId = ref('2')
  const selectedLog = []
  const captureCalls = []
  const streams = []
  let pendingResolve = null

  function createFakeStream(id) {
    const track = {
      id,
      stopped: 0,
      onended: null,
      stop() {
        this.stopped += 1
      },
    }
    const fakeStream = {
      id,
      track,
      getVideoTracks: () => [track],
      getTracks: () => [track],
    }
    streams.push(fakeStream)
    return fakeStream
  }

  const fakeVideo = { srcObject: null, play: () => Promise.resolve() }
  const scope = effectScope()
  const state = scope.run(() =>
    useScreenStream({
      active,
      displayId,
      selectDisplay: async (id) => {
        selectedLog.push(id)
        return true
      },
      getDisplayMedia: (constraints) => {
        captureCalls.push(constraints)
        if (captureCalls.length === 1) {
          return Promise.resolve(createFakeStream('s1'))
        }
        return new Promise((resolve) => {
          pendingResolve = resolve
        })
      },
    }),
  )

  state.videoEl.value = fakeVideo
  assert.equal(state.status.value, 'idle')

  // 1. 启动捕获
  active.value = true
  await flushMicrotasks()
  assert.equal(state.status.value, 'streaming')
  assert.deepEqual(selectedLog, ['2'])
  assert.deepEqual(captureCalls[0], SCREEN_CAPTURE_CONSTRAINTS)
  assert.equal(fakeVideo.srcObject?.id, 's1')

  // 2. 意外断轨 -> ended 状态并给出中文提示
  streams[0].track.onended()
  assert.equal(state.status.value, 'ended')
  assert.equal(state.stream.value, null)
  assert.match(state.error.value ?? '', /断开/)

  // 3. 切屏发起新请求，但在异步返回前被停用 -> 过期流返回后必须立刻 stop()
  displayId.value = '3'
  await flushMicrotasks()
  assert.equal(state.status.value, 'connecting')

  active.value = false
  await flushMicrotasks()
  assert.equal(state.status.value, 'idle')

  const staleStream = createFakeStream('s2-stale')
  pendingResolve(staleStream)
  await flushMicrotasks()
  assert.equal(staleStream.track.stopped, 1)
  assert.equal(state.status.value, 'idle')
  assert.equal(state.stream.value, null)

  scope.stop()
})

test('PptPanel SSR hides monitor UI outside Electron and renders disabled/popup states in Electron', async () => {
  // 1. 浏览器/Docker 模式（无 desktopApp.monitor）
  let html = await renderToString(
    createSSRApp(PptPanel).use(createPinia()),
  )
  assert.doesNotMatch(html, /⧉ 小窗/)
  assert.doesNotMatch(html, /第二屏/)

  // 2. Desktop 单屏模式
  const piniaSingle = createPinia()
  setActivePinia(piniaSingle)
  globalThis.window.desktopApp = createMockBridge([makeDisplay('1', '主屏幕')])
  let store = useMonitorStore()
  await store.init()
  html = await renderToString(createSSRApp(PptPanel).use(piniaSingle))
  assert.match(html, /⧉ 小窗/)
  assert.match(html, /第二屏/)
  assert.match(html, /disabled/)
  assert.match(html, /未检测到第二块屏幕/)

  // 3. Desktop 弹窗打开模式：只显示收回提示，不渲染 <video>
  const pinia = createPinia()
  setActivePinia(pinia)
  globalThis.window.desktopApp = createMockBridge([
    makeDisplay('1', '主屏幕'),
    makeDisplay('2', '扩展屏', { isMainWindow: false }),
  ])
  store = useMonitorStore()
  await store.init()
  await store.openPopup()
  const appPopup = createSSRApp({ render: () => h(PptPanel) }).use(pinia)
  html = await renderToString(appPopup)
  assert.match(html, /画面已在置顶小窗中/)
  assert.match(html, /收回/)
  assert.doesNotMatch(html, /<video/)

  // 弹窗开启时仍可切回静态「预览」，且不开启第二条捕获流
  store.setMode('preview')
  html = await renderToString(createSSRApp({ render: () => h(PptPanel) }).use(pinia))
  assert.doesNotMatch(html, /画面已在置顶小窗中/)
  assert.doesNotMatch(html, /<video/)
})

test('MonitorPage and ScreenMonitor SSR render video attributes and >2 screen selector', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  globalThis.window.desktopApp = createMockBridge([
    makeDisplay('1', '主屏', { isMainWindow: true }),
    makeDisplay('2', '扩展屏 A', { isMainWindow: false }),
  ])
  const store = useMonitorStore()
  await store.init()

  const htmlTwo = await renderToString(createSSRApp(MonitorPage).use(pinia))
  assert.match(htmlTwo, /<video[^>]*muted/)
  assert.match(htmlTwo, /autoplay/)
  assert.match(htmlTwo, /playsinline/)
  assert.match(htmlTwo, /收回/)
  assert.doesNotMatch(htmlTwo, /aria-label="选择监看屏幕"/)

  store.applyDisplays([
    makeDisplay('1', '主屏', { isMainWindow: true }),
    makeDisplay('2', '扩展屏 A', { isMainWindow: false }),
    makeDisplay('3', '扩展屏 B', { isMainWindow: false }),
  ])
  const htmlThree = await renderToString(createSSRApp(MonitorPage).use(pinia))
  assert.match(htmlThree, /aria-label="选择监看屏幕"/)

  const screenHtml = await renderToString(createSSRApp(ScreenMonitor, { active: false }).use(pinia))
  assert.match(screenHtml, /class="screen-video"/)
})

test('App.vue suppresses ConnectionBanner and TutorialOverlay on #/monitor route', async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: { render: () => h('div', 'dash') } },
      { path: '/monitor', name: 'monitor', component: { render: () => h('div', 'monitor-view') } },
    ],
  })

  const piniaDash = createPinia()
  setActivePinia(piniaDash)
  useConnectionStore(piniaDash).state = {
    mode: 'direct',
    backend_connected: false,
    upstream: null,
    message: '模拟后端未连接告警',
  }
  useTutorialStore(piniaDash).open = true
  await router.push('/')
  await router.isReady()
  const dashHtml = await renderToString(createSSRApp(AppVue).use(piniaDash).use(router))
  assert.match(dashHtml, /模拟后端未连接告警/)

  const piniaMon = createPinia()
  setActivePinia(piniaMon)
  globalThis.window.location.hash = '#/monitor'
  useConnectionStore(piniaMon).state = {
    mode: 'direct',
    backend_connected: false,
    upstream: null,
    message: '模拟后端未连接告警',
  }
  useTutorialStore(piniaMon).open = true
  await router.push('/monitor')
  const monHtml = await renderToString(createSSRApp(AppVue).use(piniaMon).use(router))
  assert.match(monHtml, /monitor-view/)
  assert.doesNotMatch(monHtml, /模拟后端未连接告警/)
  assert.doesNotMatch(monHtml, /tutorial/i)
})

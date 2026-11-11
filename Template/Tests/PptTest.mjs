// 使用 Vite 加载现有 TypeScript；Node 内置测试器，无额外测试依赖。
import assert from 'node:assert/strict'
import { after, afterEach, before, beforeEach, test } from 'node:test'
import { createServer } from 'vite'
import { createPinia, setActivePinia } from 'pinia'

let vite
let usePptStore
let usePlaybackStore
let preloadPptImages
let sockets = []
let storage = new Map()
let activeStore
let imageRequests = []

class CachedImage {
  complete = false
  naturalWidth = 0
  set src(value) {
    this.url = value
    imageRequests.push(value)
    queueMicrotask(() => {
      if (this.url !== value) return
      this.complete = true
      this.naturalWidth = 1280
      this.onload?.()
    })
  }
  get src() { return this.url }
  async decode() {}
  removeAttribute() { this.url = '' }
}

class Socket {
  constructor() { sockets.push(this) }
  open() { this.onopen?.() }
  emit(update) { this.onmessage?.({ data: JSON.stringify(update) }) }
  close() { this.onclose?.() }
}

function update(revision, current_slide = 1, overrides = {}) {
  return {
    type: 'ppt_state', revision,
    state: {
      app: 'powerpoint', connected: true, document_id: 'D:/show.pptx', file: 'show.pptx',
      current_slide, total_slides: 4, running: true, black: false, error: null, ...overrides,
    },
  }
}

function start() {
  const store = usePptStore()
  activeStore = store
  store.startSync()
  const socket = sockets.at(-1)
  socket.open()
  socket.emit(update(1))
  return { store, socket }
}

before(async () => {
  globalThis.window = globalThis
  globalThis.location = { protocol: 'http:', host: 'localhost:5173' }
  globalThis.WebSocket = Socket
  globalThis.localStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: (key) => storage.delete(key),
  }
  vite = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
  ;({ usePptStore } = await vite.ssrLoadModule('/src/Ppt/PptStore.ts'))
  ;({ usePlaybackStore } = await vite.ssrLoadModule('/src/Playback/PlaybackStore.ts'))
  ;({ preloadPptImages } = await vite.ssrLoadModule('/src/Ppt/PptPreload.ts'))
})

beforeEach(() => {
  sockets = []
  storage = new Map()
  imageRequests = []
  globalThis.Image = CachedImage
  setActivePinia(createPinia())
  globalThis.fetch = async () => ({ ok: true, json: async () => update(2, 2) })
})

after(async () => { await vite?.close() })
afterEach(() => {
  activeStore?.stopSync()
  activeStore = undefined
  usePlaybackStore().report('test cleanup', 'idle')
})

test('no connection means no control; a command waits for the actual returned page', async () => {
  const store = usePptStore()
  assert.equal(store.canControl, false)
  assert.equal(store.index, -1)
  const { socket } = start()
  let resolveRequest
  globalThis.fetch = () => new Promise((resolve) => { resolveRequest = resolve })
  const pending = store.next()
  assert.equal(store.pending, true)
  assert.equal(store.index, 0)
  assert.equal(store.canControl, false)
  resolveRequest({ ok: true, json: async () => update(2, 2) })
  await pending
  assert.equal(store.index, 1)
  assert.equal(store.pending, false)
  socket.emit(update(2, 2))
  assert.equal(store.index, 1)
  store.stopSync()
})

test('linked playback is done by the backend: the panel only logs each result once; stale HTTP responses do not roll pages back', async () => {
  const { store, socket } = start()
  const playback = usePlaybackStore()
  let requests = 0
  globalThis.fetch = async () => { requests += 1; return { ok: true, json: async () => update(2, 1) } }
  socket.emit({ ...update(3, 1), bindings: { 2: 18 }, link_music: true, link: null })
  assert.equal(store.slides[1].songId, 18)
  playback.report('sentinel', 'idle')
  socket.emit({ ...update(4, 2), bindings: { 2: 18 }, link: null })
  // 翻到绑了歌的页：面板自己不发播放命令，也不提前写「联动播放」。
  assert.equal(requests, 0)
  assert.equal(playback.command.text, 'sentinel')
  const played = { seq: 1, slide: 2, song_id: 18, status: 'played', message: '' }
  socket.emit({ ...update(5, 2), bindings: { 2: 18 }, link: played })
  assert.match(playback.command.text, /翻到第 2 页，联动播放/)
  playback.report('unchanged', 'idle')
  socket.emit({ ...update(6, 2), bindings: { 2: 18 }, link: played })
  assert.equal(playback.command.text, 'unchanged')
  socket.emit({ ...update(7, 2), bindings: { 2: 18 }, link: { ...played, seq: 2, status: 'failed', message: '酷狗还在连接' } })
  assert.match(playback.command.text, /失败：酷狗还在连接/)
  assert.equal(playback.command.status, 'failed')
  assert.equal(requests, 0)
  await store.next()
  assert.equal(store.index, 1)
  store.stopSync()
})

test('the link switch and old browser bindings are saved to the backend', async () => {
  storage.set('kgdash-ppt-bindings-v2', JSON.stringify({ 'powerpoint:D:/show.pptx': { 3: 18 } }))
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push([url, options.method, JSON.parse(options.body)])
    if (url.endsWith('/import')) return { ok: true, json: async () => ({ ...update(2, 1), bindings: { 3: 18 }, imported: 1 }) }
    return { ok: true, json: async () => ({ ...update(3, 1), bindings: { 3: 18 }, link_music: false }) }
  }
  const { store, socket } = start()
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.deepEqual(calls[0], ['/api/ppt/bindings/import', 'POST', { bindings: { 'powerpoint:D:/show.pptx': { 3: 18 } } }])
  assert.equal(storage.has('kgdash-ppt-bindings-v2'), false)
  assert.equal(store.slides[2].songId, 18)
  assert.equal(store.linkMusic, true)
  store.linkMusic = false
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.deepEqual(calls[1], ['/api/ppt/settings', 'PATCH', { link_music: false }])
  assert.equal(store.linkMusic, false)
  // 别的面板把开关打开：跟着后端推送变。
  socket.emit({ ...update(4, 1), link_music: true })
  assert.equal(store.linkMusic, true)
  store.stopSync()
})

test('failed commands preserve the real page and show a failure', async () => {
  const { store } = start()
  globalThis.fetch = async () => ({ ok: false, json: async () => ({ detail: { message: '软件忙碌' } }) })
  await store.next()
  assert.equal(store.index, 0)
  assert.equal(store.pending, false)
  assert.equal(store.error, '软件忙碌')
  assert.equal(usePlaybackStore().command.status, 'failed')
  store.stopSync()
})

test('preview URLs follow external page changes, identify the document and refresh on request', () => {
  const { store, socket } = start()
  const first = new URL(store.previewUrl, 'http://localhost')
  assert.equal(first.pathname, '/api/ppt/preview/1')
  assert.equal(first.searchParams.get('document'), 'D:/show.pptx')
  assert.equal(first.searchParams.get('width'), '1280')
  const thumb = new URL(store.slidePreview(2), 'http://localhost')
  assert.equal(thumb.pathname, '/api/ppt/preview/3')
  assert.equal(thumb.searchParams.get('width'), '1280')
  socket.emit(update(2, 3))
  assert.equal(new URL(store.previewUrl, 'http://localhost').pathname, '/api/ppt/preview/3')
  const previous = store.previewUrl
  store.refreshPreview()
  assert.notEqual(store.previewUrl, previous)
  socket.open()
  assert.equal(store.previewUrl, '')
  store.stopSync()
})

test('backend restart accepts reset revisions without replaying music', () => {
  const { store, socket } = start()
  const playback = usePlaybackStore()
  playback.play(18)
  store.bindCurrentSong()
  socket.emit(update(50, 3))
  // 模拟已重新建立的连接；其首次快照不能触发音乐联动。
  socket.open()
  assert.equal(store.canControl, false)
  playback.report('reconnected', 'idle')
  socket.emit(update(1, 1))
  assert.equal(store.index, 0)
  assert.equal(playback.command.text, 'reconnected')
  assert.equal(store.canControl, true)
  store.stopSync()
})

test('bindings are saved through the backend and scoped to documents; software exit clears stale pages', async () => {
  const { store, socket } = start()
  // 播放器状态以后端推送为准（未连接时 play() 不会在本地假装开播），这里模拟后端报告正在播 18 号歌
  usePlaybackStore().applyUpdate({
    type: 'player_state', revision: 0,
    state: {
      controller: 'mock', connected: true, status: 'playing', song_id: 18, title: '运动员进行曲', artist: '军乐团',
      position: 0, duration: 150, auto_next: true, queue: [], session: { id: 's', started_at: '', ended_at: null },
      recent_history: [], error: null,
    },
  })
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push([url, options.method, JSON.parse(options.body)])
    return { ok: true, json: async () => ({ ...update(2, 1), bindings: { 1: 18 } }) }
  }
  await store.bindCurrentSong()
  assert.deepEqual(calls, [['/api/ppt/bindings/1', 'PUT', { song_id: 18 }]])
  assert.equal(store.current.songId, 18)
  // 绑定跟着后端推送走：换了文稿就是另一份绑定，换回来再显示。
  socket.emit({ ...update(3, 1, { document_id: 'D:/other.pptx', file: 'other.pptx' }), bindings: {} })
  assert.equal(store.current.songId, null)
  socket.emit({ ...update(4, 1), bindings: { 1: 18 } })
  assert.equal(store.current.songId, 18)
  // 保存失败：页面上不显示成已绑定。
  globalThis.fetch = async () => ({ ok: false, json: async () => ({ detail: { message: '歌曲不存在，可能已被删除' } }) })
  await store.unbind()
  assert.equal(store.current.songId, 18)
  assert.match(usePlaybackStore().command.text, /没保存：歌曲不存在/)
  socket.emit(update(5, null, {
    connected: false, document_id: '', file: '', total_slides: 0,
    running: false, black: false, error: '软件已退出',
  }))
  assert.equal(store.index, -1)
  assert.equal(store.slides.length, 0)
  assert.equal(store.running, false)
  assert.equal(store.canControl, false)
  store.stopSync()
})

test('all pages preload on document load and turning pages reuses the decoded images', async () => {
  const { store, socket } = start()
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(store.preloadReady, 4)
  assert.equal(store.preloadTotal, 4)
  assert.equal(store.preloadLoading, false)
  assert.equal(imageRequests.length, 4)
  const cachedThird = store.thumbnailUrl(2)
  socket.emit(update(2, 3))
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(store.previewUrl, cachedThird)
  assert.equal(imageRequests.length, 4, '翻页不应重新载入整稿')
  store.refreshPreview()
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(imageRequests.length, 8)
  assert.equal(store.preloadReady, 4)
  assert.notEqual(store.thumbnailUrl(2), cachedThird)
  socket.emit({ ...update(3, 3), preview_session: 'reopened-document' })
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(new URL(store.previewUrl, 'http://localhost').searchParams.get('session'), 'reopened-document')
  assert.equal(store.preloadReady, 4)
})

test('preloading prioritizes the current page, continues after failure and cancels the old document', async () => {
  const instances = []
  class ControlledImage {
    constructor() { instances.push(this) }
    async decode() { this.decoded = true }
    removeAttribute() { this.removed = true }
  }
  globalThis.Image = ControlledImage
  const progress = []
  const stop = preloadPptImages(['one', 'two', 'three'], (value) => progress.push(value), () => ['two'])
  assert.equal(instances.length, 1, '后台一次只读取一页，避免积压控制操作')
  assert.equal(instances[0].src, 'two')
  await instances[0].onload()
  assert.equal(instances[0].decoded, true)
  assert.equal(instances[1].src, 'one')
  instances[1].onerror()
  assert.equal(instances[2].src, 'three')
  assert.equal(progress.at(-1).failed, 1)
  assert.deepEqual([...progress.at(-1).ready], ['two'])
  stop()
  assert.equal(instances[2].removed, true)
  assert.equal(instances[2].onload, null)
})

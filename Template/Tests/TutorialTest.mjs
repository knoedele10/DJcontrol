// 教程：第一次打开强制显示、看完才记下，后端或本机任一处记过就不再弹。
import assert from 'node:assert/strict'
import { after, before, beforeEach, test } from 'node:test'
import { createServer } from 'vite'
import { createPinia, setActivePinia } from 'pinia'

let vite, useTutorialStore, TUTORIAL_VERSION
let storage = new Map()
let requests = []
let remote = 0
let offline = false

before(async () => {
  globalThis.localStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: (key) => storage.delete(key),
  }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ useTutorialStore, TUTORIAL_VERSION } = await vite.ssrLoadModule('/src/Tutorial/TutorialStore.ts'))
})
after(async () => { await vite?.close() })

beforeEach(() => {
  setActivePinia(createPinia())
  storage = new Map()
  requests = []
  remote = 0
  offline = false
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ url, method: init.method ?? 'GET', body: init.body ? JSON.parse(init.body) : undefined })
    if (offline) throw new Error('无法连接控制服务')
    if (init.method === 'PUT') remote = JSON.parse(init.body).completed_version
    return { ok: true, json: async () => ({ completed_version: remote }) }
  }
})

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))
const saves = () => requests.filter((r) => r.method === 'PUT').map((r) => r.body.completed_version)

test('first launch forces the tutorial open and it cannot be closed', async () => {
  const tutorial = useTutorialStore()
  await tutorial.init()
  assert.equal(tutorial.open, true)
  assert.equal(tutorial.forced, true)
  assert.equal(tutorial.index, 0)
  tutorial.close()
  assert.equal(tutorial.open, true, '首次教程不能关闭')
  assert.deepEqual(saves(), [], '没看完不能记成已看')
})

test('finishing every step records the version on the backend and locally', async () => {
  const tutorial = useTutorialStore()
  await tutorial.init()
  tutorial.prev()
  assert.equal(tutorial.index, 0)
  for (let i = 1; i < tutorial.steps.length; i++) tutorial.next()
  assert.equal(tutorial.isLast, true)
  assert.equal(tutorial.open, true)
  tutorial.next()
  await settle()
  assert.equal(tutorial.open, false)
  assert.equal(tutorial.forced, false)
  assert.deepEqual(saves(), [TUTORIAL_VERSION])
  assert.equal(storage.get('kgdash.tutorial.version'), String(TUTORIAL_VERSION))

  setActivePinia(createPinia())
  const again = useTutorialStore()
  await again.init()
  assert.equal(again.open, false, '看完后再打开不再弹出')
})

test('a backend record suppresses the tutorial even when this browser has none', async () => {
  remote = TUTORIAL_VERSION
  const tutorial = useTutorialStore()
  await tutorial.init()
  assert.equal(tutorial.open, false)
  assert.equal(storage.get('kgdash.tutorial.version'), String(TUTORIAL_VERSION))
})

test('a local record suppresses the tutorial and is copied to a backend that lost it', async () => {
  storage.set('kgdash.tutorial.version', String(TUTORIAL_VERSION))
  const tutorial = useTutorialStore()
  await tutorial.init()
  assert.equal(tutorial.open, false)
  await settle()
  assert.deepEqual(saves(), [TUTORIAL_VERSION])
})

test('an offline backend still forces the tutorial on a fresh browser and keeps the local record', async () => {
  offline = true
  const tutorial = useTutorialStore()
  await tutorial.init()
  assert.equal(tutorial.open, true)
  assert.equal(tutorial.forced, true)
  for (let i = 0; i < tutorial.steps.length; i++) tutorial.next()
  await settle()
  assert.equal(tutorial.open, false)
  assert.equal(storage.get('kgdash.tutorial.version'), String(TUTORIAL_VERSION))
})

test('an outdated record shows the tutorial again after the version is raised', async () => {
  remote = TUTORIAL_VERSION - 1
  storage.set('kgdash.tutorial.version', String(TUTORIAL_VERSION - 1))
  const tutorial = useTutorialStore()
  await tutorial.init()
  assert.equal(tutorial.open, true)
  assert.equal(tutorial.forced, true)
})

test('reopening from the top bar can be closed at any step', async () => {
  remote = TUTORIAL_VERSION
  const tutorial = useTutorialStore()
  await tutorial.init()
  tutorial.start()
  assert.equal(tutorial.open, true)
  assert.equal(tutorial.forced, false)
  tutorial.next()
  tutorial.close()
  assert.equal(tutorial.open, false)
})

test('every step has text and only points at tutorial anchors or song cards', async () => {
  const tutorial = useTutorialStore()
  const ids = new Set()
  for (const step of tutorial.steps) {
    assert.ok(step.title && step.lines.length, step.id)
    assert.ok(!ids.has(step.id), `重复的步骤 ${step.id}`)
    ids.add(step.id)
    for (const target of step.targets ?? []) assert.match(target, /^\[data-(tour="[a-z-]+"|song-card)\]$/)
  }
})

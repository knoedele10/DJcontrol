import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import {
  MONITOR_DEFAULT_HEIGHT,
  MONITOR_DEFAULT_WIDTH,
  MONITOR_MARGIN,
  MONITOR_MIN_HEIGHT,
  MONITOR_MIN_WIDTH,
  clampMonitorBounds,
  createDisplayMediaHandler,
  describeDisplays,
  loadMonitorWindowState,
  matchCaptureSource,
  pickDefaultDisplay,
  saveMonitorWindowState,
} from '../dist/Monitor.js'

function flushAsync() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

test('describeDisplays normalizes scaleFactor, fallback labels, duplicate names, and flags', () => {
  const result = describeDisplays(
    [
      {
        id: 10,
        label: 'DELL U2720Q',
        bounds: { x: 0, y: 0, width: 1280, height: 720 },
        workArea: { x: 0, y: 0, width: 1280, height: 680 },
        size: { width: 1280, height: 720 },
        scaleFactor: 1.5,
      },
      {
        id: 20,
        label: 'DELL U2720Q',
        bounds: { x: 1280, y: 0, width: 1920, height: 1080 },
        workArea: { x: 1280, y: 0, width: 1920, height: 1040 },
        scaleFactor: 1,
      },
      {
        id: 30,
        label: '   ',
        bounds: { x: -1280, y: 0, width: 1280, height: 800 },
        workArea: { x: -1280, y: 0, width: 1280, height: 760 },
      },
    ],
    30,
    10,
  )

  assert.deepEqual(result, [
    {
      id: '10',
      label: 'DELL U2720Q (1)',
      width: 1920,
      height: 1080,
      scaleFactor: 1.5,
      isPrimary: false,
      isMainWindow: true,
    },
    {
      id: '20',
      label: 'DELL U2720Q (2)',
      width: 1920,
      height: 1080,
      scaleFactor: 1,
      isPrimary: false,
      isMainWindow: false,
    },
    {
      id: '30',
      label: '主屏幕',
      width: 1280,
      height: 800,
      scaleFactor: 1,
      isPrimary: true,
      isMainWindow: false,
    },
  ])
})

test('pickDefaultDisplay chooses non-main screen unless remembered display is still connected', () => {
  const displays = describeDisplays(
    [
      {
        id: 1,
        label: '控制屏',
        bounds: { x: 0, y: 0, width: 1920, height: 1080 },
        workArea: { x: 0, y: 0, width: 1920, height: 1040 },
      },
      {
        id: 2,
        label: 'LED 扩展屏',
        bounds: { x: 1920, y: 0, width: 1920, height: 1080 },
        workArea: { x: 1920, y: 0, width: 1920, height: 1040 },
      },
      {
        id: 3,
        label: '备屏',
        bounds: { x: 3840, y: 0, width: 1920, height: 1080 },
        workArea: { x: 3840, y: 0, width: 1920, height: 1040 },
      },
    ],
    1,
    1,
  )

  assert.equal(pickDefaultDisplay(displays)?.id, '2')
  assert.equal(pickDefaultDisplay(displays, '3')?.id, '3')
  assert.equal(pickDefaultDisplay(displays, 'missing')?.id, '2')
  assert.equal(pickDefaultDisplay([displays[0]]), null)
  assert.equal(pickDefaultDisplay([]), null)
})

test('matchCaptureSource strictly matches display_id without guessing another source', () => {
  const sources = [
    { id: 'screen:1:0', display_id: '1' },
    { id: 'screen:2:0', display_id: '2' },
  ]

  assert.equal(matchCaptureSource(sources, '2')?.id, 'screen:2:0')
  assert.equal(matchCaptureSource(sources, '999'), null)
  assert.equal(matchCaptureSource(sources, '   '), null)
  assert.equal(matchCaptureSource(sources, null), null)
})

test('clampMonitorBounds defaults to main bottom-right and recovers when saved screen disappears', () => {
  const mainDisplay = { workArea: { x: 0, y: 0, width: 1920, height: 1040 } }
  const secondDisplay = { workArea: { x: 1920, y: 0, width: 1920, height: 1080 } }

  const initial = clampMonitorBounds(null, [mainDisplay, secondDisplay], mainDisplay.workArea)
  assert.deepEqual(initial, {
    width: MONITOR_DEFAULT_WIDTH,
    height: MONITOR_DEFAULT_HEIGHT,
    x: 1920 - MONITOR_DEFAULT_WIDTH - MONITOR_MARGIN,
    y: 1040 - MONITOR_DEFAULT_HEIGHT - MONITOR_MARGIN,
  })

  const onSecond = clampMonitorBounds(
    { x: 2100, y: 120, width: 120, height: 80 },
    [mainDisplay, secondDisplay],
    mainDisplay.workArea,
  )
  assert.deepEqual(onSecond, {
    width: MONITOR_MIN_WIDTH,
    height: MONITOR_MIN_HEIGHT,
    x: 2100,
    y: 120,
  })

  const afterUnplug = clampMonitorBounds(onSecond, [mainDisplay], mainDisplay.workArea)
  assert.deepEqual(afterUnplug, {
    width: MONITOR_MIN_WIDTH,
    height: MONITOR_MIN_HEIGHT,
    x: 1920 - MONITOR_MIN_WIDTH - MONITOR_MARGIN,
    y: 1040 - MONITOR_MIN_HEIGHT - MONITOR_MARGIN,
  })
})

test('saveMonitorWindowState and loadMonitorWindowState round-trip cleanly', () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'kg-monitor-test-'))
  try {
    const filePath = path.join(tempDir, 'nested', 'monitorwindow.json')
    const mainArea = { workArea: { x: 0, y: 0, width: 1920, height: 1040 } }
    saveMonitorWindowState(filePath, { x: 100, y: 150, width: 640, height: 360 })
    const loaded = loadMonitorWindowState(filePath, [mainArea], mainArea.workArea)
    assert.deepEqual(loaded, { x: 100, y: 150, width: 640, height: 360 })
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true })
  }
})

test('createDisplayMediaHandler authorizes same-origin selected screen and rejects invalid requests', async () => {
  const loadingPagePath = path.join(os.tmpdir(), 'Loading.html')
  let appUrl = 'http://127.0.0.1:41234/'
  const selectedByWc = new Map([
    [101, '20'],
    [102, '999'],
  ])
  const screenSources = [
    { id: 'screen:10:0', display_id: '10' },
    { id: 'screen:20:0', display_id: '20' },
  ]

  const handler = createDisplayMediaHandler({
    getAppUrl: () => appUrl,
    loadingPagePath,
    getSelectedDisplayId: (wcId) => selectedByWc.get(wcId),
    getScreenSources: async () => screenSources,
    getWebContentsFromFrame: (frame) => ({ id: frame.wcId }),
  })

  const invoke = (request) =>
    new Promise((resolve) => {
      handler(request, (result) => resolve(result))
    })

  assert.equal(
    await invoke({ frame: { url: 'https://evil.example/', wcId: 101 }, securityOrigin: 'https://evil.example' }),
    null,
  )
  assert.equal(
    await invoke({ frame: { url: `file:///${loadingPagePath.replace(/\\/g, '/')}`, wcId: 101 }, securityOrigin: 'file://' }),
    null,
  )
  assert.equal(
    await invoke({ frame: { url: 'http://127.0.0.1:41234/#/monitor', wcId: 999 }, securityOrigin: 'http://127.0.0.1:41234' }),
    null,
  )
  assert.equal(
    await invoke({ frame: { url: 'http://127.0.0.1:41234/', wcId: 102 }, securityOrigin: 'http://127.0.0.1:41234' }),
    null,
  )

  const okResult = await invoke({
    frame: { url: 'http://127.0.0.1:41234/#/monitor', wcId: 101 },
    securityOrigin: 'http://127.0.0.1:41234',
  })
  assert.equal(okResult?.video?.id, 'screen:20:0')

  appUrl = null
  await flushAsync()
  assert.equal(
    await invoke({ frame: { url: 'http://127.0.0.1:41234/', wcId: 101 }, securityOrigin: 'http://127.0.0.1:41234' }),
    null,
  )
})

import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import path from 'node:path'
import { PassThrough } from 'node:stream'
import test from 'node:test'
import { BackendManager } from '../dist/BackendManager.js'

function makePaths(overrides = {}) {
  return {
    isPackaged: false,
    desktopRoot: path.resolve('D:/repo/Desktop'),
    repoRoot: path.resolve('D:/repo'),
    backendDir: path.resolve('D:/repo/Backend'),
    frontendDist: path.resolve('D:/repo/Template/dist'),
    dbPath: path.resolve('D:/repo/Backend/Data/dashboard.db'),
    logsDir: path.resolve('D:/repo/logs'),
    cacheDir: path.resolve('D:/repo/cache'),
    runnerScript: path.resolve('D:/repo/Desktop/Resources/BackendRunner.py'),
    loadingPage: path.resolve('D:/repo/Desktop/Resources/Loading.html'),
    iconPath: path.resolve('D:/repo/Desktop/Assets/Icon.ico'),
    pythonExecutable: 'python',
    ...overrides,
  }
}

function makeOptions(overrides = {}) {
  return {
    devMode: false,
    devUrl: 'http://127.0.0.1:5173',
    preferredPort: 18081,
    openDevTools: false,
    ...overrides,
  }
}

function createFakeChild() {
  const child = new EventEmitter()
  child.pid = 4242
  child.exitCode = null
  child.signalCode = null
  child.stdout = new PassThrough()
  child.stderr = new PassThrough()
  child.stdin = new PassThrough()
  const chunks = []
  child.stdin.on('data', (d) => chunks.push(d.toString()))
  child.stdinText = () => chunks.join('')
  child.kill = (signal) => {
    child.signalCode = signal || 'SIGKILL'
    child.emit('exit', null, child.signalCode)
    return true
  }
  return child
}

test('BackendManager fails fast when frontend dist is missing in production mode', async () => {
  const manager = new BackendManager(makePaths(), makeOptions(), {
    exists: () => false,
    mkdir: () => {},
    appendLog: () => {},
  })

  await assert.rejects(() => manager.start(), /未找到前端构建产物/)
  assert.equal(manager.getStatus().phase, 'error')
})

test('BackendManager starts backend, passes env, waits for health, and shuts down via stdin', async () => {
  const paths = makePaths()
  const existing = new Set([
    path.join(paths.frontendDist, 'index.html'),
    paths.runnerScript,
    path.join(paths.backendDir, 'Main.py'),
  ])

  let spawnedCommand = null
  let spawnedEnv = null
  const child = createFakeChild()
  let healthCalls = 0

  const manager = new BackendManager(paths, makeOptions(), {
    exists: (target) => existing.has(target),
    mkdir: () => {},
    appendLog: () => {},
    findPort: async () => 18081,
    healthIntervalMs: 10,
    healthTimeoutMs: 1000,
    stopTimeoutMs: 500,
    spawnProcess: (cmd, args, opts) => {
      spawnedCommand = { cmd, args }
      spawnedEnv = opts.env
      return child
    },
    fetchFn: async (url) => {
      assert.equal(url, 'http://127.0.0.1:18081/api/health')
      healthCalls += 1
      if (healthCalls < 2) throw new Error('not ready yet')
      return new Response(JSON.stringify({ status: 'ok' }), { status: 200 })
    },
  })

  const url = await manager.start()
  assert.equal(url, 'http://127.0.0.1:18081')
  assert.deepEqual(spawnedCommand, { cmd: 'python', args: ['-X', 'utf8', paths.runnerScript] })
  assert.equal(spawnedEnv.FRONTEND_DIST, paths.frontendDist)
  assert.equal(spawnedEnv.DB_PATH, paths.dbPath)
  assert.equal(spawnedEnv.KGDASH_PORT, '18081')
  assert.equal(manager.getStatus().phase, 'ready')

  child.stdin.on('finish', () => {
    queueMicrotask(() => {
      child.exitCode = 0
      child.emit('exit', 0, null)
    })
  })
  await manager.stop()
  assert.equal(child.stdinText(), 'shutdown\n')
  assert.equal(manager.getStatus().phase, 'stopped')
})

test('BackendManager connects to external backend in dev mode and validates Vite dev server', async () => {
  const manager = new BackendManager(makePaths(), makeOptions({ devMode: true, preferredPort: 8000 }), {
    exists: () => false,
    mkdir: () => {},
    appendLog: () => {},
    healthIntervalMs: 10,
    devFrontendTimeoutMs: 50,
    fetchFn: async (url) => {
      if (url === 'http://127.0.0.1:8000/api/health') {
        return new Response(JSON.stringify({ status: 'ok' }), { status: 200 })
      }
      if (url === 'http://127.0.0.1:5173') {
        return new Response('<html></html>', { status: 200 })
      }
      throw new Error(`unexpected url ${url}`)
    },
  })

  const url = await manager.start()
  assert.equal(url, 'http://127.0.0.1:5173')
  assert.equal(manager.getStatus().external, true)
  await manager.stop()
  assert.equal(manager.getStatus().phase, 'stopped')
})

test('BackendManager reports clear error in dev mode when Vite dev server is down', async () => {
  const manager = new BackendManager(makePaths(), makeOptions({ devMode: true, preferredPort: 8000 }), {
    exists: () => false,
    mkdir: () => {},
    appendLog: () => {},
    healthIntervalMs: 10,
    devFrontendTimeoutMs: 30,
    fetchFn: async (url) => {
      if (url === 'http://127.0.0.1:8000/api/health') {
        return new Response(JSON.stringify({ status: 'ok' }), { status: 200 })
      }
      throw new Error('ECONNREFUSED')
    },
  })

  await assert.rejects(() => manager.start(), /无法连接前端开发服务器/)
  assert.equal(manager.getStatus().phase, 'error')
})

test('BackendManager captures early process exit logs and unexpected crash events', async () => {
  const paths = makePaths()
  const existing = new Set([
    path.join(paths.frontendDist, 'index.html'),
    paths.runnerScript,
    path.join(paths.backendDir, 'Main.py'),
  ])

  let child = createFakeChild()
  const manager = new BackendManager(paths, makeOptions(), {
    exists: (target) => existing.has(target),
    mkdir: () => {},
    appendLog: () => {},
    findPort: async () => 18081,
    healthIntervalMs: 10,
    healthTimeoutMs: 500,
    stopTimeoutMs: 50,
    spawnProcess: () => {
      setTimeout(() => {
        child.stderr.write('ImportError: missing dependency\n')
        child.exitCode = 1
        child.emit('exit', 1, null)
      }, 15)
      return child
    },
    fetchFn: async () => {
      throw new Error('offline')
    },
  })

  await assert.rejects(() => manager.start(), /ImportError: missing dependency/)
  assert.equal(manager.getStatus().phase, 'error')

  // Test post-startup unexpected exit event
  child = createFakeChild()
  const crashEvents = []
  const crashManager = new BackendManager(paths, makeOptions(), {
    exists: (target) => existing.has(target),
    mkdir: () => {},
    appendLog: () => {},
    findPort: async () => 18081,
    healthIntervalMs: 10,
    healthTimeoutMs: 500,
    spawnProcess: () => child,
    fetchFn: async () => new Response(JSON.stringify({ status: 'ok' }), { status: 200 }),
  })
  crashManager.on('unexpected-exit', (status) => crashEvents.push(status))
  await crashManager.start()
  child.exitCode = 137
  child.emit('exit', 137, null)
  assert.equal(crashEvents.length, 1)
  assert.equal(crashEvents[0].phase, 'error')
  assert.match(crashEvents[0].error, /意外退出/)
})

test('BackendManager kills hung child with taskkill on win32 when shutdown times out', async () => {
  const paths = makePaths()
  const existing = new Set([
    path.join(paths.frontendDist, 'index.html'),
    paths.runnerScript,
    path.join(paths.backendDir, 'Main.py'),
  ])
  const child = createFakeChild()
  const spawned = []

  const manager = new BackendManager(paths, makeOptions(), {
    exists: (target) => existing.has(target),
    mkdir: () => {},
    appendLog: () => {},
    findPort: async () => 18081,
    platform: 'win32',
    healthIntervalMs: 10,
    healthTimeoutMs: 500,
    stopTimeoutMs: 30,
    spawnProcess: (cmd, args) => {
      spawned.push({ cmd, args })
      if (cmd === 'taskkill') {
        const killer = new EventEmitter()
        queueMicrotask(() => {
          child.exitCode = 1
          child.emit('exit', 1, null)
          killer.emit('exit', 0, null)
        })
        return killer
      }
      return child
    },
    fetchFn: async () => new Response(JSON.stringify({ status: 'ok' }), { status: 200 }),
  })

  await manager.start()
  await manager.stop()
  assert.equal(spawned[1].cmd, 'taskkill')
  assert.deepEqual(spawned[1].args, ['/pid', '4242', '/T', '/F'])
  assert.equal(manager.getStatus().phase, 'stopped')
})

test('BackendManager strips FRONTEND_DIST in dev mode, supports reportError, and cancels cleanly on stop mid-start', async () => {
  const paths = makePaths()
  const existing = new Set([
    paths.runnerScript,
    path.join(paths.backendDir, 'Main.py'),
  ])
  const prevFrontendDist = process.env.FRONTEND_DIST
  process.env.FRONTEND_DIST = 'D:/stale/dist'

  try {
    let capturedEnv = null
    const child = createFakeChild()
    child.stdin.on('finish', () => {
      queueMicrotask(() => {
        child.exitCode = 0
        child.emit('exit', 0, null)
      })
    })

    const devManager = new BackendManager(paths, makeOptions({ devMode: true, preferredPort: 8000 }), {
      exists: (target) => existing.has(target),
      mkdir: () => {},
      appendLog: () => {},
      healthIntervalMs: 10,
      healthTimeoutMs: 500,
      devFrontendTimeoutMs: 100,
      spawnProcess: (_cmd, _args, opts) => {
        capturedEnv = opts.env
        return child
      },
      fetchFn: async (url) => {
        if (url === 'http://127.0.0.1:8000/api/health') {
          if (!capturedEnv) throw new Error('not started')
          return new Response(JSON.stringify({ status: 'ok' }), { status: 200 })
        }
        return new Response('<html></html>', { status: 200 })
      },
    })

    await devManager.start()
    assert.equal(capturedEnv.FRONTEND_DIST, undefined)
    devManager.reportError('无法加载面板界面', 'ERR_CONNECTION_REFUSED')
    assert.equal(devManager.getStatus().phase, 'error')
    assert.equal(devManager.getStatus().error, 'ERR_CONNECTION_REFUSED')
    await devManager.stop()

    let resolvePort
    let spawnedDuringCancel = false
    const cancelManager = new BackendManager(paths, makeOptions(), {
      exists: (target) => target === path.join(paths.frontendDist, 'index.html') || existing.has(target),
      mkdir: () => {},
      appendLog: () => {},
      findPort: () => new Promise((resolve) => { resolvePort = resolve }),
      spawnProcess: () => {
        spawnedDuringCancel = true
        return createFakeChild()
      },
    })

    const pending = cancelManager.start()
    await new Promise((resolve) => setTimeout(resolve, 10))
    await cancelManager.stop()
    resolvePort(18081)
    await assert.rejects(() => pending, /取消/)
    assert.equal(spawnedDuringCancel, false)
    assert.equal(cancelManager.getStatus().phase, 'stopped')
  } finally {
    if (prevFrontendDist === undefined) delete process.env.FRONTEND_DIST
    else process.env.FRONTEND_DIST = prevFrontendDist
  }
})

test('BackendManager isolates packaged Python from host PYTHONHOME, PYTHONPATH, and user site-packages', async () => {
  const paths = makePaths({
    isPackaged: true,
    pythonExecutable: path.resolve('D:/app/resources/python/python.exe'),
  })
  const existing = new Set([
    path.join(paths.frontendDist, 'index.html'),
    paths.runnerScript,
    path.join(paths.backendDir, 'Main.py'),
    paths.pythonExecutable,
  ])

  const saved = {
    PYTHONHOME: process.env.PYTHONHOME,
    PYTHONPATH: process.env.PYTHONPATH,
    PYTHONSTARTUP: process.env.PYTHONSTARTUP,
    PYTHONUSERBASE: process.env.PYTHONUSERBASE,
    API_UPSTREAM: process.env.API_UPSTREAM,
    ELECTRON_DEV: process.env.ELECTRON_DEV,
    KGDASH_DEV: process.env.KGDASH_DEV,
    KGDASH_DEV_URL: process.env.KGDASH_DEV_URL,
  }
  process.env.PYTHONHOME = 'D:/host/python'
  process.env.PYTHONPATH = 'D:/host/libs'
  process.env.PYTHONSTARTUP = 'D:/host/startup.py'
  process.env.PYTHONUSERBASE = 'D:/host/userbase'
  process.env.API_UPSTREAM = 'http://127.0.0.1:19999'
  process.env.ELECTRON_DEV = '1'
  process.env.KGDASH_DEV = '1'
  process.env.KGDASH_DEV_URL = 'http://127.0.0.1:5173'

  try {
    let capturedEnv = null
    const child = createFakeChild()
    child.stdin.on('finish', () => {
      queueMicrotask(() => {
        child.exitCode = 0
        child.emit('exit', 0, null)
      })
    })

    const manager = new BackendManager(paths, makeOptions(), {
      exists: (target) => existing.has(target),
      mkdir: () => {},
      appendLog: () => {},
      findPort: async () => 18081,
      healthIntervalMs: 10,
      healthTimeoutMs: 500,
      spawnProcess: (_cmd, _args, opts) => {
        capturedEnv = opts.env
        return child
      },
      fetchFn: async () => new Response(JSON.stringify({ status: 'ok' }), { status: 200 }),
    })

    await manager.start()
    assert.equal(capturedEnv.PYTHONHOME, undefined)
    assert.equal(capturedEnv.PYTHONPATH, undefined)
    assert.equal(capturedEnv.PYTHONSTARTUP, undefined)
    assert.equal(capturedEnv.PYTHONUSERBASE, undefined)
    assert.equal(capturedEnv.API_UPSTREAM, undefined)
    assert.equal(capturedEnv.ELECTRON_DEV, undefined)
    assert.equal(capturedEnv.KGDASH_DEV, undefined)
    assert.equal(capturedEnv.KGDASH_DEV_URL, undefined)
    assert.equal(capturedEnv.PYTHONNOUSERSITE, '1')
    assert.equal(capturedEnv.PYTHONDONTWRITEBYTECODE, '1')
    assert.equal(capturedEnv.KGDASH_CACHE_DIR, paths.cacheDir)
    await manager.stop()
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
  }
})

test('BackendManager fails clearly when bundled Python is missing in packaged mode', async () => {
  const paths = makePaths({
    isPackaged: true,
    pythonExecutable: path.resolve('D:/app/resources/python/python.exe'),
  })
  const existing = new Set([
    path.join(paths.frontendDist, 'index.html'),
    paths.runnerScript,
    path.join(paths.backendDir, 'Main.py'),
  ])

  const manager = new BackendManager(paths, makeOptions(), {
    exists: (target) => existing.has(target),
    mkdir: () => {},
    appendLog: () => {},
  })

  await assert.rejects(() => manager.start(), /内置 Python 运行时/)
  assert.equal(manager.getStatus().phase, 'error')
})

import assert from 'node:assert/strict'
import net from 'node:net'
import path from 'node:path'
import test from 'node:test'
import { pathToFileURL } from 'node:url'
import {
  findAvailablePort,
  isAllowedAppUrl,
  parseDesktopOptions,
  resolveDesktopPaths,
  resolvePythonExecutable,
} from '../dist/Config.js'

test('resolveDesktopPaths resolves unpackaged repo paths and .venv python', () => {
  const desktopRoot = path.resolve('D:/repo/Desktop')
  const expectedVenv = path.join('D:/repo/Backend', '.venv', 'Scripts', 'python.exe')
  const paths = resolveDesktopPaths({
    isPackaged: false,
    desktopRoot,
    userDataPath: 'C:/Users/demo/AppData/Roaming/app',
    platform: 'win32',
    env: {},
    exists: (target) => path.normalize(target) === path.normalize(expectedVenv),
  })

  assert.equal(paths.repoRoot, path.resolve('D:/repo'))
  assert.equal(paths.backendDir, path.resolve('D:/repo/Backend'))
  assert.equal(paths.frontendDist, path.resolve('D:/repo/Template/dist'))
  assert.equal(paths.dbPath, path.resolve('D:/repo/Backend/Data/dashboard.db'))
  assert.equal(paths.logsDir, path.join('C:/Users/demo/AppData/Roaming/app', 'logs'))
  assert.equal(paths.runnerScript, path.join(desktopRoot, 'Resources', 'BackendRunner.py'))
  assert.equal(paths.iconPath, path.join(desktopRoot, 'Assets', 'Icon.ico'))
  assert.equal(paths.pythonExecutable, expectedVenv)
})

test('resolveDesktopPaths prefers unpacked runner/icon and userData DB when packaged', () => {
  const resourcesPath = path.resolve('C:/Program Files/App/resources')
  const desktopRoot = path.join(resourcesPath, 'app.asar')
  const unpackedRunner = path.join(resourcesPath, 'app.asar.unpacked', 'Resources', 'BackendRunner.py')
  const unpackedIcon = path.join(resourcesPath, 'app.asar.unpacked', 'Assets', 'Icon.ico')
  const bundledPython = path.join(resourcesPath, 'python', 'python.exe')
  const existing = new Set([unpackedRunner, unpackedIcon, bundledPython].map((p) => path.normalize(p)))

  const paths = resolveDesktopPaths({
    isPackaged: true,
    desktopRoot,
    resourcesPath,
    userDataPath: 'C:/Users/demo/AppData/Roaming/app',
    platform: 'win32',
    env: {},
    exists: (target) => existing.has(path.normalize(target)),
  })

  assert.equal(paths.backendDir, path.join(resourcesPath, 'backend'))
  assert.equal(paths.frontendDist, path.join(resourcesPath, 'frontend'))
  assert.equal(paths.dbPath, path.join('C:/Users/demo/AppData/Roaming/app', 'Data', 'dashboard.db'))
  assert.equal(paths.runnerScript, unpackedRunner)
  assert.equal(paths.iconPath, unpackedIcon)
  assert.equal(paths.pythonExecutable, bundledPython)
})

test('resolvePythonExecutable respects env overrides and posix paths', () => {
  assert.equal(
    resolvePythonExecutable({
      isPackaged: true,
      backendDir: '/app/backend',
      resourcesPath: '/app/resources',
      platform: 'linux',
      env: { KGDASH_PYTHON: '/custom/python3' },
      exists: () => true,
    }),
    '/custom/python3',
  )

  assert.equal(
    resolvePythonExecutable({
      isPackaged: false,
      backendDir: '/app/backend',
      platform: 'linux',
      env: {},
      exists: () => false,
    }),
    'python3',
  )
})

test('parseDesktopOptions handles dev mode, port overrides, and devtools flag', () => {
  assert.deepEqual(parseDesktopOptions([], {}), {
    devMode: false,
    devUrl: 'http://127.0.0.1:5173',
    preferredPort: 18081,
    openDevTools: false,
    smokeTest: false,
  })

  assert.deepEqual(parseDesktopOptions(['--dev'], { KGDASH_DEV_URL: 'http://127.0.0.1:5174' }), {
    devMode: true,
    devUrl: 'http://127.0.0.1:5174',
    preferredPort: 8000,
    openDevTools: true,
    smokeTest: false,
  })

  assert.deepEqual(parseDesktopOptions(['--devtools'], { KGDASH_PORT: '19000' }), {
    devMode: false,
    devUrl: 'http://127.0.0.1:5173',
    preferredPort: 19000,
    openDevTools: true,
    smokeTest: false,
  })

  assert.equal(parseDesktopOptions(['--smoke-test'], {}).smokeTest, true)
  assert.equal(parseDesktopOptions([], { KGDASH_PORT: 'not-a-port' }).preferredPort, 18081)
})

test('findAvailablePort falls back to an ephemeral port when preferred port is occupied', async () => {
  const occupied = net.createServer()
  await new Promise((resolve) => occupied.listen(0, '127.0.0.1', resolve))
  const address = occupied.address()
  assert.ok(address && typeof address === 'object')

  try {
    const port = await findAvailablePort(address.port, '127.0.0.1')
    assert.ok(Number.isInteger(port) && port > 0)
    assert.notEqual(port, address.port)
  } finally {
    await new Promise((resolve) => occupied.close(resolve))
  }
})

test('isAllowedAppUrl restricts navigation to app origin or local loading page', () => {
  const loadingPath = path.resolve('Desktop/Resources/Loading.html')
  const loadingUrl = pathToFileURL(loadingPath).toString()
  const otherFileUrl = pathToFileURL(path.resolve('Desktop/Resources/Other.html')).toString()

  assert.equal(isAllowedAppUrl(loadingUrl, null, loadingPath), true)
  assert.equal(isAllowedAppUrl(otherFileUrl, null, loadingPath), false)
  assert.equal(isAllowedAppUrl('http://127.0.0.1:18081/#/settings', 'http://127.0.0.1:18081', loadingPath), true)
  assert.equal(isAllowedAppUrl('https://example.com', 'http://127.0.0.1:18081', loadingPath), false)
  assert.equal(isAllowedAppUrl('not a url', 'http://127.0.0.1:18081', loadingPath), false)
})

import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'

export interface DesktopPaths {
  isPackaged: boolean
  desktopRoot: string
  repoRoot: string
  backendDir: string
  frontendDist: string
  dbPath: string
  logsDir: string
  runnerScript: string
  loadingPage: string
  iconPath: string
  pythonExecutable: string
}

export interface DesktopOptions {
  devMode: boolean
  devUrl: string
  preferredPort: number
  openDevTools: boolean
  smokeTest: boolean
}

export interface ResolvePathsInput {
  isPackaged: boolean
  desktopRoot: string
  resourcesPath?: string
  userDataPath: string
  platform?: NodeJS.Platform
  env?: NodeJS.ProcessEnv
  exists?: (target: string) => boolean
}

/** 根据源码目录或打包资源目录解析后端、前端产物、数据库与 Python 路径。 */
export function resolveDesktopPaths(input: ResolvePathsInput): DesktopPaths {
  const {
    isPackaged,
    desktopRoot,
    resourcesPath = '',
    userDataPath,
    platform = process.platform,
    env = process.env,
    exists = fs.existsSync,
  } = input

  const repoRoot = path.resolve(desktopRoot, '..')
  const backendDir = isPackaged
    ? path.join(resourcesPath, 'backend')
    : path.join(repoRoot, 'Backend')
  const frontendDist = env.FRONTEND_DIST?.trim()
    || (isPackaged ? path.join(resourcesPath, 'frontend') : path.join(repoRoot, 'Template', 'dist'))
  const dbPath = env.DB_PATH?.trim()
    || (isPackaged
      ? path.join(userDataPath, 'Data', 'dashboard.db')
      : path.join(backendDir, 'Data', 'dashboard.db'))
  const logsDir = path.join(userDataPath, 'logs')
  const loadingPage = path.join(desktopRoot, 'Resources', 'Loading.html')
  const iconFile = platform === 'win32' ? 'Icon.ico' : 'Icon.png'
  const iconCandidates = isPackaged
    ? [
        path.join(resourcesPath, 'app.asar.unpacked', 'Assets', iconFile),
        path.join(desktopRoot, 'Assets', iconFile),
      ]
    : [path.join(desktopRoot, 'Assets', iconFile)]
  const iconPath = iconCandidates.find((candidate) => exists(candidate)) ?? iconCandidates[0]

  const runnerCandidates = isPackaged
    ? [
        path.join(resourcesPath, 'app.asar.unpacked', 'Resources', 'BackendRunner.py'),
        path.join(resourcesPath, 'BackendRunner.py'),
        path.join(desktopRoot, 'Resources', 'BackendRunner.py'),
      ]
    : [path.join(desktopRoot, 'Resources', 'BackendRunner.py')]
  const runnerScript = runnerCandidates.find((candidate) => exists(candidate)) ?? runnerCandidates[0]

  const pythonExecutable = resolvePythonExecutable({
    isPackaged,
    backendDir,
    resourcesPath,
    platform,
    env,
    exists,
  })

  return {
    isPackaged,
    desktopRoot,
    repoRoot,
    backendDir,
    frontendDist,
    dbPath,
    logsDir,
    runnerScript,
    loadingPage,
    iconPath,
    pythonExecutable,
  }
}

export function resolvePythonExecutable(input: {
  isPackaged: boolean
  backendDir: string
  resourcesPath?: string
  platform?: NodeJS.Platform
  env?: NodeJS.ProcessEnv
  exists?: (target: string) => boolean
}): string {
  const {
    isPackaged,
    backendDir,
    resourcesPath = '',
    platform = process.platform,
    env = process.env,
    exists = fs.existsSync,
  } = input

  const override = env.KGDASH_PYTHON?.trim() || env.PYTHON_EXE?.trim()
  if (override) return override

  const candidates: string[] = []
  if (isPackaged && resourcesPath) {
    candidates.push(
      platform === 'win32'
        ? path.join(resourcesPath, 'python', 'python.exe')
        : path.join(resourcesPath, 'python', 'bin', 'python3'),
    )
  }
  candidates.push(
    platform === 'win32'
      ? path.join(backendDir, '.venv', 'Scripts', 'python.exe')
      : path.join(backendDir, '.venv', 'bin', 'python'),
  )

  return candidates.find((candidate) => exists(candidate)) ?? (platform === 'win32' ? 'python' : 'python3')
}

function parsePort(raw: string | undefined): number | null {
  if (!raw?.trim()) return null
  const value = Number(raw)
  if (!Number.isInteger(value) || value < 1 || value > 65535) return null
  return value
}

export function parseDesktopOptions(
  argv: string[] = process.argv.slice(1),
  env: NodeJS.ProcessEnv = process.env,
): DesktopOptions {
  const devMode = argv.includes('--dev') || env.KGDASH_DEV === '1' || env.ELECTRON_DEV === '1'
  const devUrl = env.KGDASH_DEV_URL?.trim() || 'http://127.0.0.1:5173'
  const preferredPort = parsePort(env.KGDASH_PORT) ?? (devMode ? 8000 : 18081)
  const openDevTools = argv.includes('--devtools') || devMode
  const smokeTest = argv.includes('--smoke-test') || env.KGDASH_SMOKE_TEST === '1'
  return { devMode, devUrl, preferredPort, openDevTools, smokeTest }
}

function bindPort(port: number, host: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.once('error', reject)
    server.listen(port, host, () => {
      const address = server.address()
      const bound = typeof address === 'object' && address ? address.port : port
      server.close((closeErr) => {
        if (closeErr) reject(closeErr)
        else resolve(bound)
      })
    })
  })
}

/** 优先使用固定本地端口以保持浏览器持久化来源稳定；被占用时回退到系统空闲端口。 */
export async function findAvailablePort(preferredPort: number, host = '127.0.0.1'): Promise<number> {
  try {
    return await bindPort(preferredPort, host)
  } catch (error) {
    const code = (error as NodeJS.ErrnoException)?.code
    if ((code === 'EADDRINUSE' || code === 'EACCES') && preferredPort !== 0) {
      return await bindPort(0, host)
    }
    throw error
  }
}

export function isAllowedAppUrl(targetUrl: string, appUrl: string | null, loadingPagePath: string): boolean {
  try {
    const target = new URL(targetUrl)
    if (target.protocol === 'file:') {
      const targetPath = path.resolve(decodeURIComponent(target.pathname.replace(/^\/([A-Za-z]:)/, '$1')))
      return targetPath.toLowerCase() === path.resolve(loadingPagePath).toLowerCase()
    }
    if (!appUrl) return false
    const allowed = new URL(appUrl)
    return target.origin === allowed.origin
  } catch {
    return false
  }
}

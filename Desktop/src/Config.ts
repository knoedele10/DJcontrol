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
  cacheDir: string
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
  // 打包版锁定内置前端与 userData 数据库路径，禁止宿主机 FRONTEND_DIST / DB_PATH 覆盖或写入安装目录。
  const frontendDist = isPackaged
    ? path.join(resourcesPath, 'frontend')
    : (env.FRONTEND_DIST?.trim() || path.join(repoRoot, 'Template', 'dist'))
  const dbPath = isPackaged
    ? path.join(userDataPath, 'Data', 'dashboard.db')
    : (env.DB_PATH?.trim() || path.join(backendDir, 'Data', 'dashboard.db'))
  const logsDir = path.join(userDataPath, 'logs')
  const cacheDir = path.join(userDataPath, 'cache')
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
    cacheDir,
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

  if (isPackaged) {
    // 打包版必须锁定随包分发的独立 Python，禁止宿主机环境变量或系统 Python 旁路。
    return platform === 'win32'
      ? path.join(resourcesPath, 'python', 'python.exe')
      : path.join(resourcesPath, 'python', 'bin', 'python3')
  }

  const override = env.KGDASH_PYTHON?.trim() || env.PYTHON_EXE?.trim()
  if (override) return override

  const venvPython = platform === 'win32'
    ? path.join(backendDir, '.venv', 'Scripts', 'python.exe')
    : path.join(backendDir, '.venv', 'bin', 'python')

  return exists(venvPython) ? venvPython : (platform === 'win32' ? 'python' : 'python3')
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
  isPackaged = false,
): DesktopOptions {
  // 打包版禁止通过宿主机开发/测试环境变量切换外部服务、端口或提前退出。
  const devMode = !isPackaged && (argv.includes('--dev') || env.KGDASH_DEV === '1' || env.ELECTRON_DEV === '1')
  const devUrl = (!isPackaged && env.KGDASH_DEV_URL?.trim()) || 'http://127.0.0.1:5173'
  const preferredPort = (!isPackaged ? parsePort(env.KGDASH_PORT) : null) ?? (devMode ? 8000 : 18081)
  const openDevTools = argv.includes('--devtools') || devMode
  const smokeTest = argv.includes('--smoke-test') || (!isPackaged && env.KGDASH_SMOKE_TEST === '1')
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

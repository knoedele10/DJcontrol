import { spawn, type ChildProcess } from 'node:child_process'
import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import path from 'node:path'
import { findAvailablePort, type DesktopOptions, type DesktopPaths } from './Config.js'

export type BackendPhase = 'idle' | 'starting' | 'ready' | 'stopping' | 'stopped' | 'error'

export interface BackendStatus {
  phase: BackendPhase
  message: string
  error: string | null
  url: string | null
  port: number | null
  external: boolean
  logs: string[]
}

export interface BackendManagerDeps {
  spawnProcess?: typeof spawn
  fetchFn?: typeof fetch
  exists?: (target: string) => boolean
  mkdir?: (target: string) => void
  appendLog?: (file: string, line: string) => void
  findPort?: (preferredPort: number, host?: string) => Promise<number>
  platform?: NodeJS.Platform
  healthTimeoutMs?: number
  healthIntervalMs?: number
  devFrontendTimeoutMs?: number
  stopTimeoutMs?: number
}

const MAX_LOG_LINES = 200

/** 管理本地 Python FastAPI 后端进程：探测端口、等待健康检查、收集日志并在退出时优雅关闭。 */
export class BackendManager extends EventEmitter {
  private readonly paths: DesktopPaths
  private readonly options: DesktopOptions
  private readonly spawnProcess: typeof spawn
  private readonly fetchFn: typeof fetch
  private readonly exists: (target: string) => boolean
  private readonly mkdir: (target: string) => void
  private readonly appendLog: (file: string, line: string) => void
  private readonly findPort: (preferredPort: number, host?: string) => Promise<number>
  private readonly platform: NodeJS.Platform
  private readonly healthTimeoutMs: number
  private readonly healthIntervalMs: number
  private readonly devFrontendTimeoutMs: number
  private readonly stopTimeoutMs: number

  private child: ChildProcess | null = null
  private external = false
  private intentionalStop = false
  private startPromise: Promise<string> | null = null
  private stopPromise: Promise<void> | null = null
  private status: BackendStatus = {
    phase: 'idle',
    message: '等待启动控制引擎',
    error: null,
    url: null,
    port: null,
    external: false,
    logs: [],
  }

  constructor(paths: DesktopPaths, options: DesktopOptions, deps: BackendManagerDeps = {}) {
    super()
    this.paths = paths
    this.options = options
    this.spawnProcess = deps.spawnProcess ?? spawn
    this.fetchFn = deps.fetchFn ?? fetch
    this.exists = deps.exists ?? fs.existsSync
    this.mkdir = deps.mkdir ?? ((target) => fs.mkdirSync(target, { recursive: true }))
    this.appendLog = deps.appendLog ?? ((file, line) => {
      try {
        fs.appendFileSync(file, `${line}\n`, 'utf8')
      } catch {
        /* 写日志失败不应阻塞主进程运行 */
      }
    })
    this.findPort = deps.findPort ?? findAvailablePort
    this.platform = deps.platform ?? process.platform
    this.healthTimeoutMs = deps.healthTimeoutMs ?? 25000
    this.healthIntervalMs = deps.healthIntervalMs ?? 150
    this.devFrontendTimeoutMs = deps.devFrontendTimeoutMs ?? 10000
    this.stopTimeoutMs = deps.stopTimeoutMs ?? 4000
  }

  getStatus(): BackendStatus {
    return { ...this.status, logs: [...this.status.logs] }
  }

  reportError(message: string, detail: string | null = null): void {
    this.updateStatus({
      phase: 'error',
      message,
      error: detail ?? message,
      url: null,
    })
  }

  private updateStatus(patch: Partial<BackendStatus>): void {
    this.status = { ...this.status, ...patch }
    this.emit('status', this.getStatus())
  }

  private pushLog(raw: string): void {
    const file = path.join(this.paths.logsDir, 'backend.log')
    const lines = raw.replace(/\r\n/g, '\n').split('\n').filter((line) => line.length > 0)
    if (!lines.length) return
    const next = [...this.status.logs, ...lines].slice(-MAX_LOG_LINES)
    this.status = { ...this.status, logs: next }
    for (const line of lines) {
      this.appendLog(file, line)
    }
  }

  private async probeHealth(port: number): Promise<boolean> {
    try {
      const response = await this.fetchFn(`http://127.0.0.1:${port}/api/health`, {
        signal: AbortSignal.timeout(800),
      })
      if (!response.ok) return false
      const payload = (await response.json()) as { status?: string }
      return payload?.status === 'ok'
    } catch {
      return false
    }
  }

  private async probeFrontend(url: string): Promise<boolean> {
    try {
      const response = await this.fetchFn(url, {
        signal: AbortSignal.timeout(800),
      })
      return response.status < 500
    } catch {
      return false
    }
  }

  private async waitForDevFrontend(): Promise<void> {
    this.updateStatus({
      phase: 'starting',
      message: `正在等待前端开发服务器（${this.options.devUrl}）…`,
    })
    const deadline = Date.now() + this.devFrontendTimeoutMs
    while (Date.now() <= deadline) {
      if (this.intentionalStop) {
        throw new Error('控制引擎启动已取消')
      }
      if (await this.probeFrontend(this.options.devUrl)) {
        return
      }
      if (Date.now() >= deadline) break
      await new Promise((resolve) => setTimeout(resolve, this.healthIntervalMs))
    }
    throw new Error(
      `无法连接前端开发服务器（${this.options.devUrl}）。请先在 Template 目录运行 pnpm dev，或使用 Scripts\\DevDesktop.ps1。`,
    )
  }

  async start(): Promise<string> {
    if (this.startPromise) return this.startPromise
    if (this.status.phase === 'ready' && this.status.url) return this.status.url

    this.startPromise = this.performStart().finally(() => {
      this.startPromise = null
    })
    return this.startPromise
  }

  private async performStart(): Promise<string> {
    this.intentionalStop = false
    this.external = false
    this.updateStatus({
      phase: 'starting',
      message: '正在检查本地环境与前端产物…',
      error: null,
      url: null,
      port: null,
      external: false,
      logs: [],
    })

    if (!this.options.devMode && !this.exists(path.join(this.paths.frontendDist, 'index.html'))) {
      const msg = `未找到前端构建产物（${this.paths.frontendDist}）。请先在 Template 目录运行 pnpm build，或使用 Scripts\\StartDesktop.ps1。`
      this.updateStatus({ phase: 'error', message: '前端尚未构建', error: msg })
      throw new Error(msg)
    }

    if (this.options.devMode && (await this.probeHealth(this.options.preferredPort))) {
      if (this.intentionalStop) throw new Error('控制引擎启动已取消')
      this.external = true
      try {
        await this.waitForDevFrontend()
      } catch (error) {
        if (!this.intentionalStop) {
          const message = error instanceof Error ? error.message : String(error)
          this.updateStatus({ phase: 'error', message: '前端开发服务器未就绪', error: message })
        }
        throw error
      }
      const url = this.options.devUrl
      this.updateStatus({
        phase: 'ready',
        message: '已连接现有开发后端',
        error: null,
        url,
        port: this.options.preferredPort,
        external: true,
      })
      return url
    }

    if (this.intentionalStop) {
      throw new Error('控制引擎启动已取消')
    }

    if (!this.exists(this.paths.runnerScript)) {
      const msg = `未找到后端启动脚本：${this.paths.runnerScript}`
      this.updateStatus({ phase: 'error', message: '桌面启动文件缺失', error: msg })
      throw new Error(msg)
    }
    if (!this.exists(path.join(this.paths.backendDir, 'Main.py'))) {
      const msg = `未找到后端入口：${path.join(this.paths.backendDir, 'Main.py')}`
      this.updateStatus({ phase: 'error', message: '后端目录不完整', error: msg })
      throw new Error(msg)
    }
    if (this.paths.isPackaged && !this.exists(this.paths.pythonExecutable)) {
      const msg = `未找到内置 Python 运行时（${this.paths.pythonExecutable}），请重新安装应用。`
      this.updateStatus({ phase: 'error', message: '内置运行环境缺失', error: msg })
      throw new Error(msg)
    }

    this.mkdir(this.paths.logsDir)
    const cacheDir = this.paths.cacheDir || path.join(path.dirname(this.paths.logsDir), 'cache')
    if (this.paths.isPackaged) {
      this.mkdir(cacheDir)
    }
    const port = this.options.devMode
      ? this.options.preferredPort
      : await this.findPort(this.options.preferredPort, '127.0.0.1')

    if (this.intentionalStop) {
      throw new Error('控制引擎启动已取消')
    }

    this.updateStatus({
      phase: 'starting',
      message: `正在启动控制引擎（127.0.0.1:${port}）…`,
      port,
    })

    const env: NodeJS.ProcessEnv = {
      ...process.env,
      PYTHONUTF8: '1',
      PYTHONIOENCODING: 'utf-8',
      PYTHONUNBUFFERED: '1',
      KGDASH_HOST: '127.0.0.1',
      KGDASH_PORT: String(port),
      KGDASH_BACKEND_DIR: this.paths.backendDir,
      DB_PATH: this.paths.dbPath,
    }
    if (this.paths.isPackaged) {
      // 打包版隔离宿主机 Python 与开发/代理环境变量，避免切入代理模式或污染依赖/缓存路径。
      delete env.PYTHONHOME
      delete env.PYTHONPATH
      delete env.PYTHONSTARTUP
      delete env.PYTHONUSERBASE
      delete env.API_UPSTREAM
      delete env.ELECTRON_DEV
      delete env.KGDASH_DEV
      delete env.KGDASH_DEV_URL
      env.PYTHONNOUSERSITE = '1'
      env.PYTHONDONTWRITEBYTECODE = '1'
      env.KGDASH_CACHE_DIR = cacheDir
    }
    if (this.options.devMode) {
      delete env.FRONTEND_DIST
    } else {
      env.FRONTEND_DIST = this.paths.frontendDist
    }

    const child = this.spawnProcess(
      this.paths.pythonExecutable,
      ['-X', 'utf8', this.paths.runnerScript],
      {
        cwd: this.paths.backendDir,
        env,
        stdio: ['pipe', 'pipe', 'pipe'],
        windowsHide: true,
      },
    )
    this.child = child

    let earlyExitMessage: string | null = null
    let settledStart = false

    const attachStream = (stream: NodeJS.ReadableStream | null) => {
      if (!stream) return
      stream.setEncoding('utf8')
      stream.on('data', (chunk: string) => this.pushLog(chunk))
    }
    attachStream(child.stdout)
    attachStream(child.stderr)

    child.once('error', (err) => {
      const msg = `无法拉起 Python 控制服务（${this.paths.pythonExecutable}）：${err.message}`
      this.pushLog(msg)
      earlyExitMessage = msg
      if (this.child === child) this.child = null
      if (settledStart && !this.intentionalStop) {
        this.updateStatus({ phase: 'error', message: '控制引擎启动失败', error: msg })
        this.emit('unexpected-exit', this.getStatus())
      }
    })

    child.once('exit', (code, signal) => {
      if (this.child === child) this.child = null
      if (this.intentionalStop) return
      const tail = this.status.logs.slice(-6).join('\n')
      const detail = tail ? `\n\n最近日志：\n${tail}` : ''
      const msg = `控制引擎意外退出（code=${code ?? 'null'}, signal=${signal ?? 'none'}）。${detail}`
      earlyExitMessage = msg
      if (settledStart) {
        this.updateStatus({ phase: 'error', message: '控制引擎已停止', error: msg })
        this.emit('unexpected-exit', this.getStatus())
      }
    })

    const deadline = Date.now() + this.healthTimeoutMs
    try {
      while (Date.now() < deadline) {
        if (this.intentionalStop) {
          throw new Error('控制引擎启动已取消')
        }
        if (earlyExitMessage) {
          throw new Error(earlyExitMessage)
        }
        if (await this.probeHealth(port)) {
          if (this.options.devMode) {
            await this.waitForDevFrontend()
          }
          settledStart = true
          const url = this.options.devMode ? this.options.devUrl : `http://127.0.0.1:${port}`
          this.updateStatus({
            phase: 'ready',
            message: '控制引擎已就绪',
            error: null,
            url,
            port,
            external: false,
          })
          return url
        }
        await new Promise((resolve) => setTimeout(resolve, this.healthIntervalMs))
      }
      const timeoutMsg = `等待控制引擎就绪超时（>${Math.round(this.healthTimeoutMs / 1000)} 秒）。`
      throw new Error(timeoutMsg)
    } catch (error) {
      settledStart = true
      if (!this.intentionalStop) {
        const message = error instanceof Error ? error.message : String(error)
        this.updateStatus({ phase: 'error', message: '控制引擎启动失败', error: message })
      }
      await this.stop()
      throw error
    }
  }

  async stop(): Promise<void> {
    if (this.stopPromise) return this.stopPromise
    this.stopPromise = this.performStop().finally(() => {
      this.stopPromise = null
    })
    return this.stopPromise
  }

  private async performStop(): Promise<void> {
    const child = this.child
    this.intentionalStop = true
    if (this.external || !child) {
      this.child = null
      if (this.status.phase !== 'error') {
        this.updateStatus({ phase: 'stopped', message: '控制引擎已停止', url: null })
      }
      return
    }

    if (this.status.phase !== 'error') {
      this.updateStatus({ phase: 'stopping', message: '正在关闭控制引擎…' })
    }

    const waitForExit = new Promise<void>((resolve) => {
      if (child.exitCode !== null || child.signalCode !== null) {
        resolve()
        return
      }
      child.once('exit', () => resolve())
      child.once('error', () => resolve())
    })

    try {
      if (child.stdin && !child.stdin.destroyed) {
        child.stdin.write('shutdown\n')
        child.stdin.end()
      }
    } catch {
      /* 管道已关闭时忽略 */
    }

    const exitedCleanly = await Promise.race([
      waitForExit.then(() => true),
      new Promise<boolean>((resolve) => setTimeout(() => resolve(false), this.stopTimeoutMs)),
    ])

    if (!exitedCleanly && child.pid) {
      if (this.platform === 'win32') {
        await new Promise<void>((resolve) => {
          const killer = this.spawnProcess('taskkill', ['/pid', String(child.pid), '/T', '/F'], {
            stdio: 'ignore',
            windowsHide: true,
          })
          killer.once('exit', () => resolve())
          killer.once('error', () => {
            try { child.kill('SIGKILL') } catch { /* ignore */ }
            resolve()
          })
        })
      } else {
        try { child.kill('SIGKILL') } catch { /* ignore */ }
      }
      await Promise.race([
        waitForExit,
        new Promise<void>((resolve) => setTimeout(resolve, 1000)),
      ])
    }

    this.child = null
    if (this.status.phase !== 'error') {
      this.updateStatus({ phase: 'stopped', message: '控制引擎已停止', url: null })
    }
  }

  async restart(): Promise<string> {
    await this.stop()
    return await this.start()
  }
}

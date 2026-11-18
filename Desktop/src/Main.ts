import fs from 'node:fs'
import path from 'node:path'
import { app, BrowserWindow, ipcMain, screen, shell } from 'electron'
import { BackendManager, type BackendStatus } from './BackendManager.js'
import { isAllowedAppUrl, parseDesktopOptions, resolveDesktopPaths } from './Config.js'
import { installApplicationMenu } from './Menu.js'
import { loadWindowState, saveWindowState } from './WindowState.js'

// 禁止 Chromium 抢占系统硬件媒体键，避免演出时影响酷狗快捷键/媒体控制。
app.commandLine.appendSwitch('disable-features', 'HardwareMediaKeyHandling')
if (process.platform === 'win32') {
  app.setAppUserModelId('com.kugoudashboard.desktop')
}

const desktopRoot = path.resolve(import.meta.dirname, '..')
const options = parseDesktopOptions(process.argv.slice(1), process.env, app.isPackaged)
const paths = resolveDesktopPaths({
  isPackaged: app.isPackaged,
  desktopRoot,
  resourcesPath: process.resourcesPath,
  userDataPath: app.getPath('userData'),
})

const windowStateFile = path.join(app.getPath('userData'), 'windowstate.json')
const backend = new BackendManager(paths, options)

let mainWindow: BrowserWindow | null = null
let activeAppUrl: string | null = null
let isQuitting = false

const gotLock = options.smokeTest ? true : app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
}

function sendStatus(status: BackendStatus): void {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('desktop:status', status)
  }
}

async function showLoadingPage(): Promise<void> {
  if (!mainWindow || mainWindow.isDestroyed()) return
  await mainWindow.loadFile(paths.loadingPage)
  sendStatus(backend.getStatus())
}

async function runSmokeCheck(): Promise<void> {
  if (!mainWindow || mainWindow.isDestroyed()) {
    throw new Error('主窗口未创建')
  }
  const deadline = Date.now() + 8000
  while (Date.now() < deadline) {
    const ok = await mainWindow.webContents.executeJavaScript(
      "Boolean(window.desktopApp?.isElectron && document.querySelector('#app')?.children.length > 0)",
    )
    if (ok) {
      console.log(`DESKTOP_SMOKE_OK ${activeAppUrl}`)
      app.quit()
      return
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error('前端界面未能完成挂载')
}

async function startAndOpenApp(): Promise<void> {
  try {
    const url = await backend.start()
    activeAppUrl = url
    if (mainWindow && !mainWindow.isDestroyed()) {
      await mainWindow.loadURL(url)
      if (options.openDevTools && !mainWindow.webContents.isDevToolsOpened()) {
        mainWindow.webContents.openDevTools({ mode: 'detach' })
      }
      if (options.smokeTest) {
        await runSmokeCheck()
      }
    }
  } catch (error) {
    activeAppUrl = null
    const current = backend.getStatus()
    if (current.phase !== 'error' && current.phase !== 'stopped') {
      const detail = error instanceof Error ? error.message : String(error)
      backend.reportError('无法加载面板界面', detail)
    }
    if (options.smokeTest) {
      console.error('DESKTOP_SMOKE_FAIL', error)
      await backend.stop()
      app.exit(1)
      return
    }
    if (mainWindow && !mainWindow.isDestroyed()) {
      const currentUrl = mainWindow.webContents.getURL()
      if (!currentUrl.startsWith('file://')) {
        await showLoadingPage()
      } else {
        sendStatus(backend.getStatus())
      }
    }
  }
}

function createMainWindow(): BrowserWindow {
  const initialState = loadWindowState(windowStateFile, screen.getAllDisplays())
  const preloadPath = path.join(import.meta.dirname, 'Preload.cjs')

  const win = new BrowserWindow({
    width: initialState.width,
    height: initialState.height,
    x: initialState.x,
    y: initialState.y,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: '#0a0918',
    title: '酷狗统筹面板',
    icon: fs.existsSync(paths.iconPath) ? paths.iconPath : undefined,
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  if (initialState.maximized) {
    win.maximize()
  }

  let normalBounds = win.getNormalBounds()
  const persistBounds = () => {
    if (options.smokeTest || win.isDestroyed()) return
    if (!win.isMaximized() && !win.isFullScreen()) {
      normalBounds = win.getBounds()
    }
    saveWindowState(windowStateFile, normalBounds, win.isMaximized())
  }

  win.on('resize', () => {
    if (!win.isMaximized() && !win.isFullScreen()) normalBounds = win.getBounds()
  })
  win.on('move', () => {
    if (!win.isMaximized() && !win.isFullScreen()) normalBounds = win.getBounds()
  })
  win.on('close', persistBounds)
  win.on('closed', () => {
    if (mainWindow === win) mainWindow = null
  })

  win.once('ready-to-show', () => {
    if (!options.smokeTest) {
      win.show()
    }
  })

  // 防止网页意外导航到外部站点；外部链接交由系统浏览器打开。
  win.webContents.on('will-navigate', (event, targetUrl) => {
    if (!isAllowedAppUrl(targetUrl, activeAppUrl, paths.loadingPage)) {
      event.preventDefault()
    }
  })
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) {
      void shell.openExternal(url)
    }
    return { action: 'deny' }
  })
  win.webContents.on('render-process-gone', (_event, details) => {
    if (isQuitting) return
    backend.reportError('界面渲染进程意外终止', `原因：${details.reason}（code=${details.exitCode}）`)
    void showLoadingPage()
  })

  mainWindow = win
  return win
}

function registerIpcHandlers(): void {
  ipcMain.handle('desktop:getStatus', () => backend.getStatus())
  ipcMain.handle('desktop:retryStart', async () => {
    await showLoadingPage()
    await startAndOpenApp()
  })
  ipcMain.handle('desktop:restartBackend', async () => {
    await showLoadingPage()
    await backend.stop()
    await startAndOpenApp()
  })
  ipcMain.handle('desktop:openLogsDir', async () => {
    fs.mkdirSync(paths.logsDir, { recursive: true })
    await shell.openPath(paths.logsDir)
  })
  ipcMain.handle('desktop:toggleFullscreen', () => {
    if (!mainWindow || mainWindow.isDestroyed()) return false
    const next = !mainWindow.isFullScreen()
    mainWindow.setFullScreen(next)
    return next
  })
}

if (gotLock) {
  backend.on('status', sendStatus)
  backend.on('unexpected-exit', () => {
    if (isQuitting) return
    activeAppUrl = null
    void showLoadingPage()
  })

  app.on('second-instance', () => {
    if (!mainWindow) return
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
  })

  app.whenReady().then(async () => {
    registerIpcHandlers()
    installApplicationMenu({
      getWindow: () => mainWindow,
      onRestartBackend: () => {
        void (async () => {
          await showLoadingPage()
          await backend.stop()
          await startAndOpenApp()
        })()
      },
      onOpenLogs: () => {
        fs.mkdirSync(paths.logsDir, { recursive: true })
        void shell.openPath(paths.logsDir)
      },
      onOpenDashboard: () => {
        if (!mainWindow || !activeAppUrl) return
        void mainWindow.loadURL(new URL('#/', activeAppUrl).toString())
      },
      onOpenSettings: () => {
        if (!mainWindow || !activeAppUrl) return
        void mainWindow.loadURL(new URL('#/settings', activeAppUrl).toString())
      },
    })

    createMainWindow()
    await showLoadingPage()
    await startAndOpenApp()
  })

  app.on('window-all-closed', () => {
    app.quit()
  })

  app.on('before-quit', (event) => {
    if (isQuitting) return
    isQuitting = true
    event.preventDefault()
    void backend.stop().finally(() => {
      app.exit(0)
    })
  })
}

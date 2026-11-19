import fs from 'node:fs'
import path from 'node:path'
import type {
  BrowserWindow as ElectronBrowserWindow,
  BrowserWindowConstructorOptions,
  DesktopCapturer,
  DesktopCapturerSource,
  IpcMain,
  Screen,
  Session,
  WebContents,
  WebFrameMain,
} from 'electron'
import { isAllowedAppUrl } from './Config.js'
import type { DisplayArea } from './WindowState.js'

export const MONITOR_DEFAULT_WIDTH = 480
export const MONITOR_DEFAULT_HEIGHT = 270
export const MONITOR_MIN_WIDTH = 280
export const MONITOR_MIN_HEIGHT = 158
export const MONITOR_MARGIN = 24

export interface MonitorDisplay {
  id: string
  label: string
  width: number
  height: number
  scaleFactor: number
  isPrimary: boolean
  isMainWindow: boolean
}

export interface RawDisplayLike {
  id: number
  label?: string
  bounds: { x: number; y: number; width: number; height: number }
  workArea: { x: number; y: number; width: number; height: number }
  size?: { width: number; height: number }
  scaleFactor?: number
}

export interface MonitorBounds {
  width: number
  height: number
  x: number
  y: number
}

export interface DisplayMediaRequestLike {
  frame: WebFrameMain | null
  securityOrigin: string
}

export interface DisplayMediaHandlerDeps {
  getAppUrl: () => string | null
  loadingPagePath: string
  getSelectedDisplayId: (webContentsId: number) => string | undefined
  getScreenSources: () => Promise<DesktopCapturerSource[]>
  getWebContentsFromFrame: (frame: WebFrameMain) => WebContents | undefined
}

export interface RegisterMonitorDeps {
  BrowserWindow: new (options?: BrowserWindowConstructorOptions) => ElectronBrowserWindow
  desktopCapturer: DesktopCapturer
  ipcMain: IpcMain
  screen: Screen
  session: { defaultSession: Session }
  webContents: { fromFrame: (frame: WebFrameMain) => WebContents | undefined }
  getMainWindow: () => ElectronBrowserWindow | null
  getAppUrl: () => string | null
  loadingPagePath: string
  preloadPath: string
  iconPath: string
  stateFile: string
  isSmokeTest: boolean
}

export interface MonitorController {
  closeWindow: () => void
  notifyMainWindowMoved: () => void
  notifyWindowState: () => void
  dispose: () => void
}

/** 将 Electron 显示器列表规范化为带物理分辨率、可读标签与主屏/主窗标记的快照。 */
export function describeDisplays(
  displays: RawDisplayLike[],
  primaryId: number | null,
  mainDisplayId: number | null,
): MonitorDisplay[] {
  const baseLabels = displays.map((display, index) => {
    const trimmed = display.label?.trim()
    if (trimmed) return trimmed
    return display.id === primaryId ? '主屏幕' : `显示器 ${index + 1}`
  })

  const labelCounts = new Map<string, number>()
  for (const label of baseLabels) {
    labelCounts.set(label, (labelCounts.get(label) ?? 0) + 1)
  }

  return displays.map((display, index) => {
    const scale = typeof display.scaleFactor === 'number' && display.scaleFactor > 0 ? display.scaleFactor : 1
    const logicalWidth = display.size?.width ?? display.bounds.width
    const logicalHeight = display.size?.height ?? display.bounds.height
    const baseLabel = baseLabels[index]
    const label = (labelCounts.get(baseLabel) ?? 0) > 1 ? `${baseLabel} (${index + 1})` : baseLabel

    return {
      id: String(display.id),
      label,
      width: Math.round(logicalWidth * scale),
      height: Math.round(logicalHeight * scale),
      scaleFactor: scale,
      isPrimary: display.id === primaryId,
      isMainWindow: display.id === mainDisplayId,
    }
  })
}

/** 优先沿用上次记忆的显示器；否则默认选择主面板未占用的扩展屏，单屏时返回 null。 */
export function pickDefaultDisplay(
  displays: MonitorDisplay[],
  preferredId?: string | null,
): MonitorDisplay | null {
  if (displays.length === 0) return null
  if (preferredId) {
    const remembered = displays.find((display) => display.id === preferredId)
    if (remembered) return remembered
  }
  return displays.find((display) => !display.isMainWindow) ?? null
}

/** 按 display_id 精确匹配屏幕捕获源；未指定或找不到时不盲猜兜底。 */
export function matchCaptureSource<T extends { id: string; display_id: string }>(
  sources: T[],
  displayId: string | null | undefined,
): T | null {
  const target = displayId?.trim()
  if (!target) return null
  return sources.find((source) => source.display_id === target) ?? null
}

function intersectsEnough(bounds: MonitorBounds, area: DisplayArea['workArea']): boolean {
  const overlapX = Math.min(bounds.x + bounds.width, area.x + area.width) - Math.max(bounds.x, area.x)
  const overlapY = Math.min(bounds.y + bounds.height, area.y + area.height) - Math.max(bounds.y, area.y)
  return overlapX >= 80 && overlapY >= 80
}

/** 钳制置顶监看小窗位置与大小；坐标失效或外接屏断开时落在基准屏幕右下角。 */
export function clampMonitorBounds(
  bounds: Partial<MonitorBounds> | null | undefined,
  displays: DisplayArea[],
  mainWorkArea?: DisplayArea['workArea'],
): MonitorBounds {
  const fallbackArea = mainWorkArea ?? displays[0]?.workArea ?? { x: 0, y: 0, width: 1920, height: 1040 }
  const maxWidth = Math.max(MONITOR_MIN_WIDTH, Math.round(fallbackArea.width))
  const maxHeight = Math.max(MONITOR_MIN_HEIGHT, Math.round(fallbackArea.height))

  const rawWidth = typeof bounds?.width === 'number' && Number.isFinite(bounds.width) && bounds.width > 0
    ? Math.round(bounds.width)
    : MONITOR_DEFAULT_WIDTH
  const rawHeight = typeof bounds?.height === 'number' && Number.isFinite(bounds.height) && bounds.height > 0
    ? Math.round(bounds.height)
    : MONITOR_DEFAULT_HEIGHT

  const width = Math.min(Math.max(MONITOR_MIN_WIDTH, rawWidth), maxWidth)
  const height = Math.min(Math.max(MONITOR_MIN_HEIGHT, rawHeight), maxHeight)

  if (
    typeof bounds?.x === 'number'
    && Number.isFinite(bounds.x)
    && typeof bounds?.y === 'number'
    && Number.isFinite(bounds.y)
  ) {
    const candidate: MonitorBounds = {
      width,
      height,
      x: Math.round(bounds.x),
      y: Math.round(bounds.y),
    }
    if (displays.some((display) => intersectsEnough(candidate, display.workArea))) {
      return candidate
    }
  }

  return {
    width,
    height,
    x: Math.max(Math.round(fallbackArea.x), Math.round(fallbackArea.x + fallbackArea.width - width - MONITOR_MARGIN)),
    y: Math.max(Math.round(fallbackArea.y), Math.round(fallbackArea.y + fallbackArea.height - height - MONITOR_MARGIN)),
  }
}

export function loadMonitorWindowState(
  filePath: string,
  displays: DisplayArea[],
  mainWorkArea?: DisplayArea['workArea'],
): MonitorBounds {
  try {
    const raw = fs.readFileSync(filePath, 'utf8')
    const parsed = JSON.parse(raw) as Partial<MonitorBounds>
    return clampMonitorBounds(parsed, displays, mainWorkArea)
  } catch {
    return clampMonitorBounds(null, displays, mainWorkArea)
  }
}

export function saveMonitorWindowState(filePath: string, bounds: Partial<MonitorBounds>): void {
  try {
    if (
      typeof bounds.width !== 'number'
      || !Number.isFinite(bounds.width)
      || typeof bounds.height !== 'number'
      || !Number.isFinite(bounds.height)
      || typeof bounds.x !== 'number'
      || !Number.isFinite(bounds.x)
      || typeof bounds.y !== 'number'
      || !Number.isFinite(bounds.y)
    ) {
      return
    }
    fs.mkdirSync(path.dirname(filePath), { recursive: true })
    const normalized: MonitorBounds = {
      width: Math.max(MONITOR_MIN_WIDTH, Math.round(bounds.width)),
      height: Math.max(MONITOR_MIN_HEIGHT, Math.round(bounds.height)),
      x: Math.round(bounds.x),
      y: Math.round(bounds.y),
    }
    fs.writeFileSync(filePath, JSON.stringify(normalized, null, 2), 'utf8')
  } catch {
    /* 写入监看小窗位置失败不影响关闭流程 */
  }
}

/** 仅放行同源前端页面的 getDisplayMedia 请求，按调用方提前选定的屏幕直接授权。 */
export function createDisplayMediaHandler(deps: DisplayMediaHandlerDeps) {
  return (
    request: DisplayMediaRequestLike,
    callback: (streams: { video: DesktopCapturerSource } | null) => void,
  ): void => {
    const frame = request.frame
    const appUrl = deps.getAppUrl()
    if (!frame || !appUrl) {
      callback(null)
      return
    }

    const originUrl = frame.url || request.securityOrigin
    if (!originUrl || originUrl.startsWith('file:') || !isAllowedAppUrl(originUrl, appUrl, deps.loadingPagePath)) {
      callback(null)
      return
    }

    const wc = deps.getWebContentsFromFrame(frame)
    if (!wc) {
      callback(null)
      return
    }

    const displayId = deps.getSelectedDisplayId(wc.id)
    if (!displayId) {
      callback(null)
      return
    }

    deps.getScreenSources()
      .then((sources) => {
        const matched = matchCaptureSource(sources, displayId)
        if (!matched) {
          callback(null)
          return
        }
        callback({ video: matched })
      })
      .catch(() => {
        callback(null)
      })
  }
}

/** 在 Electron 主进程注册屏幕枚举、媒体授权和置顶小窗管理。 */
export function registerMonitor(deps: RegisterMonitorDeps): MonitorController {
  const {
    BrowserWindow,
    desktopCapturer,
    ipcMain,
    screen,
    session,
    webContents,
    getMainWindow,
    getAppUrl,
    loadingPagePath,
    preloadPath,
    iconPath,
    stateFile,
    isSmokeTest,
  } = deps

  const selectedByWebContents = new Map<number, string>()
  const trackedCleanup = new Set<number>()
  let monitorWindow: ElectronBrowserWindow | null = null
  let lastMainDisplayId: number | null = null

  const getMainWindowDisplay = () => {
    const mainWin = getMainWindow()
    const displays = screen.getAllDisplays()
    if (!mainWin || mainWin.isDestroyed()) {
      return screen.getPrimaryDisplay() ?? displays[0]
    }
    return screen.getDisplayMatching(mainWin.getBounds())
  }

  const getSnapshot = (): MonitorDisplay[] => {
    const displays = screen.getAllDisplays()
    const primaryId = screen.getPrimaryDisplay()?.id ?? null
    const mainDisplay = getMainWindowDisplay()
    lastMainDisplayId = mainDisplay?.id ?? null
    return describeDisplays(displays, primaryId, lastMainDisplayId)
  }

  const sendToWindow = (win: ElectronBrowserWindow | null, channel: string, payload: unknown): void => {
    if (win && !win.isDestroyed()) {
      win.webContents.send(channel, payload)
    }
  }

  const notifyDisplays = (): void => {
    const snapshot = getSnapshot()
    sendToWindow(getMainWindow(), 'monitor:displaysChanged', snapshot)
    sendToWindow(monitorWindow, 'monitor:displaysChanged', snapshot)
  }

  const notifyWindowState = (): void => {
    const open = Boolean(monitorWindow && !monitorWindow.isDestroyed())
    sendToWindow(getMainWindow(), 'monitor:windowChanged', open)
  }

  const closeWindow = (): void => {
    if (monitorWindow && !monitorWindow.isDestroyed()) {
      monitorWindow.close()
    }
  }

  const openWindow = (): boolean => {
    const appUrl = getAppUrl()
    if (!appUrl) return false

    if (monitorWindow && !monitorWindow.isDestroyed()) {
      if (monitorWindow.isMinimized()) monitorWindow.restore()
      monitorWindow.focus()
      notifyWindowState()
      return true
    }

    const displays = screen.getAllDisplays()
    const mainWorkArea = getMainWindowDisplay()?.workArea
    const initialBounds = loadMonitorWindowState(stateFile, displays, mainWorkArea)

    const win = new BrowserWindow({
      width: initialBounds.width,
      height: initialBounds.height,
      x: initialBounds.x,
      y: initialBounds.y,
      minWidth: MONITOR_MIN_WIDTH,
      minHeight: MONITOR_MIN_HEIGHT,
      frame: false,
      alwaysOnTop: true,
      resizable: true,
      minimizable: false,
      maximizable: false,
      show: false,
      backgroundColor: '#0a0918',
      title: '第二屏监看',
      icon: fs.existsSync(iconPath) ? iconPath : undefined,
      webPreferences: {
        preload: preloadPath,
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    })

    // 高于普通置顶级别，确保在 PowerPoint 全屏放映时也能看到；开启内容保护防止拖到副屏后形成无限镜像。
    win.setAlwaysOnTop(true, 'screen-saver')
    win.setAspectRatio(16 / 9)
    win.setContentProtection(true)

    const persistBounds = () => {
      if (isSmokeTest || win.isDestroyed()) return
      saveMonitorWindowState(stateFile, win.getBounds())
    }

    win.on('move', persistBounds)
    win.on('resize', persistBounds)
    win.on('close', persistBounds)
    win.on('closed', () => {
      if (monitorWindow === win) {
        monitorWindow = null
        notifyWindowState()
      }
    })
    win.once('ready-to-show', () => {
      if (!isSmokeTest && !win.isDestroyed()) {
        win.show()
      }
    })

    win.webContents.on('will-navigate', (event, targetUrl) => {
      if (!isAllowedAppUrl(targetUrl, getAppUrl(), loadingPagePath)) {
        event.preventDefault()
      }
    })
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))

    monitorWindow = win
    notifyWindowState()
    void win.loadURL(new URL('#/monitor', appUrl).toString())
    return true
  }

  session.defaultSession.setDisplayMediaRequestHandler(
    createDisplayMediaHandler({
      getAppUrl,
      loadingPagePath,
      getSelectedDisplayId: (wcId) => selectedByWebContents.get(wcId),
      getScreenSources: () => desktopCapturer.getSources({
        types: ['screen'],
        thumbnailSize: { width: 0, height: 0 },
      }),
      getWebContentsFromFrame: (frame) => webContents.fromFrame(frame),
    }),
  )

  ipcMain.handle('monitor:listDisplays', () => {
    notifyWindowState()
    return getSnapshot()
  })
  ipcMain.handle('monitor:select', (event, rawDisplayId: unknown) => {
    const sender = event.sender
    const senderId = sender.id
    if (!trackedCleanup.has(senderId)) {
      trackedCleanup.add(senderId)
      sender.once('destroyed', () => {
        selectedByWebContents.delete(senderId)
        trackedCleanup.delete(senderId)
      })
    }

    const displayId = typeof rawDisplayId === 'string' ? rawDisplayId.trim() : ''
    if (!displayId) {
      selectedByWebContents.delete(senderId)
      return false
    }

    const exists = screen.getAllDisplays().some((display) => String(display.id) === displayId)
    if (!exists) {
      return false
    }
    selectedByWebContents.set(senderId, displayId)
    return true
  })
  ipcMain.handle('monitor:openWindow', () => openWindow())
  ipcMain.handle('monitor:closeWindow', () => {
    closeWindow()
  })

  const onDisplaysChanged = () => {
    notifyDisplays()
  }
  screen.on('display-added', onDisplaysChanged)
  screen.on('display-removed', onDisplaysChanged)
  screen.on('display-metrics-changed', onDisplaysChanged)

  return {
    closeWindow,
    notifyMainWindowMoved: () => {
      const nextMainId = getMainWindowDisplay()?.id ?? null
      if (nextMainId !== lastMainDisplayId) {
        notifyDisplays()
      }
    },
    notifyWindowState,
    dispose: () => {
      screen.removeListener('display-added', onDisplaysChanged)
      screen.removeListener('display-removed', onDisplaysChanged)
      screen.removeListener('display-metrics-changed', onDisplaysChanged)
      ipcMain.removeHandler('monitor:listDisplays')
      ipcMain.removeHandler('monitor:select')
      ipcMain.removeHandler('monitor:openWindow')
      ipcMain.removeHandler('monitor:closeWindow')
      session.defaultSession.setDisplayMediaRequestHandler(null)
      selectedByWebContents.clear()
      trackedCleanup.clear()
      closeWindow()
    },
  }
}

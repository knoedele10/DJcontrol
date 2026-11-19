/// <reference types="vite/client" />

interface MonitorDisplay {
  id: string
  label: string
  width: number
  height: number
  scaleFactor: number
  isPrimary: boolean
  isMainWindow: boolean
}

interface DesktopMonitorBridge {
  listDisplays: () => Promise<MonitorDisplay[]>
  select: (displayId: string | null) => Promise<boolean>
  openWindow: () => Promise<boolean>
  closeWindow: () => Promise<void>
  onDisplaysChanged: (listener: (displays: MonitorDisplay[]) => void) => () => void
  onWindowChanged: (listener: (open: boolean) => void) => () => void
}

interface DesktopBridge {
  isElectron: true
  platform: string
  versions: {
    electron: string
    node: string
    chrome: string
  }
  getStatus: () => Promise<unknown>
  retryStart: () => Promise<void>
  restartBackend: () => Promise<void>
  openLogsDir: () => Promise<void>
  toggleFullscreen: () => Promise<boolean>
  onStatus: (listener: (status: unknown) => void) => () => void
  monitor?: DesktopMonitorBridge
}

interface Window {
  desktopApp?: DesktopBridge
}

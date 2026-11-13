/// <reference types="vite/client" />

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
}

interface Window {
  desktopApp?: DesktopBridge
}

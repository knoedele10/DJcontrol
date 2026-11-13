import { contextBridge, ipcRenderer } from 'electron'

export interface DesktopBridge {
  isElectron: true
  platform: NodeJS.Platform
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

const bridge: DesktopBridge = {
  isElectron: true,
  platform: process.platform,
  versions: {
    electron: process.versions.electron ?? '',
    node: process.versions.node ?? '',
    chrome: process.versions.chrome ?? '',
  },
  getStatus: () => ipcRenderer.invoke('desktop:getStatus'),
  retryStart: () => ipcRenderer.invoke('desktop:retryStart'),
  restartBackend: () => ipcRenderer.invoke('desktop:restartBackend'),
  openLogsDir: () => ipcRenderer.invoke('desktop:openLogsDir'),
  toggleFullscreen: () => ipcRenderer.invoke('desktop:toggleFullscreen'),
  onStatus: (listener) => {
    const wrapped = (_event: Electron.IpcRendererEvent, status: unknown) => listener(status)
    ipcRenderer.on('desktop:status', wrapped)
    return () => ipcRenderer.removeListener('desktop:status', wrapped)
  },
}

contextBridge.exposeInMainWorld('desktopApp', bridge)

import { contextBridge, ipcRenderer } from 'electron'
import type { MonitorDisplay } from './Monitor.js' with { 'resolution-mode': 'import' }

export interface DesktopMonitorBridge {
  listDisplays: () => Promise<MonitorDisplay[]>
  select: (displayId: string | null) => Promise<boolean>
  openWindow: () => Promise<boolean>
  closeWindow: () => Promise<void>
  onDisplaysChanged: (listener: (displays: MonitorDisplay[]) => void) => () => void
  onWindowChanged: (listener: (open: boolean) => void) => () => void
}

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
  monitor: DesktopMonitorBridge
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
  monitor: {
    listDisplays: () => ipcRenderer.invoke('monitor:listDisplays'),
    select: (displayId) => ipcRenderer.invoke('monitor:select', displayId),
    openWindow: () => ipcRenderer.invoke('monitor:openWindow'),
    closeWindow: () => ipcRenderer.invoke('monitor:closeWindow'),
    onDisplaysChanged: (listener) => {
      const wrapped = (_event: Electron.IpcRendererEvent, displays: MonitorDisplay[]) => listener(displays)
      ipcRenderer.on('monitor:displaysChanged', wrapped)
      return () => ipcRenderer.removeListener('monitor:displaysChanged', wrapped)
    },
    onWindowChanged: (listener) => {
      const wrapped = (_event: Electron.IpcRendererEvent, open: boolean) => listener(open)
      ipcRenderer.on('monitor:windowChanged', wrapped)
      return () => ipcRenderer.removeListener('monitor:windowChanged', wrapped)
    },
  },
}

contextBridge.exposeInMainWorld('desktopApp', bridge)

import { Menu, type BrowserWindow, type MenuItemConstructorOptions } from 'electron'

export interface MenuActions {
  getWindow: () => BrowserWindow | null
  onRestartBackend: () => void
  onOpenLogs: () => void
  onOpenDashboard: () => void
  onOpenSettings: () => void
}

/** 极简中文应用菜单：默认自动隐藏保持舞台沉浸感，同时保留 F11 全屏、缩放与排障入口。 */
export function installApplicationMenu(actions: MenuActions): void {
  const template: MenuItemConstructorOptions[] = [
    {
      label: '应用',
      submenu: [
        { label: '演出主面板', click: actions.onOpenDashboard },
        { label: '设置与连接诊断', click: actions.onOpenSettings },
        { label: '重启控制引擎', click: actions.onRestartBackend },
        { label: '打开日志目录', click: actions.onOpenLogs },
        { type: 'separator' },
        { label: '退出', role: 'quit' },
      ],
    },
    {
      label: '编辑',
      submenu: [
        { label: '撤销', role: 'undo' },
        { label: '重做', role: 'redo' },
        { type: 'separator' },
        { label: '剪切', role: 'cut' },
        { label: '复制', role: 'copy' },
        { label: '粘贴', role: 'paste' },
        { label: '全选', role: 'selectAll' },
      ],
    },
    {
      label: '视图',
      submenu: [
        {
          label: '切换全屏',
          accelerator: 'F11',
          click: () => {
            const win = actions.getWindow()
            if (win) win.setFullScreen(!win.isFullScreen())
          },
        },
        { label: '刷新界面', accelerator: 'CmdOrCtrl+R', role: 'reload' },
        { label: '强制刷新', accelerator: 'CmdOrCtrl+Shift+R', role: 'forceReload' },
        { type: 'separator' },
        { label: '放大界面', accelerator: 'CmdOrCtrl+=', role: 'zoomIn' },
        { label: '缩小界面', accelerator: 'CmdOrCtrl+-', role: 'zoomOut' },
        { label: '重置缩放', accelerator: 'CmdOrCtrl+0', role: 'resetZoom' },
        { type: 'separator' },
        {
          label: '开发者工具',
          accelerator: 'F12',
          click: () => {
            const win = actions.getWindow()
            if (win) win.webContents.toggleDevTools()
          },
        },
      ],
    },
  ]

  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

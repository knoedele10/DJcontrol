import fs from 'node:fs'
import path from 'node:path'

export interface WindowBounds {
  width: number
  height: number
  x?: number
  y?: number
}

export interface PersistedWindowState extends WindowBounds {
  maximized: boolean
}

export interface DisplayArea {
  workArea: { x: number; y: number; width: number; height: number }
}

const DEFAULT_WIDTH = 1440
const DEFAULT_HEIGHT = 900
const MIN_WIDTH = 1024
const MIN_HEIGHT = 680

function intersectsEnough(bounds: WindowBounds, area: DisplayArea['workArea']): boolean {
  if (bounds.x === undefined || bounds.y === undefined) return false
  const overlapX = Math.min(bounds.x + bounds.width, area.x + area.width) - Math.max(bounds.x, area.x)
  const overlapY = Math.min(bounds.y + bounds.height, area.y + area.height) - Math.max(bounds.y, area.y)
  return overlapX >= 100 && overlapY >= 100
}

/** 读取上次窗口大小和位置；多屏断开或坐标失效时自动回退居中默认尺寸。 */
export function loadWindowState(filePath: string, displays: DisplayArea[]): PersistedWindowState {
  const fallback: PersistedWindowState = { width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT, maximized: false }
  try {
    const raw = fs.readFileSync(filePath, 'utf8')
    const parsed = JSON.parse(raw) as Partial<PersistedWindowState>
    const width = typeof parsed.width === 'number' && Number.isFinite(parsed.width)
      ? Math.max(MIN_WIDTH, Math.round(parsed.width))
      : DEFAULT_WIDTH
    const height = typeof parsed.height === 'number' && Number.isFinite(parsed.height)
      ? Math.max(MIN_HEIGHT, Math.round(parsed.height))
      : DEFAULT_HEIGHT
    const maximized = Boolean(parsed.maximized)
    const candidate: WindowBounds = {
      width,
      height,
      x: typeof parsed.x === 'number' && Number.isFinite(parsed.x) ? Math.round(parsed.x) : undefined,
      y: typeof parsed.y === 'number' && Number.isFinite(parsed.y) ? Math.round(parsed.y) : undefined,
    }
    const visible = displays.some((display) => intersectsEnough(candidate, display.workArea))
    return visible ? { ...candidate, maximized } : { width, height, maximized }
  } catch {
    return fallback
  }
}

export function saveWindowState(filePath: string, bounds: WindowBounds, maximized: boolean): void {
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true })
    const state: PersistedWindowState = {
      width: Math.max(MIN_WIDTH, Math.round(bounds.width)),
      height: Math.max(MIN_HEIGHT, Math.round(bounds.height)),
      x: bounds.x !== undefined ? Math.round(bounds.x) : undefined,
      y: bounds.y !== undefined ? Math.round(bounds.y) : undefined,
      maximized,
    }
    fs.writeFileSync(filePath, JSON.stringify(state, null, 2), 'utf8')
  } catch {
    /* 写入窗口状态失败不影响关闭流程 */
  }
}

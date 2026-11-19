import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type MonitorMode = 'preview' | 'live'

export const MONITOR_DISPLAY_STORAGE_KEY = 'kugou.monitor.displayId'

function getMonitorBridge(): DesktopMonitorBridge | undefined {
  return globalThis.window?.desktopApp?.monitor
}

function readSavedDisplayId(): string | null {
  try {
    const raw = globalThis.localStorage?.getItem(MONITOR_DISPLAY_STORAGE_KEY)
    return raw && raw.trim() ? raw.trim() : null
  } catch {
    return null
  }
}

function writeSavedDisplayId(displayId: string | null): void {
  try {
    if (displayId) {
      globalThis.localStorage?.setItem(MONITOR_DISPLAY_STORAGE_KEY, displayId)
    } else {
      globalThis.localStorage?.removeItem(MONITOR_DISPLAY_STORAGE_KEY)
    }
  } catch {
    // 隐私模式或测试环境禁用 localStorage 时降级为仅内存记忆。
  }
}

// 第二屏实时监看状态：维护扩展屏列表、记忆选屏、模式切换与置顶小窗单一捕获源协调。
export const useMonitorStore = defineStore('monitor', () => {
  const supported = ref(Boolean(getMonitorBridge()))
  const displays = ref<MonitorDisplay[]>([])
  const displaysLoaded = ref(false)
  let preferredDisplayId = readSavedDisplayId()
  const selectedDisplayId = ref<string | null>(preferredDisplayId)
  const mode = ref<MonitorMode>('preview')
  const windowOpen = ref(false)

  let initPromise: Promise<void> | null = null
  const disposers: Array<() => void> = []

  const hasSecondScreen = computed(() => displays.value.length >= 2)
  const selectedDisplay = computed(
    () => displays.value.find((display) => display.id === selectedDisplayId.value) ?? null,
  )
  const unavailableReason = computed<string | null>(() => {
    if (!supported.value) return '仅在桌面版支持第二屏实时监看'
    if (!displaysLoaded.value) return '正在检测显示器…'
    if (displays.value.length < 2) {
      return '未检测到第二块屏幕（请确认系统显示设置已设为「扩展」而非「复制」）'
    }
    if (!selectedDisplay.value) return '请选择要监看的屏幕'
    return null
  })

  function applyDisplays(nextDisplays: MonitorDisplay[]): void {
    displays.value = nextDisplays
    displaysLoaded.value = true

    if (nextDisplays.length === 0) {
      selectedDisplayId.value = null
      return
    }

    // 优先恢复用户显式记住的显示器；不覆盖 localStorage，以便断线重连后自动切回原屏幕。
    if (preferredDisplayId && nextDisplays.some((display) => display.id === preferredDisplayId)) {
      selectedDisplayId.value = preferredDisplayId
      return
    }

    const fallback = nextDisplays.find((display) => !display.isMainWindow) ?? nextDisplays[0]
    selectedDisplayId.value = fallback?.id ?? null
  }

  async function init(): Promise<void> {
    const bridge = getMonitorBridge()
    supported.value = Boolean(bridge)
    if (!bridge) {
      displays.value = []
      displaysLoaded.value = true
      return
    }

    if (initPromise) return initPromise

    disposers.push(
      bridge.onDisplaysChanged((next) => {
        applyDisplays(next)
      }),
    )
    disposers.push(
      bridge.onWindowChanged((open) => {
        windowOpen.value = open
      }),
    )

    if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
      const onStorage = (event: StorageEvent) => {
        if (event.key !== MONITOR_DISPLAY_STORAGE_KEY) return
        preferredDisplayId = event.newValue?.trim() || null
        if (displaysLoaded.value) {
          applyDisplays(displays.value)
        } else {
          selectedDisplayId.value = preferredDisplayId
        }
      }
      window.addEventListener('storage', onStorage)
      disposers.push(() => window.removeEventListener('storage', onStorage))
    }

    initPromise = bridge
      .listDisplays()
      .then((list) => {
        applyDisplays(list)
      })
      .catch(() => {
        displaysLoaded.value = true
      })

    return initPromise
  }

  function dispose(): void {
    while (disposers.length > 0) {
      const stop = disposers.pop()
      stop?.()
    }
    initPromise = null
  }

  function selectDisplay(displayId: string | null): void {
    const normalized = displayId?.trim() || null
    preferredDisplayId = normalized
    writeSavedDisplayId(normalized)
    if (displaysLoaded.value) {
      applyDisplays(displays.value)
    } else {
      selectedDisplayId.value = normalized
    }
  }

  function setMode(nextMode: MonitorMode): void {
    mode.value = nextMode
  }

  async function openPopup(): Promise<boolean> {
    const bridge = getMonitorBridge()
    if (!bridge || !hasSecondScreen.value) return false
    const previousMode = mode.value
    const previousOpen = windowOpen.value
    // 先将主面板切换为暂停捕获状态再弹小窗，确保全应用同一时刻仅一条屏幕流在采集。
    mode.value = 'live'
    windowOpen.value = true
    try {
      const opened = await bridge.openWindow()
      if (!opened) {
        windowOpen.value = previousOpen
        mode.value = previousMode
      }
      return opened
    } catch {
      windowOpen.value = previousOpen
      mode.value = previousMode
      return false
    }
  }

  async function closePopup(): Promise<void> {
    const bridge = getMonitorBridge()
    windowOpen.value = false
    if (!bridge) return
    await bridge.closeWindow()
  }

  return {
    supported,
    displays,
    displaysLoaded,
    selectedDisplayId,
    mode,
    windowOpen,
    hasSecondScreen,
    selectedDisplay,
    unavailableReason,
    applyDisplays,
    init,
    dispose,
    selectDisplay,
    setMode,
    openPopup,
    closePopup,
  }
})

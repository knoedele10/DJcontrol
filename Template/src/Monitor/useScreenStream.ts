import { onScopeDispose, ref, shallowRef, toValue, watch, type MaybeRefOrGetter } from 'vue'

export type ScreenStreamStatus = 'idle' | 'connecting' | 'streaming' | 'ended' | 'error'

export const SCREEN_CAPTURE_CONSTRAINTS: DisplayMediaStreamOptions = {
  video: {
    frameRate: { max: 30 },
    width: { max: 1920 },
    height: { max: 1080 },
  },
  audio: false,
}

export interface UseScreenStreamOptions {
  active: MaybeRefOrGetter<boolean>
  displayId: MaybeRefOrGetter<string | null>
  selectDisplay?: (displayId: string | null) => Promise<boolean>
  getDisplayMedia?: (constraints: DisplayMediaStreamOptions) => Promise<MediaStream>
}

function stopMediaStream(mediaStream: MediaStream | null): void {
  if (!mediaStream) return
  for (const track of mediaStream.getTracks()) {
    // 主动停止前先摘除 onended，避免切屏、弹小窗或卸载时误报“信号断开”。
    track.onended = null
    track.stop()
  }
}

function formatCaptureError(cause: unknown): string {
  if (cause instanceof Error) {
    if (cause.name === 'NotAllowedError' || cause.name === 'AbortError') {
      return '屏幕捕获请求被拒绝，请确认当前页位于主应用且已选择可用屏幕'
    }
    if (cause.name === 'NotFoundError') {
      return '未找到可捕获的扩展屏幕'
    }
    return cause.message ? `屏幕捕获失败：${cause.message}` : '屏幕捕获失败'
  }
  return '屏幕捕获失败'
}

/**
 * 封装桌面端第二屏捕获流：在调用 getDisplayMedia 前先通过主进程绑定目标显示器，
 * 并处理异步竞态取消、手动停流、轨道断开提示与卸载清理。
 */
export function useScreenStream(options: UseScreenStreamOptions) {
  const videoEl = shallowRef<HTMLVideoElement | null>(null)
  const stream = shallowRef<MediaStream | null>(null)
  const status = ref<ScreenStreamStatus>('idle')
  const error = ref<string | null>(null)

  let requestId = 0
  let disposed = false

  function detachVideo(element: HTMLVideoElement | null): void {
    if (!element) return
    if ('srcObject' in element) {
      element.srcObject = null
    }
  }

  function stop(nextStatus: 'idle' | 'ended' | 'error' = 'idle', reason: string | null = null): void {
    requestId += 1
    const current = stream.value
    stream.value = null
    stopMediaStream(current)
    detachVideo(videoEl.value)
    status.value = nextStatus
    error.value = reason
  }

  async function start(targetDisplayId: string): Promise<void> {
    const selectFn =
      options.selectDisplay ??
      ((id: string | null) => globalThis.window?.desktopApp?.monitor?.select(id) ?? Promise.resolve(false))
    const captureFn =
      options.getDisplayMedia ??
      ((constraints: DisplayMediaStreamOptions) => {
        const mediaDevices = globalThis.navigator?.mediaDevices
        if (!mediaDevices?.getDisplayMedia) {
          return Promise.reject(new Error('当前环境不支持屏幕捕获'))
        }
        return mediaDevices.getDisplayMedia(constraints)
      })

    requestId += 1
    const myRequest = requestId

    const previous = stream.value
    stream.value = null
    stopMediaStream(previous)
    detachVideo(videoEl.value)

    status.value = 'connecting'
    error.value = null

    const isStale = () =>
      disposed ||
      myRequest !== requestId ||
      !toValue(options.active) ||
      toValue(options.displayId) !== targetDisplayId

    try {
      const selected = await selectFn(targetDisplayId)
      if (isStale()) return
      if (!selected) {
        status.value = 'error'
        error.value = '无法锁定目标屏幕，请刷新显示器列表后重试'
        return
      }

      const nextStream = await captureFn(SCREEN_CAPTURE_CONSTRAINTS)
      if (isStale()) {
        stopMediaStream(nextStream)
        return
      }

      const videoTrack = nextStream.getVideoTracks()[0]
      if (!videoTrack) {
        stopMediaStream(nextStream)
        status.value = 'error'
        error.value = '未获取到视频捕获轨道'
        return
      }

      videoTrack.onended = () => {
        if (disposed || stream.value !== nextStream) return
        stream.value = null
        detachVideo(videoEl.value)
        status.value = 'ended'
        error.value = '第二块屏幕信号已断开（显示器已移除或系统停止共享）'
      }

      stream.value = nextStream
      status.value = 'streaming'
      error.value = null
    } catch (cause) {
      if (isStale()) return
      status.value = 'error'
      error.value = formatCaptureError(cause)
    }
  }

  function retry(): void {
    const targetId = toValue(options.displayId)
    if (!toValue(options.active) || !targetId) return
    void start(targetId)
  }

  watch(
    [videoEl, stream],
    ([el, currentStream], previous) => {
      const prevEl = previous?.[0]
      if (prevEl && prevEl !== el) {
        detachVideo(prevEl)
      }
      if (!el) return
      el.srcObject = currentStream
      if (currentStream && typeof el.play === 'function') {
        void Promise.resolve(el.play()).catch(() => {})
      }
    },
    { flush: 'post' },
  )

  watch(
    [() => toValue(options.active), () => toValue(options.displayId)],
    ([isActive, targetDisplayId]) => {
      if (!isActive || !targetDisplayId) {
        stop('idle', null)
        return
      }
      if (typeof globalThis.window === 'undefined' && !options.getDisplayMedia) {
        return
      }
      void start(targetDisplayId)
    },
    { immediate: true },
  )

  onScopeDispose(() => {
    disposed = true
    stop('idle', null)
  })

  return {
    videoEl,
    stream,
    status,
    error,
    stop,
    retry,
  }
}

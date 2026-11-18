import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { BackendConnectionState } from '@/Common/Types'
import { fetchBackendConnection } from '@/Diagnostics/DiagnosticsApi'

// 检查控制链路，独立于播放器命令和 UIA 自检，后端离线时也能快速给出原因。
export const useConnectionStore = defineStore('connection', () => {
  const state = ref<BackendConnectionState | null>(null)
  const checking = ref(false)
  let timer: ReturnType<typeof setInterval> | undefined
  let pending: Promise<void> | undefined
  function check(): Promise<void> {
    if (pending) return pending
    checking.value = true
    pending = (async () => {
      try { state.value = await fetchBackendConnection() }
      catch (cause) {
        state.value = { mode: 'unknown', backend_connected: false, upstream: null,
          message: cause instanceof Error ? cause.message : '控制服务连接检查失败' }
      } finally { checking.value = false; pending = undefined }
    })()
    return pending
  }
  function start() {
    if (timer !== undefined) return
    void check()
    timer = setInterval(() => { void check() }, 10000)
  }
  function stop() { if (timer !== undefined) clearInterval(timer); timer = undefined }
  return { state, checking, check, start, stop }
})

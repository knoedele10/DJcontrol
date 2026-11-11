// M3 播放状态：由后端 PlayerUpdate 驱动，前端不再自己推进进度或写已播记录。
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { Capability, CommandLog, CommandStatus, PlayerCommand, PlayerUpdate } from '@/Common/Types'
import { fetchPlayerState, sendPlayerCommand, setAutoNext, subscribePlayer } from '@/Playback/PlayerApi'
import { useLibraryStore } from '@/Library/LibraryStore'
import { useQueueStore } from '@/Queue/QueueStore'

const message = (cause: unknown, fallback: string) => (cause instanceof Error ? cause.message : fallback)

export const usePlaybackStore = defineStore('playback', () => {
  const library = useLibraryStore()
  const queue = useQueueStore()
  const controller = ref<'mock' | 'kugou'>('mock')
  const title = ref('')
  const artist = ref('')
  const capabilities = ref<Capability[]>([])
  const can = (name: string) => capabilities.value.some(c => c.name === name && c.supported)
  const busy = computed(() => command.value.status === 'pending')
  const currentId = ref<number | null>(null)
  const playing = ref(false)
  const position = ref(0)
  const duration = ref(0)
  const autoNext = ref(true)
  const autoNextPending = ref(false)
  const connected = ref(false)
  const error = ref('')
  const command = ref<CommandLog>({ text: '等待播放器状态', status: 'idle' })
  const current = computed(() => (currentId.value === null ? null : library.songById(currentId.value) ?? null))
  const nearEnd = computed(() => duration.value > 0 && duration.value - position.value <= 15)
  let unsubscribe: (() => void) | undefined
  let lastRevision = -1

  function report(text: string, status: CommandStatus) { command.value = { text, status } }

  /** HTTP 响应和 WebSocket 推送都走这里；比已处理的 revision 旧的直接丢弃。 */
  function applyUpdate(update: PlayerUpdate) {
    if (update.revision < lastRevision) return
    lastRevision = update.revision
    const state = update.state
    controller.value = state.controller
    title.value = state.title
    artist.value = state.artist
    capabilities.value = state.capabilities ?? []
    currentId.value = state.song_id
    playing.value = state.status === 'playing'
    position.value = state.position ?? 0
    duration.value = state.duration ?? 0
    // 开关请求还没返回时，不让轮询推送把勾选状态改回去
    if (!autoNextPending.value) autoNext.value = state.auto_next
    connected.value = state.connected
    error.value = state.error ?? ''
    queue.applyRemoteState(state)
  }

  async function setAutoNextEnabled(enabled: boolean) {
    if (autoNextPending.value) return
    autoNextPending.value = true
    autoNext.value = enabled
    const label = enabled ? '开启自动接歌' : '关闭自动接歌'
    report(label, 'pending')
    try {
      const update = await setAutoNext(enabled)
      autoNextPending.value = false
      applyUpdate(update)
      report(label, 'verified')
    } catch (cause) {
      autoNextPending.value = false
      autoNext.value = !enabled
      report(message(cause, '自动接歌设置失败'), 'failed')
    }
  }

  function startSync() {
    if (unsubscribe) return
    void fetchPlayerState().then(applyUpdate).catch((cause) => {
      connected.value = false
      error.value = message(cause, '播放器服务未连接')
    })
    unsubscribe = subscribePlayer((update) => applyUpdate(update), (open) => {
      connected.value = open
      if (open) lastRevision = -1 // 后端重启后 revision 从 0 重新开始
      else error.value = '播放器服务连接中断，正在重连…'
    })
  }
  function stopSync() { unsubscribe?.(); unsubscribe = undefined }

  /** 跟踪一个异步操作：底部状态栏先显示"发送中"，完成后改为"已核验"或"失败 + 原因"。 */
  async function track(label: string, action: () => Promise<unknown>): Promise<boolean> {
    report(label, 'pending')
    try {
      await action()
      report(label, 'verified')
      return true
    } catch (cause) {
      report(message(cause, `${label}失败`), 'failed')
      return false
    }
  }

  async function perform(request: PlayerCommand, label: string) {
    if (busy.value) return
    report(label, 'pending')
    try {
      const update = await sendPlayerCommand(request)
      applyUpdate(update)
      if (update.state.error || update.state.status === 'unknown') throw new Error(update.state.error ?? '命令已发送，但未能核验状态')
      report(`${label} · ${update.state.title || '无当前歌曲'}`, 'verified')
    } catch (cause) {
      error.value = message(cause, '播放器命令失败')
      report(error.value, 'failed')
    }
  }

  // 以后端实际状态为准：未连接时请求会失败并在状态栏显示原因，不在本地假装开始播放。
  const play = (songId: number) => perform({ action: 'play', song_id: songId }, `播放：${library.songById(songId)?.title ?? '歌曲'}`)
  const playNext = () => perform({ action: 'next_in_queue' }, '播队列下一首')
  const mediaNext = () => perform({ action: 'media_next' }, '酷狗下一首')
  const mediaPrevious = () => perform({ action: 'media_previous' }, '酷狗上一首')
  const toggle = () => perform({ action: 'toggle' }, playing.value ? '暂停播放' : '继续播放')
  const previous = () => perform({ action: 'previous' }, '上一首')
  const seek = (ratio: number) => {
    if (!duration.value) return
    return perform({ action: 'seek', position: Math.max(0, Math.min(1, ratio)) * duration.value }, '调整播放进度')
  }
  // 保留旧组件调用点；进度现在由后端轮询推进。
  const tick = () => undefined
  /** 普通提示（不是命令），状态栏只显示文字、不带"发送中/已核验"标记。 */
  const log = (text: string) => report(text, 'idle')

  return {
    controller, title, artist, capabilities, can, busy, mediaNext, mediaPrevious, currentId, current, playing, position, duration, nearEnd, autoNext, autoNextPending, connected, error, command,
    startSync, stopSync, applyUpdate, report, log, track, setAutoNextEnabled, play, playNext, toggle, previous, seek, tick,
  }
})

// M3 队列和已播记录：以后端 PlayerUpdate 为唯一事实来源。
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { HistoryItem, PlayerState, PlayerUpdate, QueueItem, Song } from '@/Common/Types'
import { clearQueue, enqueuePlayer, orderQueue, removeQueueItem } from '@/Playback/PlayerApi'
import { useLibraryStore } from '@/Library/LibraryStore'
import { usePlaybackStore } from '@/Playback/PlaybackStore'

export interface QueueRow { item: QueueItem; song: Song }

export const useQueueStore = defineStore('queue', () => {
  const library = useLibraryStore()
  const items = ref<QueueItem[]>([])
  const history = ref<HistoryItem[]>([])
  const connected = ref(false)
  const error = ref('')

  const rows = computed<QueueRow[]>(() => items.value.flatMap((item) => {
    const song = library.songById(item.song_id)
    return song ? [{ item, song }] : []
  }))
  const nextSongId = computed(() => rows.value[0]?.song.id ?? null)
  const totalSeconds = computed(() => rows.value.reduce((total, row) => total + row.song.duration, 0))
  const isPlayed = (songId: number) => history.value.some((item) => item.song_id === songId)
  const positionOf = (songId: number) => rows.value.findIndex((row) => row.song.id === songId)

  /** 只由 playback store 调用：它负责按 revision 丢弃过期状态后再分发到这里。 */
  function applyRemoteState(state: PlayerState) {
    items.value = state.queue
    history.value = state.recent_history
    connected.value = state.connected
    error.value = state.error ?? ''
  }

  /**
   * 执行一个队列请求，并把返回的完整状态交给 playback store 统一处理（含 revision 检查）。
   * 失败时抛出，由调用方（playback.track）在底部状态栏显示原因。
   * usePlaybackStore 在函数内调用：两个 store 互相引用，放在顶层会形成初始化循环。
   */
  async function run(request: () => Promise<PlayerUpdate>, fallback: string) {
    try {
      usePlaybackStore().applyUpdate(await request())
      error.value = ''
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : fallback
      throw new Error(error.value)
    }
  }

  const enqueue = (songId: number, front = false) =>
    run(() => enqueuePlayer(songId, front ? 'next' : 'end'), '加入队列失败')
  const remove = (itemId: string) => run(() => removeQueueItem(itemId), '移除队列项失败')
  const clear = () => run(() => clearQueue(), '清空队列失败')
  async function move(itemId: string, delta: -1 | 1) {
    const index = items.value.findIndex((item) => item.id === itemId)
    const target = index + delta
    if (index < 0 || target < 0 || target >= items.value.length) return
    const ids = items.value.map((item) => item.id)
    ;[ids[index], ids[target]] = [ids[target], ids[index]]
    await run(() => orderQueue(ids), '队列排序失败')
  }

  // 播放历史由后端写入；保留这两个兼容方法，旧组件不会再本地重复记录。
  function recordPlayed(_songId: number) { return undefined }
  function popPrevious(): number | null { return null }

  return {
    items, history, rows, nextSongId, totalSeconds, isPlayed, positionOf, connected, error,
    applyRemoteState, enqueue, remove, move, clear, recordPlayed, popPrevious,
  }
})

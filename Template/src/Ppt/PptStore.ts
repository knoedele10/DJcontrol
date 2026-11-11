// PPT 由后端实际状态驱动，面板操作和外部翻页走同一条状态更新路径。
// 页面绑定的歌和「翻页联动音乐」都存在后端，翻页时由后端下达播放，开几个面板窗口都只播一次。
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import type { PptApp, PptCommand, PptSlide, PptUpdate } from '@/Common/Types'
import { connectPpt, importPptBindings, sendPptCommand, setPptBinding, setPptLinkMusic, subscribePpt } from '@/Ppt/PptApi'
import { preloadPptImages } from '@/Ppt/PptPreload'
import { loadJSON, saveJSON } from '@/Common/Storage'
import { useLibraryStore } from '@/Library/LibraryStore'
import { usePlaybackStore } from '@/Playback/PlaybackStore'

const OLD_BIND_KEY = 'kgdash-ppt-bindings-v2' // 旧版把绑定存在浏览器里，首次连上后端时导入一次
const BIG_KEY = 'kgdash-ppt-big'
const emptySlide: PptSlide = { title: '请打开演示文稿', subtitle: '', bg: '#26364a', songId: null }

export const usePptStore = defineStore('ppt', () => {
  const playback = usePlaybackStore()
  const library = useLibraryStore()

  const selectedApp = ref<PptApp>('powerpoint')
  const app = computed(() => selectedApp.value === 'wps' ? 'WPS 演示' : 'PowerPoint')
  const file = ref('')
  const connected = ref(false)
  const synced = ref(false)
  const pending = ref(false)
  const error = ref('正在连接 PPT 服务…')
  const running = ref(false)
  const black = ref(false)
  const index = ref(-1)
  const linkMusicState = ref(true)
  const linkMusic = computed({
    get: () => linkMusicState.value,
    set: (enabled: boolean) => {
      linkMusicState.value = enabled
      setPptLinkMusic(enabled).then(applyUpdate).catch((cause) => {
        linkMusicState.value = !enabled
        playback.report(cause instanceof Error ? cause.message : '联动开关保存失败', 'failed')
      })
    },
  })
  const big = ref(loadJSON<boolean>(BIG_KEY, false))
  const slides = ref<PptSlide[]>([])
  const documentKey = ref('')
  const documentId = ref('')
  const previewVersion = ref(0)
  const previewSession = ref('')
  const preloadedUrls = ref(new Set<string>())
  const preloadReady = ref(0)
  const preloadTotal = ref(0)
  const preloadFailed = ref(0)
  const preloadLoading = computed(() => preloadReady.value + preloadFailed.value < preloadTotal.value)
  watch(big, (v) => saveJSON(BIG_KEY, v))

  const current = computed(() => slides.value[index.value] ?? emptySlide)
  const nextSlide = computed(() => index.value < 0 ? null : slides.value[index.value + 1] ?? null)
  const canControl = computed(() => synced.value && connected.value && !!slides.value.length && !pending.value)
  const previewUrl = computed(() => slidePreview(index.value, 1280))

  function slidePreview(i: number, width = 1280): string {
    if (!synced.value || !connected.value || !documentId.value || i < 0 || i >= slides.value.length) return ''
    const query = new URLSearchParams({
      app: selectedApp.value, document: documentId.value,
      width: String(width), version: String(previewVersion.value), session: previewSession.value,
    })
    return `/api/ppt/preview/${i + 1}?${query}`
  }
  const refreshPreview = () => { previewVersion.value = Math.max(Date.now(), previewVersion.value + 1) }
  function thumbnailUrl(i: number): string {
    const url = slidePreview(i)
    return preloadedUrls.value.has(url) ? url : ''
  }

  watch(
    [synced, connected, documentId, selectedApp, () => slides.value.length, previewVersion, previewSession],
    (_, __, onCleanup) => {
      preloadedUrls.value = new Set()
      preloadReady.value = preloadTotal.value = preloadFailed.value = 0
      if (!synced.value || !connected.value || !documentId.value || !slides.value.length) return
      const urls = slides.value.map((_, i) => slidePreview(i))
      const cancel = preloadPptImages(urls, (progress) => {
        preloadedUrls.value = progress.ready
        preloadReady.value = progress.ready.size
        preloadTotal.value = progress.total
        preloadFailed.value = progress.failed
      }, () => [index.value, index.value + 1, index.value - 1].map((i) => slidePreview(i)).filter(Boolean))
      onCleanup(cancel)
    },
  )
  let lastRevision = -1
  let lastLinkSeq: number | null = null
  let importedOld = false
  let unsubscribe: (() => void) | undefined

  async function importOldBindings() {
    if (importedOld) return
    importedOld = true
    const old = loadJSON<Record<string, Record<string, number | null>>>(OLD_BIND_KEY, {})
    if (!Object.keys(old).length) return
    try {
      const result = await importPptBindings(old) as PptUpdate & { imported: number }
      localStorage.removeItem(OLD_BIND_KEY)
      applyUpdate(result)
      if (result.imported) playback.log(`已把浏览器里保存的 ${result.imported} 条页面绑定搬到后端`)
    } catch {
      importedOld = false // 下次连上再试，浏览器里的记录先留着
    }
  }

  function applyUpdate(update: PptUpdate) {
    if (update.revision < lastRevision) return
    lastRevision = update.revision
    const state = update.state
    previewSession.value = update.preview_session ?? ''
    const key = state.document_id ? `${state.app}:${state.document_id}` : ''
    const sameDocument = key !== '' && documentKey.value === key
    selectedApp.value = state.app
    connected.value = state.connected
    file.value = state.file
    running.value = state.running
    black.value = state.black
    error.value = state.error ?? ''
    const bound = update.bindings ?? {}
    if (!sameDocument || slides.value.length !== state.total_slides) {
      slides.value = Array.from({ length: state.total_slides }, (_, i) => ({
        title: `第 ${i + 1} 页`, subtitle: '', bg: '#26364a', songId: bound[String(i + 1)] ?? null,
      }))
    } else {
      slides.value.forEach((slide, i) => { slide.songId = bound[String(i + 1)] ?? null })
    }
    if (update.link_music !== undefined) linkMusicState.value = update.link_music
    documentKey.value = key
    documentId.value = state.document_id
    index.value = state.current_slide === null ? -1 : state.current_slide - 1
    // 联动播放由后端执行，这里只把结果记到操作记录里；刚连上时看到的是以前的结果，不重复记。
    const link = update.link ?? null
    if (link && lastLinkSeq !== null && link.seq !== lastLinkSeq) {
      const title = library.songById(link.song_id)?.title ?? '歌曲'
      if (link.status === 'played') playback.log(`翻到第 ${link.slide} 页，联动播放：${title}`)
      else playback.report(`翻到第 ${link.slide} 页，联动播放「${title}」失败：${link.message}`, 'failed')
    }
    lastLinkSeq = link?.seq ?? 0
  }

  function startSync() {
    if (unsubscribe) return
    unsubscribe = subscribePpt((update) => {
      applyUpdate(update)
      synced.value = true
      void importOldBindings()
    }, (open) => {
      synced.value = false
      if (open) { lastRevision = -1; lastLinkSeq = null } // 后端重启后 revision 可以重新从零开始。
      else error.value = 'PPT 服务连接中断，正在重连…'
    })
  }

  function stopSync() {
    unsubscribe?.()
    unsubscribe = undefined
    synced.value = false
  }

  async function perform(command: PptCommand, label: string) {
    if (!canControl.value) return
    pending.value = true
    playback.report(label, 'pending')
    try {
      const update = await sendPptCommand(command)
      applyUpdate(update)
      if (update.state.error) throw new Error(update.state.error)
      const page = index.value < 0 ? '当前页待读取' : `当前第 ${index.value + 1} 页`
      playback.report(`${label} · ${page}`, 'verified')
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : 'PPT 操作失败'
      playback.report(error.value, 'failed')
    } finally {
      pending.value = false
    }
  }

  async function connectTo(target: PptApp = selectedApp.value) {
    if (pending.value) return
    pending.value = true
    try {
      applyUpdate(await connectPpt(target))
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '连接失败'
    } finally {
      pending.value = false
    }
  }

  function go(i: number) {
    if (i < 0 || i >= slides.value.length) return
    return perform({ action: 'goto', slide: i + 1 }, `PPT 跳到第 ${i + 1} 页`)
  }
  const next = () => perform({ action: 'next' }, 'PPT 下一页')
  const prev = () => perform({ action: 'previous' }, 'PPT 上一页')
  const toggleBlack = () => {
    if (running.value) return perform({ action: 'black', enabled: !black.value }, black.value ? 'PPT 恢复画面' : 'PPT 黑屏')
  }
  const toggleRunning = () => perform({ action: running.value ? 'stop' : 'start' }, running.value ? '结束放映 PPT' : '开始放映 PPT')

  async function saveBinding(songId: number | null, done: string) {
    if (!canControl.value || index.value < 0 || !documentKey.value) return
    const page = index.value + 1
    try {
      applyUpdate(await setPptBinding(page, songId))
      playback.log(`第 ${page} 页${done}`)
    } catch (cause) {
      playback.report(`第 ${page} 页绑定没保存：${cause instanceof Error ? cause.message : '请检查后端连接'}`, 'failed')
    }
  }
  function bindCurrentSong() {
    if (playback.currentId === null) {
      playback.log('先播放一首歌，再绑定到这一页')
      return
    }
    return saveBinding(playback.currentId, `绑定：${playback.current?.title}`)
  }
  const unbind = () => saveBinding(null, '已解除绑定')

  return {
    app, selectedApp, file, connected, synced, pending, error, canControl,
    running, black, index, linkMusic, big, slides, current, nextSlide,
    go, next, prev, toggleBlack, toggleRunning, bindCurrentSong, unbind,
    connectTo, startSync, stopSync,
    previewUrl, slidePreview, thumbnailUrl, refreshPreview,
    preloadReady, preloadTotal, preloadFailed, preloadLoading,
  }
})

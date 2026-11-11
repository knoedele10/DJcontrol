<script setup lang="ts">
// 演出主面板：顶部状态 / 左侧分组 + 已播 / 中间选歌 + 待播队列 / 右侧 PPT / 底部走带控制。
import { onBeforeUnmount, onMounted, ref } from 'vue'
import NowPlayingBar from '@/Playback/NowPlayingBar.vue'
import TransportBar from '@/Playback/TransportBar.vue'
import GroupSidebar from '@/Scenes/GroupSidebar.vue'
import SongBrowser from '@/Library/SongBrowser.vue'
import GroupPopover from '@/Library/GroupPopover.vue'
import QueuePanel from '@/Queue/QueuePanel.vue'
import PptPanel from '@/Ppt/PptPanel.vue'
import { useLibraryStore } from '@/Library/LibraryStore'
import { usePlaybackStore } from '@/Playback/PlaybackStore'
import { usePptStore } from '@/Ppt/PptStore'
import { useUiStore } from '@/Common/UiStore'

const library = useLibraryStore()
const playback = usePlaybackStore()
const ppt = usePptStore()
const ui = useUiStore()
const browser = ref<InstanceType<typeof SongBrowser>>()

// 全局快捷键（输入框内不触发）
function onKey(e: KeyboardEvent) {
  const t = e.target as HTMLElement
  if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable) return
  if (e.key === 'Escape' && ui.groupPopover) return ui.closeGroupPopover()
  if (e.key === 'ArrowRight' || e.key === 'PageDown') { e.preventDefault(); ppt.next() }
  else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); ppt.prev() }
  else if (e.key === 'b' || e.key === 'B' || e.key === '.') ppt.toggleBlack()
  else if (e.key === 'p' || e.key === 'P') ppt.big = !ppt.big
  else if (e.code === 'Space') {
    if (t.tagName === 'BUTTON') return
    e.preventDefault()
    playback.toggle()
  }
  else if (e.key === 'n' || e.key === 'N') playback.playNext()
  else if (e.key === '/') { e.preventDefault(); browser.value?.focusSearch() }
  else if (/^[1-9]$/.test(e.key)) {
    const c = library.activeGroup?.categories[Number(e.key) - 1]
    if (c) library.selectCategory(c.id)
  }
}

let ticker = 0
onMounted(() => {
  document.addEventListener('keydown', onKey)
  ticker = window.setInterval(() => playback.tick(), 1000)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey)
  clearInterval(ticker)
})
</script>

<template>
  <div class="app">
    <NowPlayingBar />
    <main class="main" :class="{ 'ppt-big': ppt.big }">
      <GroupSidebar class="side" />
      <div class="cstack">
        <SongBrowser ref="browser" class="browser" />
        <QueuePanel />
      </div>
      <div class="rstack">
        <PptPanel />
      </div>
    </main>
    <TransportBar />
    <GroupPopover />
  </div>
</template>

<style scoped>
/* 1920×1080 全屏：页面本身不滚动，各栏内部滚动。PPT 默认约占 40% 宽度。 */
.app { height: 100%; display: grid; grid-template-rows: auto minmax(0, 1fr) auto; gap: 14px; padding: 16px max(20px, env(safe-area-inset-right, 0px)) 16px max(20px, env(safe-area-inset-left, 0px)); max-width: 2560px; margin: 0 auto; }
.main { display: grid; grid-template-columns: 250px minmax(0, 1fr) minmax(0, 0.88fr); gap: 14px; min-height: 0; }
.main.ppt-big { grid-template-columns: 220px minmax(0, 1fr) minmax(0, 1.45fr); }
.main > * { min-height: 0; }
.cstack { display: flex; flex-direction: column; gap: 14px; min-width: 0; min-height: 0; }
.cstack > .browser { flex: 1 1 auto; }
.rstack { display: flex; flex-direction: column; gap: 14px; min-width: 0; min-height: 0; overflow-y: auto; }
.rstack > * { flex-shrink: 0; }
@media (max-width: 1400px) { .main { grid-template-columns: 220px minmax(0, 1fr) minmax(0, 0.8fr); } }
@media (max-width: 1080px), (max-height: 700px) {
  .app { height: auto; min-height: 100%; }
  .main, .main.ppt-big { grid-template-columns: minmax(0, 1fr) minmax(320px, 0.9fr); }
  .side { grid-column: 1 / -1; }
  .main.ppt-big .rstack { grid-column: 1 / -1; order: -1; }
  .rstack { overflow: visible; }
  .cstack > .browser { min-height: 520px; }
}
@media (max-width: 720px) { .main, .main.ppt-big { grid-template-columns: minmax(0, 1fr); } }
</style>

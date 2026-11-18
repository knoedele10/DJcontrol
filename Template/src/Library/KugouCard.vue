<script setup lang="ts">
// 酷狗搜索结果卡片（不在曲库里）。排队 / 播放会自动收进曲库（未分组）；＋ 收进曲库并打开分组面板。
import { nextTick } from 'vue'
import type { KugouResult } from '@/Common/Types'
import HighlightText from '@/Common/HighlightText.vue'
import { useLibraryStore } from '@/Library/LibraryStore'
import { useQueueStore } from '@/Queue/QueueStore'
import { usePlaybackStore } from '@/Playback/PlaybackStore'
import { useUiStore } from '@/Common/UiStore'
import { fmtBpm, fmtTime } from '@/Common/Format'

const props = defineProps<{ result: KugouResult; first?: boolean }>()

const library = useLibraryStore()
const queue = useQueueStore()
const playback = usePlaybackStore()
const ui = useUiStore()

async function enqueue(front = false) {
  const id = await library.ensureInLibrary(props.result)
  if (id === null) return
  const label = front ? `插到下一首：${props.result.title}` : `加入队列：${props.result.title}`
  await playback.track(label, () => queue.enqueue(id, front))
}
async function playNow() {
  const id = await library.ensureInLibrary(props.result)
  if (id !== null) playback.play(id)
}
async function addToLibrary() {
  const id = await library.ensureInLibrary(props.result)
  if (id === null) return
  playback.log(`收进曲库：${props.result.title}`)
  await nextTick()
  const btn = document.querySelector<HTMLElement>(`[data-song-card="${id}"] [aria-label="设置分组"]`)
  if (btn) ui.openGroupPopover(id, btn)
}
async function addToPlaylist() {
  if (playback.busy) return
  const id = await library.ensureInLibrary(props.result)
  if (id !== null) await playback.addPlaylistSong(id)
}
</script>

<template>
  <div class="card kg" :class="{ first }" role="button" tabindex="0" title="单击加入队列（会自动收进曲库，未分组）" @click="enqueue()" @keydown.enter.self="enqueue()">
    <div class="acts">
      <button v-if="playback.controller === 'kugou'" class="ib" :disabled="!playback.can('add_to_playlist') || playback.busy"
        title="收录并加入演出歌单（会试听切歌，完成后暂停）" aria-label="加入演出歌单" @click.stop="addToPlaylist">♫＋</button>
      <button class="ib" title="收进曲库并设置分组" aria-label="收进曲库并设置分组" @click.stop="addToLibrary">＋</button>
      <button class="ib" title="插到下一首" aria-label="插到下一首" @click.stop="enqueue(true)">⤒</button>
      <button class="ib go" title="立即播放" aria-label="立即播放" @click.stop="playNow">▶</button>
    </div>
    <div class="t"><HighlightText :text="result.title" :tokens="library.tokens" /></div>
    <div class="a"><HighlightText :text="result.artist" :tokens="library.tokens" /></div>
    <div class="meta">
      <span class="mono">{{ fmtBpm(result.bpm) }}</span>
      <span class="mono">{{ fmtTime(result.duration) }}</span>
      <span>不在曲库</span>
    </div>
  </div>
</template>

<style scoped>
.card.kg { --c: var(--violet); background: rgba(19, 18, 42, 0.9); border-style: dashed; border-left-style: solid; }
</style>

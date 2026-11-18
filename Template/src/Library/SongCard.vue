<script setup lang="ts">
// 曲库歌曲卡片：单击加队列，⌗ 设置分组，⤒ 插到下一首，▶ 立即播放；可拖到左侧分类。
import { computed, ref } from 'vue'
import type { Song } from '@/Common/Types'
import HighlightText from '@/Common/HighlightText.vue'
import { useLibraryStore } from '@/Library/LibraryStore'
import { useQueueStore } from '@/Queue/QueueStore'
import { usePlaybackStore } from '@/Playback/PlaybackStore'
import { useUiStore } from '@/Common/UiStore'
import { fmtBpm, fmtTime } from '@/Common/Format'

const props = defineProps<{ song: Song; first?: boolean }>()

const library = useLibraryStore()
const queue = useQueueStore()
const playback = usePlaybackStore()
const ui = useUiStore()

const dragging = ref(false)
const qpos = computed(() => queue.positionOf(props.song.id))
const mem = computed(() => library.memberships(props.song.id))

function enqueue(front = false) {
  const label = front ? `插到下一首：${props.song.title}` : `加入队列：${props.song.title}`
  return playback.track(label, () => queue.enqueue(props.song.id, front))
}
function onDragStart(e: DragEvent) {
  e.dataTransfer?.setData('text/plain', String(props.song.id))
  if (e.dataTransfer) e.dataTransfer.effectAllowed = 'copy'
  dragging.value = true
  ui.closeGroupPopover()
}
</script>

<template>
  <div
    class="card"
    :class="{ now: playback.currentId === song.id, first, dragging }"
    :style="{ '--c': library.colorOf(song.id) }"
    :data-song-card="song.id"
    role="button"
    tabindex="0"
    draggable="true"
    title="单击加入队列；拖到左侧分类可加入分类"
    @click="enqueue()"
    @keydown.enter.self="enqueue()"
    @dragstart="onDragStart"
    @dragend="dragging = false"
  >
    <div class="acts">
      <button v-if="playback.controller === 'kugou'" class="ib" :disabled="!playback.can('add_to_playlist') || playback.busy"
        title="加入演出歌单（会试听切歌，完成后暂停；请在演出前使用）" aria-label="加入演出歌单"
        @click.stop="playback.addPlaylistSong(song.id)">♫＋</button>
      <button class="ib" title="设置分组" aria-label="设置分组" @click.stop="ui.openGroupPopover(song.id, $event.currentTarget as HTMLElement)">⌗</button>
      <button class="ib" title="插到下一首" aria-label="插到下一首" @click.stop="enqueue(true)">⤒</button>
      <button class="ib go" :disabled="!playback.can('play_track') || playback.busy" title="立即播放" aria-label="立即播放" @click.stop="playback.play(song.id)">▶</button>
    </div>
    <div class="t"><HighlightText :text="song.title" :tokens="library.tokens" /></div>
    <div class="a"><HighlightText :text="song.artist" :tokens="library.tokens" /></div>
    <div class="meta">
      <span class="mono">{{ fmtBpm(song.bpm) }}</span>
      <span class="mono">{{ fmtTime(song.duration) }}</span>
      <span v-if="queue.isPlayed(song.id)" class="played">已播</span>
      <span v-if="playback.playlist?.songs[String(song.id)] === true" class="played" title="最近一次核验在演出歌单内；歌单改动后请刷新">歌单内</span>
    </div>
    <div class="grpline">
      <span v-for="m in mem.slice(0, 3)" :key="m.category.id" class="gtag">{{ m.group.name }}·{{ m.category.name }}</span>
      <span v-if="mem.length > 3" class="gtag">+{{ mem.length - 3 }}</span>
      <span v-if="!mem.length" class="gtag">未分组</span>
    </div>
    <span v-if="qpos >= 0" class="qpos">队列 #{{ qpos + 1 }}</span>
  </div>
</template>

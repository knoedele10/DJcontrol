<script setup lang="ts">
// 待播队列（横向条，放在选歌区下方）：第一张是"下一首"，可前移 / 后移 / 移除 / 清空。
import { useLibraryStore } from '@/Library/LibraryStore'
import { useQueueStore } from '@/Queue/QueueStore'
import { usePlaybackStore } from '@/Playback/PlaybackStore'
import { fmtBpm, fmtTime } from '@/Common/Format'

const library = useLibraryStore()
const queue = useQueueStore()
const playback = usePlaybackStore()

const clear = () => playback.track('清空队列', () => queue.clear())
const move = (itemId: string, title: string, delta: -1 | 1) =>
  playback.track(`${delta < 0 ? '前移' : '后移'}：${title}`, () => queue.move(itemId, delta))
const remove = (itemId: string, title: string) => playback.track(`移出队列：${title}`, () => queue.remove(itemId))
</script>

<template>
  <section class="col qcol" aria-label="待播队列" data-tour="queue">
    <div class="qhead">
      <h2>待播队列</h2>
      <span v-if="queue.rows.length" class="mono sum">{{ queue.rows.length }} 首 · {{ fmtTime(queue.totalSeconds) }}</span>
      <span class="sp"></span>
      <button class="play-next" :disabled="!queue.rows.length || !playback.can('play_track') || playback.busy" title="播队列下一首（N）" @click="playback.playNext()">▶ 播下一首</button>
      <button class="ib" aria-label="清空队列" title="清空队列" @click="clear">✕</button>
    </div>
    <div class="qlist">
      <div v-for="({ item, song }, i) in queue.rows" :key="item.id" class="qitem" :class="{ next: i === 0 }" :style="{ '--c': library.colorOf(song.id) }">
        <span class="idx mono">{{ i === 0 ? '下一首' : i + 1 }}</span>
        <div class="t">{{ song.title }}</div>
        <div class="s">{{ song.artist }} · <span class="mono">{{ fmtBpm(song.bpm) }}</span><template v-if="queue.isPlayed(song.id)"> · <span class="warn">已播</span></template></div>
        <div class="qops">
          <button title="前移" aria-label="前移" :disabled="i === 0" @click="move(item.id, song.title, -1)">←</button>
          <button title="后移" aria-label="后移" :disabled="i === queue.rows.length - 1" @click="move(item.id, song.title, 1)">→</button>
          <button title="移除" aria-label="移除" @click="remove(item.id, song.title)">✕</button>
        </div>
      </div>
      <div v-if="!queue.rows.length" class="empty">队列是空的。单击上方的歌曲卡片加进来，队列跨分组保留。</div>
    </div>
  </section>
</template>

<style scoped>
.qcol { flex: none; }
.qhead { display: flex; align-items: center; gap: 12px; padding: 10px 16px; border-bottom: 1px solid var(--line); }
.qhead h2 { font-size: 17px; font-weight: 700; margin: 0; }
.sum { color: var(--fg3); font-size: 14px; }
.sp { flex: 1; }
.play-next { height: 36px; padding: 0 14px; font-size: 15px; font-weight: 500; border-color: var(--hot); color: var(--hot); }
.play-next:hover:not(:disabled) { background: var(--hot-soft); }
.play-next:disabled { opacity: 0.4; cursor: default; }
.qlist { display: flex; gap: 10px; overflow-x: auto; padding: 12px 16px 14px; min-height: 124px; align-items: stretch; }
.qitem { flex: none; width: 210px; position: relative; background: var(--raise); border: 1px solid var(--line); border-top: 4px solid var(--c); border-radius: var(--r); padding: 8px 12px 10px; display: flex; flex-direction: column; gap: 2px; }
.qitem.next { background: linear-gradient(160deg, var(--hot-soft), var(--accent-soft)); border-color: rgba(255, 61, 166, 0.6); border-top-color: var(--hot); box-shadow: 0 0 18px rgba(255, 61, 166, 0.25); }
.idx { font-size: 12px; color: var(--fg3); }
.qitem.next .idx { color: var(--hot); font-weight: 700; }
.t { font-size: 16px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.s { font-size: 12px; color: var(--fg3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.warn { color: var(--warn); }
.qops { display: flex; gap: 4px; margin-top: 6px; }
.qops button { width: 32px; height: 28px; padding: 0; font-size: 14px; color: var(--fg2); }
.qops button:disabled { opacity: 0.3; cursor: default; }
.empty { padding: 20px 4px; }
</style>

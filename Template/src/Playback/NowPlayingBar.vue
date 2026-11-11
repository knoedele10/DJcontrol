<script setup lang="ts">
// 顶部状态条：当前曲目、进度、连接状态。
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { usePlaybackStore } from '@/Playback/PlaybackStore'
import { useLibraryStore } from '@/Library/LibraryStore'

import { fmtBpm, fmtTime } from '@/Common/Format'

const playback = usePlaybackStore()
const library = useLibraryStore()

const clock = ref('')
const updateClock = () => (clock.value = new Date().toTimeString().slice(0, 5))
let t = 0
onMounted(() => {
  updateClock()
  t = window.setInterval(updateClock, 10_000)
})
onBeforeUnmount(() => clearInterval(t))

function seek(e: MouseEvent) {
  if (!playback.can('seek')) return
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  playback.seek((e.clientX - r.left) / r.width)
}

function subtitle() {
  const s = playback.current
  if (!s) return playback.artist || playback.error || '从队列选一首开始'
  const c = library.categoryOf(s.id)
  return `${s.artist} · ${fmtBpm(s.bpm)}${c && library.activeGroup ? ` · ${library.activeGroup.name} › ${c.name}` : ''}`
}
</script>

<template>
  <header class="status">
    <div class="disc" :class="{ spin: playback.playing }"><i></i></div>
    <div style="min-width: 0">
      <div class="np-title">{{ playback.title || playback.current?.title || '未在播放' }}</div>
      <div class="np-sub">{{ subtitle() }}</div>
      <div v-if="playback.can('read_position')" class="prog">
        <span class="mono pos">{{ fmtTime(playback.position) }}</span>
        <div class="track" :class="{ ending: playback.nearEnd, fixed: !playback.can('seek') }" :title="playback.can('seek') ? '点击跳转（演示用）' : '当前播放器不支持跳转'" @click="seek">
          <b :style="{ width: playback.duration ? (playback.position / playback.duration) * 100 + '%' : '0' }"></b>
        </div>
        <span class="mono dur">{{ fmtTime(playback.duration) }}</span>
      </div>
    </div>
    <div class="chips">
      <span v-if="playback.error" class="chip warn">{{ playback.error }}</span>
      <span class="chip" :class="playback.connected ? 'ok' : 'warn'">{{ playback.connected ? `● 已连接 · ${playback.controller === 'kugou' ? '酷狗' : '模拟播放器'}` : '○ 播放器未连接' }}</span>
      <span v-if="playback.controller === 'mock'" class="chip warn">模拟播放器 · 状态由后端驱动</span>
      <div style="display: flex; gap: 6px; align-items: center">
        <span class="chip mute mono">{{ clock }}</span>
        <RouterLink to="/settings" class="chip mute set">⚙ 设置</RouterLink>
      </div>
    </div>
  </header>
</template>

<style scoped>
.status { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 20px; align-items: center; background: linear-gradient(100deg, rgba(255, 61, 166, 0.12), rgba(139, 92, 255, 0.1) 40%, rgba(19, 18, 42, 0.92) 75%); border: 1px solid var(--line); border-radius: 16px; padding: 14px 20px; }
.disc { width: 68px; height: 68px; border-radius: 50%; background: repeating-radial-gradient(circle at center, #2a2550 0 2px, #17152f 2px 4px); display: grid; place-items: center; border: 2px solid var(--line-strong); }
.disc i { width: 18px; height: 18px; border-radius: 50%; background: var(--grad); display: block; }
.disc.spin { animation: spin 3s linear infinite; border-color: var(--hot); box-shadow: 0 0 22px rgba(255, 61, 166, 0.45); }
@keyframes spin { to { transform: rotate(360deg); } }
.np-title { font-size: 28px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; letter-spacing: 0.01em; }
.np-sub { color: var(--fg2); font-size: 15px; margin-top: 2px; }
.prog { display: flex; align-items: center; gap: 12px; margin-top: 10px; }
.pos { font-size: 14px; color: var(--fg); }
.dur { font-size: 14px; color: var(--fg3); }
.track { flex: 1; height: 10px; background: var(--line); border-radius: 5px; cursor: pointer; position: relative; }
.track.fixed { cursor: default; }
.track b { position: absolute; inset: 0 auto 0 0; background: var(--grad); border-radius: 5px; box-shadow: 0 0 12px rgba(139, 92, 255, 0.6); }
.track.ending b { background: linear-gradient(90deg, var(--warn), var(--bad)); box-shadow: 0 0 14px rgba(255, 77, 109, 0.6); }
.chips { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }
.set { text-decoration: none; }
.set:hover { color: var(--fg); border-color: var(--fg3); }
@media (max-width: 720px) {
  .status { grid-template-columns: auto minmax(0, 1fr); }
  .chips { grid-column: 1 / -1; flex-direction: row; align-items: center; flex-wrap: wrap; }
}
</style>

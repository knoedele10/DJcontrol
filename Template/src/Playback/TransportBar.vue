<script setup lang="ts">
// 底部走带控制：上一首、播放/暂停、播队列下一首、自动接歌、快捷键说明、命令核验状态。
import { usePlaybackStore } from '@/Playback/PlaybackStore'

const playback = usePlaybackStore()

const SHORTCUTS: [string, string][] = [
  ['空格', '播放 / 暂停'],
  ['N', '播队列下一首'],
  ['/', '搜索歌曲'],
  ['1–9', '切换本组分类'],
  ['← → / PgUp PgDn', 'PPT 翻页（翻页笔可用）'],
  ['B', 'PPT 黑屏'],
  ['P', '放大 / 还原 PPT'],
  ['拖动卡片', '拖到左侧分类 = 加入分类'],
]
</script>

<template>
  <footer class="transport">
    <button class="ib side" :disabled="playback.busy || !playback.can(playback.controller === 'kugou' ? 'next' : 'play_track')" aria-label="上一首" title="上一首" @click="playback.controller === 'kugou' ? playback.mediaPrevious() : playback.previous()">⏮</button>
    <button class="big" :class="{ on: playback.playing }" :disabled="playback.busy || !playback.can('play_pause')" aria-label="播放或暂停" title="播放 / 暂停（空格）" @click="playback.toggle()">{{ playback.playing ? '❚❚' : '▶' }}</button>
    <button v-if="playback.controller === 'kugou'" :disabled="playback.busy || !playback.can('next')" @click="playback.mediaNext()">⏭ 酷狗下一首</button>
    <button :disabled="playback.busy || !playback.can('play_track')" class="mid" title="播队列下一首（N）" @click="playback.playNext()">⏭ 播队列下一首</button>
    <label class="toggle">
      <input
        type="checkbox"
        :checked="playback.autoNext"
        :disabled="playback.autoNextPending || playback.controller === 'kugou' || !playback.can('read_position') || !playback.can('play_track')"
        :title="playback.controller === 'kugou' ? '酷狗模式不支持自动接歌，请用「播队列下一首」' : undefined"
        @change="playback.setAutoNextEnabled(($event.target as HTMLInputElement).checked)"
      />快结束时自动接歌
    </label>

    <div class="keys" tabindex="0">
      <span class="keys-btn">⌨ 快捷键</span>
      <div class="keys-pop" role="tooltip">
        <div v-for="[k, d] in SHORTCUTS" :key="k" class="krow"><kbd>{{ k }}</kbd><span>{{ d }}</span></div>
      </div>
    </div>

    <div class="log">
      <template v-if="playback.command.status === 'idle'">{{ playback.command.text }}</template>
      <template v-else>
        <b :class="playback.command.status">{{ playback.command.status === 'pending' ? '发送中' : playback.command.status === 'verified' ? '已核验' : '失败' }}</b>
        · {{ playback.command.text }}
      </template>
    </div>
  </footer>
</template>

<style scoped>
.transport { display: flex; align-items: center; justify-content: center; gap: 16px; flex-wrap: wrap; background: rgba(19, 18, 42, 0.92); border: 1px solid var(--line); border-radius: 16px; padding: 12px 20px; }
.side { width: 52px; height: 52px; font-size: 20px; border-radius: 50%; }
.big { width: 72px; height: 72px; border-radius: 50%; background: var(--grad); color: #fff; border: none; font-size: 26px; display: grid; place-items: center; box-shadow: 0 0 0 4px rgba(255, 61, 166, 0.18); }
.big:hover { background: var(--grad); filter: brightness(1.12); }
.big.on { box-shadow: 0 0 0 4px rgba(255, 61, 166, 0.25), 0 0 30px rgba(139, 92, 255, 0.6); }
.mid { height: 52px; padding: 0 22px; display: inline-flex; align-items: center; gap: 8px; font-size: 17px; font-weight: 500; border-color: var(--accent); color: var(--accent); }
.mid:hover { background: var(--accent-soft); }
.toggle { display: flex; align-items: center; gap: 8px; color: var(--fg2); font-size: 15px; margin-left: 4px; cursor: pointer; }
.toggle input { accent-color: var(--hot); width: 18px; height: 18px; }
.keys { position: relative; }
.keys-btn { display: inline-block; font-size: 14px; color: var(--fg2); border: 1px solid var(--line-strong); border-radius: var(--r); padding: 8px 12px; cursor: default; }
.keys-pop { display: none; position: absolute; bottom: calc(100% + 10px); left: 50%; transform: translateX(-50%); width: 320px; background: var(--raise); border: 1px solid var(--line-strong); border-radius: 12px; padding: 12px 14px; box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5); z-index: 30; }
.keys:hover .keys-pop, .keys:focus-within .keys-pop { display: block; }
.krow { display: grid; grid-template-columns: 130px 1fr; gap: 10px; align-items: center; padding: 4px 0; font-size: 14px; color: var(--fg2); }
.krow kbd { justify-self: start; }
.log { font-size: 14px; color: var(--fg3); min-width: 240px; text-align: right; margin-left: auto; }
.log b { font-weight: 700; }
.log b.verified { color: var(--ok); }
.log b.pending { color: var(--warn); }
.log b.failed { color: var(--bad); }
@media (max-width: 720px) { .log { margin-left: 0; text-align: center; width: 100%; } }
</style>

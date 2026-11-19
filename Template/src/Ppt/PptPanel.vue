<script setup lang="ts">
// PPT 放映控制：预览、翻页、黑屏、放映开关、缩略图跳页、页面绑定歌曲与翻页联动。
import { nextTick, onMounted, ref, watch } from 'vue'
import { useLibraryStore } from '@/Library/LibraryStore'
import { useMonitorStore } from '@/Monitor/MonitorStore'
import ScreenMonitor from '@/Monitor/ScreenMonitor.vue'
import { usePlaybackStore } from '@/Playback/PlaybackStore'
import { usePptStore } from '@/Ppt/PptStore'
import type { PptApp } from '@/Common/Types'
import SlidePreview from '@/Ppt/SlidePreview.vue'

const library = useLibraryStore()
const monitor = useMonitorStore()
const playback = usePlaybackStore()
const ppt = usePptStore()

onMounted(() => {
  void monitor.init()
})

const thumbs = ref<HTMLElement>()
const songTitle = (id: number | null) => (id === null ? '' : library.songById(id)?.title ?? '')
const selectApp = (event: Event) => ppt.connectTo((event.target as HTMLSelectElement).value as PptApp)

watch(() => ppt.index, async () => {
  await nextTick()
  thumbs.value?.querySelector('.thumb.on')?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
})
</script>

<template>
  <section class="col" aria-label="PPT 放映" data-tour="ppt">
    <div class="col-h ppt-head">
      <h2>PPT 放映</h2>
      <span class="pchip" :class="ppt.synced && ppt.running ? 'live' : 'idle'">{{ !ppt.synced ? '未同步' : !ppt.connected ? '未连接' : ppt.running ? (ppt.black ? '● 放映中 · 黑屏' : '● 放映中') : '未放映' }}</span>
      <div v-if="monitor.supported" class="monitor-actions">
        <div class="monitor-switch" role="group" aria-label="画面模式">
          <button
            type="button"
            :class="{ on: monitor.mode === 'preview' }"
            title="显示后端静态幻灯片预览"
            @click="monitor.setMode('preview')"
          >
            预览
          </button>
          <button
            type="button"
            :class="{ on: monitor.mode === 'live' }"
            :disabled="!monitor.hasSecondScreen"
            :title="monitor.unavailableReason ?? '实时监看第二块屏幕画面（约 30 帧）'"
            @click="monitor.setMode('live')"
          >
            第二屏
          </button>
        </div>
        <button
          type="button"
          class="popup-btn"
          :class="{ on: monitor.windowOpen }"
          :disabled="!monitor.hasSecondScreen"
          :title="monitor.unavailableReason ?? (monitor.windowOpen ? '收回置顶监看小窗' : '弹出置顶实时监看小窗')"
          @click="monitor.windowOpen ? monitor.closePopup() : monitor.openPopup()"
        >
          {{ monitor.windowOpen ? '收回小窗' : '⧉ 小窗' }}
        </button>
      </div>
      <button class="pbig" title="放大 / 还原 PPT 区域（P）" @click="ppt.big = !ppt.big">{{ ppt.big ? '⤡ 还原' : '⤢ 放大' }}</button>
    </div>
    <div class="body">
      <div class="connection">
        <select :value="ppt.selectedApp" :disabled="ppt.pending || !ppt.synced" aria-label="演示软件" @change="selectApp">
          <option value="powerpoint">PowerPoint</option>
          <option value="wps">WPS 演示</option>
        </select>
        <span class="file">{{ ppt.file || '请先在演示软件中打开文稿' }}</span>
        <button :disabled="ppt.pending || !ppt.synced" @click="ppt.connectTo()">重新连接</button>
      </div>
      <div v-if="ppt.error" class="ppt-error" role="status">{{ ppt.error }}</div>
      <div
        v-if="monitor.supported && monitor.displaysLoaded && !monitor.hasSecondScreen && monitor.unavailableReason"
        class="monitor-hint"
        role="status"
      >
        {{ monitor.unavailableReason }}
      </div>
      <div v-if="ppt.preloadTotal" class="preload-progress" role="status">
        <template v-if="ppt.preloadLoading">正在后台预载：{{ ppt.preloadReady }} / {{ ppt.preloadTotal }} 页</template>
        <template v-else-if="ppt.preloadFailed">已预载 {{ ppt.preloadReady }} 页，{{ ppt.preloadFailed }} 页失败，可刷新预览重试</template>
        <template v-else>全部 {{ ppt.preloadTotal }} 页已就绪</template>
        <progress v-if="ppt.preloadLoading" :value="ppt.preloadReady + ppt.preloadFailed" :max="ppt.preloadTotal" aria-label="幻灯片预载进度"></progress>
      </div>

      <div
        class="slide"
        :class="{
          black: ppt.black && (!monitor.supported || monitor.mode === 'preview'),
          'live-monitor': monitor.supported && monitor.mode === 'live',
        }"
        :style="{ '--sbg': ppt.current.bg }"
      >
        <div v-if="monitor.supported && monitor.mode === 'live' && monitor.windowOpen" class="popup-active" role="status">
          <span>画面已在置顶小窗中</span>
          <span aria-hidden="true">·</span>
          <button type="button" class="popup-retract" @click="monitor.closePopup()">收回</button>
        </div>
        <ScreenMonitor
          v-else-if="monitor.supported && monitor.mode === 'live'"
          :active="monitor.mode === 'live' && !monitor.windowOpen"
        />
        <template v-else-if="!ppt.black">
          <SlidePreview v-if="ppt.previewUrl" :key="ppt.previewUrl" :src="ppt.previewUrl" :alt="`${ppt.file} 第 ${ppt.index + 1} 页`" />
          <div v-else class="st">{{ ppt.current.title }}</div>
          <div v-if="ppt.current.songId !== null" class="song">♪ {{ songTitle(ppt.current.songId) }}</div>
          <button v-if="ppt.previewUrl" class="previewhint" title="重新读取当前文稿的页面图片" @click="ppt.refreshPreview()">静态预览 · 刷新预览</button>
          <div class="sn">{{ ppt.index < 0 ? '—' : ppt.index + 1 }} / {{ ppt.slides.length }}</div>
        </template>
        <span v-else class="blackhint">黑屏中 · 按 B 恢复</span>
      </div>

      <div class="ctl">
        <button :disabled="!ppt.canControl || ppt.index <= 0" title="上一页（← / PageUp）" aria-label="上一页" @click="ppt.prev()">◀</button>
        <button class="nx" :disabled="!ppt.canControl || ppt.index < 0 || ppt.index >= ppt.slides.length - 1" title="下一页（→ / PageDown / 翻页笔）" @click="ppt.next()">下一页 ▶</button>
        <span class="pg mono">{{ ppt.index < 0 ? '—' : ppt.index + 1 }} / {{ ppt.slides.length }}</span>
        <button :disabled="!ppt.canControl || !ppt.running" :class="{ on: ppt.black }" title="黑屏（B）" @click="ppt.toggleBlack()">黑屏</button>
        <button :disabled="!ppt.canControl" @click="ppt.toggleRunning()">{{ ppt.running ? '结束放映' : '开始放映' }}</button>
      </div>

      <div class="nextline">
        <template v-if="ppt.nextSlide">
          下一页：{{ ppt.nextSlide.title }}<template v-if="ppt.nextSlide.songId !== null && ppt.linkMusic"> · 将播放 {{ songTitle(ppt.nextSlide.songId) }}</template>
        </template>
        <template v-else>{{ ppt.index < 0 ? '等待当前页' : '已是最后一页' }}</template>
      </div>

      <div ref="thumbs" class="thumbs">
        <button v-for="(s, i) in ppt.slides" :key="i" :disabled="!ppt.canControl" class="thumb" :class="{ on: i === ppt.index }" :style="{ '--sbg': s.bg }" :title="s.title" @click="ppt.go(i)">
          <SlidePreview v-if="ppt.thumbnailUrl(i)" :key="ppt.thumbnailUrl(i)" :src="ppt.thumbnailUrl(i)" :alt="s.title" thumbnail />
          <span v-else>{{ s.title }}</span><span v-if="s.songId !== null" class="tm">♪</span><span class="tn">{{ i + 1 }}</span>
        </button>
      </div>

      <div class="plink">
        <label class="lk"><input v-model="ppt.linkMusic" type="checkbox" />翻页联动音乐</label>
        <span class="sp">
          <template v-if="ppt.current.songId !== null">本页 ♪ <b>{{ songTitle(ppt.current.songId) }}</b></template>
          <template v-else>本页未绑定歌曲</template>
        </span>
        <button v-if="ppt.current.songId !== null" :disabled="!ppt.canControl || ppt.index < 0" @click="ppt.unbind()">解除</button>
        <button :disabled="!ppt.canControl || ppt.index < 0" :title="playback.current ? '' : '先播放一首歌'" @click="ppt.bindCurrentSong()">
          {{ playback.current ? `绑定「${playback.current.title}」` : '绑定正在播放的歌' }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.ppt-head { flex-wrap: wrap; gap: 8px; }
.ppt-head h2 { min-width: 72px; }
.monitor-actions { display: flex; align-items: center; gap: 6px; flex: none; }
.monitor-switch { display: inline-flex; border: 1px solid var(--line); border-radius: 7px; overflow: hidden; }
.monitor-switch button { font-size: 12px; padding: 4px 9px; border: none; border-radius: 0; background: transparent; color: var(--fg2); }
.monitor-switch button + button { border-left: 1px solid var(--line); }
.monitor-switch button.on { background: var(--accent); color: var(--accent-ink, #06101a); font-weight: 700; }
.popup-btn { font-size: 12px; padding: 4px 10px; white-space: nowrap; }
.popup-btn.on { border-color: var(--accent); color: var(--accent); }
.monitor-hint { font-size: 12px; color: var(--fg3); overflow-wrap: anywhere; }
.connection { display: flex; align-items: center; gap: 8px; }
.connection select { min-width: 0; max-width: 130px; background: var(--raise); color: var(--fg); border: 1px solid var(--line); border-radius: 5px; padding: 4px; }
.connection .file { flex: 1; min-width: 0; }
.connection button { flex: none; font-size: 12px; padding: 4px 6px; }
.ppt-error { font-size: 12px; color: var(--warn); overflow-wrap: anywhere; }
.preload-progress { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--fg3); }
.preload-progress progress { flex: 1; min-width: 30px; max-width: 120px; height: 5px; accent-color: var(--accent); }
.previewhint { position: absolute; top: 8px; right: 10px; font-size: 11px; padding: 3px 7px; background: rgba(0, 0, 0, 0.7); color: #fff; border-color: rgba(255, 255, 255, 0.3); }
button:disabled { opacity: 0.45; cursor: not-allowed; }
.body { padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }
.file { font-size: 13px; color: var(--fg3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pchip { font-size: 13px; padding: 3px 10px; border-radius: 999px; white-space: nowrap; font-weight: 500; }
.pchip.live { background: var(--bad-soft); color: var(--bad); box-shadow: 0 0 12px rgba(255, 77, 109, 0.3); }
.pchip.idle { color: var(--fg3); border: 1px solid var(--line); }
.pbig { font-size: 14px; padding: 5px 12px; white-space: nowrap; }
.slide { aspect-ratio: 16 / 9; max-width: 100%; border-radius: 12px; border: 1px solid var(--line-strong); background: radial-gradient(120% 140% at 0% 0%, rgba(255, 255, 255, 0.14), transparent 50%), var(--sbg); color: #fff; position: relative; overflow: hidden; display: flex; flex-direction: column; justify-content: center; padding: 4% 6%; container-type: inline-size; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45); }
.slide .bar { position: absolute; left: 0; top: 0; bottom: 0; width: 6px; background: rgba(255, 255, 255, 0.35); }
.slide .st { font-size: clamp(18px, 7.5cqw, 56px); font-weight: 700; line-height: 1.25; text-wrap: balance; }
.slide .ss { font-size: clamp(12px, 3.4cqw, 24px); opacity: 0.85; margin-top: 2cqw; }
.slide .song { position: absolute; left: 12px; bottom: 8px; font-size: clamp(11px, 2.4cqw, 16px); background: rgba(0, 0, 0, 0.35); padding: 2px 8px; border-radius: 999px; }
.slide .sn { position: absolute; right: 10px; bottom: 8px; font-family: var(--f-mono); font-size: clamp(11px, 2.2cqw, 15px); background: rgba(0, 0, 0, 0.7); padding: 2px 6px; border-radius: 4px; }
.slide.black { background: #000; border-color: var(--line); align-items: center; }
.slide.live-monitor { padding: 0; background: #07080f; }
.popup-active { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; gap: 8px; font-size: 14px; color: var(--fg2); padding: 16px; text-align: center; }
.popup-retract { font-size: 13px; padding: 4px 12px; border-color: var(--accent); color: var(--accent); }
.blackhint { color: var(--fg3); font-size: 14px; }
.ctl { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.ctl button { height: 46px; padding: 0 16px; font-size: 16px; white-space: nowrap; }
.ctl .nx { flex: 1 1 120px; background: var(--grad); color: #fff; border: none; font-weight: 700; font-size: 17px; }
.ctl .nx:hover { background: var(--grad); filter: brightness(1.12); box-shadow: 0 0 18px rgba(139, 92, 255, 0.5); }
.ctl .on { background: var(--fg); color: var(--bg); border-color: var(--fg); }
.pg { text-align: center; font-size: 17px; font-weight: 500; white-space: nowrap; min-width: 56px; }
.nextline { font-size: 14px; color: var(--fg2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.thumbs { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 6px; }
.thumb { flex: none; width: 112px; aspect-ratio: 16 / 9; border-radius: 7px; background: var(--sbg); border: 2px solid transparent; color: #fff; font-size: 11px; padding: 5px 7px; text-align: left; position: relative; overflow: hidden; line-height: 1.3; }
.thumb:hover { border-color: var(--fg3); background: var(--sbg); }
.thumb.on { border-color: var(--accent); box-shadow: 0 0 14px rgba(34, 211, 255, 0.5); }
.tn { position: absolute; right: 5px; bottom: 3px; font-family: var(--f-mono); background: rgba(0, 0, 0, 0.75); border-radius: 3px; padding: 1px 4px; }
.tm { position: absolute; left: 5px; bottom: 3px; background: rgba(0, 0, 0, 0.75); border-radius: 3px; padding: 1px 4px; }
.plink { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 14px; color: var(--fg2); background: var(--raise); border-radius: var(--r); padding: 10px 12px; }
.plink .sp { flex: 1; min-width: 0; }
.plink button { font-size: 14px; padding: 6px 12px; }
.plink b { color: var(--fg); font-weight: 700; }
.lk { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.lk input { accent-color: var(--hot); width: 17px; height: 17px; }
:global(.main.ppt-big) .thumb { width: 132px; }
:global(.main.ppt-big) .ctl button { height: 52px; font-size: 18px; }
</style>

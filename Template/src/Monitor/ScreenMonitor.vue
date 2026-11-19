<script setup lang="ts">
// 第二屏实时视频画面组件：承载 getDisplayMedia 视频流与断线/单屏状态提示。
import { computed, onMounted } from 'vue'
import { useMonitorStore } from '@/Monitor/MonitorStore'
import { useScreenStream } from '@/Monitor/useScreenStream'

const props = withDefaults(
  defineProps<{
    active?: boolean
    showPicker?: boolean
  }>(),
  {
    active: true,
    showPicker: true,
  },
)

const monitor = useMonitorStore()

const streamActive = computed(
  () =>
    props.active &&
    monitor.supported &&
    monitor.hasSecondScreen &&
    Boolean(monitor.selectedDisplayId),
)

const { videoEl, status, error, retry } = useScreenStream({
  active: streamActive,
  displayId: () => monitor.selectedDisplayId,
})

function onSelectDisplay(event: Event): void {
  const target = event.target as HTMLSelectElement
  monitor.selectDisplay(target.value || null)
}

onMounted(() => {
  void monitor.init()
})
</script>

<template>
  <div class="screen-monitor" :class="{ active: props.active }">
    <video ref="videoEl" class="screen-video" muted autoplay playsinline />

    <div
      v-if="status === 'streaming' && props.showPicker && monitor.displays.length >= 2"
      class="corner-picker"
    >
      <span class="live-dot" aria-hidden="true"></span>
      <select
        :value="monitor.selectedDisplayId ?? ''"
        aria-label="切换监看屏幕"
        @change="onSelectDisplay"
      >
        <option v-for="display in monitor.displays" :key="display.id" :value="display.id">
          {{ display.label }} ({{ display.width }}×{{ display.height }}){{ display.isMainWindow ? ' · 主控屏' : '' }}
        </option>
      </select>
    </div>

    <div v-if="monitor.unavailableReason || status !== 'streaming'" class="monitor-overlay" role="status">
      <template v-if="monitor.unavailableReason">
        <p class="overlay-title">{{ monitor.unavailableReason }}</p>
        <p v-if="monitor.supported && monitor.displaysLoaded" class="overlay-sub">
          接入扩展屏并将显示模式设为「扩展」后会自动显示画面
        </p>
      </template>

      <template v-else-if="status === 'ended' || status === 'error'">
        <p class="overlay-title">{{ error ?? '屏幕捕获已中断' }}</p>
        <button type="button" class="retry-btn" @click="retry()">重试连接</button>
      </template>

      <template v-else-if="props.active">
        <p class="overlay-title">正在连接第二屏画面…</p>
        <p v-if="monitor.selectedDisplay" class="overlay-sub">
          {{ monitor.selectedDisplay.label }} · {{ monitor.selectedDisplay.width }}×{{ monitor.selectedDisplay.height }}
        </p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.screen-monitor {
  position: relative;
  width: 100%;
  height: 100%;
  background: #07080f;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.screen-video {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: contain;
  background: #000;
}

.corner-picker {
  position: absolute;
  top: 8px;
  right: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(10, 9, 24, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.16);
  opacity: 0.6;
  transition: opacity 0.15s ease;
}

.corner-picker:hover,
.corner-picker:focus-within {
  opacity: 1;
}

.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--bad, #ff4d6d);
  box-shadow: 0 0 8px rgba(255, 77, 109, 0.75);
  flex: none;
}

.corner-picker select {
  background: transparent;
  color: #fff;
  border: none;
  font-size: 11px;
  max-width: 190px;
  cursor: pointer;
}

.corner-picker select option {
  background: #141326;
  color: #fff;
}

.monitor-overlay {
  position: absolute;
  inset: 0;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: center;
  background: rgba(8, 9, 18, 0.86);
  color: var(--fg, #eef0ff);
}

.overlay-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
}

.overlay-sub {
  margin: 0;
  font-size: 12px;
  color: var(--fg3, #8f95b8);
}

.retry-btn {
  margin-top: 4px;
  padding: 6px 14px;
  font-size: 13px;
  border-radius: 6px;
  border: 1px solid var(--line-strong, rgba(255, 255, 255, 0.2));
  background: var(--raise, #1c1d33);
  color: var(--fg, #eef0ff);
  cursor: pointer;
}

.retry-btn:hover {
  border-color: var(--accent, #22d3ff);
}
</style>

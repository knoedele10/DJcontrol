<script setup lang="ts">
// 置顶小窗独立页面（#/monitor）：提供可拖拽标题栏、多屏选择与收回关闭按钮。
import { onBeforeUnmount, onMounted } from 'vue'
import { useMonitorStore } from '@/Monitor/MonitorStore'
import ScreenMonitor from '@/Monitor/ScreenMonitor.vue'

const monitor = useMonitorStore()

function onSelectDisplay(event: Event): void {
  const target = event.target as HTMLSelectElement
  monitor.selectDisplay(target.value || null)
}

onMounted(() => {
  void monitor.init()
})

onBeforeUnmount(() => {
  monitor.dispose()
})
</script>

<template>
  <main class="monitor-page" aria-label="第二屏实时监看小窗">
    <header class="monitor-bar">
      <div class="bar-title">
        <span class="bar-dot" aria-hidden="true"></span>
        <span class="bar-label">
          {{ monitor.selectedDisplay ? monitor.selectedDisplay.label : '第二屏监看' }}
        </span>
        <span v-if="monitor.selectedDisplay" class="bar-meta mono">
          {{ monitor.selectedDisplay.width }}×{{ monitor.selectedDisplay.height }}
        </span>
      </div>

      <div class="bar-actions">
        <select
          v-if="monitor.displays.length > 2"
          :value="monitor.selectedDisplayId ?? ''"
          aria-label="选择监看屏幕"
          @change="onSelectDisplay"
        >
          <option v-for="display in monitor.displays" :key="display.id" :value="display.id">
            {{ display.label }} ({{ display.width }}×{{ display.height }}){{ display.isMainWindow ? ' · 主控屏' : '' }}
          </option>
        </select>

        <button
          type="button"
          class="retract-btn"
          title="关闭置顶小窗并在主面板恢复"
          @click="monitor.closePopup()"
        >
          收回
        </button>
      </div>
    </header>

    <div class="monitor-stage">
      <ScreenMonitor :active="true" :show-picker="false" />
    </div>
  </main>
</template>

<style scoped>
.monitor-page {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #0a0918;
  color: var(--fg, #eef0ff);
  overflow: hidden;
}

.monitor-bar {
  height: 32px;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 8px 0 12px;
  background: rgba(16, 15, 32, 0.96);
  border-bottom: 1px solid var(--line, rgba(255, 255, 255, 0.1));
  -webkit-app-region: drag;
  user-select: none;
}

.bar-title {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  font-size: 12px;
}

.bar-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--bad, #ff4d6d);
  box-shadow: 0 0 8px rgba(255, 77, 109, 0.7);
  flex: none;
}

.bar-label {
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bar-meta {
  font-size: 11px;
  color: var(--fg3, #8f95b8);
  flex: none;
}

.bar-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: none;
  -webkit-app-region: no-drag;
}

.bar-actions select {
  height: 22px;
  max-width: 165px;
  font-size: 11px;
  padding: 0 6px;
  border-radius: 4px;
  border: 1px solid var(--line, rgba(255, 255, 255, 0.14));
  background: var(--raise, #1c1d33);
  color: var(--fg, #eef0ff);
  cursor: pointer;
}

.retract-btn {
  height: 22px;
  padding: 0 10px;
  font-size: 11px;
  border-radius: 4px;
  border: 1px solid var(--line-strong, rgba(255, 255, 255, 0.22));
  background: var(--raise, #1c1d33);
  color: var(--fg, #eef0ff);
  cursor: pointer;
  white-space: nowrap;
}

.retract-btn:hover {
  border-color: var(--accent, #22d3ff);
  color: var(--accent, #22d3ff);
}

.monitor-stage {
  flex: 1;
  min-height: 0;
  width: 100%;
  position: relative;
}
</style>

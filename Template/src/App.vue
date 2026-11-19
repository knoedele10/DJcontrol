<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, watch } from 'vue'
import { routeLocationKey } from 'vue-router'
import { usePptStore } from '@/Ppt/PptStore'
import { useLibraryStore } from '@/Library/LibraryStore'
import { usePlaybackStore } from '@/Playback/PlaybackStore'
import { useConnectionStore } from '@/Diagnostics/ConnectionStore'
import ConnectionBanner from '@/Diagnostics/ConnectionBanner.vue'
import TutorialOverlay from '@/Tutorial/TutorialOverlay.vue'
import { useTutorialStore } from '@/Tutorial/TutorialStore'

const ppt = usePptStore()
const library = useLibraryStore()
const playback = usePlaybackStore()
const connection = useConnectionStore()
const tutorial = useTutorialStore()

const route = inject(routeLocationKey, null)
const isMonitorWindow = computed(
  () =>
    route?.name === 'monitor' ||
    route?.path === '/monitor' ||
    /^#\/monitor(?:$|[/?])/.test(globalThis.window?.location?.hash ?? ''),
)

let syncing = false

function startMainSync(): void {
  if (syncing) return
  syncing = true
  void tutorial.init()
  connection.start()
  ppt.startSync()
  library.startSync()
  playback.startSync()
}

function stopMainSync(): void {
  if (!syncing) return
  syncing = false
  connection.stop()
  ppt.stopSync()
  library.stopSync()
  playback.stopSync()
}

onMounted(() => {
  if (!isMonitorWindow.value) {
    startMainSync()
  }
})

watch(isMonitorWindow, (monitorOnly) => {
  if (monitorOnly) {
    stopMainSync()
  } else {
    startMainSync()
  }
})

onBeforeUnmount(stopMainSync)
</script>

<template>
  <div class="application-shell">
    <ConnectionBanner v-if="!isMonitorWindow" />
    <RouterView />
    <TutorialOverlay v-if="!isMonitorWindow" />
  </div>
</template>

<style scoped>
.application-shell { height: 100%; display: flex; flex-direction: column; }
/* 页面占满宽度：左右自动外边距会让弹性子项缩成内容宽度。能否超出一屏高由页面自己的 min-height 决定。 */
.application-shell > :last-child { flex: 1; width: 100%; }
</style>

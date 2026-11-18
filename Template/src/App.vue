<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
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
onMounted(() => { void tutorial.init() })
onMounted(connection.start)
onMounted(ppt.startSync)
onMounted(library.startSync)
onMounted(playback.startSync)
onBeforeUnmount(() => { connection.stop(); ppt.stopSync(); library.stopSync(); playback.stopSync() })
</script>

<template>
  <div class="application-shell">
    <ConnectionBanner />
    <RouterView />
    <TutorialOverlay />
  </div>
</template>

<style scoped>
.application-shell { height: 100%; display: flex; flex-direction: column; }
/* 页面占满宽度：左右自动外边距会让弹性子项缩成内容宽度。能否超出一屏高由页面自己的 min-height 决定。 */
.application-shell > :last-child { flex: 1; width: 100%; }
</style>

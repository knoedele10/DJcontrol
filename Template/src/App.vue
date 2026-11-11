<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { usePptStore } from '@/Ppt/PptStore'
import { useLibraryStore } from '@/Library/LibraryStore'
import { usePlaybackStore } from '@/Playback/PlaybackStore'

const ppt = usePptStore()
const library = useLibraryStore()
const playback = usePlaybackStore()
onMounted(ppt.startSync)
onMounted(library.startSync)
onMounted(playback.startSync)
onBeforeUnmount(() => { ppt.stopSync(); library.stopSync(); playback.stopSync() })
</script>

<template>
  <RouterView />
</template>

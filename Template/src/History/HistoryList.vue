<script setup lang="ts">
// 本场已播记录（最近 6 首，倒序）。放在左侧栏底部。
import { computed } from 'vue'
import { useQueueStore } from '@/Queue/QueueStore'
import { fmtClock } from '@/Common/Format'

const queue = useQueueStore()
const recent = computed(() => queue.history.slice().reverse().slice(0, 6))
</script>

<template>
  <div class="hist">
    <div class="lbl head">本场已播 <span v-if="queue.history.length" class="mono">· {{ queue.history.length }} 首</span></div>
    <div v-for="(h, i) in recent" :key="i" class="hrow" :class="{ latest: i === 0 }">
      <span class="mono">{{ fmtClock(h.played_at) }}</span><span class="txt">{{ h.title }}<small> - {{ h.artist }}</small></span>
    </div>
    <div v-if="!recent.length" class="hrow none">还没有播放记录</div>
  </div>
</template>

<style scoped>
.hist { border-top: 1px solid var(--line); padding: 12px 16px 14px; margin-top: auto; }
.head { margin-bottom: 8px; }
.hrow { display: grid; grid-template-columns: 46px minmax(0, 1fr); gap: 8px; font-size: 13px; color: var(--fg2); padding: 4px 0; }
.hrow.latest { color: var(--fg); }
.hrow small { color: var(--fg3); font-size: 12px; }
.hrow.none { grid-template-columns: 1fr; color: var(--fg3); }
.txt { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>

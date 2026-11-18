<script setup lang="ts">
import { useConnectionStore } from '@/Diagnostics/ConnectionStore'
const connection = useConnectionStore()
</script>

<template>
  <aside v-if="connection.state?.backend_connected === false" class="connection-banner" role="alert">
    <div>
      <strong>控制服务未连接</strong>
      <p>{{ connection.state.message }}</p>
      <p v-if="connection.state.mode === 'proxy'">在运行酷狗的 Windows 电脑中执行：<code>.\Scripts\StartDocker.ps1</code></p>
    </div>
    <button type="button" :disabled="connection.checking" @click="connection.check()">{{ connection.checking ? '正在检查…' : '检查连接' }}</button>
  </aside>
</template>

<style scoped>
.connection-banner { margin: 12px 20px 0; padding: 12px 16px; display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--warn); background: var(--warn-soft); border: 1px solid var(--warn); border-radius: 10px; }
.connection-banner p { margin: 5px 0 0; font-size: 13px; overflow-wrap: anywhere; }
.connection-banner code { color: var(--fg); }
.connection-banner button { flex-shrink: 0; padding: 7px 12px; }
@media (max-width: 720px) { .connection-banner { margin-inline: 12px; align-items: flex-start; flex-direction: column; } }
</style>

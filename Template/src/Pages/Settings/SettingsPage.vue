<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { Diagnostics } from '@/Common/Types'
import { fetchDiagnostics, selectController } from '@/Diagnostics/DiagnosticsApi'
const desktopApp = typeof window !== 'undefined' ? window.desktopApp : undefined
const diagnostics = ref<Diagnostics | null>(null)
const loading = ref(false)
const error = ref('')
async function refresh(name?: 'mock' | 'kugou') {
  loading.value = true; error.value = ''
  try { diagnostics.value = name ? await selectController(name) : await fetchDiagnostics() }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '诊断失败' }
  finally { loading.value = false }
}
onMounted(() => refresh())
</script>
<template>
  <div class="page">
    <header class="top"><RouterLink to="/" class="back">← 返回面板</RouterLink><h1>设置与连接诊断</h1></header>
    <p v-if="error" role="alert">{{ error }}</p>
    <section class="col">
      <div class="col-h"><h2>控制方式</h2></div>
      <div class="body">
        <label class="opt"><input type="radio" :checked="diagnostics?.controller === 'mock'" :disabled="loading" @change="refresh('mock')" /> 模拟控制器</label>
        <label class="opt"><input type="radio" :checked="diagnostics?.controller === 'kugou'" :disabled="loading" @change="refresh('kugou')" /> 酷狗音乐</label>
      </div>
    </section>
    <section v-if="diagnostics" class="col">
      <div class="col-h"><h2>酷狗连接</h2></div>
      <div class="body kv">
        <span>检测到的版本</span><b>{{ diagnostics.kugou.version ?? '未检测' }}</b>
        <span>适配档案</span><b>{{ diagnostics.kugou.profile ?? '未匹配' }}</b>
        <span>进程状态</span><b>{{ diagnostics.kugou.running ? '运行中' : '未检测到酷狗连接' }}</b>
        <template v-if="diagnostics.kugou.error">
          <span>自检说明</span><b class="error-note">{{ diagnostics.kugou.error }}</b>
        </template>
      </div>
    </section>
    <section class="col">
      <div class="col-h"><h2>能力自检</h2><button :disabled="loading" @click="refresh()">重新检测</button></div>
      <div v-if="loading" class="empty">正在检测…</div>
      <table v-else-if="diagnostics" class="caps">
        <thead><tr><th>能力</th><th>状态</th><th>说明</th></tr></thead>
        <tbody><tr v-for="c in diagnostics.capabilities" :key="c.name"><td>{{ c.label }}</td><td>{{ c.supported ? (c.verified ? '已验证' : '待验证') : '不可用' }}</td><td class="note">{{ c.note }}</td></tr></tbody>
      </table>
    </section>
    <section v-if="desktopApp?.isElectron" class="col">
      <div class="col-h"><h2>桌面应用</h2></div>
      <div class="body">
        <div class="kv">
          <span>运行容器</span><b>Electron {{ desktopApp.versions.electron }}（Chromium {{ desktopApp.versions.chrome }}）</b>
          <span>当前平台</span><b>{{ desktopApp.platform }}</b>
        </div>
        <div class="desk-acts">
          <button type="button" class="desk-btn" @click="desktopApp.toggleFullscreen()">切换全屏 (F11)</button>
          <button type="button" class="desk-btn" @click="desktopApp.openLogsDir()">打开日志目录</button>
          <button type="button" class="desk-btn" @click="desktopApp.restartBackend()">重启控制引擎</button>
        </div>
      </div>
    </section>
  </div>
</template>
<style scoped>
.page { max-width: 880px; margin: 0 auto; padding: 20px max(16px, env(safe-area-inset-right, 0px)) 40px max(16px, env(safe-area-inset-left, 0px)); display: flex; flex-direction: column; gap: 14px; }
.top { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.top h1 { font-size: 20px; margin: 0; flex: 1; }
.back { color: var(--accent); text-decoration: none; font-size: 13px; }
.body { padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; }
.opt { display: flex; align-items: center; gap: 8px; }
.opt.disabled { color: var(--fg3); }
.hint { font-size: 12px; color: var(--fg3); }
.kv { display: grid; grid-template-columns: 140px 1fr; gap: 8px 14px; font-size: 13px; color: var(--fg2); }
.kv b { color: var(--fg); font-weight: 500; }
.error-note { color: var(--bad) !important; }
.ref { font-size: 12px; padding: 4px 10px; }
.caps { width: 100%; border-collapse: collapse; font-size: 13px; }
.caps th { text-align: left; font-weight: 500; color: var(--fg3); font-size: 12px; padding: 10px 14px; border-bottom: 1px solid var(--line); }
.caps td { padding: 10px 14px; border-bottom: 1px solid var(--line); }
.note { color: var(--fg2); font-size: 12px; }
.st { font-size: 12px; padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
.st.ok { background: var(--ok-soft); color: var(--ok); }
.st.wait { background: var(--warn-soft); color: var(--warn); }
.st.no { background: var(--bad-soft); color: var(--bad); }
.desk-acts { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 4px; }
.desk-btn { font-size: 13px; padding: 6px 12px; }
</style>

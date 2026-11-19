<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { Diagnostics } from '@/Common/Types'
import { fetchDiagnostics, selectController } from '@/Diagnostics/DiagnosticsApi'
import { refreshPlaylist } from '@/Playback/PlayerApi'
import { usePlaybackStore } from '@/Playback/PlaybackStore'
import { useConnectionStore } from '@/Diagnostics/ConnectionStore'
const playback = usePlaybackStore()
const connection = useConnectionStore()
const desktopApp = typeof window !== 'undefined' ? window.desktopApp : undefined
const diagnostics = ref<Diagnostics | null>(null)
const loading = ref(false)
const error = ref('')
const playlistName = ref('')
const playlistMessage = ref('')
const checkedAt = ref('')
async function refresh(name?: 'mock' | 'kugou') {
  if (loading.value || (name && playback.busy)) return
  loading.value = true; error.value = ''
  try {
    await connection.check()
    if (connection.state?.backend_connected === false) throw new Error(connection.state.message)
    diagnostics.value = name ? await selectController(name) : await fetchDiagnostics()
    playlistName.value = diagnostics.value.playlist.name
    playback.applyPlaylist(diagnostics.value.playlist)
    checkedAt.value = new Date().toLocaleTimeString()
  }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '诊断失败' }
  finally { loading.value = false }
}
async function savePlaylist() {
  if (!diagnostics.value || loading.value || playback.busy) return
  loading.value = true; error.value = ''; playlistMessage.value = ''
  try {
    diagnostics.value = await selectController(diagnostics.value.controller, playlistName.value)
    playlistName.value = diagnostics.value.playlist.name
    diagnostics.value = await fetchDiagnostics()
    playback.applyPlaylist(diagnostics.value.playlist)
    playlistMessage.value = playlistName.value ? '配置已保存，探测结果见下方' : '已关闭歌单功能'
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '歌单配置失败' }
  finally { loading.value = false }
}
async function inspectPlaylist() {
  if (loading.value || playback.busy) return
  loading.value = true; error.value = ''
  try {
    await refreshPlaylist()
    diagnostics.value = await fetchDiagnostics()
    playback.applyPlaylist(diagnostics.value.playlist)
    playlistMessage.value = '已重新检测歌单与加歌菜单'
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '歌单检测失败' }
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
        <label class="opt"><input type="radio" :checked="diagnostics?.controller === 'mock'" :disabled="loading || playback.busy" @change="refresh('mock')" /> 模拟控制器</label>
        <label class="opt"><input type="radio" :checked="diagnostics?.controller === 'kugou'" :disabled="loading || playback.busy" @change="refresh('kugou')" /> 酷狗音乐</label>
      </div>
    </section>
    <section class="col">
      <div class="col-h"><h2>演出歌单</h2></div>
      <div class="body playlist-settings">
        <label for="playlist-name">酷狗中的歌单名称（留空关闭）</label>
        <div class="playlist-actions">
          <input id="playlist-name" v-model="playlistName" maxlength="100" placeholder="演出歌单" :disabled="loading || playback.busy" @keydown.enter="savePlaylist" />
          <button :disabled="loading || playback.busy" @click="savePlaylist">保存并检测</button>
          <button :disabled="loading || playback.busy || !diagnostics?.playlist.name || diagnostics?.controller !== 'kugou'" @click="inspectPlaylist">刷新歌单</button>
        </div>
        <p>请先在酷狗创建歌单并保持主窗口打开（不要最小化）。可以只填歌单名的一部分：检测时会在酷狗侧栏里找唯一匹配的歌单，并换成完整名称。逐首加歌会试听切歌，完成后暂停，请在演出前使用。</p>
        <p v-if="playlistMessage" role="status">{{ playlistMessage }}</p>
        <p v-if="diagnostics?.playlist">{{ diagnostics.playlist.note }}</p>
        <p v-if="diagnostics?.playlist.add_note">加歌：{{ diagnostics.playlist.add_note }}</p>
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
      <div class="col-h"><h2>能力自检</h2><button :disabled="loading" @click="refresh()">{{ loading ? '正在检测…' : '重新检测' }}</button></div>
      <div v-if="loading" class="empty" role="status">正在检测控制服务与酷狗能力…</div>
      <p v-else-if="checkedAt" class="body hint" role="status">最近检测：{{ checkedAt }}</p>
      <table v-if="!loading && diagnostics" class="caps">
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
.playlist-settings { display: grid; gap: 10px; }
.playlist-settings p { margin: 0; color: var(--fg2); font-size: 13px; }
.playlist-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.playlist-actions input { flex: 1; min-width: 160px; padding: 7px 10px; }
.playlist-actions button { padding: 7px 12px; }
</style>

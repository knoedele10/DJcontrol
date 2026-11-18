<script setup lang="ts">
// 左侧栏：活动大组 → 分类。支持新建、重命名、删除（二次确认），以及把歌曲卡片拖到分类上。
import { computed, ref } from 'vue'
import InlineInput from '@/Common/InlineInput.vue'
import HistoryList from '@/History/HistoryList.vue'
import { useLibraryStore } from '@/Library/LibraryStore'
import { usePlaybackStore } from '@/Playback/PlaybackStore'

const library = useLibraryStore()
const playback = usePlaybackStore()

type Target = { type: 'group' | 'cat'; id: string }
const adding = ref<'group' | 'cat' | null>(null)
const editing = ref<Target | null>(null)
const confirmKey = ref<string | null>(null)
const dropId = ref<string | null>(null)
let confirmTimer = 0

const group = computed(() => library.activeGroup)
const allCount = computed(() => (group.value ? library.groupSongIds(group.value).length : 0))

function startAdd(kind: 'group' | 'cat') {
  adding.value = kind
  editing.value = null
}
async function commitAdd(name: string) {
  if (adding.value === 'group') {
    const group = await library.addGroup(name)
    if (group) playback.log(`新建活动组：${name}`)
  } else if (adding.value === 'cat' && group.value) {
    const c = await library.addCategory(group.value.id, name)
    if (c) {
      library.selectCategory(c.id)
      library.manageMode = true
      playback.log(`新建分类：${group.value.name} › ${name}`)
    }
  }
  adding.value = null
}
async function commitRename(name: string) {
  const t = editing.value
  if (t?.type === 'group') await library.renameGroup(t.id, name)
  else if (t && group.value) await library.renameCategory(group.value.id, t.id, name)
  editing.value = null
}
function askDelete(key: string) {
  confirmKey.value = key
  clearTimeout(confirmTimer)
  confirmTimer = window.setTimeout(() => (confirmKey.value = null), 3000)
}
async function confirmDelete(t: Target) {
  confirmKey.value = null
  if (t.type === 'group') {
    const name = library.findGroup(t.id)?.name
    if (await library.deleteGroup(t.id)) playback.log(`已删除活动组：${name}`)
  } else if (group.value) {
    const name = group.value.categories.find((c) => c.id === t.id)?.name
    if (await library.deleteCategory(group.value.id, t.id)) playback.log(`已删除分类：${name}（歌曲仍在曲库）`)
  }
}
const isEditing = (type: Target['type'], id: string) => editing.value?.type === type && editing.value.id === id

// ---------- 拖拽 ----------
function onDragOver(e: DragEvent, catId: string) {
  if (!e.dataTransfer?.types.includes('text/plain')) return
  e.preventDefault()
  e.dataTransfer.dropEffect = 'copy'
  dropId.value = catId
}
async function onDrop(e: DragEvent, catId: string) {
  e.preventDefault()
  dropId.value = null
  const songId = Number(e.dataTransfer?.getData('text/plain'))
  const g = group.value
  const song = library.songById(songId)
  if (!g || !song) return
  const cat = g.categories.find((c) => c.id === catId)
  if (await library.addToCategory(g.id, catId, songId)) playback.log(`加入 ${g.name} › ${cat?.name}：${song.title}`)
  else playback.log(`「${song.title}」已在 ${g.name} › ${cat?.name}`)
}
</script>

<template>
  <aside class="col side" data-tour="sidebar">
    <div class="col-h"><h2>活动分组</h2></div>

    <div class="groups" data-tour="groups">
      <template v-for="g in library.groups" :key="g.id">
        <div v-if="isEditing('group', g.id)" class="grp on">
          <InlineInput :initial="g.name" placeholder="组名" @commit="commitRename" @cancel="editing = null" />
        </div>
        <div v-else class="grp" :class="{ on: g.id === library.activeGroup?.id }" tabindex="0" @click="library.selectGroup(g.id)" @keydown.enter="library.selectGroup(g.id)">
          <span class="gi" :style="{ background: g.color }">{{ g.name.slice(0, 1) }}</span>
          <span class="n">{{ g.name }}</span>
          <span class="c mono">{{ g.categories.length }} 类</span>
          <div v-if="confirmKey === 'group:' + g.id" class="ops keep">
            <button class="danger" @click.stop="confirmDelete({ type: 'group', id: g.id })">确认删除</button>
          </div>
          <div v-else class="ops">
            <button title="重命名" aria-label="重命名" @click.stop="editing = { type: 'group', id: g.id }; adding = null">✎</button>
            <button title="删除" aria-label="删除" @click.stop="askDelete('group:' + g.id)">✕</button>
          </div>
        </div>
      </template>
      <div v-if="adding === 'group'" class="grp">
        <InlineInput placeholder="新组名，如：毕业晚会" @commit="commitAdd" @cancel="adding = null" />
      </div>
      <button v-else class="addbtn" @click="startAdd('group')">＋ 新建活动组</button>
    </div>

    <div class="divider"></div>
    <div class="cat-h"><span class="lbl">{{ group ? `${group.name} · 分类` : '分类' }}</span></div>

    <div v-if="!group" class="empty">先新建一个活动组。</div>
    <div v-else class="scenes" data-tour="categories">
      <div class="scene" :class="{ on: library.activeCategoryId === 'all' }" tabindex="0" @click="library.selectCategory('all')">
        <span class="dot" style="background: var(--fg3); box-shadow: none"></span><span class="n">全部</span><span class="c mono">{{ allCount }}</span>
      </div>
      <template v-for="(c, i) in group.categories" :key="c.id">
        <div v-if="isEditing('cat', c.id)" class="scene on">
          <InlineInput :initial="c.name" placeholder="分类名" @commit="commitRename" @cancel="editing = null" />
        </div>
        <div
          v-else
          class="scene"
          :class="{ on: library.activeCategoryId === c.id, drop: dropId === c.id }"
          tabindex="0"
          :title="`快捷键 ${i + 1}`"
          @click="library.selectCategory(c.id)"
          @keydown.enter="library.selectCategory(c.id)"
          @dragover="onDragOver($event, c.id)"
          @dragleave="dropId = dropId === c.id ? null : dropId"
          @drop="onDrop($event, c.id)"
        >
          <span class="dot" :style="{ background: c.color, color: c.color }"></span>
          <span class="n">{{ c.name }}</span>
          <span class="c mono">{{ c.song_ids.length }}</span>
          <div v-if="confirmKey === 'cat:' + c.id" class="ops keep">
            <button class="danger" @click.stop="confirmDelete({ type: 'cat', id: c.id })">确认删除</button>
          </div>
          <div v-else class="ops">
            <button title="重命名" aria-label="重命名" @click.stop="editing = { type: 'cat', id: c.id }; adding = null">✎</button>
            <button title="删除" aria-label="删除" @click.stop="askDelete('cat:' + c.id)">✕</button>
          </div>
        </div>
      </template>
      <div v-if="adding === 'cat'" class="scene">
        <InlineInput placeholder="新分类名，如：开场" @commit="commitAdd" @cancel="adding = null" />
      </div>
      <button v-else class="addbtn" @click="startAdd('cat')">＋ 新建分类</button>
    </div>

    <HistoryList />
  </aside>
</template>

<style scoped>
.side { overflow-y: auto; }
.groups { display: flex; flex-direction: column; gap: 5px; padding: 12px 10px 8px; }
.grp { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid transparent; border-radius: var(--r); cursor: pointer; min-width: 0; font-size: 16px; }
.grp:hover { background: var(--raise); }
.grp.on { background: var(--raise); border-color: var(--line-strong); box-shadow: inset 3px 0 0 var(--hot); }
.gi { width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center; font-size: 14px; font-weight: 700; color: #0a0918; flex: none; }
.n { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.grp .n { font-weight: 700; }
.c { font-size: 12px; color: var(--fg3); }
.ops { display: none; gap: 3px; }
.grp:hover .ops, .scene:hover .ops, .ops.keep { display: flex; }
.ops button { width: 26px; height: 26px; padding: 0; font-size: 13px; border-color: transparent; color: var(--fg2); line-height: 1; }
.ops button:hover { border-color: var(--line-strong); }
.ops button.danger { color: var(--bad); background: var(--bad-soft); width: auto; padding: 0 8px; }
.addbtn { border: 1px dashed var(--line-strong); color: var(--fg2); padding: 9px 12px; text-align: left; width: 100%; font-size: 14px; }
.addbtn:hover { color: var(--fg); border-color: var(--hot); }
.divider { height: 1px; background: var(--line); margin: 6px 16px; }
.cat-h { display: flex; align-items: center; gap: 8px; padding: 8px 16px 4px; }
.scenes { padding: 4px 10px 10px; display: flex; flex-direction: column; gap: 4px; }
.scene { display: flex; align-items: center; gap: 12px; border: 1px solid transparent; border-radius: var(--r); padding: 10px 12px; cursor: pointer; min-width: 0; font-size: 15px; }
.scene:hover { background: var(--raise); }
.scene.on { background: var(--accent-soft); border-color: rgba(34, 211, 255, 0.55); box-shadow: 0 0 14px rgba(34, 211, 255, 0.15); }
.scene.drop { background: var(--ok-soft); border-color: var(--ok); border-style: dashed; }
.dot { width: 12px; height: 12px; border-radius: 4px; flex: none; box-shadow: 0 0 8px currentColor; }
.scene .c { font-size: 13px; }
@media (max-width: 1080px), (max-height: 700px) {
  .side { overflow: visible; }
  .groups, .scenes { flex-direction: row; flex-wrap: wrap; }
  .addbtn { width: auto; }
}
@media (hover: none), (max-width: 720px) { .ops { display: flex; } }
</style>

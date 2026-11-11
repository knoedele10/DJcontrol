<script setup lang="ts">
// "设置分组"弹出面板：列出所有活动组和分类，点分类直接加入 / 移出，可就地新建分类。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import InlineInput from '@/Common/InlineInput.vue'
import { useLibraryStore } from '@/Library/LibraryStore'
import { usePlaybackStore } from '@/Playback/PlaybackStore'
import { useUiStore } from '@/Common/UiStore'

const library = useLibraryStore()
const playback = usePlaybackStore()
const ui = useUiStore()

const el = ref<HTMLElement>()
const pos = ref({ left: 0, top: 0 })
const addingIn = ref<string | null>(null)

const song = computed(() => (ui.groupPopover ? library.songById(ui.groupPopover.songId) : null))

async function place() {
  const p = ui.groupPopover
  if (!p || !el.value) return
  await nextTick()
  const anchor = document.body.contains(p.anchor) ? p.anchor : document.querySelector<HTMLElement>(`[data-song-card="${p.songId}"] [aria-label="设置分组"]`)
  if (!anchor) return
  const r = anchor.getBoundingClientRect()
  const w = el.value.offsetWidth
  const h = el.value.offsetHeight
  const left = Math.max(16, Math.min(r.right - w, innerWidth - w - 16))
  let top = r.bottom + 6
  if (top + h > innerHeight - 16) top = Math.max(16, r.top - h - 6)
  pos.value = { left, top }
}
watch(() => ui.groupPopover, () => { addingIn.value = null; place() }, { flush: 'post' })

async function toggle(groupId: string, categoryId: string) {
  if (!song.value) return
  const g = library.findGroup(groupId)
  const c = g?.categories.find((x) => x.id === categoryId)
  const added = await library.toggleMembership(groupId, categoryId, song.value.id)
  playback.log(`${added ? '加入' : '移出'} ${g?.name} › ${c?.name}：${song.value.title}`)
}
async function commitNewCategory(groupId: string, name: string) {
  if (!song.value) return
  const g = library.findGroup(groupId)
  const category = await library.addCategory(groupId, name, [song.value.id])
  if (category) playback.log(`新建分类并加入：${g?.name} › ${name}`)
  addingIn.value = null
  place()
}

function onDocClick(e: MouseEvent) {
  if (!ui.groupPopover) return
  const t = e.target as HTMLElement
  if (el.value?.contains(t) || t.closest('[aria-label="设置分组"], [aria-label="收进曲库并设置分组"]')) return
  ui.closeGroupPopover()
}
const close = () => ui.closeGroupPopover()
onMounted(() => {
  document.addEventListener('click', onDocClick, true)
  addEventListener('resize', close)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick, true)
  removeEventListener('resize', close)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="song" ref="el" class="pop" role="dialog" aria-label="设置分组" :style="{ left: pos.left + 'px', top: pos.top + 'px' }">
      <div class="pop-h">
        <div class="t">{{ song.title }}<div class="a">{{ song.artist }} · 点分类直接加入 / 移出</div></div>
        <button class="ib" aria-label="关闭" @click="close">✕</button>
      </div>
      <div v-if="!library.groups.length" class="pop-g muted">还没有活动组，先在左侧新建一个。</div>
      <div v-for="g in library.groups" :key="g.id" class="pop-g">
        <div class="gn"><i :style="{ background: g.color }"></i>{{ g.name }}</div>
        <div class="pop-cats">
          <button
            v-for="c in g.categories"
            :key="c.id"
            class="cchip"
            :class="{ on: c.song_ids.includes(song.id) }"
            :style="{ '--cc': c.color }"
            @click="toggle(g.id, c.id)"
          >{{ c.name }}</button>
          <InlineInput v-if="addingIn === g.id" class="newcat" placeholder="新分类名" @commit="commitNewCategory(g.id, $event)" @cancel="addingIn = null" />
          <button v-else class="cchip add" @click="addingIn = g.id">＋ 新分类</button>
        </div>
      </div>
      <div class="pop-foot">也可以直接把卡片拖到左侧的分类上。</div>
    </div>
  </Teleport>
</template>

<style scoped>
.pop { position: fixed; z-index: 50; width: 340px; font-size: 15px; max-width: calc(100vw - 32px); max-height: min(460px, calc(100vh - 32px)); overflow: auto; background: var(--raise); border: 1px solid var(--line-strong); border-radius: 12px; box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45); padding: 12px; }
.pop-h { display: flex; align-items: flex-start; gap: 8px; margin-bottom: 10px; }
.pop-h .t { flex: 1; min-width: 0; font-weight: 700; }
.pop-h .a { font-size: 12px; color: var(--fg2); font-weight: 400; }
.pop-g { padding: 8px 0; border-top: 1px solid var(--line); }
.pop-g.muted { color: var(--fg3); font-size: 12px; }
.gn { font-size: 12px; color: var(--fg2); margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
.gn i { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
.pop-cats { display: flex; flex-wrap: wrap; gap: 6px; }
.cchip { font-size: 14px; padding: 6px 12px; border-radius: 999px; border: 1px solid var(--line-strong); color: var(--fg2); display: inline-flex; align-items: center; gap: 5px; }
.cchip.on { color: var(--fg); border-color: var(--cc); background: color-mix(in srgb, var(--cc) 22%, transparent); }
.cchip.on::before { content: '✓'; color: var(--cc); font-weight: 700; }
.cchip.add { border-style: dashed; }
.newcat { height: 28px; width: 130px; font-size: 12px; }
.pop-foot { font-size: 11px; color: var(--fg3); border-top: 1px solid var(--line); padding-top: 8px; margin-top: 4px; }
</style>

<script setup lang="ts">
// 中间栏：搜索框 + 当前分类的歌曲网格；有搜索词时切换为"曲库中 + 酷狗搜索"结果；管理模式下编辑分类成员。
import { computed, ref } from 'vue'
import SongCard from '@/Library/SongCard.vue'
import KugouCard from '@/Library/KugouCard.vue'
import { useLibraryStore } from '@/Library/LibraryStore'
import { useQueueStore } from '@/Queue/QueueStore'
import { usePlaybackStore } from '@/Playback/PlaybackStore'
import { useUiStore } from '@/Common/UiStore'
import { fmtBpm } from '@/Common/Format'

const library = useLibraryStore()
const queue = useQueueStore()
const playback = usePlaybackStore()
const ui = useUiStore()

const input = ref<HTMLInputElement>()
defineExpose({ focusSearch: () => input.value?.focus() })

const searching = computed(() => !!library.query.trim() && !library.manageMode)
const count = computed(() => (searching.value ? library.libraryHits.length + library.kugouNew.length : library.visibleSongs.length))
const group = computed(() => library.activeGroup)
const cat = computed(() => library.activeCategory)

function clearSearch() {
  library.query = ''
  input.value?.focus()
}
async function onSearchKey(e: KeyboardEvent) {
  if (e.key === 'Enter' && library.query.trim()) {
    e.preventDefault()
    let id: number | null = library.libraryHits[0]?.id ?? null
    if (id === null && library.kugouNew[0]) id = await library.ensureInLibrary(library.kugouNew[0])
    if (id === null) return playback.log('没有搜到可以播放的歌')
    if (e.shiftKey) playback.play(id)
    else {
      const songId = id
      await playback.track(`加入队列：${library.songById(songId)?.title ?? '歌曲'}`, () => queue.enqueue(songId))
    }
  } else if (e.key === 'Escape') {
    e.stopPropagation()
    if (library.query) library.query = ''
    else input.value?.blur()
  }
}
async function toggleInCategory(songId: number) {
  if (!group.value || !cat.value) return
  await library.toggleMembership(group.value.id, cat.value.id, songId)
}
</script>

<template>
  <section class="col" @scroll.capture="ui.closeGroupPopover()">
    <div class="col-h">
      <div class="sbox">
        <span class="si" aria-hidden="true">⌕</span>
        <input
          id="song-search"
          ref="input"
          v-model="library.query"
          class="search"
          placeholder="直接搜歌：歌名或歌手，搜全部曲库和酷狗"
          autocomplete="off"
          @keydown="onSearchKey"
        />
        <button v-if="library.query" class="sx" aria-label="清空搜索" @click="clearSearch">✕</button>
      </div>
      <span class="mono cnt">{{ count }} 首</span>
    </div>

    <!-- 面包屑 / 模式切换 -->
    <div v-if="searching" class="crumb">
      <b>搜索「{{ library.query.trim() }}」</b><span>· 全部曲库 + 酷狗</span><span class="sp"></span>
      <span class="hint"><kbd>回车</kbd> 第一首加队列 · <kbd>Shift</kbd>+<kbd>回车</kbd> 立即播放</span>
    </div>
    <div v-if="library.error" class="library-status" :class="{ offline: !library.connected }" role="status">{{ library.error }}</div>
    <div v-else-if="group" class="crumb">
      <b>{{ group.name }}</b><span>›</span><b>{{ cat?.name ?? '全部' }}</b><span class="sp"></span>
      <button v-if="cat" class="mbtn" :class="{ on: library.manageMode }" @click="library.manageMode = !library.manageMode">
        {{ library.manageMode ? '完成' : '管理本分类歌曲' }}
      </button>
      <span v-else class="hint">选中一个分类后可管理歌曲</span>
    </div>
    <div v-if="library.manageMode && group && cat" class="manage-tip">正在编辑「{{ group.name }} › {{ cat.name }}」：下面是整个曲库，点卡片把歌加入或移出这个分类。</div>

    <!-- 搜索结果 -->
    <div v-if="searching" class="grid">
      <div class="sec"><b>曲库中</b><span class="mono">{{ library.libraryHits.length }}</span><span class="ln"></span></div>
      <SongCard v-for="(s, i) in library.libraryHits" :key="s.id" :song="s" :first="i === 0" />
      <div v-if="!library.libraryHits.length" class="sec muted">曲库里没有匹配的歌</div>

      <div class="sec">
        <b>酷狗搜索</b><span class="mono">{{ library.kugouNew.length }}</span><span class="badge">{{ library.kugouAvailable ? '已连接' : '不可用' }}</span><span class="ln"></span>
        <span>{{ library.kugouAvailable ? '不在曲库的歌也能直接播、排队或收进曲库' : '这次没连上酷狗搜索，只显示曲库结果' }}</span>
      </div>
      <KugouCard v-for="(r, i) in library.kugouNew" :key="r.key" :result="r" :first="!library.libraryHits.length && i === 0" />
      <div v-if="library.kugouLoading" class="sec muted">正在搜索酷狗…</div>
      <div v-else-if="!library.kugouNew.length" class="sec muted">{{ library.kugouAvailable ? '酷狗里没有更多结果' : '酷狗搜索暂时不可用' }}</div>
    </div>

    <!-- 管理分类成员 -->
    <div v-else-if="library.manageMode && cat" class="grid">
      <div
        v-for="s in library.songs"
        :key="s.id"
        class="card"
        :class="{ out: !cat.song_ids.includes(s.id) }"
        :style="{ '--c': cat.song_ids.includes(s.id) ? cat.color : 'var(--line-strong)' }"
        role="button"
        tabindex="0"
        @click="toggleInCategory(s.id)"
        @keydown.enter="toggleInCategory(s.id)"
      >
        <div class="acts"><span class="ib" :class="{ in: cat.song_ids.includes(s.id) }" aria-hidden="true">{{ cat.song_ids.includes(s.id) ? '✓' : '＋' }}</span></div>
        <div class="t">{{ s.title }}</div>
        <div class="a">{{ s.artist }}</div>
        <div class="meta"><span class="mono">{{ fmtBpm(s.bpm) }}</span><span>{{ cat.song_ids.includes(s.id) ? '已在本分类' : '点击加入' }}</span></div>
      </div>
    </div>

    <!-- 分类视图 -->
    <div v-else class="grid">
      <SongCard v-for="s in library.visibleSongs" :key="s.id" :song="s" />
      <div v-if="!library.visibleSongs.length" class="empty">
        <template v-if="!group">先在左侧新建一个活动组。</template>
        <template v-else-if="cat">「{{ cat.name }}」里还没有歌。点右上角「管理本分类歌曲」从曲库里挑，或者直接搜歌后用 ⌗ 加进来。</template>
        <template v-else>这个活动组还没有歌。先新建分类，再往里加歌。</template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.sbox { flex: 1; position: relative; min-width: 0; display: flex; }
.search { flex: 1; height: 46px; background: rgba(10, 9, 24, 0.7); border: 1px solid var(--line-strong); border-radius: 12px; color: var(--fg); padding: 0 42px; font: inherit; font-size: 17px; min-width: 0; }
.search:focus { border-color: var(--hot); box-shadow: 0 0 0 3px var(--hot-soft); outline: none; }
.si { position: absolute; left: 14px; top: 50%; transform: translateY(-50%); color: var(--fg3); pointer-events: none; font-size: 18px; }
.sx { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); width: 30px; height: 30px; padding: 0; border-color: transparent; color: var(--fg3); }
.cnt { font-size: 14px; color: var(--fg3); }
.crumb { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 12px 16px 0; font-size: 15px; color: var(--fg2); }
.crumb b { color: var(--fg); font-weight: 700; }
.crumb .sp { flex: 1; }
.hint { font-size: 13px; color: var(--fg3); }
.mbtn { font-size: 14px; padding: 6px 12px; }
.mbtn.on { background: var(--warn-soft); color: var(--warn); border-color: var(--warn); }
.manage-tip { margin: 10px 16px 0; padding: 10px 14px; border-radius: var(--r); background: var(--warn-soft); color: var(--warn); font-size: 14px; }
.library-status { margin: 10px 16px 0; padding: 8px 12px; border-radius: var(--r); background: var(--warn-soft); color: var(--warn); font-size: 13px; }
.library-status.offline { background: var(--bad-soft); color: var(--bad); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; padding: 14px 16px 16px; overflow: auto; align-content: start; flex: 1; min-height: 0; }
.grid > .empty { grid-column: 1 / -1; }
.sec { grid-column: 1 / -1; display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--fg2); padding-top: 6px; }
.sec.muted { color: var(--fg3); }
.sec b { color: var(--fg); font-weight: 700; font-size: 15px; }
.sec .ln { flex: 1; height: 1px; background: var(--line); }
.badge { font-size: 12px; padding: 2px 9px; border-radius: 999px; background: var(--warn-soft); color: var(--warn); }
@media (max-width: 720px) { .grid { grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); } }
</style>

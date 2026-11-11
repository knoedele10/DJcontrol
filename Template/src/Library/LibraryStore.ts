// 曲库、活动组、分类和搜索：M2 起由后端 SQLite 驱动，前端只保留视图状态。
import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import type { EventGroup, KugouResult, Membership, Song } from '@/Common/Types'
import { PALETTE, seedGroups, seedSongs } from '@/Common/MockData'
import {
  addCategorySong, createCategory, createGroup, deleteCategory, deleteGroup, fetchGroups, fetchLibrarySearch,
  fetchSongs, importKugouSong, reorderCategories, reorderGroups, removeCategorySong, replaceCategorySongs,
  subscribeLibrary, updateCategory, updateGroup,
} from '@/Library/LibraryApi'

export const useLibraryStore = defineStore('library', () => {
  const songs = ref<Song[]>(seedSongs())
  const groups = ref<EventGroup[]>(seedGroups())
  const activeGroupId = ref<string | null>(groups.value[0]?.id ?? null)
  const activeCategoryId = ref<string>('all')
  const manageMode = ref(false)
  const loading = ref(false)
  const connected = ref(false)
  const error = ref('')
  const revision = ref(0)
  const query = ref('')
  const libraryHits = ref<Song[]>([])
  const kugouResults = ref<KugouResult[]>([])
  const kugouAvailable = ref(false)
  const kugouLoading = ref(false)
  let searchSeq = 0
  let unsubscribe: (() => void) | undefined

  const songById = (id: number) => songs.value.find((s) => s.id === id)
  const activeGroup = computed(() => groups.value.find((g) => g.id === activeGroupId.value) ?? groups.value[0] ?? null)
  const activeCategory = computed(() => activeGroup.value?.categories.find((c) => c.id === activeCategoryId.value) ?? null)
  const groupSongIds = (g: EventGroup) => [...new Set(g.categories.flatMap((c) => c.song_ids))]
  const memberships = (songId: number): Membership[] =>
    groups.value.flatMap((group) => group.categories.filter((c) => c.song_ids.includes(songId)).map((category) => ({ group, category })))
  const colorOf = (songId: number) => activeGroup.value?.categories.find((c) => c.song_ids.includes(songId))?.color ?? 'var(--fg3)'
  const categoryOf = (songId: number) => activeGroup.value?.categories.find((c) => c.song_ids.includes(songId)) ?? null
  const visibleSongs = computed<Song[]>(() => {
    if (manageMode.value) return songs.value
    const group = activeGroup.value
    if (!group) return []
    const ids = activeCategory.value ? activeCategory.value.song_ids : groupSongIds(group)
    return ids.map(songById).filter((song): song is Song => !!song)
  })
  const tokens = computed(() => query.value.toLowerCase().split(/\s+/).filter(Boolean))
  const findInLibrary = (result: { title: string; artist: string }) => songs.value.find((s) => s.title === result.title && s.artist === result.artist) ?? null
  const kugouNew = computed(() => kugouResults.value.filter((result) => !findInLibrary(result)))

  function applyData(nextSongs: Song[], nextGroups: EventGroup[]) {
    songs.value = nextSongs
    groups.value = nextGroups
    if (!groups.value.some((group) => group.id === activeGroupId.value)) activeGroupId.value = groups.value[0]?.id ?? null
    if (!activeGroup.value?.categories.some((category) => category.id === activeCategoryId.value)) activeCategoryId.value = 'all'
  }

  async function reload() {
    loading.value = true
    try {
      const [nextSongs, nextGroups] = await Promise.all([fetchSongs(), fetchGroups()])
      applyData(nextSongs, nextGroups)
      connected.value = true
      error.value = ''
    } catch (cause) {
      connected.value = false
      error.value = cause instanceof Error ? cause.message : '曲库服务未连接'
    } finally {
      loading.value = false
    }
  }

  function startSync() {
    if (unsubscribe) return
    void reload()
    unsubscribe = subscribeLibrary((nextRevision) => {
      if (nextRevision <= revision.value) return
      revision.value = nextRevision
      void reload()
    }, (open) => {
      connected.value = open
      if (!open) error.value = '曲库服务连接中断，正在重连…'
    })
  }
  function stopSync() { unsubscribe?.(); unsubscribe = undefined }

  watch(query, async (value) => {
    const seq = ++searchSeq
    if (!value.trim()) {
      libraryHits.value = []
      kugouResults.value = []
      kugouAvailable.value = false
      kugouLoading.value = false
      return
    }
    // 曲库结果马上出；酷狗要查网络（可能几秒），等停止输入 0.4 秒后再查，结果回来再补上。
    kugouLoading.value = true
    kugouResults.value = []
    try {
      const local = await fetchLibrarySearch(value, 'library')
      if (seq !== searchSeq) return
      libraryHits.value = local.library
    } catch (cause) {
      if (seq !== searchSeq) return
      error.value = cause instanceof Error ? cause.message : '搜索失败'
      libraryHits.value = []
    }
    await new Promise((resolve) => setTimeout(resolve, 400))
    if (seq !== searchSeq) return
    try {
      const remote = await fetchLibrarySearch(value, 'kugou')
      if (seq !== searchSeq) return
      kugouResults.value = remote.kugou
      kugouAvailable.value = remote.kugou_available
    } catch {
      if (seq !== searchSeq) return
      kugouResults.value = []
      kugouAvailable.value = false
    } finally {
      if (seq === searchSeq) kugouLoading.value = false
    }
  })

  function selectGroup(id: string) { activeGroupId.value = id; activeCategoryId.value = 'all'; manageMode.value = false }
  function selectCategory(id: string) { activeCategoryId.value = id; manageMode.value = false }
  function findGroup(id: string) { return groups.value.find((group) => group.id === id) ?? null }

  async function ensureInLibrary(result: KugouResult): Promise<number | null> {
    const existing = findInLibrary(result)
    if (existing) return existing.id
    try { const song = await importKugouSong(result.key); await reload(); return song.id }
    catch (cause) { error.value = cause instanceof Error ? cause.message : '无法收进曲库'; return null }
  }
  async function addGroup(name: string) {
    try { const group = await createGroup({ name, color: PALETTE[groups.value.length % PALETTE.length] }); await reload(); selectGroup(group.id); return group }
    catch (cause) { error.value = cause instanceof Error ? cause.message : '新建活动组失败'; return null }
  }
  async function renameGroup(id: string, name: string) {
    try { await updateGroup(id, { name }); await reload(); return true } catch (cause) { error.value = cause instanceof Error ? cause.message : '重命名失败'; return false }
  }
  async function deleteGroupById(id: string) {
    try { await deleteGroup(id); await reload(); return true } catch (cause) { error.value = cause instanceof Error ? cause.message : '删除活动组失败'; return false }
  }
  async function addCategory(groupId: string, name: string, songIds: number[] = []) {
    const group = findGroup(groupId)
    if (!group) return null
    try { const category = await createCategory(groupId, { name, color: PALETTE[group.categories.length % PALETTE.length], song_ids: songIds }); await reload(); return category }
    catch (cause) { error.value = cause instanceof Error ? cause.message : '新建分类失败'; return null }
  }
  async function renameCategory(_groupId: string, id: string, name: string) {
    try { await updateCategory(id, { name }); await reload(); return true } catch (cause) { error.value = cause instanceof Error ? cause.message : '重命名分类失败'; return false }
  }
  async function deleteCategoryById(_groupId: string, id: string) {
    try { await deleteCategory(id); await reload(); return true } catch (cause) { error.value = cause instanceof Error ? cause.message : '删除分类失败'; return false }
  }
  async function toggleMembership(groupId: string, categoryId: string, songId: number): Promise<boolean> {
    const category = findGroup(groupId)?.categories.find((item) => item.id === categoryId)
    if (!category) return false
    try { const added = !category.song_ids.includes(songId); if (added) await addCategorySong(categoryId, songId); else await removeCategorySong(categoryId, songId); await reload(); return added }
    catch (cause) { error.value = cause instanceof Error ? cause.message : '修改分类成员失败'; return false }
  }
  async function addToCategory(groupId: string, categoryId: string, songId: number) {
    const category = findGroup(groupId)?.categories.find((item) => item.id === categoryId)
    if (!category || category.song_ids.includes(songId)) return false
    try { await addCategorySong(categoryId, songId); await reload(); return true } catch (cause) { error.value = cause instanceof Error ? cause.message : '加入分类失败'; return false }
  }
  async function replaceSongs(categoryId: string, songIds: number[]) {
    try { await replaceCategorySongs(categoryId, songIds); await reload(); return true } catch (cause) { error.value = cause instanceof Error ? cause.message : '排序失败'; return false }
  }
  async function reorderGroupIds(ids: string[]) {
    try { await reorderGroups(ids); await reload(); return true } catch (cause) { error.value = cause instanceof Error ? cause.message : '活动组排序失败'; return false }
  }
  async function reorderCategoryIds(groupId: string, ids: string[]) {
    try { await reorderCategories(groupId, ids); await reload(); return true } catch (cause) { error.value = cause instanceof Error ? cause.message : '分类排序失败'; return false }
  }

  return {
    songs, groups, activeGroupId, activeCategoryId, manageMode, loading, connected, error, revision,
    songById, activeGroup, activeCategory, groupSongIds, memberships, colorOf, categoryOf, visibleSongs,
    query, tokens, libraryHits, kugouResults, kugouAvailable, kugouLoading, kugouNew, findInLibrary,
    startSync, stopSync, reload, selectGroup, selectCategory, findGroup, ensureInLibrary,
    addGroup, renameGroup, deleteGroup: deleteGroupById, addCategory, renameCategory, deleteCategory: deleteCategoryById,
    toggleMembership, addToCategory, replaceSongs, reorderGroupIds, reorderCategoryIds,
  }
})

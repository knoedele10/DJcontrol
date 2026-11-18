// 使用教程：第一次打开面板时强制显示，看完才记下；之后可从顶部「？ 教程」随时重看。
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { loadJSON, saveJSON } from '@/Common/Storage'
import { fetchTutorialVersion, saveTutorialVersion } from '@/Tutorial/TutorialApi'
import { TUTORIAL_STEPS } from '@/Tutorial/TutorialSteps'

/** 教程内容大改时加 1，所有人下次打开都会再强制看一遍。 */
export const TUTORIAL_VERSION = 1
const LOCAL_KEY = 'kgdash.tutorial.version'

function localVersion(): number {
  const value = loadJSON<unknown>(LOCAL_KEY, 0)
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : 0
}

export const useTutorialStore = defineStore('tutorial', () => {
  const steps = TUTORIAL_STEPS
  const open = ref(false)
  /** 首次教程：不能关、不能跳过，只能看完。 */
  const forced = ref(false)
  const index = ref(0)
  const step = computed(() => steps[index.value])
  const isFirst = computed(() => index.value === 0)
  const isLast = computed(() => index.value === steps.length - 1)
  let initialized: Promise<void> | undefined

  /** 面板启动时调用：本机和后端都没有看完的记录，才强制打开。 */
  function init(): Promise<void> {
    initialized ??= (async () => {
      const local = localVersion()
      if (local >= TUTORIAL_VERSION) {
        void syncRemote(local)
        return
      }
      let remote = 0
      try { remote = await fetchTutorialVersion() } catch { /* 后端暂时连不上：没有记录就按第一次处理 */ }
      if (remote >= TUTORIAL_VERSION) {
        saveJSON(LOCAL_KEY, remote)
        return
      }
      start(true)
    })()
    return initialized
  }

  /** 本机记过、后端没记（离线时看完，或后端数据重建）：补写到后端。 */
  async function syncRemote(version: number) {
    try {
      if ((await fetchTutorialVersion()) < version) await saveTutorialVersion(version)
    } catch { /* 下次启动再补 */ }
  }

  function start(first = false) {
    forced.value = first
    index.value = 0
    open.value = true
  }
  function next() {
    if (isLast.value) void finish()
    else index.value += 1
  }
  function prev() {
    if (index.value > 0) index.value -= 1
  }
  function close() {
    if (!forced.value) open.value = false
  }
  async function finish() {
    open.value = false
    forced.value = false
    index.value = 0
    saveJSON(LOCAL_KEY, TUTORIAL_VERSION)
    try { await saveTutorialVersion(TUTORIAL_VERSION) } catch { /* 后端离线时先只记本机，下次启动再补写 */ }
  }

  return { steps, open, forced, index, step, isFirst, isLast, init, start, next, prev, close, finish }
})

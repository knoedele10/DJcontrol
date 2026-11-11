// 界面临时状态：分组弹出面板等。
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useUiStore = defineStore('ui', () => {
  /** 当前打开"设置分组"面板的歌曲与锚点按钮 */
  const groupPopover = ref<{ songId: number; anchor: HTMLElement } | null>(null)

  function openGroupPopover(songId: number, anchor: HTMLElement) {
    groupPopover.value = groupPopover.value?.songId === songId ? null : { songId, anchor }
  }
  function closeGroupPopover() {
    groupPopover.value = null
  }

  return { groupPopover, openGroupPopover, closeGroupPopover }
})

<script setup lang="ts">
// 教程遮罩：压暗整个面板，只亮出当前步骤讲到的区域，说明卡片跟在旁边。
// 教程打开时遮罩挡住所有点击，按键也只给教程用，避免误触播放、切歌或翻 PPT。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTutorialStore } from '@/Tutorial/TutorialStore'
import { useUiStore } from '@/Common/UiStore'

interface Box { top: number; left: number; width: number; height: number }

const PAD = 6
const GAP = 14
const MARGIN = 16
const NARROW = 720

const tutorial = useTutorialStore()
const ui = useUiStore()
const route = useRoute()
const router = useRouter()
const card = ref<HTMLElement>()
const primary = ref<HTMLButtonElement>()
const hole = ref<Box | null>(null)
const cardPos = ref<{ top: number; left: number } | null>(null)
const narrow = ref(false)
/** 窄屏时卡片贴底；要讲的区域在下半屏（页面已滚到底）时改贴顶部，免得挡住它 */
const dockTop = ref(false)
const ready = ref(false)
let previousFocus: HTMLElement | null = null
let timer = 0

const clamp = (value: number, low: number, high: number) => Math.min(Math.max(value, low), Math.max(low, high))
const near = (a: number, b: number) => Math.abs(a - b) < 0.5

function findTarget(): HTMLElement | null {
  for (const selector of tutorial.step?.targets ?? []) {
    const element = document.querySelector<HTMLElement>(selector)
    if (element && element.getClientRects().length && element.offsetWidth + element.offsetHeight > 0) return element
  }
  return null
}

/** 卡片依次试着放在目标下方、上方、右侧、左侧；目标几乎占满屏幕时压在目标靠下的位置。 */
function placeCard(target: Box, width: number, height: number, viewWidth: number, viewHeight: number) {
  const centerX = clamp(target.left + target.width / 2 - width / 2, MARGIN, viewWidth - width - MARGIN)
  const centerY = clamp(target.top + target.height / 2 - height / 2, MARGIN, viewHeight - height - MARGIN)
  const below = target.top + target.height + GAP
  if (below + height <= viewHeight - MARGIN) return { top: below, left: centerX }
  const above = target.top - GAP - height
  if (above >= MARGIN) return { top: above, left: centerX }
  const right = target.left + target.width + GAP
  if (right + width <= viewWidth - MARGIN) return { top: centerY, left: right }
  const left = target.left - GAP - width
  if (left >= MARGIN) return { top: centerY, left }
  return { top: clamp(viewHeight - height - MARGIN * 2, MARGIN, viewHeight - height - MARGIN), left: centerX }
}

function measure() {
  if (!tutorial.open) return
  const viewWidth = window.innerWidth
  const viewHeight = window.innerHeight
  narrow.value = viewWidth < NARROW
  const rect = findTarget()?.getBoundingClientRect()
  const next = rect ? { top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 } : null
  const current = hole.value
  // 定时重新测量是为了跟上数据加载后的布局变化；没变就不改，免得每次都重新渲染
  if (!next || !current || !near(next.top, current.top) || !near(next.left, current.left)
    || !near(next.width, current.width) || !near(next.height, current.height)) hole.value = next
  dockTop.value = narrow.value && !!next && next.top + next.height / 2 > viewHeight / 2
  if (!card.value || narrow.value || !next) {
    cardPos.value = null
    return
  }
  const place = placeCard(next, card.value.offsetWidth, card.value.offsetHeight, viewWidth, viewHeight)
  if (!cardPos.value || !near(place.top, cardPos.value.top) || !near(place.left, cardPos.value.left)) cardPos.value = place
}

async function showStep() {
  await nextTick()
  findTarget()?.scrollIntoView({ block: window.innerWidth < NARROW ? 'start' : 'nearest', inline: 'nearest' })
  measure()
  await nextTick()
  measure() // 卡片换了内容，高度变了，按新高度再定一次位置
  ready.value = true
  await nextTick() // 卡片隐藏时拿不到焦点，等它显示出来再聚焦
  primary.value?.focus({ preventScroll: true })
}

watch(() => tutorial.open, async (open) => {
  clearInterval(timer)
  if (!open) {
    hole.value = null
    cardPos.value = null
    ready.value = false
    previousFocus?.focus({ preventScroll: true })
    previousFocus = null
    return
  }
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  ui.closeGroupPopover()
  if (route.name !== 'dashboard') await router.replace({ name: 'dashboard' })
  await showStep()
  timer = window.setInterval(measure, 300)
})

watch(() => tutorial.index, () => {
  if (tutorial.open) void showStep()
})

function trapFocus(event: KeyboardEvent) {
  const items = [...(card.value?.querySelectorAll<HTMLElement>('button:not([disabled])') ?? [])]
  if (!items.length) return
  event.preventDefault()
  const at = items.indexOf(document.activeElement as HTMLElement)
  items[at < 0 ? 0 : (at + (event.shiftKey ? -1 : 1) + items.length) % items.length].focus()
}

function onKey(event: KeyboardEvent) {
  if (!tutorial.open) return
  // 在捕获阶段截住：面板的空格播放、N 切歌、方向键 / 翻页笔翻 PPT 在教程期间都不生效
  event.stopPropagation()
  const inCard = event.target instanceof Node && !!card.value?.contains(event.target)
  if (event.key === 'Escape') { event.preventDefault(); tutorial.close() }
  else if (event.key === 'ArrowRight' || event.key === 'PageDown') { event.preventDefault(); tutorial.next() }
  else if (event.key === 'ArrowLeft' || event.key === 'PageUp') { event.preventDefault(); tutorial.prev() }
  else if (event.key === 'Tab') trapFocus(event)
  else if (!inCard && !event.ctrlKey && !event.metaKey && !event.altKey && (event.key.length === 1 || event.key === 'Enter')) {
    event.preventDefault() // 焦点不在卡片上时，别让空格、回车点到面板上的按钮
  }
}

function split(line: string) {
  return line.split(/(\[[^\]]+\])/).filter(Boolean).map((text) =>
    text.startsWith('[') && text.endsWith(']') ? { text: text.slice(1, -1), key: true } : { text, key: false })
}

const holeStyle = computed(() => hole.value
  ? { top: `${hole.value.top}px`, left: `${hole.value.left}px`, width: `${hole.value.width}px`, height: `${hole.value.height}px` }
  : { top: '50%', left: '50%', width: '0px', height: '0px' })
const cardStyle = computed(() => (cardPos.value && !narrow.value ? { top: `${cardPos.value.top}px`, left: `${cardPos.value.left}px` } : undefined))
const primaryText = computed(() => (tutorial.isLast ? '开始使用' : tutorial.isFirst ? '开始' : '下一步'))

onMounted(() => {
  window.addEventListener('keydown', onKey, true)
  window.addEventListener('resize', measure)
  window.addEventListener('scroll', measure, true)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey, true)
  window.removeEventListener('resize', measure)
  window.removeEventListener('scroll', measure, true)
  clearInterval(timer)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="tutorial.open && tutorial.step" class="tour" :class="{ narrow, 'dock-top': dockTop }" @mousedown.self.prevent @click.self="tutorial.close()">
      <div class="hole" :class="{ none: !hole }" :style="holeStyle" aria-hidden="true"></div>
      <section
        ref="card"
        class="tcard"
        :class="{ center: !hole && !narrow, hidden: !ready }"
        :style="cardStyle"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        aria-describedby="tour-body"
      >
        <header class="thead">
          <span class="count mono">{{ tutorial.index + 1 }} / {{ tutorial.steps.length }}</span>
          <h2 id="tour-title">{{ tutorial.step.title }}</h2>
          <button v-if="!tutorial.forced" class="x" aria-label="关闭教程" title="关闭（Esc）" @click="tutorial.close()">✕</button>
        </header>
        <div id="tour-body" class="tbody">
          <p v-for="(line, i) in tutorial.step.lines" :key="`${tutorial.step.id}-${i}`">
            <template v-for="(part, j) in split(line)" :key="j"><kbd v-if="part.key">{{ part.text }}</kbd><template v-else>{{ part.text }}</template></template>
          </p>
        </div>
        <div class="dots" aria-hidden="true">
          <i v-for="(s, i) in tutorial.steps" :key="s.id" :class="{ on: i === tutorial.index, done: i < tutorial.index }"></i>
        </div>
        <footer class="tfoot">
          <span v-if="tutorial.forced" class="note">首次使用请看完教程</span>
          <span class="sp"></span>
          <button v-if="!tutorial.isFirst" type="button" @click="tutorial.prev()">上一步</button>
          <button ref="primary" type="button" class="go" @click="tutorial.next()">{{ primaryText }}</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.tour { position: fixed; inset: 0; z-index: 1000; }
.hole {
  position: fixed; border-radius: 14px; pointer-events: none;
  box-shadow: 0 0 0 200vmax rgba(4, 3, 14, 0.74), 0 0 0 2px var(--accent), 0 0 26px 2px rgba(34, 211, 255, 0.5);
  transition: top 0.25s ease, left 0.25s ease, width 0.25s ease, height 0.25s ease;
}
.hole.none { box-shadow: 0 0 0 200vmax rgba(4, 3, 14, 0.74); }
.tcard {
  position: fixed; width: min(380px, calc(100vw - 32px)); max-height: calc(100vh - 32px); overflow: auto;
  background: var(--raise); border: 1px solid var(--line-strong); border-radius: 14px;
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.55); padding: 16px 18px 14px; transition: top 0.25s ease, left 0.25s ease;
}
.tcard.center { top: 50%; left: 50%; transform: translate(-50%, -50%); }
.tcard.hidden { visibility: hidden; }
.thead { display: flex; align-items: center; gap: 10px; }
.count { flex: none; font-size: 12px; color: var(--accent); background: var(--accent-soft); border-radius: 999px; padding: 2px 9px; }
.thead h2 { flex: 1; min-width: 0; margin: 0; font-size: 18px; }
.x { width: 30px; height: 30px; padding: 0; border-color: transparent; color: var(--fg2); flex: none; }
.tbody { margin-top: 10px; font-size: 14.5px; line-height: 1.75; color: var(--fg2); }
.tbody p { margin: 0 0 6px; }
.dots { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 12px; }
.dots i { width: 6px; height: 6px; border-radius: 3px; background: var(--line-strong); transition: width 0.2s ease; }
.dots i.done { background: var(--fg3); }
.dots i.on { width: 18px; background: var(--grad); }
.tfoot { display: flex; align-items: center; gap: 8px; margin-top: 12px; }
.note { font-size: 12px; color: var(--warn); }
.sp { flex: 1; }
.tfoot button { padding: 8px 14px; font-size: 14px; }
.tfoot .go { background: var(--grad); border: none; color: #fff; font-weight: 700; padding: 8px 20px; }
.tfoot .go:hover { background: var(--grad); filter: brightness(1.12); }
.tour.narrow .tcard { top: auto; left: 12px; right: 12px; bottom: 12px; width: auto; max-height: 55vh; transform: none; }
.tour.narrow.dock-top .tcard { top: 12px; bottom: auto; }
@media (prefers-reduced-motion: reduce) { .hole, .tcard, .dots i { transition: none; } }
</style>

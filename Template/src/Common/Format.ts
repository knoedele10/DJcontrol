export const fmtTime = (sec: number) => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, '0')}`

/** BPM 未知（null）时显示破折号 */
export const fmtBpm = (bpm: number | null) => (bpm === null ? '— BPM' : `${bpm} BPM`)

/** ISO 时间 → 本地 HH:mm */
export function fmtClock(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '--:--' : `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export const reEscape = (t: string) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** 把文本按关键词切成片段，用于 <mark> 高亮（不使用 v-html） */
export function highlightParts(text: string, tokens: string[]): { text: string; hit: boolean }[] {
  if (!tokens.length) return [{ text, hit: false }]
  const re = new RegExp(`(${tokens.map(reEscape).join('|')})`, 'gi')
  return text
    .split(re)
    .filter(Boolean)
    .map((part) => ({ text: part, hit: tokens.some((t) => part.toLowerCase() === t) }))
}

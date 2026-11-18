// 接口与数据类型。与后端交换的类型字段名与 docs/api-contract.md 一致（snake_case），不做转换。
// 仅前端使用的视图类型（Membership、CommandLog、PptSlide）不受此约束。

export type SongSource = 'library' | 'kugou'

export interface Song {
  id: number
  title: string
  artist: string
  bpm: number | null // 未知为 null
  duration: number // 秒
  source: SongSource
  note: string
}

/** 酷狗搜索结果（还不在曲库里） */
export interface KugouResult {
  key: string
  title: string
  artist: string
  bpm: number | null
  duration: number
}

export interface SearchResponse {
  query: string
  library: Song[]
  kugou: KugouResult[]
  kugou_available: boolean
}

export interface Category {
  id: string
  name: string
  color: string
  song_ids: number[]
}

/** 活动大组，例如「演唱会」「运动会」 */
export interface EventGroup {
  id: string
  name: string
  color: string
  categories: Category[]
}

export interface Membership {
  group: EventGroup
  category: Category
}

export interface QueueItem {
  id: string
  song_id: number
  added_at: string // ISO 时间
}

export interface Session {
  id: string
  started_at: string
  ended_at: string | null
}

export interface HistoryItem {
  song_id: number | null // 歌曲被删后为 null
  title: string // 播放时的快照
  artist: string
  played_at: string // ISO 时间，显示时再格式化
}

export type PlayStatus = 'playing' | 'paused' | 'stopped' | 'unknown'
export type ControllerName = 'mock' | 'kugou'

export interface BackendConnectionState {
  mode: 'local' | 'proxy' | 'unknown'
  backend_connected: boolean
  upstream: string | null
  message: string
}

/** 播放器状态（见契约 §3.5）：队列和已播随播放状态一起推送 */
export interface PlayerState {
  controller: ControllerName
  connected: boolean
  status: PlayStatus
  song_id: number | null
  title: string
  artist: string
  position: number | null
  duration: number | null
  auto_next: boolean
  queue: QueueItem[]
  session: Session
  recent_history: HistoryItem[]
  error: string | null
  capabilities: Capability[]
  via?: 'playlist' | 'search' | null
}

export interface PlayerUpdate {
  type: 'player_state'
  revision: number
  state: PlayerState
}

export type PlayerCommand =
  | { action: 'play'; song_id: number }
  | { action: 'toggle' | 'next_in_queue' | 'previous' | 'media_next' | 'media_previous' }
  | { action: 'seek'; position: number }

export type CommandStatus = 'idle' | 'pending' | 'verified' | 'failed'

export interface CommandLog {
  text: string
  status: CommandStatus
}

export interface PptSlide {
  title: string
  subtitle: string
  bg: string
  songId: number | null // 翻到这一页时联动播放的歌
}

export interface Capability {
  name: string
  label: string
  supported: boolean
  verified: boolean
  note: string
}

/** 诊断信息（见契约 §3.6）。 */
export interface Diagnostics {
  controller: ControllerName
  kugou: { running: boolean; version: string | null; profile: string | null; error: string | null }
  ppt: { app: PptApp; connected: boolean }
  capabilities: Capability[]
  playlist: PlaylistState
}

export interface PlaylistState {
  name: string
  route: 'A' | 'B' | null
  supported: boolean
  can_add: boolean
  complete: boolean
  note: string
  add_note?: string
  songs: Record<string, boolean | null>
}

export interface PlaylistAddResult {
  status: 'added' | 'already_present' | 'unverified'
  message: string
  in_playlist: boolean | null
  playlist: PlaylistState
}

export type PptApp = 'powerpoint' | 'wps'

/** 页码与后端一致，从 1 开始；没有可读取的当前页时为 null。 */
export interface PptState {
  app: PptApp
  connected: boolean
  document_id: string
  file: string
  current_slide: number | null
  total_slides: number
  running: boolean
  black: boolean
  error: string | null
}

export interface PptUpdate {
  type: 'ppt_state'
  revision: number
  state: PptState
  preview_session?: string // 文稿重新载入后更换，避免浏览器复用过期页面
  bindings?: Record<string, number> // 当前文稿里绑了歌的页：页码（从 1 开始）→ 歌曲 id
  link_music?: boolean // 翻页联动音乐开关（存在后端，所有面板共用）
  link?: PptLinkResult | null // 最近一次翻页联动的结果
}

export interface PptLinkResult {
  seq: number
  slide: number
  song_id: number
  status: 'played' | 'failed'
  message: string
}

export type PptCommand =
  | { action: 'next' | 'previous' | 'stop' }
  | { action: 'goto'; slide: number }
  | { action: 'start'; slide?: number }
  | { action: 'black'; enabled: boolean }

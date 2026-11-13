# 酷狗统筹面板 · 前后端接口契约

| 项目 | 内容 |
|---|---|
| 版本 | v0.1.1（草案） |
| 日期 | 2026-11-07 |
| 适用 | `Template/`（Vue 3）↔ `Backend/`（FastAPI） |
| 已实现 | 健康检查、PPT、曲库与分组、搜索、队列与已播、播放控制、诊断设置（§4–§9） |
| 规划中 | 无（酷狗能力以真机自检结果为准） |

本文档是前后端唯一的接口约定。改接口时先改这里，再改两端代码，并在文末「变更记录」里写一行。
**已实现部分以代码为准**；本文档与代码不一致时，视为文档缺陷，应修正文档。

---

## 1. 通用约定

### 1.1 地址
- 后端启动：`uvicorn Main:app --host 127.0.0.1 --port 8000`（在 `Backend/` 目录下）。
- REST 前缀 `/api/...`，WebSocket 前缀 `/ws/...`。
- 开发时前端经 Vite 代理访问（`Template/vite.config.ts` 已配置 `/api`、`/ws`），前端代码只写相对路径。

### 1.2 数据格式
- JSON，UTF-8。
- **字段名统一 snake_case**（与 PPT 模块现有实现一致，后端 Pydantic / dataclass 直接输出，无需别名转换）。
- **前端类型与接口字段一一对应**，不在前端做 camelCase 转换（参考 `PptState` 的写法）。
- 时长、进度单位为**秒**；时间点为 ISO 8601 字符串，带时区，例如 `2026-11-07T19:30:05+08:00`。
- **页码从 1 开始**；「没有当前页」用 `null` 表示。
- ID：歌曲为整数；活动组、分类、队列项、场次为字符串，前端不假设格式。

### 1.3 成功响应
- 查询：`200`，直接返回资源，不额外包一层。
- 创建：`201`，返回完整资源。
- 删除：`204`，无响应体。
- **控制命令（播放器、PPT）**：同步执行，执行后**重新读取实际状态**，返回 `200` 和状态信封（见 §1.5）。
  - 后端不做乐观修改、不自动重试；失败时同样先刷新状态再报错。
  - 前端请求超时 10 秒，不自动重试控制命令。

### 1.4 错误响应
沿用 FastAPI 的 `detail` 格式：

```json
{ "detail": { "code": "ppt_unavailable", "message": "未检测到正在运行的 PowerPoint" } }
```

参数校验失败（`422`）使用 FastAPI 默认格式，`detail` 是数组：

```json
{ "detail": [ { "loc": ["body", "slide"], "msg": "跳页需要 slide 页码", "type": "value_error" } ] }
```

前端统一取 `detail.message`；`detail` 是数组时取第一项的 `msg`；都没有时显示通用提示。

| HTTP | code | 含义 | 状态 |
|---|---|---|---|
| 409 | `ppt_error` | PPT 通用错误 | 已实现 |
| 409 | `ppt_command_failed` | PPT 命令执行失败 | 已实现 |
| 503 | `ppt_unavailable` | 找不到演示软件或放映 | 已实现 |
| 404 | `not_found` | 资源不存在 | 播放器 / 队列已实现 |
| 409 | `conflict` | 重名、重复添加 | 已实现 |
| 409 | `player_command_failed` | 播放器命令无法执行（队列为空、没有更早的已播歌曲、排序缺项） | 已实现 |
| 409 | `capability_unsupported` | 当前播放器适配不支持该操作 | 已实现 |
| 503 | `player_unavailable` | 找不到酷狗窗口 / 酷狗未启动 | 已实现 |
| 502 | `upstream_unavailable` | 代理模式下连不上 Windows 后端（`API_UPSTREAM` 不可达） | 已实现 |
| 504 | `command_timeout` | 控制命令执行超时 | 已实现 |

### 1.5 状态信封与实时推送
每个模块维护一份完整状态和一个**递增的 `revision`**，HTTP 控制接口和 WebSocket 推送都返回同样的信封：

```json
{ "type": "ppt_state", "revision": 42, "state": { /* 模块状态 */ } }
```

- 前端收到 `revision` 小于已处理值的消息直接丢弃。
- 后端重启后 `revision` 会从 0 重新开始：前端在 WebSocket **重新连上时**把本地已处理的 `revision` 重置为 -1。
- 状态没变化时不推送、`revision` 不增加。

WebSocket 约定（PPT 已按此实现，其他模块照做）：
- 每个模块一个端点，例如 `/ws/ppt`、`/ws/player`。
- 连接建立后服务端**立即推一次当前完整状态**。
- 服务端 15 秒没有新状态就发 `{ "type": "ping" }`；前端 25 秒收不到任何消息就主动断开重连。
- 前端断线后 1.5 秒重连。前端不需要向服务端发消息。
- 慢连接只保留最新一条状态，不积压旧状态。

---

## 2. 健康检查（已实现）

`GET /api/health` → `200 { "status": "ok" }`

---

## 3. 数据模型

前端类型定义在 `Template/src/Common/Types.ts`。标「已实现」的与代码一致；标「规划中」的是接入后端时要新增或改名的类型。

### 3.1 PPT（已实现）
```ts
type PptApp = 'powerpoint' | 'wps'

interface PptState {
  app: PptApp
  connected: boolean
  document_id: string          // 演示文稿标识；没有打开文档时为 ""
  file: string                 // 文件名
  current_slide: number | null // 从 1 开始；读不到当前页时为 null
  total_slides: number
  running: boolean             // 是否在放映
  black: boolean               // 是否黑屏
  error: string | null         // 给用户看的错误说明
}

interface PptUpdate {
  type: 'ppt_state'
  revision: number
  state: PptState
  preview_session?: string    // 当前文稿的预览缓存会话标识，重新载入后更换
}

type PptCommand =
  | { action: 'next' | 'previous' | 'stop' }
  | { action: 'goto'; slide: number }        // slide ≥ 1
  | { action: 'start'; slide?: number }      // 不传则从当前页开始（没有当前页时从第 1 页）；已在放映时只在给了 slide 时跳页
  | { action: 'black'; enabled: boolean }
```

### 3.2 曲库（已实现）
```ts
type SongSource = 'library' | 'kugou'   // library=手动添加/导入，kugou=从酷狗搜索收录

interface Song {
  id: number
  title: string
  artist: string
  bpm: number | null       // 未知为 null（前端现为 number，需改）
  duration: number         // 秒
  source: SongSource
  note: string
}

interface KugouResult {
  key: string              // 后端生成的临时标识，用于「收进曲库」
  title: string
  artist: string
  bpm: number | null
  duration: number
}
```

### 3.3 活动组与分类（已实现）
```ts
interface Category {
  id: string
  name: string             // 1–20 字，同一活动组内不可重名
  color: string            // #RRGGBB
  song_ids: number[]       // 有序（前端现为 songIds，需改）
}

interface EventGroup {
  id: string
  name: string             // 1–20 字，全局不可重名
  color: string
  categories: Category[]   // 已按排序返回
}
```
一首歌可以属于多个分类，也可以跨活动组。删除分类或活动组**不删除**歌曲。

### 3.4 队列、场次、已播（已实现，模拟播放器）
```ts
interface QueueItem {
  id: string               // 队列项 ID
  song_id: number
  added_at: string
}

interface Session {        // 一场演出
  id: string
  started_at: string
  ended_at: string | null
}

interface HistoryItem {
  song_id: number | null   // 歌曲被删后为 null
  title: string            // 播放时的快照
  artist: string
  played_at: string        // ISO 时间（前端现为 HH:mm 字符串，需改为显示时格式化）
}
```

### 3.5 播放状态（已实现，模拟播放器）
```ts
type PlayStatus = 'playing' | 'paused' | 'stopped' | 'unknown'

interface PlayerState {
  controller: 'mock' | 'kugou'
  connected: boolean
  status: PlayStatus       // 酷狗读不出播放/暂停时为 unknown
  song_id: number | null   // 能匹配到曲库时给出
  title: string            // 从播放器读到的原始信息
  artist: string
  position: number | null  // 秒；读不到进度时为 null
  duration: number | null
  auto_next: boolean
  queue: QueueItem[]       // 第 0 项是下一首
  session: Session
  recent_history: HistoryItem[]  // 本场最近 20 条，新的在前
  error: string | null
}

interface PlayerUpdate {
  type: 'player_state'
  revision: number
  state: PlayerState
}
```
队列和已播放进播放器状态里一起推送：它们和「正在播什么」总是一起变化，合并后前端只需处理一种消息。

### 3.6 诊断（已实现）
```ts
interface Capability {
  name: string
  label: string
  supported: boolean
  verified: boolean        // 是否在本机实测通过
  note: string
}

interface Diagnostics {
  controller: 'mock' | 'kugou'
  kugou: { running: boolean; version: string | null; profile: string | null; error: string | null }  // error：自检没通过的原因
  ppt: { app: PptApp; connected: boolean }
  capabilities: Capability[]
}
```

| capability.name | 说明 | 不支持时前端行为 |
|---|---|---|
| `read_state` | 读取当前曲目 | 状态栏只显示面板最后下达的歌 |
| `play_pause` | 播放 / 暂停 | 播放键置灰 |
| `next` | 上一首 / 下一首 | 上一首键置灰 |
| `play_track` | 按歌名搜索并播放 | 卡片 ▶、「播下一首」置灰 |
| `read_position` | 读取播放进度 | 隐藏进度条，关闭自动接歌 |
| `seek` | 跳转播放进度 | 进度条只显示，点击不跳转 |
| `kugou_search` | 在酷狗里搜索 | 搜索只显示「曲库中」 |

酷狗 10.2.52.25713 的运行时结论见 [KugouCapabilities.md](KugouCapabilities.md)：`read_state`、`play_pause`、`next`、`read_position`、`seek`、`play_track`、`kugou_search` 支持。酷狗的 `play_track` 一般 5–9 秒返回，最长约 24 秒，前端请求超时不要短于 30 秒；返回 409 且提示「还在连接」时歌可能稍后才开始播，开始后状态推送会带上 `song_id` 并更新队列。以 `/api/diagnostics` 实际返回为准。

---

## 4. PPT（已实现）

| 方法 | 路径 | 请求体 | 响应 |
|---|---|---|---|
| GET | `/api/ppt/state` | – | `200 PptUpdate`（会先刷新一次实际状态） |
| GET | `/api/ppt/preview/{slide}` | 查询：`app`、`document`，可选 `width`、`version`、`session` | `200 image/png`；`slide` 从 1 开始，`width` 为 160–1600，默认 1280 |
| POST | `/api/ppt/connect` | `{ "app": "powerpoint" \| "wps" }` | `200 PptUpdate` |
| POST | `/api/ppt/command` | `PptCommand` | `200 PptUpdate` |
| WS | `/ws/ppt` | – | 推送 `PptUpdate`，空闲时推 `ping` |

行为说明：
- 后端启动时连接环境变量 `PPT_APP` 指定的软件（默认 `powerpoint`）；`/api/ppt/connect` 可在运行中切换。
- 所有 COM 操作在**同一个工作线程串行执行**；后台每 0.25 秒读取一次状态，变化时推送。
  因此无论是面板翻页、翻页笔翻页还是直接在 PPT 里点，前端都会收到同一种 `ppt_state` 更新。
- `/api/ppt/command` 参数校验（违反时 `422`）：
  - `goto` 必须带 `slide`；`black` 必须带 `enabled`。
  - 只有 `goto`、`start` 接受 `slide`；只有 `black` 接受 `enabled`。
  - `slide` 必须是 ≥ 1 的整数；不接受多余字段。
- 命令执行失败：`503 ppt_unavailable` 或 `409 ppt_command_failed / ppt_error`。失败前后端已刷新并推送最新状态。
- 命令「成功」但 `state.error` 非空时，前端按失败处理并显示 `state.error`。
- 文稿载入后，前端后台逐页预取并提前解码整稿图片，优先当前页及相邻页，显示就绪进度。主预览和缩略图复用同一张图片；翻页只切换已预载的 URL。
- 图片缓存保留整份当前文稿，命中时直接提供文件，不调用 COM。携带当前 `preview_session` 的请求返回 `Cache-Control: private, max-age=31536000, immutable`；无会话的旧客户端返回 `no-store`。切换文稿或服务重启后会话标识更换，旧会话请求返回 409；手动刷新使用新 `version` 重新生成图片。

### 4.1 页面绑定歌曲与翻页联动（已实现，在后端）

`PptUpdate` 多带三个字段（`GET /api/ppt/state`、命令响应、`/ws/ppt` 推送都有）：

```ts
interface PptUpdate {
  // …原有字段
  bindings: Record<string, number>   // 当前文稿里绑了歌的页：页码（从 1 开始）→ 歌曲 id
  link_music: boolean                // 「翻页联动音乐」开关，存数据库，所有面板共用
  link: {                            // 最近一次联动的结果；还没发生过为 null
    seq: number                      // 每次联动加 1，前端据此判断是不是新的一次
    slide: number
    song_id: number
    status: 'played' | 'failed'
    message: string                  // 失败原因，给用户看
  } | null
}
```

| 方法 | 路径 | 请求体 | 响应 |
|---|---|---|---|
| PUT | `/api/ppt/bindings/{slide}` | `{ song_id: number \| null }`，`null` 为解除 | `200 PptUpdate`；作用于当前打开的文稿。没有打开文稿 `503 ppt_unavailable`；页码超出、歌曲不存在 `409` |
| PATCH | `/api/ppt/settings` | `{ link_music: boolean }` | `200 PptUpdate` |
| POST | `/api/ppt/bindings/import` | `{ bindings: { "<app>:<document_id>": { "<页码>": song_id \| null } } }` | `200 PptUpdate & { imported: number }`；把旧版存在浏览器里的绑定搬进来，后端已有记录的页不覆盖，歌不存在的跳过 |

- 绑定按「软件 + 文稿 + 页码」存在数据库表 `ppt_bindings`；歌曲被删除时绑定自动清空。
- 联动由后端触发：PPT 实际页码发生变化（面板翻页、翻页笔、直接在 PPT 里点都算），并且
  前后是同一份文稿、前后都读得到页码、正在放映、`link_music` 为真、新的一页绑了歌、这首歌不是正在播放的歌，
  就向播放器下达 `play`。首次连接、断线重连、换文稿不算翻页。
- 连续快速翻页时，只播最后停下的那一页的歌（正在下达的那一次播放不会被打断）。
- 无论开几个面板窗口，一次翻页只播一次；结果通过 `link` 推给所有面板，前端只负责把它写进操作记录。
- 酷狗模式下播放要几秒到十几秒；酷狗报「还在连接」时 `link.status` 为 `failed`，歌可能稍后才响。

---

## 5. 曲库（已实现）

| 方法 | 路径 | 请求体 | 响应 |
|---|---|---|---|
| GET | `/api/songs` | 查询：可选 `source=library|kugou` | `Song[]` |
| POST | `/api/songs` | `{ title, artist, bpm?, duration?, note? }` | `201 Song` |
| POST | `/api/songs/import` | `{ text, category_ids?: string[] }`，每行「歌名 - 歌手」 | `200 { added, skipped, songs: Song[] }` |
| PATCH | `/api/songs/{id}` | `Song` 的部分字段 | `Song` |
| DELETE | `/api/songs/{id}` | – | `204`（同时从所有分类、队列中移除） |
| POST | `/api/songs/from-kugou` | `{ key }` | `201 Song`（`source=kugou`；曲库已有同名同歌手的歌则返回那一首）。`key` 过期或不存在 `404`；酷狗搜索关闭时 `503 kugou_unavailable` |

## 6. 搜索（已实现，曲库 + 酷狗）

`GET /api/search?q=周杰伦&limit=30&source=all`

`source`：`all`（默认）/ `library`（只查曲库，立即返回）/ `kugou`（只查酷狗，要访问网络，可能几秒）。前端先请求 `library` 再请求 `kugou`。

```json
{
  "query": "周杰伦",
  "library": [ /* Song[]，按匹配度排序 */ ],
  "kugou": [ /* KugouResult[]，已去掉曲库里已有的 */ ],
  "kugou_available": true
}
```
- 关键词按空格拆分，每个关键词都要命中「歌名 + 歌手」，不区分大小写（与前端现有逻辑一致）。
- 酷狗结果来自酷狗的网络搜索接口，最多等 8 秒；失败、超时或 `KUGOU_SEARCH=off` 时 `kugou=[]`、`kugou_available=false`，曲库结果不受影响。`source=library` 时 `kugou_available` 恒为 `false`，不代表酷狗不可用。
- `KugouResult.key` 在后端保留 10 分钟，`bpm` 恒为 `null`。

## 7. 活动组与分类（已实现）

| 方法 | 路径 | 请求体 | 响应 |
|---|---|---|---|
| GET | `/api/groups` | – | `EventGroup[]`（含分类） |
| POST | `/api/groups` | `{ name, color? }` | `201 EventGroup` |
| PATCH | `/api/groups/{group_id}` | `{ name?, color? }` | `EventGroup` |
| DELETE | `/api/groups/{group_id}` | – | `204` |
| PUT | `/api/groups/order` | `{ group_ids }` | `204` |
| POST | `/api/groups/{group_id}/categories` | `{ name, color?, song_ids? }` | `201 Category` |
| PATCH | `/api/categories/{category_id}` | `{ name?, color? }` | `Category` |
| DELETE | `/api/categories/{category_id}` | – | `204` |
| PUT | `/api/groups/{group_id}/categories/order` | `{ category_ids }` | `204` |
| POST | `/api/categories/{category_id}/songs` | `{ song_id }` | `200 Category`；已在分类中 `409 conflict` |
| DELETE | `/api/categories/{category_id}/songs/{song_id}` | – | `200 Category` |
| PUT | `/api/categories/{category_id}/songs` | `{ song_ids }`（整体替换、可排序） | `200 Category` |

- `color` 不传时后端按调色板顺序分配。
- 前端操作对应：「设置分组」面板勾选 / 取消 → `POST` / `DELETE .../songs`；拖卡片到分类 → `POST .../songs`（`409` 时提示「已在该分类」）。
- 曲库和分组变化时，`/ws/library` 推送 `{ "type": "library_changed", "revision": n, "scope": "songs" | "groups" }`，前端收到后重新 `GET`。用于电脑与平板同时打开面板的场景。

## 8. 队列、场次与已播（已实现，模拟播放器）

所有修改接口都返回 `200 PlayerUpdate`（队列在播放器状态里），同时经 `/ws/player` 推送。

| 方法 | 路径 | 请求体 |
|---|---|---|
| POST | `/api/queue` | `{ song_id, position: "end" \| "next" }` |
| DELETE | `/api/queue/{item_id}` | – |
| PUT | `/api/queue/order` | `{ item_ids }` |
| DELETE | `/api/queue` | –（清空） |
| POST | `/api/sessions` | –（开始新一场，自动结束上一场） |
| POST | `/api/sessions/current/end` | – |
| GET | `/api/history?session=current&limit=200` | –，返回 `HistoryItem[]`（完整记录，状态里只带最近 20 条） |

规则（与前端现有行为一致）：
- 已在队列中的歌再次加入，**移动**到新位置，不重复。
- 一首歌开始播放后自动移出队列，并追加一条已播记录。
- 后端启动时如果没有进行中的场次，自动开一场。

## 9. 播放控制与诊断（已实现）

| 方法 | 路径 | 请求体 | 所需能力 | 响应 |
|---|---|---|---|---|
| GET | `/api/player/state` | – | – | `PlayerUpdate` |
| POST | `/api/player/command` | 见下 | 见下 | `PlayerUpdate` |
| PATCH | `/api/player/settings` | `{ auto_next }` | – | `PlayerUpdate` |
| WS | `/ws/player` | – | – | 推送 `PlayerUpdate` |
| GET | `/api/diagnostics` | – | – | `Diagnostics` |
| POST | `/api/diagnostics/refresh` | – | – | `Diagnostics`（重新自检） |
| PUT | `/api/settings/controller` | `{ name: "mock" \| "kugou" }` | – | `Diagnostics` |

播放命令，与 `PptCommand` 同一风格：
```ts
type PlayerCommand =
  | { action: 'play'; song_id: number }     // play_track
  | { action: 'toggle' }                    // play_pause
  | { action: 'next_in_queue' }             // play_track，播队列第 0 项
  | { action: 'previous' }                  // play_track，回放上一首已播
  | { action: 'seek'; position: number }    // seek
```
- 所需能力不支持时直接返回 `409 capability_unsupported`，不执行。
- 命令在后端串行执行，同一时刻只有一个命令操作酷狗；执行后重新读取酷狗状态再返回。
- 读不到状态的能力只能做到「已发送」：返回成功，但 `state.error` 为空、`status` 为 `unknown`，前端显示「已发送（未核验）」。
- 「快结束时自动接歌」由后端执行（酷狗模式下不可用：酷狗播完会自己接下一首，开启自动接歌的请求会被拒绝），前端只负责开关 `auto_next`。

---

## 10. 前端接入对照

| 前端位置 | 现在 | 接入后 |
|---|---|---|
| `Ppt/PptApi.ts`、`Ppt/PptStore.ts` | **已接真实后端** | 绑定和联动开关调接口保存；联动播放由后端执行，前端只记录结果 |
| `Library/LibraryApi.ts`、`Library/LibraryStore.ts` | localStorage + 模拟搜索 | `GET /api/songs`、`GET /api/groups`、`GET /api/search`、`/ws/library` |
| `Diagnostics/DiagnosticsApi.ts` `fetchDiagnostics` | 后端诊断接口 | `GET /api/diagnostics`、`POST /api/diagnostics/refresh` |
| `Library/LibraryStore.ts` 曲库 / 分组 | 后端接口；旧数据只作断线占位 | §5、§7；订阅 `/ws/library` |
| `Library/LibraryStore.ts` `ensureInLibrary` | 本地追加 | `POST /api/songs/from-kugou` |
| `Queue/QueueStore.ts` 队列 / 已播 | 后端接口；旧本地状态不再作为事实来源 | §8；状态来自 `/ws/player` |
| `Playback/PlaybackStore.ts` | 前端计时模拟 | `/ws/player` 驱动；`report()` 跟随命令请求的成功 / 失败 |
| `Pages/Settings/SettingsPage.vue` | **已接真实后端** | `GET /api/diagnostics`、`POST /api/diagnostics/refresh`、`PUT /api/settings/controller` |

类型对齐情况（2026-11-07 已完成）：
- `Song.bpm`、`KugouResult.bpm` 为 `number | null`，显示用 `Common/Format.ts` 的 `fmtBpm`；`Song` 含 `note`。
- `Category.song_ids`、`HistoryItem.song_id / played_at`（ISO 时间，显示用 `fmtClock`）。
- 队列为 `QueueItem[]`（`Queue/QueueStore.ts`），排序和删除按队列项 `id`。
- 已新增 `SearchResponse`、`QueueItem`、`Session`、`PlayerState`、`PlayerUpdate`、`PlayerCommand`、`Diagnostics` 类型，供接入时使用。
- 浏览器里旧版本地数据（`kgdash-library-v1`，camelCase）在首次加载时自动迁移到 `kgdash-library-v2`。

---

## 11. 待定事项

- [ ] 酷狗「按歌名播放」「酷狗搜索」能否实现，取决于能力验证结果；做不到时对应 capability 为 `supported=false`，接口保留。
- [ ] 酷狗搜索结果能否拿到 BPM（大概率不能，先返回 `null`）。
- [ ] PPT 每页标题：目前文字标签显示「第 N 页」，真实图片预览、缩略图和整稿预载已实现。如需提取真实标题，可让 `PptState` 增加 `slides: { title: string }[]`。
- [x] （2026-11-11 已完成，见 §4.1）PPT 页面绑定和翻页联动迁到后端：`PUT /api/ppt/bindings/{slide}`、`PATCH /api/ppt/settings { link_music }`，由后端在检测到翻页时下达 `play` 命令。
- [ ] 局域网内用手机 / 平板遥控时是否需要访问口令。

---

## 变更记录

| 日期 | 版本 | 内容 |
|---|---|---|
| 2026-11-11 | v0.1.8 | PPT 页面绑定与翻页联动迁到后端：`PptUpdate` 增加 `bindings`、`link_music`、`link`；新增 `PUT /api/ppt/bindings/{slide}`、`PATCH /api/ppt/settings`、`POST /api/ppt/bindings/import` |
| 2026-11-11 | v0.1.9 | M8 诊断与设置接入完成：控制器切换、酷狗/PPT 能力状态和 SQLite 设置持久化 |
| 2026-11-11 | v0.1.7 | 酷狗搜索接入：`GET /api/search` 返回酷狗结果并新增 `source` 参数；`POST /api/songs/from-kugou` 可用；capability `kugou_search` 开放 |
| 2026-11-10 | v0.1.6 | 酷狗开放 `play_track`、`seek`（投递消息实现）；`play` / `next_in_queue` / `previous` 在酷狗连接慢时返回 409「还在连接」，播出后自动补记；酷狗模式自动接歌仍不可用 |
| 2026-11-09 | v0.1.5 | M5 酷狗适配完成：酷狗开放 `read_position`；新增 capability `seek`（酷狗不支持）；诊断的 `kugou` 增加 `error` |
| 2026-11-09 | v0.1.4 | 完成 M4 真机探测与六项能力结论，链接独立验证记录；未开放酷狗适配 |
| 2026-11-07 | v0.1.2 | M2 曲库、分组、分类、本地搜索和 `/ws/library` 已接入后端；酷狗搜索保持未接入 |
| 2026-11-07 | v0.1.3 | M3 模拟播放器、队列、场次、已播和 `/ws/player` 已接入后端 |
| 2026-11-07 | v0.1.1 | 前端类型按本契约改为 snake_case，队列改为 `QueueItem[]` |
| 2026-11-07 | v0.1 | 初稿：PPT 模块按现有实现记录；其余模块按前端原型整理，统一采用 PPT 模块的约定（snake_case、同步命令返回状态信封、按模块拆分 WebSocket） |

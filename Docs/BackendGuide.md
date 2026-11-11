# 后端开发指南

面向后端开发者：怎么搭环境、代码怎么分层、新模块怎么写、剩下的活按什么顺序做、做到什么程度算完成。

相关文档：
- [ApiContract.md](ApiContract.md)：前后端接口契约（字段、路径、错误码）。**接口以它为准。**
- [PptControl.md](PptControl.md)：PPT 模块说明。PPT 是目前唯一完整实现的模块，也是其他模块的**参考模板**。

---

## 1. 现状

| 部分 | 状态 | 位置 |
|---|---|---|
| 服务入口、健康检查 | 已实现 | `Main.py` |
| PPT 控制（PowerPoint / WPS） | 已实现，有测试、探测脚本和整稿预览预载 | `PptControl/`、`PptControl/Service.py`、`PptControl/PreviewCache.py`、`PptControl/Api.py`、`Tests/TestPpt*.py`、`Probes/PptState.py` |
| 数据库与迁移 | 已实现，含迁移、种子数据和仓储测试 | `Database/`、`Database/Migrations/`、`Tests/TestDatabase.py` |
| 曲库、分组、本地搜索 | 已实现（M2）；酷狗搜索在 10.2.52 上做不了（见 M6） | `Library/Api.py`、`Library/Service.py`、`Library/Model.py`、`Tests/TestLibrary*.py` |
| 播放器（模拟）、队列、场次、已播 | 已实现（M3） | `Player/Base.py`、`Player/Mock.py`、`Player/Service.py`、`Player/Api.py`、`Player/Model.py` |
| 酷狗适配 | 已实现（M4、M5，针对 10.2.52.25713） | `KugouControl/`、`Probes/Kugou*.py`、`Tests/TestKugou*.py` |
| 诊断与设置 | 未开始（M8） | – |

前端曲库、队列、播放、PPT 已接入后端；`mockData.ts` 仅保留配色和离线兜底用的种子数据。

---

## 2. 环境与启动

### 2.1 要求
- Windows 10/11，常规 CPython 3.12+（本机为 3.13）。不要用 Microsoft Store 版 Python，COM 和界面自动化可能受限。
- 后端必须和酷狗、PowerPoint/WPS 运行在**同一个 Windows 用户的同一个桌面会话**里。
- **权限级别要一致**：如果酷狗以管理员身份运行而后端不是，界面自动化会读不到也点不动酷狗窗口。两者都用普通权限运行。

### 2.2 首次安装
```powershell
cd D:\DJproject\KuGouDashboard\Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r RequirementsDev.txt
```
下载慢或失败时，换源或临时去掉代理：
```powershell
python -m pip install -r RequirementsDev.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2.3 启动
```powershell
cd D:\DJproject\KuGouDashboard\Backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn Main:app --host 127.0.0.1 --port 8000 --reload
```
前端另开终端 `pnpm dev`，Vite 已把 `/api`、`/ws` 代理到 8000 端口。

### 2.4 环境变量
| 变量 | 默认 | 说明 | 状态 |
|---|---|---|---|
| `PPT_APP` | `powerpoint` | 启动时连接的演示软件：`powerpoint` / `wps` | 已实现 |
| `PLAYER_CONTROLLER` | `mock` | 播放器：`mock` / `kugou` | 已实现 |
| `DB_PATH` | `Backend/Data/dashboard.db` | SQLite 文件位置 | 已实现 |
| `FRONTEND_DIST` | 未设置 | 由 FastAPI 提供该目录下的前端构建产物；容器镜像里为 `/app/Template/dist` | 已实现 |
| `API_UPSTREAM` | 未设置 | 设置后进入代理模式：本地不建库、不连 COM，`/api` 与 `/ws` 全部转发到该地址 | 已实现 |
| `KUGOU_SEARCH` | `on` | 酷狗搜索：`on` / `off`。开启时搜索会访问酷狗的网络接口 | 已实现 |
| `LOG_LEVEL` | `INFO` | 日志级别 | 规划 |

新增环境变量时在这张表里补一行，并在 `Main.py` 里校验取值，非法值直接启动失败（参考 `PPT_APP`）。

### 2.5 Docker
镜像内先构建前端，再由 FastAPI 在同一进程里提供静态文件，只暴露 8000 端口：
```powershell
docker build -f Dockerfile -t kugou-dashboard .
docker run --rm -p 8000:8000 -v kugou-data:/app/Backend/Data kugou-dashboard
```
访问 `http://127.0.0.1:8000`。`DB_PATH` 已指向挂载卷，`PPT_APP`、`PLAYER_CONTROLLER` 可用 `-e` 覆盖。

Linux 容器里没有 PowerPoint/WPS、酷狗窗口，`pywin32` 也只有 Windows 版本，装不上——这不是缺依赖，是平台限制。要真机能力有两种跑法。

**A. 全在 Windows 本机跑**，一个进程同时提供界面、接口和 COM 控制：
```powershell
cd D:\DJproject\KuGouDashboard\Template; pnpm build
cd ..\Backend
$env:FRONTEND_DIST = "D:\DJproject\KuGouDashboard\Template\dist"
python -m uvicorn Main:app --host 127.0.0.1 --port 8081
```
访问 `http://127.0.0.1:8081`。开发时也可以继续用 `pnpm dev`（5173）+ 后端（8000）的 Vite 代理组合，效果相同。

**B. 容器出界面、Windows 出 COM（代理模式）**。设 `API_UPSTREAM` 后容器只提供静态页面，`/api`、`/ws` 转发给 Windows 后端；数据库和 COM 都留在 Windows 侧，容器不再挂数据卷：
```powershell
# 先在 Windows 按 A 启动后端（示例端口 8081）
docker run -d --name kugou-dashboard -p 8080:8000 `
  -e API_UPSTREAM=http://host.docker.internal:8081 `
  --add-host=host.docker.internal:host-gateway `
  --restart unless-stopped kugou-dashboard
```
访问 `http://127.0.0.1:8080`。也可以 `docker compose up -d --build`，`docker-compose.yml` 已带好 `extra_hosts` 和默认上游。

上游连不上时接口返回 502 `upstream_unavailable`；`/api/health` 只看容器自己（多带 `mode`、`upstream` 两个字段），所以 Windows 后端没起来不会让容器反复重启。

---

## 3. 分层与职责

按**功能**分文件夹，同一功能的路由、业务、请求模型、控制器放在一起；文件名不带下划线、连字符。

```text
Backend/
  Main.py            # 组装：创建服务、注册路由、生命周期（启动 / 关闭）
  Proxy.py           # 代理模式：/api 与 /ws 转发给 Windows 后端，本地不建库、不连 COM
  KugouControl/      # 控制酷狗：版本识别、窗口、媒体键、界面自动化、独立工作进程
    Profiles/        # 按酷狗版本区间的标题格式、热键、定位规则
  PptControl/        # 控制 PowerPoint / WPS：控制器、服务、预览缓存、路由、请求模型
  Player/            # 播放器接口与模拟实现、队列、场次、已播、路由、请求模型
  Library/           # 曲库、分组、本地搜索
  Diagnostics/       # 诊断与设置（M8，预留）
  Database/          # SQLite 连接、仓储、种子数据
    Migrations/      # 按序号命名的 .sql 迁移文件
  Tests/             # unittest，不依赖真实软件；文件名 Test*.py
  Data/              # 运行时数据库和日志（不入库）
../Probes/           # 只读探测脚本，在真机上验证能力
```

每个功能文件夹内部用固定的文件名表示分层：

| 文件 | 职责 |
|---|---|
| `Api.py` | HTTP + WebSocket 路由：只做参数接收、调用服务、把异常翻译成 HTTP 错误 |
| `Model.py` | Pydantic 请求结构（extra="forbid"、strict） |
| `Service.py` | 业务与状态：锁、revision、订阅推送、轮询、规则 |
| `Base.py` 及软件名命名的文件 | 和外部软件打交道：只做"读状态 / 执行动作" |

依赖方向只能是 **Api → Service → 控制器 / Database**，反过来不行：
- `Api.py` 里不写业务规则，不直接碰数据库或 COM。
- 控制器不知道 HTTP、WebSocket、数据库的存在，只抛自己的异常类型。
- `Service.py` 持有状态，是唯一可以推送 WebSocket 消息的地方。
- 跨功能引用写完整包名，例如 `from Player.Base import PlayerController`。

---

## 4. 编码约定

### 4.1 接口
- 字段 snake_case，页码从 1 开始，时间用带时区的 ISO 8601（`datetime.now().astimezone().isoformat()`）。
- 请求模型一律 `model_config = ConfigDict(extra="forbid")`，数字和布尔字段用 `strict=True`，跨字段规则用 `model_validator`（参考 `PptControl/Model.py`）。
- 业务错误用 `HTTPException(status_code, detail={"code": ..., "message": ...})`，`code` 用小写 snake_case，新增的错误码同步写进契约 §1.4。
- `message` 是给用户看的中文，说清楚发生了什么、该怎么办；不要把异常原文或堆栈返回给前端，堆栈写日志。

### 4.2 控制命令（播放器、PPT 共用的原则）
- **串行**：同一个外部软件的所有操作都在**一个专用工作线程**里执行（`ThreadPoolExecutor(max_workers=1)`），外面再套一把 `asyncio.Lock`。COM 对象的创建、使用、释放必须在同一个线程。
- **不乐观**：不先改状态再等确认。执行完重新读取实际状态，用读到的状态回复和推送。
- **不自动重试**：翻页、播放这类动作重复执行会出错（翻两页、播两遍），失败就报错，让人决定。
- **失败也刷新**：`try ... finally: refresh()`，保证前端看到的是失败后的真实状态。

### 4.3 状态推送
每个需要实时推送的模块照 `PptService` 的写法：
- 状态用不可变的 `@dataclass(frozen=True)`，便于用 `==` 判断有没有变化。
- `_publish(state)`：状态变了才 `revision += 1` 并推送。
- 每个订阅者一个 `asyncio.Queue(maxsize=1)`，满了就丢旧的，只留最新状态。
- 新订阅者连上时立刻放入当前快照。
- WebSocket 15 秒无消息发 `{"type": "ping"}`。

### 4.4 其他
- 所有 I/O 用 `async`；阻塞调用（COM、界面自动化、SQLite 大查询）放进线程池执行。
- 日志用 `logging.getLogger(__name__)`，不要 `print`。
- 函数和模块写中文 docstring，说明「为什么」，不重复「做了什么」。
- 类型标注写全；能用 `Literal` 限定取值的就用。

---

## 5. 新模块怎么写（以 PPT 为模板）

以「播放器」为例，按这个顺序写，每一步都能单独测试：

1. **契约**：先确认 `Docs/ApiContract.md` 里这个模块的字段和路径，要改先改文档。
2. **控制器接口** `Player/Base.py`：
   ```python
   class PlayerController(ABC):
       name: str
       @abstractmethod
       def capabilities(self) -> list[Capability]: ...
       @abstractmethod
       def get_state(self) -> PlayerReading: ...   # 从软件读到的原始状态
       def play_track(self, title: str, artist: str) -> None: raise CapabilityUnsupported("play_track")
       def toggle(self) -> None: raise CapabilityUnsupported("play_pause")
       def close(self) -> None: ...
   ```
   不支持的能力默认抛 `CapabilityUnsupported`，子类只覆盖自己能做的。
3. **模拟实现** `Player/Mock.py`：不依赖任何软件，前端和测试都靠它。进度按真实时间推进。
4. **服务** `Player/Service.py`：持有 `PlayerState`、队列、场次；串行执行命令；每 0.5–1 秒轮询一次控制器；变化时推送。
5. **请求模型** `Player/Model.py`：`PlayerCommand`，用 `action` 区分，规则和 `PptCommand` 同一写法。
6. **路由** `Player/Api.py`：`GET /api/player/state`、`POST /api/player/command`、`WS /ws/player`。
7. **注册** `Main.py`：在 `lifespan` 里创建服务、`start()`、退出时 `close()`；`create_app()` 接受注入的服务，方便测试替换。
8. **测试** `Tests/TestPlayer.py`：用模拟控制器和 `TestClient` 测协议、错误码、推送。
9. **探测脚本** `Probes/`：只读，真机上验证（见 §6 M4）。
10. **文档**：更新契约里的状态标记（规划中 → 已实现），必要时写模块说明（参考 `PptControl.md`）。

PPT 预览补充：文稿载入后前端逐页预取并提前解码整稿 PNG，优先当前页和相邻页；后端按当前文稿保留预览文件缓存。主预览与缩略图复用同一图片，翻页不会再次触发 COM 导出。预览请求携带 `preview_session`，切换文稿、页数变化、后端重启或手动刷新后会更换会话/版本，旧图片不会继续复用。

---

## 6. 剩余工作与顺序

按依赖排序；每项都有明确的完成标准。M1–M3 不依赖酷狗，可以先做，做完前端就能整体接入真实后端（播放仍为模拟）。

### M1 数据层（已实现）
- `Database/Connection.py`：SQLite 连接（`PRAGMA foreign_keys=ON`、WAL 模式），按文件名顺序执行 `Database/Migrations/*.sql`，用 `schema_migrations` 表记录已执行的迁移。
- `Main.py`：应用生命周期创建/注入 `Database`，启动时完成迁移和种子，关闭时释放连接；测试可注入 `Database(":memory:")`。
- `Database/Migrations/001Init.sql`：`songs`、`event_groups`、`categories`、`category_songs`（带排序）、`queue_items`、`sessions`、`history`、`ppt_bindings`、`settings`。
- 数据读写集中在 `Database/` 下的仓储函数里，服务层不拼 SQL。
- 首次启动库为空时，导入一份种子数据（与前端 `mockData.ts` 相同的曲库和两个示例活动组），方便联调。
- **完成标准**：删掉数据库文件重启能自动建表；迁移重复执行无副作用；测试用内存库 `:memory:`。当前已完成：连接启用外键和 WAL、迁移记录、前端 28 首种子歌曲与两个示例活动组、仓储级联与排序测试。

### M2 曲库、分组、本地搜索（已实现）
- 契约 §5、§6（仅曲库部分）、§7。
- 重名返回 `409 conflict`；删除歌曲时级联移出分类和队列。
- 搜索规则与前端一致：空格拆词，每个词都要命中「歌名 + 歌手」，不区分大小写。`kugou` 先固定返回空数组、`kugou_available=false`。
- `/ws/library` 在曲库或分组变化时推送 `library_changed`。
- **完成标准**：前端 `Library/LibraryStore.ts` 改为调用接口后，分组、分类、管理歌曲、拖拽、搜索全部可用，刷新页面数据不丢。当前已完成：曲库/分组/分类 CRUD、分类成员排序、批量导入、本地搜索、`/ws/library` 变更通知；酷狗搜索仍返回空数组并标记不可用。

### M3 播放器（模拟）、队列、场次、已播（已实现）
- 契约 §3.4、§3.5、§8、§9（`controller=mock`）。
- `Player/Queue.py`：入队（已存在则移动）、插到下一首、排序、删除；歌曲开始播放时出队并写已播。
- 自动接歌在后端做：距结束 ≤ 3 秒且 `auto_next=true` 时播队列第 0 首。
- 启动时没有进行中的场次就自动新建。
- **完成标准**：前端 `Queue/QueueStore.ts`、`Playback/PlaybackStore.ts` 改为由 `/ws/player` 驱动后，排队、播放、暂停、上一首、自动接歌、已播记录行为与现在的模拟版一致；开两个浏览器窗口状态同步。当前已完成：模拟控制器实时进度、串行播放器服务、队列/场次/历史接口、自动接歌和 `/ws/player`，前端已切换为后端状态。

### M4 酷狗能力验证（已完成）
在 `Probes/` 下写脚本，逐项记录结论到 `Docs/KugouCapabilities.md`（版本、能/不能/有条件、前提条件）：
- `KugouVersion.py`：找到酷狗进程，读 exe 版本号。
- `KugouWindow.py`：枚举酷狗窗口，打印标题和类名，记录标题格式（播放中 / 暂停 / 未播放各一次）。
- `KugouMedia.py`：发送系统媒体键和酷狗全局热键，观察是否生效（**这个会改变播放状态**，运行前提示用户）。
- `KugouUiaTree.py`：导出酷狗主窗口的界面自动化树，看搜索框、结果列表能否定位。
- `KugouSmtc.py`：查看酷狗是否注册了 Windows 系统媒体会话（如果有，播放状态和进度可能可以直接读）。
- **完成标准**：契约里每个 capability 都有结论；决定「按歌名播放」走界面自动化还是走专用歌单退路。
- **2026-11-09 验证结果**：[能力记录](KugouCapabilities.md) 里七项能力都有确定结论。能：读取曲目、播放/暂停、酷狗自身上下曲、读取进度。不能：按歌名播放、酷狗搜索、跳转进度（控件不接受程序写入）。SMTC 在当前配置无会话。按歌名播放走专用歌单人工选曲退路。

### M5 酷狗适配（已完成）
- `KugouControl/`：`version.py`（识别版本）、`profiles/`（按版本区间配置标题格式、热键、自动化定位规则）、`media.py`、`uia.py`、`adapter.py`。
- 启动和切换控制器时做能力自检，结果进 `Diagnostics`。
- 只实现 M4 验证过的能力；没验证的 `supported=False`，并在 `note` 里写原因。
- 异常情况：酷狗未启动、窗口最小化、弹出广告或登录窗、酷狗更新后定位失败——都要返回明确的 `player_unavailable` 或 `state.error`，不能卡死工作线程（每个动作设超时）。
- **完成标准**：在 10.2.52 上，所有标为支持的能力用面板实际操作通过；拔掉酷狗（退出程序）后面板显示未连接，重开后自动恢复。
- **2026-11-09 完成情况**：四项支持的能力通过面板接口在真机上操作通过；收到托盘、彻底退出时面板给出明确原因，重开酷狗约 3 秒自动恢复。自检结果在 `GET /api/diagnostics`（含不可用原因）。酷狗模式下自动接歌保持关闭，因为它需要按歌名播放。广告/登录弹窗和版本不匹配只有单元测试，未在真机制造。
- **2026-11-10 补充**：按歌名播放和跳转进度已开放（向酷狗窗口投递鼠标、键盘消息，不抢焦点），面板的卡片播放、播队列下一首、上一首、拖进度在酷狗模式可用；做法、限制和真机结果见 [KugouCapabilities.md](KugouCapabilities.md)。酷狗模式自动接歌仍关闭：酷狗播完会自己接下一首。后端测试 99 项通过。

### M6 酷狗搜索（已完成）
- **2026-11-11 完成情况**：不读客户端界面，后端直接查酷狗的网络搜索接口（`KugouControl/Search.py`）；`/api/search` 返回酷狗结果，`/api/songs/from-kugou` 收录，面板上可直接播、排队、收进曲库，真机通过。做法和限制见 [KugouCapabilities.md](KugouCapabilities.md)。后端测试 104 项通过。
- 原 M4 结论（已过时）：酷狗 10.2.52 的搜索框不接受程序写入，本版本不做。
- 搜索接口里查询酷狗，最多等 8 秒，超时只返回曲库结果；前端分两次请求，曲库结果先出。
- 搜索结果的 `key` 只在后端短期有效（缓存 10 分钟即可），`POST /api/songs/from-kugou` 用它收录。

### M7 PPT 联动迁到后端（已完成）
- **2026-11-11 完成情况**：`PptControl/Link.py` 负责绑定、联动开关和翻页触发；`PptService` 只多了两个钩子。前端不再自己下达联动播放，旧的浏览器绑定在首次连上后端时自动导入。自动化测试覆盖「两个面板窗口、翻页只播一次」（后端 109 项、前端 9 项通过）。
- **2026-11-11 真机验收**（PowerPoint 放映 4 页测试文稿 + 酷狗 10.2.52，两个面板连接同时开着）：面板翻到绑了「晴天」的第 2 页，10.3 秒后酷狗播出；用 COM 直接翻到第 3 页（等同翻页笔），8.4 秒后播出 We Will Rock You；翻到没绑歌的第 4 页再翻回第 3 页不重播；已播记录只新增两条，两个面板收到的联动结果完全一致。酷狗不可用时翻页，两个面板都收到失败原因。WPS 演示没有做这项真机验收。验收中发现并修复：酷狗最小化时被误报成「未找到唯一酷狗主窗口」，现在提示「已最小化或收起至托盘」。
- 契约 §11 待定项：`PUT /api/ppt/bindings/{slide}`、`PATCH /api/ppt/settings`。
- `PptService` 检测到页码变化时（排除首次连接和断线重连），查绑定，交给播放器服务执行 `play`。
- 前端删除 `Ppt/PptStore.ts` 里的联动播放逻辑，绑定改为调用接口；把浏览器里已有的绑定一次性导入后端。
- **完成标准**：开两个浏览器窗口翻页，歌只播一次。

### M8 诊断与设置
- 契约 §3.6、§9：`/api/diagnostics`、`/api/diagnostics/refresh`、`PUT /api/settings/controller`；设置存数据库，重启后保持。
- **完成标准**：前端设置页显示真实版本、档案、能力自检结果，能在模拟和酷狗之间切换。

---

## 7. 测试

- 框架用标准库 `unittest`（与现有 `Tests/TestPpt.py` 一致），运行：
  ```powershell
  cd D:\DJproject\KuGouDashboard\Backend
  python -m unittest discover -s Tests -t . -p "Test*.py" -v
  ```
- **自动化测试不碰真实软件**：用替身对象（参考 `TestPpt.py` 里的 `FakeView` 等）和模拟控制器；数据库用 `:memory:`。
- 每个接口至少覆盖：正常返回、参数校验（422）、业务错误码、状态推送（用 `TestClient.websocket_connect`）。
- 涉及线程的，断言 COM / 界面自动化调用都发生在同一个工作线程。
- **探测脚本**（`Probes/`）在真机上手动运行。默认只读；会改变软件状态的脚本必须在开头打印提示并要求确认。
- 每个模块完成后在真机做一次手动验收，结果记进对应文档。

---

## 8. 和前端对接

接入一个模块时的检查清单：
- [ ] 契约里该模块标记从「规划中」改为「已实现」，变更记录加一行。
- [ ] 前端 `Common/Types.ts` 的类型与接口返回逐字段一致（已按契约对齐，新增字段要同步）。
- [ ] 前端只在功能文件夹里的 `*Api.ts` 和 `*Store.ts` 调接口，组件不直接调接口。
- [ ] 断开后端时，前端有明确的「未连接」提示，不白屏、不报未捕获异常。
- [ ] 浏览器里已有的本地数据（曲库、分组、PPT 绑定）提供一次性导入，避免用户手工重建。

---

## 9. 常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| COM 调用报「被调用的对象已与其客户端断开」或卡住 | 跨线程使用了 COM 对象 | 所有 COM 操作放在同一个工作线程，包括释放 |
| 界面自动化找不到酷狗控件 / 点击无效 | 权限不一致，或酷狗窗口最小化 | 两者同权限运行；操作前恢复窗口 |
| 坐标点击位置偏 | 屏幕缩放（DPI）不是 100% | 进程声明 DPI 感知，或尽量不用坐标点击 |
| 酷狗更新后功能失效 | 界面变化导致定位规则失效 | 版本档案 + 启动自检；演出机关闭酷狗自动更新 |
| 媒体键被别的程序接走 | 浏览器视频等也注册了媒体会话 | 优先用酷狗全局热键；演出时关掉其他播放器 |
| 控制台中文乱码 | 终端编码不是 UTF-8 | `$env:PYTHONUTF8=1`，或日志写文件 |
| `pip install` 超时 | 代理或镜像不通 | 见 §2.2 换源，或临时清空 `HTTPS_PROXY` |

---

## 10. 完成标准（每次提交前）

- [ ] `python -m unittest discover -s Tests -t . -p "Test*.py" -v` 全部通过（包含 `TestPpt.py`、`TestPptPreview.py`）。
- [ ] 新接口与契约一致；契约和本指南需要更新的地方已更新。
- [ ] 新增的外部软件操作在专用线程串行执行、有超时、失败时刷新状态。
- [ ] 错误返回带 `code` 和中文 `message`，日志里有堆栈。
- [ ] 前端 `pnpm build` 通过（改了前端时）。

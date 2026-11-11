# 酷狗能力验证（M4）

验证日期：2026-11-09，Windows 当前用户桌面会话，CPython 3.13.13。

M4 已完成：七项能力都有确定结论（见下表和「补充验证」一节）。M5 已按这些结论落地到 `Backend/KugouControl/`，`PLAYER_CONTROLLER=kugou` 可实际使用。本报告是该机器、该版本、该配置的真机验证，换版本后需重新验证。

## 版本与前提

- 运行文件：`C:\Program Files (x86)\KuGou\KGMusic\10.2.52.25713\KuGou.exe`。
- 启动器：`C:\Program Files (x86)\KuGou\KGMusic\KuGou.exe`。
- 两者 FileVersion / ProductVersion 均为 **10.2.52.25713**。酷狗有多个同名子进程，不能取第一个 PID 当主窗口。
- 主窗口类名 `kugou_ui`。必须先用进程归属筛选窗口，再确认唯一主窗口；不能匹配所有带“酷狗”的弹窗后直接点击。
- 设置 → 热键设置：**启用媒体快捷键已勾选，启用全局快捷键未勾选**。
- 设置 → 常规设置：“支持系统播放控件，如锁屏界面”未勾选。未修改这些设置。
- 当前桌面缩放下，UIA 矩形与展示截图的像素尺寸不同；不能将截图坐标直接硬编码进控制器。
- 用户明确同意真机播放、切歌测试，并要求结束后暂停。验收结束已回到音乐页，`7 rings (Explicit)` 停在 **00:24 / 02:58**，按钮为播放，前后观察进度未再推进。

## 能力结论

“能”表示本次实际路径已通过；“有条件”表示发现可用入口，但尚不满足长期运行、超时、状态核验等要求；“不能（当前配置）”只限定本次测试环境。

| capability | 结论 | 实测与前提 | M5 开放条件 |
|---|---|---|---|
| `read_state` | 能（每次重新读取） | 窗口标题能读到当前歌名、歌手；UIA 能找到曲目文字及播放/暂停按钮。重复 UIA 观察曾返回旧内容，独立进程重读后来获得新曲目和暂停按钮。标题本身不能区分播放与暂停 | 标题读取可作为曲目来源；状态必须重新读取并核验，不得把最后下发的命令当实际状态，读失败返回 unknown/error |
| `play_pause` | 能（系统媒体键） | `VK_MEDIA_PLAY_PAUSE` 从未播放进入播放，画面进度推进到 00:58；再次发送后暂停并保持 00:24。需要酷狗启用媒体快捷键，其他播放器可能抢键 | 自检配置、目标进程和命令后状态；没有可靠回读时仅能显示“已发送（未核验）” |
| `next` | 能（系统媒体键） | `VK_MEDIA_NEXT_TRACK` 从 Tuesday 切到 Ariana Grande 的 7 rings；在搜索结果播回 Tuesday 后，`VK_MEDIA_PREV_TRACK` 又切回 7 rings，均观察到进度推进 | 只代表酷狗自身列表的上下曲；面板 `next_in_queue` / `previous` 依赖 `play_track`，不能据此声称已支持 |
| `play_track` | **能（投递消息，有前提）** | UIA 写不进搜索框，但向主窗口投递鼠标、键盘消息可以输入搜索词、回车、点「单曲」、双击第一行，不抢焦点。结果页读不到文字，只能播第一条再按窗口标题核验 | 已开放。详见下文「按歌名播放与跳转进度」；窗口不能在托盘，换版本后重新量点击位置 |
| `read_position` | **能（UIA 只读）** | 播放栏 `进度` Slider 的 RangeValue：单位百分之一秒，最大值即时长。连续采样每 0.5 秒增加约 50；暂停时不变；切歌后归零并换成新时长；一首播完后同样归零。读一次 2–5 毫秒 | 已开放。切歌加载期间（标题为空的几秒）最大值还是上一首的，此时不给进度 |
| `kugou_search` | **能（网络接口）** | 客户端结果页读不到文字；改为后端直接查酷狗的网络搜索接口，拿到歌名、歌手、时长 | 已开放。接口非官方承诺，失效时只显示曲库结果 |
| `seek` | **能（投递点击）** | `RangeValue.SetValue` 只改显示不改播放位置；改为在进度条对应位置投递一次点击，是真跳转，播放和暂停时都有效 | 已开放。跳转后回读进度核验 |

UIA 的某些父节点标记 disabled，子节点仍可能 enabled；只检查目标控件及可见状态。控件多数 `automation_id` 为空，定位应使用窗口进程、控件类型、名称、父子关系和唯一性检查组合，不能保存一次探测的索引。

## 窗口标题与 SMTC

| 状态 | 同一主窗口的标题原文 |
|---|---|
| 初始未开始播放 | `酷狗音乐` |
| 播放 Tuesday | `Burak Yeter、Danelle Sandoval - Tuesday (feat. Danelle Sandoval) - 酷狗音乐 ` |
| 暂停 7 rings | `Ariana Grande - 7 rings (Explicit) - 酷狗音乐 ` |

曲目标题末尾有空格，应先 trim，再去掉末尾固定应用名；歌名本身可能有 ` - `，不能不加验证地按所有分隔符拆分。暂停不会清空歌曲标题，因此只靠标题不能推断 playing / paused。

初始、播放中、暂停后均调用 Windows `GlobalSystemMediaTransportControlsSessionManager`，当前返回 **0 个会话**。所以本配置下无法通过 SMTC 回读播放状态/进度。这与设置页的系统播放控件关闭一致，但尚未做开关对照实验，不能断言开启后一定支持；不要将缺少 Python 依赖、探测超时和“0 会话”混为一谈。[微软 SMTC 文档](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssessionmanager?view=winrt-26100)

全局快捷键页面显示播放/暂停 `Alt+F5`、上一首 `Alt+Left`、下一首 `Alt+Right`，但总开关关闭，字段灰色。本次尝试 Alt+F5 未观察到酷狗播放状态改变，也未完成后台接收验证，**不标为可用**；M5 不应假设默认热键已启用。系统媒体键已经通过，不必为本项目自动修改用户热键配置。

## 选择的实现路线

1. **M5 已落地**：媒体键播放/暂停、酷狗自身上下曲、标题读取曲目、播放栏读取播放状态和进度；连接检测、串行命令、超时、命令后核验、断线恢复均已实现并真机通过。
2. **（已过时，见「按歌名播放与跳转进度」）当时按歌名播放采用专用歌单人工选曲退路**：演出前在酷狗准备歌单，现场由酷狗选曲，面板只提供核验过的基础控制。该退路不等于面板队列已能指定任意歌曲；酷狗模式下 `play_track` 仍为 false，关联的卡片播放、面板队列接歌保持禁用。
3. **（已过时）当时判断按歌名播放、酷狗搜索、跳转进度在 10.2.52 上做不了**（控件不接受 UIA 写入）；2026-11-10 改用投递消息后，按歌名播放和跳转进度已开放。因此酷狗模式下自动接歌、卡片播放、面板队列接歌保持禁用。酷狗升级后先跑探测，搜索框可写再重新评估。

## 酷狗搜索（2026-11-11）

客户端的搜索结果页读不到文字，所以不从客户端读：后端直接查酷狗的网络搜索接口（`http://mobilecdn.kugou.com/api/v3/search/song`），拿到歌名、歌手、时长，和客户端搜的是同一个曲库。代码在 `Backend/KugouControl/Search.py`，只用标准库，不操作酷狗窗口，酷狗没开也能搜。

- 面板搜索时曲库结果马上出；停止输入 0.4 秒后再查酷狗，结果回来补在「酷狗搜索」一栏，已在曲库里的不重复显示。
- 酷狗结果可以直接播、排队或收进曲库：都会先收进曲库（`source=kugou`，带时长，没有 BPM），播放仍走「按歌名播放」，由酷狗客户端搜「歌名 歌手」播第一条并核验。
- 最多等 8 秒；超时、断网、接口变了都只是这次没有酷狗结果，曲库搜索不受影响。同一个词 10 分钟内不重复查网络。
- **这个接口不是酷狗公开承诺的**，哪天改了或关了，酷狗搜索会显示「不可用」，需要换地址或改解析。`KUGOU_SEARCH=off` 可以整个关掉。
- 网络接口排第一的和客户端排第一的可能不是同一条（版本很多的歌尤其如此）；播出来的不是要的那首时会照常报错。

真机结果（本机经代理访问酷狗较慢）：搜「稻香 周杰伦」3.8 秒返回 25 条，同词再搜即时返回；收录「稻香 (2018 CCTV-15…现场)」后由酷狗播出，12.5 秒，标题核验通过。在面板界面搜「夜曲 周杰伦」显示 26 条，点 ▶ 自动收进曲库并播出。

## 按歌名播放与跳转进度（2026-11-10）

早先结论「做不了」只试了 UIA 写入和抢焦点模拟键盘。改用**向酷狗主窗口投递鼠标、键盘消息**（`PostMessage`）后两项都能做，而且不移动真实鼠标、不切换前台窗口，PPT 放映时可用。代码在 `Backend/KugouControl/Input.py`（投递）和 `Track.py`（流程与核验）。

**按歌名播放**的步骤：点搜索框 → 清掉旧词 → 逐字投递「歌名 歌手」并回读确认 → 回车 → 等结果列表画面换新并停稳 → 点「单曲」→ 双击第一行 → 看窗口标题是不是要的那首。

- 搜索结果页是画出来的，读不到文字，所以**只能播第一条，播出来才知道对不对**。标题里歌名、歌手对不上就报「第一条是「歌手 - 歌名」，不是要播的歌」，这时酷狗已经在放那首错的歌，需要人工处理。歌手只在歌名正文里出现（如「王安卿 - Unstoppable Sia」）按翻唱算不匹配。
- 「单曲」页签和第一行按位置点击，坐标相对结果页左上角，在搜索框高 48 像素时量得，按搜索框实际高度等比缩放（`Profiles.SEARCH_LAYOUT`）。酷狗改版后要重新量。
- 为了不点到上一次搜索留下的结果，回车前后比对结果列表的画面（`PrintWindow` 取图做指纹），换新并停稳才点。
- 一般 5–9 秒完成。酷狗连接慢时窗口标题会空十几秒到几十秒：等 12 秒还没出标题就返回 409「酷狗还在连接…」，队列和已播先不动；之后读到这首歌真的在播，再自动出队、记已播、对上曲库歌曲。
- 面板据此开放了卡片播放、「播队列下一首」、面板「上一首」（回放本场已播）。

**跳转进度**：在进度条对应比例的位置投递一次点击，2 秒内回读进度核验（容差为时长的 2%，至少 3 秒）。播放、暂停时都有效，跳转后酷狗缓冲一两秒再继续走。

**仍然做不了的**（`kugou_search` 已于 2026-11-11 改走网络接口实现，见上节）：
- 酷狗模式自动接歌：酷狗播完一首会自己接着放下一首，面板来不及接管；请用「播队列下一首」。
- 酷狗窗口最小化或收到托盘时不能操作。**必须由人点开窗口**：用程序把托盘里的窗口强行显示出来，画面不刷新、搜索框不收字。窗口被别的窗口盖住没有影响。

**真机结果**（10.2.52.25713，面板接口 + 数据库副本，全程酷狗在后台）：

| 操作 | 结果 |
|---|---|
| 播放「晴天 / 周杰伦」 | 5.7 秒返回，状态带曲库 `song_id` |
| 连续搜四首不同的歌 | 7.8–13 秒，每次都播到对的歌 |
| 入队后「播队列下一首」 | 4.7 秒，出队并记已播 |
| 「平凡之路 / 朴树」连接慢 | 16.8 秒返回「还在连接」，约 10 秒后开始播放，队列和已播自动补记 |
| 「Unstoppable / Sia」 | 第一条是翻唱，报「第一条是「王安卿 - Unstoppable Sia」」 |
| 跳到 60 秒、120 秒 | 0.4–0.5 秒返回，进度落在 59.9、119.6 并继续走 |
| 搜不到的词 | 报「没有开始播放」，原曲不受影响（改用画面比对前测得约 7 秒，之后未重测耗时） |
| 窗口缩小并挪位置后重试 | 正常（坐标相对结果页，不依赖窗口位置） |

面板「上一首」第一次真机测试时点到了上一次搜索的旧结果，由此加了上面的画面比对。2026-11-11 复测：连播几首后连按三次「上一首」，依次回到晴天、平凡之路、We Will Rock You，每次 7.8–8.8 秒，已播记录不变。复测中还发现：刚点的歌仍在连接、没记进已播时按「上一首」会多跳过一条，已修（只有单元测试，真机未再制造这种情况）。

## 补充验证与 M5 落地（2026-11-09）

曲目：Gwen Stefani《Harajuku Girls》（04:50）、Britney Spears《Showdown》（03:17）。

**进度条连续采样**（每 0.5 秒读一次 `进度` Slider）：

| 场景 | 观察 |
|---|---|
| 暂停 | 值保持 205 不变，最大值 29056（290.56 秒，对应 04:50） |
| 播放 | 322 → 377 → 430 → 480 → 531 → …，每 0.5 秒约 +50，即每秒 100 |
| 下一首 | 值立刻归 0；标题变成 `酷狗音乐` 约 4.5 秒，这期间最大值仍是 29056；标题出现后最大值变 19798（197.98 秒，对应 03:17），值从 0 开始走 |
| 再次暂停 | 值停在 504 |
| 上一首（暂停状态下按） | 归 0，标题空约 1 秒，最大值换回 29056，自动开始播放 |
| 播到结尾（单曲循环） | 28991 之后归 0，标题空约 2.5 秒，然后同一首从头播；没有出现「停止」状态 |

**写入类操作**：

| 操作 | 结果 |
|---|---|
| 进度条 `RangeValue.SetValue(6000)`（暂停时） | 调用成功，读回 6000；恢复播放后回到真实位置 11 秒附近。不是真跳转 |
| 进度条 `SetValue(最大值-500)`（播放时） | 调用成功，播放位置没变 |
| 搜索框 `ValuePattern.SetValue("周杰伦 晴天")` | `COMError 尚未实现` |
| 搜索框 `LegacyIAccessible.SetValue` | `COMError 尚未实现` |

搜索框只支持 Invoke、LegacyIAccessible、Value（只读）三种模式，没有 TextPattern。

**通过面板接口的真机操作**（临时后端 + 数据库副本，`PLAYER_CONTROLLER=kugou`）：

| 操作 | 结果 |
|---|---|
| 自检 `/api/diagnostics` | 版本 10.2.52.25713，`read_state` / `play_pause` / `next` / `read_position` 支持，`kugou_search` 不支持并带原因（`seek` / `play_track` 当时未开放，2026-11-10 已开放，见下节） |
| 播放/暂停 | 0.5 秒内返回，状态和进度与酷狗一致 |
| 酷狗下一首、上一首 | 约 1 秒返回，新曲目、新时长、进度从 0 开始 |
| `seek`、`play` | 当时返回 409 `capability_unsupported`；2026-11-10 起可用，见下节 |
| 关闭酷狗窗口（收到托盘） | 面板提示「酷狗窗口已最小化或收起至托盘，请恢复窗口后控制」，命令返回 503 `player_unavailable` |
| 彻底退出酷狗 | 面板显示未连接、「未找到唯一酷狗主窗口，请启动酷狗并关闭多余弹窗」，所有能力变为不支持 |
| 重新打开酷狗 | 约 3 秒内自动恢复连接，无需重启后端；随后播放/暂停正常，进度恢复 |

酷狗刚启动、还没播放时窗口标题是 `酷狗音乐`，面板曲目名为空；按一次播放后才显示曲目。

没有验证的情况：酷狗弹出广告/登录窗、酷狗升级后版本不匹配，这两种只有单元测试覆盖（拒绝发按键并返回原因），没有在真机上制造出来。

## 复现探测

依赖仅用于真机探测，不加入常驻服务 requirements。已在独立环境安装并实际运行：

```powershell
cd D:\DJproject\KuGouDashboard
python -m venv Probes\.venv
Probes\.venv\Scripts\python.exe -m pip install -r Probes\Requirements.txt

Probes\.venv\Scripts\python.exe Probes\KugouVersion.py --output Probes\Results\version.json
Probes\.venv\Scripts\python.exe Probes\KugouWindow.py --label idle --output Probes\Results\window-idle.json
Probes\.venv\Scripts\python.exe Probes\KugouSmtc.py --output Probes\Results\smtc-idle.json
Probes\.venv\Scripts\python.exe Probes\KugouUiaTree.py --timeout 45 --output Probes\Results\uia.json
Probes\.venv\Scripts\python.exe Probes\KugouUiaTree.py --depth 4 --values --timeout 45 --output Probes\Results\uia-values.json
```

- 没启动酷狗时，version/window 的 `running=false` 是有效观察。`KugouVersion.py --exe "安装文件路径"` 可只读安装版本，但不会把安装等同于正在运行。
- `--label` 是操作员声明，输出 `label_verified=false`，脚本不会从标题猜测状态。分别在真实 playing / paused 状态重新运行并保存不同文件。
- UIA 默认深度 8、最多 500 节点，`truncated=true` 表示树有截断。搜索结果位于较深的内嵌文档，可用 `--depth 32 --max-nodes 1000`；超时返回 timeout，而非“不支持”。
- `--backend win32` 用于对照。本次 Win32 只得到主窗口一个节点，不能因此推断 UIA 也无控件。UIA 成功导出过 150、352、87 节点的不同深度快照。
- `--hwnd` 只接受已确认属于酷狗的可见窗口，窗口不唯一则报告候选，不擅自选择。
- `--values` 只读可见的搜索框、进度/音量滑块和曲目文字，不读取设置页的账号、密码字段。完整控件名仍可能包含个人信息，原始结果留在本机，`Probes/Results/` 已忽略。
- 只读探测在子进程中执行，默认 15 秒超时，可设 0–120 秒；超时终止探测子进程，不退出酷狗。
- `status=ok` 仅代表脚本完成。还要检查 `running`、`available`、节点和会话内容；错误返回 dependency_missing/error/timeout 和非零退出码。

按键脚本默认不改变播放状态：

```powershell
Probes\.venv\Scripts\python.exe Probes\KugouMedia.py --action toggle

# 以下每条都会提示，并要求手工输入“执行”；只发送一次，不重试。
Probes\.venv\Scripts\python.exe Probes\KugouMedia.py --action toggle --execute
Probes\.venv\Scripts\python.exe Probes\KugouMedia.py --action next --execute
Probes\.venv\Scripts\python.exe Probes\KugouMedia.py --action previous --execute

# 仅在设置页确认实际已启用该热键后测试；示例不代表默认已启用。
Probes\.venv\Scripts\python.exe Probes\KugouMedia.py --hotkey alt+f5 --execute
```

按键结果始终 `verified=false`，即使 `sent=true` 也只是尝试发送过；要用酷狗画面/新鲜状态核验。测试前避免其他播放器接收媒体键，测试结束确认暂停。不能连续盲发 toggle 来“保证暂停”。

## 本机记录与自动化检查

原始 JSON 在本机 `Probes/Results/`：version、window-idle/playing/paused、smtc-idle/verified-playing/paused、uia-search/uia-paused/uia-values-paused、media-toggle/next/previous/pause。UIA 超时结果也保留，不以重试成功覆盖首次失败。

本次可见验收：Tuesday 播放 00:58/04:01 → 下一首 7 rings 播放 → 搜索结果选回 Tuesday 播放 00:32/04:01 → 上一首 7 rings 播放 → 暂停并保持 00:24/02:58。SMTC 观察没有会话。独立进程读取最终 UIA 值 2423/17867、曲目 7 rings、按钮“播放”，与最终暂停画面一致。

自动化测试在 `Backend/Tests/TestKugouProbes.py`，不连接真实软件，覆盖默认不发按键、拒绝确认不发送、发送不冒充核验、非法热键拒绝、探测超时及异常输出、其他媒体会话过滤。运行：

M4 探测阶段后端全量 68 项测试通过；M5 落地后为 88 项通过，按歌名播放和跳转进度落地后为 99 项通过，酷狗搜索落地后为 **104 项通过**（`Tests/TestKugou.py` 覆盖进度换算、切歌期间隐藏进度、能力声明、退出与恢复、慢切歌等待）。

```powershell
cd D:\DJproject\KuGouDashboard\Backend
python -X utf8 -m unittest discover -s Tests -t . -p "Test*.py" -v
```

## 参考项目的采用范围

参考项目提供思路，本机能力结论来自上面的真实操作与读取。

- [pywinauto](https://github.com/pywinauto/pywinauto)：采用 Win32/UIA 双后端对照的方法，真机脚本实际依赖它；其 Win32 与 UIA 支持不能保证任意酷狗控件可操作。
- [AutoHotkey](https://github.com/AutoHotkey/AutoHotkey)：参考短脚本验证按键的做法；本项目不增加 AHK 常驻进程。
- [Bitfocus Companion](https://github.com/bitfocus/companion)：保留为未来宏按钮和外部硬件扩展参考，本期继续使用已有 Vue/FastAPI。
- [Open Stage Control](https://framagit.org/jean-emmanuel/open-stage-control)：保留为控制台交互参考；其 [GitHub README](https://github.com/jean-emmanuel/open-stage-control) 已明确仓库迁移到 Framagit。
- [Mixxx Auto DJ 文档](https://manual.mixxx.org/2.5/en/chapters/djing_with_mixxx.html#auto-dj)：参考队列、自动接歌的交互；未复制或集成 Mixxx 代码。
- KugouControl：用户提供了角色与局限说明，但本次检索没有唯一确定对应仓库，未把它当已读源码或本机验证证据；网络到按键链路已经由本项目自己的探测确认。

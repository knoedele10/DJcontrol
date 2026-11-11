# PPT 控制与页码同步

PPT 功能已接入 FastAPI 后端。歌曲搜索和音乐播放仍沿用现有模拟实现。

## 启动

在 Windows 上使用常规 CPython，打开 PowerPoint 或支持 COM 的 WPS 演示，并在其中打开文稿。

```powershell
cd D:\DJproject\KuGouDashboard\Backend
python -m pip install -r Requirements.txt
python -m uvicorn Main:app --host 127.0.0.1 --port 8000
```

另开终端启动前端：

```powershell
cd D:\DJproject\KuGouDashboard\Template
pnpm install
pnpm dev --host 127.0.0.1
```

访问 Vite 输出的地址，在 PPT 面板中选择 PowerPoint 或 WPS 演示。默认连接 PowerPoint；也可以在启动后端前设置 `$env:PPT_APP = 'wps'`。前端现有 Vite 配置已代理 `/api` 和 `/ws`。部署构建产物时也需要代理这两个路径。

连接使用当前 Windows 用户会话中的活动 COM 对象，不会自动启动、打开或关闭演示软件。后端和演示软件应在同一个桌面会话中运行。WPS 版本需实际提供演示 COM 接口，不能仅凭安装了 WPS 判断兼容性。

## 目录与职责

```text
Backend/PptControl/
  Base.py          # PptController、状态和异常定义
  PowerPoint.py    # PowerPoint.Application
  Wps.py           # KWPP.Application，兼容 WPP.Application
  Com.py           # 两者共用的演示对象模型操作
  __init__.py      # 控制器工厂
  Service.py       # 单线程操作、轮询和状态订阅
  PreviewCache.py  # 当前文稿的预览文件缓存
  Model.py         # 请求结构
  Api.py           # HTTP 与 WebSocket
Template/src/Ppt/
  PptApi.ts        # HTTP、心跳和断线重连
  PptPreload.ts    # 整稿预载与提前解码
  PptStore.ts      # 真实状态、页码和歌曲绑定
  PptPanel.vue     # 面板
  SlidePreview.vue # 幻灯片预览
```

所有 COM 创建、读写与释放均在同一个专用线程执行。监听不依赖面板按钮或浏览器键盘事件：后端每 250 毫秒读取演示软件状态，有变化才推送。因此演示软件内的键盘、翻页笔和面板翻页都通过实际页码同步。250 毫秒是轮询间隔，不是端到端延迟保证；短于间隔的多个翻页可能合并为最新页。

面板不会先修改页码再等待确认。每条命令后都会重新读取状态，失败不会自动重试翻页。连接恢复后自动重新读取；慢连接只保留最新快照。多个浏览器共享后端所选的演示软件。

## 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/ppt/state` | 读取最新状态 |
| GET | `/api/ppt/preview/{slide}?app=powerpoint&document=...&width=1280&session=...` | 返回指定文稿页面的 PNG，主预览和缩略图共用同一张图片 |
| POST | `/api/ppt/connect` | 选择软件：`{"app":"powerpoint"}` 或 `{"app":"wps"}` |
| POST | `/api/ppt/command` | 执行控制命令并返回重新读取的状态 |
| WS | `/ws/ppt` | 连接时立即返回快照，此后推送变化 |
| GET | `/api/health` | 服务存活检查 |

命令 JSON：

```json
{"action":"next"}
{"action":"previous"}
{"action":"goto","slide":5}
{"action":"black","enabled":true}
{"action":"black","enabled":false}
{"action":"start"}
{"action":"start","slide":3}
{"action":"stop"}
```

页码统一从 **1** 开始。`goto` 和 `start` 的页码必须在实际文稿范围内。省略 `start.slide` 时从当前选中页开始；无法读取当前页时从第一页开始。前后翻页按文稿页码跳转，跳过动画步骤，在首尾边界返回错误。编辑模式支持翻页和跳页，黑屏要求正在放映。

响应及 WebSocket 快照示例：

```json
{
  "type": "ppt_state",
  "revision": 7,
  "preview_session": "文稿载入时生成的缓存标识",
  "state": {
    "app": "powerpoint",
    "connected": true,
    "document_id": "D:\\演出.pptx",
    "file": "演出.pptx",
    "current_slide": 3,
    "total_slides": 12,
    "running": true,
    "black": false,
    "error": null
  }
}
```

`current_slide` 为 `null` 表示没有可读取的当前页。软件已连接但未打开文稿时，`connected` 为 `true`、`total_slides` 为 `0`。软件退出、忙碌或未开放 COM 时，状态返回 `connected: false` 与原因，清空文稿和页码。WebSocket 无变化时每 15 秒发送 `{"type":"ping"}`，前端断线后自动重连。

错误：请求结构不合法为 HTTP 422；无文稿、越界或未放映黑屏为 409；软件不可连接为 503。后两者使用 `{"detail":{"code":"...","message":"..."}}`。

## 使用边界

- 优先控制第一个正在放映的窗口；没有放映窗口时读取活动文稿。暂不提供多文稿选择。
- 本机观察到 WPS 会把 `PowerPoint.Application` 的活动对象也指向自己；PowerPoint 实现会检查软件路径并明确提示选择 WPS，避免软件名称与实际控制目标不一致。
- 当前页通过 `View.Slide.SlideIndex` 获取，避免把自定义放映的顺序号误当成文稿页码。面板的前后翻页按物理页码执行，可能进入隐藏页；翻页笔仍遵循演示软件自己的放映顺序。
- 面板展示真实幻灯片的静态页面预览和缩略图，翻页后切换到对应页。通过演示软件的 `Slide.Export` 生成图片，不改变当前选中页和放映位置；不包含播放中的动画、视频或激光笔。页面编辑后可点击“刷新预览”重新读取图片。
- 载入文稿后自动预载全部页面并提前解码，优先当前页、下一页和上一页。后台一次读取一页，让翻页命令有机会在两页读取之间执行；面板显示预载进度，就绪后直接使用浏览器缓存，不再逐页调用演示软件。
- 主预览和缩略图复用同一张 1280 像素宽的页面图片，避免重复导出不同尺寸。预览请求携带软件、文稿和 `preview_session`；后端重启、切换文稿或页数变化会生成新的标识，避免读到旧图片。
- 后端使用当前文稿专用的临时文件缓存，至少容纳整稿，不按 20 秒或 32 张限制淘汰；命中后直接返回图片，不读取 COM 状态。切换文稿或正常关闭服务时删除这些缓存文件。文稿仍打开时，图片编辑后的更新需要点击“刷新预览”。
- 携带有效 `session` 的图片响应使用私有浏览器缓存，URL 包含文稿会话和刷新版本；兼容未携带 `session` 的旧客户端时仍使用 `no-store`。刷新预览会重新预载整稿；切换文稿、断线或页面关闭时取消上一批预载并释放图片对象。
- 本机 WPS 12 的普通全屏放映已通过验证，窗口放映模式（`ShowType=2`）在实测中启动报错。遇到该情况应先在 WPS 中把放映类型改为普通放映；面板不会擅自修改文稿的放映设置。
- 歌曲绑定按软件、文稿路径和页码保存在后端数据库（旧版存在浏览器里的会自动导入一次）；翻页联动播放由后端触发，多个面板窗口同时打开也只播一次。插入、删除、重排幻灯片或文稿另存后，应重新检查绑定。

## 验证

```powershell
cd D:\DJproject\KuGouDashboard\Backend
python -m pip install -r RequirementsDev.txt
python -m unittest discover -s Tests -t . -p "Test*.py" -v

cd D:\DJproject\KuGouDashboard
python Probes/PptState.py powerpoint
python Probes/PptState.py wps

cd Template
pnpm test
pnpm build
```

自动化测试用替代 COM 对象和测试客户端验证协议、单线程归属、页码边界、断线和 WebSocket 外部变化推送。探测脚本只读取实际应用状态，不会启动软件或修改文稿。真实软件验收时，应在自己的测试文稿中分别检查按钮、跳页、黑屏、F5/Esc、翻页笔以及退出软件后的重连。

2026-11-07 本机验证结果：15 项后端测试、5 项前端状态测试与前端构建通过。使用临时文稿验证了真实 PowerPoint 的 HTTP 翻页、跳页、黑屏、开始/结束放映及外部页码读取；真实 WPS 的相同命令及外部页码、黑屏变化的 WebSocket 推送也通过。另补充了 WPS 退出放映后窗口数量短暂滞后及兼容接口接管的回归测试。没有连接实体翻页笔；外部变化验证通过直接操作演示软件的放映画面对象完成。临时测试文稿在验证后关闭，未保存到用户目录。

对象模型参考：[PowerPoint 当前幻灯片](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.slideshowview.slide)、[跳页](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.slideshowview.gotoslide)、[放映状态](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.ppslideshowstate)、[WPS 演示 Application](https://open.wps.cn/documents/app-integration-dev/wps365/client/wpsoffice/jsapi/wpp/Application/obj)。WPS 的文档说明对象模型，不代表每个桌面发行版都开放外部 COM。

预览修复验证：18 项后端测试、6 项前端测试及构建通过；当前打开文稿的 1280×720 页面预览和 240×135 缩略图，经 Vite 代理取得有效 PNG，读取前后放映页码和运行状态保持一致。页面导出接口参考：[PowerPoint Slide.Export](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.slide.export)。

整稿预载验证：20 项后端测试、8 项前端测试及构建通过，覆盖整稿预载、优先级、提前解码、失败后继续、取消旧文稿、翻页不重载、40 页缓存不淘汰以及命中缓存不访问 COM。当前 14 页文稿的图片全部校验通过，合计约 14.94 MiB；经本机 Vite 代理测得首次生成每页响应中位数约 510 毫秒，缓存响应约 31 毫秒。这是服务端响应测量，浏览器预载后直接使用自身缓存。验证期间文稿页码和放映状态未改变。

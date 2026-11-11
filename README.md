# 酷狗统筹面板（KuGouDashboard）

活动现场用的控制面板：管理曲库和分组、排队播放（模拟或酷狗）、控制 PowerPoint / WPS 翻页并按页联动放歌。

- 后端 `Backend`：FastAPI + SQLite，运行在 Windows（COM、界面自动化需要和酷狗、PPT 同一桌面会话）
- 前端 `Template`：Vue 3 + Vite + Pinia

## 快速开始

首次安装见 [Docs/BackendGuide.md §2.2](Docs/BackendGuide.md)，之后：

```powershell
.\Scripts\Dev.ps1           # 后端 8000 + 前端 5173
.\Scripts\StartBackend.ps1  # 只起后端
.\Scripts\Build.ps1         # 构建前端，单进程运行在 8081
.\Scripts\Test.ps1          # 后端 + 前端自动化测试
docker compose up -d --build  # 容器出界面，转发到 Windows 后端（8080）
```

## 目录

同一功能的代码放在同一个文件夹里，文件名不带下划线、连字符。

| 目录 | 内容 |
|---|---|
| `Backend/KugouControl/` | 控制酷狗：版本识别、窗口、媒体键、界面自动化 |
| `Backend/PptControl/` | 控制 PowerPoint / WPS：控制器、服务、预览缓存、路由 |
| `Backend/Player/` | 播放器接口与模拟实现、队列、场次、已播 |
| `Backend/Library/` | 曲库、分组、本地搜索 |
| `Backend/Diagnostics/` | 诊断与设置（预留） |
| `Backend/Database/` | SQLite 连接、仓储、种子数据、`Migrations/` |
| `Backend/Tests/` | unittest，文件名 `Test*.py` |
| `Backend/Data/` | 运行时数据库和日志（不入库） |
| `Template/src/Pages/` | 页面，每个页面一个文件夹：`Dashboard/`、`Settings/` |
| `Template/src/Library/` 等 | 按功能放组件、状态（`*Store.ts`）和接口（`*Api.ts`）：`Library`、`Playback`、`Queue`、`History`、`Scenes`、`Ppt`、`Diagnostics` |
| `Template/src/Common/` | 公共组件、类型、格式化、本地存储 |
| `Template/Tests/` | 前端测试 |
| `Probes/` | 酷狗、PPT 能力探测脚本；`Results/` 为本机输出（不入库） |
| `Docs/` | 设计和开发文档 |
| `Scripts/` | 启动、构建、测试脚本 |
| `Desktop/` | 预留：桌面外壳，尚未开始 |

## 文档

- [ApiContract.md](Docs/ApiContract.md)：前后端接口契约，改接口先改这里
- [BackendGuide.md](Docs/BackendGuide.md)：环境、目录、里程碑进度、完成标准
- [PptControl.md](Docs/PptControl.md)：PPT 模块，新模块的参考模板
- [KugouCapabilities.md](Docs/KugouCapabilities.md)：酷狗各项能力的验证结论
- [Prototype/](Docs/Prototype/)：界面原型

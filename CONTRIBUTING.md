# 贡献指南（CONTRIBUTING）

本仓库按 GitHub 多人协作流程开发。开工前先读完这一页；流程冲突的地方，以维护者（Claude）在 PR 评审里的意见为准。

## 团队分工

| 成员 | 职责 |
|---|---|
| Claude | 维护者：建立议题与里程碑、评审、squash 合并、真机验收 |
| Codex | 后端：拆分 `Playlist.py`、歌单提速 |
| Antigravity | 前端/桌面：第二屏实时监看 |
| ZCode | 工程支持：协作规范与 CI、全项目体检报告 |

具体任务以仓库 Issues 为准，负责人通过 `owner:*` 标签标注。

## 开发流程：议题 → 分支 → PR → 评审 → CI → 合并

1. **认领议题**：每项工作对应一个 issue，先读完任务书（「要做的事」「文件归属」「验收」）。
2. **建分支**：从最新 `origin/master` 建自己的分支；并行开发一律用独立工作树（见下文）。
3. **提交**：只改议题「文件归属」里列的文件；提交信息用 Conventional Commits。
4. **提 PR**：标题带成员前缀，如 `[ZCode] ci: 协作规范与 GitHub Actions CI`；正文按 PR 模板写清做了什么、关联议题（`Closes #N`）、怎么测的。
5. **评审**：维护者在 PR 上评论，需要修改的就在同一分支继续提交。
6. **CI**：PR 必须三项检查（后端 / 前端 / 桌面端）全部通过才可合并。
7. **合并**：维护者以 squash 方式合并，议题随 `Closes #N` 自动关闭。

## 分支命名

`<类型>/<简短英文说明>`，类型只能从下面选：

- `feat/` 新功能
- `fix/` 修复缺陷
- `perf/` 性能优化
- `refactor/` 重构（不改行为）
- `chore/` 构建与工程杂务
- `docs/` 文档

例：`feat/second-screen-monitor`、`fix/playlist-detect`、`chore/ci-and-contributing`。

## 提交信息（Conventional Commits）

```
<类型>(<范围>)?: <一句话描述>
```

- 类型同分支命名的六类，另加 `test:`（测试）与 `ci:`（CI 配置）。
- 描述用中文或英文均可，祈使句，结尾不加句号。
- 例：`ci: 添加 GitHub Actions 三项检查`、`fix(playlist): 修复歌单检测读不到酷狗歌单`。

## 工作树（并行协作）

主目录 `D:\DJproject\KuGouDashboard` 是维护者的工作区，**其他成员不要在主目录做任何改动**，一律在自己的工作树里干活：

```powershell
git fetch origin
git worktree add .worktrees/<名字> -b <分支> origin/master
```

- 每个成员只在自己的 `.worktrees/<名字>` 里改代码，不要碰别人的工作树。
- `.worktrees/` 已在 `.gitignore` 里，不会被提交。
- 分支合并后清理：`git worktree remove .worktrees/<名字>`。

## 文件归属

- 每个 PR 只改自己议题「文件归属」里列出的文件；别处看到问题就在 PR 里留言或另开议题，不要顺手改。
- 跨区域的公共文件（如 `Docs/ApiContract.md`、`README.md`）需要变更时，先在 PR 正文里说明原因。
- `.github/**` 与协作文档由 CI/规范负责人维护，其他人要调整时提议题或在 PR 里留言。

## 本地测试（三项）

提 PR 前在本地把三项各跑一遍，CI 跑的是同样的命令：

```powershell
# 后端：Python 3.13（运行数据与日志在 Backend/Data/，不入库）
cd Backend
python -m pip install -r RequirementsDev.txt    # 已含 Requirements.txt 和测试所需 httpx
python -m unittest discover -s Tests -t . -p "Test*.py"
```

```powershell
# 前端：Node 24 / pnpm 11
cd Template
pnpm install --frozen-lockfile
pnpm test
pnpm build
```

```powershell
# 桌面端：类型检查 + 构建 + node 测试，不启动 Electron
cd Desktop
$env:ELECTRON_SKIP_BINARY_DOWNLOAD = '1'        # 安装时跳过 Electron 二进制下载
pnpm install --frozen-lockfile
pnpm test
```

> 统一用 `python -m pip` 而不是裸 `pip`：本机装了多个 Python 时，裸 `pip` 可能装进另一个解释器的环境。

## 真机验证

涉及**酷狗、PPT（PowerPoint / WPS）、桌面窗口**的改动，自动化测试覆盖不了真实行为，PR 里必须写明：

- 是否已在真机验证（本机 Windows + 真实酷狗 / WPS）；
- 验证了哪些场景、结果如何；
- 未验证的部分单独列出，由维护者决定是否合并或补充验收。

没写明的 PR 会被要求补充说明后再进入评审。

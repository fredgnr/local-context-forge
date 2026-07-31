# 安装与快速开始

本页按未来经过审查的 Electron DMG 描述普通用户流程，同时明确当前限制。更完整的签名、
MCP、更新、恢复和开发者说明见
[Electron 桌面版完整指南](16-electron-desktop-guide.md)。当前是否已有合格资产以
[状态快照](development/status.md)为准。legacy 路径已弃用并待删除，不再作为 quickstart
fallback。

## 0. 先确认你拿到的是可审查发行物

当前仓库已经有桌面代码和 Release workflow，但以下门禁仍是 `not-run`：

- 干净 macOS 用户安装；
- 打包应用中的真实 Codex 采集；
- 物理 Apple Silicon embedding 下载/重建；
- 真实 `N-1 → N` 物理更新。

在 GitHub Releases 出现经过维护者审查的一组正式资产之前，不要把源码构建或
`*-UNOFFICIAL.dmg` 当作推荐安装包。正式资产至少应同时包含：

- `local-context-forge-<version>-arm64.dmg`
- `SHA256SUMS`
- `release-manifest.json`
- `update-manifest.json`
- `update-manifest.json.sig`

Electron 是**有审查 Release 后的推荐目标**。在合格 Release 出现前，当前没有可推荐给普通
用户的稳定安装；不要运行 `./install.sh` 新建已弃用的 legacy 服务。

## 1. 准备 Codex CLI

桌面版默认使用当前 macOS 用户已经登录的 Codex CLI。先在终端检查：

```bash
codex --version
codex login status
```

如未登录：

```bash
codex login
```

应用不会索取、复制或保存 Codex 登录文件，也不会把 `~/.codex` 放进应用数据。实际调用使用
本机 CLI 和该账号的 Codex 用量。没有可用 Codex 时仍可打开应用和查询已有知识，但新的 Wiki
生成会失败，除非你事先在设置中明确允许符合条件的 Cursor fallback。

## 2. 安装 DMG

1. 从项目的官方 GitHub Release 下载 arm64 DMG 和 `SHA256SUMS`；
2. 按 Release 页面核对文件名与摘要；
3. 双击 DMG；
4. 把 `Local Context Forge.app` 拖到“应用程序”；
5. 从“应用程序”打开，不要长期从 DMG 或下载目录运行。

该发行策略使用项目自签名证书，不是 Apple Developer ID，也不 notarize。若 macOS 拦截：

1. 在 Finder 中按住 Control 点击应用，选择“打开”；
2. 若仍被拦截，打开“系统设置 → 隐私与安全性”；
3. 找到刚才被拦截的 Local Context Forge，选择“仍要打开”；
4. 再确认一次。

不要关闭 Gatekeeper，不要运行 `xattr -dr`，也不要使用 `sudo`。如果系统没有显示可撤销的
“打开”选项，就停止并核对 Release、摘要和文件来源。

## 3. 添加第一个仓库

打开应用后选择“仓库 → 添加仓库”。

### 本地仓库

点击“选择本地仓库”，用 macOS 系统选择器选中仓库顶层目录。页面只得到目录显示名和一次性
授权 ID，不会得到完整路径。授权提交后失效。

以下目录会被拒绝：

- home 根目录、卷根目录或应用数据/缓存目录；
- `.ssh`、`.aws`、`.codex`、`.kube` 等敏感配置目录；
- 不是当前用户拥有的目录；
- symlink、mount root 或与授权后身份不一致的目录。

私有 GitHub 仓库请先用你熟悉的 Git 工具克隆到本机，再通过选择器授权。应用不会弹窗索取
GitHub token。

### 公开远程仓库

填写：

```text
https://github.com/owner/repository.git
```

桌面 UI 当前只接受公开 `github.com` HTTPS 形式，不接受 SSH、userinfo、query、fragment 或
自定义端口。需要凭据或其他托管站时，先安全地克隆到本机。

在“采集选项”中填写：

- 分支、标签或提交，例如 `main` 或完整 commit SHA；
- “使用系统默认（推荐）”或“只用 Codex CLI”；
- 是否添加后立即采集。

## 4. 查看任务队列

采集不会阻塞页面。打开“任务”可查看：

- `queued`、`running`、`cancelling` 和终态；
- FIFO 队列位置；
- 当前阶段和进度；
- requested/effective provider；
- 错误、取消和重试入口。

页面每 5 秒刷新。当前版本固定单并发。失败任务的“重试”会创建新的审计记录，不会改写旧任务；
Codex 已经提交执行后的超时或未知结果不会自动重放。

## 5. 审核并发布

采集成功只会生成待审提案。打开“审核”：

1. 选择页面；
2. 阅读 Markdown；
3. 核对 source path 和行号；
4. 选择“批准发布”或“拒绝”；
5. 必要时运行 Wiki 校验。

同一知识版本的全部提案都批准后才会激活。一个提案被拒绝或版本只完成一部分时，该版本不会
通过默认查询或 MCP 冒充正式知识。人工批准不是装饰步骤：引用校验能证明行范围真实存在，但
不能证明模型结论在语义上一定正确。

## 6. 查询已发布知识

打开“查询”，选择知识库并输入自然语言问题，例如：

```text
如何初始化客户端并配置重试？
```

结果会显示检索引擎、页面、摘要和源码引用。使用 `Command + Enter` 可提交。未批准的提案
不会出现在查询中。

Embedding 未就绪时不会使用旧向量；指定 library 且 desktop QMD broker 健康时使用
`qmd-bm25`，broker/revision 失败或全局查询使用 Python `lexical`。这不是错误。完成下一步后
才会启用与当前 corpus revision 和模型 profile 一致的 `qmd-hybrid`。

## 7. 选择 embedding 并重建

打开“设置 → Embedding 模型”：

1. 保持默认的 EmbeddingGemma 300M Q8，或选择 Qwen3-Embedding 0.6B Q8；
2. 高级用户可填写经过格式检查的 `hf:org/repo/file.gguf`；
3. 点击“检查模型标识”；
4. 点击“保存并重建全部”。

重建进入同一个持久队列。首次重建可能需要下载模型并持续较长时间。模型准备失败、应用离线、
任务取消或 corpus 在重建期间变化时，向量状态不会被标成 ready，查询继续安全降级。

“仅保存”只更新期望设置，不会让旧索引自动变成新模型。“从此库发起”会先确认该库已有发布
版本，但因为向量空间是全局 profile，实际任务仍校验并重建全部已发布语料。

Embedding rebuild 不调用 Codex/Cursor；只有重新采集仓库才消耗生成额度。

## 8. 一键连接 Codex MCP

先确保应用已位于 `/Applications` 且 Codex 已登录。打开“设置 → 在 Codex 中使用本地文档”：

1. 点击“刷新状态”；
2. 点击“连接 Codex”；
3. 重启 Codex 或新建 CLI 会话。

应用只登记随包提供的固定 Node 和只读 MCP companion，不使用 `npx` 或系统 Node。连接后提供：

- `resolve-library-id(libraryName, query)`
- `query-docs(libraryId, query)`

MCP 不提供采集、审核、发布、模型、更新、路径或原始文件能力。Local Context Forge 应用必须
保持运行；关闭应用后 companion 会明确报告不可用。

为便于审计，应用执行的 `add` 形状包含由应用生成的 ownership marker：

```bash
codex mcp add local-context-forge \
  --env LCF_MCP_OWNER_ID=<由应用生成的所有权标记> \
  -- \
  "/Applications/Local Context Forge.app/Contents/Resources/qmd/node/bin/node" \
  "/Applications/Local Context Forge.app/Contents/Resources/companion/index.mjs"
```

这不是手工安装命令。不要复制、复用或伪造 marker；它不是 secret 或 MCP capability，但只有
marker、当前 `CODEX_HOME` 对应的私有 ownership ledger 和精确 command/arg 同时匹配时，应用
才会把 target 视为自有。Codex CLI 没有 CAS/共享配置锁，所以同一 UID 下的并发配置写入仍可能
在最终检查后发生；出现 conflict 时先人工核对，不要反复点击。

Cursor MCP 当前不自动配置；手工添加 bundled stdio companion 也不由 App 管理。不要把 Codex
marker 复制到 Cursor。具体路径和边界见
[桌面版完整指南](16-electron-desktop-guide.md)。

## 9. 日常操作速查

| 想做什么 | 位置 |
| --- | --- |
| 添加/重新采集仓库 | 仓库 |
| 查看队列、取消、重试 | 任务 |
| 检查和批准页面 | 审核 |
| 查询已发布 Wiki | 查询 |
| 允许 Cursor fallback | 设置 → 知识生成工具 |
| 更换 embedding | 设置 → Embedding 模型 |
| 重建所有索引 | 设置 → 保存并重建全部 |
| 连接 Codex MCP | 设置 → 在 Codex 中使用本地文档 |
| 检查并打开已验证更新 DMG | 设置 → 应用更新 |

## 10. 遇到问题

- 显示 Codex 未登录：在终端运行 `codex login`，再刷新设置页；
- 找不到本地仓库：选仓库顶层，避免 home/卷根、symlink 和敏感目录；
- 任务长期排队：当前固定单 worker，打开任务详情检查前一个任务；
- 任务 `uncertain` 或超时：不要盲目重放，核对旧任务后显式创建新任务；
- 查询只有 lexical：检查 embedding job、模型状态和 corpus revision；
- MCP 提示 app 未运行：先启动 Local Context Forge；
- MCP 提示移动应用：把 App 拖到 `/Applications` 后重新打开；
- 更新入口不可用：当前构建可能不是经过 provision 的正式 Release；可由用户显式点击固定的
  canonical Release 页面按钮，但这不是已验证 DMG 或自动更新。

恢复、缓存重置、源码模式与 Release 管理见
[Electron 桌面版完整指南](16-electron-desktop-guide.md)。

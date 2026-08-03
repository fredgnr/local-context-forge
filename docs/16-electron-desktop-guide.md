# Electron 桌面版完整指南

> **Release stop：** 仓库仍含会被 release tag 触发的 legacy container workflow。首个受支持
> Electron-only Release 必须先在 W13 engineering checkpoint 通过 cutover/absence，再对 W15
> formal tag 证明受限 diff，并在 W16 将要公开的 exact Draft digest 上重新运行完整
> `VAL-ELECTRON-CUTOVER-001`、`VAL-LEGACY-ABSENCE-001` 与
> `VAL-RELEASE-CONTINUITY-001`。在此之前不要创建 tag、Draft 或公开 Release；后文任何 GHCR
> 检查都只是待删除风险 inventory。

本文面向两类读者：

- 不写代码、只希望在 M4 Pro MacBook 上安装并使用 Local Context Forge 的个人用户；
- 需要运行源码、审查发行资产、配置受保护 Environment 或排查边界问题的高级用户。

## 1. 先看当前可用性

当前权威完成度见[项目状态快照](development/status.md)，进程和数据边界见
[系统设计](17-system-design.md)。主要桌面 source foundation 已实现：

- Electron Main、sandboxed renderer 与类型化 preload；
- 内置 Python sidecar 和 Node/QMD worker 的打包、审计与监督逻辑；
- 仓库提交、审核、任务队列、查询、模型设置和重建 UI；
- Codex 默认与需要显式同意的 Cursor fallback；
- 本地仓库系统选择器与一次性授权；
- Context7 兼容 MCP companion 和 Codex onboarding；
- Ed25519 更新元数据、DMG 摘要检查和 GitHub Release workflow。

这些实现仍不能替代物理证据：

| 能力/门禁 | 当前状态 | 可以得出的结论 |
| --- | --- | --- |
| 源码单元、合同、类型和构建检查 | 已有自动化证据 | 源码边界可继续审查 |
| 经过审查的正式公开 DMG | 尚未产出 | 目前没有推荐给普通用户的安装包 |
| 无开发环境的干净 macOS 用户安装 | `not-run` | 不能声称目标机零依赖已经实机通过 |
| 打包 App 的真实 Codex 采集 | `not-run` | 不能用 mock/provider 单测替代 |
| 物理 M4 模型下载、embedding、hybrid | `not-run` | lexical fallback 可用不代表模型门禁通过 |
| 真实 `N-1 → N` 物理更新与故障注入 | `not-run` | 自动应用更新尚未交付 |
| legacy Docker 数据迁移 | `superseded` / 不提供 | 不能直接覆盖或共用数据目录 |

因此，本文所称“推荐桌面安装”始终带一个前提：GitHub Releases 已出现由维护者审查的完整正式
资产，并且 release notes 没有说明阻断门禁。当前分支适合开发和审查；legacy Docker/Web
已弃用，不再作为当前稳定 fallback。

## 2. 桌面版包含什么

```text
Local Context Forge.app
├── Electron Main
│   ├── 窗口、权限、CSP 与系统目录选择器
│   ├── Python/QMD/provider 生命周期
│   ├── 私有 UDS、token 与 capability
│   ├── MCP 本地桥
│   └── 更新元数据与 DMG 校验
├── React renderer
├── Python 3.13.14 onedir sidecar
├── Node 22.23.2 + QMD 2.5.3 worker
└── stdio MCP companion
```

目标 Mac 不需要另外安装 Docker、Homebrew、Python、Node、Git、QMD 或 ctags。Codex CLI
例外：它是用户选择的生成服务入口，由用户单独安装和登录；应用不携带 Codex，也不读取它的
token。

Renderer 只负责显示和表达用户意图。它不能：

- 任意读取文件或获得本地仓库完整路径；
- 执行 shell 或选择 executable/argv；
- 读取 sidecar、QMD、provider 或 MCP token/socket；
- 直接控制 updater；
- 调用 `/api/admin/*` 或未列入 allowlist 的 API。

## 3. 普通用户安装

### 3.1 系统要求

- Apple Silicon Mac，目标架构为 arm64；
- 建议 macOS 15 或维护者在 Release notes 中明确支持的版本；
- M4 Pro 24 GB 是推荐基线；
- 建议至少保留 10 GiB 空闲空间，大仓库和多个模型需要更多；
- 当前 macOS 用户能够把 App 安装到系统 `/Applications`；
- 需要新生成 Wiki 时，安装并登录受支持的 Codex CLI。

当前不提供 Intel、Windows 或 Linux 桌面发行版。

### 3.2 识别正式 Release

正式 Release 的默认人工安装资产是：

```text
local-context-forge-<version>-arm64.dmg
```

同一 Release 还应包含：

```text
local-context-forge-<version>-arm64.zip
local-context-forge-<version>-arm64.zip.blockmap
<channel>-mac.yml
update-metadata-ed25519-public.pem
python-sidecar-build-manifest.json
python-sidecar-sbom.spdx.json
qmd-runtime-build-manifest.json
qmd-runtime-sbom.spdx.json
mcp-companion-build-manifest.json
renderer-build-manifest.json
SHA256SUMS
release-manifest.json
update-manifest.json
update-manifest.json.sig
```

DMG 供用户安装。ZIP、blockmap 和对应的 `<channel>-mac.yml` 是更新客户端辅助资产，不应手工运行。
文件名以实际 Release manifest 为准；资产缺失、重复或出现额外未知文件时停止安装并等待维护者
解释。

不要安装：

- PR artifact；
- `*-UNOFFICIAL.dmg`；
- 聊天、网盘或第三方镜像单独发来的 DMG；
- 没有同组 manifest/checksum 的文件；
- 无法确认来自 `fredgnr/local-context-forge` canonical Release 的文件。

### 3.3 核对 DMG 的 SHA-256

把 DMG 和 `SHA256SUMS` 放在同一下载目录。先列出实际文件名：

```bash
cd "$HOME/Downloads"
ls -1 local-context-forge-*-arm64.dmg SHA256SUMS
```

再把下面的 `DMG` 值替换成上一步显示的精确文件名：

```bash
cd "$HOME/Downloads"
DMG="local-context-forge-0.3.0-arm64.dmg"
EXPECTED="$(
  awk -v name="$DMG" '$2 == name {print $1}' SHA256SUMS
)"
ACTUAL="$(
  shasum -a 256 "$DMG" | awk '{print $1}'
)"
test -n "$EXPECTED" &&
  test "$EXPECTED" = "$ACTUAL" &&
  printf 'SHA-256 OK: %s\n' "$DMG"
```

如果没有打印 `SHA-256 OK`，不要打开 DMG。`SHA256SUMS` 本身必须来自同一 canonical
Release；摘要只能发现 bytes 不一致，不能单独证明发布者身份。App 内更新路径还会使用内置
Ed25519 公钥验证 canonical update manifest。

### 3.4 安装到 Applications

1. 双击 DMG；
2. 把 `Local Context Forge.app` 拖入 Applications；
3. 等复制完成后推出 DMG；
4. 从 Applications 启动 App。

不要长期从 DMG、Downloads 或临时目录运行。MCP onboarding 会要求 App 位于 Applications，
否则拒绝写入持久 Codex 配置；应用不会自行移动。

### 3.5 自签名与 Gatekeeper

正式发行策略设计为使用固定项目自签名证书：

- 不是 Apple Developer ID；
- 不进行 notarization 或 stapling；
- 不启用 hardened runtime；
- 不表示 Apple 已经审查或信任该应用。

macOS 可能显示“无法验证开发者”或阻止第一次打开。使用系统提供的、可撤销的操作：

1. 在 Finder 的 Applications 中按住 Control 点击 App；
2. 选择“打开”；
3. 若仍被拦截，前往“系统设置 → 隐私与安全性”；
4. 在刚被拦截的应用提示旁选择“仍要打开”；
5. 核对名称后再次确认。

禁止把以下命令当作安装步骤：

```text
sudo spctl --master-disable
xattr -dr com.apple.quarantine ...
sudo open ...
```

项目不会要求关闭 Gatekeeper、删除 quarantine 或用 root 身份运行。若系统没有提供针对单个
App 的继续选项，应停止并重新核对来源、摘要和 Release notes。

## 4. 准备 Codex CLI

### 4.1 登录

在终端运行：

```bash
codex --version
codex login status
```

如果尚未登录：

```bash
codex login
```

随后回到 Local Context Forge 的“设置”，刷新状态。应用支持可验证的官方 npm、
official install.sh、Homebrew cask，以及 `/usr/local/bin/codex` 中符合签名/arm64 规则的
发行版。无法证明来源、owner/mode 不安全或被修改的 executable 会显示
`unsupported installation`，不会退回到任意 PATH 命令。

### 4.2 应用如何调用 Codex

生成任务由 Electron Main 固定参数调用 Codex：

- `exec --ephemeral`
- 忽略用户 config 和仓库 rules；
- 跳过 Git repository discovery；
- sandbox 为 read-only；
- prompt 从 stdin 提供；
- output schema 和最终 JSON 写入 Main 创建的私有、受控文件；
- 不允许 renderer 或仓库选择命令、参数、工作目录或 prompt 模板。

Codex 获得的是经过预算限制的 facts/evidence，不获得正式 Wiki 的发布能力。它仍作为当前
macOS 用户运行，不是用户级文件保密沙箱；高敏感源码应使用专用 macOS 账号或独立 VM。

应用使用当前 CLI 登录对应的 Codex/ChatGPT 用量，不管理 API key，也不把 auth cache 复制到
App 或 Release。额度、可用模型和服务条款以 Codex CLI 当前官方行为为准。

## 5. 添加仓库

### 5.1 本地仓库

在“仓库”点击“添加仓库 → 选择本地仓库”。macOS 选择器只允许一个目录。Main 检查：

- canonical absolute path；
- 当前用户 ownership；
- 不是 symlink；
- 不是 home 根、`/Volumes` 根或某个 mount root；
- 不位于 LCF Application Support/cache；
- 不位于 `.aws`、`.azure`、`.codex`、`.gcp`、`.kube`、`.secrets`、`.ssh` 或
  `secrets`；
- 自定义 `CODEX_HOME` 也在排除列表中；
- 授权发出后，目录的 device/inode/owner 没有在提交前变化。

Renderer 只收到一次性 grant ID 和显示名。创建 library 时 grant 被消费，过期、重复、替换
选择或 App 退出后不能再用。

如果目录是 Git 仓库，应选择仓库顶层。linked worktree、危险 `.git` pointer、越界 object
store、submodule、Git LFS pointer 和 portable path collision 会 fail closed。需要分析
monorepo 子树时，先把所需文件导出为一个不带父 `.git` 的普通目录，再选择该目录。

### 5.2 公开 GitHub 仓库

桌面 UI 接受：

```text
https://github.com/owner/repository.git
```

也接受省略 `.git` 的形式。它拒绝：

- `git@github.com:...` 或 `ssh://...`；
- URL 中的用户名、密码、token；
- query、fragment 或非默认端口；
- 非 `github.com` 主机；
- 需要交互认证的私有仓库。

私有仓库请先用受信任工具克隆到本机，再通过系统选择器授权。不要把 token 写进 URL 或版本
字段。

### 5.3 采集选项

第一次添加时可选择立即采集。重新采集必须显式填写：

- ref：分支、标签或 commit；
- 新 version label；
- 系统默认或 Codex。

已经物化的 source/version 不原地覆盖。移动 branch/tag 指向新提交时也会产生新 source SHA
和版本，旧版本保留用于审计。

## 6. 任务队列

“任务”页每 5 秒刷新，可筛选全部、处理中和失败任务。详情包含：

- 完整 job ID；
- library；
- stage、phase、progress；
- FIFO queue position；
- requested/effective provider 和 fallback reason；
- attempt 次数；
- 创建、开始、完成和更新时间；
- 有界错误信息。

采集和 embedding rebuild 共用一个 SQLite 持久 FIFO，当前最大并发固定为 1。这样能保证
24 GB 机器上的资源上限、provider 顺序和审核记录可解释。

### 6.1 取消

`queued` 或支持取消的运行任务可点击“取消”。运行中的 provider 是否已实际消费额度取决于
commit point；取消不是额度退款保证。应用重启后，已中断的 `running/cancelling` 会
fail closed，不会假装继续原执行。

### 6.2 重试

失败或取消任务可点击“重试”。重试会创建带 `retry_of/attempt` 的新任务，旧记录不改写。
如果任务在 provider 提交后出现超时、崩溃或结果未知，系统不会自动 replay；先审查旧记录，再
决定是否承担一次新调用。

## 7. Codex 默认与 Cursor 后备

桌面“设置 → 知识生成工具”默认只有：

```text
Codex only
```

勾选“Codex 预检不可用时，允许改用 Cursor CLI”并保存后，策略才变为：

```text
Codex then Cursor
```

fallback 必须同时满足：

1. 用户同意记录仍是当前版本；
2. Codex 在任务开始前明确是 `not installed` 或 `not authenticated`；
3. Cursor 已安装并通过自己的登录 preflight；
4. provider execution 尚未 commit。

以下情况**不会**触发 Cursor：

- Codex installation unsupported；
- Codex 临时 unavailable；
- Codex 已 spawn 后超时；
- Codex 非零退出；
- Codex 输出坏 JSON 或不符合 schema；
- Electron/Main 在 commit 后崩溃。

Cursor 通过 stdin 获得同类有界 evidence，输出格式固定为 JSON，且应用绝不加 `--force`。
Cursor 仍是 Agent 能力较强的 CLI，使用独立 Cursor 账号和额度；不适合高安全仓库的自动后备。

## 8. 人工审核

“审核”只展示当前 library 的待审提案。每个提案包含：

- 标题和目标 Wiki path；
- Markdown 预览；
- source file 和 line range；
- 当前状态。

建议顺序：

1. 先核对 API 名称、签名和版本；
2. 再核对每个 source ref 是否真的支持页面声明；
3. 对涉及安全、兼容性或副作用的页面额外检查源码；
4. 运行 Wiki 校验；
5. 批准正确页面，拒绝错误页面；
6. 错误内容通过新采集和新版本修订，不手工修改已发布物化层。

批准单页只写入暂存物化。只有同一版本全部页面批准且没有 rejected，系统才激活完整版本并更新
corpus revision。中途失败或 rejected 版本不会被默认查询/MCP 使用。

## 9. 查询

“查询”只搜索已发布知识。结果包括：

- engine/mode；
- 命中页面；
- score；
- snippet/content；
- source refs。

检索优先级：

1. 当前 embedding state 的 corpus revision 和 model profile 完全匹配时，QMD 使用显式
   lexical + vector typed queries，且不加载额外 reranker/expansion 模型；
2. 模型未 ready、stale、缺失、损坏、worker 异常或 revision/profile 不一致时，回退到
   deterministic lexical；
3. 不会返回旧向量并把它标成当前结果。

Lexical fallback 是正常可用状态。不要为了消除提示而反复提交重建；先查看最近 job 的明确
错误。

## 10. Embedding 模型与重建

### 10.1 默认模型

M4 Pro 24 GB 建议先用：

```text
hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf
```

备选：

```text
hf:Qwen/Qwen3-Embedding-0.6B-GGUF/Qwen3-Embedding-0.6B-Q8_0.gguf
```

UI 分别显示为 EmbeddingGemma 300M Q8 和 Qwen3-Embedding 0.6B Q8。先用一组真实 API
问题比较命中质量，再决定是否切换；不要仅按参数量选择。

### 10.2 自定义模型

高级输入必须是：

```text
hf:org/repo/file.gguf
```

并属于 EmbeddingGemma 或 Qwen3-Embedding family。HTTP endpoint、本地路径、未知 family、
多余字段和 kind/model 不一致会被拒绝。

当前 custom model 没有逐个固定发布者签名/digest。QMD/native 层会做临时文件、大小和 GGUF
格式检查，但这不等价于完整供应链证明。高安全环境只使用经单独审查和固定的模型。

### 10.3 保存与重建

- “仅保存”：更新 desired model；不会改造已有向量；
- “保存并重建全部”：保存设置并创建 global embedding rebuild job；
- “从此库发起”：确认所选 library 有发布版本，再创建同一个全局 rebuild。

向量空间是全局 profile，因此不存在“只给一个库换模型、同时让其他库沿用旧向量”的安全
模式。每次发布新 corpus 或切换模型都会让 embedding state stale。

worker 先 reconcile 完整已发布 corpus，再 update lexical 文档，然后强制 embed。只有零
embedding error、revision/profile 仍一致且任务未取消时才原子标记 ready。重建期间发布新
版本、再次切模型、取消或崩溃都会让旧 claim 失效。

### 10.4 下载与缓存

模型不在 DMG 内。第一次显式重建可能触发下载，缓存位于：

```text
~/Library/Caches/Local Context Forge/
```

普通启动、publish/reconcile 和 lexical 查询不能触发模型下载。断网或 cache 缺失时
embedding 失败，但已发布 Wiki 和 lexical 查询仍保留。

模型物理下载、native embedding、cache corruption/resume 和 atomic index swap 的完整门禁
仍未通过，不能把 Linux fake store 或 source test 当成实机证明。

## 11. MCP：在 Codex 中使用本地文档

### 11.1 一键连接

前提：

- 使用经过打包的 App，不是 source/debug；
- App 已移动到 Applications；
- App 内 companion 与 bundled Node 通过校验；
- Codex CLI 安装受支持且已登录；
- `local-context-forge` 没有指向未知自定义 server。

打开“设置 → 在 Codex 中使用本地文档”，点击“连接 Codex”。Main 实际执行等价于：

```bash
codex mcp add local-context-forge \
  --env LCF_MCP_OWNER_ID=<由应用生成的所有权标记> \
  -- \
  "/Applications/Local Context Forge.app/Contents/Resources/qmd/node/bin/node" \
  "/Applications/Local Context Forge.app/Contents/Resources/companion/index.mjs"
```

上例只用于说明固定 argv 形状；不要手工执行，也不要复制、复用或伪造 marker。marker 由 App
使用 256-bit 随机数生成，格式为 `lcf-mcp-v1-<64 位小写十六进制>`。它是 ownership metadata，
不是 secret、认证 token 或 MCP capability；不进入 Renderer/Main bridge，companion 启动后会
先从自己的环境删除它。

Main 以显式 `CODEX_HOME`（未设置时为 `$HOME/.codex`）的规范化 absolute path 为输入，使用
domain-separated SHA-256 形成 scope，并在 Application Support 数据根保存：

```text
mcp-target-ownership-<64 位 scope hash>.json
```

数据根必须是当前 effective UID 拥有、canonical non-symlink 的 exact mode-0700 目录；ledger
必须是同 UID、single-link、canonical non-symlink 的 exact mode-0600 regular file，检查包含
special bits。ledger 保存 marker 和 exact bundled command/arg；App move/reconnect 期间最多
同时保存 old/new 两个 target，完成后收敛到当前 target。

Codex config 的 `env` 必须只包含 `LCF_MCP_OWNER_ID`，且 marker、对应 scope ledger 与 exact
command/arg 三者全部匹配，App 才视为 owned。missing/damaged ledger、旧版无 scope ledger、
marker mismatch、extra env、路径或参数不一致、仅路径外观相似全部 fail closed。

自动 mutation 还要求 packaged App 位于 `/Applications`。从
`Local Context Forge.app/Contents/Resources` 到 Node/companion 的 bundle、`Contents`、
`Resources`、每个中间目录和两个文件都必须 canonical non-symlink，由 root 或当前 effective
UID 拥有，并拒绝 group/world write 与 setuid/setgid/sticky。source/debug、其他位置或 invalid
bundle 不能 add/remove。

应用执行后会再次读取 `codex mcp list --json` 并核对 ownership 与 command/args。成功后重启
Codex 或新建 CLI 会话。若 App 后来移动，设置页会提示“重新连接 Codex”。

这些复核会缩小错误覆盖窗口，但 Codex CLI 没有 CAS 或与 App 共享的配置锁。最终 list 与
`mcp add/remove` 之间仍有小竞态；并发 writer 仍可能改写同名 target。恶意 same-UID 进程也能
读取或修改 Codex config/ledger，并利用 bundle/state check-use 窗口。因此该机制面向单用户、
同 UID 非对抗环境，不是 OS sandbox，也不能保证第三方配置在所有竞态下不受影响。

### 11.2 工具

companion 只实现：

```text
resolve-library-id(libraryName, query)
query-docs(libraryId, query)
```

它不能采集、取消、retry、review、publish、reject、修改设置、触发模型/更新、读取路径或返回
原始文件。App 必须保持运行；companion 经 Main 私有只读桥访问当前已发布 corpus。

如果 Codex 中存在同名但 marker/ledger/command/arg 不能共同证明 ownership 的 server，UI 会
报告 name conflict 并在该次操作中 fail closed。先在 Codex 中确认那条记录的来源，再自行
重命名或删除；不要把这理解成对并发 writer 的 CAS 保证。

清除由本 App 创建的连接，可在设置中点击“清除本应用的连接”。它调用：

```bash
codex mcp remove local-context-forge
```

### 11.3 Cursor MCP

当前 App 不自动配置 Cursor，也不会为 MCP onboarding 静默运行 Cursor。需要时，在 Cursor
当前版本的 MCP 设置中手工创建 stdio server：

- command：
  `/Applications/Local Context Forge.app/Contents/Resources/qmd/node/bin/node`
- args：
  `/Applications/Local Context Forge.app/Contents/Resources/companion/index.mjs`

不同 Cursor 版本的配置文件结构可能变化，所以本项目不提供可能过期的整段 JSON。配置完成后
保持 App 运行，并确认客户端只看到上述两个工具。Cursor 条目是用户手工配置，不由 App 追踪或
清除；不要把 Codex 的 `LCF_MCP_OWNER_ID` marker 复制进去。

### 11.4 当前 MCP 限制

production 持久配对、Keychain 和 client code-identity 绑定尚未完成。当前设计面向同一个
macOS 用户的本地使用，不是多用户共享服务。MCP 查询结果可能被消费端继续发送到其模型服务；
“LCF 数据在本机”不代表 Codex/Cursor 后续处理完全离线。

同一 UID 下的恶意进程、Codex 配置并发写入和上述 check-use 窗口不在本轮防护承诺内。真实
packaged `/Applications` App、官方签名 Codex、Codex 重启、两工具调用、move/reconnect/clear
物理门禁仍为 `not-run`。

## 12. 应用更新

### 12.1 已实现的安全路径

正式、已 provision 的 packaged App 在设置页可以：

1. 只查询 canonical `fredgnr/local-context-forge` GitHub Release；
2. 选择与当前 stable/prerelease channel 相符且版本更高的候选；
3. 下载 `update-manifest.json` 和 detached signature；
4. 使用 App 内固定 Ed25519 public key/lock 验证 canonical manifest；
5. 核对 tag、version、source commit、arm64、文件名、大小和 SHA-256；
6. 把 DMG 写入私有 `.partial`，验证后同卷 rename；
7. 打开已验证 DMG；
8. 由用户手工拖拽替换 App。

下载取消或 App 退出会终止请求并清理/隔离 partial。校验失败不会打开文件。若更新路径不可用，
只有用户显式点击后，Main 才可打开固定的 canonical Release 页面。该无参数操作不接受 Renderer
提供的 URL，Renderer 也读不到 URL；打开页面失败不会覆盖 signed updater 已有的 candidate/
error 状态。source/unpackaged、unprovisioned、signature/schema/asset/cache/digest 或网络
错误不会自动打开页面，也不会改为下载未验证资产。

### 12.2 尚未交付

应用不会：

- 静默运行 ZIP；
- 自动替换 `/Applications` 中的 App；
- 自动重启；
- 删除当前 App 或用户数据；
- 绕过 Gatekeeper；
- 把一次 source/CI 测试当作升级证明。

`VAL-UPDATE-001` 要求在物理 Apple Silicon Mac 上用真实上一版本 `N-1` 创建真实数据，跨到
真实单调下一版本 `N`，并在下载、校验、替换或重启故障注入后验证 DMG fallback。早期 ADR
中的版本号只是示例。该门禁仍是 `not-run`，所以文档和 UI
只把 signed 路径称为“下载并打开已验证 DMG”，不称“自动更新”。手工 Release 页面只是人工
出口，既不证明已有 DMG/Release，也不证明页面资产经过 App 验证。

## 13. 数据、备份与恢复

### 13.1 当前路径

持久数据：

```text
~/Library/Application Support/Local Context Forge/
```

可重建缓存：

```text
~/Library/Caches/Local Context Forge/
```

持久目录包含 `metadata.sqlite3`、sources、facts、proposals、jobs、wiki、provider attempts、
QMD 状态、MCP rendezvous，以及按 `CODEX_HOME` scope 隔离的 MCP ownership ledger。ledger
含 marker 和 bundled command/arg 路径，不进入 Renderer；marker 不是 secret/capability，但
同一 UID 进程可读取它。该目录可能包含完整私有源码，应放在 FileVault 或等效加密存储上。

Codex/Cursor auth、GitHub credentials、自签名 private key 和 update private key 不在这些
目录，也不应加入备份。

### 13.2 手工创建可恢复副本

当前 desktop backup UI 和物理恢复门禁尚未完成。更新、故障操作或试验性版本前：

1. 在菜单中退出 Local Context Forge；
2. 在“活动监视器”确认没有 LCF 子进程；
3. 在 Finder 中前往 `~/Library/Application Support/`；
4. 将 `Local Context Forge` 完整复制到加密外置盘或受控备份目录；
5. 记录 App 版本、备份时间和目标目录；
6. 不把 QMD cache 当作唯一备份。

熟悉终端的用户可在 App 完全退出后运行：

```bash
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_ROOT="$HOME/Documents/LCF Backups"
SOURCE="$HOME/Library/Application Support/Local Context Forge"
DESTINATION="$BACKUP_ROOT/Local Context Forge-$STAMP"
mkdir -p "$BACKUP_ROOT"
ditto "$SOURCE" "$DESTINATION"
printf 'Backup copied to: %s\n' "$DESTINATION"
```

这只是退出后的目录副本，不是已验证的一键 backup 产品能力。完成后应抽样核对目标目录，并
保护其中的私有源码。

### 13.3 可回退恢复

不要直接覆盖当前数据。先保留 quarantine：

1. 退出 App；
2. 复制当前 Application Support 目录并带时间戳改名；
3. 把可信完整备份复制回精确的 `Local Context Forge` 路径；
4. 确认 owner 是当前用户、目录不是 symlink；
5. 启动 App；
6. 检查 library、任务、proposal、查询和 Wiki；
7. 如失败，再退出 App，把恢复目录移开并将 quarantine 改回原名。

终端示例要求你先把 `BACKUP_SOURCE` 改为真实、可信、完整的备份：

```bash
DATA_ROOT="$HOME/Library/Application Support"
ACTIVE="$DATA_ROOT/Local Context Forge"
BACKUP_SOURCE="$HOME/Documents/LCF Backups/Local Context Forge-YYYYMMDD-HHMMSS"
QUARANTINE="$DATA_ROOT/Local Context Forge.before-restore-$(date +%Y%m%d-%H%M%S)"
test -d "$BACKUP_SOURCE" &&
  test ! -L "$BACKUP_SOURCE" &&
  mv "$ACTIVE" "$QUARANTINE" &&
  ditto "$BACKUP_SOURCE" "$ACTIVE" &&
  printf 'Restored copy; previous data kept at: %s\n' "$QUARANTINE"
```

如果任何一步失败，不要删除 quarantine。该流程没有声明 schema migration、跨卷原子事务或
自动回滚已通过物理门禁；它只是避免立即销毁旧数据。

### 13.4 安全重置可重建缓存

当模型/cache 明确损坏，先退出 App，然后把 cache 改名而不是删除：

```bash
CACHE="$HOME/Library/Caches/Local Context Forge"
QUARANTINE="$HOME/Library/Caches/Local Context Forge.cache-disabled-$(date +%Y%m%d-%H%M%S)"
test -d "$CACHE" &&
  test ! -L "$CACHE" &&
  mv "$CACHE" "$QUARANTINE" &&
  printf 'Cache moved to: %s\n' "$QUARANTINE"
```

重开 App 后查询应先 lexical；需要 hybrid 时重新提交 embedding rebuild。确认新 cache 和数据
正常后，再按自己的保留策略处理旧 cache。不要把这一步用于 Application Support。

### 13.5 卸载

把 App 移到废纸篓不会自动删除 Application Support 或 cache，这是为了可恢复。需要彻底清理
时：

1. 先创建并验证备份；
2. 清除 Codex MCP 连接；
3. 退出 App；
4. 删除 App；
5. 只有明确不再需要源码/Wiki/任务后，才在 Finder 中单独处理 Application Support；
6. cache 可另行处理。

普通文件删除不是 SSD、Time Machine、云备份或外置盘上的 secure erase。

## 14. Legacy Docker 数据（不迁移、不自动删除）

`./install.sh`、Compose、host runner、HTTP MCP、`data/`、`imports/` 和 `backups/` 属于
legacy 路径。项目不再计划桌面迁移 UI：

- 不要把 legacy `data/` 复制到 Application Support 后直接启动；
- 不要让 legacy API 和 Electron sidecar 同时写同一目录；
- Docker named volume 不能由桌面 App 自动读取；
- 如需历史留档，自行保留 legacy checkout、备份和原数据；项目不提供导入工具或兼容承诺。

源码 retirement 不会自动停止旧容器或删除这些资产。若用户自行固定旧 commit/image 访问
历史副本，这是 unsupported 的独立操作；不得与 Electron 同时写同一数据目录。

## 15. 常见问题

### 系统显示“需要完成设置”

打开概览卡片，检查本地服务、仓库和队列。若 sidecar/QMD 配置异常，先确认使用正式 packaged
App；source/debug marker 不能当作完整 bundle。

### Codex 未找到或未登录

```bash
codex --version
codex login status
```

修复后回设置页刷新。不要把 `auth.json` 复制进 App 或仓库。

### Codex installation unsupported

使用受支持的官方安装方式。不要通过放宽 owner/mode、关闭签名检查或让 App执行任意 PATH
命令绕过。

### 本地目录选择后提交失败

一次性 grant 可能已过期或目录身份发生变化。重新打开系统选择器，选择仓库顶层。不要选择
home、卷根、network mount root、symlink 或凭据目录。

### 任务长期 queued

当前只有一个 worker。检查队列前方任务；必要时查看详情并有意识地取消。不要同时打开多个
App 副本或启动 legacy writer。

### 任务超时或 uncertain

provider 可能已经实际执行。旧任务不会自动重放。检查 provider attempt 和输出是否已物化，
再决定是否显式 retry。

### 审核通过但查询不到

确认同一 version 的所有 proposal 都已批准且没有 rejected；运行 Wiki lint。逐页批准只有在
整版完成后才激活。

### 查询显示 lexical

检查最近 embedding rebuild：

- 是否选择了正确模型；
- 是否已完成首次下载；
- corpus revision 是否在 publish 后变化；
- 是否切换模型但只点了“仅保存”；
- 是否离线、取消或 worker 崩溃。

Lexical 可继续使用，不要删除 Application Support。

### MCP 提示移动应用

把 App 拖到 `/Applications`，从那里重新打开，再点击连接。

### MCP name conflict

先运行：

```bash
codex mcp list
```

检查已有 `local-context-forge` 是谁创建的。无并发 writer 时，ownership proof 不匹配会报告
conflict，而不是主动覆盖；确认后由用户自行重命名/移除，再回 UI。Codex CLI 没有
CAS/shared lock，同 UID 并发 mutation 仍有最终 list 后的小竞态。

### MCP 提示 App 未运行

companion 不是独立数据库服务。先启动 Local Context Forge，并保持运行。

### 更新不可用

常见原因：

- source/debug 或 unofficial build；
- public update lock 仍是 `unprovisioned`；
- 当前架构/平台不受支持；
- metadata/signature/digest 校验失败；
- 网络不可用。

不要下载旁路文件冒充更新。使用设置中的 canonical Release 按钮，并核对 Release 状态。
按钮只能由用户显式触发，且只是打开固定页面；它不改变 signed updater 状态，也不代表已有、
已签名或已验证的 DMG。

## 16. 高级用户：源码运行

源码模式用于开发 UI/API/IPC，不是“免审查安装”。需要 Git、uv/Python、Node/npm 和完整源码。

### 16.1 安装并验证依赖

```bash
make ci-python-install
npm --prefix web ci
npm --prefix desktop ci
```

运行源码门禁：

```bash
make ci-source
```

### 16.2 构建 renderer 并启动

```bash
npm --prefix web run build
make renderer-stage

LCF_RENDERER_DIR="$(pwd)/web/dist" \
LCF_SIDECAR_BIN="$(pwd)/backend/.venv/bin/lcf-service" \
npm --prefix desktop run start:source
```

Main 只接受绝对 `LCF_RENDERER_DIR` 和 `LCF_SIDECAR_BIN`；不会从 PATH 发现 sidecar。QMD staging
缺失时应 fail closed 并保留 lexical 路径。

源码模式限制：

- MCP onboarding 不写入持久 Codex 配置；
- 没有正式自签名身份；
- 不是 DMG；
- 不证明 bundled runtime；
- 不证明无系统 Python/Node/Git；
- 不证明 clean-user、真实 Codex、模型或更新门禁。

### 16.3 打包开发产物

本地 `desktop/electron-builder.yml` 设计为 ad-hoc、`*-UNOFFICIAL`，但当前命令仍走 formal
production trust audit：

```bash
npm --prefix desktop run dist:mac
```

该命令还要求你已经按构建文档准备并审计 Python/QMD/renderer/companion staging，并且仓库
已有经过 provision 的公共 update trust anchor；当前 `unprovisioned` marker 会让
`beforePack` fail closed。它不会自动变成正式 Release，也不能使用正式 secret。

因此当前没有可用的 W02 packaged smoke 或 W03 engineering test package 命令。ADR-0016 要求
后续实现独立 non-release mode：显著 `engineering-only`/`publishable=false`，不读取 production
secret/pin，不由 tag 触发、不上传、不创建 Draft/Release，updater unavailable/no-network；
不得通过削弱 formal `beforePack` 来实现。W02 只支撑 legacy slice feedback，W03 只能从
cleaned tree 构建并支撑工程物理验证。

## 17. 维护者：公开仓库与受保护 Environment

本节属于 W14–W16，必须等待 W13 final cutover/absence；不应用于 W02/W03 工程包。

### 17.1 必须满足的 GitHub 配置

canonical repository：

```text
fredgnr/local-context-forge
```

必须是 active public repository。创建两个 Environment：

```text
macos-signing
macos-release
```

`macos-signing` 配置：

1. 至少一个 required reviewer；
2. 启用 `prevent self review`；
3. 在 GitHub UI 禁止 administrator bypass；
4. deployment branches/tags 使用 custom policy；
5. 唯一允许的 tag pattern 是 `v*.*.*`；
6. Environment 内只有一个 release secret：
   `DESKTOP_RELEASE_CREDENTIAL_BUNDLE_BASE64`。

`macos-release` 配置：

1. 至少一个 required reviewer；
2. 启用 `prevent self review`；
3. 在 GitHub UI 禁止 administrator bypass；
4. deployment branches/tags 使用 custom policy；
5. 唯一允许的 branch 是 `main`；
6. Environment secret 集合必须为空。

仓库还必须开启：

1. active `protected-main` branch ruleset：只匹配 `refs/heads/main`，要求 PR、至少一个独立
   approval、push 后 dismiss stale reviews、last-push approval、resolve review threads，
   禁止 force push/delete，且没有 bypass actor；
2. active `release-tag-creation` tag ruleset：只匹配 `refs/tags/v*.*.*`，creation rule 只允许
   canonical owner actor 通过唯一 bypass 创建 tag；
3. active `immutable-release-tags` tag ruleset：相同 pattern 禁止 update/delete，无 bypass；
4. GitHub Immutable Releases。

普通 `.github/workflows/desktop-ci.yml` 不绑定 release Environment，权限保持只读。Release
build/sign job 只有 `contents: read`，只在 `macos-signing` 中读取唯一 secret；tag push 后的
独立 Draft job 在没有 Environment/private secret 的 Linux runner 上才获得 `contents: write`。
手动 promotion 必须以 `--ref main` 运行，在 zero-secret `macos-release` 中取得 reviewer 审批，
不依赖 build job，并且只有它可以把已验证 Draft 改为公开。

### 17.2 一次性生成并上传凭据

管理员机器要求：

- 当前 checkout 是 canonical public repository；
- `openssl` 可用；
- GitHub CLI `gh` 已以仓库管理员身份登录；
- 两个 Environment、三组 ruleset 和 Immutable Releases 已先配置完成；
- 已在 GitHub UI 确认两个 Environment 都禁止 admin bypass；
- private output 不在仓库内。

运行：

```bash
python3 tools/bootstrap_desktop_release_keys.py \
  --repo fredgnr/local-context-forge \
  --upload \
  --confirm-admin-bypass-disabled
```

脚本生成：

- 独立 Ed25519 update metadata key；
- identity 为 `Local Context Forge Self Signed` 的自签名 code-sign certificate；
- PKCS#12 password；
- 16-byte 随机 generation ID（编码为 32 个十六进制字符）；
- 一个 canonical base64 credential bundle。

它先通过 GitHub API 校验 canonical repository、两个 Environment 的 reviewer/self-review/
deployment policy、精确 secret membership、三组 active ruleset 和 Immutable Releases；然后
通过 `gh secret set ... --env macos-signing` 的 stdin 上传 bundle，不打印私钥。
`--confirm-admin-bypass-disabled` 是管理员已在 UI 复核该 API 难以可靠证明的开关。上传和公共
文件写入成功后，临时 private 目录被删除；`macos-release` 不配置 Environment/repository
release secret 或长期签名凭据，但 promotion job 仍使用 GitHub 自动签发的短期
`GITHUB_TOKEN`。

仓库工作区只应出现：

```text
desktop/resources/update/update-metadata-ed25519-public.pem
runtime/update-metadata-key.lock.json
runtime/macos-codesign-certificate.lock.json
```

三者共享相同 `credentialGenerationId`。审查 public key digest、certificate DER fingerprint、
identity 和 `status=provisioned`，然后只提交这些公共文件。不得提交：

- `.p12`
- private PEM
- certificate password
- credential bundle
- GitHub secret 导出
- 临时 keychain

如果 secret 已上传但公共文件写入失败，正式 workflow 会因 generation/digest 不匹配而 fail
closed。保留恢复目录，修复后按工具提示用 `--rotate` 完整重做，不手工拼接两代凭据。

### 17.3 轮换

明确轮换：

```bash
python3 tools/bootstrap_desktop_release_keys.py \
  --repo fredgnr/local-context-forge \
  --upload \
  --confirm-admin-bypass-disabled \
  --rotate
```

轮换会改变 App 内更新信任锚。必须在 tag 前审查、提交并让 release build 使用同一 generation。
旧 App 是否能信任新 key 需要独立过渡设计；不要把简单替换 public key 当作无缝轮换已经解决。

## 18. 维护者：创建正式 Release

### 18.1 Release 前

1. 确认版本文件同步：

   ```bash
   backend/.venv/bin/python tools/check_version_sync.py
   ```

2. 运行源码门禁：

   ```bash
   make ci-source
   ```

3. 确认 public update/certificate locks 已 provision；
4. 确认 `macos-signing` 的 reviewer/self-review/tag policy/唯一 secret，以及
   `macos-release` 的 reviewer/self-review/main-only、无配置 release secret/长期签名凭据，
   并确认 job 只依赖短期 `GITHUB_TOKEN`；
5. 在 UI 确认两 Environment 禁止 admin bypass，并确认 `protected-main`、
   `release-tag-creation`、`immutable-release-tags` active 且 GitHub Immutable Releases 开启；
6. 确认没有私钥、auth cache、模型、index、用户数据或 generated staging 入库；
7. 审查 release notes 对 self-signed、no notarization、no hardened runtime 和
   update gate 的披露。

### 18.2 触发

这是统一产品发行事件：同一个符合 `v*.*.*` 的 tag 会并行触发 desktop build/Draft 与 GHCR
container SemVer 发布。两条 workflow 非原子；GHCR 镜像可能在 desktop 等待审批或失败时已经
公开，desktop Draft 成功也不证明 container job 成功。创建 tag 前同时确认两类产物就绪，
创建后分别记录两个 workflow run 与 digest。Desktop workflow 还要求 tag 指向精确 release
commit。示例：

```bash
git tag -a v0.3.0 -m "Local Context Forge v0.3.0"
git push origin v0.3.0
```

使用仓库实际版本；不要照抄示例 tag。Environment reviewer 在 GitHub 界面检查 commit、tag、
workflow 和 public locks 后批准 build。

desktop workflow 的 tag 路径成功后只会得到 Draft，不会自动公开 desktop Release；这不撤销
或回滚可能已经公开的 GHCR SemVer image。先分别核对 container run/image digest 与 desktop
build/Draft run，再从 Draft 下载候选，在真实 M4 完成适用的安装、runtime、Codex、embedding
和更新测试，并记录：

```bash
shasum -a 256 "/path/to/release-assets/release-manifest.json"
```

只有物理结论允许公开时，才从受保护 `main` 启动 manual promotion：

```bash
gh workflow run desktop-release.yml \
  --repo fredgnr/local-context-forge \
  --ref main \
  -f release_tag=v0.3.0 \
  -f candidate_manifest_sha256="<64位小写SHA-256>" \
  -f confirm_publish=true
```

必须使用 `--ref main`、仓库实际 tag 和刚验证的 digest。`release_tag` 只决定读取哪个候选，
不会选择 workflow/verifier code；tag ref、其他 branch、无显式确认或 digest 不匹配都会
fail closed。`workflow_dispatch` 不提供“重新构建”模式。

### 18.3 Workflow 做什么

Build job：

1. 无 credentials checkout 精确 tag；
2. 固定 Node 22.23.2 和 Python 3.13.14；
3. 下载并双重校验固定 Python/Node archive 与 hash manifest；
4. 构建 Python onedir 和 QMD native runtime；
5. 测试并 stage renderer；
6. 测试 desktop，审计 companion/sidecar/QMD/renderer；
7. 只在这一步读取单一 Environment secret；
8. 创建临时 keychain，导入固定自签名 identity；
9. 校验 credential generation、public key 和 certificate fingerprint；
10. 签名/组装 DMG、ZIP、blockmap、update metadata；
11. 生成 canonical manifest、detached signature 和 SHA256SUMS；
12. 独立 verify asset set；
13. 上传一个 Actions artifact；
14. 清理 keychain 和临时 private files。

Draft job（同一次 tag push）：

1. 在没有 release private secret 的 Linux runner 下载上一 job 的 asset set；
2. 再次 verify；
3. 读取包含 Draft 的 authenticated GitHub Release 列表，严格选择 exact tag；
4. 没有同 tag Release 时创建 Draft；若前次创建响应丢失而已有唯一 Draft，只在它与本次
   同 tag 重建候选完整一致时恢复；
5. 再次读取远端列表，逐个比较 state、notes、asset 名称、大小、digest 和 canonical URL；
6. published、重复 Draft、缺失/额外 asset 或任何漂移都失败，绝不覆盖；
7. 到此停止，任何 tag push 路径都不执行公开。

Promotion job（独立手动运行，所有 tag 的 promotion 全局串行且不取消正在运行的任务）：

1. 校验 dispatch ref 是 fresh `main` head，输入 tag 只是 data；
2. 通过 `macos-release` 的第二次 reviewer 审批，但不读取任何 secret；
3. trusted `main` verifier fresh-fetch/peel tag、验证 main ancestry，并把 tag 放入独立
   detached worktree；workflow script 不从 tag 执行；
4. 严格选择唯一 Draft，拒绝任何已 published 预状态，固定 Release ID，再从 API 下载所有
   remote assets 到新空目录；
5. 用隔离 tag worktree 的 notes/policy 运行 `verify-assets`，并把
   `release-manifest.json` digest 与真机测试输入精确绑定；
6. 公开前再次 fresh-peel tag、refetch Release 和 fetch `origin/main`，要求 exact tag、Draft
   state、固定 Release ID 和完整资产集合均未漂移；`verifyPromotionOrder` 必须以这个
   `PATCH` 前 fresh `origin/main` comparison ref 计算 SemVer 顺序/`make_latest`，不能使用启动
   时的旧 HEAD，否则并行 tag promotion 可能让旧版本成为 latest；
7. 对该 Release ID 执行唯一一次 REST
   `PATCH {"draft":false,"make_latest":...}`，不上传/替换资产；
8. 公开后再次 fresh-peel tag，运行 `gh release verify`，并验证同一 ID 的
   `immutable=true`、published state、notes 和完整资产集合。任何失败都按发布安全事件处理，
   不重跑洗绿。

这里的 controls 不消除根信任：repository owner、可修改受保护 `main`/workflow 的
`contents` writer 和 repository settings 管理员仍可改变发布政策。GitHub Draft 也没有资产
CAS；在最终 verify 与固定 ID `PATCH` 之间发生的 mutation 只能由发布后的
`gh release verify`、`immutable=true` 和完整资产复核检测。Immutable Releases 保护公开后的
Release，不保护该 Draft 窗口。

### 18.4 Draft 测试与发布后人工检查

- Release 是 canonical repo 且 tag/commit 正确；
- 真机测试下载的 Draft 与输入的 candidate manifest digest 一致；
- DMG 名称、arm64、版本和 SHA256SUMS 一致；
- `release-manifest.json` 和 update manifest 资产集合一致；
- detached Ed25519 signature 可由提交的 public key验证；
- App 与所有 nested executable 的签名 identity/架构符合记录；
- SBOM、notices 和 license inventory 存在；
- release notes 明确 self-signed/no notarization/no hardened runtime；
- post-publish `gh release verify` 通过且 Release 为 `immutable=true`；
- 在干净 Apple Silicon 用户完成安装 smoke；
- 使用真实已登录 Codex 完成一次采集、审核、查询和 MCP；
- 在物理 M4 完成模型下载、embedding/hybrid；
- `VAL-UPDATE-001` 通过前继续保持“自动应用未交付”。

GitHub Actions 成功本身不能把最后四项标记为 `pass`。
真实 GitHub settings、受保护签名/promotion 和物理 Mac 证据均尚未运行；当前整体结论保持
**source merge GO / release NO-GO**。

## 19. 验收清单

普通用户首次验收：

- [ ] DMG 来自 canonical Release；
- [ ] 文件摘要匹配；
- [ ] App 在 Applications；
- [ ] 只使用系统可撤销方式处理首次打开；
- [ ] Codex CLI 已登录；
- [ ] 本地仓库通过系统选择器授权；
- [ ] 任务进入队列并显示 provider；
- [ ] 提案在批准前不能查询；
- [ ] 全部批准后查询带 source refs；
- [ ] embedding 重建失败时 lexical 仍可用；
- [ ] MCP 只有两个只读工具；
- [ ] App 关闭后 MCP 明确不可用；
- [ ] signed 更新路径只打开已验证 DMG；手工 fallback 只打开固定 canonical Release 页面；
- [ ] Application Support 已有退出后的完整备份。

维护者发行验收：

- [ ] `macos-signing` 有独立 reviewer、prevent self review、禁 admin bypass 和唯一 tag policy；
- [ ] `macos-release` 有独立 reviewer、prevent self review、禁 admin bypass、main-only，且
      不配置 Environment/repository release secret 或长期签名凭据；job 只使用短期
      `GITHUB_TOKEN`；
- [ ] 本 desktop release workflow 的 Environment 私有凭据只有 `macos-signing` 中的一个
      credential bundle secret；不据此推断组织其他用途的 secret；
- [ ] `protected-main`、owner-only `release-tag-creation` 和无 bypass
      `immutable-release-tags` 都 active；
- [ ] GitHub Immutable Releases 已开启；
- [ ] 三个公共 trust files 同 generation；
- [ ] PR/fork/source CI 无 secret；
- [ ] tag、source commit、version、architecture 一致；
- [ ] desktop tag 路径只创建 Draft，未出现自动公开 desktop Release 的路径；
- [ ] `.github/workflows/container-images.yml` 已删除，tag 不再触发 GHCR/container；
- [ ] `VAL-LEGACY-ABSENCE-001=pass`，且证据绑定最终 removal commit 与 candidate digest；
- [ ] promotion 以 `--ref main` 运行，trusted verifier、隔离 tag worktree、fresh peel 和固定
      Release ID 证据齐全；
- [ ] `verifyPromotionOrder` 的 comparison ref 是 `PATCH` 前 fresh-fetched `origin/main`，
      并行 tag promotion 不会把旧版本设为 latest；
- [ ] 真机候选 manifest digest 与 manual promotion 输入一致；
- [ ] Draft 和 Published remote assets 在公开前后逐个 digest 校验，published 预状态未被
      当作幂等成功；
- [ ] clean-user、real-Codex、physical-model 和 physical-update 分别记录；
- [ ] 所有未运行门禁仍明确为 `not-run`。

## 20. 相关文档

- [产品概览](00-overview.md)
- [硬件与部署](03-hardware-deployment.md)
- [快速开始](04-quickstart.md)
- [数据模型](05-data-model.md)
- [API 与 MCP](06-api-and-mcp.md)
- [Codex CLI](07-codex-cli.md)
- [安全与威胁模型](10-security.md)
- [模型选择](12-model-selection.md)
- [架构决策](adr/README.md)
- [开发状态与验证](development/README.md)

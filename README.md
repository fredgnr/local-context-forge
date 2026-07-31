# Local Context Forge

面向代码库的本地 Context7 替代方案：把源码持续编纂为**可审核、可追溯、可版本化的 API
Wiki**，再通过与 Context7 兼容的 MCP 工具交给 Codex 或其他 coding client。

它不是一次性向量索引：

```text
immutable source snapshot
        ↓
deterministic facts + source refs
        ↓
Codex-generated proposal
        ↓
schema / SHA / path / line gate
        ↓
human review
        ↓
Git-backed Wiki + SQLite materialization
        ↓
QMD hybrid or lexical retrieval
        ↓
resolve-library-id + query-docs
```

## 目标体验

在 M4 Pro 24 GB MacBook 上安装一个 Electron 应用，然后全程从 Web 风格桌面界面完成：

- 添加公开 GitHub 或经系统选择器授权的本地仓库；
- 提交采集任务，查看 FIFO 队列、阶段、进度、取消和重试；
- 审核 Markdown 与源码引用，逐页批准或拒绝；
- 查询已发布知识；
- 切换全局 embedding 模型并重建全部已发布语料；
- 一键把只读 MCP companion 连接到 Codex。

应用内置 Python sidecar、Node/QMD、renderer 和 companion。目标机不需要
Docker/Homebrew/Python/Node/Git/QMD/ctags。Wiki 生成默认使用本机已经登录的 Codex CLI；
Cursor 只能作为用户明确同意的 preflight fallback。

## 当前状态：桌面源码完成，发行门禁尚未完成

当前分支已经实现桌面进程边界、UI 工作流、provider 监督、本地 embedding、MCP onboarding
和 GitHub Release workflow，但还没有可以向非开发者推荐的公开 DMG：

| 项目 | 状态 |
| --- | --- |
| 源码测试、类型检查与构建 | 已有自动化证据 |
| 经过审查的公开正式 DMG | 尚未产出 |
| 干净 macOS 用户安装 | `not-run` |
| 打包应用中的真实 Codex 采集 | `not-run` |
| 物理 Apple Silicon 模型下载/重建 | `not-run` |
| 0.0.1 → 0.0.2 物理更新 | `not-run` |

因此，**Electron 只在经过审查的 Release 资产出现后成为推荐安装路径**。当前需要稳定运行时，
legacy Docker/Web 部署仍保留；`./install.sh` 安装的是 legacy 路径，不是 Electron。

完整安装、首次打开、MCP、恢复与发布说明：
[Electron 桌面版完整指南](docs/16-electron-desktop-guide.md)。

## M4 Pro 24 GB 默认选择

| 项目 | 推荐 |
| --- | --- |
| 生成工具 | 已登录 Codex CLI |
| Cursor | 默认关闭；仅 Codex 开始前未安装/未登录且用户已同意时使用 |
| Embedding | EmbeddingGemma 300M Q8 |
| 备选 | Qwen3-Embedding 0.6B Q8 |
| 队列 | 单 worker，最大并发固定为 1 |
| 降级 | 模型未 ready 或 revision 不一致时使用 lexical |

更换模型后必须“保存并重建全部”。Embedding rebuild 只处理已发布 Wiki，不调用
Codex/Cursor，也不消耗生成额度；重新采集仓库才会生成新提案。

Windows 32 GB + RTX 4060 可继续作为 legacy Docker/Ollama 的可选生成节点，但当前 Electron
客户端没有远程 Windows worker。详见
[硬件与部署](docs/03-hardware-deployment.md)。

## 桌面版第一次使用

正式 Release 可用后：

1. 下载 arm64 DMG、`SHA256SUMS`、release/update manifest 和 detached signature；
2. 核对摘要，把 App 拖到 `/Applications`；
3. 自签名应用若被拦截，使用 Finder“打开”或“系统设置 → 隐私与安全性 → 仍要打开”；
4. 在终端运行 `codex login`；
5. 打开 App，添加仓库并等待队列；
6. 在“审核”批准页面；
7. 在“设置”选择 embedding，保存并重建；
8. 点击“连接 Codex”，重启 Codex 或新建 CLI 会话。

自签名不是 Apple Developer ID，项目不 notarize，也不启用 hardened runtime。不要通过关闭
Gatekeeper、运行 `xattr -dr` 或使用 `sudo` 绕过系统保护。

## UI 工作流

### 仓库

桌面版接受：

- 公开 `https://github.com/<owner>/<repository>[.git]`；
- 由 macOS 系统选择器授权的本地目录。

私有仓库先用熟悉的 Git 工具 clone 到本机。应用不会索取 GitHub token。Renderer 只收到目录
显示名和一次性授权 ID，不收到完整路径；home/卷根、App 数据、缓存和常见凭据目录会被拒绝。

### 任务

采集和 embedding rebuild 进入同一持久 FIFO。任务显示 queue position、
requested/effective provider、阶段和进度。失败重试会创建新的审计记录；已提交 provider
执行的未知结果不会自动重放。

### 审核

模型输出先成为 proposal。每页展示 Markdown 和 source refs。只有同一版本全部批准后，该版本
才会成为默认查询语料；rejected/partial 版本不会被 MCP 当作正式知识。

### 查询

查询只读取已发布知识。Embedding state 与 corpus revision 完全一致时使用 hybrid；
stale、缺失、崩溃或模型失败时明确回退到 deterministic lexical。

### 设置

- Codex 是唯一默认 provider；
- Cursor fallback 需要显式勾选同意；
- curated embedding 预设可直接选择；
- custom model 只接受 EmbeddingGemma/Qwen3-Embedding 家族的
  `hf:org/repo/file.gguf`；
- “仅保存”不重建，“保存并重建全部”会创建队列任务；
- 更新面板只下载并打开通过签名和摘要校验的 DMG，不静默替换 App。

## MCP

桌面设置页可以登记 App 内置 stdio companion。它只提供：

- `resolve-library-id(libraryName, query)`
- `query-docs(libraryId, query)`

没有 ingest、review、publish、settings、update、path 或 raw-file 能力。App 必须运行。
Codex target 只有在应用生成的 `LCF_MCP_OWNER_ID`、按当前 `CODEX_HOME` 隔离的私有
ownership ledger，以及 bundle 内精确 command/arg 三者一致时才会被应用视为自有配置；
marker 不是 secret 或 MCP capability，companion 启动后会先把它从环境中删除。应用会在
`add/remove` 前后二次检查，但 Codex CLI 没有 CAS 或与应用共享的配置锁，因此最终
`list` 与写入之间仍有小竞态；同一 UID 的恶意进程也不在此边界的对抗模型内。

Cursor MCP 当前只支持用户手工配置，不由应用管理；不要把 Codex ownership marker 手工复制
到 Cursor 或其他配置。详见
[快速开始](docs/04-quickstart.md)。

## 数据与恢复

桌面数据默认位于：

```text
~/Library/Application Support/Local Context Forge/
```

可重建的 QMD/model cache 位于：

```text
~/Library/Caches/Local Context Forge/
```

Application Support 包含私有源码快照、SQLite、facts、proposal、任务和 Wiki。故障、替换应用
或更新前先退出 App，并备份整个目录。当前 desktop backup/legacy migration 的物理门禁没有
完成，不能把 legacy `data/` 直接覆盖到这里。恢复与可回退缓存重置见
[桌面版完整指南](docs/16-electron-desktop-guide.md)。

## Release 与更新

公开仓库使用 `.github/workflows/desktop-release.yml`：

- build/sign 只响应 `v*.*.*` tag push，并绑定仅允许该 tag pattern 的
  `macos-signing` Environment；
- 只有一个 private secret：
  `DESKTOP_RELEASE_CREDENTIAL_BUNDLE_BASE64`；
- Draft job 不绑定 Environment、也不读取 secret；
- 自签名证书、密码和 Ed25519 private key 不进入仓库、artifact 或普通 CI；
- public key 和 certificate fingerprint 作为可审查 lock 提交；
- tag push 只构建、签名并生成经远端复核的 Draft，不自动公开；
- 真机测试后，维护者必须以 `workflow_dispatch --ref main` 启动 promotion；`release_tag`
  只是资料输入，promotion 绑定只允许 branch `main`、零 secret 的 `macos-release`
  Environment；
- 两个 Environment 都要求独立 reviewer、prevent self review，且在 GitHub UI 禁止 admin
  bypass；`protected-main`、owner-only `release-tag-creation`、无 bypass 的
  `immutable-release-tags` ruleset 与 GitHub Immutable Releases 也必须开启；
- trusted `main` verifier 会在隔离 tag worktree 中重验候选，以固定 Release ID REST
  `PATCH` 公开；`PATCH` 前以 fresh `origin/main` comparison ref 重算 promotion order/
  `make_latest`，避免并行 tag 把旧版本设为 latest；随后执行 post-publish
  `gh release verify`、immutable 和完整资产复核。若运行开始时已经 published，一律按发布
  安全事件处理，不按幂等成功。

当前 public locks 是 `unprovisioned`，所以正式 workflow 会 fail closed。应用虽然实现了签名
manifest 检查，以及用户确认后的已验证 DMG 下载/打开，但物理 0.0.1 → 0.0.2 门禁尚未运行；
“自动应用更新”不是已交付能力。source/unprovisioned、校验或网络错误时不会旁路 signed
updater；只有用户显式操作才可让 Main 打开固定的 canonical GitHub Releases 页面，renderer
不能提供或读取该 URL，这个手工出口也不会改写 signed updater 的错误/候选状态。

repository owner、`contents` writer/能改 workflow 的主体仍是根信任；GitHub Draft 没有资产
CAS，verify→固定 ID `PATCH` 的竞态只能由发布后复核检测。真实 GitHub settings、受保护签名/
promotion、签名 DMG 和物理 Mac 证据仍为 `not-run`，所以整体结论是
**source merge GO / release NO-GO**。

## 开发者验证

```bash
make ci-source
```

分层命令：

```bash
make ci-python
make ci-web
make desktop-ci
```

源码启动需要开发运行时，不能证明 DMG：

```bash
make ci-python-install
npm --prefix web ci
npm --prefix web run build
make renderer-stage
npm --prefix desktop ci

LCF_RENDERER_DIR="$(pwd)/web/dist" \
LCF_SIDECAR_BIN="$(pwd)/backend/.venv/bin/lcf-service" \
npm --prefix desktop run start:source
```

打包、签名、clean-user、真实 Codex 和更新必须使用各自门禁，不能以 source smoke 代替。

## Legacy Docker/Web

原有路径继续保留用于当前运行和回退：

```bash
./install.sh
./scripts/lcf doctor
./scripts/lcf status
```

GitHub Actions/GHCR、多机 Ollama、HTTP MCP、legacy backup/restore 等旧操作仍在编号文档中。
不要让 legacy 与 Electron 同时写同一数据目录。后续只有完成代表性迁移、更新和回滚门禁，并
接受新的弃用 ADR 后，才会决定是否移除 legacy。

## 目录

```text
desktop/          Electron Main、preload、companion、QMD worker 与打包
web/              React + TypeScript renderer / legacy Web
backend/          Python sidecar、SQLite、队列、Wiki 与检索
mcp/              legacy streamable HTTP MCP gateway
runtime/          版本、runtime provenance、update/certificate public locks
host_runner/      legacy Docker 的宿主 CLI runner
scripts/          legacy 部署、备份、恢复与开发脚本
docs/             产品、运维、ADR、迭代和验证记录
tests/            后端与跨边界回归
```

## 文档导航

- [文档总索引](docs/README.md)
- [产品概览](docs/00-overview.md)
- [硬件与部署](docs/03-hardware-deployment.md)
- [快速开始](docs/04-quickstart.md)
- [Electron 桌面版完整指南](docs/16-electron-desktop-guide.md)
- [架构](docs/01-architecture.md)
- [API 与 MCP](docs/06-api-and-mcp.md)
- [Codex CLI](docs/07-codex-cli.md)
- [安全](docs/10-security.md)
- [开发与验证状态](docs/development/README.md)

## 许可证

项目使用 MIT License；第三方 runtime、模型和依赖仍受各自许可证约束。正式 Release 必须携带
经过审计的 notices、SBOM 与资源清单。

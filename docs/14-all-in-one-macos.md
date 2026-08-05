# M4 Pro 24 GB：all-in-one 桌面部署

> 当前事实与未完成门禁以[项目状态](development/status.md)为准；完整进程、数据和信任边界见
> [系统设计](17-system-design.md)，实际部署/发行/回滚步骤见
> [部署与运维](18-deployment-operations.md)。本章解释目标体验，不代表仓库现在已有可推荐
> 的 DMG。
>
> Docker all-in-one 小节是待删除历史内容，不再是回退建议。Electron 是唯一目标产品面。

## 部署决策

Local Context Forge 的目标默认形态是一个 macOS Apple Silicon Electron 应用：

- DMG 是普通用户唯一默认安装产物；
- Python 3.13.14 sidecar、Node 22.23.2、QMD 2.5.3、renderer 和 MCP companion 随 App
  提供；
- 目标机不需要 Docker、Homebrew、Python、Node、Git、QMD 或 ctags；
- Wiki 生成默认调用该用户已安装、已登录的 Codex CLI；
- 模型权重不塞进 DMG，只在用户明确发起 embedding rebuild 后按需准备；
- 数据保存在 Application Support，替换 App 不应覆盖用户数据。

这套结构适合 M4 Pro 24 GB，但“架构合理”不等于“发行已验证”。当前正式 Release、
clean-user、真实 Codex、物理模型和更新门禁仍未完成。只有经过审查的 DMG 存在后，才把
Electron 作为非开发者的推荐路径。

## 最简单的用户路径

经过审查的正式 Release 可用后，安装不需要脚本：

1. 下载 arm64 DMG 与发布摘要；
2. 核对 `SHA256SUMS`；
3. 打开 DMG，把 App 拖到 `/Applications`；
4. 按系统可撤销流程确认首次打开；
5. 在终端完成 `codex login`；
6. 在 App 中添加仓库、审核、查询和连接 MCP。

这比要求非技术用户运行 bootstrap 脚本更直接。完整步骤见
[快速开始](04-quickstart.md)。

## “一个脚本部署”现在指什么

仓库里有两个容易混淆的自动化入口：

### Electron 正式发行

推送符合 `v*.*.*` 的受保护 tag 后，`.github/workflows/desktop-release.yml` 在
`macos-15` runner 上自动执行整条构建：

```text
固定 tag/commit
  → 下载并校验固定 Python/Node 来源
  → 构建 Python onedir、QMD、renderer、companion
  → 运行测试和资源审计
  → 从 tag-only macos-signing Environment 读取唯一 credential bundle
  → 自签名、组装 DMG/ZIP/更新元数据
  → 无配置 Environment/repository release secret 或长期签名凭据的 job
    使用短期 GITHUB_TOKEN 创建并复核 GitHub Draft
  → 物理测试
  → --ref main、无配置 release secret/长期签名凭据的 macos-release promotion
    使用短期 GITHUB_TOKEN 复核并发布固定 Release ID
```

这是 **desktop tag 候选构建 + 独立人工 promotion**，不是终端用户安装脚本。Desktop workflow
永远停在 Draft；相同 tag 还会独立、非原子地触发 GHCR SemVer 发布，container image 可能先
公开，必须另行核对 run/digest。`release_tag` 只是 trusted `main` verifier 的资料输入。仓库
当前的 public key 和 certificate lock 仍是 `unprovisioned`，因此正式 desktop 发行会 fail
closed，不应声称已有可下载版本。

### legacy Docker all-in-one

```bash
LCF_CONTROL_BIN="$(pwd -P)/scripts/lcf"
lcf_managed() {
  env -i HOME="$HOME" PATH="$PATH" "$LCF_CONTROL_BIN" "$@"
}
lcf_managed install
```

或双击 `install.command`，仍会安装 Docker/Web/host runner 方案。它不是 Electron，不会产生
DMG，也不会写入桌面 Application Support。终端入口使用最小环境包装，是因为当前控制脚本尚未
自行隔离 Compose project/data/port 等调用者覆盖；详情见
[部署总手册](18-deployment-operations.md#22-安装)。该路径当前尚在源码树，但已经 unsupported，
不要新建部署；W02 packaged smoke 通过后，它会在 ITER-0008/W10–W11 的独立 slice 中删除，
不再等待完整 aggregate cutover。

当前没有一个把未审查源码直接变成“可推荐桌面安装”的本地脚本；这样可以避免把 source smoke
误当成签名、clean-user 和更新证据。

## 应用内部结构

| 进程 | 职责 | 用户不需要安装 |
| --- | --- | --- |
| React renderer | 仓库、任务、审核、查询、设置 UI | Node |
| Electron Main | 文件选择、IPC、进程、更新和安全边界 | 额外 daemon |
| Python sidecar | SQLite、采集、Wiki、队列和领域 API | Python/Git/ctags |
| Node/QMD worker | lexical、embedding 和 hybrid 检索 | Node/QMD |
| MCP companion | Context7 兼容 stdio 工具 | npm/npx |
| Codex CLI | 生成待审核 Wiki | 仍由用户单独安装和登录 |

Main 与 sidecar/worker 使用每次启动的私有 Unix domain socket 和能力令牌。Renderer 看不到
socket、token、完整本地路径、provider executable 或更新下载目录。

## 数据位置

当前桌面实现使用：

```text
~/Library/Application Support/Local Context Forge/
~/Library/Caches/Local Context Forge/
```

Application Support 包含数据库、源码快照、facts、提案、任务、Wiki、provider attempt 和
QMD 状态，应视为私有源码数据。Caches 包含可重建的 QMD runtime/model cache。

应用 bundle、Codex/Cursor 登录、release private key 不在这些目录。删除缓存可能要求重新下载
模型和重建索引，但不应删除已发布 Wiki；移动或删除 Application Support 则会影响真实数据。

当前桌面版没有经过物理验证的一键 backup/restore 或 legacy 自动迁移 UI。更新、卸载和故障
操作前，应先退出应用并复制整个 Application Support 目录；不要只备份 QMD cache。详细安全
步骤见[桌面版完整指南](16-electron-desktop-guide.md)。

## Codex 与 Cursor

应用启动任务前检查受支持的 Codex 安装和登录状态。执行参数固定为只读、ephemeral、
忽略用户配置和仓库规则，并通过 stdin 提供有界证据；输出必须匹配 schema。

桌面设置只有两种策略：

- `Codex only`：默认；
- `Codex then Cursor`：用户明确勾选并保存后启用。

后者也只在 Codex **开始前**被确认未安装或未登录时生效。Codex installation unsupported、
临时 unavailable、执行超时、非零退出或输出无效都不会触发 Cursor。Cursor 使用自己的账号
和额度，应用不会把两个账号视为同一个订阅。

## 仓库、队列、审核与重建

- 公开远程地址只接受 `https://github.com/...`；
- 私有仓库先 clone 到本机，再由系统目录选择器授权；
- 采集和 embedding rebuild 共用持久 FIFO，固定单 worker；
- 任务可查看队列位置、取消和显式 retry；
- 每个新 ref 必须生成新的不可变 version label；
- 提案逐页批准；整版全部批准后才激活；
- 更换 embedding 后必须“保存并重建全部”；
- embedding 未 ready 时自动 lexical fallback；
- rebuild 不调用 Codex/Cursor。

## MCP

App 位于 `/Applications` 且 Codex 已登录后，在“设置”点击“连接 Codex”。应用调用
`codex mcp add`，登记 App 内固定 Node、companion 和由应用生成的
`LCF_MCP_OWNER_ID`，随后再读取配置确认结果。只有 marker、按规范化 `CODEX_HOME` 隔离的
mode-0600 ownership ledger，以及 exact command/arg 全部匹配时，应用才把 target 视为自有；
missing/damaged/legacy/mismatch/extra-env/lookalike 状态均 fail closed。marker 不是 secret 或
MCP capability，companion 在桥接前会删除它。

应用在 add/remove 前会二次读取配置，但 Codex CLI 没有 CAS 或共享配置锁；最终 list 与 mutation
之间仍有小竞态。恶意 same-UID 进程也能读写 Codex config/ledger，并利用 bundle/state
check-use 窗口。因此这是单用户、同 UID 非对抗边界，不能无条件保证并发第三方 writer 的配置
不受影响。

companion 只提供：

- `resolve-library-id`
- `query-docs`

App 必须运行。当前持久配对、Keychain/client code identity 门禁未完成，所以不要把它用于
多用户或远程服务。Cursor MCP 只支持用户手工配置，不由 App 管理，也不要复制 Codex ownership
marker。

## 签名与首次打开

正式发行设计使用固定项目自签名证书：

- 不是 Apple Developer ID；
- 不 notarize 或 staple；
- `hardenedRuntime: false`；
- Electron fuses 仍关闭不需要的 Node/inspect 能力；
- 发布说明和 UI 必须披露限制。

首次打开只使用 Finder“打开”或“系统设置 → 隐私与安全性 → 仍要打开”。不要关闭 Gatekeeper、
清除 quarantine 或使用 `sudo`。

## 更新

设置页可以：

- 检查 canonical GitHub Release；
- 验证内置 Ed25519 公钥签名的 update manifest；
- 校验版本、架构、大小和 DMG SHA-256；
- 下载并打开已验证 DMG；
- 在 source/unprovisioned、校验、网络或打开错误时，由用户显式打开固定的官方 Release 页面。

应用目前不会静默替换 App、运行 ZIP、重启或删除数据。`VAL-UPDATE-001` 的物理
真实 `N-1 → N` 门禁仍未运行，因此“自动应用更新”不是已交付能力；用户需在打开的 DMG 中手工
拖拽替换。Release 页面操作不接受 Renderer URL，也不会把 signed updater 的候选/错误状态改成
成功；它只是人工出口，不证明页面已有 Release 或其中资产已验证。

## 高级用户：源码模式

源码模式只用于开发验证，不是 all-in-one 发行。它需要 Node、Python/uv 和源码依赖，也不会让
MCP onboarding 写入持久 Codex 配置。

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

真实启动前仍应运行：

```bash
make ci-source
```

源码模式 QMD staging、签名、DMG、clean-user 和更新能力与正式包不同。不能用一次成功启动替代
发行门禁。

## 高级用户：发布管理

本节是 W14–W16 的 formal 流程，必须等待 W13 final cutover/absence。W02/W03 engineering
artifact 不使用本节 Environment/credential/pins，也不得 tag、upload、Draft 或 promotion。
W15 必须证明 W13 checkpoint → formal tag 只有 allowlisted public pins/release metadata/version
diff；W16 必须在 exact Draft digest 重新运行完整 cutover/absence 后才可 promotion。

正式发布需要公开仓库中的两个受保护 Environment：

1. `macos-signing`：required reviewer、prevent self review、UI 禁 admin bypass，custom
   deployment policy 只允许 tag `v*.*.*`，只保存
   `DESKTOP_RELEASE_CREDENTIAL_BUNDLE_BASE64`；
2. `macos-release`：required reviewer、prevent self review、UI 禁 admin bypass，custom
   deployment policy 只允许 branch `main`，Environment/repository release secret 集合为空，
   无长期签名凭据；promotion job 仍使用 GitHub 自动签发的短期 `GITHUB_TOKEN`；
3. active `protected-main` ruleset 要求 PR、独立 approval、dismiss stale、last-push approval、
   resolve threads、禁止 force/delete、无 bypass；
4. active `release-tag-creation` 只允许 canonical owner actor 创建 `v*.*.*` tag，
   `immutable-release-tags` 禁止 update/delete 且无 bypass；
5. GitHub Immutable Releases 必须开启；
6. 公共 update key、update lock 与 certificate fingerprint lock 必须提交并经审查；
7. PR、fork 和普通 source CI 不能读取唯一 secret。

管理员初始化命令：

```bash
python3 tools/bootstrap_desktop_release_keys.py \
  --repo fredgnr/local-context-forge \
  --upload \
  --confirm-admin-bypass-disabled
```

脚本先验证公开仓库、Environment/ruleset/secret membership 与 Immutable Releases policy，
再通过 `gh` 的 stdin 向 `macos-signing` 上传一个版本化 credential bundle，只在仓库工作区
写入公共 key 与两个 public lock。`--confirm-admin-bypass-disabled` 表示管理员已在 UI 核对
API 无法可靠证明的开关。脚本不会打印私钥。管理员必须审查并提交这三个公共文件后才能打 tag；
当前未 provision 的 marker 会让 Release workflow 拒绝继续。

promotion 必须使用 `workflow_dispatch --ref main`。trusted verifier 把输入 tag 隔离到 detached
worktree，fresh-peel tag、固定 Draft Release ID；在 PATCH 前以 fresh-fetched `origin/main`
comparison ref 重算 promotion order/`make_latest`，再以一次 REST PATCH 公开，并在公开后执行
`gh release verify` 与 immutable/完整资产复核。已 published 预状态是安全事件，不按幂等成功。
repository owner、contents writer/可改 workflow 的主体和 settings admin 仍是根信任；GitHub
Draft 无资产 CAS，verify→PATCH 竞态只能后验检测。

真实 GitHub settings、protected signing/promotion 和物理 Mac 证据仍为 `not-run`；PR #20 的
W01 remediation 尚待 exact-head 独立验收，当前为 **PR merge blocked / release NO-GO**。

完整发布和恢复操作见[桌面版完整指南](16-electron-desktop-guide.md)。

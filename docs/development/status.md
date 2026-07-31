# 项目状态快照

本页是 Local Context Forge 当前状态的权威入口。用户指南、路线图、迭代记录和 Release
说明应链接本页，不应各自推断“已经可发布”。架构与实现细节分别见
[系统设计](../17-system-design.md)和[开发者手册](contributor-handbook.md)；剩余工作见
[TODO](todo.md)。

## 快照坐标

| 字段 | 值 |
| --- | --- |
| 截止日期 | 2026-07-31 |
| canonical repository | `fredgnr/local-context-forge` |
| 本轮文档审计基线 | `main@fb8bbbc3d0b4e4b5a20c943bd7fd71b2450651a8` |
| 基线来源 | PR #7、#8、#17 已合入 `main` |
| 产品版本 | `0.3.0-alpha.1` |
| 数据库 schema | `5` |
| 活动父迭代 | [ITER-0002](iterations/0002-bundled-runtimes.md) |
| 当前结论 | **source merge GO / public release NO-GO** |

这里的 `source merge GO` 只说明受审查的源码纵切和 source CI 可以继续合并。它不表示：

- 存在可推荐给普通用户的 DMG；
- 打包应用已经在干净 M4 用户上运行；
- GitHub Environments、rulesets、Immutable Releases 已按生产要求配置；
- 自签名证书和更新密钥已经 provision；
- 真实 Codex、QMD 模型、本地外置卷、MCP 或跨版本更新门禁已经通过。

## 可复现的当前源码证据

PR #17 的 head `71890ee99edc572f32a1e4eaf946853bc1e57f4e` 运行了：

- [Desktop source CI run 30611309112](https://github.com/fredgnr/local-context-forge/actions/runs/30611309112)：
  Python、Web、Desktop source checks，以及 macOS 15 arm64 source IPC contract 均成功；
- [Container PR build run 30611309114](https://github.com/fredgnr/local-context-forge/actions/runs/30611309114)：
  容器 PR 构建成功，但不发布镜像。

该 head 随 PR #17 以 merge commit `fb8bbbc` 进入 `main`。这两次运行不包含真实签名、
DMG、模型权重、已登录 Codex、干净用户安装或 GitHub 控制面验证，因此不能提升任何
packaged/physical gate。

## 交付路径状态

| 路径 | 当前可用性 | 适用对象 | 主要限制 |
| --- | --- | --- | --- |
| Electron 源码模式 | 可用于开发和 source 验证 | 开发者 | 借用开发机 Python/Node；不是正式包 |
| Electron 正式 DMG | `not-run` / 不推荐 | 将来的普通用户 | trust pins、签名、真机和 promotion 未完成 |
| Legacy Docker/Web | 已弃用、unsupported、待删除 | 仅用于解释当前仓库残留 | 不承诺修复、迁移、兼容窗口或继续可用 |
| Windows + Ollama | unsupported | — | Electron 不支持远程 Windows worker；legacy 路径将删除 |
| 公开 Sites guide | stale / 未验证 | 暂不作为使用入口 | 仍含 legacy 可复制命令；本 checkout 缺 hosting identity，禁止猜站点或误部署 |

不要新建 legacy 部署。仓库中暂存的 `./install.sh`、`install.command`、`make install`、
Compose 和 localhost HTTP 路径尚未从代码删除，但不再是受支持交付路径；它们会由
ITER-0007 移除。此状态变化不自动停止现有容器，也不读取、迁移或删除旧数据。

## 阶段状态

| 阶段 | 状态 | 已有内容 | 尚缺的退出证据 |
| --- | --- | --- | --- |
| P0 治理与契约 | `validated` | AGENTS、skills、ADR、迭代、追踪矩阵 | 持续维护链接和证据 |
| P1 Electron 信任边界 | `in-progress` | Main/preload/renderer source 合同 | packaged renderer/IPC 审计 |
| P2 Python sidecar | `in-progress` | PyInstaller/Dulwich/source 打包合同 | clean M4 bundled runtime |
| P3 QMD/MCP/provider | `in-progress` | worker、broker、companion、attempt source 合同 | native QMD、真实模型、真实 CLI/MCP |
| P4 Desktop 数据、模型 | `planned` | 标准路径部分落地 | Desktop backup/restore、完整模型供应链、unknown layout fail-closed |
| P5 DMG 与发布 | `planned` | 两阶段 workflow/source policy | GitHub settings、trust pins、签名 Draft、clean-user |
| P6 更新实机门禁 | `planned` | signed check/download/open-DMG source client | 真实 `N-1 → N`、失败注入；automatic apply 尚未设计 |
| P7 Electron-only 退出 | `planned` | ADR-0015 与严格删除计划 | capability cutover、解耦、removal、absence gate |

P2/P3 的实现依赖 P1 已冻结的 source IPC contract，而不是 P1 的完整 packaged gate。
P5/P6 的 source foundation 提前落地，不代表可以绕过 P4 或对应物理退出门禁。

## 验证门禁摘要

### Source 级已有证据

| Gate | 结果 | 说明 |
| --- | --- | --- |
| `VAL-GOV-001` baseline | `pass` | `71890ee` 的 Python source job（Actions 30611309112）包含 Markdown 相对链接检查 |
| `VAL-DOC-HANDOFF-001` R11 local review | `pass`（仅本地） | 修复后三路只读审计无 Critical/High/Medium；dirty worktree 不能替代最终 commit/PR |
| `VAL-DOC-HANDOFF-001` R11 checkpoint | `pass` | [`625db76` clean-checkout 证据](evidence/VAL-DOC-HANDOFF-001/2026-07-31-625db76.md)；冻结全部实质文档 |
| `VAL-DOC-HANDOFF-001` R11 final head | `not-run` | clean checkout/最终 PR head 的 commit-bound 复核待运行 |
| `VAL-GOV-001` R11 final head | `not-run` | 本轮本地检查后，仍须由 documentation PR 最终 head CI 绑定 |
| `VAL-GOV-001` R12 checkpoint | `pass` | `64ec3c2` clean-checkout link/version/skill/diff/ID checks；证据同下一行 |
| `VAL-LEGACY-SCOPE-001` R12 checkpoint | `pass` | [`64ec3c2` clean-checkout evidence](evidence/VAL-LEGACY-SCOPE-001/2026-07-31-64ec3c2.md)；只验证 planning/docs scope |
| `VAL-P1-SOURCE-001` | `pass` | Linux/macOS source jobs 与真实 AF_UNIX bind |
| `VAL-P1-REGRESSION-001` | `pass` | Backend/Desktop/Web/Host Runner 已有组件证据 |
| `VAL-RELEASE-POLICY-001` | `pass` | 两阶段 workflow/bootstrap 的 source policy |
| `VAL-RELEASE-PROMOTION-001` source | `pass` | Draft-only、trusted-main、fixed Release ID source 合同 |
| `VAL-UPDATE-CLIENT-001` | `pass` | manifest、cache、IPC、verified DMG source 合同 |
| `VAL-LOCAL-SOURCE-001/002` | `pass` | grant/path 与 Backend 双层 source policy |

### 必须保持 `not-run`

| Gate | 最低真实环境 |
| --- | --- |
| `VAL-TRUST-001` | packaged App 的 renderer/Main 权限审计 |
| `VAL-PY-001`、`VAL-GIT-001`、`VAL-IPC-001` | 无外部 runtime 的 clean macOS arm64 |
| `VAL-QMD-001`、`VAL-QMD-EMBED-001`、`VAL-MODEL-EMBED-001` | bundled native QMD + 真实模型 |
| `VAL-CLI-001` | 已安装并登录的真实 Codex/Cursor |
| `VAL-MCP-001`、`VAL-MCP-ONBOARD-001` | `/Applications` packaged App + 官方签名 Codex |
| `VAL-LOCAL-SOURCE-003` | home、外置卷、私有仓库和重启物理矩阵 |
| `VAL-DATA-001`、`VAL-MODEL-001` | Desktop backup/restore、完整模型下载/激活 |
| `VAL-SECRET-001` | 真实 GitHub Environments/rulesets/Immutable Releases |
| `VAL-RELEASE-001`、`VAL-INSTALL-001` | 真实签名 Draft 与 clean-user Gatekeeper/smoke |
| `VAL-UPDATE-001` | 两个真实单调版本的 `N-1 → N` 与失败恢复 |
| `VAL-ELECTRON-CUTOVER-001` | source + clean M4 packaged capability replacement matrix |
| `VAL-LEGACY-ABSENCE-001` | final removal commit + packaged inventory + active-doc audit |

`VAL-LEGACY-001` 与 `VAL-LEGACY-CONTROL-001` 从未运行，并由 ADR-0015 取代；它们保持
`not-run (superseded)`，不再是退出或发布门禁。

完整 REQ/ADR/ITER/VAL 映射见[追踪矩阵](traceability.md)。

## 当前阻塞

1. Desktop 数据布局、backup/restore 和完整模型供应链尚未达到 P4 退出条件。
2. `macos-signing`、`macos-release`、三组 ruleset 和 Immutable Releases 的真实设置没有
   证据。
3. `runtime/update-metadata-key.lock.json` 和
   `runtime/macos-codesign-certificate.lock.json` 仍为 `unprovisioned`；生产公钥文件不存在。
4. 没有由受保护 workflow 生成且通过真机测试的唯一 Draft 候选。
5. 没有 clean-user M4、真实 Codex、native QMD/model、local source 和 MCP 的完整证据。
6. 更新客户端当前只支持签名检查、下载和打开 DMG；automatic apply/install/restart/
   rollback 没有已接受设计和实现。
7. Electron capability replacement、shared-code decoupling 和 legacy absence gate 均为
   `not-run`；因此既不能直接粗暴删目录，也不能公开首个 Electron-only Release。
8. `guide-site` 源和现有公开说明仍包含 legacy 安装/localhost/Host Runner 内容，且本 checkout
   没有可验证的 `.openai/hosting.json`；必须先恢复 exact Sites identity，再改写、测试和留下
   checkpoint deployment evidence。当前站点不是权威使用入口。

## 下一步工作分组

### Ready now：无需外部管理员或物理候选

1. `TODO-GOV-EVIDENCE-001`：把剩余 source 结论统一绑定到公开 commit/Actions；
2. `TODO-CI-COVERAGE-001`：决定并机器化 QMD worker/guide-site 的 source CI 覆盖；
3. `TODO-ELECTRON-CUTOVER-001`：建立逐能力替代矩阵并补齐可在 source 环境运行的子门禁；
4. `TODO-LEGACY-DECOUPLE-001`：在删除目录前拆开 renderer/sidecar 与 browser/TCP/spool 分支。

### Dependency-blocked：先取得前序设计/格式证据

1. `TODO-DATA-LAYOUT-001` 需要先证明 ITER-0002 持久格式已经冻结到可建立新 desktop-only
   baseline 的程度；
2. Desktop backup/restore 依赖冻结后的 layout；不再开发 legacy migration；
3. 完整 model supply、formal staging 和后续物理门禁依赖上述数据合同；
4. legacy deploy/transport/release/docs 删除依赖 Electron replacement 与共享代码解耦；
5. Draft、promotion 与真实 `N-1 → N` 依赖唯一正式候选、legacy absence 和相应前序 gate。

### Admin-blocked：需要仓库控制面权限或独立 reviewer

1. `TODO-REL-GOV-001`：配置两个 Environment、三组 ruleset 和 Immutable Releases；
2. `TODO-REL-KEYS-001`：只能在前项通过后由可信管理员 provision credential bundle 并提交
   public trust pins。

解除依赖后，才依次创建唯一 Draft、完成同一资产的 M4 物理测试、从
`workflow_dispatch --ref main` promotion，并用两个真实单调版本完成 `N-1 → N`。Automatic
apply 若要实现，必须先新增或 supersede ADR-0011。

每项的 owner、依赖、产物和验收条件见[详细 TODO](todo.md)。

## 状态更新规则

- 只有包含 commit、环境、命令、结果和脱敏证据位置的记录才能把 gate 标为 `pass`。
- “当前工作树通过”、mock、fake store、source build 或同版本重装不能替代 packaged/
  physical gate。
- 更新本页时同步活动迭代和[追踪矩阵](traceability.md)；架构决策变化先新增或
  supersede ADR。
- 公开 Release 之前再次核对本页结论；任一必需 gate 为 `fail` 或 `not-run`，仍是
  **release NO-GO**。

# 项目状态快照

本页是 Local Context Forge 当前状态的权威入口。用户指南、路线图、迭代记录和 Release
说明应链接本页，不应各自推断“已经可发布”。架构与实现细节分别见
[系统设计](../17-system-design.md)和[开发者手册](contributor-handbook.md)；剩余工作见
[TODO](todo.md)。

## 快照坐标

| 字段 | 值 |
| --- | --- |
| 截止日期 | 2026-08-03 |
| canonical repository | `fredgnr/local-context-forge` |
| 本轮治理基线 | `main@da40553e43ec6272e1affc1f40abf4f9215f1ba5` |
| 基线来源 | PR #7、#8、#17、#18 已合入 `main`；本 Work 开始时 open PR/tag/Release 均为 0 |
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

PR #17 的 head `71890ee99edc572f32a1e4eaf946853bc1e57f4e` 提供了既有 source contract。
PR #18 随 merge commit `da40553e43ec6272e1affc1f40abf4f9215f1ba5` 进入 `main`。截至
2026-08-03，最近 main 的 Desktop source CI run `30630283893` 与 container run
`30630283873` 成功；container workflow 仍存在。历史 PR #17 证据包括：

- [Desktop source CI run 30611309112](https://github.com/fredgnr/local-context-forge/actions/runs/30611309112)：
  Python、Web、Desktop source checks，以及 macOS 15 arm64 source IPC contract 均成功；
- [Container PR build run 30611309114](https://github.com/fredgnr/local-context-forge/actions/runs/30611309114)：
  容器 PR 构建成功，但不发布镜像。

这些运行不包含可用 packaged smoke、真实签名、
DMG、模型权重、已登录 Codex、干净用户安装或 GitHub 控制面验证，因此不能提升任何
packaged/physical gate。

## 交付路径状态

| 路径 | 当前可用性 | 适用对象 | 主要限制 |
| --- | --- | --- | --- |
| Electron 源码模式 | 可用于开发和 source 验证 | 开发者 | 借用开发机 Python/Node；不是正式包 |
| 最小 packaged smoke | `planned` / `not-run` | 后续 W02 removal feedback | 当前 base builder 被 unprovisioned production trust audit 阻断；不得用 legacy `make smoke` 冒充 |
| 完整 engineering test package | `planned` / `not-run` | W04–W12 工程物理验证 | 只能从 W10/W11 cleaned tree 构建；UNOFFICIAL、无 production trust/tag/upload |
| Electron 正式 DMG | `not-run` / 不推荐 | 将来的普通用户 | trust pins、签名、真机和 promotion 未完成 |
| Legacy Docker/Web | 已弃用、unsupported、待删除 | 仅用于解释当前仓库残留 | 不承诺修复、迁移、兼容窗口或继续可用 |
| Windows + Ollama | unsupported | — | Electron 不支持远程 Windows worker；legacy 路径将删除 |
| 公开 Sites guide | stale / 未验证 | 暂不作为使用入口 | 仍含 legacy 可复制命令；本 checkout 缺 hosting identity，禁止猜站点或误部署 |

不要新建 legacy 部署。仓库中暂存的 `./install.sh`、`install.command`、`make install`、
Compose 和 localhost HTTP 路径尚未从代码删除，但不再是受支持交付路径；它们会由
ITER-0008 的 W10/W11 slices 移除。此状态变化不自动停止现有容器，也不读取、迁移或删除旧数据。

## 阶段状态

| 阶段 | 状态 | 已有内容 | 尚缺的退出证据 |
| --- | --- | --- | --- |
| P0 治理与契约 | `validated` | AGENTS、skills、ADR、迭代、追踪矩阵 | 持续维护链接和证据 |
| P1 Electron 信任边界 | `in-progress` | Main/preload/renderer source 合同 | packaged renderer/IPC 审计 |
| P2 Python sidecar | `in-progress` | PyInstaller/Dulwich/source 打包合同 | clean M4 bundled runtime |
| P3 QMD/MCP/provider | `in-progress` | worker、broker、companion、attempt source 合同 | native QMD、真实模型、真实 CLI/MCP |
| P4 Desktop 数据、模型 | `planned` | 标准路径部分落地 | Desktop backup/restore、完整模型供应链、unknown layout fail-closed |
| P5 DMG 与发布 | `planned` / 后置 W14–W16 | 两阶段 workflow/source policy | W13、GitHub settings、trust pins、签名 Draft、clean-user |
| P6 更新实机门禁 | `planned` | signed check/download/open-DMG source client | 真实 `N-1 → N`、失败注入；automatic apply 尚未设计 |
| P7 Electron-only 退出 | `planned` | ADR-0015/0016、W01–W16 与严格删除计划 | W02 smoke、W10/W11 slices、W03 engineering package、W13 final gates |

P2/P3 的实现依赖 P1 已冻结的 source IPC contract，而不是 P1 的完整 packaged gate。
P5/P6 的 source foundation 提前落地，不代表可以绕过 P4 或对应物理退出门禁。

## 验证门禁摘要

### Source 级已有证据

| Gate | 结果 | 说明 |
| --- | --- | --- |
| `VAL-PRE1-SEQUENCE-001` authoring observation | gate `not-run`；local command `pass` | exact mappings、11 个负向 fixtures、links/version/ID-set/diff 通过；dirty authoring tree 不能替代 final PR head |
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
| `VAL-PRE1-SEQUENCE-001` final head | clean checkout / final PR head；当前 authoring tree 结果不作 commit-bound evidence |
| `VAL-PACKAGED-SMOKE-001` | 独立 engineering-smoke mode 的 macOS arm64 packaged App |
| 六个 `VAL-LEGACY-*` slice gate | exact before/after commit 与 fresh package digest；本 Work 不执行删除 |
| `VAL-ENGINEERING-PACKAGE-001` | W10/W11 cleaned tree 的完整 non-release 工程包 |
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
| `VAL-ELECTRON-CUTOVER-001` | W13 final cleaned engineering package；W16 exact Draft digest 的完整第二次执行 |
| `VAL-LEGACY-ABSENCE-001` | W13 同一 engineering digest；W16 exact Draft/tag source 的第二次 aggregate absence |
| `VAL-RELEASE-CONTINUITY-001` | W13 checkpoint→formal tag allowlisted diff、tag source/absence 与 W16 exact Draft cutover/absence |

`VAL-LEGACY-001` 与 `VAL-LEGACY-CONTROL-001` 从未运行，并由 ADR-0015 取代；它们保持
`not-run (superseded)`，不再是退出或发布门禁。

完整 REQ/ADR/ITER/VAL 映射见[追踪矩阵](traceability.md)。

## 当前阻塞

1. 当前没有可用的 W02 packaged smoke harness；base builder 虽标记 UNOFFICIAL，仍会被
   unprovisioned production update trust audit fail closed。
2. W10/W11 的 decouple/deploy/transport/provider/release/docs slice 均未执行，container/GHCR
   workflow 与 legacy runtime 仍在。
3. W03 cleaned-tree engineering package 以及 Desktop data/backup/model/runtime/CLI/MCP/local 的
   W04–W12 工程物理矩阵尚未完成。
4. `macos-signing`、`macos-release`、三组 ruleset 和 Immutable Releases 的真实设置没有证据；
   按 ADR-0016 这些工作后置到 W14，不是 W02/W10/W11 的当前前置。
5. `runtime/update-metadata-key.lock.json` 和
   `runtime/macos-codesign-certificate.lock.json` 仍为 `unprovisioned`；生产公钥文件不存在。
6. 没有由受保护 workflow 生成且通过 continuity、exact Draft cutover/absence 与真机测试的唯一
   Draft 候选。
7. 更新客户端当前只支持签名检查、下载和打开 DMG；automatic apply/install/restart/
   rollback 没有已接受设计和实现。
8. `guide-site` 源和现有公开说明仍包含 legacy 安装/localhost/Host Runner 内容，且本 checkout
   没有可验证的 `.openai/hosting.json`；必须先恢复 exact Sites identity，再改写、测试和留下
   checkpoint deployment evidence。当前站点不是权威使用入口。

## 下一步工作分组

### Ready now：无需外部管理员或物理候选

1. 完成 W01 的 `TODO-PRE1-SEQUENCING-001`、`TODO-GOV-EVIDENCE-001` 与
   `TODO-CI-COVERAGE-001` 三个 final-head gate；
2. W01 全部退出后，执行 `TODO-PACKAGED-SMOKE-001`：实现明确隔离于 formal release 的 W02
   harness；
3. W02 通过后，按 [work plan](work-plan.md) 分别认领 W10/W11 slice；不能把它们合成无
   owner 的大删除。

### Dependency-blocked：先取得前序设计/格式证据

1. W10/W11 每个 destructive slice 依赖 W02、exact ownership，以及 affected replacement 或合格
   pure-legacy unsupported disposition；不依赖 unrelated full physical gate；
2. W03 依赖全部 W10/W11 slice；W04 data/layout/backup 和 W05 model 再依赖 cleaned package；
3. W06–W12 使用同一工程 artifact class 完成 runtime、QMD、CLI、MCP、local 与物理矩阵；
4. W13 依赖 W03–W12，并在 final rebuilt digest 上同时运行 cutover/absence；
5. Draft、promotion 与真实 `N-1 → N` 依赖 W13–W15；promotion 前还必须在 exact Draft
   digest 重跑 cutover/absence，并通过 `VAL-RELEASE-CONTINUITY-001`。

### Admin-blocked：需要仓库控制面权限或独立 reviewer

以下任务已知需要管理员，但按新顺序必须等待 W13，不应现在执行：

1. W14 `TODO-REL-GOV-001`：配置两个 Environment、三组 ruleset 和 Immutable Releases；
2. W15 `TODO-REL-KEYS-001`：只能在 W14 通过后由可信管理员 provision credential bundle 并
   提交 public trust pins。

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

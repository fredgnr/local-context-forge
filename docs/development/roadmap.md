# Electron 迁移路线图

## 基线与目标

- 上游基线：`main@5d95e58cefa1c94b5c9ac8dd681671e2dfd6d8dd`
- bundled runtime merge：`main@52a5ffa184da694519a906dbacc7ee9df26a3fcc`
- two-stage release merge：`main@fb8bbbc3d0b4e4b5a20c943bd7fd71b2450651a8`
- Electron-only planning merge：`main@da40553e43ec6272e1affc1f40abf4f9215f1ba5`
- 当前治理基线：`main@3eff97d97b2de4484d568bab5ac96d63830c79ee`
- 平台目标：macOS Apple Silicon
- 当前总体状态：`in-progress`

P0–P7 是历史产品阶段，不再直接表达执行顺序；权威 execution rank 见
[W01–W16 work plan](work-plan.md)。本路线图不是完成声明。各阶段只有在其退出门禁有可复现
`pass` 证据后，
才能进入 `validated`。当前快照见[status](status.md)，可执行任务见[TODO](todo.md)。

## 依赖图

```text
W01 governance/source baseline
  → W02 minimal packaged smoke
  → W10/W11 legacy slices
  → W03 cleaned-tree engineering package
  → W04–W12 engineering/physical gates
  → W13 final cutover + aggregate absence
  → W14–W16 production controls/credentials/formal release/update
```

P2 与 P3 可在 P1 的 IPC 契约冻结后并行。W02 只建立最小 packaged feedback；W10/W11 每个
slice 只等待受影响 replacement 或合格的 pure-legacy unsupported disposition，不等待无关完整
物理矩阵。P4 的数据/model 与其他真实能力门禁改在 W03 cleaned engineering package 上完成。
P7 的 slice 部分前置，final cutover/absence 保留为 W13；P5 production control/credential/
formal candidate 延后到 W14–W16。W13 只解锁控制面，formal tag 与 exact Draft 仍需独立
continuity 和 cutover/absence 复验。

## 里程碑总览

| 阶段 | 状态 | 迭代 | 主要产物 | 依赖 | 退出门禁 |
| --- | --- | --- | --- | --- | --- |
| P0 治理与契约 | `validated` | ITER-0001 | AGENTS、skills、ADR、迭代、追踪矩阵 | 无 | G0 |
| P1 Electron 壳与信任边界 | `in-progress` | ITER-0001 | Main/preload/renderer 骨架、类型化 IPC | P0 | G1 |
| P2 Python sidecar | `in-progress` | ITER-0002 | Python 3.13.14 PyInstaller `onedir`、生命周期契约 | P1 source IPC contract | G2 |
| P3 Node/QMD 与 MCP | `in-progress` | ITER-0002 | 独立 Node 22/QMD worker、Context7 兼容契约 | P1 source IPC contract；与 P2 并行 | G3 |
| P4 路径、备份与模型 | `planned` | ITER-0003 | macOS 路径、Desktop backup/restore、模型供应链 | P2、P3 | G4 |
| P5 DMG 发行基础 | `planned` / W14–W16 | ITER-0004 | arm64 DMG、自签名、受保护发布流程 | W13 | G5 |
| P6 更新实机门禁 | `planned` | ITER-0005 | 真实单调 `N-1 → N` 实机报告、DMG fallback | P5 | G6 |
| P7 Electron-only 退出 | `planned` | ITER-0008（ITER-0007 superseded） | W10/W11 slices、W13 final cutover/absence | W02；final gate 另依赖 W03–W12 | G7 |

表中状态表示阶段完整退出门禁，而不是“是否已有 source 实现”。P2/P3 依赖 P1 已冻结的
source IPC contract，不要求先把 P1 packaged gate 标成完成。ITER-0001 的 source
纵切已验证，但 packaged trust/IPC 尚未运行，所以 P1 仍为 `in-progress`。当前 ITER-0002
提前实现了 P5 的受保护 release workflow/policy，以及 P6 的独立签名检查和 verified DMG
fallback source 纵切；ITER-0004/0005 仍保持 `planned`，因为 protected Environment、
clean-user DMG 和物理跨版本证据均未运行。automatic apply 继续禁用，启用前还需
`VAL-UPDATE-001` 和新增或 superseding [ADR-0011](../adr/0011-main-owned-signed-update-client.md)。

## P0：治理与契约

交付：

- 根规则与分层规则约定；
- 两个职责分离的项目 skill；
- 初始 ADR、活动迭代和需求—验证映射；
- 相对链接与 skill 结构检查。

G0：

- `VAL-GOV-001` 文档内部链接通过；
- `VAL-GOV-002` 两个 skill 结构通过；
- 所有当前硬约束都有稳定需求 ID、ADR、任务和计划验证；
- 未实现能力均未标记为完成。

## P1：Electron 壳与信任边界

交付：

- React renderer 运行在 sandbox + context isolation 下；
- preload 只暴露版本化、类型化、allowlist IPC；
- Electron Main 独占文件、子进程、更新、凭据和协议路由；
- 窗口、深链和不可信内容使用安全默认值。

G1：

- `VAL-TRUST-001` 证明 renderer 无 Node/原始 IPC/任意路径或命令能力；
- CSP、导航、新窗口、外部链接与 payload 上限的负向测试通过；
- Main/renderer 契约版本不匹配时 fail closed。

当前证据：源码合同与回归已在 Linux x86_64 通过；公开仓库的 GitHub Actions 又在
Ubuntu 与 macOS 15 arm64 完成全部 source jobs，包含真实 AF_UNIX bind，因此
`VAL-P1-SOURCE-001` 为 `pass`。但 `VAL-TRUST-001` 的 packaged app 与
`VAL-IPC-001` 的 packaged child/lifecycle 仍为 `not-run`，G1 未满足，P1 保持
`in-progress`。

## P2：Python sidecar

交付：

- 固定 Python 3.13.14 构建；
- PyInstaller `onedir` 包含运行所需模块和资源；
- Main 通过私有 UDS 启动、探活、停止和恢复 sidecar；
- 目标 Mac 不使用系统 Python、Git 或 ctags。

G2：

- `VAL-PY-001` 在无系统 Python/Git/ctags 的干净用户环境运行；
- `VAL-IPC-001` 覆盖令牌、权限、超时、崩溃和 stale socket；
- 现有领域回归测试针对打包 sidecar 通过。

## P3：Node 22/QMD worker 与 MCP

交付：

- QMD 在独立、随应用交付的 Node 22 worker 中运行；
- worker 不能获得 renderer 权限或任意命令入口；
- MCP 保持 Context7 兼容工具名、输入和结果语义；
- Codex 在任务前 preflight 为默认，Cursor 只可在该阶段替代。
- packaged Applications 可通过 Main-owned 固定 argv、安全 discovery 与用户确认接入
  Codex MCP；真实签名 CLI 的物理门禁未运行。

G3：

- `VAL-QMD-001` 在无系统 Node/QMD 环境完成索引与查询生命周期；
- `VAL-MCP-001` 兼容契约回放通过；
- `VAL-MCP-ONBOARD-001` 的 source 合同通过，真实官方签名 Codex packaged gate
  保持 `not-run`；
- `VAL-CLI-001` 证明任务开始后不发生 Codex → Cursor fallback。

## P4：Desktop 运行时路径、备份与模型

交付：

- 持久数据、缓存、日志和临时 runtime 各自进入标准 macOS 路径；
- 模型权重仅按需下载，校验后原子激活；
- Desktop 数据具备有版本的 backup、restore、integrity、atomic switch 和 rollback；
- unknown/legacy layout 明确 fail closed，不尝试猜测、导入或转换。

G4：

- `VAL-DATA-001` 覆盖 Desktop fresh、backup、restore、interrupt、corrupt、low-disk 和 rollback；
- `VAL-MODEL-001` 覆盖 consent、离线、完整性失败与断点恢复；
- 用户旧 Docker data/volume/backup 不被 Electron 自动读取、转换或删除。

## P5：DMG 发行基础

P5 只指 W14–W16 的正式发行路径，不包含 W02/W03 engineering artifacts。最小 smoke 与完整
工程测试包必须使用独立 non-release mode，不读取 production secret/pin、不由 tag 触发、
不上传或创建 Draft/Release，updater unavailable/no-network。

交付：

- 默认用户产物是 macOS arm64 DMG；
- 应用及 sidecar 使用明确的自签名身份，发布记录披露未 notarize、未启用
  hardened runtime；
- release workflow 使用的唯一 private credential 只在 tag-only `macos-signing`
  Environment 中可用；
- `macos-release` 只允许 branch `main` 的 promotion，且不配置 Environment/repository
  release secret 或长期签名凭据；job 仍使用短期 `GITHUB_TOKEN`。两 Environment 都要求
  独立 reviewer、prevent self review、UI 禁 admin bypass；
- PR、fork 与普通构建不接触发布秘密。
- canonical release/update manifest、完整资产集合和独立 Ed25519 信任锚在打包前
  fail closed。
- W13 checkpoint 到 formal tag 的 diff 只允许 production public pins、release metadata/version；
  formal tag 重跑 source/absence，exact Draft digest 重跑完整 cutover/absence，形成
  `VAL-RELEASE-CONTINUITY-001`。
- 当前 source foundation 的 desktop tag path 只创建候选 Draft；`container-images.yml` 仍会让
  相同 tag 的 GHCR workflow 独立运行且非原子。W11 必须先删除该耦合；W14 前不得真实 push
  release tag。未来 desktop 公开
  promotion 必须以 `workflow_dispatch --ref main` 运行，
  将 `release_tag` 只作为资料输入，由 trusted `main` verifier 在隔离 tag worktree 中
  fresh-peel、重新下载、绑定 candidate manifest digest；在 `PATCH` 前以 fresh
  `origin/main` comparison ref 验证 promotion order/`make_latest`，再以固定 Release ID REST
  `PATCH` 并执行 post-publish attestation/immutable/完整集合复核。
- active `protected-main`、owner-only `release-tag-creation`、no-bypass
  `immutable-release-tags` ruleset 与 GitHub Immutable Releases 是发布前置。

G5：

- `VAL-INSTALL-001` 在未安装 Docker/Homebrew/Python/Node/Git/ctags 的干净 Mac
  完成安装、启动与核心 smoke；
- `VAL-RELEASE-001` 记录 DMG 内容、签名身份、架构和限制；
- `VAL-SECRET-001` 证明真实 Environment/ruleset/Immutable Releases settings 精确匹配，
  且非发布工作流拿不到 Environment Secrets。
- `VAL-LEGACY-ABSENCE-001` 在首个受支持 Electron-only 公开 Release 前为 `pass`；container
  workflow、GHCR tag 耦合和 legacy runtime 不进入该 Release。
- `VAL-RELEASE-CONTINUITY-001` 绑定 W13 checkpoint、formal tag allowlisted diff 与 exact Draft
  cutover/absence；W13 engineering pass 不得直接复用为候选 pass。

当前 source 进度：release workflow、credential bootstrap、tag/provenance、trusted-main
verifier、隔离 tag worktree、fresh peel、固定 Release ID 和 Draft/Published/immutable 远端复核
合同已实现；两阶段 policy 已通过 `VAL-RELEASE-POLICY-001`/
`VAL-RELEASE-PROMOTION-001` source 复验。published 预状态按安全事件拒绝，不提供幂等洗绿。
public trust locks 仍为 `unprovisioned`，真实 GitHub settings、protected build、真实签名 DMG、
promotion 与 Gatekeeper 均为 `not-run`。

repository owner、contents writer/可改 workflow 的主体和 settings admin 仍是根信任；GitHub
Draft 无资产 CAS，verify→fixed-ID PATCH 竞态只能在公开后检测。即使这些 P5 source contract
已经实现，也不能覆盖 PR #20 的 W01 remediation 门禁；当前总结为
**PR merge blocked / release NO-GO**。

## P6：真实 `N-1 → N` 更新实机门禁

交付：

- 物理 Apple Silicon Mac 上的版本跨越报告；
- 独立签名 update check/download 和用户确认后的 verified DMG open；signed 路径不可用时，
  仅由用户显式打开固定 canonical Release 页面；
- 物理门禁通过后才设计或启用自动更新成功路径；
- 两条路径均保留用户数据且不静默执行安装器。

G6：

- `VAL-UPDATE-001` 在实机完成安装真实上一版本 `N-1`、创建数据、更新至真实下一版本
  `N`、重启、
  校验版本/sidecar/数据；
- 同一报告注入自动更新失败，验证 DMG fallback；
- G6 通过前，不把自动应用更新列为可交付能力。

当前 source 进度：Main/preload/Web 的签名 manifest、redirect、私有 cache、脱敏 IPC、
verified DMG open 与固定 Release 页面 no-payload/URL 隐藏/状态保持合同已通过
`VAL-UPDATE-CLIENT-001`。真实 feed、下载、打开和 `N-1 → N` 物理门禁仍为 `not-run`。

ADR-0003/0011 中描述的真实 `N-1 → N` 是版本关系而非固定版本号。执行门禁必须使用与
`runtime/version.json`、tag 和 manifest 完全一致的两个真实单调版本；不能为了匹配示例伪造
旧 tag。Automatic apply 还需要新增或 supersede ADR-0011。

## P7：Electron-only cutover 与 legacy retirement

交付：

- W02 先建立最小 packaged smoke；
- W10/W11 按 decouple、transport、provider、deploy、release、docs 独立 slice，分别在 exact
  before/after package 上证明 affected replacement 或受限 pure-legacy unsupported disposition、
  absence、protected presence 与无数据副作用；
- W03 从 cleaned tree 构建完整 engineering package；
- W04–W12 在该包上完成数据、模型、runtime、QMD、CLI、MCP、本地仓库和工程物理矩阵；
- W13 从 final commit 重建 package，在同一 digest 上运行 final cutover 与永久 absence gate。

G7：

- `VAL-PACKAGED-SMOKE-001` 和六个 slice gate 分别有 commit/digest-bound `pass`；
- `VAL-ENGINEERING-PACKAGE-001` 从 cleaned tree 为 `pass`；
- `VAL-ELECTRON-CUTOVER-001` 在 final cleaned commit 的 clean M4 rebuilt package 通过；
- `VAL-LEGACY-ABSENCE-001` 在同一 digest 证明 forbidden paths/listeners/imports/workflows/active docs 不存在，
  protected renderer/sidecar/companion/QMD/release paths 仍存在并通过回归；
- 不要求 legacy migration、compatibility window、旧 API/config/data support、
  `VAL-LEGACY-001` 或 `VAL-LEGACY-CONTROL-001`；这些旧门禁保持 `not-run (superseded)`；
- 删除源码不自动删除用户 data、volume、backup、container、image 或外部 GHCR package。

只有 G7 完成才解锁 W14 production control plane；G7 本身不配置 GitHub、不 provision credentials，
也不创建 formal candidate 或 Release。

## 阻断规则

- 任一必需门禁为 `fail` 或 `not-run`，对应阶段不能标记 `validated`/`done`。
- 签名 CI 成功不能替代干净 Mac 安装；模拟更新不能替代实机 `N-1 → N`。
- Electron 替代成功不能由“新应用能启动”推断，必须逐项验证任务、页面、引用、查询、
  embedding、provider、MCP、当前数据恢复和无 public listener。
- 后续阶段如需改变已接受 ADR，先新增 superseding ADR，再调整路线图。

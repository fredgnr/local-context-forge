# 项目 TODO 与交接任务清单

本页是剩余工作的权威 roll-up。各迭代保留范围、历史和详细证据，本页负责告诉下一位执行者：
做什么、为什么、由哪个组件负责、依赖什么、交付什么，以及怎样才算完成。

当前状态见[状态快照](status.md)，架构见[系统设计](../17-system-design.md)，工作方法见
[开发者手册](contributor-handbook.md)。W01–W16 的权威 execution rank 见
[Pre-1.0 work plan](work-plan.md)；W 号是稳定 ID，不是执行序号。

## 1. 使用规则

- 状态只使用 `planned`、`in-progress`、`blocked`、`validated`、`done`、`superseded`。
- `superseded` 只用于被后续 Accepted ADR 明确取代、不会继续实施的历史任务；对应验证保持
  `not-run`，不得写成 `pass` 或 `done`。
- 验证只使用 `pass`、`fail`、`not-run`。
- Owner 先用 owning component，不凭空指派个人。
- 开始任务时在 PR/issue 声明 task ID、owner、branch 和 scope，避免重复执行。
- 完成 source 实现不等于完成 packaged/physical gate。
- 改变已接受的架构、安全、数据、打包或发布决定时先新增 superseding ADR。
- 每个任务完成时同步活动 iteration、traceability、status 和本页。

## 2. 总体依赖

```text
W01 governance/source baseline
  → W02 minimal packaged smoke
  → W10/W11 independent legacy slices
  → W03 cleaned-tree engineering test package
  → W04–W12 data/model/runtime/CLI/MCP/local/physical matrix
  → W13 final cleaned engineering checkpoint：cutover + aggregate absence
  → W14 GitHub production controls
  → W15 production credentials/trust pins + formal RC + unique Draft
  → W16 physical review + promotion + public Release + real N-1 → N
```

W02/W03 只允许明确 non-release 的 engineering artifact。GitHub settings、正式 credentials、
production trust pins、tag、Draft、promotion 和公开 Release 都不得在 W13 前提前实施。

## 3. 优先级总览

`Priority-*` 是执行紧急度；`Roadmap` 才是 [roadmap](roadmap.md) 的 P0–P7 产品阶段。两者
不是同一命名空间。

| Task ID | 优先级 | Roadmap | 状态 | Owner component | 主要依赖 | 验收 |
| --- | --- | --- | --- | --- | --- | --- |
| TODO-PRE1-SEQUENCING-001 | Priority-0 | W01 | `in-progress` | Governance/Architecture | 无 | `VAL-PRE1-SEQUENCE-001` final head |
| TODO-GOV-EVIDENCE-001 | Priority-0 | W01/P0 | `planned` | Governance/CI | 无 | `VAL-GOV-001` final head |
| TODO-CI-COVERAGE-001 | Priority-0 | W01/P0 | `planned` | CI/QMD/Sites | 无 | `VAL-CI-COVERAGE-001` |
| TODO-PACKAGED-SMOKE-001 | Priority-0 | W02 | `planned` | Desktop/Packaging/QA | W01 全部退出门禁 | `VAL-PACKAGED-SMOKE-001` |
| TODO-LEGACY-CONTROL-001 | — | historical | `superseded` | Legacy Operations/Installer | ADR-0015 | `not-run` |
| TODO-DATA-LAYOUT-001 | Priority-1 | W04/P4 | `planned` | Desktop runtime/Data | engineering package | `VAL-DATA-001` foundation |
| TODO-DATA-BACKUP-001 | Priority-1 | W04/P4 | `planned` | Desktop/Data/Operations | layout | backup/restore physical pass |
| TODO-DATA-MIGRATION-001 | — | historical | `superseded` | Backend/Desktop migration | ADR-0015 | `not-run` |
| TODO-MODEL-SUPPLY-001 | Priority-1 | W05/P4 | `planned` | QMD/Model/Release | layout | `VAL-MODEL-001` |
| TODO-REL-GOV-001 | Priority-3 | W14/P5 | `blocked` | Release governance | W13 + GitHub admin | `VAL-SECRET-001` settings |
| TODO-REL-KEYS-001 | Priority-3 | W15/P5 | `blocked` | Release admin/Security | W14 | provisioned public pins |
| TODO-PACK-ENGINEERING-001 | Priority-1 | W03 | `planned` | Desktop/Packaging/QA | W10/W11 | `VAL-ENGINEERING-PACKAGE-001` |
| TODO-PACK-ARM64-001 | Priority-3 | W15/P5 | `planned` | Packaging/Python/QMD | W13/W14、data contracts、keys | `VAL-RELEASE-CONTINUITY-001`、`VAL-PACK-001` |
| TODO-PHYS-TRUST-001 | Priority-1 | W06/P1 | `planned` | Desktop Security/QA | W03 engineering package | `VAL-TRUST-001` |
| TODO-PHYS-PY-001 | Priority-1 | W06/P2 | `planned` | Python/Desktop QA | W03 engineering package | `VAL-PY/GIT/IPC-001` |
| TODO-PHYS-QMD-001 | Priority-1 | W07/P3/P4 | `planned` | QMD/Retrieval QA | W03、model | QMD/model gates |
| TODO-PHYS-CLI-001 | Priority-1 | W08/P3 | `planned` | Provider/QA | W03、real CLIs | `VAL-CLI-001` |
| TODO-PHYS-MCP-001 | Priority-1 | W09/P3 | `planned` | MCP/QA | W03、Codex | MCP gates |
| TODO-PHYS-LOCAL-001 | Priority-1 | W12/P1/P4 | `planned` | Local source/QA | W03 | `VAL-LOCAL-SOURCE-003` |
| TODO-ELECTRON-CUTOVER-001 | Priority-1 | W13/P7 | `planned` | Desktop/Product/QA | W04–W12 final package | `VAL-ELECTRON-CUTOVER-001` |
| TODO-LEGACY-DECOUPLE-001 | Priority-0 | W10/P7 | `planned` | Desktop/Backend/Web | W02 + slice source gate | `VAL-LEGACY-DECOUPLE-001` |
| TODO-REL-DRAFT-001 | Priority-3 | W15/P5 | `blocked` | Release engineering | W13/W14、keys、formal staging、continuity tag subgate | unique verified Draft |
| TODO-REL-PROMOTE-001 | Priority-3 | W16/P5 | `blocked` | Release reviewer/Security | exact Draft cutover/absence + continuity + physical pass | public immutable Release |
| TODO-UPDATE-NMINUS1-001 | Priority-3 | W16/P6 | `blocked` | Update/Data QA | two real releases | `VAL-UPDATE-001` |
| TODO-UPDATE-APPLY-001 | Priority-2 | P6 | `planned` | Architecture/Update | superseding ADR | `VAL-UPDATE-APPLY-001` |
| TODO-OPS-DIAGNOSTICS-001 | Priority-2 | W12/P4 | `planned` | Desktop Operations | data/log layout | `VAL-DIAGNOSTICS-001` |
| TODO-RUNTIME-CANCEL-001 | Priority-2 | W06/P2/P3 | `planned` | Main/Backend lifecycle | W03 | `VAL-CANCEL-001` |
| TODO-MCP-PAIRING-001 | Priority-2 | W09/P3 | `planned` | MCP/Security | physical MCP | `VAL-MCP-PAIRING-001` |
| TODO-LOCAL-HARDEN-001 | Priority-2 | W12/P1/P4 | `planned` | Local source/Security | physical local source | `VAL-LOCAL-HARDEN-001` |
| TODO-QMD-COMPACT-001 | Priority-2 | W07/P3/P4 | `planned` | QMD/Data | real corpus fixtures | `VAL-QMD-COMPACT-001` |
| TODO-EVAL-CORPUS-001 | Priority-2 | W07/P3 | `planned` | Retrieval/Wiki QA | stable engineering package | `VAL-EVAL-001` |
| TODO-WIKI-INCREMENTAL-001 | Priority-3 | post-P3 | `planned` | Backend/Wiki | eval corpus | `VAL-WIKI-INCREMENTAL-001` |
| TODO-LEGACY-REMOVE-DEPLOY-001 | Priority-0 | W11/P7 | `planned` | Desktop/Build/Operations | W02 + decoupling | `VAL-LEGACY-DEPLOY-001` |
| TODO-LEGACY-REMOVE-TRANSPORT-001 | Priority-0 | W10/P7 | `planned` | Backend/Web/MCP | W02 + decoupling | `VAL-LEGACY-TRANSPORT-001` |
| TODO-LEGACY-REMOVE-PROVIDER-001 | Priority-0 | W10/P7 | `planned` | Desktop/Backend/Provider | W02 + decoupling | `VAL-LEGACY-PROVIDER-001` |
| TODO-LEGACY-REMOVE-RELEASE-001 | Priority-0 | W11/P7 | `planned` | CI/Release | W02 + deploy inventory | `VAL-LEGACY-RELEASE-001` |
| TODO-LEGACY-REMOVE-DOCS-001 | Priority-0 | W11/P7 | `planned` | Docs/Sites/Operations | prior slices | `VAL-LEGACY-DOCS-001` |
| TODO-LEGACY-ABSENCE-001 | Priority-1 | W13/P7 | `planned` | CI/Governance | W03–W12 | `VAL-LEGACY-ABSENCE-001` |
| TODO-LEGACY-EXIT-001 | — | historical | `superseded` | Migration/Product/Operations | ADR-0015 | `not-run` |
| TODO-REMOTE-WORKER-001 | Priority-3 | future | `planned` | Product/Architecture | desktop GA | `VAL-REMOTE-WORKER-DECISION-001` |

`blocked` 表示需要仓库管理员、真实 Release 或先行门禁；不是建议绕过。`superseded` 行是
可追溯 tombstone，不再进入执行队列。

## 4. W01/W02、数据与后置 release prerequisites

### TODO-PRE1-SEQUENCING-001：接受并机器化新的 Pre-1.0 顺序

- 状态：`in-progress`
- Owner：Governance/Architecture
- 关联：REQ-PRE1-SEQUENCING-001、ADR-0016、ITER-0002/R13
- 依赖：无

交付：ADR-0016、W01–W16 execution rank、更新后的 TODO/traceability/roadmap/status/iteration/
skills/runbook，以及接入 `ci-python` 的 `tools/check_pre1_work_plan.py` 和负向 unit fixtures。
本任务不删除 legacy、不实现 package、不改 GitHub settings、不生成凭据、不创建 Release。

验收：最终 PR head 的 links/version/plan/diff 与 CI 为 commit-bound `pass`，且所有 runtime、
packaged、physical、settings 和 release gate 保持真实的 `not-run`。

### TODO-PACKAGED-SMOKE-001：最小非发行 packaged smoke harness

- 状态：`planned`
- Owner：Desktop/Packaging/QA
- 关联：REQ-PACKAGED-SMOKE-001、ADR-0016、ITER-0008/I01
- 依赖：W01 的 `VAL-PRE1-SEQUENCE-001`、`VAL-GOV-001`、`VAL-CI-COVERAGE-001` 全部为 `pass`
<!-- pre1-w02-requires: VAL-PRE1-SEQUENCE-001,VAL-GOV-001,VAL-CI-COVERAGE-001 -->

交付独立 engineering-smoke packaging mode：绑定 exact commit/digest/arch/inventory，启动
packaged App，验证 renderer/preload handshake、Main → private UDS sidecar 的 health/一个领域
请求、正常退出、无 orphan、无 public INET listener，并以 PATH trap 证明 exercised path 不发现
系统 Python/Node/Git。

必须显著 `UNOFFICIAL` / `engineering-only` / `publishable=false`，不读取 production secret，
不要求 production trust pins，不生成 updater/release metadata，不由 tag 触发，不上传、不创建
Draft/Release；updater `unavailable` 且不联网。不得放宽 formal `beforePack` trust audit。

验收：`VAL-PACKAGED-SMOKE-001=pass`。它不证明 QMD/model、真实 CLI/MCP、backup、完整 SBOM、
正式签名、Gatekeeper、Release 或 update。

### TODO-PACK-ENGINEERING-001：清理后的完整工程测试包

- 状态：`planned`
- Owner：Desktop/Packaging/QA
- 关联：REQ-ENGINEERING-PACKAGE-001、ADR-0016、ITER-0008/I08
- 依赖：W10/W11 全部 slice gate `pass`

从 cleaned tree 生成完整 non-release engineering package，包含 audited renderer、bundled
Python、QMD worker、MCP companion、工程 inventory/digest/SBOM/notices 和 W04–W12 测试入口。
它继承 W02 的 production-secret/tag/upload/Draft/Release 禁令，updater 保持 unavailable。

验收：`VAL-ENGINEERING-PACKAGE-001=pass`；不得提升 `VAL-PACK/INSTALL/RELEASE/SECRET-001`。

### TODO-GOV-EVIDENCE-001：统一可复现证据坐标

- 状态：`planned`
- Owner：Governance/CI
- 目的：移除“当前工作树 pass”和混合历史 SHA，让每个 source 结论能追到公开 commit/Actions。
- 依赖：无

交付：

- 为 `main@fb8bbbc` 或后续统一 checkpoint 收集 Python/Web/Desktop/QMD/Host Runner 的
  Actions/本地 commit-bound 结果；
- 保留 skip 数和最低环境；
- 将 `traceability.md` 的“本次变更映射”改为带 PR/commit/date 的历史 ledger；
- 迭代中不再使用无法复现的“当前工作树”；
- 在 `docs/development/evidence/` 下按规范留存脱敏记录。

验收：

- 每个 `pass` 有 commit、环境、命令、结果和 evidence URL/path；
- dirty worktree 不作为证据；
- source 与 packaged/physical 分类清楚；
- `VAL-GOV-001` link check 通过。

### TODO-CI-COVERAGE-001：补齐并声明 source aggregate 覆盖

- 状态：`planned`
- Owner：CI/QMD/Sites
- 目的：`make ci-source` 当前遗漏 QMD worker，主 workflow 也不验证 guide-site。
- 依赖：无

交付：

- 决定 QMD worker tests 是否并入 `make ci-source` 和 Desktop source workflow；
- 决定 guide-site 是否作为主 CI 的独立 job，或明确为独立部署 pipeline；
- 输出机器可读的 component coverage；
- 更新 Makefile help、developer handbook 和 CI docs；
- 控制总耗时，避免隐式模型下载/native build。

验收：

- aggregate 名称与实际覆盖一致；
- QMD tests 在无模型网络下载条件下运行；
- guide-site 未并入时在状态页明确；
- CI 在最终 PR head 成功；
- `VAL-CI-COVERAGE-001` 为 `pass`。

### TODO-LEGACY-CONTROL-001：Legacy 实例控制与外置数据

- 状态：`superseded`
- 优先级：不再排期
- Roadmap：历史任务
- Owner：Legacy Operations/Installer
- 关联：REQ-LEGACY-001、REQ-DATA-001、ADR-0004；由 ADR-0015 取代
- Disposition：不再实施；只允许在实际删除前修复立即可触发的数据丢失或高危安全问题

原任务曾计划加固 `scripts/lcf`、installer、Compose instance identity 和 legacy backup/restore。
这会扩大即将删除的维护面，与 Electron-only 决策冲突。`VAL-LEGACY-CONTROL-001` 保持
`not-run (superseded)`；不得为了关闭任务伪造通过。对应删除范围转入
`TODO-LEGACY-REMOVE-DEPLOY-001`。

### TODO-DATA-LAYOUT-001：冻结实际 Desktop 数据布局

- 状态：`planned`
- Owner：Desktop runtime/Data
- 关联：REQ-DATA-001、ADR-0004、ITER-0003/D01
- 目的：消除 ADR 目标布局与当前 Application Support 根目录布局的差异。
- 依赖：ITER-0002 持久格式/version 已冻结到可建立新 desktop-only baseline 的程度

当前差距：

- 当前有 `metadata.sqlite3`、`sources/`、`facts/`、`proposals/`、`wiki/`、`jobs/`、
  `locks/`、`runner/`、`qmd/`、`updates/`；
- 目标为更清晰的 state/libraries/wiki/indexes/backups 分层；不建立 legacy migration area；
- 未配置独立 `~/Library/Logs/Local Context Forge/`；
- update DMG 位于持久数据根；
- 没有路径 layout version。

交付：

1. inventory 当前所有文件/目录和 producer/consumer；
2. 定义不可替代、可重建、临时、日志、凭据五类；
3. 决定保留当前布局还是切换到新的 desktop-only 分层；旧 alpha layout 不提供 converter；
4. 增加 layout/schema version 和启动 preflight；
5. update download 移到可重建 cache 或从 backup manifest 排除；
6. 实现 Logs 路径、rotation/retention/redaction；
7. 对 owner/mode/symlink/volume/low-disk 做验证；
8. 明确 uninstall 和 cache reset 语义。

验收：

- fresh/current layout 可判定且 unknown/legacy layout fail closed；
- renderer/日志不暴露绝对私有路径；
- update/cache 不进入不可替代 backup；
- 重启和中断不留下半切换 active；
- 更新系统设计、部署手册、数据模型和 traceability。

### TODO-DATA-BACKUP-001：Desktop backup/restore

- 状态：`planned`
- Owner：Desktop/Data/Operations
- 关联：REQ-DATA-001、ITER-0003/D02–D03
- 依赖：TODO-DATA-LAYOUT-001

交付：

- UI/CLI 中的 drain、writer stop、sidecar/QMD shutdown；
- canonical backup manifest：
  product version、schema/layout、counts、files、size、SHA-256；
- 私有 staging、atomic finalize、checksum sidecar；
- restore inventory、space preflight、SQLite integrity、Wiki Git、revision/profile validation；
- quarantine 当前 active、同卷 atomic switch、post-start smoke、rollback；
- encrypted/export storage guidance；
- backup/restore 不包含 CLI auth、credential、model cache、update DMG 或 runtime sockets。

测试矩阵：

- fresh、large、repeat、interrupt、corrupt、missing file、extra file；
- active writer、timeout、low disk、symlink/hardlink、wrong owner/mode；
- old/new schema、unknown version、partial archive；
- restore smoke 失败与 rollback；
- data/page/job/source-ref counts 前后一致。

验收：

- 物理 M4 上从真实数据 backup → destructive test copy → restore → query；
- 原数据和 quarantine 可恢复；
- `VAL-DATA-001` 对 backup/restore 子项为 `pass`；
- 证据不含 private source 或本地用户名/path。

### TODO-DATA-MIGRATION-001：Legacy → Desktop 可回滚迁移

- 状态：`superseded`
- Owner：Backend/Desktop migration
- 关联：REQ-DATA-001、REQ-LEGACY-001、ADR-0004、ITER-0003/D02–D03；由 ADR-0015 取代
- Disposition：不开发 legacy importer、converter、journal、compatibility shim 或回滚流程

Desktop 自身的数据布局、backup/restore、unknown-layout fail-closed 仍由
`TODO-DATA-LAYOUT-001` 与 `TODO-DATA-BACKUP-001` 交付；这两项不能随 legacy migration 一起
删除。旧 Docker data、volume、archive 或配置不会被读取、迁移，也不会被应用自动删除。
迁移子门禁保持 `not-run (superseded)`。

### TODO-MODEL-SUPPLY-001：完整模型供应链与原子 index

- 状态：`planned`
- Owner：QMD/Model/Release
- 关联：REQ-MODEL-001、ADR-0004、ADR-0010、ITER-0003/D04–D05
- 依赖：layout

当前已有：

- curated/custom family allowlist；
- 用户触发 rebuild；
- QMD download/GGUF basic validation；
- profile/revision CAS；
- stale/failed lexical fallback。

交付/仍需：

- curated model 的固定 publisher、license、size、SHA-256/signature manifest；
- custom model 的信任和责任边界；
- bounded resume、partial cleanup、ENOSPC；
- cache identity、eviction、tamper detection；
- shadow index staging + atomic swap；
- old index quarantine/rollback；
- UI 显示来源、大小、许可、空间和下载进度。

验收：

- consent、offline、resume、digest/signature mismatch、invalid GGUF、low disk；
- cancellation、publish race、model switch、cache eviction；
- 部分向量永不标为 ready；
- `VAL-MODEL-001` 为 `pass`。

### TODO-REL-GOV-001：配置 GitHub 生产控制面

- 状态：`blocked`
- Owner：Release governance/Security
- 关联：REQ-RELEASE-GOV-001、ADR-0014、ITER-0004/P02/P02a
- 依赖：W13 的 final cutover/absence 为 `pass`；canonical repository 管理员、至少一名独立
  reviewer、公开仓库支持的保护能力
- 阻塞：需要 canonical repository 管理员和独立 reviewer

本任务属于 W14。W13 前不得为了 W02/W03 工程包提前修改任何 GitHub setting。

交付：

- `macos-signing`：required reviewer、prevent self review、admin bypass disabled、
  exact tag `v*.*.*`、最终唯一 release credential；
- `macos-release`：required reviewer、prevent self review、admin bypass disabled、
  exact branch `main`、不配置 Environment/repository release secret 或长期签名凭据；
- exact `protected-main`；
- owner-only `release-tag-creation`；
- no-bypass `immutable-release-tags`；
- GitHub Immutable Releases；
- fork/PR/source job 不能读取配置的 Environment/repository release secret 或长期签名凭据。

注意：

- bootstrap 当前验证 exact rule type/include/exclude/bypass；额外 status-check rule 也可能被
  拒绝，需先修改并评审 policy；
- “唯一 release credential”只指为 desktop release 配置的长期 private credential，不声称
  组织无其他无关 secret；
- Draft、promotion、fork/PR/source workflow job 仍可按最小 `permissions` 使用 GitHub 为本次
  run 签发的短期 `GITHUB_TOKEN`；它不是配置的 Environment/repository release secret，也不
  携带长期签名材料。

验收：

- 脱敏 API JSON + UI admin-bypass 截图；
- 时间、管理员和独立 reviewer；
- bootstrap read/verify 通过；
- 未输出 secret value；
- `VAL-SECRET-001` 的 settings 子项为 `pass`。

### TODO-REL-KEYS-001：生成凭据并提交 public trust pins

- 状态：`blocked`
- Owner：Release admin/Security
- 关联：REQ-SECRET-001、REQ-UPDATE-001
- 依赖：TODO-REL-GOV-001（W14）完整通过；本任务属于 W15

执行：

```bash
python3 tools/bootstrap_desktop_release_keys.py \
  --repo fredgnr/local-context-forge \
  --upload \
  --confirm-admin-bypass-disabled
```

只提交：

- `desktop/resources/update/update-metadata-ed25519-public.pem`
- `runtime/update-metadata-key.lock.json`
- `runtime/macos-codesign-certificate.lock.json`

验收：

- locks `provisioned`；
- 同一 32-hex generation；
- public key/certificate digest、identity 相符；
- `macos-signing` secret membership 精确；
- 无 `.p12`、private key、password、bundle、keychain/export；
- rotation/revocation 说明可执行。

## 5. Engineering physical 与后置 formal packaging

### TODO-PACK-ARM64-001：正式 runtime staging 与候选打包

- 状态：`planned`
- Owner：Packaging/Python/QMD
- 关联：REQ-PACK-001、REQ-RELEASE-002、ADR-0016、ITER-0002/R02–R06、ITER-0004/P01/P03
- 依赖：W13/W14、数据合同冻结、production trust pins provisioned；属于 W15

本任务只生成正式候选，不得用来实现 W02/W03。`VAL-PACK-001` 继续要求 production trust、
protected workflow 和 formal asset set。W13 checkpoint 到 formal tag 的 diff 必须只包含经审核
allowlist 的 production public trust pins、release metadata 与版本变更；任何 runtime logic 或
legacy surface 变化都使候选 fail closed，并要求回到 W13 重跑工程门禁。

交付：

- CPython 3.13.14 双重 source digest；
- PyInstaller onedir、hash lock、module/resource audit；
- Node 22.23.2/QMD 2.5.3、better-sqlite3 arm64 source rebuild；
- renderer/companion staging；
- manifest/schema/version/source commit；
- 调用 W13 前已冻结的 machine-checkable checkpoint → tag allowlisted source-diff verifier，以及
  formal tag source/aggregate absence 入口；不得在 W13 后首次新增 verifier；
- exact inventory、normalized digest、SBOM、notices；
- Mach-O architecture、dylib/RPATH；
- nested signing order、临时 keychain 清理；
- `beforePack` tamper rejection；
- DMG/ZIP/blockmap/update/release manifest 资产集合。

验收：

- `macos-15` protected build 成功；
- formal tag 已重跑 source/aggregate absence，`VAL-RELEASE-CONTINUITY-001` tag/diff subgate 为
  `pass`；
- artifact 与 Draft bytes 一致；
- 失败 PATH 下 packaged smoke 不发现系统 runtime；
- `VAL-PACK-001`、`VAL-RELEASE-001` 的构建子项为 `pass`。

### TODO-PHYS-TRUST-001：Packaged renderer/Main 信任审计

- 状态：`planned`
- Owner：Desktop Security/QA
- 依赖：W03 engineering test package；正式候选在 W15 另行复核

验证：

- sandbox/context isolation/nodeIntegration/CSP；
- navigation/window/webview/download/permission；
- negative IPC payload、sender、route、size、response；
- renderer 无 path/argv/PID/stderr/socket/token/key/signature/URL；
- packaged renderer/resource identity 与 TOCTOU 观察；
- shutdown/relaunch/single-instance。

验收：`VAL-TRUST-001 pass`，包含物理 App 和脱敏证据。

### TODO-PHYS-PY-001：Bundled Python、Dulwich 与 UDS

- 状态：`planned`
- Owner：Python/Desktop QA
- 依赖：W03 engineering test package；正式候选在 W15 另行复核

验证：

- clean user 无 Docker/Homebrew/Python/Node/Git/ctags；
- UDS owner/mode/symlink/stale/long path/token/version/role；
- ingest、publish、lint、rollback；
- Dulwich local/remote/ref/tag、恶意 config、submodule/LFS/collision；
- child crash/restart/graceful shutdown；
- `PATH` trap 和 C Git 只读 interoperability fixture。

验收：`VAL-PY-001`、`VAL-GIT-001`、`VAL-IPC-001 pass`。

### TODO-PHYS-QMD-001：Native QMD 与真实 embedding

- 状态：`planned`
- Owner：QMD/Retrieval QA
- 依赖：W03 engineering test package、TODO-MODEL-SUPPLY-001

验证：

- bundled Node/better-sqlite3 arm64；
- reconcile/search/revision/allowlist/256 limit；
- crash/restart/search single retry/reconcile no replay；
- first download、cache hit、offline、ENOSPC、interrupt、tamper；
- forced rebuild、hybrid/profile switch、cancel/publish race；
- deterministic lexical fallback；
- native/model path/redaction。

验收：

- `VAL-QMD-001`
- `VAL-QMD-EMBED-001`
- `VAL-IPC-EMBED-001`
- `VAL-MODEL-EMBED-001`

均在最低真实环境为 `pass`。

### TODO-PHYS-CLI-001：真实 Codex/Cursor attempt

- 状态：`planned`
- Owner：Provider/QA
- 关联：REQ-CLI-001、ADR-0005、ITER-0002/R05
- 依赖：W03 engineering test package、真实 CLI 登录

产物与验证矩阵：

- Codex 默认 success；
- Codex 未安装/未登录 + 无 Cursor consent；
- Codex 未安装/未登录 + consent + Cursor success；
- identity/layout/signature drift；
- create/claim/select/commit/spawn/complete cut-point；
- timeout/cancel/crash/output oversize；
- commit 后 uncertain、不 replay、不 fallback；
- auth/argv/env/stderr/path redaction。

验收：`VAL-CLI-001 pass`。

### TODO-PHYS-MCP-001：Packaged companion 与 onboarding

- 状态：`planned`
- Owner：MCP/QA
- 依赖：W03 engineering test package 的 `/Applications` 安装、真实官方签名 Codex；formal
  candidate 在 W15 另行复核

验证：

- configure/status/clear/reconnect；
- Codex restart 后两个工具；
- App 未运行、未授权、撤销、stale、oversize、timeout；
- app move → unavailable → 放回 `/Applications` → reconnect；
- ownership ledger/marker/command/arg exactness；
- source/debug 不写持久 target；
- Cursor 手工配置边界；
- stdout 只有 MCP framing。

验收：`VAL-MCP-001`、`VAL-MCP-ONBOARD-001 pass`。

### TODO-PHYS-LOCAL-001：本地与外置卷仓库

- 状态：`planned`
- Owner：Local source/QA
- 依赖：W03 engineering test package

验证：

- home 子目录；
- `/Volumes/<name>/...`；
- 私有 pre-cloned Git repo；
- cancel/expired/replay/new grant；
- move/delete/re-own/inode drift；
- app restart 后已登记路径；
- sensitive root/data/cache/mount/symlink 拒绝；
- UI/API/MCP/evidence 不泄露绝对路径；
- 同 UID TOCTOU 观察。

验收：`VAL-LOCAL-SOURCE-003 pass`。

### TODO-REL-DRAFT-001：创建唯一、不可手工修改的 Draft

- 状态：`blocked`
- Owner：Release engineering
- 关联：REQ-RELEASE-001、REQ-RELEASE-002、REQ-SECRET-001、ADR-0014、ADR-0016
- 依赖：W13 checkpoint cutover/absence、W14 controls、keys/formal staging、目标版本同步，以及
  `VAL-RELEASE-CONTINUITY-001` tag/diff subgate `pass`

执行前：

- clean protected `main`；
- 记录 W13 checkpoint commit/package digest、formal tag commit，并证明二者之间只有 allowlisted
  production public pins/release metadata/version diff；
- runtime/package/QMD version 完全一致；
- 确认 container workflow/GHCR tag 耦合已删除，同一 `vX.Y.Z` 只进入 desktop candidate path；
- source/policy CI success；
- release notes 明示 self-signed/not notarized/not hardened/automatic apply disabled，以及 legacy
  no-migration/no-compatibility 边界。

验收：

- tag/commit/main ancestry；
- 第一次 Environment approval；
- 唯一 Draft、fixed Release ID；
- remote assets 与本地 manifest exact match；
- 无覆盖/追加/删除；
- workflow run、digests 和 reviewer 已记录。

### TODO-REL-PROMOTE-001：真机后 trusted-main 公开

- 状态：`blocked`
- Owner：Release reviewer/Security
- 关联：REQ-RELEASE-001、REQ-RELEASE-002、REQ-RELEASE-GOV-001、ADR-0014、ADR-0016
- 依赖：同一 Draft exact digest 上完整 `VAL-ELECTRON-CUTOVER-001`、
  `VAL-LEGACY-ABSENCE-001`、`VAL-RELEASE-CONTINUITY-001` 和所有 physical gate `pass`

执行：

```bash
gh workflow run desktop-release.yml \
  --repo fredgnr/local-context-forge \
  --ref main \
  -f release_tag="vX.Y.Z" \
  -f candidate_manifest_sha256="<digest>" \
  -f confirm_publish=true
```

验收：

- 第二次 Environment approval；
- verifier 来自 fresh exact `main`；
- tag detached worktree/fresh peel；
- fixed Release ID；
- exact Draft digest 的完整 cutover/absence 重新运行且
  `VAL-RELEASE-CONTINUITY-001=pass`，不得复用 W13 engineering evidence；
- PATCH 前 fresh `origin/main` promotion order；
- 唯一 mutation 为 `draft=false` PATCH；
- post-publish `gh release verify`、同一 ID、immutable、notes/assets；
- already-published/drift 演练 fail closed；
- `VAL-RELEASE-001`、`VAL-INSTALL-001`、`VAL-SECRET-001` 为 `pass`。

## 6. Priority-1/2：更新、运维和安全加固

### TODO-UPDATE-NMINUS1-001：真实跨版本更新

- 状态：`blocked`
- Owner：Update/Data QA
- 依赖：两个真实、单调、受保护 Release

早期 ADR 的 `0.0.1 → 0.0.2` 是示例。实际记录为 `N-1 → N`，两者 tag/version/manifest
必须真实一致。

当前可验证范围：

- signed check；
- download；
- cache/manifest/digest；
- 用户确认后打开 DMG；
- manual Release page 显式出口；
- 数据保留和手工替换。

验收：

- `N-1` 创建真实 library/job/page/model/MCP metadata；
- `N` check/download/open；
- network/signature/hash/cache/ENOSPC/cancel failure；
- sidecar stop、App replace/reopen、schema/data count；
- verified DMG fallback；
- 旧 App/backup rollback；
- `VAL-UPDATE-001 pass`，且不误称 automatic apply。

### TODO-UPDATE-APPLY-001：Automatic apply 决策与实现

- 状态：`planned`
- Owner：Architecture/Update
- 关联：REQ-UPDATE-001、ITER-0005/U05
- 依赖：TODO-UPDATE-NMINUS1-001 的手工/DMG路径成熟

交付：先新增或 supersede ADR-0011，并实现已接受范围，至少明确：

- apply mechanism；
- self-signed/Gatekeeper 可行性；
- process shutdown/restart；
- data/schema compatibility；
- partial replacement；
- rollback artifact；
- update feed/channel/monotonicity；
- automatic vs user confirmation；
- failure and recovery UX。

未有 Accepted ADR 和物理证据前不得启用。

验收：

- superseding ADR 已 Accepted，release notes/UI 与默认开关一致；
- partial replace、crash、权限、Gatekeeper、schema 不兼容和磁盘不足均有失败注入；
- `N-1 → N` 的 apply、restart、数据核对和 rollback 在物理 M4 通过；
- `VAL-UPDATE-APPLY-001` 为 `pass` 并已同步 traceability；旧 `VAL-UPDATE-001` 不被
  source mock 冒充。

### TODO-OPS-DIAGNOSTICS-001：Desktop doctor 与脱敏 support bundle

- 状态：`planned`
- Owner：Desktop Operations
- 依赖：data/log layout

交付：

- UI diagnostics：version/schema/runtime status、有限错误；
- export support bundle：manifest、redacted logs、health、counts、digests；
- 绝不包含 token/socket/capability/auth/private path/source/CLI stderr；
- QMD/model/sidecar/MCP/update/local-source 独立状态；
- rotation/retention；
- App 无法启动时的安全 recovery guide；
- MCP ownership cleanup 的受控工具。

验收：negative redaction、tamper、oversize、crash 和物理导出通过，
`VAL-DIAGNOSTICS-001` 为 `pass`。

### TODO-RUNTIME-CANCEL-001：硬取消与 child 退出确认

- 状态：`planned`
- Owner：Main/Backend lifecycle
- 关联：REQ-IPC-001、REQ-CLI-001、ITER-0002/R05
- 依赖：可控制真实 child 的 packaged fault-injection harness
- 目的：调用超时不等于同步 handler 已停止。

交付：

- 定义 request cancellation 到 Backend worker/CLI/QMD 的传播；
- child TERM/grace/KILL 后确认退出；
- 结果未知边界；
- App quit 时无 orphan；
- queue/provider/embedding 的 cut-point tests；
- bounded concurrency 与内存/FD pressure。

验收：packaged fault injection 通过，不能只靠 unit mock；`VAL-CANCEL-001` 为 `pass`。

### TODO-MCP-PAIRING-001：Durable MCP pairing

- 状态：`planned`
- Owner：MCP/Security
- 关联：REQ-MCP-001、REQ-MCP-ONBOARD-001、ADR-0008、ADR-0013
- 依赖：physical MCP gate

交付：新 ADR、协议/状态迁移和下列设计：

- Keychain；
- client code identity；
- revocation/expiry；
- app move/update；
- multiple clients；
- lost state/recovery；
- same-UID threat boundary。

当前每连接 UI 授权继续保留，直至新 ADR 和实现通过。

验收：

- lost/expired/revoked/duplicate/wrong-code-identity client 均 fail closed；
- app move/update/reinstall 与多个 client 的恢复/清理行为可解释、可撤销；
- Keychain/ledger 不泄露 capability，same-UID 非对抗假设在 UI/文档中明确；
- 物理 `/Applications` App + 真实 Codex 的 `VAL-MCP-PAIRING-001` 为 `pass`。

### TODO-LOCAL-HARDEN-001：本地仓库 TOCTOU 加固

- 状态：`planned`
- Owner：Local source/Security
- 关联：REQ-LOCAL-SOURCE-001、ADR-0012、ITER-0002/R10
- 依赖：physical local-source observations

交付：比较方案、记录 benchmark/threat model，并用新 ADR 选择：

- security-scoped bookmark；
- fd-based snapshot；
- isolation copy；
- App Sandbox；
- 当前 canonical path/dev/inode 双检。

验收：

- 大型 monorepo、外置盘、移动/重挂载、same-UID 替换和 UX 成本有可复现实测；
- 选择方案关闭或明确接受 validate→snapshot 的 TOCTOU；
- grant 单次/过期、path redaction 和 sensitive-root 拒绝不回归；
- `VAL-LOCAL-HARDEN-001` 在 physical local-source hardening 环境为 `pass`。

### TODO-QMD-COMPACT-001：QMD 旧文档物理清理

- 状态：`planned`
- Owner：QMD/Data
- 关联：REQ-QMD-001、ITER-0002/R07
- 依赖：真实 corpus fixtures 和 QMD API 能力

交付：

- 不影响 committed allowlist；
- 可取消、可恢复、空间预检；
- staging/backup；
- revision/profile 保持；
- 失败仍 lexical；
- 不直接运行未审计的 QMD 命令。

验收：

- 删除范围只包含不再被 committed allowlist 引用的旧文档/索引；
- cancel/crash/ENOSPC 后 active corpus、revision 和 lexical 查询仍一致；
- dry-run inventory、释放空间、rollback 和审计记录可复核；
- 真实 corpus 上 compact 前后 query/gate 通过，`VAL-QMD-COMPACT-001` 为 `pass`。

### TODO-EVAL-CORPUS-001：固定质量评测语料

- 状态：`planned`
- Owner：Retrieval/Wiki QA
- 依赖：稳定 packaged pipeline

交付：

- 可公开、固定 commit 的多语言代码库 fixture；
- API coverage、source-ref correctness、page usefulness、query hit；
- lexical vs hybrid 对比；
- embedding model/resource budgets；
- Codex-generated proposal 的人工 golden review；
- 不把模型主观输出当 deterministic unit assertion。

验收：质量回归阈值和 release evidence 已固定并可复现，`VAL-EVAL-001` 为 `pass`。

### TODO-WIKI-INCREMENTAL-001：增量生成

- 状态：`planned`
- Owner：Backend/Wiki
- 关联：需先新增增量生成 requirement 与 ADR，再写入 traceability
- 依赖：TODO-EVAL-CORPUS-001

交付：新 ADR、依赖图/重用格式、fallback 和测试实现，至少解决：

- old/new source SHA diff；
- page dependency graph；
- unchanged page reuse；
- removed/renamed symbol；
- proposal review continuity；
- provider input/token budget；
- partial failure；
- full rebuild fallback；
- source-ref and corpus revision invariants。

验收：

- 固定 old/new commit fixtures 覆盖新增、删除、重命名、跨文件依赖和无关改动；
- 未变页面字节/sidecar 可证明重用，改变页面只引用新 snapshot evidence；
- partial failure 不激活版本，full rebuild 能恢复；
- 与 full generation 的质量/引用/成本基线对比达到 Accepted ADR 阈值；
- `VAL-WIKI-INCREMENTAL-001` 为 `pass`。

## 7. Electron-only cutover、Legacy 删除与未来范围

本节受 [ADR-0015](../adr/0015-electron-only-legacy-retirement.md)、
[ADR-0016](../adr/0016-pre1-incremental-retirement-engineering-package.md) 和
[严格 removal manifest](legacy-retirement.md) 约束。项目允许在 W02 后按独立 slice 无兼容窗口
删除，但
**不允许用目录名判断归属**：`web/src/**` 是 Electron renderer，`backend/app/**` 包含 private
UDS sidecar 和领域层。任何实现 PR 必须先逐项声明 `remove`、`retain` 或 `split`，并引用本节
task ID。shared 或最终必需 Electron capability 必须先证明 replacement；纯 legacy-only 且由
REQ-PRE1-BREAKING-001 明确 unsupported 的 capability 可记录受限 `no-replacement / unsupported`，
但必须证明无 Electron caller、用户数据或外部副作用，且不得用于 protected path 或 formal
release safety。

### TODO-ELECTRON-CUTOVER-001：证明 Electron 已替代 legacy 能力

- 状态：`planned`
- 优先级：Priority-1
- Owner：Desktop/Product/QA
- 关联：REQ-ELECTRON-ONLY-001、ADR-0015、ADR-0016、ITER-0008/I09
- 依赖：W03 engineering package；W04–W12 的真实 embedding、Codex/Cursor、MCP、本地仓库和
  工程物理 gate

交付：

1. 用 source 与 packaged/physical 两层矩阵分别验证仓库创建/导入、索引、任务提交、排队、
   取消、重试、审核、发布和查询；
2. 验证 embedding 模型选择、状态、全局/单仓 rebuild 和 stale-index fallback；
3. 验证 Codex 默认、Cursor 仅 preflight fallback、attempt audit 和取消语义；
4. 验证 Context7 `resolve-library-id` / `query-docs`、Codex onboarding 和 stdio companion；
5. 从 final cleaned commit 重建 package，验证上述流程不调用 Docker、public TCP API、legacy
   `mcp/` 或 Host Runner spool；
6. 聚合每个已删除 slice 的 Electron owner、failure UX 和 absence evidence。
7. 在 W13 checkpoint 前冻结 future formal continuity verifier、source-diff allowlist 与 evidence
   schema；若以后修改它们，必须建立新 checkpoint 并重跑 W13。

验收：final rebuilt package 的 `VAL-ELECTRON-CUTOVER-001` 为 `pass`。source 或早期 W02 smoke
不能替代 clean M4 完整矩阵；该门禁也不替代 W14–W16 的正式发行或更新门禁。

### TODO-LEGACY-DECOUPLE-001：解耦共享 Renderer、Backend 与 provider

- 状态：`planned`
- 优先级：Priority-0
- Owner：Desktop/Backend/Web
- 关联：REQ-ELECTRON-ONLY-001、REQ-LEGACY-SLICE-001、ADR-0016、ITER-0008/I02
- 依赖：`VAL-PACKAGED-SMOKE-001=pass`；affected replacement source 子门禁

交付：

- renderer 只通过版本化 desktop bridge 调用；隔离 `fetch()`/`VITE_API_BASE` browser fallback，
  经 transport slice 前后门禁后删除；保留 `web/src/**`、Vite/TypeScript build 和 renderer
  staging/audit；
- Python app 只由 Main 以认证 private UDS 启动；先隔离 public TCP ASGI 入口和 CORS/browser
  分支，经 transport slice 前后门禁后删除；保留 FastAPI/uvicorn/h11、`backend/app/cli.py`、
  factory/domain/desktop routes；
- provider 只使用 Main-owned Codex/Cursor attempt；拆出 Host Runner spool、heartbeat、direct
  CLI/Ollama/browser-only provider 分支，由独立 provider slice 删除；
- Context7 MCP 只保留 `desktop/companion/**` 与 Main bridge；
- mixed tests 拆分后仍覆盖 queue/review/publish/query/Wiki/source-ref 和 cancellation。

验收：renderer 的 Electron path 测试证明不会调用网络 fetch；sidecar packaged path 不监听
TCP；Electron production path 不 import/call `mcp_server`/`host_runner`；legacy 分支仍在时由
caller inventory 证明隔离；Web/Desktop/Backend/QMD focused 和 aggregate 均通过；
`VAL-LEGACY-DECOUPLE-001=pass`。它不把 final cutover 提前标为 pass。

### TODO-LEGACY-REMOVE-DEPLOY-001：删除 Docker、Web 容器与旧安装/运维面

- 状态：`planned`
- 优先级：Priority-0
- Owner：Desktop/Build/Operations
- 关联：REQ-ELECTRON-ONLY-001、REQ-LEGACY-SLICE-001、ADR-0016、ITER-0008/I05
- 依赖：`VAL-PACKAGED-SMOKE-001=pass`；TODO-LEGACY-DECOUPLE-001 affected subgate

删除清单：

- `docker-compose.yml`、`docker/**`；
- `install.sh`、`install.command`；
- `mcp/**` gateway/tests/dependencies 由 transport task 唯一负责；`host_runner/**`、spool 与
  provider helper 由 provider task 唯一负责；
- `web/Dockerfile`、`web/nginx.conf`、`web/.dockerignore`；
- `backend/.dockerignore`、重复的 `backend/requirements*.txt`（保留 `pyproject.toml`/`uv.lock`）；
- `scripts/lcf`、legacy backup/restore/demo/reindex/smoke/native deployment scripts；
- `scripts/macos-bootstrap.sh` 的 legacy 内容；若仍需开发引导，改为 Electron-only bootstrap；
- legacy HTTP/MCP examples 和只服务上述路径的环境模板。

严格不做：不删除 `web/`、`backend/`、`desktop/companion/`、QMD worker；不停止或删除用户
container/image/volume/LaunchAgent；不删除 `data/`、imports、backup 或 Application Support；
不删除 GHCR 历史 package。最后两类外部清理需要独立管理员授权，且不属于本任务。
legacy backup/restore 与 shell diagnostics 可按受限 `no-replacement / unsupported` disposition
删除；W04 current-format Desktop backup 与 W12 Desktop diagnostics 仍是独立未来产品能力，删除
脚本绝不授权读取、迁移或清理任何既有 data/backup/log。

验收：exact before/after commit 各有 fresh package digest 和相同 smoke；清单路径不存在，
Electron clean checkout 仍可构建；Make targets 和 CI 不引用被删路径；protected paths 存在；
不产生用户数据副作用；`VAL-LEGACY-DEPLOY-001=pass`。

### TODO-LEGACY-REMOVE-TRANSPORT-001：删除公开 API、browser adapter 与兼容分支

- 状态：`planned`
- 优先级：Priority-0
- Owner：Backend/Web/MCP
- 关联：REQ-ELECTRON-ONLY-001、REQ-PRE1-BREAKING-001、REQ-LEGACY-SLICE-001、ADR-0016、
  ITER-0008/I03
- 依赖：`VAL-PACKAGED-SMOKE-001=pass`；TODO-LEGACY-DECOUPLE-001 affected subgate

“删除 API”只表示删除 host TCP listener、browser CORS、公开 REST/OpenAPI 部署和 HTTP MCP；
Electron Main ↔ Python sidecar 的认证 UDS HTTP 协议及领域 service 必须保留。“删除 Web”只
表示删除独立 browser/container 运行形态，React renderer 必须保留。

交付：删除 `backend/app/main.py`、public-mode factory/config 分支、
renderer HTTP adapter、Vite localhost proxy、legacy MCP/tests/dependencies；旧 schema/layout 直接
fail closed，不实现 converter 或 compatibility shim。

验收：exact before/after package 重跑 smoke；生产进程没有 8000/8001/8080 TCP bind、CORS 或
browser transport；只有 Main-owned private UDS sidecar 和 bundled stdio MCP companion；核心
Desktop API/queue/Wiki/MCP 与 protected-path 回归通过；`VAL-LEGACY-TRANSPORT-001=pass`。

### TODO-LEGACY-REMOVE-PROVIDER-001：删除 Host Runner 与 legacy provider helper

- 状态：`planned`
- 优先级：Priority-0
- Owner：Desktop/Backend/Provider
- 关联：REQ-ELECTRON-ONLY-001、REQ-LEGACY-SLICE-001、ADR-0016、ITER-0008/I04
- 依赖：`VAL-PACKAGED-SMOKE-001=pass`；TODO-LEGACY-DECOUPLE-001 affected subgate

交付：删除 `host_runner/**`、LaunchAgent/spool/heartbeat、legacy direct provider、Ollama、Windows
helper 和只服务这些路径的 config/env/tests/scripts；保留 Main-owned Codex/Cursor discovery、
preflight、attempt CAS、fixed argv、commit 后不 fallback/replay 与 cancellation 语义。

验收：exact before/after package 重跑 smoke；产品 path 不 import/call Host Runner/spool/direct
provider/Ollama/Windows helper；Main-owned provider focused/aggregate 与 protected-path tests 通过；
不停止/删除用户 LaunchAgent 或外部进程；`VAL-LEGACY-PROVIDER-001=pass`。

### TODO-LEGACY-REMOVE-RELEASE-001：删除 container CI、GHCR 与 tag 耦合

- 状态：`planned`
- 优先级：Priority-0
- Owner：CI/Release
- 关联：REQ-ELECTRON-ONLY-001、REQ-RELEASE-002、REQ-LEGACY-SLICE-001、ADR-0016、
  ITER-0008/I06
- 依赖：`VAL-PACKAGED-SMOKE-001=pass`；deploy inventory 已冻结

交付：删除 `.github/workflows/container-images.yml`、container Docker build/cache、GHCR SemVer
发布、container-only Make/CI targets，以及 desktop release 文档中的同-tag 非原子警告；保留
desktop Draft/promotion、签名、trust pins、Environment 和 update safety chain。已发布 GHCR
package 保留为 unsupported historical artifact，删除它需要另行、明确、不可逆管理员授权。

验收：exact before/after package 重跑 smoke；PR/main/tag 不构建或发布 container；release tag
只进入 desktop candidate path；CI 的 Python aggregate 不再安装 `mcp/` 或运行 Host Runner
测试；formal Desktop release policy 回归仍通过；不删除远端 GHCR package；
`VAL-LEGACY-RELEASE-001=pass`。

### TODO-LEGACY-REMOVE-DOCS-001：把活跃文档与 Sites 收敛到 Electron

- 状态：`planned`
- 优先级：Priority-0
- Owner：Docs/Sites/Operations
- 关联：REQ-ELECTRON-ONLY-001、REQ-LEGACY-SLICE-001、ADR-0016、ITER-0008/I07
- 依赖：deploy/transport/release removal 已完成；最终路径集合已冻结

交付：README、SECURITY、CONTRIBUTING、AGENTS、project skills、guide-site、quickstart、
architecture、API/MCP、operations、backup、GHCR、troubleshooting 和 component README 不再
给出可执行 legacy 命令或旧 migration gate。编号文档优先改写为 Electron 对应主题；
Accepted/Superseded ADR、iteration 和 evidence 保留历史事实并明确状态。同步公开 Sites 另列
部署证据，不以本任务文字假装已发布。

Sites 安全前置：先恢复并验证现有公开站点的 exact project identity/slug 与 lifecycle checkout；
当前仓库副本没有 `.openai/hosting.json`，因此不得猜 slug、创建第二个站点或把源码推到未知
项目。身份恢复前可盘点 `guide-site/**`，但不能宣称生产站已更新。身份确认后先把旧 Docker/
localhost/Host Runner 一键命令改成 Electron-only 内容并更新 tests，再按 Sites checkpoint /
deployment-status 流程留下公开部署证据。

验收：exact before/after package 重跑 smoke；活跃用户文档不存在 `docker compose`、
`./install.sh`、`scripts/lcf` 或 localhost HTTP 使用路径；Markdown links、guide-site
tests/build 与 protected history allowlist 通过；`VAL-LEGACY-DOCS-001=pass`。

### TODO-LEGACY-ABSENCE-001：永久防止 legacy 回流

- 状态：`planned`
- 优先级：Priority-1
- Owner：CI/Governance
- 关联：REQ-ELECTRON-ONLY-001、REQ-LEGACY-SLICE-001、ADR-0016、ITER-0008/I09
- 依赖：全部 legacy slice；W03 engineering package；W04–W12 physical matrix

交付机器门禁，检查 forbidden paths 缺失、protected paths 存在、workflow/Make/package 无旧
引用、产品代码无 legacy import/env/listener、活跃文档无旧命令、release tag 无 container path。
历史 ADR/evidence 通过固定 allowlist 保留，不能用全仓库“零字符串命中”误删历史。

验收：`VAL-LEGACY-ABSENCE-001` 在 final cleaned commit 为 `pass`；从该 exact commit 构建新的
engineering package，并在同一 digest 上重跑完整核心 packaged capability matrix（仓库/队列/审核/发布/
查询、Wiki、model switch/rebuild、Codex/Cursor、MCP、当前数据 backup/recovery、无 listener）。
只做启动 smoke 或复用删除前 candidate 证据均不合格。

### TODO-LEGACY-EXIT-001：历史 Legacy 去留决策

- 状态：`superseded`
- Owner：Migration/Product/Operations
- 关联：REQ-LEGACY-001、ADR-0004、ITER-0006；先由 ADR-0015/ITER-0007、再由
  ADR-0016/ITER-0008 取代执行顺序
- Disposition：不再实施 migration rehearsal、compatibility window 或 retention decision

原任务的 `VAL-LEGACY-001` 保持 `not-run (superseded)`。实际删除由上面的稳定任务拆分执行；
不能把新的 absence gate 冒充旧 migration gate 的 `pass`。

### TODO-REMOTE-WORKER-001：Windows/4060 Desktop worker 决策

- 状态：`planned`
- Owner：Product/Architecture
- 优先级：Priority-3
- 依赖：desktop GA、TODO-EVAL-CORPUS-001；若进入实现还依赖新的安全/协议 ADR
- 当前边界：Electron 明确不支持远程 Windows/Ollama worker；legacy 路径已弃用并计划删除，
  不能再作为 future worker 的实现依赖。

产物：先形成 threat/cost study 与明确的 accept/reject ADR：

- LAN authentication/TLS/device pairing；
- source/evidence 数据出境；
- task idempotency、cancel、uncertain；
- Windows service/install/update；
- model/API compatibility；
- offline and split-brain；
- 是否仍符合“本地 all-in-one 简单部署”。

没有新 ADR 前不得把 legacy Windows 操作复制进 desktop。

验收：

- ADR 明确数据是否离开 Mac、认证/传输、故障/更新成本和 all-in-one UX 影响；
- 若拒绝，status/guide/TODO 继续明确 Windows worker 不受支持；
- 若接受，另拆实现、协议、安全、Windows 安装/更新和物理矩阵任务，本任务本身不伪装成交付；
- 无论结论为何，用户都能从硬件/系统设计文档看到唯一一致边界；
- `VAL-REMOTE-WORKER-DECISION-001` 只验证决策与边界同步，不把 accept 决策冒充实现 `pass`。

## 8. 非任务：当前明确不支持

除非先有产品决策和 ADR，不要悄悄实现：

- Intel macOS、Windows/Linux desktop；
- Developer ID/notarization/hardened runtime 等价声明；
- desktop public localhost HTTP API；
- desktop Ollama provider；
- Cursor 自动 MCP onboarding；
- MCP 写操作或自动启动 App；
- packaged 产品发现系统 Git、ctags、Python、Node、QMD；
- renderer 自定义 executable、URL、path 或 update key；
- query expansion/reranker 模型。

## 9. 完成定义

任务只有同时满足以下条件才可 `done`：

- scope 与不做范围明确；
- 实现/配置已进入受保护 branch；
- focused 和 aggregate 通过；
- 最低真实环境 gate 有证据，或明确仍 `not-run` 因而任务不能 `done`；
- failure injection 和 rollback 已运行；
- 无 secret/private source/path 泄露；
- iteration、traceability、status、TODO、用户/组件文档已同步；
- PR review threads resolved，最终 head CI 通过；
- Release 能力没有越过 public release NO-GO。

## 10. 接手清单

新执行者开始前：

- [ ] 记录 exact `main` commit 和 branch；
- [ ] 阅读 AGENTS、active iteration、相关 ADR/skills；
- [ ] 从本页选择一个 task ID；
- [ ] 确认没有其他 owner 正在做同一 task；
- [ ] 写出依赖、最低环境、expected artifact；
- [ ] 跑 focused baseline；
- [ ] 建立 evidence 目录/模板；
- [ ] 变更实现和文档；
- [ ] 运行 focused + aggregate；
- [ ] 所有不能运行的 gate 保持 `not-run`；
- [ ] 创建 Draft PR，等待最终 head CI；
- [ ] 合并前以最终 PR head 同步 task/status/evidence，并确认最终 head CI；
- [ ] 只有需要记录 merge commit 坐标时才创建 follow-up；不要把一般“合并后更新”设为
  任务完成或合并的前置条件。

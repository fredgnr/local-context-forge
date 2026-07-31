# 项目 TODO 与交接任务清单

本页是剩余工作的权威 roll-up。各迭代保留范围、历史和详细证据，本页负责告诉下一位执行者：
做什么、为什么、由哪个组件负责、依赖什么、交付什么，以及怎样才算完成。

当前状态见[状态快照](status.md)，架构见[系统设计](../17-system-design.md)，工作方法见
[开发者手册](contributor-handbook.md)。

## 1. 使用规则

- 状态只使用 `planned`、`in-progress`、`blocked`、`validated`、`done`。
- 验证只使用 `pass`、`fail`、`not-run`。
- Owner 先用 owning component，不凭空指派个人。
- 开始任务时在 PR/issue 声明 task ID、owner、branch 和 scope，避免重复执行。
- 完成 source 实现不等于完成 packaged/physical gate。
- 改变已接受的架构、安全、数据、打包或发布决定时先新增 superseding ADR。
- 每个任务完成时同步活动 iteration、traceability、status 和本页。

## 2. 总体依赖

```text
Governance/evidence cleanup
        │
        ├─────────────── GitHub release controls ── trust pins
        │
        ▼
Desktop data layout ── backup/restore ── legacy migration fixtures
        │
        ├── model supply-chain completion
        │
        ▼
Formal arm64 staging ── packaged component matrix ── unique Draft
                                                    │
                                                    ▼
                                         clean M4 physical gate
                                                    │
                                                    ▼
                                         trusted-main promotion
                                                    │
                                                    ▼
                                        real N-1 → N update gate
                                                    │
                                                    ▼
                                          legacy exit decision
```

GitHub settings 可以与数据实现并行准备，但真实公开 Release 必须等待所有阻断门禁。

## 3. 优先级总览

`Priority-*` 是执行紧急度；`Roadmap` 才是 [roadmap](roadmap.md) 的 P0–P7 产品阶段。两者
不是同一命名空间。

| Task ID | 优先级 | Roadmap | 状态 | Owner component | 主要依赖 | 验收 |
| --- | --- | --- | --- | --- | --- | --- |
| TODO-GOV-EVIDENCE-001 | Priority-0 | P0 | `planned` | Governance/CI | 无 | commit-bound evidence |
| TODO-CI-COVERAGE-001 | Priority-0 | P0 | `planned` | CI/QMD/Sites | 无 | `VAL-CI-COVERAGE-001` |
| TODO-LEGACY-CONTROL-001 | Priority-0 | legacy/P7 support | `planned` | Legacy Operations/Installer | REQ-LEGACY-001、REQ-DATA-001 | `VAL-LEGACY-CONTROL-001` |
| TODO-DATA-LAYOUT-001 | Priority-0 | P4 | `planned` | Desktop runtime/Data | ADR-0004 | `VAL-DATA-001` foundation |
| TODO-DATA-BACKUP-001 | Priority-0 | P4 | `planned` | Desktop/Data/Operations | layout | backup/restore physical pass |
| TODO-DATA-MIGRATION-001 | Priority-0 | P4/P7 | `planned` | Backend/Desktop migration | layout、backup | `VAL-DATA-001` |
| TODO-MODEL-SUPPLY-001 | Priority-0 | P4 | `planned` | QMD/Model/Release | layout | `VAL-MODEL-001` |
| TODO-REL-GOV-001 | Priority-0 | P5 | `blocked` | Release governance | GitHub admin | `VAL-SECRET-001` settings |
| TODO-REL-KEYS-001 | Priority-0 | P5 | `blocked` | Release admin/Security | release controls | provisioned public pins |
| TODO-PACK-ARM64-001 | Priority-1 | P2/P3→P5 | `planned` | Packaging/Python/QMD | data contracts、keys | `VAL-PACK-001` |
| TODO-PHYS-TRUST-001 | Priority-1 | P1/P5 | `planned` | Desktop Security/QA | packaged candidate | `VAL-TRUST-001` |
| TODO-PHYS-PY-001 | Priority-1 | P2/P5 | `planned` | Python/Desktop QA | packaged candidate | `VAL-PY/GIT/IPC-001` |
| TODO-PHYS-QMD-001 | Priority-1 | P3/P4/P5 | `planned` | QMD/Retrieval QA | packaged candidate、model | QMD/model gates |
| TODO-PHYS-CLI-001 | Priority-1 | P3/P5 | `planned` | Provider/QA | packaged candidate、real CLIs | `VAL-CLI-001` |
| TODO-PHYS-MCP-001 | Priority-1 | P3/P5 | `planned` | MCP/QA | packaged candidate、Codex | MCP gates |
| TODO-PHYS-LOCAL-001 | Priority-1 | P1/P4/P5 | `planned` | Local source/QA | packaged candidate | `VAL-LOCAL-SOURCE-003` |
| TODO-REL-DRAFT-001 | Priority-1 | P5 | `blocked` | Release engineering | all Priority-0 release prerequisites | unique verified Draft |
| TODO-REL-PROMOTE-001 | Priority-1 | P5 | `blocked` | Release reviewer/Security | Draft physical pass | public immutable Release |
| TODO-UPDATE-NMINUS1-001 | Priority-1 | P6 | `blocked` | Update/Data QA | two real releases | `VAL-UPDATE-001` |
| TODO-UPDATE-APPLY-001 | Priority-2 | P6 | `planned` | Architecture/Update | superseding ADR | `VAL-UPDATE-APPLY-001` |
| TODO-OPS-DIAGNOSTICS-001 | Priority-2 | P4/P5 | `planned` | Desktop Operations | data/log layout | `VAL-DIAGNOSTICS-001` |
| TODO-RUNTIME-CANCEL-001 | Priority-2 | P2/P3 | `planned` | Main/Backend lifecycle | packaged harness | `VAL-CANCEL-001` |
| TODO-MCP-PAIRING-001 | Priority-2 | P3 | `planned` | MCP/Security | physical MCP | `VAL-MCP-PAIRING-001` |
| TODO-LOCAL-HARDEN-001 | Priority-2 | P1/P4 | `planned` | Local source/Security | physical local source | `VAL-LOCAL-HARDEN-001` |
| TODO-QMD-COMPACT-001 | Priority-2 | P3/P4 | `planned` | QMD/Data | real corpus fixtures | `VAL-QMD-COMPACT-001` |
| TODO-EVAL-CORPUS-001 | Priority-2 | P3/P5 | `planned` | Retrieval/Wiki QA | stable packaged stack | `VAL-EVAL-001` |
| TODO-WIKI-INCREMENTAL-001 | Priority-3 | post-P3 | `planned` | Backend/Wiki | eval corpus | `VAL-WIKI-INCREMENTAL-001` |
| TODO-LEGACY-EXIT-001 | Priority-3 | P7 | `blocked` | Migration/Product/Operations | roadmap P0–P6 pass | `VAL-LEGACY-001` + ADR |
| TODO-REMOTE-WORKER-001 | Priority-3 | future | `planned` | Product/Architecture | desktop GA | `VAL-REMOTE-WORKER-DECISION-001` |

`blocked` 表示需要仓库管理员、真实 Release 或先行门禁；不是建议绕过。

## 4. Priority-0：先消除证据、数据和发布阻塞

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

- 状态：`planned`
- 优先级：Priority-0
- Roadmap：legacy/P7 support
- Owner：Legacy Operations/Installer
- 关联：REQ-LEGACY-001、REQ-DATA-001、ADR-0004
- 依赖：legacy runtime manifest 和 backup/restore 格式保持可判定

当前问题：

- `scripts/lcf` 的 Compose 生命周期以及 `backup`/`restore` 子脚本会继承调用进程中的
  Compose 插值变量；shell 的 `LOCAL_DATA_DIR`、`LCF_BIND_HOST`、端口、镜像等可覆盖
  `--env-file`，`COMPOSE_PROJECT_NAME` 还可覆盖 compose 顶层 `name:`。污染环境可能把
  start/stop/down/backup/restore 指向错误 project、context、端口、数据根、监听地址、镜像或
  backup 位置；
- 受管安装器每次运行都会把 `data/`、`imports/` 和 `runner/` 强制设回当前 checkout，
  且没有受支持的外置 data 参数，重跑安装器可能创建或操作错误实例；
- 文档中的最小 `env -i` allowlist 是临时运维缓解，不是脚本的 fail-closed 控制面。

交付：

1. 修改 `scripts/lcf`、`scripts/backup.sh`、`scripts/restore.sh` 与 legacy installer，使实例
   选择只来自显式参数或经过校验的 `.lcf/runtime.env`，不直接信任调用者污染环境；
2. 为 installer 增加受支持、规范化且持久记录的外置 data/imports/runner 配置，重跑时保持
   已安装实例的 target，不静默改回 checkout；
3. 固定 Compose project identity，并为 custom Docker context、bind host、API/Web/MCP port、
   API URL、image、data/imports/runner root 和 backup root 定义优先级、canonicalization、
   owner/mode/symlink、冲突与缺失行为；
4. backup/restore manifest 绑定实例 identity、Docker context、resolved data root、API target
   与 archive digest；restore 在 target 或 manifest 不一致时 fail closed；
5. 增加隔离 Docker context/临时目录的 shell/integration tests，以及安装、升级、backup、
   restore、回滚和故障注入 fixtures；
6. 同步安装、部署、backup/restore、troubleshooting 和 security 文档，不再要求操作者靠
   `env -i` 包装才能安全选择实例。

验收：

- 在预置全部 Compose 插值变量、`COMPOSE_PROJECT_NAME`、错误 context/API/data/image 变量时，
  默认操作仍只使用目标实例 manifest，或因歧义明确拒绝；
- custom port/context/data/imports/runner/backup 配置在安装、重跑、升级、backup 和 restore
  后保持一致；
- 错误 checkout、错误 Docker context、错误 API、活动 writer、manifest 漂移、symlink、
  wrong owner/mode 和 archive target mismatch 均 fail closed；
- backup 与 restore 对同一 manifest target 的 identity、resolved paths、port/context 和
  digest 核对一致，不会跨实例 drain、覆盖或恢复；
- 脚本、测试与用户/运维文档同一变更交付，`VAL-LEGACY-CONTROL-001` 为 `pass`。

### TODO-DATA-LAYOUT-001：冻结实际 Desktop 数据布局

- 状态：`planned`
- Owner：Desktop runtime/Data
- 关联：REQ-DATA-001、ADR-0004、ITER-0003/D01
- 目的：消除 ADR 目标布局与当前 Application Support 根目录布局的差异。
- 依赖：ITER-0002 持久格式/version 已冻结到可迁移程度

当前差距：

- 当前有 `metadata.sqlite3`、`sources/`、`facts/`、`proposals/`、`wiki/`、`jobs/`、
  `locks/`、`runner/`、`qmd/`、`updates/`；
- ADR 目标为更清晰的 state/libraries/wiki/indexes/imports/backups/migration；
- 未配置独立 `~/Library/Logs/Local Context Forge/`；
- update DMG 位于持久数据根；
- 没有路径 layout version。

交付：

1. inventory 当前所有文件/目录和 producer/consumer；
2. 定义不可替代、可重建、临时、日志、凭据五类；
3. 决定保留当前布局还是迁移到 ADR 分层；若改变，新增 superseding ADR 或兼容修订；
4. 增加 layout/schema version 和启动 preflight；
5. update download 移到可重建 cache 或从 backup manifest 排除；
6. 实现 Logs 路径、rotation/retention/redaction；
7. 对 owner/mode/symlink/volume/low-disk 做验证；
8. 明确 uninstall 和 cache reset 语义。

验收：

- fresh/old layout 可判定且未知 layout fail closed；
- renderer/日志不暴露绝对私有路径；
- update/cache 不进入不可替代 backup；
- 重启和中断不留下半迁移 active；
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

- 状态：`planned`
- Owner：Backend/Desktop migration
- 关联：REQ-DATA-001、REQ-LEGACY-001、ADR-0004、ITER-0003/D02–D03
- 依赖：layout、backup/restore

交付：

- 只支持 legacy backup archive 或用户显式选择、已停 writer 的 bind-mount root；
- named volume 必须先在 legacy 环境导出；
- read-only inventory：format/schema、owner、size、checksum、SQLite、Git、counts；
- source fingerprint、migration ID 和 durable journal；
- unique staging、逐版本 converter、恢复点；
- 不执行 hooks/config/helper/repository code；
- atomic activate、post-start smoke、rollback；
- 默认保留 source、journal、quarantine；
- 防止 legacy 与 desktop writer 并发。

验收矩阵：

- fresh、repeat、interrupt、corrupt、unknown-version、symlink、active-writer、low-disk；
- 不同历史 schema、不同 corpus/index state；
- page/ref/job/settings/model counts；
- 失败后旧版本仍读取原数据；
- `VAL-DATA-001` 与迁移子门禁为 `pass`。

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
- 依赖：canonical repository 管理员、至少一名独立 reviewer、公开仓库支持的保护能力
- 阻塞：需要 canonical repository 管理员和独立 reviewer

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
- 依赖：TODO-REL-GOV-001

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

## 5. Priority-1：正式打包与物理 M4

### TODO-PACK-ARM64-001：正式 runtime staging 与候选打包

- 状态：`planned`
- Owner：Packaging/Python/QMD
- 关联：REQ-PACK-001、ITER-0002/R02–R06、ITER-0004/P01/P03
- 依赖：数据合同可冻结、trust pins provisioned

交付：

- CPython 3.13.14 双重 source digest；
- PyInstaller onedir、hash lock、module/resource audit；
- Node 22.23.2/QMD 2.5.3、better-sqlite3 arm64 source rebuild；
- renderer/companion staging；
- manifest/schema/version/source commit；
- exact inventory、normalized digest、SBOM、notices；
- Mach-O architecture、dylib/RPATH；
- nested signing order、临时 keychain 清理；
- `beforePack` tamper rejection；
- DMG/ZIP/blockmap/update/release manifest 资产集合。

验收：

- `macos-15` protected build 成功；
- artifact 与 Draft bytes 一致；
- 失败 PATH 下 packaged smoke 不发现系统 runtime；
- `VAL-PACK-001`、`VAL-RELEASE-001` 的构建子项为 `pass`。

### TODO-PHYS-TRUST-001：Packaged renderer/Main 信任审计

- 状态：`planned`
- Owner：Desktop Security/QA
- 依赖：formal candidate

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
- 依赖：formal candidate

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
- 依赖：formal candidate、TODO-MODEL-SUPPLY-001

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
- 依赖：formal candidate、真实 CLI 登录

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
- 依赖：formal `/Applications` App、真实官方签名 Codex

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
- 依赖：formal packaged App

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
- 依赖：所有 release P0、formal staging、目标版本同步

执行前：

- clean protected `main`；
- runtime/package/QMD version 完全一致；
- unified product tag review：同一 `vX.Y.Z` 也发布 container SemVer；
- source/policy CI success；
- release notes 明示 self-signed/not notarized/not hardened/automatic apply disabled。

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
- 依赖：同一 Draft 上所有 physical gate `pass`

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

## 7. Priority-3：Legacy 与未来范围

### TODO-LEGACY-EXIT-001：Legacy 去留决策

- 状态：`blocked`
- Owner：Migration/Product/Operations
- 依赖：P0–P6 所有阻断 gate `pass`

交付：

1. 脱敏、代表性的 legacy 样本和 counts；
2. migration/rollback rehearsal；
3. 页面、引用、任务、索引、设置和恢复核对；
4. 用户成本、失败率、已知不支持版本；
5. 独立 legacy retention/deprecation ADR；
6. 用户公告和时间表；
7. 只有 ADR Accepted 后才清理 Docker/Compose/host runner/installers。

验收：`VAL-LEGACY-001 pass`。在此之前 legacy 必须保留。

### TODO-REMOTE-WORKER-001：Windows/4060 Desktop worker 决策

- 状态：`planned`
- Owner：Product/Architecture
- 优先级：Priority-3
- 依赖：desktop GA、TODO-EVAL-CORPUS-001；若进入实现还依赖新的安全/协议 ADR
- 当前边界：Electron 明确不支持远程 Windows/Ollama worker；legacy 可用。

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
- 若拒绝，status/guide/TODO 继续把 Windows 限定为 legacy；
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

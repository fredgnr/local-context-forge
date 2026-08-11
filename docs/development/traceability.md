# Electron 迁移可追溯矩阵

## 坐标与规则

- 上游基线：`main@5d95e58cefa1c94b5c9ac8dd681671e2dfd6d8dd`
- 已发布 P1 检查点：`agent/electron-desktop-foundation@7e4524f`
- bundled runtime merge：`main@52a5ffa184da694519a906dbacc7ee9df26a3fcc`
- two-stage release merge：`main@fb8bbbc3d0b4e4b5a20c943bd7fd71b2450651a8`
- Electron-only planning merge：`main@da40553e43ec6272e1affc1f40abf4f9215f1ba5`
- Pre-1.0 planning merge / W01 基线：`main@3eff97d97b2de4484d568bab5ac96d63830c79ee`
- W01 accepted remediation：`36885e04df09c4789d8ec3c9dc5c5e78a381a634` / tree
  `1b9f3a34847fd3acc8b7f3a31ff19332d5328b64`
- W02 实施基线：`main@1786255b55dd1a78659ed92235893876175a0722` / same tree；source run
  `30986208251` success
- W02 PR #21 current independent verdict：reviewed
  `8c5fd23206b671b768fd21d253bf292642f93a51` / tree
  `785f4656de8a7233b6dd632fe4815976d33468fb`，latest independent `NO-GO`；same branch/PR first
  remediation `9f7d5d11225517ff5b1643d4bb71983346358ae0` / tree
  `ea8e62e9b76c3270d60135a8633f56db025ad921` technical `fail` / `superseded`；second remediation
  `9ecf0effaa48a8b010ff46ffb42afc57e0f3d948` / tree
  `ee82712c7874155eba038d1ce05d374416ed34e5` technical `fail` / `superseded`；third remediation
  `2665ec61712fe410608ac50c7a6d44fa35746092` / tree
  `c3cd1706838f7050533e2812dfdcad482aaedde5` technical `fail` / `superseded`；fourth remediation
  `c2be665f5832c15064cae87c694a782e51351e7c` / tree
  `f90b527b4de1a422f63c4bfeb01f9c1010e22b7d` technical `fail` / `superseded`；fifth exact
  remediation technical candidate `not-run`（local regression only；fresh exact-head Actions pending）
- 活动父迭代：[ITER-0002](iterations/0002-bundled-runtimes.md)
- 路线图：[P0–P7](roadmap.md)
- 工作包顺序：[W01–W16](work-plan.md)
- 当前状态：[status](status.md)
- 剩余任务：[TODO](todo.md)

每个行为变化必须形成以下链路：

```text
REQ -> ADR -> ITER/task -> owned paths -> VAL -> evidence
```

`Accepted` ADR 表示决策已确定，不表示实现或验证已完成。验证只有 `pass`、`fail`、
`not-run` 三种结果；`source 子门禁 pass` 不能替代要求 packaged/physical 环境的完整门禁。
R07–R13 是 ITER-0002 的追加记录；R12/R13 已完成。旧 W01 candidate 的 independent `fail` 仍是
历史事实；remediation exact final 已独立接受、合入并在 resulting main 完成 source coverage。
父 ITER-0002 因既有 packaged/physical 门禁继续开放，ITER-0008/W02 当前 `in-progress`。

## 需求与映射

| 需求 ID | 验收目标 | 决策 | 任务 | Owned paths | 验证 | 当前状态 |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-GOV-001 | 每项变更有 active iteration、owner、稳定 task/VAL 和 commit-bound evidence | 现有治理规则；架构变化另由 ADR-0015/REQ-ELECTRON-ONLY 承载 | ITER-0001/T01；[R11](iterations/0002-r11-documentation-handoff.md)；[R12](iterations/0002-r12-legacy-retirement-scope.md)；[R13](iterations/0002-r13-pre1-incremental-retirement.md) W01 closeout；ITER-0008/W02 | `AGENTS.md`、`.agents/skills/**`、`docs/development/**`、PR template、immutable W01 history + W02 entry/assembly/PR21-NO-GO evidence | VAL-GOV-001、VAL-DOC-HANDOFF-001、VAL-LEGACY-SCOPE-001 | 旧 W01 final `2b762946…` technical `pass` 但 independent `fail` / activation `not-eligible`；accepted W01 remediation/main/run 闭环 `pass`；W02 old static evidence preserved；PR #21 reviewed `8c5fd232…` independent `NO-GO` append-only；first `9f7d5d…`、second `9ecf0e…`、third `2665ec…`、fourth `c2be665f…` remediations technical `fail` / `superseded` appended；fifth exact candidate `not-run` |
| REQ-PRE1-SEQUENCING-001 | 固定 smoke → slices → cleaned engineering package → physical → final cutover/absence → production release 的顺序 | [ADR-0016](../adr/0016-pre1-incremental-retirement-engineering-package.md) | [R13](iterations/0002-r13-pre1-incremental-retirement.md)；[work plan](work-plan.md)；TODO-PRE1-SEQUENCING/GOV-EVIDENCE/CI-COVERAGE-001 | `docs/adr/0016-*`、`docs/development/{work-plan,todo,traceability,roadmap,status}.md`、plan checker | VAL-PRE1-SEQUENCE-001、VAL-GOV-001、VAL-CI-COVERAGE-001 | W01 exact accepted head、independent acceptance、merge 与 resulting-main source `pass`；W02 active，W10/W11 locked |
| REQ-PACKAGED-SMOKE-001 | W01 technical PR/source、independent acceptance、accepted merge 与 resulting-main source 全部完成后、任何 destructive slice 前，提供最小且明确 non-release 的 packaged feedback loop | [ADR-0016](../adr/0016-pre1-incremental-retirement-engineering-package.md) | ITER-0008/I01；TODO-PACKAGED-SMOKE-001 | `.github/workflows/packaged-smoke.yml`、`desktop/electron-builder.smoke.yml`、engineering smoke prepare/beforePack/afterPack/audit scripts、exact Git/Node/Python provenance helpers、shared renderer/Python consumers 与 schemas、formal build job 的同源 provenance 加固、policy checker/tests/evidence；legacy Web continuity 仅含 `web/Dockerfile`、container workflow/policy test；不触发 formal Draft/promotion/publish | VAL-PACKAGED-SMOKE-001 | old Draft static run historical technical `pass`；reviewed `8c5fd232…` / tree `785f4656…` independent `NO-GO`；first `9f7d5d…` / `ea8e62…`、second `9ecf0e…` / `ee8271…`、third `2665ec…` / `c3cd17…`、fourth `c2be665f…` / `f90b527b…` remediations technical `fail` / `superseded`（fourth source/Containers success；Engineering inner build/cleanup fail；no publish；engineering product artifacts `[]`）；fifth exact candidate `not-run`；formal package/App/credentials/publish/promotion 与 packaged App launch/runtime 均 `not-run`；W02 remains `in-progress` |
| REQ-LEGACY-SLICE-001 | 每个 legacy slice 独立完成 owner/split、affected replacement 或受限 pure-legacy unsupported disposition、before/after package、focused regression、absence/presence 与 data non-effect | [ADR-0016](../adr/0016-pre1-incremental-retirement-engineering-package.md) | ITER-0008/I02–I07；TODO-LEGACY-DECOUPLE/REMOVE-* | [strict manifest](legacy-retirement.md)、slice-owned paths、protected paths、evidence | VAL-LEGACY-DECOUPLE/DEPLOY/TRANSPORT/PROVIDER/RELEASE/DOCS-001 | 均 `not-run` |
| REQ-ENGINEERING-PACKAGE-001 | 从 W10/W11 cleaned tree 生成完整 non-release 工程包，作为 W04–W12 载体，不接触 production trust/release | [ADR-0016](../adr/0016-pre1-incremental-retirement-engineering-package.md) | ITER-0008/I08；TODO-PACK-ENGINEERING-001 | future engineering package config、cleaned runtime staging、inventory/SBOM/notices/test entry | VAL-ENGINEERING-PACKAGE-001 | `not-run` |
| REQ-DOC-001 | 新贡献者可从权威状态、系统设计、部署、开发、TODO 和 evidence 独立接手 | R11 基线组合 ADR-0001–0014；R12 的新 Electron-only 决策单独映射到 REQ-ELECTRON-ONLY/PRE1-BREAKING | [R11](iterations/0002-r11-documentation-handoff.md)；[R12](iterations/0002-r12-legacy-retirement-scope.md) 同步当前权威入口 | `README.md`、`TODO.md`、`docs/{README,17-*,18-*}.md`、`docs/development/**`、component READMEs | VAL-DOC-HANDOFF-001、VAL-LEGACY-SCOPE-001 | [`625db76` R11 checkpoint](evidence/VAL-DOC-HANDOFF-001/2026-07-31-625db76.md) 与 [`64ec3c2` R12 scope checkpoint](evidence/VAL-LEGACY-SCOPE-001/2026-07-31-64ec3c2.md) `pass`；最终 PR CI 待完成 |
| REQ-PLATFORM-001 | macOS Apple Silicon Electron all-in-one，React renderer | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md) | ITER-0001/T02；ITER-0004/P01、P05 | `desktop/**`、`web/src/**` | VAL-P1-SOURCE-001、VAL-INSTALL-001 | source `pass`；packaged/安装 `not-run` |
| REQ-ELECTRON-ONLY-001 | Electron 是唯一受支持产品运行/发布面；W02 后按独立 slice 删除 Docker、browser Web、public TCP API、legacy MCP、Host Runner 与 container/GHCR | [ADR-0015](../adr/0015-electron-only-legacy-retirement.md)、[ADR-0016](../adr/0016-pre1-incremental-retirement-engineering-package.md) | [R12](iterations/0002-r12-legacy-retirement-scope.md)；[R13](iterations/0002-r13-pre1-incremental-retirement.md)；[ITER-0008](iterations/0008-incremental-retirement-engineering-package.md)；legacy TODOs | [strict manifest](legacy-retirement.md)、Desktop/Web/Backend split、legacy removal paths | VAL-LEGACY-SCOPE-001、slice VALs、VAL-ELECTRON-CUTOVER-001、VAL-LEGACY-ABSENCE-001 | 决策/范围 `pass`；smoke、slices、engineering package、final gates `not-run` |
| REQ-PRE1-BREAKING-001 | 不承诺 legacy 部署/config/API/data 兼容或迁移；unknown layout fail closed；绝不自动删除用户 data/volume/backup | [ADR-0015](../adr/0015-electron-only-legacy-retirement.md)、[ADR-0016](../adr/0016-pre1-incremental-retirement-engineering-package.md) | R12/R13；ITER-0003/D01–D03；ITER-0008 | desktop-only layout、reset UX、slice PR policy/docs | VAL-DATA-001、slice VALs、VAL-ELECTRON-CUTOVER-001、VAL-LEGACY-ABSENCE-001 | policy Accepted；实现/物理证据 `not-run` |
| REQ-TRUST-001 | Main 是信任边界，renderer 只有类型化最小能力，不得到路径/argv/token/key | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md)、[ADR-0011](../adr/0011-main-owned-signed-update-client.md)、[ADR-0012](../adr/0012-local-repository-picker-opaque-grants.md)、[ADR-0013](../adr/0013-codex-mcp-onboarding-signed-cli-discovery.md) | ITER-0001/T02、T04；R08–R10 | `desktop/src/main/**`、`desktop/src/preload/**`、`web/src/**` | VAL-TRUST-001、VAL-MCP-ONBOARD-001、VAL-UPDATE-CLIENT-001、VAL-LOCAL-SOURCE-001 | source contracts `pass`；packaged trust `not-run` |
| REQ-PY-001 | CPython 3.13.14 PyInstaller `onedir` 随应用交付且可审计 | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md)、[ADR-0009](../adr/0009-bundled-runtime-provenance.md) | ITER-0002/R02 | `backend/packaging/**`、`tools/*python_sidecar*`、`desktop/generated/sidecar/**`、`desktop/resources/sidecar/**` | VAL-PY-001、VAL-PACK-001 | source build/audit contract `pass`；clean-user `not-run` |
| REQ-GIT-001 | packaged 产品不调用系统 Git，snapshot/Wiki 保持安全与回滚语义 | [ADR-0006](../adr/0006-dulwich-product-git-boundary.md)、[ADR-0012](../adr/0012-local-repository-picker-opaque-grants.md) | ITER-0002/R01、R10 | `backend/app/{source,wiki}.py`、source/Wiki tests | VAL-GIT-001、VAL-PY-001、VAL-LOCAL-SOURCE-002 | source `pass`；packaged full gate `not-run` |
| REQ-LOCAL-SOURCE-001 | picker 以一次性 opaque grant 导入预先 clone 的本地/私有仓库，不管理凭据 | [ADR-0012](../adr/0012-local-repository-picker-opaque-grants.md) | [ITER-0002/R10](iterations/0002-r10-local-repositories.md) | `desktop/src/main/localSource*`、`backend/app/{cli,config,source}.py`、`web/src/{App,desktopBridge}.ts*` | VAL-LOCAL-SOURCE-001、002、003 | Main/Backend/Web source `pass`；physical Mac `not-run` |
| REQ-QMD-001 | QMD 使用内置 Node 22.23.2 worker，经 Main broker 提供 revision-safe lexical/hybrid retrieval | [ADR-0007](../adr/0007-qmd-retrieval-broker-runtime.md)、[ADR-0009](../adr/0009-bundled-runtime-provenance.md)、[ADR-0010](../adr/0010-qmd-local-embedding-profile.md) | ITER-0002/R03、[R07](iterations/0002-r07-qmd-embeddings.md) | `desktop/workers/qmd/**`、`desktop/src/main/qmd*`、`backend/app/desktop_retrieval.py` | VAL-QMD-001、VAL-QMD-EMBED-001、VAL-PACK-001 | source contracts `pass`；native/model full gates `not-run` |
| REQ-IPC-001 | Main 与 sidecar/worker/companion 使用私有 UDS、per-launch identity 与不重放 token | [ADR-0002](../adr/0002-uds-startup-token-protocol.md)、[ADR-0008](../adr/0008-mcp-companion-main-bridge.md)、[ADR-0013](../adr/0013-codex-mcp-onboarding-signed-cli-discovery.md) | ITER-0001/T03；ITER-0002/R03–R04、R08、R10 | `desktop/src/main/**`、`desktop/companion/**`、`backend/app/{cli,desktop_session,factory}.py` | VAL-IPC-001、VAL-IPC-EMBED-001、VAL-MCP-001、VAL-LOCAL-SOURCE-002 | source/macOS bind 子门禁 `pass`；packaged lifecycle `not-run` |
| REQ-COMPAT-001 | 历史：Desktop bridge fail closed 且保留 browser/Docker HTTP transport | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md)；由 [ADR-0015](../adr/0015-electron-only-legacy-retirement.md) 取代兼容部分 | 历史 ITER-0001/T04；后续 TODO-LEGACY-DECOUPLE-001 | `web/src/{api,desktopBridge,App}.ts*`、Web tests | 历史 VAL-P1-REGRESSION-001 | `superseded`；历史 source `pass` 不构成继续保留授权 |
| REQ-VERSION-001 | 产品、协议与 schema 版本由 manifest 跨层同步 | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md)、[ADR-0002](../adr/0002-uds-startup-token-protocol.md) | ITER-0001/T05；ITER-0002/R06 | `runtime/version.json`、`backend/app/version.py`、`desktop/package.json`、`tools/check_version_sync.py` | VAL-P1-CONTRACT-001、VAL-PACK-001 | source `pass`；formal package `not-run` |
| REQ-CI-001 | 普通 source CI 最小权限且不能读取配置的 Environment/repository release secret 或长期签名凭据；job 可使用按 run 签发、最小权限的短期 `GITHUB_TOKEN` | [ADR-0003](../adr/0003-macos-release-signing-update-policy.md)、[ADR-0014](../adr/0014-two-stage-desktop-release-promotion.md) | ITER-0001/T05；R09 | `.github/workflows/{desktop-ci,desktop-release}.yml` | VAL-CI-001、VAL-RELEASE-POLICY-001、VAL-SECRET-001 | source policy `pass`；Environment setting proof `not-run` |
| REQ-CLI-001 | Codex 默认；Cursor 仅经同意且在 spawn 前明确失败时替代，commit 后不 fallback/replay | [ADR-0005](../adr/0005-provider-attempt-execution-boundary.md)、[ADR-0013](../adr/0013-codex-mcp-onboarding-signed-cli-discovery.md) | ITER-0002/R05、R08 | `backend/app/**`、`desktop/src/main/providers/**`、provider UI/tests | VAL-CLI-001、VAL-MCP-ONBOARD-001 | source policy/attempt `pass`；真实 provider `not-run` |
| REQ-MCP-001 | 内置 stdio companion 只公开两个 Context7 兼容工具，经 Main 私有只读桥 | [ADR-0008](../adr/0008-mcp-companion-main-bridge.md)、[ADR-0013](../adr/0013-codex-mcp-onboarding-signed-cli-discovery.md) | ITER-0002/R04、[R08](iterations/0002-r08-mcp-onboarding.md) | `desktop/companion/**`、`desktop/src/{mcpProtocol,main/mcp*}.ts`、[protocol](mcp-companion-protocol.md) | VAL-MCP-001、VAL-MCP-ONBOARD-001 | source 子门禁 `pass`；packaged Codex/tools `not-run` |
| REQ-MCP-ONBOARD-001 | Main 以固定 argv、安全 CLI discovery 和 scoped target ownership 配置 Codex MCP | [ADR-0013](../adr/0013-codex-mcp-onboarding-signed-cli-discovery.md) | [ITER-0002/R08](iterations/0002-r08-mcp-onboarding.md) | `desktop/src/main/{mcpOnboarding,mcpTargetOwnership}.ts`、`desktop/src/mcpProtocol.ts`、`desktop/companion/**`、providers/preload/IPC、`web/src/McpOnboarding*` | VAL-MCP-ONBOARD-001、VAL-MCP-001 | Desktop/Web source `pass`；真实 OpenAI 签名 packaged gate `not-run` |
| REQ-PACK-001 | bundled runtime 来源、文件、native closure、许可证和输入摘要可复核，篡改 fail closed | [ADR-0009](../adr/0009-bundled-runtime-provenance.md) | ITER-0002/R02–R04、R06 | runtime schemas、build/audit scripts、Electron `beforePack` | VAL-PACK-001 | source tamper/build contracts `pass`；formal arm64 staging `not-run` |
| REQ-INSTALL-001 | 默认 DMG；目标机无需 Docker/Homebrew/Python/Node/Git/ctags | [ADR-0003](../adr/0003-macos-release-signing-update-policy.md) | ITER-0004/P01、P05；R09 foundation | packaging/workflow、[release runbook](desktop-release.md) | VAL-INSTALL-001、VAL-RELEASE-POLICY-001 | source policy `pass`；clean-user `not-run` |
| REQ-MODEL-001 | 模型按需下载、校验、CAS 激活；未 ready 时不使用旧向量，desktop scoped 可用 QMD BM25，broker/global 走 Python lexical | [ADR-0004](../adr/0004-runtime-paths-legacy-data-migration.md)、[ADR-0010](../adr/0010-qmd-local-embedding-profile.md) | ITER-0003/D04–D05；R07 foundation | QMD worker、retrieval broker、model manager/cache | VAL-MODEL-001、VAL-MODEL-EMBED-001 | source race/fallback `pass`；真实 download/native `not-run` |
| REQ-RELEASE-001 | 自签名，明确未 notarize、未 hardened；exact tag/provenance/asset set | [ADR-0003](../adr/0003-macos-release-signing-update-policy.md)、[ADR-0011](../adr/0011-main-owned-signed-update-client.md)、[ADR-0014](../adr/0014-two-stage-desktop-release-promotion.md) | ITER-0004/P01–P03；[R09](iterations/0002-r09-signed-update-client.md) | `.github/workflows/desktop-release.yml`、`desktop/scripts/prepareRelease.cjs`、release docs | VAL-RELEASE-POLICY-001、VAL-RELEASE-001 | source policy `pass`；真实 signed artifact `not-run` |
| REQ-RELEASE-002 | desktop tag path 只创建候选 Draft；W13→tag 只允许 public pins/release metadata/version diff；公开前在 exact Draft 重跑 cutover/absence，并由 trusted-main verifier、fixed Release ID、candidate digest 和 post-publish attestation/immutable 推广；container/GHCR 同-tag耦合须在 W11 删除 | [ADR-0014](../adr/0014-two-stage-desktop-release-promotion.md)、[ADR-0015](../adr/0015-electron-only-legacy-retirement.md)、[ADR-0016](../adr/0016-pre1-incremental-retirement-engineering-package.md) | ITER-0002/R09；ITER-0008/I06；ITER-0004/P06–P07 | desktop release workflow/validator/runbook；container workflow 为 W11 remove surface | VAL-LEGACY-RELEASE-001、VAL-RELEASE-CONTINUITY-001、VAL-RELEASE-PROMOTION-001、VAL-RELEASE-001 | desktop source policy `pass`；legacy removal/continuity/真实 promotion `not-run` |
| REQ-SECRET-001 | 本 desktop release workflow 唯一配置的长期 private credential 只在 tag-only `macos-signing` build/sign step 使用；Draft 与 branch-only promotion 不配置 Environment/repository release secret 或长期签名凭据，但 job 仍以最小权限使用短期 `GITHUB_TOKEN` | [ADR-0003](../adr/0003-macos-release-signing-update-policy.md)、[ADR-0014](../adr/0014-two-stage-desktop-release-promotion.md) | ITER-0004/P02–P04、P06；R09 | release workflow、`tools/bootstrap_desktop_release_keys.py` | VAL-RELEASE-POLICY-001、VAL-RELEASE-PROMOTION-001、VAL-SECRET-001 | source workflow policy `pass`；真实 settings proof `not-run` |
| REQ-RELEASE-GOV-001 | 两 Environment 独立 reviewer/self-review prevention/UI no-admin-bypass；active protected-main、owner-only tag creation、no-bypass immutable tags；GitHub Immutable Releases | [ADR-0014](../adr/0014-two-stage-desktop-release-promotion.md) | ITER-0004/P02/P02a；R09 | bootstrap、GitHub settings、runbook | VAL-RELEASE-POLICY-001、VAL-SECRET-001 | source bootstrap contract `pass`；真实 GitHub settings `not-run` |
| REQ-UPDATE-001 | 独立签名 check/download；用户确认 verified DMG；signed unavailable/error 时仅显式固定 Release 页面出口；automatic apply 需新 ADR 和物理 gate | [ADR-0003](../adr/0003-macos-release-signing-update-policy.md)、[ADR-0011](../adr/0011-main-owned-signed-update-client.md) | ITER-0005/U01–U05；[R09](iterations/0002-r09-signed-update-client.md) | `desktop/src/main/update*`、preload/contracts、Web UI、release assets | VAL-UPDATE-CLIENT-001、VAL-UPDATE-001 | source client `pass`；真实 `N-1→N` `not-run` |
| REQ-DATA-001 | 标准 macOS 路径；当前 Desktop 数据 backup/restore；unknown/legacy layout fail closed，不自动删除 | [ADR-0004](../adr/0004-runtime-paths-legacy-data-migration.md)、[ADR-0015](../adr/0015-electron-only-legacy-retirement.md) | ITER-0003/D01–D03；TODO-DATA-LAYOUT/BACKUP-001 | runtime layout/version、Desktop backup/restore、reset UX | VAL-DATA-001 | Application Support/Caches/temp 部分实现；完整 gate `not-run`；legacy migration 部分 `superseded` |
| REQ-LEGACY-001 | 历史：Docker 暂留 legacy，迁移成功且另行决策后才弃用 | [ADR-0004](../adr/0004-runtime-paths-legacy-data-migration.md)；由 [ADR-0015](../adr/0015-electron-only-legacy-retirement.md) 取代 | [ITER-0006](iterations/0006-legacy-exit.md)；TODO-LEGACY-CONTROL/EXIT-001 | 历史 Docker paths/docs/installer/migration controls | VAL-LEGACY-CONTROL-001、VAL-LEGACY-001 | `superseded`；两个验证保持 `not-run` |

## TODO 任务映射

本表稳定映射 [TODO 总览](todo.md)中的每个 Task ID。它记录预期 owner surface 和最低 gate，
不是实现或验证已经完成的声明；表中 `planned` / `blocked` 任务的独立 VAL 均保持
`not-run`，直到有满足最低环境的可复现证据。

| Task ID | Roadmap | 当前状态 | Requirement / decision | Owned paths / artifact | VAL / gate |
| --- | --- | --- | --- | --- | --- |
| TODO-PRE1-SEQUENCING-001 | W01 | `done` | REQ-PRE1-SEQUENCING-001；ADR-0016 | ADR/work plan/R13/TODO/traceability/authority docs、`tools/check_pre1_work_plan.py`、negative unit fixtures、`ci-python` hook | accepted final/independent/merge/resulting-main source/activation `pass` |
| TODO-GOV-EVIDENCE-001 | W01/P0 | `done` | REQ-GOV-001、REQ-PRE1-SEQUENCING-001；现有 evidence 治理规则 | `docs/development/{evidence/**,iterations/**,status.md,traceability.md}`、immutable W01 history + W02 external entry | accepted final `36885e04…` / main `1786255b…` / tree `1b9f3a34…` closed |
| TODO-CI-COVERAGE-001 | W01/P0 | `done` | REQ-GOV-001、REQ-CI-001、REQ-PRE1-SEQUENCING-001；ADR-0009/0014 的 source/release CI 边界 | `Makefile`、`.github/{ci,workflows}/**`、QMD safe runner、guide-site exclusion、coverage checker/docs | resulting-main run `30986208251` attempt 1 / five jobs `success` |
| TODO-PACKAGED-SMOKE-001 | W02 | `in-progress` | REQ-PACKAGED-SMOKE-001；ADR-0016 | isolated engineering-smoke config、strict manifest、staging/bundle audit、capability/provenance/cleanup policy and adversarial tests；future launch/UDS/no-listener harness | [old static assembly/audit](evidence/W02/2026-08-06-08137c7-assembly.md) technical `pass`；[PR #21 remediation](evidence/W02/2026-08-07-pr21-remediation.md) latest independent `NO-GO` / four attempts `fail` / `superseded` / fifth candidate `not-run`；VAL-PACKAGED-SMOKE-001 `not-run` |
| TODO-PACK-ENGINEERING-001 | W03 | `planned` | REQ-ENGINEERING-PACKAGE-001；ADR-0016 | future cleaned-tree full engineering package、inventory/SBOM/notices/test entry | VAL-ENGINEERING-PACKAGE-001 `not-run` |
| TODO-LEGACY-CONTROL-001 | historical | `superseded` | REQ-LEGACY-001；ADR-0004，由 ADR-0015 取代 | 历史 legacy instance-control 计划；不再实施 | VAL-LEGACY-CONTROL-001 `not-run (superseded)` |
| TODO-DATA-LAYOUT-001 | W04/P4 | `planned` | REQ-DATA-001；ADR-0004 | Desktop runtime path/layout modules、layout manifest/version、Logs/cache/uninstall docs | VAL-DATA-001 layout foundation `not-run` |
| TODO-DATA-BACKUP-001 | W04/P4 | `planned` | REQ-DATA-001；ADR-0004 | Desktop backup/restore modules、canonical manifest、UI/CLI、physical fixtures/docs | VAL-DATA-001 backup/restore subgate `not-run` |
| TODO-DATA-MIGRATION-001 | historical | `superseded` | REQ-LEGACY-001；ADR-0004，由 ADR-0015 取代 | 历史 importer/journal/converter 计划；不再实施 | VAL-DATA-001 legacy-migration subgate `not-run (superseded)` |
| TODO-MODEL-SUPPLY-001 | W05/P4 | `planned` | REQ-MODEL-001、REQ-QMD-001；ADR-0004/0010 | QMD model manager/cache、signed model manifest、shadow index、release/UI docs | VAL-MODEL-001 `not-run` |
| TODO-REL-GOV-001 | W14/P5 | `blocked` | REQ-RELEASE-GOV-001、REQ-SECRET-001；ADR-0014/0016 | GitHub Environments/rulesets/Immutable Releases、bootstrap settings evidence；W13 前禁止执行 | VAL-SECRET-001 settings subgate `not-run` |
| TODO-REL-KEYS-001 | W15/P5 | `blocked` | REQ-SECRET-001、REQ-UPDATE-001；ADR-0003/0011/0014/0016 | `tools/bootstrap_desktop_release_keys.py`、public key/certificate locks、rotation/revocation docs | VAL-SECRET-001 trust-pin/secret-membership subgate `not-run` |
| TODO-PACK-ARM64-001 | W15/P5 | `planned` | REQ-PACK-001、REQ-PY-001、REQ-QMD-001、REQ-INSTALL-001、REQ-RELEASE-002；ADR-0009/0016 | formal runtime manifests/staging、SBOM/notices、candidate assets；W13→tag allowlisted diff；不可用于 W02/W03 | VAL-RELEASE-CONTINUITY-001 tag/diff、VAL-PACK-001、VAL-RELEASE-001 build subgate `not-run` |
| TODO-PHYS-TRUST-001 | W06/P1 | `planned` | REQ-TRUST-001；ADR-0001/0011/0012/0013/0016 | W03 packaged App security/IPC audit harness、negative evidence | VAL-TRUST-001 `not-run` |
| TODO-PHYS-PY-001 | W06/P2 | `planned` | REQ-PY-001、REQ-GIT-001、REQ-IPC-001；ADR-0001/0002/0006/0009/0016 | W03 bundled sidecar/Dulwich/UDS physical harness and fixtures | VAL-PY-001、VAL-GIT-001、VAL-IPC-001 `not-run` |
| TODO-PHYS-QMD-001 | W07/P3/P4 | `planned` | REQ-QMD-001、REQ-MODEL-001、REQ-IPC-001；ADR-0004/0007/0009/0010/0016 | W03 packaged QMD worker/native/model corpus and fault fixtures | VAL-QMD-001、VAL-QMD-EMBED-001、VAL-IPC-EMBED-001、VAL-MODEL-EMBED-001 `not-run` |
| TODO-PHYS-CLI-001 | W08/P3 | `planned` | REQ-CLI-001、REQ-TRUST-001；ADR-0005/0013/0016 | W03 provider supervisor/attempt records、real Codex/Cursor cut-point harness | VAL-CLI-001 `not-run` |
| TODO-PHYS-MCP-001 | W09/P3 | `planned` | REQ-MCP-001、REQ-MCP-ONBOARD-001、REQ-TRUST-001；ADR-0008/0013/0016 | W03 packaged companion/onboarding、ownership fixtures、real Codex evidence | VAL-MCP-001、VAL-MCP-ONBOARD-001 `not-run` |
| TODO-PHYS-LOCAL-001 | W12/P1/P4 | `planned` | REQ-LOCAL-SOURCE-001、REQ-GIT-001、REQ-TRUST-001；ADR-0012/0016 | W03 local-source Main/Backend policy、home/volume/private-repo physical fixtures | VAL-LOCAL-SOURCE-003 `not-run` |
| TODO-ELECTRON-CUTOVER-001 | W13/P7 | `planned` | REQ-ELECTRON-ONLY-001、REQ-PRE1-SEQUENCING-001；ADR-0015/0016 | final cleaned package capability matrix：ingest/queue/review/query/Wiki/model/rebuild/provider/MCP/data；冻结 formal continuity verifier/allowlist/schema | VAL-ELECTRON-CUTOVER-001 `not-run` |
| TODO-LEGACY-DECOUPLE-001 | W10/P7 | `planned` | REQ-ELECTRON-ONLY-001、REQ-LEGACY-SLICE-001；ADR-0015/0016 | shared renderer/sidecar/provider caller inventory、split paths、focused/aggregate tests | VAL-LEGACY-DECOUPLE-001 `not-run` |
| TODO-REL-DRAFT-001 | W15/P5 | `blocked` | REQ-RELEASE-001、REQ-RELEASE-002、REQ-SECRET-001、REQ-ELECTRON-ONLY-001；ADR-0003/0009/0014/0015/0016 | tag-bound unique formal Draft、W13 checkpoint/tag allowlisted diff、candidate manifest/evidence；engineering artifact 禁止进入 | VAL-RELEASE-POLICY-001 source `pass`；VAL-RELEASE-CONTINUITY-001 tag/diff、VAL-RELEASE-001 candidate subgate `not-run` |
| TODO-REL-PROMOTE-001 | W16/P5 | `blocked` | REQ-RELEASE-001/002、REQ-RELEASE-GOV-001、REQ-SECRET-001、REQ-ELECTRON-ONLY-001；ADR-0014/0016 | exact Draft digest 的 cutover/absence、trusted-main promotion、fixed Release ID、post-publish attestation/evidence | VAL-RELEASE-PROMOTION-001 source `pass`；VAL-ELECTRON-CUTOVER-001、VAL-LEGACY-ABSENCE-001、VAL-RELEASE-CONTINUITY-001、VAL-RELEASE-001、VAL-INSTALL-001、VAL-SECRET-001 `not-run` |
| TODO-UPDATE-NMINUS1-001 | W16/P6 | `blocked` | REQ-UPDATE-001、REQ-DATA-001；ADR-0003/0004/0011/0014/0016 | two protected releases、physical update/fallback/rollback evidence | VAL-UPDATE-001 `not-run` |
| TODO-UPDATE-APPLY-001 | P6 | `planned` | REQ-UPDATE-001；planned new/superseding ADR-0011 | updater apply/restart/rollback implementation、failure harness、UI/release docs | VAL-UPDATE-APPLY-001 `not-run` |
| TODO-OPS-DIAGNOSTICS-001 | W12/P4 | `planned` | REQ-TRUST-001、REQ-DATA-001、REQ-IPC-001；既有 redaction/path decisions | Desktop doctor/support-bundle schema、redaction tests、recovery docs | VAL-DIAGNOSTICS-001 `not-run` |
| TODO-RUNTIME-CANCEL-001 | W06/P2/P3 | `planned` | REQ-IPC-001、REQ-CLI-001、REQ-QMD-001；ADR-0002/0005/0007 | Main/Backend/CLI/QMD cancellation contract、real-child fault harness | VAL-CANCEL-001 `not-run` |
| TODO-MCP-PAIRING-001 | W09/P3 | `planned` | REQ-MCP-001、REQ-MCP-ONBOARD-001、REQ-TRUST-001；planned ADR extending ADR-0008/0013 | Keychain/code-identity pairing protocol、state migration/revocation tests/docs | VAL-MCP-PAIRING-001 `not-run` |
| TODO-LOCAL-HARDEN-001 | W12/P1/P4 | `planned` | REQ-LOCAL-SOURCE-001、REQ-TRUST-001；planned ADR after ADR-0012 | threat/benchmark record、selected bookmark/fd/copy/sandbox implementation and tests | VAL-LOCAL-HARDEN-001 `not-run` |
| TODO-QMD-COMPACT-001 | W07/P3/P4 | `planned` | REQ-QMD-001、REQ-DATA-001；ADR-0007 stale-document boundary | QMD compact inventory/staging/rollback implementation、real corpus fixtures | VAL-QMD-COMPACT-001 `not-run` |
| TODO-EVAL-CORPUS-001 | W07/P3 | `planned` | REQ-QMD-001、REQ-MODEL-001、REQ-CLI-001；quality threshold record | fixed public corpus/golden review、lexical/hybrid/release quality evidence | VAL-EVAL-001 `not-run` |
| TODO-WIKI-INCREMENTAL-001 | post-P3 | `planned` | planned incremental requirement and ADR; no implementation authority yet | Backend Wiki dependency/reuse format、old/new fixtures、full-rebuild fallback | VAL-WIKI-INCREMENTAL-001 `not-run` |
| TODO-LEGACY-REMOVE-DEPLOY-001 | W11/P7 | `planned` | REQ-ELECTRON-ONLY-001、REQ-LEGACY-SLICE-001；ADR-0015/0016 | Compose/Docker/installers/legacy deploy scripts/Nginx/examples；保留 user/external assets | VAL-LEGACY-DEPLOY-001 `not-run` |
| TODO-LEGACY-REMOVE-TRANSPORT-001 | W10/P7 | `planned` | REQ-ELECTRON-ONLY-001、REQ-LEGACY-SLICE-001；ADR-0015/0016 | Python MCP gateway、public TCP/CORS/browser fetch；保留 private UDS/desktop companion | VAL-LEGACY-TRANSPORT-001 `not-run` |
| TODO-LEGACY-REMOVE-PROVIDER-001 | W10/P7 | `planned` | REQ-ELECTRON-ONLY-001、REQ-LEGACY-SLICE-001；ADR-0015/0016 | Host Runner/LaunchAgent/spool/direct provider/Ollama/Windows helper；保留 Main-owned attempts | VAL-LEGACY-PROVIDER-001 `not-run` |
| TODO-LEGACY-REMOVE-RELEASE-001 | W11/P7 | `planned` | REQ-ELECTRON-ONLY-001、REQ-RELEASE-002、REQ-LEGACY-SLICE-001；ADR-0015/0016 | `container-images.yml`、GHCR/container Make/CI/tag docs；保留 formal desktop release safety | VAL-LEGACY-RELEASE-001 `not-run` |
| TODO-LEGACY-REMOVE-DOCS-001 | W11/P7 | `planned` | REQ-ELECTRON-ONLY-001、REQ-DOC-001、REQ-LEGACY-SLICE-001；ADR-0015/0016 | README/Sites/active numbered/component docs；保留 historical ADR/evidence | VAL-LEGACY-DOCS-001 `not-run` |
| TODO-LEGACY-ABSENCE-001 | W13/P7 | `planned` | REQ-ELECTRON-ONLY-001、REQ-LEGACY-SLICE-001；ADR-0015/0016 | final cleaned bytes、versioned aggregate absence checker、history allowlist、packaged inventory | VAL-LEGACY-ABSENCE-001 `not-run` |
| TODO-LEGACY-EXIT-001 | historical | `superseded` | REQ-LEGACY-001；ADR-0004，由 ADR-0015/ITER-0007 取代 | 历史 migration/retention decision；不再实施 | VAL-LEGACY-001 `not-run (superseded)` |
| TODO-REMOTE-WORKER-001 | future | `planned` | current unsupported desktop boundary；planned accept/reject requirement/ADR | threat/cost study、decision ADR、status/hardware/system-design sync | VAL-REMOTE-WORKER-DECISION-001 `not-run` |

## 验证目录

| 验证 ID | 所需证据 / 最低环境 | 当前结果 |
| --- | --- | --- |
| VAL-GOV-001 | exact source checkout；Python/MCP/Host Runner/demo SDK/Web/Desktop/QMD/governance commands、counts/skips/environment 与 evidence binding；Markdown links | 旧候选 technical source `pass`；independent acceptance `fail`；canonical activation `not-eligible`；accepted final `36885e04df09c4789d8ec3c9dc5c5e78a381a634` / tree `1b9f3a34847fd3acc8b7f3a31ff19332d5328b64`：PR/source、independent acceptance、canonical merge 与 resulting-main source 均 `pass` |
| VAL-GOV-002 | repository checkout；两个项目 `SKILL.md` 结构 | `pass`（继承已发布检查点） |
| VAL-DOC-HANDOFF-001 | clean checkout；权威入口、命令模式、task owner/dependency/gate 和 PR handoff 可执行性 | 首轮三路审计 `fail`；修复后 [`625db76` commit-bound checkpoint](evidence/VAL-DOC-HANDOFF-001/2026-07-31-625db76.md) `pass`；最终 PR head `not-run` |
| VAL-P1-CONTRACT-001 | Linux source；Main/preload/Web/sidecar 纯源码合同 | `pass`（继承 ITER-0001） |
| VAL-P1-SOURCE-001 | Linux/macOS source；真实 AF_UNIX bind 和 source jobs | `pass`（[Actions 30550023917](https://github.com/fredgnr/local-context-forge/actions/runs/30550023917)） |
| VAL-P1-REGRESSION-001 | source checkout；Backend/Desktop/Web/Host Runner 全量 | `pass`（当前 Desktop 245/7 skip、Backend 322/1 skip；Web 51、Host 8 继承无代码变化基线） |
| VAL-CI-001 | public GitHub Actions；普通 job 最小权限 | `pass`（继承 Actions；release policy source 另列） |
| VAL-CI-COVERAGE-001 | exact source checkout + 最终 PR head CI；manifest 与 Make/workflow/QMD safety/guide-site external-blocked 反向一致；QMD 无 lifecycle build、test external network 或模型文件 | 旧候选 technical source `pass`；independent acceptance `fail`；canonical activation `not-eligible`；accepted final `36885e04df09c4789d8ec3c9dc5c5e78a381a634` / tree `1b9f3a34847fd3acc8b7f3a31ff19332d5328b64`：PR/source、independent acceptance、canonical merge 与 resulting-main source 均 `pass` |
| VAL-PRE1-SEQUENCE-001 | exact source checkout；`make pre1-work-plan-check` + links/version；W01–W16 rank/mapping/state、formal not-run、W02 canonical activation | 旧候选 technical source `pass`；independent acceptance `fail`；canonical activation `not-eligible`；accepted final `36885e04df09c4789d8ec3c9dc5c5e78a381a634` / tree `1b9f3a34847fd3acc8b7f3a31ff19332d5328b64`：PR/source、independent acceptance、canonical merge 与 resulting-main source 均 `pass` |
| VAL-PACKAGED-SMOKE-001 | macOS arm64 engineering-smoke App；exact commit/digest/inventory、launch、renderer/preload、Main→private UDS health/domain request、quit/no orphan、无 public INET、exercised path 无系统 Python/Node/Git discovery、updater unavailable/no-network | `not-run`；[old static assembly/audit](evidence/W02/2026-08-06-08137c7-assembly.md) 与 pre-pack frozen sidecar staging smoke 不替代 packaged launch/runtime gate；[current PR #21 record](evidence/W02/2026-08-07-pr21-remediation.md) binds latest independent `NO-GO`、four remediation technical failures / superseded states and fifth exact candidate execution pending |
| VAL-LEGACY-DECOUPLE-001 | exact slice baseline/head；caller inventory、split-first、affected replacement 或受限 pure-legacy unsupported disposition、aggregate source、before/after packaged smoke、protected-path presence | `not-run` |
| VAL-LEGACY-DEPLOY-001 | exact deploy slice；Docker/Compose/Nginx/install/ops paths absent；before/after smoke；Electron build/presence；无 user/external data side effect | `not-run` |
| VAL-LEGACY-TRANSPORT-001 | exact transport slice；public TCP/CORS/browser HTTP/legacy MCP absent；private UDS + bundled companion present；before/after package regression | `not-run` |
| VAL-LEGACY-PROVIDER-001 | exact provider slice；Host Runner/LaunchAgent/spool/direct/Ollama/Windows helper absent；Main-owned Codex/Cursor attempts present；before/after package regression | `not-run` |
| VAL-LEGACY-RELEASE-001 | exact release-surface slice；container workflow/GHCR publish/tag coupling absent；formal desktop policy present；远端 GHCR/Release/settings 未修改 | `not-run` |
| VAL-LEGACY-DOCS-001 | exact docs/config/test slice；active legacy commands/env/targets absent；historical ADR/iteration/evidence allowlist retained；before/after smoke + docs build | `not-run` |
| VAL-ENGINEERING-PACKAGE-001 | W10/W11 cleaned tree；完整 non-release Electron package、bundled runtime/inventory/SBOM/notices/test entry；无 production credential/pin/tag/upload/update | `not-run`；不能提升 formal gates |
| VAL-TRUST-001 | packaged app；renderer sandbox/IPC/path/update/provider 权限审计 | `not-run`（source 负向合同 `pass`） |
| VAL-GIT-001 | clean packaged Mac + C Git fixture；Dulwich、安全、回滚、PATH trap | `not-run`（Backend source 子门禁包含在 313 pass） |
| VAL-PY-001 | clean macOS arm64；bundled sidecar、无系统 runtime | `not-run`（source build/audit 子门禁 `pass`） |
| VAL-QMD-001 | clean macOS arm64；内置 Node/QMD/native/UDS lifecycle | `not-run`（worker source 8 pass / 3 skip） |
| VAL-QMD-EMBED-001 | packaged native QMD；真实 forced embedding/hybrid/profile switch | `not-run`（R07 source profile/fallback 子门禁 `pass`） |
| VAL-IPC-EMBED-001 | packaged Main/worker/sidecar；长任务、crash/restart/revision | `not-run`（Desktop 235/7 skip + Backend 313/1 skip source 子门禁 `pass`） |
| VAL-MODEL-EMBED-001 | packaged app；真实 download/offline/disk/cancel/CAS | `not-run`（source race/error 子门禁 `pass`） |
| VAL-IPC-001 | packaged macOS；UDS 权限、token、timeout、crash、stale socket | `not-run`（macOS source bind/合同子门禁 `pass`） |
| VAL-CLI-001 | macOS integration；真实 provider preflight/cut-point/no replay | `not-run`（source policy/attempt 子门禁 `pass`） |
| VAL-MCP-001 | packaged sidecars + Codex；两个工具契约和 lifecycle | `not-run`（core 3 files / 37 pass；bridge 4 files / 15 pass / 7 skip；`fcca1e4`） |
| VAL-MCP-ONBOARD-001 | `/Applications` packaged app + 真实官方签名 Codex | `not-run`（Desktop 6 files / 73、Web 3 files / 25 source 子门禁 `pass`；`fcca1e4`） |
| VAL-PACK-001 | macOS 15 arm64 formal packaging；inventory/native/SBOM/notices/tamper | `not-run`（source beforePack/build audit 子门禁 `pass`） |
| VAL-RELEASE-POLICY-001 | source checkout；tag-only signing/Draft、main-only promotion、双 Environment、唯一配置的长期 release credential、Draft/promotion 无配置的 release secret/长期签名凭据、短期 `GITHUB_TOKEN` 最小权限、ruleset/Immutable Releases bootstrap policy | `pass`（Desktop 2 files / 18；Backend 22；真实 GitHub settings `not-run`） |
| VAL-RELEASE-PROMOTION-001 | source checkout；trusted-main verifier、隔离 tag worktree、fresh peel、PATCH 前 fresh `origin/main` comparison ref、fixed Release ID PATCH、published 预状态拒绝、post-publish attestation/immutable/完整集合 | `pass`（focused policy tests、YAML parse、17 个 workflow `run` script `bash -n`；真实 promotion `not-run`） |
| VAL-UPDATE-CLIENT-001 | source checkout；signature/schema/redirect/cache/IPC/DMG/Release-page contracts | `pass`（Desktop 5 files / 42；Web 2 files / 19；`fcca1e4`） |
| VAL-LOCAL-SOURCE-001 | Desktop/Web source；grant/path/renderer negative matrix | `pass`（full Desktop 235/7 skip、Web 51：`fcca1e4`；focused 4 files / 30：`8eedd7e`） |
| VAL-LOCAL-SOURCE-002 | Backend source/desktop transport；argv roots/owner/sensitive dirs | `pass`（focused 103 / 1 skip；full 313 / 1 skip；`8eedd7e`） |
| VAL-LOCAL-SOURCE-003 | physical packaged macOS；home/外置卷/private/move/delete/restart | `not-run` |
| VAL-INSTALL-001 | clean physical Apple Silicon；DMG/Gatekeeper/no external runtimes | `not-run` |
| VAL-RELEASE-001 | protected release；真实 DMG arch/content/sign identity/limits | `not-run` |
| VAL-SECRET-001 | public repo settings；双 Environment reviewer/self-review/no-admin-bypass/deployment、配置的 Environment/repository release secret 与长期签名凭据 membership、短期 `GITHUB_TOKEN` 最小权限、三 ruleset、Immutable Releases、fork/PR 隔离 | `not-run`（workflow/bootstrap source policy `pass`） |
| VAL-UPDATE-001 | physical Apple Silicon；真实单调 `N-1 → N` + failure DMG fallback | `not-run`；automatic apply disabled，早期 ADR 版本号仅为示例 |
| VAL-UPDATE-APPLY-001 | physical Apple Silicon；真实单调 `N-1 → N` automatic apply/restart/data check，覆盖 partial replace、crash、权限、Gatekeeper、schema、ENOSPC 与 rollback | `planned` / `not-run`；Accepted superseding ADR 前不得执行为产品能力 |
| VAL-MODEL-001 | packaged app；consent/offline/integrity/resume/atomic activation | `not-run` |
| VAL-DATA-001 | current Desktop layout/backup/restore；fresh/repeat/interrupt/corrupt/low-disk/rollback/unknown-layout fail-closed | `not-run`；legacy migration 子门禁由 ADR-0015 取代 |
| VAL-LEGACY-SCOPE-001 | documentation review；每个候选 path/capability 为 remove/retain/split，稳定 REQ/TODO/VAL 和 external-data non-goal 完整 | [`64ec3c2` clean-checkout checkpoint](evidence/VAL-LEGACY-SCOPE-001/2026-07-31-64ec3c2.md) `pass`；最终 PR CI 待完成 |
| VAL-ELECTRON-CUTOVER-001 | W13 final cleaned commit 的 clean M4 rebuilt engineering package，以及 W16 exact Draft digest；ingest/queue/review/query/Wiki/model/rebuild/provider/MCP/current-data backup；无 Docker/public TCP/legacy runner | 两个执行点均 `not-run`；W13 是工程声明门禁，不再是所有 slice 前置，且不能替代 Draft 复验 |
| VAL-LEGACY-ABSENCE-001 | W13 与相应 cutover 同一 engineering commit/package digest；W16 与 exact Draft digest；forbidden paths/imports/listeners/workflows/active docs absent，protected Electron/history/formal-release safety paths present | 两个执行点均 `not-run` |
| VAL-RELEASE-CONTINUITY-001 | W13 checkpoint commit/package digest → formal tag commit 的 allowlisted public pins/release metadata/version diff；tag source/absence 重跑；exact unique Draft digest 上完整 cutover/absence 重跑；candidate manifest/Release ID 绑定 | `not-run`；通过前不得 promotion，W13 evidence 不得复用为 Draft gate evidence |
| VAL-LEGACY-001 | 历史 physical migration/rollback gate | `not-run (superseded)`；不得伪造 `pass` |
| VAL-LEGACY-CONTROL-001 | 历史 isolated legacy instance-control gate | `not-run (superseded)`；不得继续扩大 legacy 实现 |
| VAL-DIAGNOSTICS-001 | packaged App + representative failures；doctor/support bundle redaction、tamper、oversize、retention、crash 和无法启动 recovery | `planned` / `not-run` |
| VAL-CANCEL-001 | packaged fault-injection harness + real Backend/CLI/QMD children；cancel/TERM/grace/KILL/exit/orphan/cut-point/pressure matrix | `planned` / `not-run` |
| VAL-MCP-PAIRING-001 | physical `/Applications` App + 真实 Codex；Keychain/code identity、expiry/revoke、move/update/reinstall、multi-client 和 lost-state recovery | `planned` / `not-run` |
| VAL-LOCAL-HARDEN-001 | physical macOS home/外置卷/大型 monorepo；same-UID replace、move/remount、TOCTOU mitigation 与 UX/性能 benchmark | `planned` / `not-run` |
| VAL-QMD-COMPACT-001 | packaged native QMD + 真实 corpus；dry-run、删除范围、cancel/crash/ENOSPC、revision/profile、rollback 与 query parity | `planned` / `not-run` |
| VAL-EVAL-001 | fixed public multilingual corpus + stable packaged stack；source-ref/page/query、lexical/hybrid、resource budget 与人工 golden threshold | `planned` / `not-run` |
| VAL-WIKI-INCREMENTAL-001 | fixed old/new commits；add/delete/rename/dependency/no-op、byte reuse、partial failure、full rebuild recovery 与质量/成本 parity | `planned` / `not-run`；新 requirement/ADR Accepted 前不得宣称实现 |
| VAL-REMOTE-WORKER-DECISION-001 | reviewed threat/cost study + accept/reject ADR；数据边界、认证/传输、故障/更新、all-in-one UX 和文档同步 | `planned` / `not-run`；只验证决策，不验证 remote worker 实现 |

## 精确 source 命令

| 证据 | 命令 | 结果 |
| --- | --- | --- |
| Desktop full | `cd desktop && npm test -- --run` | `71890ee` [Actions 30611309112](https://github.com/fredgnr/local-context-forge/actions/runs/30611309112) success；历史本地 30 files / 245 pass / 7 skip |
| Web full | `cd web && npm test -- --run` | `fcca1e4`：7 files / 51 pass |
| Backend full | `cd backend && .venv/bin/pytest` | `71890ee` [Actions 30611309112](https://github.com/fredgnr/local-context-forge/actions/runs/30611309112) success；历史本地 322 pass / 1 skip |
| QMD worker | `cd desktop/workers/qmd && npm test` | `8eedd7e`：8 pass / 3 skip |
| Host Runner | `backend/.venv/bin/python -m unittest discover -s host_runner/tests -t .` | `8eedd7e`：8 pass |
| MCP ownership/onboarding core | `cd desktop && ./node_modules/.bin/vitest run tests/mcpTargetOwnership.test.ts tests/mcpOnboarding.test.ts tests/mcpCompanion.test.ts` | `fcca1e4`：3 files / 37 pass |
| MCP onboarding Desktop | `cd desktop && ./node_modules/.bin/vitest run tests/provider-discovery.test.ts tests/provider-policy.test.ts tests/mcpTargetOwnership.test.ts tests/mcpOnboarding.test.ts tests/ipc.test.ts tests/preload.test.ts` | `fcca1e4`：6 files / 73 pass |
| MCP bridge Desktop | `cd desktop && ./node_modules/.bin/vitest run tests/mcpBridge.test.ts tests/mcpCompanion.test.ts tests/mcpCompanionPackaging.test.ts tests/mcpSidecarRead.test.ts` | `fcca1e4`：4 files / 15 pass / 7 skip |
| MCP onboarding Web | `cd web && ./node_modules/.bin/vitest run src/McpOnboarding.test.tsx src/App.test.tsx src/desktopBridge.test.ts` | `fcca1e4`：3 files / 25 pass |
| Update Desktop | `cd desktop && ./node_modules/.bin/vitest run tests/updateClient.test.ts tests/updateIpc.test.ts tests/updateTrustPackaging.test.ts tests/preload.test.ts tests/beforePack.test.ts` | `fcca1e4`：5 files / 42 pass |
| Update Web | `cd web && ./node_modules/.bin/vitest run src/App.test.tsx src/desktopBridge.test.ts` | `fcca1e4`：2 files / 19 pass |
| Release policy Desktop | `cd desktop && ./node_modules/.bin/vitest run tests/releasePolicy.test.ts tests/updateTrustPackaging.test.ts` | `71890ee` source CI success；历史 focused 2 files / 18 pass |
| Release policy Backend | `backend/.venv/bin/pytest -q tests/backend/test_desktop_release_bootstrap.py tests/backend/test_desktop_release_workflow_policy.py` | `71890ee` source CI success；历史 focused 22 pass |
| Two-stage release promotion | 上述 Desktop/Backend release policy commands；YAML parse；17 个 workflow `run` script `bash -n` | `71890ee` source contract `pass`；真实 settings/tag/Draft/promotion `not-run` |
| Local source Desktop core | `cd desktop && ./node_modules/.bin/vitest run tests/localSourceGrants.test.ts tests/localSourcePicker.test.ts tests/localSourcePolicy.test.ts tests/ipc.test.ts` | `8eedd7e` 历史基线：4 files / 30 pass |
| Local source Backend | `cd backend && .venv/bin/pytest -q ../tests/backend/test_source_security.py ../tests/backend/test_desktop_transport.py` | `8eedd7e`：103 pass / 1 skip |

Desktop release policy 和 Backend bootstrap/workflow policy 的公开代码证据来自
`71890ee` / [Actions 30611309112](https://github.com/fredgnr/local-context-forge/actions/runs/30611309112)；
Web、MCP、update client、QMD、Host Runner 与 local-source 继续继承表中列明的 exact
checkpoint。R11 是文档/治理变更，不能把尚未提交的工作树当成新的实现证据。表中的 7 个
Desktop/bridge 条件 skip 以及 Backend/QMD AF_UNIX/native/model skip 不得省略或折算为
pass。packaged/physical 门禁继续 `not-run`。

release source contract 通过不证明 GitHub 控制面或物理发行：两个 Environment、三组 ruleset、
Immutable Releases、真实签名/promotion 和物理 Mac 证据继续 `not-run`。repository owner、
contents writer/可改 workflow 的主体与 settings admin 仍是根信任；GitHub Draft 无资产 CAS，
verify→fixed-ID PATCH 竞态只能后验检测。当前结论是
**W01 closed / W02 PR #21 first through fourth remediations failed and superseded after independent NO-GO /
fifth exact candidate not-run / release NO-GO**。

## ADR—迭代—验证映射

| ADR | 迭代任务 | 主要验证 |
| --- | --- | --- |
| [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md) | ITER-0001/T02–T05；ITER-0002/R01–R05 | VAL-P1-*、VAL-TRUST-001、VAL-PY/QMD/CLI/MCP |
| [ADR-0002](../adr/0002-uds-startup-token-protocol.md) | ITER-0001/T03、T05；ITER-0002/R02–R04、R08、R10 | VAL-IPC-001、VAL-MCP-001、VAL-LOCAL-SOURCE-002 |
| [ADR-0003](../adr/0003-macos-release-signing-update-policy.md) | ITER-0004/P01–P05；ITER-0005/U01–U05；ITER-0002/R09 | VAL-RELEASE-POLICY-001、VAL-INSTALL/RELEASE/SECRET/UPDATE |
| [ADR-0004](../adr/0004-runtime-paths-legacy-data-migration.md) | ITER-0003/D01–D05；历史 ITER-0006/L01–L05 | VAL-DATA/MODEL；legacy migration/lifecycle 由 ADR-0015 取代 |
| [ADR-0005](../adr/0005-provider-attempt-execution-boundary.md) | ITER-0002/R05、R08 | VAL-CLI-001、VAL-MCP-ONBOARD-001 |
| [ADR-0006](../adr/0006-dulwich-product-git-boundary.md) | ITER-0002/R01、R10 | VAL-GIT-001、VAL-PY-001、VAL-LOCAL-SOURCE-002 |
| [ADR-0007](../adr/0007-qmd-retrieval-broker-runtime.md) | ITER-0002/R03、R07 | VAL-QMD-001、VAL-IPC-001、VAL-QMD-EMBED-001 |
| [ADR-0008](../adr/0008-mcp-companion-main-bridge.md) | ITER-0002/R04、R08 | VAL-MCP-001、VAL-TRUST-001 |
| [ADR-0009](../adr/0009-bundled-runtime-provenance.md) | ITER-0002/R02–R04、R06 | VAL-PY/QMD/PACK |
| [ADR-0010](../adr/0010-qmd-local-embedding-profile.md) | ITER-0002/R07 | VAL-QMD/IPC/MODEL-EMBED-001 |
| [ADR-0011](../adr/0011-main-owned-signed-update-client.md) | ITER-0002/R09；ITER-0005 | VAL-UPDATE-CLIENT-001、VAL-TRUST-001、VAL-UPDATE-001 |
| [ADR-0012](../adr/0012-local-repository-picker-opaque-grants.md) | ITER-0002/R10 | VAL-LOCAL-SOURCE-001、002、003 |
| [ADR-0013](../adr/0013-codex-mcp-onboarding-signed-cli-discovery.md) | ITER-0002/R08 | VAL-MCP-ONBOARD-001、VAL-MCP-001、VAL-TRUST-001 |
| [ADR-0014](../adr/0014-two-stage-desktop-release-promotion.md) | ITER-0002/R09；ITER-0004/P06 | VAL-RELEASE-POLICY-001、VAL-RELEASE-PROMOTION-001、VAL-SECRET/RELEASE-001 |
| [ADR-0015](../adr/0015-electron-only-legacy-retirement.md) | ITER-0002/R12；历史 ITER-0007/E01–E07；deletion sequencing 由 ADR-0016 部分取代 | VAL-LEGACY-SCOPE-001、VAL-ELECTRON-CUTOVER-001、VAL-LEGACY-ABSENCE-001 |
| [ADR-0016](../adr/0016-pre1-incremental-retirement-engineering-package.md) | ITER-0002/R13；ITER-0008/I01–I09；W01–W16 | VAL-PRE1-SEQUENCE-001、VAL-PACKAGED-SMOKE-001、六个 slice VAL、VAL-ENGINEERING-PACKAGE-001、W13/W16 cutover/absence、VAL-RELEASE-CONTINUITY-001 |

## 变更 ledger

本节按纵切累积，不能脱离对应 iteration、PR/commit 和日期理解。新的实现/文档纵切应追加
一行，不再把跨多个提交的集合称作“本次工作树”。

| 变更范围 | 目的 | 需求/任务 | 验证 |
| --- | --- | --- | --- |
| `desktop/workers/qmd/**`、`desktop/src/main/{qmdClient,qmdSupervisor,retrievalBroker}.ts`、`backend/app/{desktop_retrieval,service,version}.py`、R07 | local embedding profile、rebuild CAS、hybrid/fallback | REQ-QMD/MODEL；R07 | VAL-QMD/IPC/MODEL-EMBED source 子门禁 |
| `desktop/companion/src/{bridgeClient,index}.ts`、`desktop/src/{mcpProtocol,main/mcpBridge,main/mcpSidecarRead}.ts`、`desktop/tests/{mcpBridge,mcpCompanion,mcpCompanionPackaging,mcpSidecarRead}.test.ts`、[protocol](mcp-companion-protocol.md) | 两工具只读桥、per-launch private rendezvous、ownership marker 在 bridge 前删除 | REQ-MCP/IPC/TRUST；R04/R08 | VAL-MCP-001 source 子门禁 |
| `desktop/src/main/{mcpOnboarding,mcpTargetOwnership}.ts`、`desktop/src/main/providers/{contracts,discovery,environment,execution,preflight,providerResolver}.ts`、`desktop/src/mcpProtocol.ts`、IPC/preload、`desktop/tests/{mcpTargetOwnership,mcpOnboarding,ipc,preload}.test.ts`、`web/src/{McpOnboarding,McpOnboarding.test,App,App.test,desktopBridge,desktopBridge.test}.ts*`、R08 | Main-owned Codex 配置、四类签名 discovery、per-scope ledger/marker/exact target ownership、bundle chain 和 UI | REQ-MCP-ONBOARD/CLI/TRUST；R08 | VAL-MCP-ONBOARD-001 source 子门禁 |
| `desktop/src/main/{updateClient,updateIpc,index}.ts`、contracts/preload、`desktop/tests/{updateClient,updateIpc,updateTrustPackaging,preload,beforePack}.test.ts`、`web/src/{App,App.test,desktopBridge,desktopBridge.test}.ts*`、ADR-0011/R09 | signed manifest、私有 cache、脱敏 IPC、verified DMG 与显式固定 Release 页面出口 | REQ-UPDATE/TRUST；R09 | VAL-UPDATE-CLIENT-001；VAL-UPDATE-001 `not-run` |
| `.github/workflows/desktop-release.yml`、`.github/desktop-release-notes.md`、`tools/bootstrap_desktop_release_keys.py`、`desktop/scripts/{auditUpdateTrust,beforePack,prepareRelease}.cjs`、runtime locks、[runbook](desktop-release.md) | tag-only `macos-signing`；Draft/main promotion 不配置 Environment/repository release secret 或长期签名凭据，但使用最小权限的短期 `GITHUB_TOKEN`；credential generation、Environment/ruleset/Immutable Releases bootstrap contract | REQ-RELEASE/SECRET/RELEASE-GOV/INSTALL；R09 | VAL-RELEASE-POLICY-001 source；真实 settings/physical gates `not-run` |
| `.github/workflows/desktop-release.yml`、`desktop/scripts/prepareRelease.cjs`、`desktop/tests/releasePolicy.test.ts`、Backend workflow policy tests、[ADR-0014](../adr/0014-two-stage-desktop-release-promotion.md)、[runbook](desktop-release.md) | desktop tag path 停止在 Draft；同 tag GHCR 独立非原子；`--ref main` trusted verifier 使用隔离 worktree/fresh peel、PATCH 前 fresh `origin/main` promotion order 和 fixed Release ID，拒绝 published 预状态，并做 post-publish attestation/immutable/完整集合复核 | REQ-RELEASE-002/SECRET/RELEASE-GOV；R09、ITER-0004/P06–P07 | VAL-RELEASE-PROMOTION-001 source；真实 promotion `not-run` |
| `desktop/src/main/{localSourceGrants,localSourcePicker,localSourcePolicy,ipc,index,sidecar}.ts`、preload/contracts/tests、`backend/app/{cli,config,source}.py`、`tests/backend/{test_source_security,test_desktop_transport}.py`、`web/src/{App,App.test,desktopBridge,desktopBridge.test}.ts*`、ADR-0012/R10 | opaque grant、Main/Backend path policy、无凭据本地仓库 UX | REQ-LOCAL-SOURCE/GIT/IPC/TRUST；R10 | VAL-LOCAL-SOURCE-001/002；003 `not-run` |
| `README.md`、`SECURITY.md`、`desktop/README.md`、`docs/{README,00-overview,03-hardware-deployment,04-quickstart,06-api-and-mcp,10-security,14-all-in-one-macos,16-electron-desktop-guide}.md`、`docs/adr/{README,0003-*,0010-* 至 0013-*}.md`、`docs/development/**` | 同步用户入口、安全边界、决策、迭代、runbook、协议和证据链 | ITER-0002/R07–R10 | VAL-GOV-001 |
| `README.md`、`TODO.md`、`AGENTS.md`、`CONTRIBUTING.md`、`.github/PULL_REQUEST_TEMPLATE.md`、`docs/{README,17-system-design,18-deployment-operations}.md`、`docs/development/{status,contributor-handbook,todo,evidence/**,roadmap,traceability,iterations/**}.md`、component/legacy docs、Makefile help | PR #7/#8/#17 后的系统设计、部署、开发、TODO、evidence 和命令边界交接 | REQ-GOV-001、REQ-DOC-001；R11；基线 `main@fb8bbbc` | VAL-DOC-HANDOFF-001、VAL-GOV-001；最终 PR CI 待记录 |
| `docs/adr/0015-*`、`docs/development/{legacy-retirement,todo,roadmap,status,traceability,iterations/0002-r12-*,iterations/0006-*,iterations/0007-*}.md`、`README.md`、`docs/17-system-design.md` | 接受 Electron-only/pre-1.0 breaking policy，冻结 remove/retain/split 与后续 destruction gates；本纵切不删除代码 | REQ-ELECTRON-ONLY-001、REQ-PRE1-BREAKING-001；R12/ITER-0007 | [`64ec3c2` VAL-LEGACY-SCOPE-001](evidence/VAL-LEGACY-SCOPE-001/2026-07-31-64ec3c2.md) `pass`；最终 PR CI 待记录 |
| `docs/adr/0016-*`、`docs/development/{work-plan,legacy-retirement,todo,roadmap,status,traceability,iterations/0002-r13-*,iterations/0007-*,iterations/0008-*}.md`、authority docs/skills、`Makefile`、`tools/check_pre1_work_plan.py`、`tools/tests/test_check_pre1_work_plan.py` | 接受 minimal smoke → incremental slices → cleaned engineering package → final gates → production release 的新顺序；本纵切不删除 runtime、不实现 package、不改 GitHub | REQ-PRE1-SEQUENCING/PACKAGED-SMOKE/LEGACY-SLICE/ENGINEERING-PACKAGE-001；R13/ITER-0008 | 规划 source 纳入 W01 checkpoint；runtime/packaged/physical/settings/release gate 均保持 `not-run` |
| `.github/{ci/source-coverage.json,workflows/desktop-ci.yml}`、`Makefile`、`tools/{check_ci_coverage,check_w01_evidence,render_source_coverage_evidence,run_qmd_source_ci}.py`、QMD network trap/package script、W01 docs/evidence | 历史 W01 source aggregate、旧 C1→C2 closeout 与 premature canonical output；不实现 W02/legacy deletion/package/control plane | TODO-PRE1-SEQUENCING/GOV-EVIDENCE/CI-COVERAGE-001；R13-06；PR #20 | 旧 checkpoint `8573f608…` / run 30927840380 与 final `2b762946…` / run 30929070329 technical `pass`；独立验收 `fail`，canonical activation `not-eligible`；旧 artifacts 保留 |
| `.github/{ci/source-coverage.json,workflows/desktop-ci.yml}`、`tools/{check_ci_coverage,check_w01_evidence,render_source_coverage_evidence,render_source_coverage_provenance,run_qmd_source_ci}.py`、schema v2、QMD trap/tests 与 W01 lifecycle docs | W01 remediation：historical evidence 与 current HEAD 解耦；payload/provenance 无自引用；PR/branch/main lifecycle 分相；QMD scope 诚实 | TODO-PRE1-SEQUENCING/GOV-EVIDENCE/CI-COVERAGE-001；R13-07；PR #20 remediation | Checkpoint A `f4074a31…` / run `30980342634` PR/source `pass`；payload `8919891304` / provenance `8919891597`；independent acceptance `pending`；canonical-main source `not-run`；canonical activation `blocked`；W02 locked |
| `docs/development/evidence/W02/2026-08-05-entry.md`、R13/TODO/status/traceability/iteration indexes、`tools/check_pre1_work_plan.py` 与 tests | 追加 W01 外部 closure，不改写历史 W01 JSON；把 current authority 迁移到 W02 entry | TODO-PRE1-SEQUENCING/GOV-EVIDENCE/CI-COVERAGE-001；R13-08；PR #20 accepted remediation | final `36885e04…` / main `1786255b…` / tree `1b9f3a34…`；run `30986208251` five jobs success；W01 tasks `done`，R13 `completed` |
| `.github/workflows/{packaged-smoke,desktop-release,container-images}.yml` 的 engineering assembly/formal build/legacy container continuity jobs、`web/Dockerfile`、exact Git checker、exact Node installer/builders、Python build/auditor、shared renderer/Python consumers 与 schemas、engineering-smoke staging/audit scripts、`desktop/src/{contracts,main/distribution,main/index,main/updateClient}.ts`、`web/src/desktopBridge.ts`、packaging/container policy tests 与 W02 governance/evidence | W02 不触发 formal 发布；共享 build provenance 同步加固，legacy container 修复保持 PR no-login/no-push 与 dual-platform target，但 formal Draft/promotion、distribution/publish semantics、production credentials/settings 均保持既有状态；本 Work 不启动 assembled App | TODO-PACKAGED-SMOKE-001；ITER-0008/I01；W02-A implementation stage（非稳定 ID） | old exact `08137c7…` static run technical `pass`；reviewed `8c5fd232…` / tree `785f4656…` independent `NO-GO`；first `9f7d5d…` / `ea8e62…`、second `9ecf0e…` / `ee8271…`、third `2665ec…` / `c3cd17…`、fourth `c2be665f…` / `f90b527b…` remediations technical `fail` / `superseded`；fourth source/Containers success、Engineering inner-build/cleanup fail、no publish；fifth exact candidate `not-run`；formal package/App/credentials/publish/promotion、packaged launch 与 VAL-PACKAGED-SMOKE-001 均 `not-run`；W10/W11 locked |

后续变更应追加或更新本节，不删除已发布证据；实现路径变化时在同一变更中修正 owned paths。

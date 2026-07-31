# Electron 迁移可追溯矩阵

## 坐标与规则

- 上游基线：`main@5d95e58cefa1c94b5c9ac8dd681671e2dfd6d8dd`
- 已发布 P1 检查点：`agent/electron-desktop-foundation@7e4524f`
- 当前公开 source 检查点：`agent/electron-bundled-runtimes@fcca1e4`
- 活动父迭代：[ITER-0002](iterations/0002-bundled-runtimes.md)
- 路线图：[P0–P7](roadmap.md)

每个行为变化必须形成以下链路：

```text
REQ -> ADR -> ITER/task -> owned paths -> VAL -> evidence
```

`Accepted` ADR 表示决策已确定，不表示实现或验证已完成。验证只有 `pass`、`fail`、
`not-run` 三种结果；`source 子门禁 pass` 不能替代要求 packaged/physical 环境的完整门禁。
R07–R10 是 ITER-0002 的追加记录，继承父迭代 `in-progress` 状态。

## 需求与映射

| 需求 ID | 验收目标 | 决策 | 任务 | Owned paths | 验证 | 当前状态 |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-PLATFORM-001 | macOS Apple Silicon Electron all-in-one，React renderer | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md) | ITER-0001/T02；ITER-0004/P01、P05 | `desktop/**`、`web/src/**` | VAL-P1-SOURCE-001、VAL-INSTALL-001 | source `pass`；packaged/安装 `not-run` |
| REQ-TRUST-001 | Main 是信任边界，renderer 只有类型化最小能力，不得到路径/argv/token/key | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md)、[ADR-0011](../adr/0011-main-owned-signed-update-client.md)、[ADR-0012](../adr/0012-local-repository-picker-opaque-grants.md)、[ADR-0013](../adr/0013-codex-mcp-onboarding-signed-cli-discovery.md) | ITER-0001/T02、T04；R08–R10 | `desktop/src/main/**`、`desktop/src/preload/**`、`web/src/**` | VAL-TRUST-001、VAL-MCP-ONBOARD-001、VAL-UPDATE-CLIENT-001、VAL-LOCAL-SOURCE-001 | source contracts `pass`；packaged trust `not-run` |
| REQ-PY-001 | CPython 3.13.14 PyInstaller `onedir` 随应用交付且可审计 | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md)、[ADR-0009](../adr/0009-bundled-runtime-provenance.md) | ITER-0002/R02 | `backend/packaging/**`、`tools/*python_sidecar*`、`desktop/generated/sidecar/**`、`desktop/resources/sidecar/**` | VAL-PY-001、VAL-PACK-001 | source build/audit contract `pass`；clean-user `not-run` |
| REQ-GIT-001 | packaged 产品不调用系统 Git，snapshot/Wiki 保持安全与回滚语义 | [ADR-0006](../adr/0006-dulwich-product-git-boundary.md)、[ADR-0012](../adr/0012-local-repository-picker-opaque-grants.md) | ITER-0002/R01、R10 | `backend/app/{source,wiki}.py`、source/Wiki tests | VAL-GIT-001、VAL-PY-001、VAL-LOCAL-SOURCE-002 | source `pass`；packaged full gate `not-run` |
| REQ-LOCAL-SOURCE-001 | picker 以一次性 opaque grant 导入预先 clone 的本地/私有仓库，不管理凭据 | [ADR-0012](../adr/0012-local-repository-picker-opaque-grants.md) | [ITER-0002/R10](iterations/0002-r10-local-repositories.md) | `desktop/src/main/localSource*`、`backend/app/{cli,config,source}.py`、`web/src/{App,desktopBridge}.ts*` | VAL-LOCAL-SOURCE-001、002、003 | Main/Backend/Web source `pass`；physical Mac `not-run` |
| REQ-QMD-001 | QMD 使用内置 Node 22.23.2 worker，经 Main broker 提供 revision-safe lexical/hybrid retrieval | [ADR-0007](../adr/0007-qmd-retrieval-broker-runtime.md)、[ADR-0009](../adr/0009-bundled-runtime-provenance.md)、[ADR-0010](../adr/0010-qmd-local-embedding-profile.md) | ITER-0002/R03、[R07](iterations/0002-r07-qmd-embeddings.md) | `desktop/workers/qmd/**`、`desktop/src/main/qmd*`、`backend/app/desktop_retrieval.py` | VAL-QMD-001、VAL-QMD-EMBED-001、VAL-PACK-001 | source contracts `pass`；native/model full gates `not-run` |
| REQ-IPC-001 | Main 与 sidecar/worker/companion 使用私有 UDS、per-launch identity 与不重放 token | [ADR-0002](../adr/0002-uds-startup-token-protocol.md)、[ADR-0008](../adr/0008-mcp-companion-main-bridge.md)、[ADR-0013](../adr/0013-codex-mcp-onboarding-signed-cli-discovery.md) | ITER-0001/T03；ITER-0002/R03–R04、R08、R10 | `desktop/src/main/**`、`desktop/companion/**`、`backend/app/{cli,desktop_session,factory}.py` | VAL-IPC-001、VAL-IPC-EMBED-001、VAL-MCP-001、VAL-LOCAL-SOURCE-002 | source/macOS bind 子门禁 `pass`；packaged lifecycle `not-run` |
| REQ-COMPAT-001 | Desktop bridge fail closed，保留 browser/Docker HTTP transport | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md) | ITER-0001/T04；R07–R10 regressions | `web/src/{api,desktopBridge,App}.ts*`、Web tests | VAL-P1-REGRESSION-001 | `pass`（Web 51） |
| REQ-VERSION-001 | 产品、协议与 schema 版本由 manifest 跨层同步 | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md)、[ADR-0002](../adr/0002-uds-startup-token-protocol.md) | ITER-0001/T05；ITER-0002/R06 | `runtime/version.json`、`backend/app/version.py`、`desktop/package.json`、`tools/check_version_sync.py` | VAL-P1-CONTRACT-001、VAL-PACK-001 | source `pass`；formal package `not-run` |
| REQ-CI-001 | 普通 source CI 最小权限且不能读取 release secret | [ADR-0003](../adr/0003-macos-release-signing-update-policy.md) | ITER-0001/T05；R09 | `.github/workflows/{desktop-ci,desktop-release}.yml` | VAL-CI-001、VAL-RELEASE-POLICY-001、VAL-SECRET-001 | source policy `pass`；Environment setting proof `not-run` |
| REQ-CLI-001 | Codex 默认；Cursor 仅经同意且在 spawn 前明确失败时替代，commit 后不 fallback/replay | [ADR-0005](../adr/0005-provider-attempt-execution-boundary.md)、[ADR-0013](../adr/0013-codex-mcp-onboarding-signed-cli-discovery.md) | ITER-0002/R05、R08 | `backend/app/**`、`desktop/src/main/providers/**`、provider UI/tests | VAL-CLI-001、VAL-MCP-ONBOARD-001 | source policy/attempt `pass`；真实 provider `not-run` |
| REQ-MCP-001 | 内置 stdio companion 只公开两个 Context7 兼容工具，经 Main 私有只读桥 | [ADR-0008](../adr/0008-mcp-companion-main-bridge.md)、[ADR-0013](../adr/0013-codex-mcp-onboarding-signed-cli-discovery.md) | ITER-0002/R04、[R08](iterations/0002-r08-mcp-onboarding.md) | `desktop/companion/**`、`desktop/src/{mcpProtocol,main/mcp*}.ts`、[protocol](mcp-companion-protocol.md) | VAL-MCP-001、VAL-MCP-ONBOARD-001 | source 子门禁 `pass`；packaged Codex/tools `not-run` |
| REQ-MCP-ONBOARD-001 | Main 以固定 argv、安全 CLI discovery 和 scoped target ownership 配置 Codex MCP | [ADR-0013](../adr/0013-codex-mcp-onboarding-signed-cli-discovery.md) | [ITER-0002/R08](iterations/0002-r08-mcp-onboarding.md) | `desktop/src/main/{mcpOnboarding,mcpTargetOwnership}.ts`、`desktop/src/mcpProtocol.ts`、`desktop/companion/**`、providers/preload/IPC、`web/src/McpOnboarding*` | VAL-MCP-ONBOARD-001、VAL-MCP-001 | Desktop/Web source `pass`；真实 OpenAI 签名 packaged gate `not-run` |
| REQ-PACK-001 | bundled runtime 来源、文件、native closure、许可证和输入摘要可复核，篡改 fail closed | [ADR-0009](../adr/0009-bundled-runtime-provenance.md) | ITER-0002/R02–R04、R06 | runtime schemas、build/audit scripts、Electron `beforePack` | VAL-PACK-001 | source tamper/build contracts `pass`；formal arm64 staging `not-run` |
| REQ-INSTALL-001 | 默认 DMG；目标机无需 Docker/Homebrew/Python/Node/Git/ctags | [ADR-0003](../adr/0003-macos-release-signing-update-policy.md) | ITER-0004/P01、P05；R09 foundation | packaging/workflow、[release runbook](desktop-release.md) | VAL-INSTALL-001、VAL-RELEASE-POLICY-001 | source policy `pass`；clean-user `not-run` |
| REQ-MODEL-001 | 模型按需下载、校验、CAS 激活；失败确定性回 lexical | [ADR-0004](../adr/0004-runtime-paths-legacy-data-migration.md)、[ADR-0010](../adr/0010-qmd-local-embedding-profile.md) | ITER-0003/D04–D05；R07 foundation | QMD worker、retrieval broker、model manager/cache | VAL-MODEL-001、VAL-MODEL-EMBED-001 | source race/fallback `pass`；真实 download/native `not-run` |
| REQ-RELEASE-001 | 自签名，明确未 notarize、未 hardened；exact tag/provenance/asset set | [ADR-0003](../adr/0003-macos-release-signing-update-policy.md)、[ADR-0011](../adr/0011-main-owned-signed-update-client.md) | ITER-0004/P01–P03；[R09](iterations/0002-r09-signed-update-client.md) | `.github/workflows/desktop-release.yml`、`desktop/scripts/prepareRelease.cjs`、release docs | VAL-RELEASE-POLICY-001、VAL-RELEASE-001 | source policy `pass`；真实 signed artifact `not-run` |
| REQ-SECRET-001 | release secret 仅在 protected `macos-release` Environment | [ADR-0003](../adr/0003-macos-release-signing-update-policy.md) | ITER-0004/P02–P04；R09 | release workflow、`tools/bootstrap_desktop_release_keys.py` | VAL-RELEASE-POLICY-001、VAL-SECRET-001 | source workflow `pass`；repository Environment proof `not-run` |
| REQ-UPDATE-001 | 独立签名 check/download；用户确认 verified DMG；signed unavailable/error 时仅显式固定 Release 页面出口；automatic apply 需物理 gate | [ADR-0003](../adr/0003-macos-release-signing-update-policy.md)、[ADR-0011](../adr/0011-main-owned-signed-update-client.md) | ITER-0005/U01–U05；[R09](iterations/0002-r09-signed-update-client.md) | `desktop/src/main/update*`、preload/contracts、Web UI、release assets | VAL-UPDATE-CLIENT-001、VAL-UPDATE-001 | source client `pass`；真实 feed/0.0.1→0.0.2 `not-run` |
| REQ-DATA-001 | 标准 macOS 路径；旧数据可盘点、原子迁移、回滚 | [ADR-0004](../adr/0004-runtime-paths-legacy-data-migration.md) | ITER-0003/D01–D03 | runtime path/migration modules | VAL-DATA-001 | `planned` / `not-run` |
| REQ-LEGACY-001 | Docker 暂留 legacy，迁移成功且另行决策后才弃用 | [ADR-0004](../adr/0004-runtime-paths-legacy-data-migration.md) | ITER-0006/L01–L05 | existing Docker paths/docs | VAL-LEGACY-001 | `planned` / `not-run` |

## 验证目录

| 验证 ID | 所需证据 / 最低环境 | 当前结果 |
| --- | --- | --- |
| VAL-GOV-001 | repository checkout；所有新增/修改 Markdown 相对链接检查 | `pass`（`python tools/check_markdown_links.py`：66 files；当前工作树） |
| VAL-GOV-002 | repository checkout；两个项目 `SKILL.md` 结构 | `pass`（继承已发布检查点） |
| VAL-P1-CONTRACT-001 | Linux source；Main/preload/Web/sidecar 纯源码合同 | `pass`（继承 ITER-0001） |
| VAL-P1-SOURCE-001 | Linux/macOS source；真实 AF_UNIX bind 和 source jobs | `pass`（[Actions 30550023917](https://github.com/fredgnr/local-context-forge/actions/runs/30550023917)） |
| VAL-P1-REGRESSION-001 | source checkout；Backend/Desktop/Web/Host Runner 全量 | `pass`（Desktop/Web `fcca1e4`：235/7 skip、51；Backend/Host `8eedd7e`：313/1 skip、8） |
| VAL-CI-001 | public GitHub Actions；普通 job 最小权限 | `pass`（继承 Actions；release policy source 另列） |
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
| VAL-RELEASE-POLICY-001 | source checkout；tag/provenance/secret/asset/draft policy | `pass`（Desktop 2 files / 20；Backend 13；`8eedd7e`） |
| VAL-UPDATE-CLIENT-001 | source checkout；signature/schema/redirect/cache/IPC/DMG/Release-page contracts | `pass`（Desktop 5 files / 42；Web 2 files / 19；`fcca1e4`） |
| VAL-LOCAL-SOURCE-001 | Desktop/Web source；grant/path/renderer negative matrix | `pass`（full Desktop 235/7 skip、Web 51：`fcca1e4`；focused 4 files / 30：`8eedd7e`） |
| VAL-LOCAL-SOURCE-002 | Backend source/desktop transport；argv roots/owner/sensitive dirs | `pass`（focused 103 / 1 skip；full 313 / 1 skip；`8eedd7e`） |
| VAL-LOCAL-SOURCE-003 | physical packaged macOS；home/外置卷/private/move/delete/restart | `not-run` |
| VAL-INSTALL-001 | clean physical Apple Silicon；DMG/Gatekeeper/no external runtimes | `not-run` |
| VAL-RELEASE-001 | protected release；真实 DMG arch/content/sign identity/limits | `not-run` |
| VAL-SECRET-001 | public repo settings；fork/PR/ordinary jobs 无 Environment secret | `not-run`（workflow source policy `pass`） |
| VAL-UPDATE-001 | physical Apple Silicon；0.0.1 → 0.0.2 + failure DMG fallback | `not-run`；automatic apply disabled |
| VAL-MODEL-001 | packaged app；consent/offline/integrity/resume/atomic activation | `not-run` |
| VAL-DATA-001 | representative legacy copies；fresh/repeat/interrupt/corrupt/rollback | `not-run` |
| VAL-LEGACY-001 | physical migration rehearsal；原数据可恢复与退出评审 | `not-run` |

## 精确 source 命令

| 证据 | 命令 | 结果 |
| --- | --- | --- |
| Desktop full | `cd desktop && npm test -- --run` | `fcca1e4`：30 files / 235 pass / 7 skip |
| Web full | `cd web && npm test -- --run` | `fcca1e4`：7 files / 51 pass |
| Backend full | `cd backend && .venv/bin/pytest -q ../tests/backend` | `8eedd7e`：313 pass / 1 skip |
| QMD worker | `cd desktop/workers/qmd && npm test` | `8eedd7e`：8 pass / 3 skip |
| Host Runner | `backend/.venv/bin/python -m unittest discover -s host_runner/tests -t .` | `8eedd7e`：8 pass |
| MCP ownership/onboarding core | `cd desktop && ./node_modules/.bin/vitest run tests/mcpTargetOwnership.test.ts tests/mcpOnboarding.test.ts tests/mcpCompanion.test.ts` | `fcca1e4`：3 files / 37 pass |
| MCP onboarding Desktop | `cd desktop && ./node_modules/.bin/vitest run tests/provider-discovery.test.ts tests/provider-policy.test.ts tests/mcpTargetOwnership.test.ts tests/mcpOnboarding.test.ts tests/ipc.test.ts tests/preload.test.ts` | `fcca1e4`：6 files / 73 pass |
| MCP bridge Desktop | `cd desktop && ./node_modules/.bin/vitest run tests/mcpBridge.test.ts tests/mcpCompanion.test.ts tests/mcpCompanionPackaging.test.ts tests/mcpSidecarRead.test.ts` | `fcca1e4`：4 files / 15 pass / 7 skip |
| MCP onboarding Web | `cd web && ./node_modules/.bin/vitest run src/McpOnboarding.test.tsx src/App.test.tsx src/desktopBridge.test.ts` | `fcca1e4`：3 files / 25 pass |
| Update Desktop | `cd desktop && ./node_modules/.bin/vitest run tests/updateClient.test.ts tests/updateIpc.test.ts tests/updateTrustPackaging.test.ts tests/preload.test.ts tests/beforePack.test.ts` | `fcca1e4`：5 files / 42 pass |
| Update Web | `cd web && ./node_modules/.bin/vitest run src/App.test.tsx src/desktopBridge.test.ts` | `fcca1e4`：2 files / 19 pass |
| Release policy Desktop | `cd desktop && ./node_modules/.bin/vitest run tests/releasePolicy.test.ts tests/updateTrustPackaging.test.ts` | `8eedd7e` 历史基线：2 files / 20 pass |
| Release policy Backend | `cd backend && .venv/bin/pytest -q ../tests/backend/test_desktop_release_bootstrap.py ../tests/backend/test_desktop_release_workflow_policy.py` | `8eedd7e` 历史基线：13 pass |
| Local source Desktop core | `cd desktop && ./node_modules/.bin/vitest run tests/localSourceGrants.test.ts tests/localSourcePicker.test.ts tests/localSourcePolicy.test.ts tests/ipc.test.ts` | `8eedd7e` 历史基线：4 files / 30 pass |
| Local source Backend | `cd backend && .venv/bin/pytest -q ../tests/backend/test_source_security.py ../tests/backend/test_desktop_transport.py` | `8eedd7e`：103 pass / 1 skip |

Desktop/Web/MCP/update 的当前代码证据来自公开 checkpoint `fcca1e4`；其代码 tree 与本地
验证 tree 相同。Backend、QMD、Host Runner、release policy 与 local-source focused 证据没有
代码变化，明确继承 `8eedd7e`。表中的 7 个 Desktop/bridge 条件 skip 以及 Backend/QMD
AF_UNIX/native/model skip 不得省略或折算为 pass。packaged/physical 门禁继续 `not-run`。

## ADR—迭代—验证映射

| ADR | 迭代任务 | 主要验证 |
| --- | --- | --- |
| [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md) | ITER-0001/T02–T05；ITER-0002/R01–R05 | VAL-P1-*、VAL-TRUST-001、VAL-PY/QMD/CLI/MCP |
| [ADR-0002](../adr/0002-uds-startup-token-protocol.md) | ITER-0001/T03、T05；ITER-0002/R02–R04、R08、R10 | VAL-IPC-001、VAL-MCP-001、VAL-LOCAL-SOURCE-002 |
| [ADR-0003](../adr/0003-macos-release-signing-update-policy.md) | ITER-0004/P01–P05；ITER-0005/U01–U05；ITER-0002/R09 | VAL-RELEASE-POLICY-001、VAL-INSTALL/RELEASE/SECRET/UPDATE |
| [ADR-0004](../adr/0004-runtime-paths-legacy-data-migration.md) | ITER-0003/D01–D05；ITER-0006/L01–L05 | VAL-DATA/MODEL/LEGACY |
| [ADR-0005](../adr/0005-provider-attempt-execution-boundary.md) | ITER-0002/R05、R08 | VAL-CLI-001、VAL-MCP-ONBOARD-001 |
| [ADR-0006](../adr/0006-dulwich-product-git-boundary.md) | ITER-0002/R01、R10 | VAL-GIT-001、VAL-PY-001、VAL-LOCAL-SOURCE-002 |
| [ADR-0007](../adr/0007-qmd-retrieval-broker-runtime.md) | ITER-0002/R03、R07 | VAL-QMD-001、VAL-IPC-001、VAL-QMD-EMBED-001 |
| [ADR-0008](../adr/0008-mcp-companion-main-bridge.md) | ITER-0002/R04、R08 | VAL-MCP-001、VAL-TRUST-001 |
| [ADR-0009](../adr/0009-bundled-runtime-provenance.md) | ITER-0002/R02–R04、R06 | VAL-PY/QMD/PACK |
| [ADR-0010](../adr/0010-qmd-local-embedding-profile.md) | ITER-0002/R07 | VAL-QMD/IPC/MODEL-EMBED-001 |
| [ADR-0011](../adr/0011-main-owned-signed-update-client.md) | ITER-0002/R09；ITER-0005 | VAL-UPDATE-CLIENT-001、VAL-TRUST-001、VAL-UPDATE-001 |
| [ADR-0012](../adr/0012-local-repository-picker-opaque-grants.md) | ITER-0002/R10 | VAL-LOCAL-SOURCE-001、002、003 |
| [ADR-0013](../adr/0013-codex-mcp-onboarding-signed-cli-discovery.md) | ITER-0002/R08 | VAL-MCP-ONBOARD-001、VAL-MCP-001、VAL-TRUST-001 |

## 本次变更映射

| 变更范围 | 目的 | 需求/任务 | 验证 |
| --- | --- | --- | --- |
| `desktop/workers/qmd/**`、`desktop/src/main/{qmdClient,qmdSupervisor,retrievalBroker}.ts`、`backend/app/{desktop_retrieval,service,version}.py`、R07 | local embedding profile、rebuild CAS、hybrid/fallback | REQ-QMD/MODEL；R07 | VAL-QMD/IPC/MODEL-EMBED source 子门禁 |
| `desktop/companion/src/{bridgeClient,index}.ts`、`desktop/src/{mcpProtocol,main/mcpBridge,main/mcpSidecarRead}.ts`、`desktop/tests/{mcpBridge,mcpCompanion,mcpCompanionPackaging,mcpSidecarRead}.test.ts`、[protocol](mcp-companion-protocol.md) | 两工具只读桥、per-launch private rendezvous、ownership marker 在 bridge 前删除 | REQ-MCP/IPC/TRUST；R04/R08 | VAL-MCP-001 source 子门禁 |
| `desktop/src/main/{mcpOnboarding,mcpTargetOwnership}.ts`、`desktop/src/main/providers/{contracts,discovery,environment,execution,preflight,providerResolver}.ts`、`desktop/src/mcpProtocol.ts`、IPC/preload、`desktop/tests/{mcpTargetOwnership,mcpOnboarding,ipc,preload}.test.ts`、`web/src/{McpOnboarding,McpOnboarding.test,App,App.test,desktopBridge,desktopBridge.test}.ts*`、R08 | Main-owned Codex 配置、四类签名 discovery、per-scope ledger/marker/exact target ownership、bundle chain 和 UI | REQ-MCP-ONBOARD/CLI/TRUST；R08 | VAL-MCP-ONBOARD-001 source 子门禁 |
| `desktop/src/main/{updateClient,updateIpc,index}.ts`、contracts/preload、`desktop/tests/{updateClient,updateIpc,updateTrustPackaging,preload,beforePack}.test.ts`、`web/src/{App,App.test,desktopBridge,desktopBridge.test}.ts*`、ADR-0011/R09 | signed manifest、私有 cache、脱敏 IPC、verified DMG 与显式固定 Release 页面出口 | REQ-UPDATE/TRUST；R09 | VAL-UPDATE-CLIENT-001；VAL-UPDATE-001 `not-run` |
| `.github/workflows/desktop-release.yml`、`.github/desktop-release-notes.md`、`tools/bootstrap_desktop_release_keys.py`、`desktop/scripts/{auditUpdateTrust,beforePack,prepareRelease}.cjs`、runtime locks、[runbook](desktop-release.md) | protected tag build、credential generation、完整资产/draft verification | REQ-RELEASE/SECRET/INSTALL；R09 | VAL-RELEASE-POLICY-001；physical gates `not-run` |
| `desktop/src/main/{localSourceGrants,localSourcePicker,localSourcePolicy,ipc,index,sidecar}.ts`、preload/contracts/tests、`backend/app/{cli,config,source}.py`、`tests/backend/{test_source_security,test_desktop_transport}.py`、`web/src/{App,App.test,desktopBridge,desktopBridge.test}.ts*`、ADR-0012/R10 | opaque grant、Main/Backend path policy、无凭据本地仓库 UX | REQ-LOCAL-SOURCE/GIT/IPC/TRUST；R10 | VAL-LOCAL-SOURCE-001/002；003 `not-run` |
| `README.md`、`SECURITY.md`、`desktop/README.md`、`docs/{README,00-overview,03-hardware-deployment,04-quickstart,06-api-and-mcp,10-security,14-all-in-one-macos,16-electron-desktop-guide}.md`、`docs/adr/{README,0003-*,0010-* 至 0013-*}.md`、`docs/development/**` | 同步用户入口、安全边界、决策、迭代、runbook、协议和证据链 | ITER-0002/R07–R10 | VAL-GOV-001 |

后续变更应追加或更新本节，不删除已发布证据；实现路径变化时在同一变更中修正 owned paths。

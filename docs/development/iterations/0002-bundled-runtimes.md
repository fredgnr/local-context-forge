# ITER-0002：Bundled runtimes

- 状态：`in-progress`
- 开始日期：2026-07-31
- 上游基线：`main@5d95e58cefa1c94b5c9ac8dd681671e2dfd6d8dd`
- 前置检查点：`agent/electron-desktop-foundation@7e4524f`
- 当前工作分支：`agent/electron-bundled-runtimes`
- 当前公开 source 检查点：`fcca1e4`
- 依赖：[ITER-0001](0001-electron-foundation.md) 的源码模式 trust/IPC 契约
- 路线图阶段：P2、P3；提前落地 P5/P6 source foundation
- 追踪矩阵：[traceability](../traceability.md)

## 目标与固定范围

把已验证的源码模式进程边界变成无需系统 Python/Node/Git/QMD 的应用内置运行时，同时
保持 renderer 最小能力和 legacy browser/Docker 兼容：

- 固定 CPython 3.13.14，以 PyInstaller `onedir` 交付 Python sidecar；
- 产品源码 snapshot/Wiki Git 改用受控 Dulwich，不调用系统 Git；
- 固定 Node 22.23.2 与 QMD 2.5.3，以独立 worker + Main broker 提供 revision-safe
  lexical/hybrid 检索；
- 保持 Context7 兼容的 `resolve-library-id`、`query-docs` MCP 契约；
- wiki 默认使用已登录 Codex CLI；只有任务开始前、获得同意且 Codex 明确缺失/登出时，
  才可选择 Cursor CLI；
- packaged Applications 通过 Main-owned fixed argv 和签名 CLI discovery 接入 Codex MCP；
- 原生 picker 以一次性 opaque grant 导入已预先 clone 的本地/私有仓库，不管理凭据；
- 生成可复核的来源、依赖、许可证、SBOM、native closure 和精确资源清单。

R07–R10 是本父迭代的追加纵切，保留最初 lexical-only/无模型下载/无发行的历史范围，同时
单独记录 embedding、MCP onboarding、signed update/release policy 和 local source 的
source 实现。它们不是独立父迭代，不能绕过 packaged/physical 退出门禁。

本迭代不完成旧数据切换、notarization、hardened runtime、automatic update apply 或
Docker retirement。packaged runtime 的 source/macOS CI 合同不替代 clean-user DMG、
真实签名 provider、外置卷或物理 0.0.1 → 0.0.2 门禁。

## 已接受决策

| 决策 | 记录 | 本轮实现状态 |
| --- | --- | --- |
| Main/Python/QMD/renderer 进程边界 | [ADR-0001](../../adr/0001-electron-python-sidecar-boundary.md) | source boundary 已实现；packaged trust gate 待运行 |
| 私有 UDS、独立启动 token 与不重放 | [ADR-0002](../../adr/0002-uds-startup-token-protocol.md) | Python/QMD/MCP source lifecycle 已实现；packaged child lifecycle 待运行 |
| 自签名发行、protected Environment 与 update fallback | [ADR-0003](../../adr/0003-macos-release-signing-update-policy.md) | release policy/source client 已实现；真实 credential/build/update 待运行 |
| provider preflight、attempt 和 commit point | [ADR-0005](../../adr/0005-provider-attempt-execution-boundary.md) | source 实现与回归通过；真实 Codex/Cursor provider gate 待运行 |
| 产品 Git 使用受控 Dulwich | [ADR-0006](../../adr/0006-dulwich-product-git-boundary.md) | source snapshot/Wiki/PATH trap 已实现；bundled clean-user gate 待运行 |
| QMD worker/Main broker/lexical fallback | [ADR-0007](../../adr/0007-qmd-retrieval-broker-runtime.md) | source worker/broker 已实现；packaged native lifecycle 待运行 |
| 内置 MCP companion 与只读 Main bridge | [ADR-0008](../../adr/0008-mcp-companion-main-bridge.md) | source contract 已实现；packaged tools/lifecycle 待运行 |
| Python/Node 来源与 fail-closed 打包清单 | [ADR-0009](../../adr/0009-bundled-runtime-provenance.md) | build/audit source contract 已实现；formal macOS staging 待运行 |
| QMD local embedding profile | [ADR-0010](../../adr/0010-qmd-local-embedding-profile.md) | R07 source/CAS/fallback 已实现；真实模型/native gate 待运行 |
| Main-owned signed update client | [ADR-0011](../../adr/0011-main-owned-signed-update-client.md) | R09 source client/policy 已实现；public pins 尚未 provision |
| 本地仓库 picker 与 opaque grant | [ADR-0012](../../adr/0012-local-repository-picker-opaque-grants.md) | R10 Main/Backend/Web source 已实现；物理 volume gate 待运行 |
| Codex MCP onboarding 与签名 CLI discovery | [ADR-0013](../../adr/0013-codex-mcp-onboarding-signed-cli-discovery.md) | R08 source discovery/onboarding 已实现；真实 OpenAI 签名 gate 待运行 |

## 任务

- [x] **R00 恢复与治理**：恢复 ADR-0005–0009 和活动证据链，不把 2026-07-30 被自动
  清理的未发布 bytes/摘要当作当前证据。
- [x] **R01 产品 Git 边界**：以 Dulwich 完成 source snapshot 与 Wiki publish/rollback，
  保留安全/生命周期语义和产品 `PATH` trap。
- [x] **R02 Python bundled sidecar**：锁定 CPython 3.13.14 来源和构建工具，生成
  `onedir`、manifest/SBOM/notices/native closure，并接入 Main/beforePack 审计。
- [x] **R03 QMD runtime**：实现独立 worker/token、Main broker、Python retrieval port、
  revision/fallback、staging/audit 和 native closure 合同。
- [x] **R04 MCP companion**：实现两个兼容工具、每连接授权、独立 capability、private
  per-launch rendezvous 和 official SDK contract replay。
- [x] **R05 provider attempts**：实现 policy/consent/discovery/preflight、数据库
  attempt/CAS、Main 固定执行、uncertain 恢复和 Web 状态/重建 UI。
- [x] **R06 集成与 source release checks**：同步 manifest/schema，完成 source 回归、
  packaging tamper 合同、macOS release workflow 和独立安全复核；物理门禁另列。
- [x] **R07 QMD embeddings**：完成 local profile、forced rebuild、hybrid-ready CAS 和
  deterministic lexical fallback；见 [R07](0002-r07-qmd-embeddings.md)。
- [x] **R08 Desktop MCP onboarding**：完成固定 Codex argv、四类受控 discovery、
  per-`CODEX_HOME` ownership ledger/marker、bundle chain、UI/rendezvous；见
  [R08](0002-r08-mcp-onboarding.md)。
- [x] **R09 signed update client**：完成独立 Ed25519 manifest、私有 cache、verified DMG
  open、显式固定 Release 页面出口和受保护 release policy；见
  [R09](0002-r09-signed-update-client.md)。
- [x] **R10 local/private repositories**：完成 picker、opaque grant、Main/Backend 双层路径
  策略和脱敏 UX；见 [R10](0002-r10-local-repositories.md)。

以上 `[x]` 表示对应 source 纵切落地，不表示下列完整验收或父迭代完成。

## 验收

- [ ] 产品 Python 路径在 clean packaged Mac、失败 `PATH` 下完成 ingest、publish、lint、
  version、doctor 和真实 UDS health，不启动系统 Python/Git/ctags。
- [ ] QMD worker 在 bundle 内 Node 22.23.2/better-sqlite3 arm64 上完成 reconcile/search、
  真实模型 rebuild/hybrid，stale/崩溃按 ADR-0007/0010 降级。
- [ ] packaged renderer 不得到 executable、argv、PID、stderr、socket、token、MCP
  capability、更新 trust material 或本地绝对路径。
- [ ] provider attempt 的 create/claim/select/commit/spawn/complete cut-point 在真实
  Codex/Cursor 上可恢复；commit 后未知结果不 fallback、不重放。
- [ ] MCP 只有两个 Context7 兼容只读工具，app 未运行/未批准/stale/oversize 均
  fail closed；真实官方签名 Codex 完成 onboarding/reconnect/clear。
- [ ] Python/QMD/companion/renderer staging 的 source digest、inventory、native closure、
  SBOM、notices 和 `beforePack` tamper rejection 在正式 macOS arm64 build 可复现。
- [ ] 本地 home/外置卷私有仓库在 packaged app 中完成选择、重启、移动/删除和脱敏矩阵。
- [ ] protected Environment 生成真实签名 DMG，clean-user Gatekeeper/smoke 和
  0.0.1 → 0.0.2 + verified DMG fallback 物理门禁完成。
- [ ] VAL-GIT-001、VAL-PY-001、VAL-QMD-001、VAL-CLI-001、VAL-MCP-001、VAL-PACK-001
  获得与各自最低环境相符的完整证据。

## 验证日志

| 验证 | 结果 | 日期/提交 | 命令或过程 | 证据/说明 |
| --- | --- | --- | --- | --- |
| VAL-GOV-001 | `pass` | 2026-07-31；当前文档工作树 | `python tools/check_markdown_links.py` | Markdown link validation passed: 66 files |
| VAL-P1-SOURCE-001 | `pass` | 2026-07-30；`7e4524f` | 继承 ITER-0001 Actions 证据 | 仅证明恢复基线 |
| 当前 Backend source 回归 | `pass` | 2026-07-31；`8eedd7e` | `cd backend && .venv/bin/pytest -q ../tests/backend` | 313 pass / 1 AF_UNIX skip |
| 当前 Desktop source 回归 | `pass` | 2026-07-31；`fcca1e4` | `cd desktop && npm test -- --run` | 30 files / 235 pass / 7 skip |
| 当前 Web source 回归 | `pass` | 2026-07-31；`fcca1e4` | `cd web && npm test -- --run` | 7 files / 51 pass |
| 当前 QMD worker source 回归 | `pass` | 2026-07-31；`8eedd7e` | `cd desktop/workers/qmd && npm test` | 8 pass / 3 skip（AF_UNIX/native/model 条件） |
| 当前 Host Runner 回归 | `pass` | 2026-07-31；`8eedd7e` | `backend/.venv/bin/python -m unittest discover -s host_runner/tests -t .` | 8 pass |
| VAL-GIT-001 | `not-run` | — | source Dulwich/PATH 回归已包含在 Backend 313；完整 gate 需 packaged clean macOS | source 子检查 `pass`，最低环境未满足 |
| VAL-PY-001 | `not-run` | — | build/audit source 合同已测试；需无系统 Python/Git/ctags 的 clean macOS arm64 | 不把 CI fixture 当 bundled runtime |
| VAL-QMD-001 | `not-run` | — | worker/Main/Python source 合同已测试；需 packaged Node/QMD/native/UDS | 3 个 worker 条件 skip 保持可见 |
| VAL-QMD-EMBED-001 | `not-run` | — | R07 source profile/CAS/fallback 子检查 `pass`；需真实模型下载与 native hybrid | mock/fake store 不替代真实权重 |
| VAL-CLI-001 | `not-run` | — | provider source policy/attempt 回归已包含在全量 suite；需真实 Codex/Cursor | commit-point 物理过程未运行 |
| VAL-MCP-001 | `not-run` | — | core 3 files / 37 pass；bridge/companion source 子集 15 pass / 7 skip；需 packaged sidecars/Codex | 7 skip 保持可见；见 [R08](0002-r08-mcp-onboarding.md) |
| VAL-MCP-ONBOARD-001 | `not-run` | — | Desktop 6 files / 73、Web 3 files / 25 source 子检查 `pass`；需真实签名 Codex packaged app | `fcca1e4`；source fake/signature injection 不替代 physical |
| VAL-PACK-001 | `not-run` | — | beforePack/build/audit/source tamper 子检查已通过；需 macOS 15 arm64 formal staging | public release locks 仍 unprovisioned |
| VAL-RELEASE-POLICY-001 | `pass` | 2026-07-31；`8eedd7e` | Desktop release policy 20；Backend workflow/bootstrap policy 13 | 只证明 source workflow policy，不证明签名产物 |
| VAL-UPDATE-CLIENT-001 | `pass` | 2026-07-31；`fcca1e4` | Desktop 5 files / 42；Web 2 files / 19 | exact 命令见 [R09](0002-r09-signed-update-client.md) |
| VAL-TRUST-001 packaged | `not-run` | — | 需 packaged renderer/IPC/updater/local-source 审计 | source 负向合同不能替代 |
| VAL-LOCAL-SOURCE-001 | `pass` | 2026-07-31；full `fcca1e4`、focused `8eedd7e` | Desktop 235/7 skip、Web 51；核心 security 子集 30 | 见 [R10](0002-r10-local-repositories.md) |
| VAL-LOCAL-SOURCE-002 | `pass` | 2026-07-31；`8eedd7e` | Backend source+transport 103 pass / 1 skip；全量 Backend 313 / 1 | desktop argv roots/owner/sensitive root 重验 |
| VAL-LOCAL-SOURCE-003 | `not-run` | — | 需 physical packaged macOS home/外置卷/重启矩阵 | source checkout 不替代 NSOpenPanel/volume |
| VAL-INSTALL-001、VAL-RELEASE-001、VAL-SECRET-001 | `not-run` | — | 需 protected Environment、真实签名 DMG、clean-user 与仓库设置证据 | release policy source `pass` 不提升这些门禁 |
| VAL-UPDATE-001 | `not-run` | — | 需物理 Apple Silicon 0.0.1 → 0.0.2 与失败 DMG fallback | automatic apply 保持禁用 |

## 风险、阻塞与回滚点

| 风险/阻塞 | 影响 | 缓解/回滚点 |
| --- | --- | --- |
| source 通过数被误写成完整交付 | 绕过 clean-user/signing/native/physical 风险 | 每项记录最低环境；完整门禁继续 `not-run` |
| public update/codesign locks 尚未 provision | formal release/update 不可用 | fail closed；按 [release runbook](../desktop-release.md) 由管理员 provision |
| better-sqlite3/模型/arm64 dylib 不匹配 | QMD 只在 source fake 上可用 | formal arm64 staging、native closure、真实模型/UDS 门禁 |
| provider commit 后 Main 崩溃 | 结果未知、可能重复计费/发布 | attempt 标记 `uncertain`；用户显式新建 retry，不自动重放 |
| Codex 安装布局或签名变化 | onboarding fail closed | 固定 layout/signature allowlist；退回手动 MCP 配置 |
| Codex config 在最终 list 后并发变化 | 同名 target 可能在 add/remove 小窗口内改变 | 二次 recheck 缩小窗口；CLI 无 CAS/shared lock，明确单用户非对抗同 UID 边界 |
| 同 uid 进程替换本地目录/cache/runtime | 路径或更新/MCP identity 漂移 | 重验 owner/mode/identity/hash；后续 bookmark/fd/App Sandbox 评估 |
| 自签名、未 notarize/hardened | Gatekeeper 与用户信任限制 | manifest/release notes 明示；真实安装 gate 前不宣称 release-ready |
| 旧数据迁移尚未执行 | 新 app 与 legacy 数据并行风险 | ITER-0003/0006 保持 planned；不删除 Docker/旧数据 |

## 当前变更清单

治理与证据：

- `docs/adr/{README,0003-*,0005-* 至 0013-*}.md`
- `docs/development/{README,roadmap,traceability,desktop-release,mcp-companion-protocol}.md`
- `docs/development/iterations/{README,0002-bundled-runtimes,0002-r07-qmd-embeddings,0002-r08-mcp-onboarding,0002-r09-signed-update-client,0002-r10-local-repositories}.md`
- `README.md`、`SECURITY.md`、`desktop/README.md`
- `docs/{README,00-overview,03-hardware-deployment,04-quickstart,06-api-and-mcp,10-security,14-all-in-one-macos,16-electron-desktop-guide}.md`

核心实现：

- `backend/app/**`、`tests/backend/**`、`backend/packaging/**`
- `desktop/src/**`、`desktop/companion/**`、`desktop/workers/qmd/**`、`desktop/tests/**`
- `web/src/**`
- `runtime/**`、`tools/**`、`desktop/scripts/**`、`desktop/resources/**`
- `.github/workflows/{desktop-ci,desktop-release}.yml`

`fcca1e4` 相对 `8eedd7e` 的直接代码证据路径为：

- `desktop/src/main/{mcpOnboarding,mcpTargetOwnership,updateClient,index}.ts`
- `desktop/src/mcpProtocol.ts`
- `desktop/companion/src/{bridgeClient,index}.ts`
- `desktop/tests/{mcpTargetOwnership,mcpOnboarding,mcpCompanion,updateClient,updateIpc}.test.ts`
- `web/src/App.test.tsx`

生成 staging、release assets、缓存、模型、索引、用户数据、credential bundle 和私有 evidence
不入库。

# Electron 迁移可追溯矩阵

## 坐标与规则

- 上游基线：`main@5d95e58cefa1c94b5c9ac8dd681671e2dfd6d8dd`
- 已发布检查点：`agent/electron-desktop-foundation@7e4524f`
- 当前开发分支：`agent/electron-bundled-runtimes`
- 活动迭代：[ITER-0002](iterations/0002-bundled-runtimes.md)
- 路线图：[P0–P7](roadmap.md)

每个行为变化必须形成以下链路：

```text
REQ -> ADR -> ITER/task -> owned paths -> VAL -> evidence
```

`Accepted` ADR 表示决策已确定，不表示实现已完成。验证只有 `pass`、`fail`、
`not-run` 三种结果；没有可复现证据时不得使用 `pass`。

## 需求与映射

表中的 owned paths 是预期责任范围，部分路径会在后续里程碑创建。

| 需求 ID | 验收目标 | 决策 | 任务 | Owned paths | 验证 | 当前状态 |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-PLATFORM-001 | macOS Apple Silicon Electron all-in-one，React renderer | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md) | ITER-0001/T02；ITER-0004/P01、P05 | `desktop/**`, `web/src/**` | VAL-P1-CONTRACT-001、VAL-P1-SOURCE-001、VAL-INSTALL-001 | source gate `pass`；packaged/安装门禁 `not-run` |
| REQ-TRUST-001 | Electron Main 是信任边界，renderer 仅有类型化最小能力 | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md) | ITER-0001/T02、T04 | `desktop/src/main/**`, `desktop/src/preload/**`, `web/src/**` | VAL-P1-CONTRACT-001、VAL-TRUST-001 | 源码合同已测试；packaged trust gate `not-run` |
| REQ-PY-001 | CPython 3.13.14 sidecar 以可审计 PyInstaller `onedir` 随应用交付 | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md)、[ADR-0009](../adr/0009-bundled-runtime-provenance.md) | ITER-0002/R02 | `backend/packaging/**`, `tools/*python_sidecar*`, `desktop/resources/python/**` | VAL-PY-001、VAL-PACK-001 | `in-progress` |
| REQ-GIT-001 | packaged 产品不调用系统 Git，snapshot/Wiki 保留既有安全和回滚语义 | [ADR-0006](../adr/0006-dulwich-product-git-boundary.md) | ITER-0002/R01 | `backend/app/{source,wiki}.py`, source/Wiki tests | VAL-GIT-001、VAL-PY-001 | `in-progress` |
| REQ-QMD-001 | QMD 使用独立、内置 Node 22.23.2 worker，经 Main broker 提供 revision-safe lexical retrieval | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md)、[ADR-0007](../adr/0007-qmd-retrieval-broker-runtime.md)、[ADR-0009](../adr/0009-bundled-runtime-provenance.md) | ITER-0002/R03 | `desktop/workers/qmd/**`, `desktop/src/main/qmd*`, `backend/app/desktop_retrieval.py` | VAL-QMD-001、VAL-PACK-001 | `in-progress` |
| REQ-IPC-001 | Main 与 sidecar/worker 只经私有 UDS + 每次启动令牌通信 | [ADR-0002](../adr/0002-uds-startup-token-protocol.md) | ITER-0001/T03 | `desktop/src/main/**`, `backend/app/{cli,desktop_session,factory}.py` | VAL-P1-CONTRACT-001、VAL-P1-SOURCE-001、VAL-IPC-001 | Linux/macOS source 子门禁 `pass`；packaged child/lifecycle `not-run` |
| REQ-COMPAT-001 | Desktop bridge fail closed，同时保留 browser/Docker HTTP transport | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md) | ITER-0001/T04 | `web/src/{api,desktopBridge,App}.ts*`, `web/src/**/*.test.ts*` | VAL-P1-CONTRACT-001、VAL-P1-REGRESSION-001 | `source-tested` |
| REQ-VERSION-001 | 产品、协议与 schema 版本使用单一 manifest 并跨层同步 | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md)、[ADR-0002](../adr/0002-uds-startup-token-protocol.md) | ITER-0001/T05 | `runtime/version.json`, `backend/app/version.py`, `desktop/package.json`, `tools/check_version_sync.py` | VAL-P1-CONTRACT-001 | `source-tested` |
| REQ-CI-001 | 普通源码 CI 最小权限且不能读取发布秘密 | [ADR-0003](../adr/0003-macos-release-signing-update-policy.md) | ITER-0001/T05 | `.github/workflows/desktop-ci.yml`, `Makefile`, `.github/dependabot.yml` | VAL-CI-001 | `pass` |
| REQ-CLI-001 | Codex 默认；Cursor 仅获同意且在 spawn 前明确 preflight 失败时替代；commit 后不 fallback/重放 | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md)、[ADR-0005](../adr/0005-provider-attempt-execution-boundary.md) | ITER-0002/R05 | `backend/app/**`, `desktop/src/main/providers/**`, desktop/web provider UI | VAL-CLI-001 | `in-progress` |
| REQ-MCP-001 | 内置 stdio companion 保持两个 Context7 兼容工具，仅经 Main 只读私有桥 | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md)、[ADR-0008](../adr/0008-mcp-companion-main-bridge.md) | ITER-0002/R04 | `desktop/companion/**`, desktop MCP bridge, contract tests | VAL-MCP-001 | `in-progress` |
| REQ-PACK-001 | bundled Python/Node 来源、文件、native closure、许可证和输入摘要可复核，打包前篡改 fail closed | [ADR-0009](../adr/0009-bundled-runtime-provenance.md) | ITER-0002/R02–R03 | runtime schemas, build/audit scripts, Electron `beforePack` | VAL-PACK-001 | `in-progress` |
| REQ-INSTALL-001 | 默认 DMG；目标机无需 Docker/Homebrew/Python/Node/Git/ctags | [ADR-0003](../adr/0003-macos-release-signing-update-policy.md) | ITER-0004/P01、P05 | desktop packaging | VAL-INSTALL-001 | `planned` |
| REQ-MODEL-001 | 模型权重按需下载、校验并原子激活 | [ADR-0004](../adr/0004-runtime-paths-legacy-data-migration.md) | ITER-0003/D04–D05 | model manager/cache | VAL-MODEL-001 | `planned` |
| REQ-RELEASE-001 | 自签名，明确不 notarize、不启用 hardened runtime | [ADR-0003](../adr/0003-macos-release-signing-update-policy.md) | ITER-0004/P01–P03 | desktop packaging, release docs | VAL-RELEASE-001 | `planned` |
| REQ-SECRET-001 | 公开仓库的发布秘密仅在受保护 `macos-release` Environment | [ADR-0003](../adr/0003-macos-release-signing-update-policy.md) | ITER-0004/P02–P04 | `.github/workflows/**`, release settings | VAL-SECRET-001 | `planned` |
| REQ-UPDATE-001 | 先通过 0.0.1 → 0.0.2 实机更新；失败则校验后下载并打开 DMG | [ADR-0003](../adr/0003-macos-release-signing-update-policy.md) | ITER-0005/U01–U05 | updater/release feed | VAL-UPDATE-001 | `planned` |
| REQ-DATA-001 | 标准 macOS 路径；旧数据可盘点、原子迁移、回滚 | [ADR-0004](../adr/0004-runtime-paths-legacy-data-migration.md) | ITER-0003/D01–D03 | runtime path/migration modules | VAL-DATA-001 | `planned` |
| REQ-LEGACY-001 | Docker 暂留 legacy，迁移成功且另行决策后才弃用 | [ADR-0004](../adr/0004-runtime-paths-legacy-data-migration.md) | ITER-0006/L01–L05 | existing Docker paths and docs | VAL-LEGACY-001 | `planned` |

## 验证目录

| 验证 ID | 所需证据 | 最低环境 | 当前结果 |
| --- | --- | --- | --- |
| VAL-GOV-001 | 所有新增/修改 Markdown 相对链接检查 | repository checkout | `pass` |
| VAL-GOV-002 | 两个 `SKILL.md` frontmatter、名称和引用结构检查 | repository checkout | `pass` |
| VAL-P1-CONTRACT-001 | Electron Main/preload、Web bridge、desktop sidecar 纯源码合同与负向单元测试；不包含真实 UDS bind、macOS 或 packaged runtime | Linux x86_64 source checkout | `pass`（Desktop 42；Web 34；Backend 169，真实 bind 另列） |
| VAL-P1-SOURCE-001 | 完整源码纵切，包含真实 AF_UNIX bind 与无 skip 的 source tests | Linux/macOS source checkout | `pass`（[Actions 30550023917](https://github.com/fredgnr/local-context-forge/actions/runs/30550023917)：Python/Web/Desktop/macOS arm64 全通过） |
| VAL-P1-REGRESSION-001 | Web、API、Host Runner 全量既有测试 | Linux/macOS source checkout | `pass`（Backend 169；Host Runner 8；Web 34） |
| VAL-CI-001 | PR CI 最小权限、无 release secret/Environment、全部必需 source jobs 通过 | GitHub Actions | `pass`（[Actions 30550023917](https://github.com/fredgnr/local-context-forge/actions/runs/30550023917)；`contents: read`） |
| VAL-TRUST-001 | renderer sandbox/IPC 负向测试和权限审计 | Electron test + packaged app | `not-run`（L1 source 子检查已通过） |
| VAL-GIT-001 | Dulwich source/Wiki 安全、回滚、互操作和产品 PATH trap | source checkout + C Git test fixture | `not-run` |
| VAL-PY-001 | 打包 sidecar 回归、资源审计、无系统 Python 启动 | clean macOS arm64 user | `not-run` |
| VAL-QMD-001 | 内置 Node 22/QMD 索引与查询生命周期 | clean macOS arm64 user | `not-run` |
| VAL-IPC-001 | UDS 权限、令牌拒绝、超时、崩溃、stale socket | macOS integration test | `not-run`（macOS arm64 source bind/合同子门禁已通过；packaged child/lifecycle 未运行） |
| VAL-CLI-001 | provider preflight 矩阵与任务开始后不 fallback | macOS integration test | `not-run` |
| VAL-MCP-001 | Context7 兼容工具契约回放 | packaged sidecars | `not-run` |
| VAL-PACK-001 | Python/QMD manifest、来源、inventory/native closure 与 `beforePack` tamper rejection | macOS 15 arm64 packaging job | `not-run` |
| VAL-INSTALL-001 | 无外部运行时的 DMG 安装与核心 smoke | clean physical Apple Silicon Mac | `not-run` |
| VAL-MODEL-001 | consent、离线、完整性、resume、原子激活 | packaged app | `not-run` |
| VAL-RELEASE-001 | DMG 架构/内容/自签名身份/限制记录 | protected release build | `not-run` |
| VAL-SECRET-001 | fork/PR/普通构建无法读取发布秘密 | public-repository workflow audit | `not-run` |
| VAL-UPDATE-001 | 0.0.1 → 0.0.2 自动更新及失败 DMG fallback | physical Apple Silicon Mac | `not-run` |
| VAL-DATA-001 | fresh/repeat/interrupt/corrupt/low-disk/rollback 矩阵 | representative legacy copies | `not-run` |
| VAL-LEGACY-001 | 迁移样本、原数据可恢复、legacy 退出审查 | physical migration rehearsal | `not-run` |

## ADR—迭代—验证映射

| ADR | 迭代任务 | 主要验证 |
| --- | --- | --- |
| [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md) | ITER-0001/T02–T05；ITER-0002/R01–R05 | VAL-P1-CONTRACT-001、VAL-P1-SOURCE-001、VAL-P1-REGRESSION-001、VAL-TRUST-001、VAL-PY-001、VAL-QMD-001、VAL-CLI-001、VAL-MCP-001 |
| [ADR-0002](../adr/0002-uds-startup-token-protocol.md) | ITER-0001/T03、T05；ITER-0002/R02–R03 | VAL-P1-CONTRACT-001、VAL-P1-SOURCE-001、VAL-IPC-001 |
| [ADR-0003](../adr/0003-macos-release-signing-update-policy.md) | ITER-0001/T05；ITER-0004/P01–P05；ITER-0005/U01–U05 | VAL-CI-001、VAL-INSTALL-001、VAL-RELEASE-001、VAL-SECRET-001、VAL-UPDATE-001 |
| [ADR-0004](../adr/0004-runtime-paths-legacy-data-migration.md) | ITER-0003/D01–D05；ITER-0006/L01–L05 | VAL-DATA-001、VAL-MODEL-001、VAL-LEGACY-001 |
| [ADR-0005](../adr/0005-provider-attempt-execution-boundary.md) | ITER-0002/R05 | VAL-CLI-001 |
| [ADR-0006](../adr/0006-dulwich-product-git-boundary.md) | ITER-0002/R01 | VAL-GIT-001、VAL-PY-001 |
| [ADR-0007](../adr/0007-qmd-retrieval-broker-runtime.md) | ITER-0002/R03 | VAL-QMD-001、VAL-IPC-001 |
| [ADR-0008](../adr/0008-mcp-companion-main-bridge.md) | ITER-0002/R04 | VAL-MCP-001、VAL-TRUST-001 |
| [ADR-0009](../adr/0009-bundled-runtime-provenance.md) | ITER-0002/R02–R03 | VAL-PY-001、VAL-QMD-001、VAL-PACK-001 |

## 本次变更映射

| 变更范围 | 目的 | 需求/任务 | 验证 |
| --- | --- | --- | --- |
| `AGENTS.md`, `.agents/**`, `docs/README.md`, `docs/adr/**`, `docs/development/**`, `tools/check_markdown_links.py` | 仓库规则、分层入口、ADR、迭代和证据链 | ITER-0001/T01、T06 | VAL-GOV-001、VAL-GOV-002 |
| `docs/15-github-actions-ghcr.md` | 保留上游 Docker/GHCR 运维文档，不把 Electron 迁移误作 legacy 删除 | REQ-LEGACY-001；ITER-0006/L01–L05 | VAL-P1-REGRESSION-001；VAL-LEGACY-001 `not-run` |
| `runtime/version.json`, `backend/app/version.py`, `backend/pyproject.toml`, `backend/uv.lock`, `desktop/{package,package-lock}.json`, `tools/check_version_sync.py` | 固定产品、协议、schema 与源码依赖版本 | REQ-VERSION-001；ITER-0001/T05 | VAL-P1-CONTRACT-001 |
| `desktop/src/**`, `desktop/tests/**`, `desktop/{README.md,tsconfig.json,vitest.config.ts}` | Electron Main/preload 信任边界、静态协议、类型化 IPC、sidecar supervisor 与负向测试 | REQ-PLATFORM-001、REQ-TRUST-001、REQ-IPC-001；ITER-0001/T02–T03 | VAL-P1-CONTRACT-001；VAL-P1-SOURCE-001/VAL-TRUST-001/VAL-IPC-001 `not-run` |
| `backend/app/{__init__,cli,desktop_session,factory,main,service,version}.py`, `backend/{pyproject.toml,uv.lock}`, `tests/backend/test_desktop_transport.py` | 保留 legacy API，同时提供仅 UDS、每次启动认证的 desktop sidecar | REQ-IPC-001、REQ-COMPAT-001；ITER-0001/T03–T04 | VAL-P1-CONTRACT-001、VAL-P1-REGRESSION-001；VAL-P1-SOURCE-001/VAL-IPC-001 `not-run` |
| `web/src/{App,App.test,MarkdownView.test,api,api.test,csp.test,desktopBridge,desktopBridge.test}.ts*`, `web/src/components/{KnowledgeGraph,MarkdownView}.tsx`, `web/src/styles.css` | desktop bridge fail closed、browser transport 兼容、CSP 与 Markdown 外链收口 | REQ-TRUST-001、REQ-COMPAT-001；ITER-0001/T02、T04 | VAL-P1-CONTRACT-001、VAL-P1-REGRESSION-001；VAL-TRUST-001 `not-run` |
| `.github/workflows/desktop-ci.yml`, `.github/dependabot.yml`, `Makefile`, `.gitignore` | 最小权限源码 CI、依赖更新分组与生成物排除 | REQ-CI-001；ITER-0001/T05 | VAL-CI-001 `not-run` |
| `desktop/electron-builder.yml`, `desktop/scripts/afterPack.cjs`, `desktop/resources/**` | 为后续 arm64 打包和 fuse 提供配置骨架；本轮不生成发行产物 | REQ-INSTALL-001、REQ-RELEASE-001；ITER-0004/P01 | VAL-INSTALL-001、VAL-RELEASE-001 `not-run` |
| `docs/adr/0005-*` 至 `0009-*`, `docs/development/**`, `.agents/skills/lcf-desktop-development/references/architecture.md` | 恢复 P2 决策、活动迭代和 workspace-maintenance 恢复边界；不把丢失的本地代码当证据 | REQ-PY/GIT/QMD/CLI/MCP/PACK；ITER-0002/R00 | VAL-GOV-001 `not-run`（待本轮链接检查） |

后续变更应追加或更新本节，不删除已发布证据。若实现路径与 planned owned paths 不同，
在同一变更中修正映射。

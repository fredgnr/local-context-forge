# Electron 迁移可追溯矩阵

## 坐标与规则

- 上游基线：`main@5d95e58cefa1c94b5c9ac8dd681671e2dfd6d8dd`
- 开发分支：`agent/electron-desktop-foundation`
- 活动迭代：[ITER-0001](iterations/0001-electron-foundation.md)
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
| REQ-PLATFORM-001 | macOS Apple Silicon Electron all-in-one，React renderer | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md) | ITER-0001/T02 | `desktop/**` | VAL-INSTALL-001 | `planned` |
| REQ-TRUST-001 | Electron Main 是信任边界，renderer 仅有类型化最小能力 | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md) | ITER-0001/T02 | `desktop/main/**`, `desktop/preload/**`, `desktop/renderer/**` | VAL-TRUST-001 | `planned` |
| REQ-PY-001 | Python 3.12 sidecar 以 PyInstaller `onedir` 随应用交付 | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md) | ITER-0002/R01–R02 | `backend/**`, `desktop/resources/python/**` | VAL-PY-001 | `planned` |
| REQ-QMD-001 | QMD 使用独立、内置 Node 22 worker | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md) | ITER-0002/R03 | `desktop/workers/qmd/**` | VAL-QMD-001 | `planned` |
| REQ-IPC-001 | Main 与 sidecar/worker 只经私有 UDS + 每次启动令牌通信 | [ADR-0002](../adr/0002-uds-startup-token-protocol.md) | ITER-0001/T03 | `desktop/main/**`, sidecar adapters | VAL-IPC-001 | `planned` |
| REQ-CLI-001 | Codex CLI 默认；Cursor 只可在任务开始前 preflight 替代 | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md) | ITER-0002/R05 | provider adapters | VAL-CLI-001 | `planned` |
| REQ-MCP-001 | MCP 保持 Context7 兼容工具契约 | [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md) | ITER-0002/R04 | `mcp/**`, desktop MCP bridge | VAL-MCP-001 | `planned` |
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
| VAL-P1-SOURCE-001 | Electron Main/preload、Web bridge 与 desktop sidecar source tests | Linux/macOS source checkout | `not-run` |
| VAL-P1-REGRESSION-001 | Web、API、Host Runner 全量既有测试 | Linux/macOS source checkout | `not-run` |
| VAL-CI-001 | PR CI 最小权限、无 release secret/Environment、全部 source jobs 通过 | GitHub Actions | `not-run` |
| VAL-TRUST-001 | renderer sandbox/IPC 负向测试和权限审计 | Electron test + packaged app | `not-run` |
| VAL-PY-001 | 打包 sidecar 回归、资源审计、无系统 Python 启动 | clean macOS arm64 user | `not-run` |
| VAL-QMD-001 | 内置 Node 22/QMD 索引与查询生命周期 | clean macOS arm64 user | `not-run` |
| VAL-IPC-001 | UDS 权限、令牌拒绝、超时、崩溃、stale socket | macOS integration test | `not-run` |
| VAL-CLI-001 | provider preflight 矩阵与任务开始后不 fallback | macOS integration test | `not-run` |
| VAL-MCP-001 | Context7 兼容工具契约回放 | packaged sidecars | `not-run` |
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
| [ADR-0001](../adr/0001-electron-python-sidecar-boundary.md) | ITER-0001/T02–T04；ITER-0002/R01–R05 | VAL-P1-SOURCE-001、VAL-TRUST-001、VAL-PY-001、VAL-QMD-001、VAL-CLI-001、VAL-MCP-001 |
| [ADR-0002](../adr/0002-uds-startup-token-protocol.md) | ITER-0001/T03；ITER-0002/R02–R03 | VAL-P1-SOURCE-001、VAL-IPC-001 |
| [ADR-0003](../adr/0003-macos-release-signing-update-policy.md) | ITER-0004/P01–P05；ITER-0005/U01–U05 | VAL-INSTALL-001、VAL-RELEASE-001、VAL-SECRET-001、VAL-UPDATE-001 |
| [ADR-0004](../adr/0004-runtime-paths-legacy-data-migration.md) | ITER-0003/D01–D05；ITER-0006/L01–L05 | VAL-DATA-001、VAL-MODEL-001、VAL-LEGACY-001 |

## 本次变更映射

| 变更范围 | 目的 | 需求/任务 | 验证 |
| --- | --- | --- | --- |
| `AGENTS.md` | 仓库规则、证据和分层入口 | ITER-0001/T01 | VAL-GOV-001 |
| `docs/README.md`, `docs/development/**` | 路线图、迭代与证据链 | ITER-0001/T01 | VAL-GOV-001 |
| `docs/adr/**` | 记录四项初始跨边界决策 | REQ-TRUST/IPC/RELEASE/DATA 系列；T01 | VAL-GOV-001 |
| `.agents/skills/lcf-desktop-development/**` | 路由桌面架构与测试工作 | ITER-0001/T01 | VAL-GOV-002 |
| `.agents/skills/lcf-change-traceability/**` | 执行 ADR/迭代/验证流程 | ITER-0001/T01 | VAL-GOV-002 |

后续变更应追加或更新本节，不删除已发布证据。若实现路径与 planned owned paths 不同，
在同一变更中修正映射。

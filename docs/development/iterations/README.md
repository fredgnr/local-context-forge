# 迭代索引

迭代记录把 [P0–P7 路线图](../roadmap.md)拆成可独立审查的变更范围。只有一个父迭代可以是
`in-progress`；`Rxx` 是该父迭代的追加实施/证据记录，继承其状态，不是并行的独立迭代。
后续父迭代在前置门禁通过前保持 `planned`。

| 迭代 | 状态 | 范围 |
| --- | --- | --- |
| [ITER-0001](0001-electron-foundation.md) | `validated` | 治理、版本契约、Electron 信任边界、源码模式 UDS 纵切 |
| [ITER-0002](0002-bundled-runtimes.md) | `in-progress` | Python `onedir`、Node/QMD worker、MCP 与 CLI preflight |
| [ITER-0002/R07](0002-r07-qmd-embeddings.md) | `in-progress`（继承） | 独立追加：QMD local embedding、model switch 与 hybrid fallback |
| [ITER-0002/R08](0002-r08-mcp-onboarding.md) | `in-progress`（继承） | Codex MCP onboarding、签名 CLI discovery、scoped ownership 与 per-launch rendezvous |
| [ITER-0002/R09](0002-r09-signed-update-client.md) | `in-progress`（继承） | 独立签名更新检查、verified DMG、显式固定 Release 出口与 release policy |
| [ITER-0002/R10](0002-r10-local-repositories.md) | `in-progress`（继承） | 原生本地/私有仓库选择与不透明路径授权 |
| [ITER-0003](0003-runtime-data-models.md) | `planned` | macOS 路径、模型管理、旧数据迁移与回滚 |
| [ITER-0004](0004-macos-release.md) | `planned` | arm64 DMG、自签名、受保护发布 Environment |
| [ITER-0005](0005-updater-physical-gate.md) | `planned` | 0.0.1 → 0.0.2 实机更新与 DMG fallback |
| [ITER-0006](0006-legacy-exit.md) | `planned` | 迁移演练、Docker legacy 去留决策 |

每个记录维护自己的范围、任务、验收、风险、验证日志和变更清单。Rxx 中 source task 的
`[x]` 不代表父迭代完成，也不把 packaged/physical `not-run` 门禁提升为 `pass`。未开始的
父迭代只描述计划，不得作为实现证据。

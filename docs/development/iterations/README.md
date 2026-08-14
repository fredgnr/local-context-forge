# 迭代索引

迭代记录把 [P0–P7 路线图](../roadmap.md)拆成可独立审查的变更范围。ITER-0002 是 bundled
runtime 父 ledger；`Rxx` 是其追加实施/证据记录，继承父状态，不是并行父迭代。R13 完成并
关闭 W01 后，ITER-0008 作为 ADR-0016 的下游执行记录进入 `in-progress`；ITER-0002 因其既有
packaged/physical 退出门禁仍未满足而继续作为父 ledger 开放，这不把任何门禁提升为 `pass`。

| 迭代 | 状态 | 范围 |
| --- | --- | --- |
| [ITER-0001](0001-electron-foundation.md) | `validated` | 治理、版本契约、Electron 信任边界、源码模式 UDS 纵切 |
| [ITER-0002](0002-bundled-runtimes.md) | `in-progress` | Python `onedir`、Node/QMD worker、MCP 与 CLI preflight |
| [ITER-0002/R07](0002-r07-qmd-embeddings.md) | `in-progress`（继承） | 独立追加：QMD local embedding、model switch 与 hybrid fallback |
| [ITER-0002/R08](0002-r08-mcp-onboarding.md) | `in-progress`（继承） | Codex MCP onboarding、签名 CLI discovery、scoped ownership 与 per-launch rendezvous |
| [ITER-0002/R09](0002-r09-signed-update-client.md) | `in-progress`（继承） | 独立签名更新、候选 Draft 与 trusted-main/fixed-ID promotion policy |
| [ITER-0002/R10](0002-r10-local-repositories.md) | `in-progress`（继承） | 原生本地/私有仓库选择与不透明路径授权 |
| [ITER-0002/R11](0002-r11-documentation-handoff.md) | `in-progress`（继承） | 状态、系统设计、部署、开发、TODO 与 evidence 交接 |
| [ITER-0002/R12](0002-r12-legacy-retirement-scope.md) | `completed`（父迭代继续） | Electron-only 决策、严格 legacy removal 范围与后续任务冻结 |
| [ITER-0002/R13](0002-r13-pre1-incremental-retirement.md) | `completed`（W01 external closeout recorded；父迭代继续） | ADR-0016、W01–W16、增量 removal 与工程测试包治理 |
| [ITER-0003](0003-runtime-data-models.md) | `planned` | macOS 路径、Desktop backup/restore 与模型管理；不含 legacy importer |
| [ITER-0004](0004-macos-release.md) | `planned` | arm64 DMG、双 Environment、ruleset/Immutable Releases 与物理 promotion |
| [ITER-0005](0005-updater-physical-gate.md) | `planned` | 真实单调 `N-1 → N` 实机更新与 DMG fallback |
| [ITER-0006](0006-legacy-exit.md) | `superseded` | 历史：迁移演练、Docker legacy 去留决策；由 ADR-0015 取代 |
| [ITER-0007](0007-electron-only-retirement.md) | `superseded` | 历史计划：完整 cutover 后才删除；执行顺序由 ADR-0016/ITER-0008 取代 |
| [ITER-0008](0008-incremental-retirement-engineering-package.md) | `in-progress`（W02 static assembly/bundle audit `pass`；packaged launch/runtime `not-run`） | 最小 packaged smoke、增量 legacy slices、cleaned-tree 工程包与 final cutover |

每个记录维护自己的范围、任务、验收、风险、验证日志和变更清单。Rxx 中 source task 的
`[x]` 不代表父迭代完成，也不把 packaged/physical `not-run` 门禁提升为 `pass`。未开始的
父迭代只描述计划，不得作为实现证据。

# 迭代索引

迭代记录把 [P0–P7 路线图](../roadmap.md)拆成可独立审查的变更范围。只有一个记录可以是
`in-progress`；后续记录在前置门禁通过前保持 `planned`。

| 迭代 | 状态 | 范围 |
| --- | --- | --- |
| [ITER-0001](0001-electron-foundation.md) | `validated` | 治理、版本契约、Electron 信任边界、源码模式 UDS 纵切 |
| [ITER-0002](0002-bundled-runtimes.md) | `in-progress` | Python `onedir`、Node/QMD worker、MCP 与 CLI preflight |
| [ITER-0003](0003-runtime-data-models.md) | `planned` | macOS 路径、模型管理、旧数据迁移与回滚 |
| [ITER-0004](0004-macos-release.md) | `planned` | arm64 DMG、自签名、受保护发布 Environment |
| [ITER-0005](0005-updater-physical-gate.md) | `planned` | 0.0.1 → 0.0.2 实机更新与 DMG fallback |
| [ITER-0006](0006-legacy-exit.md) | `planned` | 迁移演练、Docker legacy 去留决策 |

每个记录维护自己的范围、任务、验收、风险、验证日志和变更清单。未开始的迭代只描述计划，
不得作为实现证据。

# Electron 迁移开发索引

本目录记录 Local Context Forge 从现有部署形态迁移到 macOS Apple Silicon
Electron all-in-one 的计划、证据和变更历史。它描述目标与门禁，不代表功能已经实现。

## 项目坐标

- 上游仓库：`fredgnr/local-context-forge`
- 上游基线：`main@5d95e58cefa1c94b5c9ac8dd681671e2dfd6d8dd`
- 已发布检查点：`agent/electron-desktop-foundation@7e4524f`
- 当前工作分支：`agent/electron-bundled-runtimes`
- 当前迁移状态：`in-progress`

## 从这里开始

| 目的 | 文档 |
| --- | --- |
| 查看 P0–P7 顺序、依赖和门禁 | [迁移路线图](roadmap.md) |
| 从需求追到 ADR、迭代、验证和文件 | [可追溯矩阵](traceability.md) |
| 查看各轮边界与当前活动记录 | [迭代索引](iterations/README.md) |
| 查看本轮范围、任务、风险和证据 | [迭代 0002](iterations/0002-bundled-runtimes.md) |
| 查看已接受或待决的架构决策 | [ADR 索引](../adr/README.md) |
| 查看原有 00–15 文档和新文档入口 | [文档总索引](../README.md) |

## Agent 工作流

- 涉及 Electron、renderer、Python sidecar、Node/QMD worker、打包或桌面测试时，
  使用
  [`lcf-desktop-development`](../../.agents/skills/lcf-desktop-development/SKILL.md)。
- 涉及 ADR、迭代状态、验证证据、需求映射或交付说明时，使用
  [`lcf-change-traceability`](../../.agents/skills/lcf-change-traceability/SKILL.md)。
- 两个 skill 分工不同：前者约束实现与测试边界，后者维护证据链；架构变化通常需要依次使用。

## 状态词

| 状态 | 含义 |
| --- | --- |
| `planned` | 已排入路线图，尚未开始 |
| `in-progress` | 正在实现或验证，不能视为可交付 |
| `blocked` | 有明确阻塞项，必须记录解除条件 |
| `validated` | 指定门禁已有可复现证据 |
| `done` | 范围、文档和全部必需门禁均完成 |

验证结果统一使用 `pass`、`fail`、`not-run`。只有附有命令、环境和产物位置的
`pass` 才能支撑 `validated` 或 `done`。

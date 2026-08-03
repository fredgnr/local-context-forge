# Electron 迁移开发索引

本目录记录 Local Context Forge 从现有部署形态迁移到 macOS Apple Silicon
Electron all-in-one 的计划、证据和变更历史。它描述目标与门禁，不代表功能已经实现。

## 项目坐标

- 上游仓库：`fredgnr/local-context-forge`
- 上游基线：`main@5d95e58cefa1c94b5c9ac8dd681671e2dfd6d8dd`
- 已发布检查点：`agent/electron-desktop-foundation@7e4524f`
- bundled runtime merge：`main@52a5ffa184da694519a906dbacc7ee9df26a3fcc`
- two-stage release merge：`main@fb8bbbc3d0b4e4b5a20c943bd7fd71b2450651a8`
- Electron-only planning merge：`main@da40553e43ec6272e1affc1f40abf4f9215f1ba5`
- 当前治理基线：`main@da40553e43ec6272e1affc1f40abf4f9215f1ba5`
- 当前治理分支：`agent/pre1-incremental-retirement-governance`
- 当前迁移状态：`in-progress`

## 从这里开始

| 目的 | 文档 |
| --- | --- |
| 查看当前 commit、gate、blocker 和发布结论 | [项目状态快照](status.md) |
| 了解组合进程、信任、数据和代码地图 | [系统设计](../17-system-design.md) |
| 安装、运维、备份、GitHub settings 和 Release | [部署与运维总手册](../18-deployment-operations.md) |
| 新贡献者搭环境、测试和提 PR | [开发者手册](contributor-handbook.md) |
| 查看所有剩余任务、owner、依赖和验收 | [详细 TODO](todo.md) |
| 查看 W01–W16 execution rank 与正式发行边界 | [Pre-1.0 work plan](work-plan.md) |
| 查看 Electron-only 的 remove/retain/split 与删除门禁 | [Legacy retirement 计划](legacy-retirement.md) |
| 建立可复现、脱敏的验证记录 | [证据规范](evidence/README.md) |
| 查看 P0–P7 顺序、依赖和门禁 | [迁移路线图](roadmap.md) |
| 从需求追到 ADR、迭代、验证和文件 | [可追溯矩阵](traceability.md) |
| 查看各轮边界与当前活动记录 | [迭代索引](iterations/README.md) |
| 查看本轮范围、任务、风险和证据 | [迭代 0002](iterations/0002-bundled-runtimes.md) |
| 查看 QMD embedding 追加纵切 | [ITER-0002/R07](iterations/0002-r07-qmd-embeddings.md) |
| 查看 Codex MCP onboarding 证据 | [ITER-0002/R08](iterations/0002-r08-mcp-onboarding.md) |
| 查看 signed update/release 证据 | [ITER-0002/R09](iterations/0002-r09-signed-update-client.md) |
| 查看 tag-only 候选与 trusted-main promotion 决策 | [ADR-0014](../adr/0014-two-stage-desktop-release-promotion.md) |
| 查看本地/私有仓库证据 | [ITER-0002/R10](iterations/0002-r10-local-repositories.md) |
| 查看文档交接记录 | [ITER-0002/R11](iterations/0002-r11-documentation-handoff.md) |
| 查看 Electron-only 范围冻结记录 | [ITER-0002/R12](iterations/0002-r12-legacy-retirement-scope.md) |
| 查看增量 retirement 治理记录 | [ITER-0002/R13](iterations/0002-r13-pre1-incremental-retirement.md) |
| 查看增量 retirement / 工程包计划 | [ITER-0008](iterations/0008-incremental-retirement-engineering-package.md) |
| 查看 packaged smoke、slice 与 release 后置决策 | [ADR-0016](../adr/0016-pre1-incremental-retirement-engineering-package.md) |
| 查看 MCP companion 私有协议 | [MCP companion 协议](mcp-companion-protocol.md) |
| 执行或审计正式桌面发布 | [macOS release runbook](desktop-release.md) |
| 使用安装后的 Electron 桌面应用 | [桌面用户指南](../16-electron-desktop-guide.md) |
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
| `superseded` | 被后续 Accepted ADR 取代且不再实施；验证保持 `not-run` |

验证结果统一使用 `pass`、`fail`、`not-run`。只有附有命令、环境和产物位置的
`pass` 才能支撑 `validated` 或 `done`。

不要用“当前工作树”作为长期证据坐标；绑定 exact commit、Actions run 或带摘要的受控
artifact。当前状态只在 [status.md](status.md) 维护，其他入口应链接它。

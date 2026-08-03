# Local Context Forge 文档索引

Local Context Forge 正在收敛为 macOS Apple Silicon Electron all-in-one 客户端。阅读文档时
请区分目标产品与尚未删除的历史运行面：

- **Electron 桌面版**：目标形态。应用内置 Python sidecar、Node/QMD、Web UI 与 MCP
  companion，并已有 tag-only Draft/trusted-main promotion source policy；但真实 GitHub
  settings、正式 Release、干净用户安装、真实 Codex 任务和物理更新门禁仍未完成。整体保持
  **source merge GO / release NO-GO**。
- **legacy Docker/Web**：已弃用、unsupported、待删除；`install.sh` 与
  `docs/15-github-actions-ghcr.md` 仍描述当前仓库残留，不再是受支持安装/回退路径。

在出现经过审查的公开 DMG 之前，不应把 Electron 称为面向普通用户的推荐发行版。当前最完整
的桌面使用、限制与维护说明见
[Electron 桌面版完整指南](16-electron-desktop-guide.md)。

## 先读权威入口

| 你要了解 | 权威入口 |
| --- | --- |
| 当前完成度、证据和 Release GO/NO-GO | [项目状态快照](development/status.md) |
| 当前 Electron 架构与待删除 legacy inventory | [系统设计](17-system-design.md) |
| Electron source/Release 与历史部署 inventory | [部署与运维总手册](18-deployment-operations.md) |
| 开发环境、测试和 PR 流程 | [开发者手册](development/contributor-handbook.md) |
| 还要做什么、由谁做、如何验收 | [详细 TODO](development/todo.md) |
| W01–W16 的显式执行顺序与 release boundary | [Pre-1.0 work plan](development/work-plan.md) |
| 哪些 legacy 文件删除、哪些共享代码保留 | [Legacy retirement 计划](development/legacy-retirement.md) |

## 产品与使用

| 编号 | 文档 | 主要内容 |
| --- | --- | --- |
| 00 | [产品概览](00-overview.md) | 产品目标、工作流与当前交付状态 |
| 01 | [架构](01-architecture.md) | Wiki 编译流水线和服务边界 |
| 02 | [Karpathy Wiki](02-karpathy-wiki.md) | 设计来源与取舍 |
| 03 | [硬件与部署](03-hardware-deployment.md) | M4 Pro 24 GB 目标；Windows 当前不受支持 |
| 04 | [快速开始](04-quickstart.md) | 从安装到第一次查询 |
| 05 | [数据模型](05-data-model.md) | library、version、proposal、job 与索引 |
| 06 | [API 与 MCP](06-api-and-mcp.md) | 私有 sidecar/desktop MCP；历史公开 HTTP inventory |
| 07 | [Codex CLI](07-codex-cli.md) | 登录、额度与执行边界 |
| 08 | [运维](08-operations.md) | legacy 服务、队列和索引运维 |
| 09 | [备份与恢复](09-backup-restore.md) | legacy 数据备份与恢复 |
| 10 | [安全](10-security.md) | 威胁模型与当前缺口 |
| 11 | [排错](11-troubleshooting.md) | 常见故障定位 |
| 12 | [模型选择](12-model-selection.md) | 生成与 embedding 模型选择 |
| 13 | [替代方案](13-alternatives.md) | 与其他本地文档方案比较 |
| 14 | [macOS all-in-one](14-all-in-one-macos.md) | 桌面部署决策和高级入口 |
| 15 | [GitHub Actions 与 GHCR](15-github-actions-ghcr.md) | legacy Docker 镜像 |
| 16 | [Electron 桌面版完整指南](16-electron-desktop-guide.md) | DMG、UI、MCP、更新、恢复与发布 |
| 17 | [系统设计](17-system-design.md) | Electron 组合拓扑、信任、时序、数据与代码地图 |
| 18 | [部署与运维总手册](18-deployment-operations.md) | Electron source/release、历史 legacy inventory 与物理门禁 |

## 开发与可追溯性

- [Electron 迁移开发索引](development/README.md)
- [项目状态快照](development/status.md)
- [开发者手册](development/contributor-handbook.md)
- [详细 TODO](development/todo.md)
- [Pre-1.0 work plan](development/work-plan.md)
- [证据记录规范](development/evidence/README.md)
- [迁移路线图](development/roadmap.md)
- [需求—决策—验证矩阵](development/traceability.md)
- [迭代记录](development/iterations/README.md)
- [架构决策记录](adr/README.md)

`Accepted` ADR 代表决策已经确认，不等于发行门禁已经通过。以开发记录中的
`pass`、`fail`、`not-run` 和实际 Release 资产为准。

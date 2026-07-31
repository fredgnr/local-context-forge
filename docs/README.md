# Local Context Forge 文档索引

Local Context Forge 正在从 Docker/Web 部署迁移为 macOS Apple Silicon
Electron all-in-one 客户端。阅读文档时请先区分两条路径：

- **Electron 桌面版**：目标形态。应用内置 Python sidecar、Node/QMD、Web UI 与 MCP
  companion，并已有 tag-only Draft/trusted-main promotion source policy；但真实 GitHub
  settings、正式 Release、干净用户安装、真实 Codex 任务和物理更新门禁仍未完成。整体保持
  **source merge GO / release NO-GO**。
- **legacy Docker/Web**：现有可运行路径，继续保留用于回退；`install.sh` 与
  `docs/15-github-actions-ghcr.md` 描述的是这条路径，不是 Electron 安装器。

在出现经过审查的公开 DMG 之前，不应把 Electron 称为面向普通用户的推荐发行版。当前最完整
的桌面使用、限制与维护说明见
[Electron 桌面版完整指南](16-electron-desktop-guide.md)。

## 产品与使用

| 编号 | 文档 | 主要内容 |
| --- | --- | --- |
| 00 | [产品概览](00-overview.md) | 产品目标、工作流与当前交付状态 |
| 01 | [架构](01-architecture.md) | Wiki 编译流水线和服务边界 |
| 02 | [Karpathy Wiki](02-karpathy-wiki.md) | 设计来源与取舍 |
| 03 | [硬件与部署](03-hardware-deployment.md) | M4 Pro 24 GB 与可选 Windows/4060 分工 |
| 04 | [快速开始](04-quickstart.md) | 从安装到第一次查询 |
| 05 | [数据模型](05-data-model.md) | library、version、proposal、job 与索引 |
| 06 | [API 与 MCP](06-api-and-mcp.md) | HTTP API 和 Context7 兼容工具 |
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

## 开发与可追溯性

- [Electron 迁移开发索引](development/README.md)
- [迁移路线图](development/roadmap.md)
- [需求—决策—验证矩阵](development/traceability.md)
- [迭代记录](development/iterations/README.md)
- [架构决策记录](adr/README.md)

`Accepted` ADR 代表决策已经确认，不等于发行门禁已经通过。以开发记录中的
`pass`、`fail`、`not-run` 和实际 Release 资产为准。

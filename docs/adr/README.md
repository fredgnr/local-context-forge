# Architecture Decision Records

ADR 记录跨组件、难以逆转或具有安全/数据/发行影响的决策。ADR 的 `Accepted` 仅表示
决策已确认；实现与验证状态以
[活动迭代](../development/iterations/0002-bundled-runtimes.md) 和
[追踪矩阵](../development/traceability.md) 为准。

## 状态规则

- `Proposed`：等待评审，不得作为不可逆实现依据。
- `Accepted`：决策生效，后续实现必须遵循。
- `Rejected`：不采用，保留原因。
- `Superseded by ADR-NNNN`：由新 ADR 替代，旧记录不重写。

每份 ADR 必须包含状态、日期、上下文、决策、后果、替代方案和验证门禁。改变已接受
决策时新增 ADR，不在原文中静默改写历史。

## 索引

| ADR | 状态 | 决策 |
| --- | --- | --- |
| [ADR-0001](0001-electron-python-sidecar-boundary.md) | Accepted | Electron Main、React renderer、Python sidecar、Node/QMD 与 CLI/MCP 边界 |
| [ADR-0002](0002-uds-startup-token-protocol.md) | Accepted | 私有 Unix domain socket 与每次启动令牌协议 |
| [ADR-0003](0003-macos-release-signing-update-policy.md) | Accepted | DMG、自签名、受保护发布与更新 fallback |
| [ADR-0004](0004-runtime-paths-legacy-data-migration.md) | Accepted | macOS 路径、按需模型和旧 Docker 数据迁移 |
| [ADR-0005](0005-provider-attempt-execution-boundary.md) | Accepted | CLI provider 的 preflight、持久 attempt 与一次性执行边界 |
| [ADR-0006](0006-dulwich-product-git-boundary.md) | Accepted | 产品运行时以受控 Dulwich 取代系统 Git |
| [ADR-0007](0007-qmd-retrieval-broker-runtime.md) | Accepted | QMD worker、Main broker 与 stale-index 确定性降级 |
| [ADR-0008](0008-mcp-companion-main-bridge.md) | Accepted | 内置 stdio MCP companion 与 Main 只读私有桥 |
| [ADR-0009](0009-bundled-runtime-provenance.md) | Accepted | Python/Node bundled runtime 的来源、清单和打包审计 |
| [ADR-0010](0010-qmd-local-embedding-profile.md) | Accepted | QMD 本地 embedding profile、显式重建与 hybrid 降级 |
| [ADR-0011](0011-main-owned-signed-update-client.md) | Accepted | Main-owned 独立签名更新检查、verified DMG 与显式固定 Release 出口 |
| [ADR-0012](0012-local-repository-picker-opaque-grants.md) | Accepted | 原生本地仓库选择与一次性不透明路径授权 |
| [ADR-0013](0013-codex-mcp-onboarding-signed-cli-discovery.md) | Accepted | Codex MCP 一键接入、签名 CLI discovery、scoped ownership 与私有 rendezvous |
| [ADR-0014](0014-two-stage-desktop-release-promotion.md) | Accepted | tag-only signing/Draft 与 trusted-main、secret-free、immutable promotion 分离 |

## 新 ADR 编号

使用下一个四位编号，文件名为 `NNNN-short-kebab-title.md`。在
[追踪矩阵](../development/traceability.md) 和活动迭代中同时链接；不要复用撤销或拒绝的编号。

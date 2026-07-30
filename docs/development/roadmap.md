# Electron 迁移路线图

## 基线与目标

- 上游基线：`main@5d95e58cefa1c94b5c9ac8dd681671e2dfd6d8dd`
- 开发分支：`agent/electron-desktop-foundation`
- 平台目标：macOS Apple Silicon
- 当前总体状态：`in-progress`

本路线图是交付顺序，不是完成声明。各阶段只有在其退出门禁有可复现 `pass` 证据后，
才能进入 `validated`。

## 依赖图

```text
P0 Governance
 └─> P1 Electron shell and trust boundary
      ├─> P2 Python sidecar
      └─> P3 Node/QMD worker and MCP
           └─> P4 Runtime paths and legacy data migration
                └─> P5 DMG release foundation
                     └─> P6 Physical updater gate
                          └─> P7 Migration exit and Docker retirement decision
```

P2 与 P3 可在 P1 的 IPC 契约冻结后并行；P4 必须等两类持久数据格式和版本标识明确后
再冻结迁移方案。

## 里程碑总览

| 阶段 | 状态 | 迭代 | 主要产物 | 依赖 | 退出门禁 |
| --- | --- | --- | --- | --- | --- |
| P0 治理与契约 | `validated` | ITER-0001 | AGENTS、skills、ADR、迭代、追踪矩阵 | 无 | G0 |
| P1 Electron 壳与信任边界 | `in-progress` | ITER-0001 | Main/preload/renderer 骨架、类型化 IPC | P0 | G1 |
| P2 Python sidecar | `planned` | ITER-0002 | Python 3.12 PyInstaller `onedir`、生命周期契约 | P1 | G2 |
| P3 Node/QMD 与 MCP | `planned` | ITER-0002 | 独立 Node 22/QMD worker、Context7 兼容契约 | P1；与 P2 并行 | G3 |
| P4 路径与迁移 | `planned` | ITER-0003 | macOS 路径、原子迁移、回滚与数据验证 | P2、P3 | G4 |
| P5 DMG 发行基础 | `planned` | ITER-0004 | arm64 DMG、自签名、受保护发布流程 | P1–P4 | G5 |
| P6 更新实机门禁 | `planned` | ITER-0005 | 0.0.1 → 0.0.2 实机报告、DMG fallback | P5 | G6 |
| P7 迁移退出 | `planned` | ITER-0006 | 发布判定、legacy Docker 去留决策 | P6 | G7 |

## P0：治理与契约

交付：

- 根规则与分层规则约定；
- 两个职责分离的项目 skill；
- 初始 ADR、活动迭代和需求—验证映射；
- 相对链接与 skill 结构检查。

G0：

- `VAL-GOV-001` 文档内部链接通过；
- `VAL-GOV-002` 两个 skill 结构通过；
- 所有当前硬约束都有稳定需求 ID、ADR、任务和计划验证；
- 未实现能力均未标记为完成。

## P1：Electron 壳与信任边界

交付：

- React renderer 运行在 sandbox + context isolation 下；
- preload 只暴露版本化、类型化、allowlist IPC；
- Electron Main 独占文件、子进程、更新、凭据和协议路由；
- 窗口、深链和不可信内容使用安全默认值。

G1：

- `VAL-TRUST-001` 证明 renderer 无 Node/原始 IPC/任意路径或命令能力；
- CSP、导航、新窗口、外部链接与 payload 上限的负向测试通过；
- Main/renderer 契约版本不匹配时 fail closed。

当前证据：源码合同与回归已在 Linux x86_64 通过；当前沙箱禁止真实 AF_UNIX bind，
且尚无 GitHub Actions、macOS 或 packaged-app 证据。因此 `VAL-P1-SOURCE-001`、
`VAL-TRUST-001` 和 `VAL-IPC-001` 仍为 `not-run`，G1 未满足，P1 保持
`in-progress`。

## P2：Python sidecar

交付：

- 固定 Python 3.12 构建；
- PyInstaller `onedir` 包含运行所需模块和资源；
- Main 通过私有 UDS 启动、探活、停止和恢复 sidecar；
- 目标 Mac 不使用系统 Python、Git 或 ctags。

G2：

- `VAL-PY-001` 在无系统 Python/Git/ctags 的干净用户环境运行；
- `VAL-IPC-001` 覆盖令牌、权限、超时、崩溃和 stale socket；
- 现有领域回归测试针对打包 sidecar 通过。

## P3：Node 22/QMD worker 与 MCP

交付：

- QMD 在独立、随应用交付的 Node 22 worker 中运行；
- worker 不能获得 renderer 权限或任意命令入口；
- MCP 保持 Context7 兼容工具名、输入和结果语义；
- Codex 在任务前 preflight 为默认，Cursor 只可在该阶段替代。

G3：

- `VAL-QMD-001` 在无系统 Node/QMD 环境完成索引与查询生命周期；
- `VAL-MCP-001` 兼容契约回放通过；
- `VAL-CLI-001` 证明任务开始后不发生 Codex → Cursor fallback。

## P4：运行时路径与旧数据迁移

交付：

- 持久数据、缓存、日志和临时 runtime 各自进入标准 macOS 路径；
- 模型权重仅按需下载，校验后原子激活；
- 旧数据先只读盘点，再经 staging、校验和原子切换迁移；
- 原数据默认保留，可回滚，拒绝新旧 writer 并发。

G4：

- `VAL-DATA-001` 覆盖 fresh、repeat、interrupt、corrupt、low-disk 和 rollback；
- `VAL-MODEL-001` 覆盖 consent、离线、完整性失败与断点恢复；
- legacy 数据在迁移失败后仍可由原版本读取。

## P5：DMG 发行基础

交付：

- 默认用户产物是 macOS arm64 DMG；
- 应用及 sidecar 使用明确的自签名身份，发布记录披露未 notarize、未启用
  hardened runtime；
- 公开仓库的发布秘密只在受保护 `macos-release` Environment 中可用；
- PR、fork 与普通构建不接触发布秘密。

G5：

- `VAL-INSTALL-001` 在未安装 Docker/Homebrew/Python/Node/Git/ctags 的干净 Mac
  完成安装、启动与核心 smoke；
- `VAL-RELEASE-001` 记录 DMG 内容、签名身份、架构和限制；
- `VAL-SECRET-001` 证明非发布工作流拿不到 Environment Secrets。

## P6：0.0.1 → 0.0.2 更新实机门禁

交付：

- 物理 Apple Silicon Mac 上的版本跨越报告；
- 自动更新成功路径；
- 自动更新失败时，校验后自动下载并打开 DMG 的恢复路径；
- 两条路径均保留用户数据且不静默执行安装器。

G6：

- `VAL-UPDATE-001` 在实机完成安装 0.0.1、创建数据、更新至 0.0.2、重启、
  校验版本/sidecar/数据；
- 同一报告注入自动更新失败，验证 DMG fallback；
- G6 通过前，不把自动应用更新列为可交付能力。

## P7：迁移退出与 legacy Docker 决策

交付：

- 汇总 P0–P6 证据、已知限制和回滚路径；
- 对现有 Docker 用户完成迁移演练；
- 根据真实迁移成功率与阻塞缺陷作出独立弃用决定。

G7：

- `VAL-LEGACY-001` 证明支持的旧数据样本迁移成功且原数据可恢复；
- 所有 P0–P6 阻断门禁为 `pass`；
- 在单独 ADR 和用户迁移公告合入前，Docker 始终保持 `legacy`，不得删除。

## 阻断规则

- 任一必需门禁为 `fail` 或 `not-run`，对应阶段不能标记 `validated`/`done`。
- 签名 CI 成功不能替代干净 Mac 安装；模拟更新不能替代实机 0.0.1 → 0.0.2。
- 迁移成功不能由“新应用能启动”推断，必须验证数据数量、引用、索引状态和回滚。
- 后续阶段如需改变已接受 ADR，先新增 superseding ADR，再调整路线图。

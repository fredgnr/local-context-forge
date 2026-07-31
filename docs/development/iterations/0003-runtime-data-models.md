# ITER-0003：Runtime data and models

- 状态：`planned`
- 依赖：ITER-0002 的持久格式与运行时版本冻结
- 路线图阶段：P4

## 目标与范围

实现标准 macOS 数据路径、按需模型获取以及从 legacy Docker 数据的可回滚迁移。迁移遵循
只读盘点、staging、校验、原子切换和保留原数据的顺序；不允许新旧 writer 并发。

## 计划任务

- [x] D01a source foundation：Main 已使用 Application Support、Caches 和 per-launch temp。
- [ ] D01b 冻结 layout version，补齐 ADR-0004 的持久/可重建/日志/更新缓存分层及旧布局兼容。
- [ ] D02 建立迁移清单、空间预检、journal、恢复和回滚。
- [ ] D03 覆盖 fresh、repeat、interrupt、corrupt、low-disk、rollback 样本。
- [x] D04a source foundation：R07 已实现用户触发、profile/revision CAS、forced embed 和
  lexical fallback。
- [ ] D04b 实现固定 publisher/digest/signature、可靠 resume、cache eviction、shadow-index
  staging/atomic swap。
- [ ] D05 覆盖离线、损坏、不可信来源、磁盘不足、取消、publish race 和 rollback。

详细可执行任务见
[TODO-DATA-* / TODO-MODEL-SUPPLY-001](../todo.md)。`[x]` 只表示 source foundation，
不提升本迭代或 `VAL-DATA/MODEL-001`。

## 退出门禁

- VAL-DATA-001、VAL-MODEL-001 为 `pass`；
- 迁移失败后原版本仍能读取原数据；
- 未完成完整性校验的模型永远不会进入 active 路径。

# ITER-0003：Runtime data and models

- 状态：`planned`
- 依赖：ITER-0002 的持久格式与运行时版本冻结
- 路线图阶段：P4

## 目标与范围

实现标准 macOS 数据路径、Desktop 自身的 backup/restore，以及按需模型获取。根据
[ADR-0015](../../adr/0015-electron-only-legacy-retirement.md)，不再实现 legacy Docker 数据
importer、converter 或 compatibility shim；未知旧 layout/schema 必须 fail closed，应用不得
自动覆盖或删除旧数据。

## 计划任务

- [x] D01a source foundation：Main 已使用 Application Support、Caches 和 per-launch temp。
- [ ] D01b 冻结新的 desktop-only layout version，补齐持久/可重建/日志/更新缓存分层；未知或
  legacy layout 只允许拒绝并提示 fresh/reset，不提供兼容读取。
- [ ] D02 建立 Desktop backup manifest、空间预检、staging、atomic restore 和 rollback。
- [ ] D03 覆盖 fresh、backup、restore、repeat、interrupt、corrupt、low-disk、rollback 样本。
- [x] D04a source foundation：R07 已实现用户触发、profile/revision CAS、forced embed 和
  lexical fallback。
- [ ] D04b 实现固定 publisher/digest/signature、可靠 resume、cache eviction、shadow-index
  staging/atomic swap。
- [ ] D05 覆盖离线、损坏、不可信来源、磁盘不足、取消、publish race 和 rollback。

详细可执行任务见
[TODO-DATA-LAYOUT-001、TODO-DATA-BACKUP-001、TODO-MODEL-SUPPLY-001](../todo.md)。
`TODO-DATA-MIGRATION-001` 已由 ADR-0015 取代，不在本迭代执行。`[x]` 只表示 source foundation，
不提升本迭代或 `VAL-DATA/MODEL-001`。

## 退出门禁

- VAL-DATA-001、VAL-MODEL-001 为 `pass`；
- unknown/legacy layout 不被静默解释、覆盖或删除；
- Desktop backup/restore 失败后当前 active 数据仍可恢复；
- 未完成完整性校验的模型永远不会进入 active 路径。

# ITER-0003：Runtime data and models

- 状态：`planned`
- 依赖：ITER-0002 的持久格式与运行时版本冻结
- 路线图阶段：P4

## 目标与范围

实现标准 macOS 数据路径、按需模型获取以及从 legacy Docker 数据的可回滚迁移。迁移遵循
只读盘点、staging、校验、原子切换和保留原数据的顺序；不允许新旧 writer 并发。

## 计划任务

- [ ] D01 实现 Application Support、Caches、Logs 和临时 runtime 的路径适配器。
- [ ] D02 建立迁移清单、空间预检、journal、恢复和回滚。
- [ ] D03 覆盖 fresh、repeat、interrupt、corrupt、low-disk、rollback 样本。
- [ ] D04 实现模型用户确认、断点下载、摘要校验与原子激活。
- [ ] D05 覆盖离线、损坏、来源不可信和磁盘不足。

## 退出门禁

- VAL-DATA-001、VAL-MODEL-001 为 `pass`；
- 迁移失败后原版本仍能读取原数据；
- 未完成完整性校验的模型永远不会进入 active 路径。

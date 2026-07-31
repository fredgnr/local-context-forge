# ITER-0006：Legacy migration and exit decision（已取代）

- 状态：`superseded`（由 [ADR-0015](../../adr/0015-electron-only-legacy-retirement.md) 与
  [ITER-0007](0007-electron-only-retirement.md) 取代）
- 依赖：ITER-0001–0005 全部阻断门禁通过
- 路线图阶段：P7

> 历史记录：本计划要求先完成 legacy 数据迁移、回滚和保留评审。2026-07-31 的产品决策
> 明确项目仍处于早期研发期，不再承诺 legacy 部署、数据、配置或协议兼容，因此本计划不再
> 执行。下面的任务和门禁仅保留用于解释旧路线，不能据此继续开发 migration/importer，也
> 不能把从未运行的 `VAL-LEGACY-001` 标为 `pass`。

## 目标与范围

使用代表性 legacy Docker 数据完成迁移演练，再通过独立 ADR 决定 Docker、Compose、
Host Runner 和原安装器的保留、弃用时间与恢复路径。本迭代开始前不得删除 legacy 路径。

## 计划任务

- [ ] L01 建立经过脱敏的代表性迁移样本和计数基线。
- [ ] L02 验证页面、引用、任务、索引、设置与原数据恢复。
- [ ] L03 汇总 P0–P6 证据、已知限制和用户迁移成本。
- [ ] L04 提交独立 legacy 去留 ADR 与用户公告草案。
- [ ] L05 仅在 ADR 接受后执行相应清理。

## 退出门禁

- VAL-LEGACY-001 为 `pass`；
- 所有前置阻断门禁为 `pass`；
- 原数据、备份和回滚期限在任何删除前明确记录。

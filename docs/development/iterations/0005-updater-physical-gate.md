# ITER-0005：Updater physical gate

- 状态：`planned`
- 依赖：W15 的正式候选与 ITER-0004 受保护工作流；W16 至少两个真实单调 Release
- 路线图阶段：P6

## 目标与范围

只在物理 Apple Silicon Mac 上用两个真实、单调且与 tag/manifest 一致的版本完成
`N-1 → N` 后，才可讨论启用 automatic apply。ADR-0003/0011 中的
真实 `N-1 → N` 是版本关系，不是可伪造的固定 tag。当前实现只提供 signed
check/download 和用户确认后的 verified DMG open；automatic apply 还必须先新增或
supersede ADR-0011。

## 计划任务

- [ ] U01 完成生产更新元数据/public pins，并新增或 supersede ADR-0011 以决定 automatic
  apply/install/restart/rollback；signed client source foundation 已存在。
- [ ] U02 安装真实 `N-1`、创建真实数据、更新至真实 `N` 并验证重启与数据。
- [ ] U03 注入下载、校验、替换或重启失败。
- [ ] U04 验证 DMG fallback 不静默执行安装器且不丢失数据。
- [ ] U05 记录机器、macOS、版本、产物摘要、步骤与审查人。

## 退出门禁

- VAL-UPDATE-001 为 `pass`；
- 成功与失败路径均来自物理机证据；
- 门禁通过前 UI 和文档不得宣称“自动更新可用”。

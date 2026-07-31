# ADR-0007：QMD worker、Main broker 与确定性检索降级

- 状态：Accepted
- 日期：2026-07-30
- 关联需求：REQ-QMD-001、REQ-IPC-001、REQ-TRUST-001
- 后续决策：第 8 条由 [ADR-0010](0010-qmd-local-embedding-profile.md) 部分取代

## 上下文

现有 Python `QmdRetriever` 直接调用宿主 `qmd` 命令，不满足 all-in-one。QMD 需要 Node 和
native SQLite addon，但 renderer 与 Python 均不应获得 QMD worker 的启动令牌。索引可能
落后于已发布 corpus，worker 也可能崩溃；查询不能把 stale 或部分索引伪装为最新结果。

## 决策

1. 固定 Node 22.23.2 与 QMD 2.5.3，使用独立 Node worker。worker 仅监听本次私有 UDS，
   QMD token 只经 Main 到 worker 的专用 fd3 传递，不进入 argv、环境、磁盘或 Python。
2. Main 在 Python 和 QMD 之间提供私有 retrieval broker。Python 通过独立、单次启动的
   broker capability（fd4）调用 allowlist 的 reconcile/search；它永远看不到 QMD token。
3. Main 验证 corpus/library/revision、collection 名称、Wiki root 和每个路径组件；拒绝
   symlink、越界、未知字段、过大 payload、非 canonical UUID/token/socket 和过长 UDS。
4. reconcile 总是提交完整 published corpus allowlist，不发送增量删除命令。超过 256 个
   collection 时明确返回 `too_many_collections`/`indexed=false`，不得对前 256 个做部分
   reconcile。
5. search 结果必须带匹配的 corpus revision。`stale_index`、revision 不一致、QMD 不可用、
   无效响应或 broker 错误时，Python 回退到既有 deterministic lexical 排序，并明确标记
   retrieval mode。
6. 只有 search 的传输故障允许 Main 重启 worker 并重试一次；stale revision 不重试，
   reconcile 从不自动重放。
7. collection 删除通过 committed allowlist 立即禁止查询。QMD 2.5.3 公共 API 不保证物理
   删除旧 documents，因此物理 compact/cleanup 不得作为已实现能力；状态和诊断需披露累积。
8. P2 只交付 lexical QMD。embedding/model 权重不随 bundle 安装，也不在启动时下载；
   后续语义检索必须遵循 ADR-0004 的显式同意、完整性和原子激活规则。

## 后果

- Python 与 QMD 的能力和令牌相互隔离，renderer 仍只有领域查询接口；
- stale/崩溃时查询可用性由确定性 lexical fallback 保持，但结果质量可能下降；
- 全量 reconcile 有明确上限和可解释失败，不会出现部分索引冒充完整 corpus；
- QMD 数据库可能保留不可查询的旧 documents，后续需要独立维护策略。

## 替代方案

1. **Python 直接启动 `qmd` CLI。** 拒绝：依赖系统 Node/QMD并泄露生命周期边界。
2. **把 QMD token 给 Python。** 拒绝：扩大 capability 泄露半径。
3. **renderer 直接查询 worker。** 拒绝：绕过 Main 信任边界。
4. **stale 时返回旧索引结果。** 拒绝：会把不一致结果标成当前 corpus。
5. **超过上限时索引部分 library。** 拒绝：状态不可解释。

## 验证门禁

- VAL-QMD-001 覆盖 worker 认证、UDS、全量 reconcile、revision、allowlist、上限、
  stale fallback、search 单次重启和 reconcile 不重放。
- bundled Node/better-sqlite3 必须在 macOS arm64 真实运行；`PATH` trap 证明不发现系统
  Node、qmd、Git、Python 或 ctags。
- 离线 lexical 测试不得下载模型或产生模型文件；native `.node`、dylib/RPATH、SBOM、
  notices 和 staged manifest 通过审计。

# ITER-0002/R07：QMD local embeddings

- 状态：`in-progress`
- 开始日期：2026-07-31
- 父迭代：[ITER-0002](0002-bundled-runtimes.md)
- 决策：[ADR-0010](../../adr/0010-qmd-local-embedding-profile.md)
- 上游基线：`main@5d95e58cefa1c94b5c9ac8dd681671e2dfd6d8dd`
- 当前工作分支：`agent/electron-bundled-runtimes`
- 追踪矩阵：[traceability](../traceability.md)

## 目标与固定范围

这是 ITER-0002 的独立 R07 实施/证据记录，不改写该迭代最初“P2 lexical-only、无模型下载”
的历史范围。ADR-0010 接受后，R07 作为显式追加纵切：

- 依据已安装、锁定的 `@tobilu/qmd@2.5.3` 公共 API 实现真实 local embedding；
- 后端现有 curated/custom HF GGUF 选择形成跨 Python/Main/worker 的安全 profile；
- 用户触发的 global rebuild 完成 model preparation、forced vector rebuild 和原子状态 CAS；
- embedding ready 时用 typed lex+vec hybrid；失败/stale 时 deterministic lexical fallback；
- 保持 QMD token 只在 Main/worker、完整 corpus reconcile、search 单次 restart 和 renderer
  最小能力。

不包含 query-expansion/reranker 模型、任意 URL/本地模型、DMG 预装权重、发布签名、
custom model 固定 digest 清单、shadow-index 原子切换或 clean-user DMG 结论。

## 任务

- [x] **R07-01 治理与 API 核实**：新增 ADR-0010；读取实际 package exports/types/source，
  记录 `createStore`、`update`、`embed` 和 typed-query `search` 签名。
- [x] **R07-02 worker**：profile validation、model-aware store lifecycle、forced embed、
  persisted profile/revision、hybrid search、cache/status/error sanitization。
- [x] **R07-03 Main broker**：exact contract、profile/revision commit、长时 rebuild deadline、
  crash/retry 和错误翻译。
- [x] **R07-04 Python/service**：desktop rebuild 真实传递 embed/model，hybrid-ready 查询，
  model/corpus/cancel CAS 和 lexical fallback。
- [x] **R07-05 验证**：worker、Main、Python/service focused suites；记录真实 native/model
  download 与 macOS arm64 未运行项。

## 验收

- [x] 普通 reconcile/search 不准备模型；embedding rebuild 才调用
  `embed(force=true, model=<validated profile>)`。
- [x] embedding state 只有 profile、revision、health 全匹配才 ready/hybrid。
- [x] model switch、离线、embed error、stale revision、worker crash、取消和 corpus race 均
  不激活旧/部分 vector index。
- [x] worker store replacement 不可恢复时 reconcile 只失败一次；Main 清空 gate 并重启
  worker，不隐式重放；model/revision 在 claim 前变化时不进入 retriever。
- [x] 错误和状态不包含 capability、socket、cache/Wiki/home path、URL 或 native stderr。
- [ ] packaged Node/QMD 在 clean macOS arm64 完成真实首次下载、forced rebuild 和 hybrid；
  未运行前保持 `not-run`。

## 验证日志

| 验证 | 结果 | 日期/提交 | 命令或过程 | 证据/说明 |
| --- | --- | --- | --- | --- |
| VAL-QMD-EMBED-001 source | `pass` | 2026-07-31；工作树 | `cd desktop/workers/qmd && npm test` | 8 pass；2 AF_UNIX sandbox skip；1 better-sqlite3 native-not-built skip；fake store 锁定 close→profile store、stale-first、forced embed 与 typed hybrid |
| VAL-IPC-EMBED-001 source | `pass` | 2026-07-31；工作树 | `cd desktop && npm run typecheck && npm test -- --run`；`cd backend && .venv/bin/pytest ...` | Desktop 136 pass/5 sandbox skip；Backend focused 66 pass；backend excluding optional MCP-formatting dependency 283 pass/1 skip |
| VAL-MODEL-EMBED-001 source race 子检查 | `pass` | 2026-07-31；工作树 | worker + `test_desktop_retrieval.py` | 模拟 cold/unavailable、ENOSPC/partial cache、取消、claim 前 model switch 不调用 retriever、完成前 model switch activation CAS 与路径脱敏；没有下载真实权重 |
| VAL-MODEL-EMBED-001 real download | `not-run` | — | 需真实模型、离线/磁盘矩阵 | 当前 source checkout 没有 built better-sqlite3，也不以 mock 代替 |
| VAL-QMD-001 macOS/native | `not-run` | — | 需 packaged macOS arm64 | 不以当前 Linux Node 代替 |

## 风险与回滚点

| 风险 | 缓解/回滚点 |
| --- | --- |
| QMD store model 在创建时固定 | profile switch 关闭并以 `config.models.embed` 重开 store |
| `force` 在下载/embedding 失败前清除旧向量 | stale-first 持久化、health 验证、Python CAS；查询回 lexical |
| 首次模型下载较慢或离线 | 独立长 deadline、有限状态/错误码、普通 lexical 不触网 |
| custom HF 资源缺少固定 digest manifest | 不宣称完整 VAL-MODEL-001；后续按 ADR-0004 补齐 |
| cold download 磁盘满/中断留下 `.partial` cache | partial 仍是可清除 cache，worker state 保持 unavailable/failed；不记录路径，不把 profile/revision 标 ready；后续显式 rebuild 由 node-llama-cpp resume/replace |
| 取消无法中断 QMD SDK 内部所有 native 阶段 | 完成后 CAS 拒绝激活；即使 worker DB 已写完向量，Python embedding state 仍 stale，查询不发送 hybrid；后续 rebuild 再 force |
| profile store 与 lexical fallback store 都无法打开 | reconcile 返回脱敏失败；Main 清空 revision/profile gate 并重启 worker，但不重放该 reconcile；下一次用户显式 retry 使用新 worker |

## 当前变更清单

- `docs/adr/0010-qmd-local-embedding-profile.md`
- `docs/development/iterations/0002-r07-qmd-embeddings.md`
- `desktop/workers/qmd/{index.mjs,src/**,test/**}`
- `desktop/src/main/{qmdClient,qmdSupervisor,retrievalBroker}.ts`
- `desktop/tests/{qmdClient,qmdSupervisor,retrievalBroker}.test.ts`
- `backend/app/{desktop_retrieval,service,version}.py`
- `tests/backend/test_desktop_retrieval.py` 及相关 service tests

package lock、QMD staging/build/audit、MCP 和 release workflow 由 ITER-0002 其他任务维护；R07
不修改这些路径。

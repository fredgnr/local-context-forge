# ADR-0010：QMD 本地 embedding profile、显式重建与 hybrid 降级

- 状态：Accepted
- 日期：2026-07-31
- 关联需求：REQ-QMD-001、REQ-MODEL-001、REQ-IPC-001、REQ-TRUST-001
- 部分取代：ADR-0007 第 8 条、ADR-0009 第 4 条中的 P2 lexical-only/no-model-download 范围
- 保留约束：ADR-0007 第 1–7 条及 ADR-0004 的模型缓存、完整性与激活原则

## 上下文

R03 的 QMD worker 已能用 QMD 2.5.3 SDK 完成 collection reconcile 和 BM25 检索，但
desktop `DesktopRetriever.rebuild(embed=True)` 仍把请求降为 lexical reconcile，查询也固定
发送 `hybrid=False`。因此设置页允许选择 embedding model、数据库记录 `ready` 的状态和实际
worker 行为不一致：模型不会被使用，强制重建不会生成向量。

锁定的 `@tobilu/qmd@2.5.3` 公共 SDK 已核实提供：

- `createStore({dbPath, config.models.embed})` 为 store 选择 embedding model；
- `store.update()` 更新 BM25 文档；
- `store.embed({force, model, ...})` 强制重建向量；
- `store.search({queries: [{type: "lex"}, {type: "vec"}], rerank: false, ...})`
  在只加载 embedding model 的情况下执行 BM25 + vector/RRF hybrid 检索。

直接调用简单 `store.search({query})` 会额外触发 query-expansion/reranker 模型，不符合本轮
只启用用户所选 embedding model 的最小下载边界。

## 决策

1. desktop semantic 路径只使用上述 QMD 2.5.3 公共 SDK 签名。hybrid 查询传入显式
   `lex` + `vec` typed queries 且 `rerank=false`；本轮不下载 query-expansion 或 reranker
   模型。
2. 跨 Python、Main、worker 的模型输入是 exact-key profile：
   `{kind: "curated" | "custom", model: "hf:org/repo/file.gguf"}`。三个边界分别验证：
   curated profile 必须等于后端现有两个固定 model URI；custom profile 必须符合既有安全
   Hugging Face GGUF 语法，并且属于 EmbeddingGemma 或 Qwen3-Embedding family。HTTP URL、
   本地路径、未知字段、kind/model 不一致一律拒绝。
3. 模型下载只可由用户创建的全局 embedding rebuild job 间接触发。启动、普通 publish/
   reconcile 和 lexical 查询不得触发模型下载。QMD model cache 使用 Main 下发并验证的私有
   app cache root，不写入 bundle、argv 之外的隐式宿主路径或 renderer 可见状态。
4. worker 对完整 corpus 先执行 collection reconcile + `update()`，然后在 rebuild 请求中用
   `embed({force: true, model, chunkStrategy: "auto", maxDocsPerBatch: 50,
   maxBatchBytes: 64 MiB})`。模型 profile、embedding revision 和 ready/stale/failed 状态以
   原子 state file 持久化；只有零 embedding errors 且 index health 不再需要 embedding 时
   才标记 ready。
5. worker store 的 model 在 profile 切换时通过新的 `createStore` 实例切换；不得假设
   `embed({model})` 会改变已创建 store 内部固定的 LlamaCpp model。切换、强制清空向量或
   embed 前先持久化 stale 状态；崩溃、超时或部分失败不能保留 ready 标记。
6. hybrid search 同时携带 corpus revision 和 model profile。Main 与 worker 都要求它们和
   已提交的 embedding state 完全匹配，并在查询前确认模型 cache 文件与 QMD index health；
   任一 stale、缺失、异常、worker crash 或响应不匹配均回到 Python 的 deterministic
   lexical search。普通 lexical QMD search 仍可在 embedding 失败后工作。
7. reconcile 返回脱敏的 `model_status` 和有限错误码（例如 `model_unavailable`、
   `embedding_failed`），不返回 cache path、下载 URL、原始 native 错误或 stderr。
   worker health 只报告有限 activity/status；完整本地路径仍不得进入 Python、renderer 或
   job error。
8. reconcile 仍不自动重放。若 reconcile 因不可用 worker 失败，Main 先清空本地
   revision/profile gate，再只重启 worker，不在后台重发原请求；下一次显式 reconcile
   才可继续。search 仍只允许一次有界 worker restart/retry。Python 在进入 retriever 前先以
   desired model + corpus revision compare-and-set 取得 rebuild claim，完成后再次核对 job
   未取消并以相同条件 compare-and-set 激活；取消、并发 model switch 或 publish race 的
   结果保持 stale/failed，claim 已失效时不得执行耗时模型工作。
9. 本轮依赖 QMD/node-llama-cpp 对下载临时文件、最终大小和 GGUF magic 的校验，但没有独立
   固定每个 custom model 的发布者签名/digest。因此只记录 VAL-MODEL-EMBED-001 子门禁，
   不把 ADR-0004 的完整 VAL-MODEL-001（固定 digest/signature、resume、cache eviction 和
   原子 index staging/swap）宣称为已完成。

## 后果

- desktop 的 model setting、重建 job、持久状态和实际 QMD model/vector 行为一致；
- 首次 embedding rebuild 可能下载数百 MiB，并在离线或缓存损坏时明确失败，但 BM25/
  deterministic lexical 查询保持可用；
- typed-query hybrid 不需要额外的 expansion/reranker 权重，下载和显存边界更小；
- QMD `force` 在同一数据库中重建向量，虽然 stale-first/CAS 能防止错误激活，但完整的 shadow
  index 原子切换仍留给 ADR-0004 后续门禁。

## 替代方案

1. **继续让 desktop 永远 lexical。** 拒绝：与现有设置、重建 API 和用户选择不一致。
2. **只把 model 传给 `store.embed()`。** 拒绝：QMD 2.5.3 store 的 LlamaCpp model 在
   `createStore()` 时确定，可能用错误模型生成向量。
3. **调用 `store.search({query})`。** 拒绝：会隐式加载 expansion/reranker 模型。
4. **允许任意 URL 或本地 GGUF 路径。** 拒绝：扩大下载来源和本地文件读取能力。
5. **embedding 失败后仍返回旧 vector 结果。** 拒绝：profile/revision 不一致不可解释。
6. **把原始模型错误或 cache path 返回 UI。** 拒绝：泄露本地路径并使 API 不稳定。

## 验证门禁

- VAL-QMD-EMBED-001：worker 单元/集成覆盖真实 QMD 2.5.3 方法签名、profile validation、
  `update` + forced `embed`、hybrid typed queries、state restore、模型切换、失败与 stale。
- VAL-IPC-EMBED-001：Main/Python exact contract、超时、revision/profile mismatch、失败
  reconcile 不重放的 worker replacement、崩溃 restart 和无路径泄露。
- VAL-MODEL-EMBED-001：用户触发的首次准备状态、缓存命中、离线失败、GGUF 缺失/无效、
  model switch、取消/publish race；只可把实际运行过的环境标记 `pass`。
- clean macOS arm64 packaged model download/native embedding/hybrid 仍是物理门禁；Linux fake
  store 或无模型 source tests 不得替代。

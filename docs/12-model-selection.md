# 模型选择、QMD 重建与评估

## 两类模型、两个职责

LCF 把模型分开：

- **检索模型（Mac）**：embedding；只导航已发布 Wiki。
- **生成模型**：Electron 默认调用 Mac 上已登录的 Codex CLI；legacy 可选 Windows/Ollama。

不要用一个“大模型”同时承担所有任务，也不要把 embedding 分数当作事实置信度。没有 ready
的全局 embedding profile 时，产品使用不含旧向量的 lexical-only 路径；只有真实评测证明自然
语言召回不足时才需要 hybrid。

本文把这类路径简写为 “lexical fallback”，但响应的 `engine` 要更精确：desktop 指定
library 且 QMD broker/revision 健康时是 `qmd-bm25`；broker/响应失败或全局查询是 Python
`lexical`。Legacy/native retriever 也可能直接使用 Python `lexical`。

Desktop 当前明确使用 QMD typed `lex + vec`、`rerank=false`，不会下载 query expansion 或
reranker 模型。Legacy/native QMD 的命令和缓存是另一部署配置，不能据此推断 desktop bundle
会启用额外模型。

## 检索默认值

全局 profile 记录 desired/active model、corpus/indexed revision 与 rebuild 状态。模型改变或
新版本发布后状态为 stale，查询自动使用上述 lexical-only 路径。只有持久队列中的
`embedding_rebuild` 成功，并且完成时的目标模型与 corpus revision 仍匹配，profile 才变为
ready 并允许 hybrid。

`LCF_QMD_HYBRID_ENABLED` 是管理员的一次性部署级总开关，all-in-one 默认 `true`。这只表示
允许 hybrid，不会在安装或发布时自动下载模型；只有用户在 Web/API 明确提交全局 rebuild 后才会
下载、构建并激活向量。需要完全禁用向量的环境可把它设为 `false` 并重启。总开关关闭、
profile stale、QMD 不可用或 rebuild 失败时都使用 lexical。

交付配置不依赖 QMD 隐式默认值，而是把 embedding URI 明确固定为：

```dotenv
QMD_EMBED_MODEL=hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf
```

启用 hybrid 后，当前 QMD 组合大致为：

| 任务 | 模型 | 大约大小 | 选择理由 |
|---|---|---:|---|
| embedding | EmbeddingGemma 300M Q8 | 300 MB | 英文代码/技术文档足够轻，适合 M4 Pro 24 GB |

来源：[QMD README](https://github.com/tobi/qmd)。英文代码库无需为中文兼容换模型；
`Qwen3-Embedding-0.6B` 可以作为 A/B 候选，但只能由本地 query 集决定是否升级。

## QMD 写入的共同规则

所有由 LCF 发起的 collection register/update/embed/remove/rebuild 共用一个跨进程 writer lock。
不要在 API 运行时直接执行 `qmd update` 或 `qmd embed`，否则会绕过该锁。日常写操作统一在 Web
“系统设置”提交，或调用 `POST /api/rebuilds`。它创建 SQLite 持久 FIFO 中的
`embedding_rebuild` job，注册**完整的 fully published corpus**，然后执行无 collection 参数的
全局 `qmd update` 与 `qmd embed -f`。即使 API 接受 library scope，该 scope 也不能把共享的
向量空间变成局部重建。

任一 registration、全局 update 或 embedding 失败，job 都保留阶段与错误，可从任务页重试。
失败或取消不会激活半成品 profile，查询继续 lexical fallback。`scripts/reindex.sh` 仅作为
资深用户的同步诊断入口，也必须经过 API/writer lock。

Compose 和 native 是两个独立运行方式。它们共享 SQLite/Wiki 数据，但 QMD 路径不同：

| 运行方式 | QMD config | QMD cache/index |
|---|---|---|
| Compose | 宿主 `data/qmd/config`（容器 `/data/qmd/config`） | 宿主 `data/qmd/cache` |
| native | `data/qmd/native-config` | `data/qmd/native-cache` |

Web/API 只操作当前 runtime 的 config。`reindex.sh`、`make qmd-embed` 与
`make qmd-embed-native` 也都只调用 `LCF_API_URL` 指向的当前 API；target 名不会选择 runtime。
不要同时运行两个 API，也不要把一套 config/cache 交给另一套 runtime。

## 完整流程 A：Docker Compose

以下是 legacy/development 配置。若实例由安装器创建，先按
[部署总手册](18-deployment-operations.md#22-安装)定义 `lcf_managed`，再运行
`lcf_managed start|status|doctor`。当前 `scripts/lcf` 本身不会清除调用者
shell/Compose 覆盖；裸 Compose 只用于你明确管理的开发 checkout。

### 1. 启动并检查状态

确认 native 服务已停止，然后启动 Compose：

```bash
LCF_API_BASE="http://127.0.0.1:8000"
docker compose up -d --build
docker compose ps
docker compose exec api qmd status
```

后续命令沿用同一 shell 中显式设置的 `LCF_API_BASE`；自定义端口时在执行任何写操作前修改并
核对该值。

### 2. 发布 Wiki，再提交全局重建

完成 ingest/review/publish 后，在 Web 的“系统设置”选择 curated embedding 模型并点击重建。
高级用户也可以填写严格校验的 `hf:org/repo/file.gguf`；系统不接受 HTTP embedding endpoint。
任务进入持久 FIFO，可显示 queue position、取消或失败后重试。命令行等价入口为：

```bash
curl --fail-with-body -X POST \
  -H 'Content-Type: application/json' \
  -d '{}' \
  "${LCF_API_BASE}/api/rebuilds" | jq
```

索引重建不调用生成模型，也不消耗 Codex/Cursor 额度。成功后确认
`/api/system/status` 中 `embedding.hybrid_ready=true`，再直连 API 预热：

```bash
curl --fail-with-body --max-time 650 \
  -H 'Content-Type: application/json' \
  -d '{"library_id":"/local/acme-widget","query":"create client timeout","limit":1}' \
  "${LCF_API_BASE}/api/query" | jq '{engine, hits:(.results|length)}'
```

期望 `engine=qmd-hybrid`。Codex MCP 还应设置 `tool_timeout_sec = 660.0`，MCP gateway 的
`BACKEND_TIMEOUT_SECONDS=660` 是另一层独立超时。

## 完整流程 B：macOS native

### 1. 完全停止 Compose，再安装原生依赖

```bash
docker compose down
./scripts/macos-bootstrap.sh --native
```

### 2. 启动 native API

在终端 A：

```bash
make dev-native
```

`dev-native.sh` 会把 native config/cache 与 `QMD_EMBED_MODEL` 注入 API。保持该终端运行。

### 3. 通过当前 native API 建立向量

在 Web 提交全局重建，或在终端 B 调用上一节的 `POST /api/rebuilds`。确认 job completed 且
`embedding.hybrid_ready=true` 后再 warm-up。不要为了复用向量把 native API 指向
`data/qmd/config`；宿主绝对 Wiki 路径与容器 `/data/...` 路径不同。

## 更换 embedding 模型

正确顺序对 Compose/native 都相同：

1. 在 Web 从 curated presets 选择模型，或填写安全的 `hf:org/repo/file.gguf`；
   API 使用 settings revision 防止并发覆盖。
2. 修改后 desired model 立即更新，profile 变为 stale，查询继续 lexical fallback。
3. 提交全局 rebuild job；worker 注册完整 published corpus，并固定使用 `-f`。
4. 检查 job completed，以及 active/desired model、indexed/corpus revision 全部一致。
5. 运行固定 query 集评测并记录模型 URI/digest、QMD 版本和结果编号。

试验 Qwen3 0.6B 的候选 URI：

```dotenv
QMD_EMBED_MODEL=hf:Qwen/Qwen3-Embedding-0.6B-GGUF/Qwen3-Embedding-0.6B-Q8_0.gguf
```

不要用临时 `export` 或直接修改 QMD config 绕过设置 API，也不要让不同 embedding 模型共享一个
“看似 ready”的 profile。

## 新版本发布后的动作

新版本 publish 会推进 corpus revision，并把 embedding profile 标为 stale；查询随即回退到
lexical。提交新的全局 rebuild job 后，worker 注册全部已发布版本并刷新共享向量空间。QMD
busy/失败不会回滚已经激活的 Git/SQLite version，运维方应根据 job 错误修复后重试。

“重建索引”和“重新采集仓库”是两个操作：前者不调用 LLM，只重新索引已审核内容；后者重新运行
Codex/Cursor/Ollama，产出新 proposal，因此会消耗相应额度并再次进入审核。

## 生成模型：RTX 4060 起点

建议把 Ollama `qwen3.5:9b` Q4 作为候选起点，条件是当前模型目录确有该 tag 且本机测试稳定。
不同时间、平台的模型目录会变化，安装脚本不会替你偷偷换模型。

模型选择优先级：

1. 严格遵循 JSON schema。
2. 从证据生成准确的签名、约束和反例。
3. 不伪造 source_ref。
4. 8 GB VRAM 下 8K–16K 上下文稳定。
5. 单页吞吐可接受。
6. 文风与覆盖度。

若 9B OOM，先缩 `LCF_MAX_MODEL_*` outbound budgets 与上下文，再试 7B/8B Q4。不要靠取消
source-ref/review gate 换速度。

Codex CLI 适合复杂架构 overview、跨文件关系与高价值页面 second opinion，不适合默认批量后端；
即使使用 Codex，也必须走相同 proposal/schema/source-ref/review 流水线。详见
[Codex CLI](07-codex-cli.md)。

## 评测集

为每个代表性仓库维护 30–100 个问题：

```json
{
  "query": "How do I configure request timeout?",
  "library_id": "/local/acme-widget",
  "version": "v1.4.0",
  "expected_pages": ["api/client-create", "guides/timeouts"],
  "must_contain_refs": ["src/acme/client.py"],
  "category": "usage"
}
```

覆盖精确符号/参数/错误码、自然语言用法、多步骤 guide、breaking change、相似名称歧义，以及
“文档中没有答案”的负样本。

检索至少记录 Recall@5、MRR、nDCG@10、版本过滤正确率、精确 API 名称 top-1、无答案行为、
p50/p95 延迟和内存。生成至少记录 schema 首次通过率、source_ref 有效率、签名精确率、审核
接受率与修改量。

## A/B 流程

1. 固定源码 snapshot、事实包、QMD 版本与 query 集。
2. 每个模型使用独立 config/cache；不要混向量。
3. 按对应 Compose 或 native 完整流程启动、reindex、warm-up。
4. 冷/热各测一次，先比较召回，再比较 rerank。
5. 人工盲审生成页面，不显示模型名。
6. 只有质量提升超过资源与运维成本时才升级。

对本项目而言，“类型化 Wiki + 证据 + 版本隔离”通常比从 300M/0.6B embedding 盲目升级到 4B
带来更大的收益。

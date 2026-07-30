# 从 Karpathy 的 “LLM-maintained Wiki” 得到的改进

参考方案：[gist: LLM-maintained persistent wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)。

## 关键判断

传统 RAG 在每个问题到来时执行“切块 → 召回 → 在临时上下文里重新推理”。对于 API 文档，这会导致：

- 同一问题在不同时间得到不同叙述。
- 精确签名和跨文件关系容易被语义召回漏掉。
- 已经做过的综合分析无法积累。
- 很难审阅“知识库改变了什么”。
- 版本之间的知识容易混在一起。

gist 提议把 LLM 当成 Wiki 的维护者：原始资料进入后，模型持续整理一份可编译、可 lint、可 Git 跟踪的知识层。查询优先读这份持久知识，而不是每次从原料重新推导。

## LCF 对原方案的工程化扩展

| 原始思路 | LCF 的落地 |
|---|---|
| raw / wiki / schema 三层 | immutable snapshot / fact evidence / typed Wiki |
| ingest、query、lint | 后台 job、proposal review、publish、QMD query、全局 lint |
| `index.md` | 每个 library/version 的可检索入口与结构化 `index.json` |
| `log.md` | 追加发布日志 + Git commit |
| Git 保存 Wiki | 每次发布写审计提交，可 diff/tag；当前 runtime 仍读 SQLite，不能仅用 Git 回滚 |
| 可选 qmd 搜索 | QMD 成为发布层的混合检索引擎 |
| LLM 自行维护知识 | 增加确定性 API 抽取与证据约束，降低幻觉 |
| 自由 Markdown | 增加 JSON Schema sidecar、稳定 ID 与写入时实体解析 |
| 单人笔记式流程 | 增加提案、审批、策略门和服务化 API/MCP |

## 为什么不能只让模型读完整仓库

“让代理自由浏览并写 Wiki”适合个人试验，但在代码知识库里有四个风险：

1. **上下文预算**：大型仓库无法完整放入单次上下文。
2. **不可复现**：代理选择了哪些文件不透明。
3. **指令注入**：仓库中的 README、issue 模板、`AGENTS.md` 或测试数据可能包含诱导指令。
4. **事实漂移**：模型可能把旧文档、测试 fixture 或注释误当当前 API。

LCF 因此先构建有字节上限的 evidence pack：它是数据，不是指令，并带路径和行号。生成器使用 schema；系统把每页引用绑定到该 provider 在预算裁剪后实际可见的 evidence/symbol 行范围，发布门再验证 source SHA、非敏感普通文件路径与行号。验证器仍不做 claim-support 语义蕴含判断。

## “编译 Wiki”的含义

这里的“编译”不是把 Markdown 变成 HTML，而是从多个输入层产生一个可验证制品：

```text
source snapshot
  + symbol facts
  + tests/examples
  + old wiki
  + generator/version/schema
          │
          ▼
proposal.json
          │ schema + visible evidence range + source SHA/path/line gate
          ▼
published markdown + sidecar + index + log + git commit
          │
          └─ post-publish Wiki link lint
```

相同源码与相同工具版本应产生可比较的事实层；LLM 叙述可能有非确定性。proposal 让正文、metadata 与 source refs 可审核，但当前 Web UI 只有全文预览，不提供 base-vs-proposal diff；需要差异审查时导出内容比较，或在发布后查看 Git audit commit。

## 写入时实体解析

查询时才猜“Client”指哪个类会不断重复歧义。LCF 当前在发布前绑定 library、version、page 与 source ref；更强的跨版本 symbol identity 是演进项：

- `context7_id`：例如 `/local/acme-widget`
- `version_id`：例如 `v1.4.0+git.3ac10e1`
- `symbol id`：当前为 path/line/name；目标可升级为语言、限定名和签名摘要
- `page id`：数据库 page ID + library/version/path
- `source_ref`：source_sha + path + line range

页面正文写易读名称，sidecar 保存这些引用。当前图谱和 MCP 使用 ID/引用；增量影响分析尚未实现。

## 检索不再承担什么

QMD 很强，但它不负责：

- 判断哪个版本是“最新稳定版”；
- 合并冲突的 API 叙述；
- 执行或验证代码示例（当前尚未实现 example runner）；
- 把同名符号解析成同一实体；
- 决定模型提案是否可以发布。

这些是 ingest/publish 的职责。QMD 负责从**已发布知识**中找到最合适的页面和片段。

## `index.md` 与 `log.md`

当前每个已发布版本会有：

- `index.md`：按 kind 组织的页面导航。
- `log.md`：逐页发布时刻、source sha 与 proposal ID。

生产演进可在 sidecar/log 中再加入生成器、prompt/schema、lint 摘要与审批主体。

它们让代理先建立全局地图，再按需读取页面；也让维护者快速判断一次更新发生了什么。

## 从“一次性生成”升级为“持续维护”

生产演进推荐发布策略（当前参考实现每次 ingest 全量生成提案）：

- 新库首次 ingest：全量生成，必须人工审核。
- 同一 minor/patch 更新：只更新受影响页，默认人工审核。
- 仅注释/文档变化且 lint 全通过：可选自动发布。
- major 版本或导出面显著变化：创建新版本树，不覆盖旧版。
- 生成器/schema 升级：记录 toolchain version；必要时全量重建为新提案。

## 仍保留原始 RAG 的地方

当 Wiki 没有覆盖内部实现细节时，演进版本可以查询事实 collection 或源码，并标注：

- `knowledge_tier=wiki`：已发布说明。
- `knowledge_tier=fact`：确定性抽取证据。
- `knowledge_tier=source`：原始片段，尚未形成文档。

当前 `query-docs` 只查询已发布 Wiki，没有自动下钻或 `knowledge_tier` 字段。未来增加下钻时，应仅在用户明确要求或置信度不足时启用，避免把“代码恰好这么写”误表述成公开 API 契约。

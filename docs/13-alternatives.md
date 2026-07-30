# docs-mcp-server、Context7 与 QMD 的取舍

## 结论

LCF 不把 [`arabold/docs-mcp-server`](https://github.com/arabold/docs-mcp-server) 当作核心数据库，而把它视为一个可选的外部文档采集/检索参考；核心改成：

```text
repository snapshot
  → deterministic facts
  → typed, reviewed, Git-backed Wiki
  → QMD navigation
  → Context7-compatible MCP
```

原因不是 docs-mcp-server “不好”，而是目标发生了变化：用户需要的不是只建立代码/网页索引，而是持续产出可审阅的 API 使用文档，并保留版本、证据和发布历史。

## 能力对照

| 维度 | docs-mcp-server 型方案 | Context7 云端体验 | LCF |
|---|---|---|---|
| 获取已有 docs | 强 | 强 | 可 ingest README/docs/examples |
| 原始代码检索 | 可索引后查询 | 服务内部能力 | facts + 可选 QMD |
| 持久 API Wiki | 不是主要抽象 | 用户看到整理后的 docs | 是核心制品 |
| 确定性符号/签名 | 取决于输入文档 | 不透明 | ctags + AST/regex fallback |
| 来源行号验证 | 通常是 chunk 来源 | 不透明 | publish 前验证 |
| proposal/review | 非主要流程 | 云端维护 | 显式 pending/publish/reject |
| Git 历史 | 非核心 | 不可见 | 每库 Wiki Git |
| 版本隔离 | collection/source 配置 | library/version | 物化 version + source SHA |
| 完全本地 | 可 | 否 | 是 |
| MCP 调用习惯 | 自有 tools | resolve/query | 兼容 resolve/query 名称 |

“Context7 完全平替”应理解为常用使用体验与本地知识质量的替代，而不是复制其未公开的内部实现或服务协议。

## 为什么 QMD 放在发布层

[`tobi/qmd`](https://github.com/tobi/qmd) 把 BM25、vector、query expansion 与 reranker 放在本机，并提供 collection/context。对英文 API Wiki：

- BM25 擅长精确符号、参数和错误码。
- vector 擅长“我想完成什么”的自然语言问题。
- reranker 在候选页面之间做二次排序。
- AST-aware chunk 可用于代码，但 LCF 默认优先索引 Wiki，避免源码块压过使用说明。

QMD 2.5.3 要求 Node 22+。默认 GGUF 组合适合 M4 Pro 24 GB。日常通过 Web 选择全局
embedding profile 并提交重建；profile ready 前查询自动使用 lexical fallback。命令行
`reindex.sh` 仅作为高级诊断入口。

## docs-mcp-server 仍适合什么

- 已有网页/厂商文档是主要事实源。
- 只需要快速 MCP 检索，不需要生成/审核 Wiki。
- 希望复用它的 crawler、source 管理或现有 collection。

未来可以写 importer，把其导出的 Markdown/页面清单作为 LCF snapshot 的 `external-docs` evidence；但 importer 输出仍应经过版本绑定、proposal 与 publish，不应绕过 Wiki。

## Context7 兼容边界

LCF MCP 当前提供：

- `resolve-library-id(libraryName, query?)`
- `query-docs(libraryId, query)`

差异：

- ID 为本地 `/local/<slug>`。
- `query-docs` 当前使用 default version，没有独立 version 参数。
- 内容来自本机已发布 Wiki，附 source SHA/行号。
- 没有云端目录、评分或托管权限系统。

客户端 prompt 可以沿用“先 resolve，再 query”的两步模式。对非默认版本、review、ingest 和 graph，使用 LCF HTTP API/Web。

## 迁移路径

从单纯索引系统迁移：

1. 保留原系统，只导出最常用 docs/query 作为基线。
2. 在 LCF 用 `mock` ingest 建立 facts 与骨架。
3. 用 Ollama 生成 proposal，人工审核第一版。
4. 用真实问题建立评测集，对比 top-5 与答案引用。
5. 把 MCP 客户端切到 `/local/...`。
6. 原系统只作为网页 importer 或回退，验证一段时间后再下线。

这样能区分“索引迁移问题”和“生成文档质量问题”，避免一次性替换后无法定位回归。

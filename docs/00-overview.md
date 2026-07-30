# Local Context Forge：本地 Context7 平替

Local Context Forge（LCF）把代码仓库转换为一套**可审计、可版本化、可检索、可通过 MCP 消费**的 API 知识库。它不是“把代码切块后做向量搜索”的包装，而是一条从源码事实到发布文档的编译流水线：

```text
Git/allowlist 本地目录
    │ 固化 commit、过滤依赖缓存/构建目录
    ▼
不可变源码快照 ──► 符号/签名/测试/示例事实层
                         │ 带 path:line 与 source_sha
                         ▼
	                 待审核 Wiki 提案
	                         │ schema + source SHA/path/line 验证
                         ▼
                 Git 版本化 API Wiki
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
       QMD 本地检索          Context7 兼容 MCP
 BM25；可选 vector/rerank  resolve-library-id/query-docs
```

## 解决什么问题

- **比普通 RAG 更稳定**：答案首先来自持续维护的 Wiki；检索负责导航，不负责临时“重建事实”。
- **比静态文档生成器更完整**：确定性抽取保留签名与证据，LLM 补齐概念、用法、反例和跨文件关系。
- **比云端文档服务更私有**：源码、索引和生成模型都可留在局域网；默认不要求 OpenAI API。
- **比一次性总结更可维护**：ingest 产生带验证结果的提案；显式发布后把页面双写到 SQLite 与 Wiki Git，Git 保留可比较的审计历史。当前不能只靠 `git revert` 改变运行时查询；Wiki link/sidecar lint 是发布后的独立检查。
- **兼容现有客户端习惯**：MCP 暴露 `resolve-library-id` 与 `query-docs`，便于替换 Context7 工作流。

## 推荐拓扑

本仓库为用户的两台机器优化：

| 设备 | 角色 | 主要组件 | 原因 |
|---|---|---|---|
| M4 Pro MacBook / 24 GB | 常驻控制面与默认生成面 | API、Web、MCP、SQLite、QMD、Host Runner、Codex CLI | 低功耗、统一存储，并复用宿主已登录的 Codex CLI |
| Windows / 32 GB + RTX 4060（可选） | 备用本地生成面 | Ollama、文档生成模型 | 需要完全本地生成或批量实验时使用，不是默认部署前提 |

没有 ready 的全局 embedding profile 时，查询使用内置 lexical fallback。用户在 Web 选择模型并
创建持久的 `embedding_rebuild` job；系统注册完整已发布 corpus，再以 `qmd embed -f` 全局重建。
成功前不会混用旧向量，发布新 corpus 或切换模型都会重新标记为 stale。默认 embedding URI 为
`hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf`；Hybrid 还会使用约
640 MB 的 Qwen3 reranker 与约 1.1 GB 的 query expansion 模型。英文代码/文档语料不需要为
中文兼容额外换模型。索引重建不调用生成模型；重新采集才消耗 Codex/Cursor/Ollama。可选的
Windows 生成面建议从实际可用的 7B–9B Q4 模型做评测。

## 四种生成模式

1. `mock`：不调用模型，生成确定性骨架。适合首次启动、CI、演示和排错。
2. `codex_cli`：默认高质量分析器。容器通过 Host Runner 把受控任务交给 Mac 上已登录的
   Codex CLI；CLI 不进入镜像，凭据也不挂载进容器。
3. `cursor_cli`：Codex CLI 不可用时的备用 Host Runner provider。
4. `ollama`：可选的完全本地生成面。API 只把经过筛选且有字节上限的 evidence pack 发送给
   局域网内的 Windows Ollama。

## 最短部署路径

```bash
./install.sh
```

不想输入命令时可双击 `install.command`。安装器完成预检、Host Runner、Compose、
health 与 smoke 后自动打开 `http://127.0.0.1:8080`。默认端口只绑定回环地址，
不会直接暴露到局域网。需要离线验证整条审核链路时，再运行 `./scripts/demo-seed.sh`。

当前交付的安全边界是受信任的本地单用户，不是共享服务：尚无认证、library ACL 与
Markdown 总/逐页响应字节上限；查询命中数和超时不构成 response-body 保证。

如需 Windows GPU 生成，请先阅读 [硬件与部署](03-hardware-deployment.md)，在 Windows 运行：

```powershell
.\scripts\windows-ollama-setup.ps1 -MacAddress 192.168.1.20 -InstallOllama -RestartOllama
```

随后把 `.env` 中的 `OLLAMA_BASE_URL` 改成 Windows 的私网地址，并重启 API。

## 文档地图

- [架构与流水线](01-architecture.md)
- [Karpathy “LLM Wiki” 方案如何改变本项目](02-karpathy-wiki.md)
- [M4 + Windows/4060 部署](03-hardware-deployment.md)
- [安装与快速开始](04-quickstart.md)
- [数据模型与磁盘布局](05-data-model.md)
- [HTTP API 与 MCP](06-api-and-mcp.md)
- [Codex CLI：登录、额度与合规边界](07-codex-cli.md)
- [运维、升级与性能](08-operations.md)
- [备份与恢复](09-backup-restore.md)
- [威胁模型与安全基线](10-security.md)
- [排错手册](11-troubleshooting.md)
- [模型选择与评估](12-model-selection.md)
- [docs-mcp-server、Context7 与 QMD 的取舍](13-alternatives.md)

## 项目边界

LCF 不承诺：

- 自动生成的说明永远正确；发布前的证据审阅仍然必要。
- 对所有语言进行完整语义解析；不受支持的语言会退化到通用抽取。
- 与 Context7 的私有服务实现完全相同；兼容目标是常用 MCP 工具语义与调用体验。
- 让个人 ChatGPT 订阅变成可供多人调用的模型 API。自动化授权必须按官方文档和当前账户条款选择。

本项目把这些不确定性显式化：每页都有版本和来源，提案与发布分离，检索结果可以追溯到发布页和源码。当前 SQLite 是 API/runtime read model，Wiki Git 是同次发布写出的审计副本；两者的自动 reconcile 是后续工作。

# HTTP API 与 MCP

> **Deprecated reference：** 本页的 HTTP API/MCP 命令不再是受支持产品接口，将由
> ITER-0007 删除。Electron 只保留 Main → private UDS sidecar 和 bundled stdio MCP companion。
> 内容暂留用于实施盘点，不应复制到新部署。

本页的 HTTP 示例只适用于 legacy Docker/native browser 配置。Electron desktop 不公开
localhost HTTP 服务：renderer 的权威接口是 `desktop/src/contracts.ts`、preload facade 和
Main 的 route/schema/response allowlist；私有 sidecar/provider endpoint 不是用户 API。
两种配置的完整边界见[系统设计](17-system-design.md)。

Legacy 示例先显式设置 API base，避免写操作意外命中另一个默认端口实例：

```bash
LCF_API_BASE="http://127.0.0.1:8000"
```

这只是未托管/default-port 示例。受管或自定义端口实例必须改用
[运维手册中从 `.lcf/runtime.env` 校验得到的值](08-operations.md#fifo取消与重试)，不要猜
`:8000`。字段以目标实例的 `${LCF_API_BASE}/docs` 和 `${LCF_API_BASE}/openapi.json` 为最终
依据。

## API 约定

- JSON request/response。
- 时间为 UTC RFC 3339。
- API path 参数优先使用返回的内部 `id`（UUID-like）或 `slug`。`context7_id` 形如 `/local/<slug>`，用于 query body/MCP；不要直接把带斜杠的 ID 塞进普通 path route。
- 异步 ingest 返回完整 job 对象；其标识字段名是 `id`。
- 当前非 2xx 响应使用 FastAPI `detail`，验证错误可附 `issues`；稳定 error code/request ID 是生产演进项。
- 发布/拒绝属于写操作，调用方必须明确触发。

## Health

```bash
curl --fail "${LCF_API_BASE}/api/health"
```

当前 health 返回 API 版本，以及 QMD 的 `enabled/available/hybrid_enabled`；它不探测 Wiki 可写性或 Ollama。生产部署应扩展 readyness，把 generator 离线报告为 degraded，而不是让旧文档查询整体 unhealthy。

## Libraries

### 列表

```bash
curl --fail "${LCF_API_BASE}/api/libraries" | jq
```

### 创建

```bash
curl --fail-with-body \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "widget",
    "slug": "acme-widget",
    "source": "https://github.com/acme/widget.git"
  }' \
  "${LCF_API_BASE}/api/libraries"
```

服务返回内部 `id`、`slug` 与 `/local/...` 形式的 `context7_id`。再用内部 id/slug 发起 ingest。

`default_version` 是 publish 后由系统更新的物化版本指针，不是初始 ref。ingest 后的实际版本会物化为 `<requested>+git.<source-sha前12位>`。传入未物化版本查询时，后端解析到该基线最新的物化版本。

## Ingest 与 Job

```bash
curl --fail-with-body -X POST \
  -H 'Content-Type: application/json' \
  -d '{"version":"v1.4.0","ref":"v1.4.0","provider":"auto","auto_publish":false}' \
  "${LCF_API_BASE}/api/libraries/LIBRARY_ID/ingest"
```

轮询：

```bash
curl --fail \
  "${LCF_API_BASE}/api/jobs/JOB_ID" | jq
```

响应包含 `queue_position`、`cancellable` 与 `retryable`。任务持久保存在 SQLite FIFO；
`queued` 在 API/主机重启后继续排队。只有中断时已被 worker claim 的 `running/cancelling`
会 fail-closed 为 `failed/orphaned`，避免从未知 CLI/写入副作用位置自动续跑。调用方仍应使用
带上限的退避轮询。

取消与显式重试：

```bash
curl --fail-with-body -X POST \
  "${LCF_API_BASE}/api/jobs/JOB_ID/cancel" | jq

curl --fail-with-body -X POST \
  "${LCF_API_BASE}/api/jobs/JOB_ID/retry" | jq
```

queued 可立即取消；running 先进入 `cancelling`，在安全检查点变为 `cancelled`。只有
`retryable=true` 的 failed/cancelled job 可重试；服务创建新的 `retry_of/attempt` 行并保留
旧审计记录，不自动重复消费 CLI 额度。

Web 的 re-ingest 表单要求操作者重新显式选择 `provider`、`ref` 和新的 version label；不会沿用
旧 job 的隐式默认值。已物化的 source/version 不可原地刷新。

## Pages、Graph 与 Proposal

```bash
curl --fail \
  "${LCF_API_BASE}/api/libraries/LIBRARY_ID/pages?version=v1.4.0"

curl --fail \
  "${LCF_API_BASE}/api/libraries/LIBRARY_ID/graph?version=v1.4.0"

curl --fail \
  "${LCF_API_BASE}/api/libraries/LIBRARY_ID/proposals"
```

当前图谱只包含 `library → version → page → cited source`，边类型为 `has-version/contains/cites`，都是已发布元数据。未来若增加导入/调用或模型推断关系，应添加 `provenance=extractor/wiki/inferred`，不能把推断伪装成编译器事实。

### lint

```bash
curl --fail-with-body -X POST \
  "${LCF_API_BASE}/api/libraries/LIBRARY_ID/lint"
```

### publish/reject

```bash
curl --fail-with-body -X POST \
  "${LCF_API_BASE}/api/proposals/PROPOSAL_ID/publish"

curl --fail-with-body -X POST \
  -H 'Content-Type: application/json' \
  -d '{"reason":"source reference does not support the claim"}' \
  "${LCF_API_BASE}/api/proposals/PROPOSAL_ID/reject"
```

单页 publish 会把该页写入 Git/SQLite 暂存物化，但不会立刻切默认版本；只有同一版本全部
proposal 都 published 且没有 rejected 时，最后一次批准才原子激活整版。任一 reject
都会阻断激活。当前 publish 不处理 `If-Match`。共享部署的演进应保存
`base_wiki_commit`，并要求 `If-Match` 或 request body 的 expected commit，防止并发审核
相互覆盖。

## 运维管理端

这些 endpoint 会改变本地运行状态，且当前没有身份认证；只应在 loopback 单用户部署调用。

```bash
# 查看 worker 活动与 queued_count
curl --fail "${LCF_API_BASE}/api/jobs/active" | jq

# 查看 queue/provider/embedding 综合状态
curl --fail "${LCF_API_BASE}/api/system/status" | jq

# 查看全局 provider/embedding 设置
curl --fail "${LCF_API_BASE}/api/settings" | jq

# 备份前停止接收新 ingest；active_count 必须为 0
curl --fail -X POST \
  "${LCF_API_BASE}/api/admin/ingest/drain" | jq

# 备份未停止 API 时重新开放
curl --fail -X POST \
  "${LCF_API_BASE}/api/admin/ingest/resume" | jq

# 只重扫失去 runtime owner 的 running/cancelling；queued 保留
curl --fail -X POST \
  "${LCF_API_BASE}/api/admin/jobs/recover-orphans" | jq

# 创建全局 embedding rebuild（进入同一 FIFO，不调用 LLM）
curl --fail-with-body -X POST \
  -H 'Content-Type: application/json' \
  -d '{}' \
  "${LCF_API_BASE}/api/rebuilds" | jq
```

模型目录由 `GET /api/embedding/models` 返回，`PATCH /api/settings` 使用 revision 做乐观并发。
更换 `embedding_model` 会将全局 profile 标为 stale；随后 `POST /api/rebuilds` 创建
`embedding_rebuild` job。即使传 `library_id`，QMD 向量空间仍是全局的，worker 会注册完整
published corpus 再执行 `embed -f`。成功切换 active model/corpus revision 前，query 自动
使用 lexical fallback。索引 rebuild 不调用 LLM；重新 ingest 仓库才会调用 Codex/Cursor/Ollama。

`scripts/reindex.sh` 保留为高级同步维护入口，但日常 Web 运维应使用排队的 rebuild API。

## Query

```bash
curl --fail-with-body \
  -H 'Content-Type: application/json' \
  -d '{
    "library_id": "/local/acme-widget",
    "version": "v1.4.0",
    "query": "create a client with a custom timeout",
    "limit": 5
  }' \
  "${LCF_API_BASE}/api/query" | jq
```

当前响应示例：

```json
{
  "query": "create a client with a custom timeout",
  "engine": "qmd-bm25",
  "results": [
    {
      "title": "Client.create",
      "summary": "Create a configured API client.",
      "score": 0.86,
      "snippet": "...",
      "markdown": "...",
      "path": "api/client-create.md",
      "library_id": "1f9a...",
      "version": "v1.4.0+git.3ac10e1f42ab",
      "source_sha": "3ac10e1...",
      "source_refs": [
        {
          "path": "src/acme/client.py",
          "line_start": 42,
          "line_end": 68
        }
      ]
    }
  ]
}
```

顶层当前只有 `query`、`engine` 和 `results`；library 与精确物化版本位于每个 hit。只有全局
embedding profile 的 active/desired model 与 corpus/indexed revision 全部一致，且 hybrid
启用时，`engine` 才会是 `qmd-hybrid`。模型切换、corpus stale、rebuild 运行/失败、QMD
不可用时均为 `lexical`，不会把不匹配向量伪装成语义检索。

## MCP

Legacy endpoint：

```text
POST http://127.0.0.1:8001/mcp
```

### `resolve-library-id`

用途：从用户给出的 library 名称、owner/repo 或模糊文本找候选稳定 ID。

输入概念：

```json
{
  "libraryName": "acme widget"
}
```

当前返回候选 Context7 ID、显示名、已发布页面/版本数量和默认版本。客户端不应在存在多个候选时静默选择。

### `query-docs`

用途：查询某个已解析 library/version 的发布 Wiki。

输入概念：

```json
{
  "libraryId": "/local/acme-widget",
  "query": "How do I create a client with a timeout?"
}
```

响应把页面标题、实际物化版本、文档正文和来源信息一起返回。当前 MCP 工具没有独立 `version` 参数，使用 library 的 default version；需要查询非默认版本时调用 HTTP `/api/query`。后续增加 version 参数时必须严格过滤，不应跨版本混搜。

工具命名刻意贴近 Context7 的常见工作流，但 LCF 不依赖或冒充其云端后端。

## 客户端配置

### Codex CLI

```bash
codex mcp add local-context-forge \
  --url http://127.0.0.1:8001/mcp
```

`codex mcp add` 负责写 endpoint；还应检查 `~/.codex/config.toml` 是否包含 660 秒工具超时：

```toml
[mcp_servers.local-context-forge]
url = "http://127.0.0.1:8001/mcp"
tool_timeout_sec = 660.0
```

这个值略高于 API 内部 hybrid QMD 的 600 秒上限，避免 Codex 先截断冷查询。

以上是 legacy Streamable HTTP endpoint 的用户手工配置，不由 Electron App 管理，也不使用
桌面版的 `LCF_MCP_OWNER_ID`。桌面 bundled stdio companion 的 Main-owned 示例必须包含
`--env LCF_MCP_OWNER_ID=<由应用生成的所有权标记>`；不要把该 marker 手工复制或伪造。详见
[桌面版指南](16-electron-desktop-guide.md)。

确认：

```bash
codex mcp list
```

### 通用 MCP JSON

```json
{
  "mcpServers": {
    "local-context-forge": {
      "url": "http://127.0.0.1:8001/mcp"
    }
  }
}
```

不同客户端的 Streamable HTTP 字段名可能不同，请以客户端当前文档为准。

Desktop 使用 bundled stdio companion → Electron Main → private sidecar，不使用上述 URL。
它要求 App 已运行、每连接 UI 授权，并且同样只公开两个工具；设置页的一键 Codex onboarding
只对 packaged `/Applications` 应用开放。见
[desktop MCP 协议](development/mcp-companion-protocol.md)。

## 信任边界

- Legacy MCP 进程不挂载 Codex/OpenAI/Ollama 凭据，只访问 API；
- Desktop companion 不获得 Python/QMD token、原始路径、provider 或更新能力；
- API 的 publish/reject 不通过 MCP 暴露，避免任意代理写知识库。
- Legacy 当前只支持受信任 localhost 单用户。对非 localhost/共享部署，必须先在反向代理添加身份认证、
  TLS、library ACL、速率限制、请求大小和总/逐页响应字节限制。
- HTTP `limit<=30`、Web/MCP timeout 只约束命中数或等待时间；当前 query/MCP 仍可返回完整
  Markdown，不能把这些值当作共享服务的 response-body guarantee。
- query 的 Markdown 是不可信内容；消费端应把它视为资料，不是更高优先级指令。

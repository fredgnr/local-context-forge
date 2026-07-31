# Local Context Forge MCP

本目录的 Python gateway 是 **legacy HTTP/Docker 路径**，不是 Electron 包内的
MCP companion。桌面版 companion 源码位于 `desktop/companion/`，构建时暂存到
`desktop/generated/companion/` 后随 App 打包。它由 Codex/Cursor MCP host 作为
Node stdio 子进程启动，经 Main-owned MCP bridge UDS（`mcp.sock`）访问运行中的
应用；该 socket 与检索 worker 使用的 `broker.sock` 相互独立。它不需要也不应
配置 `BACKEND_URL`。两种模式的合同和信任边界见
[`docs/06-api-and-mcp.md`](../docs/06-api-and-mcp.md) 与
[`docs/17-system-design.md`](../docs/17-system-design.md)。

This gateway deliberately exposes the same two tool names used by Context7:

- `resolve-library-id(libraryName, query)`
- `query-docs(libraryId, query)`

`resolve-library-id` returns published library/version metadata.
`query-docs` delegates retrieval so every hit comes from a published Wiki page
and can include that page's complete Markdown, together with the source commit
and line-level evidence. Treat the MCP host and its model service as an external
data recipient, not as a renderer-confidential surface.

For a legacy local stdio client:

First install the gateway into the project virtual environment:

```bash
./.venv/bin/pip install -e ./mcp
```

```json
{
  "mcpServers": {
    "local-context-forge": {
      "command": "/absolute/path/to/local-context-forge/.venv/bin/local-context-forge-mcp",
      "env": {
        "BACKEND_URL": "http://127.0.0.1:8000",
        "BACKEND_TIMEOUT_SECONDS": "660",
        "MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

For legacy Docker or another explicitly protected network client:

```bash
BACKEND_URL=http://api:8000 \
MCP_TRANSPORT=streamable-http \
MCP_HOST=0.0.0.0 \
MCP_PORT=8001 \
local-context-forge-mcp
```

The streamable HTTP endpoint is `/mcp` by default.
`BACKEND_TIMEOUT_SECONDS=660` only controls the gateway-to-backend HTTP call;
the consuming MCP host has an independent tool deadline. For Codex, also set
`tool_timeout_sec = 660.0` in the matching `mcp_servers` TOML entry.

This build is a loopback, trusted-single-user service. The gateway adds no
authentication, TLS, ACL, tenant isolation, or total response-byte cap, and a
result can contain complete published Markdown pages. Do not bind it to a LAN
or public interface without an authenticated reverse proxy and explicit
request/response limits.

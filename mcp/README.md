# Local Context Forge MCP

This gateway deliberately exposes the same two tool names used by Context7:

- `resolve-library-id(libraryName, query)`
- `query-docs(libraryId, query)`

It delegates retrieval to the backend so every result comes from a published
Wiki page and includes the source commit plus line-level evidence.

For a local stdio client:

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

For Docker or another network client:

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

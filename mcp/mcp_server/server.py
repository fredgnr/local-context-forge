from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from .client import (
    BackendClient,
    BackendError,
    format_libraries,
    format_query_results,
)

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8001"))
MCP_PATH = os.getenv("MCP_PATH", "/mcp")

client = BackendClient(
    BACKEND_URL,
    timeout_seconds=int(os.getenv("BACKEND_TIMEOUT_SECONDS", "660")),
)
mcp = FastMCP(
    "Local Context Forge",
    instructions=(
        "Resolve a local library ID first, then query its evidence-backed, "
        "versioned API Wiki. Results contain exact source provenance."
    ),
    host=MCP_HOST,
    port=MCP_PORT,
    streamable_http_path=MCP_PATH,
    json_response=True,
    stateless_http=True,
)


@mcp.custom_route("/health", methods=["GET"], name="health")
async def health(_request: Request) -> JSONResponse:
    """Container health check that does not invoke an MCP tool."""

    return JSONResponse(
        {
            "status": "ok",
            "service": "local-context-forge-mcp",
        }
    )


@mcp.tool(
    name="resolve-library-id",
    title="Resolve local library ID",
    description=(
        "Resolve a package or repository name to a Local Context Forge "
        "Context7-compatible library ID. Call this before query-docs unless "
        "the user already supplied an exact /local/... ID."
    ),
)
def resolve_library_id(libraryName: str, query: str = "") -> str:
    """Find published local libraries relevant to a documentation question."""

    try:
        libraries = client.libraries(libraryName)
        return format_libraries(libraries, libraryName, query)
    except BackendError as error:
        return f"Local Context Forge error: {error}"


@mcp.tool(
    name="query-docs",
    title="Query local API documentation",
    description=(
        "Query the persistent, evidence-backed API Wiki for a resolved local "
        "library ID. Use specific API names and describe what you are trying "
        "to build for the best result."
    ),
)
def query_docs(libraryId: str, query: str) -> str:
    """Retrieve API guides and examples with source-line provenance."""

    try:
        result = client.query_docs(libraryId, query)
        return format_query_results(result)
    except BackendError as error:
        return f"Local Context Forge error: {error}"


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    if transport not in {"stdio", "sse", "streamable-http"}:
        raise SystemExit("MCP_TRANSPORT must be one of: stdio, sse, streamable-http")
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()

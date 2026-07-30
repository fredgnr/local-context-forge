from __future__ import annotations

from mcp_server.client import format_libraries, format_query_results
from mcp_server.server import mcp
from starlette.testclient import TestClient


def test_context7_library_format() -> None:
    output = format_libraries(
        [
            {
                "name": "Widgets",
                "context7_id": "/local/widgets",
                "description": "Widget API",
                "page_count": 4,
                "version_count": 1,
                "default_version": "1.0.0",
            }
        ],
        "widgets",
        "render a widget",
    )
    assert "Context7-compatible library ID: `/local/widgets`" in output
    assert "render a widget" in output


def test_context7_query_format_includes_evidence() -> None:
    output = format_query_results(
        {
            "engine": "lexical",
            "results": [
                {
                    "title": "widgets.py",
                    "path": "api/widgets.md",
                    "version": "1.0.0",
                    "source_sha": "1234567890abcdef",
                    "summary": "Public Widget API",
                    "markdown": "## `build_widget`\n\nBuild a widget.",
                    "source_refs": [
                        {
                            "path": "widgets.py",
                            "line_start": 18,
                            "line_end": 20,
                        }
                    ],
                }
            ],
        }
    )
    assert "build_widget" in output
    assert "widgets.py:18-20" in output
    assert "1234567890ab" in output


def test_mcp_http_health_route() -> None:
    with TestClient(mcp.streamable_http_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

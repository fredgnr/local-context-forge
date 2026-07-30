from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class BackendError(RuntimeError):
    pass


@dataclass(slots=True)
class BackendClient:
    base_url: str
    timeout_seconds: int = 660

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read().decode("utf-8")).get(
                    "detail", error.reason
                )
            except (json.JSONDecodeError, AttributeError):
                detail = error.reason
            raise BackendError(f"Backend returned {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise BackendError(
                f"Cannot reach Local Context Forge backend: {error}"
            ) from error
        except json.JSONDecodeError as error:
            raise BackendError("Backend returned invalid JSON") from error

    def libraries(self, search: str) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode({"search": search})
        result = self._request("GET", f"/api/libraries?{query}")
        if not isinstance(result, list):
            raise BackendError("Unexpected library response")
        return result

    def query_docs(self, library_id: str, query: str, limit: int = 8) -> dict[str, Any]:
        result = self._request(
            "POST",
            "/api/query",
            {
                "library_id": library_id,
                "query": query,
                "limit": limit,
            },
        )
        if not isinstance(result, dict):
            raise BackendError("Unexpected query response")
        return result


def format_libraries(
    libraries: list[dict[str, Any]], library_name: str, query: str
) -> str:
    if not libraries:
        return (
            f'No local library matched "{library_name}". Add and publish the '
            "repository in Local Context Forge, then call this tool again."
        )
    lines = [
        "# Available local libraries",
        "",
        (
            f"Selection context: `{query}`"
            if query
            else "Choose the library whose name and description match the task."
        ),
        "",
    ]
    for library in libraries[:20]:
        lines.extend(
            [
                f"- Title: {library['name']}",
                f"  - Context7-compatible library ID: `{library['context7_id']}`",
                f"  - Description: {library.get('description') or 'No description'}",
                f"  - Published pages: {library.get('page_count', 0)}",
                f"  - Published versions: {library.get('version_count', 0)}",
                (
                    f"  - Default version: `{library['default_version']}`"
                    if library.get("default_version")
                    else "  - Default version: not published yet"
                ),
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def format_query_results(result: dict[str, Any]) -> str:
    hits = result.get("results", [])
    if not hits:
        return (
            "No published local documentation matched this query. Try an exact "
            "API symbol, publish pending Wiki proposals, or run ingest again."
        )
    lines = [
        "# Local documentation results",
        "",
        f"Retrieval engine: `{result.get('engine', 'unknown')}`",
        "",
    ]
    for index, hit in enumerate(hits, 1):
        refs = hit.get("source_refs", [])
        reference_text = ", ".join(
            f"{ref['path']}:{ref['line_start']}-{ref['line_end']}" for ref in refs[:8]
        )
        lines.extend(
            [
                f"## {index}. {hit['title']}",
                "",
                (
                    f"Wiki path: `{hit['path']}` · Version: `{hit['version']}` · "
                    f"Source: `{hit['source_sha'][:12]}`"
                ),
                "",
                hit.get("summary", ""),
                "",
            ]
        )
        markdown = str(hit.get("markdown") or hit.get("snippet") or "").strip()
        if markdown:
            lines.extend([markdown, ""])
        if reference_text:
            lines.extend([f"Evidence: {reference_text}", ""])
    return "\n".join(lines).rstrip()

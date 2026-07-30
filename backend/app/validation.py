from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .source import sensitive_path_reason
from .utils import safe_page_path, safe_relative_path

MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def validate_page(
    page: dict[str, Any],
    *,
    snapshot_repo: Path,
    source_sha: str,
    require_publish_schema: bool = False,
    allowed_source_ranges: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if require_publish_schema:
        if page.get("schema_version") != 1:
            issues.append(
                {
                    "level": "error",
                    "code": "invalid-page-schema",
                    "message": "Published proposals require schema_version 1",
                }
            )
        for field in ("title", "summary", "markdown"):
            if not isinstance(page.get(field), str) or not page[field].strip():
                issues.append(
                    {
                        "level": "error",
                        "code": "invalid-page-schema",
                        "message": f"Published proposal requires non-empty {field}",
                    }
                )
        if page.get("kind") not in {
            "overview",
            "guide",
            "api",
            "example",
            "concept",
        }:
            issues.append(
                {
                    "level": "error",
                    "code": "invalid-page-schema",
                    "message": "Published proposal has an invalid kind",
                }
            )
        if not isinstance(page.get("tags"), list):
            issues.append(
                {
                    "level": "error",
                    "code": "invalid-page-schema",
                    "message": "Published proposal tags must be an array",
                }
            )
    try:
        safe_page_path(page["path"])
    except (KeyError, ValueError) as error:
        issues.append({"level": "error", "code": "unsafe-path", "message": str(error)})
    refs = page.get("source_refs", [])
    if not isinstance(refs, list):
        return [
            {
                "level": "error",
                "code": "invalid-source-refs",
                "message": "source_refs must be an array",
            }
        ]
    if not refs:
        issues.append(
            {
                "level": "error" if require_publish_schema else "warning",
                "code": "missing-source-ref",
                "message": "Page has no source reference",
            }
        )
    allowed_by_path: dict[str, list[tuple[int, int]]] | None = None
    if allowed_source_ranges is not None:
        allowed_by_path = {}
        for allowed in allowed_source_ranges:
            try:
                allowed_path = safe_relative_path(str(allowed["path"]))
                allowed_start = int(allowed["line_start"])
                allowed_end = int(allowed["line_end"])
            except (KeyError, TypeError, ValueError):
                continue
            if allowed_start >= 1 and allowed_end >= allowed_start:
                allowed_by_path.setdefault(allowed_path, []).append(
                    (allowed_start, allowed_end)
                )
    snapshot_root = snapshot_repo.resolve()
    for ref in refs:
        try:
            relative = safe_relative_path(str(ref["path"]))
            line_start = int(ref["line_start"])
            line_end = int(ref["line_end"])
        except (KeyError, TypeError, ValueError) as error:
            issues.append(
                {
                    "level": "error",
                    "code": "invalid-source-ref",
                    "message": f"Invalid source ref: {error}",
                }
            )
            continue
        if sensitive_path_reason(relative):
            issues.append(
                {
                    "level": "error",
                    "code": "sensitive-source-ref",
                    "message": f"Source ref targets a filtered sensitive path: {relative}",
                }
            )
            continue
        if allowed_by_path is not None and not any(
            allowed_start <= line_start and line_end <= allowed_end
            for allowed_start, allowed_end in allowed_by_path.get(relative, [])
        ):
            issues.append(
                {
                    "level": "error",
                    "code": "source-ref-outside-evidence",
                    "message": (
                        "Source ref is outside the exact evidence/symbol ranges "
                        f"visible to the generator: {relative}:{line_start}-{line_end}"
                    ),
                }
            )
            continue
        source_path = snapshot_repo / relative
        cursor = snapshot_repo
        has_symlink_component = False
        for part in PurePosixPath(relative).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                has_symlink_component = True
                break
        try:
            resolved_source = source_path.resolve(strict=True)
        except OSError:
            resolved_source = source_path
        if (
            has_symlink_component
            or not resolved_source.is_relative_to(snapshot_root)
            or not resolved_source.is_file()
        ):
            issues.append(
                {
                    "level": "error",
                    "code": "missing-source-path",
                    "message": (
                        "Source path is missing, outside the snapshot, or traverses "
                        f"a symlink: {relative}"
                    ),
                }
            )
            continue
        try:
            with resolved_source.open(
                "r", encoding="utf-8", errors="replace"
            ) as source_handle:
                line_count = sum(1 for _line in source_handle)
        except OSError:
            line_count = 0
        if line_start < 1 or line_end < line_start or line_end > line_count:
            issues.append(
                {
                    "level": "error",
                    "code": "invalid-source-lines",
                    "message": (
                        f"Invalid line range {line_start}-{line_end} for "
                        f"{relative} ({line_count} lines)"
                    ),
                }
            )
    metadata_sha = page.get("source_sha")
    if metadata_sha and metadata_sha != source_sha:
        issues.append(
            {
                "level": "error",
                "code": "stale-source-sha",
                "message": f"Expected {source_sha}, got {metadata_sha}",
            }
        )
    return issues


def lint_published_wiki(
    version_root: Path,
    pages: list[dict[str, Any]],
    *,
    expected_source_sha: str | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    expected_paths = {page["path"] for page in pages}
    index_path = version_root / "index.json"
    if not index_path.exists():
        issues.append(
            {
                "level": "error",
                "code": "missing-typed-index",
                "message": "Structured index.json is missing",
            }
        )
    else:
        try:
            typed_index = json.loads(index_path.read_text(encoding="utf-8"))
            if typed_index.get("schema_version") != 1 or not isinstance(
                typed_index.get("pages"), list
            ):
                raise ValueError("invalid index schema")
            indexed_paths = {
                item.get("path")
                for item in typed_index["pages"]
                if isinstance(item, dict)
            }
            if indexed_paths != expected_paths:
                issues.append(
                    {
                        "level": "error",
                        "code": "stale-typed-index",
                        "message": "index.json page set differs from published metadata",
                    }
                )
            else:
                indexed_by_path = {
                    item["path"]: item
                    for item in typed_index["pages"]
                    if isinstance(item, dict) and item.get("path")
                }
                for page in pages:
                    expected_index_entry = {
                        "path": page["path"],
                        "title": page["title"],
                        "kind": page["kind"],
                        "summary": page["summary"],
                        "tags": page.get("metadata", {}).get("tags", []),
                        "source_sha": page["source_sha"],
                    }
                    if indexed_by_path.get(page["path"]) != expected_index_entry:
                        issues.append(
                            {
                                "level": "error",
                                "code": "typed-index-drift",
                                "path": page["path"],
                                "message": "index.json differs from runtime metadata",
                            }
                        )
        except (OSError, ValueError, json.JSONDecodeError):
            issues.append(
                {
                    "level": "error",
                    "code": "invalid-typed-index",
                    "message": "Structured index.json is not valid",
                }
            )
    seen: set[str] = set()
    for page in pages:
        path = page["path"]
        if path in seen:
            issues.append(
                {
                    "level": "error",
                    "code": "duplicate-page",
                    "path": path,
                    "message": f"Duplicate page path: {path}",
                }
            )
        seen.add(path)
        markdown_path = version_root / path
        if not markdown_path.exists():
            issues.append(
                {
                    "level": "error",
                    "code": "missing-page-file",
                    "path": path,
                    "message": f"Published page is missing on disk: {path}",
                }
            )
        facts_path = version_root / "facts" / Path(path).with_suffix(".json")
        if not facts_path.exists():
            issues.append(
                {
                    "level": "error",
                    "code": "missing-sidecar",
                    "path": path,
                    "message": f"Typed sidecar is missing: {facts_path.relative_to(version_root)}",
                }
            )
        else:
            try:
                sidecar = json.loads(facts_path.read_text(encoding="utf-8"))
                if (
                    expected_source_sha
                    and sidecar.get("source_sha") != expected_source_sha
                ):
                    issues.append(
                        {
                            "level": "error",
                            "code": "stale-sidecar",
                            "path": path,
                            "message": "Typed sidecar points at a different source SHA",
                        }
                    )
                if sidecar.get("version") != page.get("version"):
                    issues.append(
                        {
                            "level": "error",
                            "code": "stale-sidecar-version",
                            "path": path,
                            "message": "Typed sidecar points at a different version",
                        }
                    )
                expected_sidecar_fields = {
                    "path": page["path"],
                    "title": page["title"],
                    "kind": page["kind"],
                    "summary": page["summary"],
                    "tags": page.get("metadata", {}).get("tags", []),
                    "version": page["version"],
                    "source_sha": page["source_sha"],
                    "source_refs": page.get("metadata", {}).get("source_refs", []),
                }
                if any(
                    sidecar.get(key) != value
                    for key, value in expected_sidecar_fields.items()
                ):
                    issues.append(
                        {
                            "level": "error",
                            "code": "typed-sidecar-drift",
                            "path": path,
                            "message": "Typed sidecar differs from runtime metadata",
                        }
                    )
            except (OSError, json.JSONDecodeError):
                issues.append(
                    {
                        "level": "error",
                        "code": "invalid-sidecar",
                        "path": path,
                        "message": "Typed sidecar is not valid JSON",
                    }
                )

        for target in MARKDOWN_LINK.findall(page.get("markdown", "")):
            target = target.split("#", 1)[0].strip()
            if not target or target.startswith(
                ("http://", "https://", "mailto:", "#", "qmd://")
            ):
                continue
            linked = (PurePosixPath(path).parent / PurePosixPath(target)).as_posix()
            normalized_parts: list[str] = []
            for part in linked.split("/"):
                if part in {"", "."}:
                    continue
                if part == "..":
                    if normalized_parts:
                        normalized_parts.pop()
                    continue
                normalized_parts.append(part)
            normalized = "/".join(normalized_parts)
            if normalized.endswith(".md") and normalized not in expected_paths:
                issues.append(
                    {
                        "level": "warning",
                        "code": "broken-wiki-link",
                        "path": path,
                        "message": f"Wiki link target does not exist: {target}",
                    }
                )

    disk_pages = {
        item.relative_to(version_root).as_posix()
        for item in version_root.rglob("*.md")
        if "facts" not in item.relative_to(version_root).parts
        and item.name not in {"index.md", "log.md"}
    }
    for orphan in sorted(disk_pages - expected_paths):
        issues.append(
            {
                "level": "warning",
                "code": "orphan-page",
                "path": orphan,
                "message": f"Page exists on disk but not in metadata: {orphan}",
            }
        )
    errors = sum(issue["level"] == "error" for issue in issues)
    warnings = sum(issue["level"] == "warning" for issue in issues)
    return {
        "ok": errors == 0,
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
    }

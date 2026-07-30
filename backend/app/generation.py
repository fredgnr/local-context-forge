from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .facts import FactsBundle
from .utils import atomic_write_json, parse_json_object, safe_page_path, slugify

PAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["pages"],
    "properties": {
        "pages": {
            "type": "array",
            "minItems": 1,
            "maxItems": 80,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "path",
                    "title",
                    "kind",
                    "summary",
                    "markdown",
                    "tags",
                    "source_refs",
                ],
                "properties": {
                    "path": {"type": "string"},
                    "title": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["overview", "guide", "api", "example", "concept"],
                    },
                    "summary": {"type": "string"},
                    "markdown": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "source_refs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["path", "line_start", "line_end"],
                            "properties": {
                                "path": {"type": "string"},
                                "line_start": {"type": "integer", "minimum": 1},
                                "line_end": {"type": "integer", "minimum": 1},
                                "symbol": {"type": "string"},
                            },
                        },
                    },
                },
            },
        }
    },
}


@dataclass(slots=True)
class GenerationContext:
    library_name: str
    library_slug: str
    version: str
    source_sha: str
    facts: FactsBundle
    existing_wiki: list[dict[str, Any]]
    runner_id: str = ""
    cancel_check: Callable[[], bool] | None = None


class GenerationError(RuntimeError):
    pass


class GenerationCancelled(GenerationError):
    pass


class Generator(ABC):
    @abstractmethod
    def generate(self, context: GenerationContext) -> list[dict[str, Any]]:
        raise NotImplementedError


def _first_ref(context: GenerationContext) -> list[dict[str, Any]]:
    files = context.facts.evidence.get("files", [])
    first = next(
        (
            item
            for item in files
            if str(item.get("content") or "").splitlines()
        ),
        None,
    )
    if not first:
        return []
    return [{"path": first["path"], "line_start": 1, "line_end": 1}]


class MockGenerator(Generator):
    """Deterministic generator used for tests, demos, and offline bootstrapping."""

    def generate(self, context: GenerationContext) -> list[dict[str, Any]]:
        symbols = context.facts.symbols
        language_counts = context.facts.manifest.get("languages", {})
        primary_languages = [
            language
            for language, _ in sorted(
                language_counts.items(), key=lambda item: (-item[1], item[0])
            )
            if language != "Unknown"
        ][:5]
        refs = _first_ref(context)
        overview = {
            "path": "overview.md",
            "title": f"{context.library_name} overview",
            "kind": "overview",
            "summary": (
                f"Evidence-backed overview for {context.library_name} "
                f"at {context.version}."
            ),
            "tags": ["overview", *[item.lower() for item in primary_languages]],
            "source_refs": refs,
            "markdown": "\n".join(
                [
                    f"# {context.library_name}",
                    "",
                    f"Version: `{context.version}`  ",
                    f"Source commit: `{context.source_sha}`",
                    "",
                    "## What is indexed",
                    "",
                    f"- {context.facts.manifest.get('file_count', 0)} source files",
                    f"- {len(symbols)} public symbols",
                    f"- Languages: {', '.join(primary_languages) or 'not detected'}",
                    "",
                    (
                        "This page was produced from the immutable source snapshot and "
                        "its deterministic fact pack. Review API pages for signatures "
                        "and source-backed usage notes."
                    ),
                ]
            ),
        }

        readme = next(
            (
                item
                for item in context.facts.evidence.get("files", [])
                if Path(item["path"]).name.lower().startswith("readme")
            ),
            None,
        )
        readme_excerpt = ""
        guide_refs = refs
        if readme:
            readme_excerpt = "\n".join(readme["content"].splitlines()[:24])
            readme_lines = readme["content"].splitlines()
            if readme_lines:
                guide_refs = [
                    {
                        "path": readme["path"],
                        "line_start": 1,
                        "line_end": min(24, len(readme_lines)),
                    }
                ]
        guide = {
            "path": "guides/getting-started.md",
            "title": "Getting started",
            "kind": "guide",
            "summary": "Install, initialize, and verify the library from local evidence.",
            "tags": ["guide", "getting-started"],
            "source_refs": guide_refs,
            "markdown": "\n".join(
                [
                    "# Getting started",
                    "",
                    (
                        "Use the repository's own README and examples as the "
                        "authoritative setup source. The excerpt below is preserved as "
                        "evidence rather than invented by the generator."
                    ),
                    "",
                    "## Repository guidance",
                    "",
                    readme_excerpt or "_No README was found in the evidence pack._",
                ]
            ),
        }

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for symbol in symbols:
            if symbol.get("role", "source") != "source":
                continue
            grouped[symbol["path"]].append(symbol)
        api_pages: list[dict[str, Any]] = []
        used_paths: set[str] = set()
        for source_path, source_symbols in list(grouped.items())[:40]:
            stem = slugify(source_path.rsplit(".", 1)[0].replace("/", "-"))
            page_path = f"api/{stem}.md"
            counter = 2
            while page_path in used_paths:
                page_path = f"api/{stem}-{counter}.md"
                counter += 1
            used_paths.add(page_path)
            sections = [
                f"# {source_path}",
                "",
                f"Public API extracted from `{source_path}`.",
                "",
            ]
            source_refs: list[dict[str, Any]] = []
            for symbol in source_symbols[:80]:
                sections.extend(
                    [
                        f"## `{symbol['name']}`",
                        "",
                        "```text",
                        symbol["signature"],
                        "```",
                        "",
                    ]
                )
                if symbol.get("docstring"):
                    sections.extend([symbol["docstring"], ""])
                sections.append(f"Source: `{symbol['path']}:{symbol['line']}`")
                sections.append("")
                source_refs.append(
                    {
                        "path": symbol["path"],
                        "line_start": symbol["line"],
                        # The deterministic symbol fact exposes the declaration,
                        # signature, and bounded docstring, not the full body.
                        "line_end": symbol["line"],
                        "symbol": symbol["name"],
                    }
                )
            api_pages.append(
                {
                    "path": page_path,
                    "title": source_path,
                    "kind": "api",
                    "summary": (
                        f"{len(source_symbols)} extracted public symbols from "
                        f"{source_path}."
                    ),
                    "tags": ["api", Path(source_path).suffix.lstrip(".")],
                    "source_refs": source_refs,
                    "markdown": "\n".join(sections).rstrip(),
                }
            )
        return [overview, guide, *api_pages]


SYSTEM_PROMPT = """\
You edit and correct a persistent, evidence-backed API wiki for a source
repository; do not treat this as a blank-slate RAG answer. existing_wiki is a
bounded baseline from the last published Wiki and may be outdated. Current
manifest, symbols, and evidence_files always override it. Never carry forward a
claim, API, signature, installation command, behavior, or example unless the
current evidence still supports it. Return only JSON matching the supplied
schema. Every substantive claim must be traceable to current source_refs.
Prefer concise API pages, a getting-started guide, and one overview. Paths must
be safe relative Markdown paths. Preserve exact symbol names and signatures. If
evidence is insufficient, say so explicitly or remove the stale statement.
"""


def _bounded_text_items(
    items: list[dict[str, Any]],
    *,
    byte_limit: int,
    text_key: str,
) -> list[dict[str, Any]]:
    remaining = max(0, byte_limit - 2)
    output: list[dict[str, Any]] = []
    for original in items:
        separator_bytes = 1 if output else 0
        available = remaining - separator_bytes
        item = dict(original)
        text_value = str(item.get(text_key) or "")
        item[text_key] = ""
        fixed_size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        if fixed_size >= available:
            break
        low, high = 0, len(text_value)
        while low < high:
            midpoint = (low + high + 1) // 2
            item[text_key] = text_value[:midpoint]
            size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
            if size <= available:
                low = midpoint
            else:
                high = midpoint - 1
        item[text_key] = text_value[:low]
        if "truncated" in item:
            item["truncated"] = bool(item["truncated"]) or low < len(text_value)
        used = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        output.append(item)
        remaining -= used + separator_bytes
        if remaining < 256:
            break
    return output


def _bounded_json_items(
    items: list[dict[str, Any]], *, byte_limit: int
) -> list[dict[str, Any]]:
    remaining = max(0, byte_limit - 2)
    output: list[dict[str, Any]] = []
    for item in items:
        separator_bytes = 1 if output else 0
        encoded_size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        if encoded_size + separator_bytes > remaining:
            break
        output.append(item)
        remaining -= encoded_size + separator_bytes
    return output


def _context_payload(context: GenerationContext, settings: Settings) -> dict[str, Any]:
    manifest_files = [
        {
            "path": str(item.get("path", ""))[:300],
            "language": item.get("language"),
            "role": item.get("role"),
        }
        for item in context.facts.manifest.get("files", [])[
            : settings.max_model_manifest_files
        ]
    ]
    symbols = [
        {
            "name": str(item.get("name", ""))[:300],
            "kind": item.get("kind"),
            "path": str(item.get("path", ""))[:300],
            "line": item.get("line"),
            "end_line": item.get("end_line"),
            "signature": str(item.get("signature", ""))[:300],
            "docstring": str(item.get("docstring", ""))[:300],
            "role": item.get("role"),
        }
        for item in context.facts.symbols[: settings.max_model_symbols]
    ]
    evidence_files = [
        {
            "path": str(item.get("path", ""))[:300],
            "language": item.get("language"),
            "role": item.get("role"),
            "content": item.get("content", ""),
            "truncated": item.get("truncated", False),
        }
        for item in context.facts.evidence.get("files", [])
    ]
    payload = {
        "library": context.library_name,
        "version": context.version,
        "source_sha": context.source_sha,
        "generation_limits": {
            "bounded_single_pass": True,
            "payload_bytes": settings.max_model_payload_bytes,
            "manifest_bytes": settings.max_model_manifest_bytes,
            "symbols_bytes": settings.max_model_symbols_bytes,
            "evidence_bytes": settings.max_model_evidence_bytes,
            "existing_wiki_bytes": settings.max_existing_wiki_bytes,
        },
        "manifest": {
            "file_count": context.facts.manifest.get("file_count"),
            "languages": context.facts.manifest.get("languages"),
            "files": _bounded_json_items(
                manifest_files, byte_limit=settings.max_model_manifest_bytes
            ),
        },
        "symbols": _bounded_json_items(
            symbols, byte_limit=settings.max_model_symbols_bytes
        ),
        "evidence_files": _bounded_text_items(
            evidence_files,
            byte_limit=settings.max_model_evidence_bytes,
            text_key="content",
        ),
        "existing_wiki": _bounded_text_items(
            context.existing_wiki,
            byte_limit=settings.max_existing_wiki_bytes,
            text_key="markdown",
        ),
    }
    # The component budgets leave headroom, but enforce a final hard ceiling in
    # case unusually long metadata or JSON escaping consumes it.
    trim_order = (
        payload["existing_wiki"],
        payload["evidence_files"],
        payload["symbols"],
        payload["manifest"]["files"],
    )
    while (
        len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        > settings.max_model_payload_bytes
    ):
        trimmed = False
        for collection in trim_order:
            if collection:
                collection.pop()
                trimmed = True
                break
        if not trimmed:
            raise GenerationError("Model payload metadata exceeds its hard byte budget")
    return payload


def generation_evidence_ranges(
    context: GenerationContext,
    settings: Settings,
    provider: str,
) -> list[dict[str, Any]]:
    """Return the exact source ranges the selected generator can cite.

    Ollama and Codex are limited to the post-budget outbound payload. The local
    deterministic mock generator receives the in-memory facts bundle directly,
    so its range set comes from the full persistent evidence and symbol facts.
    """

    if provider == "mock":
        evidence_files = context.facts.evidence.get("files", [])
        symbols = context.facts.symbols
    else:
        payload = _context_payload(context, settings)
        evidence_files = payload["evidence_files"]
        symbols = payload["symbols"]

    ranges_by_path: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for item in evidence_files:
        path = str(item.get("path") or "")
        content = str(item.get("content") or "")
        line_count = len(content.splitlines())
        # A byte/character budget may stop in the middle of the final line.
        # Line-level provenance cannot describe a partial line, so only fully
        # visible lines are citeable in that case.
        if (
            item.get("truncated")
            and content
            and not content.endswith(("\n", "\r"))
        ):
            line_count = max(0, line_count - 1)
        if path and line_count:
            ranges_by_path[path].append((1, line_count, "evidence"))
    for item in symbols:
        path = str(item.get("path") or "")
        try:
            line_start = int(item.get("line"))
        except (TypeError, ValueError):
            continue
        if path and line_start >= 1:
            # Symbol payloads contain a derived signature/docstring plus the
            # declaration locator. They do not contain the function/class body,
            # even when end_line records its location in the fact store.
            ranges_by_path[path].append((line_start, line_start, "symbol"))

    merged: list[dict[str, Any]] = []
    for path, ranges in sorted(ranges_by_path.items()):
        current_start: int | None = None
        current_end = 0
        origins: set[str] = set()
        for line_start, line_end, origin in sorted(ranges):
            if current_start is None or line_start > current_end + 1:
                if current_start is not None:
                    merged.append(
                        {
                            "path": path,
                            "line_start": current_start,
                            "line_end": current_end,
                            "origins": sorted(origins),
                        }
                    )
                current_start = line_start
                current_end = line_end
                origins = {origin}
            else:
                current_end = max(current_end, line_end)
                origins.add(origin)
        if current_start is not None:
            merged.append(
                {
                    "path": path,
                    "line_start": current_start,
                    "line_end": current_end,
                    "origins": sorted(origins),
                }
            )
    return merged


_SENSITIVE_ENV_MARKERS = {
    "API_KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "AUTH",
    "COOKIE",
    "SESSION",
    "PROXY",
}
_SENSITIVE_ENV_PREFIXES = {
    "AWS_",
    "AZURE_",
    "GCP_",
    "GOOGLE_",
    "OPENAI_",
    "ANTHROPIC_",
    "GITHUB_",
    "GITLAB_",
    "CI_",
}


def _minimal_codex_environment(settings: Settings) -> dict[str, str]:
    environment: dict[str, str] = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", str(Path.home())),
        "NO_COLOR": "1",
        "TERM": os.environ.get("TERM", "dumb"),
    }
    if os.name == "nt" and os.environ.get("SYSTEMROOT"):
        environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    for name in settings.codex_env_allowlist:
        normalized = name.strip().upper()
        if (
            not re.fullmatch(r"[A-Z_][A-Z0-9_]*", normalized)
            or normalized in {"CI", "CONTINUOUS_INTEGRATION"}
            or any(marker in normalized for marker in _SENSITIVE_ENV_MARKERS)
            or any(normalized.startswith(prefix) for prefix in _SENSITIVE_ENV_PREFIXES)
        ):
            continue
        if normalized in os.environ:
            environment[normalized] = os.environ[normalized]
    return environment


class OllamaGenerator(Generator):
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate(self, context: GenerationContext) -> list[dict[str, Any]]:
        payload = {
            "model": self.settings.ollama_model,
            "stream": False,
            "format": PAGE_SCHEMA,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        _context_payload(context, self.settings), ensure_ascii=False
                    ),
                },
            ],
            "options": {
                "temperature": 0.1,
                "num_ctx": self.settings.ollama_num_ctx,
                "num_predict": self.settings.ollama_num_predict,
            },
        }
        request = urllib.request.Request(
            f"{self.settings.ollama_base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.settings.ollama_timeout_seconds
            ) as response:
                outer = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise GenerationError(f"Ollama request failed: {error}") from error
        content = outer.get("message", {}).get("content", "")
        try:
            result = parse_json_object(content)
        except (ValueError, json.JSONDecodeError) as error:
            raise GenerationError(
                "Ollama returned invalid structured output"
            ) from error
        pages = result.get("pages")
        if not isinstance(pages, list):
            raise GenerationError("Ollama response does not contain pages")
        return pages


class CodexGenerator(Generator):
    """Opt-in adapter for the official Codex CLI.

    The working directory contains only a sanitized evidence bundle, but the
    legacy CLI ``read-only`` sandbox is not a filesystem confidentiality
    boundary. Therefore this adapter requires an external container/VM that
    exposes only that evidence and an explicit isolation acknowledgement.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def generate(self, context: GenerationContext) -> list[dict[str, Any]]:
        if not self.settings.codex_enabled:
            raise GenerationError(
                "Codex provider is disabled. Set LCF_ENABLE_CODEX_PROVIDER=true "
                "only for an explicit, single-user CLI workflow."
            )
        if not self.settings.codex_filesystem_isolated:
            raise GenerationError(
                "Codex provider requires an external filesystem-isolated "
                "container or VM. The CLI read-only sandbox can still read host "
                "files. After isolating the runtime, set "
                "LCF_CODEX_FILESYSTEM_ISOLATED=true."
            )
        with tempfile.TemporaryDirectory(prefix="lcf-codex-evidence-") as temp:
            workdir = Path(temp)
            evidence_path = workdir / "evidence.json"
            schema_path = workdir / "schema.json"
            output_path = workdir / "result.json"
            evidence_path.write_text(
                json.dumps(
                    _context_payload(context, self.settings),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            schema_path.write_text(
                json.dumps(PAGE_SCHEMA, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            prompt = (
                SYSTEM_PROMPT
                + "\nRead ./evidence.json, then produce the complete wiki proposal."
            )
            command = [
                self.settings.codex_bin,
                "exec",
                "--ephemeral",
            ]
            if self.settings.codex_strict_isolation:
                command.extend(["--ignore-user-config", "--ignore-rules"])
            command.extend(
                [
                    "--skip-git-repo-check",
                    "--sandbox",
                    "read-only",
                    "--output-schema",
                    str(schema_path),
                    "--output-last-message",
                    str(output_path),
                ]
            )
            if self.settings.codex_model:
                command.extend(["--model", self.settings.codex_model])
            command.append("-")
            environment = _minimal_codex_environment(self.settings)
            try:
                subprocess.run(
                    command,
                    cwd=workdir,
                    input=prompt.encode("utf-8"),
                    capture_output=True,
                    check=True,
                    timeout=1800,
                    env=environment,
                )
                result = parse_json_object(output_path.read_text(encoding="utf-8"))
            except FileNotFoundError as error:
                raise GenerationError(
                    f"Codex CLI was not found: {self.settings.codex_bin}"
                ) from error
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                stderr = getattr(error, "stderr", b"")
                detail = stderr.decode("utf-8", errors="replace")[-2000:]
                raise GenerationError(f"Codex CLI failed: {detail}") from error
            except (OSError, ValueError, json.JSONDecodeError) as error:
                raise GenerationError(
                    "Codex returned invalid structured output"
                ) from error
        pages = result.get("pages")
        if not isinstance(pages, list):
            raise GenerationError("Codex response does not contain pages")
        return pages


def _safe_runner_error(value: object, settings: Settings) -> str:
    detail = str(value or "Host CLI runner failed").replace("\0", "")
    for sensitive_path in {
        str(Path.home()),
        str(settings.data_dir),
        str(settings.resolved_runner_dir),
    }:
        if sensitive_path:
            detail = detail.replace(sensitive_path, "<local-path>")
    detail = re.sub(
        r"(?i)\b(api[_ -]?key|token|authorization|password)"
        r"(\s*[:=]\s*)([^\s,;]+)",
        r"\1\2<redacted>",
        detail,
    )
    detail = re.sub(
        r"\b(?:sk|key)-[A-Za-z0-9_-]{8,}\b",
        "<redacted>",
        detail,
    )
    return detail[-2000:]


class HostCliSpoolGenerator(Generator):
    """Exchange one bounded request with the separately installed host runner.

    The backend never opens Codex/Cursor credential files and never launches a
    cloud CLI.  The host runner owns authentication and implements the narrow
    fallback rule defined by the protocol.
    """

    def __init__(self, settings: Settings, provider: str):
        self.settings = settings
        self.requested_provider = provider
        self.effective_provider: str | None = None
        self.fallback_reason: str | None = None

    def generate(self, context: GenerationContext) -> list[dict[str, Any]]:
        runner_id = context.runner_id.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", runner_id):
            raise GenerationError("Host runner id is invalid")
        request_path = self.settings.runner_inbox_dir / f"{runner_id}.json"
        response_path = self.settings.runner_outbox_dir / f"{runner_id}.json"
        if request_path.is_symlink() or response_path.is_symlink():
            raise GenerationError("Host runner spool path cannot be a symlink")
        if not 30 <= self.settings.runner_timeout_seconds <= 3600:
            raise GenerationError(
                "Host runner timeout must be between 30 and 3600 seconds"
            )
        request = {
            "id": runner_id,
            "task": "wiki_v1",
            "provider": self.requested_provider,
            "timeout_seconds": self.settings.runner_timeout_seconds,
            "evidence": _context_payload(context, self.settings),
            "output_schema": PAGE_SCHEMA,
        }
        if self.settings.codex_model:
            request["model"] = self.settings.codex_model
        # A retry may inherit a terminal response left behind after the
        # backend crashed. In that case, consuming the durable response
        # directly is what prevents a second paid CLI invocation.
        if not response_path.is_file():
            atomic_write_json(request_path, request)
        deadline = time.monotonic() + self.settings.runner_timeout_seconds
        while not response_path.is_file():
            if time.monotonic() >= deadline:
                raise GenerationError("Host CLI runner timed out")
            time.sleep(0.1)
        try:
            if response_path.is_symlink():
                raise GenerationError(
                    "Host CLI runner response cannot be a symlink"
                )
            size = response_path.stat().st_size
            if size > self.settings.runner_max_response_bytes:
                raise GenerationError("Host CLI runner response exceeds size limit")
            response = json.loads(response_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise GenerationError("Host CLI runner returned invalid JSON") from error
        finally:
            try:
                response_path.unlink()
            except OSError:
                pass
        if not isinstance(response, dict):
            raise GenerationError("Host CLI runner response must be an object")
        if set(response) != {
            "id",
            "task",
            "completed_at",
            "requested_provider",
            "effective_provider",
            "fallback_reason",
            "result",
            "error",
        }:
            raise GenerationError("Host CLI runner response shape mismatch")
        if (
            response.get("id") != runner_id
            or response.get("task") != "wiki_v1"
            or response.get("requested_provider") != self.requested_provider
            or not (
                (
                    isinstance(response.get("completed_at"), int)
                    and not isinstance(response.get("completed_at"), bool)
                    and response["completed_at"] >= 0
                )
                or isinstance(response.get("completed_at"), str)
            )
        ):
            raise GenerationError("Host CLI runner response identity mismatch")
        self.effective_provider = str(response.get("effective_provider") or "") or None
        self.fallback_reason = str(response.get("fallback_reason") or "") or None
        if response.get("error"):
            raise GenerationError(
                _safe_runner_error(response.get("error"), self.settings)
            )
        if self.effective_provider not in {"codex_cli", "cursor_cli"}:
            raise GenerationError("Host CLI runner returned an invalid provider")
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("pages"), list):
            raise GenerationError("Host CLI runner result does not contain pages")
        return result["pages"]


def get_generator(name: str, settings: Settings) -> Generator:
    if name == "mock":
        return MockGenerator()
    if name == "ollama":
        return OllamaGenerator(settings)
    if name in {"auto", "codex_cli", "cursor_cli"}:
        return HostCliSpoolGenerator(settings, name)
    if name == "codex":
        return HostCliSpoolGenerator(settings, "codex_cli")
    raise GenerationError(f"Unknown generator provider: {name}")


def normalize_page(page: dict[str, Any]) -> dict[str, Any]:
    """Normalize untrusted generator output before validation and persistence."""

    normalized = {
        "path": safe_page_path(str(page.get("path", ""))),
        "title": str(page.get("title", "")).strip(),
        "kind": str(page.get("kind", "")).strip(),
        "summary": str(page.get("summary", "")).strip(),
        "markdown": str(page.get("markdown", "")).strip(),
        "tags": [
            str(item).strip() for item in page.get("tags", []) if str(item).strip()
        ][:30],
        "source_refs": page.get("source_refs", []),
    }
    if (
        not normalized["title"]
        or not normalized["summary"]
        or not normalized["markdown"]
    ):
        raise GenerationError(f"Incomplete page proposal: {normalized['path']}")
    if normalized["kind"] not in {"overview", "guide", "api", "example", "concept"}:
        raise GenerationError(f"Invalid page kind: {normalized['kind']}")
    return normalized

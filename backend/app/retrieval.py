from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import Settings
from .locks import LockUnavailable, filesystem_lock, lock_path
from .utils import slugify

TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_.:/-]*|\d+")


def collection_name(library_slug: str, version: str) -> str:
    digest = hashlib.sha256(
        f"{library_slug}\0{version}".encode()
    ).hexdigest()[:12]
    prefix = f"lcf-{slugify(library_slug)}-{slugify(version)}"
    return f"{prefix[:106]}-{digest}"


def _shown_collection_paths(output: str) -> set[Path]:
    """Extract only complete path fields from `qmd collection show` output."""

    candidates: set[str] = set()
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        parsed = None

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, str(child_key).lower())
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str) and key in {
            "path",
            "root",
            "directory",
            "source",
        }:
            candidates.add(value)

    if parsed is not None:
        visit(parsed)
    for raw_line in output.splitlines():
        line = raw_line.strip().strip("\"'")
        if not line:
            continue
        if line.startswith(("/", "~")):
            candidates.add(line)
            continue
        if ":" in line:
            label, value = line.split(":", 1)
            if label.strip().lower() in {"path", "root", "directory", "source"}:
                candidates.add(value.strip().strip("\"'"))

    resolved: set[Path] = set()
    for candidate in candidates:
        try:
            resolved.add(Path(candidate).expanduser().resolve())
        except (OSError, RuntimeError, ValueError):
            continue
    return resolved


def _snippet(markdown: str, terms: list[str], size: int = 420) -> str:
    flattened = re.sub(r"\s+", " ", markdown).strip()
    lowered = flattened.lower()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    position = min(positions) if positions else 0
    start = max(0, position - size // 3)
    end = min(len(flattened), start + size)
    prefix = "…" if start else ""
    suffix = "…" if end < len(flattened) else ""
    return prefix + flattened[start:end] + suffix


def lexical_search(
    pages: list[dict[str, Any]], query: str, limit: int
) -> list[dict[str, Any]]:
    terms = [item.lower() for item in TOKEN_PATTERN.findall(query)]
    phrase = query.strip().lower()
    scored: list[tuple[float, dict[str, Any]]] = []
    for page in pages:
        title = page["title"].lower()
        summary = page["summary"].lower()
        markdown = page["markdown"].lower()
        path = page["path"].lower()
        score = 0.0
        for term in terms:
            score += title.count(term) * 7
            score += path.count(term) * 5
            score += summary.count(term) * 3
            score += min(markdown.count(term), 12)
        if phrase:
            score += title.count(phrase) * 10
            score += summary.count(phrase) * 5
            score += markdown.count(phrase) * 2
        if score > 0:
            scored.append((score, page))
    scored.sort(key=lambda item: (-item[0], item[1]["path"]))
    return [
        {
            **page,
            "score": float(score),
            "snippet": _snippet(page["markdown"], terms),
        }
        for score, page in scored[:limit]
    ]


class QmdRetriever:
    """Thin, failure-tolerant QMD adapter.

    QMD improves navigation with BM25, vectors, and reranking. The reviewed
    Wiki plus its SQLite runtime materialization remain authoritative for
    queries; QMD is disposable. Any missing binary/model/index automatically
    falls back to deterministic lexical search.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def available(self) -> bool:
        return (
            self.settings.qmd_enabled
            and shutil.which(self.settings.qmd_bin) is not None
        )

    def _environment(self, model: str | None = None) -> dict[str, str]:
        environment = os.environ.copy()
        if self.settings.qmd_config_dir:
            environment["QMD_CONFIG_DIR"] = str(self.settings.qmd_config_dir)
        if self.settings.qmd_cache_dir:
            environment["XDG_CACHE_HOME"] = str(self.settings.qmd_cache_dir)
        if model:
            environment["QMD_EMBED_MODEL"] = model
        return environment

    def _run(
        self,
        arguments: list[str],
        *,
        timeout: int = 180,
        model: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.settings.qmd_bin, *arguments],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=self._environment(model),
            check=False,
        )

    def _run_for_model(
        self,
        arguments: list[str],
        *,
        timeout: int,
        model: str | None,
    ) -> subprocess.CompletedProcess[str]:
        if model is None:
            return self._run(arguments, timeout=timeout)
        return self._run(arguments, timeout=timeout, model=model)

    def index(self, wiki_root: Path, name: str) -> dict[str, Any]:
        if not self.available:
            return {"indexed": False, "reason": "qmd-unavailable"}
        wiki_root.mkdir(parents=True, exist_ok=True)
        try:
            with filesystem_lock(
                lock_path(self.settings.locks_dir, "__qmd__", "write"),
                blocking=True,
                timeout_seconds=60,
            ):
                registered = self._register_collection(wiki_root, name)
                # Publication has a bounded completion boundary. Refresh BM25,
                # but build vectors only through the explicit reindex path.
                refreshed = self._refresh(embed=False)
        except LockUnavailable:
            return {"indexed": False, "reason": "qmd-busy"}
        registration_ok = bool(registered.get("registered"))
        refresh_ok = bool(refreshed.get("updated"))
        return {
            "indexed": registration_ok and refresh_ok,
            "collection_registered": registration_ok,
            "embedded": bool(refreshed.get("embedded")),
            "error": str(
                refreshed.get("error") or registered.get("error") or ""
            )[-1000:],
            "reason": registered.get("reason") or refreshed.get("reason"),
            "requires_embedding_refresh": bool(
                self.settings.qmd_hybrid_enabled
                and registration_ok
                and refresh_ok
            ),
        }

    def register_collection(self, wiki_root: Path, name: str) -> dict[str, Any]:
        try:
            with filesystem_lock(
                lock_path(self.settings.locks_dir, "__qmd__", "write"),
                blocking=True,
                timeout_seconds=60,
            ):
                return self._register_collection(wiki_root, name)
        except LockUnavailable:
            return {
                "collection": name,
                "registered": False,
                "reason": "qmd-busy",
            }

    def _register_collection(
        self, wiki_root: Path, name: str
    ) -> dict[str, Any]:
        if not self.available:
            return {
                "collection": name,
                "registered": False,
                "reason": "qmd-unavailable",
            }
        if not wiki_root.is_dir():
            return {
                "collection": name,
                "registered": False,
                "reason": "wiki-root-missing",
                "error": f"Published Wiki directory does not exist: {wiki_root}",
            }
        try:
            existing = self._run(["collection", "show", name])
            if (
                existing.returncode == 0
                and wiki_root.resolve() in _shown_collection_paths(existing.stdout)
            ):
                return {
                    "collection": name,
                    "registered": True,
                    "already_registered": True,
                    "reason": None,
                    "error": "",
                }
            if existing.returncode == 0:
                removed = self._run(["collection", "remove", name])
                if removed.returncode != 0:
                    return {
                        "collection": name,
                        "registered": False,
                        "reason": "qmd-register-failed",
                        "error": removed.stderr[-1000:],
                    }
            add = self._run(
                [
                    "collection",
                    "add",
                    str(wiki_root),
                    "--name",
                    name,
                    "--mask",
                    "**/*.md",
                ]
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return {
                "collection": name,
                "registered": False,
                "reason": "qmd-register-failed",
                "error": str(error)[:1000],
            }
        return {
            "collection": name,
            "registered": add.returncode == 0,
            "reason": None if add.returncode == 0 else "qmd-register-failed",
            "error": add.stderr[-1000:] if add.returncode != 0 else "",
        }

    def refresh(self, *, embed: bool, model: str | None = None) -> dict[str, Any]:
        try:
            with filesystem_lock(
                lock_path(self.settings.locks_dir, "__qmd__", "write"),
                blocking=True,
                timeout_seconds=60,
            ):
                if model is None:
                    return self._refresh(embed=embed)
                return self._refresh(embed=embed, model=model)
        except LockUnavailable:
            return {
                "updated": False,
                "embedded": False,
                "reason": "qmd-busy",
            }

    def _refresh(
        self, *, embed: bool, model: str | None = None
    ) -> dict[str, Any]:
        if not self.available:
            return {
                "updated": False,
                "embedded": False,
                "reason": "qmd-unavailable",
            }
        try:
            update = self._run_for_model(
                ["update"], timeout=600, model=model
            )
            embedded = False
            embed_error = ""
            if embed and update.returncode == 0:
                embed_result = self._run_for_model(
                    [
                        "embed",
                        "-f",
                        "--chunk-strategy",
                        "auto",
                        "--max-docs-per-batch",
                        "50",
                        "--max-batch-mb",
                        "64",
                    ],
                    timeout=1800,
                    model=model,
                )
                embedded = embed_result.returncode == 0
                embed_error = embed_result.stderr[-1000:]
        except (OSError, subprocess.TimeoutExpired) as error:
            return {
                "updated": False,
                "embedded": False,
                "reason": "qmd-refresh-failed",
                "error": str(error)[:1000],
            }
        reason = None
        if update.returncode != 0:
            reason = "qmd-refresh-failed"
        elif embed and not embedded:
            reason = "qmd-embed-failed"
        return {
            "updated": update.returncode == 0,
            "embedded": embedded,
            "reason": reason,
            "error": (
                embed_error if embed and not embedded else update.stderr
            )[-1000:],
        }

    def remove_collection(self, name: str) -> dict[str, Any]:
        try:
            with filesystem_lock(
                lock_path(self.settings.locks_dir, "__qmd__", "write"),
                blocking=True,
                timeout_seconds=60,
            ):
                return self._remove_collection(name)
        except LockUnavailable:
            return {
                "collection": name,
                "removed": False,
                "reason": "qmd-busy",
            }

    def _remove_collection(self, name: str) -> dict[str, Any]:
        if not self.available:
            return {
                "collection": name,
                "removed": False,
                "reason": "qmd-unavailable",
            }
        try:
            result = self._run(["collection", "remove", name])
        except (OSError, subprocess.TimeoutExpired) as error:
            return {
                "collection": name,
                "removed": False,
                "reason": "qmd-remove-failed",
                "error": str(error)[:1000],
            }
        return {
            "collection": name,
            "removed": result.returncode == 0,
            "reason": None if result.returncode == 0 else "qmd-remove-failed",
            "error": result.stderr[-1000:] if result.returncode != 0 else "",
        }

    def rebuild(
        self,
        collections: list[tuple[Path, str]],
        *,
        embed: bool,
        model: str | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Register and refresh every collection under one global writer lock."""

        try:
            with filesystem_lock(
                lock_path(self.settings.locks_dir, "__qmd__", "write"),
                blocking=True,
                timeout_seconds=60,
            ):
                registrations = [
                    self._register_collection(root, name)
                    for root, name in collections
                ]
                refresh = (
                    (
                        self._refresh(embed=embed)
                        if model is None
                        else self._refresh(embed=embed, model=model)
                    )
                    if registrations
                    else {
                        "updated": False,
                        "embedded": False,
                        "reason": "no-published-versions",
                    }
                )
                return registrations, refresh
        except LockUnavailable:
            return (
                [
                    {
                        "collection": name,
                        "registered": False,
                        "reason": "qmd-busy",
                    }
                    for _root, name in collections
                ],
                {
                    "updated": False,
                    "embedded": False,
                    "reason": "qmd-busy",
                },
            )

    @staticmethod
    def _candidate_path(item: dict[str, Any], collection: str) -> str:
        for key in ("path", "file", "document", "uri"):
            value = item.get(key)
            if not isinstance(value, str):
                continue
            value = value.replace("\\", "/")
            if value.startswith("qmd://"):
                value = value.removeprefix("qmd://")
                if value.startswith(collection + "/"):
                    value = value[len(collection) + 1 :]
            if "/versions/" in value:
                value = value.split("/versions/", 1)[1]
                if "/" in value:
                    value = value.split("/", 1)[1]
            return value.lstrip("./")
        return ""

    def query(
        self,
        pages: list[dict[str, Any]],
        *,
        query: str,
        collection: str,
        limit: int,
        model: str | None = None,
        hybrid: bool | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        if not self.available:
            return "lexical", lexical_search(pages, query, limit)
        use_hybrid = (
            self.settings.qmd_hybrid_enabled if hybrid is None else hybrid
        )
        command = "query" if use_hybrid else "search"
        # A collection also contains generated index.md/log.md files which are
        # intentionally absent from the SQLite page authority. Ask QMD for a
        # wider candidate set so filtering those internal documents does not
        # consume the caller's entire result budget.
        candidate_limit = min(max(limit * 4, 20), 100)
        try:
            result = self._run_for_model(
                [
                    command,
                    query,
                    "--json",
                    "-c",
                    collection,
                    "-n",
                    str(candidate_limit),
                ],
                timeout=600 if command == "query" else 180,
                model=model,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "lexical", lexical_search(pages, query, limit)
        if result.returncode != 0:
            return "lexical", lexical_search(pages, query, limit)
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            return "lexical", lexical_search(pages, query, limit)
        if isinstance(parsed, dict):
            candidates = (
                parsed.get("results")
                or parsed.get("documents")
                or parsed.get("matches")
                or []
            )
        else:
            candidates = parsed
        if not isinstance(candidates, list):
            return "lexical", lexical_search(pages, query, limit)
        page_by_path = {page["path"]: page for page in pages}
        ranked: list[dict[str, Any]] = []
        used: set[str] = set()
        terms = [item.lower() for item in TOKEN_PATTERN.findall(query)]
        for rank, item in enumerate(candidates):
            if not isinstance(item, dict):
                continue
            candidate = self._candidate_path(item, collection)
            matches = [
                path
                for path in page_by_path
                if candidate == path or candidate.endswith("/" + path)
            ]
            if not matches:
                continue
            path = matches[0]
            if path in used:
                continue
            page = page_by_path[path]
            raw_score = item.get("score", item.get("similarity", limit - rank))
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                score = float(limit - rank)
            ranked.append(
                {
                    **page,
                    "score": score,
                    "snippet": str(
                        item.get("snippet") or _snippet(page["markdown"], terms)
                    ),
                }
            )
            used.add(path)
        if not ranked:
            return "lexical", lexical_search(pages, query, limit)
        engine = "qmd-hybrid" if command == "query" else "qmd-bm25"
        return engine, ranked[:limit]

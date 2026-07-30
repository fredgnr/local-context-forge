from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .source import sensitive_path_reason
from .utils import atomic_write_json, utcnow

SKIP_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "target",
    "__pycache__",
    ".next",
}

LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".c": "C",
    ".h": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".swift": "Swift",
    ".scala": "Scala",
    ".sh": "Shell",
    ".sql": "SQL",
    ".md": "Markdown",
}

INTERESTING_NAMES = {
    "readme",
    "readme.md",
    "package.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "makefile",
    "dockerfile",
}

CTAGS_KIND_MAP = {
    "c": "class",
    "class": "class",
    "f": "function",
    "function": "function",
    "method": "method",
    "m": "method",
    "member": "field",
    "field": "field",
    "property": "property",
    "interface": "interface",
    "struct": "struct",
    "structure": "struct",
    "enum": "enum",
    "enumeration": "enum",
    "enumerator": "constant",
    "constant": "constant",
    "macro": "macro",
    "define": "macro",
    "trait": "trait",
    "type": "type",
    "typedef": "type",
    "module": "module",
    "namespace": "namespace",
}


@dataclass(slots=True)
class FactsBundle:
    root: Path
    manifest: dict[str, Any]
    symbols: list[dict[str, Any]]
    evidence: dict[str, Any]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _is_likely_text(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:4096]
    except OSError:
        return False
    return b"\0" not in chunk


def _iter_files(repo: Path):
    for path in sorted(repo.rglob("*")):
        if (
            path.is_file()
            and not path.is_symlink()
            and not any(part in SKIP_PARTS for part in path.relative_to(repo).parts)
            and not sensitive_path_reason(path.relative_to(repo))
        ):
            yield path


def _python_symbols(relative: str, text: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    result: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.name.startswith("_") and not (
            node.name.startswith("__") and node.name.endswith("__")
        ):
            continue
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        if isinstance(node, ast.AsyncFunctionDef):
            kind = "async-function"
        try:
            rendered_lines = ast.unparse(node).splitlines()
            signature = next(
                line.strip()
                for line in rendered_lines
                if line.lstrip().startswith(("def ", "async def ", "class "))
            )
            signature = signature.removesuffix(":")
        except (RecursionError, StopIteration, ValueError):
            signature = f"{kind} {node.name}"
        result.append(
            {
                "id": f"{relative}:{node.lineno}:{node.name}",
                "name": node.name,
                "kind": kind,
                "path": relative,
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "signature": signature[:500],
                "docstring": (ast.get_docstring(node) or "")[:2000],
            }
        )
    return result


GENERIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "class",
        re.compile(
            r"^\s*(?:export\s+)?(?:public\s+)?(?:abstract\s+)?"
            r"(?:class|interface|struct|enum|trait)\s+([A-Za-z_]\w*)"
        ),
    ),
    (
        "function",
        re.compile(
            r"^\s*(?:export\s+)?(?:(?:pub|public)\s+)?(?:async\s+)?"
            r"(?:function|func|fn|def)\s+([A-Za-z_]\w*)\s*[\(<]"
        ),
    ),
    (
        "method",
        re.compile(r"^\s*func\s+\([^)]*\)\s+([A-Za-z_]\w*)\s*\("),
    ),
    (
        "method",
        re.compile(
            r"^\s*(?:(?:pub|public|private|protected|static|async)\s+)+"
            r"([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:->[^{}]+)?[{:]?\s*$"
        ),
    ),
]


def _generic_symbols(relative: str, text: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if len(line) > 800:
            continue
        for kind, pattern in GENERIC_PATTERNS:
            match = pattern.match(line)
            if not match:
                continue
            name = match.group(1)
            if name in {"if", "for", "while", "switch", "catch"}:
                continue
            result.append(
                {
                    "id": f"{relative}:{line_number}:{name}",
                    "name": name,
                    "kind": kind,
                    "path": relative,
                    "line": line_number,
                    "end_line": line_number,
                    "signature": line.strip()[:500],
                    "docstring": "",
                }
            )
            break
    return result


def _extract_symbols(relative: str, language: str, text: str) -> list[dict[str, Any]]:
    if language == "Python":
        return _python_symbols(relative, text)
    if language in {
        "JavaScript",
        "TypeScript",
        "Go",
        "Rust",
        "Java",
        "Kotlin",
        "Ruby",
        "PHP",
        "C#",
        "C",
        "C++",
        "Swift",
        "Scala",
    }:
        return _generic_symbols(relative, text)
    return []


def _ctags_symbols(
    settings: Settings,
    repo: Path,
    allowed_paths: set[str],
) -> list[dict[str, Any]] | None:
    """Extract normalized symbols with Universal Ctags.

    ``None`` means ctags was unavailable or failed and instructs the caller to
    use the AST/regex fallback. An empty list is a successful ctags run with no
    supported tags.
    """

    if not settings.ctags_enabled:
        return None
    executable = shutil.which(settings.ctags_bin)
    if not executable:
        return None
    command = [
        executable,
        "--options=NONE",
        "--links=no",
        "--output-format=json",
        "--fields=+aneKSt",
        "--extras=-F",
        "--sort=no",
        "--recurse=yes",
        "--exclude=.git",
        "--exclude=node_modules",
        "--exclude=.venv",
        "--exclude=venv",
        "--exclude=dist",
        "--exclude=build",
        "--exclude=target",
        "--exclude=.aws",
        "--exclude=.azure",
        "--exclude=.codex",
        "--exclude=.gcp",
        "--exclude=.kube",
        "--exclude=.secrets",
        "--exclude=.ssh",
        "--exclude=secrets",
        "--exclude=.env",
        "--exclude=.env.*",
        "--exclude=auth.json",
        "--exclude=id_rsa",
        "--exclude=id_ed25519",
        "--exclude=*.pem",
        "--exclude=*.key",
        "--exclude=*.p12",
        "--exclude=*.pfx",
        "-f",
        "-",
        ".",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            timeout=settings.ctags_timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None

    repo_root = repo.resolve()
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    lines_by_path: dict[str, list[str]] = {}
    # Bound parsing even if an unusual ctags build emits duplicate/noisy data.
    max_records = max(settings.max_symbols * 20, 2_000)
    for raw_line in completed.stdout.splitlines()[:max_records]:
        if len(raw_line) > 1_000_000:
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("_type") != "tag":
            continue
        raw_path = record.get("path")
        name = str(record.get("name") or "").strip()
        if not isinstance(raw_path, str) or not name or len(name) > 300:
            continue
        if name.startswith("_") and not (name.startswith("__") and name.endswith("__")):
            continue
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = repo_root / candidate
        try:
            resolved = candidate.resolve()
            if not resolved.is_relative_to(repo_root) or not resolved.is_file():
                continue
            relative = resolved.relative_to(repo_root).as_posix()
        except (OSError, ValueError):
            continue
        if relative not in allowed_paths:
            continue
        kind = CTAGS_KIND_MAP.get(str(record.get("kind") or "").lower())
        if not kind:
            continue
        access = str(record.get("access") or "").lower()
        if access in {"private", "protected", "internal", "package"}:
            continue
        try:
            line = int(record.get("line"))
        except (TypeError, ValueError):
            continue
        if relative not in lines_by_path:
            try:
                lines_by_path[relative] = resolved.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
            except OSError:
                continue
        source_lines = lines_by_path[relative]
        if line < 1 or line > len(source_lines):
            continue
        try:
            end_line = int(record.get("end", line))
        except (TypeError, ValueError):
            end_line = line
        end_line = min(max(line, end_line), len(source_lines))
        key = (relative, line, name)
        if key in seen:
            continue
        seen.add(key)
        source_signature = source_lines[line - 1].strip()
        ctags_signature = str(record.get("signature") or "").strip()
        if ctags_signature and source_signature.count("(") > source_signature.count(
            ")"
        ):
            signature = f"{name}{ctags_signature}"
        else:
            signature = source_signature or (
                f"{name}{ctags_signature}" if ctags_signature else f"{kind} {name}"
            )
        docstring = str(record.get("doc") or record.get("documentation") or "").strip()
        result.append(
            {
                "id": f"{relative}:{line}:{name}",
                "name": name,
                "kind": kind,
                "path": relative,
                "line": line,
                "end_line": end_line,
                "signature": signature[:500],
                "docstring": docstring[:2000],
                "role": _file_role(relative),
            }
        )
        if len(result) >= settings.max_symbols:
            break
    return result


def _evidence_priority(relative: str, language: str) -> tuple[int, str]:
    lowered = relative.lower()
    name = Path(lowered).name
    if name in INTERESTING_NAMES or name.startswith("readme"):
        return (0, lowered)
    if any(
        part in {"docs", "doc", "examples", "example"} for part in Path(lowered).parts
    ):
        return (1, lowered)
    if language not in {"Unknown", "Markdown"}:
        if any(
            part in {"tests", "test", "__tests__", "spec"}
            for part in Path(lowered).parts
        ):
            return (3, lowered)
        return (2, lowered)
    return (4, lowered)


def _file_role(relative: str) -> str:
    parts = {part.lower() for part in Path(relative).parts}
    name = Path(relative).name.lower()
    if (
        parts.intersection({"tests", "test", "__tests__", "spec"})
        or name.startswith("test_")
        or name.endswith((".test.ts", ".test.js", ".spec.ts", ".spec.js"))
    ):
        return "test"
    if parts.intersection({"examples", "example", "samples", "sample"}):
        return "example"
    if parts.intersection({"docs", "doc"}) or Path(relative).suffix.lower() == ".md":
        return "documentation"
    return "source"


def extract_facts(
    settings: Settings,
    library_slug: str,
    source_sha: str,
    repo: Path,
) -> FactsBundle:
    """Build deterministic facts and a bounded evidence pack from a snapshot."""

    facts_root = settings.facts_dir / library_slug / source_sha
    manifest_path = facts_root / "manifest.json"
    symbols_path = facts_root / "symbols.json"
    evidence_path = facts_root / "evidence.json"
    if manifest_path.exists() and symbols_path.exists() and evidence_path.exists():
        return FactsBundle(
            root=facts_root,
            manifest=json.loads(manifest_path.read_text(encoding="utf-8")),
            symbols=json.loads(symbols_path.read_text(encoding="utf-8")),
            evidence=json.loads(evidence_path.read_text(encoding="utf-8")),
        )

    files: list[dict[str, Any]] = []
    fallback_symbols: list[dict[str, Any]] = []
    candidate_evidence: list[dict[str, Any]] = []
    language_counts: dict[str, int] = {}
    detected_sensitive = [
        {
            "path": path.relative_to(repo).as_posix(),
            "reason": sensitive_path_reason(path.relative_to(repo)),
        }
        for path in sorted(repo.rglob("*"))
        if (path.is_file() or path.is_symlink())
        and sensitive_path_reason(path.relative_to(repo))
    ]

    for path in _iter_files(repo):
        relative = path.relative_to(repo).as_posix()
        size = path.stat().st_size
        language = LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "Unknown")
        role = _file_role(relative)
        language_counts[language] = language_counts.get(language, 0) + 1
        record = {
            "path": relative,
            "bytes": size,
            "sha256": _sha256(path),
            "language": language,
            "role": role,
        }
        files.append(record)
        if size > settings.max_file_bytes or not _is_likely_text(path):
            continue
        if len(fallback_symbols) < settings.max_symbols:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            extracted = _extract_symbols(relative, language, text)[
                : settings.max_symbols - len(fallback_symbols)
            ]
            for symbol in extracted:
                symbol["role"] = role
            fallback_symbols.extend(extracted)
        candidate_evidence.append(
            {
                "path": relative,
                "language": language,
                "role": role,
                "_source_path": path,
                "_priority": _evidence_priority(relative, language),
            }
        )

    ctags_symbols = _ctags_symbols(
        settings, repo, {str(item["path"]) for item in files}
    )
    if ctags_symbols is None:
        symbols = fallback_symbols
        symbol_extractor = "ast-regex-fallback"
    else:
        fallback_by_key = {
            (item["path"], item["line"], item["name"]): item
            for item in fallback_symbols
        }
        for symbol in ctags_symbols:
            fallback = fallback_by_key.get(
                (symbol["path"], symbol["line"], symbol["name"])
            )
            if fallback and not symbol["docstring"]:
                symbol["docstring"] = fallback["docstring"]
        symbols = ctags_symbols
        symbol_extractor = "universal-ctags"

    used_bytes = 0
    evidence_files: list[dict[str, Any]] = []
    for item in sorted(candidate_evidence, key=lambda item: item["_priority"]):
        try:
            content_on_disk = item["_source_path"].read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            continue
        encoded = content_on_disk.encode("utf-8")
        remaining = settings.max_evidence_bytes - used_bytes
        if remaining <= 0:
            break
        if len(encoded) > remaining:
            if remaining < 2_000:
                continue
            content = encoded[:remaining].decode("utf-8", errors="ignore")
            truncated = True
        else:
            content = content_on_disk
            truncated = False
        used_bytes += len(content.encode("utf-8"))
        evidence_files.append(
            {
                "path": item["path"],
                "language": item["language"],
                "role": item["role"],
                "content": content,
                "truncated": truncated,
            }
        )

    manifest = {
        "schema_version": 1,
        "source_sha": source_sha,
        "created_at": utcnow(),
        "file_count": len(files),
        "languages": language_counts,
        "symbol_extractor": symbol_extractor,
        "symbol_count": len(symbols),
        "skipped_sensitive": detected_sensitive,
        "files": files,
    }
    snapshot_metadata_path = repo.parent / "snapshot.json"
    if snapshot_metadata_path.exists():
        try:
            snapshot_metadata = json.loads(
                snapshot_metadata_path.read_text(encoding="utf-8")
            )
            skipped_sensitive = snapshot_metadata.get("skipped_sensitive", [])
            if isinstance(skipped_sensitive, list):
                merged = {
                    (str(item.get("path")), str(item.get("reason"))): item
                    for item in [*detected_sensitive, *skipped_sensitive]
                    if isinstance(item, dict)
                }
                manifest["skipped_sensitive"] = [merged[key] for key in sorted(merged)]
        except (OSError, json.JSONDecodeError):
            pass
    evidence = {
        "schema_version": 1,
        "source_sha": source_sha,
        "created_at": utcnow(),
        "files": evidence_files,
        "symbols": symbols,
        "evidence_bytes": used_bytes,
    }
    facts_root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(manifest_path, manifest)
    atomic_write_json(symbols_path, symbols)
    atomic_write_json(evidence_path, evidence)
    return FactsBundle(
        root=facts_root, manifest=manifest, symbols=symbols, evidence=evidence
    )

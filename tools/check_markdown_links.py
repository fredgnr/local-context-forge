#!/usr/bin/env python3
"""Validate repository-local links in Markdown documentation."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)\s]+)(?:\s+[^)]*)?\)")
EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "node_modules",
    "dist",
    "release",
}


def markdown_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not EXCLUDED_PARTS.intersection(path.relative_to(ROOT).parts)
    )


def link_target(source: Path, raw_target: str) -> Path | None:
    target = unquote(raw_target.strip("<>")).split("#", 1)[0].split("?", 1)[0]
    if (
        not target
        or target.startswith(("#", "/", "//"))
        or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target)
    ):
        return None
    return (source.parent / target).resolve()


def main() -> int:
    failures: list[str] = []
    for source in markdown_files():
        content = source.read_text(encoding="utf-8")
        for line_number, line in enumerate(content.splitlines(), start=1):
            for match in MARKDOWN_LINK.finditer(line):
                target = link_target(source, match.group(1))
                if target is None:
                    continue
                try:
                    target.relative_to(ROOT)
                except ValueError:
                    failures.append(
                        f"{source.relative_to(ROOT)}:{line_number}: "
                        f"link escapes repository: {match.group(1)}"
                    )
                    continue
                if not target.exists():
                    failures.append(
                        f"{source.relative_to(ROOT)}:{line_number}: "
                        f"missing target: {match.group(1)}"
                    )

    if failures:
        print("Markdown link validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"Markdown link validation passed: {len(markdown_files())} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

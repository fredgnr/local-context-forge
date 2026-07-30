from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-.")
    return value or "library"


def safe_relative_path(value: str, *, suffix: str | None = None) -> str:
    original = value
    if (
        not original
        or original.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:", original)
        or "\0" in original
    ):
        raise ValueError(f"Unsafe relative path: {original!r}")
    value = original.replace("\\", "/")
    path = PurePosixPath(value)
    if (
        any(part in {"", ".", ".."} for part in path.parts)
        or len(value.encode("utf-8")) > 800
        or any(len(part.encode("utf-8")) > 240 for part in path.parts)
    ):
        raise ValueError(f"Unsafe relative path: {original!r}")
    normalized = str(path)
    if suffix and not normalized.endswith(suffix):
        normalized += suffix
    return normalized


_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def safe_page_path(value: str, *, suffix: str = ".md") -> str:
    """Normalize a generated Wiki page path for macOS/Windows portability."""

    normalized_value = unicodedata.normalize("NFC", value)
    normalized = safe_relative_path(normalized_value, suffix=suffix)
    parts = PurePosixPath(normalized).parts
    if parts[0].casefold() in {"facts", "index.md", "log.md"}:
        raise ValueError(f"Page path collides with generated Wiki metadata: {value!r}")
    for part in parts:
        upper_stem = part.split(".", 1)[0].upper()
        if (
            part.casefold() == ".git"
            or upper_stem in _WINDOWS_RESERVED_NAMES
            or any(character in '<>:"|?*' for character in part)
            or any(ord(character) < 32 for character in part)
            or part.endswith((" ", "."))
        ):
            raise ValueError(f"Non-portable Wiki page path: {value!r}")
    return normalized


def portable_path_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(
        path, json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )


def parse_json_object(value: str) -> dict[str, Any]:
    cleaned = value.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object")  # noqa: TRY004
    return parsed

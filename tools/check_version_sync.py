#!/usr/bin/env python3
"""Fail when product and protocol versions drift across release surfaces."""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "runtime" / "version.json"


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain an object")
    return value


def _python_project_version(path: Path) -> str:
    value = tomllib.loads(path.read_text(encoding="utf-8"))
    return str(value["project"]["version"])


def _safe_constant_expression(
    value: ast.expr,
    symbols: dict[str, object],
) -> object:
    try:
        return ast.literal_eval(value)
    except (ValueError, TypeError):
        pass
    if isinstance(value, ast.Name) and value.id in symbols:
        return symbols[value.id]
    if isinstance(value, ast.JoinedStr):
        pieces: list[str] = []
        for part in value.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                pieces.append(part.value)
            elif (
                isinstance(part, ast.FormattedValue)
                and part.conversion == -1
                and part.format_spec is None
            ):
                resolved = _safe_constant_expression(part.value, symbols)
                if not isinstance(resolved, (str, int)):
                    raise ValueError("formatted constant is not a string or integer")
                pieces.append(str(resolved))
            else:
                raise ValueError("joined constant is not statically resolvable")
        return "".join(pieces)
    raise ValueError("constant is not statically resolvable")


def _constant(path: Path, name: str) -> object:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    symbols: dict[str, object] = {}
    for statement in module.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            target = statement.target
            value = statement.value
        if isinstance(target, ast.Name) and value is not None:
            try:
                resolved = _safe_constant_expression(value, symbols)
            except (ValueError, TypeError) as error:
                if target.id == name:
                    raise ValueError(
                        f"{name} in {path.relative_to(ROOT)} must be static"
                    ) from error
                continue
            symbols[target.id] = resolved
            if target.id == name:
                return resolved
    raise ValueError(f"{name} is missing from {path.relative_to(ROOT)}")


def _typescript_string_constant(path: Path, name: str) -> str:
    pattern = re.compile(
        rf"^export\s+const\s+{re.escape(name)}\s*=\s*[\"']([^\"']+)[\"']",
        re.MULTILINE,
    )
    match = pattern.search(path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"{name} is missing from {path.relative_to(ROOT)}")
    return match.group(1)


def main() -> int:
    manifest = _load_json(MANIFEST_PATH)
    product = str(manifest["productVersion"])
    python_distribution = str(manifest["pythonDistributionVersion"])
    protocol = manifest["desktopProtocol"]
    if not isinstance(protocol, dict):
        raise ValueError("desktopProtocol must contain major and minor")
    retrieval_protocol = manifest["desktopRetrievalProtocol"]
    if not isinstance(retrieval_protocol, dict):
        raise ValueError("desktopRetrievalProtocol must contain major and minor")
    protocol_version = f"{protocol['major']}.{protocol['minor']}"
    retrieval_protocol_version = (
        f"{retrieval_protocol['major']}.{retrieval_protocol['minor']}"
    )

    checks: list[tuple[str, object, object]] = [
        (
            "backend project version",
            _python_project_version(ROOT / "backend" / "pyproject.toml"),
            python_distribution,
        ),
        (
            "backend product version",
            _constant(ROOT / "backend" / "app" / "version.py", "APP_VERSION"),
            product,
        ),
        (
            "backend distribution constant",
            _constant(
                ROOT / "backend" / "app" / "version.py",
                "PYTHON_DISTRIBUTION_VERSION",
            ),
            python_distribution,
        ),
        (
            "backend protocol major",
            int(
                _constant(
                    ROOT / "backend" / "app" / "version.py",
                    "DESKTOP_PROTOCOL_MAJOR",
                )
            ),
            int(protocol["major"]),
        ),
        (
            "backend protocol minor",
            int(
                _constant(
                    ROOT / "backend" / "app" / "version.py",
                    "DESKTOP_PROTOCOL_MINOR",
                )
            ),
            int(protocol["minor"]),
        ),
        (
            "backend retrieval protocol major",
            int(
                _constant(
                    ROOT / "backend" / "app" / "version.py",
                    "DESKTOP_RETRIEVAL_PROTOCOL_MAJOR",
                )
            ),
            int(retrieval_protocol["major"]),
        ),
        (
            "backend retrieval protocol minor",
            int(
                _constant(
                    ROOT / "backend" / "app" / "version.py",
                    "DESKTOP_RETRIEVAL_PROTOCOL_MINOR",
                )
            ),
            int(retrieval_protocol["minor"]),
        ),
        (
            "backend retrieval protocol version",
            _constant(
                ROOT / "backend" / "app" / "version.py",
                "DESKTOP_RETRIEVAL_PROTOCOL_VERSION",
            ),
            retrieval_protocol_version,
        ),
        (
            "database schema",
            int(_constant(ROOT / "backend" / "app" / "db.py", "SCHEMA_VERSION")),
            int(manifest["databaseSchema"]),
        ),
    ]

    desktop_package = ROOT / "desktop" / "package.json"
    if desktop_package.exists():
        desktop_contracts = ROOT / "desktop" / "src" / "contracts.ts"
        desktop_retrieval_broker = (
            ROOT / "desktop" / "src" / "main" / "retrievalBroker.ts"
        )
        checks.extend(
            [
                (
                    "desktop package version",
                    str(_load_json(desktop_package)["version"]),
                    product,
                ),
                (
                    "desktop bridge protocol",
                    _typescript_string_constant(
                        desktop_contracts, "DESKTOP_BRIDGE_VERSION"
                    ),
                    protocol_version,
                ),
                (
                    "desktop sidecar protocol",
                    _typescript_string_constant(
                        desktop_contracts, "SIDECAR_PROTOCOL_VERSION"
                    ),
                    protocol_version,
                ),
                (
                    "desktop retrieval broker protocol",
                    _typescript_string_constant(
                        desktop_retrieval_broker,
                        "RETRIEVAL_BROKER_PROTOCOL_VERSION",
                    ),
                    retrieval_protocol_version,
                ),
            ]
        )

    web_bridge = ROOT / "web" / "src" / "desktopBridge.ts"
    if web_bridge.exists():
        checks.append(
            (
                "web desktop bridge protocol",
                _typescript_string_constant(web_bridge, "DESKTOP_BRIDGE_VERSION"),
                f"{protocol['major']}.{protocol['minor']}",
            )
        )

    failures = [
        f"{label}: found {actual!r}, expected {expected!r}"
        for label, actual, expected in checks
        if actual != expected
    ]
    if failures:
        print("Version synchronization failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(
        "Version synchronization passed: "
        f"{product}, desktop protocol {protocol['major']}.{protocol['minor']}, "
        "desktop retrieval protocol "
        f"{retrieval_protocol['major']}.{retrieval_protocol['minor']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

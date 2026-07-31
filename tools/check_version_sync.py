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


def _constant(path: Path, name: str) -> object:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for statement in module.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            target = statement.target
            value = statement.value
        if isinstance(target, ast.Name) and target.id == name and value is not None:
            try:
                return ast.literal_eval(value)
            except (ValueError, TypeError) as error:
                raise ValueError(
                    f"{name} in {path.relative_to(ROOT)} must be a literal"
                ) from error
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
            "database schema",
            int(_constant(ROOT / "backend" / "app" / "db.py", "SCHEMA_VERSION")),
            int(manifest["databaseSchema"]),
        ),
    ]

    desktop_package = ROOT / "desktop" / "package.json"
    if desktop_package.exists():
        desktop_contracts = ROOT / "desktop" / "src" / "contracts.ts"
        protocol_version = f"{protocol['major']}.{protocol['minor']}"
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
        f"{product}, desktop protocol {protocol['major']}.{protocol['minor']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

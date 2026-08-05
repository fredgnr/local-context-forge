#!/usr/bin/env python3
"""Fail-closed audit for a staged PyInstaller onedir.

The production native scanner intentionally requires Darwin's ``lipo`` and
``otool``. Pure-Python policy functions accept an injected scanner so Linux
fixtures can exercise inventory and tamper decisions without pretending to
validate a macOS binary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import re
import secrets
import stat
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


MANIFEST_NAME = "build-manifest.json"
MANIFEST_SCHEMA_VERSION = 1
EXPECTED_EXECUTABLE = "lcf-service"
REVIEWED_PYTHON_FRAMEWORK_LEAF = PurePosixPath(
    "_internal/Python.framework/Versions/3.13/Python"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
PACKAGING_ROOT = BACKEND_ROOT / "packaging"
RUNTIME_ROOT = REPOSITORY_ROOT / "runtime"
VERSION_FILE = RUNTIME_ROOT / "version.json"
TOOLCHAIN_LOCK = PACKAGING_ROOT / "python-sidecar-toolchain.lock.json"
MANIFEST_SCHEMA = RUNTIME_ROOT / "python-sidecar-build-manifest.schema.json"
SYSTEM_DYLIB_PREFIXES = ("/usr/lib/", "/System/Library/")
FORBIDDEN_PATH_FRAGMENTS = (
    "/opt/homebrew/",
    "/usr/local/",
    "/.venv/",
    "/Library/Frameworks/Python.framework/",
)
MACHO_MAGICS = {
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
}
REQUIRED_RUNTIME_COMPONENTS = {
    "certifi",
    "cpython",
    "dulwich",
    "openssl",
    "pydantic-core",
    "pyinstaller-bootloader",
    "python-hashlib",
    "sqlite",
    "urllib3",
}
REQUIRED_BUILD_TOOLS = {
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "uv",
}
EXPECTED_FROZEN_SMOKE = {
    "status": "pass",
    "pathTrap": True,
    "checks": [
        "version",
        "doctor",
        "uds-handshake",
        "uds-health",
        "domain-ingest",
        "domain-publish",
        "domain-lint",
    ],
}
MAX_REVIEWED_FRAMEWORK_LEAF_BYTES = 256 * 1024 * 1024
ISOLATED_FRAMEWORK_LEAF_TEMP_PREFIX = "lcf-python-leaf-"
PRODUCTION_ISOLATION_PARENT = Path("/private/tmp")
ISOLATED_FRAMEWORK_LEAF_PARENT = PRODUCTION_ISOLATION_PARENT
BOUND_FILE_STAT_FIELDS = (
    "st_dev",
    "st_ino",
    "st_mode",
    "st_uid",
    "st_gid",
    "st_nlink",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
)


class AuditError(RuntimeError):
    """Raised when staged sidecar evidence is incomplete or unsafe."""


@dataclass(frozen=True)
class _IsolatedFrameworkLeaf:
    parent: Path
    child: Path
    child_name: str
    source: Path
    copy: Path
    parent_descriptor: int
    child_descriptor: int
    source_descriptor: int
    copy_descriptor: int
    parent_snapshot: tuple[Any, ...]
    child_snapshot: tuple[Any, ...]
    source_snapshot: tuple[Any, ...]
    copy_snapshot: tuple[Any, ...]


NativeScanner = Callable[[Path], list[dict[str, Any]]]


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise AuditError(f"{label} must be an object")
    return value


def cast_mapping(value: Any, label: str = "manifest value") -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AuditError(f"{label} must be an object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise AuditError("Unable to hash an audited file") from exc
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def normalized_inventory_sha256(
    files: Sequence[Mapping[str, Any]],
    native: Sequence[Mapping[str, Any]],
) -> str:
    return hashlib.sha256(
        canonical_json_bytes({"files": list(files), "native": list(native)})
    ).hexdigest()


def critical_input_paths() -> list[Path]:
    """Return the exact repository inputs that invalidate an audited staging."""

    paths = [
        REPOSITORY_ROOT / "Makefile",
        BACKEND_ROOT / "pyproject.toml",
        BACKEND_ROOT / "uv.lock",
        PACKAGING_ROOT / "build-requirements.lock",
        PACKAGING_ROOT / "frozen_entrypoint.py",
        PACKAGING_ROOT / "lcf_sidecar.spec",
        PACKAGING_ROOT / "license-policy.json",
        PACKAGING_ROOT / "missing-imports-allowlist.json",
        PACKAGING_ROOT / "python-sidecar-toolchain.lock.json",
        *sorted((PACKAGING_ROOT / "notices").glob("*.txt")),
        REPOSITORY_ROOT / "desktop" / "electron-builder.yml",
        REPOSITORY_ROOT / "desktop" / "electron-builder.release.yml",
        REPOSITORY_ROOT / "desktop" / "package-lock.json",
        REPOSITORY_ROOT / "desktop" / "package.json",
        REPOSITORY_ROOT / "desktop" / "scripts" / "afterPack.cjs",
        REPOSITORY_ROOT / "desktop" / "scripts" / "beforePack.cjs",
        REPOSITORY_ROOT
        / "desktop"
        / "scripts"
        / "resealPackagedRuntimes.cjs",
        REPOSITORY_ROOT / ".github" / "workflows" / "desktop-release.yml",
        MANIFEST_SCHEMA,
        VERSION_FILE,
        REPOSITORY_ROOT / "tools" / "audit_python_sidecar.py",
        REPOSITORY_ROOT / "tools" / "build_python_sidecar.py",
    ]
    return sorted(set(paths), key=lambda path: path.as_posix())


def critical_input_digests() -> dict[str, str]:
    result: dict[str, str] = {}
    for path in critical_input_paths():
        try:
            info = path.lstat()
        except OSError as exc:
            raise AuditError("A critical build input is missing") from exc
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise AuditError("A critical build input is not a regular file")
        result[path.relative_to(REPOSITORY_ROOT).as_posix()] = sha256_file(path)
    return dict(sorted(result.items()))


def _relative_name(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise AuditError("Inventory path escapes the sidecar root") from exc
    value = relative.as_posix()
    pure = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or value.startswith("../")
        or ".." in pure.parts
        or "\\" in value
        or "\x00" in value
    ):
        raise AuditError("Inventory contains an unsafe relative path")
    return value


def _contained(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_symlink(root: Path, path: Path) -> str:
    try:
        target = os.readlink(path)
    except OSError as exc:
        raise AuditError("Sidecar symlink is unreadable") from exc
    if not target or "\x00" in target or os.path.isabs(target):
        raise AuditError("Sidecar contains an absolute or empty symlink")
    try:
        resolved = (path.parent / target).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AuditError("Sidecar contains a broken or cyclic symlink") from exc
    if not _contained(root, resolved):
        raise AuditError("Sidecar symlink escapes the bundle")
    return target


def build_file_inventory(root: Path) -> list[dict[str, Any]]:
    """Build an exact, sorted inventory excluding the self-referential manifest."""

    try:
        root_info = root.lstat()
    except OSError as exc:
        raise AuditError("Sidecar root must be a real directory") from exc
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise AuditError("Sidecar root must be a real directory")
    root = root.resolve()
    inventory: list[dict[str, Any]] = []

    def walk(directory: Path) -> None:
        try:
            children = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise AuditError("Sidecar directory is unreadable") from exc
        for child in children:
            path = Path(child.path)
            relative = _relative_name(root, path)
            if relative == MANIFEST_NAME:
                continue
            try:
                info = path.lstat()
            except OSError as exc:
                raise AuditError("Sidecar entry changed during inventory") from exc
            common: dict[str, Any] = {
                "path": relative,
                "mode": f"{stat.S_IMODE(info.st_mode):04o}",
            }
            if stat.S_ISLNK(info.st_mode):
                target = _validate_symlink(root, path)
                encoded = target.encode("utf-8")
                inventory.append(
                    {
                        **common,
                        "type": "symlink",
                        "size": len(encoded),
                        "sha256": hashlib.sha256(encoded).hexdigest(),
                        "linkTarget": target,
                    }
                )
            elif stat.S_ISDIR(info.st_mode):
                inventory.append({**common, "type": "directory", "size": 0})
                walk(path)
            elif stat.S_ISREG(info.st_mode):
                inventory.append(
                    {
                        **common,
                        "type": "file",
                        "size": info.st_size,
                        "sha256": sha256_file(path),
                    }
                )
            else:
                raise AuditError("Sidecar contains a special file")

    walk(root)
    inventory.sort(key=lambda item: str(item["path"]))
    paths = [str(item["path"]) for item in inventory]
    if len(paths) != len(set(paths)):
        raise AuditError("Sidecar inventory contains duplicate paths")
    return inventory


def is_macho(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) in MACHO_MAGICS
    except OSError as exc:
        raise AuditError("Unable to inspect a possible Mach-O file") from exc


def _native_tool_label(
    arguments: Sequence[str],
    *,
    isolated_framework_leaf: _IsolatedFrameworkLeaf | None = None,
) -> str:
    contracts = {
        ("/usr/bin/otool", "-l"): "otool-load-commands",
        ("/usr/bin/otool", "-L"): "otool-dependencies",
        ("/usr/bin/otool", "-D"): "otool-install-name",
        ("/usr/bin/lipo", "-archs"): "lipo-architectures",
    }
    if len(arguments) < 2:
        raise AuditError("Native inspection tool contract is invalid")
    if (arguments[0], arguments[1]) == ("/usr/bin/codesign", "--verify"):
        if len(arguments) == 4 and arguments[2] == "--strict":
            if isolated_framework_leaf is None:
                label = "codesign-verify"
            elif _is_isolated_framework_leaf_contract(
                arguments,
                isolated_framework_leaf,
            ):
                label = "codesign-verify-isolated-leaf"
            else:
                label = None
        else:
            label = None
    else:
        if isolated_framework_leaf is not None:
            raise AuditError("Native inspection tool contract is invalid")
        label = contracts.get((arguments[0], arguments[1]))
    expected_length = 4 if label in {
        "codesign-verify",
        "codesign-verify-isolated-leaf",
    } else 3
    if (
        label is None
        or len(arguments) != expected_length
        or not Path(arguments[-1]).is_absolute()
    ):
        raise AuditError("Native inspection tool contract is invalid")
    return label


def _is_isolated_framework_leaf_contract(
    arguments: Sequence[str],
    capability: _IsolatedFrameworkLeaf,
) -> bool:
    if not isinstance(capability, _IsolatedFrameworkLeaf):
        return False
    source = capability.source
    isolated_copy = capability.copy
    if (
        not source.is_absolute()
        or not isolated_copy.is_absolute()
        or Path(arguments[-1]) != isolated_copy
        or source == isolated_copy
        or capability.parent != ISOLATED_FRAMEWORK_LEAF_PARENT
        or capability.child != capability.parent / capability.child_name
        or isolated_copy != capability.child / "Python"
        or isolated_copy.name != "Python"
        or tuple(source.parts[-len(REVIEWED_PYTHON_FRAMEWORK_LEAF.parts) :])
        != REVIEWED_PYTHON_FRAMEWORK_LEAF.parts
        or any(
            part.casefold().endswith(".framework")
            for part in isolated_copy.parts
        )
    ):
        return False
    try:
        _validate_isolated_framework_leaf_state(capability)
    except AuditError:
        return False
    return True


def _native_target_label(
    arguments: Sequence[str],
    *,
    isolated_framework_leaf: _IsolatedFrameworkLeaf | None = None,
) -> str:
    if isolated_framework_leaf is not None:
        return "python-framework"
    target = Path(arguments[-1])
    if target.name == EXPECTED_EXECUTABLE:
        return "entrypoint"
    if target.suffix == ".so":
        return "extension-module"
    if target.suffix == ".dylib":
        return "dylib"
    framework_parts = {
        part
        for part in target.parts
        if part.casefold().endswith(".framework")
    }
    normalized_framework_parts = {part.casefold() for part in framework_parts}
    if "python.framework" in normalized_framework_parts:
        return "python-framework"
    if "tcl.framework" in normalized_framework_parts:
        return "tcl-framework"
    if "tk.framework" in normalized_framework_parts:
        return "tk-framework"
    if framework_parts:
        return "other-framework"
    return "other-macho"


def _native_failure_category(
    tool: str,
    stderr: Any,
) -> str:
    if tool not in {
        "codesign-verify",
        "codesign-verify-isolated-leaf",
    } or not isinstance(stderr, str):
        return "exit"
    normalized = stderr.lower()
    if "code object is not signed at all" in normalized:
        return "unsigned"
    if (
        "invalid signature" in normalized
        or "invalid or unsupported format" in normalized
    ):
        return "invalid-signature"
    if (
        "resource envelope" in normalized
        or "sealed resource" in normalized
        or "unsealed content" in normalized
    ):
        return "resource-seal"
    if "bundle format" in normalized:
        return "unsupported-format"
    if (
        "main executable failed strict validation" in normalized
        or "errseccsbadmainexecutable" in normalized
    ):
        return "strict-layout"
    return "exit"


def _run_native_tool(
    arguments: Sequence[str],
    *,
    isolated_framework_leaf: _IsolatedFrameworkLeaf | None = None,
) -> str:
    if platform.system() != "Darwin":
        raise AuditError("Real Mach-O inspection requires Darwin")
    label = _native_tool_label(
        arguments,
        isolated_framework_leaf=isolated_framework_leaf,
    )
    target = _native_target_label(
        arguments,
        isolated_framework_leaf=isolated_framework_leaf,
    )
    try:
        completed = subprocess.run(
            list(arguments),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
                "LC_ALL": "C",
            },
        )
    except subprocess.CalledProcessError as exc:
        category = _native_failure_category(label, exc.stderr)
        return_code = (
            exc.returncode
            if isinstance(exc.returncode, int) and -255 <= exc.returncode <= 255
            else "other"
        )
        raise AuditError(
            "Native inspection tool failed "
            f"(tool={label}; target={target}; category={category}; "
            f"code={return_code})"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AuditError(
            "Native inspection tool failed "
            f"(tool={label}; target={target}; category=timeout)"
        ) from exc
    except OSError as exc:
        raise AuditError(
            "Native inspection tool failed "
            f"(tool={label}; target={target}; category=launch)"
        ) from exc
    return completed.stdout


def _parse_lipo_architectures(output: str) -> list[str]:
    architectures = output.strip().split()
    if not architectures or any(
        re.fullmatch(r"[A-Za-z0-9_]+", item) is None for item in architectures
    ):
        raise AuditError("Unable to parse Mach-O architectures")
    return sorted(set(architectures))


def _parse_otool_dependencies(output: str) -> list[str]:
    lines = output.splitlines()
    dependencies: list[str] = []
    for line in lines[1:]:
        value = line.strip()
        if not value:
            continue
        dependency = value.split(" (", 1)[0]
        if dependency:
            dependencies.append(dependency)
    return sorted(set(dependencies))


def _parse_otool_install_name(output: str) -> str | None:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[1] if len(lines) > 1 else None


def _parse_otool_rpaths(output: str) -> list[str]:
    lines = output.splitlines()
    rpaths: list[str] = []
    for index, line in enumerate(lines):
        if line.strip() != "cmd LC_RPATH":
            continue
        for detail in lines[index + 1 : index + 8]:
            match = re.match(r"\s*path\s+(.+?)\s+\(offset\s+\d+\)\s*$", detail)
            if match:
                rpaths.append(match.group(1))
                break
        else:
            raise AuditError("Malformed LC_RPATH load command")
    return sorted(set(rpaths))


def _parse_otool_build_target(output: str) -> tuple[str, str]:
    """Return the single effective platform/minimum-version load command."""

    lines = output.splitlines()
    targets: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        command = line.strip()
        if command == "cmd LC_BUILD_VERSION":
            platform_name: str | None = None
            minimum: str | None = None
            for detail in lines[index + 1 : index + 10]:
                platform_match = re.match(r"\s*platform\s+(\S+)\s*$", detail)
                if platform_match:
                    raw_platform = platform_match.group(1)
                    platform_name = (
                        "macos"
                        if raw_platform.lower() in {"1", "macos", "macosx"}
                        else raw_platform.lower()
                    )
                minimum_match = re.match(
                    r"\s*minos\s+([0-9]+(?:\.[0-9]+){1,2})\s*$",
                    detail,
                )
                if minimum_match:
                    minimum = minimum_match.group(1)
            if platform_name is None or minimum is None:
                raise AuditError("Malformed LC_BUILD_VERSION load command")
            targets.append((platform_name, minimum))
        elif command == "cmd LC_VERSION_MIN_MACOSX":
            minimum = None
            for detail in lines[index + 1 : index + 7]:
                match = re.match(
                    r"\s*version\s+([0-9]+(?:\.[0-9]+){1,2})\s*$",
                    detail,
                )
                if match:
                    minimum = match.group(1)
                    break
            if minimum is None:
                raise AuditError("Malformed LC_VERSION_MIN_MACOSX load command")
            targets.append(("macos", minimum))
    if len(targets) != 1:
        raise AuditError("Mach-O must have exactly one macOS build target")
    return targets[0]


def _read_bound_framework_plist(path: Path) -> tuple[bytes, os.stat_result]:
    """Read the fixed framework plist through a no-follow, identity-bound fd."""

    descriptor: int | None = None
    try:
        path_before = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        fd_before = os.fstat(descriptor)
        current_uid = os.geteuid()
        fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        path_before_identity = tuple(
            getattr(path_before, field) for field in fields
        )
        fd_before_identity = tuple(
            getattr(fd_before, field) for field in fields
        )
        if (
            not stat.S_ISREG(path_before.st_mode)
            or stat.S_ISLNK(path_before.st_mode)
            or path_before.st_uid != current_uid
            or path_before.st_nlink != 1
            or path_before.st_size <= 0
            or path_before.st_size > 1024 * 1024
            or stat.S_IMODE(path_before.st_mode) & 0o022
            or not stat.S_ISREG(fd_before.st_mode)
            or fd_before.st_uid != current_uid
            or fd_before.st_nlink != 1
            or fd_before.st_size <= 0
            or fd_before.st_size > 1024 * 1024
            or stat.S_IMODE(fd_before.st_mode) & 0o022
            or path_before_identity != fd_before_identity
        ):
            raise AuditError("Reviewed Python framework Info.plist is unsafe")
        chunks: list[bytes] = []
        remaining = 1024 * 1024 + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        fd_after = os.fstat(descriptor)
        path_after = path.lstat()
        if (
            len(payload) != fd_before.st_size
            or tuple(getattr(fd_after, field) for field in fields)
            != fd_before_identity
            or tuple(getattr(path_after, field) for field in fields)
            != fd_before_identity
        ):
            raise AuditError("Reviewed Python framework Info.plist changed")
        return payload, fd_before
    except AuditError:
        raise
    except OSError as exc:
        raise AuditError("Reviewed Python framework Info.plist is unreadable") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as exc:
                raise AuditError(
                    "Reviewed Python framework Info.plist could not be closed"
                ) from exc


def _validate_reviewed_python_framework(
    root: Path,
    path: Path,
) -> tuple[tuple[Any, ...], ...] | None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise AuditError("Mach-O path escapes the sidecar") from exc
    framework_parts = [
        part
        for part in relative.parts
        if part.casefold().endswith(".framework")
    ]
    if not framework_parts:
        return None
    if relative != REVIEWED_PYTHON_FRAMEWORK_LEAF:
        raise AuditError("Mach-O uses an unreviewed framework layout")

    framework = root / "_internal" / "Python.framework"
    versions = framework / "Versions"
    version = versions / "3.13"
    resources = version / "Resources"
    current_uid = os.geteuid()
    snapshot: list[tuple[Any, ...]] = []
    for directory in (
        root / "_internal",
        framework,
        versions,
        version,
        resources,
    ):
        try:
            info = directory.lstat()
            canonical = directory.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise AuditError("Reviewed Python framework layout is incomplete") from exc
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != current_uid
            or stat.S_IMODE(info.st_mode) & 0o022
            or canonical != directory
        ):
            raise AuditError("Reviewed Python framework layout is unsafe")
        try:
            entries = tuple(sorted(item.name for item in directory.iterdir()))
        except OSError as exc:
            raise AuditError("Reviewed Python framework layout is unreadable") from exc
        snapshot.append(
            (
                directory.relative_to(root).as_posix(),
                info.st_dev,
                info.st_ino,
                info.st_mode,
                info.st_uid,
                info.st_nlink,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
                entries,
            )
        )

    expected_entries = {
        framework: ("Python", "Resources", "Versions"),
        versions: ("3.13", "Current"),
        version: ("Python", "Resources"),
        resources: ("Info.plist",),
    }
    for directory, expected in expected_entries.items():
        observed = next(
            item[-1]
            for item in snapshot
            if item[0] == directory.relative_to(root).as_posix()
        )
        if observed != expected:
            raise AuditError("Reviewed Python framework entries differ")

    required_links = {
        framework / "Python": "Versions/Current/Python",
        framework / "Resources": "Versions/Current/Resources",
        versions / "Current": "3.13",
    }
    for link, expected_target in required_links.items():
        try:
            info = link.lstat()
            target = os.readlink(link)
        except OSError as exc:
            raise AuditError("Reviewed Python framework layout is incomplete") from exc
        if (
            not stat.S_ISLNK(info.st_mode)
            or info.st_uid != current_uid
            or target != expected_target
        ):
            raise AuditError("Reviewed Python framework symlink differs")
        try:
            canonical_target = link.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise AuditError("Reviewed Python framework symlink is unsafe") from exc
        expected_canonical = {
            framework / "Python": path,
            framework / "Resources": resources,
            versions / "Current": version,
        }[link]
        if canonical_target != expected_canonical:
            raise AuditError("Reviewed Python framework symlink is unsafe")
        snapshot.append(
            (
                link.relative_to(root).as_posix(),
                info.st_dev,
                info.st_ino,
                info.st_mode,
                info.st_uid,
                info.st_nlink,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
                target,
            )
        )

    try:
        leaf_info = path.lstat()
        canonical_leaf = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AuditError("Reviewed Python framework leaf is missing") from exc
    if (
        not stat.S_ISREG(leaf_info.st_mode)
        or stat.S_ISLNK(leaf_info.st_mode)
        or leaf_info.st_uid != current_uid
        or leaf_info.st_nlink != 1
        or stat.S_IMODE(leaf_info.st_mode) & 0o022
        or canonical_leaf != path
    ):
        raise AuditError("Reviewed Python framework leaf is unsafe")
    snapshot.append(
        (
            relative.as_posix(),
            leaf_info.st_dev,
            leaf_info.st_ino,
            leaf_info.st_mode,
            leaf_info.st_uid,
            leaf_info.st_nlink,
            leaf_info.st_size,
            leaf_info.st_mtime_ns,
            leaf_info.st_ctime_ns,
            sha256_file(path),
        )
    )

    info_plist = resources / "Info.plist"
    try:
        plist_bytes, info = _read_bound_framework_plist(info_plist)
        plist = plistlib.loads(plist_bytes)
    except AuditError:
        raise
    except (plistlib.InvalidFileException, ValueError, RecursionError) as exc:
        raise AuditError("Reviewed Python framework Info.plist is unreadable") from exc
    if (
        not isinstance(plist, dict)
        or plist.get("CFBundleExecutable") != "Python"
        or plist.get("CFBundleName") != "Python"
        or plist.get("CFBundleIdentifier") != "org.python.python"
        or plist.get("CFBundlePackageType") != "FMWK"
    ):
        raise AuditError("Reviewed Python framework Info.plist differs")
    snapshot.append(
        (
            info_plist.relative_to(root).as_posix(),
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_uid,
            info.st_nlink,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
            hashlib.sha256(plist_bytes).hexdigest(),
        )
    )
    return tuple(sorted(snapshot, key=lambda item: str(item[0])))


def _bound_file_identity(info: os.stat_result) -> tuple[Any, ...]:
    return tuple(getattr(info, field) for field in BOUND_FILE_STAT_FIELDS)


def _shared_parent_identity(info: os.stat_result) -> tuple[Any, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
    )


def _bound_directory_snapshot(
    descriptor: int,
    path: Path,
    *,
    expected_uid: int,
    expected_mode: int,
    exact_entries: tuple[str, ...] | None,
    shared_parent: bool,
    error_message: str,
) -> tuple[Any, ...]:
    """Bind a real canonical directory path to its held descriptor."""

    try:
        canonical = path.resolve(strict=True)
        path_before = path.lstat()
        fd_before = os.fstat(descriptor)
        identity = (
            _shared_parent_identity(fd_before)
            if shared_parent
            else _bound_file_identity(fd_before)
        )
        path_identity = (
            _shared_parent_identity(path_before)
            if shared_parent
            else _bound_file_identity(path_before)
        )
        if (
            canonical != path
            or not stat.S_ISDIR(path_before.st_mode)
            or stat.S_ISLNK(path_before.st_mode)
            or not stat.S_ISDIR(fd_before.st_mode)
            or path_before.st_uid != expected_uid
            or fd_before.st_uid != expected_uid
            or stat.S_IMODE(path_before.st_mode) != expected_mode
            or stat.S_IMODE(fd_before.st_mode) != expected_mode
            or path_identity != identity
        ):
            raise AuditError(error_message)
        entries = (
            tuple(sorted(os.listdir(descriptor)))
            if exact_entries is not None
            else None
        )
        fd_after = os.fstat(descriptor)
        path_after = path.lstat()
        after_identity = (
            _shared_parent_identity(fd_after)
            if shared_parent
            else _bound_file_identity(fd_after)
        )
        path_after_identity = (
            _shared_parent_identity(path_after)
            if shared_parent
            else _bound_file_identity(path_after)
        )
        if (
            after_identity != identity
            or path_after_identity != identity
            or (exact_entries is not None and entries != exact_entries)
        ):
            raise AuditError(error_message)
        return (*identity, entries)
    except AuditError:
        raise
    except (OSError, RuntimeError) as exc:
        raise AuditError(error_message) from exc


def _bound_open_regular_file_snapshot(
    descriptor: int,
    path: Path,
    *,
    required_mode: int | None,
    relative_parent_descriptor: int | None,
    relative_name: str | None,
    error_message: str,
) -> tuple[Any, ...]:
    """Hash a held regular-file fd and prove its no-follow path identity."""

    try:
        canonical = path.resolve(strict=True)
        path_before = path.lstat()
        fd_before = os.fstat(descriptor)
        relative_before = (
            os.stat(
                relative_name,
                dir_fd=relative_parent_descriptor,
                follow_symlinks=False,
            )
            if relative_parent_descriptor is not None
            and relative_name is not None
            else path_before
        )
        identity = _bound_file_identity(fd_before)
        mode = stat.S_IMODE(fd_before.st_mode)
        if (
            canonical != path
            or not stat.S_ISREG(path_before.st_mode)
            or stat.S_ISLNK(path_before.st_mode)
            or not stat.S_ISREG(fd_before.st_mode)
            or not stat.S_ISREG(relative_before.st_mode)
            or path_before.st_uid != os.geteuid()
            or fd_before.st_uid != os.geteuid()
            or relative_before.st_uid != os.geteuid()
            or path_before.st_nlink != 1
            or fd_before.st_nlink != 1
            or relative_before.st_nlink != 1
            or fd_before.st_size <= 0
            or fd_before.st_size > MAX_REVIEWED_FRAMEWORK_LEAF_BYTES
            or mode & 0o022
            or (required_mode is not None and mode != required_mode)
            or _bound_file_identity(path_before) != identity
            or _bound_file_identity(relative_before) != identity
        ):
            raise AuditError(error_message)

        digest = hashlib.sha256()
        offset = 0
        while offset <= MAX_REVIEWED_FRAMEWORK_LEAF_BYTES:
            remaining = MAX_REVIEWED_FRAMEWORK_LEAF_BYTES + 1 - offset
            chunk = os.pread(descriptor, min(1024 * 1024, remaining), offset)
            if not chunk:
                break
            digest.update(chunk)
            offset += len(chunk)

        fd_after = os.fstat(descriptor)
        path_after = path.lstat()
        relative_after = (
            os.stat(
                relative_name,
                dir_fd=relative_parent_descriptor,
                follow_symlinks=False,
            )
            if relative_parent_descriptor is not None
            and relative_name is not None
            else path_after
        )
        if (
            offset != fd_before.st_size
            or offset > MAX_REVIEWED_FRAMEWORK_LEAF_BYTES
            or _bound_file_identity(fd_after) != identity
            or _bound_file_identity(path_after) != identity
            or _bound_file_identity(relative_after) != identity
        ):
            raise AuditError(error_message)
        return (*identity, digest.hexdigest())
    except AuditError:
        raise
    except (OSError, RuntimeError) as exc:
        raise AuditError(error_message) from exc


def _open_isolation_parent() -> tuple[Path, int]:
    parent = ISOLATED_FRAMEWORK_LEAF_PARENT
    error_message = "Python framework isolation parent is unsafe"
    descriptor: int | None = None
    try:
        if (
            not parent.is_absolute()
            or parent.resolve(strict=True) != parent
            or any(
                part.casefold().endswith(".framework")
                for part in parent.parts
            )
        ):
            raise AuditError(error_message)
        descriptor = os.open(
            parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        expected_uid = 0 if parent == PRODUCTION_ISOLATION_PARENT else os.geteuid()
        _bound_directory_snapshot(
            descriptor,
            parent,
            expected_uid=expected_uid,
            expected_mode=0o1777,
            exact_entries=None,
            shared_parent=True,
            error_message=error_message,
        )
        return parent, descriptor
    except AuditError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except (OSError, RuntimeError) as exc:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise AuditError(error_message) from exc


def _cleanup_isolated_framework_leaf(
    *,
    parent: Path | None,
    child: Path | None,
    parent_descriptor: int | None,
    child_descriptor: int | None,
    source_descriptor: int | None,
    copy_descriptor: int | None,
    child_name: str | None,
    copy_created: bool,
) -> None:
    """Remove only the fixed copy and exact private child via held dirfds."""

    failed = False
    if child_descriptor is None:
        failed = (
            child is not None
            or child_name is not None
            or copy_created
            or copy_descriptor is not None
        )
        for descriptor in (
            copy_descriptor,
            source_descriptor,
            parent_descriptor,
        ):
            if descriptor is None:
                continue
            try:
                os.close(descriptor)
            except OSError:
                failed = True
        if failed:
            raise AuditError("Python framework isolation cleanup failed")
        return

    safe_to_remove = False
    expected_parent_uid = (
        0 if parent == PRODUCTION_ISOLATION_PARENT else os.geteuid()
    )
    try:
        if (
            parent is None
            or child is None
            or parent_descriptor is None
            or child_descriptor is None
            or child_name is None
            or child != parent / child_name
            or re.fullmatch(
                rf"{re.escape(ISOLATED_FRAMEWORK_LEAF_TEMP_PREFIX)}[0-9a-f]{{32}}",
                child_name,
            )
            is None
            or any(
                part.casefold().endswith(".framework")
                for part in child.parts
            )
        ):
            raise AuditError("Python framework isolation cleanup failed")
        _bound_directory_snapshot(
            parent_descriptor,
            parent,
            expected_uid=expected_parent_uid,
            expected_mode=0o1777,
            exact_entries=None,
            shared_parent=True,
            error_message="Python framework isolation cleanup failed",
        )
        child_fd_info = os.fstat(child_descriptor)
        child_relative_info = os.stat(
            child_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        child_path_info = child.lstat()
        child_stable_identity = (
            child_fd_info.st_dev,
            child_fd_info.st_ino,
            child_fd_info.st_mode,
            child_fd_info.st_uid,
            child_fd_info.st_gid,
            child_fd_info.st_nlink,
        )
        if (
            not stat.S_ISDIR(child_fd_info.st_mode)
            or stat.S_ISLNK(child_relative_info.st_mode)
            or stat.S_ISLNK(child_path_info.st_mode)
            or child_fd_info.st_uid != os.geteuid()
            or stat.S_IMODE(child_fd_info.st_mode) != 0o700
            or child_stable_identity
            != (
                child_relative_info.st_dev,
                child_relative_info.st_ino,
                child_relative_info.st_mode,
                child_relative_info.st_uid,
                child_relative_info.st_gid,
                child_relative_info.st_nlink,
            )
            or child_stable_identity
            != (
                child_path_info.st_dev,
                child_path_info.st_ino,
                child_path_info.st_mode,
                child_path_info.st_uid,
                child_path_info.st_gid,
                child_path_info.st_nlink,
            )
        ):
            raise AuditError("Python framework isolation cleanup failed")
        expected_entries = ("Python",) if copy_created else ()
        if tuple(sorted(os.listdir(child_descriptor))) != expected_entries:
            raise AuditError("Python framework isolation cleanup failed")
        if copy_created:
            if copy_descriptor is None:
                raise AuditError("Python framework isolation cleanup failed")
            copy_fd_info = os.fstat(copy_descriptor)
            copy_relative_info = os.stat(
                "Python",
                dir_fd=child_descriptor,
                follow_symlinks=False,
            )
            copy_path_info = (child / "Python").lstat()
            copy_identity = _bound_file_identity(copy_fd_info)
            if (
                not stat.S_ISREG(copy_fd_info.st_mode)
                or stat.S_ISLNK(copy_relative_info.st_mode)
                or stat.S_ISLNK(copy_path_info.st_mode)
                or copy_fd_info.st_uid != os.geteuid()
                or copy_fd_info.st_nlink != 1
                or stat.S_IMODE(copy_fd_info.st_mode) != 0o500
                or _bound_file_identity(copy_relative_info) != copy_identity
                or _bound_file_identity(copy_path_info) != copy_identity
            ):
                raise AuditError("Python framework isolation cleanup failed")
        safe_to_remove = True
    except (AuditError, OSError, RuntimeError):
        failed = True

    if safe_to_remove and copy_created:
        try:
            os.unlink("Python", dir_fd=child_descriptor)
        except OSError:
            failed = True
    for descriptor in (copy_descriptor, source_descriptor):
        if descriptor is None:
            continue
        try:
            os.close(descriptor)
        except OSError:
            failed = True
    if safe_to_remove and child_descriptor is not None:
        try:
            if os.listdir(child_descriptor):
                failed = True
        except OSError:
            failed = True
    if (
        safe_to_remove
        and parent_descriptor is not None
        and child_descriptor is not None
        and child_name is not None
    ):
        try:
            os.rmdir(child_name, dir_fd=parent_descriptor)
        except OSError:
            failed = True
        else:
            try:
                os.stat(
                    child_name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            except OSError:
                failed = True
            else:
                failed = True
            try:
                _bound_directory_snapshot(
                    parent_descriptor,
                    parent,
                    expected_uid=expected_parent_uid,
                    expected_mode=0o1777,
                    exact_entries=None,
                    shared_parent=True,
                    error_message="Python framework isolation cleanup failed",
                )
            except AuditError:
                failed = True
    if child_descriptor is not None:
        try:
            os.close(child_descriptor)
        except OSError:
            failed = True
    if parent_descriptor is not None:
        try:
            os.close(parent_descriptor)
        except OSError:
            failed = True
    if failed:
        raise AuditError("Python framework isolation cleanup failed")


def _prepare_isolated_framework_leaf(source: Path) -> _IsolatedFrameworkLeaf:
    """Create one byte-identical private copy while retaining every bound fd."""

    parent: Path | None = None
    child: Path | None = None
    child_name: str | None = None
    parent_descriptor: int | None = None
    child_descriptor: int | None = None
    source_descriptor: int | None = None
    copy_descriptor: int | None = None
    copy_created = False
    error_message = "Reviewed Python framework leaf could not be isolated"
    try:
        parent, parent_descriptor = _open_isolation_parent()
        for _attempt in range(8):
            candidate = (
                f"{ISOLATED_FRAMEWORK_LEAF_TEMP_PREFIX}{secrets.token_hex(16)}"
            )
            try:
                os.mkdir(candidate, mode=0o700, dir_fd=parent_descriptor)
            except FileExistsError:
                continue
            child_name = candidate
            break
        if child_name is None:
            raise AuditError(error_message)
        child = parent / child_name
        child_descriptor = os.open(
            child_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_descriptor,
        )
        os.fchmod(child_descriptor, 0o700)
        _bound_directory_snapshot(
            child_descriptor,
            child,
            expected_uid=os.geteuid(),
            expected_mode=0o700,
            exact_entries=(),
            shared_parent=False,
            error_message=error_message,
        )

        source_descriptor = os.open(
            source,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        source_snapshot = _bound_open_regular_file_snapshot(
            source_descriptor,
            source,
            required_mode=None,
            relative_parent_descriptor=None,
            relative_name=None,
            error_message=error_message,
        )

        copy_descriptor = os.open(
            "Python",
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | os.O_CLOEXEC
            | os.O_NOFOLLOW,
            0o500,
            dir_fd=child_descriptor,
        )
        copy_created = True

        digest = hashlib.sha256()
        bytes_copied = 0
        while True:
            chunk = os.read(source_descriptor, 1024 * 1024)
            if not chunk:
                break
            bytes_copied += len(chunk)
            if bytes_copied > MAX_REVIEWED_FRAMEWORK_LEAF_BYTES:
                raise AuditError(error_message)
            digest.update(chunk)
            remaining = memoryview(chunk)
            while remaining:
                written = os.write(copy_descriptor, remaining)
                if written <= 0:
                    raise AuditError(error_message)
                remaining = remaining[written:]
        os.fchmod(copy_descriptor, 0o500)
        os.fsync(copy_descriptor)
        copy = child / "Python"
        source_after_copy = _bound_open_regular_file_snapshot(
            source_descriptor,
            source,
            required_mode=None,
            relative_parent_descriptor=None,
            relative_name=None,
            error_message=error_message,
        )
        copy_snapshot = _bound_open_regular_file_snapshot(
            copy_descriptor,
            copy,
            required_mode=0o500,
            relative_parent_descriptor=child_descriptor,
            relative_name="Python",
            error_message=error_message,
        )
        if (
            source_after_copy != source_snapshot
            or source_snapshot[-1] != digest.hexdigest()
            or copy_snapshot[-1] != source_snapshot[-1]
            or copy_snapshot[:2] == source_snapshot[:2]
            or bytes_copied != source_snapshot[6]
        ):
            raise AuditError(error_message)
        parent_snapshot = _bound_directory_snapshot(
            parent_descriptor,
            parent,
            expected_uid=(
                0 if parent == PRODUCTION_ISOLATION_PARENT else os.geteuid()
            ),
            expected_mode=0o1777,
            exact_entries=None,
            shared_parent=True,
            error_message=error_message,
        )
        child_snapshot = _bound_directory_snapshot(
            child_descriptor,
            child,
            expected_uid=os.geteuid(),
            expected_mode=0o700,
            exact_entries=("Python",),
            shared_parent=False,
            error_message=error_message,
        )
        return _IsolatedFrameworkLeaf(
            parent=parent,
            child=child,
            child_name=child_name,
            source=source,
            copy=copy,
            parent_descriptor=parent_descriptor,
            child_descriptor=child_descriptor,
            source_descriptor=source_descriptor,
            copy_descriptor=copy_descriptor,
            parent_snapshot=parent_snapshot,
            child_snapshot=child_snapshot,
            source_snapshot=source_snapshot,
            copy_snapshot=copy_snapshot,
        )
    except AuditError:
        _cleanup_isolated_framework_leaf(
            parent=parent,
            child=child,
            parent_descriptor=parent_descriptor,
            child_descriptor=child_descriptor,
            source_descriptor=source_descriptor,
            copy_descriptor=copy_descriptor,
            child_name=child_name,
            copy_created=copy_created,
        )
        raise
    except (OSError, RuntimeError) as exc:
        try:
            _cleanup_isolated_framework_leaf(
                parent=parent,
                child=child,
                parent_descriptor=parent_descriptor,
                child_descriptor=child_descriptor,
                source_descriptor=source_descriptor,
                copy_descriptor=copy_descriptor,
                child_name=child_name,
                copy_created=copy_created,
            )
        except AuditError as cleanup_exc:
            raise cleanup_exc from exc
        raise AuditError(error_message) from exc


def _validate_isolated_framework_leaf_state(
    isolation: _IsolatedFrameworkLeaf,
) -> None:
    error_message = "Isolated Python framework leaf changed during verification"
    expected_parent_uid = (
        0
        if isolation.parent == PRODUCTION_ISOLATION_PARENT
        else os.geteuid()
    )
    if _bound_directory_snapshot(
        isolation.parent_descriptor,
        isolation.parent,
        expected_uid=expected_parent_uid,
        expected_mode=0o1777,
        exact_entries=None,
        shared_parent=True,
        error_message=error_message,
    ) != isolation.parent_snapshot:
        raise AuditError(error_message)
    if _bound_directory_snapshot(
        isolation.child_descriptor,
        isolation.child,
        expected_uid=os.geteuid(),
        expected_mode=0o700,
        exact_entries=("Python",),
        shared_parent=False,
        error_message=error_message,
    ) != isolation.child_snapshot:
        raise AuditError(error_message)
    source_snapshot = _bound_open_regular_file_snapshot(
        isolation.source_descriptor,
        isolation.source,
        required_mode=None,
        relative_parent_descriptor=None,
        relative_name=None,
        error_message="Reviewed Python framework changed during verification",
    )
    copy_snapshot = _bound_open_regular_file_snapshot(
        isolation.copy_descriptor,
        isolation.copy,
        required_mode=0o500,
        relative_parent_descriptor=isolation.child_descriptor,
        relative_name="Python",
        error_message=error_message,
    )
    if source_snapshot != isolation.source_snapshot:
        raise AuditError("Reviewed Python framework changed during verification")
    if (
        copy_snapshot != isolation.copy_snapshot
        or copy_snapshot[-1] != source_snapshot[-1]
        or copy_snapshot[:2] == source_snapshot[:2]
    ):
        raise AuditError(error_message)


def _verify_code_signature(root: Path, path: Path) -> None:
    framework_snapshot = _validate_reviewed_python_framework(root, path)
    if framework_snapshot is not None:
        isolation = _prepare_isolated_framework_leaf(path)
        try:
            _run_native_tool(
                (
                    "/usr/bin/codesign",
                    "--verify",
                    "--strict",
                    str(isolation.copy),
                ),
                isolated_framework_leaf=isolation,
            )
            _validate_isolated_framework_leaf_state(isolation)
            if (
                _validate_reviewed_python_framework(root, path)
                != framework_snapshot
            ):
                raise AuditError(
                    "Reviewed Python framework changed during verification"
                )
        finally:
            _cleanup_isolated_framework_leaf(
                parent=isolation.parent,
                child=isolation.child,
                parent_descriptor=isolation.parent_descriptor,
                child_descriptor=isolation.child_descriptor,
                source_descriptor=isolation.source_descriptor,
                copy_descriptor=isolation.copy_descriptor,
                child_name=isolation.child_name,
                copy_created=True,
            )
        return
    _run_native_tool(("/usr/bin/codesign", "--verify", "--strict", str(path)))


def scan_macho_inventory(root: Path) -> list[dict[str, Any]]:
    """Inspect every Mach-O using platform tools and return canonical evidence."""

    if platform.system() != "Darwin":
        raise AuditError("Real Mach-O inspection requires Darwin")
    root = root.resolve()
    records: list[dict[str, Any]] = []
    for path in sorted(
        (candidate for candidate in root.rglob("*") if candidate.is_file()),
        key=lambda candidate: candidate.relative_to(root).as_posix(),
    ):
        if path.is_symlink() or not is_macho(path):
            continue
        load_commands = _run_native_tool(("/usr/bin/otool", "-l", str(path)))
        native_platform, minimum_macos = _parse_otool_build_target(load_commands)
        _verify_code_signature(root, path)
        record: dict[str, Any] = {
            "path": _relative_name(root, path),
            "architectures": _parse_lipo_architectures(
                _run_native_tool(("/usr/bin/lipo", "-archs", str(path)))
            ),
            "dylibs": _parse_otool_dependencies(
                _run_native_tool(("/usr/bin/otool", "-L", str(path)))
            ),
            "rpaths": _parse_otool_rpaths(load_commands),
            "platform": native_platform,
            "minimumMacosVersion": minimum_macos,
            "codeSignature": "valid",
        }
        install_name = _parse_otool_install_name(
            _run_native_tool(("/usr/bin/otool", "-D", str(path)))
        )
        if install_name is not None:
            record["installName"] = install_name
        records.append(record)
    return records


def _safe_manifest_path(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str):
        raise AuditError(f"{label} path must be a string")
    pure = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or ".." in pure.parts
        or "\\" in value
        or "\x00" in value
    ):
        raise AuditError(f"{label} path is unsafe")
    return pure


def _expanded_rpath(root: Path, owner: Path, rpath: str) -> Path:
    if rpath == "@loader_path":
        candidate = owner.parent
    elif rpath.startswith("@loader_path/"):
        candidate = owner.parent / rpath[len("@loader_path/") :]
    elif rpath == "@executable_path":
        candidate = root
    elif rpath.startswith("@executable_path/"):
        candidate = root / rpath[len("@executable_path/") :]
    else:
        raise AuditError("Mach-O contains an absolute or unsupported RPATH")
    resolved = candidate.resolve(strict=False)
    if not _contained(root, resolved):
        raise AuditError("Mach-O RPATH escapes the sidecar")
    return resolved


def _resolve_dependency(
    root: Path,
    owner: Path,
    dependency: str,
    rpaths: Sequence[str],
) -> Path | None:
    if dependency.startswith(SYSTEM_DYLIB_PREFIXES):
        return None
    if dependency.startswith("@loader_path/"):
        candidates = [owner.parent / dependency[len("@loader_path/") :]]
    elif dependency.startswith("@executable_path/"):
        candidates = [root / dependency[len("@executable_path/") :]]
    elif dependency.startswith("@rpath/"):
        suffix = dependency[len("@rpath/") :]
        candidates = [
            _expanded_rpath(root, owner, rpath) / suffix for rpath in rpaths
        ]
    else:
        if dependency.startswith("/Library/Frameworks/Python.framework/"):
            raise AuditError("Mach-O depends on an external Python framework")
        if dependency.startswith("/opt/homebrew/"):
            raise AuditError("Mach-O depends on Homebrew")
        if dependency.startswith("/usr/local/"):
            raise AuditError("Mach-O depends on /usr/local")
        if dependency.startswith("/"):
            raise AuditError("Mach-O contains a non-system absolute dependency")
        raise AuditError("Mach-O contains an unsupported dependency reference")

    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if _contained(root, resolved):
            return resolved
    raise AuditError("Mach-O dependency does not resolve inside the sidecar")


def validate_native_inventory(
    root: Path, records: Sequence[Mapping[str, Any]]
) -> None:
    """Validate arm64 architecture, RPATHs, install names and dylib closure."""

    root = root.resolve()
    if not records:
        raise AuditError("Sidecar contains no audited Mach-O files")
    native_paths: set[str] = set()
    canonical_paths: dict[str, str] = {}
    for record in records:
        pure = _safe_manifest_path(record.get("path"), "native")
        value = pure.as_posix()
        if value in native_paths:
            raise AuditError("Native inventory contains duplicate paths")
        native_paths.add(value)
        path = root / pure
        try:
            info = path.lstat()
        except OSError as exc:
            raise AuditError("Native inventory references a missing file") from exc
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise AuditError("Native inventory references a non-regular file")
        try:
            canonical_paths[value] = path.resolve(strict=True).relative_to(root).as_posix()
        except (OSError, RuntimeError, ValueError) as exc:
            raise AuditError("Native inventory path escapes the sidecar") from exc
        if record.get("architectures") != ["arm64"]:
            raise AuditError("Every Mach-O must be arm64-only")
        if record.get("platform") != "macos":
            raise AuditError("Every Mach-O must target macOS")
        minimum_macos = record.get("minimumMacosVersion")
        if (
            not isinstance(minimum_macos, str)
            or re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", minimum_macos) is None
            or tuple(
                ([
                    *[int(part) for part in minimum_macos.split(".")],
                    0,
                    0,
                ])[:3]
            )
            > (14, 0, 0)
        ):
            raise AuditError("Mach-O minimum macOS exceeds the reviewed target")
        if record.get("codeSignature") != "valid":
            raise AuditError("Every Mach-O must have a valid code signature")
        dylibs = record.get("dylibs")
        rpaths = record.get("rpaths")
        if not isinstance(dylibs, list) or not all(
            isinstance(item, str) and item for item in dylibs
        ):
            raise AuditError("Native dependency evidence is malformed")
        if not isinstance(rpaths, list) or not all(
            isinstance(item, str) and item for item in rpaths
        ):
            raise AuditError("Native RPATH evidence is malformed")
        raw_values = [*dylibs, *rpaths]
        install_name = record.get("installName")
        if install_name is not None:
            if not isinstance(install_name, str) or not install_name:
                raise AuditError("Mach-O install name is malformed")
            raw_values.append(install_name)
            if install_name.startswith("/Library/Frameworks/Python.framework/"):
                raise AuditError("Mach-O install name uses an external Python framework")
            if install_name.startswith("/") or (
                not install_name.startswith(
                    ("@rpath/", "@loader_path/", "@executable_path/")
                )
            ):
                raise AuditError("Mach-O install name is not bundle-relative")
        if any(
            fragment in value
            for value in raw_values
            for fragment in FORBIDDEN_PATH_FRAGMENTS
        ):
            if any("/opt/homebrew/" in value for value in raw_values):
                raise AuditError("Mach-O evidence contains Homebrew")
            if any(
                "/Library/Frameworks/Python.framework/" in value
                for value in raw_values
            ):
                raise AuditError("Mach-O evidence contains an external Python framework")
            raise AuditError("Mach-O evidence contains a forbidden host path")
        owner = path
        for rpath in rpaths:
            _expanded_rpath(root, owner, rpath)

    resolved_native_paths = set(canonical_paths.values())
    executable_rpaths: Sequence[str] = ()
    for record in records:
        if record.get("path") == EXPECTED_EXECUTABLE:
            candidate = record.get("rpaths")
            if isinstance(candidate, list):
                executable_rpaths = candidate
            break
    for record in records:
        owner = root / _safe_manifest_path(record.get("path"), "native")
        for dependency in record["dylibs"]:
            resolved = _resolve_dependency(
                root,
                owner,
                dependency,
                tuple(dict.fromkeys([*record["rpaths"], *executable_rpaths])),
            )
            if resolved is None:
                continue
            relative = resolved.relative_to(root).as_posix()
            if relative not in resolved_native_paths:
                raise AuditError("Mach-O dependency is absent from native inventory")


def _canonical_native(
    records: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for record in records:
        item: dict[str, Any] = {
            "path": record.get("path"),
            "architectures": sorted(record.get("architectures", [])),
            "dylibs": sorted(record.get("dylibs", [])),
            "rpaths": sorted(record.get("rpaths", [])),
            "platform": record.get("platform"),
            "minimumMacosVersion": record.get("minimumMacosVersion"),
            "codeSignature": record.get("codeSignature"),
        }
        if record.get("installName") is not None:
            item["installName"] = record.get("installName")
        normalized.append(item)
    return sorted(normalized, key=lambda item: str(item["path"]))


def _require_relative_artifact(root: Path, value: Any, label: str) -> Path:
    pure = _safe_manifest_path(value, label)
    artifact = root / pure
    try:
        info = artifact.lstat()
    except OSError as exc:
        raise AuditError(f"Manifest {label} artifact is missing") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise AuditError(f"Manifest {label} artifact is not a regular file")
    return artifact


def _validate_python_provenance(
    python: Mapping[str, Any], toolchain: Mapping[str, Any]
) -> None:
    expected_python = cast_mapping(toolchain.get("python"), "toolchain Python")
    distribution = cast_mapping(
        expected_python.get("distribution"), "toolchain Python distribution"
    )
    expected = {
        "implementation": expected_python.get("implementation"),
        "version": expected_python.get("version"),
        "installRoot": expected_python.get("installRoot"),
        "provider": distribution.get("provider"),
        "releaseTag": distribution.get("releaseTag"),
        "archiveName": distribution.get("archiveName"),
        "archiveSource": distribution.get("archiveSource"),
        "archiveSha256": distribution.get("archiveSha256"),
        "installerPackageName": distribution.get("installerPackageName"),
        "installerPackageSha256": distribution.get(
            "installerPackageSha256"
        ),
        "hashManifestName": distribution.get("hashManifestName"),
        "hashManifestSource": distribution.get("hashManifestSource"),
        "hashManifestSha256": distribution.get("hashManifestSha256"),
    }
    if any(python.get(key) != value for key, value in expected.items()):
        raise AuditError("Manifest Python provenance differs from the reviewed lock")
    if re.fullmatch(
        r"[0-9a-f]{64}", str(python.get("installRootFingerprintSha256", ""))
    ) is None:
        raise AuditError("Manifest installed Python fingerprint is invalid")


def _validate_input_digests(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise AuditError("Manifest build input digests are missing")
    expected = critical_input_digests()
    if dict(value) != expected:
        raise AuditError("Manifest critical input digests are stale or incomplete")


def _validate_manifest_shape(manifest: Mapping[str, Any]) -> None:
    if manifest.get("$schema") != "python-sidecar-build-manifest.schema.json":
        raise AuditError("Unexpected Python sidecar manifest schema identifier")
    if manifest.get("schemaVersion") != MANIFEST_SCHEMA_VERSION:
        raise AuditError("Unsupported Python sidecar build manifest schema")
    if manifest.get("kind") != "local-context-forge-python-sidecar":
        raise AuditError("Unexpected Python sidecar manifest kind")
    if manifest.get("entrypoint") != EXPECTED_EXECUTABLE:
        raise AuditError("Manifest entrypoint is not the reviewed executable")

    versions = _load_json(VERSION_FILE, "Canonical runtime versions")
    expected_product = {
        "appVersion": versions.get("productVersion"),
        "pythonDistributionVersion": versions.get("pythonDistributionVersion"),
        "desktopProtocol": versions.get("desktopProtocol"),
        "databaseSchema": versions.get("databaseSchema"),
    }
    if manifest.get("product") != expected_product:
        raise AuditError("Manifest product/protocol/schema versions are not canonical")

    toolchain = _load_json(TOOLCHAIN_LOCK, "Python toolchain lock")
    target = cast_mapping(toolchain.get("target"), "toolchain target")
    if manifest.get("target") != {
        "os": target.get("os"),
        "architecture": target.get("architecture"),
    }:
        raise AuditError("Manifest target differs from the reviewed lock")

    build = cast_mapping(manifest.get("build"), "manifest build provenance")
    commit = build.get("repositoryCommit")
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise AuditError("Manifest repository commit is invalid")
    epoch = build.get("sourceDateEpoch")
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 100_000_000:
        raise AuditError("Manifest source date epoch is invalid")
    if (
        not isinstance(build.get("runnerImageVersion"), str)
        or re.fullmatch(
            r"[0-9]{8}\.[0-9]+\.[0-9]+", build["runnerImageVersion"]
        )
        is None
        or not isinstance(build.get("xcodeVersion"), str)
        or not build["xcodeVersion"]
        or not isinstance(build.get("sdkVersion"), str)
        or not build["sdkVersion"]
    ):
        raise AuditError("Manifest runner/Xcode/SDK provenance is incomplete")
    tools = cast_mapping(toolchain.get("tools"), "toolchain tools")
    pinned = {
        "runnerImage": target.get("runnerLabel"),
        "macosDeploymentTarget": target.get("deploymentTarget"),
        "uvVersion": tools.get("uv"),
        "pyinstallerVersion": tools.get("pyinstaller"),
        "pyinstallerHooksContribVersion": tools.get(
            "pyinstallerHooksContrib"
        ),
    }
    if any(build.get(key) != value for key, value in pinned.items()):
        raise AuditError("Manifest build environment differs from reviewed pins")
    _validate_python_provenance(
        cast_mapping(build.get("python"), "manifest Python provenance"),
        toolchain,
    )
    _validate_input_digests(build.get("inputDigests"))


def _validate_components(root: Path, manifest: Mapping[str, Any]) -> None:
    components = manifest.get("components")
    if not isinstance(components, list):
        raise AuditError("Manifest component inventory is missing")
    by_name: dict[str, Mapping[str, Any]] = {}
    for component in components:
        if not isinstance(component, Mapping):
            raise AuditError("Manifest component is malformed")
        name = component.get("name")
        if not isinstance(name, str) or not name or name in by_name:
            raise AuditError("Manifest component name is missing or duplicated")
        if (
            not isinstance(component.get("version"), str)
            or not component["version"]
            or component.get("scope") not in {"runtime", "build-tool"}
            or not isinstance(component.get("licenseExpression"), str)
            or not component["licenseExpression"]
        ):
            raise AuditError("Manifest component metadata is incomplete")
        licenses = component.get("licenseFiles")
        if not isinstance(licenses, list) or not licenses:
            raise AuditError("Every component must have license evidence")
        for license_path in licenses:
            _require_relative_artifact(root, license_path, "license")
        by_name[name] = component

    if REQUIRED_RUNTIME_COMPONENTS - set(by_name):
        raise AuditError("Manifest omits a required runtime component")
    if any(
        by_name[name].get("scope") != "runtime"
        for name in REQUIRED_RUNTIME_COMPONENTS
    ):
        raise AuditError("A required runtime component has the wrong scope")
    if REQUIRED_BUILD_TOOLS - set(by_name) or any(
        by_name[name].get("scope") != "build-tool"
        for name in REQUIRED_BUILD_TOOLS
    ):
        raise AuditError("Manifest omits a required build-tool component")
    if by_name["cpython"].get("version") != "3.13.14":
        raise AuditError("CPython component differs from the reviewed pin")
    if by_name["dulwich"].get("version") != "1.2.11":
        raise AuditError("Dulwich component differs from the reviewed pin")
    if by_name["pyinstaller"].get("version") != "6.21.0":
        raise AuditError("PyInstaller component differs from the reviewed pin")

    properties = by_name["certifi"].get("properties")
    if not isinstance(properties, Mapping):
        raise AuditError("Certifi component omits CA bundle evidence")
    ca_bundle = _require_relative_artifact(
        root, properties.get("caBundlePath"), "certifi CA bundle"
    )
    if properties.get("caBundleSha256") != sha256_file(ca_bundle):
        raise AuditError("Certifi CA bundle digest does not match manifest")


def _validate_sbom(root: Path, manifest: Mapping[str, Any]) -> None:
    artifacts = cast_mapping(manifest.get("artifacts"), "manifest artifacts")
    sbom_path = _require_relative_artifact(
        root, artifacts.get("spdxSbom"), "SBOM"
    )
    _require_relative_artifact(
        root, artifacts.get("thirdPartyNotices"), "third-party notices"
    )
    license_directory = root / _safe_manifest_path(
        artifacts.get("licensesDirectory"), "licenses directory"
    )
    try:
        license_info = license_directory.lstat()
    except OSError as exc:
        raise AuditError("Manifest licenses directory is missing") from exc
    if not stat.S_ISDIR(license_info.st_mode) or stat.S_ISLNK(
        license_info.st_mode
    ):
        raise AuditError("Manifest licenses directory is not a real directory")
    sbom = _load_json(sbom_path, "SPDX SBOM")
    if (
        sbom.get("spdxVersion") != "SPDX-2.3"
        or sbom.get("dataLicense") != "CC0-1.0"
        or not isinstance(sbom.get("packages"), list)
    ):
        raise AuditError("SPDX SBOM has an unsupported or incomplete shape")
    sbom_names = {
        package.get("name")
        for package in sbom["packages"]
        if isinstance(package, Mapping)
    }
    component_names = {
        component.get("name")
        for component in manifest.get("components", [])
        if isinstance(component, Mapping)
    }
    if not component_names.issubset(sbom_names):
        raise AuditError("SPDX SBOM does not cover every manifest component")


def load_manifest(path: Path) -> dict[str, Any]:
    return _load_json(path, "Python sidecar build manifest")


def audit_bundle(
    root: Path,
    *,
    native_scanner: NativeScanner | None = None,
) -> dict[str, int]:
    """Validate a staged bundle and return only non-sensitive summary counts."""

    try:
        root_info = root.lstat()
    except OSError as exc:
        raise AuditError("Sidecar root must be a real directory") from exc
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise AuditError("Sidecar root must be a real directory")
    root = root.resolve()

    executable = root / EXPECTED_EXECUTABLE
    try:
        executable_info = executable.lstat()
    except OSError as exc:
        raise AuditError("Sidecar entrypoint is missing") from exc
    if (
        not stat.S_ISREG(executable_info.st_mode)
        or stat.S_ISLNK(executable_info.st_mode)
        or not stat.S_IMODE(executable_info.st_mode) & 0o111
    ):
        raise AuditError("Sidecar entrypoint must be a regular executable")

    manifest_path = root / MANIFEST_NAME
    try:
        manifest_info = manifest_path.lstat()
    except OSError as exc:
        raise AuditError("Python sidecar build manifest is missing") from exc
    if not stat.S_ISREG(manifest_info.st_mode) or stat.S_ISLNK(
        manifest_info.st_mode
    ):
        raise AuditError("Python sidecar build manifest is not a regular file")
    manifest = load_manifest(manifest_path)
    _validate_manifest_shape(manifest)

    recorded_files = manifest.get("files")
    if not isinstance(recorded_files, list):
        raise AuditError("Manifest file inventory is missing")
    actual_files = build_file_inventory(root)
    if recorded_files != actual_files:
        raise AuditError("Staged sidecar differs from its exact file inventory")

    scanner = native_scanner or scan_macho_inventory
    native = scanner(root)
    validate_native_inventory(root, native)
    recorded_native = manifest.get("native")
    if not isinstance(recorded_native, list):
        raise AuditError("Manifest native inventory is missing")
    if _canonical_native(recorded_native) != _canonical_native(native):
        raise AuditError("Staged Mach-O inventory differs from the manifest")
    if EXPECTED_EXECUTABLE not in {
        record.get("path")
        for record in recorded_native
        if isinstance(record, Mapping)
    }:
        raise AuditError("Native inventory omits the sidecar entrypoint")

    audit = cast_mapping(manifest.get("audit"), "manifest audit")
    if (
        audit.get("status") != "pass"
        or audit.get("policyVersion") != 1
        or audit.get("frozenSmoke") != EXPECTED_FROZEN_SMOKE
    ):
        raise AuditError("Manifest does not contain complete passing audit evidence")
    if audit.get("normalizedInventorySha256") != normalized_inventory_sha256(
        recorded_files, recorded_native
    ):
        raise AuditError("Manifest normalized inventory digest does not match")

    _validate_components(root, manifest)
    _validate_sbom(root, manifest)
    return {
        "files": len(actual_files),
        "nativeFiles": len(native),
        "components": len(manifest["components"]),
    }


def reseal_manifest(root: Path) -> dict[str, int]:
    """Refresh inventory evidence after reviewed outer certificate signing."""

    try:
        root_info = root.lstat()
    except OSError as exc:
        raise AuditError("Sidecar root must be a real directory") from exc
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise AuditError("Sidecar root must be a real directory")
    root = root.resolve()
    manifest_path = root / MANIFEST_NAME
    manifest = load_manifest(manifest_path)
    _validate_manifest_shape(manifest)
    files = build_file_inventory(root)
    native = scan_macho_inventory(root)
    validate_native_inventory(root, native)
    if EXPECTED_EXECUTABLE not in {
        record.get("path")
        for record in native
        if isinstance(record, Mapping)
    }:
        raise AuditError("Native inventory omits the sidecar entrypoint")
    manifest["files"] = files
    manifest["native"] = native
    audit = manifest.get("audit")
    if not isinstance(audit, dict):
        raise AuditError("manifest audit must be an object")
    audit["normalizedInventorySha256"] = normalized_inventory_sha256(
        files, native
    )
    encoded = canonical_json_bytes(manifest) + b"\n"
    temporary = manifest_path.with_name(f".{MANIFEST_NAME}.reseal")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, manifest_path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise AuditError("Unable to reseal sidecar manifest") from exc
    return {
        "files": len(files),
        "nativeFiles": len(native),
        "components": len(manifest["components"]),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit a darwin-arm64 Python sidecar staging directory"
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        default=Path("desktop/generated/sidecar"),
        help="staged PyInstaller onedir root",
    )
    parser.add_argument(
        "--reseal-manifest",
        action="store_true",
        help=(
            "refresh file/native inventory after reviewed certificate signing"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        summary = (
            reseal_manifest(arguments.bundle)
            if arguments.reseal_manifest
            else audit_bundle(arguments.bundle)
        )
    except AuditError as exc:
        print(f"python-sidecar audit failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

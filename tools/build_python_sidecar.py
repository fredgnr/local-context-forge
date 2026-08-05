#!/usr/bin/env python3
"""Build the reviewed darwin-arm64 Python sidecar.

The build has two deliberately separate modes:

* ``--verify-source-only`` verifies the pinned actions/python-versions archive,
  its independently pinned hash manifest, and the embedded Python.org package.
  This mode is portable and does not install or execute anything from the
  archive.
* the default mode is a macOS-arm64 release gate. It binds the running Python
  to the reviewed framework install, checks the GitHub runner and dependency
  locks, builds a PyInstaller onedir, runs the frozen UDS lifecycle under a
  hostile PATH, audits every byte/native dependency, then atomically publishes
  the staging directory.

No code from the downloaded archive is ever executed by this script.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import errno
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import secrets
import shutil
import socket
import sqlite3
import ssl
import stat
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import threading
import time
import tomllib
import uuid
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = Path(__file__).resolve().parent
if str(TOOLS_ROOT) not in sys.path:
    # ``-I`` intentionally removes the script directory. Re-add only this
    # reviewed repository path so the paired auditor can be imported.
    sys.path.insert(0, str(TOOLS_ROOT))
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
PACKAGING_ROOT = BACKEND_ROOT / "packaging"
TOOLCHAIN_LOCK = PACKAGING_ROOT / "python-sidecar-toolchain.lock.json"
BUILD_REQUIREMENTS_LOCK = PACKAGING_ROOT / "build-requirements.lock"
LICENSE_POLICY = PACKAGING_ROOT / "license-policy.json"
MISSING_IMPORTS_ALLOWLIST = PACKAGING_ROOT / "missing-imports-allowlist.json"
VERSION_FILE = REPOSITORY_ROOT / "runtime" / "version.json"
SPEC_FILE = PACKAGING_ROOT / "lcf_sidecar.spec"
DEFAULT_STAGING = REPOSITORY_ROOT / "desktop" / "generated" / "sidecar"
DEFAULT_EVIDENCE = (
    REPOSITORY_ROOT / "desktop" / "generated" / "python-sidecar-evidence"
)
MAX_SOURCE_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_HASH_MANIFEST_BYTES = 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 384 * 1024 * 1024
MAX_SMOKE_BROKER_REQUEST_BYTES = 262_144
MAX_SMOKE_BROKER_COLLECTIONS = 256
MAX_SMOKE_BROKER_REVISION = 2**53 - 1
MAX_FROZEN_START_LOG_BYTES = 1024 * 1024
MAX_FROZEN_UDS_PATH_BYTES = 100
FROZEN_UDS_CHECKS = frozenset(
    {
        "handshake",
        "health",
        "library-create",
        "library-ingest",
        "job-status",
        "pages",
        "lint",
        "library-publish",
        "post-publish-health",
    }
)
EXPECTED_MISSING_IMPORT_PATTERN = re.compile(
    r"^missing module named ['\"]?([^ '\"(),]+)['\"]?"
)
SAFE_MISSING_IMPORT_NAME_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_.]{0,127}$"
)
WHEEL_REQUIREMENT_PATTERN = re.compile(
    r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)\s+"
    r"--hash=sha256:([0-9a-f]{64})$"
)
SAFE_COMPONENT_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
SMOKE_COLLECTION_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,118}")


class BuildError(RuntimeError):
    """Raised when a release build cannot prove a required invariant."""


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise BuildError(f"{label} must be an object")
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BuildError(f"{label} must be an object")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise BuildError("Unable to hash a build input") from exc
    return digest.hexdigest()


def _sha256_stream(handle: Any) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _write_canonical_json(path: Path, value: Any) -> None:
    path.write_bytes(_canonical_json_bytes(value) + b"\n")


def _real_regular_file(
    path: Path,
    *,
    label: str,
    maximum_size: int,
) -> os.stat_result:
    if not path.is_absolute():
        raise BuildError(f"{label} path must be absolute")
    try:
        info = path.lstat()
    except OSError as exc:
        raise BuildError(f"{label} is missing") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_nlink != 1
        or info.st_size > maximum_size
    ):
        raise BuildError(f"{label} must be a bounded, unlinked regular file")
    return info


def _safe_archive_member_name(name: str) -> str:
    normalized = name[2:] if name.startswith("./") else name
    normalized = normalized.rstrip("/")
    if normalized == "":
        return "."
    pure = PurePosixPath(normalized)
    if (
        name.startswith("/")
        or ".." in pure.parts
        or "\\" in name
        or "\x00" in name
    ):
        raise BuildError("Python source archive contains an unsafe path")
    return pure.as_posix()


def _expected_archive_members(
    distribution: Mapping[str, Any],
) -> dict[str, tuple[int, str]]:
    raw_members = distribution.get("archiveMembers")
    if not isinstance(raw_members, list) or not raw_members:
        raise BuildError("Python source lock omits exact archive members")
    result: dict[str, tuple[int, str]] = {}
    for item in raw_members:
        member = _mapping(item, "Python archive member lock")
        path = member.get("path")
        size = member.get("size")
        digest = member.get("sha256")
        if (
            not isinstance(path, str)
            or _safe_archive_member_name(path) != path
            or path == "."
            or path in result
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or size > MAX_ARCHIVE_MEMBER_BYTES
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise BuildError("Python archive member lock is malformed")
        result[path] = (size, digest)
    return result


def _verify_hash_manifest(
    path: Path,
    distribution: Mapping[str, Any],
) -> None:
    info = _real_regular_file(
        path,
        label="Python hash manifest",
        maximum_size=MAX_HASH_MANIFEST_BYTES,
    )
    if (
        info.st_size != distribution.get("hashManifestSize")
        or _sha256_file(path) != distribution.get("hashManifestSha256")
    ):
        raise BuildError("Python hash manifest differs from the reviewed lock")
    try:
        text = path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as exc:
        raise BuildError("Python hash manifest must be strict ASCII") from exc
    matches: list[str] = []
    seen_names: set[str] = set()
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9A-Fa-f]{64})[ \t]+[*]?([^ \t]+)", line)
        if match is None:
            raise BuildError("Python hash manifest contains a malformed line")
        digest, name = match.groups()
        if (
            name in seen_names
            or "/" in name
            or "\\" in name
            or "\x00" in name
        ):
            raise BuildError("Python hash manifest contains an unsafe duplicate")
        seen_names.add(name)
        if name == distribution.get("archiveName"):
            matches.append(digest.lower())
    if matches != [distribution.get("archiveSha256")]:
        raise BuildError("Python hash manifest target entry is absent or ambiguous")


def verify_distribution_files(
    archive: Path,
    hash_manifest: Path,
    *,
    toolchain: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify the complete pinned source chain without executing the archive."""

    reviewed = toolchain or _load_json(TOOLCHAIN_LOCK, "Python toolchain lock")
    python_lock = _mapping(reviewed.get("python"), "Python toolchain entry")
    distribution = _mapping(
        python_lock.get("distribution"), "Python distribution lock"
    )
    archive_info = _real_regular_file(
        archive,
        label="Python distribution archive",
        maximum_size=MAX_SOURCE_ARCHIVE_BYTES,
    )
    _verify_hash_manifest(hash_manifest, distribution)
    if (
        archive_info.st_size != distribution.get("archiveSize")
        or _sha256_file(archive) != distribution.get("archiveSha256")
    ):
        raise BuildError("Python distribution archive differs from the reviewed lock")

    expected_members = _expected_archive_members(distribution)
    observed: dict[str, tuple[int, str]] = {}
    total_size = 0
    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            for member in tar:
                name = _safe_archive_member_name(member.name)
                if name == ".":
                    if not member.isdir():
                        raise BuildError("Python archive root is not a directory")
                    continue
                if name in observed:
                    raise BuildError("Python archive contains duplicate members")
                if not member.isfile() or member.issym() or member.islnk():
                    raise BuildError("Python archive contains a non-regular member")
                if member.size < 0 or member.size > MAX_ARCHIVE_MEMBER_BYTES:
                    raise BuildError("Python archive member exceeds its size bound")
                total_size += member.size
                if total_size > MAX_ARCHIVE_TOTAL_BYTES:
                    raise BuildError("Python archive expands beyond its size bound")
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise BuildError("Python archive member is unreadable")
                with extracted:
                    digest = _sha256_stream(extracted)
                observed[name] = (member.size, digest)
    except (OSError, tarfile.TarError) as exc:
        raise BuildError("Python distribution archive is invalid") from exc
    if observed != expected_members:
        raise BuildError("Python archive members differ from the reviewed lock")
    package_name = distribution.get("installerPackageName")
    if (
        expected_members.get(str(package_name), (None, None))[1]
        != distribution.get("installerPackageSha256")
        or distribution.get("installMethod") != "macos-installer-pkg-direct"
    ):
        raise BuildError("Python installer package evidence is inconsistent")

    return {
        "implementation": python_lock.get("implementation"),
        "version": python_lock.get("version"),
        "installRoot": python_lock.get("installRoot"),
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


def extract_reviewed_installer_package(
    archive: Path,
    hash_manifest: Path,
    output: Path,
    *,
    toolchain: Mapping[str, Any] | None = None,
) -> Path:
    """Extract only the reviewed pkg; never execute the archive's setup.sh."""

    reviewed = toolchain or _load_json(TOOLCHAIN_LOCK, "Python toolchain lock")
    verify_distribution_files(
        archive,
        hash_manifest,
        toolchain=reviewed,
    )
    distribution = _mapping(
        _mapping(reviewed.get("python"), "Python toolchain entry").get(
            "distribution"
        ),
        "Python distribution lock",
    )
    package_name = str(distribution.get("installerPackageName"))
    if not output.is_absolute():
        raise BuildError("Extracted installer package path must be absolute")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent_info = output.parent.lstat()
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or stat.S_ISLNK(parent_info.st_mode)
        or output.parent.resolve(strict=True) != output.parent
    ):
        raise BuildError("Installer output parent must be a real directory")
    if output.exists() or output.is_symlink():
        existing = output.lstat()
        if not stat.S_ISREG(existing.st_mode) or stat.S_ISLNK(existing.st_mode):
            raise BuildError("Existing installer output is not a regular file")
    temporary = output.with_name(f".{output.name}.{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        found = False
        digest = hashlib.sha256()
        written = 0
        with os.fdopen(descriptor, "wb", closefd=False) as destination:
            with tarfile.open(archive, mode="r:gz") as tar:
                for member in tar:
                    if _safe_archive_member_name(member.name) != package_name:
                        continue
                    if found or not member.isfile() or member.issym() or member.islnk():
                        raise BuildError("Reviewed installer package is ambiguous")
                    found = True
                    source = tar.extractfile(member)
                    if source is None:
                        raise BuildError("Reviewed installer package is unreadable")
                    with source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            written += len(chunk)
                            if written > MAX_ARCHIVE_MEMBER_BYTES:
                                raise BuildError("Installer package exceeds its size bound")
                            digest.update(chunk)
                            destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        if (
            not found
            or written
            != next(
                int(member["size"])
                for member in distribution["archiveMembers"]
                if member["path"] == package_name
            )
            or digest.hexdigest() != distribution.get("installerPackageSha256")
        ):
            raise BuildError("Extracted installer package differs from its lock")
        os.replace(temporary, output)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(descriptor)
    return output


def _contained(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _reviewed_broken_symlinks(
    python_lock: Mapping[str, Any],
) -> dict[str, str]:
    raw_entries = python_lock.get("reviewedBrokenSymlinks")
    if not isinstance(raw_entries, list):
        raise BuildError("Python toolchain lock omits reviewed broken symlinks")
    result: dict[str, str] = {}
    for raw_entry in raw_entries:
        entry = _mapping(raw_entry, "Reviewed Python broken symlink")
        if set(entry) != {"path", "target"}:
            raise BuildError("Reviewed Python broken symlink entry is malformed")
        relative = entry.get("path")
        target = entry.get("target")
        if not isinstance(relative, str) or not isinstance(target, str):
            raise BuildError("Reviewed Python broken symlink entry is malformed")
        relative_path = PurePosixPath(relative)
        target_path = PurePosixPath(target)
        if (
            not relative
            or relative_path.is_absolute()
            or relative_path.as_posix() != relative
            or any(part in {"", ".", ".."} for part in relative_path.parts)
            or "\\" in relative
            or "\x00" in relative
            or not target
            or target_path.is_absolute()
            or any(part in {"", ".", ".."} for part in target_path.parts)
            or "\\" in target
            or "\x00" in target
            or relative in result
        ):
            raise BuildError("Reviewed Python broken symlink entry is unsafe")
        result[relative] = target
    if list(result) != sorted(result):
        raise BuildError("Reviewed Python broken symlinks are not ordered")
    return result


def fingerprint_install_root(
    root: Path,
    *,
    reviewed_broken_symlinks: Mapping[str, str] | None = None,
) -> str:
    """Fingerprint immutable framework content without runtime bytecode caches."""

    try:
        info = root.lstat()
    except OSError as exc:
        raise BuildError("Pinned Python install root is missing") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise BuildError("Pinned Python install root must be a real directory")
    root = root.resolve(strict=True)
    reviewed_broken = dict(reviewed_broken_symlinks or {})
    observed_broken: dict[str, str] = {}
    inventory: list[dict[str, Any]] = []
    for path in sorted(
        root.rglob("*"),
        key=lambda candidate: candidate.relative_to(root).as_posix(),
    ):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        try:
            item_info = path.lstat()
        except OSError as exc:
            raise BuildError("Python install root changed during fingerprinting") from exc
        item: dict[str, Any] = {
            "path": relative.as_posix(),
            "mode": f"{stat.S_IMODE(item_info.st_mode):04o}",
        }
        if stat.S_ISLNK(item_info.st_mode):
            target = os.readlink(path)
            if not target or os.path.isabs(target) or "\x00" in target:
                raise BuildError("Python install root contains an unsafe symlink")
            try:
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                try:
                    unresolved_target = (path.parent / target).resolve(strict=False)
                except (OSError, RuntimeError) as target_exc:
                    raise BuildError(
                        "Python install root contains an unsafe broken symlink"
                    ) from target_exc
                relative_name = relative.as_posix()
                if (
                    not _contained(root, unresolved_target)
                    or reviewed_broken.get(relative_name) != target
                ):
                    raise BuildError(
                        "Python install root contains an unreviewed broken symlink: "
                        f"{relative_name!r} -> {target!r}"
                    ) from exc
                observed_broken[relative_name] = target
                item.update(
                    {
                        "type": "symlink",
                        "target": target,
                        "broken": True,
                        "sha256": hashlib.sha256(
                            target.encode("utf-8")
                        ).hexdigest(),
                    }
                )
                inventory.append(item)
                continue
            if not _contained(root, resolved):
                raise BuildError("Python install root symlink escapes the framework")
            item.update(
                {
                    "type": "symlink",
                    "target": target,
                    "sha256": hashlib.sha256(target.encode("utf-8")).hexdigest(),
                }
            )
        elif stat.S_ISDIR(item_info.st_mode):
            item["type"] = "directory"
        elif stat.S_ISREG(item_info.st_mode):
            item.update(
                {
                    "type": "file",
                    "size": item_info.st_size,
                    "sha256": _sha256_file(path),
                }
            )
        else:
            raise BuildError("Python install root contains a special file")
        inventory.append(item)
    if observed_broken != reviewed_broken:
        raise BuildError("Reviewed Python broken symlink set changed")
    if not inventory:
        raise BuildError("Python install root fingerprint is empty")
    return hashlib.sha256(_canonical_json_bytes(inventory)).hexdigest()


def verify_python_install_binding(
    install_root: Path,
    *,
    toolchain: Mapping[str, Any] | None = None,
    implementation: str | None = None,
    version: str | None = None,
    system: str | None = None,
    machine: str | None = None,
    base_prefix: Path | None = None,
    base_executable: Path | None = None,
    executable: Path | None = None,
    cache_tag: str | None = None,
    gil_disabled: bool | None = None,
    fingerprint: Callable[[Path], str] | None = None,
) -> str:
    """Bind the active interpreter/venv to the reviewed Python.org framework."""

    reviewed = toolchain or _load_json(TOOLCHAIN_LOCK, "Python toolchain lock")
    python_lock = _mapping(reviewed.get("python"), "Python toolchain entry")
    expected_root = Path(str(python_lock.get("installRoot")))
    if not install_root.is_absolute():
        raise BuildError("LCF_PYTHON_INSTALL_ROOT must be absolute")
    try:
        canonical_root = install_root.resolve(strict=True)
        canonical_expected = expected_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BuildError("Pinned Python framework root cannot be resolved") from exc
    if (
        canonical_root != canonical_expected
        or install_root != expected_root
        or install_root.is_symlink()
    ):
        raise BuildError("Python install root differs from the reviewed framework path")

    observed_implementation = implementation or platform.python_implementation()
    observed_version = version or platform.python_version()
    observed_system = system or platform.system()
    observed_machine = machine or platform.machine()
    observed_base_prefix = (base_prefix or Path(sys.base_prefix)).resolve()
    observed_base_executable = (
        base_executable
        or Path(getattr(sys, "_base_executable", sys.executable))
    ).resolve()
    observed_executable = (executable or Path(sys.executable)).resolve()
    observed_cache_tag = cache_tag or str(sys.implementation.cache_tag)
    if gil_disabled is None:
        gil_disabled = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))

    if (
        observed_implementation != python_lock.get("implementation")
        or observed_version != python_lock.get("version")
        or observed_system != "Darwin"
        or observed_machine != "arm64"
        or observed_cache_tag != "cpython-313"
        or gil_disabled
        or observed_base_prefix != canonical_root
        or not _contained(canonical_root, observed_base_executable)
        or not _contained(canonical_root, observed_executable)
        or "PythonT.framework" in str(observed_base_executable)
    ):
        raise BuildError("Active Python is not the reviewed CPython framework")
    expected_interpreter = (
        canonical_root / str(python_lock.get("interpreterRelativePath"))
    )
    try:
        expected_interpreter = expected_interpreter.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BuildError("Reviewed framework interpreter is missing") from exc
    if observed_base_executable != expected_interpreter:
        raise BuildError("Active Python base executable is not the reviewed interpreter")
    if base_prefix is None:
        active_prefix = Path(sys.prefix).resolve()
        if active_prefix == canonical_root:
            raise BuildError("Release build must run in an isolated Python venv")
        configuration = active_prefix / "pyvenv.cfg"
        try:
            settings = configuration.read_text(encoding="utf-8").lower()
        except (OSError, UnicodeDecodeError) as exc:
            raise BuildError("Build venv configuration is unreadable") from exc
        if not re.search(
            r"(?m)^include-system-site-packages\s*=\s*false\s*$",
            settings,
        ):
            raise BuildError("Build venv inherits system site-packages")
    if fingerprint is not None:
        return fingerprint(canonical_root)
    reviewed_broken = _reviewed_broken_symlinks(python_lock)
    return fingerprint_install_root(
        canonical_root,
        reviewed_broken_symlinks=reviewed_broken,
    )


def parse_build_requirements(path: Path = BUILD_REQUIREMENTS_LOCK) -> dict[str, str]:
    """Parse the intentionally tiny, hash-only build wheel lock."""

    try:
        physical_lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise BuildError("Build requirements lock is unreadable") from exc
    logical_lines: list[str] = []
    pending = ""
    for raw in physical_lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            pending += line[:-1].strip() + " "
            continue
        logical_lines.append((pending + line).strip())
        pending = ""
    if pending:
        raise BuildError("Build requirements lock ends with a continuation")
    result: dict[str, str] = {}
    for line in logical_lines:
        match = WHEEL_REQUIREMENT_PATTERN.fullmatch(line)
        if match is None:
            raise BuildError("Build requirements must be exact hash-locked wheels")
        raw_name, version, digest = match.groups()
        name = raw_name.lower().replace("_", "-").replace(".", "-")
        if name in result:
            raise BuildError("Build requirements contain a duplicate distribution")
        result[name] = version
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise BuildError("Build requirement digest is malformed")
    required = {
        "altgraph",
        "macholib",
        "packaging",
        "pyinstaller",
        "pyinstaller-hooks-contrib",
        "setuptools",
        "uv",
    }
    if set(result) != required:
        raise BuildError("Build requirements lock has an unexpected package set")
    return result


def _distribution_version(name: str) -> str:
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise BuildError(f"Required distribution {name} is not installed") from exc
    try:
        location = Path(distribution.locate_file("")).resolve(strict=True)
        active_prefix = Path(sys.prefix).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BuildError(f"Required distribution {name} has an invalid location") from exc
    if not _contained(active_prefix, location):
        raise BuildError(f"Required distribution {name} is outside the build venv")
    return distribution.version


def verify_build_tool_versions(
    toolchain: Mapping[str, Any],
    build_requirements: Mapping[str, str],
) -> None:
    tools = _mapping(toolchain.get("tools"), "toolchain tools")
    expected = {
        "uv": tools.get("uv"),
        "pyinstaller": tools.get("pyinstaller"),
        "pyinstaller-hooks-contrib": tools.get("pyinstallerHooksContrib"),
    }
    if any(build_requirements.get(name) != value for name, value in expected.items()):
        raise BuildError("Build wheel lock and toolchain versions disagree")
    for name, expected_version in build_requirements.items():
        if _distribution_version(name) != expected_version:
            raise BuildError(f"Installed build tool {name} differs from its wheel lock")


def _run_checked(
    arguments: Sequence[str],
    *,
    cwd: Path = REPOSITORY_ROOT,
    env: Mapping[str, str] | None = None,
    timeout: int = 120,
    label: str,
) -> str:
    try:
        completed = subprocess.run(
            list(arguments),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise BuildError(f"{label} failed") from exc
    return completed.stdout.strip()


def _git_output(*arguments: str) -> str:
    return _run_checked(
        ("/usr/bin/git", *arguments),
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        label="Git provenance check",
    )


def _selected_source_commit(environment: Mapping[str, str]) -> str:
    """Return the reviewed checkout SHA without trusting a PR merge SHA."""

    source_name = (
        "LCF_SOURCE_SHA" if environment.get("LCF_SOURCE_SHA") else "GITHUB_SHA"
    )
    repository_commit = environment.get(source_name, "").lower()
    if re.fullmatch(r"[0-9a-f]{40}", repository_commit) is None:
        raise BuildError(f"{source_name} must be a full Git commit SHA")
    return repository_commit


def validate_release_environment(
    environment: Mapping[str, str],
    toolchain: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate non-self-referential runner and repository provenance."""

    required_inputs = toolchain.get("requiredCiInputs")
    if not isinstance(required_inputs, list) or not all(
        isinstance(item, str) and item for item in required_inputs
    ):
        raise BuildError("Toolchain required CI inputs are malformed")
    missing = [name for name in required_inputs if not environment.get(name)]
    if missing:
        raise BuildError("Required Python sidecar CI inputs are missing")
    target = _mapping(toolchain.get("target"), "toolchain target")
    if (
        platform.system() != "Darwin"
        or platform.machine() != "arm64"
        or environment.get("GITHUB_ACTIONS") != "true"
        or environment.get("RUNNER_OS") != "macOS"
        or environment.get("RUNNER_ARCH") != "ARM64"
        or environment.get("ImageOS") not in {"macos15", "macos-15"}
        or target.get("runnerLabel") != "macos-15"
    ):
        raise BuildError("Python sidecar builds require the native macos-15 arm64 runner")
    if _run_checked(
        ("/usr/sbin/sysctl", "-in", "sysctl.proc_translated"),
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        label="Rosetta check",
    ) not in {"0", ""}:
        raise BuildError("Python sidecar must not build under Rosetta")

    repository_commit = _selected_source_commit(environment)
    if _git_output("rev-parse", "HEAD").lower() != repository_commit:
        raise BuildError(
            "Selected source SHA does not identify the checked-out source"
        )
    if _git_output("status", "--porcelain", "--untracked-files=all"):
        raise BuildError("Source changes must be committed before packaging")
    try:
        source_epoch = int(environment["LCF_SOURCE_DATE_EPOCH"])
    except ValueError as exc:
        raise BuildError("LCF_SOURCE_DATE_EPOCH must be an integer") from exc
    if (
        source_epoch < 100_000_000
        or int(_git_output("show", "-s", "--format=%ct", "HEAD")) != source_epoch
    ):
        raise BuildError("SOURCE_DATE_EPOCH differs from the source commit timestamp")

    runner_version = environment["ImageVersion"]
    if re.fullmatch(r"[0-9]{8}\.[0-9]+\.[0-9]+", runner_version) is None:
        raise BuildError("GitHub runner image version is malformed")
    xcode_output = _run_checked(
        ("/usr/bin/xcodebuild", "-version"),
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        label="Xcode version check",
    ).splitlines()
    if not xcode_output or re.fullmatch(r"Xcode [0-9]+(?:\.[0-9]+){0,2}", xcode_output[0]) is None:
        raise BuildError("Xcode version output is malformed")
    xcode_version = xcode_output[0].split(" ", 1)[1]
    sdk_version = _run_checked(
        ("/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-version"),
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        label="macOS SDK version check",
    )
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", sdk_version) is None:
        raise BuildError("macOS SDK version output is malformed")
    install_root = Path(environment["LCF_PYTHON_INSTALL_ROOT"])
    locked_python = _mapping(toolchain.get("python"), "toolchain Python")
    if install_root != Path(str(locked_python.get("installRoot"))):
        raise BuildError("LCF_PYTHON_INSTALL_ROOT differs from the reviewed lock")
    return {
        "repositoryCommit": repository_commit,
        "sourceDateEpoch": source_epoch,
        "runnerImage": target.get("runnerLabel"),
        "runnerImageVersion": runner_version,
        "macosDeploymentTarget": target.get("deploymentTarget"),
        "xcodeVersion": xcode_version,
        "sdkVersion": sdk_version,
    }


def verify_repository_provenance(release: Mapping[str, Any]) -> None:
    if (
        _git_output("rev-parse", "HEAD").lower()
        != release.get("repositoryCommit")
        or _git_output("status", "--porcelain", "--untracked-files=all")
        or int(_git_output("show", "-s", "--format=%ct", "HEAD"))
        != release.get("sourceDateEpoch")
    ):
        raise BuildError("Repository provenance changed during packaging")


def _marker_applies(marker: Any) -> bool:
    if marker is None:
        return True
    if not isinstance(marker, str):
        raise BuildError("uv.lock dependency marker is malformed")
    try:
        from packaging.markers import Marker
    except ImportError as exc:
        raise BuildError("Hash-locked packaging is required to evaluate uv.lock") from exc
    environment = {
        "implementation_name": "cpython",
        "implementation_version": "3.13.14",
        "os_name": "posix",
        "platform_machine": "arm64",
        "platform_python_implementation": "CPython",
        "platform_release": "",
        "platform_system": "Darwin",
        "platform_version": "",
        "python_full_version": "3.13.14",
        "python_version": "3.13",
        "sys_platform": "darwin",
        "extra": "",
    }
    try:
        return Marker(marker).evaluate(environment=environment)
    except Exception as exc:
        raise BuildError("uv.lock dependency marker cannot be evaluated") from exc


def _canonical_distribution_name(name: str) -> str:
    try:
        from packaging.utils import canonicalize_name
    except ImportError as exc:
        raise BuildError("Hash-locked packaging is required for dependency checks") from exc
    return canonicalize_name(name)


def runtime_dependency_versions(
    lock_path: Path = BACKEND_ROOT / "uv.lock",
) -> dict[str, str]:
    """Resolve the production dependency closure for CPython 3.13/Darwin."""

    try:
        lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise BuildError("uv.lock is unreadable") from exc
    if lock.get("version") != 1:
        raise BuildError("Unsupported uv.lock format")
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise BuildError("uv.lock package list is missing")
    by_name: dict[str, list[Mapping[str, Any]]] = {}
    root: Mapping[str, Any] | None = None
    for raw in packages:
        package = _mapping(raw, "uv.lock package")
        raw_name = package.get("name")
        raw_version = package.get("version")
        if not isinstance(raw_name, str) or not isinstance(raw_version, str):
            raise BuildError("uv.lock package identity is malformed")
        name = _canonical_distribution_name(raw_name)
        by_name.setdefault(name, []).append(package)
        if name == "local-context-forge-backend":
            root = package
    if root is None:
        raise BuildError("uv.lock omits the backend project")

    resolved: dict[str, str] = {}
    expanded: set[str] = set()
    queue: deque[Mapping[str, Any]] = deque()
    dependencies = root.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise BuildError("Backend production dependencies are malformed")
    queue.extend(_mapping(item, "uv.lock dependency") for item in dependencies)
    while queue:
        dependency = queue.popleft()
        if not _marker_applies(dependency.get("marker")):
            continue
        raw_name = dependency.get("name")
        if not isinstance(raw_name, str):
            raise BuildError("uv.lock dependency name is malformed")
        name = _canonical_distribution_name(raw_name)
        candidates = by_name.get(name, [])
        if len(candidates) != 1:
            raise BuildError("uv.lock dependency selection is ambiguous")
        package = candidates[0]
        version = package.get("version")
        if not isinstance(version, str):
            raise BuildError("uv.lock dependency version is malformed")
        previous = resolved.setdefault(name, version)
        if previous != version:
            raise BuildError("uv.lock resolves multiple dependency versions")
        if name not in expanded:
            expanded.add(name)
            children = package.get("dependencies", [])
            if not isinstance(children, list):
                raise BuildError("uv.lock transitive dependencies are malformed")
            for child in children:
                queue.append(_mapping(child, "uv.lock dependency"))
    forbidden = {"httptools", "uvloop", "watchfiles", "websockets"}
    if forbidden & set(resolved):
        raise BuildError("Production lock includes forbidden Uvicorn standard extras")
    return dict(sorted(resolved.items()))


def verify_runtime_dependencies(expected: Mapping[str, str]) -> None:
    for name, version in expected.items():
        if _distribution_version(name) != version:
            raise BuildError(f"Installed runtime dependency {name} differs from uv.lock")


def _uv_lock_failure_category(stderr: str) -> str:
    """Return a stable, non-sensitive category for uv lock failures."""

    normalized = stderr.lower()
    if (
        re.search(
            r"(?:lockfile|lock file)[^\n]{0,200}needs to be updated",
            normalized,
        )
        or "no `uv.lock` found" in normalized
        or "uv.lock is missing" in normalized
    ):
        return "lock-drift"
    if any(
        marker in normalized
        for marker in (
            "no interpreter found",
            "python interpreter was not found",
            "no python installation found",
        )
    ):
        return "interpreter-unavailable"
    if any(
        marker in normalized
        for marker in (
            "network was disabled",
            "not found in the cache",
            "offline mode",
        )
    ):
        return "offline-resolution"
    if "unexpected argument" in normalized or "usage: uv lock" in normalized:
        return "cli-contract"
    return "unclassified"


def verify_uv_lock(uv_executable: Path) -> None:
    if not uv_executable.is_absolute():
        raise BuildError("uv executable path must be absolute")
    active_python = Path(sys.executable)
    if not active_python.is_absolute():
        raise BuildError("Build venv Python path must be absolute")
    try:
        uv_path_info = uv_executable.lstat()
        resolved = uv_executable.resolve(strict=True)
        info = resolved.lstat()
        uv_bin = uv_executable.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BuildError("uv executable is missing") from exc
    try:
        active_info = active_python.lstat()
        resolved_python = active_python.resolve(strict=True)
        resolved_python_info = resolved_python.lstat()
        python_bin = active_python.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BuildError("Build venv Python is missing") from exc
    if (
        not stat.S_ISREG(uv_path_info.st_mode)
        or stat.S_ISLNK(uv_path_info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or not (stat.S_IMODE(info.st_mode) & 0o111)
    ):
        raise BuildError("uv executable is not a regular executable")
    if (
        uv_bin != python_bin
        or (
            not stat.S_ISREG(active_info.st_mode)
            and not stat.S_ISLNK(active_info.st_mode)
        )
        or not stat.S_ISREG(resolved_python_info.st_mode)
        or not (stat.S_IMODE(resolved_python_info.st_mode) & 0o111)
    ):
        raise BuildError("uv and Python must come from the same build venv")
    with tempfile.TemporaryDirectory(prefix="lcf-uv-lock-cache-") as cache:
        try:
            completed = subprocess.run(
                [
                    str(resolved),
                    "lock",
                    "--check",
                    "--python",
                    str(resolved_python),
                ],
                cwd=BACKEND_ROOT,
                env={
                    "PATH": "/usr/bin:/bin",
                    "LANG": "C",
                    "LC_ALL": "C",
                    "UV_CACHE_DIR": cache,
                    "UV_NO_CONFIG": "1",
                    "UV_NO_PROGRESS": "1",
                    "UV_OFFLINE": "1",
                    "UV_PYTHON_DOWNLOADS": "never",
                },
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=180,
            )
        except OSError as exc:
            raise BuildError("uv lock check could not start") from exc
        except subprocess.TimeoutExpired as exc:
            raise BuildError("uv lock check timed out") from exc
        if completed.returncode != 0:
            category = _uv_lock_failure_category(completed.stderr)
            raise BuildError(
                "uv lock check failed "
                f"(exit={completed.returncode}; category={category})"
            )


def _sanitize_text(
    text: str,
    *,
    build_root: Path,
    install_root: Path,
) -> str:
    replacements = [
        (str(REPOSITORY_ROOT), "$REPOSITORY_ROOT"),
        (str(build_root), "$BUILD_ROOT"),
        (str(install_root), "$PYTHON_INSTALL_ROOT"),
    ]
    sanitized = text
    for raw, replacement in sorted(replacements, key=lambda item: -len(item[0])):
        sanitized = sanitized.replace(raw, replacement)
    # A CI evidence file must not retain a runner home/workspace path even if a
    # tool printed a path we did not anticipate above.
    if re.search(r"/Users/runner/|/Users/[^/\s]+/work/", sanitized):
        raise BuildError("PyInstaller evidence contains an unsanitized runner path")
    return sanitized


def _collect_pyinstaller_evidence(
    *,
    work_root: Path,
    log_text: str,
    destination: Path,
    build_root: Path,
    install_root: Path,
) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "pyinstaller.log").write_text(
        _sanitize_text(
            log_text,
            build_root=build_root,
            install_root=install_root,
        ),
        encoding="utf-8",
    )
    if not work_root.exists():
        return
    for source in sorted(work_root.rglob("*")):
        if (
            not source.is_file()
            or source.is_symlink()
            or source.suffix.lower() not in {".txt", ".html", ".toc"}
        ):
            continue
        info = source.stat()
        if info.st_size > 16 * 1024 * 1024:
            raise BuildError("PyInstaller evidence file exceeds its size bound")
        relative = source.relative_to(work_root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            raw = source.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError) as exc:
            raise BuildError("PyInstaller evidence must be UTF-8 text") from exc
        target.write_text(
            _sanitize_text(
                raw,
                build_root=build_root,
                install_root=install_root,
            ),
            encoding="utf-8",
        )


def _warn_file(evidence: Path) -> Path:
    matches = sorted(evidence.rglob("warn-*.txt"))
    if len(matches) != 1:
        raise BuildError("PyInstaller warning evidence is missing or ambiguous")
    return matches[0]


def validate_missing_imports(
    warning_file: Path,
    *,
    allowlist_path: Path = MISSING_IMPORTS_ALLOWLIST,
) -> set[str]:
    allowlist = _load_json(allowlist_path, "Missing-import allowlist")
    if set(allowlist) != {
        "schemaVersion",
        "target",
        "pyinstallerVersion",
        "pyinstallerHooksContribVersion",
        "modules",
    } or allowlist.get("schemaVersion") != 2:
        raise BuildError("Missing-import allowlist schema is unsupported")
    toolchain = _load_json(TOOLCHAIN_LOCK, "Python toolchain lock")
    target = _mapping(toolchain.get("target"), "toolchain target")
    python = _mapping(toolchain.get("python"), "Python toolchain entry")
    tools = _mapping(toolchain.get("tools"), "toolchain tools")
    if allowlist.get("target") != {
        "os": target.get("os"),
        "architecture": target.get("architecture"),
        "pythonVersion": python.get("version"),
    }:
        raise BuildError("Missing-import allowlist target differs from the toolchain")
    if (
        allowlist.get("pyinstallerVersion") != tools.get("pyinstaller")
        or allowlist.get("pyinstallerHooksContribVersion")
        != tools.get("pyinstallerHooksContrib")
    ):
        raise BuildError("Missing-import allowlist tool versions differ from the toolchain")
    modules = allowlist.get("modules")
    if not isinstance(modules, Mapping) or not all(
        isinstance(name, str)
        and SAFE_MISSING_IMPORT_NAME_PATTERN.fullmatch(name)
        and isinstance(reason, str)
        and reason
        for name, reason in modules.items()
    ):
        raise BuildError("Missing-import allowlist is malformed")
    try:
        lines = warning_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise BuildError("PyInstaller warning file is unreadable") from exc
    observed: set[str] = set()
    for line in lines:
        match = EXPECTED_MISSING_IMPORT_PATTERN.match(line.strip())
        if match:
            module = match.group(1)
            if not SAFE_MISSING_IMPORT_NAME_PATTERN.fullmatch(module):
                raise BuildError(
                    "PyInstaller warning evidence contains a malformed module name"
                )
            observed.add(module)
            if len(observed) > 256:
                raise BuildError("PyInstaller warning evidence exceeds its module bound")
    unexpected = observed - set(modules)
    missing = set(modules) - observed
    if unexpected or missing:
        def safe_names(values: set[str]) -> str:
            names = ",".join(sorted(values))
            if len(names) <= 2048:
                return names
            return "sha256:" + hashlib.sha256(names.encode("ascii")).hexdigest()

        differences = []
        if unexpected:
            differences.append(f"unexpected={safe_names(unexpected)}")
        if missing:
            differences.append(f"missing={safe_names(missing)}")
        raise BuildError(
            "PyInstaller missing-import inventory differs from the reviewed target "
            f"(observed={len(observed)}; reviewed={len(modules)}; "
            + "; ".join(differences)
            + ")"
        )
    return observed


def run_pyinstaller(
    *,
    build_root: Path,
    install_root: Path,
    source_date_epoch: int,
    deployment_target: str,
) -> tuple[Path, Path]:
    """Run PyInstaller with a minimal deterministic environment."""

    active_python = Path(sys.executable)
    try:
        executable_info = active_python.lstat()
        resolved_python = active_python.resolve(strict=True)
        expected_python = (
            install_root / "bin" / "python3.13"
        ).resolve(strict=True)
        active_bin = (Path(sys.prefix) / "bin").resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BuildError("Build venv Python cannot be resolved") from exc
    if (
        not active_python.is_absolute()
        or active_python.parent.resolve() != active_bin
        or (
            not stat.S_ISREG(executable_info.st_mode)
            and not stat.S_ISLNK(executable_info.st_mode)
        )
        or resolved_python != expected_python
    ):
        raise BuildError("PyInstaller must run through the reviewed build venv")

    dist_root = build_root / "dist"
    work_root = build_root / "work"
    config_root = build_root / "pyinstaller-config"
    temp_root = build_root / "tmp"
    for directory in (dist_root, work_root, config_root, temp_root):
        directory.mkdir(mode=0o700)
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "SOURCE_DATE_EPOCH": str(source_date_epoch),
        "MACOSX_DEPLOYMENT_TARGET": deployment_target,
        "PYINSTALLER_CONFIG_DIR": str(config_root),
        "TMPDIR": str(temp_root),
    }
    arguments = (
        str(active_python),
        "-I",
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_root),
        "--workpath",
        str(work_root),
        str(SPEC_FILE),
    )
    try:
        completed = subprocess.run(
            arguments,
            cwd=REPOSITORY_ROOT,
            env=environment,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=1800,
        )
        log_text = completed.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        log_text = f"PyInstaller invocation failed: {type(exc).__name__}\n"
        completed = None
    evidence = build_root / "evidence"
    _collect_pyinstaller_evidence(
        work_root=work_root,
        log_text=log_text,
        destination=evidence,
        build_root=build_root,
        install_root=install_root,
    )
    if completed is None or completed.returncode != 0:
        raise BuildError("PyInstaller build failed; sanitized evidence was retained")
    validate_missing_imports(_warn_file(evidence))
    bundle = dist_root / "lcf-service"
    executable = bundle / "lcf-service"
    if (
        not bundle.is_dir()
        or bundle.is_symlink()
        or not executable.is_file()
        or executable.is_symlink()
    ):
        raise BuildError("PyInstaller did not produce the reviewed onedir shape")
    shutil.copytree(evidence, bundle / "_build-evidence", symlinks=True)
    return bundle, evidence


def _license_sources(distribution_name: str) -> list[Path]:
    try:
        distribution = importlib.metadata.distribution(distribution_name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise BuildError(
            f"License source distribution {distribution_name} is missing"
        ) from exc
    sources: list[Path] = []
    for item in distribution.files or ():
        parts = tuple(part.lower() for part in item.parts)
        name = item.name.lower()
        if (
            "licenses" not in parts
            and not name.startswith(("license", "copying", "notice"))
        ):
            continue
        source = Path(distribution.locate_file(item))
        try:
            info = source.lstat()
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            sources.append(source)
    return sorted(set(sources), key=lambda path: path.as_posix())


def _copy_component_licenses(
    *,
    component_name: str,
    sources: Sequence[Path],
    bundle: Path,
) -> list[str]:
    component_directory = (
        bundle / "licenses" / SAFE_COMPONENT_PATTERN.sub("-", component_name)
    )
    component_directory.mkdir(parents=True, exist_ok=False)
    result: list[str] = []
    used_names: set[str] = set()
    for index, source in enumerate(sources, start=1):
        filename = SAFE_COMPONENT_PATTERN.sub("-", source.name) or f"LICENSE-{index}"
        if filename in used_names:
            filename = f"{index:02d}-{filename}"
        used_names.add(filename)
        target = component_directory / filename
        shutil.copyfile(source, target, follow_symlinks=False)
        result.append(target.relative_to(bundle).as_posix())
    if not result:
        raise BuildError(f"Component {component_name} has no license evidence")
    return sorted(result)


def _component_from_distribution(
    *,
    name: str,
    version: str,
    scope: str,
    license_expression: str,
    bundle: Path,
) -> dict[str, Any]:
    if _distribution_version(name) != version:
        raise BuildError(f"Component {name} version changed during the build")
    return {
        "name": name,
        "version": version,
        "scope": scope,
        "licenseExpression": license_expression,
        "licenseFiles": _copy_component_licenses(
            component_name=name,
            sources=_license_sources(name),
            bundle=bundle,
        ),
    }


def _platform_component(
    *,
    name: str,
    version: str,
    license_expression: str,
    notice_name: str,
    bundle: Path,
) -> dict[str, Any]:
    notice = PACKAGING_ROOT / "notices" / notice_name
    return {
        "name": name,
        "version": version,
        "scope": "runtime",
        "licenseExpression": license_expression,
        "licenseFiles": _copy_component_licenses(
            component_name=name,
            sources=[notice],
            bundle=bundle,
        ),
    }


def _openssl_version() -> str:
    match = re.search(r"OpenSSL\s+([0-9]+(?:\.[0-9]+){1,2}[A-Za-z0-9.-]*)", ssl.OPENSSL_VERSION)
    if match is None:
        raise BuildError("Bundled OpenSSL version is not identifiable")
    return match.group(1)


def build_components(
    *,
    bundle: Path,
    runtime_versions: Mapping[str, str],
    build_versions: Mapping[str, str],
) -> list[dict[str, Any]]:
    policy = _load_json(LICENSE_POLICY, "Python sidecar license policy")
    if policy.get("schemaVersion") != 1:
        raise BuildError("Python sidecar license policy schema is unsupported")
    runtime_policy = _mapping(
        policy.get("requiredRuntimeComponents"), "runtime license policy"
    )
    build_policy = _mapping(
        policy.get("buildToolComponents"), "build-tool license policy"
    )
    platform_policy = _mapping(
        policy.get("platformComponents"), "platform license policy"
    )
    if set(runtime_versions) != set(runtime_policy):
        raise BuildError("Runtime dependency closure and license policy differ")
    if set(build_versions) != set(build_policy):
        raise BuildError("Build wheel closure and license policy differ")

    components: list[dict[str, Any]] = []
    for name, version in sorted(runtime_versions.items()):
        components.append(
            _component_from_distribution(
                name=name,
                version=version,
                scope="runtime",
                license_expression=str(runtime_policy[name]),
                bundle=bundle,
            )
        )
    for name, version in sorted(build_versions.items()):
        sources = _license_sources(name)
        if not sources and name == "uv":
            sources = [PACKAGING_ROOT / "notices" / "uv-NOTICE.txt"]
        if not sources:
            raise BuildError(f"Build tool {name} has no license evidence")
        components.append(
            {
                "name": name,
                "version": version,
                "scope": "build-tool",
                "licenseExpression": str(build_policy[name]),
                "licenseFiles": _copy_component_licenses(
                    component_name=name,
                    sources=sources,
                    bundle=bundle,
                ),
            }
        )

    platform_definitions = [
        (
            "cpython",
            platform.python_version(),
            "CPython-NOTICE.txt",
        ),
        (
            "openssl",
            _openssl_version(),
            "OpenSSL-NOTICE.txt",
        ),
        (
            "pyinstaller-bootloader",
            build_versions["pyinstaller"],
            "PyInstaller-Bootloader-NOTICE.txt",
        ),
        (
            "python-hashlib",
            platform.python_version(),
            "CPython-NOTICE.txt",
        ),
        (
            "sqlite",
            sqlite3.sqlite_version,
            "SQLite-PUBLIC-DOMAIN.txt",
        ),
    ]
    if {item[0] for item in platform_definitions} != set(platform_policy):
        raise BuildError("Platform component set and license policy differ")
    for name, version, notice_name in platform_definitions:
        components.append(
            _platform_component(
                name=name,
                version=version,
                license_expression=str(platform_policy[name]),
                notice_name=notice_name,
                bundle=bundle,
            )
        )

    ca_candidates = sorted(
        path
        for path in bundle.rglob("cacert.pem")
        if path.is_file() and not path.is_symlink()
    )
    if len(ca_candidates) != 1:
        raise BuildError("Frozen certifi CA bundle is missing or ambiguous")
    ca_bundle = ca_candidates[0]
    certifi_component = next(
        component for component in components if component["name"] == "certifi"
    )
    certifi_component["properties"] = {
        "caBundlePath": ca_bundle.relative_to(bundle).as_posix(),
        "caBundleSha256": _sha256_file(ca_bundle),
    }

    names = [str(component["name"]) for component in components]
    if len(names) != len(set(names)):
        raise BuildError("Component inventory contains duplicate names")
    return sorted(components, key=lambda component: str(component["name"]))


def write_compliance_artifacts(
    *,
    bundle: Path,
    components: Sequence[Mapping[str, Any]],
    repository_commit: str,
    source_date_epoch: int,
) -> dict[str, str]:
    notices_path = bundle / "THIRD-PARTY-NOTICES.txt"
    lines = [
        "Local Context Forge Python sidecar third-party notices",
        "",
        "This generated index records the exact component, version, declared",
        "license expression, and bundled license evidence for this staging.",
        "",
    ]
    for component in components:
        lines.extend(
            [
                f"{component['name']} {component['version']}",
                f"Scope: {component['scope']}",
                f"License: {component['licenseExpression']}",
                "Evidence:",
                *[
                    f"  - {path}"
                    for path in component["licenseFiles"]
                ],
                "",
            ]
        )
    notices_path.write_text("\n".join(lines), encoding="utf-8")

    packages: list[dict[str, Any]] = []
    for index, component in enumerate(components, start=1):
        packages.append(
            {
                "SPDXID": f"SPDXRef-Package-{index:03d}",
                "name": component["name"],
                "versionInfo": component["version"],
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": component["licenseExpression"],
                "licenseDeclared": component["licenseExpression"],
                "copyrightText": "NOASSERTION",
            }
        )
    created = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(source_date_epoch),
    )
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "local-context-forge-python-sidecar",
        "documentNamespace": (
            "https://local-context-forge.dev/spdx/python-sidecar/"
            f"{repository_commit}"
        ),
        "creationInfo": {
            "created": created,
            "creators": ["Tool: Local Context Forge build_python_sidecar.py"],
        },
        "packages": packages,
    }
    sbom_path = bundle / "sbom.spdx.json"
    _write_canonical_json(sbom_path, sbom)
    return {
        "spdxSbom": sbom_path.relative_to(bundle).as_posix(),
        "thirdPartyNotices": notices_path.relative_to(bundle).as_posix(),
        "licensesDirectory": "licenses",
    }


def _trap_environment(
    trap_directory: Path,
    marker: Path,
    *,
    local_source_root: Path | None = None,
) -> dict[str, str]:
    local_source_roots = (
        str(local_source_root.resolve(strict=True))
        if local_source_root is not None
        else ""
    )
    return {
        "PATH": str(trap_directory),
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONNOUSERSITE": "1",
        "LCF_PATH_TRAP_LOG": str(marker),
        "LCF_QMD_ENABLED": "0",
        "LCF_QMD_HYBRID_ENABLED": "0",
        "LCF_CTAGS_ENABLED": "0",
        "LCF_ENABLE_CODEX_PROVIDER": "0",
        "LCF_ENABLE_CURSOR_PROVIDER": "0",
        "LCF_LOCAL_SOURCE_ROOTS": local_source_roots,
    }


def _create_path_trap(directory: Path, marker: Path) -> None:
    directory.mkdir(mode=0o700)
    script = (
        "#!/bin/sh\n"
        'exec /usr/bin/printf "%s\\n" "$0" >> "$LCF_PATH_TRAP_LOG"\n'
    )
    for name in (
        "python",
        "python3",
        "python3.13",
        "node",
        "npm",
        "npx",
        "git",
        "git-lfs",
        "qmd",
        "ctags",
    ):
        path = directory / name
        path.write_text(script, encoding="utf-8")
        path.chmod(0o700)
    if marker.exists():
        raise BuildError("PATH trap marker unexpectedly pre-exists")


def _assert_no_smoke_secrets(
    root: Path,
    values: Sequence[str],
) -> None:
    encoded = tuple(value.encode("utf-8") for value in values)
    total_size = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        try:
            info = path.lstat()
        except OSError as exc:
            raise BuildError("Frozen smoke state changed during secret scan") from exc
        if stat.S_ISDIR(info.st_mode):
            continue
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_size > 32 * 1024 * 1024
        ):
            raise BuildError("Frozen smoke state contains an unsafe file")
        total_size += info.st_size
        if total_size > 64 * 1024 * 1024:
            raise BuildError("Frozen smoke state exceeds its scan bound")
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise BuildError("Frozen smoke state cannot be scanned") from exc
        if any(secret in payload for secret in encoded):
            raise BuildError("Frozen sidecar persisted a session secret")


def _run_frozen_command(
    executable: Path,
    arguments: Sequence[str],
    *,
    environment: Mapping[str, str],
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            (str(executable), *arguments),
            cwd=executable.parent,
            env=dict(environment),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BuildError("Frozen sidecar command did not complete") from exc


def _http_json_over_uds(
    socket_path: Path,
    request_path: str,
    *,
    check: str,
    token: str,
    launch_id: str,
    method: str = "GET",
    body: Mapping[str, Any] | None = None,
    expected_status: int = 200,
    timeout: float = 10.0,
) -> Any:
    if check not in FROZEN_UDS_CHECKS:
        raise BuildError("Frozen UDS smoke requested an unknown check")
    if method not in {"GET", "POST"}:
        raise BuildError("Frozen UDS smoke requested an unsupported method")
    if not isinstance(expected_status, int) or not 100 <= expected_status <= 599:
        raise BuildError("Frozen UDS smoke expected an invalid status")
    if (
        not isinstance(request_path, str)
        or re.fullmatch(
            r"/api/[A-Za-z0-9._~!$&'()*+,;=:@%/?-]{0,2042}",
            request_path,
        )
        is None
        or re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None
        or re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            launch_id,
        )
        is None
        or not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not 0.1 <= timeout <= 120.0
    ):
        raise BuildError(f"Frozen UDS request is invalid (check={check})")
    try:
        serialized = (
            b""
            if body is None
            else json.dumps(
                body,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise BuildError(
            f"Frozen UDS request cannot be serialized (check={check})"
        ) from exc
    if len(serialized) > 1024 * 1024:
        raise BuildError("Frozen UDS request exceeds its size bound")
    request_id = str(uuid.uuid4())
    deadline = int(time.time() * 1000) + int(timeout * 1000)
    headers = (
        f"{method} {request_path} HTTP/1.1\r\n"
        "Host: localhost\r\n"
        "Accept: application/json\r\n"
        "Connection: close\r\n"
        f"Authorization: Bearer {token}\r\n"
        "X-LCF-Protocol-Version: 1.0\r\n"
        f"X-LCF-Launch-Id: {launch_id}\r\n"
        f"X-LCF-Request-Id: {request_id}\r\n"
        f"X-LCF-Deadline-Ms: {deadline}\r\n"
        f"Content-Length: {len(serialized)}\r\n"
    )
    if body is not None:
        headers += "Content-Type: application/json\r\n"
    try:
        request = headers.encode("ascii") + b"\r\n" + serialized
    except UnicodeEncodeError as exc:
        raise BuildError(
            f"Frozen UDS request cannot be encoded (check={check})"
        ) from exc
    client: socket.socket | None = None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(str(socket_path))
        client.sendall(request)
        response = bytearray()
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            response.extend(chunk)
            if len(response) > 1024 * 1024:
                raise BuildError(
                    "Frozen UDS response exceeds its size bound "
                    f"(check={check})"
                )
    except (OSError, TypeError, ValueError) as exc:
        raise BuildError(f"Frozen UDS request failed (check={check})") from exc
    finally:
        if client is not None:
            active_error = sys.exception()
            try:
                client.close()
            except OSError as exc:
                if active_error is None:
                    raise BuildError(
                        f"Frozen UDS request cleanup failed (check={check})"
                    ) from exc
    try:
        raw_headers, body = bytes(response).split(b"\r\n\r\n", 1)
        status_parts = raw_headers.split(b"\r\n", 1)[0].split(b" ", 2)
        if (
            len(status_parts) != 3
            or status_parts[0] != b"HTTP/1.1"
            or re.fullmatch(rb"[0-9]{3}", status_parts[1]) is None
            or not status_parts[2]
            or len(status_parts[2]) > 64
            or any(byte < 0x20 or byte > 0x7E for byte in status_parts[2])
        ):
            raise ValueError("noncanonical status line")
        status = int(status_parts[1].decode("ascii"))
        payload = json.loads(body.decode("utf-8"))
    except (
        ValueError,
        IndexError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
    ) as exc:
        raise BuildError(
            f"Frozen UDS response is malformed (check={check})"
        ) from exc
    if not 100 <= status <= 599:
        raise BuildError(
            f"Frozen UDS response has an invalid status (check={check})"
        )
    if status != expected_status or not isinstance(payload, (dict, list)):
        payload_kind = (
            "object"
            if isinstance(payload, dict)
            else "array"
            if isinstance(payload, list)
            else "scalar"
        )
        raise BuildError(
            "Frozen UDS response did not pass "
            f"(check={check}; expected={expected_status}; "
            f"observed={status}; payload={payload_kind})"
        )
    return payload


def _create_smoke_source_repository(
    repository: Path,
    *,
    source_date_epoch: int,
) -> None:
    """Create a deterministic Git fixture without invoking a PATH executable."""

    try:
        from dulwich import porcelain
    except ImportError as exc:
        raise BuildError("Locked Dulwich is unavailable for frozen smoke") from exc
    repository.mkdir(parents=True, mode=0o700)
    source = repository / "src"
    source.mkdir(mode=0o700)
    (repository / "README.md").write_text(
        "# Frozen Widget\n\nA deterministic packaging smoke fixture.\n",
        encoding="utf-8",
    )
    (source / "widget.py").write_text(
        "def build_widget(name: str) -> str:\n"
        '    \"\"\"Build a deterministic widget label.\"\"\"\n'
        '    return f\"widget:{name}\"\n',
        encoding="utf-8",
    )
    opened = None
    try:
        opened = porcelain.init(repository)
        porcelain.add(opened, paths=["README.md", "src/widget.py"])
        commit = porcelain.commit(
            opened,
            message=b"Create frozen smoke fixture",
            author=b"Local Context Forge <build@local.invalid>",
            author_timestamp=source_date_epoch,
            author_timezone=0,
            committer=b"Local Context Forge <build@local.invalid>",
            commit_timestamp=source_date_epoch,
            commit_timezone=0,
        )
    except Exception as exc:
        raise BuildError("Unable to create the frozen smoke Git fixture") from exc
    finally:
        if opened is not None:
            opened.close()
    if (
        not isinstance(commit, bytes)
        or re.fullmatch(rb"[0-9a-f]{40}", commit) is None
    ):
        raise BuildError("Frozen smoke Git fixture has a noncanonical commit")


def _read_smoke_broker_request(
    connection: socket.socket,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Read one bounded HTTP/1.1 JSON request from the private smoke broker."""

    maximum_headers = 64 * 1024
    maximum_body = MAX_SMOKE_BROKER_REQUEST_BYTES
    received = bytearray()
    while b"\r\n\r\n" not in received:
        chunk = connection.recv(16 * 1024)
        if not chunk:
            raise BuildError("Frozen smoke broker received a truncated request")
        received.extend(chunk)
        if len(received) > maximum_headers:
            raise BuildError("Frozen smoke broker request headers are too large")
    raw_headers, body = bytes(received).split(b"\r\n\r\n", 1)
    try:
        lines = raw_headers.decode("ascii").split("\r\n")
    except UnicodeDecodeError as exc:
        raise BuildError("Frozen smoke broker headers are not ASCII") from exc
    request_parts = lines[0].split(" ")
    if (
        len(request_parts) != 3
        or request_parts[0] != "POST"
        or request_parts[2] != "HTTP/1.1"
    ):
        raise BuildError("Frozen smoke broker received an invalid request line")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            raise BuildError("Frozen smoke broker received a malformed header")
        raw_name, raw_value = line.split(":", 1)
        name = raw_name.strip().lower()
        value = raw_value.strip()
        if not name or name in headers:
            raise BuildError("Frozen smoke broker received duplicate headers")
        headers[name] = value
    content_length = headers.get("content-length", "")
    if (
        not content_length.isdigit()
        or int(content_length) > maximum_body
    ):
        raise BuildError("Frozen smoke broker request length is invalid")
    expected_length = int(content_length)
    while len(body) < expected_length:
        chunk = connection.recv(min(16 * 1024, expected_length - len(body)))
        if not chunk:
            raise BuildError("Frozen smoke broker received a truncated body")
        body += chunk
    if len(body) != expected_length:
        raise BuildError("Frozen smoke broker received trailing request bytes")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildError("Frozen smoke broker body is not JSON") from exc
    if not isinstance(payload, dict):
        raise BuildError("Frozen smoke broker body is not an object")
    return request_parts[1], headers, payload


def _safe_smoke_wiki_root(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or value.startswith(("/", "\\"))
        or "\\" in value
        or "\x00" in value
        or len(value.encode("utf-8")) > 800
    ):
        return False
    path = PurePosixPath(value)
    return all(
        part not in {"", ".", ".."} and len(part.encode("utf-8")) <= 240
        for part in path.parts
    )


def _serve_smoke_broker(
    listener: socket.socket,
    *,
    capability: str,
    launch_id: str,
    protocol: str,
    stop: threading.Event,
    requests: deque[dict[str, Any]],
    failures: deque[str],
) -> None:
    """Serve strict, capability-authenticated reconcile responses for smoke."""

    listener.settimeout(0.2)
    while not stop.is_set():
        try:
            connection, _address = listener.accept()
        except TimeoutError:
            continue
        except OSError:
            if stop.is_set():
                return
            failures.append("accept")
            return
        with connection:
            connection.settimeout(10)
            try:
                endpoint, headers, payload = _read_smoke_broker_request(connection)
                try:
                    deadline = int(headers.get("x-lcf-deadline-ms", ""))
                except ValueError:
                    deadline = 0
                current_millis = int(time.time() * 1000)
                collections = payload.get("collections")
                collection_names = (
                    [
                        item["name"]
                        for item in collections
                        if isinstance(item, dict)
                        and isinstance(item.get("name"), str)
                    ]
                    if isinstance(collections, list)
                    else []
                )
                if (
                    endpoint != "/reconcile"
                    or headers.get("authorization") != f"Bearer {capability}"
                    or headers.get("accept") != "application/json"
                    or headers.get("content-type") != "application/json"
                    or headers.get("x-lcf-protocol-version") != protocol
                    or headers.get("x-lcf-launch-id") != launch_id
                    or re.fullmatch(
                        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
                        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                        headers.get("x-lcf-request-id", ""),
                    )
                    is None
                    or deadline <= current_millis
                    or deadline > current_millis + 121_000
                    or set(payload) != {"revision", "collections"}
                    or not isinstance(payload["revision"], int)
                    or isinstance(payload["revision"], bool)
                    or payload["revision"] < 0
                    or payload["revision"] > MAX_SMOKE_BROKER_REVISION
                    or not isinstance(collections, list)
                    or len(collections) > MAX_SMOKE_BROKER_COLLECTIONS
                    or len(collection_names) != len(collections)
                    or len(collection_names) != len(set(collection_names))
                    or not all(
                        isinstance(item, dict)
                        and set(item) == {"name", "wiki_root"}
                        and isinstance(item["name"], str)
                        and SMOKE_COLLECTION_PATTERN.fullmatch(item["name"])
                        is not None
                        and ".." not in item["name"]
                        and _safe_smoke_wiki_root(item["wiki_root"])
                        for item in collections
                    )
                ):
                    raise BuildError(
                        "Frozen sidecar sent an invalid broker request"
                    )
                response_payload = {
                    "indexed": True,
                    "revision": payload["revision"],
                    "collections": len(collections),
                    "update": {
                        "indexed": len(collections),
                        "updated": 0,
                        "unchanged": 0,
                        "removed": 0,
                    },
                }
                serialized = _canonical_json_bytes(response_payload)
                response = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(serialized)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                ).encode("ascii") + serialized
                connection.sendall(response)
                requests.append(
                    {
                        "endpoint": endpoint,
                        "revision": payload["revision"],
                        "collections": len(collections),
                    }
                )
            except (BuildError, OSError, TimeoutError):
                failures.append("request")
                try:
                    connection.sendall(
                        b"HTTP/1.1 400 Bad Request\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Content-Length: 27\r\n"
                        b"Connection: close\r\n\r\n"
                        b'{"error":"invalid_request"}'
                    )
                except OSError:
                    pass


def _open_frozen_log(log_path: Path) -> tuple[Any, tuple[int, int]]:
    if not log_path.is_absolute() or not hasattr(os, "O_NOFOLLOW"):
        raise BuildError("Frozen smoke log cannot be created securely")
    try:
        descriptor = os.open(
            log_path,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | os.O_CLOEXEC
            | os.O_NOFOLLOW,
            0o600,
        )
    except OSError as exc:
        raise BuildError("Frozen smoke log cannot be created securely") from exc
    try:
        handle = os.fdopen(descriptor, "w+b", buffering=0)
    except Exception as exc:
        os.close(descriptor)
        raise BuildError("Frozen smoke log cannot be opened securely") from exc
    try:
        info = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_size != 0
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise BuildError("Frozen smoke log has unsafe metadata")
    except Exception:
        handle.close()
        raise
    return handle, (info.st_dev, info.st_ino)


def _frozen_log_metadata(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read_bound_frozen_log(
    log_handle: Any,
    log_path: Path,
    identity: tuple[int, int],
) -> tuple[str, bytes | None]:
    try:
        before = os.fstat(log_handle.fileno())
        path_before = log_path.lstat()
        if (
            (before.st_dev, before.st_ino) != identity
            or (path_before.st_dev, path_before.st_ino) != identity
            or _frozen_log_metadata(before) != _frozen_log_metadata(path_before)
        ):
            return "log-changed", None
        if (
            not stat.S_ISREG(before.st_mode)
            or not stat.S_ISREG(path_before.st_mode)
            or stat.S_ISLNK(path_before.st_mode)
            or before.st_uid != os.geteuid()
            or path_before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or path_before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or stat.S_IMODE(path_before.st_mode) != 0o600
            or before.st_size > MAX_FROZEN_START_LOG_BYTES
        ):
            return "log-unsafe", None
        os.lseek(log_handle.fileno(), 0, os.SEEK_SET)
        raw = bytearray()
        while len(raw) <= MAX_FROZEN_START_LOG_BYTES:
            chunk = os.read(
                log_handle.fileno(),
                min(64 * 1024, MAX_FROZEN_START_LOG_BYTES + 1 - len(raw)),
            )
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(log_handle.fileno())
        path_after = log_path.lstat()
        if (
            len(raw) > MAX_FROZEN_START_LOG_BYTES
            or len(raw) != before.st_size
            or _frozen_log_metadata(after) != _frozen_log_metadata(before)
            or _frozen_log_metadata(path_after)
            != _frozen_log_metadata(path_before)
            or _frozen_log_metadata(after) != _frozen_log_metadata(path_after)
        ):
            return "log-changed", None
    except (OSError, ValueError):
        return "log-unavailable", None
    return "ok", bytes(raw)


def _frozen_start_failure_category(
    log_handle: Any,
    log_path: Path,
    identity: tuple[int, int],
) -> str:
    """Classify a failed frozen start without exposing its captured output."""

    status, raw = _read_bound_frozen_log(log_handle, log_path, identity)
    if status != "ok" or raw is None:
        return status
    if not raw:
        return "no-output"
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return "log-non-utf8"

    if "ModuleNotFoundError: No module named" in text:
        return "module-not-found"
    if "ImportError: cannot import name" in text:
        return "import-error"
    if "AttributeError: module" in text and "has no attribute" in text:
        return "attribute-error"
    if "lcf-service: desktop transport setup failed" in text:
        return "desktop-transport"
    if "Traceback (most recent call last):" in text:
        return "python-traceback"
    return "unclassified"


def _wait_for_socket(
    socket_path: Path,
    process: subprocess.Popen[Any],
    log_handle: Any,
    log_path: Path,
    log_identity: tuple[int, int],
) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            category = _frozen_start_failure_category(
                log_handle,
                log_path,
                log_identity,
            )
            raise BuildError(
                "Frozen sidecar exited before its UDS became ready "
                f"(exit={return_code}; category={category})"
            )
        try:
            info = socket_path.lstat()
        except FileNotFoundError:
            time.sleep(0.05)
            continue
        except OSError as exc:
            raise BuildError("Frozen sidecar socket cannot be inspected") from exc
        if (
            stat.S_ISSOCK(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_uid == os.geteuid()
            and info.st_nlink == 1
        ):
            return_code = process.poll()
            if return_code is not None:
                category = _frozen_start_failure_category(
                    log_handle,
                    log_path,
                    log_identity,
                )
                raise BuildError(
                    "Frozen sidecar exited before its UDS became ready "
                    f"(exit={return_code}; category={category})"
                )
            return
        raise BuildError("Frozen sidecar created an unsafe socket")
    raise BuildError("Frozen sidecar UDS readiness timed out")


def _canonical_private_smoke_root(raw_root: str) -> Path:
    lexical_root = Path(raw_root)
    if not lexical_root.is_absolute() or ".." in lexical_root.parts:
        raise BuildError("Frozen smoke root is not an absolute path")
    try:
        lexical_info = lexical_root.lstat()
        canonical_root = lexical_root.resolve(strict=True)
        canonical_info = canonical_root.lstat()
    except OSError as exc:
        raise BuildError("Frozen smoke root cannot be inspected") from exc
    if (
        not stat.S_ISDIR(lexical_info.st_mode)
        or stat.S_ISLNK(lexical_info.st_mode)
        or not stat.S_ISDIR(canonical_info.st_mode)
        or stat.S_ISLNK(canonical_info.st_mode)
        or (lexical_info.st_dev, lexical_info.st_ino)
        != (canonical_info.st_dev, canonical_info.st_ino)
        or lexical_info.st_uid != os.geteuid()
        or canonical_info.st_uid != os.geteuid()
        or stat.S_IMODE(lexical_info.st_mode) != 0o700
        or stat.S_IMODE(canonical_info.st_mode) != 0o700
        or canonical_root.resolve(strict=True) != canonical_root
    ):
        raise BuildError("Frozen smoke root is not a private canonical directory")
    return canonical_root


def _frozen_socket_paths(smoke_root: Path) -> tuple[Path, Path, Path]:
    runtime_directory = smoke_root / "r"
    socket_path = runtime_directory / "s"
    broker_socket_path = runtime_directory / "b"
    if (
        not smoke_root.is_absolute()
        or ".." in smoke_root.parts
        or socket_path == broker_socket_path
    ):
        raise BuildError("Frozen smoke socket root is invalid")
    for candidate in (socket_path, broker_socket_path):
        try:
            encoded = str(candidate).encode("utf-8")
        except UnicodeEncodeError as exc:
            raise BuildError("Frozen smoke socket path is not UTF-8") from exc
        if b"\0" in encoded or len(encoded) > MAX_FROZEN_UDS_PATH_BYTES:
            raise BuildError("Frozen smoke socket path exceeds the runtime bound")
    return runtime_directory, socket_path, broker_socket_path


def _duplicate_high(descriptor: int) -> int:
    try:
        import fcntl
    except ImportError as exc:
        raise BuildError("Frozen fd smoke requires POSIX descriptor controls") from exc
    command = getattr(fcntl, "F_DUPFD_CLOEXEC", fcntl.F_DUPFD)
    return int(fcntl.fcntl(descriptor, command, 10))


def _desktop_retrieval_protocol(versions: Mapping[str, Any]) -> str:
    protocol = _mapping(
        versions.get("desktopRetrievalProtocol"),
        "canonical desktop retrieval protocol",
    )
    major = protocol.get("major")
    minor = protocol.get("minor")
    if (
        not isinstance(major, int)
        or isinstance(major, bool)
        or major < 0
        or not isinstance(minor, int)
        or isinstance(minor, bool)
        or minor < 0
    ):
        raise BuildError("Canonical desktop retrieval protocol is malformed")
    return f"{major}.{minor}"


SavedControlFd = tuple[int | None, bool | None]


def _open_child_control_fds() -> tuple[
    dict[int, int],
    dict[int, SavedControlFd],
]:
    """Install pipe read ends at child fd3/fd4 and return high write ends."""

    saved: dict[int, SavedControlFd] = {}
    writers: dict[int, int] = {}
    try:
        for target in (3, 4):
            try:
                inheritable = os.get_inheritable(target)
                saved[target] = (
                    _duplicate_high(target),
                    inheritable,
                )
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    raise BuildError(
                        "Unable to preserve parent control descriptor"
                    ) from exc
                saved[target] = (None, None)
        for target in (3, 4):
            raw_read, raw_write = os.pipe()
            try:
                read_fd = _duplicate_high(raw_read)
                write_fd = _duplicate_high(raw_write)
            finally:
                os.close(raw_read)
                os.close(raw_write)
            try:
                os.dup2(read_fd, target, inheritable=True)
            finally:
                os.close(read_fd)
            writers[target] = write_fd
    except Exception:
        for descriptor in writers.values():
            os.close(descriptor)
        _restore_parent_control_fds(saved)
        raise
    return writers, saved


def _restore_parent_control_fds(
    saved: Mapping[int, SavedControlFd],
) -> None:
    for target, (saved_descriptor, inheritable) in saved.items():
        try:
            os.close(target)
        except OSError:
            pass
        if saved_descriptor is not None:
            try:
                os.dup2(
                    saved_descriptor,
                    target,
                    inheritable=bool(inheritable),
                )
            finally:
                os.close(saved_descriptor)


def run_frozen_smoke(
    bundle: Path,
    versions: Mapping[str, Any],
    *,
    source_date_epoch: int,
) -> dict[str, Any]:
    """Exercise the frozen API and a real domain lifecycle under PATH traps."""

    executable = (bundle / "lcf-service").resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="lcf-", dir="/tmp") as raw_root:
        # macOS commonly exposes its temporary root through /var while the
        # canonical inode lives below /private/var. Retrieval sockets reject
        # that lexical alias, so derive every child path from the verified
        # canonical directory without weakening the runtime validation.
        smoke_root = _canonical_private_smoke_root(raw_root)
        trap_directory = smoke_root / "trap"
        trap_marker = smoke_root / "path-used.log"
        source_root = smoke_root / "source-root"
        source_root.mkdir(mode=0o700)
        source_repository = source_root / "fixture"
        _create_smoke_source_repository(
            source_repository,
            source_date_epoch=source_date_epoch,
        )
        _create_path_trap(trap_directory, trap_marker)
        environment = _trap_environment(
            trap_directory,
            trap_marker,
            local_source_root=source_root,
        )

        version = _run_frozen_command(
            executable,
            ("version",),
            environment=environment,
        )
        if (
            version.returncode != 0
            or version.stdout != f"{versions.get('productVersion')}\n"
            or version.stderr
        ):
            raise BuildError("Frozen version command differs from the product lock")

        doctor_result = _run_frozen_command(
            executable,
            ("doctor",),
            environment=environment,
        )
        try:
            doctor = json.loads(doctor_result.stdout)
        except json.JSONDecodeError as exc:
            raise BuildError("Frozen doctor output is not canonical JSON") from exc
        if (
            doctor_result.returncode != 0
            or doctor_result.stderr
            or not isinstance(doctor, dict)
            or doctor.get("ok") is not True
            or doctor.get("service") != "local-context-forge"
            or doctor.get("role") != "python-sidecar"
            or doctor.get("app_version") != versions.get("productVersion")
            or doctor.get("sidecar_version") != versions.get("productVersion")
            or doctor.get("python_distribution_version")
            != versions.get("pythonDistributionVersion")
            or doctor.get("protocol") != versions.get("desktopProtocol")
            or doctor.get("schema_version") != versions.get("databaseSchema")
            or _mapping(doctor.get("checks"), "frozen doctor checks").get(
                "python_runtime"
            )
            != "ok"
            or _mapping(doctor.get("checks"), "frozen doctor checks").get(
                "unix_domain_sockets"
            )
            != "ok"
        ):
            raise BuildError("Frozen doctor command differs from canonical versions")

        runtime_directory, socket_path, broker_socket_path = _frozen_socket_paths(
            smoke_root
        )
        data_directory = smoke_root / "data"
        runtime_directory.mkdir(mode=0o700)
        data_directory.mkdir(mode=0o700)
        broker_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            broker_listener.bind(str(broker_socket_path))
            broker_socket_path.chmod(0o600)
            broker_listener.listen(4)
        except Exception:
            broker_listener.close()
            raise
        launch_id = str(uuid.uuid4())
        token = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode(
            "ascii"
        )
        capability = base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).rstrip(b"=").decode("ascii")
        if len(token) != 43 or len(capability) != 43 or capability == token:
            raise BuildError("Frozen smoke generated a noncanonical capability")
        protocol = _desktop_retrieval_protocol(versions)
        broker_stop = threading.Event()
        broker_requests: deque[dict[str, Any]] = deque()
        broker_failures: deque[str] = deque()
        broker_thread = threading.Thread(
            target=_serve_smoke_broker,
            kwargs={
                "listener": broker_listener,
                "capability": capability,
                "launch_id": launch_id,
                "protocol": protocol,
                "stop": broker_stop,
                "requests": broker_requests,
                "failures": broker_failures,
            },
            name="lcf-frozen-smoke-broker",
            daemon=True,
        )
        broker_started = False
        broker_shutdown_failed = False
        writers: dict[int, int] = {}
        saved_descriptors: dict[int, SavedControlFd] = {}
        log_path = smoke_root / "sidecar.log"
        log_handle: Any | None = None
        log_identity: tuple[int, int] | None = None
        process: subprocess.Popen[Any] | None = None
        try:
            writers, saved_descriptors = _open_child_control_fds()
            broker_thread.start()
            broker_started = True
            log_handle, log_identity = _open_frozen_log(log_path)
            process = subprocess.Popen(
                (
                    str(executable),
                    "api",
                    "--uds",
                    str(socket_path),
                    "--launch-id",
                    launch_id,
                    "--token-fd",
                    "3",
                    "--data-dir",
                    str(data_directory),
                    "--local-source-root",
                    str(source_root),
                    "--retrieval-broker-uds",
                    str(broker_socket_path),
                    "--retrieval-capability-fd",
                    "4",
                ),
                cwd=executable.parent,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                pass_fds=(3, 4),
                close_fds=True,
            )
            _restore_parent_control_fds(saved_descriptors)
            saved_descriptors = {}
            os.write(writers[3], token.encode("ascii") + b"\n")
            os.write(writers[4], capability.encode("ascii") + b"\n")
            os.close(writers.pop(4))
            _wait_for_socket(
                socket_path,
                process,
                log_handle,
                log_path,
                log_identity,
            )
            handshake = _http_json_over_uds(
                socket_path,
                "/api/desktop/handshake",
                check="handshake",
                token=token,
                launch_id=launch_id,
            )
            if (
                not isinstance(handshake, dict)
                or handshake.get("service") != "local-context-forge"
                or handshake.get("role") != "python-sidecar"
                or handshake.get("app_version") != versions.get("productVersion")
                or handshake.get("sidecar_version")
                != versions.get("productVersion")
                or handshake.get("protocol") != versions.get("desktopProtocol")
                or handshake.get("schema_version") != versions.get("databaseSchema")
                or handshake.get("launch_id") != launch_id
                or handshake.get("transport") != "uds"
                or not {
                    "desktop-handshake",
                    "health",
                    "library-api",
                }.issubset(set(handshake.get("capabilities", [])))
            ):
                raise BuildError("Frozen UDS handshake differs from the contract")
            health = _http_json_over_uds(
                socket_path,
                "/api/health",
                check="health",
                token=token,
                launch_id=launch_id,
            )
            if (
                not isinstance(health, dict)
                or health.get("status") != "ok"
                or health.get("service") != "local-context-forge"
                or health.get("version") != versions.get("productVersion")
            ):
                raise BuildError("Frozen UDS health differs from the contract")

            library = _http_json_over_uds(
                socket_path,
                "/api/libraries",
                check="library-create",
                token=token,
                launch_id=launch_id,
                method="POST",
                body={
                    "name": "Frozen Widget",
                    "source": str(source_repository),
                    "description": "Frozen packaging domain smoke",
                },
                expected_status=201,
            )
            if (
                not isinstance(library, dict)
                or not isinstance(library.get("id"), str)
                or re.fullmatch(r"[0-9a-f]{32}", library["id"]) is None
                or library.get("source") != str(source_repository)
            ):
                raise BuildError("Frozen domain smoke could not create a library")
            library_id = library["id"]
            job = _http_json_over_uds(
                socket_path,
                f"/api/libraries/{library_id}/ingest",
                check="library-ingest",
                token=token,
                launch_id=launch_id,
                method="POST",
                body={
                    "version": "1.0.0",
                    "provider": "mock",
                    "auto_publish": True,
                },
                expected_status=202,
            )
            if (
                not isinstance(job, dict)
                or not isinstance(job.get("id"), str)
                or re.fullmatch(r"[0-9a-f]{32}", job["id"]) is None
            ):
                raise BuildError("Frozen domain smoke could not enqueue ingestion")
            job_id = job["id"]
            job_deadline = time.monotonic() + 90
            while True:
                completed_job = _http_json_over_uds(
                    socket_path,
                    f"/api/jobs/{job_id}",
                    check="job-status",
                    token=token,
                    launch_id=launch_id,
                )
                if (
                    not isinstance(completed_job, dict)
                    or not isinstance(completed_job.get("status"), str)
                ):
                    raise BuildError("Frozen domain smoke returned an invalid job")
                if completed_job["status"] not in {
                    "queued",
                    "running",
                    "cancelling",
                }:
                    break
                if time.monotonic() >= job_deadline:
                    raise BuildError("Frozen domain ingestion did not finish")
                time.sleep(0.05)
            if completed_job["status"] != "completed":
                raise BuildError("Frozen domain ingestion or publication failed")
            job_result = completed_job.get("result")
            resolved_version = (
                job_result.get("version")
                if isinstance(job_result, dict)
                else None
            )
            if (
                not isinstance(job_result, dict)
                or job_result.get("auto_publish") is not True
                or not isinstance(resolved_version, str)
                or re.fullmatch(
                    r"1\.0\.0\+git\.[0-9a-f]{12}",
                    resolved_version,
                )
                is None
                or completed_job.get("effective_provider") != "mock"
            ):
                raise BuildError(
                    "Frozen domain job did not prove mock auto-publication"
                )

            pages = _http_json_over_uds(
                socket_path,
                f"/api/libraries/{library_id}/pages?version=1.0.0",
                check="pages",
                token=token,
                launch_id=launch_id,
            )
            if (
                not isinstance(pages, list)
                or not pages
                or not all(
                    isinstance(page, dict)
                    and isinstance(page.get("version"), str)
                    and page["version"] == resolved_version
                    and isinstance(page.get("published_at"), str)
                    and bool(page["published_at"])
                    for page in pages
                )
            ):
                raise BuildError("Frozen domain smoke did not publish pages")
            lint = _http_json_over_uds(
                socket_path,
                f"/api/libraries/{library_id}/lint?version=1.0.0",
                check="lint",
                token=token,
                launch_id=launch_id,
                method="POST",
            )
            if not isinstance(lint, dict) or lint.get("ok") is not True:
                raise BuildError("Frozen domain lint did not pass")
            published_library = _http_json_over_uds(
                socket_path,
                f"/api/libraries/{library_id}",
                check="library-publish",
                token=token,
                launch_id=launch_id,
            )
            if (
                not isinstance(published_library, dict)
                or published_library.get("default_version")
                != resolved_version
                or not isinstance(published_library.get("versions"), list)
                or not any(
                    isinstance(item, dict)
                    and item.get("version") == resolved_version
                    and item.get("status") == "published"
                    for item in published_library["versions"]
                )
            ):
                raise BuildError("Frozen domain version was not activated")
            post_publish_health = _http_json_over_uds(
                socket_path,
                "/api/health",
                check="post-publish-health",
                token=token,
                launch_id=launch_id,
            )
            if (
                not isinstance(post_publish_health, dict)
                or not isinstance(post_publish_health.get("qmd"), dict)
                or post_publish_health["qmd"].get("available") is not True
            ):
                raise BuildError(
                    "Frozen domain publication did not activate retrieval"
                )
            if broker_failures or not any(
                request.get("endpoint") == "/reconcile"
                and request.get("collections", 0) > 0
                for request in broker_requests
            ):
                raise BuildError(
                    "Frozen domain publication did not reconcile retrieval"
                )
            os.close(writers.pop(3))
            try:
                return_code = process.wait(timeout=20)
            except subprocess.TimeoutExpired as exc:
                raise BuildError("Frozen sidecar did not stop after parent EOF") from exc
            if return_code != 0:
                raise BuildError("Frozen sidecar exited unsuccessfully")
            if socket_path.exists() or socket_path.is_symlink():
                raise BuildError("Frozen sidecar did not remove its UDS")
            _assert_no_smoke_secrets(
                data_directory,
                (token, capability, launch_id),
            )
            log_status, frozen_log_bytes = _read_bound_frozen_log(
                log_handle,
                log_path,
                log_identity,
            )
            if log_status != "ok" or frozen_log_bytes is None:
                raise BuildError(
                    "Frozen smoke log could not be audited "
                    f"(category={log_status})"
                )
            try:
                frozen_log = frozen_log_bytes.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise BuildError("Frozen smoke log is not UTF-8") from exc
            if token in frozen_log or capability in frozen_log or launch_id in frozen_log:
                raise BuildError("Frozen sidecar logged session secrets")
        finally:
            if saved_descriptors:
                _restore_parent_control_fds(saved_descriptors)
            for descriptor in writers.values():
                os.close(descriptor)
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            broker_stop.set()
            broker_listener.close()
            if broker_started:
                broker_thread.join(timeout=2)
                broker_shutdown_failed = broker_thread.is_alive()
            if log_handle is not None:
                log_handle.close()
        if broker_shutdown_failed:
            raise BuildError("Frozen smoke broker did not stop")
        if trap_marker.exists() and trap_marker.stat().st_size:
            raise BuildError("Frozen sidecar invoked a forbidden PATH executable")
    return {
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


def normalize_tree(root: Path, source_date_epoch: int) -> None:
    """Normalize modes and mtimes without following bundle symlinks."""

    paths = [root, *sorted(root.rglob("*"), key=lambda path: path.as_posix())]
    for path in paths:
        try:
            info = path.lstat()
        except OSError as exc:
            raise BuildError("Staging changed during normalization") from exc
        if stat.S_ISLNK(info.st_mode):
            try:
                os.utime(
                    path,
                    (source_date_epoch, source_date_epoch),
                    follow_symlinks=False,
                )
            except (NotImplementedError, OSError) as exc:
                raise BuildError("Unable to normalize a staging symlink") from exc
            continue
        if stat.S_ISDIR(info.st_mode):
            path.chmod(0o755)
        elif stat.S_ISREG(info.st_mode):
            executable = bool(stat.S_IMODE(info.st_mode) & 0o111)
            path.chmod(0o755 if executable else 0o644)
        else:
            raise BuildError("Staging contains a special file")
        os.utime(path, (source_date_epoch, source_date_epoch))


def _exchange_paths(first: Path, second: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    encoded_first = os.fsencode(first)
    encoded_second = os.fsencode(second)
    if platform.system() == "Darwin":
        function = getattr(libc, "renameatx_np", None)
        if function is None:
            raise BuildError("Atomic rename swap is unavailable on Darwin")
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        result = function(-2, encoded_first, -2, encoded_second, 0x00000002)
    elif platform.system() == "Linux":
        function = getattr(libc, "renameat2", None)
        if function is None:
            raise BuildError("Atomic rename exchange is unavailable on Linux")
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        result = function(-100, encoded_first, -100, encoded_second, 0x2)
    else:
        raise BuildError("Atomic staging replacement is unsupported on this OS")
    if result != 0:
        error_number = ctypes.get_errno()
        raise BuildError("Atomic staging exchange failed") from OSError(
            error_number,
            os.strerror(error_number),
        )


def publish_staging(
    candidate: Path,
    destination: Path,
    *,
    verifier: Callable[[Path], Any],
) -> None:
    """Verify and atomically publish a directory, rolling back on recheck."""

    if not candidate.is_absolute() or not destination.is_absolute():
        raise BuildError("Atomic staging paths must be absolute")
    try:
        candidate_info = candidate.lstat()
    except OSError as exc:
        raise BuildError("Atomic staging candidate is missing") from exc
    if not stat.S_ISDIR(candidate_info.st_mode) or stat.S_ISLNK(
        candidate_info.st_mode
    ):
        raise BuildError("Atomic staging candidate must be a real directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if candidate.resolve() == destination.resolve(strict=False):
        raise BuildError("Atomic staging candidate and destination must differ")
    try:
        if candidate.stat().st_dev != destination.parent.stat().st_dev:
            raise BuildError("Atomic staging candidate must share destination filesystem")
    except OSError as exc:
        raise BuildError("Atomic staging filesystem cannot be inspected") from exc

    verifier(candidate)
    destination_existed = destination.exists()
    if destination_existed:
        destination_info = destination.lstat()
        if not stat.S_ISDIR(destination_info.st_mode) or stat.S_ISLNK(
            destination_info.st_mode
        ):
            raise BuildError("Existing staging destination must be a real directory")
        _exchange_paths(candidate, destination)
    else:
        os.rename(candidate, destination)
    try:
        verifier(destination)
    except Exception as verification_error:
        try:
            if destination_existed:
                _exchange_paths(candidate, destination)
            else:
                os.rename(destination, candidate)
        except Exception as rollback_error:
            raise BuildError(
                "Published staging failed verification and rollback"
            ) from rollback_error
        raise BuildError("Published staging failed its post-swap audit") from verification_error
    if destination_existed:
        shutil.rmtree(candidate)


def _preserve_evidence(evidence: Path, destination: Path) -> None:
    if not evidence.is_dir() or evidence.is_symlink():
        return

    def verify(candidate: Path) -> None:
        log = candidate / "pyinstaller.log"
        if not log.is_file() or log.is_symlink() or log.stat().st_size == 0:
            raise BuildError("Sanitized PyInstaller evidence is incomplete")

    publish_staging(
        evidence.resolve(),
        destination.resolve(),
        verifier=verify,
    )


def _build_manifest(
    *,
    bundle: Path,
    versions: Mapping[str, Any],
    toolchain: Mapping[str, Any],
    release: Mapping[str, Any],
    python_provenance: Mapping[str, Any],
    python_fingerprint: str,
    components: Sequence[Mapping[str, Any]],
    artifacts: Mapping[str, str],
    frozen_smoke: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        import audit_python_sidecar as audit
    except ImportError as exc:
        raise BuildError("Python sidecar auditor cannot be imported") from exc
    target = _mapping(toolchain.get("target"), "toolchain target")
    tools = _mapping(toolchain.get("tools"), "toolchain tools")
    files = audit.build_file_inventory(bundle)
    native = audit.scan_macho_inventory(bundle)
    audit.validate_native_inventory(bundle, native)
    return {
        "$schema": "python-sidecar-build-manifest.schema.json",
        "schemaVersion": 1,
        "kind": "local-context-forge-python-sidecar",
        "entrypoint": "lcf-service",
        "product": {
            "appVersion": versions.get("productVersion"),
            "pythonDistributionVersion": versions.get(
                "pythonDistributionVersion"
            ),
            "desktopProtocol": versions.get("desktopProtocol"),
            "databaseSchema": versions.get("databaseSchema"),
        },
        "target": {
            "os": target.get("os"),
            "architecture": target.get("architecture"),
        },
        "build": {
            **release,
            "uvVersion": tools.get("uv"),
            "pyinstallerVersion": tools.get("pyinstaller"),
            "pyinstallerHooksContribVersion": tools.get(
                "pyinstallerHooksContrib"
            ),
            "python": {
                **python_provenance,
                "installRootFingerprintSha256": python_fingerprint,
            },
            "inputDigests": audit.critical_input_digests(),
        },
        "components": list(components),
        "artifacts": dict(artifacts),
        "files": files,
        "native": native,
        "audit": {
            "status": "pass",
            "policyVersion": 1,
            "normalizedInventorySha256": audit.normalized_inventory_sha256(
                files,
                native,
            ),
            "frozenSmoke": dict(frozen_smoke),
        },
    }


def build_python_sidecar(
    *,
    destination: Path,
    evidence_destination: Path,
    environment: Mapping[str, str],
) -> dict[str, int]:
    try:
        import audit_python_sidecar as audit
    except ImportError as exc:
        raise BuildError("Python sidecar auditor cannot be imported") from exc

    toolchain = _load_json(TOOLCHAIN_LOCK, "Python toolchain lock")
    release = validate_release_environment(environment, toolchain)
    archive = Path(environment["LCF_PYTHON_DISTRIBUTION_ARCHIVE"])
    hash_manifest = Path(
        environment["LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST"]
    )
    python_provenance = verify_distribution_files(
        archive,
        hash_manifest,
        toolchain=toolchain,
    )
    install_root = Path(environment["LCF_PYTHON_INSTALL_ROOT"])
    python_fingerprint = verify_python_install_binding(
        install_root,
        toolchain=toolchain,
    )
    build_versions = parse_build_requirements()
    verify_build_tool_versions(toolchain, build_versions)
    uv_executable = Path(sys.executable).parent / "uv"
    verify_uv_lock(uv_executable)
    runtime_versions = runtime_dependency_versions()
    verify_runtime_dependencies(runtime_versions)
    versions = _load_json(VERSION_FILE, "Canonical runtime versions")

    destination = destination.resolve()
    evidence_destination = evidence_destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    raw_build_root = tempfile.mkdtemp(
        prefix=".python-sidecar-build-",
        dir=destination.parent,
    )
    build_root = Path(raw_build_root)
    evidence: Path | None = None
    try:
        bundle, evidence = run_pyinstaller(
            build_root=build_root,
            install_root=install_root,
            source_date_epoch=int(release["sourceDateEpoch"]),
            deployment_target=str(release["macosDeploymentTarget"]),
        )
        frozen_smoke = run_frozen_smoke(
            bundle,
            versions,
            source_date_epoch=int(release["sourceDateEpoch"]),
        )
        components = build_components(
            bundle=bundle,
            runtime_versions=runtime_versions,
            build_versions=build_versions,
        )
        artifacts = write_compliance_artifacts(
            bundle=bundle,
            components=components,
            repository_commit=str(release["repositoryCommit"]),
            source_date_epoch=int(release["sourceDateEpoch"]),
        )
        python_lock = _mapping(toolchain.get("python"), "Python toolchain entry")
        if (
            fingerprint_install_root(
                install_root,
                reviewed_broken_symlinks=_reviewed_broken_symlinks(python_lock),
            )
            != python_fingerprint
        ):
            raise BuildError("Pinned Python framework changed during the build")
        verify_repository_provenance(release)
        normalize_tree(bundle, int(release["sourceDateEpoch"]))
        manifest = _build_manifest(
            bundle=bundle,
            versions=versions,
            toolchain=toolchain,
            release=release,
            python_provenance=python_provenance,
            python_fingerprint=python_fingerprint,
            components=components,
            artifacts=artifacts,
            frozen_smoke=frozen_smoke,
        )
        manifest_path = bundle / audit.MANIFEST_NAME
        _write_canonical_json(manifest_path, manifest)
        manifest_path.chmod(0o644)
        os.utime(
            manifest_path,
            (
                int(release["sourceDateEpoch"]),
                int(release["sourceDateEpoch"]),
            ),
        )
        def final_verifier(candidate: Path) -> dict[str, int]:
            verify_repository_provenance(release)
            return audit.audit_bundle(candidate)

        summary = final_verifier(bundle)
        publish_staging(bundle, destination, verifier=final_verifier)
        return summary
    except Exception:
        if evidence is None:
            candidate = build_root / "evidence"
            if candidate.is_dir():
                evidence = candidate
        if evidence is not None:
            try:
                _preserve_evidence(evidence, evidence_destination)
            except Exception as preservation_error:
                raise BuildError(
                    "Python sidecar build failed and evidence preservation failed"
                ) from preservation_error
        raise
    finally:
        if build_root.exists():
            shutil.rmtree(build_root)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or verify the pinned darwin-arm64 Python sidecar"
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--verify-source-only",
        action="store_true",
        help="verify archive/hash manifest/pkg without executing or installing it",
    )
    modes.add_argument(
        "--extract-installer-package",
        action="store_true",
        help="verify source and extract only the locked pkg for explicit installation",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        help="absolute actions/python-versions archive path",
    )
    parser.add_argument(
        "--hash-manifest",
        type=Path,
        help="absolute release hashes.sha256 path",
    )
    parser.add_argument(
        "--installer-output",
        type=Path,
        default=REPOSITORY_ROOT
        / ".python-sidecar-build"
        / "python-3.13.14-macos11.pkg",
        help="absolute output used with --extract-installer-package",
    )
    parser.add_argument(
        "--staging",
        type=Path,
        default=DEFAULT_STAGING,
        help="atomically published onedir staging path",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=DEFAULT_EVIDENCE,
        help="sanitized evidence destination retained after a failed build",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.verify_source_only or arguments.extract_installer_package:
            if arguments.archive is None or arguments.hash_manifest is None:
                raise BuildError(
                    "source verification requires --archive and --hash-manifest"
                )
            if arguments.extract_installer_package:
                output = extract_reviewed_installer_package(
                    arguments.archive,
                    arguments.hash_manifest,
                    arguments.installer_output,
                )
                print(
                    json.dumps(
                        {
                            "installerPackage": str(output),
                            "installerPackageSha256": _sha256_file(output),
                            "status": "extracted",
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                )
                return 0
            provenance = verify_distribution_files(
                arguments.archive,
                arguments.hash_manifest,
            )
            print(
                json.dumps(
                    {
                        "archive": provenance["archiveName"],
                        "archiveSha256": provenance["archiveSha256"],
                        "installerPackageSha256": provenance[
                            "installerPackageSha256"
                        ],
                        "status": "verified",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0
        summary = build_python_sidecar(
            destination=arguments.staging,
            evidence_destination=arguments.evidence,
            environment=os.environ,
        )
    except (BuildError, audit_error_type()) as exc:
        print(f"python-sidecar build failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0


def audit_error_type() -> type[Exception]:
    """Avoid importing the platform auditor until error handling is needed."""

    try:
        import audit_python_sidecar as audit
    except ImportError:
        return BuildError
    return audit.AuditError


if __name__ == "__main__":
    raise SystemExit(main())

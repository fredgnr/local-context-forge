#!/usr/bin/env python3
"""Build the Python sidecar through an exact, private toolchain capability.

This outer driver is intentionally stdlib-only.  It is launched by the pinned
framework Python from the workflow's private exact-commit repository, creates
ephemeral bootstrap/final venvs below ``RUNNER_TEMP``, installs only hash-locked
wheels, seals the complete final venv before any installed build tool is used,
then starts the reviewed inner builder with held descriptors.  Every owned
toolchain byte is removed before this process returns or propagates a signal.

The threat boundary explicitly excludes an active same-UID writer after the
workflow has created and validated the random 0700 exact source/toolchain
roots.  Revalidation detects every observable identity/content drift; it does
not claim to defeat an unobservable same-UID ABA in a final pathname syscall.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPOSITORY_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

TOOLCHAIN_ROOT_PREFIX = "python-sidecar-toolchain-"
INSTALLER_ROOT_PREFIX = "lcf-python-installer."
TOOLCHAIN_EVIDENCE_SCHEMA = "python-sidecar-toolchain-evidence.json"
TOOLCHAIN_EVIDENCE_NAME = "python-build-toolchain.json"
BUILD_VENV_NAME = "build-venv"
BOOTSTRAP_VENV_NAME = "bootstrap-venv"
RUNTIME_REQUIREMENTS_NAME = "runtime-requirements.lock"
MAX_TREE_ENTRIES = 100_000
MAX_TREE_FILE_BYTES = 256 * 1024 * 1024
MAX_TREE_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_RUNTIME_LOCK_BYTES = 32 * 1024 * 1024
MAX_EVIDENCE_BYTES = 128 * 1024 * 1024
MAX_SUBPROCESS_OUTPUT_BYTES = 32 * 1024 * 1024
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_REVIEWED_FRAMEWORK_ROOT = PurePosixPath(
    "/Library/Frameworks/Python.framework/Versions/3.13"
)

SOURCE_INPUTS = (
    "Makefile",
    "backend/pyproject.toml",
    "backend/uv.lock",
    "backend/packaging/build-requirements.lock",
    "backend/packaging/lcf_sidecar.spec",
    "backend/packaging/python-sidecar-toolchain.lock.json",
    "runtime/python-sidecar-build-manifest.schema.json",
    "tools/audit_python_sidecar.py",
    "tools/bootstrap_python_sidecar.py",
    "tools/build_python_sidecar.py",
)

BUILD_TOOL_MANIFEST_KEYS = {
    "altgraph": "altgraphVersion",
    "macholib": "macholibVersion",
    "packaging": "packagingVersion",
    "pyinstaller": "pyinstallerVersion",
    "pyinstaller-hooks-contrib": "pyinstallerHooksContribVersion",
    "setuptools": "setuptoolsVersion",
    "uv": "uvVersion",
}

RELEASE_ENVIRONMENT_KEYS = frozenset(
    {
        "GITHUB_ACTIONS",
        "RUNNER_OS",
        "RUNNER_ARCH",
        "ImageOS",
        "ImageVersion",
        "LCF_SOURCE_SHA",
        "LCF_SOURCE_TREE",
        "LCF_SOURCE_DATE_EPOCH",
        "LCF_PYTHON_DISTRIBUTION_ARCHIVE",
        "LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST",
        "LCF_PYTHON_INSTALL_ROOT",
        "LCF_REVIEWED_BUILD_PYTHON",
        "LCF_REVIEWED_SOURCE_ROOT",
        "RUNNER_TEMP",
    }
)


class ToolchainBootstrapError(RuntimeError):
    """Raised when the exact toolchain cannot be proven or cleaned."""


@dataclass(frozen=True)
class _BoundFile:
    path: Path
    descriptor: int
    identity: tuple[int, ...]
    size: int
    sha256: str


@dataclass(frozen=True)
class InstalledTreeSeal:
    entries: tuple[dict[str, Any], ...]
    content_sha256: str
    identity_sha256: str


@dataclass
class _ToolchainRoot:
    parent: Path
    parent_descriptor: int
    parent_snapshot: Any
    path: Path
    name: str
    descriptor: int
    snapshot: Any
    child_descriptors: list[int] = field(default_factory=list)
    closed: bool = False


@dataclass
class _SourceSeal:
    root: Path
    descriptor: int
    identity: tuple[int, ...]
    repository_commit: str
    repository_tree: str
    source_snapshot_sha256: str
    files: tuple[_BoundFile, ...]


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _stable_directory_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
    )


def _read_regular_descriptor(
    descriptor: int,
    *,
    expected_size: int,
    maximum_size: int,
    error_message: str,
) -> bytes:
    if expected_size < 0 or expected_size > maximum_size:
        raise ToolchainBootstrapError(error_message)
    chunks: list[bytes] = []
    offset = 0
    try:
        while offset < expected_size:
            chunk = os.pread(
                descriptor,
                min(1024 * 1024, expected_size - offset),
                offset,
            )
            if not chunk:
                raise ToolchainBootstrapError(error_message)
            chunks.append(chunk)
            offset += len(chunk)
        if os.pread(descriptor, 1, expected_size):
            raise ToolchainBootstrapError(error_message)
    except ToolchainBootstrapError:
        raise
    except OSError as exc:
        raise ToolchainBootstrapError(error_message) from exc
    return b"".join(chunks)


def _open_bound_file(
    path: Path,
    *,
    maximum_size: int,
    error_message: str,
) -> _BoundFile:
    descriptor: int | None = None
    try:
        if not path.is_absolute():
            raise ToolchainBootstrapError(error_message)
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        before = os.fstat(descriptor)
        path_before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(path_before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o022
            or _identity(before) != _identity(path_before)
        ):
            raise ToolchainBootstrapError(error_message)
        payload = _read_regular_descriptor(
            descriptor,
            expected_size=before.st_size,
            maximum_size=maximum_size,
            error_message=error_message,
        )
        after = os.fstat(descriptor)
        path_after = path.lstat()
        if _identity(after) != _identity(before) or _identity(path_after) != _identity(before):
            raise ToolchainBootstrapError(error_message)
        result = _BoundFile(
            path=path,
            descriptor=descriptor,
            identity=_identity(after),
            size=after.st_size,
            sha256=hashlib.sha256(payload).hexdigest(),
        )
        descriptor = None
        return result
    except ToolchainBootstrapError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ToolchainBootstrapError(error_message) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _revalidate_bound_file(
    bound: _BoundFile,
    *,
    maximum_size: int,
    error_message: str,
) -> None:
    try:
        before = os.fstat(bound.descriptor)
        path_before = bound.path.lstat()
        if _identity(before) != bound.identity or _identity(path_before) != bound.identity:
            raise ToolchainBootstrapError(error_message)
        payload = _read_regular_descriptor(
            bound.descriptor,
            expected_size=bound.size,
            maximum_size=maximum_size,
            error_message=error_message,
        )
        after = os.fstat(bound.descriptor)
        path_after = bound.path.lstat()
        if (
            _identity(after) != bound.identity
            or _identity(path_after) != bound.identity
            or hashlib.sha256(payload).hexdigest() != bound.sha256
        ):
            raise ToolchainBootstrapError(error_message)
    except ToolchainBootstrapError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ToolchainBootstrapError(error_message) from exc


def _private_canonical_directory(
    raw: str,
    *,
    expected_mode: int | None,
    error_message: str,
) -> tuple[Path, int, tuple[int, ...]]:
    descriptor: int | None = None
    try:
        lexical = Path(raw)
        if not lexical.is_absolute() or ".." in lexical.parts:
            raise ToolchainBootstrapError(error_message)
        lexical_info = lexical.lstat()
        canonical = lexical.resolve(strict=True)
        canonical_info = canonical.lstat()
        descriptor = os.open(
            canonical,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        held = os.fstat(descriptor)
        if (
            canonical != lexical
            or not stat.S_ISDIR(lexical_info.st_mode)
            or stat.S_ISLNK(lexical_info.st_mode)
            or not stat.S_ISDIR(held.st_mode)
            or _identity(lexical_info) != _identity(canonical_info)
            or _identity(canonical_info) != _identity(held)
            or held.st_uid != os.geteuid()
            or (
                stat.S_IMODE(held.st_mode) != expected_mode
                if expected_mode is not None
                else bool(stat.S_IMODE(held.st_mode) & 0o022)
            )
        ):
            raise ToolchainBootstrapError(error_message)
        result = (canonical, descriptor, _identity(held))
        descriptor = None
        return result
    except ToolchainBootstrapError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ToolchainBootstrapError(error_message) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _validate_source_root(
    environment: Mapping[str, str],
    build: Any,
) -> _SourceSeal:
    raw_root = environment.get("LCF_REVIEWED_SOURCE_ROOT", "")
    root, descriptor, identity = _private_canonical_directory(
        raw_root,
        expected_mode=0o700,
        error_message="Reviewed exact source root is unavailable",
    )
    files: list[_BoundFile] = []
    try:
        cwd = Path.cwd().resolve(strict=True)
        if root != REPOSITORY_ROOT or root != cwd:
            raise ToolchainBootstrapError(
                "Python sidecar bootstrap must run from the reviewed exact source root"
            )
        commit = environment.get("LCF_SOURCE_SHA", "").lower()
        tree = environment.get("LCF_SOURCE_TREE", "").lower()
        if COMMIT_PATTERN.fullmatch(commit) is None or COMMIT_PATTERN.fullmatch(tree) is None:
            raise ToolchainBootstrapError("Reviewed exact source identity is malformed")
        state = build._validate_repository_state(
            {"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree},
            repository_root=root,
        )
        if (
            state.get("repositoryCommit") != commit
            or state.get("repositoryTree") != tree
        ):
            raise ToolchainBootstrapError("Reviewed exact source identity changed")
        for relative in SOURCE_INPUTS:
            files.append(
                _open_bound_file(
                    root / relative,
                    maximum_size=MAX_TREE_FILE_BYTES,
                    error_message="Reviewed exact source input is unsafe",
                )
            )
        return _SourceSeal(
            root=root,
            descriptor=descriptor,
            identity=identity,
            repository_commit=commit,
            repository_tree=tree,
            source_snapshot_sha256=str(state["sourceSnapshotSha256"]),
            files=tuple(files),
        )
    except BaseException:
        for item in files:
            try:
                os.close(item.descriptor)
            except OSError:
                pass
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _revalidate_source_seal(seal: _SourceSeal, build: Any) -> None:
    try:
        held = os.fstat(seal.descriptor)
        observed = seal.root.lstat()
        if _identity(held) != seal.identity or _identity(observed) != seal.identity:
            raise ToolchainBootstrapError("Reviewed exact source root changed")
        for item in seal.files:
            _revalidate_bound_file(
                item,
                maximum_size=MAX_TREE_FILE_BYTES,
                error_message="Reviewed exact source input changed",
            )
        state = build._validate_repository_state(
            {
                "LCF_SOURCE_SHA": seal.repository_commit,
                "LCF_SOURCE_TREE": seal.repository_tree,
            },
            repository_root=seal.root,
        )
        if state.get("sourceSnapshotSha256") != seal.source_snapshot_sha256:
            raise ToolchainBootstrapError("Reviewed exact source content changed")
    except ToolchainBootstrapError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ToolchainBootstrapError("Reviewed exact source root changed") from exc


@contextlib.contextmanager
def _held_toolchain_root(
    parent: Path,
    build: Any,
    *,
    prefix: str = TOOLCHAIN_ROOT_PREFIX,
) -> Any:
    parent_descriptor: int | None = None
    root_descriptor: int | None = None
    capability: _ToolchainRoot | None = None
    primary_error: BaseException | None = None
    try:
        parent_descriptor = os.open(
            parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        parent_snapshot = build._capture_bound_directory(
            parent_descriptor,
            parent,
            parent_descriptor=None,
            relative_name=None,
            expected=None,
            expected_mode=None,
            exact_entries=None,
            error_message="Python toolchain parent capability is unsafe",
        )
        parent_info = os.fstat(parent_descriptor)
        if (
            parent_info.st_uid != os.geteuid()
            or stat.S_IMODE(parent_info.st_mode) & 0o022
        ):
            raise ToolchainBootstrapError(
                "Python toolchain parent capability is unsafe"
            )
        if not prefix or "/" in prefix or "\x00" in prefix:
            raise ToolchainBootstrapError(
                "Python capability prefix is unsafe"
            )
        name = f"{prefix}{secrets.token_hex(16)}"
        with build._defer_publish_signals():
            root_descriptor, root_snapshot = build._create_bound_child_directory(
                parent_descriptor=parent_descriptor,
                parent_path=parent,
                name=name,
                mode=0o700,
                error_message="Python toolchain capability cannot be created",
            )
            capability = _ToolchainRoot(
                parent=parent,
                parent_descriptor=parent_descriptor,
                parent_snapshot=parent_snapshot,
                path=parent / name,
                name=name,
                descriptor=root_descriptor,
                snapshot=root_snapshot,
            )
        yield capability
    except BaseException as exc:
        primary_error = exc

    cleanup_error: BaseException | None = None
    try:
        with build._defer_publish_signals(preserve_error=primary_error):
            if capability is not None:
                for descriptor in capability.child_descriptors:
                    try:
                        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                            _make_installed_tree_cleanup_writable(descriptor)
                    except (OSError, ToolchainBootstrapError) as exc:
                        cleanup_error = cleanup_error or exc
                for descriptor in reversed(capability.child_descriptors):
                    try:
                        os.close(descriptor)
                    except OSError as exc:
                        cleanup_error = cleanup_error or exc
                capability.child_descriptors.clear()
                if cleanup_error is None:
                    build._rollback_bound_directory(
                        parent_descriptor=capability.parent_descriptor,
                        parent_path=capability.parent,
                        name=capability.name,
                        descriptor=capability.descriptor,
                        snapshot=capability.snapshot,
                        error_message="Python toolchain capability cleanup failed",
                    )
                    try:
                        os.stat(
                            capability.name,
                            dir_fd=capability.parent_descriptor,
                            follow_symlinks=False,
                        )
                    except FileNotFoundError:
                        pass
                    except OSError as exc:
                        cleanup_error = cleanup_error or exc
                    else:
                        cleanup_error = cleanup_error or ToolchainBootstrapError(
                            "Python toolchain capability cleanup left a residue"
                        )
                capability.closed = True
            elif root_descriptor is not None:
                cleanup_error = ToolchainBootstrapError(
                    "Python toolchain capability cleanup failed"
                )
            for descriptor in (root_descriptor, parent_descriptor):
                if descriptor is None:
                    continue
                try:
                    os.close(descriptor)
                except OSError as exc:
                    cleanup_error = cleanup_error or exc
    except BaseException as exc:
        cleanup_error = cleanup_error or exc
    if cleanup_error is not None:
        if primary_error is not None:
            raise ToolchainBootstrapError(
                "Python toolchain failed and exact cleanup failed"
            ) from primary_error
        raise ToolchainBootstrapError(
            "Python toolchain capability cleanup failed"
        ) from cleanup_error
    if primary_error is not None:
        raise primary_error


def _create_private_child(
    capability: _ToolchainRoot,
    name: str,
    build: Any,
) -> tuple[Path, int, Any]:
    descriptor: int | None = None
    snapshot: Any = None
    try:
        with build._defer_publish_signals():
            descriptor, snapshot = build._create_bound_child_directory(
                parent_descriptor=capability.descriptor,
                parent_path=capability.path,
                name=name,
                mode=0o700,
                error_message="Python toolchain child capability cannot be created",
            )
            capability.child_descriptors.append(descriptor)
        return capability.path / name, descriptor, snapshot
    except BaseException:
        if descriptor is not None and descriptor not in capability.child_descriptors:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


def _safe_symlink_target(
    relative: str,
    target: str,
    reviewed_framework_root: PurePosixPath,
) -> bool:
    if not target or "\x00" in target or "\\" in target:
        return False
    target_path = PurePosixPath(target)
    if target_path.is_absolute():
        # Standard venv links may target the pinned Python framework.  The
        # framework has an independent complete fingerprint in the manifest.
        raw_parts = target.split("/")
        if raw_parts[0] != "" or any(
            part in {"", ".", ".."} for part in raw_parts[1:]
        ):
            return False
        try:
            target_path.relative_to(reviewed_framework_root)
        except ValueError:
            return False
        return target_path != reviewed_framework_root
    parts = list(PurePosixPath(relative).parent.parts)
    for part in target_path.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return False
            parts.pop()
        else:
            parts.append(part)
    return bool(parts)


def _inventory_installed_tree(
    root: Path,
    descriptor: int,
    *,
    require_read_only: bool,
    reviewed_framework_root: PurePosixPath = DEFAULT_REVIEWED_FRAMEWORK_ROOT,
) -> InstalledTreeSeal:
    content: list[dict[str, Any]] = []
    identities: list[tuple[Any, ...]] = []
    total_size = 0

    def visit(directory_descriptor: int, relative: str, depth: int) -> None:
        nonlocal total_size
        if depth > 128:
            raise ToolchainBootstrapError("Installed toolchain tree exceeds its depth bound")
        try:
            names = tuple(sorted(os.listdir(directory_descriptor)))
        except OSError as exc:
            raise ToolchainBootstrapError("Installed toolchain tree cannot be inventoried") from exc
        for name in names:
            if not name or "/" in name or "\x00" in name:
                raise ToolchainBootstrapError("Installed toolchain tree contains an unsafe name")
            path = f"{relative}/{name}" if relative else name
            try:
                before = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
            except OSError as exc:
                raise ToolchainBootstrapError("Installed toolchain tree changed") from exc
            mode = stat.S_IMODE(before.st_mode)
            is_symlink = stat.S_ISLNK(before.st_mode)
            if (
                before.st_uid != os.geteuid()
                or before.st_gid != os.getegid()
                or (
                    not is_symlink
                    and (
                        mode & 0o7000
                        or mode & 0o022
                        or (require_read_only and mode & 0o200)
                    )
                )
            ):
                raise ToolchainBootstrapError("Installed toolchain tree has unsafe ownership or mode")
            common = {"path": path, "mode": f"{mode:04o}"}
            if stat.S_ISREG(before.st_mode):
                if (
                    before.st_nlink != 1
                    or before.st_size > MAX_TREE_FILE_BYTES
                    or (
                        require_read_only
                        and mode not in {0o400, 0o444, 0o500, 0o555}
                    )
                ):
                    raise ToolchainBootstrapError("Installed toolchain file is unsafe")
                file_descriptor: int | None = None
                try:
                    file_descriptor = os.open(
                        name,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=directory_descriptor,
                    )
                    opened = os.fstat(file_descriptor)
                    if _identity(opened) != _identity(before):
                        raise ToolchainBootstrapError("Installed toolchain file changed")
                    payload = _read_regular_descriptor(
                        file_descriptor,
                        expected_size=before.st_size,
                        maximum_size=MAX_TREE_FILE_BYTES,
                        error_message="Installed toolchain file changed",
                    )
                    after = os.fstat(file_descriptor)
                    relative_after = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if _identity(after) != _identity(before) or _identity(relative_after) != _identity(before):
                        raise ToolchainBootstrapError("Installed toolchain file changed")
                finally:
                    if file_descriptor is not None:
                        os.close(file_descriptor)
                total_size += before.st_size
                content.append(
                    {
                        **common,
                        "type": "file",
                        "size": before.st_size,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )
            elif stat.S_ISDIR(before.st_mode) and not stat.S_ISLNK(before.st_mode):
                if require_read_only and mode not in {0o500, 0o555}:
                    raise ToolchainBootstrapError(
                        "Installed toolchain directory mode is unsafe"
                    )
                child = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory_descriptor,
                )
                try:
                    opened = os.fstat(child)
                    if _identity(opened) != _identity(before):
                        raise ToolchainBootstrapError("Installed toolchain directory changed")
                    content.append({**common, "type": "directory", "size": 0})
                    identities.append((path, "directory", *_identity(opened)))
                    visit(child, path, depth + 1)
                    after = os.fstat(child)
                    relative_after = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if _identity(after) != _identity(opened) or _identity(relative_after) != _identity(opened):
                        raise ToolchainBootstrapError("Installed toolchain directory changed")
                finally:
                    os.close(child)
                if len(content) > MAX_TREE_ENTRIES:
                    raise ToolchainBootstrapError("Installed toolchain tree exceeds its entry bound")
                continue
            elif stat.S_ISLNK(before.st_mode):
                if before.st_nlink != 1 or mode != 0o777:
                    raise ToolchainBootstrapError("Installed toolchain symlink is unsafe")
                target = os.readlink(name, dir_fd=directory_descriptor)
                target_bytes = target.encode("utf-8", errors="strict")
                if not _safe_symlink_target(
                    path,
                    target,
                    reviewed_framework_root,
                ):
                    raise ToolchainBootstrapError("Installed toolchain symlink escapes its safe roots")
                total_size += len(target_bytes)
                content.append(
                    {
                        **common,
                        "type": "symlink",
                        "size": len(target_bytes),
                        "target": target,
                    }
                )
            else:
                raise ToolchainBootstrapError("Installed toolchain tree contains a special file")
            identities.append((path, content[-1]["type"], *_identity(before)))
            if len(content) > MAX_TREE_ENTRIES or total_size > MAX_TREE_TOTAL_BYTES:
                raise ToolchainBootstrapError("Installed toolchain tree exceeds its size bound")

    try:
        root_before = os.fstat(descriptor)
        root_path_before = root.lstat()
        root_mode = stat.S_IMODE(root_before.st_mode)
        if (
            not stat.S_ISDIR(root_before.st_mode)
            or stat.S_ISLNK(root_path_before.st_mode)
            or _identity(root_before) != _identity(root_path_before)
            or root_before.st_uid != os.geteuid()
            or root_before.st_gid != os.getegid()
            or root_mode & 0o022
            or (require_read_only and root_mode & 0o200)
        ):
            raise ToolchainBootstrapError("Installed toolchain root is unsafe")
        content.append(
            {"path": ".", "type": "directory", "mode": f"{root_mode:04o}", "size": 0}
        )
        identities.append((".", "directory", *_identity(root_before)))
        visit(descriptor, "", 0)
        root_after = os.fstat(descriptor)
        root_path_after = root.lstat()
        if _identity(root_after) != _identity(root_before) or _identity(root_path_after) != _identity(root_before):
            raise ToolchainBootstrapError("Installed toolchain root changed")
    except ToolchainBootstrapError:
        raise
    except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
        raise ToolchainBootstrapError("Installed toolchain tree cannot be inventoried") from exc
    content.sort(key=lambda item: str(item["path"]))
    identities.sort(key=lambda item: str(item[0]))
    content_bytes = _canonical_json_bytes(
        {"schemaVersion": 1, "entries": content}
    )
    identity_bytes = _canonical_json_bytes(
        {"schemaVersion": 1, "entries": identities}
    )
    return InstalledTreeSeal(
        entries=tuple(content),
        content_sha256=hashlib.sha256(content_bytes).hexdigest(),
        identity_sha256=hashlib.sha256(identity_bytes).hexdigest(),
    )


def _chmod_installed_tree_read_only(descriptor: int, depth: int = 0) -> None:
    if depth > 128:
        raise ToolchainBootstrapError("Installed toolchain tree exceeds its depth bound")
    try:
        names = tuple(sorted(os.listdir(descriptor)))
        for name in names:
            before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if before.st_uid != os.geteuid() or before.st_gid != os.getegid():
                raise ToolchainBootstrapError("Installed toolchain ownership changed")
            if stat.S_ISREG(before.st_mode):
                if before.st_nlink != 1:
                    raise ToolchainBootstrapError("Installed toolchain hardlink is forbidden")
                child = os.open(
                    name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=descriptor,
                )
                try:
                    if _identity(os.fstat(child)) != _identity(before):
                        raise ToolchainBootstrapError("Installed toolchain file changed")
                    os.fchmod(child, stat.S_IMODE(before.st_mode) & 0o555)
                finally:
                    os.close(child)
            elif stat.S_ISDIR(before.st_mode) and not stat.S_ISLNK(before.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=descriptor,
                )
                try:
                    _chmod_installed_tree_read_only(child, depth + 1)
                    os.fchmod(child, stat.S_IMODE(before.st_mode) & 0o555)
                finally:
                    os.close(child)
            elif not stat.S_ISLNK(before.st_mode):
                raise ToolchainBootstrapError("Installed toolchain tree contains a special file")
        root_mode = stat.S_IMODE(os.fstat(descriptor).st_mode)
        os.fchmod(descriptor, root_mode & 0o555)
    except ToolchainBootstrapError:
        raise
    except OSError as exc:
        raise ToolchainBootstrapError("Installed toolchain tree cannot be sealed") from exc


def _make_installed_tree_cleanup_writable(
    descriptor: int,
    depth: int = 0,
) -> None:
    """Restore owner directory mutation only for exact held-tree cleanup."""

    if depth > 128:
        raise ToolchainBootstrapError(
            "Installed toolchain cleanup tree exceeds its depth bound"
        )
    try:
        for name in tuple(sorted(os.listdir(descriptor))):
            before = os.stat(
                name,
                dir_fd=descriptor,
                follow_symlinks=False,
            )
            if before.st_uid != os.geteuid():
                raise ToolchainBootstrapError(
                    "Installed toolchain cleanup ownership changed"
                )
            if stat.S_ISDIR(before.st_mode) and not stat.S_ISLNK(before.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=descriptor,
                )
                try:
                    if _identity(os.fstat(child)) != _identity(before):
                        raise ToolchainBootstrapError(
                            "Installed toolchain cleanup tree changed"
                        )
                    _make_installed_tree_cleanup_writable(child, depth + 1)
                    os.fchmod(child, 0o700)
                finally:
                    os.close(child)
            elif not (
                stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
            ):
                raise ToolchainBootstrapError(
                    "Installed toolchain cleanup tree contains a special file"
                )
        root_info = os.fstat(descriptor)
        if root_info.st_uid != os.geteuid():
            raise ToolchainBootstrapError(
                "Installed toolchain cleanup ownership changed"
            )
        os.fchmod(descriptor, 0o700)
    except ToolchainBootstrapError:
        raise
    except OSError as exc:
        raise ToolchainBootstrapError(
            "Installed toolchain cleanup permissions could not be restored"
        ) from exc


def seal_installed_tree(
    root: Path,
    descriptor: int,
    *,
    reviewed_framework_root: PurePosixPath = DEFAULT_REVIEWED_FRAMEWORK_ROOT,
) -> InstalledTreeSeal:
    _inventory_installed_tree(
        root,
        descriptor,
        require_read_only=False,
        reviewed_framework_root=reviewed_framework_root,
    )
    _chmod_installed_tree_read_only(descriptor)
    return _inventory_installed_tree(
        root,
        descriptor,
        require_read_only=True,
        reviewed_framework_root=reviewed_framework_root,
    )


def verify_installed_tree(
    root: Path,
    descriptor: int,
    *,
    content_sha256: str,
    identity_sha256: str,
    reviewed_framework_root: PurePosixPath = DEFAULT_REVIEWED_FRAMEWORK_ROOT,
) -> InstalledTreeSeal:
    if SHA256_PATTERN.fullmatch(content_sha256) is None or SHA256_PATTERN.fullmatch(identity_sha256) is None:
        raise ToolchainBootstrapError("Installed toolchain seal is malformed")
    observed = _inventory_installed_tree(
        root,
        descriptor,
        require_read_only=True,
        reviewed_framework_root=reviewed_framework_root,
    )
    if observed.content_sha256 != content_sha256 or observed.identity_sha256 != identity_sha256:
        raise ToolchainBootstrapError("Installed toolchain seal changed")
    return observed


def _sanitized_environment(
    *,
    home: Path,
    cache: Path,
    temporary: Path,
) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(home),
        "TMPDIR": str(temporary),
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PIP_CONFIG_FILE": "/dev/null",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
        "PIP_NO_COMPILE": "1",
        "PIP_ONLY_BINARY": ":all:",
        "PIP_REQUIRE_VIRTUALENV": "1",
        "PIP_CACHE_DIR": str(cache / "pip"),
        "UV_CACHE_DIR": str(cache / "uv"),
        "UV_NO_CONFIG": "1",
        "UV_NO_PROGRESS": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_NO_BUILD": "1",
    }


def _run_owned_process(
    arguments: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    pass_fds: Sequence[int],
    timeout: int,
    label: str,
    build: Any,
) -> str:
    process: subprocess.Popen[str] | None = None
    try:
        with build._defer_publish_signals():
            process = subprocess.Popen(
                list(arguments),
                cwd=cwd,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                pass_fds=tuple(pass_fds),
                start_new_session=True,
            )
        stdout, _stderr = process.communicate(timeout=timeout)
        with build._defer_publish_signals():
            descendants = build._process_group_exists(process.pid)
            if descendants:
                build._terminate_owned_process_group(
                    process,
                    error_message=f"{label} process group did not stop",
                )
        if descendants:
            raise ToolchainBootstrapError(f"{label} left a descendant process")
        if process.returncode != 0:
            raise ToolchainBootstrapError(f"{label} failed")
        if len(stdout.encode("utf-8")) > MAX_SUBPROCESS_OUTPUT_BYTES:
            raise ToolchainBootstrapError(f"{label} output exceeds its bound")
        return stdout
    except BaseException as exc:
        if process is not None:
            try:
                with build._defer_publish_signals(preserve_error=exc):
                    build._terminate_owned_process_group(
                        process,
                        error_message=f"{label} process group did not stop",
                    )
            except BaseException as cleanup_error:
                raise ToolchainBootstrapError(
                    f"{label} failed and its process group could not be cleaned"
                ) from exc
        if isinstance(exc, ToolchainBootstrapError):
            raise
        if isinstance(exc, build.BuildError):
            raise
        raise ToolchainBootstrapError(f"{label} failed") from exc


def _write_bound_file(
    capability: _ToolchainRoot,
    name: str,
    payload: bytes,
    *,
    mode: int,
    maximum_size: int,
) -> _BoundFile:
    if not payload or len(payload) > maximum_size:
        raise ToolchainBootstrapError("Python toolchain generated evidence is invalid")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            mode,
            dir_fd=capability.descriptor,
        )
        os.fchmod(descriptor, mode)
        remaining = memoryview(payload)
        while remaining:
            count = os.write(descriptor, remaining)
            if count <= 0:
                raise ToolchainBootstrapError("Python toolchain generated evidence could not be written")
            remaining = remaining[count:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        return _open_bound_file(
            capability.path / name,
            maximum_size=maximum_size,
            error_message="Python toolchain generated evidence is unsafe",
        )
    except ToolchainBootstrapError:
        raise
    except OSError as exc:
        raise ToolchainBootstrapError("Python toolchain generated evidence could not be written") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _validate_exported_runtime_lock(payload: bytes) -> None:
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ToolchainBootstrapError("Exported runtime lock is not UTF-8") from exc
    lowered = text.lower()
    if (
        not text.strip()
        or "--hash=sha256:" not in text
        or any(
            token in lowered
            for token in (
                "--no-binary",
                "--trusted-host",
                "--find-links",
                "file://",
                "-e ",
                "--editable",
            )
        )
    ):
        raise ToolchainBootstrapError("Exported runtime lock is unsafe")


def _tool_versions(build_versions: Mapping[str, str]) -> dict[str, str]:
    if set(build_versions) != set(BUILD_TOOL_MANIFEST_KEYS):
        raise ToolchainBootstrapError("Build tool lock has an unexpected package set")
    return {
        BUILD_TOOL_MANIFEST_KEYS[name]: build_versions[name]
        for name in sorted(build_versions)
    }


def _read_evidence_descriptor(
    descriptor: int,
    expected_sha256: str,
) -> tuple[dict[str, Any], bytes]:
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o400
            or info.st_size > MAX_EVIDENCE_BYTES
        ):
            raise ToolchainBootstrapError("Python toolchain evidence fd is unsafe")
        payload = _read_regular_descriptor(
            descriptor,
            expected_size=info.st_size,
            maximum_size=MAX_EVIDENCE_BYTES,
            error_message="Python toolchain evidence changed",
        )
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise ToolchainBootstrapError("Python toolchain evidence changed")
        value = json.loads(payload.decode("utf-8"))
    except ToolchainBootstrapError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolchainBootstrapError("Python toolchain evidence is malformed") from exc
    if not isinstance(value, dict):
        raise ToolchainBootstrapError("Python toolchain evidence is malformed")
    return value, payload


def verify_toolchain_environment(
    environment: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], bytes]:
    """Recompute both venv seals through inherited fds for the inner builder."""

    active = environment or os.environ
    try:
        venv_descriptor = int(active["LCF_PYTHON_BUILD_VENV_FD"])
        evidence_descriptor = int(active["LCF_PYTHON_TOOLCHAIN_EVIDENCE_FD"])
        root = Path(active["LCF_PYTHON_BUILD_VENV_ROOT"])
        content_sha256 = active["LCF_PYTHON_BUILD_VENV_CONTENT_SHA256"]
        identity_sha256 = active["LCF_PYTHON_BUILD_VENV_IDENTITY_SHA256"]
        evidence_sha256 = active["LCF_PYTHON_TOOLCHAIN_EVIDENCE_SHA256"]
        reviewed_framework_root = PurePosixPath(
            active["LCF_PYTHON_INSTALL_ROOT"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolchainBootstrapError("Python toolchain capability environment is missing") from exc
    if SHA256_PATTERN.fullmatch(evidence_sha256) is None:
        raise ToolchainBootstrapError("Python toolchain evidence digest is malformed")
    if (
        not reviewed_framework_root.is_absolute()
        or ".." in reviewed_framework_root.parts
    ):
        raise ToolchainBootstrapError("Reviewed Python framework root is malformed")
    try:
        held = os.fstat(venv_descriptor)
        observed = root.lstat()
        if _identity(held) != _identity(observed):
            raise ToolchainBootstrapError("Installed toolchain root was replaced")
    except ToolchainBootstrapError:
        raise
    except OSError as exc:
        raise ToolchainBootstrapError("Installed toolchain root is unavailable") from exc
    seal = verify_installed_tree(
        root,
        venv_descriptor,
        content_sha256=content_sha256,
        identity_sha256=identity_sha256,
        reviewed_framework_root=reviewed_framework_root,
    )
    evidence, payload = _read_evidence_descriptor(
        evidence_descriptor,
        evidence_sha256,
    )
    required = {
        "$schema",
        "schemaVersion",
        "buildRequirementsLockSha256",
        "runtimeLockSha256",
        "runtimeRequirementsSha256",
        "installedTreeContentSha256",
        "buildTools",
        "files",
    }
    if (
        set(evidence) != required
        or evidence.get("$schema") != TOOLCHAIN_EVIDENCE_SCHEMA
        or evidence.get("schemaVersion") != 1
        or evidence.get("installedTreeContentSha256") != seal.content_sha256
        or evidence.get("files") != list(seal.entries)
        or any(
            SHA256_PATTERN.fullmatch(str(evidence.get(name, ""))) is None
            for name in (
                "buildRequirementsLockSha256",
                "runtimeLockSha256",
                "runtimeRequirementsSha256",
            )
        )
        or not isinstance(evidence.get("buildTools"), dict)
        or set(evidence["buildTools"]) != set(BUILD_TOOL_MANIFEST_KEYS.values())
    ):
        raise ToolchainBootstrapError("Python toolchain evidence is inconsistent")
    return evidence, payload


def _close_source_seal(seal: _SourceSeal) -> bool:
    failed = False
    for descriptor in (*[item.descriptor for item in seal.files], seal.descriptor):
        try:
            os.close(descriptor)
        except OSError:
            failed = True
    return failed


def _source_file(seal: _SourceSeal, relative: str) -> _BoundFile:
    expected = seal.root / relative
    matches = [item for item in seal.files if item.path == expected]
    if len(matches) != 1:
        raise ToolchainBootstrapError(
            "Reviewed exact source input is missing or ambiguous"
        )
    return matches[0]


def _load_bound_json(bound: _BoundFile, label: str) -> dict[str, Any]:
    _revalidate_bound_file(
        bound,
        maximum_size=MAX_TREE_FILE_BYTES,
        error_message=f"{label} changed",
    )
    try:
        payload = _read_regular_descriptor(
            bound.descriptor,
            expected_size=bound.size,
            maximum_size=MAX_TREE_FILE_BYTES,
            error_message=f"{label} changed",
        )
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except ToolchainBootstrapError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolchainBootstrapError(f"{label} is malformed") from exc
    if not isinstance(value, dict):
        raise ToolchainBootstrapError(f"{label} is malformed")
    return value


def install_reviewed_python(
    environment: Mapping[str, str],
    *,
    archive: Path,
    hash_manifest: Path,
) -> str:
    """Verify and install the locked framework from one held private root."""

    try:
        import build_python_sidecar as build
    except ImportError as exc:
        raise ToolchainBootstrapError(
            "Reviewed Python installer helper cannot be imported"
        ) from exc
    if Path(build.__file__).resolve(strict=True) != TOOLS_ROOT / "build_python_sidecar.py":
        raise ToolchainBootstrapError(
            "Reviewed Python installer helper path is unexpected"
        )
    source = _validate_source_root(environment, build)
    with build._translate_cleanup_signals():
        primary_error: BaseException | None = None
        result: str | None = None
        try:
            runner_temp, runner_descriptor, _runner_identity = (
                _private_canonical_directory(
                    environment.get("RUNNER_TEMP", ""),
                    expected_mode=None,
                    error_message="RUNNER_TEMP is not a safe canonical directory",
                )
            )
            os.close(runner_descriptor)
            toolchain_lock = _load_bound_json(
                _source_file(
                    source,
                    "backend/packaging/python-sidecar-toolchain.lock.json",
                ),
                "Python toolchain lock",
            )
            python_lock = toolchain_lock.get("python")
            if not isinstance(python_lock, dict):
                raise ToolchainBootstrapError("Python toolchain lock is malformed")
            distribution = python_lock.get("distribution")
            if not isinstance(distribution, dict):
                raise ToolchainBootstrapError("Python distribution lock is malformed")
            install_root = Path(str(python_lock.get("installRoot", "")))
            interpreter = install_root / str(
                python_lock.get("interpreterRelativePath", "")
            )
            package_name = str(distribution.get("installerPackageName", ""))
            package_sha256 = str(distribution.get("installerPackageSha256", ""))
            if (
                not install_root.is_absolute()
                or ".." in install_root.parts
                or not package_name
                or Path(package_name).name != package_name
                or SHA256_PATTERN.fullmatch(package_sha256) is None
            ):
                raise ToolchainBootstrapError("Python distribution lock is malformed")
            with _held_toolchain_root(
                runner_temp,
                build,
                prefix=INSTALLER_ROOT_PREFIX,
            ) as capability:
                home_root, home_fd, _home_snapshot = _create_private_child(
                    capability,
                    "home",
                    build,
                )
                cache_root, cache_fd, _cache_snapshot = _create_private_child(
                    capability,
                    "cache",
                    build,
                )
                temporary_root, temporary_fd, _temporary_snapshot = (
                    _create_private_child(
                        capability,
                        "tmp",
                        build,
                    )
                )
                os.mkdir("pip", mode=0o700, dir_fd=cache_fd)
                os.mkdir("uv", mode=0o700, dir_fd=cache_fd)
                sanitized = _sanitized_environment(
                    home=home_root,
                    cache=cache_root,
                    temporary=temporary_root,
                )
                package_path = capability.path / package_name
                _revalidate_source_seal(source, build)
                try:
                    build.extract_reviewed_installer_package(
                        archive,
                        hash_manifest,
                        package_path,
                        toolchain=toolchain_lock,
                    )
                except build.BuildError as exc:
                    raise ToolchainBootstrapError(
                        "Reviewed Python installer extraction failed"
                    ) from exc
                package = _open_bound_file(
                    package_path,
                    maximum_size=MAX_TREE_FILE_BYTES,
                    error_message="Reviewed Python installer package is unsafe",
                )
                capability.child_descriptors.append(package.descriptor)
                if package.sha256 != package_sha256:
                    raise ToolchainBootstrapError(
                        "Reviewed Python installer package changed"
                    )
                pass_fds = (
                    source.descriptor,
                    capability.descriptor,
                    home_fd,
                    cache_fd,
                    temporary_fd,
                    package.descriptor,
                )
                for arguments, label, timeout in (
                    (
                        ("/usr/sbin/pkgutil", "--check-signature", str(package_path)),
                        "Python installer signature verification",
                        120,
                    ),
                    (
                        (
                            "/usr/sbin/spctl",
                            "--assess",
                            "--type",
                            "install",
                            "--verbose=4",
                            str(package_path),
                        ),
                        "Python installer policy assessment",
                        120,
                    ),
                    (
                        (
                            "/usr/bin/sudo",
                            "--non-interactive",
                            "/usr/sbin/installer",
                            "-pkg",
                            str(package_path),
                            "-target",
                            "/",
                        ),
                        "Python framework installation",
                        900,
                    ),
                ):
                    _revalidate_source_seal(source, build)
                    _revalidate_bound_file(
                        package,
                        maximum_size=MAX_TREE_FILE_BYTES,
                        error_message="Reviewed Python installer package changed",
                    )
                    _run_owned_process(
                        arguments,
                        cwd=source.root,
                        environment=sanitized,
                        pass_fds=pass_fds,
                        timeout=timeout,
                        label=label,
                        build=build,
                    )
                try:
                    interpreter_info = interpreter.lstat()
                    resolved_interpreter = interpreter.resolve(strict=True)
                except (OSError, RuntimeError) as exc:
                    raise ToolchainBootstrapError(
                        "Installed framework interpreter is unavailable"
                    ) from exc
                if (
                    not stat.S_ISREG(interpreter_info.st_mode)
                    or stat.S_ISLNK(interpreter_info.st_mode)
                    or resolved_interpreter != interpreter
                    or not stat.S_IMODE(interpreter_info.st_mode) & 0o111
                ):
                    raise ToolchainBootstrapError(
                        "Installed framework interpreter is unavailable"
                    )
                observer = (
                    "import json,platform,sys,sysconfig;"
                    "print(json.dumps({"
                    "'implementation':platform.python_implementation(),"
                    "'version':platform.python_version(),"
                    "'system':platform.system(),"
                    "'machine':platform.machine(),"
                    "'basePrefix':sys.base_prefix,"
                    "'baseExecutable':getattr(sys,'_base_executable',sys.executable),"
                    "'executable':sys.executable,"
                    "'cacheTag':sys.implementation.cache_tag,"
                    "'gilDisabled':bool(sysconfig.get_config_var('Py_GIL_DISABLED'))"
                    "},sort_keys=True,separators=(',',':')))"
                )
                observed_text = _run_owned_process(
                    (str(interpreter), "-I", "-c", observer),
                    cwd=source.root,
                    environment=sanitized,
                    pass_fds=pass_fds,
                    timeout=120,
                    label="Installed framework interpreter verification",
                    build=build,
                )
                try:
                    observed = json.loads(observed_text)
                    if not isinstance(observed, dict):
                        raise TypeError("observer")
                    fingerprint = build.verify_python_install_binding(
                        install_root,
                        toolchain=toolchain_lock,
                        implementation=str(observed["implementation"]),
                        version=str(observed["version"]),
                        system=str(observed["system"]),
                        machine=str(observed["machine"]),
                        base_prefix=Path(str(observed["basePrefix"])),
                        base_executable=Path(str(observed["baseExecutable"])),
                        executable=Path(str(observed["executable"])),
                        cache_tag=str(observed["cacheTag"]),
                        gil_disabled=bool(observed["gilDisabled"]),
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ToolchainBootstrapError(
                        "Installed framework interpreter evidence is malformed"
                    ) from exc
                except build.BuildError as exc:
                    raise ToolchainBootstrapError(
                        "Installed framework interpreter binding is invalid"
                    ) from exc
                _revalidate_bound_file(
                    package,
                    maximum_size=MAX_TREE_FILE_BYTES,
                    error_message="Reviewed Python installer package changed",
                )
                _revalidate_source_seal(source, build)
                result = fingerprint
        except BaseException as exc:
            primary_error = exc
        with build._defer_publish_signals(preserve_error=primary_error):
            source_close_failed = _close_source_seal(source)
        if source_close_failed:
            if primary_error is not None:
                raise ToolchainBootstrapError(
                    "Python installation failed and source descriptors could not be closed"
                ) from primary_error
            raise ToolchainBootstrapError(
                "Reviewed exact source descriptors could not be closed"
            )
        if primary_error is not None:
            raise primary_error
        if result is None:
            raise ToolchainBootstrapError(
                "Python installation produced no framework fingerprint"
            )
        return result


def build_with_exact_toolchain(environment: Mapping[str, str]) -> str:
    try:
        import build_python_sidecar as build
    except ImportError as exc:
        raise ToolchainBootstrapError("Reviewed Python inner builder cannot be imported") from exc
    if Path(build.__file__).resolve(strict=True) != TOOLS_ROOT / "build_python_sidecar.py":
        raise ToolchainBootstrapError("Reviewed Python inner builder path is unexpected")
    source = _validate_source_root(environment, build)
    source_close_failed = False
    try:
        runner_temp, runner_descriptor, _runner_identity = _private_canonical_directory(
            environment.get("RUNNER_TEMP", ""),
            expected_mode=None,
            error_message="RUNNER_TEMP is not a safe canonical directory",
        )
        os.close(runner_descriptor)
        toolchain_lock = _load_bound_json(
            _source_file(
                source,
                "backend/packaging/python-sidecar-toolchain.lock.json",
            ),
            "Python toolchain lock",
        )
        try:
            python_lock = toolchain_lock["python"]
            if not isinstance(python_lock, dict):
                raise TypeError("python lock")
            install_root = Path(environment["LCF_PYTHON_INSTALL_ROOT"])
            locked_install_root = Path(str(python_lock["installRoot"]))
            interpreter_relative = Path(str(python_lock["interpreterRelativePath"]))
            framework_python = Path(environment["LCF_REVIEWED_BUILD_PYTHON"])
            expected_python = locked_install_root / interpreter_relative
            if (
                install_root != locked_install_root
                or framework_python != expected_python
                or not framework_python.is_absolute()
                or ".." in framework_python.parts
            ):
                raise ToolchainBootstrapError(
                    "Reviewed build Python differs from the locked interpreter"
                )
            framework_info = framework_python.lstat()
            resolved_python = framework_python.resolve(strict=True)
            resolved_info = resolved_python.lstat()
            active_python = Path(sys.executable).resolve(strict=True)
        except ToolchainBootstrapError:
            raise
        except (OSError, RuntimeError, KeyError, TypeError, ValueError) as exc:
            raise ToolchainBootstrapError("Pinned framework Python is unavailable") from exc
        if (
            not stat.S_ISREG(framework_info.st_mode)
            or stat.S_ISLNK(framework_info.st_mode)
            or not stat.S_ISREG(resolved_info.st_mode)
            or not stat.S_IMODE(resolved_info.st_mode) & 0o111
            or resolved_python != framework_python
            or active_python != framework_python
        ):
            raise ToolchainBootstrapError("Pinned framework Python is unavailable")
        _revalidate_source_seal(source, build)
        try:
            build.verify_python_install_binding(
                install_root,
                toolchain=toolchain_lock,
                base_prefix=install_root,
                base_executable=framework_python,
                executable=framework_python,
            )
        except build.BuildError as exc:
            raise ToolchainBootstrapError(
                "Pinned framework Python install binding is invalid"
            ) from exc
        _revalidate_source_seal(source, build)

        with build._translate_cleanup_signals():
            with _held_toolchain_root(runner_temp, build) as capability:
                bootstrap_root, bootstrap_fd, _bootstrap_snapshot = _create_private_child(
                    capability, BOOTSTRAP_VENV_NAME, build
                )
                build_root, build_fd, _build_snapshot = _create_private_child(
                    capability, BUILD_VENV_NAME, build
                )
                cache_root, cache_fd, _cache_snapshot = _create_private_child(
                    capability, "cache", build
                )
                home_root, home_fd, _home_snapshot = _create_private_child(
                    capability, "home", build
                )
                temporary_root, temporary_fd, _temporary_snapshot = _create_private_child(
                    capability, "tmp", build
                )
                os.mkdir("pip", mode=0o700, dir_fd=cache_fd)
                os.mkdir("uv", mode=0o700, dir_fd=cache_fd)
                sanitized = _sanitized_environment(
                    home=home_root,
                    cache=cache_root,
                    temporary=temporary_root,
                )
                build_lock = next(
                    item
                    for item in source.files
                    if item.path.name == "build-requirements.lock"
                )
                uv_lock = next(
                    item
                    for item in source.files
                    if item.path == source.root / "backend" / "uv.lock"
                )
                build_versions = build.parse_build_requirements(build_lock.path)
                tools = _tool_versions(build_versions)
                pass_fds = (
                    source.descriptor,
                    build_lock.descriptor,
                    uv_lock.descriptor,
                    bootstrap_fd,
                    build_fd,
                    cache_fd,
                    home_fd,
                    temporary_fd,
                )
                _revalidate_source_seal(source, build)
                _run_owned_process(
                    (
                        str(framework_python),
                        "-I",
                        "-m",
                        "venv",
                        "--clear",
                        str(bootstrap_root),
                    ),
                    cwd=source.root,
                    environment=sanitized,
                    pass_fds=pass_fds,
                    timeout=300,
                    label="Python bootstrap venv creation",
                    build=build,
                )
                bootstrap_python = bootstrap_root / "bin" / "python"
                _run_owned_process(
                    (
                        str(bootstrap_python),
                        "-I",
                        "-m",
                        "pip",
                        "--isolated",
                        "install",
                        "--disable-pip-version-check",
                        "--no-input",
                        "--no-deps",
                        "--no-compile",
                        "--only-binary=:all:",
                        "--require-hashes",
                        "-r",
                        f"/dev/fd/{build_lock.descriptor}",
                    ),
                    cwd=source.root,
                    environment=sanitized,
                    pass_fds=pass_fds,
                    timeout=900,
                    label="Hash-locked Python bootstrap install",
                    build=build,
                )
                reviewed_framework_root = PurePosixPath(
                    install_root.as_posix()
                )
                bootstrap_seal = seal_installed_tree(
                    bootstrap_root,
                    bootstrap_fd,
                    reviewed_framework_root=reviewed_framework_root,
                )
                verify_installed_tree(
                    bootstrap_root,
                    bootstrap_fd,
                    content_sha256=bootstrap_seal.content_sha256,
                    identity_sha256=bootstrap_seal.identity_sha256,
                    reviewed_framework_root=reviewed_framework_root,
                )
                uv_environment = {**sanitized, "UV_OFFLINE": "1"}
                runtime_text = _run_owned_process(
                    (
                        str(bootstrap_root / "bin" / "uv"),
                        "export",
                        "--frozen",
                        "--no-dev",
                        "--no-emit-project",
                        "--format",
                        "requirements-txt",
                        "--python",
                        str(bootstrap_python),
                    ),
                    cwd=Path(f"/dev/fd/{source.descriptor}") / "backend",
                    environment=uv_environment,
                    pass_fds=pass_fds,
                    timeout=300,
                    label="Exact uv runtime export",
                    build=build,
                )
                runtime_payload = runtime_text.encode("utf-8")
                _validate_exported_runtime_lock(runtime_payload)
                runtime_lock = _write_bound_file(
                    capability,
                    RUNTIME_REQUIREMENTS_NAME,
                    runtime_payload,
                    mode=0o400,
                    maximum_size=MAX_RUNTIME_LOCK_BYTES,
                )
                capability.child_descriptors.append(runtime_lock.descriptor)
                verify_installed_tree(
                    bootstrap_root,
                    bootstrap_fd,
                    content_sha256=bootstrap_seal.content_sha256,
                    identity_sha256=bootstrap_seal.identity_sha256,
                    reviewed_framework_root=reviewed_framework_root,
                )
                _revalidate_source_seal(source, build)
                final_pass_fds = (*pass_fds, runtime_lock.descriptor)
                _run_owned_process(
                    (
                        str(framework_python),
                        "-I",
                        "-m",
                        "venv",
                        "--clear",
                        str(build_root),
                    ),
                    cwd=source.root,
                    environment=sanitized,
                    pass_fds=final_pass_fds,
                    timeout=300,
                    label="Python build venv creation",
                    build=build,
                )
                build_python = build_root / "bin" / "python"
                _run_owned_process(
                    (
                        str(build_python),
                        "-I",
                        "-m",
                        "pip",
                        "--isolated",
                        "install",
                        "--disable-pip-version-check",
                        "--no-input",
                        "--no-deps",
                        "--no-compile",
                        "--only-binary=:all:",
                        "--require-hashes",
                        "-r",
                        f"/dev/fd/{build_lock.descriptor}",
                        "-r",
                        f"/dev/fd/{runtime_lock.descriptor}",
                    ),
                    cwd=source.root,
                    environment=sanitized,
                    pass_fds=final_pass_fds,
                    timeout=1200,
                    label="Complete hash-locked Python build install",
                    build=build,
                )
                installed_seal = seal_installed_tree(
                    build_root,
                    build_fd,
                    reviewed_framework_root=reviewed_framework_root,
                )
                evidence_value = {
                    "$schema": TOOLCHAIN_EVIDENCE_SCHEMA,
                    "schemaVersion": 1,
                    "buildRequirementsLockSha256": build_lock.sha256,
                    "runtimeLockSha256": uv_lock.sha256,
                    "runtimeRequirementsSha256": runtime_lock.sha256,
                    "installedTreeContentSha256": installed_seal.content_sha256,
                    "buildTools": tools,
                    "files": list(installed_seal.entries),
                }
                evidence_payload = _canonical_json_bytes(evidence_value) + b"\n"
                evidence_file = _write_bound_file(
                    capability,
                    "toolchain-evidence.json",
                    evidence_payload,
                    mode=0o400,
                    maximum_size=MAX_EVIDENCE_BYTES,
                )
                capability.child_descriptors.append(evidence_file.descriptor)
                _revalidate_source_seal(source, build)
                verify_installed_tree(
                    build_root,
                    build_fd,
                    content_sha256=installed_seal.content_sha256,
                    identity_sha256=installed_seal.identity_sha256,
                    reviewed_framework_root=reviewed_framework_root,
                )
                child_environment = {
                    **sanitized,
                    **{
                        key: value
                        for key, value in environment.items()
                        if key in RELEASE_ENVIRONMENT_KEYS
                    },
                    "LCF_PYTHON_BUILD_VENV_FD": str(build_fd),
                    "LCF_PYTHON_BUILD_VENV_ROOT": str(build_root),
                    "LCF_PYTHON_BUILD_VENV_CONTENT_SHA256": installed_seal.content_sha256,
                    "LCF_PYTHON_BUILD_VENV_IDENTITY_SHA256": installed_seal.identity_sha256,
                    "LCF_PYTHON_TOOLCHAIN_EVIDENCE_FD": str(evidence_file.descriptor),
                    "LCF_PYTHON_TOOLCHAIN_EVIDENCE_SHA256": evidence_file.sha256,
                }
                child_fds = (
                    *final_pass_fds,
                    evidence_file.descriptor,
                )
                stdout = _run_owned_process(
                    (
                        str(build_python),
                        "-I",
                        str(source.root / "tools" / "build_python_sidecar.py"),
                    ),
                    cwd=source.root,
                    environment=child_environment,
                    pass_fds=child_fds,
                    timeout=3600,
                    label="Exact Python sidecar inner build",
                    build=build,
                )
                verify_installed_tree(
                    build_root,
                    build_fd,
                    content_sha256=installed_seal.content_sha256,
                    identity_sha256=installed_seal.identity_sha256,
                    reviewed_framework_root=reviewed_framework_root,
                )
                _revalidate_source_seal(source, build)
                _revalidate_bound_file(
                    evidence_file,
                    maximum_size=MAX_EVIDENCE_BYTES,
                    error_message="Python toolchain evidence changed after build",
                )
                return stdout
    finally:
        source_close_failed = _close_source_seal(source)
        if source_close_failed and sys.exception() is None:
            raise ToolchainBootstrapError("Reviewed exact source descriptors could not be closed")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the Python sidecar through the exact private toolchain"
    )
    parser.add_argument(
        "--install-reviewed-python",
        action="store_true",
        help="verify and install the locked framework through a held private root",
    )
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--hash-manifest", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.install_reviewed_python:
            if arguments.archive is None or arguments.hash_manifest is None:
                raise ToolchainBootstrapError(
                    "Python installation requires --archive and --hash-manifest"
                )
            output = install_reviewed_python(
                os.environ,
                archive=arguments.archive,
                hash_manifest=arguments.hash_manifest,
            )
        else:
            if arguments.archive is not None or arguments.hash_manifest is not None:
                raise ToolchainBootstrapError(
                    "Build mode does not accept installer source arguments"
                )
            output = build_with_exact_toolchain(os.environ)
    except (ToolchainBootstrapError, RuntimeError) as exc:
        print(f"python-sidecar toolchain failed: {exc}", file=sys.stderr)
        return 2
    print(output.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

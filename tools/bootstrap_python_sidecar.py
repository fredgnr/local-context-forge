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
import selectors
import stat
import subprocess
import sys
import time
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
MAX_FRAMEWORK_CORE_INVENTORY_BYTES = 16 * 1024 * 1024
MAX_INNER_DIAGNOSTIC_BYTES = 128
INNER_BUILD_DIAGNOSTIC_FD_ENV = "LCF_INNER_BUILD_DIAGNOSTIC_FD"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_REVIEWED_FRAMEWORK_ROOT = PurePosixPath(
    "/Library/Frameworks/Python.framework/Versions/3.13"
)
REVIEWED_FRAMEWORK_CORE_EXCLUDED_PATHS = (
    "Resources/English.lproj/Documentation",
    "bin/pip",
    "bin/pip3",
    "bin/pip3.13",
    "bin/python",
    "bin/python313",
    "etc/openssl/cert.pem",
    "lib/python3.13/site-packages",
    "share/doc/python3.13/html",
)
REVIEWED_FRAMEWORK_CORE_INVENTORY_NAME = (
    "python-framework-sealed-inventory.json"
)
REVIEWED_FRAMEWORK_CORE_INVENTORY_SOURCE = (
    f"backend/packaging/{REVIEWED_FRAMEWORK_CORE_INVENTORY_NAME}"
)
REVIEWED_FRAMEWORK_CORE_INVENTORY_KEYS = frozenset(
    {
        "fileName",
        "fileSize",
        "fileSha256",
        "schemaVersion",
        "sourcePayloadSize",
        "sourcePayloadSha256",
        "sourceEntryCount",
        "sourceInventorySha256",
        "transformationCount",
        "entryCount",
        "inventorySha256",
    }
)

SOURCE_INPUTS = (
    "Makefile",
    "backend/pyproject.toml",
    "backend/uv.lock",
    "backend/packaging/build-requirements.lock",
    "backend/packaging/lcf_sidecar.spec",
    REVIEWED_FRAMEWORK_CORE_INVENTORY_SOURCE,
    "backend/packaging/python-sidecar-toolchain.lock.json",
    "runtime/python-sidecar-build-manifest.schema.json",
    "tools/audit_python_sidecar.py",
    "tools/bootstrap_python_sidecar.py",
    "tools/build_python_sidecar.py",
)

# A child created while ``_defer_publish_signals`` is active inherits the
# blocked cleanup-signal mask.  Python's subprocess ``restore_signals`` does
# not clear that mask, and Darwin cannot use ``/dev/fd/N/child`` as a cwd.
# This fixed, isolated runner enters an already-held directory with fchdir,
# reduces the inherited descriptor set to an explicit exec allowlist, restores
# the cleanup signals, and performs one absolute execve without a shell or PATH
# lookup.  It intentionally reports only fixed stages and errno values.
HELD_CWD_EXEC_RUNNER = r"""
import errno
import os
import signal
import stat
import sys

def fail(stage, number=0):
    try:
        payload = (
            "lcf-held-cwd-exec: stage=" + stage + " errno=" + str(int(number)) + "\n"
        ).encode("ascii", errors="strict")
        os.write(2, payload)
    except BaseException:
        pass
    os._exit(126)

try:
    if len(sys.argv) < 13:
        fail("contract")
    raw_cwd = sys.argv[1]
    raw_keep_count = sys.argv[2]
    if not raw_cwd.isascii() or not raw_cwd.isdecimal():
        fail("contract")
    if not raw_keep_count.isascii() or not raw_keep_count.isdecimal():
        fail("contract")
    cwd_fd = int(raw_cwd, 10)
    keep_count = int(raw_keep_count, 10)
    if str(cwd_fd) != raw_cwd or cwd_fd < 3 or not 0 <= keep_count <= 256:
        fail("contract")
    keep_identity_offset = 3 + keep_count
    cwd_identity_offset = keep_identity_offset + (keep_count * 9)
    target_identity_offset = cwd_identity_offset + 9
    if len(sys.argv) < target_identity_offset + 10:
        fail("contract")
    keep = []
    for raw in sys.argv[3:keep_identity_offset]:
        if not raw.isascii() or not raw.isdecimal():
            fail("contract")
        descriptor = int(raw, 10)
        if str(descriptor) != raw or descriptor < 3:
            fail("contract")
        keep.append(descriptor)
    if len(set(keep)) != len(keep) or cwd_fd in keep:
        fail("contract")
    raw_keep_identities = sys.argv[keep_identity_offset:cwd_identity_offset]
    raw_cwd_identity = sys.argv[cwd_identity_offset:target_identity_offset]
    raw_target_identity = sys.argv[target_identity_offset:target_identity_offset + 9]
    if any(
        not item.isascii() or not item.isdecimal()
        for item in (
            *raw_keep_identities,
            *raw_cwd_identity,
            *raw_target_identity,
        )
    ):
        fail("contract")
    expected_keep_identities = tuple(
        tuple(
            int(item, 10)
            for item in raw_keep_identities[index:index + 9]
        )
        for index in range(0, len(raw_keep_identities), 9)
    )
    if len(expected_keep_identities) != keep_count:
        fail("contract")
    expected_cwd_identity = tuple(int(item, 10) for item in raw_cwd_identity)
    expected_target_identity = tuple(int(item, 10) for item in raw_target_identity)
    target_arguments = sys.argv[target_identity_offset + 9:]
    if not target_arguments or not target_arguments[0].startswith("/"):
        fail("contract")
    target = target_arguments[0]
    stage = "target"
    observed_target = os.stat(target, follow_symlinks=True)
    target_identity = (
        observed_target.st_dev,
        observed_target.st_ino,
        observed_target.st_mode,
        observed_target.st_uid,
        observed_target.st_gid,
        observed_target.st_nlink,
        observed_target.st_size,
        observed_target.st_mtime_ns,
        observed_target.st_ctime_ns,
    )
    if (
        target_identity != expected_target_identity
        or not stat.S_ISREG(observed_target.st_mode)
        or not observed_target.st_mode & 0o111
    ):
        fail("target")
    stage = "cwd-fd"
    cwd_info = os.fstat(cwd_fd)
    cwd_identity = (
        cwd_info.st_dev,
        cwd_info.st_ino,
        cwd_info.st_mode,
        cwd_info.st_uid,
        cwd_info.st_gid,
        cwd_info.st_nlink,
        cwd_info.st_size,
        cwd_info.st_mtime_ns,
        cwd_info.st_ctime_ns,
    )
    if not stat.S_ISDIR(cwd_info.st_mode) or cwd_identity != expected_cwd_identity:
        fail("cwd-fd", errno.ENOTDIR)
    for descriptor, expected_identity in zip(
        keep,
        expected_keep_identities,
        strict=True,
    ):
        keep_info = os.fstat(descriptor)
        keep_identity = (
            keep_info.st_dev,
            keep_info.st_ino,
            keep_info.st_mode,
            keep_info.st_uid,
            keep_info.st_gid,
            keep_info.st_nlink,
            keep_info.st_size,
            keep_info.st_mtime_ns,
            keep_info.st_ctime_ns,
        )
        if keep_identity != expected_identity:
            fail("fd-allowlist")
    # PEP 446 makes interpreter-created descriptors non-inheritable, while
    # Popen passed only cwd_fd plus keep.  Close any unexpected descriptor
    # anyway so execve has a mechanically explicit allowlist on Darwin too.
    stage = "fd-allowlist"
    for raw in os.listdir("/dev/fd"):
        if not raw.isdecimal():
            continue
        descriptor = int(raw, 10)
        if descriptor < 3 or descriptor == cwd_fd or descriptor in keep:
            continue
        try:
            os.close(descriptor)
        except OSError as exc:
            if exc.errno != errno.EBADF:
                fail("fd-allowlist", exc.errno or 0)
    for descriptor in keep:
        os.set_inheritable(descriptor, True)
    stage = "fchdir"
    os.fchdir(cwd_fd)
    entered = os.stat(".", follow_symlinks=False)
    entered_identity = (
        entered.st_dev,
        entered.st_ino,
        entered.st_mode,
        entered.st_uid,
        entered.st_gid,
        entered.st_nlink,
        entered.st_size,
        entered.st_mtime_ns,
        entered.st_ctime_ns,
    )
    if entered_identity != expected_cwd_identity:
        fail("fchdir")
    os.set_inheritable(cwd_fd, False)
    stage = "signal-reset"
    reset_signals = {
        signal.SIGINT,
        signal.SIGTERM,
        getattr(signal, "SIGHUP", signal.SIGTERM),
        getattr(signal, "SIGPIPE", signal.SIGTERM),
        getattr(signal, "SIGXFZ", signal.SIGTERM),
        getattr(signal, "SIGXFSZ", signal.SIGTERM),
    }
    for number in reset_signals:
        signal.signal(number, signal.SIG_DFL)
    if not hasattr(signal, "pthread_sigmask"):
        fail("signal-reset")
    signal.pthread_sigmask(
        signal.SIG_UNBLOCK,
        {
            signal.SIGINT,
            signal.SIGTERM,
            getattr(signal, "SIGHUP", signal.SIGTERM),
        },
    )
    stage = "execve"
    os.execve(target, target_arguments, dict(os.environ))
except OSError as exc:
    fail(locals().get("stage", "contract"), exc.errno or 0)
except BaseException:
    fail("contract")
""".strip()

PATH_CAPABILITY_EXEC_RUNNER = r"""
import errno
import os
import signal
import stat
import sys

def fail(stage, number=0):
    try:
        os.write(
            2,
            (
                "lcf-path-capability-exec: stage=" + stage
                + " errno=" + str(int(number)) + "\n"
            ).encode("ascii", errors="strict"),
        )
    except BaseException:
        pass
    os._exit(126)

try:
    if len(sys.argv) < 12:
        fail("contract")
    raw_count = sys.argv[1]
    if not raw_count.isascii() or not raw_count.isdecimal():
        fail("contract")
    count = int(raw_count, 10)
    if str(count) != raw_count or not 1 <= count <= 16:
        fail("contract")
    target_identity_offset = 2 + (count * 12)
    target_arguments_offset = target_identity_offset + 9
    if len(sys.argv) <= target_arguments_offset:
        fail("contract")
    descriptors = []
    for index in range(count):
        offset = 2 + (index * 12)
        raw_descriptor = sys.argv[offset]
        kind = sys.argv[offset + 1]
        raw_identity = sys.argv[offset + 2:offset + 11]
        path = sys.argv[offset + 11]
        if (
            not raw_descriptor.isascii()
            or not raw_descriptor.isdecimal()
            or kind not in {"absolute", "relative"}
            or len(raw_identity) != 9
            or any(not item.isascii() or not item.isdecimal() for item in raw_identity)
            or not path
            or "\x00" in path
            or (kind == "absolute") != path.startswith("/")
            or (kind == "relative" and (
                os.path.isabs(path)
                or path in {".", ".."}
                or ".." in path.split("/")
            ))
        ):
            fail("contract")
        descriptor = int(raw_descriptor, 10)
        if descriptor < 3 or str(descriptor) != raw_descriptor:
            fail("contract")
        expected = tuple(int(item, 10) for item in raw_identity)
        stage = "path-fd"
        held = os.fstat(descriptor)
        held_identity = (
            held.st_dev,
            held.st_ino,
            held.st_mode,
            held.st_uid,
            held.st_gid,
            held.st_nlink,
            held.st_size,
            held.st_mtime_ns,
            held.st_ctime_ns,
        )
        stage = "path-name"
        named = os.lstat(path)
        named_identity = (
            named.st_dev,
            named.st_ino,
            named.st_mode,
            named.st_uid,
            named.st_gid,
            named.st_nlink,
            named.st_size,
            named.st_mtime_ns,
            named.st_ctime_ns,
        )
        if held_identity != expected or named_identity != expected:
            fail("path-name")
        descriptors.append(descriptor)
    if len(set(descriptors)) != len(descriptors):
        fail("contract")
    raw_target_identity = sys.argv[
        target_identity_offset:target_arguments_offset
    ]
    target_arguments = sys.argv[target_arguments_offset:]
    if (
        len(raw_target_identity) != 9
        or any(
            not item.isascii() or not item.isdecimal()
            for item in raw_target_identity
        )
        or not target_arguments
        or not target_arguments[0].startswith("/")
    ):
        fail("contract")
    expected_target = tuple(int(item, 10) for item in raw_target_identity)
    stage = "target"
    target = os.stat(target_arguments[0], follow_symlinks=True)
    target_identity = (
        target.st_dev,
        target.st_ino,
        target.st_mode,
        target.st_uid,
        target.st_gid,
        target.st_nlink,
        target.st_size,
        target.st_mtime_ns,
        target.st_ctime_ns,
    )
    if (
        target_identity != expected_target
        or not stat.S_ISREG(target.st_mode)
        or not stat.S_IMODE(target.st_mode) & 0o111
    ):
        fail("target")
    for descriptor in descriptors:
        os.set_inheritable(descriptor, False)
    stage = "signal-reset"
    reset = {
        signal.SIGINT,
        signal.SIGTERM,
        getattr(signal, "SIGHUP", signal.SIGTERM),
        getattr(signal, "SIGPIPE", signal.SIGTERM),
        getattr(signal, "SIGXFZ", signal.SIGTERM),
        getattr(signal, "SIGXFSZ", signal.SIGTERM),
    }
    for number in reset:
        signal.signal(number, signal.SIG_DFL)
    if not hasattr(signal, "pthread_sigmask"):
        fail("signal-reset")
    signal.pthread_sigmask(
        signal.SIG_UNBLOCK,
        {
            signal.SIGINT,
            signal.SIGTERM,
            getattr(signal, "SIGHUP", signal.SIGTERM),
        },
    )
    stage = "execve"
    os.execve(target_arguments[0], target_arguments, dict(os.environ))
except OSError as exc:
    fail(locals().get("stage", "contract"), exc.errno or 0)
except BaseException:
    fail("contract", errno.EINVAL)
""".strip()

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
class _HeldExecutable:
    path: Path
    descriptor: int
    identity: tuple[int, ...]
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


def _symlink_identity(info: os.stat_result) -> tuple[int, ...]:
    """Return stable link identity without non-portable raw ownership or mode."""

    return (
        info.st_dev,
        info.st_ino,
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


def _node_binding(info: os.stat_result) -> tuple[int, ...]:
    """Return the pathname binding fields that intentional chmod may not change."""

    return (
        info.st_dev,
        info.st_ino,
        stat.S_IFMT(info.st_mode),
        info.st_uid,
        info.st_gid,
    )


def _chmod_stable_identity(info: os.stat_result) -> tuple[int, ...]:
    """Return content identity while excluding mode and chmod-updated ctime."""

    return (
        *_node_binding(info),
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
    )


def _materialize_private_regular_file(
    directory_descriptor: int,
    name: str,
    before: os.stat_result,
    desired_mode: int,
    build: Any,
) -> None:
    """Break one producer-created hardlink into the held private tree."""

    source_descriptor: int | None = None
    private_descriptor: int | None = None
    private_created = False
    private_cleanup_binding: tuple[int, ...] | None = None
    private_name = f".lcf-private-{secrets.token_hex(16)}"
    try:
        source_descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory_descriptor,
        )
        if _identity(os.fstat(source_descriptor)) != _identity(before):
            raise ToolchainBootstrapError(
                "Installed toolchain producer output changed"
            )
        payload = _read_regular_descriptor(
            source_descriptor,
            expected_size=before.st_size,
            maximum_size=MAX_TREE_FILE_BYTES,
            error_message="Installed toolchain producer output changed",
        )
        if (
            _identity(os.fstat(source_descriptor)) != _identity(before)
            or _identity(
                os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            )
            != _identity(before)
        ):
            raise ToolchainBootstrapError(
                "Installed toolchain producer output changed"
            )
        private_descriptor = os.open(
            private_name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | os.O_CLOEXEC,
            0o600,
            dir_fd=directory_descriptor,
        )
        private_created = True
        private_before = os.fstat(private_descriptor)
        if (
            not stat.S_ISREG(private_before.st_mode)
            or private_before.st_uid != os.geteuid()
            or private_before.st_gid != os.getegid()
            or private_before.st_nlink != 1
        ):
            raise ToolchainBootstrapError(
                "Installed toolchain private copy is unsafe"
            )
        private_cleanup_binding = _node_binding(private_before)
        offset = 0
        payload_view = memoryview(payload)
        while offset < len(payload):
            written = os.write(private_descriptor, payload_view[offset:])
            if written <= 0:
                raise ToolchainBootstrapError(
                    "Installed toolchain private copy failed"
                )
            offset += written
        os.fchmod(private_descriptor, desired_mode)
        os.fsync(private_descriptor)
        private_after = os.fstat(private_descriptor)
        if (
            not stat.S_ISREG(private_after.st_mode)
            or private_after.st_uid != os.geteuid()
            or private_after.st_gid != os.getegid()
            or private_after.st_nlink != 1
            or private_after.st_size != len(payload)
            or stat.S_IMODE(private_after.st_mode) != desired_mode
            or _read_regular_descriptor(
                private_descriptor,
                expected_size=len(payload),
                maximum_size=MAX_TREE_FILE_BYTES,
                error_message="Installed toolchain private copy changed",
            )
            != payload
        ):
            raise ToolchainBootstrapError(
                "Installed toolchain private copy changed"
            )
        if (
            _identity(os.fstat(source_descriptor)) != _identity(before)
            or _identity(
                os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            )
            != _identity(before)
        ):
            raise ToolchainBootstrapError(
                "Installed toolchain producer output changed"
            )
        with build._defer_publish_signals():
            build._exchange_at(
                directory_descriptor,
                name,
                directory_descriptor,
                private_name,
            )
            private_cleanup_binding = _node_binding(before)
        installed = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        held = os.fstat(private_descriptor)
        displaced = os.stat(
            private_name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (
            _node_binding(installed) != _node_binding(held)
            or _node_binding(displaced)
            != _node_binding(os.fstat(source_descriptor))
            or not stat.S_ISREG(installed.st_mode)
            or installed.st_nlink != 1
            or installed.st_size != len(payload)
            or stat.S_IMODE(installed.st_mode) != desired_mode
            or _read_regular_descriptor(
                private_descriptor,
                expected_size=len(payload),
                maximum_size=MAX_TREE_FILE_BYTES,
                error_message="Installed toolchain private copy changed",
            )
            != payload
        ):
            raise ToolchainBootstrapError(
                "Installed toolchain private copy changed"
            )
        os.unlink(private_name, dir_fd=directory_descriptor)
        private_created = False
        os.fsync(directory_descriptor)
    except ToolchainBootstrapError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ToolchainBootstrapError(
            "Installed toolchain private copy failed"
        ) from exc
    finally:
        for descriptor in (private_descriptor, source_descriptor):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        if private_created:
            try:
                cleanup_info = os.stat(
                    private_name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                if (
                    _node_binding(cleanup_info)
                    in {
                        private_cleanup_binding,
                        _node_binding(before),
                    }
                ):
                    os.unlink(private_name, dir_fd=directory_descriptor)
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _privatize_installed_tree(
    root: Path,
    descriptor: int,
    build: Any,
) -> None:
    """Canonicalize trusted producer output before the strict immutable seal.

    The held random parent and child roots are already private capabilities.
    Producer-created regular hardlinks are copied to independent inodes, and
    all non-symlink modes become owner-only before any installed tool is used.
    """

    entry_count = 0
    total_size = 0

    def visit(directory_descriptor: int, depth: int) -> None:
        nonlocal entry_count, total_size
        if depth > 128:
            raise ToolchainBootstrapError(
                "Installed toolchain producer output exceeds its depth bound"
            )
        try:
            names = tuple(sorted(os.listdir(directory_descriptor)))
        except OSError as exc:
            raise ToolchainBootstrapError(
                "Installed toolchain producer output cannot be privatized"
            ) from exc
        for name in names:
            if not name or "/" in name or "\x00" in name:
                raise ToolchainBootstrapError(
                    "Installed toolchain producer output contains an unsafe name"
                )
            try:
                before = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                mode = stat.S_IMODE(before.st_mode)
                if stat.S_ISLNK(before.st_mode):
                    entry_count += 1
                    after = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if _symlink_identity(after) != _symlink_identity(before):
                        raise ToolchainBootstrapError(
                            "Installed toolchain producer symlink changed"
                        )
                    if entry_count > MAX_TREE_ENTRIES:
                        raise ToolchainBootstrapError(
                            "Installed toolchain producer output exceeds its size bound"
                        )
                    continue
                if (
                    before.st_uid != os.geteuid()
                    or before.st_gid != os.getegid()
                    or mode & 0o7000
                ):
                    raise ToolchainBootstrapError(
                        "Installed toolchain producer output has unsafe ownership or mode"
                    )
                if stat.S_ISREG(before.st_mode):
                    if (
                        not mode & 0o400
                        or before.st_nlink < 1
                        or before.st_size > MAX_TREE_FILE_BYTES
                    ):
                        raise ToolchainBootstrapError(
                            "Installed toolchain producer file is unsafe"
                        )
                    desired_mode = 0o700 if mode & 0o100 else 0o600
                    if before.st_nlink != 1:
                        if mode & 0o022:
                            raise ToolchainBootstrapError(
                                "Installed toolchain producer hardlink is writable"
                            )
                        _materialize_private_regular_file(
                            directory_descriptor,
                            name,
                            before,
                            desired_mode,
                            build,
                        )
                    else:
                        child = os.open(
                            name,
                            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=directory_descriptor,
                        )
                        try:
                            opened = os.fstat(child)
                            if _identity(opened) != _identity(before):
                                raise ToolchainBootstrapError(
                                    "Installed toolchain producer output changed"
                                )
                            os.fchmod(child, desired_mode)
                            after = os.fstat(child)
                            relative_after = os.stat(
                                name,
                                dir_fd=directory_descriptor,
                                follow_symlinks=False,
                            )
                            if (
                                _chmod_stable_identity(after)
                                != _chmod_stable_identity(before)
                                or _node_binding(relative_after)
                                != _node_binding(after)
                                or stat.S_IMODE(after.st_mode) != desired_mode
                            ):
                                raise ToolchainBootstrapError(
                                    "Installed toolchain producer output changed"
                                )
                        finally:
                            os.close(child)
                    total_size += before.st_size
                elif stat.S_ISDIR(before.st_mode):
                    if mode & 0o500 != 0o500:
                        raise ToolchainBootstrapError(
                            "Installed toolchain producer directory is unsafe"
                        )
                    child = os.open(
                        name,
                        os.O_RDONLY
                        | os.O_DIRECTORY
                        | os.O_NOFOLLOW
                        | os.O_CLOEXEC,
                        dir_fd=directory_descriptor,
                    )
                    try:
                        opened = os.fstat(child)
                        if _identity(opened) != _identity(before):
                            raise ToolchainBootstrapError(
                                "Installed toolchain producer output changed"
                            )
                        os.fchmod(child, 0o700)
                        private_directory = os.fstat(child)
                        relative_private_directory = os.stat(
                            name,
                            dir_fd=directory_descriptor,
                            follow_symlinks=False,
                        )
                        if (
                            _node_binding(private_directory)
                            != _node_binding(before)
                            or _node_binding(relative_private_directory)
                            != _node_binding(private_directory)
                            or stat.S_IMODE(private_directory.st_mode) != 0o700
                        ):
                            raise ToolchainBootstrapError(
                                "Installed toolchain producer output changed"
                            )
                        visit(child, depth + 1)
                        after_children = os.fstat(child)
                        relative_after = os.stat(
                            name,
                            dir_fd=directory_descriptor,
                            follow_symlinks=False,
                        )
                        if (
                            _node_binding(after_children) != _node_binding(before)
                            or _node_binding(relative_after)
                            != _node_binding(after_children)
                            or stat.S_IMODE(after_children.st_mode) != 0o700
                        ):
                            raise ToolchainBootstrapError(
                                "Installed toolchain producer output changed"
                            )
                    finally:
                        os.close(child)
                else:
                    raise ToolchainBootstrapError(
                        "Installed toolchain producer output contains a special file"
                    )
                entry_count += 1
                if (
                    entry_count > MAX_TREE_ENTRIES
                    or total_size > MAX_TREE_TOTAL_BYTES
                ):
                    raise ToolchainBootstrapError(
                        "Installed toolchain producer output exceeds its size bound"
                    )
            except ToolchainBootstrapError:
                raise
            except OSError as exc:
                raise ToolchainBootstrapError(
                    "Installed toolchain producer output cannot be privatized"
                ) from exc
        try:
            if tuple(sorted(os.listdir(directory_descriptor))) != names:
                raise ToolchainBootstrapError(
                    "Installed toolchain producer output changed"
                )
        except ToolchainBootstrapError:
            raise
        except OSError as exc:
            raise ToolchainBootstrapError(
                "Installed toolchain producer output cannot be privatized"
            ) from exc

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
            or root_mode & 0o7000
            or root_mode & 0o500 != 0o500
        ):
            raise ToolchainBootstrapError(
                "Installed toolchain producer root is unsafe"
            )
        os.fchmod(descriptor, 0o700)
        private_root = os.fstat(descriptor)
        private_root_path = root.lstat()
        if (
            _node_binding(private_root) != _node_binding(root_before)
            or _node_binding(private_root_path) != _node_binding(private_root)
            or stat.S_IMODE(private_root.st_mode) != 0o700
        ):
            raise ToolchainBootstrapError(
                "Installed toolchain producer root changed"
            )
        visit(descriptor, 0)
        root_after = os.fstat(descriptor)
        root_path_after = root.lstat()
        if (
            _node_binding(root_after) != _node_binding(root_before)
            or _node_binding(root_path_after) != _node_binding(root_after)
            or stat.S_IMODE(root_after.st_mode) != 0o700
        ):
            raise ToolchainBootstrapError(
                "Installed toolchain producer root changed"
            )
    except ToolchainBootstrapError:
        raise
    except OSError as exc:
        raise ToolchainBootstrapError(
            "Installed toolchain producer output cannot be privatized"
        ) from exc


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
            if not is_symlink and (
                before.st_uid != os.geteuid()
                or before.st_gid != os.getegid()
                or mode & 0o7000
                or mode & 0o022
                or (require_read_only and mode & 0o200)
            ):
                raise ToolchainBootstrapError("Installed toolchain tree has unsafe ownership or mode")
            common = {
                "path": path,
                "mode": "0777" if is_symlink else f"{mode:04o}",
            }
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
                if before.st_nlink != 1:
                    raise ToolchainBootstrapError("Installed toolchain symlink is unsafe")
                target = os.readlink(name, dir_fd=directory_descriptor)
                after = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                if (
                    not stat.S_ISLNK(after.st_mode)
                    or _symlink_identity(after) != _symlink_identity(before)
                ):
                    raise ToolchainBootstrapError("Installed toolchain symlink changed")
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
            identity = (
                _symlink_identity(before)
                if is_symlink
                else _identity(before)
            )
            identities.append((path, content[-1]["type"], *identity))
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
            if stat.S_ISREG(before.st_mode):
                if before.st_uid != os.geteuid() or before.st_gid != os.getegid():
                    raise ToolchainBootstrapError("Installed toolchain ownership changed")
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
                if before.st_uid != os.geteuid() or before.st_gid != os.getegid():
                    raise ToolchainBootstrapError("Installed toolchain ownership changed")
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
            if stat.S_ISDIR(before.st_mode) and not stat.S_ISLNK(before.st_mode):
                if before.st_uid != os.geteuid():
                    raise ToolchainBootstrapError(
                        "Installed toolchain cleanup ownership changed"
                    )
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
            elif stat.S_ISREG(before.st_mode):
                if before.st_uid != os.geteuid():
                    raise ToolchainBootstrapError(
                        "Installed toolchain cleanup ownership changed"
                    )
            elif not stat.S_ISLNK(before.st_mode):
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


def _reviewed_framework_security_contract(
    python_lock: Mapping[str, Any],
) -> tuple[tuple[Path, int, str], ...]:
    """Return the two executable-closure files pinned by the reviewed lock."""

    try:
        interpreter_relative = Path(str(python_lock["interpreterRelativePath"]))
        interpreter_size = int(python_lock["interpreterSize"])
        interpreter_sha256 = str(python_lock["interpreterSha256"])
        framework_relative = Path(str(python_lock["frameworkBinaryRelativePath"]))
        framework_size = int(python_lock["frameworkBinarySize"])
        framework_sha256 = str(python_lock["frameworkBinarySha256"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolchainBootstrapError(
            "Reviewed Python framework security lock is malformed"
        ) from exc
    entries = (
        (interpreter_relative, interpreter_size, interpreter_sha256),
        (framework_relative, framework_size, framework_sha256),
    )
    if any(
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or size <= 0
        or size > MAX_TREE_FILE_BYTES
        or SHA256_PATTERN.fullmatch(digest) is None
        for relative, size, digest in entries
    ):
        raise ToolchainBootstrapError(
            "Reviewed Python framework security lock is malformed"
        )
    return entries


def _reviewed_framework_core_contract(
    python_lock: Mapping[str, Any],
) -> tuple[tuple[str, ...], str]:
    """Return the exact dynamic exclusions and locked core payload digest."""

    raw_exclusions = python_lock.get("frameworkCoreFingerprintExcludedPaths")
    digest = str(python_lock.get("frameworkCoreFingerprintSha256", ""))
    if (
        raw_exclusions != list(REVIEWED_FRAMEWORK_CORE_EXCLUDED_PATHS)
        or SHA256_PATTERN.fullmatch(digest) is None
    ):
        raise ToolchainBootstrapError(
            "Reviewed Python framework core lock is malformed"
        )
    inventory = _reviewed_framework_inventory_contract(python_lock)
    if inventory["inventorySha256"] != digest:
        raise ToolchainBootstrapError(
            "Reviewed Python framework core lock is malformed"
        )
    return REVIEWED_FRAMEWORK_CORE_EXCLUDED_PATHS, digest


def _reviewed_framework_inventory_contract(
    python_lock: Mapping[str, Any],
) -> dict[str, Any]:
    raw = python_lock.get("frameworkCoreInventory")
    if not isinstance(raw, dict) or set(raw) != REVIEWED_FRAMEWORK_CORE_INVENTORY_KEYS:
        raise ToolchainBootstrapError(
            "Reviewed Python framework inventory lock is malformed"
        )

    def positive_integer(name: str, maximum: int) -> bool:
        value = raw.get(name)
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 < value <= maximum
        )

    def nonnegative_integer(name: str, maximum: int) -> bool:
        value = raw.get(name)
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= maximum
        )

    def sha256(name: str) -> bool:
        value = raw.get(name)
        return isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None

    if (
        raw.get("fileName") != REVIEWED_FRAMEWORK_CORE_INVENTORY_NAME
        or not positive_integer(
            "fileSize", MAX_FRAMEWORK_CORE_INVENTORY_BYTES
        )
        or not sha256("fileSha256")
        or not isinstance(raw.get("schemaVersion"), int)
        or isinstance(raw.get("schemaVersion"), bool)
        or raw.get("schemaVersion") != 1
        or not positive_integer("sourcePayloadSize", MAX_TREE_FILE_BYTES)
        or not sha256("sourcePayloadSha256")
        or not positive_integer("sourceEntryCount", MAX_TREE_ENTRIES)
        or not sha256("sourceInventorySha256")
        or not nonnegative_integer("transformationCount", MAX_TREE_ENTRIES)
        or not positive_integer("entryCount", MAX_TREE_ENTRIES)
        or not sha256("inventorySha256")
    ):
        raise ToolchainBootstrapError(
            "Reviewed Python framework inventory lock is malformed"
        )
    distribution = python_lock.get("distribution")
    if isinstance(distribution, Mapping):
        component = distribution.get("frameworkComponent")
        if isinstance(component, Mapping) and (
            raw["sourcePayloadSize"] != component.get("payloadSize")
            or raw["sourcePayloadSha256"] != component.get("payloadSha256")
        ):
            raise ToolchainBootstrapError(
                "Reviewed Python framework inventory lock is malformed"
            )
    return dict(raw)


def _verify_reviewed_framework_inventory_file(
    bound: _BoundFile,
    contract: Mapping[str, Any],
) -> None:
    error_message = "Reviewed Python framework inventory file is inconsistent"
    _revalidate_bound_file(
        bound,
        maximum_size=MAX_FRAMEWORK_CORE_INVENTORY_BYTES,
        error_message=error_message,
    )
    if (
        bound.path.name != contract["fileName"]
        or bound.size != contract["fileSize"]
        or bound.sha256 != contract["fileSha256"]
    ):
        raise ToolchainBootstrapError(error_message)
    payload = _read_regular_descriptor(
        bound.descriptor,
        expected_size=bound.size,
        maximum_size=MAX_FRAMEWORK_CORE_INVENTORY_BYTES,
        error_message=error_message,
    )
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolchainBootstrapError(error_message) from exc
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "source",
        "transformations",
        "entryCount",
        "inventorySha256",
        "entries",
    }:
        raise ToolchainBootstrapError(error_message)
    source = value.get("source")
    transformations = value.get("transformations")
    entries = value.get("entries")
    if (
        not isinstance(source, dict)
        or set(source)
        != {
            "payloadSize",
            "payloadSha256",
            "coreEntryCount",
            "coreInventorySha256",
        }
        or value.get("schemaVersion") != contract["schemaVersion"]
        or source.get("payloadSize") != contract["sourcePayloadSize"]
        or source.get("payloadSha256") != contract["sourcePayloadSha256"]
        or source.get("coreEntryCount") != contract["sourceEntryCount"]
        or source.get("coreInventorySha256")
        != contract["sourceInventorySha256"]
        or not isinstance(transformations, list)
        or len(transformations) != contract["transformationCount"]
        or source.get("coreEntryCount")
        != contract["entryCount"] + contract["transformationCount"]
        or value.get("entryCount") != contract["entryCount"]
        or value.get("inventorySha256") != contract["inventorySha256"]
        or not isinstance(entries, list)
        or len(entries) != contract["entryCount"]
        or hashlib.sha256(_canonical_json_bytes(entries)).hexdigest()
        != contract["inventorySha256"]
    ):
        raise ToolchainBootstrapError(error_message)
    _validate_reviewed_framework_transformations(
        transformations,
        entries,
        error_message=error_message,
    )


def _validate_reviewed_framework_transformations(
    transformations: list[Any],
    entries: list[Any],
    *,
    error_message: str,
) -> None:
    """Require the exact Installer metadata-removal schema consumed by the seal."""

    previous_path: str | None = None
    transformation_paths: set[str] = set()
    for transformation in transformations:
        if (
            not isinstance(transformation, dict)
            or set(transformation)
            != {"kind", "path", "type", "mode", "size", "sha256"}
        ):
            raise ToolchainBootstrapError(error_message)
        raw_path = transformation.get("path")
        if not isinstance(raw_path, str):
            raise ToolchainBootstrapError(error_message)
        relative = PurePosixPath(raw_path)
        size = transformation.get("size")
        if (
            not raw_path
            or raw_path.startswith("/")
            or "\\" in raw_path
            or "\x00" in raw_path
            or relative.as_posix() != raw_path
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
            or transformation.get("kind") != "remove-appledouble"
            or transformation.get("type") != "file"
            or transformation.get("mode") != "0664"
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or size > MAX_TREE_FILE_BYTES
            or not isinstance(transformation.get("sha256"), str)
            or SHA256_PATTERN.fullmatch(transformation["sha256"]) is None
            or not relative.name.startswith("._")
            or relative.name == "._"
            or (previous_path is not None and previous_path >= raw_path)
        ):
            raise ToolchainBootstrapError(error_message)
        previous_path = raw_path
        transformation_paths.add(raw_path)

    final_paths = {
        item.get("path")
        for item in entries
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if transformation_paths & final_paths:
        raise ToolchainBootstrapError(error_message)


def _verify_reviewed_framework_inventory_source(
    source: _SourceSeal,
    python_lock: Mapping[str, Any],
) -> None:
    contract = _reviewed_framework_inventory_contract(python_lock)
    bound = _source_file(source, REVIEWED_FRAMEWORK_CORE_INVENTORY_SOURCE)
    _verify_reviewed_framework_inventory_file(bound, contract)


def _reviewed_framework_owner() -> int:
    """The Python.org framework producer and permission finalizer run as root."""

    return 0


def _reviewed_broken_framework_symlinks(
    python_lock: Mapping[str, Any],
) -> dict[str, str]:
    raw_entries = python_lock.get("reviewedBrokenSymlinks")
    if not isinstance(raw_entries, list):
        raise ToolchainBootstrapError(
            "Reviewed Python framework symlink lock is malformed"
        )
    result: dict[str, str] = {}
    for item in raw_entries:
        if not isinstance(item, dict) or set(item) != {"path", "target"}:
            raise ToolchainBootstrapError(
                "Reviewed Python framework symlink lock is malformed"
            )
        relative = PurePosixPath(str(item["path"]))
        target = PurePosixPath(str(item["target"]))
        relative_text = relative.as_posix()
        target_text = target.as_posix()
        if (
            relative.is_absolute()
            or target.is_absolute()
            or not relative.parts
            or not target.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
            or any(part in {"", ".", ".."} for part in target.parts)
            or relative_text in result
        ):
            raise ToolchainBootstrapError(
                "Reviewed Python framework symlink lock is malformed"
            )
        result[relative_text] = target_text
    if tuple(result) != tuple(sorted(result)):
        raise ToolchainBootstrapError(
            "Reviewed Python framework symlink lock is malformed"
        )
    return result


def _verify_locked_framework_regular(
    path: Path,
    *,
    expected_owner: int,
    expected_size: int,
    expected_sha256: str,
) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        held = os.fstat(descriptor)
        named = path.lstat()
        if (
            not stat.S_ISREG(held.st_mode)
            or stat.S_ISLNK(named.st_mode)
            or _identity(held) != _identity(named)
            or held.st_uid != expected_owner
            or held.st_nlink != 1
            or held.st_size != expected_size
            or stat.S_IMODE(held.st_mode) & 0o7022
        ):
            raise ToolchainBootstrapError(
                "Reviewed Python framework execution closure is unsafe"
            )
        payload = _read_regular_descriptor(
            descriptor,
            expected_size=expected_size,
            maximum_size=MAX_TREE_FILE_BYTES,
            error_message="Reviewed Python framework execution closure changed",
        )
        if (
            hashlib.sha256(payload).hexdigest() != expected_sha256
            or _identity(os.fstat(descriptor)) != _identity(held)
            or _identity(path.lstat()) != _identity(held)
        ):
            raise ToolchainBootstrapError(
                "Reviewed Python framework execution closure changed"
            )
    except ToolchainBootstrapError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ToolchainBootstrapError(
            "Reviewed Python framework execution closure is unavailable"
        ) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _verify_reviewed_framework_acl_seal(root: Path) -> None:
    """On macOS, reject every extended ACL without trusting the mode suffix."""

    if sys.platform != "darwin":
        return
    commands = (
        (
            "/bin/ls",
            "-led",
            str(root.parents[3]),
            str(root.parents[2]),
            str(root.parents[1]),
            str(root.parent),
            str(root),
        ),
        ("/bin/ls", "-leR", str(root)),
    )
    acl_entry = re.compile(rb"(?m)^[ \t]+[0-9]+: ")
    for command in commands:
        expected = _exec_target_identity(Path(command[0]))
        try:
            process = subprocess.run(
                command,
                cwd=Path("/"),
                env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
                check=False,
                start_new_session=True,
                umask=0o077,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ToolchainBootstrapError(
                "Reviewed Python framework ACL seal is unavailable"
            ) from exc
        if (
            process.returncode != 0
            or not process.stdout
            or process.stderr
            or len(process.stdout) > MAX_SUBPROCESS_OUTPUT_BYTES
            or acl_entry.search(process.stdout) is not None
            or expected != _exec_target_identity(Path(command[0]))
        ):
            raise ToolchainBootstrapError(
                "Reviewed Python framework ACL seal is unsafe"
            )


def _verify_reviewed_framework_seal(
    root: Path,
    *,
    python_lock: Mapping[str, Any],
    expected_owner: int | None = None,
) -> None:
    """Prove the installed framework is root-sealed before any code is used."""

    if expected_owner is None:
        expected_owner = _reviewed_framework_owner()
    try:
        if (
            not root.is_absolute()
            or ".." in root.parts
            or root.resolve(strict=True) != root
            or root.parent.resolve(strict=True) != root.parent
        ):
            raise ToolchainBootstrapError(
                "Reviewed Python framework seal is unsafe"
            )
        root_before = root.lstat()
        parent_before = root.parent.lstat()
        anchor_before = root.parents[1].lstat()
        container_before = root.parents[2].lstat()
        library_before = root.parents[3].lstat()
        if (
            not stat.S_ISDIR(root_before.st_mode)
            or stat.S_ISLNK(root_before.st_mode)
            or root_before.st_uid != expected_owner
            or stat.S_IMODE(root_before.st_mode) & 0o7022
            or not stat.S_ISDIR(parent_before.st_mode)
            or stat.S_ISLNK(parent_before.st_mode)
            or parent_before.st_uid != expected_owner
            or stat.S_IMODE(parent_before.st_mode) & 0o7022
            or not stat.S_ISDIR(anchor_before.st_mode)
            or stat.S_ISLNK(anchor_before.st_mode)
            or anchor_before.st_uid != expected_owner
            or stat.S_IMODE(anchor_before.st_mode) & 0o7022
            or not stat.S_ISDIR(container_before.st_mode)
            or stat.S_ISLNK(container_before.st_mode)
            or container_before.st_uid != expected_owner
            or stat.S_IMODE(container_before.st_mode) & 0o7022
            or not stat.S_ISDIR(library_before.st_mode)
            or stat.S_ISLNK(library_before.st_mode)
            or library_before.st_uid != expected_owner
            or stat.S_IMODE(library_before.st_mode) & 0o7022
        ):
            raise ToolchainBootstrapError(
                "Reviewed Python framework seal is unsafe"
            )
        broken = _reviewed_broken_framework_symlinks(python_lock)
        observed_broken: dict[str, str] = {}
        entry_count = 0
        total_size = 0
        for directory, directory_names, file_names in os.walk(
            root,
            topdown=True,
            followlinks=False,
        ):
            directory_names.sort()
            file_names.sort()
            for name in (*directory_names, *file_names):
                path = Path(directory) / name
                relative = path.relative_to(root).as_posix()
                relative_path = PurePosixPath(relative)
                folded_parts = tuple(
                    part.casefold() for part in relative_path.parts
                )
                info = path.lstat()
                entry_count += 1
                if entry_count > MAX_TREE_ENTRIES:
                    raise ToolchainBootstrapError(
                        "Reviewed Python framework seal exceeds its entry bound"
                    )
                if (
                    "__pycache__" in folded_parts
                    or relative_path.name.casefold().endswith((".pyc", ".pyo"))
                ):
                    raise ToolchainBootstrapError(
                        "Reviewed Python framework seal contains executable bytecode cache"
                    )
                if info.st_uid != expected_owner:
                    raise ToolchainBootstrapError(
                        "Reviewed Python framework seal has unsafe ownership"
                    )
                if stat.S_ISLNK(info.st_mode):
                    if info.st_nlink != 1:
                        raise ToolchainBootstrapError(
                            "Reviewed Python framework seal has an unsafe alias"
                        )
                    target = os.readlink(path)
                    target_path = PurePosixPath(target)
                    if (
                        not target
                        or target_path.is_absolute()
                        or "\x00" in target
                    ):
                        raise ToolchainBootstrapError(
                            "Reviewed Python framework seal has an unsafe symlink"
                        )
                    try:
                        resolved = path.resolve(strict=True)
                    except (OSError, RuntimeError) as exc:
                        unresolved = path.parent.joinpath(target).resolve(strict=False)
                        if (
                            broken.get(relative) != target
                            or root not in (unresolved, *unresolved.parents)
                        ):
                            raise ToolchainBootstrapError(
                                "Reviewed Python framework seal has an unsafe broken symlink"
                            ) from exc
                        observed_broken[relative] = target
                    else:
                        if root not in (resolved, *resolved.parents):
                            raise ToolchainBootstrapError(
                                "Reviewed Python framework seal has an escaping symlink"
                            )
                    continue
                mode = stat.S_IMODE(info.st_mode)
                if mode & 0o7022:
                    raise ToolchainBootstrapError(
                        "Reviewed Python framework seal is writable or privileged"
                    )
                if stat.S_ISDIR(info.st_mode):
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise ToolchainBootstrapError(
                        "Reviewed Python framework seal contains a special file"
                    )
                if info.st_nlink != 1 or info.st_size > MAX_TREE_FILE_BYTES:
                    raise ToolchainBootstrapError(
                        "Reviewed Python framework seal has an unsafe regular file"
                    )
                total_size += info.st_size
                if total_size > MAX_TREE_TOTAL_BYTES:
                    raise ToolchainBootstrapError(
                        "Reviewed Python framework seal exceeds its byte bound"
                    )
        if observed_broken != broken:
            raise ToolchainBootstrapError(
                "Reviewed Python framework broken symlink set changed"
            )
        if (
            _identity(root.lstat()) != _identity(root_before)
            or _identity(root.parent.lstat()) != _identity(parent_before)
            or _identity(root.parents[1].lstat()) != _identity(anchor_before)
            or _identity(root.parents[2].lstat()) != _identity(container_before)
            or _identity(root.parents[3].lstat()) != _identity(library_before)
        ):
            raise ToolchainBootstrapError(
                "Reviewed Python framework seal changed during verification"
            )
        _verify_reviewed_framework_acl_seal(root)
        for relative, size, digest in _reviewed_framework_security_contract(
            python_lock
        ):
            _verify_locked_framework_regular(
                root / relative,
                expected_owner=expected_owner,
                expected_size=size,
                expected_sha256=digest,
            )
    except ToolchainBootstrapError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ToolchainBootstrapError(
            "Reviewed Python framework seal is unavailable"
        ) from exc


def _verify_reviewed_framework_core(
    root: Path,
    *,
    python_lock: Mapping[str, Any],
    build: Any,
) -> None:
    """Bind every non-dynamic framework byte to the reviewed pkg payload."""

    exclusions, expected = _reviewed_framework_core_contract(python_lock)
    try:
        observed = build.fingerprint_install_root(
            root,
            reviewed_broken_symlinks=_reviewed_broken_framework_symlinks(
                python_lock
            ),
            excluded_paths=exclusions,
        )
    except build.BuildError as exc:
        raise ToolchainBootstrapError(
            "Reviewed Python framework core fingerprint failed"
        ) from exc
    if observed != expected:
        raise ToolchainBootstrapError(
            "Reviewed Python framework core fingerprint changed"
        )


@contextlib.contextmanager
def _held_executable(
    path: Path,
    *,
    error_message: str,
) -> Any:
    """Hold one exact executable inode while its canonical name stays bound."""

    descriptor: int | None = None
    binding: _HeldExecutable | None = None
    primary_error: BaseException | None = None
    try:
        if (
            not path.is_absolute()
            or ".." in path.parts
            or path.resolve(strict=True) != path
        ):
            raise ToolchainBootstrapError(error_message)
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        held = os.fstat(descriptor)
        named = path.lstat()
        if (
            not stat.S_ISREG(held.st_mode)
            or stat.S_ISLNK(named.st_mode)
            or _identity(held) != _identity(named)
            or held.st_uid not in {0, os.geteuid()}
            or held.st_nlink != 1
            or stat.S_IMODE(held.st_mode) & 0o7022
            or not stat.S_IMODE(held.st_mode) & 0o111
        ):
            raise ToolchainBootstrapError(error_message)
        payload = _read_regular_descriptor(
            descriptor,
            expected_size=held.st_size,
            maximum_size=MAX_TREE_FILE_BYTES,
            error_message=error_message,
        )
        if _identity(os.fstat(descriptor)) != _identity(held):
            raise ToolchainBootstrapError(error_message)
        binding = _HeldExecutable(
            path=path,
            descriptor=descriptor,
            identity=_identity(held),
            sha256=hashlib.sha256(payload).hexdigest(),
        )
        yield binding
    except BaseException as exc:
        primary_error = exc

    terminal_error: BaseException | None = None
    if binding is not None:
        try:
            _revalidate_held_executable(
                binding,
                error_message=error_message,
            )
        except BaseException as exc:
            terminal_error = exc

    close_error: BaseException | None = None
    if descriptor is not None:
        try:
            os.close(descriptor)
        except OSError as exc:
            close_error = exc
    if primary_error is not None:
        if terminal_error is not None or close_error is not None:
            raise ToolchainBootstrapError(
                f"{error_message} and its terminal capability could not be verified"
            ) from primary_error
        raise primary_error
    if terminal_error is not None:
        if close_error is not None:
            raise ToolchainBootstrapError(
                f"{error_message} and its held descriptor could not be closed"
            ) from terminal_error
        raise terminal_error
    if close_error is not None:
        raise ToolchainBootstrapError(
            f"{error_message} descriptor could not be closed"
        ) from close_error


def _revalidate_held_executable(
    binding: _HeldExecutable,
    *,
    error_message: str,
) -> None:
    """Revalidate the held launcher and its unchanged canonical name."""

    try:
        held = os.fstat(binding.descriptor)
        held_identity = _identity(held)
        named = binding.path.lstat()
        if (
            held_identity != binding.identity
            or _identity(named) != binding.identity
        ):
            raise ToolchainBootstrapError(error_message)
        payload = _read_regular_descriptor(
            binding.descriptor,
            expected_size=binding.identity[6],
            maximum_size=MAX_TREE_FILE_BYTES,
            error_message=error_message,
        )
        if hashlib.sha256(payload).hexdigest() != binding.sha256:
            raise ToolchainBootstrapError(error_message)
    except ToolchainBootstrapError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ToolchainBootstrapError(error_message) from exc


def _exec_target_identity(path: Path) -> tuple[int, ...]:
    """Bind one absolute executable without resolving it into a PATH lookup."""

    try:
        if not path.is_absolute() or ".." in path.parts:
            raise ToolchainBootstrapError("Owned process executable is unsafe")
        info = path.stat(follow_symlinks=True)
    except ToolchainBootstrapError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ToolchainBootstrapError("Owned process executable is unsafe") from exc
    if not stat.S_ISREG(info.st_mode) or not stat.S_IMODE(info.st_mode) & 0o111:
        raise ToolchainBootstrapError("Owned process executable is unsafe")
    return _identity(info)


def _held_cwd_exec_command(
    launcher_python: Path,
    arguments: Sequence[str],
    *,
    cwd_descriptor: int,
    keep_fds: Sequence[int],
) -> tuple[tuple[str, ...], tuple[int, ...], tuple[int, ...]]:
    """Wrap an absolute argv in the fixed fchdir/execve runner contract."""

    if not arguments:
        raise ToolchainBootstrapError("Owned process command is empty")
    launcher_identity = _exec_target_identity(launcher_python)
    target = Path(arguments[0])
    target_identity = _exec_target_identity(target)
    try:
        cwd_info = os.fstat(cwd_descriptor)
    except OSError as exc:
        raise ToolchainBootstrapError("Owned process cwd capability is unavailable") from exc
    if (
        cwd_descriptor < 3
        or not stat.S_ISDIR(cwd_info.st_mode)
        or cwd_info.st_uid != os.geteuid()
        or stat.S_IMODE(cwd_info.st_mode) & 0o022
    ):
        raise ToolchainBootstrapError("Owned process cwd capability is unsafe")
    normalized_keep = tuple(int(item) for item in keep_fds)
    if (
        len(normalized_keep) > 256
        or len(set(normalized_keep)) != len(normalized_keep)
        or cwd_descriptor in normalized_keep
        or any(item < 3 for item in normalized_keep)
    ):
        raise ToolchainBootstrapError("Owned process fd allowlist is invalid")
    try:
        keep_identities = tuple(
            _identity(os.fstat(descriptor)) for descriptor in normalized_keep
        )
    except OSError as exc:
        raise ToolchainBootstrapError("Owned process fd allowlist is unavailable") from exc
    command = (
        str(launcher_python),
        "-I",
        "-S",
        "-c",
        HELD_CWD_EXEC_RUNNER,
        str(cwd_descriptor),
        str(len(normalized_keep)),
        *(str(item) for item in normalized_keep),
        *(
            str(item)
            for identity in keep_identities
            for item in identity
        ),
        *(str(item) for item in _identity(cwd_info)),
        *(str(item) for item in target_identity),
        *tuple(arguments),
    )
    inherited = (cwd_descriptor, *normalized_keep)
    return command, inherited, (*launcher_identity, *target_identity)


def _revalidate_exec_identity(
    launcher_python: Path,
    arguments: Sequence[str],
    expected: Sequence[int],
) -> None:
    observed = (*_exec_target_identity(launcher_python), *_exec_target_identity(Path(arguments[0])))
    if tuple(expected) != observed:
        raise ToolchainBootstrapError("Owned process executable changed")


def _held_cwd_failure_category(stderr: str) -> str:
    held_matches = re.findall(
        r"^lcf-held-cwd-exec: stage="
        r"(contract|target|cwd-fd|fd-allowlist|fchdir|signal-reset|execve) "
        r"errno=[0-9]+$",
        stderr,
        flags=re.MULTILINE,
    )
    path_matches = re.findall(
        r"^lcf-path-capability-exec: stage="
        r"(contract|path-fd|path-name|target|signal-reset|execve) "
        r"errno=[0-9]+$",
        stderr,
        flags=re.MULTILINE,
    )
    categories = [
        *held_matches,
        *(f"path-{stage}" for stage in path_matches),
    ]
    return categories[0] if len(categories) == 1 else "unclassified"


def _communicate_bounded(
    process: subprocess.Popen[bytes],
    *,
    timeout: int,
    label: str,
) -> tuple[str, str]:
    """Drain two owned pipes without allowing unbounded child output."""

    if process.stdout is None or process.stderr is None:
        raise ToolchainBootstrapError(f"{label} output pipes are unavailable")
    streams = {
        process.stdout.fileno(): bytearray(),
        process.stderr.fileno(): bytearray(),
    }
    stream_objects = {
        process.stdout.fileno(): process.stdout,
        process.stderr.fileno(): process.stderr,
    }
    stdout_descriptor = process.stdout.fileno()
    total = 0
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    try:
        for descriptor in streams:
            os.set_blocking(descriptor, False)
            selector.register(descriptor, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, timeout)
            events = selector.select(min(0.1, remaining))
            for key, _mask in events:
                descriptor = int(key.fd)
                chunk = os.read(
                    descriptor,
                    min(65_536, MAX_SUBPROCESS_OUTPUT_BYTES - total + 1),
                )
                if not chunk:
                    selector.unregister(descriptor)
                    continue
                total += len(chunk)
                if total > MAX_SUBPROCESS_OUTPUT_BYTES:
                    raise ToolchainBootstrapError(
                        f"{label} output exceeds its bound"
                    )
                streams[descriptor].extend(chunk)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        process.wait(timeout=remaining)
    finally:
        selector.close()
        for stream in stream_objects.values():
            stream.close()
    try:
        stdout = bytes(streams[stdout_descriptor]).decode("utf-8", errors="strict")
        stderr_descriptor = next(
            descriptor for descriptor in streams if descriptor != stdout_descriptor
        )
        stderr = bytes(streams[stderr_descriptor]).decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ToolchainBootstrapError(f"{label} output is not UTF-8") from exc
    return stdout, stderr


def _read_inner_build_diagnostic(descriptor: int) -> tuple[str, str] | None:
    """Read exactly one strict fixed-enum inner-build diagnostic record."""

    payload = bytearray()
    try:
        os.set_blocking(descriptor, False)
        while len(payload) <= MAX_INNER_DIAGNOSTIC_BYTES:
            try:
                chunk = os.read(
                    descriptor,
                    MAX_INNER_DIAGNOSTIC_BYTES + 1 - len(payload),
                )
            except BlockingIOError:
                # The leader has already exited.  A live writer now means an
                # unreviewed descendant retained the capability; reject it
                # without waiting on an attacker-controlled lifetime.
                return None
            if not chunk:
                break
            payload.extend(chunk)
    except OSError:
        return None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    if len(payload) > MAX_INNER_DIAGNOSTIC_BYTES:
        return None
    try:
        record = payload.decode("ascii", errors="strict")
    except UnicodeError:
        return None
    match = re.fullmatch(
        r"lcf-inner-build: primary=([a-z][a-z-]{0,31}) "
        r"cleanup=([a-z][a-z-]{0,31})\n",
        record,
    )
    if match is None:
        return None
    try:
        import build_python_sidecar as inner
    except ImportError:
        return None
    primary, cleanup = match.groups()
    if (
        primary not in inner.INNER_PRIMARY_CATEGORIES
        or cleanup not in inner.INNER_CLEANUP_CATEGORIES
    ):
        return None
    return primary, cleanup


def _run_owned_process(
    arguments: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    pass_fds: Sequence[int],
    timeout: int,
    label: str,
    build: Any,
    cwd_descriptor: int | None = None,
    launcher_python: Path | None = None,
    launcher_binding: _HeldExecutable | None = None,
    inner_build_diagnostic: bool = False,
    check: bool = True,
    path_capabilities: Sequence[tuple[int, str, bool]] = (),
) -> str | subprocess.CompletedProcess[str]:
    process: subprocess.Popen[bytes] | None = None
    spawn_arguments: Sequence[str] = arguments
    spawn_cwd = cwd
    inherited_fds = tuple(pass_fds)
    spawn_environment = dict(environment)
    executable_identity: tuple[int, ...] | None = None
    cwd_identity: tuple[int, ...] | None = None
    diagnostic_reader: int | None = None
    diagnostic_writer: int | None = None
    diagnostic: tuple[str, str] | None = None
    keep_fd_identities: tuple[tuple[int, ...], ...] = ()
    path_capability_bindings: tuple[
        tuple[int, str, bool, tuple[int, ...]], ...
    ] = ()
    actual_target_identity: tuple[int, ...] | None = None
    effective_arguments: Sequence[str] = arguments

    def terminal_fd_identity(
        descriptor: int,
        expected: Sequence[int] | None = None,
    ) -> tuple[int, ...]:
        identity = _identity(os.fstat(descriptor))
        # Inherited producer-directory capabilities may legitimately gain
        # entries while the child runs.  Bind those descriptors to the same
        # object and access contract here; call-site owners separately verify
        # the allowed tree/content transition.  Immutable regular-file
        # capabilities retain their complete metadata identity on every exit.
        reference = tuple(expected) if expected is not None else identity
        return identity[:5] if stat.S_ISDIR(reference[2]) else identity

    def revalidate_owned_bindings() -> None:
        if cwd_descriptor is None:
            return
        if cwd_identity != _identity(os.fstat(cwd_descriptor)):
            raise ToolchainBootstrapError(f"{label} cwd capability changed")
        if launcher_python is None or executable_identity is None:
            raise ToolchainBootstrapError(
                f"{label} executable binding is unavailable"
            )
        if len(keep_fd_identities) != len(pass_fds) or any(
            expected != terminal_fd_identity(descriptor, expected)
            for descriptor, expected in zip(
                pass_fds,
                keep_fd_identities,
                strict=True,
            )
        ):
            raise ToolchainBootstrapError(f"{label} fd capability changed")
        for descriptor, path, _mutable, expected in path_capability_bindings:
            held = _identity(os.fstat(descriptor))
            named = _identity(
                os.stat(
                    path,
                    dir_fd=(
                        cwd_descriptor if not os.path.isabs(path) else None
                    ),
                    follow_symlinks=False,
                )
            )
            if (
                held != expected
                or named != expected
            ):
                raise ToolchainBootstrapError(
                    f"{label} path capability changed"
                )
        if launcher_binding is not None:
            _revalidate_held_executable(
                launcher_binding,
                error_message=f"{label} launcher capability changed",
            )
        _revalidate_exec_identity(
            launcher_python,
            effective_arguments,
            executable_identity,
        )
        if (
            actual_target_identity is not None
            and actual_target_identity
            != _exec_target_identity(Path(arguments[0]))
        ):
            raise ToolchainBootstrapError(f"{label} executable changed")

    try:
        if launcher_binding is not None and (
            launcher_python is None
            or launcher_binding.path != launcher_python
        ):
            raise ToolchainBootstrapError(
                "Owned process launcher capability is invalid"
            )
        if launcher_binding is not None:
            _revalidate_held_executable(
                launcher_binding,
                error_message="Owned process launcher capability is invalid",
            )
        if path_capabilities and cwd_descriptor is None:
            raise ToolchainBootstrapError(
                "Owned process path capability requires a held cwd"
            )
        if inner_build_diagnostic and not check:
            raise ToolchainBootstrapError(
                "Owned process diagnostic contract is invalid"
            )
        if inner_build_diagnostic:
            diagnostic_reader, diagnostic_writer = os.pipe()
            os.set_inheritable(diagnostic_reader, False)
            os.set_inheritable(diagnostic_writer, False)
            inherited_fds = (*inherited_fds, diagnostic_writer)
            spawn_environment[INNER_BUILD_DIAGNOSTIC_FD_ENV] = str(
                diagnostic_writer
            )
        if cwd_descriptor is not None:
            if launcher_python is None:
                raise ToolchainBootstrapError(
                    "Owned process fchdir launcher is unavailable"
                )
            cwd_identity = _identity(os.fstat(cwd_descriptor))
            keep_fd_identities = tuple(
                terminal_fd_identity(descriptor) for descriptor in pass_fds
            )
            if path_capabilities:
                if launcher_python is None:
                    raise ToolchainBootstrapError(
                        "Owned process path-capability launcher is unavailable"
                    )
                normalized_paths: list[
                    tuple[int, str, bool, tuple[int, ...]]
                ] = []
                seen_descriptors: set[int] = set()
                for raw_descriptor, raw_path, mutable in path_capabilities:
                    descriptor = int(raw_descriptor)
                    path = str(raw_path)
                    if (
                        descriptor < 3
                        or descriptor == cwd_descriptor
                        or descriptor in pass_fds
                        or descriptor in seen_descriptors
                        or not path
                        or "\x00" in path
                        or (
                            not os.path.isabs(path)
                            and (
                                path in {".", ".."}
                                or ".." in path.split("/")
                            )
                        )
                        or mutable is not False
                    ):
                        raise ToolchainBootstrapError(
                            "Owned process path capability is invalid"
                        )
                    identity = _identity(os.fstat(descriptor))
                    named = _identity(
                        os.stat(
                            path,
                            dir_fd=(
                                cwd_descriptor
                                if not os.path.isabs(path)
                                else None
                            ),
                            follow_symlinks=False,
                        )
                    )
                    if named != identity:
                        raise ToolchainBootstrapError(
                            "Owned process path capability is unavailable"
                        )
                    seen_descriptors.add(descriptor)
                    normalized_paths.append(
                        (descriptor, path, mutable, identity)
                    )
                path_capability_bindings = tuple(normalized_paths)
                actual_target_identity = _exec_target_identity(Path(arguments[0]))
                effective_arguments = (
                    str(launcher_python),
                    "-I",
                    "-S",
                    "-c",
                    PATH_CAPABILITY_EXEC_RUNNER,
                    str(len(path_capability_bindings)),
                    *(
                        item
                        for descriptor, path, _mutable, identity
                        in path_capability_bindings
                        for item in (
                            str(descriptor),
                            "absolute" if os.path.isabs(path) else "relative",
                            *(str(value) for value in identity),
                            path,
                        )
                    ),
                    *(str(item) for item in actual_target_identity),
                    *tuple(arguments),
                )
                inherited_fds = (
                    *inherited_fds,
                    *(descriptor for descriptor, *_rest in path_capability_bindings),
                )
            spawn_arguments, inherited_fds, executable_identity = (
                _held_cwd_exec_command(
                    launcher_python,
                    effective_arguments,
                    cwd_descriptor=cwd_descriptor,
                    keep_fds=inherited_fds,
                )
            )
            spawn_cwd = Path("/")
        elif launcher_python is not None:
            raise ToolchainBootstrapError(
                "Owned process fchdir launcher contract is invalid"
            )
        with build._defer_publish_signals():
            process = subprocess.Popen(
                list(spawn_arguments),
                cwd=spawn_cwd,
                env=spawn_environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                pass_fds=inherited_fds,
                close_fds=True,
                start_new_session=True,
                umask=0o077,
            )
        if diagnostic_writer is not None:
            os.close(diagnostic_writer)
            diagnostic_writer = None
        stdout, stderr = _communicate_bounded(
            process,
            timeout=timeout,
            label=label,
        )
        if diagnostic_reader is not None:
            diagnostic = _read_inner_build_diagnostic(diagnostic_reader)
            diagnostic_reader = None
        with build._defer_publish_signals():
            descendants = build._process_group_exists(process.pid)
            if descendants:
                build._terminate_owned_process_group(
                    process,
                    error_message=f"{label} process group did not stop",
                )
        if descendants:
            raise ToolchainBootstrapError(f"{label} left a descendant process")
        revalidate_owned_bindings()
        if process.returncode != 0 and check:
            if cwd_descriptor is not None:
                category = _held_cwd_failure_category(stderr)
                if diagnostic is not None and category == "unclassified":
                    primary, cleanup = diagnostic
                    raise ToolchainBootstrapError(
                        f"{label} failed (exit={process.returncode}; "
                        f"category=inner-build; primary={primary}; "
                        f"cleanup={cleanup})"
                    )
                raise ToolchainBootstrapError(
                    f"{label} failed (exit={process.returncode}; "
                    f"category={category})"
                )
            raise ToolchainBootstrapError(f"{label} failed")
        if not check:
            return subprocess.CompletedProcess(
                tuple(arguments),
                process.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        return stdout
    except BaseException as exc:
        cleanup_error: BaseException | None = None
        if process is not None:
            try:
                with build._defer_publish_signals(preserve_error=exc):
                    build._terminate_owned_process_group(
                        process,
                        error_message=f"{label} process group did not stop",
                    )
            except BaseException as observed_cleanup_error:
                cleanup_error = observed_cleanup_error
        binding_error: BaseException | None = None
        if process is not None:
            try:
                revalidate_owned_bindings()
            except BaseException as observed_error:
                binding_error = observed_error
        if cleanup_error is not None or binding_error is not None:
            raise ToolchainBootstrapError(
                f"{label} failed and its owned process state could not be verified"
            ) from exc
        if isinstance(exc, ToolchainBootstrapError):
            raise
        if isinstance(exc, build.BuildError):
            raise
        raise ToolchainBootstrapError(f"{label} failed") from exc
    finally:
        for descriptor in (diagnostic_reader, diagnostic_writer):
            if descriptor is None:
                continue
            try:
                os.close(descriptor)
            except OSError:
                pass


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


def _open_held_source_directory(
    seal: _SourceSeal,
    relative: str,
) -> tuple[int, tuple[int, ...]]:
    """Open one reviewed source child with openat and bind its inode."""

    if (
        not relative
        or "/" in relative
        or "\\" in relative
        or relative in {".", ".."}
    ):
        raise ToolchainBootstrapError("Reviewed source directory is invalid")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            relative,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=seal.descriptor,
        )
        held = os.fstat(descriptor)
        observed = os.stat(
            relative,
            dir_fd=seal.descriptor,
            follow_symlinks=False,
        )
        identity = _identity(held)
        if (
            not stat.S_ISDIR(held.st_mode)
            or identity != _identity(observed)
            or held.st_uid != os.geteuid()
            or stat.S_IMODE(held.st_mode) & 0o022
        ):
            raise ToolchainBootstrapError(
                "Reviewed source directory capability is unsafe"
            )
        result = (descriptor, identity)
        descriptor = None
        return result
    except ToolchainBootstrapError:
        raise
    except OSError as exc:
        raise ToolchainBootstrapError(
            "Reviewed source directory capability is unavailable"
        ) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _revalidate_held_source_directory(
    seal: _SourceSeal,
    relative: str,
    descriptor: int,
    identity: tuple[int, ...],
) -> None:
    try:
        held = os.fstat(descriptor)
        observed = os.stat(
            relative,
            dir_fd=seal.descriptor,
            follow_symlinks=False,
        )
        if _identity(held) != identity or _identity(observed) != identity:
            raise ToolchainBootstrapError(
                "Reviewed source directory capability changed"
            )
    except ToolchainBootstrapError:
        raise
    except OSError as exc:
        raise ToolchainBootstrapError(
            "Reviewed source directory capability changed"
        ) from exc


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
    """Bind the sealed framework to the locked, signed distribution bytes."""

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
            _reviewed_framework_security_contract(python_lock)
            _reviewed_framework_core_contract(python_lock)
            _verify_reviewed_framework_inventory_source(source, python_lock)
            _reviewed_broken_framework_symlinks(python_lock)
            install_root = Path(str(python_lock.get("installRoot", "")))
            interpreter = install_root / str(
                python_lock.get("interpreterRelativePath", "")
            )
            package_name = str(distribution.get("installerPackageName", ""))
            package_sha256 = str(distribution.get("installerPackageSha256", ""))
            if (
                not install_root.is_absolute()
                or ".." in install_root.parts
                or PurePosixPath(install_root.as_posix())
                != DEFAULT_REVIEWED_FRAMEWORK_ROOT
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
                source_child_fds = tuple(
                    descriptor
                    for descriptor in pass_fds
                    if descriptor
                    not in {
                        source.descriptor,
                        capability.descriptor,
                        cache_fd,
                        package.descriptor,
                    }
                )
                distribution_path_capabilities = (
                    (capability.descriptor, str(capability.path), False),
                    (cache_fd, str(cache_root), False),
                    (package.descriptor, str(package_path), False),
                )
                _verify_reviewed_framework_seal(
                    install_root,
                    python_lock=python_lock,
                )
                _verify_reviewed_framework_core(
                    install_root,
                    python_lock=python_lock,
                    build=build,
                )
                try:
                    active_launcher = Path(sys.executable).resolve(strict=True)
                except (OSError, RuntimeError) as exc:
                    raise ToolchainBootstrapError(
                        "Reviewed Python installer launcher is unavailable"
                    ) from exc
                if active_launcher != interpreter:
                    raise ToolchainBootstrapError(
                        "Reviewed Python installer launcher is not the locked interpreter"
                    )
                with _held_executable(
                    active_launcher,
                    error_message="Reviewed Python installer launcher is unsafe",
                ) as old_launcher:
                    for arguments, label, timeout in (
                        (
                            (
                                "/usr/sbin/pkgutil",
                                "--check-signature",
                                str(package_path),
                            ),
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
                    ):
                        _revalidate_source_seal(source, build)
                        _revalidate_bound_file(
                            package,
                            maximum_size=MAX_TREE_FILE_BYTES,
                            error_message=(
                                "Reviewed Python installer package changed"
                            ),
                        )
                        _run_owned_process(
                            arguments,
                            cwd=source.root,
                            environment=sanitized,
                            pass_fds=source_child_fds,
                            timeout=timeout,
                            label=label,
                            build=build,
                            cwd_descriptor=source.descriptor,
                            launcher_python=active_launcher,
                            launcher_binding=old_launcher,
                            path_capabilities=distribution_path_capabilities,
                        )
                    _revalidate_source_seal(source, build)
                    _revalidate_bound_file(
                        package,
                        maximum_size=MAX_TREE_FILE_BYTES,
                        error_message="Reviewed Python installer package changed",
                    )
                    _verify_reviewed_framework_seal(
                        install_root,
                        python_lock=python_lock,
                    )
                    _verify_reviewed_framework_core(
                        install_root,
                        python_lock=python_lock,
                        build=build,
                    )
                    _revalidate_held_executable(
                        old_launcher,
                        error_message=(
                            "Reviewed Python installer launcher is unsafe"
                        ),
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
                    with _held_executable(
                        interpreter,
                        error_message=(
                            "Installed framework interpreter is unsafe"
                        ),
                    ) as installed_launcher:
                        observed_text = _run_owned_process(
                            (str(interpreter), "-I", "-S", "-c", observer),
                            cwd=source.root,
                            environment=sanitized,
                            pass_fds=source_child_fds,
                            timeout=120,
                            label=(
                                "Installed framework interpreter verification"
                            ),
                            build=build,
                            cwd_descriptor=source.descriptor,
                            launcher_python=interpreter,
                            launcher_binding=installed_launcher,
                            path_capabilities=distribution_path_capabilities,
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
                                base_executable=Path(
                                    str(observed["baseExecutable"])
                                ),
                                executable=Path(str(observed["executable"])),
                                cache_tag=str(observed["cacheTag"]),
                                gil_disabled=bool(observed["gilDisabled"]),
                            )
                        except (
                            KeyError,
                            TypeError,
                            ValueError,
                            json.JSONDecodeError,
                        ) as exc:
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
                            error_message=(
                                "Reviewed Python installer package changed"
                            ),
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
                    "Python distribution binding failed and source descriptors could not be closed"
                ) from primary_error
            raise ToolchainBootstrapError(
                "Reviewed exact source descriptors could not be closed"
            )
        if primary_error is not None:
            raise primary_error
        if result is None:
            raise ToolchainBootstrapError(
                "Python distribution binding produced no framework fingerprint"
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
            _reviewed_framework_security_contract(python_lock)
            _reviewed_framework_core_contract(python_lock)
            _verify_reviewed_framework_inventory_source(source, python_lock)
            _reviewed_broken_framework_symlinks(python_lock)
            install_root = Path(environment["LCF_PYTHON_INSTALL_ROOT"])
            locked_install_root = Path(str(python_lock["installRoot"]))
            interpreter_relative = Path(str(python_lock["interpreterRelativePath"]))
            framework_python = Path(environment["LCF_REVIEWED_BUILD_PYTHON"])
            expected_python = locked_install_root / interpreter_relative
            if (
                install_root != locked_install_root
                or framework_python != expected_python
                or PurePosixPath(install_root.as_posix())
                != DEFAULT_REVIEWED_FRAMEWORK_ROOT
                or not framework_python.is_absolute()
                or ".." in framework_python.parts
            ):
                raise ToolchainBootstrapError(
                    "Reviewed build Python differs from the locked interpreter"
                )
            _verify_reviewed_framework_seal(
                install_root,
                python_lock=python_lock,
            )
            _verify_reviewed_framework_core(
                install_root,
                python_lock=python_lock,
                build=build,
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
                source_child_fds = tuple(
                    descriptor
                    for descriptor in pass_fds
                    if descriptor
                    not in {
                        source.descriptor,
                        capability.descriptor,
                        cache_fd,
                    }
                )
                toolchain_path_capabilities = (
                    (capability.descriptor, str(capability.path), False),
                    (cache_fd, str(cache_root), False),
                )
                _revalidate_source_seal(source, build)
                _run_owned_process(
                    (
                        str(framework_python),
                        "-I",
                        "-S",
                        "-m",
                        "venv",
                        "--clear",
                        str(bootstrap_root),
                    ),
                    cwd=source.root,
                    environment=sanitized,
                    pass_fds=source_child_fds,
                    timeout=300,
                    label="Python bootstrap venv creation",
                    build=build,
                    cwd_descriptor=source.descriptor,
                    launcher_python=framework_python,
                    path_capabilities=toolchain_path_capabilities,
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
                    pass_fds=source_child_fds,
                    timeout=900,
                    label="Hash-locked Python bootstrap install",
                    build=build,
                    cwd_descriptor=source.descriptor,
                    launcher_python=bootstrap_python,
                    path_capabilities=toolchain_path_capabilities,
                )
                _privatize_installed_tree(bootstrap_root, bootstrap_fd, build)
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
                backend_fd, backend_identity = _open_held_source_directory(
                    source,
                    "backend",
                )
                runtime_text: str | None = None
                runtime_error: BaseException | None = None
                try:
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
                        cwd=source.root,
                        environment=uv_environment,
                        pass_fds=source_child_fds,
                        timeout=300,
                        label="Exact uv runtime export",
                        build=build,
                        cwd_descriptor=backend_fd,
                        launcher_python=bootstrap_python,
                        path_capabilities=toolchain_path_capabilities,
                    )
                except BaseException as exc:
                    runtime_error = exc
                capability_error: BaseException | None = None
                with build._defer_publish_signals(preserve_error=runtime_error):
                    try:
                        _revalidate_held_source_directory(
                            source,
                            "backend",
                            backend_fd,
                            backend_identity,
                        )
                    except BaseException as exc:
                        capability_error = exc
                    try:
                        os.close(backend_fd)
                    except OSError as exc:
                        capability_error = capability_error or exc
                if capability_error is not None:
                    if runtime_error is not None:
                        raise ToolchainBootstrapError(
                            "Exact uv runtime export failed and its source "
                            "capability could not be revalidated"
                        ) from runtime_error
                    raise ToolchainBootstrapError(
                        "Exact uv runtime export source capability changed"
                    ) from capability_error
                if runtime_error is not None:
                    raise runtime_error
                if runtime_text is None:  # pragma: no cover - closed contract
                    raise ToolchainBootstrapError(
                        "Exact uv runtime export produced no output"
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
                final_source_child_fds = tuple(
                    descriptor
                    for descriptor in final_pass_fds
                    if descriptor
                    not in {
                        source.descriptor,
                        capability.descriptor,
                        cache_fd,
                    }
                )
                _run_owned_process(
                    (
                        str(framework_python),
                        "-I",
                        "-S",
                        "-m",
                        "venv",
                        "--clear",
                        str(build_root),
                    ),
                    cwd=source.root,
                    environment=sanitized,
                    pass_fds=final_source_child_fds,
                    timeout=300,
                    label="Python build venv creation",
                    build=build,
                    cwd_descriptor=source.descriptor,
                    launcher_python=framework_python,
                    path_capabilities=toolchain_path_capabilities,
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
                    pass_fds=final_source_child_fds,
                    timeout=1200,
                    label="Complete hash-locked Python build install",
                    build=build,
                    cwd_descriptor=source.descriptor,
                    launcher_python=build_python,
                    path_capabilities=toolchain_path_capabilities,
                )
                _privatize_installed_tree(build_root, build_fd, build)
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
                    *(
                        descriptor
                        for descriptor in final_pass_fds
                        if descriptor
                        not in {
                            source.descriptor,
                            capability.descriptor,
                            cache_fd,
                        }
                    ),
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
                    cwd_descriptor=source.descriptor,
                    launcher_python=build_python,
                    inner_build_diagnostic=True,
                    path_capabilities=toolchain_path_capabilities,
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
        help=(
            "bind the sealed framework to the locked signed distribution "
            "through a held private root"
        ),
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
                    "Python distribution binding requires --archive and --hash-manifest"
                )
            output = install_reviewed_python(
                os.environ,
                archive=arguments.archive,
                hash_manifest=arguments.hash_manifest,
            )
        else:
            if arguments.archive is not None or arguments.hash_manifest is not None:
                raise ToolchainBootstrapError(
                    "Build mode does not accept distribution source arguments"
                )
            output = build_with_exact_toolchain(os.environ)
    except (ToolchainBootstrapError, RuntimeError) as exc:
        print(f"python-sidecar toolchain failed: {exc}", file=sys.stderr)
        return 2
    print(output.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

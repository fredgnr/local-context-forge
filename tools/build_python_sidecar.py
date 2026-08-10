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
import contextlib
import ctypes
import errno
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import secrets
import signal
import shutil
import socket
import sqlite3
import ssl
import stat
import subprocess
import sys
import sysconfig
import tarfile
import threading
import time
import tomllib
import uuid
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
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
MAX_SOURCE_SNAPSHOT_FILES = 100_000
MAX_SOURCE_SNAPSHOT_FILE_BYTES = 256 * 1024 * 1024
MAX_SOURCE_SNAPSHOT_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_EVIDENCE_FILES = 2
MAX_EVIDENCE_DIRECTORIES = 16
MAX_EVIDENCE_FILE_BYTES = 16 * 1024 * 1024
MAX_EVIDENCE_TOTAL_BYTES = 24 * 1024 * 1024
SCRATCH_PARENT_NAME = "python-sidecar-build"
SOURCE_SNAPSHOT_NAME = "source-snapshot"
UV_CACHE_NAME = "uv-cache"
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
TOOLCHAIN_EVIDENCE_ARTIFACT = "python-build-toolchain.json"
BUILD_TOOL_EVIDENCE_KEYS = {
    "altgraph": "altgraphVersion",
    "macholib": "macholibVersion",
    "packaging": "packagingVersion",
    "pyinstaller": "pyinstallerVersion",
    "pyinstaller-hooks-contrib": "pyinstallerHooksContribVersion",
    "setuptools": "setuptoolsVersion",
    "uv": "uvVersion",
}

# The locked runner receives canonical paths only after the outer owner has
# bound each private path to a held descriptor.  Darwin fdesc child traversal
# is deliberately not part of the contract.  The wrapper is self-contained
# because isolated mode ignores PYTHONPATH and sitecustomize.
PYINSTALLER_CAPABILITY_RUNNER = r"""
import os
import stat
import sys

source_descriptor = int(sys.argv.pop(1))
bundle_descriptor = int(sys.argv.pop(1))
dist_descriptor = int(sys.argv.pop(1))
work_descriptor = int(sys.argv.pop(1))
config_descriptor = int(sys.argv.pop(1))
temp_descriptor = int(sys.argv.pop(1))
source_root = os.path.abspath(os.path.normpath(sys.argv.pop(1)))
bundle_root = os.path.abspath(os.path.normpath(sys.argv.pop(1)))
dist_root = os.path.abspath(os.path.normpath(sys.argv.pop(1)))
work_root = os.path.abspath(os.path.normpath(sys.argv.pop(1)))
config_root = os.path.abspath(os.path.normpath(sys.argv.pop(1)))
temp_root = os.path.abspath(os.path.normpath(sys.argv.pop(1)))
capability_roots = (
    source_root,
    bundle_root,
    dist_root,
    work_root,
    config_root,
    temp_root,
)
capability_descriptors = (
    source_descriptor,
    bundle_descriptor,
    dist_descriptor,
    work_descriptor,
    config_descriptor,
    temp_descriptor,
)

for capability_descriptor, capability_root in zip(
    capability_descriptors,
    capability_roots,
    strict=True,
):
    held = os.fstat(capability_descriptor)
    observed = os.lstat(capability_root)
    probe = os.open(
        capability_root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        opened = os.fstat(probe)
        if (
            not stat.S_ISDIR(held.st_mode)
            or stat.S_ISLNK(observed.st_mode)
            or (held.st_dev, held.st_ino) != (observed.st_dev, observed.st_ino)
            or (held.st_dev, held.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise RuntimeError("PyInstaller directory capability is unavailable")
    finally:
        os.close(probe)
    os.set_inheritable(capability_descriptor, False)

held_bundle = os.fstat(bundle_descriptor)
observed_bundle = os.stat(bundle_root)
held_dist = os.fstat(dist_descriptor)
observed_dist = os.stat(dist_root)
expected_output = dist_root + "/lcf-service"
observed_output = os.stat(expected_output)
if (
    not stat.S_ISDIR(held_bundle.st_mode)
    or not stat.S_ISDIR(held_dist.st_mode)
    or (held_bundle.st_dev, held_bundle.st_ino)
    != (observed_bundle.st_dev, observed_bundle.st_ino)
    or (held_dist.st_dev, held_dist.st_ino)
    != (observed_dist.st_dev, observed_dist.st_ino)
    or (held_bundle.st_dev, held_bundle.st_ino)
    != (observed_output.st_dev, observed_output.st_ino)
):
    raise RuntimeError("PyInstaller bundle capability is unavailable")

def required_option(name):
    matches = []
    prefix = name + "="
    for index, argument in enumerate(sys.argv[1:], start=1):
        if argument == name:
            if index + 1 >= len(sys.argv):
                raise RuntimeError("PyInstaller capability option is incomplete")
            matches.append(sys.argv[index + 1])
        elif argument.startswith(prefix):
            matches.append(argument[len(prefix):])
    if len(matches) != 1:
        raise RuntimeError("PyInstaller capability option is ambiguous")
    return os.path.abspath(os.path.normpath(matches[0]))

if required_option("--distpath") != dist_root:
    raise RuntimeError("PyInstaller dist capability is unexpected")
if required_option("--workpath") != work_root:
    raise RuntimeError("PyInstaller work capability is unexpected")
if os.environ.get("PYINSTALLER_CONFIG_DIR") != config_root:
    raise RuntimeError("PyInstaller config capability is unexpected")
if os.environ.get("TMPDIR") != temp_root:
    raise RuntimeError("PyInstaller temporary capability is unexpected")
os.environ["LCF_PYINSTALLER_SOURCE_FD"] = str(source_descriptor)
os.environ["LCF_PYINSTALLER_SOURCE_ROOT"] = source_root

from PyInstaller.lib.modulegraph import modulegraph

original_os = modulegraph.os

class CapabilityPathProxy:
    def __init__(self, delegate):
        self._delegate = delegate

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def realpath(self, value, *args, **kwargs):
        raw = os.fspath(value)
        normalized = self._delegate.abspath(self._delegate.normpath(raw))
        for capability_root in capability_roots:
            if normalized == capability_root or normalized.startswith(
                capability_root + os.sep
            ):
                return normalized
        return self._delegate.realpath(value, *args, **kwargs)

class CapabilityOsProxy:
    def __init__(self, delegate):
        self._delegate = delegate
        self.path = CapabilityPathProxy(delegate.path)

    def __getattr__(self, name):
        return getattr(self._delegate, name)

modulegraph.os = CapabilityOsProxy(original_os)

from PyInstaller.building import api as building_api

original_collect_init = building_api.COLLECT.__init__
original_make_clean_directory = building_api._make_clean_directory

def capability_collect_init(self, *args, **kwargs):
    requested_name = kwargs.get("name")
    if os.path.basename(os.fspath(requested_name)) != "lcf-service":
        raise RuntimeError("PyInstaller bundle output is unexpected")
    from PyInstaller.config import CONF
    configured_dist = CONF.get("distpath")
    if os.path.abspath(os.path.normpath(configured_dist)) != dist_root:
        raise RuntimeError("PyInstaller dist capability is unexpected")
    kwargs["name"] = os.path.basename(bundle_root)
    CONF["distpath"] = os.path.dirname(bundle_root)
    try:
        original_collect_init(self, *args, **kwargs)
    finally:
        CONF["distpath"] = configured_dist
    if os.path.abspath(os.path.normpath(self.name)) != bundle_root:
        raise RuntimeError("PyInstaller bundle output is unexpected")

def capability_make_clean_directory(path):
    normalized = os.path.abspath(os.path.normpath(path))
    if normalized != bundle_root:
        return original_make_clean_directory(path)
    before = os.fstat(bundle_descriptor)
    relative = os.stat(expected_output)
    if (
        (before.st_dev, before.st_ino) != (relative.st_dev, relative.st_ino)
        or os.listdir(bundle_descriptor)
    ):
        raise RuntimeError("PyInstaller bundle capability changed before assembly")

building_api.COLLECT.__init__ = capability_collect_init
building_api._make_clean_directory = capability_make_clean_directory

import PyInstaller.__main__
PyInstaller.__main__.run()
""".strip()


class BuildError(RuntimeError):
    """Raised when a release build cannot prove a required invariant."""


class _CapabilityDriftError(BuildError):
    """Raised when a held path name no longer denotes its captured object."""


class _CleanupBlockedError(BuildError):
    """Raised when deletion must be refused to preserve a replacement."""


class _DeferredSignalError(BuildError):
    """Raised after a cleanup-critical region has reached a stable state."""


@dataclass(frozen=True)
class _DirectorySnapshot:
    """Complete metadata captured from one held directory descriptor."""

    device: int
    inode: int
    mode: int
    uid: int
    gid: int
    links: int
    size: int
    mtime_ns: int
    ctime_ns: int
    entries: tuple[str, ...]


@dataclass
class _EvidenceCapability:
    """Held authority for the exact sanitized failure-evidence directory."""

    path: Path
    name: str
    parent_descriptor: int
    descriptor: int
    snapshot: _DirectorySnapshot
    tree_snapshot: tuple[tuple[Any, ...], ...]
    content_snapshot: tuple[tuple[str, str], ...]
    closed: bool = False


@dataclass
class _BundleCapability:
    """Held authority for the PyInstaller candidate from first inspection."""

    path: Path
    name: str
    parent_path: Path
    parent_name: str
    parent_descriptor: int
    parent_snapshot: _DirectorySnapshot
    descriptor: int
    snapshot: _DirectorySnapshot
    tree_snapshot: tuple[tuple[Any, ...], ...]
    closed: bool = False


@dataclass
class _ProducerDirectoryCapability:
    """Held authority for one PyInstaller producer-owned directory."""

    path: Path
    capability_path: Path
    name: str
    descriptor: int
    snapshot: _DirectorySnapshot
    tree_snapshot: tuple[tuple[Any, ...], ...]


@dataclass
class _PyInstallerProducerCapabilities:
    """Retained work/config/tmp roots and their immutable parent binding."""

    parent_snapshot: _DirectorySnapshot
    directories: dict[str, _ProducerDirectoryCapability]
    closed: bool = False


@dataclass
class _RetainedPublishedDirectory:
    """Held authority for an exchanged old destination kept in scratch."""

    parent_path: Path
    name: str
    parent_descriptor: int
    descriptor: int
    snapshot: _DirectorySnapshot
    tree_snapshot: tuple[tuple[Any, ...], ...]
    owns_parent_descriptor: bool
    closed: bool = False


@dataclass
class _ScratchCapability:
    """Held authority for one exact build scratch lifecycle.

    Paths are retained only for tools that cannot consume a directory
    descriptor. Every destructive or publish operation is instead performed
    relative to the held descriptors and rebinds the path entry to the
    captured device/inode before it acts.
    """

    destination_parent: Path
    destination_parent_descriptor: int
    destination_parent_snapshot: _DirectorySnapshot
    scratch_parent: Path
    scratch_parent_name: str
    scratch_parent_descriptor: int
    scratch_parent_snapshot: _DirectorySnapshot
    build_root: Path
    build_root_name: str
    build_root_descriptor: int
    build_root_snapshot: _DirectorySnapshot
    source_snapshot: Path | None = None
    source_snapshot_descriptor: int | None = None
    source_snapshot_metadata: _DirectorySnapshot | None = None
    source_inventory: tuple[_TreeEntry, ...] | None = None
    source_tree_metadata: tuple[tuple[Any, ...], ...] | None = None
    evidence: _EvidenceCapability | None = None
    bundle: _BundleCapability | None = None
    retained_published_directories: list[_RetainedPublishedDirectory] = field(
        default_factory=list
    )
    poisoned: bool = False
    closed: bool = False


@dataclass(frozen=True)
class _TreeEntry:
    path: str
    mode: str
    object_type: str
    object_id: str


@dataclass
class _PublishCapability:
    candidate: Path
    candidate_name: str
    candidate_parent: Path
    candidate_parent_descriptor: int
    candidate_parent_snapshot: _DirectorySnapshot
    candidate_descriptor: int
    candidate_snapshot: _DirectorySnapshot
    candidate_tree_snapshot: tuple[tuple[Any, ...], ...]
    destination: Path
    destination_name: str
    destination_parent: Path
    destination_parent_descriptor: int
    destination_parent_snapshot: _DirectorySnapshot
    existing_destination_descriptor: int | None
    existing_destination_snapshot: _DirectorySnapshot | None
    existing_destination_tree_snapshot: tuple[tuple[Any, ...], ...] | None


@dataclass
class _PublishOwnershipTransfer:
    """Owned publication callbacks; commit/rollback perform no system calls."""

    prepare: Callable[[_PublishCapability], None]
    commit: Callable[[_PublishCapability], None]
    apply: Callable[[_PublishCapability], tuple[int, ...]]
    rollback: Callable[[_PublishCapability], None]
    retain_previous_in_scratch: bool


_SIGNAL_TRANSLATION_STATE = threading.local()
_SIGNAL_DEFERRAL_STATE = threading.local()
_INTERRUPTED_ERROR = (
    "Python sidecar operation was interrupted after reaching a safe state"
)


def _cleanup_signals() -> frozenset[signal.Signals]:
    values = {signal.SIGINT, signal.SIGTERM}
    if hasattr(signal, "SIGHUP"):
        values.add(signal.SIGHUP)
    return frozenset(values)


def _latch_cleanup_cancellation() -> None:
    """Latch one cancellation and keep later cleanup signals blocked.

    The translation owner is process-lifecycle state, not merely a temporary
    Python exception handler.  Once the first cleanup signal is observed, no
    later INT/TERM/HUP may interrupt process-group cleanup, publish rollback,
    or scratch/fd teardown.  The outermost translation scope drains pending
    signals and restores the caller's mask only after those owners are stable.
    """

    _SIGNAL_TRANSLATION_STATE.cancelled = True
    try:
        signal.pthread_sigmask(signal.SIG_BLOCK, _cleanup_signals())
    except (OSError, ValueError) as exc:
        _SIGNAL_TRANSLATION_STATE.latch_error = exc


def _raise_cleanup_signal(_number: int, _frame: Any) -> None:
    already_latched = bool(
        getattr(_SIGNAL_TRANSLATION_STATE, "cancelled", False)
    )
    _latch_cleanup_cancellation()
    latch_error = getattr(_SIGNAL_TRANSLATION_STATE, "latch_error", None)
    if latch_error is not None:
        raise BuildError(
            "Python sidecar cancellation could not be latched"
        ) from latch_error
    if already_latched or int(
        getattr(_SIGNAL_DEFERRAL_STATE, "depth", 0)
    ):
        return
    raise _DeferredSignalError(_INTERRUPTED_ERROR)


def _drain_pending_cleanup_signals(
    blocked: frozenset[signal.Signals],
    *,
    error_message: str,
) -> bool:
    """Consume process-directed signals while they are still blocked."""

    if not hasattr(signal, "sigpending") or not hasattr(signal, "sigwait"):
        raise BuildError(error_message)
    observed = False
    try:
        while True:
            pending = set(signal.sigpending()).intersection(blocked)
            if not pending:
                return observed
            signal.sigwait(pending)
            observed = True
    except BaseException as exc:
        raise BuildError(error_message) from exc


@contextlib.contextmanager
def _translate_cleanup_signals() -> Any:
    """Translate TERM/HUP/INT under one outermost lifecycle owner.

    Nested callers borrow the outer handlers. The final owner restores the
    caller's handlers while cleanup signals are blocked; once it releases the
    old mask, later signals again follow the caller's disposition. This scope
    does not defer cancellation during its body.
    """

    depth = int(getattr(_SIGNAL_TRANSLATION_STATE, "depth", 0))
    if depth:
        _SIGNAL_TRANSLATION_STATE.depth = depth + 1
        try:
            yield
        finally:
            _SIGNAL_TRANSLATION_STATE.depth = depth
        return

    error_message = "Python sidecar signal translation could not be installed"
    if (
        threading.current_thread() is not threading.main_thread()
        or not hasattr(signal, "pthread_sigmask")
    ):
        raise BuildError(error_message)
    blocked = _cleanup_signals()
    previous_mask: set[signal.Signals] | None = None
    previous_handlers: dict[signal.Signals, Any] = {}
    _SIGNAL_TRANSLATION_STATE.depth = 1
    _SIGNAL_TRANSLATION_STATE.cancelled = False
    _SIGNAL_TRANSLATION_STATE.latch_error = None
    try:
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
        for item in blocked:
            previous_handlers[item] = signal.getsignal(item)
            signal.signal(item, _raise_cleanup_signal)
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    except BaseException as exc:
        if previous_mask is not None:
            try:
                signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
                for item, handler in previous_handlers.items():
                    signal.signal(item, handler)
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            except BaseException:
                pass
        _SIGNAL_TRANSLATION_STATE.depth = 0
        _SIGNAL_TRANSLATION_STATE.cancelled = False
        _SIGNAL_TRANSLATION_STATE.latch_error = None
        raise BuildError(error_message) from exc

    active_error: BaseException | None = None
    deferred = False
    try:
        yield
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        restore_error: BaseException | None = None
        try:
            signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
            deferred = _drain_pending_cleanup_signals(
                blocked,
                error_message="Python sidecar signal translation cleanup failed",
            )
            deferred = deferred or bool(
                getattr(_SIGNAL_TRANSLATION_STATE, "cancelled", False)
            )
            transition_observed = False

            def record_transition_signal(_number: int, _frame: Any) -> None:
                nonlocal transition_observed
                transition_observed = True

            for item in blocked:
                signal.signal(item, record_transition_signal)
            if previous_mask is None:  # pragma: no cover - guarded by setup
                raise BuildError(
                    "Python sidecar signal translation cleanup failed"
                )
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
            deferred = deferred or transition_observed
            deferred = deferred or _drain_pending_cleanup_signals(
                blocked,
                error_message="Python sidecar signal translation cleanup failed",
            )
            for item, handler in previous_handlers.items():
                signal.signal(item, handler)
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        except BaseException as exc:
            restore_error = exc
        latch_error = getattr(_SIGNAL_TRANSLATION_STATE, "latch_error", None)
        _SIGNAL_TRANSLATION_STATE.depth = 0
        _SIGNAL_TRANSLATION_STATE.cancelled = False
        _SIGNAL_TRANSLATION_STATE.latch_error = None
        if restore_error is not None:
            if active_error is not None:
                raise BuildError(
                    "Python sidecar operation failed and signal cleanup failed"
                ) from active_error
            raise BuildError(
                "Python sidecar signal translation cleanup failed"
            ) from restore_error
        if latch_error is not None:
            if active_error is not None:
                raise BuildError(
                    "Python sidecar operation failed and cancellation cleanup failed"
                ) from active_error
            raise BuildError(
                "Python sidecar cancellation cleanup failed"
            ) from latch_error
        if deferred and not isinstance(active_error, _DeferredSignalError):
            raise _DeferredSignalError(_INTERRUPTED_ERROR) from active_error


@contextlib.contextmanager
def _defer_publish_signals(
    *,
    preserve_error: BaseException | None = None,
) -> Any:
    """Defer cleanup signals across a bounded mutation transaction."""

    depth = int(getattr(_SIGNAL_DEFERRAL_STATE, "depth", 0))
    if depth:
        _SIGNAL_DEFERRAL_STATE.depth = depth + 1
        try:
            yield
        finally:
            _SIGNAL_DEFERRAL_STATE.depth = depth
        return

    error_message = "Atomic staging signal deferral is unavailable"
    if not hasattr(signal, "pthread_sigmask"):
        raise BuildError(error_message)
    blocked = _cleanup_signals()
    cancelled_at_entry = bool(
        getattr(_SIGNAL_TRANSLATION_STATE, "cancelled", False)
    )
    _SIGNAL_DEFERRAL_STATE.depth = 1
    try:
        previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    except (OSError, ValueError) as exc:
        _SIGNAL_DEFERRAL_STATE.depth = 0
        raise BuildError(error_message) from exc
    active_error: BaseException | None = None
    deferred = False
    try:
        yield
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        restore_error: BaseException | None = None
        try:
            deferred = _drain_pending_cleanup_signals(
                blocked,
                error_message="Atomic staging signal deferral cleanup failed",
            )
            translation_active = bool(
                getattr(_SIGNAL_TRANSLATION_STATE, "depth", 0)
            )
            cancellation_latched = bool(
                getattr(_SIGNAL_TRANSLATION_STATE, "cancelled", False)
            )
            deferred = deferred or (
                cancellation_latched and not cancelled_at_entry
            )
            if deferred and translation_active:
                _latch_cleanup_cancellation()
                cancellation_latched = True
            restore_mask = set(previous)
            if cancellation_latched:
                restore_mask.update(blocked)
            signal.pthread_sigmask(signal.SIG_SETMASK, restore_mask)
        except BaseException as exc:
            restore_error = exc
        _SIGNAL_DEFERRAL_STATE.depth = 0
        if restore_error is not None:
            if active_error is not None:
                raise BuildError(
                    "Atomic staging failed and signal cleanup failed"
                ) from active_error
            raise BuildError(
                "Atomic staging signal deferral cleanup failed"
            ) from restore_error
        if deferred and active_error is None and preserve_error is None:
            raise _DeferredSignalError(_INTERRUPTED_ERROR)


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


def _verify_exact_toolchain_environment(
    environment: Mapping[str, str],
) -> tuple[dict[str, Any], bytes]:
    """Revalidate the sealed installed tree before any installed code use."""

    try:
        import bootstrap_python_sidecar as bootstrap
    except ImportError as exc:
        raise BuildError("Python toolchain verifier cannot be imported") from exc
    try:
        verifier_path = Path(bootstrap.__file__).resolve(strict=True)
    except (OSError, RuntimeError, TypeError) as exc:
        raise BuildError("Python toolchain verifier path is unavailable") from exc
    if verifier_path != TOOLS_ROOT / "bootstrap_python_sidecar.py":
        raise BuildError("Python toolchain verifier path is unexpected")
    try:
        evidence, payload = bootstrap.verify_toolchain_environment(environment)
    except bootstrap.ToolchainBootstrapError as exc:
        raise BuildError("Installed Python toolchain seal is invalid") from exc
    if payload != _canonical_json_bytes(evidence) + b"\n":
        raise BuildError("Python toolchain evidence is not canonical")
    return evidence, payload


def _validate_toolchain_evidence_against_source(
    evidence: Mapping[str, Any],
    *,
    build_versions: Mapping[str, str],
    packaging_root: Path,
    backend_root: Path,
) -> None:
    expected_tools = {
        BUILD_TOOL_EVIDENCE_KEYS[name]: version
        for name, version in sorted(build_versions.items())
    }
    if (
        set(build_versions) != set(BUILD_TOOL_EVIDENCE_KEYS)
        or evidence.get("buildRequirementsLockSha256")
        != _sha256_file(packaging_root / "build-requirements.lock")
        or evidence.get("runtimeLockSha256")
        != _sha256_file(backend_root / "uv.lock")
        or evidence.get("buildTools") != expected_tools
        or re.fullmatch(
            r"[0-9a-f]{64}",
            str(evidence.get("runtimeRequirementsSha256", "")),
        )
        is None
        or re.fullmatch(
            r"[0-9a-f]{64}",
            str(evidence.get("installedTreeContentSha256", "")),
        )
        is None
    ):
        raise BuildError("Python toolchain evidence differs from exact source locks")


def _write_toolchain_evidence_artifact(
    bundle: Path,
    payload: bytes,
) -> str:
    destination = bundle / TOOLCHAIN_EVIDENCE_ARTIFACT
    descriptor: int | None = None
    try:
        descriptor = os.open(
            destination,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | os.O_CLOEXEC,
            0o600,
        )
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise BuildError("Python toolchain evidence could not be written")
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o644)
        final = os.fstat(descriptor)
        observed = destination.lstat()
        if (
            not stat.S_ISREG(final.st_mode)
            or stat.S_ISLNK(observed.st_mode)
            or final.st_uid != os.geteuid()
            or final.st_nlink != 1
            or final.st_size != len(payload)
            or _stat_metadata(final) != _stat_metadata(observed)
        ):
            raise BuildError("Python toolchain evidence artifact is unsafe")
    except BuildError:
        raise
    except OSError as exc:
        raise BuildError("Python toolchain evidence could not be written") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as exc:
                if sys.exception() is None:
                    raise BuildError(
                        "Python toolchain evidence descriptor could not be closed"
                    ) from exc
    return TOOLCHAIN_EVIDENCE_ARTIFACT


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
    except BaseException:
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


def _stat_metadata(info: os.stat_result) -> tuple[int, ...]:
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


def _stable_directory_identity(
    value: _DirectorySnapshot | os.stat_result,
) -> tuple[int, ...]:
    if isinstance(value, _DirectorySnapshot):
        return (
            value.device,
            value.inode,
            value.mode,
            value.uid,
            value.gid,
        )
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
    )


def _snapshot_from_stat(
    info: os.stat_result,
    entries: tuple[str, ...],
) -> _DirectorySnapshot:
    return _DirectorySnapshot(
        device=info.st_dev,
        inode=info.st_ino,
        mode=info.st_mode,
        uid=info.st_uid,
        gid=info.st_gid,
        links=info.st_nlink,
        size=info.st_size,
        mtime_ns=info.st_mtime_ns,
        ctime_ns=info.st_ctime_ns,
        entries=entries,
    )


def _capture_bound_directory(
    descriptor: int,
    path: Path,
    *,
    parent_descriptor: int | None,
    relative_name: str | None,
    expected: _DirectorySnapshot | None,
    expected_mode: int | None,
    exact_entries: tuple[str, ...] | None,
    error_message: str,
) -> _DirectorySnapshot:
    """Bind a canonical path entry to one held directory descriptor."""

    try:
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise BuildError(error_message)
        fd_before = os.fstat(descriptor)
        path_before = path.lstat()
        relative_before = (
            os.stat(
                relative_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if parent_descriptor is not None and relative_name is not None
            else path_before
        )
        if (
            not stat.S_ISDIR(fd_before.st_mode)
            or not stat.S_ISDIR(path_before.st_mode)
            or not stat.S_ISDIR(relative_before.st_mode)
            or stat.S_ISLNK(path_before.st_mode)
            or stat.S_ISLNK(relative_before.st_mode)
            or fd_before.st_uid != os.geteuid()
            or path_before.st_uid != os.geteuid()
            or relative_before.st_uid != os.geteuid()
            or _stat_metadata(fd_before) != _stat_metadata(path_before)
            or _stat_metadata(fd_before) != _stat_metadata(relative_before)
            or (
                expected_mode is not None
                and stat.S_IMODE(fd_before.st_mode) != expected_mode
            )
            or (
                expected is not None
                and _stable_directory_identity(fd_before)
                != _stable_directory_identity(expected)
            )
        ):
            raise BuildError(error_message)
        entries = tuple(sorted(os.listdir(descriptor)))
        fd_after = os.fstat(descriptor)
        path_after = path.lstat()
        relative_after = (
            os.stat(
                relative_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if parent_descriptor is not None and relative_name is not None
            else path_after
        )
        if (
            _stat_metadata(fd_after) != _stat_metadata(fd_before)
            or _stat_metadata(path_after) != _stat_metadata(fd_before)
            or _stat_metadata(relative_after) != _stat_metadata(fd_before)
            or (exact_entries is not None and entries != exact_entries)
        ):
            raise BuildError(error_message)
        return _snapshot_from_stat(fd_after, entries)
    except BuildError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise BuildError(error_message) from exc


def _create_bound_child_directory(
    *,
    parent_descriptor: int,
    parent_path: Path,
    name: str,
    mode: int,
    error_message: str,
) -> tuple[int, _DirectorySnapshot]:
    """Create, snapshot, open, and bind one child without an interrupt gap.

    Once mkdir succeeds, any failure preserves the untrusted namespace state;
    callers must poison the owning lifecycle instead of deleting by name.
    """

    descriptor: int | None = None
    created = False
    try:
        with _defer_publish_signals():
            os.mkdir(name, mode=mode, dir_fd=parent_descriptor)
            created = True
            created_info = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            parent_info = os.fstat(parent_descriptor)
            if (
                not stat.S_ISDIR(created_info.st_mode)
                or stat.S_ISLNK(created_info.st_mode)
                or created_info.st_uid != os.geteuid()
                or stat.S_IMODE(created_info.st_mode) != mode
                or created_info.st_dev != parent_info.st_dev
            ):
                raise _CleanupBlockedError(error_message)
            created_snapshot = _snapshot_from_stat(created_info, ())
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_descriptor,
            )
            snapshot = _capture_bound_directory(
                descriptor,
                parent_path / name,
                parent_descriptor=parent_descriptor,
                relative_name=name,
                expected=created_snapshot,
                expected_mode=mode,
                exact_entries=(),
                error_message=error_message,
            )
        result = descriptor
        descriptor = None
        return result, snapshot
    except BaseException as exc:
        if created:
            raise _CleanupBlockedError(error_message) from exc
        if isinstance(exc, BuildError):
            raise
        raise BuildError(error_message) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _tree_metadata_snapshot(
    descriptor: int,
    *,
    error_message: str,
    maximum_entries: int = MAX_SOURCE_SNAPSHOT_FILES,
) -> tuple[tuple[Any, ...], ...]:
    """Capture descriptor-relative inode metadata for a complete tree."""

    records: list[tuple[Any, ...]] = []

    def visit(directory_descriptor: int, prefix: str, depth: int) -> None:
        if depth > 128:
            raise BuildError(error_message)
        try:
            names = tuple(sorted(os.listdir(directory_descriptor)))
        except OSError as exc:
            raise BuildError(error_message) from exc
        for name in names:
            if not name or "/" in name or "\x00" in name:
                raise BuildError(error_message)
            try:
                before = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise BuildError(error_message) from exc
            relative = f"{prefix}/{name}" if prefix else name
            link_target: str | None = None
            if stat.S_ISLNK(before.st_mode):
                try:
                    link_target = os.readlink(name, dir_fd=directory_descriptor)
                except OSError as exc:
                    raise BuildError(error_message) from exc
            records.append((relative, *_stat_metadata(before), link_target))
            if len(records) > maximum_entries:
                raise BuildError(error_message)
            if stat.S_ISDIR(before.st_mode) and not stat.S_ISLNK(before.st_mode):
                child_descriptor: int | None = None
                try:
                    child_descriptor = os.open(
                        name,
                        os.O_RDONLY
                        | os.O_DIRECTORY
                        | os.O_NOFOLLOW
                        | os.O_CLOEXEC,
                        dir_fd=directory_descriptor,
                    )
                    opened = os.fstat(child_descriptor)
                    relative_now = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        _stat_metadata(opened) != _stat_metadata(before)
                        or _stat_metadata(relative_now) != _stat_metadata(before)
                    ):
                        raise BuildError(error_message)
                    visit(child_descriptor, relative, depth + 1)
                    after = os.fstat(child_descriptor)
                    relative_after = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        _stat_metadata(after) != _stat_metadata(opened)
                        or _stat_metadata(relative_after) != _stat_metadata(opened)
                    ):
                        raise BuildError(error_message)
                except BuildError:
                    raise
                except OSError as exc:
                    raise BuildError(error_message) from exc
                finally:
                    if child_descriptor is not None:
                        try:
                            os.close(child_descriptor)
                        except OSError as exc:
                            raise BuildError(error_message) from exc

    visit(descriptor, "", 0)
    return tuple(records)


def _remove_tree_contents(
    descriptor: int,
    *,
    error_message: str,
    depth: int = 0,
) -> None:
    """Quarantine captured leaves and refuse every observable identity drift.

    Destructive calls use a held parent and an unpredictable quarantine name;
    the original leaf name is never passed to ``unlink``/``rmdir``.  Identity
    is rechecked in the final deletion wrapper, and an observed replacement is
    restored no-replace and retained.  Portable POSIX has no unlink-by-fd, so
    this does not claim protection from an unobservable same-UID namespace
    write in the final syscall interval.
    """

    if depth > 128:
        raise BuildError(error_message)
    try:
        names = tuple(sorted(os.listdir(descriptor)))
    except OSError as exc:
        raise BuildError(error_message) from exc
    for name in names:
        if not name or "/" in name or "\x00" in name:
            raise BuildError(error_message)
        quarantine = f".lcf-delete-{secrets.token_hex(16)}"
        try:
            before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(before.st_mode) and not stat.S_ISLNK(before.st_mode):
                child_descriptor = os.open(
                    name,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW
                    | os.O_CLOEXEC,
                    dir_fd=descriptor,
                )
                try:
                    opened = os.fstat(child_descriptor)
                    relative = os.stat(
                        name,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        _stat_metadata(opened) != _stat_metadata(before)
                        or _stat_metadata(relative) != _stat_metadata(before)
                        or opened.st_uid != os.geteuid()
                        or stat.S_IMODE(opened.st_mode) & 0o022
                    ):
                        raise BuildError(error_message)
                    _rename_noreplace_at(
                        descriptor,
                        name,
                        descriptor,
                        quarantine,
                    )
                    quarantined = os.stat(
                        quarantine,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        _stable_directory_identity(quarantined)
                        != _stable_directory_identity(opened)
                    ):
                        try:
                            _rename_noreplace_at(
                                descriptor,
                                quarantine,
                                descriptor,
                                name,
                            )
                        except BaseException as restore_error:
                            raise _CleanupBlockedError(error_message) from restore_error
                        raise _CleanupBlockedError(error_message)
                    os.fchmod(child_descriptor, 0o700)
                    opened = os.fstat(child_descriptor)
                    relative = os.stat(
                        quarantine,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        _stable_directory_identity(relative)
                        != _stable_directory_identity(opened)
                    ):
                        raise BuildError(error_message)
                    _remove_tree_contents(
                        child_descriptor,
                        error_message=error_message,
                        depth=depth + 1,
                    )
                    if os.listdir(child_descriptor):
                        raise BuildError(error_message)
                    after = os.fstat(child_descriptor)
                    relative_after = os.stat(
                        quarantine,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        _stable_directory_identity(after)
                        != _stable_directory_identity(opened)
                        or _stable_directory_identity(relative_after)
                        != _stable_directory_identity(opened)
                    ):
                        raise BuildError(error_message)
                    _remove_verified_quarantine_leaf(
                        descriptor,
                        original_name=name,
                        quarantine_name=quarantine,
                        expected=after,
                        directory=True,
                        error_message=error_message,
                    )
                finally:
                    os.close(child_descriptor)
            elif (
                stat.S_ISREG(before.st_mode)
                or stat.S_ISLNK(before.st_mode)
                or stat.S_ISSOCK(before.st_mode)
            ):
                _rename_noreplace_at(
                    descriptor,
                    name,
                    descriptor,
                    quarantine,
                )
                relative = os.stat(
                    quarantine,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
                if (
                    _stable_directory_identity(relative)
                    != _stable_directory_identity(before)
                ):
                    try:
                        _rename_noreplace_at(
                            descriptor,
                            quarantine,
                            descriptor,
                            name,
                        )
                    except BaseException as restore_error:
                        raise _CleanupBlockedError(error_message) from restore_error
                    raise _CleanupBlockedError(error_message)
                _remove_verified_quarantine_leaf(
                    descriptor,
                    original_name=name,
                    quarantine_name=quarantine,
                    expected=before,
                    directory=False,
                    error_message=error_message,
                )
            else:
                raise BuildError(error_message)
        except BuildError:
            raise
        except OSError as exc:
            raise BuildError(error_message) from exc


def _remove_verified_quarantine_leaf(
    parent_descriptor: int,
    *,
    original_name: str,
    quarantine_name: str,
    expected: os.stat_result,
    directory: bool,
    error_message: str,
) -> None:
    """Final observable identity gate before a quarantine name is removed."""

    try:
        current = os.stat(
            quarantine_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if _stable_directory_identity(current) != _stable_directory_identity(expected):
            try:
                _rename_noreplace_at(
                    parent_descriptor,
                    quarantine_name,
                    parent_descriptor,
                    original_name,
                )
            except BaseException as restore_error:
                raise _CleanupBlockedError(error_message) from restore_error
            raise _CleanupBlockedError(error_message)
        if directory:
            os.rmdir(quarantine_name, dir_fd=parent_descriptor)
        else:
            os.unlink(quarantine_name, dir_fd=parent_descriptor)
    except _CleanupBlockedError:
        raise
    except OSError as exc:
        raise BuildError(error_message) from exc


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


def _isolated_git_environment() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _isolated_git_command(
    *arguments: str,
    repository_root: Path = REPOSITORY_ROOT,
) -> list[str]:
    error_message = "Git provenance repository boundary is unsafe"
    git_directory = repository_root / ".git"
    try:
        root_info = repository_root.lstat()
        git_info = git_directory.lstat()
        if (
            not repository_root.is_absolute()
            or repository_root.resolve(strict=True) != repository_root
            or not stat.S_ISDIR(root_info.st_mode)
            or stat.S_ISLNK(root_info.st_mode)
            or root_info.st_uid != os.geteuid()
            or stat.S_IMODE(root_info.st_mode) & 0o022
            or not stat.S_ISDIR(git_info.st_mode)
            or stat.S_ISLNK(git_info.st_mode)
            or git_info.st_uid != os.geteuid()
            or git_directory.resolve(strict=True) != git_directory
            or stat.S_IMODE(git_info.st_mode) & 0o022
        ):
            raise BuildError(error_message)
    except BuildError:
        raise
    except (OSError, RuntimeError) as exc:
        raise BuildError(error_message) from exc
    return [
        "/usr/bin/git",
        f"--git-dir={git_directory}",
        f"--work-tree={repository_root}",
        "-c",
        "core.bare=false",
        "-c",
        f"core.worktree={repository_root}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        "-c",
        "core.excludesFile=/dev/null",
        "-c",
        "core.attributesFile=/dev/null",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fileMode=true",
        "-c",
        "core.symlinks=true",
        "-c",
        "status.showUntrackedFiles=all",
        "-c",
        "diff.ignoreSubmodules=none",
        *arguments,
    ]


def _git_output(
    *arguments: str,
    repository_root: Path = REPOSITORY_ROOT,
) -> str:
    return _run_checked(
        _isolated_git_command(*arguments, repository_root=repository_root),
        cwd=repository_root,
        env=_isolated_git_environment(),
        label="Git provenance check",
    )


def _git_bytes(
    *arguments: str,
    repository_root: Path = REPOSITORY_ROOT,
) -> bytes:
    try:
        completed = subprocess.run(
            _isolated_git_command(*arguments, repository_root=repository_root),
            cwd=repository_root,
            env=_isolated_git_environment(),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise BuildError("Git provenance check failed") from exc
    return completed.stdout


def _selected_source_commit(environment: Mapping[str, str]) -> str:
    """Return the explicit reviewed checkout SHA; never use event metadata."""

    repository_commit = environment.get("LCF_SOURCE_SHA", "").lower()
    if re.fullmatch(r"[0-9a-f]{40}", repository_commit) is None:
        raise BuildError("LCF_SOURCE_SHA must be a full Git commit SHA")
    return repository_commit


def _selected_source_tree(environment: Mapping[str, str]) -> str:
    repository_tree = environment.get("LCF_SOURCE_TREE", "").lower()
    if re.fullmatch(r"[0-9a-f]{40}", repository_tree) is None:
        raise BuildError("LCF_SOURCE_TREE must be a full Git tree SHA")
    return repository_tree


def _repository_tree_inventory(
    repository_commit: str,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> tuple[_TreeEntry, ...]:
    """Return the exact safe blob inventory for one commit tree."""

    raw = _git_bytes(
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        repository_commit,
        repository_root=repository_root,
    )
    result: list[_TreeEntry] = []
    seen: set[str] = set()
    for encoded in raw.split(b"\0"):
        if not encoded:
            continue
        try:
            header, raw_path = encoded.split(b"\t", 1)
            mode, object_type, object_id = header.decode("ascii").split(" ")
            path = raw_path.decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise BuildError("Git source tree inventory is malformed") from exc
        pure = PurePosixPath(path)
        if (
            object_type != "blob"
            or mode not in {"100644", "100755", "120000"}
            or re.fullmatch(r"[0-9a-f]{40}", object_id) is None
            or not path
            or pure.is_absolute()
            or pure.as_posix() != path
            or any(part in {"", ".", "..", ".git"} for part in pure.parts)
            or "\\" in path
            or any(ord(character) < 0x20 for character in path)
            or path in seen
        ):
            raise BuildError("Git source tree inventory is unsafe")
        seen.add(path)
        result.append(
            _TreeEntry(
                path=path,
                mode=mode,
                object_type=object_type,
                object_id=object_id,
            )
        )
        if len(result) > MAX_SOURCE_SNAPSHOT_FILES:
            raise BuildError("Git source tree inventory exceeds its file bound")
    if not result:
        raise BuildError("Git source tree inventory is empty")
    return tuple(sorted(result, key=lambda item: item.path))


def _source_snapshot_sha256(entries: Sequence[_TreeEntry]) -> str:
    payload = [
        {
            "mode": entry.mode,
            "objectId": entry.object_id,
            "path": entry.path,
            "type": entry.object_type,
        }
        for entry in entries
    ]
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _validate_local_git_configuration(
    *,
    repository_root: Path,
) -> None:
    """Reject repository-local configuration that can execute or hide input."""

    error_message = "Git repository local configuration is unsafe"
    config = repository_root / ".git" / "config"
    try:
        info = config.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or info.st_size > 1024 * 1024
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise BuildError(error_message)
        completed = subprocess.run(
            [
                "/usr/bin/git",
                f"--git-dir={repository_root / '.git'}",
                "config",
                f"--file={config}",
                "--no-includes",
                "--null",
                "--list",
            ],
            cwd=repository_root,
            env=_isolated_git_environment(),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except BuildError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise BuildError(error_message) from exc
    allowed_values: dict[str, frozenset[str] | None] = {
        "core.repositoryformatversion": frozenset({"0"}),
        "core.filemode": frozenset({"true", "false"}),
        "core.bare": frozenset({"false"}),
        "core.logallrefupdates": frozenset({"true"}),
        "core.ignorecase": frozenset({"true", "false"}),
        "core.precomposeunicode": frozenset({"true", "false"}),
        "core.symlinks": frozenset({"true", "false"}),
        "extensions.objectformat": frozenset({"sha1"}),
        "gc.auto": frozenset({"0"}),
        "user.name": None,
        "user.email": None,
    }
    try:
        records: list[tuple[str, str]] = []
        for raw in completed.stdout.split(b"\0"):
            if not raw:
                continue
            encoded_key, separator, encoded_value = raw.partition(b"\n")
            if not separator:
                raise BuildError(error_message)
            records.append(
                (
                    encoded_key.decode("utf-8", errors="strict").lower(),
                    encoded_value.decode("utf-8", errors="strict"),
                )
            )
    except UnicodeDecodeError as exc:
        raise BuildError(error_message) from exc
    for key, value in records:
        allowed_pattern = (
            re.fullmatch(r"remote\..+\.(?:url|pushurl|fetch)", key)
            or re.fullmatch(r"branch\..+\.(?:remote|merge|description)", key)
        )
        reviewed_values = allowed_values.get(key)
        if (
            key in allowed_values
            and (reviewed_values is None or value.lower() in reviewed_values)
        ):
            continue
        if allowed_pattern is None:
            raise BuildError(error_message)


def _validate_git_info_overrides(*, repository_root: Path) -> None:
    """Reject local info files that can alter visibility or object lookup."""

    error_message = "Git repository local attributes or excludes are unsafe"
    comment_only = (Path("info") / "attributes", Path("info") / "exclude")
    must_be_empty = (
        Path("info") / "grafts",
        Path("objects") / "info" / "alternates",
        Path("objects") / "info" / "http-alternates",
    )
    for relative in (*comment_only, *must_be_empty):
        path = repository_root / ".git" / relative
        descriptor: int | None = None
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise BuildError(error_message) from exc
        try:
            before = os.fstat(descriptor)
            path_info = path.lstat()
            if (
                not stat.S_ISREG(before.st_mode)
                or stat.S_ISLNK(path_info.st_mode)
                or _stat_metadata(before) != _stat_metadata(path_info)
                or before.st_uid != os.geteuid()
                or before.st_nlink != 1
                or before.st_size > 1024 * 1024
                or stat.S_IMODE(before.st_mode) & 0o022
            ):
                raise BuildError(error_message)
            payload = bytearray()
            while len(payload) <= 1024 * 1024:
                chunk = os.read(descriptor, min(65536, 1024 * 1024 + 1 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
            after = os.fstat(descriptor)
            path_after = path.lstat()
            if (
                len(payload) > 1024 * 1024
                or _stat_metadata(after) != _stat_metadata(before)
                or _stat_metadata(path_after) != _stat_metadata(before)
            ):
                raise BuildError(error_message)
            if relative in must_be_empty:
                if payload:
                    raise BuildError(error_message)
            else:
                try:
                    lines = payload.decode("utf-8", errors="strict").splitlines()
                except UnicodeDecodeError as exc:
                    raise BuildError(error_message) from exc
                if any(
                    line.strip() and not line.lstrip().startswith("#")
                    for line in lines
                ):
                    raise BuildError(error_message)
        except OSError as exc:
            raise BuildError(error_message) from exc
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError as exc:
                    if sys.exception() is None:
                        raise BuildError(error_message) from exc


def _validate_git_index(
    inventory: Sequence[_TreeEntry],
    *,
    repository_root: Path,
) -> None:
    """Require a stage-zero index with no hidden per-entry flags."""

    error_message = "Git index state is unsafe"
    expected = {
        entry.path: (entry.mode, entry.object_id)
        for entry in inventory
    }
    staged: dict[str, tuple[str, str]] = {}
    raw_stage = _git_bytes(
        "ls-files",
        "--stage",
        "-z",
        repository_root=repository_root,
    )
    for raw in raw_stage.split(b"\0"):
        if not raw:
            continue
        try:
            header, encoded_path = raw.split(b"\t", 1)
            mode, object_id, stage = header.decode("ascii").split(" ")
            path = encoded_path.decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise BuildError(error_message) from exc
        if (
            stage != "0"
            or path in staged
            or re.fullmatch(r"[0-9a-f]{40}", object_id) is None
        ):
            raise BuildError(error_message)
        staged[path] = (mode, object_id)
    if staged != expected:
        raise BuildError(error_message)
    raw_flags = _git_bytes(
        "ls-files",
        "-v",
        "-z",
        repository_root=repository_root,
    )
    flagged_paths: set[str] = set()
    for raw in raw_flags.split(b"\0"):
        if not raw:
            continue
        if not raw.startswith(b"H "):
            raise BuildError(error_message)
        try:
            path = raw[2:].decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise BuildError(error_message) from exc
        if path in flagged_paths:
            raise BuildError(error_message)
        flagged_paths.add(path)
    if flagged_paths != set(expected):
        raise BuildError(error_message)


def _validate_tracked_worktree(
    inventory: Sequence[_TreeEntry],
    *,
    repository_root: Path,
) -> None:
    """Compare tracked no-follow bytes and modes directly with commit blobs."""

    error_message = "Tracked worktree differs from the selected commit"
    root_descriptor: int | None = None
    total_size = 0

    def validate_directory(info: os.stat_result) -> None:
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise BuildError(error_message)

    try:
        root_before = repository_root.lstat()
        validate_directory(root_before)
        root_descriptor = os.open(
            repository_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        root_opened = os.fstat(root_descriptor)
        validate_directory(root_opened)
        if _stat_metadata(root_opened) != _stat_metadata(root_before):
            raise BuildError(error_message)
        for entry in inventory:
            pure = PurePosixPath(entry.path)
            directory_descriptor = os.dup(root_descriptor)
            open_directories = [directory_descriptor]
            bindings: list[tuple[int, str, int, tuple[int, ...]]] = []
            try:
                if len(pure.parts) > 128:
                    raise BuildError(error_message)
                for part in pure.parts[:-1]:
                    before_child = os.stat(
                        part,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    validate_directory(before_child)
                    child = os.open(
                        part,
                        os.O_RDONLY
                        | os.O_DIRECTORY
                        | os.O_NOFOLLOW
                        | os.O_CLOEXEC,
                        dir_fd=directory_descriptor,
                    )
                    child_opened = os.fstat(child)
                    relative_child = os.stat(
                        part,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    validate_directory(child_opened)
                    if (
                        _stat_metadata(child_opened) != _stat_metadata(before_child)
                        or _stat_metadata(relative_child)
                        != _stat_metadata(before_child)
                    ):
                        os.close(child)
                        raise BuildError(error_message)
                    bindings.append(
                        (
                            directory_descriptor,
                            part,
                            child,
                            _stat_metadata(child_opened),
                        )
                    )
                    open_directories.append(child)
                    directory_descriptor = child
                parent_before = os.fstat(directory_descriptor)
                validate_directory(parent_before)
                leaf = pure.name
                before = os.stat(
                    leaf,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                if entry.mode == "120000":
                    if not stat.S_ISLNK(before.st_mode) or before.st_uid != os.geteuid():
                        raise BuildError(error_message)
                    payload = os.fsencode(os.readlink(leaf, dir_fd=directory_descriptor))
                    payload_chunks: Sequence[bytes] = (payload,)
                    payload_size = len(payload)
                    total_size += len(payload)
                    after = os.stat(
                        leaf,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if _stat_metadata(after) != _stat_metadata(before):
                        raise BuildError(error_message)
                else:
                    expected_mode = 0o755 if entry.mode == "100755" else 0o644
                    if (
                        not stat.S_ISREG(before.st_mode)
                        or stat.S_ISLNK(before.st_mode)
                        or before.st_uid != os.geteuid()
                        or before.st_nlink != 1
                        or before.st_size > MAX_SOURCE_SNAPSHOT_FILE_BYTES
                        or stat.S_IMODE(before.st_mode) != expected_mode
                    ):
                        raise BuildError(error_message)
                    total_size += before.st_size
                    descriptor = os.open(
                        leaf,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=directory_descriptor,
                    )
                    try:
                        opened = os.fstat(descriptor)
                        if _stat_metadata(opened) != _stat_metadata(before):
                            raise BuildError(error_message)
                        chunks: list[bytes] = []
                        remaining = opened.st_size
                        while remaining:
                            chunk = os.read(descriptor, min(1024 * 1024, remaining))
                            if not chunk:
                                raise BuildError(error_message)
                            chunks.append(chunk)
                            remaining -= len(chunk)
                        if os.read(descriptor, 1):
                            raise BuildError(error_message)
                        after = os.fstat(descriptor)
                        relative_after = os.stat(
                            leaf,
                            dir_fd=directory_descriptor,
                            follow_symlinks=False,
                        )
                        if (
                            _stat_metadata(after) != _stat_metadata(opened)
                            or _stat_metadata(relative_after) != _stat_metadata(opened)
                        ):
                            raise BuildError(error_message)
                        payload_chunks = chunks
                        payload_size = opened.st_size
                    finally:
                        os.close(descriptor)
                if total_size > MAX_SOURCE_SNAPSHOT_TOTAL_BYTES:
                    raise BuildError(error_message)
                if _git_blob_digest(payload_size, payload_chunks) != entry.object_id:
                    raise BuildError(error_message)
                if _stat_metadata(os.fstat(directory_descriptor)) != _stat_metadata(
                    parent_before
                ):
                    raise BuildError(error_message)
                for parent, name, child, expected_child in reversed(bindings):
                    if (
                        _stat_metadata(os.fstat(child)) != expected_child
                        or _stat_metadata(
                            os.stat(
                                name,
                                dir_fd=parent,
                                follow_symlinks=False,
                            )
                        )
                        != expected_child
                    ):
                        raise BuildError(error_message)
                if (
                    _stat_metadata(os.fstat(root_descriptor))
                    != _stat_metadata(root_opened)
                    or _stat_metadata(repository_root.lstat())
                    != _stat_metadata(root_opened)
                ):
                    raise BuildError(error_message)
            finally:
                close_error: OSError | None = None
                for descriptor in reversed(open_directories):
                    try:
                        os.close(descriptor)
                    except OSError as exc:
                        close_error = close_error or exc
                if close_error is not None and sys.exception() is None:
                    raise BuildError(error_message) from close_error
    except BuildError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise BuildError(error_message) from exc
    finally:
        if root_descriptor is not None:
            try:
                os.close(root_descriptor)
            except OSError as exc:
                if sys.exception() is None:
                    raise BuildError(error_message) from exc


def _validate_repository_state(
    environment: Mapping[str, str],
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    repository_commit = _selected_source_commit(environment)
    repository_tree = _selected_source_tree(environment)
    _validate_local_git_configuration(repository_root=repository_root)
    _validate_git_info_overrides(repository_root=repository_root)
    if (
        _git_output("rev-parse", "HEAD", repository_root=repository_root).lower()
        != repository_commit
        or _git_output(
            "rev-parse",
            "HEAD^{tree}",
            repository_root=repository_root,
        ).lower()
        != repository_tree
        or _git_output(
            "rev-parse",
            f"{repository_commit}^{{tree}}",
            repository_root=repository_root,
        ).lower()
        != repository_tree
        or _git_output("write-tree", repository_root=repository_root).lower()
        != repository_tree
    ):
        raise BuildError("Selected Git commit/tree does not identify the checkout")
    inventory = _repository_tree_inventory(
        repository_commit,
        repository_root=repository_root,
    )
    _validate_git_index(inventory, repository_root=repository_root)
    _validate_tracked_worktree(inventory, repository_root=repository_root)
    if _git_output(
        "status",
        "--porcelain=v2",
        "--untracked-files=all",
        repository_root=repository_root,
    ):
        raise BuildError("Source changes must be committed before packaging")
    if _git_output(
        "submodule",
        "status",
        "--recursive",
        repository_root=repository_root,
    ):
        # Exact snapshot materialization intentionally has no implicit
        # submodule network or secondary-checkout contract.
        raise BuildError("Git submodules are not supported by the exact source snapshot")
    return {
        "repositoryCommit": repository_commit,
        "repositoryTree": repository_tree,
        "sourceSnapshotSha256": _source_snapshot_sha256(inventory),
        "sourceInventory": inventory,
    }


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

    repository_state = _validate_repository_state(environment)
    repository_commit = str(repository_state["repositoryCommit"])
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
        "repositoryTree": repository_state["repositoryTree"],
        "sourceSnapshotSha256": repository_state["sourceSnapshotSha256"],
        "sourceDateEpoch": source_epoch,
        "runnerImage": target.get("runnerLabel"),
        "runnerImageVersion": runner_version,
        "macosDeploymentTarget": target.get("deploymentTarget"),
        "xcodeVersion": xcode_version,
        "sdkVersion": sdk_version,
    }


def verify_repository_provenance(release: Mapping[str, Any]) -> None:
    environment = {
        "LCF_SOURCE_SHA": str(release.get("repositoryCommit", "")),
        "LCF_SOURCE_TREE": str(release.get("repositoryTree", "")),
    }
    state = _validate_repository_state(environment)
    if (
        state.get("sourceSnapshotSha256")
        != release.get("sourceSnapshotSha256")
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


def verify_uv_lock(
    uv_executable: Path,
    *,
    backend_root: Path,
    cache_directory: Path,
    cache_parent_descriptor: int | None = None,
    cache_descriptor: int | None = None,
    cache_snapshot: _DirectorySnapshot | None = None,
    source_descriptor: int | None = None,
) -> None:
    if not uv_executable.is_absolute():
        raise BuildError("uv executable path must be absolute")
    active_python = Path(sys.executable)
    if not active_python.is_absolute():
        raise BuildError("Build venv Python path must be absolute")
    backend_descriptor: int | None = None
    backend_identity: tuple[int, ...] | None = None
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
    active_cache_descriptor = cache_descriptor
    owns_cache_descriptor = False
    try:
        if source_descriptor is not None:
            try:
                held_source = os.fstat(source_descriptor)
                source_path = backend_root.parent
                path_source = source_path.lstat()
                if (
                    not source_path.is_absolute()
                    or backend_root != source_path / "backend"
                    or stat.S_ISLNK(path_source.st_mode)
                    or _stat_metadata(held_source) != _stat_metadata(path_source)
                ):
                    raise BuildError("uv source capability is unavailable")
                backend_descriptor = os.open(
                    "backend",
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW
                    | os.O_CLOEXEC,
                    dir_fd=source_descriptor,
                )
                held_backend = os.fstat(backend_descriptor)
                relative_backend = os.stat(
                    "backend",
                    dir_fd=source_descriptor,
                    follow_symlinks=False,
                )
                path_backend = backend_root.lstat()
                backend_identity = _stat_metadata(held_backend)
                if (
                    not stat.S_ISDIR(held_backend.st_mode)
                    or backend_identity != _stat_metadata(relative_backend)
                    or backend_identity != _stat_metadata(path_backend)
                    or held_backend.st_uid != os.geteuid()
                    or stat.S_IMODE(held_backend.st_mode) & 0o022
                ):
                    raise BuildError("uv source capability is unavailable")
            except BuildError:
                raise
            except (OSError, RuntimeError, ValueError) as exc:
                raise BuildError("uv source capability is unavailable") from exc
        if active_cache_descriptor is None:
            active_cache_descriptor = os.open(
                cache_directory,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            owns_cache_descriptor = True
        elif cache_snapshot is None:
            raise BuildError("uv cache capability is unsafe")
        captured_cache = _capture_bound_directory(
            active_cache_descriptor,
            cache_directory,
            parent_descriptor=cache_parent_descriptor,
            relative_name=(
                cache_directory.name
                if cache_parent_descriptor is not None
                else None
            ),
            expected=cache_snapshot,
            expected_mode=0o700,
            exact_entries=(),
            error_message="uv cache capability is unsafe",
        )
        command = (
            str(resolved),
            "lock",
            "--check",
            "--python",
            str(resolved_python),
        )
        completed = subprocess.run(
            list(command),
            cwd=backend_root,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
                "LC_ALL": "C",
                "UV_CACHE_DIR": str(cache_directory),
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
            pass_fds=(),
            close_fds=True,
        )
        if backend_descriptor is not None:
            if (
                backend_identity != _stat_metadata(os.fstat(backend_descriptor))
                or backend_identity != _stat_metadata(backend_root.lstat())
            ):
                raise BuildError("uv source capability changed during lock verification")
        _capture_bound_directory(
            active_cache_descriptor,
            cache_directory,
            parent_descriptor=cache_parent_descriptor,
            relative_name=(
                cache_directory.name
                if cache_parent_descriptor is not None
                else None
            ),
            expected=captured_cache,
            expected_mode=0o700,
            exact_entries=None,
            error_message="uv cache capability changed during lock verification",
        )
    except subprocess.TimeoutExpired as exc:
        raise BuildError("uv lock check timed out") from exc
    except BuildError:
        raise
    except OSError as exc:
        raise BuildError("uv lock check could not start") from exc
    finally:
        if backend_descriptor is not None:
            try:
                os.close(backend_descriptor)
            except OSError as exc:
                if sys.exception() is None:
                    raise BuildError("uv source capability cleanup failed") from exc
        if owns_cache_descriptor and active_cache_descriptor is not None:
            try:
                os.close(active_cache_descriptor)
            except OSError as exc:
                raise BuildError("uv cache capability cleanup failed") from exc
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
    source_root: Path,
) -> str:
    replacements = [
        (str(REPOSITORY_ROOT), "$REPOSITORY_ROOT"),
        (str(source_root), "$SOURCE_SNAPSHOT"),
        (str(build_root), "$BUILD_ROOT"),
        (str(install_root), "$PYTHON_INSTALL_ROOT"),
    ]
    sanitized = text
    for raw, replacement in sorted(replacements, key=lambda item: -len(item[0])):
        sanitized = sanitized.replace(raw, replacement)
    # A CI evidence file must not retain a runner home/workspace path even if a
    # tool printed a path we did not anticipate above.
    sensitive_path = (
        r"/(?:Users/[^/\s]+|private|var/folders|workspace|tmp)"
        r"/[^\s\"'<>]*"
    )
    sanitized = re.sub(sensitive_path, "$REDACTED_PATH", sanitized)
    if re.search(sensitive_path, sanitized):
        raise BuildError("PyInstaller evidence contains an unsanitized runner path")
    return sanitized


def _read_held_evidence_tree(
    evidence: _EvidenceCapability,
    *,
    expected_tree: tuple[tuple[Any, ...], ...],
    expected_content: tuple[tuple[str, str], ...] | None,
    error_message: str,
) -> tuple[dict[str, bytes], tuple[tuple[str, str], ...]]:
    """Read a sealed evidence tree only through its held directory fd.

    Every leaf is opened descriptor-relative and matched to the metadata that
    was sealed before it is read.  A pathname replacement of the evidence root
    therefore cannot affect either allowlist validation or the bundled copy.
    """

    expected: dict[str, tuple[Any, ...]] = {}
    for record in expected_tree:
        if (
            len(record) != 11
            or not isinstance(record[0], str)
            or record[0] in expected
        ):
            raise BuildError(error_message)
        expected[record[0]] = record
    expected_digests = dict(expected_content or ())
    files: dict[str, bytes] = {}
    observed: set[str] = set()
    directories = 0
    total_size = 0

    def visit(directory_descriptor: int, prefix: str, depth: int) -> None:
        nonlocal directories, total_size
        if depth > 128:
            raise BuildError(error_message)
        try:
            names = tuple(sorted(os.listdir(directory_descriptor)))
        except OSError as exc:
            raise BuildError(error_message) from exc
        for name in names:
            if not name or "/" in name or "\x00" in name:
                raise BuildError(error_message)
            relative = f"{prefix}/{name}" if prefix else name
            record = expected.get(relative)
            if record is None or relative in observed:
                raise BuildError(error_message)
            observed.add(relative)
            try:
                before = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise BuildError(error_message) from exc
            if tuple(record[1:10]) != _stat_metadata(before) or record[10] is not None:
                raise BuildError(error_message)
            if stat.S_ISDIR(before.st_mode) and not stat.S_ISLNK(before.st_mode):
                directories += 1
                if (
                    directories > MAX_EVIDENCE_DIRECTORIES
                    or stat.S_IMODE(before.st_mode) & 0o022
                ):
                    raise BuildError(error_message)
                child_descriptor: int | None = None
                try:
                    child_descriptor = os.open(
                        name,
                        os.O_RDONLY
                        | os.O_DIRECTORY
                        | os.O_NOFOLLOW
                        | os.O_CLOEXEC,
                        dir_fd=directory_descriptor,
                    )
                    opened = os.fstat(child_descriptor)
                    if _stat_metadata(opened) != _stat_metadata(before):
                        raise BuildError(error_message)
                    visit(child_descriptor, relative, depth + 1)
                    after = os.fstat(child_descriptor)
                    relative_after = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        _stat_metadata(after) != _stat_metadata(opened)
                        or _stat_metadata(relative_after) != _stat_metadata(opened)
                    ):
                        raise BuildError(error_message)
                except BuildError:
                    raise
                except OSError as exc:
                    raise BuildError(error_message) from exc
                finally:
                    if child_descriptor is not None:
                        try:
                            os.close(child_descriptor)
                        except OSError as exc:
                            raise BuildError(error_message) from exc
                continue
            if (
                not stat.S_ISREG(before.st_mode)
                or stat.S_ISLNK(before.st_mode)
                or before.st_nlink != 1
                or before.st_size <= 0
                or before.st_size > MAX_EVIDENCE_FILE_BYTES
                or stat.S_IMODE(before.st_mode) & 0o022
            ):
                raise BuildError(error_message)
            total_size += before.st_size
            if (
                len(files) >= MAX_EVIDENCE_FILES
                or total_size > MAX_EVIDENCE_TOTAL_BYTES
            ):
                raise BuildError(error_message)
            file_descriptor: int | None = None
            try:
                file_descriptor = os.open(
                    name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory_descriptor,
                )
                opened = os.fstat(file_descriptor)
                relative_opened = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                if (
                    _stat_metadata(opened) != _stat_metadata(before)
                    or _stat_metadata(relative_opened) != _stat_metadata(before)
                ):
                    raise BuildError(error_message)
                raw = bytearray()
                while len(raw) < opened.st_size:
                    chunk = os.read(
                        file_descriptor,
                        min(1024 * 1024, opened.st_size - len(raw)),
                    )
                    if not chunk:
                        raise BuildError(error_message)
                    raw.extend(chunk)
                if os.read(file_descriptor, 1):
                    raise BuildError(error_message)
                after = os.fstat(file_descriptor)
                relative_after = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                if (
                    _stat_metadata(after) != _stat_metadata(opened)
                    or _stat_metadata(relative_after) != _stat_metadata(opened)
                ):
                    raise BuildError(error_message)
            except BuildError:
                raise
            except OSError as exc:
                raise BuildError(error_message) from exc
            finally:
                if file_descriptor is not None:
                    try:
                        os.close(file_descriptor)
                    except OSError as exc:
                        raise BuildError(error_message) from exc
            payload = bytes(raw)
            digest = hashlib.sha256(payload).hexdigest()
            if expected_content is not None and expected_digests.get(relative) != digest:
                raise BuildError(error_message)
            files[relative] = payload

    try:
        if evidence.closed:
            raise BuildError(error_message)
        visit(evidence.descriptor, "", 0)
    except BuildError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise BuildError(error_message) from exc
    if (
        observed != set(expected)
        or not 1 <= len(files) <= MAX_EVIDENCE_FILES
        or (
            expected_content is not None
            and set(files) != set(expected_digests)
        )
    ):
        raise BuildError(error_message)
    content = tuple(
        (relative, hashlib.sha256(payload).hexdigest())
        for relative, payload in sorted(files.items())
    )
    return files, content


def _create_failure_evidence_capability(
    scratch: _ScratchCapability,
) -> _EvidenceCapability:
    """Create and bind evidence before any producer writes through its name."""

    error_message = "Sanitized PyInstaller evidence capability could not be created"
    if scratch.evidence is not None or scratch.closed or scratch.poisoned:
        raise _CleanupBlockedError(error_message)
    _validate_source_snapshot(scratch)
    _refresh_scratch_capability(scratch)
    path = scratch.build_root / "evidence"
    descriptor: int | None = None
    snapshot: _DirectorySnapshot | None = None
    evidence: _EvidenceCapability | None = None
    initial_parent_snapshot = scratch.build_root_snapshot
    attempted = False
    try:
        # A pending signal cannot land between first bind and owner
        # registration.  The outer transaction covers the helper's nested
        # deferral, scratch.evidence transfer, and the post-bind validation.
        with _defer_publish_signals():
            attempted = True
            descriptor, snapshot = _create_bound_child_directory(
                parent_descriptor=scratch.build_root_descriptor,
                parent_path=scratch.build_root,
                name="evidence",
                mode=0o700,
                error_message=error_message,
            )
            attempted = False
            evidence = _EvidenceCapability(
                path=path,
                name="evidence",
                parent_descriptor=scratch.build_root_descriptor,
                descriptor=descriptor,
                snapshot=snapshot,
                tree_snapshot=(),
                content_snapshot=(),
            )
            scratch.evidence = evidence
            scratch.build_root_snapshot = _capture_bound_directory(
                scratch.build_root_descriptor,
                scratch.build_root,
                parent_descriptor=scratch.scratch_parent_descriptor,
                relative_name=scratch.build_root_name,
                expected=scratch.build_root_snapshot,
                expected_mode=0o700,
                exact_entries=None,
                error_message=error_message,
            )
            _validate_source_snapshot(scratch)
        return evidence
    except BaseException as exc:
        ambiguous = False
        if attempted:
            try:
                os.stat(
                    "evidence",
                    dir_fd=scratch.build_root_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            except OSError:
                ambiguous = True
            else:
                ambiguous = True
        active_descriptor = (
            evidence.descriptor if evidence is not None else descriptor
        )
        active_snapshot = evidence.snapshot if evidence is not None else snapshot
        cleanup_failed = ambiguous
        if active_descriptor is not None and active_snapshot is not None:
            try:
                with _defer_publish_signals(preserve_error=exc):
                    _rollback_bound_directory(
                        parent_descriptor=scratch.build_root_descriptor,
                        parent_path=scratch.build_root,
                        name="evidence",
                        descriptor=active_descriptor,
                        snapshot=active_snapshot,
                        error_message=error_message,
                    )
                    os.close(active_descriptor)
                    if evidence is not None:
                        evidence.closed = True
                    scratch.evidence = None
                    scratch.build_root_snapshot = _capture_bound_directory(
                        scratch.build_root_descriptor,
                        scratch.build_root,
                        parent_descriptor=scratch.scratch_parent_descriptor,
                        relative_name=scratch.build_root_name,
                        expected=initial_parent_snapshot,
                        expected_mode=0o700,
                        exact_entries=initial_parent_snapshot.entries,
                        error_message=error_message,
                    )
            except BaseException:
                cleanup_failed = True
        elif active_descriptor is not None:
            try:
                os.close(active_descriptor)
            except OSError:
                cleanup_failed = True
        if cleanup_failed:
            scratch.poisoned = True
            raise _CleanupBlockedError(error_message) from exc
        scratch.poisoned = False
        raise


def _seal_failure_evidence_capability(
    scratch: _ScratchCapability,
) -> _EvidenceCapability:
    """Freeze evidence tree metadata after proving source and scratch binding."""

    error_message = "Sanitized PyInstaller evidence capability changed"
    evidence = scratch.evidence
    if evidence is None or evidence.closed or scratch.poisoned:
        scratch.poisoned = True
        raise _CleanupBlockedError(error_message)
    try:
        _validate_source_snapshot(scratch)
        _refresh_scratch_capability(scratch)
        before = _capture_bound_directory(
            evidence.descriptor,
            evidence.path,
            parent_descriptor=evidence.parent_descriptor,
            relative_name=evidence.name,
            expected=evidence.snapshot,
            expected_mode=0o700,
            exact_entries=None,
            error_message=error_message,
        )
        tree = _tree_metadata_snapshot(
            evidence.descriptor,
            error_message=error_message,
        )
        _files, content = _read_held_evidence_tree(
            evidence,
            expected_tree=tree,
            expected_content=None,
            error_message=error_message,
        )
        after = _capture_bound_directory(
            evidence.descriptor,
            evidence.path,
            parent_descriptor=evidence.parent_descriptor,
            relative_name=evidence.name,
            expected=before,
            expected_mode=0o700,
            exact_entries=before.entries,
            error_message=error_message,
        )
        if before != after:
            raise _CapabilityDriftError(error_message)
        evidence.snapshot = after
        evidence.tree_snapshot = tree
        evidence.content_snapshot = content
        _validate_source_snapshot(scratch)
        return evidence
    except BaseException as exc:
        scratch.poisoned = True
        raise _CleanupBlockedError(error_message) from exc


def _revalidate_failure_evidence_capability(
    scratch: _ScratchCapability,
    *,
    error_message: str,
) -> _EvidenceCapability:
    evidence = scratch.evidence
    if evidence is None or evidence.closed or scratch.poisoned:
        scratch.poisoned = True
        raise _CleanupBlockedError(error_message)
    try:
        _validate_source_snapshot(scratch)
        _refresh_scratch_capability(scratch)
        current = _capture_bound_directory(
            evidence.descriptor,
            evidence.path,
            parent_descriptor=evidence.parent_descriptor,
            relative_name=evidence.name,
            expected=evidence.snapshot,
            expected_mode=0o700,
            exact_entries=evidence.snapshot.entries,
            error_message=error_message,
        )
        if (
            current != evidence.snapshot
            or _tree_metadata_snapshot(
                evidence.descriptor,
                error_message=error_message,
            )
            != evidence.tree_snapshot
        ):
            raise _CapabilityDriftError(error_message)
        _read_held_evidence_tree(
            evidence,
            expected_tree=evidence.tree_snapshot,
            expected_content=evidence.content_snapshot,
            error_message=error_message,
        )
        _validate_source_snapshot(scratch)
        return evidence
    except BaseException as exc:
        scratch.poisoned = True
        raise _CleanupBlockedError(error_message) from exc


def _collect_pyinstaller_evidence(
    *,
    work_root: Path,
    log_text: str,
    destination: Path,
    build_root: Path,
    install_root: Path,
    source_root: Path,
    scratch: _ScratchCapability | None = None,
) -> _EvidenceCapability | None:
    evidence = (
        _create_failure_evidence_capability(scratch)
        if scratch is not None
        else None
    )
    if evidence is not None and destination != evidence.path:
        scratch.poisoned = True
        raise _CleanupBlockedError(
            "Sanitized PyInstaller evidence destination is not capability-bound"
        )
    if evidence is None:
        destination.mkdir(parents=True, exist_ok=False)

    primary_error: BaseException | None = None
    try:
        (destination / "pyinstaller.log").write_text(
            _sanitize_text(
                log_text,
                build_root=build_root,
                install_root=install_root,
                source_root=source_root,
            ),
            encoding="utf-8",
        )
        if work_root.exists():
            for source in sorted(work_root.rglob("*")):
                if (
                    not source.is_file()
                    or source.is_symlink()
                    or source.suffix.lower() != ".txt"
                    or not source.name.startswith("warn-")
                ):
                    continue
                info = source.stat()
                if info.st_size > 16 * 1024 * 1024:
                    raise BuildError(
                        "PyInstaller evidence file exceeds its size bound"
                    )
                relative = source.relative_to(work_root)
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    raw = source.read_text(encoding="utf-8", errors="strict")
                except (OSError, UnicodeDecodeError) as exc:
                    raise BuildError(
                        "PyInstaller evidence must be UTF-8 text"
                    ) from exc
                target.write_text(
                    _sanitize_text(
                        raw,
                        build_root=build_root,
                        install_root=install_root,
                        source_root=source_root,
                    ),
                    encoding="utf-8",
                )
    except BaseException as exc:
        primary_error = exc
    if scratch is not None:
        try:
            evidence = _seal_failure_evidence_capability(scratch)
        except BaseException as binding_error:
            if primary_error is not None:
                raise _CleanupBlockedError(
                    "Sanitized PyInstaller evidence collection lost its capability"
                ) from primary_error
            raise binding_error
    if primary_error is not None:
        raise primary_error
    return evidence


def _warn_file(evidence: Path) -> Path:
    matches = sorted(evidence.rglob("warn-*.txt"))
    if len(matches) != 1:
        raise BuildError("PyInstaller warning evidence is missing or ambiguous")
    return matches[0]


def _validate_missing_import_text(
    warning_text: str,
    *,
    allowlist_path: Path = MISSING_IMPORTS_ALLOWLIST,
    toolchain_path: Path = TOOLCHAIN_LOCK,
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
    toolchain = _load_json(toolchain_path, "Python toolchain lock")
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
    lines = warning_text.splitlines()
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


def validate_missing_imports(
    warning_file: Path,
    *,
    allowlist_path: Path = MISSING_IMPORTS_ALLOWLIST,
    toolchain_path: Path = TOOLCHAIN_LOCK,
) -> set[str]:
    """Validate a standalone warning path for non-capability callers/tests."""

    try:
        warning_text = warning_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise BuildError("PyInstaller warning file is unreadable") from exc
    return _validate_missing_import_text(
        warning_text,
        allowlist_path=allowlist_path,
        toolchain_path=toolchain_path,
    )


def _consume_failure_evidence(
    scratch: _ScratchCapability,
    evidence: _EvidenceCapability,
    *,
    error_message: str,
) -> dict[str, bytes]:
    """Return sealed evidence bytes without rediscovering its pathname."""

    if scratch.evidence is not evidence:
        scratch.poisoned = True
        raise _CleanupBlockedError(error_message)
    try:
        held = _revalidate_failure_evidence_capability(
            scratch,
            error_message=error_message,
        )
        files, _content = _read_held_evidence_tree(
            held,
            expected_tree=held.tree_snapshot,
            expected_content=held.content_snapshot,
            error_message=error_message,
        )
        _revalidate_failure_evidence_capability(
            scratch,
            error_message=error_message,
        )
        return files
    except BaseException as exc:
        scratch.poisoned = True
        raise _CleanupBlockedError(error_message) from exc


def _copy_evidence_bytes_to_bundle(
    files: Mapping[str, bytes],
    destination: Path,
) -> None:
    """Create a private evidence copy from already-held immutable bytes."""

    error_message = "Bundled PyInstaller evidence could not be materialized"
    descriptor: int | None = None
    try:
        destination.mkdir(mode=0o700)
        descriptor = os.open(
            destination,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        directory_descriptors: dict[str, int] = {"": descriptor}
        try:
            directories = sorted(
                {
                    parent.as_posix()
                    for relative in files
                    for parent in PurePosixPath(relative).parents
                    if parent.as_posix() != "."
                },
                key=lambda value: (len(PurePosixPath(value).parts), value),
            )
            for relative in directories:
                pure = PurePosixPath(relative)
                parent = pure.parent.as_posix()
                if parent == ".":
                    parent = ""
                os.mkdir(
                    pure.name,
                    mode=0o700,
                    dir_fd=directory_descriptors[parent],
                )
                child = os.open(
                    pure.name,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW
                    | os.O_CLOEXEC,
                    dir_fd=directory_descriptors[parent],
                )
                directory_descriptors[relative] = child
            for relative, payload in sorted(files.items()):
                pure = PurePosixPath(relative)
                if (
                    pure.is_absolute()
                    or pure.as_posix() != relative
                    or any(part in {"", ".", ".."} for part in pure.parts)
                ):
                    raise BuildError(error_message)
                parent = pure.parent.as_posix()
                if parent == ".":
                    parent = ""
                file_descriptor = os.open(
                    pure.name,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | os.O_NOFOLLOW
                    | os.O_CLOEXEC,
                    0o600,
                    dir_fd=directory_descriptors[parent],
                )
                try:
                    remaining = memoryview(payload)
                    while remaining:
                        written = os.write(file_descriptor, remaining)
                        if written <= 0:
                            raise BuildError(error_message)
                        remaining = remaining[written:]
                    os.fsync(file_descriptor)
                    if os.fstat(file_descriptor).st_size != len(payload):
                        raise BuildError(error_message)
                finally:
                    os.close(file_descriptor)
        finally:
            for relative, child in sorted(
                directory_descriptors.items(),
                key=lambda item: len(PurePosixPath(item[0]).parts),
                reverse=True,
            ):
                if relative:
                    os.close(child)
    except BuildError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise BuildError(error_message) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as exc:
                if sys.exception() is None:
                    raise BuildError(error_message) from exc


def _bundle_capability_path(bundle: _BundleCapability) -> Path:
    error_message = "Python sidecar bundle capability is unavailable"
    if bundle.closed:
        raise _CleanupBlockedError(error_message)
    path = Path("/dev/fd") / str(bundle.descriptor)
    probe: int | None = None
    try:
        held = os.fstat(bundle.descriptor)
        observed = os.stat(path)
        probe = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        opened = os.fstat(probe)
        if (
            not stat.S_ISDIR(held.st_mode)
            or _stable_directory_identity(held)
            != _stable_directory_identity(bundle.snapshot)
            or _stable_directory_identity(observed)
            != _stable_directory_identity(held)
            or _stable_directory_identity(opened)
            != _stable_directory_identity(held)
        ):
            raise _CleanupBlockedError(error_message)
        return path
    except _CleanupBlockedError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise _CleanupBlockedError(error_message) from exc
    finally:
        if probe is not None:
            try:
                os.close(probe)
            except OSError as exc:
                if sys.exception() is None:
                    raise _CleanupBlockedError(error_message) from exc


def _create_bundle_capability(
    scratch: _ScratchCapability,
    *,
    dist_root: Path,
    dist_descriptor: int,
    dist_snapshot: _DirectorySnapshot,
    descriptor: int,
    created_snapshot: _DirectorySnapshot,
) -> _BundleCapability:
    """Bind PyInstaller's output before any build consumer inspects it."""

    error_message = "PyInstaller bundle capability could not be acquired"
    try:
        if scratch.bundle is not None or scratch.poisoned or scratch.closed:
            raise _CleanupBlockedError(error_message)
        _validate_source_snapshot(scratch)
        _refresh_scratch_capability(scratch)
        parent_snapshot = _capture_bound_directory(
            dist_descriptor,
            dist_root,
            parent_descriptor=scratch.build_root_descriptor,
            relative_name="dist",
            expected=dist_snapshot,
            expected_mode=0o700,
            exact_entries=("lcf-service",),
            error_message=error_message,
        )
        path = dist_root / "lcf-service"
        snapshot = _capture_bound_directory(
            descriptor,
            path,
            parent_descriptor=dist_descriptor,
            relative_name="lcf-service",
            expected=created_snapshot,
            expected_mode=0o700,
            exact_entries=(),
            error_message=error_message,
        )
        if stat.S_IMODE(snapshot.mode) & 0o022:
            raise _CleanupBlockedError(error_message)
        tree = _tree_metadata_snapshot(descriptor, error_message=error_message)
        bundle = _BundleCapability(
            path=path,
            name="lcf-service",
            parent_path=dist_root,
            parent_name="dist",
            parent_descriptor=dist_descriptor,
            parent_snapshot=parent_snapshot,
            descriptor=descriptor,
            snapshot=snapshot,
            tree_snapshot=tree,
        )
        _bundle_capability_path(bundle)
        _validate_source_snapshot(scratch)
        # Ownership transfers only after every fallible acquisition check.
        # Before this assignment the caller remains the sole fd owner.
        scratch.bundle = bundle
        return bundle
    except BaseException as exc:
        scratch.poisoned = True
        raise _CleanupBlockedError(error_message) from exc


def _validate_bundle_capability(
    scratch: _ScratchCapability,
    *,
    accept_tree_changes: bool = False,
    error_message: str = "Python sidecar bundle capability changed",
) -> Path:
    """Validate or intentionally advance one held candidate-tree snapshot."""

    bundle = scratch.bundle
    if bundle is None or bundle.closed or scratch.poisoned or scratch.closed:
        scratch.poisoned = True
        raise _CleanupBlockedError(error_message)
    try:
        _validate_source_snapshot(scratch)
        _refresh_scratch_capability(scratch)
        parent = _capture_bound_directory(
            bundle.parent_descriptor,
            bundle.parent_path,
            parent_descriptor=scratch.build_root_descriptor,
            relative_name=bundle.parent_name,
            expected=bundle.parent_snapshot,
            expected_mode=0o700,
            exact_entries=(bundle.name,),
            error_message=error_message,
        )
        current = _capture_bound_directory(
            bundle.descriptor,
            bundle.path,
            parent_descriptor=bundle.parent_descriptor,
            relative_name=bundle.name,
            expected=bundle.snapshot,
            expected_mode=None,
            exact_entries=None,
            error_message=error_message,
        )
        tree = _tree_metadata_snapshot(
            bundle.descriptor,
            error_message=error_message,
        )
        if not accept_tree_changes and (
            parent != bundle.parent_snapshot
            or current != bundle.snapshot
            or tree != bundle.tree_snapshot
        ):
            raise _CapabilityDriftError(error_message)
        bundle.parent_snapshot = parent
        bundle.snapshot = current
        bundle.tree_snapshot = tree
        _validate_source_snapshot(scratch)
        return _bundle_capability_path(bundle)
    except BaseException as exc:
        scratch.poisoned = True
        raise _CleanupBlockedError(error_message) from exc


def _verify_held_bundle_tree(
    bundle: _BundleCapability,
    *,
    error_message: str,
) -> Path:
    """Verify the sealed candidate through its fd, independent of its name."""

    try:
        path = _bundle_capability_path(bundle)
        if (
            _stable_directory_identity(os.fstat(bundle.descriptor))
            != _stable_directory_identity(bundle.snapshot)
            or _tree_metadata_snapshot(
                bundle.descriptor,
                error_message=error_message,
            )
            != bundle.tree_snapshot
        ):
            raise _CapabilityDriftError(error_message)
        return path
    except BaseException as exc:
        raise _CleanupBlockedError(error_message) from exc


def _verify_held_bundle_candidate(
    bundle: _BundleCapability,
    candidate: Path,
    *,
    error_message: str,
) -> Path:
    """Bind the current publish name to the held, sealed bundle tree."""

    descriptor: int | None = None
    try:
        _verify_held_bundle_tree(bundle, error_message=error_message)
        if not candidate.is_absolute() or ".." in candidate.parts:
            raise _CapabilityDriftError(error_message)
        named = candidate.lstat()
        descriptor = os.open(
            candidate,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        opened = os.fstat(descriptor)
        held = os.fstat(bundle.descriptor)
        expected_identity = _stable_directory_identity(bundle.snapshot)
        if (
            stat.S_ISLNK(named.st_mode)
            or not stat.S_ISDIR(named.st_mode)
            or not stat.S_ISDIR(opened.st_mode)
            or _stable_directory_identity(held) != expected_identity
            or _stable_directory_identity(named) != expected_identity
            or _stable_directory_identity(opened) != expected_identity
            or _tree_metadata_snapshot(
                descriptor,
                error_message=error_message,
            )
            != bundle.tree_snapshot
        ):
            raise _CapabilityDriftError(error_message)
        return candidate
    except _CleanupBlockedError:
        raise
    except BaseException as exc:
        raise _CleanupBlockedError(error_message) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as exc:
                if sys.exception() is None:
                    raise _CleanupBlockedError(error_message) from exc


def _close_published_bundle_capability(scratch: _ScratchCapability) -> None:
    bundle = scratch.bundle
    if bundle is None or bundle.closed:
        scratch.poisoned = True
        raise _CleanupBlockedError(
            "Published Python sidecar bundle capability is unavailable"
        )
    failed = False
    for descriptor in (bundle.descriptor, bundle.parent_descriptor):
        try:
            os.close(descriptor)
        except OSError:
            failed = True
    bundle.closed = True
    scratch.bundle = None
    if failed:
        scratch.poisoned = True
        raise _CleanupBlockedError(
            "Published Python sidecar bundle capability cleanup failed"
        )


def _run_pyinstaller_command(
    *,
    active_python: Path,
    source_root: Path,
    source_descriptor: int,
    bundle_descriptor: int,
    dist_descriptor: int,
    work_descriptor: int,
    config_descriptor: int,
    temp_descriptor: int,
    dist_root: Path,
    work_root: Path,
    config_root: Path,
    temp_root: Path,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    """Exec PyInstaller in an owned session with every root inherited."""

    error_message = "PyInstaller directory capability is unavailable"
    roots = (
        (source_descriptor, source_root),
        (bundle_descriptor, dist_root / "lcf-service"),
        (dist_descriptor, dist_root),
        (work_descriptor, work_root),
        (config_descriptor, config_root),
        (temp_descriptor, temp_root),
    )
    try:
        for descriptor, root in roots:
            observed = root.lstat()
            probe = os.open(
                root,
                os.O_RDONLY
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | os.O_CLOEXEC,
            )
            try:
                opened = os.fstat(probe)
                held = os.fstat(descriptor)
                if (
                    stat.S_ISLNK(observed.st_mode)
                    or _stable_directory_identity(observed)
                    != _stable_directory_identity(held)
                    or _stable_directory_identity(opened)
                    != _stable_directory_identity(held)
                ):
                    raise BuildError(error_message)
            finally:
                os.close(probe)
        if (
            environment.get("PYINSTALLER_CONFIG_DIR") != str(config_root)
            or environment.get("TMPDIR") != str(temp_root)
        ):
            raise BuildError(error_message)
    except BuildError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise BuildError(error_message) from exc
    arguments = (
        str(active_python),
        "-I",
        "-c",
        PYINSTALLER_CAPABILITY_RUNNER,
        str(source_descriptor),
        str(bundle_descriptor),
        str(dist_descriptor),
        str(work_descriptor),
        str(config_descriptor),
        str(temp_descriptor),
        str(source_root),
        str(dist_root / "lcf-service"),
        str(dist_root),
        str(work_root),
        str(config_root),
        str(temp_root),
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_root),
        "--workpath",
        str(work_root),
        str(source_root / "backend" / "packaging" / "lcf_sidecar.spec"),
    )
    process: subprocess.Popen[str] | None = None
    try:
        # A spawned process group is an owned capability before Python can
        # expose the return value to an unmasked signal handler.  Keep the
        # spawn/assignment handoff masked; any pending cancellation then lands
        # in this try block with a usable pid and must terminate the group.
        with _defer_publish_signals():
            process = subprocess.Popen(
                arguments,
                cwd=source_root,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                pass_fds=(
                    source_descriptor,
                    bundle_descriptor,
                    dist_descriptor,
                    work_descriptor,
                    config_descriptor,
                    temp_descriptor,
                ),
                start_new_session=True,
            )
        stdout, _stderr = process.communicate(timeout=1800)
        for descriptor, root in roots:
            observed = root.lstat()
            probe = os.open(
                root,
                os.O_RDONLY
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | os.O_CLOEXEC,
            )
            try:
                if (
                    _stable_directory_identity(observed)
                    != _stable_directory_identity(os.fstat(descriptor))
                    or _stable_directory_identity(os.fstat(probe))
                    != _stable_directory_identity(os.fstat(descriptor))
                ):
                    raise BuildError(error_message)
            finally:
                os.close(probe)
        descendants = False
        # Stabilize the communicate -> process-group absence decision.  A
        # signal observed at this handoff is caught below and still runs the
        # bounded group cleanup while the pid owner remains live.
        with _defer_publish_signals():
            descendants = _process_group_exists(process.pid)
            if descendants:
                _terminate_pyinstaller_process_group(process)
            completed = subprocess.CompletedProcess(
                arguments,
                process.returncode,
                stdout=stdout,
                stderr=None,
            )
        if descendants:
            raise BuildError("PyInstaller left a descendant process running")
        return completed
    except BaseException as exc:
        if process is not None:
            try:
                with _defer_publish_signals(preserve_error=exc):
                    _terminate_pyinstaller_process_group(process)
            except BaseException as cleanup_error:
                raise BuildError(
                    "PyInstaller process group cleanup failed"
                ) from exc
        raise


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError as exc:
        raise BuildError("PyInstaller process group state is unavailable") from exc
    return True


def _terminate_pyinstaller_process_group(
    process: subprocess.Popen[str],
) -> None:
    """Boundedly stop and reap the isolated PyInstaller process group."""

    _terminate_owned_process_group(
        process,
        error_message="PyInstaller process group did not stop",
    )


def _terminate_owned_process_group(
    process: subprocess.Popen[Any],
    *,
    error_message: str,
) -> None:
    """Boundedly stop, reap, and prove absence of one owned session."""

    process_group = process.pid
    for stop_signal, timeout in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 5.0)):
        try:
            os.killpg(process_group, stop_signal)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                process.wait(timeout=min(0.1, max(0.01, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                pass
            if not _process_group_exists(process_group):
                return
            time.sleep(0.01)
    try:
        process.wait(timeout=0.1)
    except subprocess.TimeoutExpired as exc:
        raise BuildError(error_message) from exc
    if _process_group_exists(process_group):
        raise BuildError(error_message)


def _rollback_bound_directory(
    *,
    parent_descriptor: int,
    parent_path: Path,
    name: str,
    descriptor: int,
    snapshot: _DirectorySnapshot,
    error_message: str,
) -> None:
    """Remove one fully-bound owned directory without trusting its pathname."""

    path = parent_path / name
    try:
        current = _capture_bound_directory(
            descriptor,
            path,
            parent_descriptor=parent_descriptor,
            relative_name=name,
            expected=snapshot,
            expected_mode=None,
            exact_entries=None,
            error_message=error_message,
        )
        if _stable_directory_identity(current) != _stable_directory_identity(snapshot):
            raise _CleanupBlockedError(error_message)
        _remove_tree_contents(descriptor, error_message=error_message)
        empty = _capture_bound_directory(
            descriptor,
            path,
            parent_descriptor=parent_descriptor,
            relative_name=name,
            expected=current,
            expected_mode=None,
            exact_entries=(),
            error_message=error_message,
        )
        quarantine = f".lcf-acquisition-{secrets.token_hex(16)}"
        _rename_noreplace_at(
            parent_descriptor,
            name,
            parent_descriptor,
            quarantine,
        )
        quarantined = os.stat(
            quarantine,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if _stable_directory_identity(quarantined) != _stable_directory_identity(empty):
            try:
                _rename_noreplace_at(
                    parent_descriptor,
                    quarantine,
                    parent_descriptor,
                    name,
                )
            except BaseException as restore_error:
                raise _CleanupBlockedError(error_message) from restore_error
            raise _CleanupBlockedError(error_message)
        _remove_verified_quarantine_leaf(
            parent_descriptor,
            original_name=name,
            quarantine_name=quarantine,
            expected=quarantined,
            directory=True,
            error_message=error_message,
        )
    except _CleanupBlockedError:
        raise
    except BaseException as exc:
        raise _CleanupBlockedError(error_message) from exc


def _rollback_pyinstaller_acquisition(
    scratch: _ScratchCapability,
    *,
    initial_parent_snapshot: _DirectorySnapshot,
    directory_descriptors: Mapping[str, int],
    directory_snapshots: Mapping[str, _DirectorySnapshot],
    bundle_capability: _BundleCapability | None,
    pending_bundle_descriptor: int | None,
    pending_bundle_snapshot: _DirectorySnapshot | None,
    ambiguous_name: str | None,
) -> None:
    """Rollback every fully-bound acquisition; retain ambiguous namespace state."""

    error_message = "PyInstaller capability acquisition cleanup failed"
    bundle_descriptor_to_close = (
        bundle_capability.descriptor
        if bundle_capability is not None
        else pending_bundle_descriptor
    )
    descriptors_to_close: list[int] = []
    if bundle_descriptor_to_close is not None:
        descriptors_to_close.append(bundle_descriptor_to_close)
    for name in ("tmp", "pyinstaller-config", "work", "dist"):
        descriptor = directory_descriptors.get(name)
        if descriptor is not None and descriptor not in descriptors_to_close:
            descriptors_to_close.append(descriptor)
    failed = ambiguous_name is not None
    try:
        active_bundle_descriptor = (
            bundle_capability.descriptor
            if bundle_capability is not None
            else pending_bundle_descriptor
        )
        active_bundle_snapshot = (
            bundle_capability.snapshot
            if bundle_capability is not None
            else pending_bundle_snapshot
        )
        dist_descriptor = directory_descriptors.get("dist")
        if (
            active_bundle_descriptor is not None
            and active_bundle_snapshot is not None
            and dist_descriptor is not None
        ):
            _rollback_bound_directory(
                parent_descriptor=dist_descriptor,
                parent_path=scratch.build_root / "dist",
                name="lcf-service",
                descriptor=active_bundle_descriptor,
                snapshot=active_bundle_snapshot,
                error_message=error_message,
            )
            if bundle_capability is not None:
                bundle_capability.closed = True
                scratch.bundle = None
        elif ambiguous_name == "lcf-service":
            failed = True

        for name in ("tmp", "pyinstaller-config", "work", "dist"):
            descriptor = directory_descriptors.get(name)
            snapshot = directory_snapshots.get(name)
            if descriptor is None or snapshot is None:
                continue
            if ambiguous_name == name or (
                name == "dist" and ambiguous_name == "lcf-service"
            ):
                failed = True
                continue
            _rollback_bound_directory(
                parent_descriptor=scratch.build_root_descriptor,
                parent_path=scratch.build_root,
                name=name,
                descriptor=descriptor,
                snapshot=snapshot,
                error_message=error_message,
            )
        if not failed:
            scratch.build_root_snapshot = _capture_bound_directory(
                scratch.build_root_descriptor,
                scratch.build_root,
                parent_descriptor=scratch.scratch_parent_descriptor,
                relative_name=scratch.build_root_name,
                expected=initial_parent_snapshot,
                expected_mode=0o700,
                exact_entries=initial_parent_snapshot.entries,
                error_message=error_message,
            )
    except BaseException:
        failed = True
    close_failed = False
    for descriptor in descriptors_to_close:
        try:
            os.close(descriptor)
        except OSError:
            close_failed = True
    if bundle_capability is not None:
        bundle_capability.closed = True
        if scratch.bundle is bundle_capability:
            scratch.bundle = None
    if failed or close_failed:
        scratch.poisoned = True
        raise _CleanupBlockedError(error_message)
    scratch.poisoned = False


def _prepare_pyinstaller_capabilities(
    scratch: _ScratchCapability,
) -> tuple[_BundleCapability, _PyInstallerProducerCapabilities]:
    """Bind every private producer directory before PyInstaller starts."""

    build_root = scratch.build_root
    directory_names = ("dist", "work", "pyinstaller-config", "tmp")
    directory_descriptors: dict[str, int] = {}
    directory_snapshots: dict[str, _DirectorySnapshot] = {}
    directory_paths: dict[str, Path] = {}
    pending_bundle_descriptor: int | None = None
    pending_bundle_snapshot: _DirectorySnapshot | None = None
    bundle_capability: _BundleCapability | None = None
    producer_capabilities: _PyInstallerProducerCapabilities | None = None
    attempted_name: str | None = None
    ambiguous_name: str | None = None
    initial_parent_snapshot = scratch.build_root_snapshot
    try:
        # Nested helper deferrals borrow this outer transaction.  Therefore a
        # signal cannot land between mkdir/open/bind and registration in these
        # ownership maps, nor between final bundle ownership and return.
        with _defer_publish_signals():
            for name in directory_names:
                attempted_name = name
                descriptor, snapshot = _create_bound_child_directory(
                    parent_descriptor=scratch.build_root_descriptor,
                    parent_path=build_root,
                    name=name,
                    mode=0o700,
                    error_message="PyInstaller work capability is unavailable",
                )
                directory_descriptors[name] = descriptor
                directory_snapshots[name] = snapshot
                directory_paths[name] = build_root / name
                attempted_name = None
            attempted_name = "lcf-service"
            pending_bundle_descriptor, pending_bundle_snapshot = (
                _create_bound_child_directory(
                    parent_descriptor=directory_descriptors["dist"],
                    parent_path=build_root / "dist",
                    name="lcf-service",
                    mode=0o700,
                    error_message="PyInstaller bundle capability could not be acquired",
                )
            )
            attempted_name = None
            bundle_capability = _create_bundle_capability(
                scratch,
                dist_root=build_root / "dist",
                dist_descriptor=directory_descriptors["dist"],
                dist_snapshot=directory_snapshots["dist"],
                descriptor=pending_bundle_descriptor,
                created_snapshot=pending_bundle_snapshot,
            )
            producer_directories = {
                name: _ProducerDirectoryCapability(
                    path=build_root / name,
                    capability_path=directory_paths[name],
                    name=name,
                    descriptor=directory_descriptors[name],
                    snapshot=directory_snapshots[name],
                    tree_snapshot=(),
                )
                for name in ("work", "pyinstaller-config", "tmp")
            }
            producer_capabilities = _PyInstallerProducerCapabilities(
                parent_snapshot=scratch.build_root_snapshot,
                directories=producer_directories,
            )
        if bundle_capability is None or producer_capabilities is None:
            raise AssertionError("PyInstaller capability transfer is incomplete")
        return bundle_capability, producer_capabilities
    except BaseException as exc:
        if attempted_name is not None:
            parent_descriptor = (
                directory_descriptors.get("dist")
                if attempted_name == "lcf-service"
                else scratch.build_root_descriptor
            )
            if parent_descriptor is not None:
                try:
                    os.stat(
                        attempted_name,
                        dir_fd=parent_descriptor,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    pass
                except OSError:
                    ambiguous_name = attempted_name
                else:
                    ambiguous_name = attempted_name
        try:
            with _defer_publish_signals(preserve_error=exc):
                _rollback_pyinstaller_acquisition(
                    scratch,
                    initial_parent_snapshot=initial_parent_snapshot,
                    directory_descriptors=directory_descriptors,
                    directory_snapshots=directory_snapshots,
                    bundle_capability=bundle_capability,
                    pending_bundle_descriptor=(
                        None
                        if bundle_capability is not None
                        else pending_bundle_descriptor
                    ),
                    pending_bundle_snapshot=(
                        None
                        if bundle_capability is not None
                        else pending_bundle_snapshot
                    ),
                    ambiguous_name=ambiguous_name,
                )
        except BaseException as cleanup_error:
            raise _CleanupBlockedError(
                "PyInstaller capability acquisition cleanup failed"
            ) from cleanup_error
        raise


def _revalidate_pyinstaller_producer_capabilities(
    scratch: _ScratchCapability,
    capabilities: _PyInstallerProducerCapabilities,
    *,
    accept_tree_changes: bool,
    accept_parent_metadata_change: bool = False,
    expected_parent_entries: tuple[str, ...] | None = None,
    error_message: str,
) -> None:
    """Rebind every producer name and either seal or verify its tree."""

    if capabilities.closed or scratch.poisoned or scratch.closed:
        scratch.poisoned = True
        raise _CleanupBlockedError(error_message)
    try:
        parent = _capture_bound_directory(
            scratch.build_root_descriptor,
            scratch.build_root,
            parent_descriptor=scratch.scratch_parent_descriptor,
            relative_name=scratch.build_root_name,
            expected=capabilities.parent_snapshot,
            expected_mode=0o700,
            exact_entries=(
                capabilities.parent_snapshot.entries
                if expected_parent_entries is None
                else expected_parent_entries
            ),
            error_message=error_message,
        )
        if (
            _stable_directory_identity(parent)
            != _stable_directory_identity(capabilities.parent_snapshot)
            or (
                not accept_parent_metadata_change
                and parent != capabilities.parent_snapshot
            )
        ):
            raise _CapabilityDriftError(error_message)
        observed: dict[
            str,
            tuple[_DirectorySnapshot, tuple[tuple[Any, ...], ...]],
        ] = {}
        for name, capability in sorted(capabilities.directories.items()):
            current = _capture_bound_directory(
                capability.descriptor,
                capability.path,
                parent_descriptor=scratch.build_root_descriptor,
                relative_name=capability.name,
                expected=capability.snapshot,
                expected_mode=0o700,
                exact_entries=(
                    None if accept_tree_changes else capability.snapshot.entries
                ),
                error_message=error_message,
            )
            tree = _tree_metadata_snapshot(
                capability.descriptor,
                error_message=error_message,
            )
            if (
                _stable_directory_identity(current)
                != _stable_directory_identity(capability.snapshot)
                or (
                    not accept_tree_changes
                    and (
                        current != capability.snapshot
                        or tree != capability.tree_snapshot
                    )
                )
            ):
                raise _CapabilityDriftError(error_message)
            expected_capability_path = capability.path
            probe: int | None = None
            try:
                probe = os.open(
                    expected_capability_path,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW
                    | os.O_CLOEXEC,
                )
                probed = os.fstat(probe)
            finally:
                if probe is not None:
                    os.close(probe)
            if (
                capability.capability_path != expected_capability_path
                or _stable_directory_identity(probed)
                != _stable_directory_identity(current)
            ):
                raise _CapabilityDriftError(error_message)
            observed[name] = (current, tree)
        capabilities.parent_snapshot = parent
        scratch.build_root_snapshot = parent
        for name, (current, tree) in observed.items():
            capabilities.directories[name].snapshot = current
            capabilities.directories[name].tree_snapshot = tree
        _validate_source_snapshot(scratch)
    except BaseException as exc:
        scratch.poisoned = True
        raise _CleanupBlockedError(error_message) from exc


def _close_pyinstaller_producer_capabilities(
    scratch: _ScratchCapability,
    capabilities: _PyInstallerProducerCapabilities,
) -> None:
    failed = False
    if capabilities.closed:
        scratch.poisoned = True
        return
    for capability in capabilities.directories.values():
        try:
            os.close(capability.descriptor)
        except OSError:
            failed = True
    capabilities.closed = True
    if failed:
        scratch.poisoned = True


def run_pyinstaller(
    *,
    scratch: _ScratchCapability,
    install_root: Path,
    source_date_epoch: int,
    deployment_target: str,
    source_root: Path,
) -> tuple[_BundleCapability, _EvidenceCapability]:
    """Run PyInstaller with a minimal deterministic environment."""

    build_root = scratch.build_root
    source_descriptor = scratch.source_snapshot_descriptor
    if (
        source_descriptor is None
        or scratch.source_snapshot is None
        or source_root != scratch.source_snapshot
    ):
        raise BuildError("PyInstaller source capability is unavailable")
    _validate_source_snapshot(scratch)
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

    bundle_capability: _BundleCapability | None = None
    producer_capabilities: _PyInstallerProducerCapabilities | None = None
    command_error: BaseException | None = None
    try:
        # The caller owns the CALL -> UNPACK/STORE handoff.  The acquisition
        # helper cannot protect the bytecode window after its RETURN_VALUE.
        with _defer_publish_signals():
            bundle_capability, producer_capabilities = (
                _prepare_pyinstaller_capabilities(scratch)
            )
        dist_root = bundle_capability.parent_path
        work_root = producer_capabilities.directories["work"].capability_path
        config_root = producer_capabilities.directories[
            "pyinstaller-config"
        ].capability_path
        temp_root = producer_capabilities.directories["tmp"].capability_path
        environment = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "LC_ALL": "C",
            "PYTHONHASHSEED": "0",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "SOURCE_DATE_EPOCH": str(source_date_epoch),
            "MACOSX_DEPLOYMENT_TARGET": deployment_target,
            "PYINSTALLER_CONFIG_DIR": str(config_root),
            "TMPDIR": str(temp_root),
        }

        _revalidate_pyinstaller_producer_capabilities(
            scratch,
            producer_capabilities,
            accept_tree_changes=False,
            error_message="PyInstaller producer capability changed before execution",
        )
        completed = _run_pyinstaller_command(
            active_python=active_python,
            source_root=source_root,
            source_descriptor=source_descriptor,
            bundle_descriptor=bundle_capability.descriptor,
            dist_descriptor=bundle_capability.parent_descriptor,
            work_descriptor=producer_capabilities.directories[
                "work"
            ].descriptor,
            config_descriptor=producer_capabilities.directories[
                "pyinstaller-config"
            ].descriptor,
            temp_descriptor=producer_capabilities.directories["tmp"].descriptor,
            dist_root=dist_root,
            work_root=work_root,
            config_root=config_root,
            temp_root=temp_root,
            environment=environment,
        )
        log_text = completed.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        log_text = f"PyInstaller invocation failed: {type(exc).__name__}\n"
        completed = None
    except BaseException as exc:
        log_text = "PyInstaller invocation was interrupted\n"
        completed = None
        command_error = exc
    try:
        if bundle_capability is None or producer_capabilities is None:
            if command_error is not None:
                raise command_error
            raise BuildError("PyInstaller capabilities are unavailable")
        _revalidate_pyinstaller_producer_capabilities(
            scratch,
            producer_capabilities,
            accept_tree_changes=True,
            error_message="PyInstaller producer capability changed during execution",
        )
        _validate_bundle_capability(
            scratch,
            accept_tree_changes=True,
            error_message="PyInstaller bundle changed during producer assembly",
        )
    except BaseException:
        if producer_capabilities is not None:
            _close_pyinstaller_producer_capabilities(
                scratch,
                producer_capabilities,
            )
        raise
    if command_error is not None:
        if producer_capabilities is not None:
            _close_pyinstaller_producer_capabilities(
                scratch,
                producer_capabilities,
            )
        raise command_error
    try:
        evidence = build_root / "evidence"
        evidence_capability = _collect_pyinstaller_evidence(
            work_root=work_root,
            log_text=log_text,
            destination=evidence,
            build_root=build_root,
            install_root=install_root,
            source_root=source_root,
            scratch=scratch,
        )
        expected_parent_entries = tuple(
            sorted((*producer_capabilities.parent_snapshot.entries, "evidence"))
        )
        _revalidate_pyinstaller_producer_capabilities(
            scratch,
            producer_capabilities,
            accept_tree_changes=False,
            accept_parent_metadata_change=True,
            expected_parent_entries=expected_parent_entries,
            error_message="PyInstaller producer capability changed during evidence collection",
        )
        if evidence_capability is None:
            raise BuildError("PyInstaller evidence capability is unavailable")
        if completed is None or completed.returncode != 0:
            raise BuildError("PyInstaller build failed; sanitized evidence was retained")
        _bundle_capability_path(bundle_capability)
        bundle = bundle_capability.path
        evidence_files = _consume_failure_evidence(
            scratch,
            evidence_capability,
            error_message="Sanitized PyInstaller evidence changed before use",
        )
        warning_matches = [
            payload
            for relative, payload in sorted(evidence_files.items())
            if PurePosixPath(relative).name.startswith("warn-")
            and PurePosixPath(relative).name.endswith(".txt")
        ]
        if len(warning_matches) != 1:
            scratch.poisoned = True
            raise _CleanupBlockedError(
                "PyInstaller warning evidence is missing or ambiguous"
            )
        try:
            warning_text = warning_matches[0].decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            scratch.poisoned = True
            raise _CleanupBlockedError(
                "PyInstaller warning evidence is not UTF-8"
            ) from exc
        _validate_missing_import_text(
            warning_text,
            allowlist_path=(
                source_root
                / "backend"
                / "packaging"
                / "missing-imports-allowlist.json"
            ),
            toolchain_path=(
                source_root
                / "backend"
                / "packaging"
                / "python-sidecar-toolchain.lock.json"
            ),
        )
        executable = bundle / "lcf-service"
        if (
            not bundle.is_dir()
            or bundle.is_symlink()
            or not executable.is_file()
            or executable.is_symlink()
        ):
            raise BuildError("PyInstaller did not produce the reviewed onedir shape")
        _revalidate_failure_evidence_capability(
            scratch,
            error_message="Sanitized PyInstaller evidence changed before bundling",
        )
        _copy_evidence_bytes_to_bundle(
            evidence_files,
            bundle / "_build-evidence",
        )
        _revalidate_failure_evidence_capability(
            scratch,
            error_message="Sanitized PyInstaller evidence changed during bundling",
        )
        _validate_bundle_capability(
            scratch,
            accept_tree_changes=True,
            error_message="Python sidecar bundle changed during evidence materialization",
        )
        return bundle_capability, evidence_capability
    finally:
        if producer_capabilities is not None:
            _close_pyinstaller_producer_capabilities(
                scratch,
                producer_capabilities,
            )


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
    packaging_root: Path,
) -> dict[str, Any]:
    notice = packaging_root / "notices" / notice_name
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
    source_root: Path,
) -> list[dict[str, Any]]:
    packaging_root = source_root / "backend" / "packaging"
    policy = _load_json(
        packaging_root / "license-policy.json",
        "Python sidecar license policy",
    )
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
            sources = [packaging_root / "notices" / "uv-NOTICE.txt"]
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
                packaging_root=packaging_root,
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
    inherited_descriptor: int | None = None,
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
            pass_fds=(
                (inherited_descriptor,)
                if inherited_descriptor is not None
                else ()
            ),
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
        re.fullmatch(r"[0-9]{1,10}", content_length) is None
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
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
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
                embedding = payload.get("embedding")
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
                    or set(payload) != {"revision", "collections", "embedding"}
                    or not isinstance(payload["revision"], int)
                    or isinstance(payload["revision"], bool)
                    or payload["revision"] < 0
                    or payload["revision"] > MAX_SMOKE_BROKER_REVISION
                    or not isinstance(collections, list)
                    or len(collections) > MAX_SMOKE_BROKER_COLLECTIONS
                    or len(collection_names) != len(collections)
                    or len(collection_names) != len(set(collection_names))
                    or embedding != {"mode": "lexical", "profile": None}
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
                    "embedding": {
                        "status": "stale",
                        "profile": None,
                        "revision": None,
                        "model_status": "not_requested",
                        "error": None,
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
                        "embedding": "lexical",
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
    except BaseException as exc:
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
    except BaseException:
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
    socket_identity: tuple[int, int] | None = None
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
            if socket_identity is not None:
                raise BuildError(
                    "Frozen sidecar socket changed during readiness"
                )
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
            continue
        except OSError as exc:
            raise BuildError("Frozen sidecar socket cannot be inspected") from exc
        if (
            stat.S_ISSOCK(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_uid == os.geteuid()
            and info.st_nlink == 1
        ):
            current_identity = (info.st_dev, info.st_ino)
            if socket_identity is None:
                socket_identity = current_identity
            elif current_identity != socket_identity:
                raise BuildError(
                    "Frozen sidecar socket changed during readiness"
                )
        else:
            raise BuildError("Frozen sidecar created an unsafe socket")

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
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        probe: socket.socket | None = None
        connection_refused = False
        try:
            try:
                probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            except (OSError, TypeError, ValueError) as exc:
                raise BuildError(
                    "Frozen sidecar UDS readiness probe failed"
                ) from exc
            try:
                probe.settimeout(min(1.0, remaining))
            except (OSError, TypeError, ValueError) as exc:
                raise BuildError(
                    "Frozen sidecar UDS readiness probe failed"
                ) from exc
            try:
                probe.connect(str(socket_path))
            except OSError as exc:
                if exc.errno != errno.ECONNREFUSED:
                    raise BuildError(
                        "Frozen sidecar UDS readiness probe failed"
                    ) from exc
                connection_refused = True
            except (TypeError, ValueError) as exc:
                raise BuildError(
                    "Frozen sidecar UDS readiness probe failed"
                ) from exc
        finally:
            if probe is not None:
                active_error = sys.exception()
                try:
                    probe.close()
                except OSError as exc:
                    if active_error is None:
                        raise BuildError(
                            "Frozen sidecar UDS readiness probe cleanup failed"
                        ) from exc

        try:
            after = socket_path.lstat()
        except OSError as exc:
            raise BuildError(
                "Frozen sidecar socket changed during readiness"
            ) from exc
        if (
            (after.st_dev, after.st_ino) != socket_identity
            or not stat.S_ISSOCK(after.st_mode)
            or stat.S_IMODE(after.st_mode) != 0o600
            or after.st_uid != os.geteuid()
            or after.st_nlink != 1
        ):
            raise BuildError("Frozen sidecar socket changed during readiness")
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
        if not connection_refused:
            return
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
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


@contextlib.contextmanager
def _held_private_smoke_root(
    parent_override: Path | None = None,
) -> Any:
    """Yield one exact /private/tmp child and clean it only through held fds."""

    parent: Path | None = None
    child: Path | None = None
    parent_descriptor: int | None = None
    child_descriptor: int | None = None
    child_name: str | None = None
    parent_identity: tuple[int, ...] | None = None
    child_snapshot: _DirectorySnapshot | None = None
    primary_error: BaseException | None = None
    creation_error = "Frozen smoke root capability cannot be created"
    try:
        parent = (
            parent_override.resolve(strict=True)
            if parent_override is not None
            else Path("/tmp").resolve(strict=True)
        )
        expected_parent_uid = (
            os.geteuid() if parent_override is not None else 0
        )
        expected_parent_mode = 0o700 if parent_override is not None else 0o1777
        parent_descriptor = os.open(
            parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        parent_fd_info = os.fstat(parent_descriptor)
        parent_path_info = parent.lstat()
        parent_identity = _stable_directory_identity(parent_fd_info)
        if (
            not stat.S_ISDIR(parent_fd_info.st_mode)
            or stat.S_ISLNK(parent_path_info.st_mode)
            or _stable_directory_identity(parent_path_info) != parent_identity
            or parent_fd_info.st_uid != expected_parent_uid
            or stat.S_IMODE(parent_fd_info.st_mode) != expected_parent_mode
        ):
            raise BuildError(creation_error)
        for _attempt in range(8):
            candidate = f"lcf-{secrets.token_hex(16)}"
            try:
                os.mkdir(candidate, mode=0o700, dir_fd=parent_descriptor)
            except FileExistsError:
                continue
            child_name = candidate
            break
        if child_name is None:
            raise BuildError(creation_error)
        child = parent / child_name
        child_descriptor = os.open(
            child_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_descriptor,
        )
        child_snapshot = _capture_bound_directory(
            child_descriptor,
            child,
            parent_descriptor=parent_descriptor,
            relative_name=child_name,
            expected=None,
            expected_mode=0o700,
            exact_entries=(),
            error_message=creation_error,
        )
        try:
            yield child
        except BaseException as exc:
            primary_error = exc
    except BaseException as exc:
        if primary_error is None:
            primary_error = exc

    cleanup_failed = False
    cleanup_error = "Frozen smoke root cleanup failed"
    if (
        parent is not None
        and child is not None
        and parent_descriptor is not None
        and child_descriptor is not None
        and child_name is not None
        and parent_identity is not None
        and child_snapshot is not None
    ):
        try:
            parent_fd_info = os.fstat(parent_descriptor)
            parent_path_info = parent.lstat()
            if (
                _stable_directory_identity(parent_fd_info) != parent_identity
                or _stable_directory_identity(parent_path_info) != parent_identity
                or parent_fd_info.st_uid != expected_parent_uid
                or stat.S_IMODE(parent_fd_info.st_mode) != expected_parent_mode
            ):
                raise BuildError(cleanup_error)
            _capture_bound_directory(
                child_descriptor,
                child,
                parent_descriptor=parent_descriptor,
                relative_name=child_name,
                expected=child_snapshot,
                expected_mode=0o700,
                exact_entries=None,
                error_message=cleanup_error,
            )
            _remove_tree_contents(child_descriptor, error_message=cleanup_error)
            _capture_bound_directory(
                child_descriptor,
                child,
                parent_descriptor=parent_descriptor,
                relative_name=child_name,
                expected=child_snapshot,
                expected_mode=0o700,
                exact_entries=(),
                error_message=cleanup_error,
            )
            os.rmdir(child_name, dir_fd=parent_descriptor)
        except BaseException:
            cleanup_failed = True
    elif child_name is not None:
        cleanup_failed = True
    for descriptor in (child_descriptor, parent_descriptor):
        if descriptor is None:
            continue
        try:
            os.close(descriptor)
        except OSError:
            cleanup_failed = True
    if cleanup_failed:
        if primary_error is not None:
            raise BuildError(
                "Frozen smoke failed and root cleanup failed"
            ) from primary_error
        raise BuildError(cleanup_error)
    if primary_error is not None:
        raise primary_error


def _refresh_scratch_capability(
    capability: _ScratchCapability,
    *,
    exact_build_entries: tuple[str, ...] | None = None,
) -> None:
    if capability.closed:
        raise BuildError("Python sidecar scratch capability is closed")
    destination_snapshot = _capture_bound_directory(
        capability.destination_parent_descriptor,
        capability.destination_parent,
        parent_descriptor=None,
        relative_name=None,
        expected=capability.destination_parent_snapshot,
        expected_mode=None,
        exact_entries=None,
        error_message="Python sidecar destination parent changed",
    )
    if destination_snapshot != capability.destination_parent_snapshot:
        raise BuildError("Python sidecar destination parent changed")
    scratch_snapshot = _capture_bound_directory(
        capability.scratch_parent_descriptor,
        capability.scratch_parent,
        parent_descriptor=capability.destination_parent_descriptor,
        relative_name=capability.scratch_parent_name,
        expected=capability.scratch_parent_snapshot,
        expected_mode=0o700,
        exact_entries=(capability.build_root_name,),
        error_message="Python sidecar scratch parent changed",
    )
    if scratch_snapshot != capability.scratch_parent_snapshot:
        raise BuildError("Python sidecar scratch parent changed")
    capability.build_root_snapshot = _capture_bound_directory(
        capability.build_root_descriptor,
        capability.build_root,
        parent_descriptor=capability.scratch_parent_descriptor,
        relative_name=capability.build_root_name,
        expected=capability.build_root_snapshot,
        expected_mode=0o700,
        exact_entries=exact_build_entries,
        error_message="Python sidecar scratch root changed",
    )


def _accept_destination_parent_metadata(
    capability: _ScratchCapability,
) -> None:
    """Advance the destination snapshot after a capability-checked publish."""

    capability.destination_parent_snapshot = _capture_bound_directory(
        capability.destination_parent_descriptor,
        capability.destination_parent,
        parent_descriptor=None,
        relative_name=None,
        expected=capability.destination_parent_snapshot,
        expected_mode=None,
        exact_entries=None,
        error_message="Python sidecar destination parent changed",
    )


def _cleanup_retained_published_directories(
    capability: _ScratchCapability,
    *,
    error_message: str,
) -> bool:
    """Remove exchanged old destinations only through their held identities."""

    close_failed = False
    for retained in capability.retained_published_directories:
        if retained.closed:
            raise _CleanupBlockedError(error_message)
        current = _capture_bound_directory(
            retained.descriptor,
            retained.parent_path / retained.name,
            parent_descriptor=retained.parent_descriptor,
            relative_name=retained.name,
            expected=retained.snapshot,
            expected_mode=None,
            exact_entries=retained.snapshot.entries,
            error_message=error_message,
        )
        if (
            current != retained.snapshot
            or _tree_metadata_snapshot(
                retained.descriptor,
                error_message=error_message,
            )
            != retained.tree_snapshot
        ):
            raise _CleanupBlockedError(error_message)
        _rollback_bound_directory(
            parent_descriptor=retained.parent_descriptor,
            parent_path=retained.parent_path,
            name=retained.name,
            descriptor=retained.descriptor,
            snapshot=retained.snapshot,
            error_message=error_message,
        )
        for descriptor in (
            retained.descriptor,
            (
                retained.parent_descriptor
                if retained.owns_parent_descriptor
                else None
            ),
        ):
            if descriptor is None:
                continue
            try:
                os.close(descriptor)
            except OSError:
                close_failed = True
        retained.closed = True
    capability.retained_published_directories.clear()
    return close_failed


def _close_scratch_descriptors(capability: _ScratchCapability) -> bool:
    failed = False
    descriptors = [
        (
            capability.bundle.descriptor
            if capability.bundle is not None
            and not capability.bundle.closed
            else None
        ),
        (
            capability.bundle.parent_descriptor
            if capability.bundle is not None
            and not capability.bundle.closed
            else None
        ),
        (
            capability.evidence.descriptor
            if capability.evidence is not None
            and not capability.evidence.closed
            else None
        ),
        capability.source_snapshot_descriptor,
        capability.build_root_descriptor,
        capability.scratch_parent_descriptor,
        capability.destination_parent_descriptor,
    ]
    for retained in capability.retained_published_directories:
        if retained.closed:
            continue
        descriptors.append(retained.descriptor)
        if retained.owns_parent_descriptor:
            descriptors.append(retained.parent_descriptor)
    seen: set[int] = set()
    for descriptor in descriptors:
        if descriptor is None or descriptor in seen:
            continue
        seen.add(descriptor)
        try:
            os.close(descriptor)
        except OSError:
            failed = True
    capability.source_snapshot_descriptor = None
    if capability.evidence is not None:
        capability.evidence.closed = True
    if capability.bundle is not None:
        capability.bundle.closed = True
    for retained in capability.retained_published_directories:
        retained.closed = True
    capability.closed = True
    return failed


def _cleanup_scratch_capability(capability: _ScratchCapability) -> None:
    """Remove only the exact held candidate and its dedicated empty parent."""

    error_message = "Python sidecar scratch cleanup failed"
    if capability.poisoned:
        try:
            _close_scratch_descriptors(capability)
        except BaseException:
            pass
        raise BuildError(error_message)
    failed = False
    safe_to_remove = False
    try:
        if capability.closed:
            raise BuildError(error_message)
        _refresh_scratch_capability(capability)
        retained_close_failed = _cleanup_retained_published_directories(
            capability,
            error_message=error_message,
        )
        if retained_close_failed:
            failed = True
        if capability.bundle is not None:
            bundle = capability.bundle
            _validate_bundle_capability(
                capability,
                error_message=error_message,
            )
            os.close(bundle.descriptor)
            os.close(bundle.parent_descriptor)
            bundle.closed = True
            capability.bundle = None
        if capability.evidence is not None:
            evidence = _revalidate_failure_evidence_capability(
                capability,
                error_message=error_message,
            )
            os.close(evidence.descriptor)
            evidence.closed = True
        if capability.source_snapshot_descriptor is not None:
            os.close(capability.source_snapshot_descriptor)
            capability.source_snapshot_descriptor = None
        safe_to_remove = True
    except BaseException:
        failed = True

    if safe_to_remove:
        try:
            _remove_tree_contents(
                capability.build_root_descriptor,
                error_message=error_message,
            )
            _capture_bound_directory(
                capability.build_root_descriptor,
                capability.build_root,
                parent_descriptor=capability.scratch_parent_descriptor,
                relative_name=capability.build_root_name,
                expected=capability.build_root_snapshot,
                expected_mode=0o700,
                exact_entries=(),
                error_message=error_message,
            )
            os.rmdir(
                capability.build_root_name,
                dir_fd=capability.scratch_parent_descriptor,
            )
            try:
                os.stat(
                    capability.build_root_name,
                    dir_fd=capability.scratch_parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                raise BuildError(error_message)
            _capture_bound_directory(
                capability.scratch_parent_descriptor,
                capability.scratch_parent,
                parent_descriptor=capability.destination_parent_descriptor,
                relative_name=capability.scratch_parent_name,
                expected=capability.scratch_parent_snapshot,
                expected_mode=0o700,
                exact_entries=(),
                error_message=error_message,
            )
            os.rmdir(
                capability.scratch_parent_name,
                dir_fd=capability.destination_parent_descriptor,
            )
            try:
                os.stat(
                    capability.scratch_parent_name,
                    dir_fd=capability.destination_parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                raise BuildError(error_message)
        except BaseException:
            failed = True

    if _close_scratch_descriptors(capability):
        failed = True
    if failed:
        raise BuildError(error_message)


def _finish_scratch_lifecycle(
    capability: _ScratchCapability,
    primary_error: BaseException | None,
) -> None:
    """Close scratch while preserving only a fixed, redacted failure class."""

    try:
        _cleanup_scratch_capability(capability)
    except BaseException as cleanup_error:
        if primary_error is not None:
            raise BuildError(
                "Python sidecar build failed and scratch cleanup failed"
            ) from primary_error
        raise BuildError("Python sidecar scratch cleanup failed") from cleanup_error


def _cleanup_failed_scratch_creation(
    *,
    destination_descriptor: int | None,
    scratch_descriptor: int | None,
    build_descriptor: int | None,
    scratch_snapshot: _DirectorySnapshot | None,
    build_snapshot: _DirectorySnapshot | None,
    scratch_created: bool,
    build_created: bool,
    scratch_parent: Path,
    build_root: Path,
    scratch_name: str,
    build_name: str,
) -> bool:
    """Clean fully-bound creation objects while cleanup signals stay masked."""

    cleanup_failed = (
        (scratch_created and (scratch_descriptor is None or scratch_snapshot is None))
        or (build_created and (build_descriptor is None or build_snapshot is None))
    )
    active_build_descriptor = build_descriptor
    active_scratch_descriptor = scratch_descriptor
    if active_build_descriptor is not None:
        try:
            if not os.listdir(active_build_descriptor) and build_snapshot is not None:
                if active_scratch_descriptor is None or not build_created:
                    raise BuildError(
                        "Python sidecar scratch creation cleanup failed"
                    )
                _capture_bound_directory(
                    active_build_descriptor,
                    build_root,
                    parent_descriptor=active_scratch_descriptor,
                    relative_name=build_name,
                    expected=build_snapshot,
                    expected_mode=0o700,
                    exact_entries=(),
                    error_message=(
                        "Python sidecar scratch creation cleanup failed"
                    ),
                )
                os.close(active_build_descriptor)
                active_build_descriptor = None
                os.rmdir(build_name, dir_fd=active_scratch_descriptor)
            else:
                cleanup_failed = True
        except (BuildError, OSError):
            cleanup_failed = True
    if active_scratch_descriptor is not None:
        try:
            if not os.listdir(active_scratch_descriptor) and scratch_snapshot is not None:
                if destination_descriptor is None or not scratch_created:
                    raise BuildError(
                        "Python sidecar scratch creation cleanup failed"
                    )
                _capture_bound_directory(
                    active_scratch_descriptor,
                    scratch_parent,
                    parent_descriptor=destination_descriptor,
                    relative_name=scratch_name,
                    expected=scratch_snapshot,
                    expected_mode=0o700,
                    exact_entries=(),
                    error_message=(
                        "Python sidecar scratch creation cleanup failed"
                    ),
                )
                os.close(active_scratch_descriptor)
                active_scratch_descriptor = None
                os.rmdir(scratch_name, dir_fd=destination_descriptor)
            else:
                cleanup_failed = True
        except (BuildError, OSError):
            cleanup_failed = True
    for descriptor in (
        active_build_descriptor,
        active_scratch_descriptor,
        destination_descriptor,
    ):
        if descriptor is None:
            continue
        try:
            os.close(descriptor)
        except OSError:
            cleanup_failed = True
    return cleanup_failed


def _create_private_build_root_impl(
    destination_parent: Path,
) -> _ScratchCapability:
    """Create one non-reusable private scratch hierarchy and hold every fd."""

    error_message = "Python sidecar scratch capability cannot be created"
    destination_descriptor: int | None = None
    scratch_descriptor: int | None = None
    build_descriptor: int | None = None
    scratch_snapshot: _DirectorySnapshot | None = None
    build_snapshot: _DirectorySnapshot | None = None
    scratch_created = False
    build_created = False
    creation_error: BaseException | None = None
    scratch_name = f"{SCRATCH_PARENT_NAME}-{secrets.token_hex(16)}"
    build_name = f"candidate-{secrets.token_hex(16)}"
    scratch_parent = destination_parent / scratch_name
    build_root = scratch_parent / build_name
    try:
        if (
            not destination_parent.is_absolute()
            or destination_parent.resolve(strict=True) != destination_parent
        ):
            raise BuildError(error_message)
        destination_descriptor = os.open(
            destination_parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        destination_snapshot = _capture_bound_directory(
            destination_descriptor,
            destination_parent,
            parent_descriptor=None,
            relative_name=None,
            expected=None,
            expected_mode=None,
            exact_entries=None,
            error_message=error_message,
        )
        if stat.S_IMODE(destination_snapshot.mode) & 0o022:
            raise BuildError(error_message)
        try:
            os.stat(
                scratch_name,
                dir_fd=destination_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            raise BuildError("Python sidecar scratch parent must not pre-exist")
        with _defer_publish_signals():
            os.mkdir(scratch_name, mode=0o700, dir_fd=destination_descriptor)
            scratch_created = True
            scratch_created_info = os.stat(
                scratch_name,
                dir_fd=destination_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(scratch_created_info.st_mode)
                or stat.S_ISLNK(scratch_created_info.st_mode)
                or scratch_created_info.st_uid != os.geteuid()
                or stat.S_IMODE(scratch_created_info.st_mode) != 0o700
            ):
                raise BuildError(error_message)
            scratch_created_snapshot = _snapshot_from_stat(
                scratch_created_info,
                (),
            )
            scratch_descriptor = os.open(
                scratch_name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=destination_descriptor,
            )
            scratch_snapshot = _capture_bound_directory(
                scratch_descriptor,
                scratch_parent,
                parent_descriptor=destination_descriptor,
                relative_name=scratch_name,
                expected=scratch_created_snapshot,
                expected_mode=0o700,
                exact_entries=(),
                error_message=error_message,
            )
        if scratch_snapshot.device != destination_snapshot.device:
            raise BuildError(error_message)
        with _defer_publish_signals():
            os.mkdir(build_name, mode=0o700, dir_fd=scratch_descriptor)
            build_created = True
            build_created_info = os.stat(
                build_name,
                dir_fd=scratch_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(build_created_info.st_mode)
                or stat.S_ISLNK(build_created_info.st_mode)
                or build_created_info.st_uid != os.geteuid()
                or stat.S_IMODE(build_created_info.st_mode) != 0o700
            ):
                raise BuildError(error_message)
            build_created_snapshot = _snapshot_from_stat(
                build_created_info,
                (),
            )
            build_descriptor = os.open(
                build_name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=scratch_descriptor,
            )
            build_snapshot = _capture_bound_directory(
                build_descriptor,
                build_root,
                parent_descriptor=scratch_descriptor,
                relative_name=build_name,
                expected=build_created_snapshot,
                expected_mode=0o700,
                exact_entries=(),
                error_message=error_message,
            )
        if build_snapshot.device != destination_snapshot.device:
            raise BuildError(error_message)
        scratch_snapshot = _capture_bound_directory(
            scratch_descriptor,
            scratch_parent,
            parent_descriptor=destination_descriptor,
            relative_name=scratch_name,
            expected=scratch_snapshot,
            expected_mode=0o700,
            exact_entries=(build_name,),
            error_message=error_message,
        )
        destination_snapshot = _capture_bound_directory(
            destination_descriptor,
            destination_parent,
            parent_descriptor=None,
            relative_name=None,
            expected=destination_snapshot,
            expected_mode=None,
            exact_entries=None,
            error_message=error_message,
        )
        return _ScratchCapability(
            destination_parent=destination_parent,
            destination_parent_descriptor=destination_descriptor,
            destination_parent_snapshot=destination_snapshot,
            scratch_parent=scratch_parent,
            scratch_parent_name=scratch_name,
            scratch_parent_descriptor=scratch_descriptor,
            scratch_parent_snapshot=scratch_snapshot,
            build_root=build_root,
            build_root_name=build_name,
            build_root_descriptor=build_descriptor,
            build_root_snapshot=build_snapshot,
        )
    except BuildError as exc:
        creation_error = exc
    except (OSError, RuntimeError) as exc:
        creation_error = exc
    except BaseException as exc:
        creation_error = exc
    else:  # pragma: no cover - the success path returns above
        raise AssertionError("unreachable")

    with _defer_publish_signals(preserve_error=creation_error):
        cleanup_failed = _cleanup_failed_scratch_creation(
            destination_descriptor=destination_descriptor,
            scratch_descriptor=scratch_descriptor,
            build_descriptor=build_descriptor,
            scratch_snapshot=scratch_snapshot,
            build_snapshot=build_snapshot,
            scratch_created=scratch_created,
            build_created=build_created,
            scratch_parent=scratch_parent,
            build_root=build_root,
            scratch_name=scratch_name,
            build_name=build_name,
        )
    if cleanup_failed:
        raise BuildError("Python sidecar scratch creation cleanup failed")
    if isinstance(creation_error, BuildError):
        raise creation_error
    if isinstance(creation_error, (KeyboardInterrupt, SystemExit)):
        raise creation_error
    raise BuildError(error_message) from creation_error


def _create_private_build_root(
    destination_parent: Path,
) -> _ScratchCapability:
    """Create scratch with process-signal translation around fd handoff."""

    with _translate_cleanup_signals():
        return _create_private_build_root_impl(destination_parent)


def _ensure_fixed_output_parent() -> Path:
    """Create only the reviewed generated directory through a held Desktop fd."""

    error_message = "Python sidecar output parent is unsafe"
    desktop_root = REPOSITORY_ROOT / "desktop"
    generated_root = desktop_root / "generated"
    desktop_descriptor: int | None = None
    generated_descriptor: int | None = None
    close_failed = False
    try:
        desktop_descriptor = os.open(
            desktop_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        desktop_snapshot = _capture_bound_directory(
            desktop_descriptor,
            desktop_root,
            parent_descriptor=None,
            relative_name=None,
            expected=None,
            expected_mode=None,
            exact_entries=None,
            error_message=error_message,
        )
        if stat.S_IMODE(desktop_snapshot.mode) & 0o022:
            raise BuildError(error_message)
        try:
            generated_entry = os.stat(
                "generated",
                dir_fd=desktop_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            os.mkdir("generated", mode=0o755, dir_fd=desktop_descriptor)
        else:
            if (
                not stat.S_ISDIR(generated_entry.st_mode)
                or stat.S_ISLNK(generated_entry.st_mode)
            ):
                raise BuildError(error_message)
        generated_descriptor = os.open(
            "generated",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=desktop_descriptor,
        )
        generated_snapshot = _capture_bound_directory(
            generated_descriptor,
            generated_root,
            parent_descriptor=desktop_descriptor,
            relative_name="generated",
            expected=None,
            expected_mode=None,
            exact_entries=None,
            error_message=error_message,
        )
        if (
            stat.S_IMODE(generated_snapshot.mode) & 0o022
            or generated_snapshot.device != desktop_snapshot.device
        ):
            raise BuildError(error_message)
        return generated_root
    except BuildError:
        raise
    except (OSError, RuntimeError) as exc:
        raise BuildError(error_message) from exc
    finally:
        for descriptor in (generated_descriptor, desktop_descriptor):
            if descriptor is None:
                continue
            try:
                os.close(descriptor)
            except OSError:
                close_failed = True
        if close_failed:
            raise BuildError(error_message)


def _git_blob_digest(size: int, chunks: Sequence[bytes]) -> str:
    digest = hashlib.sha1()
    digest.update(f"blob {size}\0".encode("ascii"))
    for chunk in chunks:
        digest.update(chunk)
    return digest.hexdigest()


def _source_inventory_layout(
    inventory: Sequence[_TreeEntry],
    *,
    error_message: str,
) -> tuple[
    dict[str, _TreeEntry],
    set[str],
    dict[str, tuple[str, ...]],
]:
    """Return the exact blob/directory namespace implied by a Git tree."""

    entries: dict[str, _TreeEntry] = {}
    directories = {""}
    for entry in inventory:
        if not all(
            isinstance(value, str)
            for value in (
                entry.path,
                entry.mode,
                entry.object_type,
                entry.object_id,
            )
        ):
            raise BuildError(error_message)
        pure = PurePosixPath(entry.path)
        if (
            entry.object_type != "blob"
            or entry.mode not in {"100644", "100755", "120000"}
            or re.fullmatch(r"[0-9a-f]{40}", entry.object_id) is None
            or not entry.path
            or pure.is_absolute()
            or pure.as_posix() != entry.path
            or len(pure.parts) > 128
            or any(part in {"", ".", "..", ".git"} for part in pure.parts)
            or "\\" in entry.path
            or any(ord(character) < 0x20 for character in entry.path)
            or entry.path in entries
        ):
            raise BuildError(error_message)
        entries[entry.path] = entry
        for index in range(1, len(pure.parts)):
            directories.add("/".join(pure.parts[:index]))
    if (
        not entries
        or any(path in directories for path in entries)
        or len(entries) + len(directories) - 1 > MAX_SOURCE_SNAPSHOT_FILES
    ):
        raise BuildError(error_message)

    children: dict[str, set[str]] = {path: set() for path in directories}
    for directory in directories - {""}:
        parent, _separator, name = directory.rpartition("/")
        if name in children[parent]:
            raise BuildError(error_message)
        children[parent].add(name)
    for path in entries:
        parent, _separator, name = path.rpartition("/")
        if name in children[parent]:
            raise BuildError(error_message)
        children[parent].add(name)
    return (
        entries,
        directories,
        {path: tuple(sorted(names)) for path, names in children.items()},
    )


def _source_directory_identity(info: os.stat_result) -> tuple[int, int]:
    return (info.st_dev, info.st_ino)


def _held_source_capability_path(capability: _ScratchCapability) -> Path:
    """Return an fd-backed source path after proving it denotes the held root."""

    error_message = "Exact Git source capability path is unavailable"
    descriptor = capability.source_snapshot_descriptor
    metadata = capability.source_snapshot_metadata
    if descriptor is None or metadata is None or capability.closed:
        raise BuildError(error_message)
    path = Path("/dev/fd") / str(descriptor)
    probe: int | None = None
    try:
        held = os.fstat(descriptor)
        path_info = os.stat(path, follow_symlinks=True)
        probe = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
        )
        opened = os.fstat(probe)
        if (
            not stat.S_ISDIR(held.st_mode)
            or _stable_directory_identity(held)
            != _stable_directory_identity(metadata)
            or _stable_directory_identity(path_info)
            != _stable_directory_identity(held)
            or _stable_directory_identity(opened)
            != _stable_directory_identity(held)
        ):
            raise BuildError(error_message)
        return path
    except BuildError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise BuildError(error_message) from exc
    finally:
        if probe is not None:
            try:
                os.close(probe)
            except OSError as exc:
                if sys.exception() is None:
                    raise BuildError(error_message) from exc


def _open_source_directory(
    root_descriptor: int,
    relative_path: str,
    identities: Mapping[str, tuple[int, int]],
    *,
    allowed_modes: frozenset[int],
    error_message: str,
) -> int:
    """Open one recorded snapshot directory through only held parent fds."""

    current_descriptor: int | None = None
    try:
        root_before = os.fstat(root_descriptor)
        current_descriptor = os.dup(root_descriptor)
        root_opened = os.fstat(current_descriptor)
        root_after = os.fstat(root_descriptor)
        root_identity = identities.get("")
        if (
            root_identity is None
            or _stat_metadata(root_opened) != _stat_metadata(root_before)
            or _stat_metadata(root_after) != _stat_metadata(root_before)
            or _source_directory_identity(root_before) != root_identity
        ):
            raise BuildError(error_message)

        prefix = ""
        for name in PurePosixPath(relative_path).parts if relative_path else ():
            parent_before = os.fstat(current_descriptor)
            child_before = os.stat(
                name,
                dir_fd=current_descriptor,
                follow_symlinks=False,
            )
            child_descriptor = os.open(
                name,
                os.O_RDONLY
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | os.O_CLOEXEC,
                dir_fd=current_descriptor,
            )
            try:
                child_opened = os.fstat(child_descriptor)
                child_relative = os.stat(
                    name,
                    dir_fd=current_descriptor,
                    follow_symlinks=False,
                )
                parent_after = os.fstat(current_descriptor)
                child_path = f"{prefix}/{name}" if prefix else name
                if (
                    _stat_metadata(parent_after) != _stat_metadata(parent_before)
                    or _stat_metadata(child_opened) != _stat_metadata(child_before)
                    or _stat_metadata(child_relative) != _stat_metadata(child_before)
                    or not stat.S_ISDIR(child_opened.st_mode)
                    or stat.S_ISLNK(child_relative.st_mode)
                    or _source_directory_identity(child_opened)
                    != identities.get(child_path)
                ):
                    raise BuildError(error_message)
            except BaseException:
                try:
                    os.close(child_descriptor)
                except OSError:
                    pass
                raise
            os.close(current_descriptor)
            current_descriptor = child_descriptor
            prefix = child_path

        current = os.fstat(current_descriptor)
        if (
            not stat.S_ISDIR(current.st_mode)
            or current.st_uid != os.geteuid()
            or current.st_gid != os.getegid()
            or current.st_nlink < 1
            or stat.S_IMODE(current.st_mode) not in allowed_modes
            or _source_directory_identity(current) != identities.get(relative_path)
            or current.st_dev != root_before.st_dev
        ):
            raise BuildError(error_message)
        return current_descriptor
    except BuildError:
        if current_descriptor is not None:
            try:
                os.close(current_descriptor)
            except OSError:
                pass
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        if current_descriptor is not None:
            try:
                os.close(current_descriptor)
            except OSError:
                pass
        raise BuildError(error_message) from exc
    except BaseException:
        if current_descriptor is not None:
            try:
                os.close(current_descriptor)
            except OSError:
                pass
        raise


@contextlib.contextmanager
def _held_source_directory(
    root_descriptor: int,
    relative_path: str,
    identities: Mapping[str, tuple[int, int]],
    *,
    allowed_modes: frozenset[int],
    error_message: str,
) -> Any:
    descriptor = _open_source_directory(
        root_descriptor,
        relative_path,
        identities,
        allowed_modes=allowed_modes,
        error_message=error_message,
    )
    try:
        yield descriptor
    finally:
        active_error = sys.exception()
        try:
            os.close(descriptor)
        except OSError as exc:
            if active_error is None:
                raise BuildError(error_message) from exc


def _source_symlinks_are_contained(
    entries: Mapping[str, _TreeEntry],
    directories: set[str],
    targets: Mapping[str, str],
) -> bool:
    """Resolve reviewed link text lexically inside the inventory namespace."""

    node_types = {path: "directory" for path in directories}
    node_types.update(
        {
            path: "symlink" if entry.mode == "120000" else "regular"
            for path, entry in entries.items()
        }
    )
    for link_path, initial_target in targets.items():
        pending = deque(
            [
                *PurePosixPath(link_path).parent.parts,
                *PurePosixPath(initial_target).parts,
            ]
        )
        resolved: list[str] = []
        expansions = 0
        while pending:
            component = pending.popleft()
            if component in {"", "."}:
                continue
            if component == "..":
                if not resolved:
                    return False
                resolved.pop()
                continue
            candidate = "/".join((*resolved, component))
            node_type = node_types.get(candidate)
            if node_type is None:
                return False
            if node_type == "symlink":
                expansions += 1
                if expansions > len(targets) + 128:
                    return False
                target = targets.get(candidate)
                if target is None or PurePosixPath(target).is_absolute():
                    return False
                pending.extendleft(reversed(PurePosixPath(target).parts))
                continue
            resolved.append(component)
            if pending and node_type != "directory":
                return False
    return True


def _verify_source_inventory(
    descriptor: int,
    inventory: Sequence[_TreeEntry],
    *,
    error_message: str,
) -> tuple[tuple[Any, ...], ...]:
    """Hash and metadata-check an exact source tree from its held root fd."""

    entries, directories, children = _source_inventory_layout(
        inventory,
        error_message=error_message,
    )
    records: list[tuple[Any, ...]] = []
    symlink_targets: dict[str, str] = {}
    total_size = 0
    try:
        root_info = os.fstat(descriptor)
    except OSError as exc:
        raise BuildError(error_message) from exc
    root_device = root_info.st_dev

    def expected_directory_links(path: str) -> int:
        return 2 + sum(
            1
            for name in children[path]
            if (f"{path}/{name}" if path else name) in directories
        )

    def validate_directory(info: os.stat_result, path: str) -> None:
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_dev != root_device
            or info.st_uid != os.geteuid()
            or info.st_gid != os.getegid()
            or info.st_nlink != expected_directory_links(path)
            or stat.S_IMODE(info.st_mode) != 0o500
        ):
            raise BuildError(error_message)

    def visit(directory_descriptor: int, prefix: str, depth: int) -> None:
        nonlocal total_size
        if depth > 128:
            raise BuildError(error_message)
        directory_before = os.fstat(directory_descriptor)
        validate_directory(directory_before, prefix)
        try:
            names = tuple(sorted(os.listdir(directory_descriptor)))
        except OSError as exc:
            raise BuildError(error_message) from exc
        if names != children[prefix]:
            raise BuildError(error_message)
        for name in names:
            if not name or "/" in name or "\0" in name:
                raise BuildError(error_message)
            relative = f"{prefix}/{name}" if prefix else name
            try:
                before = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise BuildError(error_message) from exc
            if relative in directories:
                validate_directory(before, relative)
                child_descriptor: int | None = None
                try:
                    child_descriptor = os.open(
                        name,
                        os.O_RDONLY
                        | os.O_DIRECTORY
                        | os.O_NOFOLLOW
                        | os.O_CLOEXEC,
                        dir_fd=directory_descriptor,
                    )
                    opened = os.fstat(child_descriptor)
                    relative_now = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        _stat_metadata(opened) != _stat_metadata(before)
                        or _stat_metadata(relative_now) != _stat_metadata(before)
                    ):
                        raise BuildError(error_message)
                    records.append((relative, *_stat_metadata(before), None))
                    visit(child_descriptor, relative, depth + 1)
                    after = os.fstat(child_descriptor)
                    relative_after = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        _stat_metadata(after) != _stat_metadata(opened)
                        or _stat_metadata(relative_after) != _stat_metadata(opened)
                    ):
                        raise BuildError(error_message)
                except BuildError:
                    raise
                except (OSError, RuntimeError, ValueError) as exc:
                    raise BuildError(error_message) from exc
                finally:
                    if child_descriptor is not None:
                        active_error = sys.exception()
                        try:
                            os.close(child_descriptor)
                        except OSError as exc:
                            if active_error is None:
                                raise BuildError(error_message) from exc
                continue

            entry = entries.get(relative)
            if entry is None:
                raise BuildError(error_message)
            link_target: str | None = None
            if entry.mode in {"100644", "100755"}:
                expected_mode = 0o555 if entry.mode == "100755" else 0o444
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_dev != root_device
                    or before.st_uid != os.geteuid()
                    or before.st_gid != os.getegid()
                    or before.st_nlink != 1
                    or stat.S_IMODE(before.st_mode) != expected_mode
                    or before.st_size < 0
                    or before.st_size > MAX_SOURCE_SNAPSHOT_FILE_BYTES
                ):
                    raise BuildError(error_message)
                total_size += before.st_size
                if total_size > MAX_SOURCE_SNAPSHOT_TOTAL_BYTES:
                    raise BuildError(error_message)
                file_descriptor: int | None = None
                try:
                    file_descriptor = os.open(
                        name,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=directory_descriptor,
                    )
                    opened = os.fstat(file_descriptor)
                    relative_now = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        _stat_metadata(opened) != _stat_metadata(before)
                        or _stat_metadata(relative_now) != _stat_metadata(before)
                    ):
                        raise BuildError(error_message)
                    digest = hashlib.sha1()
                    digest.update(f"blob {before.st_size}\0".encode("ascii"))
                    read_size = 0
                    while read_size < before.st_size:
                        chunk = os.read(
                            file_descriptor,
                            min(1024 * 1024, before.st_size - read_size),
                        )
                        if not chunk:
                            raise BuildError(error_message)
                        read_size += len(chunk)
                        digest.update(chunk)
                    if os.read(file_descriptor, 1):
                        raise BuildError(error_message)
                    after = os.fstat(file_descriptor)
                    relative_after = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        read_size != before.st_size
                        or digest.hexdigest() != entry.object_id
                        or _stat_metadata(after) != _stat_metadata(opened)
                        or _stat_metadata(relative_after) != _stat_metadata(opened)
                    ):
                        raise BuildError(error_message)
                except BuildError:
                    raise
                except (OSError, RuntimeError, ValueError) as exc:
                    raise BuildError(error_message) from exc
                finally:
                    if file_descriptor is not None:
                        active_error = sys.exception()
                        try:
                            os.close(file_descriptor)
                        except OSError as exc:
                            if active_error is None:
                                raise BuildError(error_message) from exc
            elif entry.mode == "120000":
                if (
                    not stat.S_ISLNK(before.st_mode)
                    or before.st_dev != root_device
                    or before.st_uid != os.geteuid()
                    or before.st_gid != os.getegid()
                    or before.st_nlink != 1
                    or stat.S_IMODE(before.st_mode) != 0o777
                ):
                    raise BuildError(error_message)
                try:
                    link_target = os.readlink(name, dir_fd=directory_descriptor)
                    encoded_target = link_target.encode("utf-8", errors="strict")
                    after = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                except (OSError, UnicodeError) as exc:
                    raise BuildError(error_message) from exc
                if (
                    not link_target
                    or PurePosixPath(link_target).is_absolute()
                    or "\0" in link_target
                    or len(encoded_target) > MAX_SOURCE_SNAPSHOT_FILE_BYTES
                    or _git_blob_digest(len(encoded_target), (encoded_target,))
                    != entry.object_id
                    or _stat_metadata(after) != _stat_metadata(before)
                ):
                    raise BuildError(error_message)
                total_size += len(encoded_target)
                if total_size > MAX_SOURCE_SNAPSHOT_TOTAL_BYTES:
                    raise BuildError(error_message)
                symlink_targets[relative] = link_target
            else:  # pragma: no cover - layout rejects this
                raise BuildError(error_message)
            records.append((relative, *_stat_metadata(before), link_target))
            if len(records) > MAX_SOURCE_SNAPSHOT_FILES:
                raise BuildError(error_message)
        directory_after = os.fstat(directory_descriptor)
        if _stat_metadata(directory_after) != _stat_metadata(directory_before):
            raise BuildError(error_message)

    try:
        visit(descriptor, "", 0)
    except BuildError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise BuildError(error_message) from exc
    if (
        len(records) != len(entries) + len(directories) - 1
        or set(symlink_targets)
        != {path for path, entry in entries.items() if entry.mode == "120000"}
        or not _source_symlinks_are_contained(
            entries,
            directories,
            symlink_targets,
        )
    ):
        raise BuildError(error_message)
    return tuple(records)


def _materialize_source_snapshot(
    capability: _ScratchCapability,
    release_state: Mapping[str, Any],
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> Path:
    """Materialize and verify an inventory-bound read-only commit snapshot."""

    error_message = "Exact Git source snapshot could not be materialized"
    inventory = release_state.get("sourceInventory")
    if not isinstance(inventory, tuple) or not all(
        isinstance(entry, _TreeEntry) for entry in inventory
    ):
        raise BuildError(error_message)
    expected, directories, root_children = _source_inventory_layout(
        inventory,
        error_message=error_message,
    )
    if (
        _source_snapshot_sha256(inventory)
        != release_state.get("sourceSnapshotSha256")
    ):
        raise BuildError(error_message)
    seen: set[str] = set()
    seen_directories: set[str] = set()
    snapshot_descriptor: int | None = None
    snapshot: Path | None = None
    snapshot_initial: _DirectorySnapshot | None = None
    build_root_binding: _DirectorySnapshot | None = None
    process: subprocess.Popen[bytes] | None = None
    stdout_closed = False
    try:
        _refresh_scratch_capability(capability, exact_build_entries=())
        snapshot = capability.build_root / SOURCE_SNAPSHOT_NAME
        snapshot_descriptor, snapshot_initial = _create_bound_child_directory(
            parent_descriptor=capability.build_root_descriptor,
            parent_path=capability.build_root,
            name=SOURCE_SNAPSHOT_NAME,
            mode=0o700,
            error_message=error_message,
        )
        build_root_binding = _capture_bound_directory(
            capability.build_root_descriptor,
            capability.build_root,
            parent_descriptor=capability.scratch_parent_descriptor,
            relative_name=capability.build_root_name,
            expected=capability.build_root_snapshot,
            expected_mode=0o700,
            exact_entries=(SOURCE_SNAPSHOT_NAME,),
            error_message=error_message,
        )
        directory_identities: dict[str, tuple[int, int]] = {
            "": (snapshot_initial.device, snapshot_initial.inode)
        }
        for directory in sorted(
            directories - {""},
            key=lambda path: (len(PurePosixPath(path).parts), path),
        ):
            parent, _separator, name = directory.rpartition("/")
            with _held_source_directory(
                snapshot_descriptor,
                parent,
                directory_identities,
                allowed_modes=frozenset({0o700}),
                error_message=error_message,
            ) as parent_descriptor:
                try:
                    os.stat(
                        name,
                        dir_fd=parent_descriptor,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    pass
                else:
                    raise BuildError(error_message)
                child_descriptor: int | None = None
                try:
                    parent_path = snapshot if not parent else snapshot / parent
                    child_descriptor, child_snapshot = (
                        _create_bound_child_directory(
                            parent_descriptor=parent_descriptor,
                            parent_path=parent_path,
                            name=name,
                            mode=0o700,
                            error_message=error_message,
                        )
                    )
                    opened = os.fstat(child_descriptor)
                    if (
                        _stable_directory_identity(opened)
                        != _stable_directory_identity(child_snapshot)
                        or not stat.S_ISDIR(opened.st_mode)
                        or opened.st_uid != os.geteuid()
                        or opened.st_gid != os.getegid()
                        or opened.st_nlink != 2
                        or stat.S_IMODE(opened.st_mode) != 0o700
                        or opened.st_dev != snapshot_initial.device
                    ):
                        raise BuildError(error_message)
                    directory_identities[directory] = _source_directory_identity(
                        opened
                    )
                except BuildError:
                    raise
                except (OSError, RuntimeError, ValueError) as exc:
                    raise BuildError(error_message) from exc
                finally:
                    if child_descriptor is not None:
                        active_error = sys.exception()
                        try:
                            os.close(child_descriptor)
                        except OSError as exc:
                            if active_error is None:
                                raise BuildError(error_message) from exc
        with _defer_publish_signals():
            process = subprocess.Popen(
                [
                    *_isolated_git_command(
                        "archive",
                        "--format=tar",
                        str(release_state.get("repositoryCommit", "")),
                        repository_root=repository_root,
                    ),
                ],
                cwd=repository_root,
                env=_isolated_git_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        if process.stdout is None:
            raise BuildError(error_message)
        total_size = 0
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for member in archive:
                name = member.name[:-1] if member.name.endswith("/") else member.name
                pure = PurePosixPath(name)
                if (
                    not name
                    or pure.is_absolute()
                    or pure.as_posix() != name
                    or any(part in {"", ".", "..", ".git"} for part in pure.parts)
                    or "\\" in name
                    or any(ord(character) < 0x20 for character in name)
                ):
                    raise BuildError(error_message)
                if member.isdir():
                    if name not in directories or name in seen_directories:
                        raise BuildError(error_message)
                    seen_directories.add(name)
                    continue
                entry = expected.get(name)
                if entry is None or name in seen:
                    raise BuildError(error_message)
                parent = pure.parent.as_posix()
                if parent == ".":
                    parent = ""
                leaf = pure.name
                if entry.mode in {"100644", "100755"}:
                    if (
                        not member.isfile()
                        or member.issym()
                        or member.islnk()
                        or member.size < 0
                        or member.size > MAX_SOURCE_SNAPSHOT_FILE_BYTES
                    ):
                        raise BuildError(error_message)
                    total_size += member.size
                    if total_size > MAX_SOURCE_SNAPSHOT_TOTAL_BYTES:
                        raise BuildError(error_message)
                    source = archive.extractfile(member)
                    if source is None:
                        raise BuildError(error_message)
                    digest = hashlib.sha1()
                    digest.update(f"blob {member.size}\0".encode("ascii"))
                    written = 0
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
                    flags |= os.O_NOFOLLOW
                    descriptor: int | None = None
                    try:
                        with _held_source_directory(
                            snapshot_descriptor,
                            parent,
                            directory_identities,
                            allowed_modes=frozenset({0o700}),
                            error_message=error_message,
                        ) as parent_descriptor:
                            descriptor = os.open(
                                leaf,
                                flags,
                                0o600,
                                dir_fd=parent_descriptor,
                            )
                            os.fchmod(descriptor, 0o600)
                            created = os.fstat(descriptor)
                            relative = os.stat(
                                leaf,
                                dir_fd=parent_descriptor,
                                follow_symlinks=False,
                            )
                            if (
                                _stat_metadata(created) != _stat_metadata(relative)
                                or not stat.S_ISREG(created.st_mode)
                                or created.st_uid != os.geteuid()
                                or created.st_gid != os.getegid()
                                or created.st_nlink != 1
                                or created.st_size != 0
                                or stat.S_IMODE(created.st_mode) != 0o600
                                or created.st_dev != snapshot_initial.device
                            ):
                                raise BuildError(error_message)
                            while True:
                                chunk = source.read(1024 * 1024)
                                if not chunk:
                                    break
                                written += len(chunk)
                                if written > member.size:
                                    raise BuildError(error_message)
                                digest.update(chunk)
                                remaining = memoryview(chunk)
                                while remaining:
                                    count = os.write(descriptor, remaining)
                                    if count <= 0:
                                        raise BuildError(error_message)
                                    remaining = remaining[count:]
                            os.fsync(descriptor)
                            if (
                                written != member.size
                                or digest.hexdigest() != entry.object_id
                            ):
                                raise BuildError(error_message)
                            os.fchmod(
                                descriptor,
                                0o555 if entry.mode == "100755" else 0o444,
                            )
                            finalized = os.fstat(descriptor)
                            relative = os.stat(
                                leaf,
                                dir_fd=parent_descriptor,
                                follow_symlinks=False,
                            )
                            if (
                                _stat_metadata(finalized) != _stat_metadata(relative)
                                or finalized.st_size != member.size
                                or stat.S_IMODE(finalized.st_mode)
                                != (0o555 if entry.mode == "100755" else 0o444)
                            ):
                                raise BuildError(error_message)
                    finally:
                        active_error = sys.exception()
                        close_failed: OSError | None = None
                        if descriptor is not None:
                            try:
                                os.close(descriptor)
                            except OSError as exc:
                                close_failed = exc
                        try:
                            source.close()
                        except OSError as exc:
                            close_failed = close_failed or exc
                        if close_failed is not None and active_error is None:
                            raise BuildError(error_message) from close_failed
                elif entry.mode == "120000":
                    if not member.issym() or member.islnk():
                        raise BuildError(error_message)
                    link_target = member.linkname
                    try:
                        encoded_target = link_target.encode(
                            "utf-8",
                            errors="strict",
                        )
                    except UnicodeError as exc:
                        raise BuildError(error_message) from exc
                    if (
                        not link_target
                        or PurePosixPath(link_target).is_absolute()
                        or "\x00" in link_target
                        or len(encoded_target) > MAX_SOURCE_SNAPSHOT_FILE_BYTES
                        or _git_blob_digest(len(encoded_target), (encoded_target,))
                        != entry.object_id
                    ):
                        raise BuildError(error_message)
                    total_size += len(encoded_target)
                    if total_size > MAX_SOURCE_SNAPSHOT_TOTAL_BYTES:
                        raise BuildError(error_message)
                    with _held_source_directory(
                        snapshot_descriptor,
                        parent,
                        directory_identities,
                        allowed_modes=frozenset({0o700}),
                        error_message=error_message,
                    ) as parent_descriptor:
                        os.symlink(
                            link_target,
                            leaf,
                            dir_fd=parent_descriptor,
                        )
                        relative = os.stat(
                            leaf,
                            dir_fd=parent_descriptor,
                            follow_symlinks=False,
                        )
                        actual_target = os.readlink(
                            leaf,
                            dir_fd=parent_descriptor,
                        )
                        after = os.stat(
                            leaf,
                            dir_fd=parent_descriptor,
                            follow_symlinks=False,
                        )
                        if (
                            _stat_metadata(after) != _stat_metadata(relative)
                            or not stat.S_ISLNK(relative.st_mode)
                            or relative.st_uid != os.geteuid()
                            or relative.st_gid != os.getegid()
                            or relative.st_nlink != 1
                            or stat.S_IMODE(relative.st_mode) != 0o777
                            or relative.st_dev != snapshot_initial.device
                            or actual_target != link_target
                        ):
                            raise BuildError(error_message)
                else:  # pragma: no cover - inventory parsing rejects this
                    raise BuildError(error_message)
                seen.add(name)
        process.stdout.close()
        stdout_closed = True
        if process.wait(timeout=30) != 0 or seen != set(expected):
            raise BuildError(error_message)
        with _defer_publish_signals():
            descendants = _process_group_exists(process.pid)
            if descendants:
                _terminate_owned_process_group(
                    process,
                    error_message="Exact Git archive process group did not stop",
                )
        if descendants:
            raise BuildError("Exact Git archive left a descendant process running")
        for directory in sorted(
            directories - {""},
            key=lambda path: (-len(PurePosixPath(path).parts), path),
        ):
            with _held_source_directory(
                snapshot_descriptor,
                directory,
                directory_identities,
                allowed_modes=frozenset({0o700, 0o500}),
                error_message=error_message,
            ) as directory_descriptor:
                os.fchmod(directory_descriptor, 0o500)
                if stat.S_IMODE(os.fstat(directory_descriptor).st_mode) != 0o500:
                    raise BuildError(error_message)
        os.fchmod(snapshot_descriptor, 0o500)
        metadata = _capture_bound_directory(
            snapshot_descriptor,
            snapshot,
            parent_descriptor=capability.build_root_descriptor,
            relative_name=SOURCE_SNAPSHOT_NAME,
            expected=None,
            expected_mode=0o500,
            exact_entries=root_children[""],
            error_message=error_message,
        )
        source_tree_metadata = _verify_source_inventory(
            snapshot_descriptor,
            inventory,
            error_message=error_message,
        )
        final_build_root = _capture_bound_directory(
            capability.build_root_descriptor,
            capability.build_root,
            parent_descriptor=capability.scratch_parent_descriptor,
            relative_name=capability.build_root_name,
            expected=build_root_binding,
            expected_mode=0o700,
            exact_entries=(SOURCE_SNAPSHOT_NAME,),
            error_message=error_message,
        )
        if final_build_root != build_root_binding:
            raise BuildError(error_message)
        capability.source_snapshot = snapshot
        capability.source_snapshot_descriptor = snapshot_descriptor
        capability.source_snapshot_metadata = metadata
        capability.source_inventory = tuple(inventory)
        capability.source_tree_metadata = source_tree_metadata
        capability.build_root_snapshot = final_build_root
        return _held_source_capability_path(capability)
    except _CleanupBlockedError:
        capability.poisoned = True
        raise
    except BuildError:
        raise
    except (
        OSError,
        RuntimeError,
        UnicodeError,
        ValueError,
        tarfile.TarError,
        subprocess.SubprocessError,
    ) as exc:
        raise BuildError(error_message) from exc
    finally:
        active_error = sys.exception()
        process_cleanup_error: BaseException | None = None
        if process is not None and process.stdout is not None and not stdout_closed:
            try:
                process.stdout.close()
            except OSError:
                pass
        if process is not None:
            try:
                with _defer_publish_signals(preserve_error=active_error):
                    if _process_group_exists(process.pid):
                        _terminate_owned_process_group(
                            process,
                            error_message=(
                                "Exact Git archive process group did not stop"
                            ),
                        )
            except BaseException as exc:
                process_cleanup_error = exc
        if (
            snapshot_descriptor is not None
            and capability.source_snapshot_descriptor != snapshot_descriptor
        ):
            try:
                os.close(snapshot_descriptor)
            except OSError:
                pass
        if process_cleanup_error is not None:
            capability.poisoned = True
            raise BuildError(
                "Exact Git archive process group cleanup failed"
            ) from (active_error or process_cleanup_error)


def _validate_source_snapshot(capability: _ScratchCapability) -> Path:
    error_message = "Exact Git source snapshot changed during packaging"
    if (
        capability.closed
        or capability.source_snapshot is None
        or capability.source_snapshot_descriptor is None
        or capability.source_snapshot_metadata is None
        or capability.source_inventory is None
        or capability.source_tree_metadata is None
    ):
        raise BuildError(error_message)
    build_root_before = _capture_bound_directory(
        capability.build_root_descriptor,
        capability.build_root,
        parent_descriptor=capability.scratch_parent_descriptor,
        relative_name=capability.build_root_name,
        expected=capability.build_root_snapshot,
        expected_mode=0o700,
        exact_entries=None,
        error_message=error_message,
    )
    root_before = _capture_bound_directory(
        capability.source_snapshot_descriptor,
        capability.source_snapshot,
        parent_descriptor=capability.build_root_descriptor,
        relative_name=SOURCE_SNAPSHOT_NAME,
        expected=capability.source_snapshot_metadata,
        expected_mode=0o500,
        exact_entries=capability.source_snapshot_metadata.entries,
        error_message=error_message,
    )
    current_tree = _verify_source_inventory(
        capability.source_snapshot_descriptor,
        capability.source_inventory,
        error_message=error_message,
    )
    root_after = _capture_bound_directory(
        capability.source_snapshot_descriptor,
        capability.source_snapshot,
        parent_descriptor=capability.build_root_descriptor,
        relative_name=SOURCE_SNAPSHOT_NAME,
        expected=capability.source_snapshot_metadata,
        expected_mode=0o500,
        exact_entries=capability.source_snapshot_metadata.entries,
        error_message=error_message,
    )
    build_root_after = _capture_bound_directory(
        capability.build_root_descriptor,
        capability.build_root,
        parent_descriptor=capability.scratch_parent_descriptor,
        relative_name=capability.build_root_name,
        expected=build_root_before,
        expected_mode=0o700,
        exact_entries=build_root_before.entries,
        error_message=error_message,
    )
    if (
        root_before != capability.source_snapshot_metadata
        or root_after != capability.source_snapshot_metadata
        or build_root_after != build_root_before
        or current_tree != capability.source_tree_metadata
    ):
        raise BuildError(error_message)
    return _held_source_capability_path(capability)


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
    except BaseException:
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
    bundle_descriptor: int | None = None,
) -> dict[str, Any]:
    """Exercise the frozen API and a real domain lifecycle under PATH traps."""

    executable = bundle / "lcf-service"
    try:
        executable_info = executable.lstat()
    except OSError as exc:
        raise BuildError("Frozen sidecar executable is unavailable") from exc
    if (
        not stat.S_ISREG(executable_info.st_mode)
        or stat.S_ISLNK(executable_info.st_mode)
        or not stat.S_IMODE(executable_info.st_mode) & 0o111
    ):
        raise BuildError("Frozen sidecar executable is unsafe")
    with _held_private_smoke_root() as smoke_root:
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
            inherited_descriptor=bundle_descriptor,
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
            inherited_descriptor=bundle_descriptor,
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
        except BaseException:
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
            with _defer_publish_signals():
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
                    pass_fds=tuple(
                        descriptor
                        for descriptor in (3, 4, bundle_descriptor)
                        if descriptor is not None
                    ),
                    close_fds=True,
                    start_new_session=True,
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
                or post_publish_health["qmd"].get("enabled") is not False
                or post_publish_health["qmd"].get("available") is not True
                or post_publish_health["qmd"].get("hybrid_enabled") is not False
            ):
                raise BuildError(
                    "Frozen domain publication did not activate desktop retrieval"
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
            with _defer_publish_signals():
                descendants = _process_group_exists(process.pid)
                if descendants:
                    _terminate_owned_process_group(
                        process,
                        error_message="Frozen sidecar process group did not stop",
                    )
            if descendants:
                raise BuildError("Frozen sidecar left a descendant process running")
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
            active_error = sys.exception()
            process_cleanup_error: BaseException | None = None
            if saved_descriptors:
                _restore_parent_control_fds(saved_descriptors)
            for descriptor in writers.values():
                os.close(descriptor)
            if process is not None:
                try:
                    with _defer_publish_signals(preserve_error=active_error):
                        if _process_group_exists(process.pid):
                            _terminate_owned_process_group(
                                process,
                                error_message=(
                                    "Frozen sidecar process group did not stop"
                                ),
                            )
                except BaseException as exc:
                    process_cleanup_error = exc
            broker_stop.set()
            broker_listener.close()
            if broker_started:
                broker_thread.join(timeout=2)
                broker_shutdown_failed = broker_thread.is_alive()
            if log_handle is not None:
                log_handle.close()
            if process_cleanup_error is not None:
                raise BuildError(
                    "Frozen sidecar process group cleanup failed"
                ) from (active_error or process_cleanup_error)
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


def _exchange_at(
    first_parent_descriptor: int,
    first_name: str,
    second_parent_descriptor: int,
    second_name: str,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    encoded_first = os.fsencode(first_name)
    encoded_second = os.fsencode(second_name)
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
        result = function(
            first_parent_descriptor,
            encoded_first,
            second_parent_descriptor,
            encoded_second,
            0x00000002,
        )
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
        result = function(
            first_parent_descriptor,
            encoded_first,
            second_parent_descriptor,
            encoded_second,
            0x2,
        )
    else:
        raise BuildError("Atomic staging replacement is unsupported on this OS")
    if result != 0:
        error_number = ctypes.get_errno()
        raise BuildError("Atomic staging exchange failed") from OSError(
            error_number,
            os.strerror(error_number),
        )


def _rename_noreplace_at(
    source_parent_descriptor: int,
    source_name: str,
    destination_parent_descriptor: int,
    destination_name: str,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    encoded_source = os.fsencode(source_name)
    encoded_destination = os.fsencode(destination_name)
    if platform.system() == "Darwin":
        function = getattr(libc, "renameatx_np", None)
        if function is None:
            raise BuildError("Atomic no-replace rename is unavailable on Darwin")
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        result = function(
            source_parent_descriptor,
            encoded_source,
            destination_parent_descriptor,
            encoded_destination,
            0x00000004,
        )
    elif platform.system() == "Linux":
        function = getattr(libc, "renameat2", None)
        if function is None:
            raise BuildError("Atomic no-replace rename is unavailable on Linux")
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        result = function(
            source_parent_descriptor,
            encoded_source,
            destination_parent_descriptor,
            encoded_destination,
            0x1,
        )
    else:
        raise BuildError("Atomic no-replace staging is unsupported on this OS")
    if result != 0:
        error_number = ctypes.get_errno()
        raise BuildError("Atomic no-replace staging rename failed") from OSError(
            error_number,
            os.strerror(error_number),
        )


def _open_publish_capability(
    candidate: Path,
    destination: Path,
    *,
    held_candidate: _EvidenceCapability | _BundleCapability | None = None,
) -> _PublishCapability:
    error_message = "Atomic staging capability is unsafe"
    descriptors: list[int] = []
    try:
        if (
            not candidate.is_absolute()
            or not destination.is_absolute()
            or candidate == destination
            or candidate.parent.resolve(strict=True) != candidate.parent
            or destination.parent.resolve(strict=True) != destination.parent
            or candidate.resolve(strict=True) != candidate
            or candidate.name in {"", ".", ".."}
            or destination.name in {"", ".", ".."}
        ):
            raise BuildError(error_message)
        candidate_parent_descriptor = os.open(
            candidate.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        descriptors.append(candidate_parent_descriptor)
        destination_parent_descriptor = os.open(
            destination.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        descriptors.append(destination_parent_descriptor)
        candidate_parent_snapshot = _capture_bound_directory(
            candidate_parent_descriptor,
            candidate.parent,
            parent_descriptor=None,
            relative_name=None,
            expected=None,
            expected_mode=None,
            exact_entries=None,
            error_message=error_message,
        )
        destination_parent_snapshot = _capture_bound_directory(
            destination_parent_descriptor,
            destination.parent,
            parent_descriptor=None,
            relative_name=None,
            expected=None,
            expected_mode=None,
            exact_entries=None,
            error_message=error_message,
        )
        if (
            candidate_parent_snapshot.device
            != destination_parent_snapshot.device
            or stat.S_IMODE(candidate_parent_snapshot.mode) & 0o022
            or stat.S_IMODE(destination_parent_snapshot.mode) & 0o022
        ):
            raise BuildError(error_message)
        if held_candidate is not None:
            if (
                held_candidate.closed
                or held_candidate.path != candidate
                or held_candidate.name != candidate.name
                or _stable_directory_identity(
                    os.fstat(held_candidate.parent_descriptor)
                )
                != _stable_directory_identity(candidate_parent_snapshot)
            ):
                raise _CapabilityDriftError(error_message)
            candidate_descriptor = os.dup(held_candidate.descriptor)
            os.set_inheritable(candidate_descriptor, False)
        else:
            candidate_descriptor = os.open(
                candidate.name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=candidate_parent_descriptor,
            )
        descriptors.append(candidate_descriptor)
        candidate_snapshot = _capture_bound_directory(
            candidate_descriptor,
            candidate,
            parent_descriptor=candidate_parent_descriptor,
            relative_name=candidate.name,
            expected=(
                held_candidate.snapshot
                if held_candidate is not None
                else None
            ),
            expected_mode=None,
            exact_entries=None,
            error_message=error_message,
        )
        if stat.S_IMODE(candidate_snapshot.mode) & 0o022:
            raise BuildError(error_message)
        candidate_tree_snapshot = _tree_metadata_snapshot(
            candidate_descriptor,
            error_message=error_message,
        )
        if held_candidate is not None and (
            candidate_snapshot != held_candidate.snapshot
            or candidate_tree_snapshot != held_candidate.tree_snapshot
            or _stable_directory_identity(
                os.fstat(held_candidate.descriptor)
            )
            != _stable_directory_identity(candidate_snapshot)
        ):
            raise _CapabilityDriftError(error_message)
        if isinstance(held_candidate, _EvidenceCapability):
            _read_held_evidence_tree(
                held_candidate,
                expected_tree=held_candidate.tree_snapshot,
                expected_content=held_candidate.content_snapshot,
                error_message=error_message,
            )

        existing_descriptor: int | None = None
        existing_snapshot: _DirectorySnapshot | None = None
        existing_tree: tuple[tuple[Any, ...], ...] | None = None
        try:
            destination_entry = os.stat(
                destination.name,
                dir_fd=destination_parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            destination_entry = None
        if destination_entry is not None:
            if not stat.S_ISDIR(destination_entry.st_mode):
                raise BuildError(error_message)
            existing_descriptor = os.open(
                destination.name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=destination_parent_descriptor,
            )
            descriptors.append(existing_descriptor)
            existing_snapshot = _capture_bound_directory(
                existing_descriptor,
                destination,
                parent_descriptor=destination_parent_descriptor,
                relative_name=destination.name,
                expected=None,
                expected_mode=None,
                exact_entries=None,
                error_message=error_message,
            )
            if stat.S_IMODE(existing_snapshot.mode) & 0o022:
                raise BuildError(error_message)
            existing_tree = _tree_metadata_snapshot(
                existing_descriptor,
                error_message=error_message,
            )
        return _PublishCapability(
            candidate=candidate,
            candidate_name=candidate.name,
            candidate_parent=candidate.parent,
            candidate_parent_descriptor=candidate_parent_descriptor,
            candidate_parent_snapshot=candidate_parent_snapshot,
            candidate_descriptor=candidate_descriptor,
            candidate_snapshot=candidate_snapshot,
            candidate_tree_snapshot=candidate_tree_snapshot,
            destination=destination,
            destination_name=destination.name,
            destination_parent=destination.parent,
            destination_parent_descriptor=destination_parent_descriptor,
            destination_parent_snapshot=destination_parent_snapshot,
            existing_destination_descriptor=existing_descriptor,
            existing_destination_snapshot=existing_snapshot,
            existing_destination_tree_snapshot=existing_tree,
        )
    except BuildError:
        raise
    except (OSError, RuntimeError) as exc:
        raise BuildError(error_message) from exc
    finally:
        if sys.exc_info()[0] is not None:
            for descriptor in reversed(descriptors):
                try:
                    os.close(descriptor)
                except OSError:
                    pass


def _close_publish_capability(capability: _PublishCapability) -> None:
    failed = False
    seen: set[int] = set()
    for descriptor in (
        capability.existing_destination_descriptor,
        capability.candidate_descriptor,
        capability.destination_parent_descriptor,
        capability.candidate_parent_descriptor,
    ):
        if descriptor is None or descriptor in seen:
            continue
        seen.add(descriptor)
        try:
            os.close(descriptor)
        except OSError:
            failed = True
    if failed:
        raise BuildError("Atomic staging capability cleanup failed")


def _revalidate_publish_directory(
    descriptor: int,
    path: Path,
    *,
    parent_descriptor: int,
    relative_name: str,
    expected: _DirectorySnapshot,
    expected_tree: tuple[tuple[Any, ...], ...],
    error_message: str,
    allow_root_metadata_change: bool = False,
) -> _DirectorySnapshot:
    try:
        current = _capture_bound_directory(
            descriptor,
            path,
            parent_descriptor=parent_descriptor,
            relative_name=relative_name,
            expected=expected,
            expected_mode=None,
            exact_entries=expected.entries,
            error_message=error_message,
        )
        if (
            _stable_directory_identity(current)
            != _stable_directory_identity(expected)
            or (not allow_root_metadata_change and current != expected)
            or _tree_metadata_snapshot(
                descriptor,
                error_message=error_message,
            )
            != expected_tree
        ):
            raise _CapabilityDriftError(error_message)
        return current
    except _CapabilityDriftError:
        raise
    except BaseException as exc:
        raise _CapabilityDriftError(error_message) from exc


def _revalidate_publish_parent(
    descriptor: int,
    path: Path,
    expected: _DirectorySnapshot,
    *,
    error_message: str,
    allow_metadata_change: bool = False,
    expected_entries: tuple[str, ...] | None = None,
) -> _DirectorySnapshot:
    try:
        current = _capture_bound_directory(
            descriptor,
            path,
            parent_descriptor=None,
            relative_name=None,
            expected=expected,
            expected_mode=None,
            exact_entries=(
                expected.entries
                if expected_entries is None
                else expected_entries
            ),
            error_message=error_message,
        )
        if not allow_metadata_change and current != expected:
            raise _CapabilityDriftError(error_message)
        return current
    except _CapabilityDriftError:
        raise
    except BaseException as exc:
        raise _CapabilityDriftError(error_message) from exc


def _finish_publish_signal_deferral(
    scope: Any | None,
    primary_error: BaseException | None,
) -> None:
    if scope is None:
        return
    try:
        scope.__exit__(
            type(primary_error) if primary_error is not None else None,
            primary_error,
            primary_error.__traceback__ if primary_error is not None else None,
        )
    except _DeferredSignalError:
        if primary_error is None:
            raise
    except BaseException as signal_error:
        if primary_error is not None:
            raise BuildError(
                "Atomic staging failed and signal cleanup failed"
            ) from primary_error
        raise BuildError(
            "Atomic staging signal cleanup failed"
        ) from signal_error


def _publish_staging_impl(
    candidate: Path,
    destination: Path,
    *,
    verifier: Callable[[Path], Any],
    held_candidate: _EvidenceCapability | _BundleCapability | None,
    ownership_transfer: _PublishOwnershipTransfer | None = None,
) -> None:
    """Verify and atomically publish a directory, rolling back on recheck."""

    capability = _open_publish_capability(
        candidate,
        destination,
        held_candidate=held_candidate,
    )
    swapped = False
    primary_error: BaseException | None = None
    cleanup_blocked = False
    transaction_signals: Any | None = None
    ownership_committed = False
    ownership_descriptors: tuple[int, ...] = ()
    old_cleanup_error: BaseException | None = None
    try:
        initial_candidate_parent_entries = (
            capability.candidate_parent_snapshot.entries
        )
        initial_destination_parent_entries = (
            capability.destination_parent_snapshot.entries
        )
        candidate_parent_identity = _stable_directory_identity(
            capability.candidate_parent_snapshot
        )
        destination_parent_identity = _stable_directory_identity(
            capability.destination_parent_snapshot
        )
        if capability.existing_destination_descriptor is not None:
            post_swap_candidate_parent_entries = initial_candidate_parent_entries
            post_swap_destination_parent_entries = (
                initial_destination_parent_entries
            )
        elif candidate_parent_identity == destination_parent_identity:
            entries = set(initial_candidate_parent_entries)
            if (
                capability.candidate_name not in entries
                or capability.destination_name in entries
            ):
                raise BuildError("Atomic staging parent inventory is inconsistent")
            entries.remove(capability.candidate_name)
            entries.add(capability.destination_name)
            post_swap_candidate_parent_entries = tuple(sorted(entries))
            post_swap_destination_parent_entries = (
                post_swap_candidate_parent_entries
            )
        else:
            candidate_entries = set(initial_candidate_parent_entries)
            destination_entries = set(initial_destination_parent_entries)
            if (
                capability.candidate_name not in candidate_entries
                or capability.destination_name in destination_entries
            ):
                raise BuildError("Atomic staging parent inventory is inconsistent")
            candidate_entries.remove(capability.candidate_name)
            destination_entries.add(capability.destination_name)
            post_swap_candidate_parent_entries = tuple(sorted(candidate_entries))
            post_swap_destination_parent_entries = tuple(sorted(destination_entries))
    except BaseException:
        try:
            _close_publish_capability(capability)
        except BuildError:
            pass
        raise
    try:
        verifier(candidate)
        _revalidate_publish_directory(
            capability.candidate_descriptor,
            capability.candidate,
            parent_descriptor=capability.candidate_parent_descriptor,
            relative_name=capability.candidate_name,
            expected=capability.candidate_snapshot,
            expected_tree=capability.candidate_tree_snapshot,
            error_message="Atomic staging candidate changed during verification",
        )
        capability.candidate_parent_snapshot = _revalidate_publish_parent(
            capability.candidate_parent_descriptor,
            capability.candidate_parent,
            capability.candidate_parent_snapshot,
            error_message="Atomic staging candidate parent changed",
        )
        capability.destination_parent_snapshot = _revalidate_publish_parent(
            capability.destination_parent_descriptor,
            capability.destination_parent,
            capability.destination_parent_snapshot,
            error_message="Atomic staging destination parent changed",
        )
        if (
            capability.existing_destination_descriptor is not None
            and capability.existing_destination_snapshot is not None
            and capability.existing_destination_tree_snapshot is not None
        ):
            _revalidate_publish_directory(
                capability.existing_destination_descriptor,
                capability.destination,
                parent_descriptor=capability.destination_parent_descriptor,
                relative_name=capability.destination_name,
                expected=capability.existing_destination_snapshot,
                expected_tree=capability.existing_destination_tree_snapshot,
                error_message="Atomic staging destination changed before swap",
            )
        transaction_signals = _defer_publish_signals()
        transaction_signals.__enter__()
        if capability.existing_destination_descriptor is not None:
            _exchange_at(
                capability.candidate_parent_descriptor,
                capability.candidate_name,
                capability.destination_parent_descriptor,
                capability.destination_name,
            )
        else:
            _rename_noreplace_at(
                capability.candidate_parent_descriptor,
                capability.candidate_name,
                capability.destination_parent_descriptor,
                capability.destination_name,
            )
        swapped = True
        capability.candidate_parent_snapshot = _revalidate_publish_parent(
            capability.candidate_parent_descriptor,
            capability.candidate_parent,
            capability.candidate_parent_snapshot,
            error_message="Atomic staging candidate parent changed after swap",
            allow_metadata_change=True,
            expected_entries=post_swap_candidate_parent_entries,
        )
        capability.destination_parent_snapshot = _revalidate_publish_parent(
            capability.destination_parent_descriptor,
            capability.destination_parent,
            capability.destination_parent_snapshot,
            error_message="Atomic staging destination parent changed after swap",
            allow_metadata_change=True,
            expected_entries=post_swap_destination_parent_entries,
        )
        capability.candidate_snapshot = _revalidate_publish_directory(
            capability.candidate_descriptor,
            capability.destination,
            parent_descriptor=capability.destination_parent_descriptor,
            relative_name=capability.destination_name,
            expected=capability.candidate_snapshot,
            expected_tree=capability.candidate_tree_snapshot,
            error_message="Published staging binding changed after swap",
            allow_root_metadata_change=True,
        )
        if (
            capability.existing_destination_descriptor is not None
            and capability.existing_destination_snapshot is not None
            and capability.existing_destination_tree_snapshot is not None
        ):
            capability.existing_destination_snapshot = _revalidate_publish_directory(
                capability.existing_destination_descriptor,
                capability.candidate,
                parent_descriptor=capability.candidate_parent_descriptor,
                relative_name=capability.candidate_name,
                expected=capability.existing_destination_snapshot,
                expected_tree=capability.existing_destination_tree_snapshot,
                error_message="Old staging destination binding changed after swap",
                allow_root_metadata_change=True,
            )
        verifier(destination)
        _revalidate_publish_directory(
            capability.candidate_descriptor,
            capability.destination,
            parent_descriptor=capability.destination_parent_descriptor,
            relative_name=capability.destination_name,
            expected=capability.candidate_snapshot,
            expected_tree=capability.candidate_tree_snapshot,
            error_message="Published staging changed during post-swap audit",
        )
        if ownership_transfer is not None:
            ownership_transfer.prepare(capability)
            # The commit gate remains inside the rollback-capable section and
            # performs no ownership mutation.  Only after it returns does the
            # publisher apply the fully preallocated Python state transfer.
            ownership_transfer.commit(capability)
    except BaseException as exc:
        primary_error = exc

    if primary_error is not None and not swapped:
        try:
            _revalidate_publish_directory(
                capability.candidate_descriptor,
                capability.candidate,
                parent_descriptor=capability.candidate_parent_descriptor,
                relative_name=capability.candidate_name,
                expected=capability.candidate_snapshot,
                expected_tree=capability.candidate_tree_snapshot,
                error_message="Atomic staging candidate changed during verification",
            )
        except BaseException:
            cleanup_blocked = True

    if primary_error is not None and swapped:
        try:
            capability.candidate_parent_snapshot = _revalidate_publish_parent(
                capability.candidate_parent_descriptor,
                capability.candidate_parent,
                capability.candidate_parent_snapshot,
                error_message="Published staging rollback safety check failed",
            )
            capability.destination_parent_snapshot = _revalidate_publish_parent(
                capability.destination_parent_descriptor,
                capability.destination_parent,
                capability.destination_parent_snapshot,
                error_message="Published staging rollback safety check failed",
            )
            _revalidate_publish_directory(
                capability.candidate_descriptor,
                capability.destination,
                parent_descriptor=capability.destination_parent_descriptor,
                relative_name=capability.destination_name,
                expected=capability.candidate_snapshot,
                expected_tree=capability.candidate_tree_snapshot,
                error_message="Published staging rollback safety check failed",
            )
            if (
                capability.existing_destination_descriptor is not None
                and capability.existing_destination_snapshot is not None
                and capability.existing_destination_tree_snapshot is not None
            ):
                _revalidate_publish_directory(
                    capability.existing_destination_descriptor,
                    capability.candidate,
                    parent_descriptor=capability.candidate_parent_descriptor,
                    relative_name=capability.candidate_name,
                    expected=capability.existing_destination_snapshot,
                    expected_tree=capability.existing_destination_tree_snapshot,
                    error_message="Published staging rollback safety check failed",
                )
                _exchange_at(
                    capability.candidate_parent_descriptor,
                    capability.candidate_name,
                    capability.destination_parent_descriptor,
                    capability.destination_name,
                )
            else:
                _rename_noreplace_at(
                    capability.destination_parent_descriptor,
                    capability.destination_name,
                    capability.candidate_parent_descriptor,
                    capability.candidate_name,
                )
            capability.candidate_parent_snapshot = _revalidate_publish_parent(
                capability.candidate_parent_descriptor,
                capability.candidate_parent,
                capability.candidate_parent_snapshot,
                error_message="Published staging rollback safety check failed",
                allow_metadata_change=True,
                expected_entries=initial_candidate_parent_entries,
            )
            capability.destination_parent_snapshot = _revalidate_publish_parent(
                capability.destination_parent_descriptor,
                capability.destination_parent,
                capability.destination_parent_snapshot,
                error_message="Published staging rollback safety check failed",
                allow_metadata_change=True,
                expected_entries=initial_destination_parent_entries,
            )
            capability.candidate_snapshot = _revalidate_publish_directory(
                capability.candidate_descriptor,
                capability.candidate,
                parent_descriptor=capability.candidate_parent_descriptor,
                relative_name=capability.candidate_name,
                expected=capability.candidate_snapshot,
                expected_tree=capability.candidate_tree_snapshot,
                error_message="Published staging rollback safety check failed",
                allow_root_metadata_change=True,
            )
            if (
                capability.existing_destination_descriptor is not None
                and capability.existing_destination_snapshot is not None
                and capability.existing_destination_tree_snapshot is not None
            ):
                capability.existing_destination_snapshot = _revalidate_publish_directory(
                    capability.existing_destination_descriptor,
                    capability.destination,
                    parent_descriptor=capability.destination_parent_descriptor,
                    relative_name=capability.destination_name,
                    expected=capability.existing_destination_snapshot,
                    expected_tree=capability.existing_destination_tree_snapshot,
                    error_message="Published staging rollback safety check failed",
                    allow_root_metadata_change=True,
                )
            else:
                try:
                    os.stat(
                        capability.destination_name,
                        dir_fd=capability.destination_parent_descriptor,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    pass
                else:
                    raise _CapabilityDriftError(
                        "Published staging rollback safety check failed"
                    )
            if ownership_transfer is not None:
                # The callback existed before the swap, so even failures in
                # the post-swap verifier or ownership prepare restore every
                # caller-owned snapshot after namespace rollback completes.
                ownership_transfer.rollback(capability)
        except BaseException as rollback_error:
            try:
                _close_publish_capability(capability)
            except BuildError:
                pass
            _finish_publish_signal_deferral(
                transaction_signals,
                rollback_error,
            )
            raise _CleanupBlockedError(
                "Published staging rollback safety check failed"
            ) from rollback_error

    if (
        primary_error is None
        and capability.existing_destination_descriptor is not None
        and not (
            ownership_transfer is not None
            and ownership_transfer.retain_previous_in_scratch
        )
    ):
        try:
            if (
                capability.existing_destination_snapshot is None
                or capability.existing_destination_tree_snapshot is None
            ):
                raise BuildError("Published staging old destination cleanup failed")
            capability.candidate_parent_snapshot = _revalidate_publish_parent(
                capability.candidate_parent_descriptor,
                capability.candidate_parent,
                capability.candidate_parent_snapshot,
                error_message="Published staging old destination cleanup failed",
            )
            _revalidate_publish_directory(
                capability.existing_destination_descriptor,
                capability.candidate,
                parent_descriptor=capability.candidate_parent_descriptor,
                relative_name=capability.candidate_name,
                expected=capability.existing_destination_snapshot,
                expected_tree=capability.existing_destination_tree_snapshot,
                error_message="Published staging old destination cleanup failed",
            )
            quarantine = f".lcf-old-{secrets.token_hex(16)}"
            _rename_noreplace_at(
                capability.candidate_parent_descriptor,
                capability.candidate_name,
                capability.candidate_parent_descriptor,
                quarantine,
            )
            quarantined = os.stat(
                quarantine,
                dir_fd=capability.candidate_parent_descriptor,
                follow_symlinks=False,
            )
            held = os.fstat(capability.existing_destination_descriptor)
            if (
                _stable_directory_identity(quarantined)
                != _stable_directory_identity(held)
            ):
                try:
                    _rename_noreplace_at(
                        capability.candidate_parent_descriptor,
                        quarantine,
                        capability.candidate_parent_descriptor,
                        capability.candidate_name,
                    )
                except BaseException as restore_error:
                    raise _CleanupBlockedError(
                        "Published staging old destination cleanup failed"
                    ) from restore_error
                raise _CleanupBlockedError(
                    "Published staging old destination cleanup failed"
                )
            _remove_tree_contents(
                capability.existing_destination_descriptor,
                error_message="Published staging old destination cleanup failed",
            )
            if os.listdir(capability.existing_destination_descriptor):
                raise BuildError("Published staging old destination cleanup failed")
            relative = os.stat(
                quarantine,
                dir_fd=capability.candidate_parent_descriptor,
                follow_symlinks=False,
            )
            held = os.fstat(capability.existing_destination_descriptor)
            if _stable_directory_identity(relative) != _stable_directory_identity(held):
                raise BuildError("Published staging old destination cleanup failed")
            os.rmdir(
                quarantine,
                dir_fd=capability.candidate_parent_descriptor,
            )
            try:
                os.stat(
                    capability.candidate_name,
                    dir_fd=capability.candidate_parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                raise _CleanupBlockedError(
                    "Published staging old destination cleanup failed"
                )
        except BaseException as cleanup_error:
            old_cleanup_error = cleanup_error

    if primary_error is None and ownership_transfer is not None:
        # Every fallible revalidation ran in ownership prepare while the
        # previous destination was still rollback-capable.  Commit performs
        # only Python state transfers and returns descriptors for best-effort
        # close after the namespace and scratch owner are already stable.
        ownership_descriptors = ownership_transfer.apply(capability)
        ownership_committed = True

    close_error: BaseException | None = None
    try:
        _close_publish_capability(capability)
    except BaseException as exc:
        close_error = exc
    for descriptor in ownership_descriptors:
        try:
            os.close(descriptor)
        except OSError as exc:
            close_error = close_error or exc
    if close_error is not None:
        _finish_publish_signal_deferral(
            transaction_signals,
            primary_error or old_cleanup_error or close_error,
        )
        if primary_error is not None:
            raise BuildError(
                "Published staging failed and capability cleanup failed"
            ) from close_error
        if old_cleanup_error is not None:
            if ownership_committed:
                raise BuildError(
                    "Published staging old destination cleanup failed"
                ) from old_cleanup_error
            raise _CleanupBlockedError(
                "Published staging old destination cleanup failed"
            ) from old_cleanup_error
        raise BuildError("Published staging capability cleanup failed") from close_error
    _finish_publish_signal_deferral(
        transaction_signals,
        primary_error or old_cleanup_error,
    )
    if old_cleanup_error is not None:
        if ownership_committed:
            raise BuildError(
                "Published staging old destination cleanup failed"
            ) from old_cleanup_error
        raise _CleanupBlockedError(
            "Published staging old destination cleanup failed"
        ) from old_cleanup_error
    if primary_error is not None:
        if cleanup_blocked:
            raise _CleanupBlockedError(
                "Atomic staging capability drifted during verification"
            ) from primary_error
        if isinstance(primary_error, (KeyboardInterrupt, SystemExit)):
            raise primary_error
        if swapped:
            raise BuildError("Published staging failed its post-swap audit") from primary_error
        raise BuildError("Atomic staging candidate failed verification") from primary_error


def publish_staging(
    candidate: Path,
    destination: Path,
    *,
    verifier: Callable[[Path], Any],
    held_candidate: _EvidenceCapability | _BundleCapability | None = None,
    ownership_transfer: _PublishOwnershipTransfer | None = None,
) -> None:
    """Publish with scoped process-signal translation around the transaction."""

    with _translate_cleanup_signals():
        _publish_staging_impl(
            candidate,
            destination,
            verifier=verifier,
            held_candidate=held_candidate,
            ownership_transfer=ownership_transfer,
        )


def _prepare_published_bundle_ownership(
    scratch: _ScratchCapability,
    bundle: _BundleCapability,
    publish: _PublishCapability,
) -> _DirectorySnapshot:
    """Prove the complete bundle handoff while publication can roll back."""

    error_message = "Published Python sidecar bundle capability changed"
    if scratch.bundle is not bundle or bundle.closed or scratch.poisoned:
        raise _CleanupBlockedError(error_message)
    _validate_source_snapshot(scratch)
    moved = _capture_bound_directory(
        bundle.descriptor,
        publish.destination,
        parent_descriptor=publish.destination_parent_descriptor,
        relative_name=publish.destination_name,
        expected=bundle.snapshot,
        expected_mode=None,
        exact_entries=bundle.snapshot.entries,
        error_message=error_message,
    )
    if (
        _stable_directory_identity(moved)
        != _stable_directory_identity(bundle.snapshot)
        or _tree_metadata_snapshot(
            bundle.descriptor,
            error_message=error_message,
        )
        != bundle.tree_snapshot
    ):
        raise _CapabilityDriftError(error_message)
    destination_snapshot = _capture_bound_directory(
        scratch.destination_parent_descriptor,
        scratch.destination_parent,
        parent_descriptor=None,
        relative_name=None,
        expected=scratch.destination_parent_snapshot,
        expected_mode=None,
        exact_entries=publish.destination_parent_snapshot.entries,
        error_message=error_message,
    )
    if (
        _stable_directory_identity(destination_snapshot)
        != _stable_directory_identity(publish.destination_parent_snapshot)
    ):
        raise _CapabilityDriftError(error_message)

    return destination_snapshot


def _prepare_published_evidence_ownership(
    scratch: _ScratchCapability,
    evidence: _EvidenceCapability,
    publish: _PublishCapability,
) -> tuple[_DirectorySnapshot, _DirectorySnapshot]:
    """Prove evidence/source/scratch handoff before previous cleanup."""

    error_message = "Published PyInstaller evidence capability changed"
    if scratch.evidence is not evidence or evidence.closed or scratch.poisoned:
        raise _CleanupBlockedError(error_message)
    moved = _capture_bound_directory(
        evidence.descriptor,
        publish.destination,
        parent_descriptor=publish.destination_parent_descriptor,
        relative_name=publish.destination_name,
        expected=evidence.snapshot,
        expected_mode=0o700,
        exact_entries=evidence.snapshot.entries,
        error_message=error_message,
    )
    if (
        _stable_directory_identity(moved)
        != _stable_directory_identity(evidence.snapshot)
        or _tree_metadata_snapshot(
            evidence.descriptor,
            error_message=error_message,
        )
        != evidence.tree_snapshot
    ):
        raise _CapabilityDriftError(error_message)
    _read_held_evidence_tree(
        evidence,
        expected_tree=evidence.tree_snapshot,
        expected_content=evidence.content_snapshot,
        error_message=error_message,
    )
    destination_snapshot = _capture_bound_directory(
        scratch.destination_parent_descriptor,
        scratch.destination_parent,
        parent_descriptor=None,
        relative_name=None,
        expected=scratch.destination_parent_snapshot,
        expected_mode=None,
        exact_entries=publish.destination_parent_snapshot.entries,
        error_message=error_message,
    )
    build_root_snapshot = _capture_bound_directory(
        scratch.build_root_descriptor,
        scratch.build_root,
        parent_descriptor=scratch.scratch_parent_descriptor,
        relative_name=scratch.build_root_name,
        expected=scratch.build_root_snapshot,
        expected_mode=0o700,
        exact_entries=publish.candidate_parent_snapshot.entries,
        error_message=error_message,
    )
    _validate_source_snapshot(scratch)

    return destination_snapshot, build_root_snapshot


def _bundle_publish_ownership_transfer(
    scratch: _ScratchCapability,
    bundle: _BundleCapability,
) -> _PublishOwnershipTransfer:
    """Create rollback ownership before any bundle namespace mutation."""

    prepared_destination = scratch.destination_parent_snapshot
    prepared_retained_directories = scratch.retained_published_directories
    retained_previous: _RetainedPublishedDirectory | None = None
    close_bundle_only = (bundle.descriptor,)
    close_bundle_and_parent = (bundle.descriptor, bundle.parent_descriptor)
    prepared = False

    def prepare(publish: _PublishCapability) -> None:
        nonlocal prepared, prepared_destination, retained_previous
        nonlocal prepared_retained_directories
        prepared_destination = _prepare_published_bundle_ownership(
            scratch,
            bundle,
            publish,
        )
        if publish.existing_destination_descriptor is not None:
            if (
                publish.existing_destination_snapshot is None
                or publish.existing_destination_tree_snapshot is None
            ):
                raise _CleanupBlockedError(
                    "Published Python sidecar bundle capability changed"
                )
            retained_previous = _RetainedPublishedDirectory(
                parent_path=bundle.parent_path,
                name=bundle.name,
                parent_descriptor=bundle.parent_descriptor,
                descriptor=publish.existing_destination_descriptor,
                snapshot=publish.existing_destination_snapshot,
                tree_snapshot=publish.existing_destination_tree_snapshot,
                owns_parent_descriptor=True,
            )
            prepared_retained_directories = [
                *scratch.retained_published_directories,
                retained_previous,
            ]
        prepared = True

    def commit(_publish: _PublishCapability) -> None:
        if not prepared:
            raise AssertionError("bundle ownership commit was not prepared")

    def apply(publish: _PublishCapability) -> tuple[int, ...]:
        scratch.destination_parent_snapshot = prepared_destination
        scratch.retained_published_directories = prepared_retained_directories
        if retained_previous is not None:
            publish.existing_destination_descriptor = None
        bundle.closed = True
        scratch.bundle = None
        if retained_previous is not None:
            return close_bundle_only
        return close_bundle_and_parent

    def rollback(publish: _PublishCapability) -> None:
        scratch.destination_parent_snapshot = publish.destination_parent_snapshot
        bundle.parent_snapshot = publish.candidate_parent_snapshot
        bundle.snapshot = publish.candidate_snapshot

    return _PublishOwnershipTransfer(
        prepare=prepare,
        commit=commit,
        apply=apply,
        rollback=rollback,
        retain_previous_in_scratch=True,
    )


def _evidence_publish_ownership_transfer(
    scratch: _ScratchCapability,
    evidence: _EvidenceCapability,
) -> _PublishOwnershipTransfer:
    """Create rollback ownership before any evidence namespace mutation."""

    prepared_destination = scratch.destination_parent_snapshot
    prepared_build_root = scratch.build_root_snapshot
    prepared_retained_directories = scratch.retained_published_directories
    retained_previous: _RetainedPublishedDirectory | None = None
    close_evidence = (evidence.descriptor,)
    prepared = False

    def prepare(publish: _PublishCapability) -> None:
        nonlocal prepared, prepared_destination, prepared_build_root
        nonlocal prepared_retained_directories, retained_previous
        prepared_destination, prepared_build_root = (
            _prepare_published_evidence_ownership(
                scratch,
                evidence,
                publish,
            )
        )
        if publish.existing_destination_descriptor is not None:
            if (
                publish.existing_destination_snapshot is None
                or publish.existing_destination_tree_snapshot is None
            ):
                raise _CleanupBlockedError(
                    "Published PyInstaller evidence capability changed"
                )
            retained_previous = _RetainedPublishedDirectory(
                parent_path=scratch.build_root,
                name=evidence.name,
                parent_descriptor=scratch.build_root_descriptor,
                descriptor=publish.existing_destination_descriptor,
                snapshot=publish.existing_destination_snapshot,
                tree_snapshot=publish.existing_destination_tree_snapshot,
                owns_parent_descriptor=False,
            )
            prepared_retained_directories = [
                *scratch.retained_published_directories,
                retained_previous,
            ]
        prepared = True

    def commit(_publish: _PublishCapability) -> None:
        if not prepared:
            raise AssertionError("evidence ownership commit was not prepared")

    def apply(publish: _PublishCapability) -> tuple[int, ...]:
        scratch.destination_parent_snapshot = prepared_destination
        scratch.build_root_snapshot = prepared_build_root
        scratch.retained_published_directories = prepared_retained_directories
        if retained_previous is not None:
            publish.existing_destination_descriptor = None
        evidence.closed = True
        scratch.evidence = None
        return close_evidence

    def rollback(publish: _PublishCapability) -> None:
        scratch.destination_parent_snapshot = publish.destination_parent_snapshot
        scratch.build_root_snapshot = publish.candidate_parent_snapshot
        evidence.snapshot = publish.candidate_snapshot

    return _PublishOwnershipTransfer(
        prepare=prepare,
        commit=commit,
        apply=apply,
        rollback=rollback,
        retain_previous_in_scratch=True,
    )


def _publish_owned_bundle(
    scratch: _ScratchCapability,
    bundle: _BundleCapability,
    destination: Path,
    *,
    verifier: Callable[[Path], Any],
) -> None:
    """Commit publication and its two ownership transfers as one signal unit."""

    if scratch.bundle is not bundle:
        scratch.poisoned = True
        raise _CleanupBlockedError(
            "Published Python sidecar bundle capability is unavailable"
        )
    with _defer_publish_signals():
        ownership_transfer = _bundle_publish_ownership_transfer(scratch, bundle)
        publish_staging(
            bundle.path,
            destination,
            verifier=verifier,
            held_candidate=bundle,
            ownership_transfer=ownership_transfer,
        )


def _publish_owned_evidence(
    scratch: _ScratchCapability,
    evidence: _EvidenceCapability,
    destination: Path,
    *,
    verifier: Callable[[Path], Any],
) -> None:
    """Publish evidence and transfer its held ownership without signal gaps."""

    if scratch.evidence is not evidence or evidence.closed:
        scratch.poisoned = True
        raise _CleanupBlockedError(
            "Sanitized PyInstaller evidence capability is unavailable"
        )
    try:
        with _defer_publish_signals():
            ownership_transfer = _evidence_publish_ownership_transfer(
                scratch,
                evidence,
            )
            publish_staging(
                evidence.path,
                destination,
                verifier=verifier,
                held_candidate=evidence,
                ownership_transfer=ownership_transfer,
            )
    except _DeferredSignalError:
        raise
    except BaseException as exc:
        if isinstance(exc, _CleanupBlockedError):
            scratch.poisoned = True
            raise _CleanupBlockedError(
                "Published PyInstaller evidence capability changed"
            ) from exc
        # A verifier/prepare failure that reaches here was rolled back by the
        # publish transaction while it still held both namespace bindings.
        # The original evidence capability therefore remains the exact owner
        # and the outer scratch lifecycle can remove it normally.
        if isinstance(exc, (BuildError, KeyboardInterrupt, SystemExit)):
            raise
        raise BuildError("Published PyInstaller evidence failed") from exc


def _preserve_evidence(
    evidence: Path | _EvidenceCapability,
    destination: Path,
    *,
    scratch: _ScratchCapability | None = None,
) -> None:
    held_evidence: _EvidenceCapability | None = None
    if isinstance(evidence, _EvidenceCapability):
        if scratch is None or scratch.evidence is not evidence:
            if scratch is not None:
                scratch.poisoned = True
            raise _CleanupBlockedError(
                "Sanitized PyInstaller evidence capability is unavailable"
            )
        held_evidence = _revalidate_failure_evidence_capability(
            scratch,
            error_message="Sanitized PyInstaller evidence capability changed",
        )
        candidate_path = held_evidence.path
    else:
        candidate_path = evidence
        if not candidate_path.is_dir() or candidate_path.is_symlink():
            return

    def verify(candidate: Path) -> None:
        if scratch is not None:
            _validate_source_snapshot(scratch)
        if held_evidence is not None:
            files, _content = _read_held_evidence_tree(
                held_evidence,
                expected_tree=held_evidence.tree_snapshot,
                expected_content=held_evidence.content_snapshot,
                error_message="Sanitized PyInstaller evidence is unsafe",
            )
            names = sorted(PurePosixPath(name).name for name in files)
            if (
                names.count("pyinstaller.log") != 1
                or len(
                    [
                        name
                        for name in names
                        if name.startswith("warn-") and name.endswith(".txt")
                    ]
                )
                > 1
            ):
                raise BuildError("Sanitized PyInstaller evidence is incomplete")
            for payload in files.values():
                try:
                    text = payload.decode("utf-8", errors="strict")
                except UnicodeDecodeError as exc:
                    raise BuildError(
                        "Sanitized PyInstaller evidence is not UTF-8"
                    ) from exc
                if re.search(
                    r"/(?:Users/[^/\s]+|private|var/folders|workspace|tmp)/",
                    text,
                ):
                    raise BuildError(
                        "Sanitized PyInstaller evidence contains a private path"
                    )
            if scratch is not None:
                _validate_source_snapshot(scratch)
            return
        files: list[Path] = []
        directories = 0
        total_size = 0
        for path in sorted(candidate.rglob("*"), key=lambda item: item.as_posix()):
            try:
                info = path.lstat()
            except OSError as exc:
                raise BuildError("Sanitized PyInstaller evidence is unsafe") from exc
            if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
                directories += 1
                if directories > 16 or stat.S_IMODE(info.st_mode) & 0o022:
                    raise BuildError("Sanitized PyInstaller evidence is unsafe")
                continue
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or info.st_nlink != 1
                or info.st_size <= 0
                or info.st_size > 16 * 1024 * 1024
                or stat.S_IMODE(info.st_mode) & 0o022
            ):
                raise BuildError("Sanitized PyInstaller evidence is unsafe")
            files.append(path)
            total_size += info.st_size
        if not 1 <= len(files) <= 2 or total_size > 24 * 1024 * 1024:
            raise BuildError("Sanitized PyInstaller evidence is incomplete")
        names = sorted(path.name for path in files)
        if (
            names.count("pyinstaller.log") != 1
            or len([name for name in names if name.startswith("warn-") and name.endswith(".txt")])
            > 1
        ):
            raise BuildError("Sanitized PyInstaller evidence is incomplete")
        for path in files:
            descriptor: int | None = None
            try:
                descriptor = os.open(
                    path,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                )
                before = os.fstat(descriptor)
                path_before = path.lstat()
                if _stat_metadata(before) != _stat_metadata(path_before):
                    raise BuildError("Sanitized PyInstaller evidence is unsafe")
                chunks: list[bytes] = []
                remaining = before.st_size
                while remaining:
                    chunk = os.read(descriptor, min(1024 * 1024, remaining))
                    if not chunk:
                        raise BuildError("Sanitized PyInstaller evidence is unsafe")
                    chunks.append(chunk)
                    remaining -= len(chunk)
                if os.read(descriptor, 1):
                    raise BuildError("Sanitized PyInstaller evidence is unsafe")
                after = os.fstat(descriptor)
                path_after = path.lstat()
                if (
                    _stat_metadata(after) != _stat_metadata(before)
                    or _stat_metadata(path_after) != _stat_metadata(before)
                ):
                    raise BuildError("Sanitized PyInstaller evidence is unsafe")
                text = b"".join(chunks).decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise BuildError("Sanitized PyInstaller evidence is not UTF-8") from exc
            except BuildError:
                raise
            except OSError as exc:
                raise BuildError("Sanitized PyInstaller evidence is unsafe") from exc
            finally:
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError as exc:
                        raise BuildError("Sanitized PyInstaller evidence cleanup failed") from exc
            if re.search(
                r"/(?:Users/[^/\s]+|private|var/folders|workspace|tmp)/",
                text,
            ):
                raise BuildError("Sanitized PyInstaller evidence contains a private path")
        if scratch is not None:
            _validate_source_snapshot(scratch)

    if scratch is None or held_evidence is None:
        publish_staging(
            candidate_path,
            destination,
            verifier=verify,
            held_candidate=held_evidence,
        )
        return
    _publish_owned_evidence(
        scratch,
        held_evidence,
        destination,
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
    toolchain_evidence: Mapping[str, Any],
    source_root: Path,
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
            "pythonToolchain": {
                name: toolchain_evidence[name]
                for name in (
                    "buildRequirementsLockSha256",
                    "runtimeLockSha256",
                    "runtimeRequirementsSha256",
                    "installedTreeContentSha256",
                    "buildTools",
                )
            },
            "inputDigests": audit.critical_input_digests(source_root),
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


def _build_python_sidecar_impl(
    *,
    destination: Path,
    evidence_destination: Path,
    environment: Mapping[str, str],
) -> dict[str, int]:
    try:
        import audit_python_sidecar as audit
    except ImportError as exc:
        raise BuildError("Python sidecar auditor cannot be imported") from exc

    if destination != DEFAULT_STAGING or evidence_destination != DEFAULT_EVIDENCE:
        raise BuildError("Python sidecar output paths differ from the fixed contract")
    output_parent = _ensure_fixed_output_parent()
    if destination.parent != output_parent or evidence_destination.parent != output_parent:
        raise BuildError("Python sidecar output parent is unsafe")
    for candidate in (destination, evidence_destination):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise BuildError("Python sidecar output endpoint is unsafe") from exc
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise BuildError("Python sidecar output endpoint is unsafe")

    toolchain_evidence, toolchain_evidence_payload = (
        _verify_exact_toolchain_environment(environment)
    )

    def verify_exact_toolchain() -> None:
        observed, payload = _verify_exact_toolchain_environment(environment)
        if observed != toolchain_evidence or payload != toolchain_evidence_payload:
            raise BuildError("Installed Python toolchain evidence changed")

    scratch: _ScratchCapability | None = None
    evidence: _EvidenceCapability | None = None
    primary_error: BaseException | None = None
    summary: dict[str, int] | None = None
    try:
        # The lifecycle owner must cover the callee RETURN_VALUE -> caller
        # STORE_FAST window.  If the transaction reports a pending signal
        # after the assignment, this same try still owns exact cleanup.
        with _defer_publish_signals():
            scratch = _create_private_build_root(output_parent)
        repository_state = _validate_repository_state(environment)
        _materialize_source_snapshot(scratch, repository_state)
        _validate_source_snapshot(scratch)
        source_root = scratch.source_snapshot
        if source_root is None:  # pragma: no cover - validated immediately above
            raise BuildError("Exact Git source capability path is unavailable")
        toolchain = _load_json(
            source_root
            / "backend"
            / "packaging"
            / "python-sidecar-toolchain.lock.json",
            "Python toolchain lock",
        )
        release = validate_release_environment(environment, toolchain)
        if (
            release.get("repositoryCommit")
            != repository_state.get("repositoryCommit")
            or release.get("repositoryTree")
            != repository_state.get("repositoryTree")
            or release.get("sourceSnapshotSha256")
            != repository_state.get("sourceSnapshotSha256")
        ):
            raise BuildError("Repository provenance changed before snapshot use")
        _validate_source_snapshot(scratch)
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
        packaging_root = source_root / "backend" / "packaging"
        build_versions = parse_build_requirements(
            packaging_root / "build-requirements.lock"
        )
        _validate_toolchain_evidence_against_source(
            toolchain_evidence,
            build_versions=build_versions,
            packaging_root=packaging_root,
            backend_root=source_root / "backend",
        )
        verify_exact_toolchain()
        verify_build_tool_versions(toolchain, build_versions)
        uv_cache = scratch.build_root / UV_CACHE_NAME
        uv_cache_descriptor, uv_cache_snapshot = _create_bound_child_directory(
            parent_descriptor=scratch.build_root_descriptor,
            parent_path=scratch.build_root,
            name=UV_CACHE_NAME,
            mode=0o700,
            error_message="uv cache capability is unsafe",
        )
        uv_executable = Path(sys.executable).parent / "uv"
        try:
            verify_uv_lock(
                uv_executable,
                backend_root=source_root / "backend",
                cache_directory=uv_cache,
                cache_parent_descriptor=scratch.build_root_descriptor,
                cache_descriptor=uv_cache_descriptor,
                cache_snapshot=uv_cache_snapshot,
                source_descriptor=scratch.source_snapshot_descriptor,
            )
        finally:
            active_error = sys.exception()
            try:
                os.close(uv_cache_descriptor)
            except OSError as exc:
                scratch.poisoned = True
                if active_error is None:
                    raise _CleanupBlockedError(
                        "uv cache capability cleanup failed"
                    ) from exc
        runtime_versions = runtime_dependency_versions(
            source_root / "backend" / "uv.lock"
        )
        verify_exact_toolchain()
        verify_runtime_dependencies(runtime_versions)
        versions = _load_json(
            source_root / "runtime" / "version.json",
            "Canonical runtime versions",
        )
        _validate_source_snapshot(scratch)
        verify_repository_provenance(release)
        verify_exact_toolchain()
        bundle_capability, evidence = run_pyinstaller(
            scratch=scratch,
            install_root=install_root,
            source_date_epoch=int(release["sourceDateEpoch"]),
            deployment_target=str(release["macosDeploymentTarget"]),
            source_root=source_root,
        )
        verify_exact_toolchain()
        _validate_source_snapshot(scratch)
        verify_repository_provenance(release)
        _validate_bundle_capability(scratch)
        canonical_bundle = bundle_capability.path
        frozen_smoke = run_frozen_smoke(
            canonical_bundle,
            versions,
            source_date_epoch=int(release["sourceDateEpoch"]),
            bundle_descriptor=bundle_capability.descriptor,
        )
        _validate_bundle_capability(
            scratch,
            error_message="Python sidecar bundle changed during frozen smoke",
        )
        _validate_bundle_capability(scratch)
        bundle = bundle_capability.path
        components = build_components(
            bundle=bundle,
            runtime_versions=runtime_versions,
            build_versions=build_versions,
            source_root=source_root,
        )
        _validate_bundle_capability(
            scratch,
            accept_tree_changes=True,
            error_message="Python sidecar bundle changed during component assembly",
        )
        bundle = bundle_capability.path
        artifacts = write_compliance_artifacts(
            bundle=bundle,
            components=components,
            repository_commit=str(release["repositoryCommit"]),
            source_date_epoch=int(release["sourceDateEpoch"]),
        )
        artifacts["pythonBuildToolchain"] = _write_toolchain_evidence_artifact(
            bundle,
            toolchain_evidence_payload,
        )
        _validate_bundle_capability(
            scratch,
            accept_tree_changes=True,
            error_message="Python sidecar bundle changed during compliance assembly",
        )
        bundle = bundle_capability.path
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
        _validate_source_snapshot(scratch)
        _validate_bundle_capability(scratch)
        bundle = bundle_capability.path
        normalize_tree(bundle, int(release["sourceDateEpoch"]))
        _validate_bundle_capability(
            scratch,
            accept_tree_changes=True,
            error_message="Python sidecar bundle changed during normalization",
        )
        bundle = bundle_capability.path
        canonical_bundle = bundle_capability.path
        manifest = _build_manifest(
            bundle=canonical_bundle,
            versions=versions,
            toolchain=toolchain,
            release=release,
            python_provenance=python_provenance,
            python_fingerprint=python_fingerprint,
            components=components,
            artifacts=artifacts,
            frozen_smoke=frozen_smoke,
            toolchain_evidence=toolchain_evidence,
            source_root=source_root,
        )
        _validate_bundle_capability(
            scratch,
            error_message="Python sidecar bundle changed during manifest assembly",
        )
        bundle = bundle_capability.path
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
        _validate_bundle_capability(
            scratch,
            accept_tree_changes=True,
            error_message="Python sidecar bundle changed during manifest sealing",
        )
        bundle = bundle_capability.path

        def final_verifier(candidate: Path) -> dict[str, int]:
            verify_exact_toolchain()
            verify_repository_provenance(release)
            _validate_source_snapshot(scratch)
            _verify_held_bundle_candidate(
                bundle_capability,
                candidate,
                error_message="Python sidecar bundle changed during final audit",
            )
            result = audit.audit_bundle(
                candidate,
                repository_root=source_root,
                verify_git_provenance=False,
            )
            _verify_held_bundle_candidate(
                bundle_capability,
                candidate,
                error_message="Python sidecar bundle changed during final audit",
            )
            verify_exact_toolchain()
            return result

        summary = final_verifier(bundle)
        verify_exact_toolchain()
        _publish_owned_bundle(
            scratch,
            bundle_capability,
            destination,
            verifier=final_verifier,
        )
        verify_exact_toolchain()
    except BaseException as exc:
        primary_error = exc
        if scratch is None:
            pass
        elif isinstance(exc, _CleanupBlockedError):
            scratch.poisoned = True
        if scratch is not None and evidence is None:
            evidence = scratch.evidence
        if (
            scratch is not None
            and
            evidence is not None
            and not scratch.poisoned
            and not isinstance(exc, (KeyboardInterrupt, SystemExit))
        ):
            try:
                _preserve_evidence(
                    evidence,
                    evidence_destination,
                    scratch=scratch,
                )
            except BaseException as preservation_error:
                if isinstance(preservation_error, _CleanupBlockedError):
                    scratch.poisoned = True
                combined_error = BuildError(
                    "Python sidecar build failed and evidence preservation failed"
                )
                combined_error.__cause__ = primary_error
                primary_error = combined_error
    if scratch is not None:
        with _defer_publish_signals(preserve_error=primary_error):
            _finish_scratch_lifecycle(scratch, primary_error)
    if primary_error is not None:
        if isinstance(primary_error, BuildError):
            raise primary_error
        if isinstance(primary_error, (KeyboardInterrupt, SystemExit)):
            raise primary_error
        raise BuildError("Python sidecar build failed") from primary_error
    if summary is None:
        raise BuildError("Python sidecar build produced no audit summary")
    return summary


def build_python_sidecar(
    *,
    destination: Path,
    evidence_destination: Path,
    environment: Mapping[str, str],
) -> dict[str, int]:
    """Run the complete scratch-owned lifecycle with cancellable translation."""

    with _translate_cleanup_signals():
        return _build_python_sidecar_impl(
            destination=destination,
            evidence_destination=evidence_destination,
            environment=environment,
        )


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
        default=None,
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
                if arguments.installer_output is None:
                    raise BuildError(
                        "installer extraction requires --installer-output"
                    )
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

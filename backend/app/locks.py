from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO


class LockUnavailable(RuntimeError):
    """Raised when another process owns a requested library lock."""


def _lock_file(handle: BinaryIO) -> bool:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _unlock_file(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def lock_path(locks_dir: Path, library_id: str, operation: str) -> Path:
    digest = hashlib.sha256(library_id.encode("utf-8")).hexdigest()[:32]
    return locks_dir / f"{digest}.{operation}.lock"


@contextmanager
def filesystem_lock(
    path: Path,
    *,
    blocking: bool,
    timeout_seconds: float = 60.0,
) -> Iterator[None]:
    """Take an advisory lock shared by every API process on the same host.

    The lock file contains no data and is intentionally retained after release.
    A hash-derived filename prevents restored or malformed database identifiers
    from becoming filesystem paths.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise LockUnavailable(f"Refusing symlink lock path: {path}")
    with path.open("a+b") as handle:
        # Windows byte-range locking needs at least one byte in the file.
        if os.name == "nt" and path.stat().st_size == 0:
            handle.write(b"\0")
            handle.flush()
            handle.seek(0)
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while not _lock_file(handle):
            if not blocking or time.monotonic() >= deadline:
                raise LockUnavailable(f"Lock is already held: {path.name}")
            time.sleep(0.05)
        try:
            yield
        finally:
            _unlock_file(handle)

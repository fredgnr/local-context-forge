from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from .locks import LockUnavailable, filesystem_lock, lock_path

if TYPE_CHECKING:
    from .service import AppService


class PersistentJobDispatcher:
    """Single-consumer FIFO dispatcher backed entirely by SQLite rows."""

    def __init__(self, service: AppService):
        self.service = service
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._active = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def active(self) -> bool:
        return self._active.is_set()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="local-context-forge-worker",
            daemon=True,
        )
        self._thread.start()

    def notify(self) -> None:
        self._wake.set()

    def stop(self) -> bool:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread:
            thread.join(self.service.settings.worker_shutdown_grace_seconds)
        stopped = not bool(thread and thread.is_alive())
        if stopped:
            self._thread = None
        return stopped

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with filesystem_lock(
                    lock_path(
                        self.service.settings.locks_dir,
                        "__jobs__",
                        "worker",
                    ),
                    blocking=False,
                ):
                    self._active.set()
                    try:
                        while not self._stop.is_set():
                            if self.service.dispatch_next_job():
                                continue
                            self._wake.wait(
                                self.service.settings.worker_poll_seconds
                            )
                            self._wake.clear()
                    finally:
                        self._active.clear()
            except LockUnavailable:
                # Stay alive as a hot standby. If the current worker process
                # exits, this API process takes the global lock without a
                # restart and continues the durable queue.
                self._wake.wait(self.service.settings.worker_poll_seconds)
                self._wake.clear()

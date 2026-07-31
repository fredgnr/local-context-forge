"""Authenticated HTTP-over-UDS boundary for the desktop sidecar."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import select
import socket
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .version import DESKTOP_PROTOCOL_VERSION


# Darwin's sockaddr_un.sun_path is small (104 bytes including termination).
# Keeping several bytes of margin avoids relying on platform-specific edge
# behavior and makes the same validation deterministic on development hosts.
MAX_UDS_PATH_BYTES = 100
MAX_STARTUP_TOKEN_BYTES = 43
MAX_DESKTOP_REQUEST_BODY_BYTES = 262_144
MAX_DESKTOP_DEADLINE_MS = 120_000

_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}\Z"
)
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class DesktopTransportError(ValueError):
    """A fail-closed desktop transport validation error."""


class _RequestRejected(Exception):
    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.detail = detail


class _ResponseDeadlineExpired(Exception):
    pass


_BACKGROUND_APPLICATION_TASKS: set[asyncio.Task[None]] = set()


def _consume_background_task(task: asyncio.Task[None]) -> None:
    _BACKGROUND_APPLICATION_TASKS.discard(task)
    try:
        task.exception()
    except asyncio.CancelledError:
        pass
    except Exception:
        # The HTTP response is already closed. Never surface a late stack or
        # let a detached task produce "exception was never retrieved" output.
        pass


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise DesktopTransportError(
            "Desktop transport path could not be inspected"
        ) from error


def validate_runtime_directory(path: str | os.PathLike[str]) -> Path:
    """Validate the private directory that directly owns a sidecar socket."""

    runtime_directory = Path(path)
    if not runtime_directory.is_absolute() or ".." in runtime_directory.parts:
        raise DesktopTransportError(
            "Desktop runtime directory must be an absolute canonical path"
        )

    metadata = _lstat(runtime_directory)
    if metadata is None or not stat.S_ISDIR(metadata.st_mode):
        raise DesktopTransportError(
            "Desktop runtime directory must be a real directory"
        )
    if stat.S_ISLNK(metadata.st_mode):
        raise DesktopTransportError(
            "Desktop runtime directory must not be a symbolic link"
        )
    if metadata.st_uid != os.geteuid():
        raise DesktopTransportError(
            "Desktop runtime directory has an unexpected owner"
        )
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise DesktopTransportError(
            "Desktop runtime directory must have mode 0700"
        )
    return runtime_directory


def validate_runtime_parent(path: str | os.PathLike[str]) -> Path:
    """Compatibility name for callers that describe the directory as parent."""

    return validate_runtime_directory(path)


def validate_socket_path(path: str | os.PathLike[str]) -> Path:
    """Validate a not-yet-created UDS path without deleting stale entries."""

    socket_path = Path(path)
    if (
        not socket_path.is_absolute()
        or ".." in socket_path.parts
        or socket_path.name in {"", ".", ".."}
    ):
        raise DesktopTransportError(
            "Desktop socket path must be an absolute canonical path"
        )
    try:
        encoded_path = str(socket_path).encode("utf-8")
    except UnicodeEncodeError as error:
        raise DesktopTransportError(
            "Desktop socket path must be valid UTF-8"
        ) from error
    if b"\0" in encoded_path or len(encoded_path) > MAX_UDS_PATH_BYTES:
        raise DesktopTransportError("Desktop socket path is too long")

    validate_runtime_directory(socket_path.parent)
    if _lstat(socket_path) is not None:
        raise DesktopTransportError("Desktop socket path already exists")
    return socket_path


def read_token_fd(
    fd: int,
    *,
    max_bytes: int = MAX_STARTUP_TOKEN_BYTES,
) -> str:
    """Read one newline-framed token while retaining the FD for liveness."""

    if not isinstance(fd, int) or fd < 0:
        raise DesktopTransportError("Startup token descriptor is invalid")
    if max_bytes < 1:
        raise DesktopTransportError("Startup token bound is invalid")

    payload = bytearray()
    try:
        while True:
            try:
                chunk = os.read(fd, 1)
            except InterruptedError:
                continue
            except OSError as error:
                raise DesktopTransportError(
                    "Startup token could not be read"
                ) from error
            if not chunk:
                raise DesktopTransportError(
                    "Startup token frame was not completed"
                )
            if chunk == b"\n":
                break
            payload.extend(chunk)
            if len(payload) > max_bytes:
                raise DesktopTransportError("Startup token is invalid")
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise

    try:
        token = bytes(payload).decode("ascii")
    except UnicodeDecodeError as error:
        os.close(fd)
        raise DesktopTransportError("Startup token is invalid") from error
    if not _TOKEN_PATTERN.fullmatch(token):
        os.close(fd)
        raise DesktopTransportError("Startup token is invalid")
    return token


def read_startup_token(
    fd: int,
    *,
    max_bytes: int = MAX_STARTUP_TOKEN_BYTES,
) -> str:
    """Descriptive alias used by the CLI launch path."""

    return read_token_fd(fd, max_bytes=max_bytes)


class ParentLivenessWatcher:
    """Set the sidecar exit signal when Main closes its fd3 write end."""

    def __init__(
        self,
        fd: int,
        on_disconnect: Callable[[], None],
    ) -> None:
        self._fd = fd
        self._on_disconnect = on_disconnect
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._watch,
            name="lcf-parent-liveness",
            daemon=True,
        )
        self._started = False

    def start(self) -> None:
        if self._started:
            raise RuntimeError("Parent liveness watcher already started")
        self._started = True
        self._thread.start()

    def _watch(self) -> None:
        while not self._stop.is_set():
            try:
                readable, _, _ = select.select([self._fd], [], [], 0.1)
            except (OSError, ValueError):
                if not self._stop.is_set():
                    self._on_disconnect()
                return
            if not readable:
                continue
            try:
                _control_data = os.read(self._fd, 1024)
            except InterruptedError:
                continue
            except OSError:
                if not self._stop.is_set():
                    self._on_disconnect()
                return
            # The post-token channel carries liveness only. EOF means Main
            # exited; any unexpected bytes fail closed as a protocol error.
            self._on_disconnect()
            return

    def close(self) -> None:
        self._stop.set()
        if self._started:
            self._thread.join(timeout=1)
        try:
            os.close(self._fd)
        except OSError:
            pass


def _unlink_owned_socket(path: Path, device: int, inode: int) -> None:
    metadata = _lstat(path)
    if metadata is None:
        return
    if (
        metadata.st_dev != device
        or metadata.st_ino != inode
        or not stat.S_ISSOCK(metadata.st_mode)
    ):
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        raise DesktopTransportError(
            "Desktop socket could not be cleaned up"
        ) from error


@contextmanager
def prebound_unix_socket(
    path: str | os.PathLike[str],
) -> Iterator[socket.socket]:
    """Bind a private UDS before uvicorn starts and clean up only that inode."""

    socket_path = validate_socket_path(path)
    try:
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    except OSError as error:
        raise DesktopTransportError(
            "Desktop socket could not be created"
        ) from error
    bound_metadata: os.stat_result | None = None
    runtime_metadata = socket_path.parent.lstat()
    previous_umask = os.umask(0o077)
    try:
        try:
            listener.bind(str(socket_path))
            bound_metadata = socket_path.lstat()
            os.chmod(socket_path, 0o600, follow_symlinks=False)
            secured_metadata = socket_path.lstat()
            validate_runtime_directory(socket_path.parent)
            current_runtime_metadata = socket_path.parent.lstat()
            if (
                secured_metadata.st_dev != bound_metadata.st_dev
                or secured_metadata.st_ino != bound_metadata.st_ino
                or current_runtime_metadata.st_dev != runtime_metadata.st_dev
                or current_runtime_metadata.st_ino != runtime_metadata.st_ino
                or not stat.S_ISSOCK(secured_metadata.st_mode)
                or secured_metadata.st_uid != os.geteuid()
                or stat.S_IMODE(secured_metadata.st_mode) != 0o600
            ):
                raise DesktopTransportError(
                    "Desktop socket permissions are invalid"
                )
        except DesktopTransportError:
            listener.close()
            if bound_metadata is not None:
                _unlink_owned_socket(
                    socket_path,
                    bound_metadata.st_dev,
                    bound_metadata.st_ino,
                )
            raise
        except OSError as error:
            listener.close()
            if bound_metadata is not None:
                _unlink_owned_socket(
                    socket_path,
                    bound_metadata.st_dev,
                    bound_metadata.st_ino,
                )
            raise DesktopTransportError(
                "Desktop socket could not be bound"
            ) from error
    finally:
        os.umask(previous_umask)

    try:
        yield listener
    finally:
        listener.close()
        if bound_metadata is not None:
            _unlink_owned_socket(
                socket_path,
                bound_metadata.st_dev,
                bound_metadata.st_ino,
            )


def _single_header(scope: Scope, name: bytes) -> bytes | None:
    values = [
        value
        for key, value in scope.get("headers", [])
        if key.lower() == name
    ]
    if len(values) > 1:
        raise _RequestRejected(400, "invalid_headers", "Invalid request headers")
    return values[0] if values else None


async def _send_error(
    send: Send,
    *,
    status_code: int,
    code: str,
    detail: str,
) -> None:
    body = json.dumps(
        {"code": code, "detail": detail},
        separators=(",", ":"),
    ).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
    ]
    if status_code == 401:
        headers.append((b"www-authenticate", b"Bearer"))
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": headers,
        }
    )
    await send({"type": "http.response.body", "body": body})


class DesktopSession:
    """ASGI middleware enforcing the per-launch desktop request contract.

    An unbound instance can be passed to ``create_app``. Starlette also creates
    bound instances directly when it builds the application's middleware
    stack.
    """

    __slots__ = (
        "app",
        "launch_id",
        "max_request_body_bytes",
        "_expected_authorization",
    )

    def __init__(
        self,
        app: ASGIApp | None = None,
        *,
        token: str | None = None,
        launch_id: str | None = None,
        max_request_body_bytes: int = MAX_DESKTOP_REQUEST_BODY_BYTES,
        expected_authorization: bytes | None = None,
        session: DesktopSession | None = None,
    ) -> None:
        if session is not None:
            if (
                token is not None
                or launch_id is not None
                or expected_authorization is not None
            ):
                raise DesktopTransportError(
                    "Desktop middleware configuration is invalid"
                )
            launch_id = session.launch_id
            max_request_body_bytes = session.max_request_body_bytes
            expected_authorization = session._expected_authorization
        if launch_id is None or not _UUID_PATTERN.fullmatch(launch_id):
            raise DesktopTransportError("Desktop launch ID is invalid")
        if max_request_body_bytes < 1:
            raise DesktopTransportError("Desktop request body bound is invalid")
        if expected_authorization is None:
            if not isinstance(token, str) or not _TOKEN_PATTERN.fullmatch(token):
                raise DesktopTransportError("Startup token is invalid")
            try:
                token_bytes = token.encode("ascii")
            except UnicodeEncodeError as error:
                raise DesktopTransportError("Startup token is invalid") from error
            if len(token_bytes) != MAX_STARTUP_TOKEN_BYTES:
                raise DesktopTransportError("Startup token is invalid")
            expected_authorization = b"Bearer " + token_bytes
        self.app = app
        self.launch_id = launch_id
        self.max_request_body_bytes = max_request_body_bytes
        self._expected_authorization = expected_authorization

    def middleware_options(self) -> dict[str, object]:
        """Return non-logging options used to bind this instance to an app."""

        return {"session": self}

    def __repr__(self) -> str:
        return (
            "DesktopSession("
            f"launch_id={self.launch_id!r}, "
            f"max_request_body_bytes={self.max_request_body_bytes!r})"
        )

    def _validate_headers(self, scope: Scope) -> int:
        authorization = _single_header(scope, b"authorization")
        if authorization is None or not hmac.compare_digest(
            authorization,
            self._expected_authorization,
        ):
            raise _RequestRejected(401, "unauthorized", "Unauthorized")

        protocol = _single_header(scope, b"x-lcf-protocol-version")
        if protocol != DESKTOP_PROTOCOL_VERSION.encode("ascii"):
            raise _RequestRejected(
                426,
                "protocol_mismatch",
                "Desktop protocol version is not supported",
            )

        launch_id = _single_header(scope, b"x-lcf-launch-id")
        try:
            launch_id_text = (
                launch_id.decode("ascii") if launch_id is not None else ""
            )
        except UnicodeDecodeError as error:
            raise _RequestRejected(
                403,
                "launch_mismatch",
                "Desktop launch ID is not valid",
            ) from error
        if not hmac.compare_digest(launch_id_text, self.launch_id):
            raise _RequestRejected(
                403,
                "launch_mismatch",
                "Desktop launch ID is not valid",
            )

        request_id = _single_header(scope, b"x-lcf-request-id")
        try:
            request_id_text = (
                request_id.decode("ascii") if request_id is not None else ""
            )
        except UnicodeDecodeError as error:
            raise _RequestRejected(
                400,
                "invalid_request_id",
                "Request ID is invalid",
            ) from error
        if not _UUID_PATTERN.fullmatch(request_id_text):
            raise _RequestRejected(
                400,
                "invalid_request_id",
                "Request ID is invalid",
            )

        deadline = _single_header(scope, b"x-lcf-deadline-ms")
        if deadline is None or len(deadline) > 20 or not deadline.isdigit():
            raise _RequestRejected(
                400,
                "invalid_deadline",
                "Request deadline is invalid",
            )
        deadline_ms = int(deadline)
        now_ms = time.time_ns() // 1_000_000
        if deadline_ms <= now_ms:
            raise _RequestRejected(
                408,
                "deadline_exceeded",
                "Request deadline has expired",
            )
        if deadline_ms > now_ms + MAX_DESKTOP_DEADLINE_MS:
            raise _RequestRejected(
                400,
                "invalid_deadline",
                "Request deadline is invalid",
            )
        return deadline_ms

    def _validate_content_length(self, scope: Scope) -> None:
        content_length = _single_header(scope, b"content-length")
        if content_length is None:
            return
        if (
            len(content_length) > 20
            or not content_length.isdigit()
            or int(content_length) > self.max_request_body_bytes
        ):
            status_code = (
                413
                if content_length.isdigit()
                and int(content_length) > self.max_request_body_bytes
                else 400
            )
            raise _RequestRejected(
                status_code,
                "payload_too_large"
                if status_code == 413
                else "invalid_content_length",
                "Request payload is too large"
                if status_code == 413
                else "Content-Length is invalid",
            )

    async def _read_request_body(
        self,
        receive: Receive,
        deadline_ms: int,
    ) -> bytes:
        body = bytearray()
        while True:
            remaining = (deadline_ms - time.time_ns() // 1_000_000) / 1000
            if remaining <= 0:
                raise _RequestRejected(
                    408,
                    "deadline_exceeded",
                    "Request deadline has expired",
                )
            try:
                message = await asyncio.wait_for(receive(), timeout=remaining)
            except TimeoutError as error:
                raise _RequestRejected(
                    408,
                    "deadline_exceeded",
                    "Request deadline has expired",
                ) from error
            if message["type"] == "http.disconnect":
                raise _RequestRejected(
                    400,
                    "request_disconnected",
                    "Request was not completed",
                )
            if message["type"] != "http.request":
                raise _RequestRejected(
                    400,
                    "invalid_request",
                    "Request was not valid",
                )
            chunk = message.get("body", b"")
            if not isinstance(chunk, bytes):
                raise _RequestRejected(
                    400,
                    "invalid_request",
                    "Request was not valid",
                )
            if len(chunk) > self.max_request_body_bytes - len(body):
                raise _RequestRejected(
                    413,
                    "payload_too_large",
                    "Request payload is too large",
                )
            body.extend(chunk)
            if not message.get("more_body", False):
                return bytes(body)

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if self.app is None:
            raise RuntimeError("DesktopSession middleware is not bound")
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send(
                {
                    "type": "websocket.close",
                    "code": 1008,
                    "reason": "WebSocket transport is not supported",
                }
            )
            return
        if scope["type"] != "http":
            raise RuntimeError("Unsupported desktop ASGI scope")

        try:
            deadline_ms = self._validate_headers(scope)
            self._validate_content_length(scope)
            body = await self._read_request_body(receive, deadline_ms)
        except _RequestRejected as error:
            await _send_error(
                send,
                status_code=error.status_code,
                code=error.code,
                detail=error.detail,
            )
            return

        delivered = False

        async def replay_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        response_started = False
        response_completed = False
        deadline_closed = False

        async def deadline_send(message: Message) -> None:
            nonlocal response_started, response_completed
            if (
                deadline_closed
                or time.time_ns() // 1_000_000 >= deadline_ms
            ):
                raise _ResponseDeadlineExpired
            if message["type"] == "http.response.start":
                response_started = True
            elif (
                message["type"] == "http.response.body"
                and not message.get("more_body", False)
            ):
                response_completed = True
            await send(message)

        remaining = (deadline_ms - time.time_ns() // 1_000_000) / 1000
        application_task = asyncio.create_task(
            self.app(scope, replay_receive, deadline_send)
        )
        try:
            done, _ = await asyncio.wait(
                {application_task},
                timeout=max(remaining, 0),
            )
            if application_task in done:
                await application_task
                return
        except _ResponseDeadlineExpired:
            pass

        deadline_closed = True
        if not response_started:
            await _send_error(
                send,
                status_code=408,
                code="deadline_exceeded",
                detail="Request deadline has expired",
            )
        elif not response_completed:
            await send(
                {
                    "type": "http.response.body",
                    "body": b"",
                    "more_body": False,
                }
            )
        if not application_task.done():
            application_task.cancel()
            _BACKGROUND_APPLICATION_TASKS.add(application_task)
            application_task.add_done_callback(_consume_background_task)
        else:
            # Cover the narrow race where the task completed just after
            # asyncio.wait reported the timeout.
            _consume_background_task(application_task)

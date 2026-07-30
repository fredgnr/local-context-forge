from __future__ import annotations

import asyncio
import json
import os
import socket
import stat
import threading
import time
import tomllib
from pathlib import Path

import pytest
import app.factory as app_factory
from app.cli import main as cli_main
from app.config import Settings
from app.desktop_session import (
    MAX_DESKTOP_REQUEST_BODY_BYTES,
    MAX_STARTUP_TOKEN_BYTES,
    MAX_UDS_PATH_BYTES,
    DesktopSession,
    DesktopTransportError,
    ParentLivenessWatcher,
    prebound_unix_socket,
    read_token_fd,
    validate_runtime_directory,
    validate_socket_path,
)
from app.main import create_app
from app.version import APP_VERSION
from fastapi import FastAPI
from fastapi.testclient import TestClient


TOKEN = "a" * 43
LAUNCH_ID = "01234567-89ab-4cde-8fab-0123456789ab"
REQUEST_ID = "12345678-9abc-4def-8abc-123456789abc"


def _settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        data_dir=data_dir,
        database_path=data_dir / "metadata.sqlite3",
        qmd_enabled=False,
    )


def _headers(**updates: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "X-LCF-Protocol-Version": "1.0",
        "X-LCF-Launch-Id": LAUNCH_ID,
        "X-LCF-Request-Id": REQUEST_ID,
        "X-LCF-Deadline-Ms": str(time.time_ns() // 1_000_000 + 30_000),
    }
    headers.update(updates)
    return headers


def _desktop_app(tmp_path: Path):
    return create_app(
        _settings(tmp_path),
        desktop_session=DesktopSession(token=TOKEN, launch_id=LAUNCH_ID),
    )


def test_legacy_app_remains_anonymous_and_keeps_cors(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        response = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "http://localhost:3000"
    )


def test_factory_import_has_no_module_level_service_and_cli_is_explicit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert not hasattr(app_factory, "app")

    assert cli_main(["version"]) == 0
    assert capsys.readouterr().out == f"{APP_VERSION}\n"

    doctor_status = cli_main(["doctor"])
    doctor = json.loads(capsys.readouterr().out)
    assert doctor_status == (0 if doctor["ok"] else 1)
    assert doctor["checks"]["python_runtime"] == "ok"
    assert doctor["protocol"] == {"major": 1, "minor": 0}
    assert doctor["schema_version"] == 3

    project = tomllib.loads(
        (
            Path(__file__).resolve().parents[2]
            / "backend"
            / "pyproject.toml"
        ).read_text(encoding="utf-8")
    )
    assert project["project"]["scripts"] == {"lcf-service": "app.cli:main"}


@pytest.mark.parametrize("unsupported_command", ["runner", "mcp"])
def test_cli_does_not_claim_unimplemented_subcommands(
    unsupported_command: str,
) -> None:
    with pytest.raises(SystemExit) as error:
        cli_main([unsupported_command])
    assert error.value.code == 2


def test_desktop_rejects_missing_and_wrong_token(tmp_path: Path) -> None:
    app = _desktop_app(tmp_path)
    with TestClient(app) as client:
        missing = _headers()
        del missing["Authorization"]
        assert client.get("/api/health", headers=missing).status_code == 401

        wrong = _headers(Authorization="Bearer definitely-not-the-token")
        response = client.get("/api/health", headers=wrong)
        assert response.status_code == 401
        assert TOKEN not in response.text


def test_desktop_handshake_and_health_require_complete_headers(
    tmp_path: Path,
) -> None:
    app = _desktop_app(tmp_path)
    with TestClient(app) as client:
        handshake = client.get(
            "/api/desktop/handshake",
            headers=_headers(),
        )
        health = client.get("/api/health", headers=_headers())

    assert handshake.status_code == 200
    assert handshake.json() == {
        "service": "local-context-forge",
        "role": "python-sidecar",
        "app_version": APP_VERSION,
        "sidecar_version": APP_VERSION,
        "protocol": {"major": 1, "minor": 0},
        "launch_id": LAUNCH_ID,
        "transport": "uds",
        "schema_version": 3,
        "capabilities": [
            "desktop-handshake",
            "health",
            "library-api",
        ],
    }
    assert health.status_code == 200
    assert health.json()["version"] == APP_VERSION


def test_desktop_mode_has_no_cors_and_does_not_repr_token(
    tmp_path: Path,
) -> None:
    app = _desktop_app(tmp_path)
    assert TOKEN not in repr(app.user_middleware)
    with TestClient(app) as client:
        response = client.get(
            "/api/health",
            headers={
                **_headers(),
                "Origin": "http://localhost:3000",
            },
        )
    assert "access-control-allow-origin" not in response.headers


def test_desktop_session_fails_closed_for_websocket_scope() -> None:
    downstream_called = False
    sent: list[dict] = []

    async def downstream(scope, receive, send) -> None:
        nonlocal downstream_called
        downstream_called = True

    session = DesktopSession(
        downstream,
        token=TOKEN,
        launch_id=LAUNCH_ID,
    )

    async def receive() -> dict:
        return {"type": "websocket.connect"}

    async def send(message: dict) -> None:
        sent.append(message)

    asyncio.run(
        session(
            {
                "type": "websocket",
                "asgi": {"version": "3.0"},
                "scheme": "ws",
                "path": "/ws",
                "raw_path": b"/ws",
                "query_string": b"",
                "headers": [],
                "client": None,
                "server": None,
                "subprotocols": [],
            },
            receive,
            send,
        )
    )
    assert downstream_called is False
    assert sent == [
        {
            "type": "websocket.close",
            "code": 1008,
            "reason": "WebSocket transport is not supported",
        }
    ]


@pytest.mark.parametrize(
    ("mutate", "expected_status"),
    [
        ({"X-LCF-Launch-Id": "another-launch"}, 403),
        ({"X-LCF-Protocol-Version": "2.0"}, 426),
        ({"X-LCF-Request-Id": ""}, 400),
        ({"X-LCF-Request-Id": " "}, 400),
        ({"X-LCF-Deadline-Ms": "not-a-number"}, 400),
        ({"X-LCF-Deadline-Ms": "1"}, 408),
        (
            {
                    "X-LCF-Deadline-Ms": str(
                        time.time_ns() // 1_000_000 + 10_000_000
                    )
            },
            400,
        ),
    ],
)
def test_desktop_rejects_invalid_contract_headers(
    tmp_path: Path,
    mutate: dict[str, str],
    expected_status: int,
) -> None:
    app = _desktop_app(tmp_path)
    with TestClient(app) as client:
        response = client.get(
            "/api/desktop/handshake",
            headers=_headers(**mutate),
        )
    assert response.status_code == expected_status
    assert TOKEN not in response.text


@pytest.mark.parametrize(
    "required_header",
    [
        "X-LCF-Launch-Id",
        "X-LCF-Protocol-Version",
        "X-LCF-Request-Id",
        "X-LCF-Deadline-Ms",
    ],
)
def test_desktop_rejects_each_missing_contract_header(
    tmp_path: Path,
    required_header: str,
) -> None:
    headers = _headers()
    del headers[required_header]
    app = _desktop_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/health", headers=headers)
    assert response.status_code in {400, 403, 408, 426}


def test_desktop_rejects_oversize_body_before_routing(tmp_path: Path) -> None:
    app = _desktop_app(tmp_path)
    body = b"x" * (MAX_DESKTOP_REQUEST_BODY_BYTES + 1)
    with TestClient(app) as client:
        response = client.post(
            "/api/query",
            content=body,
            headers=_headers(**{"Content-Type": "application/json"}),
        )
    assert response.status_code == 413
    assert TOKEN not in response.text


def test_desktop_rejects_streamed_oversize_body_without_content_length() -> None:
    downstream_called = False
    sent: list[dict] = []

    async def downstream(scope, receive, send) -> None:
        nonlocal downstream_called
        downstream_called = True

    middleware = DesktopSession(
        downstream,
        token=TOKEN,
        launch_id=LAUNCH_ID,
    )
    raw_headers = [
        (name.lower().encode("ascii"), value.encode("ascii"))
        for name, value in _headers().items()
    ]
    messages = iter(
        [
            {
                "type": "http.request",
                "body": b"x" * 200_000,
                "more_body": True,
            },
            {
                "type": "http.request",
                "body": b"x" * 70_000,
                "more_body": False,
            },
        ]
    )

    async def receive() -> dict:
        return next(messages)

    async def send(message: dict) -> None:
        sent.append(message)

    asyncio.run(
        middleware(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/api/query",
                "raw_path": b"/api/query",
                "query_string": b"",
                "headers": raw_headers,
                "client": None,
                "server": None,
            },
            receive,
            send,
        )
    )

    assert downstream_called is False
    assert sent[0]["status"] == 413


@pytest.mark.parametrize(
    "duplicated_name",
    [
        "authorization",
        "x-lcf-protocol-version",
        "x-lcf-launch-id",
        "x-lcf-request-id",
        "x-lcf-deadline-ms",
    ],
)
def test_desktop_rejects_duplicate_security_headers(
    tmp_path: Path,
    duplicated_name: str,
) -> None:
    headers = list(_headers().items())
    value = next(
        value for name, value in headers if name.lower() == duplicated_name
    )
    headers.append((duplicated_name, value))
    app = _desktop_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/health", headers=headers)
    assert response.status_code == 400
    assert TOKEN not in response.text


def test_deadline_covers_handler_and_response_time() -> None:
    sent: list[dict] = []
    cancelled = False

    async def slow_app(scope, receive, send) -> None:
        nonlocal cancelled
        try:
            await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            cancelled = True
            raise
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"late"})

    middleware = DesktopSession(
        slow_app,
        token=TOKEN,
        launch_id=LAUNCH_ID,
    )
    headers = _headers(
        **{
            "X-LCF-Deadline-Ms": str(
                time.time_ns() // 1_000_000 + 20
            )
        }
    )
    raw_headers = [
        (name.lower().encode("ascii"), value.encode("ascii"))
        for name, value in headers.items()
    ]
    received = False

    async def receive() -> dict:
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    asyncio.run(
        middleware(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/health",
                "raw_path": b"/api/health",
                "query_string": b"",
                "headers": raw_headers,
                "client": None,
                "server": None,
            },
            receive,
            send,
        )
    )

    assert cancelled is True
    assert sent[0]["status"] == 408


def test_deadline_returns_promptly_for_sync_threadpool_handler() -> None:
    application = FastAPI()

    @application.get("/slow")
    def slow_handler() -> dict[str, bool]:
        time.sleep(0.2)
        return {"completed": True}

    secured = DesktopSession(
        application,
        token=TOKEN,
        launch_id=LAUNCH_ID,
    )
    headers = _headers(
        **{
            "X-LCF-Deadline-Ms": str(
                time.time_ns() // 1_000_000 + 30
            )
        }
    )
    with TestClient(secured) as client:
        started = time.monotonic()
        response = client.get("/slow", headers=headers)
        elapsed = time.monotonic() - started

    assert response.status_code == 408
    assert elapsed < 0.15


def test_handshake_does_not_expose_process_transport_secrets(
    tmp_path: Path,
) -> None:
    app = _desktop_app(tmp_path)
    with TestClient(app) as client:
        payload = client.get(
            "/api/desktop/handshake",
            headers=_headers(),
        ).json()
    encoded = json.dumps(payload)
    assert TOKEN not in encoded
    assert "socket" not in encoded.lower()
    assert "pid" not in encoded.lower()
    assert set(payload) == {
        "service",
        "role",
        "app_version",
        "sidecar_version",
        "protocol",
        "launch_id",
        "transport",
        "schema_version",
        "capabilities",
    }


def _runtime_directory(tmp_path: Path) -> Path:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    runtime.chmod(0o700)
    return runtime


def test_runtime_directory_rejects_symlink_and_wrong_mode(
    tmp_path: Path,
) -> None:
    runtime = _runtime_directory(tmp_path)
    assert validate_runtime_directory(runtime) == runtime

    link = tmp_path / "runtime-link"
    link.symlink_to(runtime, target_is_directory=True)
    with pytest.raises(DesktopTransportError):
        validate_runtime_directory(link)

    runtime.chmod(0o755)
    with pytest.raises(DesktopTransportError):
        validate_runtime_directory(runtime)


def test_runtime_directory_rejects_unexpected_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime_directory(tmp_path)
    monkeypatch.setattr(os, "geteuid", lambda: runtime.stat().st_uid + 1)
    with pytest.raises(DesktopTransportError):
        validate_runtime_directory(runtime)


@pytest.mark.parametrize("existing_kind", ["file", "directory", "symlink"])
def test_socket_path_rejects_any_existing_entry(
    tmp_path: Path,
    existing_kind: str,
) -> None:
    runtime = _runtime_directory(tmp_path)
    socket_path = runtime / "py.sock"
    if existing_kind == "file":
        socket_path.write_text("stale", encoding="utf-8")
    elif existing_kind == "directory":
        socket_path.mkdir()
    else:
        socket_path.symlink_to(runtime / "missing-target")

    with pytest.raises(DesktopTransportError):
        validate_socket_path(socket_path)


def test_socket_path_rejects_conservative_macos_overflow(
    tmp_path: Path,
) -> None:
    runtime = _runtime_directory(tmp_path)
    base_bytes = len(f"{runtime}/".encode("utf-8"))
    filename_size = MAX_UDS_PATH_BYTES - base_bytes + 1
    if filename_size > 255:
        pytest.skip("temporary root is too short to create the boundary path")
    socket_path = runtime / ("s" * filename_size)
    assert len(str(socket_path).encode("utf-8")) == MAX_UDS_PATH_BYTES + 1
    with pytest.raises(DesktopTransportError):
        validate_socket_path(socket_path)


def test_prebound_socket_is_0600_and_removed_on_exit(tmp_path: Path) -> None:
    runtime = _runtime_directory(tmp_path)
    socket_path = runtime / "py.sock"
    try:
        with prebound_unix_socket(socket_path) as listener:
            metadata = socket_path.lstat()
            assert listener.family == socket.AF_UNIX
            assert stat.S_ISSOCK(metadata.st_mode)
            assert stat.S_IMODE(metadata.st_mode) == 0o600
            assert metadata.st_uid == os.geteuid()
    except DesktopTransportError as error:
        if isinstance(error.__cause__, PermissionError):
            if os.getenv("CI", "").lower() == "true":
                raise
            pytest.skip("execution sandbox prohibits AF_UNIX socket creation")
        raise
    assert not os.path.lexists(socket_path)


def test_token_fd_read_is_bounded_and_closes_descriptor() -> None:
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"x" * (MAX_STARTUP_TOKEN_BYTES + 1))
    os.close(write_fd)

    with pytest.raises(DesktopTransportError):
        read_token_fd(read_fd)
    with pytest.raises(OSError):
        os.fstat(read_fd)


def test_token_fd_reads_exact_bytes_without_trimming() -> None:
    read_fd, write_fd = os.pipe()
    os.write(write_fd, TOKEN.encode("ascii") + b"\n")

    assert read_token_fd(read_fd) == TOKEN
    os.fstat(read_fd)
    os.close(read_fd)
    os.close(write_fd)


@pytest.mark.parametrize(
    "payload",
    [
        b"short\n",
        b"a" * 43,
        b"a" * 42 + b"+\n",
        b"a" * 43 + b"=\n",
    ],
)
def test_token_fd_rejects_noncanonical_or_unframed_token(
    payload: bytes,
) -> None:
    read_fd, write_fd = os.pipe()
    os.write(write_fd, payload)
    os.close(write_fd)

    with pytest.raises(DesktopTransportError):
        read_token_fd(read_fd)
    with pytest.raises(OSError):
        os.fstat(read_fd)


def test_parent_liveness_watcher_signals_only_after_frame(
) -> None:
    read_fd, write_fd = os.pipe()
    os.write(write_fd, TOKEN.encode("ascii") + b"\n")
    assert read_token_fd(read_fd) == TOKEN

    disconnected = threading.Event()
    watcher = ParentLivenessWatcher(read_fd, disconnected.set)
    watcher.start()
    assert disconnected.wait(0.05) is False

    os.close(write_fd)
    assert disconnected.wait(1) is True
    watcher.close()
    with pytest.raises(OSError):
        os.fstat(read_fd)

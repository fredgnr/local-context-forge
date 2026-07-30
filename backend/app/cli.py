"""Command-line entry point for the packaged Python sidecar."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import uvicorn

from .config import Settings
from .db import SCHEMA_VERSION
from .desktop_session import (
    DesktopSession,
    DesktopTransportError,
    ParentLivenessWatcher,
    prebound_unix_socket,
    read_startup_token,
)
from .version import (
    APP_VERSION,
    DESKTOP_PROTOCOL_MAJOR,
    DESKTOP_PROTOCOL_MINOR,
    PYTHON_DISTRIBUTION_VERSION,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lcf-service")
    subparsers = parser.add_subparsers(dest="command", required=True)

    api = subparsers.add_parser(
        "api",
        help="run the authenticated desktop API on a Unix domain socket",
    )
    api.add_argument("--uds", required=True, type=Path)
    api.add_argument("--launch-id", required=True)
    api.add_argument("--token-fd", required=True, type=int, choices=(3,))
    api.add_argument("--data-dir", required=True, type=Path)

    subparsers.add_parser("doctor", help="print a local sidecar diagnostic")
    subparsers.add_parser("version", help="print the product version")
    return parser


def _desktop_settings(data_dir: Path) -> Settings:
    if not data_dir.is_absolute() or ".." in data_dir.parts:
        raise DesktopTransportError(
            "Desktop data directory must be an absolute canonical path"
        )
    resolved_data_dir = data_dir.resolve()
    configured = Settings.from_env()
    return replace(
        configured,
        data_dir=resolved_data_dir,
        database_path=resolved_data_dir / "metadata.sqlite3",
        qmd_config_dir=resolved_data_dir / "qmd" / "config",
        qmd_cache_dir=resolved_data_dir / "qmd" / "cache",
        runner_dir=resolved_data_dir / "runner",
    )


def run_api(
    *,
    uds: Path,
    launch_id: str,
    token_fd: int,
    data_dir: Path,
) -> int:
    """Run the desktop API without opening a TCP listener."""

    if token_fd != 3:
        raise DesktopTransportError("Startup token descriptor is invalid")
    token = read_startup_token(token_fd)
    watcher: ParentLivenessWatcher | None = None
    try:
        session = DesktopSession(token=token, launch_id=launch_id)
        settings = _desktop_settings(data_dir)

        from .factory import create_app

        application = create_app(settings, desktop_session=session)
        config = uvicorn.Config(
            application,
            access_log=False,
            date_header=True,
            h11_max_incomplete_event_size=16_384,
            host=None,
            limit_concurrency=64,
            log_level="warning",
            proxy_headers=False,
            server_header=False,
            timeout_graceful_shutdown=10,
            timeout_keep_alive=5,
            workers=1,
            ws="none",
        )
        server = uvicorn.Server(config)
        watcher = ParentLivenessWatcher(
            token_fd,
            lambda: setattr(server, "should_exit", True),
        )
        watcher.start()
        with prebound_unix_socket(uds) as listener:
            server.run(sockets=[listener])
        return 0
    finally:
        if watcher is not None:
            watcher.close()
        else:
            try:
                os.close(token_fd)
            except OSError:
                pass


def _doctor() -> int:
    uds_available = False
    if hasattr(socket, "AF_UNIX"):
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        except OSError:
            pass
        else:
            probe.close()
            uds_available = True
    python_compatible = sys.version_info[:2] == (3, 12)
    ok = uds_available and python_compatible
    result = {
        "ok": ok,
        "service": "local-context-forge",
        "role": "python-sidecar",
        "app_version": APP_VERSION,
        "sidecar_version": APP_VERSION,
        "python_distribution_version": PYTHON_DISTRIBUTION_VERSION,
        "protocol": {
            "major": int(DESKTOP_PROTOCOL_MAJOR),
            "minor": int(DESKTOP_PROTOCOL_MINOR),
        },
        "schema_version": SCHEMA_VERSION,
        "checks": {
            "python_runtime": (
                "ok" if python_compatible else "requires-python-3.12"
            ),
            "unix_domain_sockets": (
                "ok" if uds_available else "unavailable"
            ),
        },
    }
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "version":
        print(APP_VERSION)
        return 0
    if args.command == "doctor":
        return _doctor()
    if args.command == "api":
        try:
            return run_api(
                uds=args.uds,
                launch_id=args.launch_id,
                token_fd=args.token_fd,
                data_dir=args.data_dir,
            )
        except DesktopTransportError:
            print(
                "lcf-service: desktop transport setup failed",
                file=sys.stderr,
            )
            return 2
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())

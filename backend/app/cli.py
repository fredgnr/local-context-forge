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
from .desktop_retrieval import (
    DesktopRetrievalClient,
    DesktopRetriever,
    read_broker_capability,
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
    api.add_argument(
        "--local-source-root",
        action="append",
        default=[],
        type=Path,
        help=argparse.SUPPRESS,
    )
    api.add_argument("--retrieval-broker-uds", required=True, type=Path)
    api.add_argument(
        "--retrieval-capability-fd",
        required=True,
        type=int,
        choices=(4,),
    )

    subparsers.add_parser("doctor", help="print a local sidecar diagnostic")
    subparsers.add_parser("version", help="print the product version")
    return parser


def _desktop_settings(
    data_dir: Path,
    local_source_roots: Sequence[Path] = (),
) -> Settings:
    if not data_dir.is_absolute() or ".." in data_dir.parts:
        raise DesktopTransportError(
            "Desktop data directory must be an absolute canonical path"
        )
    resolved_data_dir = data_dir.resolve()
    reviewed_roots: list[Path] = []
    for root in local_source_roots:
        if not root.is_absolute() or ".." in root.parts:
            raise DesktopTransportError(
                "Desktop local source root must be an absolute canonical path"
            )
        resolved_root = root.resolve()
        if (
            resolved_root == Path(resolved_root.anchor)
            or resolved_root != root
            or resolved_root in reviewed_roots
        ):
            raise DesktopTransportError(
                "Desktop local source root must be unique and non-root"
            )
        reviewed_roots.append(resolved_root)
    configured = Settings.from_env()
    return replace(
        configured,
        data_dir=resolved_data_dir,
        database_path=resolved_data_dir / "metadata.sqlite3",
        qmd_config_dir=resolved_data_dir / "qmd" / "config",
        qmd_cache_dir=resolved_data_dir / "qmd" / "cache",
        qmd_hybrid_enabled=False,
        local_source_roots=tuple(reviewed_roots),
        local_source_owner_check=True,
        ctags_enabled=False,
        runner_dir=resolved_data_dir / "runner",
    )


def run_api(
    *,
    uds: Path,
    launch_id: str,
    token_fd: int,
    data_dir: Path,
    local_source_roots: Sequence[Path],
    retrieval_broker_uds: Path,
    retrieval_capability_fd: int,
) -> int:
    """Run the desktop API without opening a TCP listener."""

    if token_fd != 3 or retrieval_capability_fd != 4:
        raise DesktopTransportError("Startup token descriptor is invalid")
    token = read_startup_token(token_fd)
    watcher: ParentLivenessWatcher | None = None
    try:
        capability = read_broker_capability(retrieval_capability_fd)
        session = DesktopSession(token=token, launch_id=launch_id)
        settings = _desktop_settings(data_dir, local_source_roots)
        retriever = DesktopRetriever(
            DesktopRetrievalClient(
                socket_path=retrieval_broker_uds,
                capability=capability,
                launch_id=launch_id,
            ),
            settings.wiki_dir,
        )

        from .factory import create_app

        application = create_app(
            settings,
            desktop_session=session,
            retriever=retriever,
        )
        config = uvicorn.Config(
            application,
            access_log=False,
            date_header=True,
            h11_max_incomplete_event_size=16_384,
            host=None,
            limit_concurrency=64,
            log_level="warning",
            loop="asyncio",
            proxy_headers=False,
            server_header=False,
            timeout_graceful_shutdown=10,
            timeout_keep_alive=5,
            workers=1,
            http="h11",
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
    python_compatible = sys.version_info[:3] == (3, 13, 14)
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
                "ok" if python_compatible else "requires-python-3.13.14"
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
                local_source_roots=args.local_source_root,
                retrieval_broker_uds=args.retrieval_broker_uds,
                retrieval_capability_fd=args.retrieval_capability_fd,
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

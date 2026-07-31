"""Capability-scoped retrieval port used only by the desktop sidecar."""

from __future__ import annotations

import http.client
import json
import math
import os
import re
import socket
import stat
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from .desktop_session import (
    MAX_STARTUP_TOKEN_BYTES,
    MAX_UDS_PATH_BYTES,
    DesktopTransportError,
    read_token_fd,
)
from .retrieval import TOKEN_PATTERN, _snippet, lexical_search
from .version import DESKTOP_RETRIEVAL_PROTOCOL_VERSION

MAX_BROKER_REQUEST_BYTES = 262_144
MAX_BROKER_RESPONSE_BYTES = 2_097_152
MAX_COLLECTIONS = 256
MAX_QUERY_BYTES = 8_192
MAX_RESULTS = 100

_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_COLLECTION_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,118}\Z")


class DesktopRetrievalError(RuntimeError):
    """Sanitized broker failure that never contains capability or socket data."""

    def __init__(self, code: str) -> None:
        super().__init__(f"Desktop retrieval request failed ({code})")
        self.code = code


def read_broker_capability(fd: int) -> str:
    """Read the fd4 capability frame and close the descriptor immediately."""

    try:
        return read_token_fd(fd, max_bytes=MAX_STARTUP_TOKEN_BYTES)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _validate_launch_id(value: str) -> str:
    if not isinstance(value, str) or not _UUID_PATTERN.fullmatch(value):
        raise DesktopTransportError("Retrieval launch identifier is invalid")
    return value


def _validate_capability(value: str) -> str:
    if not isinstance(value, str) or not _TOKEN_PATTERN.fullmatch(value):
        raise DesktopTransportError("Retrieval capability is invalid")
    return value


def _validate_socket(path: Path) -> tuple[int, int]:
    if (
        not path.is_absolute()
        or ".." in path.parts
        or "\0" in str(path)
        or len(str(path).encode("utf-8")) > MAX_UDS_PATH_BYTES
    ):
        raise DesktopTransportError("Retrieval broker socket path is invalid")
    try:
        metadata = path.lstat()
        parent = path.parent.lstat()
    except OSError as error:
        raise DesktopTransportError(
            "Retrieval broker socket is unavailable"
        ) from error
    if (
        not stat.S_ISSOCK(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise DesktopTransportError("Retrieval broker socket is not private")
    try:
        if path.parent.resolve(strict=True) != path.parent:
            raise DesktopTransportError(
                "Retrieval broker socket parent is not canonical"
            )
    except OSError as error:
        raise DesktopTransportError(
            "Retrieval broker socket parent is invalid"
        ) from error
    return metadata.st_dev, metadata.st_ino


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        try:
            connection.connect(self._socket_path)
        except BaseException:
            connection.close()
            raise
        self.sock = connection


class DesktopRetrievalClient:
    """Strict synchronous HTTP-over-UDS client for the Main-owned broker."""

    def __init__(
        self,
        *,
        socket_path: Path,
        capability: str,
        launch_id: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.socket_path = socket_path
        self._capability = _validate_capability(capability)
        self.launch_id = _validate_launch_id(launch_id)
        if not 0.1 <= timeout_seconds <= 120:
            raise DesktopTransportError("Retrieval timeout is invalid")
        self.timeout_seconds = timeout_seconds
        self._socket_identity = _validate_socket(socket_path)

    def request(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if endpoint not in {"/reconcile", "/search"}:
            raise DesktopRetrievalError("invalid_request")
        timeout = timeout_seconds or self.timeout_seconds
        if not 0.1 <= timeout <= 120:
            raise DesktopRetrievalError("invalid_request")
        try:
            serialized = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise DesktopRetrievalError("invalid_request") from error
        if len(serialized) > MAX_BROKER_REQUEST_BYTES:
            raise DesktopRetrievalError("request_too_large")
        try:
            current_identity = _validate_socket(self.socket_path)
        except DesktopTransportError as error:
            raise DesktopRetrievalError("transport") from error
        if current_identity != self._socket_identity:
            raise DesktopRetrievalError("transport")

        connection = _UnixHTTPConnection(str(self.socket_path), timeout)
        try:
            deadline = int(time.time() * 1000 + timeout * 1000)
            connection.request(
                "POST",
                endpoint,
                body=serialized,
                headers={
                    "Authorization": f"Bearer {self._capability}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Content-Length": str(len(serialized)),
                    "X-LCF-Protocol-Version": (
                        DESKTOP_RETRIEVAL_PROTOCOL_VERSION
                    ),
                    "X-LCF-Launch-Id": self.launch_id,
                    "X-LCF-Request-Id": str(uuid.uuid4()),
                    "X-LCF-Deadline-Ms": str(deadline),
                },
            )
            response = connection.getresponse()
            content_type = response.getheader("Content-Type", "")
            if content_type.split(";", 1)[0].strip().lower() != (
                "application/json"
            ):
                raise DesktopRetrievalError("invalid_response")
            declared_response = response.getheader("Content-Length")
            if (
                declared_response is not None
                and (
                    not declared_response.isdigit()
                    or int(declared_response) > MAX_BROKER_RESPONSE_BYTES
                )
            ):
                raise DesktopRetrievalError("invalid_response")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BROKER_RESPONSE_BYTES:
                    raise DesktopRetrievalError("invalid_response")
                chunks.append(chunk)
            try:
                parsed = json.loads(b"".join(chunks).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise DesktopRetrievalError("invalid_response") from error
            if not isinstance(parsed, dict):
                raise DesktopRetrievalError("invalid_response")
            if response.status != 200:
                if set(parsed) != {"error"} or not isinstance(
                    parsed["error"], str
                ):
                    raise DesktopRetrievalError("invalid_response")
                code = parsed["error"]
                if code not in {
                    "stale_index",
                    "too_many_collections",
                    "qmd_unavailable",
                    "invalid_response",
                }:
                    code = "broker_error"
                raise DesktopRetrievalError(code)
            return parsed
        except DesktopRetrievalError:
            raise
        except (OSError, TimeoutError, http.client.HTTPException) as error:
            raise DesktopRetrievalError("transport") from error
        finally:
            connection.close()


def _is_collection_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and _COLLECTION_PATTERN.fullmatch(value) is not None
        and ".." not in value
    )


def _is_revision(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= (2**53 - 1)
    )


def _is_safe_result_path(value: object) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or value.startswith(("/", "\\"))
        or "\\" in value
        or "\0" in value
        or len(value.encode("utf-8")) > 800
    ):
        return False
    path = PurePosixPath(value)
    return all(
        part not in {"", ".", ".."} and len(part.encode("utf-8")) <= 240
        for part in path.parts
    )


class DesktopRetriever:
    """QMD-compatible service port backed by Main's capability broker."""

    desktop_broker = True
    lexical_only = True

    def __init__(
        self,
        client: DesktopRetrievalClient,
        wiki_root: Path,
    ) -> None:
        if not wiki_root.is_absolute() or ".." in wiki_root.parts:
            raise DesktopTransportError("Desktop Wiki root is invalid")
        self.client = client
        self.wiki_root = wiki_root
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def _relative_wiki_root(self, candidate: Path) -> str:
        try:
            if not candidate.is_absolute() or ".." in candidate.parts:
                raise ValueError("candidate is not canonical")
            raw_relative = candidate.relative_to(self.wiki_root)
            current = self.wiki_root
            if stat.S_ISLNK(current.lstat().st_mode):
                raise ValueError("Wiki root is a symlink")
            for part in raw_relative.parts:
                current = current / part
                if stat.S_ISLNK(current.lstat().st_mode):
                    raise ValueError("Wiki path contains a symlink")
            canonical_wiki = self.wiki_root.resolve(strict=True)
            canonical_candidate = candidate.resolve(strict=True)
            relative = canonical_candidate.relative_to(canonical_wiki)
        except (OSError, RuntimeError, ValueError) as error:
            raise DesktopRetrievalError("invalid_request") from error
        value = PurePosixPath(*relative.parts).as_posix()
        if not _is_safe_result_path(value):
            raise DesktopRetrievalError("invalid_request")
        return value

    def reconcile(
        self,
        collections: list[tuple[Path, str]],
        *,
        revision: int,
    ) -> dict[str, Any]:
        if not _is_revision(revision):
            self._available = False
            return {"indexed": False, "reason": "invalid_revision"}
        if len(collections) > MAX_COLLECTIONS:
            self._available = False
            return {
                "indexed": False,
                "reason": "too_many_collections",
                "revision": revision,
                "collections": len(collections),
            }
        payload_collections: list[dict[str, str]] = []
        names: set[str] = set()
        try:
            for root, name in collections:
                if not _is_collection_name(name) or name in names:
                    raise DesktopRetrievalError("invalid_request")
                names.add(name)
                payload_collections.append(
                    {
                        "name": name,
                        "wiki_root": self._relative_wiki_root(root),
                    }
                )
            response = self.client.request(
                "/reconcile",
                {
                    "revision": revision,
                    "collections": payload_collections,
                },
                timeout_seconds=120,
            )
        except DesktopRetrievalError as error:
            self._available = False
            return {
                "indexed": False,
                "reason": error.code,
                "revision": revision,
                "collections": len(collections),
            }
        if (
            set(response) != {"indexed", "revision", "collections", "update"}
            or response["indexed"] is not True
            or response["revision"] != revision
            or response["collections"] != len(collections)
            or not isinstance(response["update"], dict)
            or set(response["update"])
            != {"indexed", "updated", "unchanged", "removed"}
            or not all(
                isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
                for value in response["update"].values()
            )
        ):
            self._available = False
            return {
                "indexed": False,
                "reason": "invalid_response",
                "revision": revision,
                "collections": len(collections),
            }
        self._available = True
        return response

    def rebuild(
        self,
        collections: list[tuple[Path, str]],
        *,
        embed: bool,
        model: str | None = None,
        revision: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        del model
        result = self.reconcile(
            collections,
            revision=revision if revision is not None else -1,
        )
        succeeded = bool(result.get("indexed"))
        registrations = [
            {
                "collection": name,
                "registered": succeeded,
                "reason": None if succeeded else result.get("reason"),
            }
            for _root, name in collections
        ]
        return registrations, {
            "updated": succeeded,
            "embedded": False,
            "reason": (
                "desktop-lexical-only"
                if succeeded and embed
                else (None if succeeded else result.get("reason"))
            ),
            "revision": result.get("revision"),
            "indexed": succeeded,
        }

    def index(self, _wiki_root: Path, _name: str) -> dict[str, Any]:
        return {"indexed": False, "reason": "full_reconcile_required"}

    def register_collection(
        self, _wiki_root: Path, name: str
    ) -> dict[str, Any]:
        return {
            "collection": name,
            "registered": False,
            "reason": "full_reconcile_required",
        }

    def remove_collection(self, name: str) -> dict[str, Any]:
        return {
            "collection": name,
            "removed": False,
            "reason": "full_reconcile_required",
        }

    def refresh(
        self, *, embed: bool, model: str | None = None
    ) -> dict[str, Any]:
        del embed, model
        return {
            "updated": False,
            "embedded": False,
            "reason": "full_reconcile_required",
        }

    def query(
        self,
        pages: list[dict[str, Any]],
        *,
        query: str,
        collection: str,
        limit: int,
        model: str | None = None,
        hybrid: bool | None = None,
        revision: int | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        del model, hybrid
        fallback = lambda: ("lexical", lexical_search(pages, query, limit))
        if (
            not _is_revision(revision)
            or not _is_collection_name(collection)
            or not isinstance(query, str)
            or not query.strip()
            or query != query.strip()
            or len(query.encode("utf-8")) > MAX_QUERY_BYTES
            or not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_RESULTS
        ):
            return fallback()
        candidate_limit = min(max(limit * 4, 20), MAX_RESULTS)
        try:
            response = self.client.request(
                "/search",
                {
                    "revision": revision,
                    "collection": collection,
                    "query": query,
                    "limit": candidate_limit,
                },
            )
        except DesktopRetrievalError:
            self._available = False
            return fallback()
        if (
            set(response) != {"revision", "results"}
            or response["revision"] != revision
            or not isinstance(response["results"], list)
            or len(response["results"]) > candidate_limit
        ):
            self._available = False
            return fallback()
        page_by_path = {str(page["path"]): page for page in pages}
        terms = [item.lower() for item in TOKEN_PATTERN.findall(query)]
        ranked: list[dict[str, Any]] = []
        used: set[str] = set()
        for item in response["results"]:
            if (
                not isinstance(item, dict)
                or set(item) != {"path", "score", "title"}
                or not _is_safe_result_path(item["path"])
                or not isinstance(item["score"], (int, float))
                or isinstance(item["score"], bool)
                or not math.isfinite(float(item["score"]))
                or not isinstance(item["title"], str)
                or item["path"] in used
            ):
                self._available = False
                return fallback()
            page = page_by_path.get(item["path"])
            if page is None:
                continue
            ranked.append(
                {
                    **page,
                    "score": float(item["score"]),
                    "snippet": _snippet(page["markdown"], terms),
                }
            )
            used.add(item["path"])
            if len(ranked) == limit:
                break
        self._available = True
        return "qmd-bm25", ranked

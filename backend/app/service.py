from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from .config import Settings
from .db import Database
from .desktop_generation import DesktopProviderGenerator
from .facts import extract_facts
from .generation import (
    GenerationCancelled,
    GenerationContext,
    GenerationError,
    generation_evidence_ranges,
    get_generator,
    normalize_page,
)
from .locks import LockUnavailable, filesystem_lock, lock_path
from .provider_attempts import ProviderAttemptStore
from .retrieval import QmdRetriever, collection_name, lexical_search
from .source import (
    SourceError,
    create_snapshot,
    validate_source_location,
)
from .utils import (
    atomic_write_json,
    atomic_write_text,
    portable_path_key,
    safe_page_path,
    slugify,
    utcnow,
)
from .validation import lint_published_wiki, validate_page
from .version import APP_VERSION
from .wiki import WikiError, WikiStore


class ServiceError(RuntimeError):
    status_code = 400


class NotFoundError(ServiceError):
    status_code = 404


class ConflictError(ServiceError):
    status_code = 409


class ValidationError(ServiceError):
    status_code = 422

    def __init__(self, message: str, issues: list[dict[str, str]] | None = None):
        super().__init__(message)
        self.issues = issues or []


def _identifier() -> str:
    return uuid.uuid4().hex


class JobCancelled(RuntimeError):
    pass


DEFAULT_EMBEDDING_MODEL = (
    "hf:ggml-org/embeddinggemma-300M-GGUF/"
    "embeddinggemma-300M-Q8_0.gguf"
)


def _status_error(value: object, settings: Settings) -> str | None:
    if not value:
        return None
    detail = str(value).replace("\0", "")
    for local_path in (
        str(Path.home()),
        str(settings.data_dir),
        str(settings.resolved_runner_dir),
    ):
        detail = detail.replace(local_path, "<local-path>")
    return detail[-1000:]


class AppService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        retriever: Any | None = None,
        desktop_mode: bool = False,
    ):
        self.settings = settings or Settings.from_env()
        self.desktop_mode = desktop_mode
        self.settings.ensure_directories()
        self.db = Database(self.settings.database_path)
        self.provider_attempts = (
            ProviderAttemptStore(self.db) if self.desktop_mode else None
        )
        self.retriever = (
            retriever if retriever is not None else QmdRetriever(self.settings)
        )
        self.instance_id = _identifier()
        self._runtime_lock_context = filesystem_lock(
            lock_path(self.settings.locks_dir, self.instance_id, "runtime"),
            blocking=False,
        )
        self._runtime_lock_context.__enter__()
        self._accepting_ingest = True
        self._drain_guard = threading.Lock()
        self._ingest_locks: dict[str, threading.Lock] = {}
        self._ingest_locks_guard = threading.Lock()
        self._publish_locks: dict[str, threading.Lock] = {}
        self._publish_locks_guard = threading.Lock()
        self.dispatcher = None
        self._ensure_runtime_settings()
        if self.provider_attempts is not None:
            self.provider_attempts.recover_interrupted()
        self.recover_orphaned_jobs()

    def close(self) -> None:
        if self.dispatcher is not None:
            if not self.dispatcher.stop():
                # Keep the runtime ownership lock while a cooperative job is
                # still unwinding. Process exit will release both.
                return
            self.dispatcher = None
        runtime_lock = getattr(self, "_runtime_lock_context", None)
        if runtime_lock is not None:
            self._runtime_lock_context = None
            runtime_lock.__exit__(None, None, None)

    def start_worker(self) -> None:
        if self.dispatcher is None:
            from .queue import PersistentJobDispatcher

            self.dispatcher = PersistentJobDispatcher(self)
        self.dispatcher.start()

    def _ensure_runtime_settings(self) -> None:
        now = utcnow()
        model = os.getenv("QMD_EMBED_MODEL", DEFAULT_EMBEDDING_MODEL)
        configured_provider = self.settings.default_provider
        configured_provider = {
            "codex": "codex_cli",
            "cursor": "cursor_cli",
        }.get(configured_provider, configured_provider)
        if self.desktop_mode:
            provider_order = ["codex_cli"]
            fallback_enabled = 0
        elif configured_provider == "auto":
            provider_order = ["codex_cli", "cursor_cli"]
            fallback_enabled = 1
        elif configured_provider in {
            "codex_cli",
            "cursor_cli",
            "mock",
            "ollama",
        }:
            provider_order = [configured_provider]
            fallback_enabled = 0
        else:
            provider_order = ["codex_cli", "cursor_cli"]
            fallback_enabled = 1
        with self.db.transaction() as connection:
            published_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM versions WHERE status = 'published'"
                ).fetchone()[0]
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO runtime_settings (
                    id, revision, provider_order_json, fallback_enabled,
                    provider_policy, cursor_consent_version,
                    cursor_consent_granted_at, concurrency, embedding_model,
                    updated_at
                ) VALUES (1, 1, ?, ?, 'codex_only', NULL, NULL, 1, ?, ?)
                """,
                (
                    json.dumps(provider_order),
                    fallback_enabled,
                    model,
                    now,
                ),
            )
            if self.desktop_mode:
                # Schema-5 intentionally converts every pre-desktop implicit
                # Cursor fallback into a fail-closed Codex-only policy. Cursor
                # can only be enabled again through a current explicit consent.
                connection.execute(
                    """
                    UPDATE runtime_settings
                    SET provider_order_json = '["codex_cli"]',
                        fallback_enabled = 0
                    WHERE id = 1 AND provider_policy = 'codex_only'
                    """
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO embedding_state (
                    id, desired_model, active_model, status, error,
                    last_job_id, corpus_revision, indexed_revision, updated_at
                ) VALUES (1, ?, ?, ?, ?, NULL, ?, 0, ?)
                """,
                (
                    model,
                    model,
                    "stale" if published_count else "ready",
                    (
                        "Existing published corpus requires an embedding rebuild"
                        if published_count
                        else None
                    ),
                    1 if published_count else 0,
                    now,
                ),
            )
            # A schema-v2 database had no corpus/index revision. Never mark its
            # pre-existing QMD vectors compatible with the new model profile.
            if published_count:
                connection.execute(
                    """
                    UPDATE embedding_state
                    SET status = 'stale', corpus_revision = 1,
                        error = COALESCE(
                            error,
                            'Existing published corpus requires an embedding rebuild'
                        ),
                        updated_at = ?
                    WHERE id = 1 AND corpus_revision = 0
                    """,
                    (now,),
                )

    def active_jobs(self) -> list[dict[str, Any]]:
        return self.db.fetchall(
            """
            SELECT * FROM jobs
            WHERE status IN ('queued', 'running', 'cancelling')
            ORDER BY queue_seq
            """
        )

    def begin_ingest_drain(self) -> dict[str, Any]:
        """Stop accepting new ingest jobs before a consistent backup."""

        with self._drain_guard:
            self._accepting_ingest = False
            active = self.db.fetchall(
                """
                SELECT * FROM jobs
                WHERE status IN ('running', 'cancelling')
                ORDER BY queue_seq
                """
            )
            queued = self.db.fetchone(
                "SELECT COUNT(*) AS count FROM jobs WHERE status = 'queued'"
            )
        return {
            "draining": True,
            "active_count": len(active),
            "active_jobs": active,
            "queued_count": int(queued["count"] if queued else 0),
        }

    def queue_activity(self) -> dict[str, Any]:
        running = self.db.fetchall(
            """
            SELECT * FROM jobs
            WHERE status IN ('running', 'cancelling')
            ORDER BY queue_seq
            """
        )
        queued = self.db.fetchone(
            "SELECT COUNT(*) AS count FROM jobs WHERE status = 'queued'"
        )
        return {
            "active_count": len(running),
            "active_jobs": [self._job_output(row) for row in running],
            "queued_count": int(queued["count"] if queued else 0),
        }

    def resume_ingest(self) -> dict[str, Any]:
        with self._drain_guard:
            self._accepting_ingest = True
        if self.dispatcher is not None:
            self.dispatcher.notify()
        return {"draining": False}

    @staticmethod
    def embedding_models() -> list[dict[str, Any]]:
        return [
            {
                "id": "embeddinggemma-300m-q8",
                "name": "EmbeddingGemma 300M Q8",
                "model": DEFAULT_EMBEDDING_MODEL,
                "recommended": True,
                "architecture": "GGUF",
                "dimensions": 768,
                "scope": "global",
            },
            {
                "id": "qwen3-embedding-0.6b-q8",
                "name": "Qwen3 Embedding 0.6B Q8",
                "model": (
                    "hf:Qwen/Qwen3-Embedding-0.6B-GGUF/"
                    "Qwen3-Embedding-0.6B-Q8_0.gguf"
                ),
                "recommended": False,
                "architecture": "GGUF",
                "dimensions": 1024,
                "scope": "global",
            },
        ]

    def validate_embedding_model(self, model: str) -> dict[str, Any]:
        normalized = model.strip()
        if (
            normalized != model
            or not normalized
            or any(character.isspace() for character in normalized)
            or any(character in normalized for character in "\0\r\n")
        ):
            raise ValidationError(
                "Embedding model must be a single safe identifier"
            )
        preset = next(
            (
                item
                for item in self.embedding_models()
                if item["model"] == normalized or item["id"] == normalized
            ),
            None,
        )
        if preset:
            return {
                "valid": True,
                "curated": True,
                "canonical_model": preset["model"],
                "preset": preset,
            }
        if (
            len(normalized) > 500
            or not re.fullmatch(
                r"hf:[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/"
                r"[A-Za-z0-9._+/-]+\.gguf",
                normalized,
            )
            or "//" in normalized
            or any(
                segment in {"", ".", ".."}
                for segment in normalized.removeprefix("hf:").split("/")
            )
        ):
            raise ValidationError(
                "Custom embedding model must be a safe hf:org/repo/file.gguf "
                "identifier; HTTP endpoints are not supported"
            )
        lowered = normalized.lower()
        if (
            "embeddinggemma" not in lowered
            and "qwen3-embedding" not in lowered
        ):
            raise ValidationError(
                "QMD 2.5.3 custom embedding models must use an "
                "EmbeddingGemma or Qwen3-Embedding GGUF family"
            )
        return {
            "valid": True,
            "curated": False,
            "canonical_model": normalized,
            "preset": None,
        }

    def get_settings(self) -> dict[str, Any]:
        row = self.db.fetchone("SELECT * FROM runtime_settings WHERE id = 1")
        if not row:
            raise RuntimeError("Runtime settings row is missing")
        provider_policy = str(row.get("provider_policy") or "codex_only")
        consent_granted = bool(
            row.get("cursor_consent_version") == 1
            and row.get("cursor_consent_granted_at")
        )
        if self.desktop_mode:
            provider_order = (
                ["codex_cli", "cursor_cli"]
                if provider_policy == "codex_then_cursor" and consent_granted
                else ["codex_cli"]
            )
            fallback_enabled = len(provider_order) == 2
        else:
            try:
                provider_order = json.loads(str(row["provider_order_json"]))
            except json.JSONDecodeError:
                provider_order = ["codex_cli", "cursor_cli"]
            fallback_enabled = bool(row["fallback_enabled"])
        return {
            "revision": int(row["revision"]),
            "provider_order": provider_order,
            "fallback_enabled": fallback_enabled,
            "provider_policy": (
                provider_policy if self.desktop_mode else None
            ),
            "cursor_fallback_consent": {
                "subject": "cursor_cli_fallback",
                "version": 1,
                "granted": consent_granted,
                "granted_at": (
                    row.get("cursor_consent_granted_at")
                    if consent_granted
                    else None
                ),
            },
            "concurrency": int(row["concurrency"]),
            "embedding_model": row["embedding_model"],
        }

    def embedding_status(self) -> dict[str, Any]:
        row = self.db.fetchone("SELECT * FROM embedding_state WHERE id = 1")
        if not row:
            return {
                "status": "unknown",
                "desired_model": None,
                "active_model": None,
                "error": "embedding state is missing",
            }
        return {
            "status": row["status"],
            "desired_model": row["desired_model"],
            "active_model": row["active_model"],
            "error": _status_error(row["error"], self.settings),
            "last_job_id": row["last_job_id"],
            "corpus_revision": int(row["corpus_revision"]),
            "indexed_revision": int(row["indexed_revision"]),
            "scope": "global",
            "hybrid_ready": bool(
                self.settings.qmd_hybrid_enabled
                and self.retriever.available
                and row["status"] == "ready"
                and row["active_model"] == row["desired_model"]
                and int(row["indexed_revision"]) == int(row["corpus_revision"])
            ),
        }

    def patch_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        supplied_revision = payload.pop("expected_revision", None)
        allowed = (
            {
                "provider_policy",
                "cursor_fallback_consent",
                "concurrency",
                "embedding_model",
            }
            if self.desktop_mode
            else {
                "provider_order",
                "fallback_enabled",
                "concurrency",
                "embedding_model",
            }
        )
        if any(key not in allowed for key in payload):
            raise ValidationError("Unknown runtime setting")
        if payload.get("concurrency") not in {None, 1}:
            raise ValidationError("This release supports concurrency=1 only")
        provider_order = payload.get("provider_order")
        if provider_order is not None and (
            not isinstance(provider_order, list)
            or not provider_order
            or len(provider_order) != len(set(provider_order))
            or any(
                item not in {"codex_cli", "cursor_cli", "mock", "ollama"}
                for item in provider_order
            )
        ):
            raise ValidationError("provider_order is invalid")
        model = payload.get("embedding_model")
        if model is not None:
            model = self.validate_embedding_model(str(model))[
                "canonical_model"
            ]
        now = utcnow()
        with self.db.transaction() as connection:
            current = connection.execute(
                "SELECT * FROM runtime_settings WHERE id = 1"
            ).fetchone()
            if current is None:
                raise RuntimeError("Runtime settings row is missing")
            expected_revision = int(
                supplied_revision
                if supplied_revision is not None
                else current["revision"]
            )
            if int(current["revision"]) != expected_revision:
                raise ConflictError("Settings revision changed; reload and retry")
            provider_policy = str(
                current["provider_policy"] or "codex_only"
            )
            cursor_consent_version = current["cursor_consent_version"]
            cursor_consent_granted_at = current[
                "cursor_consent_granted_at"
            ]
            if self.desktop_mode:
                requested_policy = payload.get("provider_policy")
                if requested_policy is not None:
                    provider_policy = str(requested_policy)
                consent_change = payload.get("cursor_fallback_consent")
                if consent_change is True:
                    cursor_consent_version = 1
                    cursor_consent_granted_at = now
                elif consent_change is False:
                    cursor_consent_version = None
                    cursor_consent_granted_at = None
                    if requested_policy is None:
                        provider_policy = "codex_only"
                if provider_policy not in {
                    "codex_only",
                    "codex_then_cursor",
                }:
                    raise ValidationError("provider_policy is invalid")
                if provider_policy == "codex_then_cursor" and not (
                    cursor_consent_version == 1
                    and cursor_consent_granted_at
                ):
                    raise ValidationError(
                        "Current explicit Cursor fallback consent is required"
                    )
                provider_order = (
                    ["codex_cli", "cursor_cli"]
                    if provider_policy == "codex_then_cursor"
                    else ["codex_cli"]
                )
            values = {
                "provider_order_json": (
                    json.dumps(provider_order)
                    if provider_order is not None
                    else current["provider_order_json"]
                ),
                "fallback_enabled": (
                    int(provider_policy == "codex_then_cursor")
                    if self.desktop_mode
                    else (
                        int(bool(payload["fallback_enabled"]))
                        if "fallback_enabled" in payload
                        else current["fallback_enabled"]
                    )
                ),
                "provider_policy": provider_policy,
                "cursor_consent_version": cursor_consent_version,
                "cursor_consent_granted_at": cursor_consent_granted_at,
                "concurrency": (
                    int(payload["concurrency"])
                    if payload.get("concurrency") is not None
                    else current["concurrency"]
                ),
                "embedding_model": (
                    str(model) if model is not None else current["embedding_model"]
                ),
            }
            cursor = connection.execute(
                """
                UPDATE runtime_settings
                SET revision = revision + 1, provider_order_json = ?,
                    fallback_enabled = ?, provider_policy = ?,
                    cursor_consent_version = ?,
                    cursor_consent_granted_at = ?, concurrency = ?,
                    embedding_model = ?, updated_at = ?
                WHERE id = 1 AND revision = ?
                """,
                (
                    values["provider_order_json"],
                    values["fallback_enabled"],
                    values["provider_policy"],
                    values["cursor_consent_version"],
                    values["cursor_consent_granted_at"],
                    values["concurrency"],
                    values["embedding_model"],
                    now,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Settings revision changed; reload and retry")
            if model is not None and model != current["embedding_model"]:
                published = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM versions WHERE status = 'published'"
                    ).fetchone()[0]
                )
                connection.execute(
                    """
                    UPDATE embedding_state
                    SET desired_model = ?, status = ?,
                        active_model = CASE WHEN ? = 0 THEN ? ELSE active_model END,
                        indexed_revision = CASE
                            WHEN ? = 0 THEN corpus_revision
                            ELSE indexed_revision
                        END,
                        error = NULL, updated_at = ?
                    WHERE id = 1
                    """,
                    (
                        model,
                        "ready" if published == 0 else "stale",
                        published,
                        model,
                        published,
                        now,
                    ),
                )
        return {
            **self.get_settings(),
            "embedding": self.embedding_status(),
        }

    def _provider_heartbeat(self) -> dict[str, Any]:
        path = self.settings.resolved_runner_dir / "heartbeat.json"
        if not path.is_file() or path.is_symlink():
            return {"status": "unhealthy", "providers": {}}
        try:
            if path.stat().st_size > 64_000:
                raise ValueError("heartbeat too large")
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {"status": "unhealthy", "providers": {}}
        updated_at = payload.get("updated_at")
        if (
            payload.get("schema_version") != 1
            or payload.get("status") != "ready"
            or not isinstance(updated_at, (int, float))
            or updated_at > time.time() + 5
            or time.time() - updated_at > 30
        ):
            return {"status": "unhealthy", "providers": {}}
        providers = payload.get("providers", {})
        safe_providers: dict[str, Any] = {}
        if isinstance(providers, dict):
            for name in ("codex_cli", "cursor_cli"):
                item = providers.get(name)
                if isinstance(item, dict):
                    authenticated = item.get("authenticated")
                    version = item.get("version")
                    safe_providers[name] = {
                        "installed": bool(item.get("installed")),
                        "authenticated": (
                            authenticated
                            if authenticated is None
                            or isinstance(authenticated, bool)
                            else None
                        ),
                        "usable": bool(item.get("usable")),
                        "version": (
                            str(version).replace("\r", "").replace("\n", " ")[:120]
                            if version is not None
                            else None
                        ),
                    }
        return {
            "status": "ready",
            "updated_at": updated_at,
            "providers": safe_providers,
        }

    def _runner_active_task(self) -> str | None:
        """Read only the runner task ID for duplicate-billing protection."""

        path = self.settings.resolved_runner_dir / "heartbeat.json"
        if not path.is_file() or path.is_symlink():
            return None
        try:
            if path.stat().st_size > 64_000:
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
            updated_at = payload.get("updated_at")
            active_task = payload.get("active_task")
        except (OSError, json.JSONDecodeError):
            return None
        if (
            payload.get("schema_version") != 1
            or payload.get("status") != "ready"
            or not isinstance(updated_at, (int, float))
            or updated_at > time.time() + 5
            or time.time() - updated_at > 30
            or not isinstance(active_task, str)
            or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", active_task
            )
        ):
            return None
        return active_task

    def system_status(self) -> dict[str, Any]:
        counts = self.db.fetchall(
            "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status"
        )
        queue = {str(row["status"]): int(row["count"]) for row in counts}
        providers = (
            {
                "status": "managed",
                "providers": {},
                "policy": self.get_settings()["provider_policy"],
            }
            if self.desktop_mode
            else self._provider_heartbeat()
        )
        embedding = self.embedding_status()
        runtime = self.get_settings()
        ordered_providers = runtime["provider_order"]
        runner_required = bool(
            ordered_providers
            and ordered_providers[0] in {"codex_cli", "cursor_cli"}
        )
        usable_cli = any(
            bool(providers["providers"].get(provider, {}).get("usable"))
            for provider in ordered_providers
            if provider in {"codex_cli", "cursor_cli"}
        )
        ready = self.desktop_mode or not runner_required or (
            providers["status"] == "ready" and usable_cli
        )
        checks = [
            {
                "id": "database",
                "label": "Database",
                "status": "ok",
                "message": "SQLite metadata store is ready",
            },
            {
                "id": "host-runner",
                "label": (
                    "Desktop CLI broker"
                    if self.desktop_mode
                    else "Host CLI runner"
                ),
                "status": (
                    "ok"
                    if self.desktop_mode
                    or (
                        providers["status"] == "ready"
                        and (usable_cli or not runner_required)
                    )
                    else ("error" if runner_required else "optional")
                ),
                "message": (
                    (
                        "Codex login is checked locally when a job starts; "
                        "Cursor is considered only with explicit consent"
                    )
                    if self.desktop_mode
                    else "At least one configured CLI provider is usable"
                    if providers["status"] == "ready" and usable_cli
                    else (
                        "Host CLI runner is healthy but no configured CLI is usable"
                        if providers["status"] == "ready" and runner_required
                        else "Host CLI runner is unavailable"
                    )
                ),
            },
            {
                "id": "qmd",
                "label": "Search index",
                "status": (
                    "ok"
                    if self.retriever.available
                    else ("optional" if not self.settings.qmd_enabled else "warning")
                ),
                "message": (
                    "QMD is available"
                    if self.retriever.available
                    else "Queries will use deterministic lexical retrieval"
                ),
            },
            {
                "id": "embedding",
                "label": "Embedding",
                "status": (
                    "ok"
                    if embedding["status"] == "ready"
                    else "warning"
                ),
                "message": f"Global embedding state: {embedding['status']}",
            },
        ]
        return {
            "ready": ready,
            "initialized": True,
            "version": APP_VERSION,
            "queue": {
                "queued": queue.get("queued", 0),
                "running": queue.get("running", 0),
                "cancelling": queue.get("cancelling", 0),
                "worker_running": bool(
                    self.dispatcher is not None and self.dispatcher.active
                ),
                "concurrency": 1,
            },
            "providers": providers,
            "embedding": embedding,
            "checks": checks,
        }

    def recover_orphaned_jobs(self) -> dict[str, Any]:
        """Fail active rows whose owning API process no longer holds its lock.

        Queued rows belong to the durable FIFO and are deliberately preserved.
        A running/cancelling row also records the worker runtime in its sidecar;
        a missing/corrupt owner or an acquirable owner lock means execution was
        interrupted and must fail closed before an explicit retry.
        """

        recovered: list[str] = []
        preserved: list[str] = []
        try:
            recovery_lock = filesystem_lock(
                lock_path(self.settings.locks_dir, "__jobs__", "recovery"),
                blocking=True,
                timeout_seconds=30,
            )
            with recovery_lock:
                for job in self.active_jobs():
                    if job["status"] == "queued":
                        preserved.append(str(job["id"]))
                        continue
                    control_path = self.settings.jobs_dir / f"{job['id']}.json"
                    owner = ""
                    try:
                        control = json.loads(control_path.read_text(encoding="utf-8"))
                        if isinstance(control, dict):
                            owner = str(control.get("owner_instance") or "")
                    except (OSError, TypeError, ValueError, json.JSONDecodeError):
                        owner = ""
                    if owner == self.instance_id:
                        preserved.append(str(job["id"]))
                        continue
                    owner_alive = False
                    if owner:
                        try:
                            with filesystem_lock(
                                lock_path(
                                    self.settings.locks_dir,
                                    owner,
                                    "runtime",
                                ),
                                blocking=False,
                            ):
                                pass
                        except LockUnavailable:
                            owner_alive = True
                    if owner_alive:
                        preserved.append(str(job["id"]))
                        continue
                    changed = self._mark_job_failed(
                        str(job["id"]),
                        stage="orphaned",
                        message="Ingest executor was lost before reaching a terminal state",
                        error=(
                            "Recovered an interrupted worker job; retry it after "
                            "checking the previous snapshot/proposals"
                        ),
                    )
                    if changed:
                        recovered.append(str(job["id"]))
        except LockUnavailable as error:
            raise ConflictError(
                "Timed out waiting to recover orphaned ingest jobs"
            ) from error
        activated_versions = self.recover_ready_versions()
        return {
            "recovered_count": len(recovered),
            "recovered_jobs": recovered,
            "preserved_count": len(preserved),
            "preserved_jobs": preserved,
            "activated_version_count": len(activated_versions),
            "activated_versions": activated_versions,
        }

    def recover_ready_versions(self) -> list[str]:
        """Finish the visibility pointer after a crash past the last page."""

        rows = self.db.fetchall(
            """
            SELECT versions.id, versions.version, versions.library_id
            FROM versions
            WHERE versions.status IN ('publishing', 'partial')
              AND EXISTS (
                  SELECT 1 FROM proposals
                  WHERE proposals.version_id = versions.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM proposals
                  WHERE proposals.version_id = versions.id
                    AND proposals.status != 'published'
              )
            ORDER BY versions.created_at, versions.id
            """
        )
        activated: list[str] = []
        for row in rows:
            library_id = str(row["library_id"])
            thread_lock = self._publish_lock_for_library(library_id)
            if not thread_lock.acquire(blocking=False):
                continue
            try:
                try:
                    with filesystem_lock(
                        lock_path(
                            self.settings.locks_dir,
                            library_id,
                            "publish",
                        ),
                        blocking=False,
                    ):
                        result = self._activate_reviewed_version_if_complete(
                            library_id=library_id,
                            version_id=str(row["id"]),
                            version=str(row["version"]),
                        )
                except LockUnavailable:
                    continue
                if result["activated"]:
                    activated.append(str(row["id"]))
            finally:
                thread_lock.release()
        return activated

    def _lock_for_library(self, library_id: str) -> threading.Lock:
        with self._ingest_locks_guard:
            return self._ingest_locks.setdefault(library_id, threading.Lock())

    def _publish_lock_for_library(self, library_id: str) -> threading.Lock:
        with self._publish_locks_guard:
            return self._publish_locks.setdefault(library_id, threading.Lock())

    @staticmethod
    def _library_output(row: dict[str, Any]) -> dict[str, Any]:
        return dict(row)

    @staticmethod
    def _evidence_ranges_for_page(
        page: dict[str, Any], allowed_ranges: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        refs = page.get("source_refs", [])
        if not isinstance(refs, list):
            return selected
        for allowed in allowed_ranges:
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                try:
                    covered = (
                        str(ref["path"]) == str(allowed["path"])
                        and int(allowed["line_start"]) <= int(ref["line_start"])
                        and int(ref["line_end"]) <= int(allowed["line_end"])
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                if covered:
                    selected.append(dict(allowed))
                    break
        return selected

    def create_library(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with filesystem_lock(
                lock_path(self.settings.locks_dir, "__catalog__", "create"),
                blocking=True,
                timeout_seconds=30,
            ):
                return self._create_library_locked(payload)
        except LockUnavailable as error:
            raise ConflictError("Timed out waiting to create a library") from error

    def _create_library_locked(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        source = str(payload.get("source", "")).strip()
        if not name or not source:
            raise ValidationError("name and source are required")
        try:
            validate_source_location(self.settings, source)
        except SourceError as error:
            raise ValidationError(str(error)) from error
        base_slug = slugify(str(payload.get("slug") or name))
        slug = base_slug
        counter = 2

        def slug_reserved(candidate: str) -> bool:
            return bool(
                self.db.fetchone(
                    "SELECT id FROM libraries WHERE slug = ?", (candidate,)
                )
                or (self.settings.sources_dir / candidate).exists()
                or (self.settings.facts_dir / candidate).exists()
                or (self.settings.wiki_dir / candidate).exists()
            )

        while slug_reserved(slug):
            if payload.get("slug"):
                raise ConflictError(
                    f"Library slug or preserved on-disk data already exists: {slug}"
                )
            slug = f"{base_slug}-{counter}"
            counter += 1
        now = utcnow()
        library = {
            "id": _identifier(),
            "name": name,
            "slug": slug,
            "context7_id": f"/local/{slug}",
            "source": source,
            "description": str(payload.get("description") or ""),
            "default_version": None,
            "created_at": now,
            "updated_at": now,
        }
        with self.db.transaction() as connection:
            connection.execute(
                """
                INSERT INTO libraries (
                    id, name, slug, context7_id, source, description,
                    default_version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(library.values()),
            )
        return library

    def list_libraries(self, search: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM libraries"
        parameters: tuple[object, ...] = ()
        if search:
            pattern = f"%{search.strip().lower()}%"
            query += (
                " WHERE lower(name) LIKE ? OR lower(slug) LIKE ? "
                "OR lower(context7_id) LIKE ? OR lower(description) LIKE ?"
            )
            parameters = (pattern, pattern, pattern, pattern)
        query += " ORDER BY updated_at DESC, name"
        rows = self.db.fetchall(query, parameters)
        for row in rows:
            counts = self.db.fetchone(
                """
                SELECT
                    COUNT(DISTINCT pages.version) AS versions,
                    COUNT(*) AS pages
                FROM pages
                JOIN versions ON versions.id = pages.version_id
                WHERE pages.library_id = ? AND versions.status = 'published'
                """,
                (row["id"],),
            )
            row["version_count"] = int(counts["versions"] or 0) if counts else 0
            row["page_count"] = int(counts["pages"] or 0) if counts else 0
        return rows

    def resolve_library(self, identifier: str) -> dict[str, Any]:
        normalized = identifier
        row = self.db.fetchone(
            """
            SELECT * FROM libraries
            WHERE id = ? OR slug = ? OR context7_id = ?
            """,
            (normalized, normalized, normalized),
        )
        if row:
            return row
        raise NotFoundError(f"Library not found: {identifier}")

    def get_library(self, identifier: str) -> dict[str, Any]:
        library = self.resolve_library(identifier)
        versions = self.db.fetchall(
            """
            SELECT id, version, source_sha, snapshot_path, facts_path,
                   wiki_path, status, created_at, published_at
            FROM versions WHERE library_id = ?
            ORDER BY created_at DESC
            """,
            (library["id"],),
        )
        result = dict(library)
        result["versions"] = versions
        return result

    def update_library(
        self, identifier: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        library = self.resolve_library(identifier)
        allowed = {"name", "source", "description", "default_version"}
        values = {
            key: value
            for key, value in payload.items()
            if key in allowed and value is not None
        }
        if not values:
            return self.get_library(library["id"])
        if "name" in values and not str(values["name"]).strip():
            raise ValidationError("name cannot be empty")
        if "source" in values and not str(values["source"]).strip():
            raise ValidationError("source cannot be empty")
        if "source" in values:
            try:
                validate_source_location(self.settings, str(values["source"]))
            except SourceError as error:
                raise ValidationError(str(error)) from error
        if "default_version" in values and not str(values["default_version"]).strip():
            raise ValidationError("default_version cannot be empty")
        if values.get("default_version"):
            published = self.list_pages(library["id"], str(values["default_version"]))
            if not published:
                raise ValidationError(
                    "default_version must name an already published version"
                )
            resolved_default = str(published[0]["version"])
            version_state = self.db.fetchone(
                """
                SELECT status FROM versions
                WHERE library_id = ? AND version = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (library["id"], resolved_default),
            )
            if not version_state or version_state["status"] != "published":
                raise ValidationError(
                    "default_version must name a fully published version"
                )
            values["default_version"] = resolved_default
        values["updated_at"] = utcnow()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self.db.transaction() as connection:
            connection.execute(
                f"UPDATE libraries SET {assignments} WHERE id = ?",
                (*values.values(), library["id"]),
            )
        return self.get_library(library["id"])

    def delete_library(self, identifier: str, *, purge: bool = False) -> dict[str, Any]:
        try:
            with filesystem_lock(
                lock_path(self.settings.locks_dir, "__catalog__", "create"),
                blocking=True,
                timeout_seconds=30,
            ):
                return self._delete_library_catalog_locked(
                    identifier, purge=purge
                )
        except LockUnavailable as error:
            raise ConflictError("Timed out waiting to delete a library") from error

    def _delete_library_catalog_locked(
        self, identifier: str, *, purge: bool = False
    ) -> dict[str, Any]:
        library = self.resolve_library(identifier)
        ingest_lock = self._lock_for_library(str(library["id"]))
        publish_lock = self._publish_lock_for_library(str(library["id"]))
        if not ingest_lock.acquire(blocking=False):
            raise ConflictError("Library is currently ingesting and cannot be deleted")
        if not publish_lock.acquire(blocking=False):
            ingest_lock.release()
            raise ConflictError("Library is currently publishing and cannot be deleted")
        try:
            try:
                with filesystem_lock(
                    lock_path(
                        self.settings.locks_dir, str(library["id"]), "ingest"
                    ),
                    blocking=False,
                ), filesystem_lock(
                    lock_path(
                        self.settings.locks_dir, str(library["id"]), "publish"
                    ),
                    blocking=False,
                ):
                    return self._delete_library_locked(
                        str(library["id"]), purge=purge
                    )
            except LockUnavailable as error:
                raise ConflictError(
                    "Library is busy in another API process and cannot be deleted"
                ) from error
        finally:
            publish_lock.release()
            ingest_lock.release()

    def _delete_library_locked(
        self, identifier: str, *, purge: bool = False
    ) -> dict[str, Any]:
        library = self.resolve_library(identifier)
        jobs = self.db.fetchall(
            "SELECT id, status FROM jobs WHERE library_id = ?", (library["id"],)
        )
        active_jobs = [
            str(item["id"])
            for item in jobs
            if item["status"] in {"queued", "running", "cancelling"}
        ]
        if active_jobs:
            raise ConflictError(
                "Library has queued, running, or cancelling jobs; wait for a "
                "terminal state before deleting it"
            )
        proposals = self.db.fetchall(
            "SELECT id, job_id FROM proposals WHERE library_id = ?",
            (library["id"],),
        )
        versions = self.db.fetchall(
            "SELECT id, version, status FROM versions WHERE library_id = ?",
            (library["id"],),
        )
        job_ids = {str(item["id"]) for item in jobs}
        job_ids.update(str(item["job_id"]) for item in proposals)
        proposal_ids = {str(item["id"]) for item in proposals}
        qmd_names = sorted(
            {
                collection_name(str(library["slug"]), str(item["version"]))
                for item in versions
            }
        )
        with self.db.transaction() as connection:
            connection.execute("DELETE FROM libraries WHERE id = ?", (library["id"],))
            if any(item["status"] == "published" for item in versions):
                connection.execute(
                    """
                    UPDATE embedding_state
                    SET status = 'stale',
                        corpus_revision = corpus_revision + 1,
                        error = 'Published corpus changed; rebuild required',
                        updated_at = ?
                    WHERE id = 1
                    """,
                    (utcnow(),),
                )
        removed_paths: list[str] = []
        missing_paths: list[str] = []
        failed_paths: list[dict[str, str]] = []
        qmd_results: list[dict[str, Any]] = []
        if purge:
            targets = [
                self.settings.sources_dir / library["slug"],
                self.settings.facts_dir / library["slug"],
                self.settings.wiki_dir / library["slug"],
            ]
            targets.extend(
                self.settings.proposals_dir / job_id for job_id in sorted(job_ids)
            )
            targets.extend(
                candidate
                for proposal_id in sorted(proposal_ids)
                if (candidate := self.settings.proposals_dir / proposal_id).exists()
                or candidate.is_symlink()
            )
            for job_id in sorted(job_ids):
                targets.extend(
                    [
                        self.settings.jobs_dir / f"{job_id}.json",
                        self.settings.jobs_dir / f"{job_id}.validation.json",
                    ]
                )
            data_root = self.settings.data_dir.absolute()
            for target in targets:
                target_absolute = target.absolute()
                if not target_absolute.is_relative_to(data_root):
                    failed_paths.append(
                        {
                            "path": str(target),
                            "error": "refused path outside data directory",
                        }
                    )
                    continue
                if not target.exists() and not target.is_symlink():
                    missing_paths.append(str(target))
                    continue
                try:
                    if target.is_symlink() or target.is_file():
                        target.unlink()
                    else:
                        shutil.rmtree(target)
                    removed_paths.append(str(target))
                except OSError as error:
                    failed_paths.append(
                        {"path": str(target), "error": str(error)[:1000]}
                    )
            if not getattr(self.retriever, "desktop_broker", False):
                qmd_results = [
                    self.retriever.remove_collection(name) for name in qmd_names
                ]
        if getattr(self.retriever, "desktop_broker", False):
            qmd_results = [self.reconcile_desktop_retrieval()]
        return {
            "deleted": True,
            "id": library["id"],
            "purged": purge,
            "removed_paths": removed_paths,
            "missing_paths": missing_paths,
            "failed_paths": failed_paths,
            "qmd_collections": qmd_results,
            "collected_before_delete": {
                "jobs": len(jobs),
                "proposals": len(proposals),
                "versions": len(versions),
            },
            "secure_erase": False,
        }

    def create_ingest_job(
        self,
        library_id: str,
        *,
        version: str | None,
        ref: str,
        provider: str,
        auto_publish: bool,
        _retry_of: str | None = None,
        _attempt: int = 1,
        _notify: bool = True,
        _job_id: str | None = None,
    ) -> dict[str, Any]:
        with self._drain_guard:
            if not self._accepting_ingest:
                raise ConflictError(
                    "Ingest is temporarily drained for a consistent backup"
                )
        library = self.resolve_library(library_id)
        ingest_lock = self._lock_for_library(str(library["id"]))
        if not ingest_lock.acquire(blocking=False):
            raise ConflictError("Another ingest for this library is already running")
        try:
            try:
                with filesystem_lock(
                    lock_path(
                        self.settings.locks_dir, str(library["id"]), "ingest"
                    ),
                    blocking=False,
                ):
                    # The library may have been deleted between the optimistic
                    # lookup above and acquiring the cross-process lock.
                    library = self.resolve_library(str(library["id"]))
                    return self._create_ingest_job_locked(
                        library,
                        version=version,
                        ref=ref,
                        provider=provider,
                        auto_publish=auto_publish,
                        retry_of=_retry_of,
                        attempt=_attempt,
                        notify=_notify,
                        job_id=_job_id,
                    )
            except LockUnavailable as error:
                raise ConflictError(
                    "Another ingest for this library is running in another process"
                ) from error
        finally:
            ingest_lock.release()

    def _create_ingest_job_locked(
        self,
        library: dict[str, Any],
        *,
        version: str | None,
        ref: str,
        provider: str,
        auto_publish: bool,
        retry_of: str | None = None,
        attempt: int = 1,
        notify: bool = True,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        with self._drain_guard:
            if not self._accepting_ingest:
                raise ConflictError(
                    "Ingest is temporarily drained for a consistent backup"
                )
            if provider == "codex":
                provider = "codex_cli"
            if provider == "cursor":
                provider = "cursor_cli"
            desktop_authorization: dict[str, Any] = {}
            if self.desktop_mode:
                if provider not in {"auto", "codex_cli", "mock"}:
                    raise ValidationError(
                        "Desktop jobs support the default Codex policy, "
                        "explicit Codex, or the internal deterministic "
                        "packaging self-test provider"
                    )
                runtime = self.get_settings()
                requested_policy = (
                    "codex_only"
                    if provider == "codex_cli"
                    else str(runtime["provider_policy"])
                )
                consent = runtime["cursor_fallback_consent"]
                desktop_authorization = {
                    "desktop_provider_policy": requested_policy,
                    "cursor_consent_version": (
                        consent["version"]
                        if requested_policy == "codex_then_cursor"
                        and consent["granted"]
                        else None
                    ),
                    "cursor_consent_granted_at": (
                        consent["granted_at"]
                        if requested_policy == "codex_then_cursor"
                        and consent["granted"]
                        else None
                    ),
                }
            elif provider == "auto":
                runtime = self.get_settings()
                provider_order = runtime["provider_order"]
                preferred = str(provider_order[0])
                if (
                    not runtime["fallback_enabled"]
                    or preferred != "codex_cli"
                ):
                    provider = preferred
            if provider not in {
                "auto",
                "mock",
                "ollama",
                "codex_cli",
                "cursor_cli",
            }:
                raise ValidationError(f"Unknown provider: {provider}")
            if version is not None:
                version = str(version).strip()
                if not version or any(
                    character in version for character in "\0\r\n"
                ):
                    raise ValidationError("version must be a non-empty single line")
            ref = str(ref).strip()
            if (
                not ref
                or ref.startswith("-")
                or any(character in ref for character in "\0\r\n")
            ):
                raise ValidationError("ref must be a non-empty safe Git ref")
            provisional_version = version or (ref if ref != "HEAD" else "pending")
            now = utcnow()
            request_payload = {
                "schema_version": 1,
                "kind": "ingest",
                "library_id": library["id"],
                "source": library["source"],
                "version": version,
                "ref": ref,
                "provider": provider,
                "auto_publish": auto_publish,
                **desktop_authorization,
            }
            job = {
                "id": job_id or _identifier(),
                "library_id": library["id"],
                "version_id": None,
                "version": provisional_version,
                "provider": provider,
                "kind": "ingest",
                "request_json": json.dumps(request_payload, ensure_ascii=False),
                "attempt": attempt,
                "retry_of": retry_of,
                "status": "queued",
                "stage": "queued",
                "progress": 0,
                "message": "Waiting to ingest source",
                "error": None,
                "started_at": None,
                "finished_at": None,
                "cancel_requested_at": None,
                "result_json": None,
                "effective_provider": None,
                "fallback_reason": None,
                "created_at": now,
                "updated_at": now,
            }
            with self.db.transaction() as connection:
                queue_seq = self._next_queue_seq(connection)
                job["queue_seq"] = queue_seq
                connection.execute(
                    """
                    INSERT INTO jobs (
                        id, library_id, version_id, version, provider, status,
                        stage, progress, message, error, created_at, updated_at,
                        kind, queue_seq, request_json, attempt, retry_of,
                        started_at, finished_at, cancel_requested_at,
                        result_json, effective_provider, fallback_reason
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        job["id"],
                        job["library_id"],
                        job["version_id"],
                        job["version"],
                        job["provider"],
                        job["status"],
                        job["stage"],
                        job["progress"],
                        job["message"],
                        job["error"],
                        job["created_at"],
                        job["updated_at"],
                        job["kind"],
                        job["queue_seq"],
                        job["request_json"],
                        job["attempt"],
                        job["retry_of"],
                        job["started_at"],
                        job["finished_at"],
                        job["cancel_requested_at"],
                        job["result_json"],
                        job["effective_provider"],
                        job["fallback_reason"],
                    ),
                )
            # Keep the complete immutable job input outside the mutable library
            # row. If the control file cannot be committed, remove the queued
            # DB row so no incomplete job can be picked up later.
            try:
                atomic_write_json(
                    self.settings.jobs_dir / f"{job['id']}.json",
                    {
                        "job_id": job["id"],
                        "library_id": library["id"],
                        "owner_instance": self.instance_id,
                        "source": library["source"],
                        "version": version,
                        "ref": ref,
                        "provider": provider,
                        "auto_publish": auto_publish,
                        **desktop_authorization,
                    },
                )
            except OSError:
                with self.db.transaction() as connection:
                    connection.execute(
                        "DELETE FROM jobs WHERE id = ?", (job["id"],)
                    )
                raise
            if notify and self.dispatcher is not None:
                self.dispatcher.notify()
            return self._job_output(job)

    @staticmethod
    def _next_queue_seq(connection: Any) -> int:
        row = connection.execute(
            "SELECT value FROM queue_counter WHERE id = 1"
        ).fetchone()
        current = int(row["value"] if row else 0) + 1
        connection.execute(
            """
            INSERT INTO queue_counter(id, value) VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET value = excluded.value
            """,
            (current,),
        )
        return current

    def _update_job(self, job_id: str, **values: Any) -> None:
        values["updated_at"] = utcnow()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self.db.transaction() as connection:
            connection.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",
                (*values.values(), job_id),
            )

    def _claim_queued_job(self, job_id: str) -> bool:
        now = utcnow()
        with self.db.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, stage = ?, progress = ?, message = ?,
                    error = NULL, started_at = COALESCE(started_at, ?),
                    effective_provider = NULL, fallback_reason = NULL,
                    updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    "running",
                    "claim",
                    1,
                    "Claimed by an ingest worker",
                    now,
                    now,
                    job_id,
                    "queued",
                ),
            )
            return cursor.rowcount == 1

    def _mark_job_failed(
        self,
        job_id: str,
        *,
        stage: str,
        message: str,
        error: str,
    ) -> bool:
        now = utcnow()
        with self.db.transaction() as connection:
            connection.execute(
                """
                UPDATE versions
                SET status = CASE
                    WHEN status IN ('published', 'proposed') THEN status
                    WHEN EXISTS (
                        SELECT 1 FROM pages WHERE pages.version_id = versions.id
                    ) THEN 'partial'
                    ELSE 'failed'
                END
                WHERE id = (
                    SELECT version_id FROM jobs
                    WHERE id = ? AND status IN ('queued', 'running')
                )
                """,
                (job_id,),
            )
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, stage = ?, message = ?, error = ?,
                    finished_at = ?, updated_at = ?
                WHERE id = ? AND status IN ('queued', 'running', 'cancelling')
                """,
                ("failed", stage, message, error, now, now, job_id),
            )
            return cursor.rowcount == 1

    def _job_publication_state(self, job_id: str) -> tuple[int, bool]:
        row = self.db.fetchone(
            """
            SELECT
                j.version AS job_version,
                v.status AS version_status,
                l.default_version AS default_version,
                (
                    SELECT COUNT(*)
                    FROM proposals p
                    WHERE p.job_id = j.id AND p.status = 'published'
                ) AS published_count
            FROM jobs j
            JOIN libraries l ON l.id = j.library_id
            LEFT JOIN versions v ON v.id = j.version_id
            WHERE j.id = ?
            """,
            (job_id,),
        )
        if not row:
            return 0, False
        published_count = int(row["published_count"] or 0)
        activated = (
            row["version_status"] == "published"
            and row["default_version"] == row["job_version"]
        )
        return published_count, activated

    def _existing_wiki_baseline(
        self,
        library: dict[str, Any],
        target_version: str,
    ) -> list[dict[str, Any]]:
        pages = self.list_pages(library["id"], target_version)
        if not pages:
            previous_version = library.get("default_version")
            if previous_version and previous_version != target_version:
                pages = self.list_pages(library["id"], str(previous_version))
        remaining = max(0, self.settings.max_existing_wiki_bytes - 2)
        baseline: list[dict[str, Any]] = []
        for page in pages:
            separator_bytes = 1 if baseline else 0
            available = remaining - separator_bytes
            entry = {
                "path": page["path"],
                "title": page["title"],
                "kind": page["kind"],
                "summary": page["summary"],
                "markdown": "",
                "source_refs": page["metadata"].get("source_refs", []),
            }
            fixed_bytes = len(json.dumps(entry, ensure_ascii=False).encode("utf-8"))
            if fixed_bytes >= available:
                break
            markdown = page["markdown"]
            low, high = 0, len(markdown)
            while low < high:
                midpoint = (low + high + 1) // 2
                entry["markdown"] = markdown[:midpoint]
                candidate_size = len(
                    json.dumps(entry, ensure_ascii=False).encode("utf-8")
                )
                if candidate_size <= available:
                    low = midpoint
                else:
                    high = midpoint - 1
            entry["markdown"] = markdown[:low]
            used = len(json.dumps(entry, ensure_ascii=False).encode("utf-8"))
            baseline.append(entry)
            remaining -= used + separator_bytes
            if remaining < 512:
                break
        return baseline

    def _desktop_generator(
        self,
        *,
        job_id: str,
        version_id: str,
        provider: str,
        control: dict[str, Any],
    ) -> Any:
        if provider == "mock":
            # Used only by the frozen-package domain smoke. The shipped UI
            # never offers this deterministic provider.
            return get_generator(provider, self.settings)
        if provider not in {"auto", "codex_cli"}:
            raise GenerationError(
                "Desktop provider selection is outside the supported policy"
            )
        policy = "codex_only"
        consent_version: int | None = None
        consent_granted_at: str | None = None
        if (
            provider == "auto"
            and control.get("desktop_provider_policy")
            == "codex_then_cursor"
            and control.get("cursor_consent_version") == 1
            and isinstance(control.get("cursor_consent_granted_at"), str)
        ):
            current = self.get_settings()
            consent = current["cursor_fallback_consent"]
            if (
                current["provider_policy"] == "codex_then_cursor"
                and consent["granted"] is True
                and consent["version"] == 1
                and isinstance(consent["granted_at"], str)
            ):
                policy = "codex_then_cursor"
                consent_version = 1
                consent_granted_at = consent["granted_at"]
        state = self.db.fetchone(
            "SELECT corpus_revision FROM embedding_state WHERE id = 1"
        )
        if self.provider_attempts is None:
            raise GenerationError("Desktop provider broker is unavailable")
        return DesktopProviderGenerator(
            self.settings,
            self.provider_attempts,
            job_id=job_id,
            version_id=version_id,
            corpus_revision=int(state["corpus_revision"] if state else 0),
            policy=policy,
            cursor_consent_version=consent_version,
            cursor_consent_granted_at=consent_granted_at,
        )

    def run_ingest_job(
        self,
        job_id: str,
        *,
        version: str | None = None,
        ref: str | None = None,
        provider: str | None = None,
        auto_publish: bool | None = None,
    ) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job["status"] != "queued":
            return job
        control_path = self.settings.jobs_dir / f"{job_id}.json"
        control: dict[str, Any] = {}
        try:
            loaded_control = job.get("request") or {}
            if not isinstance(loaded_control, dict):
                raise TypeError("job control must be a JSON object")
            if loaded_control.get("schema_version") != 1:
                # Compatibility with pre-queue databases whose immutable
                # request lived only in the sidecar.
                if not control_path.is_file():
                    raise FileNotFoundError(
                        f"Missing job control file: {control_path}"
                    )
                loaded_control = json.loads(
                    control_path.read_text(encoding="utf-8")
                )
                if not isinstance(loaded_control, dict):
                    raise TypeError("job control must be a JSON object")
            control = loaded_control
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            self._mark_job_failed(
                job_id,
                stage="control",
                message="Ingest job control is unreadable",
                error=f"{type(error).__name__}: {error}",
            )
            return self.get_job(job_id)
        version = version if version is not None else control.get("version")
        ref = ref or control.get("ref") or "HEAD"
        provider = provider or control.get("provider") or job["provider"]
        auto_publish = (
            auto_publish
            if auto_publish is not None
            else bool(control.get("auto_publish", False))
        )
        library = self.resolve_library(job["library_id"])
        source = str(control.get("source") or library["source"])

        if not self._claim_queued_job(job_id):
            return self.get_job(job_id)
        try:
            atomic_write_json(
                control_path,
                {
                    **control,
                    "job_id": job_id,
                    "owner_instance": self.instance_id,
                },
            )
        except OSError as error:
            self._mark_job_failed(
                job_id,
                stage="control",
                message="Could not persist worker ownership",
                error=str(error),
            )
            return self.get_job(job_id)

        lock = self._lock_for_library(library["id"])
        if not lock.acquire(blocking=False):
            self._mark_job_failed(
                job_id,
                stage="lock",
                error="Another ingest for this library is already running",
                message="Concurrent ingest rejected",
            )
            return self.get_job(job_id)
        process_lock = ExitStack()
        try:
            process_lock.enter_context(
                filesystem_lock(
                    lock_path(
                        self.settings.locks_dir, str(library["id"]), "ingest"
                    ),
                    blocking=False,
                )
            )
        except (LockUnavailable, OSError):
            lock.release()
            self._mark_job_failed(
                job_id,
                stage="lock",
                error="Another ingest for this library is running in another process",
                message="Concurrent ingest rejected",
            )
            return self.get_job(job_id)
        generator: Any = None
        try:
            self._raise_if_cancelled(job_id)
            self._update_job(
                job_id,
                status="running",
                stage="snapshot",
                progress=8,
                message="Creating immutable source snapshot",
                error=None,
            )
            snapshot = create_snapshot(
                self.settings, library["slug"], source, ref
            )
            self._raise_if_cancelled(job_id)
            if version:
                requested_version = str(version)
                suffix = f"+git.{snapshot.source_sha[:12]}"
                resolved_version = (
                    requested_version
                    if requested_version.endswith(suffix)
                    else requested_version + suffix
                )
            else:
                resolved_version = snapshot.source_sha[:12]
            wiki = WikiStore(self.settings, library["slug"])
            version_row = self.db.fetchone(
                """
                SELECT * FROM versions
                WHERE library_id = ? AND version = ? AND source_sha = ?
                """,
                (library["id"], resolved_version, snapshot.source_sha),
            )
            if version_row is not None and version_row["status"] in {
                "proposed",
                "publishing",
                "partial",
                "published",
                "rejected",
            }:
                raise ValidationError(
                    "This source/version is already materialized. Continue its "
                    "existing review or use a new version label; immutable "
                    "materializations are never refreshed in place."
                )
            if version_row is None:
                version_row = {
                    "id": _identifier(),
                    "library_id": library["id"],
                    "version": resolved_version,
                    "source_sha": snapshot.source_sha,
                    "snapshot_path": str(snapshot.repo_path),
                    "facts_path": "",
                    "wiki_path": str(wiki.version_root(resolved_version)),
                    "status": "extracting",
                    "created_at": utcnow(),
                    "published_at": None,
                }
                with self.db.transaction() as connection:
                    connection.execute(
                        """
                        INSERT INTO versions (
                            id, library_id, version, source_sha, snapshot_path,
                            facts_path, wiki_path, status, created_at, published_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        tuple(version_row.values()),
                    )
            self._update_job(
                job_id,
                version_id=version_row["id"],
                version=resolved_version,
                stage="facts",
                progress=28,
                message="Extracting deterministic symbols and evidence",
            )
            facts = extract_facts(
                self.settings,
                library["slug"],
                snapshot.source_sha,
                snapshot.repo_path,
            )
            self._raise_if_cancelled(job_id)
            with self.db.transaction() as connection:
                connection.execute(
                    """
                    UPDATE versions
                    SET facts_path = ?,
                        status = CASE
                            WHEN status IN ('published', 'proposed') THEN status
                            ELSE 'generating'
                        END
                    WHERE id = ?
                    """,
                    (str(facts.root), version_row["id"]),
                )
            self._update_job(
                job_id,
                stage="generation",
                progress=50,
                message=f"Generating typed wiki proposals with {provider}",
            )
            generator = (
                self._desktop_generator(
                    job_id=job_id,
                    version_id=str(version_row["id"]),
                    provider=str(provider),
                    control=control,
                )
                if self.desktop_mode
                else get_generator(provider, self.settings)
            )
            existing_wiki = self._existing_wiki_baseline(library, resolved_version)
            generation_context = GenerationContext(
                library_name=library["name"],
                library_slug=library["slug"],
                version=resolved_version,
                source_sha=snapshot.source_sha,
                facts=facts,
                existing_wiki=existing_wiki,
                runner_id=job_id,
                cancel_check=lambda: self._cancel_requested(job_id),
            )
            evidence_ranges = generation_evidence_ranges(
                generation_context, self.settings, provider
            )
            generated = generator.generate(generation_context)
            effective_provider = str(
                getattr(generator, "effective_provider", None) or provider
            )
            fallback_reason = (
                str(getattr(generator, "fallback_reason", None) or "") or None
            )
            self._update_job(
                job_id,
                effective_provider=effective_provider,
                fallback_reason=fallback_reason,
            )
            self._raise_if_cancelled(job_id)
            if not isinstance(generated, list) or not 1 <= len(generated) <= 80:
                raise ValidationError(
                    "Generator must return between 1 and 80 page proposals"
                )
            if not all(isinstance(item, dict) for item in generated):
                raise ValidationError("Every generated page proposal must be an object")
            normalized: list[dict[str, Any]] = []
            seen_paths: set[str] = set()
            validation_issues: list[dict[str, str]] = []
            for raw_page in generated:
                page = normalize_page(raw_page)
                collision_key = portable_path_key(page["path"])
                if collision_key in seen_paths:
                    validation_issues.append(
                        {
                            "level": "error",
                            "code": "duplicate-page",
                            "message": f"Duplicate proposal path: {page['path']}",
                        }
                    )
                seen_paths.add(collision_key)
                page["source_sha"] = snapshot.source_sha
                issues = validate_page(
                    page,
                    snapshot_repo=snapshot.repo_path,
                    source_sha=snapshot.source_sha,
                    allowed_source_ranges=evidence_ranges,
                )
                validation_issues.extend(
                    [{**issue, "path": page["path"]} for issue in issues]
                )
                page["validation"] = issues
                page["generation_evidence_ranges"] = (
                    self._evidence_ranges_for_page(page, evidence_ranges)
                )
                normalized.append(page)
            errors = [issue for issue in validation_issues if issue["level"] == "error"]
            if errors:
                raise ValidationError(
                    "Generated wiki failed schema/source-reference validation "
                    f"({len(errors)} errors)",
                    validation_issues,
                )
            self._update_job(
                job_id,
                stage="proposal",
                progress=74,
                message=f"Persisting {len(normalized)} reviewable proposals",
            )
            proposal_root = self.settings.proposals_dir / job_id
            proposal_ids: list[str] = []
            now = utcnow()
            with self.db.transaction() as connection:
                for page in normalized:
                    proposal_id = _identifier()
                    proposal_ids.append(proposal_id)
                    metadata = {
                        "schema_version": 1,
                        "tags": page["tags"],
                        "source_refs": page["source_refs"],
                        "source_sha": snapshot.source_sha,
                        "version": resolved_version,
                        "generator_provider": effective_provider,
                        "requested_generator_provider": provider,
                        "generator_fallback_reason": fallback_reason,
                        "generation_evidence_ranges": page[
                            "generation_evidence_ranges"
                        ],
                        "validation": page["validation"],
                    }
                    connection.execute(
                        """
                        INSERT INTO proposals (
                            id, library_id, version_id, job_id, version,
                            source_sha, status, path, title, kind, summary,
                            markdown, metadata_json, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            proposal_id,
                            library["id"],
                            version_row["id"],
                            job_id,
                            resolved_version,
                            snapshot.source_sha,
                            "pending",
                            page["path"],
                            page["title"],
                            page["kind"],
                            page["summary"],
                            page["markdown"],
                            json.dumps(metadata, ensure_ascii=False),
                            now,
                            now,
                        ),
                    )
                    markdown_path = proposal_root / safe_page_path(page["path"])
                    atomic_write_text(markdown_path, page["markdown"].rstrip() + "\n")
                    atomic_write_json(
                        proposal_root
                        / "facts"
                        / Path(page["path"]).with_suffix(".json"),
                        {**metadata, "proposal_id": proposal_id, "path": page["path"]},
                    )
                connection.execute(
                    """
                    UPDATE versions
                    SET status = CASE
                        WHEN status = 'published' THEN status
                        ELSE 'proposed'
                    END
                    WHERE id = ?
                    """,
                    (version_row["id"],),
                )
                connection.execute(
                    "UPDATE libraries SET updated_at = ? WHERE id = ?",
                    (now, library["id"]),
                )

            if auto_publish:
                self._raise_if_cancelled(job_id)
                self._update_job(
                    job_id,
                    stage="publish",
                    progress=84,
                    message="Publishing validated proposals",
                )
                self._publish_proposal_batch(
                    library,
                    str(version_row["id"]),
                    resolved_version,
                    proposal_ids,
                )
                self._index_version(library, resolved_version)
            self._raise_if_cancelled(job_id)
            self._update_job(
                job_id,
                status="completed",
                stage="completed",
                progress=100,
                message=(
                    f"Published {len(proposal_ids)} pages"
                    if auto_publish
                    else f"Created {len(proposal_ids)} proposals for review"
                ),
                finished_at=utcnow(),
                result_json=json.dumps(
                    {
                        "version_id": version_row["id"],
                        "version": resolved_version,
                        "proposal_ids": proposal_ids,
                        "auto_publish": auto_publish,
                    },
                    ensure_ascii=False,
                ),
            )
        except (JobCancelled, GenerationCancelled):
            self._mark_job_cancelled(job_id)
        except (SourceError, GenerationError, ValidationError, OSError) as error:
            if generator is not None:
                self._update_job(
                    job_id,
                    effective_provider=getattr(
                        generator, "effective_provider", None
                    ),
                    fallback_reason=getattr(
                        generator, "fallback_reason", None
                    ),
                )
            if isinstance(error, ValidationError) and error.issues:
                try:
                    atomic_write_json(
                        self.settings.jobs_dir / f"{job_id}.validation.json",
                        error.issues,
                    )
                except OSError:
                    pass
            published_count, activated = self._job_publication_state(job_id)
            failure_message = "Ingest failed"
            if published_count and not activated:
                failure_message = (
                    f"Ingest failed after publishing {published_count} page(s); "
                    "the incomplete version was not activated as default"
                )
            self._mark_job_failed(
                job_id,
                stage="failed",
                message=failure_message,
                error=str(error),
            )
        except Exception as error:  # noqa: BLE001 - persist terminal job failure
            published_count, activated = self._job_publication_state(job_id)
            failure_message = "Unexpected ingest failure"
            if published_count and not activated:
                failure_message = (
                    "Unexpected ingest failure after publishing "
                    f"{published_count} page(s); the incomplete version was not "
                    "activated as default"
                )
            self._mark_job_failed(
                job_id,
                stage="failed",
                message=failure_message,
                error=f"{type(error).__name__}: {error}",
            )
        finally:
            process_lock.close()
            lock.release()
        return self.get_job(job_id)

    def _cancel_requested(self, job_id: str) -> bool:
        row = self.db.fetchone(
            "SELECT status, cancel_requested_at FROM jobs WHERE id = ?",
            (job_id,),
        )
        return bool(
            row
            and (
                row["status"] in {"cancelling", "cancelled"}
                or row["cancel_requested_at"]
            )
        )

    def _raise_if_cancelled(self, job_id: str) -> None:
        if self._cancel_requested(job_id):
            raise JobCancelled

    def _mark_job_cancelled(self, job_id: str) -> None:
        now = utcnow()
        with self.db.transaction() as connection:
            connection.execute(
                """
                UPDATE versions
                SET status = CASE
                    WHEN status IN ('published', 'proposed') THEN status
                    WHEN EXISTS (
                        SELECT 1 FROM pages WHERE pages.version_id = versions.id
                    ) THEN 'partial'
                    ELSE 'failed'
                END
                WHERE id = (SELECT version_id FROM jobs WHERE id = ?)
                """,
                (job_id,),
            )
            connection.execute(
                """
                UPDATE jobs
                SET status = 'cancelled', stage = 'cancelled',
                    message = 'Job cancelled by user', error = NULL,
                    finished_at = ?, updated_at = ?
                WHERE id = ? AND status IN ('running', 'cancelling')
                """,
                (now, now, job_id),
            )

    def dispatch_next_job(self) -> bool:
        with self._drain_guard:
            if not self._accepting_ingest:
                return False
        row = self.db.fetchone(
            """
            SELECT id, kind FROM jobs
            WHERE status = 'queued'
            ORDER BY queue_seq
            LIMIT 1
            """
        )
        if not row:
            return False
        if row["kind"] == "embedding_rebuild":
            self.run_rebuild_job(str(row["id"]))
        else:
            self.run_ingest_job(str(row["id"]))
        return True

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        now = utcnow()
        with self.db.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"Job not found: {job_id}")
            if row["status"] == "queued":
                connection.execute(
                    """
                    UPDATE jobs SET status = 'cancelled', stage = 'cancelled',
                        message = 'Cancelled before execution',
                        cancel_requested_at = ?, finished_at = ?, updated_at = ?
                    WHERE id = ? AND status = 'queued'
                    """,
                    (now, now, now, job_id),
                )
            elif row["status"] == "running":
                connection.execute(
                    """
                    UPDATE jobs SET status = 'cancelling',
                        cancel_requested_at = ?, message = 'Cancellation requested',
                        updated_at = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (now, now, job_id),
                )
            elif row["status"] not in {"cancelling", "cancelled"}:
                raise ConflictError("Only queued or running jobs can be cancelled")
        if self.provider_attempts is not None:
            attempt = self.db.fetchone(
                "SELECT id FROM provider_attempts WHERE job_id = ?",
                (job_id,),
            )
            if attempt is not None:
                self.provider_attempts.request_cancel(str(attempt["id"]))
        if self.dispatcher is not None:
            self.dispatcher.notify()
        return self.get_job(job_id)

    def retry_job(self, job_id: str) -> dict[str, Any]:
        try:
            with filesystem_lock(
                lock_path(self.settings.locks_dir, job_id, "retry"),
                blocking=True,
                timeout_seconds=30,
            ):
                existing = self.db.fetchone(
                    """
                    SELECT id FROM jobs
                    WHERE retry_of = ?
                    ORDER BY queue_seq LIMIT 1
                    """,
                    (job_id,),
                )
                if existing:
                    result = self.get_job(str(existing["id"]))
                    result["idempotent_retry"] = True
                    return result
                return self._retry_job_locked(job_id)
        except LockUnavailable as error:
            raise ConflictError(
                "Timed out waiting for another retry request"
            ) from error

    def _retry_job_locked(self, job_id: str) -> dict[str, Any]:
        original = self.get_job(job_id)
        if original["status"] not in {"failed", "cancelled"}:
            raise ConflictError("Only failed or cancelled jobs can be retried")
        if original["kind"] == "embedding_rebuild":
            request = original.get("request") or {}
            return self.create_rebuild_job(
                model=str(
                    request.get("model")
                    or self.get_settings()["embedding_model"]
                ),
                scope_library_id=request.get("scope_library_id"),
                retry_of=job_id,
                attempt=int(original.get("attempt") or 1) + 1,
            )
        if original.get("version_id"):
            proposal = self.db.fetchone(
                "SELECT id FROM proposals WHERE version_id = ? LIMIT 1",
                (original["version_id"],),
            )
            if proposal:
                raise ConflictError(
                    "This attempt already created reviewable material; continue "
                    "its review instead of regenerating it"
                )
        request = original.get("request") or {}
        requested_provider = str(
            request.get("provider") or original["provider"]
        )
        reusable_response = self._retry_runner_response(
            original, requested_provider
        )
        retry_id = _identifier()
        retry_response_path = (
            self.settings.runner_outbox_dir / f"{retry_id}.json"
        )
        if reusable_response is not None:
            reusable_response["id"] = retry_id
            atomic_write_json(
                retry_response_path,
                reusable_response,
            )
        try:
            retried = self.create_ingest_job(
                str(original["library_id"]),
                version=request.get("version"),
                ref=str(request.get("ref") or "HEAD"),
                provider=requested_provider,
                auto_publish=bool(request.get("auto_publish", False)),
                _retry_of=job_id,
                _attempt=int(original.get("attempt") or 1) + 1,
                _notify=False,
                _job_id=retry_id,
            )
        except Exception:
            if reusable_response is not None:
                try:
                    retry_response_path.unlink()
                except OSError:
                    pass
            raise
        if reusable_response is not None:
            old_response = (
                self.settings.runner_outbox_dir / f"{original['id']}.json"
            )
            try:
                old_response.unlink()
            except OSError:
                pass
        if self.dispatcher is not None:
            self.dispatcher.notify()
        return self.get_job(str(retried["id"]))

    def _retry_runner_response(
        self,
        original: dict[str, Any],
        requested_provider: str,
    ) -> dict[str, Any] | None:
        if self.desktop_mode:
            # Desktop provider attempts are single-use. A retry receives a new
            # job/attempt identity and never reuses a previous CLI result.
            return None
        if requested_provider not in {"auto", "codex_cli", "cursor_cli"}:
            return None
        old_id = str(original["id"])
        response_path = self.settings.runner_outbox_dir / f"{old_id}.json"
        inbox_path = self.settings.runner_inbox_dir / f"{old_id}.json"
        working_path = (
            self.settings.resolved_runner_dir / "working" / f"{old_id}.json"
        )
        if response_path.exists() or response_path.is_symlink():
            if response_path.is_symlink():
                raise ConflictError(
                    "Original runner response is an unsafe symlink"
                )
            try:
                if (
                    response_path.stat().st_size
                    > self.settings.runner_max_response_bytes
                ):
                    raise ValueError("response exceeds size limit")
                response = json.loads(
                    response_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError, json.JSONDecodeError) as error:
                raise ConflictError(
                    "Original runner response is unreadable; resolve it before retry"
                ) from error
            if (
                not isinstance(response, dict)
                or response.get("id") != old_id
                or response.get("task") != "wiki_v1"
                or response.get("requested_provider") != requested_provider
            ):
                raise ConflictError(
                    "Original runner response identity is inconsistent"
                )
            if not response.get("error") and isinstance(
                response.get("result"), dict
            ):
                return response
            return None
        if (
            self._runner_active_task() == old_id
            or inbox_path.exists()
            or inbox_path.is_symlink()
            or working_path.exists()
            or working_path.is_symlink()
        ):
            raise ConflictError(
                "The original host CLI request may still execute; wait for its "
                "terminal response before retrying to avoid duplicate usage"
            )
        return None

    def _job_output(self, row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for source_key, target_key in (
            ("request_json", "request"),
            ("result_json", "result"),
        ):
            raw = result.pop(source_key, None)
            try:
                result[target_key] = json.loads(str(raw)) if raw else None
            except json.JSONDecodeError:
                result[target_key] = None
        if result["status"] == "queued":
            position = self.db.fetchone(
                """
                SELECT COUNT(*) AS count FROM jobs
                WHERE status = 'queued' AND queue_seq <= ?
                """,
                (result["queue_seq"],),
            )
            result["queue_position"] = int(position["count"] if position else 0)
        else:
            result["queue_position"] = None
        result["cancellable"] = result["status"] in {"queued", "running", "cancelling"}
        has_proposals = bool(
            result.get("version_id")
            and self.db.fetchone(
                "SELECT id FROM proposals WHERE version_id = ? LIMIT 1",
                (result["version_id"],),
            )
        )
        result["retryable"] = (
            result["status"] in {"failed", "cancelled"} and not has_proposals
        )
        return result

    def get_job(self, job_id: str) -> dict[str, Any]:
        row = self.db.fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not row:
            raise NotFoundError(f"Job not found: {job_id}")
        return self._job_output(row)

    def list_jobs(
        self, library_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        if library_id is not None and not library_id.strip():
            raise ValidationError(
                "library_id cannot be empty; omit it to list jobs globally"
            )
        if library_id is not None:
            library = self.resolve_library(library_id)
            rows = self.db.fetchall(
                """
                SELECT * FROM jobs WHERE library_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (library["id"], limit),
            )
            return [self._job_output(row) for row in rows]
        rows = self.db.fetchall(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [self._job_output(row) for row in rows]

    @staticmethod
    def _decode_proposal(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["metadata"] = json.loads(str(result.pop("metadata_json")))
        return result

    def list_proposals(
        self,
        library_id: str,
        *,
        status: str | None = None,
        version: str | None = None,
    ) -> list[dict[str, Any]]:
        library = self.resolve_library(library_id)
        clauses = ["library_id = ?"]
        parameters: list[object] = [library["id"]]
        if status:
            clauses.append("status = ?")
            parameters.append(status)
        if version:
            clauses.append("version = ?")
            parameters.append(version)
        rows = self.db.fetchall(
            f"""
            SELECT * FROM proposals WHERE {" AND ".join(clauses)}
            ORDER BY created_at DESC, path
            """,
            tuple(parameters),
        )
        return [self._decode_proposal(row) for row in rows]

    def get_proposal(self, proposal_id: str) -> dict[str, Any]:
        row = self.db.fetchone("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        if not row:
            raise NotFoundError(f"Proposal not found: {proposal_id}")
        return self._decode_proposal(row)

    @staticmethod
    def _decode_page(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["metadata"] = json.loads(str(result.pop("metadata_json")))
        return result

    def list_pages(
        self, library_id: str, version: str | None = None
    ) -> list[dict[str, Any]]:
        library = self.resolve_library(library_id)
        if version is not None and not version.strip():
            raise ValidationError("version cannot be empty")
        requested_version = version
        resolved_version = version or library.get("default_version")
        if not resolved_version:
            return []
        rows = self.db.fetchall(
            """
            SELECT * FROM pages WHERE library_id = ? AND version = ?
            ORDER BY kind, path
            """,
            (library["id"], resolved_version),
        )
        if not rows and requested_version and "+git." not in requested_version:
            default_version = str(library.get("default_version") or "")
            if default_version.startswith(f"{requested_version}+git."):
                alias_version = default_version
            else:
                escaped = (
                    requested_version.replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )
                alias = self.db.fetchone(
                    """
                    SELECT version FROM versions
                    WHERE library_id = ?
                      AND version LIKE ? ESCAPE '\\'
                      AND status = 'published'
                    ORDER BY published_at DESC, created_at DESC
                    LIMIT 1
                    """,
                    (library["id"], f"{escaped}+git.%"),
                )
                alias_version = str(alias["version"]) if alias else ""
            if alias_version:
                rows = self.db.fetchall(
                    """
                    SELECT * FROM pages
                    WHERE library_id = ? AND version = ?
                    ORDER BY kind, path
                    """,
                    (library["id"], alias_version),
                )
        return [self._decode_page(row) for row in rows]

    def get_page(
        self, library_id: str, page_path: str, version: str | None = None
    ) -> dict[str, Any]:
        try:
            path = safe_page_path(page_path)
        except ValueError as error:
            raise ValidationError(str(error)) from error
        pages = self.list_pages(library_id, version)
        for page in pages:
            if page["path"] == path:
                return page
        raise NotFoundError(f"Page not found: {path}")

    def publish_proposal(
        self,
        proposal_id: str,
        *,
        reindex: bool = True,
    ) -> dict[str, Any]:
        proposal = self.get_proposal(proposal_id)
        with self._publish_lock_for_library(str(proposal["library_id"])):
            try:
                with filesystem_lock(
                    lock_path(
                        self.settings.locks_dir,
                        str(proposal["library_id"]),
                        "publish",
                    ),
                    blocking=True,
                    timeout_seconds=60,
                ):
                    proposal_before_publish = self.get_proposal(proposal_id)
                    version_before_publish = self.db.fetchone(
                        "SELECT status FROM versions WHERE id = ?",
                        (proposal_before_publish["version_id"],),
                    )
                    updates_published_version = bool(
                        proposal_before_publish["status"] != "published"
                        and version_before_publish
                        and version_before_publish["status"] == "published"
                    )
                    result = self._publish_proposal_locked(
                        proposal_id,
                        reindex=False,
                        activate_version=False,
                    )
                    current = self.get_proposal(proposal_id)
                    activation = self._activate_reviewed_version_if_complete(
                        library_id=str(current["library_id"]),
                        version_id=str(current["version_id"]),
                        version=str(current["version"]),
                    )
                    if updates_published_version:
                        with self.db.transaction() as connection:
                            connection.execute(
                                """
                                UPDATE embedding_state
                                SET status = 'stale',
                                    corpus_revision = corpus_revision + 1,
                                    error = 'Published corpus changed; rebuild required',
                                    updated_at = ?
                                WHERE id = 1
                                """,
                                (utcnow(),),
                            )
                    library = self.resolve_library(str(current["library_id"]))
                    result["activation"] = activation
                    result["index"] = (
                        self._index_version(library, str(current["version"]))
                        if (
                            (activation["activated"] or updates_published_version)
                            and reindex
                        )
                        else {
                            "indexed": False,
                            "reason": (
                                "deferred"
                                if (
                                    activation["activated"]
                                    or updates_published_version
                                )
                                else "version-not-active"
                            ),
                        }
                    )
                    return result
            except LockUnavailable as error:
                raise ConflictError(
                    "Timed out waiting for another API process to publish"
                ) from error
            except WikiError as error:
                raise ConflictError(
                    "Wiki publication is blocked by inconsistent on-disk state; "
                    "run the library lint check and restore or reconcile the "
                    "service-owned Wiki before retrying"
                ) from error

    def _publish_proposal_locked(
        self,
        proposal_id: str,
        *,
        reindex: bool,
        activate_version: bool = True,
    ) -> dict[str, Any]:
        proposal = self.get_proposal(proposal_id)
        if proposal["status"] == "rejected":
            raise ConflictError("Rejected proposal cannot be published")
        if proposal["status"] == "published":
            page = self.db.fetchone(
                """
                SELECT * FROM pages
                WHERE library_id = ? AND version = ? AND path = ?
                """,
                (proposal["library_id"], proposal["version"], proposal["path"]),
            )
            return {
                "proposal": proposal,
                "page": self._decode_page(page) if page else None,
                "idempotent": True,
            }
        library = self.resolve_library(proposal["library_id"])
        version_row = self.db.fetchone(
            "SELECT * FROM versions WHERE id = ?", (proposal["version_id"],)
        )
        if not version_row:
            raise NotFoundError("Version metadata is missing")
        page = {
            "id": _identifier(),
            "library_id": library["id"],
            "version_id": version_row["id"],
            "version": proposal["version"],
            "path": proposal["path"],
            "title": proposal["title"],
            "kind": proposal["kind"],
            "summary": proposal["summary"],
            "markdown": proposal["markdown"],
            "source_sha": proposal["source_sha"],
            "schema_version": proposal["metadata"].get("schema_version"),
            "tags": proposal["metadata"].get("tags", []),
            "source_refs": proposal["metadata"].get("source_refs", []),
        }
        issues = validate_page(
            page,
            snapshot_repo=Path(str(version_row["snapshot_path"])),
            source_sha=str(version_row["source_sha"]),
            require_publish_schema=True,
            allowed_source_ranges=(
                proposal["metadata"].get("generation_evidence_ranges")
                if isinstance(
                    proposal["metadata"].get("generation_evidence_ranges"), list
                )
                else []
            ),
        )
        errors = [issue for issue in issues if issue["level"] == "error"]
        if errors:
            raise ValidationError("Proposal no longer passes validation", issues)

        existing_pages = self.list_pages(library["id"], proposal["version"])
        page_key = portable_path_key(str(page["path"]))
        colliding_page = next(
            (
                existing
                for existing in existing_pages
                if existing["path"] != page["path"]
                and portable_path_key(str(existing["path"])) == page_key
            ),
            None,
        )
        if colliding_page:
            collision_issue = {
                "level": "error",
                "code": "portable-page-path-collision",
                "message": (
                    f"Page path {page['path']!r} collides with "
                    f"{colliding_page['path']!r} on case-insensitive filesystems"
                ),
            }
            raise ValidationError(
                "Proposal page path is not portable", [collision_issue]
            )
        index_pages = [
            {
                **existing,
                "tags": existing["metadata"].get("tags", []),
                "source_refs": existing["metadata"].get("source_refs", []),
            }
            for existing in existing_pages
            if existing["path"] != page["path"]
        ]
        index_pages.append(page)
        wiki = WikiStore(self.settings, library["slug"])
        publication = wiki.publish(page, all_pages=index_pages, proposal_id=proposal_id)
        published_at = utcnow()
        metadata = {
            **proposal["metadata"],
            "git_commit": publication["git_commit"],
            "published_at": published_at,
        }
        try:
            existing = self.db.fetchone(
                """
                SELECT id FROM pages
                WHERE library_id = ? AND version = ? AND path = ?
                """,
                (library["id"], proposal["version"], proposal["path"]),
            )
            if existing:
                page["id"] = existing["id"]
            with self.db.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO pages (
                        id, library_id, version_id, version, path, title, kind,
                        summary, markdown, metadata_json, source_sha, published_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(library_id, version, path) DO UPDATE SET
                        version_id = excluded.version_id,
                        title = excluded.title,
                        kind = excluded.kind,
                        summary = excluded.summary,
                        markdown = excluded.markdown,
                        metadata_json = excluded.metadata_json,
                        source_sha = excluded.source_sha,
                        published_at = excluded.published_at
                    """,
                    (
                        page["id"],
                        page["library_id"],
                        page["version_id"],
                        page["version"],
                        page["path"],
                        page["title"],
                        page["kind"],
                        page["summary"],
                        page["markdown"],
                        json.dumps(metadata, ensure_ascii=False),
                        page["source_sha"],
                        published_at,
                    ),
                )
                connection.execute(
                    "UPDATE proposals SET status = ?, updated_at = ? WHERE id = ?",
                    ("published", published_at, proposal_id),
                )
                if activate_version:
                    connection.execute(
                        """
                        UPDATE versions SET status = ?, published_at = ?
                        WHERE id = ?
                        """,
                        ("published", published_at, version_row["id"]),
                    )
                    connection.execute(
                        """
                        UPDATE libraries
                        SET default_version = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (proposal["version"], published_at, library["id"]),
                    )
                    connection.execute(
                        """
                        UPDATE embedding_state
                        SET status = 'stale',
                            corpus_revision = corpus_revision + 1,
                            error = 'Published corpus changed; rebuild required',
                            updated_at = ?
                        WHERE id = 1
                        """,
                        (published_at,),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE versions
                        SET status = CASE
                            WHEN status = 'published' THEN status
                            ELSE 'publishing'
                        END
                        WHERE id = ?
                        """,
                        (version_row["id"],),
                    )
        except Exception as database_error:
            try:
                wiki.rollback_publication(
                    previous_commit=publication["previous_git_commit"],
                    published_commit=publication["git_commit"],
                    version=str(proposal["version"]),
                )
            except WikiError as rollback_error:
                database_error.add_note(
                    "SQLite publication failed and Wiki rollback also failed: "
                    f"{rollback_error}"
                )
            raise
        index_result = (
            self._index_version(library, proposal["version"])
            if reindex
            else {"indexed": False, "reason": "deferred"}
        )
        return {
            "proposal": self.get_proposal(proposal_id),
            "page": self.get_page(library["id"], proposal["path"], proposal["version"]),
            "publication": publication,
            "index": index_result,
        }

    def _activate_reviewed_version_if_complete(
        self,
        *,
        library_id: str,
        version_id: str,
        version: str,
    ) -> dict[str, Any]:
        """Atomically expose a manually reviewed version only when complete."""

        activated_at = utcnow()
        with self.db.transaction() as connection:
            version_state = connection.execute(
                "SELECT status FROM versions WHERE id = ? AND library_id = ?",
                (version_id, library_id),
            ).fetchone()
            if version_state is None:
                raise NotFoundError("Version metadata is missing")
            already_published = version_state["status"] == "published"
            counts = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN status = 'published' THEN 1 ELSE 0 END) AS published,
                    SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected
                FROM proposals
                WHERE version_id = ?
                """,
                (version_id,),
            ).fetchone()
            total = int(counts["total"] or 0)
            pending = int(counts["pending"] or 0)
            published = int(counts["published"] or 0)
            rejected = int(counts["rejected"] or 0)
            activated = (
                not already_published
                and
                total > 0
                and pending == 0
                and rejected == 0
                and published == total
            )
            if activated:
                connection.execute(
                    """
                    UPDATE versions
                    SET status = 'published', published_at = ?
                    WHERE id = ?
                    """,
                    (activated_at, version_id),
                )
                connection.execute(
                    """
                    UPDATE libraries
                    SET default_version = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (version, activated_at, library_id),
                )
                connection.execute(
                    """
                    UPDATE embedding_state
                    SET status = 'stale',
                        corpus_revision = corpus_revision + 1,
                        error = 'Published corpus changed; rebuild required',
                        updated_at = ?
                    WHERE id = 1
                    """,
                    (activated_at,),
                )
            elif rejected and not already_published:
                connection.execute(
                    """
                    UPDATE versions
                    SET status = CASE
                        WHEN EXISTS (
                            SELECT 1 FROM pages WHERE version_id = ?
                        ) THEN 'partial'
                        ELSE 'rejected'
                    END
                    WHERE id = ? AND status != 'published'
                    """,
                    (version_id, version_id),
                )
            elif not already_published:
                connection.execute(
                    """
                    UPDATE versions
                    SET status = 'publishing'
                    WHERE id = ? AND status != 'published'
                    """,
                    (version_id,),
                )
        return {
            "activated": activated,
            "already_published": already_published,
            "total": total,
            "published": published,
            "pending": pending,
            "rejected": rejected,
        }

    def _publish_proposal_batch(
        self,
        library: dict[str, Any],
        version_id: str,
        version: str,
        proposal_ids: list[str],
    ) -> int:
        """Publish a generated batch before atomically activating its version.

        Git and page commits remain individually recoverable, but the library's
        default_version is changed only after every proposal has published.
        """

        published_count = 0
        with self._publish_lock_for_library(str(library["id"])):
            try:
                with filesystem_lock(
                    lock_path(
                        self.settings.locks_dir,
                        str(library["id"]),
                        "publish",
                    ),
                    blocking=True,
                    timeout_seconds=60,
                ):
                    for proposal_id in proposal_ids:
                        self._publish_proposal_locked(
                            proposal_id,
                            reindex=False,
                            activate_version=False,
                        )
                        published_count += 1
                    activated_at = utcnow()
                    with self.db.transaction() as connection:
                        connection.execute(
                            """
                            UPDATE versions
                            SET status = ?, published_at = ?
                            WHERE id = ?
                            """,
                            ("published", activated_at, version_id),
                        )
                        connection.execute(
                            """
                            UPDATE libraries
                            SET default_version = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (version, activated_at, library["id"]),
                        )
                        connection.execute(
                            """
                            UPDATE embedding_state
                            SET status = 'stale',
                                corpus_revision = corpus_revision + 1,
                                error = 'Published corpus changed; rebuild required',
                                updated_at = ?
                            WHERE id = 1
                            """,
                            (activated_at,),
                        )
            except LockUnavailable as error:
                raise ConflictError(
                    "Timed out waiting to publish the generated batch"
                ) from error
            except WikiError as error:
                raise ConflictError(
                    "Wiki batch publication is blocked by inconsistent on-disk "
                    "state; run lint and reconcile the service-owned Wiki"
                ) from error
        return published_count

    def _published_retrieval_collections(
        self,
    ) -> tuple[list[tuple[Path, str]], int]:
        rows = self.db.fetchall(
            """
            SELECT versions.version, libraries.slug AS library_slug
            FROM versions
            JOIN libraries ON libraries.id = versions.library_id
            WHERE versions.status = 'published'
            ORDER BY libraries.slug, versions.published_at, versions.version
            """
        )
        collections: list[tuple[Path, str]] = []
        for row in rows:
            wiki = WikiStore(self.settings, str(row["library_slug"]))
            collections.append(
                (
                    wiki.version_root(str(row["version"])),
                    collection_name(
                        str(row["library_slug"]), str(row["version"])
                    ),
                )
            )
        state = self.db.fetchone(
            "SELECT corpus_revision FROM embedding_state WHERE id = 1"
        )
        return collections, int(state["corpus_revision"] if state else 0)

    def reconcile_desktop_retrieval(self) -> dict[str, Any]:
        if not getattr(self.retriever, "desktop_broker", False):
            return {"indexed": False, "reason": "not-desktop-retrieval"}
        collections, revision = self._published_retrieval_collections()
        return self.retriever.reconcile(collections, revision=revision)

    def _index_version(self, library: dict[str, Any], version: str) -> dict[str, Any]:
        if getattr(self.retriever, "desktop_broker", False):
            return self.reconcile_desktop_retrieval()
        wiki = WikiStore(self.settings, library["slug"])
        return self.retriever.index(
            wiki.version_root(version),
            collection_name(library["slug"], version),
        )

    def create_rebuild_job(
        self,
        *,
        model: str | None,
        scope_library_id: str | None,
        retry_of: str | None = None,
        attempt: int = 1,
    ) -> dict[str, Any]:
        settings = self.get_settings()
        requested_model = str(model or settings["embedding_model"]).strip()
        target_model = str(
            self.validate_embedding_model(requested_model)["canonical_model"]
        )
        if target_model != settings["embedding_model"]:
            self.patch_settings(
                {
                    "expected_revision": settings["revision"],
                    "embedding_model": target_model,
                }
            )
        scope_library: dict[str, Any] | None = None
        if scope_library_id:
            scope_library = self.resolve_library(scope_library_id)
        rows = self.db.fetchall(
            """
            SELECT DISTINCT libraries.id
            FROM versions
            JOIN libraries ON libraries.id = versions.library_id
            WHERE versions.status = 'published'
              AND (? IS NULL OR libraries.id = ?)
            ORDER BY libraries.id
            """,
            (
                scope_library["id"] if scope_library else None,
                scope_library["id"] if scope_library else None,
            ),
        )
        if not rows:
            if scope_library:
                raise ValidationError("Library has no fully published version")
            now = utcnow()
            with self.db.transaction() as connection:
                connection.execute(
                    """
                    UPDATE embedding_state
                    SET desired_model = ?, active_model = ?, status = 'ready',
                        indexed_revision = corpus_revision,
                        error = NULL, last_job_id = NULL, updated_at = ?
                    WHERE id = 1
                    """,
                    (target_model, target_model, now),
                )
            return {
                "id": None,
                "kind": "embedding_rebuild",
                "status": "completed",
                "stage": "no-published-versions",
                "message": "No published versions require embedding",
                "global_embedding": True,
                "queue_position": None,
                "cancellable": False,
                "retryable": False,
            }
        associated_library_id = str(rows[0]["id"])
        request_payload = {
            "schema_version": 1,
            "kind": "embedding_rebuild",
            "model": target_model,
            "scope_library_id": (
                str(scope_library["id"]) if scope_library else None
            ),
            "global_embedding": True,
        }
        now = utcnow()
        job_id = _identifier()
        with self.db.transaction() as connection:
            active = connection.execute(
                """
                SELECT id FROM jobs
                WHERE kind = 'embedding_rebuild'
                  AND status IN ('queued', 'running', 'cancelling')
                ORDER BY queue_seq LIMIT 1
                """
            ).fetchone()
            if active:
                raise ConflictError(
                    f"Embedding rebuild already active: {active['id']}"
                )
            queue_seq = self._next_queue_seq(connection)
            connection.execute(
                """
                INSERT INTO jobs (
                    id, library_id, version_id, version, provider, kind,
                    queue_seq, request_json, attempt, retry_of, status, stage,
                    progress, message, error, created_at, updated_at
                ) VALUES (
                    ?, ?, NULL, 'global', 'system', 'embedding_rebuild',
                    ?, ?, ?, ?, 'queued', 'queued', 0,
                    'Waiting for global embedding rebuild', NULL, ?, ?
                )
                """,
                (
                    job_id,
                    associated_library_id,
                    queue_seq,
                    json.dumps(request_payload, ensure_ascii=False),
                    attempt,
                    retry_of,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE embedding_state
                SET desired_model = ?, status = 'stale', error = NULL,
                    last_job_id = ?, updated_at = ?
                WHERE id = 1
                """,
                (target_model, job_id, now),
            )
        if self.dispatcher is not None:
            self.dispatcher.notify()
        return self.get_job(job_id)

    def run_rebuild_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job["status"] != "queued":
            return job
        request = job.get("request") or {}
        if not self._claim_queued_job(job_id):
            return self.get_job(job_id)
        try:
            atomic_write_json(
                self.settings.jobs_dir / f"{job_id}.json",
                {
                    **request,
                    "job_id": job_id,
                    "owner_instance": self.instance_id,
                },
            )
        except OSError as error:
            self._mark_job_failed(
                job_id,
                stage="control",
                message="Could not persist worker ownership",
                error=str(error),
            )
            return self.get_job(job_id)
        model = str(request.get("model") or "").strip()
        scope_library_id = request.get("scope_library_id")
        now = utcnow()
        state = self.db.fetchone(
            "SELECT corpus_revision FROM embedding_state WHERE id = 1"
        )
        target_corpus_revision = int(
            state["corpus_revision"] if state else 0
        )
        try:
            self._raise_if_cancelled(job_id)
            with self.db.transaction() as connection:
                connection.execute(
                    """
                    UPDATE embedding_state
                    SET status = 'rebuilding', error = NULL,
                        last_job_id = ?, updated_at = ?
                    WHERE id = 1 AND desired_model = ?
                      AND corpus_revision = ?
                    """,
                    (job_id, now, model, target_corpus_revision),
                )
            self._update_job(
                job_id,
                stage="embedding",
                progress=20,
                message="Rebuilding global QMD embeddings",
            )
            result = self.reindex(
                # Embeddings share one QMD store/model. Even a rebuild
                # requested from one library must register the complete
                # published corpus before the global `embed -f`.
                library_id=None,
                embed=True,
                model=model,
            )
            result["requested_scope_library_id"] = scope_library_id
            self._raise_if_cancelled(job_id)
            registrations_ok = all(
                bool(item.get("registered"))
                for item in result["registrations"]
            )
            refresh = result["refresh"]
            if not (
                registrations_ok
                and bool(refresh.get("updated"))
                and bool(refresh.get("embedded"))
            ):
                raise RuntimeError(
                    str(
                        refresh.get("error")
                        or refresh.get("reason")
                        or "QMD embedding rebuild failed"
                    )
                )
            completed_at = utcnow()
            with self.db.transaction() as connection:
                activation = connection.execute(
                    """
                    UPDATE embedding_state
                    SET active_model = ?, status = 'ready',
                        indexed_revision = ?, error = NULL,
                        last_job_id = ?, updated_at = ?
                    WHERE id = 1 AND desired_model = ?
                      AND corpus_revision = ?
                    """,
                    (
                        model,
                        target_corpus_revision,
                        job_id,
                        completed_at,
                        model,
                        target_corpus_revision,
                    ),
                )
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'completed', stage = 'completed', progress = 100,
                        message = 'Global embedding rebuild completed',
                        result_json = ?, finished_at = ?, updated_at = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (
                        json.dumps(
                            {
                                **result,
                                "global_embedding": True,
                                "model": model,
                                "activated": activation.rowcount == 1,
                                "corpus_revision": target_corpus_revision,
                            },
                            ensure_ascii=False,
                        ),
                        completed_at,
                        completed_at,
                        job_id,
                    ),
                )
        except JobCancelled:
            with self.db.transaction() as connection:
                connection.execute(
                    """
                    UPDATE embedding_state
                    SET status = 'stale', error = 'Rebuild cancelled',
                        updated_at = ?
                    WHERE id = 1 AND desired_model = ?
                      AND corpus_revision = ?
                    """,
                    (utcnow(), model, target_corpus_revision),
                )
            self._mark_job_cancelled(job_id)
        except Exception as error:  # noqa: BLE001 - terminal state is persisted
            detail = str(error)[-2000:]
            with self.db.transaction() as connection:
                connection.execute(
                    """
                    UPDATE embedding_state
                    SET status = 'failed', error = ?, updated_at = ?
                    WHERE id = 1 AND desired_model = ?
                      AND corpus_revision = ?
                    """,
                    (detail, utcnow(), model, target_corpus_revision),
                )
            self._mark_job_failed(
                job_id,
                stage="failed",
                message="Global embedding rebuild failed",
                error=detail,
            )
        return self.get_job(job_id)

    def reindex(
        self,
        *,
        library_id: str | None = None,
        version: str | None = None,
        embed: bool = False,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Rebuild QMD registrations from fully published Wiki versions."""

        manage_embedding_state = embed and model is None
        if library_id is not None and not library_id.strip():
            raise ValidationError("library_id cannot be empty")
        if version is not None and not version.strip():
            raise ValidationError("version cannot be empty")
        if version is not None and library_id is None:
            raise ValidationError("version requires library_id")

        clauses = ["versions.status = 'published'"]
        parameters: list[object] = []
        library: dict[str, Any] | None = None
        if library_id is not None:
            library = self.resolve_library(library_id)
            clauses.append("libraries.id = ?")
            parameters.append(library["id"])
        if version is not None:
            requested = version.strip()
            escaped = (
                requested.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            clauses.append(
                "(versions.version = ? OR versions.version LIKE ? ESCAPE '\\')"
            )
            parameters.extend([requested, f"{escaped}+git.%"])

        rows = self.db.fetchall(
            f"""
            SELECT versions.version, libraries.id AS library_id,
                   libraries.slug AS library_slug
            FROM versions
            JOIN libraries ON libraries.id = versions.library_id
            WHERE {" AND ".join(clauses)}
            ORDER BY libraries.slug, versions.published_at, versions.version
            """,
            tuple(parameters),
        )
        if version is not None and not rows:
            raise ValidationError(
                f"Version is not fully published: {version}"
            )

        collections: list[tuple[Path, str]] = []
        for row in rows:
            wiki = WikiStore(self.settings, str(row["library_slug"]))
            collections.append(
                (
                    wiki.version_root(str(row["version"])),
                    collection_name(
                        str(row["library_slug"]), str(row["version"])
                    ),
                )
            )
        if getattr(self.retriever, "desktop_broker", False):
            all_collections, corpus_revision = (
                self._published_retrieval_collections()
            )
            registrations, refresh = self.retriever.rebuild(
                all_collections,
                embed=False,
                revision=corpus_revision,
            )
            return {
                "library_id": library["id"] if library else None,
                "requested_version": version,
                "published_versions": len(all_collections),
                "registrations": registrations,
                "refresh": refresh,
                "embedding_state_managed": False,
            }
        target_corpus_revision: int | None = None
        if manage_embedding_state:
            with self.db.transaction() as connection:
                state = connection.execute(
                    """
                    SELECT desired_model, corpus_revision
                    FROM embedding_state WHERE id = 1
                    """
                ).fetchone()
                if not state:
                    raise RuntimeError("Embedding state is missing")
                model = str(state["desired_model"])
                target_corpus_revision = int(state["corpus_revision"])
                connection.execute(
                    """
                    UPDATE embedding_state
                    SET status = 'rebuilding', error = NULL, updated_at = ?
                    WHERE id = 1 AND desired_model = ?
                      AND corpus_revision = ?
                    """,
                    (utcnow(), model, target_corpus_revision),
                )
        try:
            if model is None:
                registrations, refresh = self.retriever.rebuild(
                    collections, embed=embed
                )
            else:
                registrations, refresh = self.retriever.rebuild(
                    collections, embed=embed, model=model
                )
        except Exception as error:
            if manage_embedding_state and target_corpus_revision is not None:
                with self.db.transaction() as connection:
                    connection.execute(
                        """
                        UPDATE embedding_state
                        SET status = 'failed', error = ?, updated_at = ?
                        WHERE id = 1 AND desired_model = ?
                          AND corpus_revision = ?
                        """,
                        (
                            str(error)[-2000:],
                            utcnow(),
                            model,
                            target_corpus_revision,
                        ),
                    )
            raise
        if manage_embedding_state and target_corpus_revision is not None:
            registrations_ok = all(
                bool(item.get("registered")) for item in registrations
            )
            succeeded = (
                not collections
                or (
                    registrations_ok
                    and bool(refresh.get("updated"))
                    and bool(refresh.get("embedded"))
                )
            )
            with self.db.transaction() as connection:
                if succeeded:
                    connection.execute(
                        """
                        UPDATE embedding_state
                        SET active_model = ?, status = 'ready',
                            indexed_revision = ?, error = NULL, updated_at = ?
                        WHERE id = 1 AND desired_model = ?
                          AND corpus_revision = ?
                        """,
                        (
                            model,
                            target_corpus_revision,
                            utcnow(),
                            model,
                            target_corpus_revision,
                        ),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE embedding_state
                        SET status = 'failed', error = ?, updated_at = ?
                        WHERE id = 1 AND desired_model = ?
                          AND corpus_revision = ?
                        """,
                        (
                            str(
                                refresh.get("error")
                                or refresh.get("reason")
                                or "QMD embedding rebuild failed"
                            )[-2000:],
                            utcnow(),
                            model,
                            target_corpus_revision,
                        ),
                    )
        return {
            "library_id": library["id"] if library else None,
            "requested_version": version,
            "published_versions": len(rows),
            "registrations": registrations,
            "refresh": refresh,
            "embedding_state_managed": manage_embedding_state,
        }

    def reject_proposal(self, proposal_id: str, reason: str = "") -> dict[str, Any]:
        proposal = self.get_proposal(proposal_id)
        with self._publish_lock_for_library(str(proposal["library_id"])):
            try:
                with filesystem_lock(
                    lock_path(
                        self.settings.locks_dir,
                        str(proposal["library_id"]),
                        "publish",
                    ),
                    blocking=True,
                    timeout_seconds=60,
                ):
                    return self._reject_proposal_locked(proposal_id, reason)
            except LockUnavailable as error:
                raise ConflictError(
                    "Timed out waiting for another API process to finish review"
                ) from error

    def _reject_proposal_locked(
        self, proposal_id: str, reason: str = ""
    ) -> dict[str, Any]:
        proposal = self.get_proposal(proposal_id)
        if proposal["status"] == "published":
            raise ConflictError("Published proposal cannot be rejected")
        if proposal["status"] == "rejected":
            return proposal
        metadata = proposal["metadata"]
        metadata["rejection_reason"] = reason
        metadata["rejected_at"] = utcnow()
        with self.db.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE proposals
                SET status = ?, metadata_json = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    "rejected",
                    json.dumps(metadata, ensure_ascii=False),
                    utcnow(),
                    proposal_id,
                    "pending",
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("Proposal state changed during review")
            connection.execute(
                """
                UPDATE versions
                SET status = CASE
                    WHEN EXISTS (
                        SELECT 1 FROM pages WHERE version_id = ?
                    ) THEN 'partial'
                    ELSE 'rejected'
                END
                WHERE id = ? AND status != 'published'
                """,
                (proposal["version_id"], proposal["version_id"]),
            )
        return self.get_proposal(proposal_id)

    def query(
        self,
        query: str,
        *,
        library_id: str | None = None,
        version: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ValidationError("query cannot be empty")
        if library_id is not None and not library_id.strip():
            raise ValidationError("library_id cannot be empty; omit it for global search")
        if version is not None and not version.strip():
            raise ValidationError("version cannot be empty")
        if library_id is None and version is not None:
            raise ValidationError("version requires library_id")
        if library_id is not None:
            library = self.resolve_library(library_id)
            pages = self.list_pages(library["id"], version)
            if pages:
                version_state = self.db.fetchone(
                    """
                    SELECT status FROM versions
                    WHERE id = ? AND library_id = ?
                    """,
                    (pages[0]["version_id"], library["id"]),
                )
                if not version_state or version_state["status"] != "published":
                    pages = []
            resolved_version = (
                pages[0]["version"]
                if pages
                else version or library.get("default_version") or ""
            )
            embedding = self.embedding_status()
            if getattr(self.retriever, "desktop_broker", False):
                engine, hits = self.retriever.query(
                    pages,
                    query=query,
                    collection=collection_name(
                        library["slug"], resolved_version
                    ),
                    limit=limit,
                    hybrid=False,
                    revision=int(embedding["corpus_revision"]),
                )
            elif embedding["hybrid_ready"]:
                engine, hits = self.retriever.query(
                    pages,
                    query=query,
                    collection=collection_name(
                        library["slug"], resolved_version
                    ),
                    limit=limit,
                    model=str(embedding["active_model"]),
                    hybrid=True,
                )
            else:
                engine = "lexical"
                hits = lexical_search(pages, query, limit)
        else:
            rows = self.db.fetchall(
                """
                SELECT pages.*
                FROM pages
                JOIN versions ON versions.id = pages.version_id
                WHERE versions.status = 'published'
                ORDER BY pages.published_at DESC
                """
            )
            pages = [self._decode_page(row) for row in rows]
            engine = "lexical"
            hits = lexical_search(pages, query, limit)
        results = []
        for hit in hits:
            metadata = hit.get("metadata", {})
            results.append(
                {
                    "path": hit["path"],
                    "title": hit["title"],
                    "summary": hit["summary"],
                    "snippet": hit["snippet"],
                    "score": hit["score"],
                    "library_id": hit["library_id"],
                    "version": hit["version"],
                    "source_sha": hit["source_sha"],
                    "source_refs": metadata.get("source_refs", []),
                    "markdown": hit["markdown"],
                }
            )
        return {"query": query, "engine": engine, "results": results}

    def graph(self, library_id: str, version: str | None = None) -> dict[str, Any]:
        library = self.resolve_library(library_id)
        pages = self.list_pages(library["id"], version)
        nodes: list[dict[str, Any]] = [
            {
                "id": f"library:{library['id']}",
                "type": "library",
                "label": library["name"],
                "metadata": {"context7_id": library["context7_id"]},
            }
        ]
        edges: list[dict[str, Any]] = []
        version_nodes: set[str] = set()
        source_nodes: set[str] = set()
        for page in pages:
            version_id = f"version:{library['id']}:{page['version']}"
            if version_id not in version_nodes:
                version_nodes.add(version_id)
                nodes.append(
                    {
                        "id": version_id,
                        "type": "version",
                        "label": page["version"],
                        "metadata": {"source_sha": page["source_sha"]},
                    }
                )
                edges.append(
                    {
                        "source": f"library:{library['id']}",
                        "target": version_id,
                        "type": "has-version",
                    }
                )
            page_id = f"page:{page['id']}"
            nodes.append(
                {
                    "id": page_id,
                    "type": "page",
                    "label": page["title"],
                    "metadata": {
                        "path": page["path"],
                        "kind": page["kind"],
                        "summary": page["summary"],
                    },
                }
            )
            edges.append({"source": version_id, "target": page_id, "type": "contains"})
            for ref in page["metadata"].get("source_refs", []):
                source_id = f"source:{library['id']}:{ref['path']}"
                if source_id not in source_nodes:
                    source_nodes.add(source_id)
                    nodes.append(
                        {
                            "id": source_id,
                            "type": "source",
                            "label": ref["path"],
                            "metadata": {},
                        }
                    )
                edges.append(
                    {
                        "source": page_id,
                        "target": source_id,
                        "type": "cites",
                        "metadata": {
                            "line_start": ref["line_start"],
                            "line_end": ref["line_end"],
                            "symbol": ref.get("symbol"),
                        },
                    }
                )
        return {"nodes": nodes, "edges": edges}

    def lint(self, library_id: str, version: str | None = None) -> dict[str, Any]:
        library = self.resolve_library(library_id)
        pages = self.list_pages(library["id"], version)
        wiki = WikiStore(self.settings, library["slug"])
        if not pages:
            issues: list[dict[str, Any]] = [
                {
                    "level": "warning",
                    "code": "empty-wiki",
                    "message": "No published pages to lint",
                }
            ]
            if wiki.root.exists() or wiki.root.is_symlink():
                try:
                    git_status = wiki.git_status()
                except WikiError:
                    issues.append(
                        {
                            "level": "error",
                            "code": "wiki-git-unreadable",
                            "message": (
                                "Service-owned Wiki Git metadata is invalid; "
                                "restore a trusted backup before publishing"
                            ),
                        }
                    )
                else:
                    if git_status:
                        issues.append(
                            {
                                "level": "error",
                                "code": "wiki-git-dirty",
                                "message": (
                                    "Wiki Git working tree has uncommitted or "
                                    "uninitialized state"
                                ),
                                "detail": git_status[:4000],
                            }
                        )
            requested_version = version or library.get("default_version")
            version_row: dict[str, Any] | None = None
            if requested_version:
                version_row = self.db.fetchone(
                    """
                    SELECT * FROM versions
                    WHERE library_id = ?
                      AND (
                        version = ?
                        OR version LIKE ? ESCAPE '\\'
                      )
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (
                        library["id"],
                        requested_version,
                        (
                            requested_version.replace("\\", "\\\\")
                            .replace("%", "\\%")
                            .replace("_", "\\_")
                            + "+git.%"
                        ),
                    ),
                )
            else:
                version_row = self.db.fetchone(
                    """
                    SELECT * FROM versions
                    WHERE library_id = ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (library["id"],),
                )
            resolved_version = (
                str(version_row["version"])
                if version_row
                else str(requested_version or "")
            )
            if resolved_version:
                version_root = wiki.version_root(resolved_version)
                try:
                    has_orphan_files = version_root.is_dir() and any(
                        item.is_file() or item.is_symlink()
                        for item in version_root.rglob("*")
                    )
                except OSError:
                    has_orphan_files = True
                if has_orphan_files:
                    issues.append(
                        {
                            "level": "error",
                            "code": "wiki-orphan-files",
                            "message": (
                                "Wiki version files exist without matching "
                                "runtime pages"
                            ),
                        }
                    )
            errors = sum(item["level"] == "error" for item in issues)
            return {
                "ok": errors == 0,
                "errors": errors,
                "warnings": sum(
                    item["level"] == "warning" for item in issues
                ),
                "issues": issues,
                "library_id": library["id"],
                "version": resolved_version or None,
            }
        resolved_version = pages[0]["version"]
        expected_sha = pages[0]["source_sha"]
        result = lint_published_wiki(
            wiki.version_root(resolved_version),
            pages,
            expected_source_sha=expected_sha,
        )
        version_root = wiki.version_root(resolved_version)
        for page in pages:
            markdown_path = version_root / page["path"]
            if markdown_path.exists():
                expected_markdown = WikiStore.render_markdown(
                    {
                        **page,
                        "tags": page["metadata"].get("tags", []),
                        "source_refs": page["metadata"].get("source_refs", []),
                    }
                )
                try:
                    actual_markdown = markdown_path.read_text(encoding="utf-8")
                except OSError:
                    actual_markdown = ""
                if actual_markdown != expected_markdown:
                    result["issues"].append(
                        {
                            "level": "error",
                            "code": "wiki-markdown-drift",
                            "path": page["path"],
                            "message": "Git Wiki Markdown differs from runtime metadata",
                        }
                    )
        try:
            git_status = wiki.git_status()
        except WikiError:
            git_status = ""
            result["issues"].append(
                {
                    "level": "error",
                    "code": "wiki-git-unreadable",
                    "message": (
                        "Service-owned Wiki Git metadata is invalid; restore a "
                        "trusted backup before publishing"
                    ),
                }
            )
        if git_status:
            result["issues"].append(
                {
                    "level": "error",
                    "code": "wiki-git-dirty",
                    "message": "Wiki Git working tree has uncommitted changes",
                    "detail": git_status[:4000],
                }
            )
        version_row = self.db.fetchone(
            """
            SELECT * FROM versions
            WHERE library_id = ? AND version = ? AND source_sha = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (library["id"], resolved_version, expected_sha),
        )
        if version_row:
            for page in pages:
                issues = validate_page(
                    {
                        **page,
                        "source_refs": page["metadata"].get("source_refs", []),
                    },
                    snapshot_repo=Path(str(version_row["snapshot_path"])),
                    source_sha=expected_sha,
                    allowed_source_ranges=(
                        page["metadata"].get("generation_evidence_ranges")
                        if isinstance(
                            page["metadata"].get("generation_evidence_ranges"), list
                        )
                        else []
                    ),
                )
                for issue in issues:
                    result["issues"].append({**issue, "path": page["path"]})
        result["errors"] = sum(item["level"] == "error" for item in result["issues"])
        result["warnings"] = sum(
            item["level"] == "warning" for item in result["issues"]
        )
        result["ok"] = result["errors"] == 0
        result["library_id"] = library["id"]
        result["version"] = resolved_version
        result["source_sha"] = expected_sha
        return result

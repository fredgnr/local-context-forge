from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .locks import filesystem_lock

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS libraries (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    context7_id TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    default_version TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
    id TEXT PRIMARY KEY,
    library_id TEXT NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    source_sha TEXT NOT NULL,
    snapshot_path TEXT NOT NULL,
    facts_path TEXT NOT NULL,
    wiki_path TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_at TEXT,
    UNIQUE(library_id, version, source_sha)
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    library_id TEXT NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    version_id TEXT REFERENCES versions(id) ON DELETE SET NULL,
    version TEXT NOT NULL,
    provider TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'ingest',
    queue_seq INTEGER,
    request_json TEXT NOT NULL DEFAULT '{}',
    attempt INTEGER NOT NULL DEFAULT 1,
    retry_of TEXT REFERENCES jobs(id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    error TEXT,
    started_at TEXT,
    finished_at TEXT,
    cancel_requested_at TEXT,
    result_json TEXT,
    effective_provider TEXT,
    fallback_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    library_id TEXT NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    source_sha TEXT NOT NULL,
    status TEXT NOT NULL,
    path TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    markdown TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_proposals_library_status
ON proposals(library_id, status);

CREATE TABLE IF NOT EXISTS pages (
    id TEXT PRIMARY KEY,
    library_id TEXT NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    path TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    markdown TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    source_sha TEXT NOT NULL,
    published_at TEXT NOT NULL,
    UNIQUE(library_id, version, path)
);

CREATE INDEX IF NOT EXISTS idx_pages_library_version
ON pages(library_id, version);

CREATE TABLE IF NOT EXISTS queue_counter (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    value INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    revision INTEGER NOT NULL,
    provider_order_json TEXT NOT NULL,
    fallback_enabled INTEGER NOT NULL,
    concurrency INTEGER NOT NULL,
    embedding_model TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embedding_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    desired_model TEXT NOT NULL,
    active_model TEXT,
    status TEXT NOT NULL,
    error TEXT,
    last_job_id TEXT,
    corpus_revision INTEGER NOT NULL DEFAULT 0,
    indexed_revision INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_attempts (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    version_id TEXT REFERENCES versions(id) ON DELETE SET NULL,
    corpus_revision INTEGER NOT NULL,
    policy TEXT NOT NULL CHECK (
        policy IN ('codex_only', 'codex_then_cursor')
    ),
    candidates_json TEXT NOT NULL,
    cursor_consent_version INTEGER,
    cursor_consent_granted_at TEXT,
    status TEXT NOT NULL CHECK (
        status IN (
            'pending', 'claimed', 'selected', 'executing',
            'succeeded', 'failed', 'cancelled', 'uncertain'
        )
    ),
    input_sha256 TEXT NOT NULL,
    evidence_path TEXT NOT NULL,
    selected_provider TEXT CHECK (
        selected_provider IS NULL OR
        selected_provider IN ('codex_cli', 'cursor_cli')
    ),
    executable_identity_json TEXT,
    fallback_reason TEXT CHECK (
        fallback_reason IS NULL OR
        fallback_reason IN (
            'codex_not_installed', 'codex_not_authenticated'
        )
    ),
    diagnostic TEXT,
    claim_id TEXT,
    claimed_at TEXT,
    claim_expires_at TEXT,
    selected_at TEXT,
    execution_committed_at TEXT,
    cancel_requested_at TEXT,
    finished_at TEXT,
    output_sha256 TEXT,
    output_size INTEGER,
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_attempts_job
ON provider_attempts(job_id);

CREATE INDEX IF NOT EXISTS idx_provider_attempts_recovery
ON provider_attempts(status, execution_committed_at);
"""

SCHEMA_VERSION = 4

_JOB_COLUMNS: dict[str, str] = {
    "kind": "TEXT NOT NULL DEFAULT 'ingest'",
    "queue_seq": "INTEGER",
    "request_json": "TEXT NOT NULL DEFAULT '{}'",
    "attempt": "INTEGER NOT NULL DEFAULT 1",
    "retry_of": "TEXT",
    "started_at": "TEXT",
    "finished_at": "TEXT",
    "cancel_requested_at": "TEXT",
    "result_json": "TEXT",
    "effective_provider": "TEXT",
    "fallback_reason": "TEXT",
}

_EMBEDDING_COLUMNS: dict[str, str] = {
    "corpus_revision": "INTEGER NOT NULL DEFAULT 0",
    "indexed_revision": "INTEGER NOT NULL DEFAULT 0",
}

_PROVIDER_ATTEMPT_COLUMNS: dict[str, str] = {
    "cancel_requested_at": "TEXT",
}


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        # SQLite serializes writes, but PRAGMA journal_mode and executescript
        # can still fail immediately when two fresh API processes initialize
        # the same legacy file. The host-wide advisory lock covers that setup
        # window; BEGIN EXCLUSIVE then protects against non-app SQLite clients.
        migration_lock = self.path.with_name(f"{self.path.name}.migrate.lock")
        with filesystem_lock(
            migration_lock,
            blocking=True,
            timeout_seconds=30,
        ), self.connect() as connection:
            version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema {version} is newer than supported "
                    f"schema {SCHEMA_VERSION}"
                )
            connection.executescript(SCHEMA)
            # Every introspection and ALTER shares one exclusive
            # transaction so no non-app writer can interleave migration.
            connection.execute("BEGIN EXCLUSIVE")
            try:
                self._migrate_locked(connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _migrate_locked(connection: sqlite3.Connection) -> None:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema {version} is newer than supported "
                f"schema {SCHEMA_VERSION}"
            )
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
        }
        for name, declaration in _JOB_COLUMNS.items():
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE jobs ADD COLUMN {name} {declaration}"
                )
        embedding_columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(embedding_state)"
            ).fetchall()
        }
        for name, declaration in _EMBEDDING_COLUMNS.items():
            if name not in embedding_columns:
                connection.execute(
                    "ALTER TABLE embedding_state "
                    f"ADD COLUMN {name} {declaration}"
                )
        provider_attempt_columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(provider_attempts)"
            ).fetchall()
        }
        for name, declaration in _PROVIDER_ATTEMPT_COLUMNS.items():
            if name not in provider_attempt_columns:
                connection.execute(
                    "ALTER TABLE provider_attempts "
                    f"ADD COLUMN {name} {declaration}"
                )

        rows = connection.execute(
            """
            SELECT id FROM jobs
            WHERE queue_seq IS NULL
            ORDER BY created_at, id
            """
        ).fetchall()
        current = int(
            connection.execute(
                "SELECT COALESCE(MAX(queue_seq), 0) FROM jobs"
            ).fetchone()[0]
        )
        for row in rows:
            current += 1
            connection.execute(
                "UPDATE jobs SET queue_seq = ? WHERE id = ?",
                (current, row["id"]),
            )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_queue_seq
            ON jobs(queue_seq)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_dispatch
            ON jobs(status, queue_seq)
            """
        )
        connection.execute(
            """
            INSERT INTO queue_counter(id, value) VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET value =
                MAX(queue_counter.value, excluded.value)
            """,
            (current,),
        )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def fetchone(
        self, query: str, parameters: tuple[object, ...] = ()
    ) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(query, parameters).fetchone()
            return dict(row) if row else None

    def fetchall(
        self, query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
            return [dict(row) for row in rows]

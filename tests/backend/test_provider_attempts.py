from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.db import Database, SCHEMA_VERSION
from app.provider_attempts import (
    ProviderAttemptConflict,
    ProviderAttemptStore,
    ProviderAttemptValidation,
    input_digest,
)


class Clock:
    def __init__(self, value: str = "2026-07-31T12:00:00+00:00") -> None:
        self.value = value

    def __call__(self) -> str:
        return self.value


class Identifiers:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"{self.value:032x}"


def seed_job(database: Database) -> tuple[str, str]:
    library_id = "a" * 32
    version_id = "b" * 32
    job_id = "c" * 32
    now = "2026-07-31T11:00:00+00:00"
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO libraries (
                id, name, slug, context7_id, source, created_at, updated_at
            ) VALUES (?, 'Library', 'library', '/library', '/tmp/source', ?, ?)
            """,
            (library_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO versions (
                id, library_id, version, source_sha, snapshot_path, facts_path,
                wiki_path, status, created_at
            ) VALUES (?, ?, 'v1', ?, 'snapshots/v1', 'facts/v1', 'wiki/v1',
                      'ready', ?)
            """,
            (version_id, library_id, "d" * 40, now),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                id, library_id, version_id, version, provider, queue_seq,
                status, stage, created_at, updated_at
            ) VALUES (?, ?, ?, 'v1', 'codex_cli', 1, 'running',
                      'generate', ?, ?)
            """,
            (job_id, library_id, version_id, now, now),
        )
    return job_id, version_id


def identity(provider: str = "codex_cli") -> dict[str, object]:
    return {
        "provider": provider,
        "canonical_path": f"/Applications/{provider}",
        "sha256": "d" * 64,
        "size": 123,
        "mtime_ms": 42.5,
        "device": 1,
        "inode": 2,
        "mode": 0o100755,
        "version": "0.146.0",
    }


@pytest.fixture
def attempt_store(tmp_path: Path) -> tuple[ProviderAttemptStore, Database, Clock]:
    database = Database(tmp_path / "app.db")
    seed_job(database)
    clock = Clock()
    return (
        ProviderAttemptStore(
            database,
            now=clock,
            identifiers=Identifiers(),
        ),
        database,
        clock,
    )


def create_attempt(
    store: ProviderAttemptStore,
    *,
    policy: str = "codex_only",
) -> dict[str, object]:
    return store.create(
        job_id="c" * 32,
        version_id="b" * 32,
        corpus_revision=7,
        policy=policy,
        candidates=(
            ["codex_cli"]
            if policy == "codex_only"
            else ["codex_cli", "cursor_cli"]
        ),
        cursor_consent_version=1 if policy == "codex_then_cursor" else None,
        cursor_consent_granted_at=(
            "2026-07-31T11:30:00+00:00"
            if policy == "codex_then_cursor"
            else None
        ),
        input_sha256=input_digest(b"private prompt"),
        evidence_path="provider-attempts/attempt-1",
    )


def test_schema_four_creates_attempt_table(tmp_path: Path) -> None:
    database = Database(tmp_path / "schema.db")
    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert SCHEMA_VERSION == 4
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(provider_attempts)"
            ).fetchall()
        }
    assert {
        "execution_committed_at",
        "executable_identity_json",
        "input_sha256",
        "evidence_path",
    } <= columns


def test_create_requires_directed_policy_and_current_consent(
    attempt_store: tuple[ProviderAttemptStore, Database, Clock],
) -> None:
    store, _, _ = attempt_store
    with pytest.raises(ProviderAttemptValidation):
        store.create(
            job_id="c" * 32,
            version_id="b" * 32,
            corpus_revision=0,
            policy="cursor_only",
            candidates=["cursor_cli"],
            cursor_consent_version=1,
            cursor_consent_granted_at="2026-07-31T11:30:00+00:00",
            input_sha256="a" * 64,
            evidence_path="provider-attempts/x",
        )
    with pytest.raises(ProviderAttemptValidation):
        store.create(
            job_id="c" * 32,
            version_id="b" * 32,
            corpus_revision=0,
            policy="codex_then_cursor",
            candidates=["codex_cli", "cursor_cli"],
            cursor_consent_version=None,
            cursor_consent_granted_at=None,
            input_sha256="a" * 64,
            evidence_path="provider-attempts/x",
        )


def test_claim_select_commit_complete_is_single_use(
    attempt_store: tuple[ProviderAttemptStore, Database, Clock],
) -> None:
    store, _, _ = attempt_store
    attempt = create_attempt(store, policy="codex_then_cursor")
    claimed = store.claim(str(attempt["id"]))
    selected = store.select(
        str(attempt["id"]),
        claim_id=str(claimed["claim_id"]),
        provider="cursor_cli",
        executable_identity=identity("cursor_cli"),
        fallback_reason="codex_not_authenticated",
    )
    assert selected["status"] == "selected"
    receipt = store.commit_execution(
        str(attempt["id"]),
        claim_id=str(claimed["claim_id"]),
    )
    assert receipt == {
        "attempt_id": attempt["id"],
        "claim_id": claimed["claim_id"],
        "selected_provider": "cursor_cli",
        "executable_sha256": "d" * 64,
        "execution_committed_at": "2026-07-31T12:00:00+00:00",
    }
    with pytest.raises(ProviderAttemptConflict):
        store.commit_execution(
            str(attempt["id"]),
            claim_id=str(claimed["claim_id"]),
        )
    with pytest.raises(ProviderAttemptConflict):
        store.claim(str(attempt["id"]))
    completed = store.complete(
        str(attempt["id"]),
        claim_id=str(claimed["claim_id"]),
        status="succeeded",
        output_sha256="e" * 64,
        output_size=2048,
    )
    assert completed["status"] == "succeeded"
    with pytest.raises(ProviderAttemptConflict):
        store.complete(
            str(attempt["id"]),
            claim_id=str(claimed["claim_id"]),
            status="failed",
            error_code="retry",
        )


def test_preflight_failure_is_terminal_without_execution_commit(
    attempt_store: tuple[ProviderAttemptStore, Database, Clock],
) -> None:
    store, _, _ = attempt_store
    attempt = create_attempt(store)
    claimed = store.claim(str(attempt["id"]))
    failed = store.fail_preflight(
        str(attempt["id"]),
        claim_id=str(claimed["claim_id"]),
        diagnostic="codex-not-authenticated",
    )
    assert failed["status"] == "failed"
    assert failed["execution_committed_at"] is None
    with pytest.raises(ProviderAttemptConflict):
        store.claim(str(attempt["id"]))


def test_claim_next_returns_none_then_the_oldest_claimable_attempt(
    attempt_store: tuple[ProviderAttemptStore, Database, Clock],
) -> None:
    store, _, _ = attempt_store
    assert store.claim_next() is None
    attempt = create_attempt(store)
    claimed = store.claim_next()
    assert claimed is not None
    assert claimed["id"] == attempt["id"]
    assert claimed["status"] == "claimed"
    assert store.claim_next() is None


def test_expired_precommit_claim_is_recoverable_but_commit_is_uncertain(
    attempt_store: tuple[ProviderAttemptStore, Database, Clock],
) -> None:
    store, _, clock = attempt_store
    attempt = create_attempt(store)
    claimed = store.claim(str(attempt["id"]), lease_seconds=30)
    store.select(
        str(attempt["id"]),
        claim_id=str(claimed["claim_id"]),
        provider="codex_cli",
        executable_identity=identity(),
    )
    clock.value = "2026-07-31T12:01:00+00:00"
    assert store.recover_interrupted() == {"uncertain": 0, "reset": 1}
    reclaimed = store.claim(str(attempt["id"]))
    assert reclaimed["claim_id"] != claimed["claim_id"]
    store.select(
        str(attempt["id"]),
        claim_id=str(reclaimed["claim_id"]),
        provider="codex_cli",
        executable_identity=identity(),
    )
    store.commit_execution(
        str(attempt["id"]),
        claim_id=str(reclaimed["claim_id"]),
    )
    clock.value = "2026-07-31T12:02:00+00:00"
    assert store.recover_interrupted() == {"uncertain": 1, "reset": 0}
    recovered = store.get(str(attempt["id"]))
    assert recovered["status"] == "uncertain"
    assert store.public_view(str(attempt["id"]))["requires_explicit_retry"] is True
    with pytest.raises(ProviderAttemptConflict):
        store.claim(str(attempt["id"]))


def test_public_view_never_exposes_execution_material(
    attempt_store: tuple[ProviderAttemptStore, Database, Clock],
) -> None:
    store, _, _ = attempt_store
    attempt = create_attempt(store)
    claimed = store.claim(str(attempt["id"]))
    store.select(
        str(attempt["id"]),
        claim_id=str(claimed["claim_id"]),
        provider="codex_cli",
        executable_identity=identity(),
    )
    view = store.public_view(str(attempt["id"]))
    serialized = str(view)
    assert "canonical_path" not in serialized
    assert "sha256" not in serialized
    assert "claim_id" not in serialized
    assert "evidence_path" not in serialized


def test_database_migration_from_schema_three_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA user_version = 3")
    connection.commit()
    connection.close()
    Database(database_path)
    Database(database_path)
    with sqlite3.connect(database_path) as migrated:
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == 4

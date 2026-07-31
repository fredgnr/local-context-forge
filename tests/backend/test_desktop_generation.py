from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.desktop_generation import DesktopProviderGenerator
from app.facts import FactsBundle
from app.generation import (
    GenerationCancelled,
    GenerationContext,
    GenerationError,
)
from app.provider_attempts import ProviderAttemptStore


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "metadata.sqlite3",
        qmd_enabled=False,
        ctags_enabled=False,
        runner_timeout_seconds=30,
    )


def _seed(database: Database) -> None:
    now = "2026-07-31T11:00:00+00:00"
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO libraries (
                id, name, slug, context7_id, source, created_at, updated_at
            ) VALUES (?, 'Library', 'library', '/library', '/tmp/source', ?, ?)
            """,
            ("a" * 32, now, now),
        )
        connection.execute(
            """
            INSERT INTO versions (
                id, library_id, version, source_sha, snapshot_path, facts_path,
                wiki_path, status, created_at
            ) VALUES (?, ?, 'v1', ?, 'snapshots/v1', 'facts/v1', 'wiki/v1',
                      'ready', ?)
            """,
            ("b" * 32, "a" * 32, "d" * 40, now),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                id, library_id, version_id, version, provider, queue_seq,
                status, stage, created_at, updated_at
            ) VALUES (?, ?, ?, 'v1', 'codex_cli', 1, 'running',
                      'generate', ?, ?)
            """,
            ("c" * 32, "a" * 32, "b" * 32, now, now),
        )


def _context(cancel=lambda: False) -> GenerationContext:
    return GenerationContext(
        library_name="Library",
        library_slug="library",
        version="v1",
        source_sha="d" * 40,
        facts=FactsBundle(
            root=Path("/tmp/facts"),
            manifest={"files": [], "languages": {}, "file_count": 0},
            symbols=[],
            evidence={"files": []},
        ),
        existing_wiki=[],
        runner_id="c" * 32,
        cancel_check=cancel,
    )


def _generator(
    tmp_path: Path,
    *,
    wait,
    monotonic=lambda: 0.0,
) -> tuple[DesktopProviderGenerator, ProviderAttemptStore]:
    settings = _settings(tmp_path)
    settings.ensure_directories()
    database = Database(settings.database_path)
    _seed(database)
    store = ProviderAttemptStore(
        database,
        now=lambda: "2026-07-31T12:00:00+00:00",
        identifiers=iter(
            [f"{number:032x}" for number in range(1, 20)]
        ).__next__,
    )
    return (
        DesktopProviderGenerator(
            settings,
            store,
            job_id="c" * 32,
            version_id="b" * 32,
            corpus_revision=3,
            policy="codex_only",
            wait=wait,
            monotonic=monotonic,
        ),
        store,
    )


def test_generator_creates_private_manifest_and_consumes_verified_output(
    tmp_path: Path,
) -> None:
    holder: dict[str, object] = {}

    def wait(_seconds: float) -> None:
        store = holder["store"]
        assert isinstance(store, ProviderAttemptStore)
        attempt = store.claim_next()
        assert attempt is not None
        store.select(
            str(attempt["id"]),
            claim_id=str(attempt["claim_id"]),
            provider="codex_cli",
            executable_identity={
                "provider": "codex_cli",
                "canonical_path": "/opt/codex",
                "sha256": "d" * 64,
                "size": 1,
                "mtime_ms": 1,
                "device": 1,
                "inode": 2,
                "mode": 0o100755,
                "version": "0.146.0",
            },
        )
        store.commit_execution(
            str(attempt["id"]),
            claim_id=str(attempt["claim_id"]),
        )
        output = b'{"pages":[{"path":"overview.md"}]}'
        output_path = (
            tmp_path / "provider-attempts" / ("c" * 32) / "result.json"
        )
        output_path.write_bytes(output)
        output_path.chmod(0o600)
        store.complete(
            str(attempt["id"]),
            claim_id=str(attempt["claim_id"]),
            status="succeeded",
            output_sha256=hashlib.sha256(output).hexdigest(),
            output_size=len(output),
        )

    generator, store = _generator(tmp_path, wait=wait)
    holder["store"] = store
    assert generator.generate(_context()) == [{"path": "overview.md"}]
    assert generator.effective_provider == "codex_cli"
    directory = tmp_path / "provider-attempts" / ("c" * 32)
    assert directory.stat().st_mode & 0o777 == 0o700
    manifest = json.loads((directory / "request.json").read_text())
    assert manifest["job_id"] == "c" * 32
    assert set(manifest["files"]) == {
        "evidence.json",
        "schema.json",
        "prompt.txt",
    }
    assert "OPENAI_API_KEY" not in (directory / "prompt.txt").read_text()


def test_generator_detects_output_tampering(tmp_path: Path) -> None:
    holder: dict[str, object] = {}

    def wait(_seconds: float) -> None:
        store = holder["store"]
        assert isinstance(store, ProviderAttemptStore)
        attempt = store.claim_next()
        assert attempt is not None
        store.select(
            str(attempt["id"]),
            claim_id=str(attempt["claim_id"]),
            provider="codex_cli",
            executable_identity={
                "provider": "codex_cli",
                "canonical_path": "/opt/codex",
                "sha256": "d" * 64,
                "size": 1,
                "mtime_ms": 1,
                "device": 1,
                "inode": 2,
                "mode": 0o100755,
                "version": "0.146.0",
            },
        )
        store.commit_execution(
            str(attempt["id"]),
            claim_id=str(attempt["claim_id"]),
        )
        expected = b'{"pages":[]}'
        output_path = (
            tmp_path / "provider-attempts" / ("c" * 32) / "result.json"
        )
        output_path.write_bytes(b'{"tampered":true}')
        store.complete(
            str(attempt["id"]),
            claim_id=str(attempt["claim_id"]),
            status="succeeded",
            output_sha256=hashlib.sha256(expected).hexdigest(),
            output_size=len(expected),
        )

    generator, store = _generator(tmp_path, wait=wait)
    holder["store"] = store
    with pytest.raises(GenerationError, match="metadata changed|digest changed"):
        generator.generate(_context())


def test_generator_cancels_before_main_claim(tmp_path: Path) -> None:
    generator, store = _generator(tmp_path, wait=lambda _seconds: None)
    with pytest.raises(GenerationCancelled):
        generator.generate(_context(cancel=lambda: True))
    attempt = store.claim_next()
    assert attempt is None
    row = store._database.fetchone(  # noqa: SLF001 - assert durable state
        "SELECT status FROM provider_attempts WHERE job_id = ?",
        ("c" * 32,),
    )
    assert row == {"status": "cancelled"}

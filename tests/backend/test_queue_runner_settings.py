from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from app.config import Settings
from app.db import Database
from app.facts import FactsBundle
from app.generation import GenerationContext, HostCliSpoolGenerator
from app.service import (
    DEFAULT_EMBEDDING_MODEL,
    AppService,
    ConflictError,
    ValidationError,
)
from conftest import create_fixture_repository


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "data_dir": tmp_path / "data",
        "database_path": tmp_path / "data" / "metadata.sqlite3",
        "qmd_enabled": False,
        "local_source_roots": (tmp_path,),
    }
    values.update(overrides)
    return Settings(**values)


def _context(tmp_path: Path, runner_id: str) -> GenerationContext:
    return GenerationContext(
        library_name="Widgets",
        library_slug="widgets",
        version="v1",
        source_sha="a" * 40,
        facts=FactsBundle(
            root=tmp_path,
            manifest={
                "file_count": 1,
                "languages": {"Python": 1},
                "files": [{"path": "widgets.py", "role": "source"}],
            },
            symbols=[],
            evidence={
                "files": [
                    {
                        "path": "widgets.py",
                        "language": "Python",
                        "role": "source",
                        "content": "def widget():\n    pass\n",
                        "truncated": False,
                    }
                ]
            },
        ),
        existing_wiki=[],
        runner_id=runner_id,
    )


def _wait_until(predicate, timeout: float = 5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def test_host_runner_timeout_uses_canonical_env_with_legacy_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LCF_DATA_DIR", str(tmp_path / "canonical"))
    monkeypatch.setenv("LCF_HOST_RUNNER_TIMEOUT_SECONDS", "42")
    monkeypatch.setenv("LCF_RUNNER_TIMEOUT_SECONDS", "99")

    canonical = Settings.from_env()

    assert canonical.runner_timeout_seconds == 42
    assert canonical.runner_max_response_bytes == 2_097_152
    monkeypatch.delenv("LCF_HOST_RUNNER_TIMEOUT_SECONDS")
    assert Settings.from_env().runner_timeout_seconds == 99


def test_host_runner_spool_uses_exact_contract_and_removes_response(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        runner_dir=tmp_path / "runner",
        runner_timeout_seconds=30,
    )
    settings.ensure_directories()
    request_id = "a" * 32
    response_path = settings.runner_outbox_dir / f"{request_id}.json"
    request_path = settings.runner_inbox_dir / f"{request_id}.json"

    def respond() -> None:
        assert _wait_until(request_path.is_file)
        response_path.write_text(
            json.dumps(
                {
                    "id": request_id,
                    "task": "wiki_v1",
                    "completed_at": 1_785_283_200,
                    "requested_provider": "auto",
                    "effective_provider": "cursor_cli",
                    "fallback_reason": "codex authentication unavailable",
                    "result": {"pages": []},
                    "error": None,
                }
            ),
            encoding="utf-8",
        )

    responder = threading.Thread(target=respond)
    responder.start()

    generator = HostCliSpoolGenerator(settings, "auto")
    assert generator.generate(_context(tmp_path, request_id)) == []
    responder.join(5)
    assert not responder.is_alive()
    request = json.loads(
        request_path.read_text(encoding="utf-8")
    )
    assert set(request) == {
        "id",
        "task",
        "provider",
        "timeout_seconds",
        "evidence",
        "output_schema",
    }
    assert request["id"] == request_id
    assert request["provider"] == "auto"
    assert generator.effective_provider == "cursor_cli"
    assert generator.fallback_reason == "codex authentication unavailable"
    assert not response_path.exists()


def test_host_runner_cancellation_waits_for_runner_completion_boundary(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        runner_dir=tmp_path / "runner",
        runner_timeout_seconds=30,
    )
    settings.ensure_directories()
    request_id = "b" * 32
    (settings.runner_outbox_dir / f"{request_id}.json").write_text(
        json.dumps(
            {
                "id": request_id,
                "task": "wiki_v1",
                "completed_at": 1,
                "requested_provider": "codex_cli",
                "effective_provider": "codex_cli",
                "fallback_reason": None,
                "result": {"pages": []},
                "error": None,
            }
        ),
        encoding="utf-8",
    )
    context = _context(tmp_path, request_id)
    context.cancel_check = lambda: True

    pages = HostCliSpoolGenerator(settings, "codex_cli").generate(context)

    # The pipeline checks cancellation immediately after this return. The
    # adapter itself must not pretend it terminated the separately owned CLI.
    assert pages == []


def test_database_migrates_legacy_jobs_and_backfills_fifo_sequence(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                library_id TEXT NOT NULL,
                version_id TEXT,
                version TEXT NOT NULL,
                provider TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO jobs VALUES
                ('b', 'library', NULL, 'v2', 'mock', 'queued', 'queued',
                 0, '', NULL, '2026-01-02', '2026-01-02'),
                ('a', 'library', NULL, 'v1', 'mock', 'queued', 'queued',
                 0, '', NULL, '2026-01-01', '2026-01-01');
            """
        )

    database = Database(database_path)
    rows = database.fetchall(
        "SELECT id, kind, queue_seq, attempt FROM jobs ORDER BY queue_seq"
    )

    assert rows == [
        {"id": "a", "kind": "ingest", "queue_seq": 1, "attempt": 1},
        {"id": "b", "kind": "ingest", "queue_seq": 2, "attempt": 1},
    ]


def test_database_migration_is_safe_during_concurrent_startup(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-concurrent.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                library_id TEXT NOT NULL,
                version_id TEXT,
                version TEXT NOT NULL,
                provider TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO jobs VALUES (
                'legacy', 'library', NULL, 'v1', 'mock', 'queued', 'queued',
                0, '', NULL, '2026-01-01', '2026-01-01'
            )
            """
        )

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def initialize() -> None:
        try:
            barrier.wait()
            Database(database_path)
        except Exception as error:  # noqa: BLE001 - asserted below
            errors.append(error)

    threads = [threading.Thread(target=initialize) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    database = Database(database_path)
    assert database.fetchone(
        "SELECT queue_seq, kind, attempt FROM jobs WHERE id = 'legacy'"
    ) == {"queue_seq": 1, "kind": "ingest", "attempt": 1}


def test_database_refuses_unknown_future_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "future.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 999")

    with pytest.raises(RuntimeError, match="newer than supported"):
        Database(database_path)


def test_standby_worker_takes_over_without_process_restart(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, worker_poll_seconds=0.02)
    primary = AppService(settings)
    standby = AppService(settings)
    try:
        primary.start_worker()
        assert _wait_until(lambda: bool(primary.dispatcher.active))
        standby.start_worker()
        assert _wait_until(lambda: bool(standby.dispatcher.running))
        assert standby.dispatcher.active is False

        primary.close()

        assert _wait_until(lambda: bool(standby.dispatcher.active))
        assert standby.system_status()["queue"]["worker_running"] is True
    finally:
        primary.close()
        standby.close()


def test_existing_corpus_without_revision_is_forced_stale(
    tmp_path: Path,
) -> None:
    repository = create_fixture_repository(tmp_path)
    settings = _settings(
        tmp_path,
        qmd_enabled=False,
        qmd_hybrid_enabled=True,
    )
    service = AppService(settings)
    library = service.create_library(
        {"name": "Widgets", "source": str(repository)}
    )
    ingest = service.create_ingest_job(
        library["id"],
        version="v1",
        ref="HEAD",
        provider="mock",
        auto_publish=True,
    )
    assert service.run_ingest_job(ingest["id"])["status"] == "completed"
    with service.db.transaction() as connection:
        connection.execute(
            """
            UPDATE embedding_state
            SET status = 'ready', corpus_revision = 0,
                indexed_revision = 0, error = NULL
            WHERE id = 1
            """
        )
    service.close()

    reopened = AppService(settings)
    embedding = reopened.embedding_status()

    assert embedding["status"] == "stale"
    assert embedding["corpus_revision"] == 1
    assert embedding["indexed_revision"] == 0
    assert embedding["hybrid_ready"] is False
    reopened.close()


def test_cancelled_queued_job_can_be_retried_with_new_fifo_sequence(
    tmp_path: Path,
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = AppService(_settings(tmp_path))
    library = service.create_library(
        {"name": "Widgets", "source": str(repository)}
    )
    original = service.create_ingest_job(
        library["id"],
        version="v1",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )

    cancelled = service.cancel_job(original["id"])
    retried = service.retry_job(original["id"])
    repeated = service.retry_job(original["id"])

    assert cancelled["status"] == "cancelled"
    assert retried["status"] == "queued"
    assert retried["retry_of"] == original["id"]
    assert retried["attempt"] == 2
    assert retried["queue_seq"] > original["queue_seq"]
    assert retried["request"]["source"] == str(repository)
    assert repeated["id"] == retried["id"]
    assert repeated["idempotent_retry"] is True


def test_cli_retry_blocks_while_original_runner_request_can_execute(
    tmp_path: Path,
) -> None:
    repository = create_fixture_repository(tmp_path)
    settings = _settings(tmp_path, runner_dir=tmp_path / "runner")
    service = AppService(settings)
    library = service.create_library(
        {"name": "Widgets", "source": str(repository)}
    )
    original = service.create_ingest_job(
        library["id"],
        version="v1",
        ref="HEAD",
        provider="codex_cli",
        auto_publish=False,
    )
    assert service._claim_queued_job(original["id"]) is True
    assert service._mark_job_failed(
        original["id"],
        stage="orphaned",
        message="worker interrupted",
        error="fixture",
    )
    working = settings.resolved_runner_dir / "working"
    working.mkdir(parents=True, exist_ok=True)
    (working / f"{original['id']}.json").write_text(
        json.dumps({"id": original["id"]}),
        encoding="utf-8",
    )

    with pytest.raises(ConflictError, match="duplicate usage"):
        service.retry_job(original["id"])


def test_cli_retry_reuses_completed_runner_response_without_second_call(
    tmp_path: Path,
) -> None:
    repository = create_fixture_repository(tmp_path)
    settings = _settings(tmp_path, runner_dir=tmp_path / "runner")
    service = AppService(settings)
    library = service.create_library(
        {"name": "Widgets", "source": str(repository)}
    )
    original = service.create_ingest_job(
        library["id"],
        version="v1",
        ref="HEAD",
        provider="codex_cli",
        auto_publish=False,
    )
    assert service._claim_queued_job(original["id"]) is True
    assert service._mark_job_failed(
        original["id"],
        stage="orphaned",
        message="worker interrupted",
        error="fixture",
    )
    old_response = settings.runner_outbox_dir / f"{original['id']}.json"
    old_response.write_text(
        json.dumps(
            {
                "id": original["id"],
                "task": "wiki_v1",
                "completed_at": 1_785_283_200,
                "requested_provider": "codex_cli",
                "effective_provider": "codex_cli",
                "fallback_reason": None,
                "result": {"pages": []},
                "error": None,
            }
        ),
        encoding="utf-8",
    )

    retried = service.retry_job(original["id"])
    reused = json.loads(
        (settings.runner_outbox_dir / f"{retried['id']}.json").read_text(
            encoding="utf-8"
        )
    )

    assert reused["id"] == retried["id"]
    assert reused["result"] == {"pages": []}
    assert not old_response.exists()
    assert service.run_ingest_job(retried["id"])["status"] == "failed"
    assert not (
        settings.runner_inbox_dir / f"{retried['id']}.json"
    ).exists()


def test_cancelling_job_blocks_library_delete(tmp_path: Path) -> None:
    repository = create_fixture_repository(tmp_path)
    service = AppService(_settings(tmp_path))
    library = service.create_library(
        {"name": "Widgets", "source": str(repository)}
    )
    job = service.create_ingest_job(
        library["id"],
        version="v1",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )
    assert service._claim_queued_job(job["id"]) is True
    assert service.cancel_job(job["id"])["status"] == "cancelling"

    with pytest.raises(ConflictError, match="cancelling"):
        service.delete_library(library["id"], purge=True)


def test_settings_patch_without_revision_is_compatible_and_validated(
    tmp_path: Path,
) -> None:
    service = AppService(_settings(tmp_path))
    before = service.get_settings()
    model = next(
        item["model"]
        for item in service.embedding_models()
        if item["id"] == "qwen3-embedding-0.6b-q8"
    )

    updated = service.patch_settings({"embedding_model": model})

    assert updated["revision"] == before["revision"] + 1
    assert updated["embedding_model"] == model
    assert updated["embedding"]["active_model"] == model
    assert updated["embedding"]["status"] == "ready"
    with pytest.raises(ValidationError, match="concurrency=1"):
        service.patch_settings({"concurrency": 2})


def test_auto_provider_honors_runtime_priority_and_fallback_policy(
    tmp_path: Path,
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = AppService(_settings(tmp_path))
    current = service.get_settings()
    service.patch_settings(
        {
            "expected_revision": current["revision"],
            "provider_order": ["cursor_cli", "codex_cli"],
            "fallback_enabled": True,
        }
    )
    library = service.create_library(
        {"name": "Widgets", "source": str(repository)}
    )

    job = service.create_ingest_job(
        library["id"],
        version="v1",
        ref="HEAD",
        provider="auto",
        auto_publish=False,
    )

    assert job["provider"] == "cursor_cli"
    assert job["request"]["provider"] == "cursor_cli"


def test_new_database_honors_mock_installer_default(tmp_path: Path) -> None:
    repository = create_fixture_repository(tmp_path)
    service = AppService(_settings(tmp_path, default_provider="mock"))
    library = service.create_library(
        {"name": "Widgets", "source": str(repository)}
    )

    job = service.create_ingest_job(
        library["id"],
        version="v1",
        ref="HEAD",
        provider="auto",
        auto_publish=False,
    )

    assert service.get_settings()["provider_order"] == ["mock"]
    assert job["provider"] == "mock"
    assert service.run_ingest_job(job["id"])["status"] == "completed"


def test_installer_default_does_not_overwrite_existing_web_setting(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, default_provider="mock")
    first = AppService(settings)
    current = first.get_settings()
    first.patch_settings(
        {
            "expected_revision": current["revision"],
            "provider_order": ["codex_cli", "cursor_cli"],
            "fallback_enabled": True,
        }
    )
    first.close()

    reopened = AppService(settings)

    assert reopened.get_settings()["provider_order"] == [
        "codex_cli",
        "cursor_cli",
    ]
    assert reopened.get_settings()["fallback_enabled"] is True


def test_embedding_validation_canonicalizes_presets_and_safe_custom_ids(
    tmp_path: Path,
) -> None:
    service = AppService(_settings(tmp_path))
    preset = service.validate_embedding_model("embeddinggemma-300m-q8")
    custom = service.validate_embedding_model(
        "hf:example-org/Qwen3-Embedding-Code/"
        "models/Qwen3-Embedding-Code-Q8_0.gguf"
    )

    assert preset["canonical_model"] == DEFAULT_EMBEDDING_MODEL
    assert preset["curated"] is True
    assert custom["curated"] is False
    with pytest.raises(ValidationError, match="EmbeddingGemma or Qwen3"):
        service.validate_embedding_model(
            "hf:example-org/other-model/models/other-model-Q8_0.gguf"
        )
    with pytest.raises(ValidationError, match="HTTP endpoints"):
        service.validate_embedding_model("https://example.invalid/embed")


def test_failed_global_embedding_rebuild_keeps_query_lexical(
    tmp_path: Path,
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = AppService(
        _settings(tmp_path, qmd_hybrid_enabled=True, qmd_enabled=False)
    )
    library = service.create_library(
        {"name": "Widgets", "source": str(repository)}
    )
    ingest = service.create_ingest_job(
        library["id"],
        version="v1",
        ref="HEAD",
        provider="mock",
        auto_publish=True,
    )
    assert service.run_ingest_job(ingest["id"])["status"] == "completed"
    rebuild = service.create_rebuild_job(
        model=None,
        scope_library_id=None,
    )

    failed = service.run_rebuild_job(rebuild["id"])
    result = service.query("build_widget", library_id=library["id"])

    assert failed["status"] == "failed"
    assert service.embedding_status()["status"] == "failed"
    assert result["engine"] == "lexical"
    assert result["results"]


def test_concurrent_rebuild_requests_enqueue_only_one_active_job(
    tmp_path: Path,
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = AppService(_settings(tmp_path))
    library = service.create_library(
        {"name": "Widgets", "source": str(repository)}
    )
    ingest = service.create_ingest_job(
        library["id"],
        version="v1",
        ref="HEAD",
        provider="mock",
        auto_publish=True,
    )
    assert service.run_ingest_job(ingest["id"])["status"] == "completed"
    barrier = threading.Barrier(2)
    jobs: list[dict] = []
    errors: list[Exception] = []

    def enqueue() -> None:
        try:
            barrier.wait()
            jobs.append(
                service.create_rebuild_job(
                    model=None,
                    scope_library_id=None,
                )
            )
        except Exception as error:  # noqa: BLE001 - asserted below
            errors.append(error)

    threads = [threading.Thread(target=enqueue) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert len(jobs) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], ConflictError)
    active = service.db.fetchall(
        """
        SELECT id FROM jobs
        WHERE kind = 'embedding_rebuild'
          AND status IN ('queued', 'running', 'cancelling')
        """
    )
    assert active == [{"id": jobs[0]["id"]}]


def test_system_status_accepts_only_fresh_sanitized_runner_heartbeat(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, runner_dir=tmp_path / "runner")
    service = AppService(settings)
    heartbeat = {
        "schema_version": 1,
        "status": "ready",
        "pid": 12345,
        "updated_at": time.time(),
        "active_task": "secret-repository",
        "providers": {
            "codex_cli": {
                "installed": True,
                "authenticated": True,
                "usable": True,
                "version": "1.2.3",
            },
            "cursor_cli": {
                "installed": True,
                "authenticated": None,
                "usable": True,
                "version": None,
            },
        },
    }
    (settings.resolved_runner_dir / "heartbeat.json").write_text(
        json.dumps(heartbeat),
        encoding="utf-8",
    )

    status = service.system_status()
    providers = status["providers"]

    assert providers["status"] == "ready"
    assert providers["providers"]["cursor_cli"]["authenticated"] is None
    encoded = json.dumps(providers)
    assert "pid" not in encoded
    assert "secret-repository" not in encoded
    assert status["ready"] is True
    assert status["initialized"] is True
    assert isinstance(status["checks"], list)


def test_system_status_requires_a_usable_configured_cli(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, runner_dir=tmp_path / "runner")
    service = AppService(settings)
    (settings.resolved_runner_dir / "heartbeat.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "ready",
                "pid": 1,
                "updated_at": time.time(),
                "active_task": None,
                "providers": {
                    "codex_cli": {
                        "installed": True,
                        "authenticated": False,
                        "usable": False,
                        "version": "1",
                    },
                    "cursor_cli": {
                        "installed": False,
                        "authenticated": None,
                        "usable": False,
                        "version": None,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    status = service.system_status()

    assert status["providers"]["status"] == "ready"
    assert status["ready"] is False
    host_check = next(
        item for item in status["checks"] if item["id"] == "host-runner"
    )
    assert host_check["status"] == "error"
    assert host_check["label"] == "Host CLI runner"

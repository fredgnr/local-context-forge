from __future__ import annotations

import json
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

import app.service as service_module
import pytest
from app.config import Settings
from app.generation import GenerationError
from app.service import AppService, ConflictError, NotFoundError, ValidationError
from app.wiki import WikiError, WikiStore
from conftest import create_fixture_repository


def _service(tmp_path: Path) -> AppService:
    data = tmp_path / "data"
    return AppService(
        Settings(
            data_dir=data,
            database_path=data / "metadata.sqlite3",
            qmd_enabled=False,
            local_source_roots=(tmp_path,),
        )
    )


def _pending_proposal(tmp_path: Path) -> tuple[AppService, dict, dict]:
    repository = create_fixture_repository(tmp_path)
    service = _service(tmp_path)
    library = service.create_library({"name": "Widgets", "source": str(repository)})
    job = service.create_ingest_job(
        library["id"],
        version="main",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )
    assert service.run_ingest_job(job["id"])["status"] == "completed"
    proposal = service.list_proposals(library["id"], status="pending")[0]
    return service, library, proposal


def test_queued_job_blocks_library_delete(tmp_path: Path) -> None:
    repository = create_fixture_repository(tmp_path)
    service = _service(tmp_path)
    library = service.create_library({"name": "Widgets", "source": str(repository)})
    job = service.create_ingest_job(
        library["id"],
        version="main",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )

    with pytest.raises(ConflictError, match="queued.*running"):
        service.delete_library(library["id"], purge=True)
    assert service.get_job(job["id"])["status"] == "queued"
    assert (service.settings.jobs_dir / f"{job['id']}.json").is_file()


def test_multiple_ingests_are_assigned_strict_fifo_sequence(
    tmp_path: Path,
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = _service(tmp_path)
    library = service.create_library({"name": "Widgets", "source": str(repository)})
    first = service.create_ingest_job(
        library["id"],
        version="one",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )

    second = service.create_ingest_job(
        library["id"],
        version="two",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )

    assert service.get_job(first["id"])["status"] == "queued"
    assert first["queue_seq"] < second["queue_seq"]
    assert first["queue_position"] == 1
    assert second["queue_position"] == 2


def test_delete_holds_catalog_lock_until_slug_artifacts_are_purged(
    tmp_path: Path, monkeypatch
) -> None:
    repository = create_fixture_repository(tmp_path)
    deleting_service = _service(tmp_path)
    creating_service = _service(tmp_path)
    library = deleting_service.create_library(
        {"name": "Widgets", "slug": "widgets", "source": str(repository)}
    )
    old_artifact = deleting_service.settings.sources_dir / "widgets" / "old"
    old_artifact.mkdir(parents=True)
    entered_purge = threading.Event()
    release_purge = threading.Event()
    create_finished = threading.Event()
    original_rmtree = service_module.shutil.rmtree

    def blocking_rmtree(path, *args, **kwargs):
        if Path(path) == deleting_service.settings.sources_dir / "widgets":
            entered_purge.set()
            assert release_purge.wait(5)
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(service_module.shutil, "rmtree", blocking_rmtree)
    delete_result: dict[str, object] = {}
    create_result: dict[str, object] = {}

    def delete_old() -> None:
        delete_result.update(
            deleting_service.delete_library(library["id"], purge=True)
        )

    def create_new() -> None:
        created = creating_service.create_library(
            {"name": "Widgets", "slug": "widgets", "source": str(repository)}
        )
        marker = creating_service.settings.sources_dir / "widgets" / "new"
        marker.mkdir(parents=True)
        create_result.update(created)
        create_finished.set()

    delete_thread = threading.Thread(target=delete_old)
    create_thread = threading.Thread(target=create_new)
    delete_thread.start()
    assert entered_purge.wait(5)
    create_thread.start()
    assert not create_finished.wait(0.2)
    release_purge.set()
    delete_thread.join(5)
    create_thread.join(5)

    assert delete_result["deleted"] is True
    assert create_result["slug"] == "widgets"
    assert (creating_service.settings.sources_dir / "widgets" / "new").is_dir()


def test_enqueue_rechecks_library_after_acquiring_lifecycle_lock(
    tmp_path: Path, monkeypatch
) -> None:
    repository = create_fixture_repository(tmp_path)
    creating_service = _service(tmp_path)
    deleting_service = _service(tmp_path)
    library = creating_service.create_library(
        {"name": "Widgets", "source": str(repository)}
    )
    initial_lookup_finished = threading.Event()
    continue_enqueue = threading.Event()
    original_lock_for_library = creating_service._lock_for_library
    result: dict[str, object] = {}

    def delayed_lock_for_library(library_id: str):
        initial_lookup_finished.set()
        assert continue_enqueue.wait(5)
        return original_lock_for_library(library_id)

    def enqueue() -> None:
        try:
            creating_service.create_ingest_job(
                library["id"],
                version="main",
                ref="HEAD",
                provider="mock",
                auto_publish=False,
            )
        except Exception as error:  # noqa: BLE001 - asserted below
            result["error"] = error

    monkeypatch.setattr(
        creating_service, "_lock_for_library", delayed_lock_for_library
    )
    enqueue_thread = threading.Thread(target=enqueue)
    enqueue_thread.start()
    assert initial_lookup_finished.wait(5)
    assert deleting_service.delete_library(library["id"], purge=True)["deleted"]
    continue_enqueue.set()
    enqueue_thread.join(5)

    assert isinstance(result.get("error"), NotFoundError)
    assert list(creating_service.settings.jobs_dir.glob("*.json")) == []


def test_database_request_survives_missing_sidecar_and_source_change(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first = create_fixture_repository(first_root)
    second = create_fixture_repository(second_root)
    service = _service(tmp_path)
    library = service.create_library({"name": "Widgets", "source": str(first)})
    job = service.create_ingest_job(
        library["id"],
        version="requested-main",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )
    (service.settings.jobs_dir / f"{job['id']}.json").unlink()
    service.update_library(library["id"], {"source": str(second)})

    completed = service.run_ingest_job(job["id"])
    assert completed["status"] == "completed"
    assert completed["version"].startswith("requested-main+git.")
    assert len(service.get_library(library["id"])["versions"]) == 1


def test_first_generation_failure_marks_version_failed(
    tmp_path: Path, monkeypatch
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = _service(tmp_path)
    library = service.create_library({"name": "Widgets", "source": str(repository)})

    class FailedGenerator:
        def generate(self, _context):
            raise GenerationError("fixture generation failure")

    monkeypatch.setattr(
        service_module, "get_generator", lambda _provider, _settings: FailedGenerator()
    )
    job = service.create_ingest_job(
        library["id"],
        version="broken",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )
    failed = service.run_ingest_job(job["id"])
    assert failed["status"] == "failed"
    versions = service.get_library(library["id"])["versions"]
    assert len(versions) == 1
    assert versions[0]["status"] == "failed"


def test_empty_generator_output_cannot_activate_an_empty_version(
    tmp_path: Path, monkeypatch
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = _service(tmp_path)
    library = service.create_library({"name": "Widgets", "source": str(repository)})

    class EmptyGenerator:
        def generate(self, _context):
            return []

    monkeypatch.setattr(
        service_module, "get_generator", lambda _provider, _settings: EmptyGenerator()
    )
    job = service.create_ingest_job(
        library["id"],
        version="empty",
        ref="HEAD",
        provider="mock",
        auto_publish=True,
    )
    failed = service.run_ingest_job(job["id"])

    assert failed["status"] == "failed"
    current = service.get_library(library["id"])
    assert current["default_version"] is None
    assert current["versions"][0]["status"] == "failed"
    assert service.list_pages(library["id"]) == []


def test_publish_rolls_git_back_when_sqlite_commit_fails(
    tmp_path: Path, monkeypatch
) -> None:
    service, library, proposal = _pending_proposal(tmp_path)
    original_transaction = service.db.transaction

    @contextmanager
    def failed_transaction():
        raise RuntimeError("fixture sqlite failure")
        yield

    monkeypatch.setattr(service.db, "transaction", failed_transaction)
    with pytest.raises(RuntimeError, match="fixture sqlite failure"):
        service.publish_proposal(proposal["id"], reindex=False)
    monkeypatch.setattr(service.db, "transaction", original_transaction)

    assert service.get_proposal(proposal["id"])["status"] == "pending"
    assert service.list_pages(library["id"]) == []
    version = service.get_library(library["id"])["versions"][0]
    wiki_root = Path(version["wiki_path"]).parents[1]
    commits = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=wiki_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert commits == "1"
    assert not Path(version["wiki_path"]).exists()


def test_interrupted_wiki_initialization_is_retryable(
    tmp_path: Path, monkeypatch
) -> None:
    service, library, proposal = _pending_proposal(tmp_path)
    original_git = WikiStore._git
    failed_once = False

    def fail_initial_commit_once(self, arguments, *, allow_empty=False):
        nonlocal failed_once
        if (
            arguments == ["commit", "-m", "Initialize generated API wiki"]
            and not failed_once
        ):
            failed_once = True
            raise WikiError("fixture interrupted initialization")
        return original_git(self, arguments, allow_empty=allow_empty)

    monkeypatch.setattr(WikiStore, "_git", fail_initial_commit_once)
    with pytest.raises(ConflictError, match="inconsistent on-disk"):
        service.publish_proposal(proposal["id"], reindex=False)
    assert service.get_proposal(proposal["id"])["status"] == "pending"

    published = service.publish_proposal(proposal["id"], reindex=False)
    assert published["proposal"]["status"] == "published"
    assert published["activation"]["activated"] is False
    assert len(
        service.list_pages(library["id"], published["proposal"]["version"])
    ) == 1
    assert (
        service.lint(library["id"], published["proposal"]["version"])["ok"]
        is True
    )


def test_wiki_publication_does_not_execute_restored_git_hooks(
    tmp_path: Path,
) -> None:
    service, library, proposal = _pending_proposal(tmp_path)
    wiki = WikiStore(service.settings, library["slug"])
    wiki.initialize()
    sentinel = tmp_path / "hook-executed"
    hook = wiki.root / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        f"#!/bin/sh\nprintf unsafe > '{sentinel}'\nexit 1\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)

    published = service.publish_proposal(proposal["id"], reindex=False)

    assert published["proposal"]["status"] == "published"
    assert not sentinel.exists()


def test_wiki_status_does_not_honor_restored_ignore_rules(tmp_path: Path) -> None:
    service = _service(tmp_path)
    wiki = WikiStore(service.settings, "ignored")
    wiki.initialize()
    (wiki.root / ".gitignore").write_text("*.txt\n", encoding="utf-8")
    (wiki.root / "hidden.txt").write_text("dirty\n", encoding="utf-8")

    status = wiki.git_status()

    assert "?? .gitignore" in status
    assert "?? hidden.txt" in status


def test_wiki_rejects_symlinked_restored_config(tmp_path: Path) -> None:
    service = _service(tmp_path)
    wiki = WikiStore(service.settings, "config-link")
    wiki.initialize()
    config = wiki.root / ".git" / "config"
    config.unlink()
    config.symlink_to(tmp_path / "outside.gitconfig")

    with pytest.raises(WikiError, match="config must be a regular"):
        wiki.git_status()


def test_wiki_clean_refuses_symlinked_scope_ancestor(tmp_path: Path) -> None:
    service = _service(tmp_path)
    wiki = WikiStore(service.settings, "clean-link")
    wiki.initialize()
    outside = tmp_path / "outside-wiki"
    target = outside / "v1"
    target.mkdir(parents=True)
    sentinel = target / "keep.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    (wiki.root / "versions").symlink_to(outside, target_is_directory=True)

    with pytest.raises(WikiError, match="contains a symlink"):
        wiki._git(["clean", "-fd", "--", "versions/v1"])

    assert sentinel.read_text(encoding="utf-8") == "keep\n"


def test_publish_rejects_ref_outside_recorded_generation_evidence(
    tmp_path: Path,
) -> None:
    service, _library, proposal = _pending_proposal(tmp_path)
    metadata = proposal["metadata"]
    allowed = metadata["generation_evidence_ranges"][0]
    metadata["source_refs"] = [
        {
            "path": allowed["path"],
            "line_start": int(allowed["line_end"]) + 1,
            "line_end": int(allowed["line_end"]) + 1,
        }
    ]
    with service.db.transaction() as connection:
        connection.execute(
            "UPDATE proposals SET metadata_json = ? WHERE id = ?",
            (json.dumps(metadata), proposal["id"]),
        )

    with pytest.raises(ValidationError) as captured:
        service.publish_proposal(proposal["id"], reindex=False)
    assert {
        issue["code"] for issue in captured.value.issues
    } >= {"source-ref-outside-evidence"}


def test_publish_and_reject_share_one_review_barrier(
    tmp_path: Path, monkeypatch
) -> None:
    service, library, proposal = _pending_proposal(tmp_path)
    entered_publish = threading.Event()
    release_publish = threading.Event()
    reject_finished = threading.Event()
    original_publish = WikiStore.publish
    results: dict[str, object] = {}

    def blocking_publish(self, *args, **kwargs):
        entered_publish.set()
        assert release_publish.wait(5)
        return original_publish(self, *args, **kwargs)

    def publish() -> None:
        results["publish"] = service.publish_proposal(
            proposal["id"], reindex=False
        )

    def reject() -> None:
        try:
            service.reject_proposal(proposal["id"], "racing rejection")
        except Exception as error:  # noqa: BLE001 - asserted below
            results["reject_error"] = error
        finally:
            reject_finished.set()

    monkeypatch.setattr(WikiStore, "publish", blocking_publish)
    publish_thread = threading.Thread(target=publish)
    reject_thread = threading.Thread(target=reject)
    publish_thread.start()
    assert entered_publish.wait(5)
    reject_thread.start()
    assert not reject_finished.wait(0.2)
    release_publish.set()
    publish_thread.join(5)
    reject_thread.join(5)

    assert isinstance(results.get("reject_error"), ConflictError)
    assert service.get_proposal(proposal["id"])["status"] == "published"
    assert len(
        service.list_pages(library["id"], proposal["version"])
    ) == 1


def test_reingest_never_mutates_an_already_materialized_version(
    tmp_path: Path, monkeypatch
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = _service(tmp_path)
    library = service.create_library({"name": "Widgets", "source": str(repository)})
    initial = service.create_ingest_job(
        library["id"],
        version="main",
        ref="HEAD",
        provider="mock",
        auto_publish=True,
    )
    published = service.run_ingest_job(initial["id"])
    assert published["status"] == "completed"

    rejected_manual_refresh = service.create_ingest_job(
        library["id"],
        version="main",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )
    manual = service.run_ingest_job(rejected_manual_refresh["id"])
    assert manual["status"] == "failed"
    assert "already materialized" in str(manual["error"])
    assert service.get_library(library["id"])["versions"][0]["status"] == "published"

    rejected_auto_refresh = service.create_ingest_job(
        library["id"],
        version="main",
        ref="HEAD",
        provider="mock",
        auto_publish=True,
    )
    rejected = service.run_ingest_job(rejected_auto_refresh["id"])
    assert rejected["status"] == "failed"
    assert "already materialized" in str(rejected["error"])

    class FailedGenerator:
        def generate(self, _context):
            raise GenerationError("fixture refresh failure")

    monkeypatch.setattr(
        service_module, "get_generator", lambda _provider, _settings: FailedGenerator()
    )
    failed_refresh = service.create_ingest_job(
        library["id"],
        version="main",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )
    assert service.run_ingest_job(failed_refresh["id"])["status"] == "failed"
    current = service.get_library(library["id"])
    assert current["versions"][0]["status"] == "published"
    assert current["default_version"] == published["version"]
    assert service.list_pages(library["id"], published["version"])


def test_failed_refresh_preserves_existing_proposed_materialization(
    tmp_path: Path, monkeypatch
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = _service(tmp_path)
    library = service.create_library({"name": "Widgets", "source": str(repository)})
    initial = service.create_ingest_job(
        library["id"],
        version="main",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )
    assert service.run_ingest_job(initial["id"])["status"] == "completed"
    pending_before = service.list_proposals(library["id"], status="pending")
    assert pending_before
    assert service.get_library(library["id"])["versions"][0]["status"] == "proposed"

    class FailedGenerator:
        def generate(self, _context):
            raise GenerationError("fixture refresh failure")

    monkeypatch.setattr(
        service_module, "get_generator", lambda _provider, _settings: FailedGenerator()
    )
    refresh = service.create_ingest_job(
        library["id"],
        version="main",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )
    assert service.run_ingest_job(refresh["id"])["status"] == "failed"
    assert service.get_library(library["id"])["versions"][0]["status"] == "proposed"
    assert {
        item["id"] for item in service.list_proposals(library["id"], status="pending")
    } >= {item["id"] for item in pending_before}


def test_auto_publish_partial_failure_never_activates_incomplete_version(
    tmp_path: Path, monkeypatch
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = _service(tmp_path)
    library = service.create_library({"name": "Widgets", "source": str(repository)})
    original_publish = WikiStore.publish
    publish_calls = 0

    def fail_second_publish(self, *args, **kwargs):
        nonlocal publish_calls
        publish_calls += 1
        if publish_calls == 2:
            raise WikiError("fixture second-page failure")
        return original_publish(self, *args, **kwargs)

    monkeypatch.setattr(WikiStore, "publish", fail_second_publish)
    job = service.create_ingest_job(
        library["id"],
        version="main",
        ref="HEAD",
        provider="mock",
        auto_publish=True,
    )
    failed = service.run_ingest_job(job["id"])

    assert failed["status"] == "failed"
    assert "not activated as default" in failed["message"]
    current = service.get_library(library["id"])
    assert current["default_version"] is None
    assert current["versions"][0]["status"] == "partial"
    assert service.list_pages(library["id"]) == []
    assert service.list_pages(library["id"], "main") == []
    assert len(service.list_pages(library["id"], failed["version"])) == 1
    assert service.query("Widget", library_id=library["id"])["results"] == []
    assert (
        service.query(
            "Widget", library_id=library["id"], version=failed["version"]
        )["results"]
        == []
    )
    assert service.query("Widget")["results"] == []
    with pytest.raises(ValidationError, match="fully published"):
        service.update_library(
            library["id"], {"default_version": failed["version"]}
        )
    statuses = [
        item["status"] for item in service.list_proposals(library["id"])
    ]
    assert statuses.count("published") == 1
    assert statuses.count("pending") >= 1


def test_manual_review_activates_only_after_every_proposal_is_published(
    tmp_path: Path,
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = _service(tmp_path)
    library = service.create_library(
        {"name": "Widgets", "source": str(repository)}
    )
    job = service.create_ingest_job(
        library["id"],
        version="reviewed",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )
    completed = service.run_ingest_job(job["id"])
    proposals = service.list_proposals(library["id"], status="pending")
    assert len(proposals) >= 3

    first = service.publish_proposal(proposals[0]["id"], reindex=False)
    assert first["activation"]["activated"] is False
    current = service.get_library(library["id"])
    assert current["default_version"] is None
    assert current["versions"][0]["status"] == "publishing"
    assert service.query("Widget", library_id=library["id"])["results"] == []
    assert service.query(
        "Widget",
        library_id=library["id"],
        version=completed["version"],
    )["results"] == []

    for proposal in proposals[1:-1]:
        intermediate = service.publish_proposal(
            proposal["id"], reindex=False
        )
        assert intermediate["activation"]["activated"] is False
    final = service.publish_proposal(proposals[-1]["id"], reindex=False)
    assert final["activation"]["activated"] is True
    current = service.get_library(library["id"])
    assert current["default_version"] == completed["version"]
    assert current["versions"][0]["status"] == "published"
    assert service.query("Widget", library_id=library["id"])["results"]


def test_rejected_proposal_blocks_manual_version_activation(
    tmp_path: Path,
) -> None:
    service, library, first = _pending_proposal(tmp_path)
    proposals = service.list_proposals(library["id"], status="pending")
    service.reject_proposal(first["id"], "API is intentionally private")
    for proposal in proposals:
        if proposal["id"] != first["id"]:
            result = service.publish_proposal(proposal["id"], reindex=False)
            assert result["activation"]["activated"] is False

    current = service.get_library(library["id"])
    assert current["default_version"] is None
    assert current["versions"][0]["status"] == "partial"
    assert service.query("Widget", library_id=library["id"])["results"] == []


def test_startup_finishes_activation_after_last_page_commit_crash(
    tmp_path: Path,
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = _service(tmp_path)
    library = service.create_library(
        {"name": "Widgets", "source": str(repository)}
    )
    job = service.create_ingest_job(
        library["id"],
        version="crash-window",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )
    completed = service.run_ingest_job(job["id"])
    proposals = service.list_proposals(library["id"], status="pending")
    for proposal in proposals:
        service._publish_proposal_locked(
            proposal["id"],
            reindex=False,
            activate_version=False,
        )
    before = service.get_library(library["id"])
    assert before["default_version"] is None
    assert before["versions"][0]["status"] == "publishing"
    service.close()

    restarted = _service(tmp_path)
    after = restarted.get_library(library["id"])
    assert after["default_version"] == completed["version"]
    assert after["versions"][0]["status"] == "published"
    assert restarted.query("Widget", library_id=library["id"])["results"]


def test_concurrent_library_creates_get_unique_slugs(tmp_path: Path) -> None:
    repository = create_fixture_repository(tmp_path)
    services = [_service(tmp_path), _service(tmp_path)]
    barrier = threading.Barrier(10)
    results: list[dict] = []
    errors: list[Exception] = []
    guard = threading.Lock()

    def create(index: int) -> None:
        try:
            barrier.wait(5)
            created = services[index % 2].create_library(
                {"name": "Same Name", "source": str(repository)}
            )
            with guard:
                results.append(created)
        except Exception as error:  # noqa: BLE001 - asserted below
            with guard:
                errors.append(error)

    threads = [threading.Thread(target=create, args=(index,)) for index in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert errors == []
    slugs = {str(item["slug"]) for item in results}
    assert len(slugs) == 10
    assert "same-name" in slugs
    assert "same-name-10" in slugs


def test_runtime_recovery_preserves_durable_queued_job(
    tmp_path: Path,
) -> None:
    repository = create_fixture_repository(tmp_path)
    owner = _service(tmp_path)
    library = owner.create_library(
        {"name": "Widgets", "source": str(repository)}
    )
    job = owner.create_ingest_job(
        library["id"],
        version="orphan",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )

    observer = _service(tmp_path)
    assert observer.get_job(job["id"])["status"] == "queued"
    assert observer.recover_orphaned_jobs()["recovered_count"] == 0

    owner.close()
    recovered = observer.recover_orphaned_jobs()
    assert recovered["recovered_jobs"] == []
    assert observer.get_job(job["id"])["status"] == "queued"


def test_ingest_drain_is_atomic_and_resumable(tmp_path: Path) -> None:
    repository = create_fixture_repository(tmp_path)
    service = _service(tmp_path)
    library = service.create_library(
        {"name": "Widgets", "source": str(repository)}
    )

    drained = service.begin_ingest_drain()
    assert drained["draining"] is True
    assert drained["active_count"] == 0
    with pytest.raises(ConflictError, match="drained"):
        service.create_ingest_job(
            library["id"],
            version="blocked",
            ref="HEAD",
            provider="mock",
            auto_publish=False,
        )

    service.resume_ingest()
    queued = service.create_ingest_job(
        library["id"],
        version="allowed",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )
    assert queued["status"] == "queued"


def test_reindex_registers_only_fully_published_versions(
    tmp_path: Path, monkeypatch
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = _service(tmp_path)
    library = service.create_library(
        {"name": "Widgets", "source": str(repository)}
    )
    published_job = service.create_ingest_job(
        library["id"],
        version="stable",
        ref="HEAD",
        provider="mock",
        auto_publish=True,
    )
    published = service.run_ingest_job(published_job["id"])
    assert published["status"] == "completed"
    pending_job = service.create_ingest_job(
        library["id"],
        version="next",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )
    pending = service.run_ingest_job(pending_job["id"])
    assert pending["status"] == "completed"

    registered: list[tuple[Path, str]] = []
    refreshed: list[bool] = []
    models: list[str | None] = []

    def rebuild(
        collections: list[tuple[Path, str]],
        *,
        embed: bool,
        model: str | None = None,
    ) -> tuple[list[dict], dict]:
        registered.extend(collections)
        refreshed.append(embed)
        models.append(model)
        return (
            [
                {"collection": name, "registered": True}
                for _root, name in collections
            ],
            {"updated": True, "embedded": embed},
        )

    monkeypatch.setattr(service.retriever, "rebuild", rebuild)
    result = service.reindex(embed=True)
    assert result["published_versions"] == 1
    assert len(registered) == 1
    assert "stable" in registered[0][0].as_posix()
    assert refreshed == [True]
    assert models == [service.get_settings()["embedding_model"]]
    assert result["embedding_state_managed"] is True
    embedding = service.embedding_status()
    assert embedding["status"] == "ready"
    assert embedding["active_model"] == embedding["desired_model"]
    assert embedding["indexed_revision"] == embedding["corpus_revision"]

    with pytest.raises(ValidationError, match="not fully published"):
        service.reindex(
            library_id=library["id"],
            version=pending["version"],
        )


def test_direct_embedding_reindex_failure_does_not_stick_rebuilding(
    tmp_path: Path, monkeypatch
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = _service(tmp_path)
    library = service.create_library(
        {"name": "Widgets", "source": str(repository)}
    )
    ingest = service.create_ingest_job(
        library["id"],
        version="stable",
        ref="HEAD",
        provider="mock",
        auto_publish=True,
    )
    assert service.run_ingest_job(ingest["id"])["status"] == "completed"

    def fail_rebuild(*_args, **_kwargs):
        raise RuntimeError("fixture QMD failure")

    monkeypatch.setattr(service.retriever, "rebuild", fail_rebuild)

    with pytest.raises(RuntimeError, match="fixture QMD failure"):
        service.reindex(embed=True)

    embedding = service.embedding_status()
    assert embedding["status"] == "failed"
    assert "fixture QMD failure" in embedding["error"]
    assert embedding["hybrid_ready"] is False

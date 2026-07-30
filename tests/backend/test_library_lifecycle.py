from __future__ import annotations

from pathlib import Path

import pytest
from app.config import Settings
from app.retrieval import collection_name
from app.service import AppService, NotFoundError
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


def test_library_resolution_never_uses_arbitrary_path_tail(tmp_path: Path) -> None:
    service = _service(tmp_path)
    library = service.create_library(
        {
            "name": "Widgets",
            "source": "https://github.com/example/widgets.git",
        }
    )
    for identifier in (
        library["id"],
        library["slug"],
        library["context7_id"],
        f"/local/{library['slug']}",
    ):
        assert service.resolve_library(identifier)["id"] == library["id"]

    for invalid in (
        f"/foo/{library['slug']}",
        f"/local/extra/{library['slug']}",
        f"/local/{library['slug']}/",
        f"/{library['slug']}",
        f" {library['slug']} ",
    ):
        with pytest.raises(NotFoundError):
            service.resolve_library(invalid)


def test_purge_removes_all_owned_artifacts_and_reports_qmd_failure(
    tmp_path: Path, monkeypatch
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = _service(tmp_path)
    library = service.create_library(
        {
            "name": "Widgets",
            "source": str(repository),
        }
    )
    queued = service.create_ingest_job(
        library["id"],
        version="main",
        ref="HEAD",
        provider="mock",
        auto_publish=True,
    )
    completed = service.run_ingest_job(queued["id"])
    assert completed["status"] == "completed"
    job_id = queued["id"]
    proposal_root = service.settings.proposals_dir / job_id
    job_control = service.settings.jobs_dir / f"{job_id}.json"
    validation_file = service.settings.jobs_dir / f"{job_id}.validation.json"
    validation_file.write_text("[]\n", encoding="utf-8")
    owned_roots = [
        service.settings.sources_dir / library["slug"],
        service.settings.facts_dir / library["slug"],
        service.settings.wiki_dir / library["slug"],
        proposal_root,
        job_control,
        validation_file,
    ]
    assert all(path.exists() for path in owned_roots)

    expected_collection = collection_name(library["slug"], completed["version"])
    removed_collections: list[str] = []

    def failed_qmd_remove(name: str):
        removed_collections.append(name)
        return {
            "collection": name,
            "removed": False,
            "reason": "qmd-remove-failed",
            "error": "fixture failure",
        }

    monkeypatch.setattr(service.retriever, "remove_collection", failed_qmd_remove)
    result = service.delete_library(library["id"], purge=True)

    assert service.list_libraries() == []
    assert all(not path.exists() for path in owned_roots)
    assert result["purged"] is True
    assert result["secure_erase"] is False
    assert result["failed_paths"] == []
    assert result["collected_before_delete"]["jobs"] == 1
    assert result["collected_before_delete"]["proposals"] >= 1
    assert result["collected_before_delete"]["versions"] == 1
    assert removed_collections == [expected_collection]
    assert result["qmd_collections"] == [
        {
            "collection": expected_collection,
            "removed": False,
            "reason": "qmd-remove-failed",
            "error": "fixture failure",
        }
    ]

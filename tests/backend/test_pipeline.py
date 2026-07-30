from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import app.service as service_module
import pytest
from app.config import Settings
from app.generation import MockGenerator
from app.retrieval import collection_name
from app.service import AppService, ValidationError
from conftest import create_fixture_repository


def settings_for(root: Path) -> Settings:
    data = root / "data"
    return Settings(
        data_dir=data,
        database_path=data / "metadata.sqlite3",
        qmd_enabled=False,
        local_source_roots=(root,),
    )


def test_evidence_to_published_wiki_pipeline(tmp_path: Path) -> None:
    repository = create_fixture_repository(tmp_path)
    service = AppService(settings_for(tmp_path))
    library = service.create_library(
        {
            "name": "Sample Widgets",
            "source": str(repository),
            "description": "Fixture package for pipeline testing",
        }
    )

    queued = service.create_ingest_job(
        library["id"],
        version="1.0.0",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )
    completed = service.run_ingest_job(queued["id"])

    assert completed["status"] == "completed", completed
    assert completed["progress"] == 100
    assert completed["version"].startswith("1.0.0+git.")
    proposals = service.list_proposals(library["id"], status="pending")
    assert len(proposals) >= 3
    assert any(item["kind"] == "api" for item in proposals)

    version = service.get_library(library["id"])["versions"][0]
    snapshot = Path(version["snapshot_path"])
    assert (snapshot / "widgets.py").exists()
    assert not ((snapshot / "widgets.py").stat().st_mode & stat.S_IWUSR)
    facts = json.loads(
        (Path(version["facts_path"]) / "symbols.json").read_text(encoding="utf-8")
    )
    assert any(symbol["name"] == "build_widget" for symbol in facts)

    for proposal in proposals:
        service.publish_proposal(proposal["id"], reindex=False)

    pages = service.list_pages(library["id"], "1.0.0")
    assert len(pages) == len(proposals)
    assert all(page["metadata"]["source_refs"] for page in pages)
    wiki_root = Path(version["wiki_path"])
    assert (wiki_root / "index.md").exists()
    assert (wiki_root / "index.json").exists()
    assert (wiki_root / "log.md").exists()
    assert (wiki_root / "facts" / "overview.json").exists()

    query = service.query(
        "build_widget Widget factory",
        library_id=library["context7_id"],
        version="1.0.0",
    )
    assert query["engine"] == "lexical"
    assert query["results"]
    assert any("widgets" in hit["path"] for hit in query["results"])
    assert query["results"][0]["source_refs"]

    lint = service.lint(library["id"], "1.0.0")
    assert lint["ok"], lint
    graph = service.graph(library["id"], "1.0.0")
    assert any(node["type"] == "page" for node in graph["nodes"])
    assert any(edge["type"] == "cites" for edge in graph["edges"])


def test_reject_and_idempotent_publish(tmp_path: Path) -> None:
    repository = create_fixture_repository(tmp_path)
    service = AppService(settings_for(tmp_path))
    library = service.create_library({"name": "Widgets", "source": str(repository)})
    job = service.create_ingest_job(
        library["id"],
        version="dev",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )
    assert service.run_ingest_job(job["id"])["status"] == "completed"
    proposals = service.list_proposals(library["id"], status="pending")
    rejected = service.reject_proposal(proposals[0]["id"], "Not part of public API")
    assert rejected["status"] == "rejected"

    first = service.publish_proposal(proposals[1]["id"], reindex=False)
    second = service.publish_proposal(proposals[1]["id"], reindex=False)
    assert first["page"]["id"] == second["page"]["id"]
    assert second["idempotent"] is True


def test_retrying_old_published_proposal_cannot_roll_back_default_version(
    tmp_path: Path,
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = AppService(settings_for(tmp_path))
    library = service.create_library({"name": "Widgets", "source": str(repository)})

    first_job = service.create_ingest_job(
        library["id"],
        version="v1",
        ref="HEAD",
        provider="mock",
        auto_publish=True,
    )
    first = service.run_ingest_job(first_job["id"])
    old_proposal = service.list_proposals(
        library["id"], version=first["version"]
    )[0]
    second_job = service.create_ingest_job(
        library["id"],
        version="v2",
        ref="HEAD",
        provider="mock",
        auto_publish=True,
    )
    second = service.run_ingest_job(second_job["id"])
    assert service.get_library(library["id"])["default_version"] == second["version"]

    retried = service.publish_proposal(old_proposal["id"], reindex=False)

    assert retried["idempotent"] is True
    assert retried["activation"]["activated"] is False
    assert retried["activation"]["already_published"] is True
    assert service.get_library(library["id"])["default_version"] == second["version"]


def test_same_version_different_commits_are_isolated(tmp_path: Path) -> None:
    repository = create_fixture_repository(tmp_path)
    service = AppService(settings_for(tmp_path))
    library = service.create_library({"name": "Widgets", "source": str(repository)})

    first_job = service.create_ingest_job(
        library["id"],
        version="main",
        ref="HEAD",
        provider="mock",
        auto_publish=True,
    )
    first = service.run_ingest_job(first_job["id"])
    assert first["status"] == "completed"

    widget_file = repository / "widgets.py"
    widget_file.write_text(
        widget_file.read_text(encoding="utf-8")
        + "\n\ndef widget_version() -> str:\n    return 'v2'\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "widgets.py"], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Add version API"],
        cwd=repository,
        check=True,
        stdout=subprocess.PIPE,
    )

    second_job = service.create_ingest_job(
        library["id"],
        version="main",
        ref="HEAD",
        provider="mock",
        auto_publish=True,
    )
    second = service.run_ingest_job(second_job["id"])
    assert second["status"] == "completed"
    assert first["version"] != second["version"]
    assert collection_name(library["slug"], first["version"]) != collection_name(
        library["slug"], second["version"]
    )

    first_pages = service.list_pages(library["id"], first["version"])
    second_pages = service.list_pages(library["id"], second["version"])
    assert first_pages and second_pages
    first_short_sha = first["version"].rsplit(".", 1)[-1]
    second_short_sha = second["version"].rsplit(".", 1)[-1]
    assert all(page["source_sha"].startswith(first_short_sha) for page in first_pages)
    assert all(page["source_sha"].startswith(second_short_sha) for page in second_pages)
    versions = service.get_library(library["id"])["versions"]
    wiki_paths = {
        item["wiki_path"]
        for item in versions
        if item["version"]
        in {
            first["version"],
            second["version"],
        }
    }
    assert len(wiki_paths) == 2
    # The raw alias intentionally resolves only to the latest materialized SHA.
    assert {
        page["source_sha"] for page in service.list_pages(library["id"], "main")
    } == {second_pages[0]["source_sha"]}


def test_second_ingest_receives_published_wiki_baseline(
    tmp_path: Path, monkeypatch
) -> None:
    repository = create_fixture_repository(tmp_path)
    service = AppService(settings_for(tmp_path))
    library = service.create_library({"name": "Widgets", "source": str(repository)})
    first_job = service.create_ingest_job(
        library["id"],
        version="1.0.0",
        ref="HEAD",
        provider="mock",
        auto_publish=True,
    )
    assert service.run_ingest_job(first_job["id"])["status"] == "completed"

    captured: dict[str, object] = {}

    class RecordingGenerator:
        def generate(self, context):
            captured["existing_wiki"] = context.existing_wiki
            return MockGenerator().generate(context)

    monkeypatch.setattr(
        service_module, "get_generator", lambda _name, _settings: RecordingGenerator()
    )
    second_job = service.create_ingest_job(
        library["id"],
        version="1.1.0",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )
    assert service.run_ingest_job(second_job["id"])["status"] == "completed"
    baseline = captured["existing_wiki"]
    assert isinstance(baseline, list) and baseline
    assert {
        "path",
        "title",
        "kind",
        "summary",
        "markdown",
        "source_refs",
    }.issubset(baseline[0])
    assert any(item["markdown"] for item in baseline)
    assert (
        len(json.dumps(baseline, ensure_ascii=False).encode("utf-8"))
        <= service.settings.max_existing_wiki_bytes
    )


def test_publish_blocks_invalid_schema_and_missing_source_refs(tmp_path: Path) -> None:
    repository = create_fixture_repository(tmp_path)
    service = AppService(settings_for(tmp_path))
    library = service.create_library({"name": "Widgets", "source": str(repository)})
    job = service.create_ingest_job(
        library["id"],
        version="review",
        ref="HEAD",
        provider="mock",
        auto_publish=False,
    )
    assert service.run_ingest_job(job["id"])["status"] == "completed"
    proposals = service.list_proposals(library["id"], status="pending")

    invalid_schema = proposals[0]["metadata"]
    invalid_schema["schema_version"] = 2
    with service.db.transaction() as connection:
        connection.execute(
            "UPDATE proposals SET metadata_json = ? WHERE id = ?",
            (json.dumps(invalid_schema), proposals[0]["id"]),
        )
    with pytest.raises(ValidationError, match="validation"):
        service.publish_proposal(proposals[0]["id"], reindex=False)

    missing_refs = proposals[1]["metadata"]
    missing_refs["source_refs"] = []
    with service.db.transaction() as connection:
        connection.execute(
            "UPDATE proposals SET metadata_json = ? WHERE id = ?",
            (json.dumps(missing_refs), proposals[1]["id"]),
        )
    with pytest.raises(ValidationError, match="validation"):
        service.publish_proposal(proposals[1]["id"], reindex=False)


def test_lint_detects_git_wiki_markdown_drift(tmp_path: Path) -> None:
    repository = create_fixture_repository(tmp_path)
    service = AppService(settings_for(tmp_path))
    library = service.create_library({"name": "Widgets", "source": str(repository)})
    job = service.create_ingest_job(
        library["id"],
        version="drift",
        ref="HEAD",
        provider="mock",
        auto_publish=True,
    )
    completed = service.run_ingest_job(job["id"])
    assert completed["status"] == "completed"
    page = service.list_pages(library["id"], completed["version"])[0]
    version = next(
        item
        for item in service.get_library(library["id"])["versions"]
        if item["version"] == completed["version"]
    )
    markdown_path = Path(version["wiki_path"]) / page["path"]
    markdown_path.write_text("# tampered\n", encoding="utf-8")

    lint = service.lint(library["id"], completed["version"])
    assert lint["ok"] is False
    assert {item["code"] for item in lint["issues"]}.issuperset(
        {"wiki-markdown-drift", "wiki-git-dirty"}
    )

from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from pathlib import Path

import app.retrieval as retrieval_module
from app.config import Settings
from app.locks import LockUnavailable
from app.retrieval import QmdRetriever, collection_name
from app.wiki import WikiStore


def _page() -> dict[str, object]:
    return {
        "id": "page",
        "library_id": "library",
        "version": "1.0+git.abc",
        "path": "api/widgets.md",
        "title": "Widgets",
        "kind": "api",
        "summary": "Widget API",
        "markdown": "# Widgets",
        "source_sha": "abc",
        "metadata": {"source_refs": []},
    }


def test_qmd_without_embeddings_uses_bm25_search(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_bin="/bin/true",
        qmd_enabled=True,
        qmd_hybrid_enabled=False,
    )
    retriever = QmdRetriever(settings)
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], *, timeout: int = 180):
        calls.append(arguments)
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout=json.dumps(
                [{"file": "api/widgets.md", "score": 0.9, "snippet": "Widget"}]
            ),
            stderr="",
        )

    monkeypatch.setattr(retriever, "_run", fake_run)
    engine, hits = retriever.query(
        [_page()], query="Widget", collection="widgets", limit=3
    )
    assert calls[0][0] == "search"
    assert engine == "qmd-bm25"
    assert hits


def test_qmd_with_embeddings_uses_hybrid_query(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_bin="/bin/true",
        qmd_enabled=True,
        qmd_hybrid_enabled=True,
    )
    retriever = QmdRetriever(settings)
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], *, timeout: int = 180):
        calls.append(arguments)
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout=json.dumps([{"file": "api/widgets.md", "score": 0.9}]),
            stderr="",
        )

    monkeypatch.setattr(retriever, "_run", fake_run)
    engine, _hits = retriever.query(
        [_page()], query="Widget", collection="widgets", limit=3
    )
    assert calls[0][0] == "query"
    assert engine == "qmd-hybrid"


def test_qmd_internal_documents_do_not_consume_page_result_budget(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_bin="/bin/true",
        qmd_enabled=True,
        qmd_hybrid_enabled=False,
    )
    retriever = QmdRetriever(settings)
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], *, timeout: int = 180):
        calls.append(arguments)
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout=json.dumps(
                [
                    {"file": "index.md", "score": 1.0},
                    {"file": "log.md", "score": 0.9},
                    {"file": "api/widgets.md", "score": 0.8},
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr(retriever, "_run", fake_run)

    engine, hits = retriever.query(
        [_page()], query="Widget", collection="widgets", limit=1
    )

    assert calls[0][-2:] == ["-n", "20"]
    assert engine == "qmd-bm25"
    assert [hit["path"] for hit in hits] == ["api/widgets.md"]


def test_publish_index_never_builds_embeddings(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_bin="/bin/true",
        qmd_enabled=True,
        qmd_hybrid_enabled=True,
    )
    retriever = QmdRetriever(settings)
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], *, timeout: int = 180):
        calls.append(arguments)
        return subprocess.CompletedProcess(
            arguments,
            1 if arguments[:2] == ["collection", "show"] else 0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(retriever, "_run", fake_run)
    wiki = tmp_path / "wiki"
    wiki.mkdir()

    result = retriever.index(wiki, "fixture")

    assert result["indexed"] is True
    assert ["update"] in calls
    assert not any(arguments and arguments[0] == "embed" for arguments in calls)


def test_lossy_version_slugs_cannot_collide(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_enabled=False,
    )
    wiki = WikiStore(settings, "widgets")
    left = "release/a+git.123456789abc"
    right = "release a+git.123456789abc"
    assert wiki.version_root(left) != wiki.version_root(right)
    assert collection_name("widgets", left) != collection_name("widgets", right)


def test_long_library_slugs_cannot_collide_in_qmd() -> None:
    shared_prefix = "library-" + "x" * 150
    assert collection_name(shared_prefix + "-a", "v1") != collection_name(
        shared_prefix + "-b", "v1"
    )


def test_qmd_collection_removal_failure_is_reported(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_bin="/bin/true",
        qmd_enabled=True,
    )
    retriever = QmdRetriever(settings)

    def timeout(_arguments, *, timeout=180):
        raise subprocess.TimeoutExpired("qmd", timeout)

    monkeypatch.setattr(retriever, "_run", timeout)
    result = retriever.remove_collection("fixture")
    assert result["removed"] is False
    assert result["reason"] == "qmd-remove-failed"


def test_qmd_query_timeout_falls_back_to_lexical(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_bin="/bin/true",
        qmd_enabled=True,
    )
    retriever = QmdRetriever(settings)

    def timeout(_arguments, *, timeout=180):
        raise subprocess.TimeoutExpired("qmd", timeout)

    monkeypatch.setattr(retriever, "_run", timeout)
    engine, hits = retriever.query(
        [_page()], query="Widgets", collection="fixture", limit=3
    )
    assert engine == "lexical"
    assert hits


def test_qmd_index_timeout_is_reported_without_raising(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_bin="/bin/true",
        qmd_enabled=True,
    )
    retriever = QmdRetriever(settings)

    def timeout(_arguments, *, timeout=180):
        raise subprocess.TimeoutExpired("qmd", timeout)

    monkeypatch.setattr(retriever, "_run", timeout)
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    result = retriever.index(wiki, "fixture")
    assert result["indexed"] is False
    assert result["reason"] == "qmd-register-failed"


def test_qmd_registration_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_bin="/bin/true",
        qmd_enabled=True,
    )
    retriever = QmdRetriever(settings)
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], *, timeout: int = 180):
        calls.append(arguments)
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout=str((tmp_path / "wiki").resolve()),
            stderr="",
        )

    monkeypatch.setattr(retriever, "_run", fake_run)
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    result = retriever.register_collection(wiki, "fixture")
    assert result["registered"] is True
    assert result["already_registered"] is True
    assert calls == [["collection", "show", "fixture"]]


def test_qmd_registration_repairs_a_relocated_collection(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_bin="/bin/true",
        qmd_enabled=True,
    )
    retriever = QmdRetriever(settings)
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], *, timeout: int = 180):
        calls.append(arguments)
        stdout = "/old/checkout/wiki" if arguments[-1] == "fixture" else ""
        return subprocess.CompletedProcess(arguments, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(retriever, "_run", fake_run)
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    result = retriever.register_collection(wiki, "fixture")
    assert result["registered"] is True
    assert calls == [
        ["collection", "show", "fixture"],
        ["collection", "remove", "fixture"],
        [
            "collection",
            "add",
            str(wiki),
            "--name",
            "fixture",
            "--mask",
            "**/*.md",
        ],
    ]


def test_qmd_registration_does_not_accept_path_prefix_collision(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_bin="/bin/true",
        qmd_enabled=True,
    )
    retriever = QmdRetriever(settings)
    calls: list[list[str]] = []
    wiki = tmp_path / "wiki"
    wiki.mkdir()

    def fake_run(arguments: list[str], *, timeout: int = 180):
        calls.append(arguments)
        stdout = f"path: {wiki.resolve()}-old\n" if arguments[1] == "show" else ""
        return subprocess.CompletedProcess(arguments, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(retriever, "_run", fake_run)
    result = retriever.register_collection(wiki, "fixture")

    assert result["registered"] is True
    assert [call[:2] for call in calls] == [
        ["collection", "show"],
        ["collection", "remove"],
        ["collection", "add"],
    ]


def test_qmd_refresh_uses_bounded_embedding_batches(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_bin="/bin/true",
        qmd_enabled=True,
    )
    retriever = QmdRetriever(settings)
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], *, timeout: int = 180):
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(retriever, "_run", fake_run)
    result = retriever.refresh(embed=True)
    assert result["updated"] is True
    assert result["embedded"] is True
    assert calls[0] == ["update"]
    assert calls[1] == [
        "embed",
        "-f",
        "--chunk-strategy",
        "auto",
        "--max-docs-per-batch",
        "50",
        "--max-batch-mb",
        "64",
    ]


def test_qmd_embedding_failure_is_not_reported_as_success(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_bin="/bin/true",
        qmd_enabled=True,
    )
    retriever = QmdRetriever(settings)

    def fake_run(arguments: list[str], *, timeout: int = 180):
        return subprocess.CompletedProcess(
            arguments,
            1 if arguments[0] == "embed" else 0,
            stdout="",
            stderr="embedding failed",
        )

    monkeypatch.setattr(retriever, "_run", fake_run)
    result = retriever.refresh(embed=True)
    assert result["updated"] is True
    assert result["embedded"] is False
    assert result["reason"] == "qmd-embed-failed"
    assert result["error"] == "embedding failed"


def test_qmd_rebuild_holds_one_global_writer_lock(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_bin="/bin/true",
        qmd_enabled=True,
    )
    retriever = QmdRetriever(settings)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    events: list[str] = []

    @contextmanager
    def fake_lock(_path, *, blocking, timeout_seconds):
        assert blocking is True
        assert timeout_seconds == 60
        events.append("lock-enter")
        yield
        events.append("lock-exit")

    def register(_root: Path, name: str) -> dict[str, object]:
        events.append(f"register:{name}")
        return {"collection": name, "registered": True}

    def refresh(*, embed: bool) -> dict[str, object]:
        events.append(f"refresh:{embed}")
        return {"updated": True, "embedded": embed}

    monkeypatch.setattr(retrieval_module, "filesystem_lock", fake_lock)
    monkeypatch.setattr(retriever, "_register_collection", register)
    monkeypatch.setattr(retriever, "_refresh", refresh)

    registrations, result = retriever.rebuild(
        [(first, "first"), (second, "second")], embed=True
    )

    assert [item["collection"] for item in registrations] == ["first", "second"]
    assert result["embedded"] is True
    assert events == [
        "lock-enter",
        "register:first",
        "register:second",
        "refresh:True",
        "lock-exit",
    ]


def test_qmd_rebuild_reports_global_writer_contention(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        qmd_bin="/bin/true",
        qmd_enabled=True,
    )
    retriever = QmdRetriever(settings)
    wiki = tmp_path / "wiki"
    wiki.mkdir()

    @contextmanager
    def busy_lock(_path, *, blocking, timeout_seconds):
        assert blocking is True
        assert timeout_seconds == 60
        raise LockUnavailable("fixture busy")
        yield

    monkeypatch.setattr(retrieval_module, "filesystem_lock", busy_lock)

    registrations, result = retriever.rebuild(
        [(wiki, "fixture")], embed=True
    )

    assert registrations == [
        {
            "collection": "fixture",
            "registered": False,
            "reason": "qmd-busy",
        }
    ]
    assert result == {
        "updated": False,
        "embedded": False,
        "reason": "qmd-busy",
    }

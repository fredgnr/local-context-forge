from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from app.desktop_retrieval import (
    MAX_COLLECTIONS,
    DesktopRetrievalError,
    DesktopRetriever,
    read_broker_capability,
)
from app.config import Settings
from app.retrieval import lexical_search
from app.service import AppService
from app.utils import utcnow
from app.wiki import WikiStore


TOKEN = "a" * 43
MODEL = (
    "hf:ggml-org/embeddinggemma-300M-GGUF/"
    "embeddinggemma-300M-Q8_0.gguf"
)
PROFILE = {"kind": "curated", "model": MODEL}


def _stale_embedding() -> dict[str, Any]:
    return {
        "status": "stale",
        "profile": None,
        "revision": None,
        "model_status": "not_requested",
        "error": None,
    }


def _ready_embedding(revision: int) -> dict[str, Any]:
    return {
        "status": "ready",
        "profile": PROFILE,
        "revision": revision,
        "model_status": "ready",
        "error": None,
    }


def _page(path: str = "api/widgets.md") -> dict[str, Any]:
    return {
        "id": "page",
        "library_id": "library",
        "version": "1.0+git.abc",
        "path": path,
        "title": "Widgets",
        "kind": "api",
        "summary": "Widget API",
        "markdown": "# Widgets\n\nBuild a widget.",
        "source_sha": "abc",
        "metadata": {"source_refs": []},
    }


class StubClient:
    def __init__(
        self,
        responses: list[dict[str, Any] | DesktopRetrievalError] | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.calls: list[tuple[str, dict[str, Any], float | None]] = []

    def request(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append((endpoint, payload, timeout_seconds))
        response = self.responses.pop(0)
        if isinstance(response, DesktopRetrievalError):
            raise response
        return response


def _wiki(tmp_path: Path) -> tuple[Path, Path]:
    wiki = tmp_path / "wiki"
    version = wiki / "widgets" / "versions" / "v1"
    version.mkdir(parents=True)
    return wiki, version


def test_broker_capability_fd_is_read_once_then_closed() -> None:
    read_fd, write_fd = os.pipe()
    os.write(write_fd, TOKEN.encode("ascii") + b"\n")
    os.close(write_fd)

    assert read_broker_capability(read_fd) == TOKEN
    with pytest.raises(OSError):
        os.fstat(read_fd)


def test_reconcile_sends_relative_wiki_roots_and_exact_revision(
    tmp_path: Path,
) -> None:
    wiki, version = _wiki(tmp_path)
    client = StubClient(
        [
            {
                "indexed": True,
                "revision": 7,
                "collections": 1,
                "update": {
                    "indexed": 2,
                    "updated": 0,
                    "unchanged": 0,
                    "removed": 0,
                },
                "embedding": _stale_embedding(),
            }
        ]
    )
    retriever = DesktopRetriever(client, wiki)  # type: ignore[arg-type]

    result = retriever.reconcile(
        [(version, "lcf-widgets-v1-0123456789ab")],
        revision=7,
    )

    assert result["indexed"] is True
    assert client.calls == [
        (
            "/reconcile",
            {
                "revision": 7,
                "collections": [
                    {
                        "name": "lcf-widgets-v1-0123456789ab",
                        "wiki_root": "widgets/versions/v1",
                    }
                ],
                "embedding": {"mode": "lexical", "profile": None},
            },
            120,
        )
    ]


def test_too_many_collections_is_explicit_and_never_partially_sent(
    tmp_path: Path,
) -> None:
    wiki, version = _wiki(tmp_path)
    client = StubClient()
    retriever = DesktopRetriever(client, wiki)  # type: ignore[arg-type]
    collections = [
        (version, f"collection-{index}")
        for index in range(MAX_COLLECTIONS + 1)
    ]

    result = retriever.reconcile(collections, revision=1)

    assert result == {
        "indexed": False,
        "reason": "too_many_collections",
        "revision": 1,
        "collections": MAX_COLLECTIONS + 1,
    }
    assert client.calls == []


def test_reconcile_rejects_symlinked_wiki_component_without_broker_call(
    tmp_path: Path,
) -> None:
    wiki, version = _wiki(tmp_path)
    linked = wiki / "linked"
    linked.symlink_to(version.parent.parent, target_is_directory=True)
    client = StubClient()
    retriever = DesktopRetriever(client, wiki)  # type: ignore[arg-type]

    result = retriever.reconcile(
        [(linked / "versions" / "v1", "collection")],
        revision=1,
    )

    assert result["indexed"] is False
    assert result["reason"] == "invalid_request"
    assert client.calls == []


@pytest.mark.parametrize(
    "response",
    [
        DesktopRetrievalError("stale_index"),
        DesktopRetrievalError("transport"),
        {"revision": 6, "mode": "lexical", "results": []},
        {
            "revision": 7,
            "mode": "lexical",
            "results": [
                {
                    "path": "../escape.md",
                    "score": 1.0,
                    "title": "escape",
                }
            ],
        },
    ],
)
def test_stale_transport_revision_and_invalid_response_fall_back_lexically(
    tmp_path: Path,
    response: dict[str, Any] | DesktopRetrievalError,
) -> None:
    wiki, _version = _wiki(tmp_path)
    client = StubClient([response])
    retriever = DesktopRetriever(client, wiki)  # type: ignore[arg-type]
    pages = [_page()]

    engine, hits = retriever.query(
        pages,
        query="Widgets",
        collection="lcf-widgets-v1-0123456789ab",
        limit=3,
        revision=7,
    )

    assert engine == "lexical"
    assert hits == lexical_search(pages, "Widgets", 3)


def test_valid_revision_safe_search_returns_qmd_bm25_results(
    tmp_path: Path,
) -> None:
    wiki, _version = _wiki(tmp_path)
    client = StubClient(
        [
            {
                "revision": 7,
                "mode": "lexical",
                "results": [
                    {
                        "path": "api/widgets.md",
                        "score": 3.25,
                        "title": "Widgets",
                    }
                ],
            }
        ]
    )
    retriever = DesktopRetriever(client, wiki)  # type: ignore[arg-type]

    engine, hits = retriever.query(
        [_page()],
        query="Widgets",
        collection="lcf-widgets-v1-0123456789ab",
        limit=3,
        revision=7,
    )

    assert engine == "qmd-bm25"
    assert [hit["path"] for hit in hits] == ["api/widgets.md"]
    assert hits[0]["score"] == 3.25
    assert client.calls[0][1]["limit"] == 20


def test_valid_empty_qmd_result_does_not_masquerade_as_fallback(
    tmp_path: Path,
) -> None:
    wiki, _version = _wiki(tmp_path)
    retriever = DesktopRetriever(  # type: ignore[arg-type]
        StubClient([{"revision": 2, "mode": "lexical", "results": []}]),
        wiki,
    )

    assert retriever.query(
        [_page()],
        query="missing",
        collection="collection",
        limit=3,
        revision=2,
    ) == ("qmd-bm25", [])


def test_rebuild_sends_validated_profile_and_requires_ready_embedding(
    tmp_path: Path,
) -> None:
    wiki, version = _wiki(tmp_path)
    client = StubClient(
        [
            {
                "indexed": True,
                "revision": 14,
                "collections": 1,
                "update": {
                    "indexed": 1,
                    "updated": 0,
                    "unchanged": 0,
                    "removed": 0,
                },
                "embedding": _ready_embedding(14),
            }
        ]
    )
    retriever = DesktopRetriever(client, wiki)  # type: ignore[arg-type]

    registrations, refresh = retriever.rebuild(
        [(version, "collection")],
        embed=True,
        model=MODEL,
        revision=14,
    )

    assert registrations == [
        {"collection": "collection", "registered": True, "reason": None}
    ]
    assert refresh["embedded"] is True
    assert refresh["model_status"] == "ready"
    assert client.calls == [
        (
            "/reconcile",
            {
                "revision": 14,
                "collections": [
                    {
                        "name": "collection",
                        "wiki_root": "widgets/versions/v1",
                    }
                ],
                "embedding": {"mode": "rebuild", "profile": PROFILE},
            },
            35 * 60,
        )
    ]


def test_model_download_failure_is_sanitized_and_keeps_lexical_index(
    tmp_path: Path,
) -> None:
    wiki, version = _wiki(tmp_path)
    client = StubClient(
        [
            {
                "indexed": True,
                "revision": 15,
                "collections": 1,
                "update": {
                    "indexed": 1,
                    "updated": 0,
                    "unchanged": 0,
                    "removed": 0,
                },
                "embedding": {
                    "status": "failed",
                    "profile": PROFILE,
                    "revision": None,
                    "model_status": "unavailable",
                    "error": "model_unavailable",
                },
            }
        ]
    )
    retriever = DesktopRetriever(client, wiki)  # type: ignore[arg-type]

    registrations, refresh = retriever.rebuild(
        [(version, "collection")],
        embed=True,
        model=MODEL,
        revision=15,
    )

    assert registrations[0]["registered"] is True
    assert refresh == {
        "updated": True,
        "embedded": False,
        "reason": "model_unavailable",
        "model_status": "unavailable",
        "revision": 15,
        "indexed": True,
    }
    assert "/" not in str(refresh["reason"])


def test_embedding_ready_query_uses_hybrid_profile_and_mode(
    tmp_path: Path,
) -> None:
    wiki, _version = _wiki(tmp_path)
    client = StubClient(
        [
            {
                "revision": 16,
                "mode": "hybrid",
                "results": [
                    {
                        "path": "api/widgets.md",
                        "score": 0.95,
                        "title": "Widgets",
                    }
                ],
            }
        ]
    )
    retriever = DesktopRetriever(client, wiki)  # type: ignore[arg-type]

    engine, hits = retriever.query(
        [_page()],
        query="semantic widgets",
        collection="collection",
        limit=3,
        model=MODEL,
        hybrid=True,
        revision=16,
    )

    assert engine == "qmd-hybrid"
    assert [hit["path"] for hit in hits] == ["api/widgets.md"]
    assert client.calls[0] == (
        "/search",
        {
            "revision": 16,
            "collection": "collection",
            "query": "semantic widgets",
            "limit": 20,
            "mode": "hybrid",
            "profile": PROFILE,
        },
        600,
    )


def test_unsafe_hybrid_model_falls_back_without_broker_call(
    tmp_path: Path,
) -> None:
    wiki, _version = _wiki(tmp_path)
    client = StubClient()
    retriever = DesktopRetriever(client, wiki)  # type: ignore[arg-type]

    engine, _hits = retriever.query(
        [_page()],
        query="Widgets",
        collection="collection",
        limit=3,
        model="https://example.invalid/model.gguf",
        hybrid=True,
        revision=16,
    )

    assert engine == "lexical"
    assert client.calls == []


class RecordingDesktopRetriever:
    desktop_broker = True
    available = True

    def __init__(self) -> None:
        self.reconciliations: list[tuple[list[tuple[Path, str]], int]] = []
        self.rebuilds: list[
            tuple[list[tuple[Path, str]], bool, str | None, int | None]
        ] = []
        self.queries: list[dict[str, Any]] = []
        self.on_rebuild: Any | None = None

    def reconcile(
        self,
        collections: list[tuple[Path, str]],
        *,
        revision: int,
    ) -> dict[str, Any]:
        self.reconciliations.append((collections, revision))
        return {
            "indexed": True,
            "revision": revision,
            "collections": len(collections),
        }

    def rebuild(
        self,
        collections: list[tuple[Path, str]],
        *,
        embed: bool,
        model: str | None = None,
        revision: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self.rebuilds.append((collections, embed, model, revision))
        if self.on_rebuild:
            self.on_rebuild()
        return (
            [
                {"collection": name, "registered": True, "reason": None}
                for _root, name in collections
            ],
            {
                "updated": True,
                "embedded": embed,
                "reason": None,
                "revision": revision,
            },
        )

    def query(
        self,
        pages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> tuple[str, list[dict[str, Any]]]:
        self.queries.append(kwargs)
        return (
            "qmd-hybrid" if kwargs.get("hybrid") else "qmd-bm25",
            [
                {
                    **pages[0],
                    "score": 0.9,
                    "snippet": "semantic result",
                }
            ]
            if pages
            else [],
        )


def _insert_published_version(
    service: AppService,
    settings: Settings,
    *,
    slug: str = "alpha",
    corpus_revision: int = 11,
) -> tuple[str, Path]:
    now = utcnow()
    library_id = f"library-{slug}"
    wiki_root = WikiStore(settings, slug).version_root("v1")
    wiki_root.mkdir(parents=True)
    with service.db.transaction() as connection:
        connection.execute(
            """
            INSERT INTO libraries (
                id, name, slug, context7_id, source, description,
                default_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, '', 'v1', ?, ?)
            """,
            (
                library_id,
                slug.title(),
                slug,
                f"/local/{slug}",
                f"https://example.com/{slug}.git",
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO versions (
                id, library_id, version, source_sha, snapshot_path,
                facts_path, wiki_path, status, created_at, published_at
            ) VALUES (?, ?, 'v1', 'sha', ?, ?, ?, 'published', ?, ?)
            """,
            (
                f"version-{slug}",
                library_id,
                str(settings.sources_dir / slug),
                str(settings.facts_dir / slug),
                str(wiki_root),
                now,
                now,
            ),
        )
        connection.execute(
            "UPDATE embedding_state SET corpus_revision = ? WHERE id = 1",
            (corpus_revision,),
        )
    return library_id, wiki_root


def test_service_reconcile_always_submits_the_complete_published_corpus(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "metadata.sqlite3",
        qmd_enabled=False,
    )
    retriever = RecordingDesktopRetriever()
    service = AppService(settings, retriever=retriever)
    now = utcnow()
    try:
        with service.db.transaction() as connection:
            for index, slug in enumerate(("alpha", "beta"), start=1):
                library_id = f"library-{index}"
                connection.execute(
                    """
                    INSERT INTO libraries (
                        id, name, slug, context7_id, source, description,
                        default_version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, '', 'v1', ?, ?)
                    """,
                    (
                        library_id,
                        slug.title(),
                        slug,
                        f"/local/{slug}",
                        f"https://example.com/{slug}.git",
                        now,
                        now,
                    ),
                )
                wiki_root = WikiStore(settings, slug).version_root("v1")
                wiki_root.mkdir(parents=True)
                connection.execute(
                    """
                    INSERT INTO versions (
                        id, library_id, version, source_sha, snapshot_path,
                        facts_path, wiki_path, status, created_at, published_at
                    ) VALUES (?, ?, 'v1', ?, ?, ?, ?, 'published', ?, ?)
                    """,
                    (
                        f"version-{index}",
                        library_id,
                        f"sha-{index}",
                        str(settings.sources_dir / slug),
                        str(settings.facts_dir / slug),
                        str(wiki_root),
                        now,
                        now,
                    ),
                )
            connection.execute(
                "UPDATE embedding_state SET corpus_revision = 11 WHERE id = 1"
            )

        result = service.reconcile_desktop_retrieval()

        assert result["indexed"] is True
        assert len(retriever.reconciliations) == 1
        collections, revision = retriever.reconciliations[0]
        assert revision == 11
        assert [root.parts[-3:-1] for root, _name in collections] == [
            ("alpha", "versions"),
            ("beta", "versions"),
        ]
        assert all(root.name.startswith("v1--") for root, _name in collections)
        assert len({name for _root, name in collections}) == 2
    finally:
        service.close()


def test_service_desktop_reindex_forwards_embed_model_and_corpus_revision(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "metadata.sqlite3",
        qmd_enabled=False,
    )
    retriever = RecordingDesktopRetriever()
    service = AppService(settings, retriever=retriever)
    try:
        _insert_published_version(service, settings, corpus_revision=17)

        result = service.reindex(embed=True, model=MODEL)

        assert result["refresh"]["embedded"] is True
        assert len(retriever.rebuilds) == 1
        collections, embed, model, revision = retriever.rebuilds[0]
        assert len(collections) == 1
        assert embed is True
        assert model == MODEL
        assert revision == 17
    finally:
        service.close()


def test_service_desktop_query_uses_active_profile_only_when_hybrid_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "metadata.sqlite3",
        qmd_enabled=False,
        qmd_hybrid_enabled=True,
    )
    retriever = RecordingDesktopRetriever()
    service = AppService(settings, retriever=retriever)
    page = {
        **_page(),
        "version_id": "version-alpha",
        "version": "v1",
    }
    monkeypatch.setattr(
        service,
        "resolve_library",
        lambda _library_id: {
            "id": "library",
            "slug": "alpha",
            "default_version": "v1",
        },
    )
    monkeypatch.setattr(service, "list_pages", lambda *_args: [page])
    original_fetchone = service.db.fetchone

    def fetchone(sql: str, parameters: tuple[object, ...] = ()):
        if "SELECT status FROM versions" in sql:
            return {"status": "published"}
        return original_fetchone(sql, parameters)

    monkeypatch.setattr(service.db, "fetchone", fetchone)
    monkeypatch.setattr(
        service,
        "embedding_status",
        lambda: {
            "status": "ready",
            "desired_model": MODEL,
            "active_model": MODEL,
            "corpus_revision": 19,
            "indexed_revision": 19,
            "hybrid_ready": True,
        },
    )
    try:
        result = service.query("semantic widgets", library_id="library")

        assert result["engine"] == "qmd-hybrid"
        assert len(retriever.queries) == 1
        call = retriever.queries[0]
        assert call["query"] == "semantic widgets"
        assert call["collection"].startswith("lcf-alpha-v1-")
        assert call["limit"] == 8
        assert call["model"] == MODEL
        assert call["hybrid"] is True
        assert call["revision"] == 19
    finally:
        service.close()


def test_cancelled_desktop_rebuild_never_activates_worker_result(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "metadata.sqlite3",
        qmd_enabled=False,
        qmd_hybrid_enabled=True,
    )
    retriever = RecordingDesktopRetriever()
    service = AppService(settings, retriever=retriever)
    try:
        _insert_published_version(service, settings, corpus_revision=21)
        job = service.create_rebuild_job(
            model=MODEL,
            scope_library_id=None,
        )
        retriever.on_rebuild = lambda: service.cancel_job(str(job["id"]))

        cancelled = service.run_rebuild_job(str(job["id"]))
        embedding = service.embedding_status()

        assert cancelled["status"] == "cancelled"
        assert embedding["status"] == "stale"
        assert embedding["hybrid_ready"] is False
        assert embedding["indexed_revision"] != 21
    finally:
        service.close()


def test_model_switch_during_desktop_rebuild_fails_activation_cas(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "metadata.sqlite3",
        qmd_enabled=False,
        qmd_hybrid_enabled=True,
    )
    retriever = RecordingDesktopRetriever()
    service = AppService(settings, retriever=retriever, desktop_mode=True)
    replacement = (
        "hf:Qwen/Qwen3-Embedding-0.6B-GGUF/"
        "Qwen3-Embedding-0.6B-Q8_0.gguf"
    )
    try:
        _insert_published_version(service, settings, corpus_revision=23)
        job = service.create_rebuild_job(
            model=MODEL,
            scope_library_id=None,
        )

        def switch_model() -> None:
            current = service.get_settings()
            service.patch_settings(
                {
                    "expected_revision": current["revision"],
                    "embedding_model": replacement,
                }
            )

        retriever.on_rebuild = switch_model
        failed = service.run_rebuild_job(str(job["id"]))
        embedding = service.embedding_status()

        assert failed["status"] == "failed"
        assert failed["error"] == "embedding_activation_stale"
        assert embedding["desired_model"] == replacement
        assert embedding["status"] == "stale"
        assert embedding["hybrid_ready"] is False
    finally:
        service.close()


def test_model_switch_before_desktop_rebuild_claim_skips_retriever(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "metadata.sqlite3",
        qmd_enabled=False,
        qmd_hybrid_enabled=True,
    )
    retriever = RecordingDesktopRetriever()
    service = AppService(settings, retriever=retriever, desktop_mode=True)
    replacement = (
        "hf:Qwen/Qwen3-Embedding-0.6B-GGUF/"
        "Qwen3-Embedding-0.6B-Q8_0.gguf"
    )
    try:
        _insert_published_version(service, settings, corpus_revision=29)
        job = service.create_rebuild_job(
            model=MODEL,
            scope_library_id=None,
        )
        original_fetchone = service.db.fetchone
        switched = False

        def fetchone(
            sql: str,
            parameters: tuple[object, ...] = (),
        ) -> Any:
            nonlocal switched
            row = original_fetchone(sql, parameters)
            if (
                not switched
                and "SELECT corpus_revision FROM embedding_state" in sql
            ):
                switched = True
                current = service.get_settings()
                service.patch_settings(
                    {
                        "expected_revision": current["revision"],
                        "embedding_model": replacement,
                    }
                )
            return row

        monkeypatch.setattr(service.db, "fetchone", fetchone)

        failed = service.run_rebuild_job(str(job["id"]))
        embedding = service.embedding_status()

        assert switched is True
        assert retriever.rebuilds == []
        assert failed["status"] == "failed"
        assert failed["error"] == "embedding_claim_stale"
        assert embedding["desired_model"] == replacement
        assert embedding["status"] == "stale"
        assert embedding["hybrid_ready"] is False
    finally:
        service.close()

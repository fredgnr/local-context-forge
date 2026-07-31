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
        {"revision": 6, "results": []},
        {
            "revision": 7,
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
        StubClient([{"revision": 2, "results": []}]),
        wiki,
    )

    assert retriever.query(
        [_page()],
        query="missing",
        collection="collection",
        limit=3,
        revision=2,
    ) == ("qmd-bm25", [])


class RecordingDesktopRetriever:
    desktop_broker = True
    available = True

    def __init__(self) -> None:
        self.reconciliations: list[tuple[list[tuple[Path, str]], int]] = []

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

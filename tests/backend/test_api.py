from __future__ import annotations

import time
from pathlib import Path

from app.config import Settings
from app.main import create_app
from app.wiki import WikiStore
from conftest import create_fixture_repository
from fastapi.testclient import TestClient


def _wait_for_job(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in {"queued", "running", "cancelling"}:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job did not finish: {job_id}")


def test_api_happy_path(tmp_path: Path) -> None:
    repository = create_fixture_repository(tmp_path)
    data = tmp_path / "api-data"
    app = create_app(
        Settings(
            data_dir=data,
            database_path=data / "metadata.sqlite3",
            qmd_enabled=False,
            local_source_roots=(tmp_path,),
        )
    )
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        created = client.post(
            "/api/libraries",
            json={
                "name": "API Widgets",
                "source": str(repository),
                "description": "Test through HTTP",
            },
        )
        assert created.status_code == 201
        library = created.json()

        response = client.post(
            f"/api/libraries/{library['id']}/ingest",
            json={
                "version": "2.0.0",
                "provider": "mock",
                "auto_publish": True,
            },
        )
        assert response.status_code == 202
        job = _wait_for_job(client, response.json()["id"])
        assert job["status"] == "completed", job

        pages = client.get(
            f"/api/libraries/{library['id']}/pages",
            params={"version": "2.0.0"},
        ).json()
        assert pages
        result = client.post(
            "/api/query",
            json={
                "query": "build_widget",
                "library_id": library["context7_id"],
                "version": "2.0.0",
            },
        )
        assert result.status_code == 200
        assert result.json()["results"]
        lint = client.post(
            f"/api/libraries/{library['id']}/lint",
            params={"version": "2.0.0"},
        )
        assert lint.json()["ok"] is True


def test_api_validation_and_not_found(tmp_path: Path) -> None:
    data = tmp_path / "data"
    app = create_app(
        Settings(
            data_dir=data,
            database_path=data / "metadata.sqlite3",
            qmd_enabled=False,
            local_source_roots=(tmp_path,),
        )
    )
    with TestClient(app) as client:
        assert client.get("/api/libraries/not-here").status_code == 404
        assert client.post("/api/query", json={"query": ""}).status_code == 422
        assert (
            client.post(
                "/api/query", json={"query": "widgets", "library_id": ""}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/query", json={"query": "widgets", "version": "main"}
            ).status_code
            == 422
        )
        assert client.get("/api/jobs", params={"library_id": ""}).status_code == 422
        assert (
            client.get(
                "/api/libraries/not-here/page", params={"path": "../secret"}
            ).status_code
            == 422
        )


def test_api_rejects_unsafe_page_path_and_blank_ingest_inputs(
    tmp_path: Path,
) -> None:
    repository = create_fixture_repository(tmp_path)
    data = tmp_path / "data"
    app = create_app(
        Settings(
            data_dir=data,
            database_path=data / "metadata.sqlite3",
            qmd_enabled=False,
            local_source_roots=(tmp_path,),
        )
    )
    with TestClient(app) as client:
        library = client.post(
            "/api/libraries",
            json={"name": "Widgets", "source": str(repository)},
        ).json()
        assert (
            client.get(
                f"/api/libraries/{library['id']}/page",
                params={"path": "../secret"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/api/libraries/{library['id']}/ingest",
                json={"version": "", "ref": "HEAD", "provider": "mock"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/api/libraries/{library['id']}/ingest",
                json={"version": "main", "ref": " ", "provider": "mock"},
            ).status_code
            == 422
        )


def test_operations_routes_expose_drain_and_active_jobs(tmp_path: Path) -> None:
    repository = create_fixture_repository(tmp_path)
    data = tmp_path / "ops-data"
    app = create_app(
        Settings(
            data_dir=data,
            database_path=data / "metadata.sqlite3",
            qmd_enabled=False,
            local_source_roots=(tmp_path,),
        )
    )
    with TestClient(app) as client:
        library = client.post(
            "/api/libraries",
            json={"name": "Widgets", "source": str(repository)},
        ).json()
        active = client.get("/api/jobs/active")
        assert active.status_code == 200
        assert active.json() == {
            "active_count": 0,
            "active_jobs": [],
            "queued_count": 0,
        }

        drained = client.post("/api/admin/ingest/drain")
        assert drained.status_code == 200
        assert drained.json()["draining"] is True
        blocked = client.post(
            f"/api/libraries/{library['id']}/ingest",
            json={"version": "blocked", "provider": "mock"},
        )
        assert blocked.status_code == 409

        assert client.post("/api/admin/ingest/resume").status_code == 200


def test_dirty_wiki_publish_returns_409_and_empty_lint_detects_drift(
    tmp_path: Path,
) -> None:
    repository = create_fixture_repository(tmp_path)
    data = tmp_path / "dirty-data"
    app = create_app(
        Settings(
            data_dir=data,
            database_path=data / "metadata.sqlite3",
            qmd_enabled=False,
            local_source_roots=(tmp_path,),
        )
    )
    with TestClient(app) as client:
        library = client.post(
            "/api/libraries",
            json={"name": "Dirty Widgets", "source": str(repository)},
        ).json()
        job = client.post(
            f"/api/libraries/{library['id']}/ingest",
            json={
                "version": "dirty-v1",
                "provider": "mock",
                "auto_publish": False,
            },
        ).json()
        assert _wait_for_job(client, job["id"])["status"] == "completed"
        proposal = client.get(
            f"/api/libraries/{library['id']}/proposals",
            params={"status": "pending"},
        ).json()[0]
        wiki = WikiStore(app.state.service.settings, library["slug"])
        wiki.initialize()
        (wiki.root / "unexpected.txt").write_text("dirty\n", encoding="utf-8")

        response = client.post(f"/api/proposals/{proposal['id']}/publish")
        assert response.status_code == 409
        assert "inconsistent on-disk" in response.json()["detail"]
        assert "unexpected.txt" not in response.json()["detail"]

        lint = client.post(
            f"/api/libraries/{library['id']}/lint",
            params={"version": proposal["version"]},
        ).json()
        assert lint["ok"] is False
        assert {issue["code"] for issue in lint["issues"]} >= {
            "empty-wiki",
            "wiki-git-dirty",
        }

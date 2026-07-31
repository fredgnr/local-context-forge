from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import Database
from app.desktop_provider_api import install_desktop_provider_routes
from app.provider_attempts import ProviderAttemptStore


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


def _application(tmp_path: Path) -> tuple[FastAPI, ProviderAttemptStore]:
    database = Database(tmp_path / "metadata.sqlite3")
    _seed(database)
    store = ProviderAttemptStore(
        database,
        now=lambda: "2026-07-31T12:00:00+00:00",
        identifiers=iter(
            [f"{number:032x}" for number in range(1, 20)]
        ).__next__,
    )
    attempt_directory = tmp_path / "provider-attempts" / ("c" * 32)
    attempt_directory.mkdir(parents=True, mode=0o700)
    attempt_directory.chmod(0o700)
    inputs = {
        "request.json": b'{"schema_version":1}',
        "evidence.json": b'{"files":[]}',
        "schema.json": b'{"type":"object"}',
        "prompt.txt": b"produce a wiki",
    }
    for name, body in inputs.items():
        target = attempt_directory / name
        target.write_bytes(body)
        target.chmod(0o600)
    request_digest = hashlib.sha256(inputs["request.json"]).hexdigest()
    store.create(
        job_id="c" * 32,
        version_id="b" * 32,
        corpus_revision=1,
        policy="codex_only",
        candidates=["codex_cli"],
        cursor_consent_version=None,
        cursor_consent_granted_at=None,
        input_sha256=request_digest,
        evidence_path=f"provider-attempts/{'c' * 32}",
    )
    application = FastAPI()
    application.state.service = SimpleNamespace(
        provider_attempts=store,
        settings=SimpleNamespace(data_dir=tmp_path),
    )
    install_desktop_provider_routes(application)
    return application, store


def _identity() -> dict[str, object]:
    return {
        "provider": "codex_cli",
        "canonical_path": "/opt/codex",
        "sha256": "d" * 64,
        "size": 123,
        "mtime_ms": 42.5,
        "device": 1,
        "inode": 2,
        "mode": 0o100755,
        "version": "0.146.0",
    }


def test_desktop_provider_route_replays_the_cas_contract(tmp_path: Path) -> None:
    application, _ = _application(tmp_path)
    client = TestClient(application)
    claim = client.post(
        "/api/desktop/provider-attempts/claim-next",
        json={"lease_seconds": 120},
    )
    assert claim.status_code == 200
    private = claim.json()
    assert private["attempt_directory"].startswith(str(tmp_path))
    assert private["input_sha256"] not in private["request_path"]

    attempt_id = private["attempt_id"]
    claim_id = private["claim_id"]
    selected = client.post(
        f"/api/desktop/provider-attempts/{attempt_id}/select",
        json={
            "claim_id": claim_id,
            "provider": "codex_cli",
            "executable_identity": _identity(),
            "fallback_reason": None,
        },
    )
    assert selected.status_code == 200
    assert selected.json()["status"] == "selected"
    assert "/opt/codex" not in selected.text

    committed = client.post(
        f"/api/desktop/provider-attempts/{attempt_id}/commit",
        json={"claim_id": claim_id},
    )
    assert committed.status_code == 200
    assert committed.json()["executable_sha256"] == "d" * 64
    cancellation = client.post(
        f"/api/desktop/provider-attempts/{attempt_id}/cancellation-state",
        json={"claim_id": claim_id},
    )
    assert cancellation.status_code == 200
    assert cancellation.json() == {
        "attempt_id": attempt_id,
        "cancel_requested": False,
        "status": "executing",
    }
    duplicate = client.post(
        f"/api/desktop/provider-attempts/{attempt_id}/commit",
        json={"claim_id": claim_id},
    )
    assert duplicate.status_code == 409

    result = b'{"pages":[{"path":"overview.md"}]}'
    result_path = Path(private["output_path"])
    result_path.write_bytes(result)
    result_path.chmod(0o600)
    completed = client.post(
        f"/api/desktop/provider-attempts/{attempt_id}/complete",
        json={
            "claim_id": claim_id,
            "status": "succeeded",
            "output_sha256": hashlib.sha256(result).hexdigest(),
            "output_size": len(result),
            "error_code": None,
        },
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "succeeded"
    assert "claim_id" not in completed.text


def test_claim_fails_closed_for_symlinked_evidence(tmp_path: Path) -> None:
    application, _ = _application(tmp_path)
    prompt = tmp_path / "provider-attempts" / ("c" * 32) / "prompt.txt"
    prompt.unlink()
    prompt.symlink_to("/etc/hosts")
    response = TestClient(application).post(
        "/api/desktop/provider-attempts/claim-next",
        json={"lease_seconds": 120},
    )
    assert response.status_code == 422
    assert str(tmp_path) not in response.text


def test_extra_fields_are_rejected(tmp_path: Path) -> None:
    application, _ = _application(tmp_path)
    response = TestClient(application).post(
        "/api/desktop/provider-attempts/claim-next",
        content=json.dumps({"lease_seconds": 120, "command": "evil"}),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.desktop_generation import DesktopProviderGenerator
from app.desktop_session import DesktopSession
from app.factory import create_app
from app.service import AppService, ValidationError


TOKEN = "a" * 43
LAUNCH_ID = "01234567-89ab-4cde-8fab-0123456789ab"


def _settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        data_dir=data_dir,
        database_path=data_dir / "metadata.sqlite3",
        qmd_enabled=False,
        qmd_hybrid_enabled=False,
        ctags_enabled=False,
    )


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {TOKEN}",
        "X-LCF-Protocol-Version": "1.0",
        "X-LCF-Launch-Id": LAUNCH_ID,
        "X-LCF-Request-Id": "12345678-9abc-4def-8abc-123456789abc",
        "X-LCF-Deadline-Ms": str(
            time.time_ns() // 1_000_000 + 30_000
        ),
    }


def test_desktop_settings_require_versioned_cursor_consent(
    tmp_path: Path,
) -> None:
    application = create_app(
        _settings(tmp_path),
        desktop_session=DesktopSession(token=TOKEN, launch_id=LAUNCH_ID),
    )
    with TestClient(application) as client:
        initial = client.get("/api/settings", headers=_headers())
        assert initial.status_code == 200
        assert initial.json()["provider_policy"] == "codex_only"
        assert initial.json()["provider_order"] == ["codex_cli"]
        assert initial.json()["cursor_fallback_consent"] == {
            "subject": "cursor_cli_fallback",
            "version": 1,
            "granted": False,
            "granted_at": None,
        }

        missing_consent = client.patch(
            "/api/settings",
            headers=_headers(),
            json={
                "expected_revision": initial.json()["revision"],
                "provider_policy": "codex_then_cursor",
            },
        )
        assert missing_consent.status_code == 422

        enabled = client.patch(
            "/api/settings",
            headers=_headers(),
            json={
                "expected_revision": initial.json()["revision"],
                "provider_policy": "codex_then_cursor",
                "cursor_fallback_consent": True,
            },
        )
        assert enabled.status_code == 200
        assert enabled.json()["provider_order"] == [
            "codex_cli",
            "cursor_cli",
        ]
        assert enabled.json()["fallback_enabled"] is True
        assert enabled.json()["cursor_fallback_consent"]["granted"] is True
        assert enabled.json()["cursor_fallback_consent"]["granted_at"]

        revoked = client.patch(
            "/api/settings",
            headers=_headers(),
            json={
                "expected_revision": enabled.json()["revision"],
                "cursor_fallback_consent": False,
            },
        )
        assert revoked.status_code == 200
        assert revoked.json()["provider_policy"] == "codex_only"
        assert revoked.json()["provider_order"] == ["codex_cli"]


def test_desktop_rejects_legacy_implicit_fallback_settings(
    tmp_path: Path,
) -> None:
    application = create_app(
        _settings(tmp_path),
        desktop_session=DesktopSession(token=TOKEN, launch_id=LAUNCH_ID),
    )
    with TestClient(application) as client:
        response = client.patch(
            "/api/settings",
            headers=_headers(),
            json={
                "provider_order": ["codex_cli", "cursor_cli"],
                "fallback_enabled": True,
            },
        )
    assert response.status_code == 422
    assert "Unknown runtime setting" in response.text


def test_internal_provider_routes_exist_only_on_desktop(
    tmp_path: Path,
) -> None:
    legacy = create_app(_settings(tmp_path))
    with TestClient(legacy) as client:
        response = client.post(
            "/api/desktop/provider-attempts/claim-next",
            json={"lease_seconds": 120},
        )
    assert response.status_code == 404


def test_queued_authorization_cannot_outlive_cursor_revocation(
    tmp_path: Path,
) -> None:
    service = AppService(_settings(tmp_path), desktop_mode=True)
    try:
        initial = service.get_settings()
        with pytest.raises(ValidationError, match="explicit Cursor"):
            service.patch_settings(
                {
                    "expected_revision": initial["revision"],
                    "provider_policy": "codex_then_cursor",
                }
            )
        enabled = service.patch_settings(
            {
                "expected_revision": initial["revision"],
                "provider_policy": "codex_then_cursor",
                "cursor_fallback_consent": True,
            }
        )
        consent = enabled["cursor_fallback_consent"]
        queued_control = {
            "desktop_provider_policy": "codex_then_cursor",
            "cursor_consent_version": 1,
            "cursor_consent_granted_at": consent["granted_at"],
        }
        authorized = service._desktop_generator(  # noqa: SLF001
            job_id="a" * 32,
            version_id="b" * 32,
            provider="auto",
            control=queued_control,
        )
        assert isinstance(authorized, DesktopProviderGenerator)
        assert authorized.policy == "codex_then_cursor"

        revoked = service.patch_settings(
            {
                "expected_revision": enabled["revision"],
                "cursor_fallback_consent": False,
            }
        )
        assert revoked["provider_policy"] == "codex_only"
        downgraded = service._desktop_generator(  # noqa: SLF001
            job_id="a" * 32,
            version_id="b" * 32,
            provider="auto",
            control=queued_control,
        )
        assert downgraded.policy == "codex_only"
        assert downgraded.cursor_consent_version is None
    finally:
        service.close()


def test_schema_five_revokes_legacy_implicit_desktop_fallback(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    settings.data_dir.mkdir(parents=True)
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            """
            CREATE TABLE runtime_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                revision INTEGER NOT NULL,
                provider_order_json TEXT NOT NULL,
                fallback_enabled INTEGER NOT NULL,
                concurrency INTEGER NOT NULL,
                embedding_model TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO runtime_settings VALUES (
                1, 8, '["codex_cli","cursor_cli"]', 1, 1,
                'embeddinggemma-300m-q8', '2026-07-31T00:00:00+00:00'
            )
            """
        )
        connection.execute("PRAGMA user_version = 4")
    service = AppService(settings, desktop_mode=True)
    try:
        migrated = service.get_settings()
        assert migrated["revision"] == 8
        assert migrated["provider_policy"] == "codex_only"
        assert migrated["provider_order"] == ["codex_cli"]
        assert migrated["fallback_enabled"] is False
        assert migrated["cursor_fallback_consent"]["granted"] is False
    finally:
        service.close()

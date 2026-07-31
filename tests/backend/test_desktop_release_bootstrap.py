from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOLS_ROOT = PROJECT_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import bootstrap_desktop_release_keys as bootstrap  # noqa: E402


def _generated_material() -> tuple[
    dict[str, bytes | str],
    dict[str, bytes | str],
]:
    return (
        {
            "privateKey": b"private-update-key",
            "publicKey": b"public-update-key",
            "publicKeySha256": "a" * 64,
        },
        {
            "bundle": b"certificate-bundle",
            "password": b"certificate-password",
            "certificateSha256": "b" * 64,
        },
    )


def test_credential_bundle_is_one_versioned_exact_generation() -> None:
    update, codesign = _generated_material()
    encoded = bootstrap._credential_bundle("c" * 32, update, codesign)
    payload = json.loads(base64.b64decode(encoded, validate=True))

    assert set(payload) == {
        "schemaVersion",
        "credentialGenerationId",
        "repository",
        "environment",
        "updateMetadata",
        "macosCodeSigning",
    }
    assert payload["schemaVersion"] == 1
    assert payload["credentialGenerationId"] == "c" * 32
    assert payload["repository"] == bootstrap.CANONICAL_REPOSITORY
    assert payload["environment"] == bootstrap.ENVIRONMENT_NAME
    assert set(payload["updateMetadata"]) == {
        "algorithm",
        "privateKeyPemBase64",
        "publicKeySha256",
    }
    assert set(payload["macosCodeSigning"]) == {
        "identity",
        "certificateP12Base64",
        "certificatePasswordBase64",
        "certificateSha256",
    }
    assert (
        base64.b64decode(
            payload["updateMetadata"]["privateKeyPemBase64"],
            validate=True,
        )
        == update["privateKey"]
    )
    assert (
        base64.b64decode(
            payload["macosCodeSigning"]["certificateP12Base64"],
            validate=True,
        )
        == codesign["bundle"]
    )


def test_public_pin_transaction_rolls_back_all_written_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_public = tmp_path / "update-public.pem"
    update_lock = tmp_path / "update-lock.json"
    codesign_lock = tmp_path / "codesign-lock.json"
    old_values = {
        update_public: b"old public\n",
        update_lock: b'{"status":"unprovisioned"}\n',
        codesign_lock: b'{"status":"unprovisioned"}\n',
    }
    for path, value in old_values.items():
        path.write_bytes(value)
    monkeypatch.setattr(bootstrap, "UPDATE_PUBLIC_KEY", update_public)
    monkeypatch.setattr(bootstrap, "UPDATE_LOCK", update_lock)
    monkeypatch.setattr(bootstrap, "CODESIGN_LOCK", codesign_lock)
    monkeypatch.setattr(bootstrap, "REPOSITORY_ROOT", tmp_path)
    real_atomic_write = bootstrap._atomic_write
    failed = False

    def fail_second(path: Path, value: bytes, mode: int) -> None:
        nonlocal failed
        if path == update_lock and not failed:
            failed = True
            raise OSError("synthetic write failure")
        real_atomic_write(path, value, mode)

    monkeypatch.setattr(bootstrap, "_atomic_write", fail_second)
    update, codesign = _generated_material()
    with pytest.raises(
        bootstrap.BootstrapError,
        match="rolled back",
    ):
        bootstrap._commit_public_artifacts(
            "c" * 32,
            update,
            codesign,
        )

    assert {
        path: path.read_bytes() for path in old_values
    } == old_values


def test_upload_uses_one_bundle_then_verifies_before_public_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_directory = tmp_path / "private"
    update_lock = tmp_path / "update-lock.json"
    codesign_lock = tmp_path / "codesign-lock.json"
    update_lock.write_text('{"status":"unprovisioned"}\n', encoding="utf-8")
    codesign_lock.write_text(
        '{"status":"unprovisioned"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(bootstrap, "UPDATE_PUBLIC_KEY", tmp_path / "public.pem")
    monkeypatch.setattr(bootstrap, "UPDATE_LOCK", update_lock)
    monkeypatch.setattr(bootstrap, "CODESIGN_LOCK", codesign_lock)
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: "/usr/bin/tool")
    monkeypatch.setattr(
        bootstrap,
        "_verify_protected_environment",
        lambda _: events.append("environment"),
    )
    update, codesign = _generated_material()
    monkeypatch.setattr(
        bootstrap,
        "_generate_update_key",
        lambda _: update,
    )
    monkeypatch.setattr(
        bootstrap,
        "_generate_codesign_certificate",
        lambda _: codesign,
    )
    events: list[str] = []
    uploaded: list[tuple[str, bytes]] = []

    def set_secret(repository: str, name: str, value: bytes) -> None:
        assert repository == bootstrap.CANONICAL_REPOSITORY
        uploaded.append((name, value))
        events.append("upload")

    monkeypatch.setattr(bootstrap, "_set_environment_secret", set_secret)
    monkeypatch.setattr(
        bootstrap,
        "_verify_environment_secret_exists",
        lambda _repository, _name: events.append("secret-verified"),
    )
    monkeypatch.setattr(
        bootstrap,
        "_commit_public_artifacts",
        lambda _generation, _update, _codesign: events.append("public-commit"),
    )

    assert (
        bootstrap.main(
            [
                "--repo",
                bootstrap.CANONICAL_REPOSITORY,
                "--upload",
                "--private-output-dir",
                str(private_directory),
            ]
        )
        == 0
    )
    assert events == [
        "environment",
        "upload",
        "secret-verified",
        "public-commit",
    ]
    assert [name for name, _ in uploaded] == [
        bootstrap.CREDENTIAL_BUNDLE_SECRET
    ]
    assert not private_directory.exists()


def test_public_commit_failure_preserves_recovery_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_directory = tmp_path / "private"
    update_lock = tmp_path / "update-lock.json"
    codesign_lock = tmp_path / "codesign-lock.json"
    update_lock.write_text('{"status":"unprovisioned"}\n', encoding="utf-8")
    codesign_lock.write_text(
        '{"status":"unprovisioned"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(bootstrap, "UPDATE_PUBLIC_KEY", tmp_path / "public.pem")
    monkeypatch.setattr(bootstrap, "UPDATE_LOCK", update_lock)
    monkeypatch.setattr(bootstrap, "CODESIGN_LOCK", codesign_lock)
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: "/usr/bin/tool")
    monkeypatch.setattr(
        bootstrap,
        "_verify_protected_environment",
        lambda _: None,
    )
    update, codesign = _generated_material()
    monkeypatch.setattr(
        bootstrap,
        "_generate_update_key",
        lambda _: update,
    )
    monkeypatch.setattr(
        bootstrap,
        "_generate_codesign_certificate",
        lambda _: codesign,
    )
    monkeypatch.setattr(
        bootstrap,
        "_set_environment_secret",
        lambda _repository, _name, _value: None,
    )
    monkeypatch.setattr(
        bootstrap,
        "_verify_environment_secret_exists",
        lambda _repository, _name: None,
    )
    monkeypatch.setattr(
        bootstrap,
        "_commit_public_artifacts",
        lambda *_: (_ for _ in ()).throw(
            bootstrap.BootstrapError("synthetic public failure")
        ),
    )

    with pytest.raises(
        bootstrap.BootstrapError,
        match="synthetic public failure",
    ):
        bootstrap.main(
            [
                "--repo",
                bootstrap.CANONICAL_REPOSITORY,
                "--upload",
                "--private-output-dir",
                str(private_directory),
            ]
        )

    assert private_directory.is_dir()
    assert (
        private_directory
        / "desktop-release-credential-bundle.base64"
    ).is_file()
    error = capsys.readouterr().err
    assert "formal release is fail-closed" in error
    assert "private-update-key" not in error
    assert "certificate-password" not in error


def test_environment_allows_single_maintainer_self_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def response(
        _repository: str,
        endpoint: str,
        _label: str,
    ) -> dict[str, Any]:
        if endpoint == f"repos/{bootstrap.CANONICAL_REPOSITORY}":
            return {
                "full_name": bootstrap.CANONICAL_REPOSITORY,
                "private": False,
                "visibility": "public",
                "archived": False,
            }
        if endpoint.endswith(f"/environments/{bootstrap.ENVIRONMENT_NAME}"):
            return {
                "name": bootstrap.ENVIRONMENT_NAME,
                "protection_rules": [
                    {
                        "type": "required_reviewers",
                        "prevent_self_review": False,
                        "reviewers": [{"type": "User", "reviewer": {"id": 1}}],
                    }
                ],
                "deployment_branch_policy": {
                    "protected_branches": False,
                    "custom_branch_policies": True,
                },
            }
        return {
            "branch_policies": [
                {"name": bootstrap.RELEASE_TAG_POLICY, "type": "tag"}
            ]
        }

    monkeypatch.setattr(bootstrap, "_gh_api_json", response)
    bootstrap._verify_protected_environment(
        bootstrap.CANONICAL_REPOSITORY
    )

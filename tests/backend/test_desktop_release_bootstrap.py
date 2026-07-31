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
    assert payload["environment"] == bootstrap.SIGNING_ENVIRONMENT_NAME
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
        "_verify_protected_environments",
        lambda _: events.append("environment"),
    )
    monkeypatch.setattr(
        bootstrap,
        "_verify_repository_has_no_release_secrets",
        lambda _: events.append("repository-secrets"),
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
    uploaded: list[tuple[str, str, bytes]] = []

    def set_secret(
        repository: str,
        environment: str,
        name: str,
        value: bytes,
    ) -> None:
        assert repository == bootstrap.CANONICAL_REPOSITORY
        uploaded.append((environment, name, value))
        events.append("upload")

    monkeypatch.setattr(bootstrap, "_set_environment_secret", set_secret)
    monkeypatch.setattr(
        bootstrap,
        "_verify_environment_secrets",
        lambda _repository, environment, names: events.append(
            f"secrets:{environment}:{','.join(sorted(names))}"
        ),
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
                "--confirm-admin-bypass-disabled",
                "--private-output-dir",
                str(private_directory),
            ]
        )
        == 0
    )
    assert events == [
        "environment",
        "repository-secrets",
        "secrets:macos-release:",
        "upload",
        "secrets:macos-signing:DESKTOP_RELEASE_CREDENTIAL_BUNDLE_BASE64",
        "secrets:macos-release:",
        "public-commit",
    ]
    assert [
        (environment, name)
        for environment, name, _ in uploaded
    ] == [
        (
            bootstrap.SIGNING_ENVIRONMENT_NAME,
            bootstrap.CREDENTIAL_BUNDLE_SECRET,
        )
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
        "_verify_protected_environments",
        lambda _: None,
    )
    monkeypatch.setattr(
        bootstrap,
        "_verify_repository_has_no_release_secrets",
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
        lambda _repository, _environment, _name, _value: None,
    )
    monkeypatch.setattr(
        bootstrap,
        "_verify_environment_secrets",
        lambda _repository, _environment, _names: None,
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
                "--confirm-admin-bypass-disabled",
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


def test_release_platform_requires_two_environments_rulesets_and_immutability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id = 7
    ruleset_ids = {
        bootstrap.MAIN_RULESET_NAME: 100,
        bootstrap.RELEASE_TAG_CREATION_RULESET_NAME: 101,
        bootstrap.RELEASE_TAG_RULESET_NAME: 102,
    }

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
                "owner": {"login": "fredgnr", "id": owner_id},
            }
        if endpoint.endswith("/immutable-releases"):
            return {"enabled": True, "enforced_by_owner": False}
        for environment, policy, policy_type in (
            (
                bootstrap.SIGNING_ENVIRONMENT_NAME,
                bootstrap.RELEASE_TAG_POLICY,
                "tag",
            ),
            (
                bootstrap.PROMOTION_ENVIRONMENT_NAME,
                bootstrap.PROMOTION_BRANCH_POLICY,
                "branch",
            ),
        ):
            if endpoint.endswith(f"/environments/{environment}"):
                return {
                    "name": environment,
                    "protection_rules": [
                        {
                            "type": "required_reviewers",
                            "prevent_self_review": True,
                            "reviewers": [
                                {"type": "User", "reviewer": {"id": 8}}
                            ],
                        }
                    ],
                    "deployment_branch_policy": {
                        "protected_branches": False,
                        "custom_branch_policies": True,
                    },
                }
            if endpoint.endswith(
                f"/environments/{environment}"
                "/deployment-branch-policies?per_page=100"
            ):
                return {
                    "total_count": 1,
                    "branch_policies": [
                        {"name": policy, "type": policy_type}
                    ]
                }
        for name, ruleset_id in ruleset_ids.items():
            if endpoint.endswith(f"/rulesets/{ruleset_id}"):
                if name == bootstrap.MAIN_RULESET_NAME:
                    return {
                        "name": name,
                        "target": "branch",
                        "enforcement": "active",
                        "source_type": "Repository",
                        "source": bootstrap.CANONICAL_REPOSITORY,
                        "bypass_actors": [],
                        "conditions": {
                            "ref_name": {
                                "include": [bootstrap.MAIN_RULESET_PATTERN],
                                "exclude": [],
                            }
                        },
                        "rules": [
                            {"type": "deletion"},
                            {"type": "non_fast_forward"},
                            {
                                "type": "pull_request",
                                "parameters": {
                                    "allowed_merge_methods": ["merge"],
                                    "dismiss_stale_reviews_on_push": True,
                                    "require_code_owner_review": False,
                                    "require_last_push_approval": True,
                                    "required_approving_review_count": 1,
                                    "required_review_thread_resolution": True,
                                },
                            },
                        ],
                    }
                return {
                    "name": name,
                    "target": "tag",
                    "enforcement": "active",
                    "source_type": "Repository",
                    "source": bootstrap.CANONICAL_REPOSITORY,
                    "bypass_actors": (
                        [
                            {
                                "actor_id": owner_id,
                                "actor_type": "User",
                                "bypass_mode": "always",
                            }
                        ]
                        if name
                        == bootstrap.RELEASE_TAG_CREATION_RULESET_NAME
                        else []
                    ),
                    "conditions": {
                        "ref_name": {
                            "include": [
                                bootstrap.RELEASE_TAG_RULESET_PATTERN
                            ],
                            "exclude": [],
                        }
                    },
                    "rules": (
                        [{"type": "creation"}]
                        if name
                        == bootstrap.RELEASE_TAG_CREATION_RULESET_NAME
                        else [{"type": "update"}, {"type": "deletion"}]
                    ),
                }
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    monkeypatch.setattr(bootstrap, "_gh_api_json", response)
    monkeypatch.setattr(
        bootstrap,
        "_gh_api_array",
        lambda _repository, _endpoint, _label: [
            {
                "name": name,
                "target": (
                    "branch"
                    if name == bootstrap.MAIN_RULESET_NAME
                    else "tag"
                ),
                "id": ruleset_id,
            }
            for name, ruleset_id in ruleset_ids.items()
        ],
    )
    bootstrap._verify_protected_environments(
        bootstrap.CANONICAL_REPOSITORY
    )


def test_environment_rejects_self_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bootstrap,
        "_gh_api_json",
        lambda _repository, _endpoint, _label: {
            "name": bootstrap.SIGNING_ENVIRONMENT_NAME,
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
        },
    )
    with pytest.raises(
        bootstrap.BootstrapError,
        match="independent reviewers",
    ):
        bootstrap._verify_environment_policy(
            bootstrap.CANONICAL_REPOSITORY,
            environment_name=bootstrap.SIGNING_ENVIRONMENT_NAME,
            deployment_name=bootstrap.RELEASE_TAG_POLICY,
            deployment_type="tag",
        )


def test_main_ruleset_rejects_direct_or_self_reviewed_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ruleset_id = 100
    monkeypatch.setattr(
        bootstrap,
        "_gh_api_array",
        lambda _repository, _endpoint, _label: [
            {
                "name": bootstrap.MAIN_RULESET_NAME,
                "target": "branch",
                "id": ruleset_id,
            }
        ],
    )
    monkeypatch.setattr(
        bootstrap,
        "_gh_api_json",
        lambda _repository, _endpoint, _label: {
            "name": bootstrap.MAIN_RULESET_NAME,
            "target": "branch",
            "enforcement": "active",
            "source_type": "Repository",
            "source": bootstrap.CANONICAL_REPOSITORY,
            "bypass_actors": [],
            "conditions": {
                "ref_name": {
                    "include": [bootstrap.MAIN_RULESET_PATTERN],
                    "exclude": [],
                }
            },
            "rules": [
                {"type": "deletion"},
                {"type": "non_fast_forward"},
                {
                    "type": "pull_request",
                    "parameters": {
                        "allowed_merge_methods": ["merge"],
                        "dismiss_stale_reviews_on_push": True,
                        "require_last_push_approval": False,
                        "required_approving_review_count": 0,
                        "required_review_thread_resolution": True,
                    },
                },
            ],
        },
    )
    with pytest.raises(
        bootstrap.BootstrapError,
        match="independently reviewed pull requests",
    ):
        bootstrap._verify_main_ruleset(
            bootstrap.CANONICAL_REPOSITORY
        )


@pytest.mark.parametrize("reported_type", [None, "tag"])
def test_environment_policy_requires_exact_branch_type(
    monkeypatch: pytest.MonkeyPatch,
    reported_type: str | None,
) -> None:
    def response(
        _repository: str,
        endpoint: str,
        _label: str,
    ) -> dict[str, Any]:
        if endpoint.endswith(
            f"/environments/{bootstrap.PROMOTION_ENVIRONMENT_NAME}"
        ):
            return {
                "name": bootstrap.PROMOTION_ENVIRONMENT_NAME,
                "protection_rules": [
                    {
                        "type": "required_reviewers",
                        "prevent_self_review": True,
                        "reviewers": [{"type": "User", "reviewer": {"id": 8}}],
                    }
                ],
                "deployment_branch_policy": {
                    "protected_branches": False,
                    "custom_branch_policies": True,
                },
            }
        return {
            "total_count": 1,
            "branch_policies": [
                {
                    "name": bootstrap.PROMOTION_BRANCH_POLICY,
                    **(
                        {}
                        if reported_type is None
                        else {"type": reported_type}
                    ),
                }
            ]
        }

    monkeypatch.setattr(bootstrap, "_gh_api_json", response)
    with pytest.raises(
        bootstrap.BootstrapError,
        match="exact branch deployment policy",
    ):
        bootstrap._verify_environment_policy(
            bootstrap.CANONICAL_REPOSITORY,
            environment_name=bootstrap.PROMOTION_ENVIRONMENT_NAME,
            deployment_name=bootstrap.PROMOTION_BRANCH_POLICY,
            deployment_type="branch",
        )


def test_environment_policy_requires_exhaustive_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def response(
        _repository: str,
        endpoint: str,
        _label: str,
    ) -> dict[str, Any]:
        if endpoint.endswith(
            f"/environments/{bootstrap.PROMOTION_ENVIRONMENT_NAME}"
        ):
            return {
                "name": bootstrap.PROMOTION_ENVIRONMENT_NAME,
                "protection_rules": [
                    {
                        "type": "required_reviewers",
                        "prevent_self_review": True,
                        "reviewers": [
                            {"type": "User", "reviewer": {"id": 8}}
                        ],
                    }
                ],
                "deployment_branch_policy": {
                    "protected_branches": False,
                    "custom_branch_policies": True,
                },
            }
        return {
            "total_count": 2,
            "branch_policies": [
                {
                    "name": bootstrap.PROMOTION_BRANCH_POLICY,
                    "type": "branch",
                }
            ],
        }

    monkeypatch.setattr(bootstrap, "_gh_api_json", response)
    with pytest.raises(
        bootstrap.BootstrapError,
        match="exact branch deployment policy",
    ):
        bootstrap._verify_environment_policy(
            bootstrap.CANONICAL_REPOSITORY,
            environment_name=bootstrap.PROMOTION_ENVIRONMENT_NAME,
            deployment_name=bootstrap.PROMOTION_BRANCH_POLICY,
            deployment_type="branch",
        )


def test_environment_secret_verification_requires_exact_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "total_count": 1,
        "secrets": [{"name": bootstrap.CREDENTIAL_BUNDLE_SECRET}],
    }
    monkeypatch.setattr(
        bootstrap,
        "_gh_api_json",
        lambda _repository, _endpoint, _label: expected,
    )
    bootstrap._verify_environment_secrets(
        bootstrap.CANONICAL_REPOSITORY,
        bootstrap.SIGNING_ENVIRONMENT_NAME,
        {bootstrap.CREDENTIAL_BUNDLE_SECRET},
    )
    monkeypatch.setattr(
        bootstrap,
        "_gh_api_json",
        lambda _repository, _endpoint, _label: {
            "total_count": 0,
            "secrets": [],
        },
    )
    bootstrap._verify_environment_secrets(
        bootstrap.CANONICAL_REPOSITORY,
        bootstrap.PROMOTION_ENVIRONMENT_NAME,
        set(),
    )

    for invalid in (
        {
            "total_count": 2,
            "secrets": [
                {"name": bootstrap.CREDENTIAL_BUNDLE_SECRET},
                {"name": "UNREVIEWED_EXTRA_SECRET"},
            ],
        },
        {
            "total_count": 1,
            "secrets": [{"name": "WRONG_SECRET"}],
        },
        {
            "total_count": 2,
            "secrets": [{"name": bootstrap.CREDENTIAL_BUNDLE_SECRET}],
        },
    ):
        monkeypatch.setattr(
            bootstrap,
            "_gh_api_json",
            lambda _repository, _endpoint, _label, value=invalid: value,
        )
        with pytest.raises(
            bootstrap.BootstrapError,
            match="membership differs",
        ):
            bootstrap._verify_environment_secrets(
                bootstrap.CANONICAL_REPOSITORY,
                bootstrap.SIGNING_ENVIRONMENT_NAME,
                {bootstrap.CREDENTIAL_BUNDLE_SECRET},
            )


def test_repository_scope_rejects_release_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bootstrap,
        "_gh_api_json",
        lambda _repository, _endpoint, _label: {
            "total_count": 1,
            "secrets": [{"name": "UNRELATED_INTEGRATION_TOKEN"}],
        },
    )
    bootstrap._verify_repository_has_no_release_secrets(
        bootstrap.CANONICAL_REPOSITORY
    )

    monkeypatch.setattr(
        bootstrap,
        "_gh_api_json",
        lambda _repository, _endpoint, _label: {
            "total_count": 1,
            "secrets": [
                {"name": bootstrap.CREDENTIAL_BUNDLE_SECRET}
            ],
        },
    )
    with pytest.raises(
        bootstrap.BootstrapError,
        match="contain a release credential",
    ):
        bootstrap._verify_repository_has_no_release_secrets(
            bootstrap.CANONICAL_REPOSITORY
        )

    monkeypatch.setattr(
        bootstrap,
        "_gh_api_json",
        lambda _repository, _endpoint, _label: {
            "total_count": 1,
            "secrets": [],
        },
    )
    with pytest.raises(
        bootstrap.BootstrapError,
        match="exhaustively verified",
    ):
        bootstrap._verify_repository_has_no_release_secrets(
            bootstrap.CANONICAL_REPOSITORY
        )

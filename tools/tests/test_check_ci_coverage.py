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
        CHECKER.read(CHECKER.STATUS),
        CHECKER.read(CHECKER.HANDBOOK),
        CHECKER.read(CHECKER.CONTRIBUTING),
    ]


class SourceCoverageContractTests(unittest.TestCase):
    def test_current_contract_is_consistent(self) -> None:
        self.assertEqual(CHECKER.validate_contract(*inputs()), [])

    def test_missing_qmd_make_dependency_fails(self) -> None:
        current = inputs()
        current[1] = str(current[1]).replace(
            "ci-source: ci-python ci-qmd-worker ci-web desktop-ci",
            "ci-source: ci-python ci-web desktop-ci",
            1,
        )
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("Make ci-source dependencies" in error for error in errors))

    def test_lifecycle_enabled_qmd_install_fails(self) -> None:
        current = inputs()
        current[1] = str(current[1]).replace(" ci --ignore-scripts", " ci", 1)
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
        current[2] = str(current[2]).replace("make ci-qmd-worker", "make qmd-status", 1)
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("python job missing 'make ci-qmd-worker'" in error for error in errors))

    def test_summary_needs_drift_fails(self) -> None:
        current = inputs()
        current[2] = str(current[2]).replace(
            "needs: [python, web, desktop, macos-ipc]",
            "needs: [python, web, desktop]",
            1,
        )
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("source-coverage job missing" in error for error in errors))

    def test_default_pr_merge_checkout_fails(self) -> None:
        current = inputs()
        current[2] = str(current[2]).replace(
            f"          ref: {CHECKER.SOURCE_EXPRESSION}\n",
            "",
            1,
        )
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("every checkout must set" in error for error in errors))

    def test_optional_execution_fails(self) -> None:
        current = inputs()
        current[2] = str(current[2]).replace(
            "      - name: Run Python source checks",
            "      - name: Run Python source checks\n        continue-on-error: true",
            1,
        )
        errors = CHECKER.validate_contract(*current)
        self.assertIn("source workflow must not make source execution optional", errors)

    def test_source_network_trap_removal_fails(self) -> None:
        current = inputs()
        current[4] = str(current[4]).replace("LCF_QMD_SOURCE_TEST", "REMOVED_SOURCE_GATE", 1)
        errors = CHECKER.validate_contract(*current)
        self.assertTrue(any("QMD network trap missing" in error for error in errors))

    def test_direct_untrapped_npm_test_fails(self) -> None:
        current = inputs()
        package = copy.deepcopy(current[3])
        package["scripts"]["test"] = "node --test test/*.test.mjs"
        current[3] = package
        errors = CHECKER.validate_contract(*current)
        self.assertIn("QMD npm test must use the fail-closed source runner", errors)

    def test_guide_exclusion_wording_is_machine_required(self) -> None:
        current = inputs()
        current[5] = str(current[5]).replace(CHECKER.GUIDE_STATUS_PHRASE, "guide omitted", 1)
        errors = CHECKER.validate_contract(*current)
        self.assertIn("status missing exact guide-site exclusion phrase", errors)


if __name__ == "__main__":
    unittest.main()

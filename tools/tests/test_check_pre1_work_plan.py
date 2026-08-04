from __future__ import annotations

import json
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "check_pre1_work_plan.py"
SPEC = importlib.util.spec_from_file_location("check_pre1_work_plan", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def documents() -> list[str]:
    return [
        CHECKER.read(CHECKER.PLAN),
        CHECKER.read(CHECKER.TODO),
        CHECKER.read(CHECKER.TRACE),
        CHECKER.read(CHECKER.ITERATION),
        CHECKER.read(CHECKER.LEGACY_MANIFEST),
        CHECKER.read(CHECKER.ADR),
        CHECKER.read(CHECKER.STATUS),
        CHECKER.read(CHECKER.R13),
        CHECKER.read(CHECKER.RELEASE_RUNBOOK),
        json.loads(CHECKER.read(CHECKER.W01_EVIDENCE)),
    ]


class Pre1WorkPlanTests(unittest.TestCase):
    def test_current_pre1_work_plan_is_consistent(self) -> None:
        self.assertEqual(CHECKER.validate_documents(*documents()), [])

    def test_wrong_execution_rank_fails(self) -> None:
        docs = documents()
        docs[0] = docs[0].replace("| 1 | W01 |", "| 2 | W01 |", 1)
        errors = CHECKER.validate_documents(*docs)
        self.assertTrue(any("execution ranks" in error for error in errors))

    def test_cross_document_work_mapping_drift_fails(self) -> None:
        docs = documents()
        docs[2] = docs[2].replace(
            "| TODO-EVAL-CORPUS-001 | W07/P3 |",
            "| TODO-EVAL-CORPUS-001 | W08/P3 |",
            1,
        )
        errors = CHECKER.validate_documents(*docs)
        self.assertTrue(any("TODO-EVAL-CORPUS-001 maps" in error for error in errors))

    def test_work_gate_mapping_drift_fails(self) -> None:
        docs = documents()
        original = "`VAL-MODEL-001`、`VAL-MODEL-EMBED-001`"
        self.assertIn(original, docs[0])
        docs[0] = docs[0].replace(original, "`VAL-MODEL-001`、`VAL-CLI-001`", 1)
        errors = CHECKER.validate_documents(*docs)
        self.assertTrue(any("W05 gates" in error for error in errors))

    def test_task_status_drift_fails(self) -> None:
        docs = documents()
        original = "| TODO-PACKAGED-SMOKE-001 | Priority-0 | W02 | `planned` |"
        self.assertIn(original, docs[1])
        docs[1] = docs[1].replace(
            original,
            "| TODO-PACKAGED-SMOKE-001 | Priority-0 | W02 | `in-progress` |",
            1,
        )
        errors = CHECKER.validate_documents(*docs)
        self.assertTrue(any("TODO-PACKAGED-SMOKE-001 status" in error for error in errors))

    def test_detailed_task_status_drift_fails(self) -> None:
        docs = documents()
        current_status = "done" if docs[9]["status"] == "pass" else "in-progress"
        drifted_status = "planned" if current_status == "done" else "done"
        original = (
            "### TODO-GOV-EVIDENCE-001：统一可复现证据坐标\n\n"
            f"- 状态：`{current_status}`"
        )
        self.assertIn(original, docs[1])
        docs[1] = docs[1].replace(
            original,
            "### TODO-GOV-EVIDENCE-001：统一可复现证据坐标\n\n"
            f"- 状态：`{drifted_status}`",
            1,
        )
        errors = CHECKER.validate_documents(*docs)
        self.assertTrue(any("detail status" in error for error in errors))

    def test_w01_evidence_state_must_match_documents(self) -> None:
        docs = documents()
        changed_status = "not-run" if docs[9]["status"] == "pass" else "pass"
        docs[9]["status"] = changed_status
        docs[9]["gates"] = {
            "VAL-PRE1-SEQUENCE-001": changed_status,
            "VAL-GOV-001": changed_status,
            "VAL-CI-COVERAGE-001": changed_status,
        }
        errors = CHECKER.validate_documents(*docs)
        self.assertTrue(any("status" in error and "expected" in error for error in errors))

    def test_r13_cannot_complete_before_w01_evidence(self) -> None:
        docs = documents()
        current_status = "completed" if docs[9]["status"] == "pass" else "in-progress"
        drifted_status = "in-progress" if current_status == "completed" else "completed"
        docs[7] = docs[7].replace(
            f"- 状态：`{current_status}`",
            f"- 状态：`{drifted_status}`",
            1,
        )
        errors = CHECKER.validate_documents(*docs)
        self.assertIn(f"R13 status must be {current_status}", errors)

    def test_mixed_not_run_and_formal_pass_fails(self) -> None:
        docs = documents()
        original = (
            "| `not-run`；通过前不得 promotion，W13 evidence 不得复用为 Draft gate evidence |"
        )
        self.assertIn(original, docs[2])
        docs[2] = docs[2].replace(
            original,
            "| `not-run` historically；formal `pass` |",
            1,
        )
        errors = CHECKER.validate_documents(*docs)
        self.assertTrue(any("VAL-RELEASE-CONTINUITY-001 status words" in error for error in errors))

    def test_w01_exit_dependency_marker_is_required(self) -> None:
        docs = documents()
        self.assertIn(CHECKER.W01_EXIT_MARKER, docs[0])
        docs[0] = docs[0].replace(CHECKER.W01_EXIT_MARKER, "", 1)
        errors = CHECKER.validate_documents(*docs)
        self.assertIn("work plan must contain the exact W01-to-W02 exit marker once", errors)

    def test_release_continuity_components_are_required(self) -> None:
        docs = documents()
        self.assertIn("tag source/absence 重跑", docs[2])
        docs[2] = docs[2].replace("tag source/absence 重跑", "unspecified future check", 1)
        errors = CHECKER.validate_documents(*docs)
        self.assertIn("release continuity definition missing tag source/absence 重跑", errors)

    def test_iteration_must_enumerate_each_new_stable_id(self) -> None:
        docs = documents()
        self.assertIn("TODO-PACKAGED-SMOKE-001", docs[3])
        docs[3] = docs[3].replace("TODO-PACKAGED-SMOKE-001", "REMOVED-TASK-ID")
        errors = CHECKER.validate_documents(*docs)
        self.assertIn("iteration stable ID missing TODO-PACKAGED-SMOKE-001", errors)

    def test_todo_must_reference_each_new_stable_id(self) -> None:
        docs = documents()
        self.assertIn("REQ-LEGACY-SLICE-001", docs[1])
        docs[1] = docs[1].replace("REQ-LEGACY-SLICE-001", "REMOVED-REQ-ID")
        errors = CHECKER.validate_documents(*docs)
        self.assertIn("TODO stable ID missing REQ-LEGACY-SLICE-001", errors)

    def test_legacy_manifest_cannot_restore_global_replacement_prerequisite(self) -> None:
        docs = documents()
        marker = "W01/W02 退出门禁\n  通过后，按 ADR-0016 的 slice eligibility 独立删除"
        self.assertIn(marker, docs[4])
        docs[4] = docs[4].replace(marker, "完整替代后删除", 1)
        errors = CHECKER.validate_documents(*docs)
        self.assertTrue(
            any("aggregate replacement before every slice" in error for error in errors)
        )

    def test_r13_continuity_status_must_remain_not_run(self) -> None:
        docs = documents()
        original = "| `VAL-RELEASE-CONTINUITY-001` | `not-run` |"
        self.assertIn(original, docs[7])
        docs[7] = docs[7].replace(
            original,
            "| `VAL-RELEASE-CONTINUITY-001` | `pass` |",
            1,
        )
        errors = CHECKER.validate_documents(*docs)
        self.assertTrue(any("R13 missing required release-boundary phrase" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

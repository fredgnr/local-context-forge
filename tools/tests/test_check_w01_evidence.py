from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "check_w01_evidence.py"
SPEC = importlib.util.spec_from_file_location("check_w01_evidence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def pending_record() -> dict[str, object]:
    return json.loads(CHECKER.EVIDENCE.read_text(encoding="utf-8"))


def pass_record() -> dict[str, object]:
    record = pending_record()
    commit = "a" * 40
    record.update(
        {
            "status": "pass",
            "pull_request": 20,
            "gates": {gate: "pass" for gate in CHECKER.GATES},
            "checkpoint": {
                "commit": commit,
                "tree": "b" * 40,
                "clean_checkout": True,
                "base_to_head_diff_check": "pass",
                "manifest_sha256": "c" * 64,
                "runtime_evidence_sha256": "d" * 64,
                "runtime_artifact_name": f"w01-source-coverage-{commit}",
                "environment": {
                    "python_job": "ubuntu-24.04",
                    "web_job": "ubuntu-24.04",
                    "desktop_job": "ubuntu-24.04",
                    "macos_ipc_job": "macos-15 arm64",
                    "tool_versions": {"python": "3.12", "qmd_node": "22.23.2"},
                },
                "actions_run": {
                    "event": "push",
                    "head_sha": commit,
                    "exact_checked_out_sha": commit,
                    "workflow_path": ".github/workflows/desktop-ci.yml",
                    "workflow_sha": commit,
                    "github_context_sha": commit,
                    "source_ref": "refs/heads/agent/w01-governance-source-ci",
                    "run_id": 123,
                    "attempt": 1,
                    "url": "https://github.com/fredgnr/local-context-forge/actions/runs/123",
                    "conclusion": "success",
                    "job_results": {
                        **{job: "success" for job in CHECKER.REQUIRED_JOBS},
                        "source-coverage": "success",
                    },
                },
                "components": {
                    "python": {"result": "pass", "tests": 322, "skipped": 1, "command": "make ci-python"},
                    "host_runner": {"result": "pass", "tests": 8, "skipped": 0, "command": "unittest"},
                    "mcp": {"result": "pass", "checks": 2, "skipped": 0, "command": "compile/import"},
                    "demo_python_sdk": {"result": "pass", "tests": 3, "skipped": 0, "command": "pytest"},
                    "web": {"result": "pass", "tests": 51, "skipped": 0, "command": "make ci-web"},
                    "desktop": {"result": "pass", "tests": 245, "skipped": 7, "command": "make desktop-ci"},
                    "governance": {"result": "pass", "tests": 40, "skipped": 0, "command": "tools tests"},
                    "qmd_worker": {
                        "result": "pass",
                        "tests": 11,
                        "node_version": "22.23.2",
                        "skipped": 1,
                        "command": "make ci-qmd-worker",
                        "network_trap": "active",
                        "model_files_created": 0,
                        "model_cache_paths_created": 0,
                    },
                },
            },
        }
    )
    return record


class W01EvidenceTests(unittest.TestCase):
    def test_pending_record_is_honest(self) -> None:
        self.assertEqual(CHECKER.validate_evidence(pending_record()), [])

    def test_complete_pass_record_is_valid(self) -> None:
        self.assertEqual(CHECKER.validate_evidence(pass_record()), [])

    def test_self_referential_literal_final_head_is_not_the_binding(self) -> None:
        record = pass_record()
        record["final_head_binding"] = {"commit": "c" * 40}
        self.assertIn(
            "W01 final-head binding contract drifted",
            CHECKER.validate_evidence(record),
        )

    def test_actions_head_must_match_checkpoint(self) -> None:
        record = pass_record()
        record["checkpoint"]["actions_run"]["head_sha"] = "c" * 40
        self.assertIn(
            "checkpoint Actions head does not match checkpoint commit",
            CHECKER.validate_evidence(record),
        )

    def test_pull_request_synthetic_sha_is_recorded_but_not_used_as_source(self) -> None:
        record = pass_record()
        synthetic = "e" * 40
        run = record["checkpoint"]["actions_run"]
        run.update(
            {
                "event": "pull_request",
                "source_ref": "refs/pull/20/merge",
                "github_context_sha": synthetic,
                "workflow_sha": synthetic,
            }
        )
        self.assertEqual(CHECKER.validate_evidence(record), [])
        run["exact_checked_out_sha"] = synthetic
        self.assertIn(
            "checkpoint Actions exact checked-out SHA does not match checkpoint commit",
            CHECKER.validate_evidence(record),
        )

    def test_missing_component_counts_fail(self) -> None:
        record = pass_record()
        del record["checkpoint"]["components"]["qmd_worker"]
        self.assertIn(
            "checkpoint component evidence set is incomplete",
            CHECKER.validate_evidence(record),
        )

    def test_unexpected_qmd_skip_fails(self) -> None:
        record = pass_record()
        record["checkpoint"]["components"]["qmd_worker"]["skipped"] = 2
        self.assertIn(
            "checkpoint QMD skipped must be 1",
            CHECKER.validate_evidence(record),
        )

    def test_canonical_main_run_condition_cannot_be_removed(self) -> None:
        record = copy.deepcopy(pass_record())
        record["canonical_activation"].pop()
        self.assertIn(
            "W01 canonical activation conditions drifted",
            CHECKER.validate_evidence(record),
        )


if __name__ == "__main__":
    unittest.main()

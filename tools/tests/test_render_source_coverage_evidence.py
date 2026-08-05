from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "render_source_coverage_evidence.py"
SPEC = importlib.util.spec_from_file_location("render_source_coverage_evidence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
RENDERER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDERER)


def qmd_result() -> dict[str, object]:
    return {
        "schema_version": 2,
        "result": "pass",
        "node_version": "22.23.2",
        "command": (
            "node --import desktop/scripts/qmdNetworkTrap.mjs --test "
            "desktop/workers/qmd/test/*.test.mjs"
        ),
        "allowed_skip_reason": (
            "better-sqlite3 native binding is not built in source checkout"
        ),
        "network_trap": "active",
        "network_policy": "deny-external-allow-af-unix",
        "model_scan": {
            "scope": RENDERER.MODEL_SCAN_SCOPE,
            "repository_worktree_scanned": False,
            "global_tmp_scanned": False,
            "model_files_before": 0,
            "model_files_after": 0,
            "model_files_created": 0,
            "model_file_paths_created": [],
            "model_cache_paths_before": 0,
            "model_cache_paths_after": 0,
            "model_cache_paths_created": 0,
            "model_cache_path_names_created": [],
        },
        "tests": {
            "tests": 11,
            "pass": 10,
            "fail": 0,
            "cancelled": 0,
            "skipped": 1,
            "todo": 0,
        },
        "errors": [],
    }


def fixture() -> tuple[
    dict[str, object], dict[str, object], dict[str, str], str, str
]:
    manifest = json.loads(
        (ROOT / ".github" / "ci" / "source-coverage.json").read_text(
            encoding="utf-8"
        )
    )
    head = "a" * 40
    tree = "d" * 40
    needs = {
        job: {"result": "success", "outputs": {}}
        for job in manifest["aggregate"]["required_jobs"]
    }
    needs["python"]["outputs"].update(
        {
            "python-version": "Python 3.12.13",
            "qmd-node-version": "v22.23.2",
            "npm-version": "10.9.8",
            "uv-version": "uv 0.11.29",
        }
    )
    needs["web"]["outputs"].update(
        {"node-version": "v24.9.0", "npm-version": "11.6.0"}
    )
    needs["desktop"]["outputs"].update(
        {"node-version": "v24.9.0", "npm-version": "11.6.0"}
    )
    needs["macos-ipc"]["outputs"].update(
        {
            "architecture": "arm64",
            "python-version": "Python 3.12.13",
            "uv-version": "uv 0.11.29",
        }
    )
    needs["python"]["outputs"]["qmd-result"] = json.dumps(qmd_result())
    synthetic = "b" * 40
    environment = {
        "LCF_SOURCE_SHA": head,
        "GITHUB_SHA": synthetic,
        "GITHUB_REPOSITORY": "fredgnr/local-context-forge",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REF": "refs/pull/20/merge",
        "GITHUB_HEAD_REF": "agent/w01-governance-source-ci",
        "GITHUB_WORKFLOW": "Desktop source CI",
        "GITHUB_WORKFLOW_REF": (
            "fredgnr/local-context-forge/.github/workflows/desktop-ci.yml@"
            "refs/pull/20/merge"
        ),
        "GITHUB_WORKFLOW_SHA": synthetic,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SERVER_URL": "https://github.com",
        "LCF_MANIFEST_SHA256": "e" * 64,
        "LCF_RECORDED_AT": "2026-08-04T00:00:00+00:00",
    }
    return manifest, needs, environment, head, tree


def render(
    manifest: dict[str, object],
    needs: dict[str, object],
    environment: dict[str, str],
    head: str,
    tree: str,
) -> tuple[dict[str, object], list[str]]:
    return RENDERER.build_report(manifest, needs, environment, head, tree)


def workflow_ref(source_ref: str) -> str:
    return (
        "fredgnr/local-context-forge/.github/workflows/desktop-ci.yml@" + source_ref
    )


class RenderSourceCoverageTests(unittest.TestCase):
    def test_pull_request_is_technical_pass_but_canonical_blocked(self) -> None:
        values = fixture()
        report, errors = render(*values)
        self.assertEqual(errors, [])
        self.assertEqual(report["lifecycle_phase"], "pull-request-candidate")
        self.assertEqual(
            set(report["technical_candidate_gate_results"].values()), {"pass"}
        )
        self.assertIsNone(report["main_source_gate_results"])
        self.assertEqual(report["independent_acceptance"]["status"], "pending")
        self.assertEqual(report["canonical_activation"]["status"], "blocked")
        self.assertEqual(
            report["canonical_activation"]["required_conditions"],
            RENDERER.PR_ACTIVATION_CONDITIONS,
        )
        self.assertNotIn("canonical_gate_results", report)

    def test_branch_push_remains_canonical_blocked(self) -> None:
        manifest, needs, environment, head, tree = fixture()
        environment.update(
            {
                "GITHUB_EVENT_NAME": "push",
                "GITHUB_REF": "refs/heads/agent/w01-governance-source-ci",
                "GITHUB_HEAD_REF": "",
                "GITHUB_SHA": head,
                "GITHUB_WORKFLOW_SHA": head,
                "GITHUB_WORKFLOW_REF": workflow_ref(
                    "refs/heads/agent/w01-governance-source-ci"
                ),
            }
        )
        report, errors = render(manifest, needs, environment, head, tree)
        self.assertEqual(errors, [])
        self.assertEqual(report["lifecycle_phase"], "branch-candidate")
        self.assertEqual(report["canonical_activation"]["status"], "blocked")

    def test_workflow_dispatch_on_main_is_not_a_main_push(self) -> None:
        manifest, needs, environment, head, tree = fixture()
        environment.update(
            {
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_HEAD_REF": "",
                "GITHUB_SHA": head,
                "GITHUB_WORKFLOW_SHA": head,
                "GITHUB_WORKFLOW_REF": workflow_ref("refs/heads/main"),
            }
        )
        report, errors = render(manifest, needs, environment, head, tree)
        self.assertEqual(errors, [])
        self.assertEqual(report["lifecycle_phase"], "branch-candidate")
        self.assertIsNone(report["main_source_gate_results"])

    def test_main_push_records_main_source_but_not_canonical_pass(self) -> None:
        manifest, needs, environment, head, tree = fixture()
        environment.update(
            {
                "GITHUB_EVENT_NAME": "push",
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_HEAD_REF": "",
                "GITHUB_SHA": head,
                "GITHUB_WORKFLOW_SHA": head,
                "GITHUB_WORKFLOW_REF": workflow_ref("refs/heads/main"),
            }
        )
        report, errors = render(manifest, needs, environment, head, tree)
        self.assertEqual(errors, [])
        self.assertEqual(report["lifecycle_phase"], "canonical-main-source")
        self.assertIsNone(report["technical_candidate_gate_results"])
        self.assertEqual(set(report["main_source_gate_results"].values()), {"pass"})
        self.assertEqual(
            report["independent_acceptance"]["status"],
            "not-observable-by-source-workflow",
        )
        self.assertEqual(
            report["canonical_activation"]["status"],
            "requires-external-conditions",
        )

    def test_failed_main_source_is_canonical_blocked(self) -> None:
        manifest, needs, environment, head, tree = fixture()
        environment.update(
            {
                "GITHUB_EVENT_NAME": "push",
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_HEAD_REF": "",
                "GITHUB_SHA": head,
                "GITHUB_WORKFLOW_SHA": head,
                "GITHUB_WORKFLOW_REF": workflow_ref("refs/heads/main"),
            }
        )
        needs["web"]["result"] = "failure"
        report, errors = render(manifest, needs, environment, head, tree)
        self.assertNotEqual(errors, [])
        self.assertEqual(report["result"], "fail")
        self.assertEqual(report["canonical_activation"]["status"], "blocked")
        self.assertEqual(
            report["canonical_activation"]["required_conditions"],
            RENDERER.FAILED_MAIN_ACTIVATION_CONDITIONS,
        )

    def test_unknown_event_fails_closed(self) -> None:
        manifest, needs, environment, head, tree = fixture()
        environment["GITHUB_EVENT_NAME"] = "schedule"
        report, errors = render(manifest, needs, environment, head, tree)
        self.assertTrue(any("unsupported workflow event" in error for error in errors))
        self.assertEqual(report["result"], "fail")

    def test_tag_push_fails_closed(self) -> None:
        manifest, needs, environment, head, tree = fixture()
        environment.update(
            {
                "GITHUB_EVENT_NAME": "push",
                "GITHUB_REF": "refs/tags/v1",
                "GITHUB_SHA": head,
                "GITHUB_WORKFLOW_SHA": head,
            }
        )
        report, errors = render(manifest, needs, environment, head, tree)
        self.assertTrue(any("must identify a branch" in error for error in errors))
        self.assertEqual(report["result"], "fail")

    def test_pull_request_ref_must_be_numbered(self) -> None:
        manifest, needs, environment, head, tree = fixture()
        environment["GITHUB_REF"] = "refs/pull/not-a-number/merge"
        environment["GITHUB_WORKFLOW_REF"] = workflow_ref(environment["GITHUB_REF"])
        report, errors = render(manifest, needs, environment, head, tree)
        self.assertTrue(any("numbered synthetic" in error for error in errors))
        self.assertEqual(report["result"], "fail")

    def test_future_pull_request_number_is_not_frozen_to_pr20(self) -> None:
        manifest, needs, environment, head, tree = fixture()
        environment["GITHUB_REF"] = "refs/pull/21/merge"
        environment["GITHUB_WORKFLOW_REF"] = workflow_ref(environment["GITHUB_REF"])
        report, errors = render(manifest, needs, environment, head, tree)
        self.assertEqual(errors, [])
        self.assertEqual(report["pull_request_number"], 21)
        self.assertEqual(report["canonical_activation"]["status"], "blocked")

    def test_each_non_success_required_job_fails(self) -> None:
        for state in ("failure", "skipped", "cancelled"):
            with self.subTest(state=state):
                manifest, needs, environment, head, tree = fixture()
                needs["macos-ipc"]["result"] = state
                report, errors = render(manifest, needs, environment, head, tree)
                self.assertTrue(any(state in error for error in errors))
                self.assertEqual(report["result"], "fail")

    def test_missing_required_job_fails(self) -> None:
        manifest, needs, environment, head, tree = fixture()
        del needs["macos-ipc"]
        report, errors = render(manifest, needs, environment, head, tree)
        self.assertTrue(any("macos-ipc" in error for error in errors))
        self.assertEqual(report["required_job_results"]["macos-ipc"], "missing")
        self.assertEqual(report["result"], "fail")

    def test_missing_tool_output_fails(self) -> None:
        manifest, needs, environment, head, tree = fixture()
        del needs["web"]["outputs"]["npm-version"]
        _, errors = render(manifest, needs, environment, head, tree)
        self.assertTrue(any("web output npm-version" in error for error in errors))

    def test_tool_versions_and_macos_architecture_are_cross_checked(self) -> None:
        manifest, needs, environment, head, tree = fixture()
        needs["python"]["outputs"]["qmd-node-version"] = "v0.0.0"
        needs["macos-ipc"]["outputs"]["architecture"] = "x86_64"
        report, errors = render(manifest, needs, environment, head, tree)
        self.assertTrue(any("v22.23.2" in error for error in errors))
        self.assertTrue(any("arm64" in error for error in errors))
        self.assertEqual(report["result"], "fail")

    def test_synthetic_context_does_not_replace_exact_source_or_tree(self) -> None:
        manifest, needs, environment, head, tree = fixture()
        report, errors = render(manifest, needs, environment, head, tree)
        self.assertEqual(errors, [])
        self.assertEqual(report["source_commit"], head)
        self.assertEqual(report["source_tree"], tree)
        self.assertEqual(report["exact_checked_out_sha"], head)
        self.assertNotEqual(report["synthetic_context_sha"], head)

    def test_malformed_source_tree_run_attempt_and_digest_fail(self) -> None:
        manifest, needs, environment, head, _ = fixture()
        environment["GITHUB_RUN_ATTEMPT"] = "zero"
        environment["LCF_MANIFEST_SHA256"] = "ABC"
        _, errors = render(manifest, needs, environment, head, "short")
        self.assertTrue(any("tree" in error for error in errors))
        self.assertTrue(any("GITHUB_RUN_ATTEMPT" in error for error in errors))
        self.assertTrue(any("manifest digest" in error for error in errors))

    def test_workflow_identity_and_timestamp_are_strict(self) -> None:
        manifest, needs, environment, head, tree = fixture()
        environment["GITHUB_WORKFLOW_REF"] = "wrong/workflow@refs/pull/20/merge"
        environment["LCF_RECORDED_AT"] = "not-a-time"
        _, errors = render(manifest, needs, environment, head, tree)
        self.assertTrue(any("workflow ref" in error for error in errors))
        self.assertTrue(any("recorded_at" in error for error in errors))

    def test_qmd_schema_tampering_fails_closed(self) -> None:
        mutations = {
            "schema": lambda qmd: qmd.update({"schema_version": 1}),
            "skip reason": lambda qmd: qmd.update({"allowed_skip_reason": "changed"}),
            "skipped": lambda qmd: qmd["tests"].update({"skipped": 2}),
            "total": lambda qmd: qmd["tests"].update({"tests": 12}),
            "fail": lambda qmd: qmd["tests"].update({"fail": 1}),
            "cancelled": lambda qmd: qmd["tests"].update({"cancelled": 1}),
            "todo": lambda qmd: qmd["tests"].update({"todo": 1}),
            "trap": lambda qmd: qmd.update({"network_trap": "missing"}),
            "policy": lambda qmd: qmd.update({"network_policy": "changed"}),
            "scope": lambda qmd: qmd["model_scan"].update({"scope": []}),
            "repository scope": lambda qmd: qmd["model_scan"].update(
                {"repository_worktree_scanned": True}
            ),
            "global scope": lambda qmd: qmd["model_scan"].update(
                {"global_tmp_scanned": True}
            ),
            "model delta": lambda qmd: qmd["model_scan"].update(
                {
                    "model_files_after": 1,
                    "model_files_created": 1,
                    "model_file_paths_created": ["cache/model.gguf"],
                }
            ),
            "cache delta": lambda qmd: qmd["model_scan"].update(
                {
                    "model_cache_paths_after": 1,
                    "model_cache_paths_created": 1,
                    "model_cache_path_names_created": ["cache/models"],
                }
            ),
            "errors": lambda qmd: qmd.update({"errors": ["hidden"]}),
            "boolean counts": lambda qmd: qmd.update(
                {
                    "tests": {
                        "tests": True,
                        "pass": False,
                        "fail": False,
                        "cancelled": False,
                        "skipped": True,
                        "todo": False,
                    }
                }
            ),
            "negative counts": lambda qmd: qmd["tests"].update(
                {"tests": -1, "pass": -2}
            ),
            "zero pass": lambda qmd: qmd["tests"].update(
                {"tests": 1, "pass": 0}
            ),
            "boolean model count": lambda qmd: qmd["model_scan"].update(
                {"model_files_before": False}
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                manifest, needs, environment, head, tree = fixture()
                changed = copy.deepcopy(qmd_result())
                mutate(changed)
                needs["python"]["outputs"]["qmd-result"] = json.dumps(changed)
                report, errors = render(manifest, needs, environment, head, tree)
                self.assertNotEqual(errors, [])
                self.assertEqual(report["result"], "fail")

    def test_downstream_gate_universe_remains_not_run(self) -> None:
        report, errors = render(*fixture())
        self.assertEqual(errors, [])
        self.assertEqual(
            set(report["downstream_gate_results"]), set(RENDERER.DOWNSTREAM_GATES)
        )
        self.assertEqual(set(report["downstream_gate_results"].values()), {"not-run"})


if __name__ == "__main__":
    unittest.main()

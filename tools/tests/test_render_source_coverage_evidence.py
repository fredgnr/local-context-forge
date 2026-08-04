from __future__ import annotations

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
        "result": "pass",
        "node_version": "22.23.2",
        "network_trap": "active",
        "network_policy": "deny-external-allow-af-unix",
        "model_files_created": 0,
        "model_cache_paths_created": 0,
        "isolated_home_xdg_tmp": True,
        "tests": {
            "tests": 11,
            "pass": 10,
            "fail": 0,
            "cancelled": 0,
            "skipped": 1,
            "todo": 0,
        },
    }


def fixture() -> tuple[dict[str, object], dict[str, object], dict[str, str], str]:
    manifest = json.loads(
        (ROOT / ".github" / "ci" / "source-coverage.json").read_text(encoding="utf-8")
    )
    head = "a" * 40
    needs = {
        job: {"result": "success", "outputs": {}}
        for job in manifest["aggregate"]["required_jobs"]
    }
    needs["python"]["outputs"].update(
        {
            "python-version": "Python 3.12.13",
            "qmd-node-version": "v22.23.2",
            "npm-version": "10.9.2",
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
    environment = {
        "LCF_SOURCE_SHA": head,
        "GITHUB_SHA": "b" * 40,
        "GITHUB_REPOSITORY": "fredgnr/local-context-forge",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REF": "refs/pull/20/merge",
        "GITHUB_HEAD_REF": "agent/w01",
        "GITHUB_WORKFLOW": "Desktop source CI",
        "GITHUB_WORKFLOW_REF": "fredgnr/local-context-forge/.github/workflows/desktop-ci.yml@refs/pull/20/merge",
        "GITHUB_WORKFLOW_SHA": "c" * 40,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SERVER_URL": "https://github.com",
        "LCF_MANIFEST_SHA256": "d" * 64,
        "LCF_RECORDED_AT": "2026-08-04T00:00:00+00:00",
    }
    return manifest, needs, environment, head


class RenderSourceCoverageTests(unittest.TestCase):
    def test_success_requires_all_jobs_and_qmd_invariants(self) -> None:
        manifest, needs, environment, head = fixture()
        report, errors = RENDERER.build_report(
            manifest, needs, environment, head, range_check="pass", evidence_status="pass"
        )
        self.assertEqual(errors, [])
        self.assertEqual(report["result"], "pass")
        self.assertEqual(set(report["canonical_gate_results"].values()), {"pass"})
        self.assertEqual(report["guide_site"]["disposition"], "external-blocked")

    def test_missing_required_job_fails(self) -> None:
        manifest, needs, environment, head = fixture()
        del needs["macos-ipc"]
        report, errors = RENDERER.build_report(
            manifest, needs, environment, head, range_check="pass", evidence_status="pass"
        )
        self.assertTrue(any("macos-ipc" in error for error in errors))
        self.assertEqual(report["result"], "fail")

    def test_unexpected_qmd_skip_fails(self) -> None:
        manifest, needs, environment, head = fixture()
        changed = qmd_result()
        changed["tests"]["skipped"] = 2
        needs["python"]["outputs"]["qmd-result"] = json.dumps(changed)
        _, errors = RENDERER.build_report(
            manifest, needs, environment, head, range_check="pass", evidence_status="pass"
        )
        self.assertTrue(any("exactly one" in error for error in errors))

    def test_synthetic_context_sha_does_not_replace_checked_out_head(self) -> None:
        manifest, needs, environment, head = fixture()
        report, errors = RENDERER.build_report(
            manifest, needs, environment, head, range_check="pass", evidence_status="pass"
        )
        self.assertEqual(errors, [])
        self.assertEqual(report["source_commit"], head)
        self.assertNotEqual(report["github_context_sha"], head)

    def test_checkpoint_run_stays_canonically_not_run_until_attestation(self) -> None:
        manifest, needs, environment, head = fixture()
        report, errors = RENDERER.build_report(
            manifest,
            needs,
            environment,
            head,
            range_check="pass",
            evidence_status="not-run",
        )
        self.assertEqual(errors, [])
        self.assertEqual(set(report["technical_candidate_gate_results"].values()), {"pass"})
        self.assertEqual(set(report["canonical_gate_results"].values()), {"not-run"})


if __name__ == "__main__":
    unittest.main()

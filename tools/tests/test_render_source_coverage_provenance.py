from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "render_source_coverage_provenance.py"
SPEC = importlib.util.spec_from_file_location("render_source_coverage_provenance", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
PROVENANCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROVENANCE)


def payload() -> dict[str, object]:
    source = "a" * 40
    qmd = {
        "schema_version": 2,
        "result": "pass",
        "node_version": "22.23.2",
        "command": (
            "node --import desktop/scripts/qmdNetworkTrap.mjs --test "
            "desktop/workers/qmd/test/*.test.mjs"
        ),
        "tests": {
            "tests": 11,
            "pass": 10,
            "fail": 0,
            "cancelled": 0,
            "skipped": 1,
            "todo": 0,
        },
        "allowed_skip_reason": (
            "better-sqlite3 native binding is not built in source checkout"
        ),
        "network_trap": "active",
        "network_policy": "deny-external-allow-af-unix",
        "model_scan": {
            "scope": PROVENANCE.PAYLOAD_RENDERER.MODEL_SCAN_SCOPE,
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
        "errors": [],
    }
    manifest = json.loads(
        (ROOT / ".github" / "ci" / "source-coverage.json").read_text(encoding="utf-8")
    )
    needs = {
        "python": {
            "result": "success",
            "outputs": {
                "python-version": "Python 3.12.13",
                "qmd-node-version": "v22.23.2",
                "npm-version": "10.9.8",
                "uv-version": "uv 0.11.29",
                "qmd-result": json.dumps(qmd),
            },
        },
        "web": {
            "result": "success",
            "outputs": {"node-version": "v24.9.0", "npm-version": "11.6.0"},
        },
        "desktop": {
            "result": "success",
            "outputs": {"node-version": "v24.9.0", "npm-version": "11.6.0"},
        },
        "macos-ipc": {
            "result": "success",
            "outputs": {
                "architecture": "arm64",
                "python-version": "Python 3.12.13",
                "uv-version": "uv 0.11.29",
            },
        },
    }
    synthetic = "c" * 40
    environment = {
        "LCF_SOURCE_SHA": source,
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
        "LCF_MANIFEST_SHA256": "d" * 64,
        "LCF_RECORDED_AT": "2026-08-04T00:00:00+00:00",
    }
    report, errors = PROVENANCE.PAYLOAD_RENDERER.build_report(
        manifest, needs, environment, source, "b" * 40
    )
    if errors:
        raise AssertionError(errors)
    return report


def environment(source: str = "a" * 40) -> dict[str, str]:
    return {
        "LCF_PAYLOAD_ARTIFACT_ID": "456",
        "LCF_PAYLOAD_ARTIFACT_NAME": f"w01-source-coverage-{source}",
        "LCF_PAYLOAD_ARTIFACT_URL": (
            "https://github.com/fredgnr/local-context-forge/actions/runs/123/artifacts/456"
        ),
        "LCF_PAYLOAD_ARTIFACT_DIGEST": "c" * 64,
    }


def failed_main_payload() -> dict[str, object]:
    value = payload()
    source = value["source_commit"]
    value.update(
        {
            "lifecycle_phase": "canonical-main-source",
            "event": "push",
            "source_ref": "refs/heads/main",
            "source_branch": "main",
            "pull_request_number": None,
            "github_context_sha": source,
            "synthetic_context_sha": None,
            "workflow_ref": (
                "fredgnr/local-context-forge/.github/workflows/desktop-ci.yml@"
                "refs/heads/main"
            ),
            "workflow_sha": source,
            "technical_candidate_gate_results": None,
            "main_source_gate_results": {
                gate: "fail" for gate in PROVENANCE.PAYLOAD_RENDERER.GATES
            },
            "independent_acceptance": {
                "status": "not-observable-by-source-workflow",
                "external_reference": None,
            },
            "canonical_activation": {
                "status": "blocked",
                "required_conditions": (
                    PROVENANCE.PAYLOAD_RENDERER.FAILED_MAIN_ACTIVATION_CONDITIONS
                ),
            },
            "result": "fail",
            "errors": ["required job web concluded failure"],
        }
    )
    value["required_job_results"]["web"] = "failure"
    return value


class SourceCoverageProvenanceTests(unittest.TestCase):
    def build(
        self,
        changed_payload: dict[str, object] | None = None,
        changed_environment: dict[str, str] | None = None,
    ) -> tuple[dict[str, object], list[str]]:
        value = changed_payload if changed_payload is not None else payload()
        env = changed_environment if changed_environment is not None else environment()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "w01-source-coverage.json"
            path.write_text(json.dumps(value) + "\n", encoding="utf-8")
            return PROVENANCE.build_provenance(value, path, env)

    def test_payload_upload_is_bound_without_self_reference(self) -> None:
        record, errors = self.build()
        self.assertEqual(errors, [])
        self.assertEqual(record["payload_artifact"]["id"], 456)
        self.assertRegex(record["payload_artifact"]["archive_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(record["payload"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("provenance_artifact", record)
        self.assertNotIn("provenance_archive_sha256", record)
        self.assertEqual(record["result"], "pass")
        self.assertEqual(record["errors"], [])

    def test_missing_or_invalid_artifact_id_fails(self) -> None:
        for value in ("", "0", "not-an-id"):
            with self.subTest(value=value):
                env = environment()
                env["LCF_PAYLOAD_ARTIFACT_ID"] = value
                _, errors = self.build(changed_environment=env)
                self.assertTrue(any("artifact ID" in error for error in errors))

    def test_archive_digest_must_be_full_lowercase_sha256(self) -> None:
        for value in ("short", "A" * 64):
            with self.subTest(value=value):
                env = environment()
                env["LCF_PAYLOAD_ARTIFACT_DIGEST"] = value
                _, errors = self.build(changed_environment=env)
                self.assertTrue(any("archive digest" in error for error in errors))

    def test_artifact_name_must_match_payload_and_source(self) -> None:
        value = payload()
        value["payload_artifact_name"] = "w01-source-coverage-wrong"
        _, errors = self.build(value)
        self.assertTrue(any("artifact name" in error for error in errors))

    def test_payload_source_tree_run_and_lifecycle_are_strict(self) -> None:
        mutations = {
            "source": ("source_commit", "short"),
            "tree": ("source_tree", "short"),
            "run": ("run_id", 0),
            "attempt": ("run_attempt", 0),
            "lifecycle": ("lifecycle_phase", "future-unknown"),
        }
        for label, (key, changed) in mutations.items():
            with self.subTest(label=label):
                value = payload()
                value[key] = changed
                _, errors = self.build(value)
                self.assertNotEqual(errors, [])

    def test_exact_checkout_must_equal_source_commit(self) -> None:
        value = payload()
        value["exact_checked_out_sha"] = "d" * 40
        _, errors = self.build(value)
        self.assertTrue(any("checked-out SHA" in error for error in errors))

    def test_artifact_url_must_bind_run_and_artifact_id(self) -> None:
        env = environment()
        env["LCF_PAYLOAD_ARTIFACT_URL"] = (
            "https://github.com/fredgnr/local-context-forge/actions/runs/999/artifacts/456"
        )
        _, errors = self.build(changed_environment=env)
        self.assertTrue(any("URL conflicts" in error for error in errors))

    def test_candidate_payload_cannot_claim_canonical_pass(self) -> None:
        value = payload()
        value["canonical_activation"] = {"status": "pass"}
        _, errors = self.build(value)
        self.assertTrue(any("canonical activation" in error for error in errors))

    def test_future_pull_request_number_remains_valid(self) -> None:
        value = payload()
        value["pull_request_number"] = 21
        value["source_ref"] = "refs/pull/21/merge"
        value["workflow_ref"] = (
            "fredgnr/local-context-forge/.github/workflows/desktop-ci.yml@"
            "refs/pull/21/merge"
        )
        record, errors = self.build(value)
        self.assertEqual(errors, [])
        self.assertEqual(record["result"], "pass")

    def test_failed_main_payload_receives_truthful_provenance(self) -> None:
        record, errors = self.build(failed_main_payload())
        self.assertEqual(errors, [])
        self.assertEqual(record["payload"]["result"], "fail")
        self.assertEqual(record["canonical_activation_status"], "blocked")
        self.assertEqual(record["result"], "pass")

    def test_pull_request_number_and_ref_mismatch_fails(self) -> None:
        value = payload()
        value["pull_request_number"] = 21
        _, errors = self.build(value)
        self.assertTrue(any("number and source ref conflict" in error for error in errors))

    def test_payload_schema_is_closed_and_complete(self) -> None:
        mutations = {
            "unknown canonical field": lambda value: value.update(
                {"canonical_gate_results": {"VAL-GOV-001": "pass"}}
            ),
            "missing result": lambda value: value.pop("result"),
            "missing required jobs": lambda value: value.pop("required_jobs"),
            "missing QMD": lambda value: value.pop("qmd_source"),
            "unknown tool field": lambda value: value["tool_versions"]["web"].update(
                {"extra-version": "1.0.0"}
            ),
            "invalid timestamp": lambda value: value.update({"recorded_at": "not-a-time"}),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                value = payload()
                mutate(value)
                record, errors = self.build(value)
                self.assertNotEqual(errors, [])
                self.assertEqual(record["result"], "fail")
                self.assertEqual(record["errors"], errors)

    def test_minimal_payload_cannot_receive_passing_provenance(self) -> None:
        value = {
            "schema_version": 2,
            "repository": "fredgnr/local-context-forge",
            "work_id": "W01",
        }
        record, errors = self.build(value)
        self.assertNotEqual(errors, [])
        self.assertEqual(record["result"], "fail")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
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


def checkpoint_a() -> dict[str, object]:
    source = "f" * 40
    payload = {
        "id": 1001,
        "name": f"w01-source-coverage-{source}",
        "source_commit": source,
        "run_id": 2001,
        "archive_sha256": "1" * 64,
        "inner_json_sha256": "2" * 64,
        "payload_schema_version": 2,
    }
    return {
        "source_commit": source,
        "source_tree": "e" * 40,
        "lifecycle_phase": "branch-candidate",
        "run": {
            "id": 2001,
            "attempt": 1,
            "event": "push",
            "source_ref": "refs/heads/agent/w01-governance-source-ci",
            "exact_checked_out_sha": source,
            "synthetic_context_sha": None,
            "workflow_path": ".github/workflows/desktop-ci.yml",
            "workflow_sha": source,
            "url": "https://github.com/fredgnr/local-context-forge/actions/runs/2001",
            "conclusion": "success",
            "job_results": {
                "python": "success",
                "web": "success",
                "desktop": "success",
                "macos-ipc": "success",
                "source-coverage": "success",
            },
        },
        "payload_artifact": payload,
        "provenance_artifact": {
            "id": 1002,
            "name": f"w01-source-coverage-provenance-{source}",
            "source_commit": source,
            "run_id": 2001,
            "archive_sha256": "3" * 64,
            "inner_json_sha256": "4" * 64,
            "payload_binding": {
                "artifact_id": payload["id"],
                "artifact_name": payload["name"],
                "archive_sha256": payload["archive_sha256"],
                "inner_json_sha256": payload["inner_json_sha256"],
            },
        },
        "provenance_absence_reason": None,
        "technical_gate_results": {gate: "pass" for gate in CHECKER.GATES},
        "legacy_payload_canonical_gate_results": None,
        "tool_versions": {
            "python": {
                "python-version": "Python 3.12.13",
                "qmd-node-version": "v22.23.2",
                "npm-version": "10.9.8",
                "uv-version": "uv 0.11.29",
            },
            "web": {"node-version": "v24.18.0", "npm-version": "11.16.0"},
            "desktop": {
                "node-version": "v24.18.0",
                "npm-version": "11.16.0",
            },
            "macos-ipc": {
                "architecture": "arm64",
                "python-version": "Python 3.12.10",
                "uv-version": "uv 0.11.29",
            },
        },
        "qmd_source": {
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
                "scope": CHECKER.MODEL_SCAN_SCOPE,
                "repository_worktree_scanned": False,
                "global_tmp_scanned": False,
                "model_files_created": 0,
                "model_cache_paths_created": 0,
                "scope_basis": "runtime payload v2 explicit scope",
            },
        },
        "guide_site": {
            "disposition": "external-blocked",
            "included": False,
            "validated": False,
        },
    }


def completed_record() -> dict[str, object]:
    record = pending_record()
    checkpoint = checkpoint_a()
    remediation = record["remediation"]
    remediation["checkpoint_a"] = checkpoint
    remediation["checkpoint_a_record_sha256"] = CHECKER.canonical_object_digest(checkpoint)
    remediation["technical_source_result"] = "pass"
    return record


def refresh_checkpoint_digest(record: dict[str, object]) -> None:
    remediation = record["remediation"]
    checkpoint = remediation["checkpoint_a"]
    remediation["checkpoint_a_record_sha256"] = CHECKER.canonical_object_digest(checkpoint)


def git(cwd: Path, *arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class W01EvidenceTests(unittest.TestCase):
    def test_production_checker_has_no_current_git_history_dependency(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in (
            "import subprocess",
            "subprocess.",
            "verify_git_binding",
            "merge-base",
            "--is-ancestor",
            "git diff",
            "ALLOWED_ATTESTATION_PATHS",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_schema_nested_contract_cannot_be_weakened(self) -> None:
        schema = json.loads(CHECKER.SCHEMA.read_text(encoding="utf-8"))
        schema["$defs"]["qmd"]["additionalProperties"] = True
        self.assertIn(
            "W01 schema v2 immutable contract digest drifted",
            CHECKER.validate_schema_document(schema),
        )

    def test_pending_remediation_record_is_honest(self) -> None:
        self.assertEqual(CHECKER.validate_evidence(pending_record()), [])

    def test_completed_checkpoint_record_is_valid_but_acceptance_pending(self) -> None:
        record = completed_record()
        self.assertEqual(CHECKER.validate_evidence(record), [])
        self.assertEqual(record["remediation"]["independent_acceptance"], "pending")
        self.assertEqual(record["remediation"]["canonical_activation"]["status"], "blocked")

    def test_old_rejected_candidate_coordinates_are_immutable(self) -> None:
        mutations = {
            "candidate source": lambda value: value["candidate_history"][0].update(
                {"source_commit": "0" * 40}
            ),
            "candidate tree": lambda value: value["candidate_history"][0].update(
                {"source_tree": "0" * 40}
            ),
            "checkpoint source": lambda value: value["candidate_history"][0][
                "implementation_checkpoint"
            ].update({"source_commit": "0" * 40}),
            "checkpoint tree": lambda value: value["candidate_history"][0][
                "implementation_checkpoint"
            ].update({"source_tree": "0" * 40}),
            "final archive": lambda value: value["candidate_history"][0][
                "final_source_execution"
            ]["payload_artifact"].update({"archive_sha256": "0" * 64}),
            "historical tool version": lambda value: value["candidate_history"][0][
                "final_source_execution"
            ]["tool_versions"]["python"].update({"python-version": "Python 0.0"}),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                record = pending_record()
                mutate(record)
                self.assertNotEqual(CHECKER.validate_evidence(record), [])

    def test_artifact_id_inner_digest_and_name_are_required(self) -> None:
        mutations = {
            "artifact ID": lambda checkpoint: checkpoint["payload_artifact"].pop("id"),
            "inner digest": lambda checkpoint: checkpoint["payload_artifact"].pop(
                "inner_json_sha256"
            ),
            "artifact name": lambda checkpoint: checkpoint["payload_artifact"].update(
                {"name": "w01-source-coverage-wrong"}
            ),
            "artifact run": lambda checkpoint: checkpoint["payload_artifact"].update(
                {"run_id": 9999}
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                record = completed_record()
                mutate(record["remediation"]["checkpoint_a"])
                refresh_checkpoint_digest(record)
                errors = CHECKER.validate_evidence(record)
                self.assertNotEqual(errors, [])
                self.assertFalse(any("record digest" in error for error in errors))

    def test_provenance_must_bind_payload_digests(self) -> None:
        record = completed_record()
        checkpoint = record["remediation"]["checkpoint_a"]
        checkpoint["payload_artifact"]["archive_sha256"] = "9" * 64
        errors = CHECKER.validate_evidence(record)
        self.assertTrue(any("provenance binding" in error for error in errors))
        self.assertTrue(any("record digest" in error for error in errors))

    def test_checkpoint_tool_versions_are_cross_checked(self) -> None:
        record = completed_record()
        checkpoint = record["remediation"]["checkpoint_a"]
        checkpoint["tool_versions"]["python"]["qmd-node-version"] = "v0.0.0"
        checkpoint["tool_versions"]["macos-ipc"]["architecture"] = "x86_64"
        refresh_checkpoint_digest(record)
        errors = CHECKER.validate_evidence(record)
        self.assertTrue(any("v22.23.2" in error for error in errors))
        self.assertTrue(any("arm64" in error for error in errors))
        self.assertFalse(any("record digest" in error for error in errors))

    def test_unknown_lifecycle_phase_fails(self) -> None:
        record = completed_record()
        record["remediation"]["checkpoint_a"]["lifecycle_phase"] = "future-unknown"
        self.assertTrue(
            any("lifecycle phase" in error for error in CHECKER.validate_evidence(record))
        )

    def test_candidate_source_ref_must_bind_pr20_or_the_w01_branch(self) -> None:
        record = completed_record()
        checkpoint = record["remediation"]["checkpoint_a"]
        checkpoint["lifecycle_phase"] = "pull-request-candidate"
        checkpoint["run"].update(
            {
                "event": "pull_request",
                "source_ref": "refs/pull/999/merge",
                "synthetic_context_sha": "a" * 40,
                "workflow_sha": "a" * 40,
            }
        )
        refresh_checkpoint_digest(record)
        errors = CHECKER.validate_evidence(record)
        self.assertIn("remediation checkpoint A PR source ref must bind PR #20", errors)

    def test_old_rejected_candidate_cannot_be_changed_to_accepted(self) -> None:
        record = pending_record()
        record["candidate_history"][0]["independent_acceptance"] = "pass"
        record["candidate_history"][0]["canonical_activation"]["status"] = "eligible"
        errors = CHECKER.validate_evidence(record)
        self.assertTrue(any("independent_acceptance" in error for error in errors))
        self.assertTrue(any("accepted/eligible" in error for error in errors))

    def test_new_candidate_cannot_self_declare_acceptance(self) -> None:
        record = completed_record()
        record["remediation"]["independent_acceptance"] = "pass"
        errors = CHECKER.validate_evidence(record)
        self.assertIn("new W01 candidate independent acceptance must remain pending", errors)

    def test_canonical_activation_conditions_cannot_be_removed(self) -> None:
        record = completed_record()
        record["remediation"]["canonical_activation"]["required_conditions"].pop()
        errors = CHECKER.validate_evidence(record)
        self.assertIn("new W01 candidate canonical activation conditions drifted", errors)

    def test_qmd_field_tampering_fails(self) -> None:
        mutations = {
            "skip reason": lambda qmd: qmd.update({"allowed_skip_reason": "changed"}),
            "skipped": lambda qmd: qmd["tests"].update({"skipped": 2}),
            "totals": lambda qmd: qmd["tests"].update({"tests": 12}),
            "fail": lambda qmd: qmd["tests"].update({"fail": 1}),
            "cancelled": lambda qmd: qmd["tests"].update({"cancelled": 1}),
            "todo": lambda qmd: qmd["tests"].update({"todo": 1}),
            "network trap": lambda qmd: qmd.update({"network_trap": "missing"}),
            "network policy": lambda qmd: qmd.update({"network_policy": "changed"}),
            "scope missing": lambda qmd: qmd["model_scan"].pop("scope"),
            "model file": lambda qmd: qmd["model_scan"].update(
                {"model_files_created": 1}
            ),
            "model cache": lambda qmd: qmd["model_scan"].update(
                {"model_cache_paths_created": 1}
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                record = completed_record()
                mutate(record["remediation"]["checkpoint_a"]["qmd_source"])
                refresh_checkpoint_digest(record)
                errors = CHECKER.validate_evidence(record)
                self.assertNotEqual(errors, [])
                self.assertFalse(any("record digest" in error for error in errors))

        for label, mutate in {
            "boolean tests": lambda qmd: qmd["tests"].update(
                {
                    "tests": True,
                    "pass": False,
                    "fail": False,
                    "cancelled": False,
                    "skipped": True,
                    "todo": False,
                }
            ),
            "negative tests": lambda qmd: qmd["tests"].update(
                {"tests": -1, "pass": -2}
            ),
            "zero pass": lambda qmd: qmd["tests"].update(
                {"tests": 1, "pass": 0}
            ),
            "boolean model count": lambda qmd: qmd["model_scan"].update(
                {"model_files_created": False}
            ),
        }.items():
            with self.subTest(label=label):
                record = completed_record()
                mutate(record["remediation"]["checkpoint_a"]["qmd_source"])
                refresh_checkpoint_digest(record)
                errors = CHECKER.validate_evidence(record)
                self.assertNotEqual(errors, [])
                self.assertFalse(any("record digest" in error for error in errors))

    def test_out_of_scope_contract_is_closed(self) -> None:
        record = completed_record()
        record["out_of_scope"].pop()
        self.assertIn(
            "W01 out-of-scope list must match the closed v2 schema contract",
            CHECKER.validate_evidence(record),
        )

    def test_checkpoint_record_digest_detects_field_rewrite(self) -> None:
        record = completed_record()
        record["remediation"]["checkpoint_a"]["source_tree"] = "a" * 40
        self.assertTrue(
            any("record digest" in error for error in CHECKER.validate_evidence(record))
        )

    def run_checker_in_fixture(
        self, repository: Path, source_commit: str, source_tree: str
    ) -> subprocess.CompletedProcess[str]:
        evidence = repository / "evidence.json"
        record = completed_record()
        checkpoint = record["remediation"]["checkpoint_a"]
        checkpoint["source_commit"] = source_commit
        checkpoint["source_tree"] = source_tree
        checkpoint["run"]["exact_checked_out_sha"] = source_commit
        checkpoint["run"]["workflow_sha"] = source_commit
        checkpoint["payload_artifact"]["source_commit"] = source_commit
        checkpoint["payload_artifact"]["name"] = f"w01-source-coverage-{source_commit}"
        checkpoint["provenance_artifact"]["source_commit"] = source_commit
        checkpoint["provenance_artifact"]["name"] = (
            f"w01-source-coverage-provenance-{source_commit}"
        )
        checkpoint["provenance_artifact"]["payload_binding"]["artifact_name"] = (
            checkpoint["payload_artifact"]["name"]
        )
        refresh_checkpoint_digest(record)
        evidence.write_text(json.dumps(record) + "\n", encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--evidence",
                str(evidence),
                "--schema",
                str(CHECKER.SCHEMA),
            ],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
        )

    def initialize_git_fixture(self, repository: Path) -> str:
        git(repository, "init", "-b", "main")
        git(repository, "config", "user.name", "W01 Fixture")
        git(repository, "config", "user.email", "fixture@example.invalid")
        write(repository / "README.md", "fixture\n")
        git(repository, "add", "README.md")
        git(repository, "commit", "-m", "base")
        return git(repository, "rev-parse", "HEAD")

    def test_future_product_descendant_does_not_invalidate_historical_w01_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            historical_source = self.initialize_git_fixture(repository)
            historical_tree = git(repository, "rev-parse", "HEAD^{tree}")
            write(repository / "desktop" / "w02" / "smoke.py", "print('future')\n")
            git(repository, "add", "desktop/w02/smoke.py")
            git(repository, "commit", "-m", "future W02 product change")
            result = self.run_checker_in_fixture(
                repository, historical_source, historical_tree
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_merge_commit_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            self.initialize_git_fixture(repository)
            git(repository, "checkout", "-b", "candidate")
            write(repository / "candidate.txt", "candidate\n")
            git(repository, "add", "candidate.txt")
            git(repository, "commit", "-m", "candidate")
            candidate = git(repository, "rev-parse", "HEAD")
            candidate_tree = git(repository, "rev-parse", "HEAD^{tree}")
            git(repository, "checkout", "main")
            git(repository, "merge", "--no-ff", "candidate", "-m", "merge candidate")
            ancestry = subprocess.run(
                ["git", "merge-base", "--is-ancestor", candidate, "HEAD"],
                cwd=repository,
                check=False,
            )
            self.assertEqual(ancestry.returncode, 0)
            result = self.run_checker_in_fixture(repository, candidate, candidate_tree)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_squash_equivalent_tree_compatibility_without_ancestry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            self.initialize_git_fixture(repository)
            git(repository, "checkout", "-b", "candidate")
            write(repository / "candidate.txt", "candidate\n")
            git(repository, "add", "candidate.txt")
            git(repository, "commit", "-m", "candidate")
            candidate = git(repository, "rev-parse", "HEAD")
            candidate_tree = git(repository, "rev-parse", "HEAD^{tree}")
            git(repository, "checkout", "main")
            git(repository, "merge", "--squash", "candidate")
            git(repository, "commit", "-m", "squash equivalent")
            self.assertEqual(git(repository, "rev-parse", "HEAD^{tree}"), candidate_tree)
            ancestry = subprocess.run(
                ["git", "merge-base", "--is-ancestor", candidate, "HEAD"], cwd=repository
            )
            self.assertNotEqual(ancestry.returncode, 0)
            result = self.run_checker_in_fixture(repository, candidate, candidate_tree)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rebase_equivalent_compatibility_without_original_ancestry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            self.initialize_git_fixture(repository)
            git(repository, "checkout", "-b", "candidate")
            write(repository / "candidate.txt", "candidate\n")
            git(repository, "add", "candidate.txt")
            git(repository, "commit", "-m", "candidate")
            original_candidate = git(repository, "rev-parse", "HEAD")
            original_tree = git(repository, "rev-parse", "HEAD^{tree}")
            git(repository, "checkout", "main")
            write(repository / "main-movement.txt", "unrelated\n")
            git(repository, "add", "main-movement.txt")
            git(repository, "commit", "-m", "main movement")
            git(repository, "checkout", "candidate")
            git(repository, "rebase", "main")
            ancestry = subprocess.run(
                ["git", "merge-base", "--is-ancestor", original_candidate, "HEAD"],
                cwd=repository,
            )
            self.assertNotEqual(ancestry.returncode, 0)
            self.assertEqual((repository / "candidate.txt").read_text(), "candidate\n")
            self.assertEqual(
                (repository / "main-movement.txt").read_text(), "unrelated\n"
            )
            result = self.run_checker_in_fixture(
                repository, original_candidate, original_tree
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_main_movement_before_merge_is_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            self.initialize_git_fixture(repository)
            git(repository, "checkout", "-b", "candidate")
            write(repository / "candidate.txt", "candidate\n")
            git(repository, "add", "candidate.txt")
            git(repository, "commit", "-m", "candidate")
            candidate = git(repository, "rev-parse", "HEAD")
            candidate_tree = git(repository, "rev-parse", "HEAD^{tree}")
            git(repository, "checkout", "main")
            write(repository / "unrelated-main.txt", "unrelated\n")
            git(repository, "add", "unrelated-main.txt")
            git(repository, "commit", "-m", "move main")
            git(repository, "merge", "--no-ff", "candidate", "-m", "merge after movement")
            self.assertTrue((repository / "unrelated-main.txt").exists())
            result = self.run_checker_in_fixture(repository, candidate, candidate_tree)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Validate the two-stage, non-self-referential W01 evidence record."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "development" / "evidence" / "W01" / "2026-08-04.json"
BASELINE = "3eff97d97b2de4484d568bab5ac96d63830c79ee"
GATES = {
    "VAL-PRE1-SEQUENCE-001",
    "VAL-GOV-001",
    "VAL-CI-COVERAGE-001",
}
REQUIRED_JOBS = ["python", "web", "desktop", "macos-ipc"]
SOURCE_EXPRESSION = "${{ github.event.pull_request.head.sha || github.sha }}"
FINAL_BINDING = {
    "mode": "github-actions-check-on-containing-commit",
    "workflow_path": ".github/workflows/desktop-ci.yml",
    "workflow_name": "Desktop source CI",
    "events": ["push", "pull_request"],
    "source_expression": SOURCE_EXPRESSION,
    "required_jobs": REQUIRED_JOBS,
    "summary_job": "source-coverage",
    "runtime_artifact_prefix": "w01-source-coverage-",
}
CANONICAL_ACTIVATION = [
    "independent acceptance of the exact final PR head",
    "merge of that accepted PR into canonical main",
    "successful source-coverage job on the exact resulting canonical main commit",
]
ALLOWED_ATTESTATION_PATHS = {
    "docs/development/evidence/W01/2026-08-04.json",
    "docs/development/evidence/README.md",
    "docs/development/iterations/0002-bundled-runtimes.md",
    "docs/development/iterations/0002-r13-pre1-incremental-retirement.md",
    "docs/development/iterations/README.md",
    "docs/development/status.md",
    "docs/development/todo.md",
    "docs/development/traceability.md",
    "docs/development/work-plan.md",
}


def validate_evidence(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != 1:
        errors.append("W01 evidence schema_version must be 1")
    if record.get("work_id") != "W01":
        errors.append("W01 evidence work_id is wrong")
    if record.get("repository") != "fredgnr/local-context-forge":
        errors.append("W01 evidence repository is wrong")
    if record.get("baseline_commit") != BASELINE:
        errors.append("W01 evidence baseline commit drifted")
    if record.get("final_head_binding") != FINAL_BINDING:
        errors.append("W01 final-head binding contract drifted")
    if record.get("canonical_activation") != CANONICAL_ACTIVATION:
        errors.append("W01 canonical activation conditions drifted")
    out_of_scope = record.get("out_of_scope", [])
    for phrase in (
        "W02 packaged smoke",
        "Legacy deletion",
        "engineering test package",
        "GitHub production control plane",
    ):
        if phrase not in out_of_scope:
            errors.append(f"W01 out-of-scope list missing {phrase!r}")

    status = record.get("status")
    gates = record.get("gates")
    if not isinstance(gates, dict) or set(gates) != GATES:
        errors.append("W01 evidence must enumerate exactly the three W01 gates")
        gates = {}
    if status == "not-run":
        if record.get("checkpoint") is not None:
            errors.append("not-run W01 evidence cannot name a checkpoint")
        if record.get("pull_request") is not None:
            errors.append("not-run W01 evidence cannot name a pull request")
        if any(value != "not-run" for value in gates.values()):
            errors.append("not-run W01 evidence must keep all gates not-run")
        return errors
    if status != "pass":
        errors.append("W01 evidence status must be pass or not-run")
        return errors
    if any(value != "pass" for value in gates.values()):
        errors.append("pass W01 evidence requires all three gates pass")
    if not isinstance(record.get("pull_request"), int):
        errors.append("pass W01 evidence requires a pull request number")

    checkpoint = record.get("checkpoint")
    if not isinstance(checkpoint, dict):
        errors.append("pass W01 evidence requires a checkpoint object")
        return errors
    commit = checkpoint.get("commit")
    tree = checkpoint.get("tree")
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        errors.append("checkpoint commit must be a full lowercase SHA")
    if not isinstance(tree, str) or re.fullmatch(r"[0-9a-f]{40}", tree) is None:
        errors.append("checkpoint tree must be a full lowercase SHA")
    if checkpoint.get("clean_checkout") is not True:
        errors.append("checkpoint must record a clean checkout")
    if checkpoint.get("base_to_head_diff_check") != "pass":
        errors.append("checkpoint base-to-head diff check must pass")
    for digest_name in ("manifest_sha256", "runtime_evidence_sha256"):
        digest = checkpoint.get(digest_name)
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            errors.append(f"checkpoint {digest_name} must be a SHA-256")
    if checkpoint.get("runtime_artifact_name") != f"w01-source-coverage-{commit}":
        errors.append("checkpoint runtime artifact name is not commit-bound")
    environment = checkpoint.get("environment")
    required_environment = {
        "python_job",
        "web_job",
        "desktop_job",
        "macos_ipc_job",
        "tool_versions",
    }
    if not isinstance(environment, dict) or set(environment) != required_environment:
        errors.append("checkpoint environment/tool-version record is incomplete")
    elif not all(isinstance(value, (str, dict)) and value for value in environment.values()):
        errors.append("checkpoint environment/tool-version values must be non-empty")

    run = checkpoint.get("actions_run")
    if not isinstance(run, dict):
        errors.append("checkpoint requires an Actions run")
        return errors
    if run.get("event") not in {"push", "pull_request"}:
        errors.append("checkpoint Actions event is not an exact-head eligible event")
    if run.get("head_sha") != commit:
        errors.append("checkpoint Actions head does not match checkpoint commit")
    if run.get("workflow_path") != ".github/workflows/desktop-ci.yml":
        errors.append("checkpoint Actions workflow path drifted")
    if run.get("workflow_sha") != commit:
        errors.append("checkpoint Actions workflow SHA does not match checkpoint commit")
    if run.get("source_ref") != "refs/heads/agent/w01-governance-source-ci":
        errors.append("checkpoint Actions source ref is wrong")
    if run.get("conclusion") != "success":
        errors.append("checkpoint Actions run did not succeed")
    run_id = run.get("run_id")
    expected_url = f"https://github.com/fredgnr/local-context-forge/actions/runs/{run_id}"
    if not isinstance(run_id, int) or run.get("url") != expected_url:
        errors.append("checkpoint Actions run ID/URL are inconsistent")
    if run.get("attempt") != 1:
        errors.append("checkpoint Actions run attempt must be recorded explicitly")
    job_results = run.get("job_results")
    if not isinstance(job_results, dict) or set(job_results) != {
        *REQUIRED_JOBS,
        "source-coverage",
    }:
        errors.append("checkpoint Actions job result set is incomplete")
    elif any(value != "success" for value in job_results.values()):
        errors.append("every checkpoint Actions job must succeed")

    components = checkpoint.get("components")
    required_components = {
        "python",
        "host_runner",
        "mcp",
        "demo_python_sdk",
        "web",
        "desktop",
        "qmd_worker",
        "governance",
    }
    if not isinstance(components, dict) or set(components) != required_components:
        errors.append("checkpoint component evidence set is incomplete")
    elif any(
        not isinstance(component, dict) or component.get("result") != "pass"
        for component in components.values()
    ):
        errors.append("every checkpoint component result must pass")
    if isinstance(components, dict) and set(components) == required_components:
        for component_name, component in components.items():
            if not isinstance(component.get("command"), str) or not component["command"]:
                errors.append(f"checkpoint component {component_name} is missing its command")
            count_key = "checks" if component_name == "mcp" else "tests"
            count = component.get(count_key)
            skipped = component.get("skipped")
            if not isinstance(count, int) or count <= 0:
                errors.append(f"checkpoint component {component_name} has no positive {count_key} count")
            if not isinstance(skipped, int) or skipped < 0:
                errors.append(f"checkpoint component {component_name} has no explicit skip count")
    qmd = components.get("qmd_worker", {}) if isinstance(components, dict) else {}
    for key, expected in (
        ("node_version", "22.23.2"),
        ("skipped", 1),
        ("network_trap", "active"),
        ("model_files_created", 0),
        ("model_cache_paths_created", 0),
    ):
        if qmd.get(key) != expected:
            errors.append(f"checkpoint QMD {key} must be {expected!r}")
    return errors


def git_output(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def verify_git_binding(record: dict[str, Any]) -> list[str]:
    if record.get("status") != "pass":
        return []
    errors: list[str] = []
    checkpoint = record["checkpoint"]
    commit = checkpoint["commit"]
    try:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        errors.append("checkpoint commit is not an ancestor of the containing commit")
        return errors
    if git_output("rev-parse", f"{commit}^{{tree}}") != checkpoint["tree"]:
        errors.append("checkpoint tree does not match local git object")
    changed = set(git_output("diff", "--name-only", commit, "HEAD").splitlines())
    unexpected = sorted(changed - ALLOWED_ATTESTATION_PATHS)
    if unexpected:
        errors.append(f"checkpoint-to-attestation delta contains non-governance paths: {unexpected}")
    try:
        subprocess.run(
            ["git", "diff", "--check", commit, "HEAD"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        errors.append("checkpoint-to-attestation diff check failed")
    return errors


def main() -> int:
    record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    errors = [*validate_evidence(record), *verify_git_binding(record)]
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"W01 evidence OK: {record['status']} with non-self-referential final-head binding")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

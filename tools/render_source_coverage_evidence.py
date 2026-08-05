#!/usr/bin/env python3
"""Render strict exact-head W01 source evidence without canonical self-promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 2
REPOSITORY = "fredgnr/local-context-forge"
WORKFLOW_PATH = ".github/workflows/desktop-ci.yml"
PAYLOAD_ARTIFACT_PREFIX = "w01-source-coverage-"
GATES = (
    "VAL-PRE1-SEQUENCE-001",
    "VAL-GOV-001",
    "VAL-CI-COVERAGE-001",
)
REQUIRED_OUTPUTS = {
    "python": ["python-version", "qmd-node-version", "npm-version", "uv-version"],
    "web": ["node-version", "npm-version"],
    "desktop": ["node-version", "npm-version"],
    "macos-ipc": ["architecture", "python-version", "uv-version"],
}
MODEL_SCAN_SCOPE = [
    "isolated HOME",
    "isolated XDG_CACHE_HOME",
    "isolated XDG_CONFIG_HOME",
    "isolated XDG_DATA_HOME",
    "isolated TMPDIR",
]
PR_ACTIVATION_CONDITIONS = [
    "independent acceptance of the exact final PR head",
    "merge of that accepted candidate into canonical main",
    "successful source-coverage on the exact resulting main commit",
]
MAIN_ACTIVATION_CONDITIONS = [
    "verifiable external independent-acceptance reference for the incorporated exact PR candidate",
    "verified linkage from that accepted candidate to this canonical main commit",
]
FAILED_MAIN_ACTIVATION_CONDITIONS = [
    "successful source-coverage on the exact resulting main commit",
    *MAIN_ACTIVATION_CONDITIONS,
]
DOWNSTREAM_GATES = (
    "VAL-PACKAGED-SMOKE-001",
    "VAL-LEGACY-DECOUPLE-001",
    "VAL-LEGACY-TRANSPORT-001",
    "VAL-LEGACY-PROVIDER-001",
    "VAL-LEGACY-DEPLOY-001",
    "VAL-LEGACY-RELEASE-001",
    "VAL-LEGACY-DOCS-001",
    "VAL-ENGINEERING-PACKAGE-001",
    "VAL-ELECTRON-CUTOVER-001",
    "VAL-LEGACY-ABSENCE-001",
    "VAL-RELEASE-CONTINUITY-001",
    "VAL-SECRET-001",
    "VAL-PACK-001",
    "VAL-INSTALL-001",
    "VAL-RELEASE-001",
    "VAL-UPDATE-001",
)
SHA40 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")


def canonical_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def integer_environment(environment: dict[str, str], name: str, errors: list[str]) -> int | None:
    value = environment.get(name, "")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        errors.append(f"{name} must be a positive integer")
        return None
    if parsed <= 0:
        errors.append(f"{name} must be a positive integer")
        return None
    return parsed


def lifecycle_phase(event: str, source_ref: str) -> str:
    if event == "pull_request":
        return "pull-request-candidate"
    if event == "push" and source_ref == "refs/heads/main":
        return "canonical-main-source"
    return "branch-candidate"


def validate_qmd_result(qmd: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(qmd, dict):
        return ["python job did not expose a QMD object"]
    expected_top_level = {
        "schema_version",
        "node_version",
        "command",
        "tests",
        "allowed_skip_reason",
        "network_trap",
        "network_policy",
        "model_scan",
        "result",
        "errors",
    }
    if set(qmd) != expected_top_level:
        errors.append("QMD result field set is incomplete or contains unknown fields")
    expected_values = {
        "schema_version": 2,
        "node_version": "22.23.2",
        "allowed_skip_reason": (
            "better-sqlite3 native binding is not built in source checkout"
        ),
        "network_trap": "active",
        "network_policy": "deny-external-allow-af-unix",
        "result": "pass",
        "errors": [],
    }
    for key, expected in expected_values.items():
        if qmd.get(key) != expected:
            errors.append(f"QMD result {key}={qmd.get(key)!r}, expected {expected!r}")
    if qmd.get("command") != (
        "node --import desktop/scripts/qmdNetworkTrap.mjs --test "
        "desktop/workers/qmd/test/*.test.mjs"
    ):
        errors.append("QMD result command is not the exact allowlisted source command")

    tests = qmd.get("tests")
    expected_test_keys = {"tests", "pass", "fail", "cancelled", "skipped", "todo"}
    if not isinstance(tests, dict) or set(tests) != expected_test_keys:
        errors.append("QMD test summary field set is incomplete or contains unknown fields")
        tests = {}
    if any(type(tests.get(key)) is not int for key in expected_test_keys):
        errors.append("QMD test summary values must be non-boolean integers")
    else:
        if tests["tests"] <= 0 or tests["pass"] <= 0:
            errors.append("QMD tests and pass count must be positive")
        if any(tests[key] < 0 for key in ("fail", "cancelled", "skipped", "todo")):
            errors.append("QMD fail/cancelled/skipped/todo counts must be non-negative")
        if tests["skipped"] != 1:
            errors.append("QMD result must retain exactly one allowlisted native skip")
        for key in ("fail", "cancelled", "todo"):
            if tests[key] != 0:
                errors.append(f"QMD result {key} must be zero")
        if tests["tests"] != tests["pass"] + tests["skipped"]:
            errors.append("QMD test total must equal pass + skipped")

    scan = qmd.get("model_scan")
    expected_scan_keys = {
        "scope",
        "repository_worktree_scanned",
        "global_tmp_scanned",
        "model_files_before",
        "model_files_after",
        "model_files_created",
        "model_file_paths_created",
        "model_cache_paths_before",
        "model_cache_paths_after",
        "model_cache_paths_created",
        "model_cache_path_names_created",
    }
    if not isinstance(scan, dict) or set(scan) != expected_scan_keys:
        errors.append("QMD model scan field set is incomplete or contains unknown fields")
        scan = {}
    if scan.get("scope") != MODEL_SCAN_SCOPE:
        errors.append("QMD model scan scope does not match the isolated runner roots")
    if scan.get("repository_worktree_scanned") is not False:
        errors.append("QMD model scan must truthfully record repository_worktree_scanned=false")
    if scan.get("global_tmp_scanned") is not False:
        errors.append("QMD model scan must truthfully record global_tmp_scanned=false")
    for key in (
        "model_files_before",
        "model_files_after",
        "model_files_created",
        "model_cache_paths_before",
        "model_cache_paths_after",
        "model_cache_paths_created",
    ):
        if type(scan.get(key)) is not int or scan[key] < 0:
            errors.append(
                f"QMD model scan {key} must be a non-boolean non-negative integer"
            )
    for key in ("model_file_paths_created", "model_cache_path_names_created"):
        if not isinstance(scan.get(key), list):
            errors.append(f"QMD model scan {key} must be a list")
    if scan.get("model_files_created") != 0 or scan.get("model_file_paths_created") != []:
        errors.append("QMD isolated roots contain a model-file delta")
    if (
        scan.get("model_cache_paths_created") != 0
        or scan.get("model_cache_path_names_created") != []
    ):
        errors.append("QMD isolated roots contain a model-cache-path delta")
    if isinstance(scan.get("model_files_before"), int) and isinstance(
        scan.get("model_files_after"), int
    ):
        if scan["model_files_after"] - scan["model_files_before"] != scan.get(
            "model_files_created"
        ):
            errors.append("QMD model-file before/after/created counts conflict")
    if isinstance(scan.get("model_cache_paths_before"), int) and isinstance(
        scan.get("model_cache_paths_after"), int
    ):
        if scan["model_cache_paths_after"] - scan["model_cache_paths_before"] != scan.get(
            "model_cache_paths_created"
        ):
            errors.append("QMD model-cache before/after/created counts conflict")
    return errors


def validate_tool_versions(
    tool_versions: dict[str, dict[str, str]], qmd_result: Any
) -> list[str]:
    errors: list[str] = []
    if set(tool_versions) != set(REQUIRED_OUTPUTS):
        errors.append("tool version job field set is incomplete or unknown")
    for job, required in REQUIRED_OUTPUTS.items():
        versions = tool_versions.get(job)
        if not isinstance(versions, dict) or set(versions) != set(required):
            errors.append(f"{job} tool version field set is incomplete or unknown")
    python_value = tool_versions.get("python", {})
    web_value = tool_versions.get("web", {})
    desktop_value = tool_versions.get("desktop", {})
    macos_value = tool_versions.get("macos-ipc", {})
    python = python_value if isinstance(python_value, dict) else {}
    web = web_value if isinstance(web_value, dict) else {}
    desktop = desktop_value if isinstance(desktop_value, dict) else {}
    macos = macos_value if isinstance(macos_value, dict) else {}
    qmd_node = python.get("qmd-node-version")
    if qmd_node != "v22.23.2":
        errors.append("QMD job tool output must record exact Node v22.23.2")
    if isinstance(qmd_result, dict) and qmd_node != f"v{qmd_result.get('node_version')}":
        errors.append("QMD job Node output conflicts with qmd_source.node_version")
    if python.get("npm-version") != "10.9.8":
        errors.append("QMD job npm output must match Node 22.23.2 npm 10.9.8")
    for label, value, pattern in (
        ("Python job Python", python.get("python-version"), r"Python 3\.12\.[0-9]+"),
        ("Python job uv", python.get("uv-version"), r"uv 0\.11\.29(?:\s.*)?"),
        ("Web Node", web.get("node-version"), r"v24\.[0-9]+\.[0-9]+"),
        ("Web npm", web.get("npm-version"), r"[0-9]+\.[0-9]+\.[0-9]+"),
        ("Desktop Node", desktop.get("node-version"), r"v24\.[0-9]+\.[0-9]+"),
        ("Desktop npm", desktop.get("npm-version"), r"[0-9]+\.[0-9]+\.[0-9]+"),
        ("macOS Python", macos.get("python-version"), r"Python 3\.12\.[0-9]+"),
        ("macOS uv", macos.get("uv-version"), r"uv 0\.11\.29(?:\s.*)?"),
    ):
        if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
            errors.append(f"{label} output conflicts with the workflow tool pin")
    if macos.get("architecture") != "arm64":
        errors.append("macOS IPC architecture output must be arm64")
    return errors


def build_report(
    manifest: dict[str, Any],
    needs: dict[str, Any],
    environment: dict[str, str],
    actual_head: str,
    actual_tree: str,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    aggregate = manifest["aggregate"]
    expected_head = environment.get("LCF_SOURCE_SHA", "")
    if SHA40.fullmatch(actual_head) is None:
        errors.append("checked-out HEAD must be a full lowercase commit SHA")
    if SHA40.fullmatch(actual_tree) is None:
        errors.append("checked-out tree must be a full lowercase tree SHA")
    if not expected_head or actual_head != expected_head:
        errors.append(
            f"checked-out HEAD {actual_head!r} does not match expected source {expected_head!r}"
        )

    job_results: dict[str, str] = {}
    tool_versions: dict[str, dict[str, str]] = {}
    for job in aggregate["required_jobs"]:
        job_data = needs.get(job)
        result = job_data.get("result") if isinstance(job_data, dict) else None
        job_results[job] = result or "missing"
        if result != "success":
            errors.append(f"required job {job} concluded {result or 'missing'}")
        outputs = job_data.get("outputs", {}) if isinstance(job_data, dict) else {}
        tool_versions[job] = {}
        for output_name in REQUIRED_OUTPUTS[job]:
            value = outputs.get(output_name) if isinstance(outputs, dict) else None
            tool_versions[job][output_name] = value or "missing"
            if not isinstance(value, str) or not value.strip():
                errors.append(f"required job {job} output {output_name} is missing")

    qmd_result: Any = {}
    python_data = needs.get("python")
    python_outputs = python_data.get("outputs", {}) if isinstance(python_data, dict) else {}
    serialized_qmd = python_outputs.get("qmd-result", "")
    try:
        qmd_result = json.loads(serialized_qmd)
    except (TypeError, json.JSONDecodeError):
        errors.append("python job did not expose valid qmd-result JSON")
    errors.extend(validate_qmd_result(qmd_result))
    errors.extend(validate_tool_versions(tool_versions, qmd_result))

    manifest_digest = environment.get("LCF_MANIFEST_SHA256", "")
    if SHA256.fullmatch(manifest_digest) is None:
        errors.append("coverage manifest digest must be a full lowercase SHA-256")

    event = environment.get("GITHUB_EVENT_NAME", "")
    source_ref = environment.get("GITHUB_REF", "")
    pull_request_number: int | None = None
    if event not in {"pull_request", "push", "workflow_dispatch"}:
        errors.append(f"unsupported workflow event {event!r}")
    if event in {"push", "workflow_dispatch"} and not source_ref.startswith("refs/heads/"):
        errors.append(f"{event} source ref must identify a branch")
    phase = lifecycle_phase(event, source_ref)
    github_context_sha = environment.get("GITHUB_SHA", "")
    workflow_sha = environment.get("GITHUB_WORKFLOW_SHA", "")
    for name, value in (
        ("github context SHA", github_context_sha),
        ("workflow SHA", workflow_sha),
    ):
        if SHA40.fullmatch(value) is None:
            errors.append(f"{name} must be a full lowercase SHA")
    if phase == "pull-request-candidate":
        if github_context_sha == actual_head:
            errors.append("PR synthetic context SHA must remain distinct from exact source")
        pull_request_match = re.fullmatch(r"refs/pull/([1-9][0-9]*)/merge", source_ref)
        if pull_request_match is None:
            errors.append("PR source ref must identify a numbered synthetic merge context")
        else:
            pull_request_number = int(pull_request_match.group(1))
        if workflow_sha != github_context_sha:
            errors.append("PR workflow SHA must equal the synthetic context SHA")
    elif github_context_sha != actual_head or workflow_sha != actual_head:
        errors.append("push/workflow-dispatch context and workflow SHA must equal exact source")

    if environment.get("GITHUB_REPOSITORY") != REPOSITORY:
        errors.append("workflow repository does not match the canonical repository")
    if environment.get("GITHUB_WORKFLOW") != "Desktop source CI":
        errors.append("workflow name does not match Desktop source CI")
    workflow_ref = environment.get("GITHUB_WORKFLOW_REF", "")
    if workflow_ref != f"{REPOSITORY}/{WORKFLOW_PATH}@{source_ref}":
        errors.append("workflow ref does not bind the expected workflow path and source ref")
    recorded_at = environment.get("LCF_RECORDED_AT", "")
    try:
        parsed_recorded_at = datetime.fromisoformat(recorded_at)
    except (TypeError, ValueError):
        parsed_recorded_at = None
    if parsed_recorded_at is None or parsed_recorded_at.tzinfo is None:
        errors.append("recorded_at must be an RFC3339 timestamp with timezone")

    run_id = integer_environment(environment, "GITHUB_RUN_ID", errors)
    run_attempt = integer_environment(environment, "GITHUB_RUN_ATTEMPT", errors)
    guide = next(
        component for component in manifest["components"] if component["id"] == "guide-site"
    )
    gate_result = "pass" if not errors else "fail"
    candidate_results = {gate: gate_result for gate in GATES}
    if phase == "canonical-main-source":
        technical_candidate_gate_results: dict[str, str] | None = None
        main_source_gate_results: dict[str, str] | None = candidate_results
        independent_acceptance = {
            "status": "not-observable-by-source-workflow",
            "external_reference": None,
        }
        canonical_activation = (
            {
                "status": "requires-external-conditions",
                "required_conditions": MAIN_ACTIVATION_CONDITIONS,
            }
            if gate_result == "pass"
            else {
                "status": "blocked",
                "required_conditions": FAILED_MAIN_ACTIVATION_CONDITIONS,
            }
        )
    else:
        technical_candidate_gate_results = candidate_results
        main_source_gate_results = None
        independent_acceptance = {"status": "pending", "external_reference": None}
        canonical_activation = {
            "status": "blocked",
            "required_conditions": PR_ACTIVATION_CONDITIONS,
        }

    report = {
        "schema_version": SCHEMA_VERSION,
        "repository": environment.get("GITHUB_REPOSITORY"),
        "work_id": "W01",
        "lifecycle_phase": phase,
        "source_commit": actual_head,
        "source_tree": actual_tree,
        "exact_checked_out_sha": actual_head,
        "github_context_sha": github_context_sha,
        "synthetic_context_sha": (
            github_context_sha if phase == "pull-request-candidate" else None
        ),
        "event": event,
        "source_ref": source_ref,
        "pull_request_number": pull_request_number,
        "source_branch": environment.get("GITHUB_HEAD_REF") or source_ref.removeprefix(
            "refs/heads/"
        ),
        "workflow_path": WORKFLOW_PATH,
        "workflow_name": environment.get("GITHUB_WORKFLOW"),
        "workflow_ref": workflow_ref,
        "workflow_sha": workflow_sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "run_url": (
            f"{environment.get('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{environment.get('GITHUB_REPOSITORY')}/actions/runs/{run_id}"
        ),
        "recorded_at": recorded_at,
        "manifest_sha256": manifest_digest,
        "payload_artifact_name": f"{PAYLOAD_ARTIFACT_PREFIX}{actual_head}",
        "required_jobs": aggregate["required_jobs"],
        "required_job_results": job_results,
        "tool_versions": tool_versions,
        "qmd_source": qmd_result,
        "guide_site": {
            "disposition": guide["disposition"],
            "included": guide["included"],
            "validated": guide["validated"],
            "reason": guide["reason"],
        },
        "technical_candidate_gate_results": technical_candidate_gate_results,
        "main_source_gate_results": main_source_gate_results,
        "independent_acceptance": independent_acceptance,
        "canonical_activation": canonical_activation,
        "downstream_gate_results": {gate: "not-run" for gate in DOWNSTREAM_GATES},
        "result": gate_result,
        "errors": errors,
    }
    return report, errors


def git_output(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    try:
        needs = json.loads(os.environ.get("NEEDS_JSON", ""))
    except json.JSONDecodeError:
        needs = {}
    actual_head = git_output("rev-parse", "HEAD")
    actual_tree = git_output("rev-parse", "HEAD^{tree}")
    environment = dict(os.environ)
    environment["LCF_MANIFEST_SHA256"] = canonical_digest(arguments.manifest)
    environment["LCF_RECORDED_AT"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    report, errors = build_report(
        manifest,
        needs,
        environment,
        actual_head,
        actual_tree,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"W01 exact-head source evidence written to {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Bind an uploaded W01 payload artifact without recursive self-hashing."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2
PAYLOAD_RENDERER_PATH = Path(__file__).with_name("render_source_coverage_evidence.py")
PAYLOAD_SPEC = importlib.util.spec_from_file_location(
    "w01_payload_renderer_for_provenance", PAYLOAD_RENDERER_PATH
)
assert PAYLOAD_SPEC is not None and PAYLOAD_SPEC.loader is not None
PAYLOAD_RENDERER = importlib.util.module_from_spec(PAYLOAD_SPEC)
PAYLOAD_SPEC.loader.exec_module(PAYLOAD_RENDERER)
REPOSITORY = "fredgnr/local-context-forge"
WORKFLOW_PATH = ".github/workflows/desktop-ci.yml"
PAYLOAD_PREFIX = "w01-source-coverage-"
PROVENANCE_PREFIX = "w01-source-coverage-provenance-"
LIFECYCLE_PHASES = {
    "pull-request-candidate",
    "branch-candidate",
    "canonical-main-source",
}
SHA40 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
PAYLOAD_FIELDS = {
    "schema_version",
    "repository",
    "work_id",
    "lifecycle_phase",
    "source_commit",
    "source_tree",
    "exact_checked_out_sha",
    "github_context_sha",
    "synthetic_context_sha",
    "event",
    "source_ref",
    "pull_request_number",
    "source_branch",
    "workflow_path",
    "workflow_name",
    "workflow_ref",
    "workflow_sha",
    "run_id",
    "run_attempt",
    "run_url",
    "recorded_at",
    "manifest_sha256",
    "payload_artifact_name",
    "required_jobs",
    "required_job_results",
    "tool_versions",
    "qmd_source",
    "guide_site",
    "technical_candidate_gate_results",
    "main_source_gate_results",
    "independent_acceptance",
    "canonical_activation",
    "downstream_gate_results",
    "result",
    "errors",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def positive_integer(value: str, label: str, errors: list[str]) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        errors.append(f"{label} must be a positive integer")
        return None
    if parsed <= 0:
        errors.append(f"{label} must be a positive integer")
        return None
    return parsed


def validate_gate_results(value: Any, expected: str, label: str, errors: list[str]) -> None:
    if not isinstance(value, dict) or set(value) != set(PAYLOAD_RENDERER.GATES):
        errors.append(f"payload {label} field set is incomplete or unknown")
    elif any(result != expected for result in value.values()):
        errors.append(f"payload {label} must record every W01 gate as {expected}")


def validate_payload_schema(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["payload must be an object"]
    if set(payload) != PAYLOAD_FIELDS:
        errors.append("payload field set is incomplete or contains unknown fields")

    source_commit = payload.get("source_commit")
    source_tree = payload.get("source_tree")
    phase = payload.get("lifecycle_phase")
    event = payload.get("event")
    source_ref = payload.get("source_ref")
    pull_request_number = payload.get("pull_request_number")
    github_context_sha = payload.get("github_context_sha")
    synthetic_context_sha = payload.get("synthetic_context_sha")
    workflow_sha = payload.get("workflow_sha")
    result = payload.get("result")
    payload_errors = payload.get("errors")

    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append("payload schema version must be 2")
    if payload.get("repository") != REPOSITORY or payload.get("work_id") != "W01":
        errors.append("payload repository/work identity is wrong")
    if not isinstance(source_commit, str) or SHA40.fullmatch(source_commit) is None:
        errors.append("payload source commit must be a full lowercase SHA")
    if not isinstance(source_tree, str) or SHA40.fullmatch(source_tree) is None:
        errors.append("payload source tree must be a full lowercase SHA")
    if payload.get("exact_checked_out_sha") != source_commit:
        errors.append("payload exact checked-out SHA conflicts with its source commit")
    for label, value in (
        ("github context SHA", github_context_sha),
        ("workflow SHA", workflow_sha),
    ):
        if not isinstance(value, str) or SHA40.fullmatch(value) is None:
            errors.append(f"payload {label} must be a full lowercase SHA")
    if phase not in LIFECYCLE_PHASES:
        errors.append("payload lifecycle phase is unknown")
    if phase == "pull-request-candidate":
        if event != "pull_request":
            errors.append("pull-request payload event must be pull_request")
        if type(pull_request_number) is not int or pull_request_number <= 0:
            errors.append("pull-request number must be a positive non-boolean integer")
        elif source_ref != f"refs/pull/{pull_request_number}/merge":
            errors.append("pull-request number and source ref conflict")
        if synthetic_context_sha != github_context_sha or github_context_sha == source_commit:
            errors.append("pull-request payload synthetic context is invalid")
        if workflow_sha != github_context_sha:
            errors.append("pull-request workflow SHA must equal synthetic context SHA")
    elif phase == "branch-candidate":
        if pull_request_number is not None:
            errors.append("branch-candidate payload cannot record a pull-request number")
        if event not in {"push", "workflow_dispatch"}:
            errors.append("branch-candidate payload event is invalid")
        if not isinstance(source_ref, str) or not source_ref.startswith("refs/heads/"):
            errors.append("branch-candidate payload ref is invalid")
        if synthetic_context_sha is not None:
            errors.append("branch-candidate payload cannot record a synthetic context")
        if github_context_sha != source_commit or workflow_sha != source_commit:
            errors.append("branch-candidate context/workflow SHA must equal source commit")
    elif phase == "canonical-main-source":
        if pull_request_number is not None:
            errors.append("canonical-main payload cannot record a pull-request number")
        if event != "push" or source_ref != "refs/heads/main":
            errors.append("canonical-main payload must be a push to refs/heads/main")
        if synthetic_context_sha is not None:
            errors.append("canonical-main payload cannot record a synthetic context")
        if github_context_sha != source_commit or workflow_sha != source_commit:
            errors.append("canonical-main context/workflow SHA must equal source commit")

    if payload.get("workflow_path") != WORKFLOW_PATH:
        errors.append("payload workflow path is wrong")
    if payload.get("workflow_name") != "Desktop source CI":
        errors.append("payload workflow name is wrong")
    workflow_ref = payload.get("workflow_ref")
    if workflow_ref != f"{REPOSITORY}/{WORKFLOW_PATH}@{source_ref}":
        errors.append("payload workflow ref conflicts with workflow path/source ref")
    run_id = payload.get("run_id")
    run_attempt = payload.get("run_attempt")
    if type(run_id) is not int or run_id <= 0:
        errors.append("payload run ID must be a positive non-boolean integer")
    if type(run_attempt) is not int or run_attempt <= 0:
        errors.append("payload run attempt must be a positive non-boolean integer")
    if payload.get("run_url") != f"https://github.com/{REPOSITORY}/actions/runs/{run_id}":
        errors.append("payload run ID and URL conflict")
    recorded_at = payload.get("recorded_at")
    try:
        parsed_recorded_at = datetime.fromisoformat(recorded_at)
    except (TypeError, ValueError):
        parsed_recorded_at = None
    if parsed_recorded_at is None or parsed_recorded_at.tzinfo is None:
        errors.append("payload recorded_at must be an RFC3339 timestamp with timezone")
    if not isinstance(payload.get("source_branch"), str) or not payload["source_branch"]:
        errors.append("payload source branch must be a non-empty string")
    if not isinstance(payload.get("manifest_sha256"), str) or SHA256.fullmatch(
        payload["manifest_sha256"]
    ) is None:
        errors.append("payload manifest digest must be a full lowercase SHA-256")
    if payload.get("payload_artifact_name") != f"{PAYLOAD_PREFIX}{source_commit}":
        errors.append("payload artifact name is not source-commit-bound")

    if payload.get("required_jobs") != list(PAYLOAD_RENDERER.REQUIRED_OUTPUTS):
        errors.append("payload required job list drifted")
    job_results = payload.get("required_job_results")
    if not isinstance(job_results, dict) or set(job_results) != set(
        PAYLOAD_RENDERER.REQUIRED_OUTPUTS
    ):
        errors.append("payload required job result field set drifted")
    elif any(
        value not in {"success", "failure", "cancelled", "skipped", "missing"}
        for value in job_results.values()
    ):
        errors.append("payload required job result contains an unknown state")

    tool_versions = payload.get("tool_versions")
    if not isinstance(tool_versions, dict):
        errors.append("payload tool versions must be an object")
    else:
        errors.extend(PAYLOAD_RENDERER.validate_tool_versions(tool_versions, payload.get("qmd_source")))
    errors.extend(PAYLOAD_RENDERER.validate_qmd_result(payload.get("qmd_source")))

    if result not in {"pass", "fail"}:
        errors.append("payload result must be pass or fail")
    if not isinstance(payload_errors, list) or any(
        not isinstance(item, str) or not item for item in payload_errors
    ):
        errors.append("payload errors must be an array of non-empty strings")
    elif (result == "pass") != (payload_errors == []):
        errors.append("payload result and errors conflict")
    if isinstance(job_results, dict) and result == "pass" and any(
        value != "success" for value in job_results.values()
    ):
        errors.append("passing payload requires every required job to succeed")

    technical = payload.get("technical_candidate_gate_results")
    main = payload.get("main_source_gate_results")
    independent = payload.get("independent_acceptance")
    activation = payload.get("canonical_activation")
    if phase == "canonical-main-source":
        if technical is not None:
            errors.append("canonical-main payload cannot contain candidate gate results")
        validate_gate_results(main, result, "main source gates", errors)
        if independent != {
            "status": "not-observable-by-source-workflow",
            "external_reference": None,
        }:
            errors.append("canonical-main payload independent acceptance is invalid")
        expected_activation = (
            {
                "status": "requires-external-conditions",
                "required_conditions": PAYLOAD_RENDERER.MAIN_ACTIVATION_CONDITIONS,
            }
            if result == "pass"
            else {
                "status": "blocked",
                "required_conditions": PAYLOAD_RENDERER.FAILED_MAIN_ACTIVATION_CONDITIONS,
            }
        )
    else:
        validate_gate_results(technical, result, "technical candidate gates", errors)
        if main is not None:
            errors.append("candidate payload cannot contain main source gate results")
        if independent != {"status": "pending", "external_reference": None}:
            errors.append("candidate payload independent acceptance must remain pending")
        expected_activation = {
            "status": "blocked",
            "required_conditions": PAYLOAD_RENDERER.PR_ACTIVATION_CONDITIONS,
        }
    if activation != expected_activation:
        errors.append("payload canonical activation conflicts with lifecycle/result")

    guide = payload.get("guide_site")
    if not isinstance(guide, dict) or set(guide) != {
        "disposition",
        "included",
        "validated",
        "reason",
    }:
        errors.append("payload guide-site field set drifted")
    elif (
        guide.get("disposition") != "external-blocked"
        or guide.get("included") is not False
        or guide.get("validated") is not False
        or not isinstance(guide.get("reason"), str)
        or not guide["reason"]
    ):
        errors.append("payload guide-site disposition is untruthful")
    downstream = payload.get("downstream_gate_results")
    if not isinstance(downstream, dict) or set(downstream) != set(
        PAYLOAD_RENDERER.DOWNSTREAM_GATES
    ):
        errors.append("payload downstream gate field set drifted")
    elif any(value != "not-run" for value in downstream.values()):
        errors.append("payload downstream gates must remain not-run")
    return errors


def build_provenance(
    payload: dict[str, Any],
    payload_path: Path,
    environment: dict[str, str],
) -> tuple[dict[str, Any], list[str]]:
    errors = validate_payload_schema(payload)
    source_commit = payload.get("source_commit")
    source_tree = payload.get("source_tree")
    lifecycle_phase = payload.get("lifecycle_phase")
    run_id = payload.get("run_id")
    run_attempt = payload.get("run_attempt")
    artifact_id = positive_integer(
        environment.get("LCF_PAYLOAD_ARTIFACT_ID", ""),
        "payload artifact ID",
        errors,
    )
    artifact_name = environment.get("LCF_PAYLOAD_ARTIFACT_NAME", "")
    artifact_url = environment.get("LCF_PAYLOAD_ARTIFACT_URL", "")
    archive_digest = environment.get("LCF_PAYLOAD_ARTIFACT_DIGEST", "")

    if payload.get("payload_artifact_name") != artifact_name:
        errors.append("payload artifact name conflicts with the upload output")
    if isinstance(source_commit, str) and artifact_name != f"{PAYLOAD_PREFIX}{source_commit}":
        errors.append("payload artifact name is not source-commit-bound")
    if SHA256.fullmatch(archive_digest) is None:
        errors.append("payload artifact archive digest must be a full lowercase SHA-256")
    expected_artifact_url = (
        f"https://github.com/{REPOSITORY}/actions/runs/{run_id}/artifacts/{artifact_id}"
        if isinstance(run_id, int) and isinstance(artifact_id, int)
        else None
    )
    if artifact_url != expected_artifact_url:
        errors.append("payload artifact URL conflicts with repository/run/artifact ID")
    activation = payload.get("canonical_activation")
    activation_status = activation.get("status") if isinstance(activation, dict) else None
    expected_activation = (
        "requires-external-conditions"
        if lifecycle_phase == "canonical-main-source" and payload.get("result") == "pass"
        else "blocked"
    )
    if activation_status != expected_activation:
        errors.append("payload canonical activation conflicts with its lifecycle phase")

    payload_sha256 = digest(payload_path)
    provenance_name = (
        f"{PROVENANCE_PREFIX}{source_commit}" if isinstance(source_commit, str) else "invalid"
    )
    provenance = {
        "schema_version": SCHEMA_VERSION,
        "repository": REPOSITORY,
        "work_id": "W01",
        "lifecycle_phase": lifecycle_phase,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "event": payload.get("event"),
        "source_ref": payload.get("source_ref"),
        "workflow_path": payload.get("workflow_path"),
        "run_id": run_id,
        "run_attempt": run_attempt,
        "payload_artifact": {
            "id": artifact_id,
            "name": artifact_name,
            "url": artifact_url,
            "archive_sha256": archive_digest,
        },
        "payload": {
            "file_name": payload_path.name,
            "sha256": payload_sha256,
            "result": payload.get("result"),
        },
        "provenance_artifact_name": provenance_name,
        "canonical_activation_status": activation_status,
        "result": "pass" if not errors else "fail",
        "errors": errors,
        "recorded_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    return provenance, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        payload = json.loads(arguments.payload.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"ERROR: cannot read payload: {error}")
        return 1
    provenance, errors = build_provenance(payload, arguments.payload, dict(os.environ))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"W01 payload provenance written to {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

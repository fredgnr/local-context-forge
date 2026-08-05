#!/usr/bin/env python3
"""Validate immutable W01 history without coupling it to the current Git HEAD."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "development" / "evidence" / "W01" / "2026-08-04.json"
SCHEMA = ROOT / "docs" / "development" / "evidence" / "W01" / "schema-v2.json"
REPOSITORY = "fredgnr/local-context-forge"
WORKFLOW_PATH = ".github/workflows/desktop-ci.yml"
SCHEMA_OBJECT_SHA256 = "064952f183fb8024edab629e572b1d8d72c1c3cda8d0d161353a81b2755b85f5"
BASELINE = {
    "commit": "3eff97d97b2de4484d568bab5ac96d63830c79ee",
    "tree": "21fe2cbe46d42bf351d2b0c84019ee63959081b7",
}
GATES = (
    "VAL-PRE1-SEQUENCE-001",
    "VAL-GOV-001",
    "VAL-CI-COVERAGE-001",
)
REQUIRED_JOBS = ("python", "web", "desktop", "macos-ipc")
JOB_RESULTS = (*REQUIRED_JOBS, "source-coverage")
REQUIRED_OUTPUTS = {
    "python": {"python-version", "qmd-node-version", "npm-version", "uv-version"},
    "web": {"node-version", "npm-version"},
    "desktop": {"node-version", "npm-version"},
    "macos-ipc": {"architecture", "python-version", "uv-version"},
}
MODEL_SCAN_SCOPE = [
    "isolated HOME",
    "isolated XDG_CACHE_HOME",
    "isolated XDG_CONFIG_HOME",
    "isolated XDG_DATA_HOME",
    "isolated TMPDIR",
]
ACTIVATION_CONDITIONS = [
    "independent acceptance of the exact final PR head",
    "merge of that accepted candidate into canonical main",
    "successful source-coverage on the exact resulting main commit",
]
REJECTION_IDS = [
    "W01-EVIDENCE-FUTURE-DESCENDANT-FREEZE",
    "W01-EVIDENCE-MERGE-STRATEGY-INCOMPATIBLE",
    "W01-ARTIFACT-PREMATURE-CANONICAL-PASS",
]
OUT_OF_SCOPE = [
    "W02 packaged smoke",
    "Legacy deletion",
    "engineering test package",
    "GitHub production control plane",
    "production credentials, signing, tags, Drafts, Releases, and updates",
]
FINAL_BINDING = {
    "mode": "attached-exact-head-payload-and-provenance",
    "workflow_path": WORKFLOW_PATH,
    "workflow_name": "Desktop source CI",
    "events": ["push", "pull_request", "workflow_dispatch"],
    "source_expression": "${{ github.event.pull_request.head.sha || github.sha }}",
    "required_jobs": list(REQUIRED_JOBS),
    "summary_job": "source-coverage",
    "payload_artifact_prefix": "w01-source-coverage-",
    "provenance_artifact_prefix": "w01-source-coverage-provenance-",
}
DOWNSTREAM_GATES = {
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
}
SHA40 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
OLD_CANDIDATE = {
    "source_commit": "2b7629468c711d0db5107f7001aa90c0271079ae",
    "source_tree": "ad1b76febd1adcaf1ada96ed7dd43fbe1e5a3adf",
}
OLD_EXECUTIONS = {
    "implementation_checkpoint": {
        "source_commit": "8573f608df589bc2ef9e05f0c75d84887464c825",
        "source_tree": "40c039f240cdd8c6e0589c8608260c3d45c6ebaa",
        "run_id": 30927840380,
        "synthetic_context_sha": "29e2498e666cfeebf162aa6bb726954e42d109ea",
        "artifact_id": 8899870692,
        "archive_sha256": "9dc17f1163f9b111aff8b7ae603574d6c22f552e269e1cac299754c23051a91a",
        "inner_json_sha256": "e1a9b65e44b8258d8529c7018d64e3865b8135dc4677e9b9e6904484cb8bc6e7",
        "legacy_canonical": "not-run",
        "record_sha256": "cfcc8c31de3a9ee7cbfdcd1357abe526923bd730ab90f945998435d53fa69405",
    },
    "final_source_execution": {
        "source_commit": OLD_CANDIDATE["source_commit"],
        "source_tree": OLD_CANDIDATE["source_tree"],
        "run_id": 30929070329,
        "synthetic_context_sha": "cb844bfb5502f948bf55a227300a12761427195e",
        "artifact_id": 8900365901,
        "archive_sha256": "b446ef4e84eb60dfd3da5322c85737d8dab960a349933a565fd5bd7ed3965e4d",
        "inner_json_sha256": "4d0deeb7fc6886e03c671e0df2dbc80b03586c6222a38ad27549a0a3f42c403d",
        "legacy_canonical": "pass",
        "record_sha256": "35ea3fd59daf0964366067c7306b2c6764632e221eff1c2c65c1ebb53f6f968d",
    },
}


def exact_keys(value: Any, expected: set[str], label: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return False
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        errors.append(f"{label} fields differ; missing={missing}, unknown={unknown}")
        return False
    return True


def full_sha(value: Any, label: str, errors: list[str]) -> bool:
    if not isinstance(value, str) or SHA40.fullmatch(value) is None:
        errors.append(f"{label} must be a full lowercase 40-hex SHA")
        return False
    return True


def full_digest(value: Any, label: str, errors: list[str]) -> bool:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        errors.append(f"{label} must be a full lowercase 64-hex SHA-256")
        return False
    return True


def positive_integer(value: Any, label: str, errors: list[str]) -> bool:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        errors.append(f"{label} must be a positive integer")
        return False
    return True


def validate_gate_results(
    value: Any, expected: str, label: str, errors: list[str]
) -> None:
    if not exact_keys(value, set(GATES), label, errors):
        return
    if any(result != expected for result in value.values()):
        errors.append(f"{label} must record every W01 gate as {expected}")


def validate_run(
    run: Any,
    source_commit: str,
    lifecycle_phase: str,
    label: str,
    errors: list[str],
) -> None:
    expected_keys = {
        "id",
        "attempt",
        "event",
        "source_ref",
        "exact_checked_out_sha",
        "synthetic_context_sha",
        "workflow_path",
        "workflow_sha",
        "url",
        "conclusion",
        "job_results",
    }
    if not exact_keys(run, expected_keys, f"{label} run", errors):
        return
    positive_integer(run["id"], f"{label} run ID", errors)
    positive_integer(run["attempt"], f"{label} run attempt", errors)
    if run["exact_checked_out_sha"] != source_commit:
        errors.append(f"{label} exact checked-out SHA conflicts with source commit")
    if run["workflow_path"] != WORKFLOW_PATH:
        errors.append(f"{label} workflow path drifted")
    full_sha(run["workflow_sha"], f"{label} workflow SHA", errors)
    event = run["event"]
    source_ref = run["source_ref"]
    synthetic = run["synthetic_context_sha"]
    if event == "pull_request":
        if lifecycle_phase != "pull-request-candidate":
            errors.append(f"{label} PR event conflicts with lifecycle phase")
        if source_ref != "refs/pull/20/merge":
            errors.append(f"{label} PR source ref must bind PR #20")
        if not full_sha(synthetic, f"{label} synthetic context SHA", errors):
            pass
        elif synthetic == source_commit:
            errors.append(f"{label} PR synthetic SHA must differ from exact source")
        if run["workflow_sha"] != synthetic:
            errors.append(f"{label} PR workflow SHA must equal synthetic context SHA")
    elif event in {"push", "workflow_dispatch"}:
        if lifecycle_phase != "branch-candidate":
            errors.append(f"{label} branch event conflicts with lifecycle phase")
        if source_ref != "refs/heads/agent/w01-governance-source-ci":
            errors.append(f"{label} branch source ref must bind the W01 branch")
        if synthetic is not None:
            errors.append(f"{label} branch execution cannot record a synthetic SHA")
        if run["workflow_sha"] != source_commit:
            errors.append(f"{label} branch workflow SHA must equal exact source")
    else:
        errors.append(f"{label} run event is unknown")
    expected_url = f"https://github.com/{REPOSITORY}/actions/runs/{run['id']}"
    if run["url"] != expected_url:
        errors.append(f"{label} run ID and URL conflict")
    if run["conclusion"] != "success":
        errors.append(f"{label} run conclusion must be success")
    job_results = run["job_results"]
    if exact_keys(job_results, set(JOB_RESULTS), f"{label} job results", errors):
        if any(result != "success" for result in job_results.values()):
            errors.append(f"{label} required and summary jobs must all succeed")


def validate_payload_artifact(
    artifact: Any,
    source_commit: str,
    run_id: int,
    label: str,
    errors: list[str],
) -> int | None:
    keys = {
        "id",
        "name",
        "source_commit",
        "run_id",
        "archive_sha256",
        "inner_json_sha256",
        "payload_schema_version",
    }
    if not exact_keys(artifact, keys, f"{label} payload artifact", errors):
        return None
    positive_integer(artifact["id"], f"{label} payload artifact ID", errors)
    if artifact["source_commit"] != source_commit:
        errors.append(f"{label} payload artifact source commit conflicts")
    if artifact["run_id"] != run_id:
        errors.append(f"{label} payload artifact run ID conflicts")
    if artifact["name"] != f"w01-source-coverage-{source_commit}":
        errors.append(f"{label} payload artifact name/source conflict")
    full_digest(artifact["archive_sha256"], f"{label} payload archive digest", errors)
    full_digest(artifact["inner_json_sha256"], f"{label} payload inner digest", errors)
    if artifact["payload_schema_version"] not in {1, 2}:
        errors.append(f"{label} payload schema version is unsupported")
    return artifact["payload_schema_version"]


def validate_provenance_artifact(
    provenance: Any,
    payload: dict[str, Any],
    source_commit: str,
    run_id: int,
    label: str,
    errors: list[str],
) -> None:
    keys = {
        "id",
        "name",
        "source_commit",
        "run_id",
        "archive_sha256",
        "inner_json_sha256",
        "payload_binding",
    }
    if not exact_keys(provenance, keys, f"{label} provenance artifact", errors):
        return
    positive_integer(provenance["id"], f"{label} provenance artifact ID", errors)
    if provenance["source_commit"] != source_commit:
        errors.append(f"{label} provenance artifact source commit conflicts")
    if provenance["run_id"] != run_id:
        errors.append(f"{label} provenance artifact run ID conflicts")
    if provenance["name"] != f"w01-source-coverage-provenance-{source_commit}":
        errors.append(f"{label} provenance artifact name/source conflict")
    full_digest(provenance["archive_sha256"], f"{label} provenance archive digest", errors)
    full_digest(provenance["inner_json_sha256"], f"{label} provenance inner digest", errors)
    binding = provenance["payload_binding"]
    binding_keys = {
        "artifact_id",
        "artifact_name",
        "archive_sha256",
        "inner_json_sha256",
    }
    if exact_keys(binding, binding_keys, f"{label} provenance payload binding", errors):
        expected = {
            "artifact_id": payload["id"],
            "artifact_name": payload["name"],
            "archive_sha256": payload["archive_sha256"],
            "inner_json_sha256": payload["inner_json_sha256"],
        }
        if binding != expected:
            errors.append(f"{label} provenance binding conflicts with payload artifact")


def validate_tool_versions(value: Any, label: str, errors: list[str]) -> None:
    if not exact_keys(value, set(REQUIRED_OUTPUTS), f"{label} tool versions", errors):
        return
    for job, expected_keys in REQUIRED_OUTPUTS.items():
        versions = value[job]
        if not exact_keys(versions, expected_keys, f"{label} {job} versions", errors):
            continue
        if any(not isinstance(item, str) or not item.strip() for item in versions.values()):
            errors.append(f"{label} {job} tool versions must be non-empty strings")
    if not isinstance(value, dict):
        return
    python = value.get("python", {})
    web = value.get("web", {})
    desktop = value.get("desktop", {})
    macos = value.get("macos-ipc", {})
    if not all(isinstance(item, dict) for item in (python, web, desktop, macos)):
        return
    if python.get("qmd-node-version") != "v22.23.2":
        errors.append(f"{label} QMD Node version must be exact v22.23.2")
    if python.get("npm-version") != "10.9.8":
        errors.append(f"{label} QMD npm version must be exact 10.9.8")
    for version_label, version, pattern in (
        ("Python job Python", python.get("python-version"), r"Python 3\.12\.[0-9]+"),
        ("Python job uv", python.get("uv-version"), r"uv 0\.11\.29(?:\s.*)?"),
        ("Web Node", web.get("node-version"), r"v24\.[0-9]+\.[0-9]+"),
        ("Web npm", web.get("npm-version"), r"[0-9]+\.[0-9]+\.[0-9]+"),
        ("Desktop Node", desktop.get("node-version"), r"v24\.[0-9]+\.[0-9]+"),
        ("Desktop npm", desktop.get("npm-version"), r"[0-9]+\.[0-9]+\.[0-9]+"),
        ("macOS Python", macos.get("python-version"), r"Python 3\.12\.[0-9]+"),
        ("macOS uv", macos.get("uv-version"), r"uv 0\.11\.29(?:\s.*)?"),
    ):
        if not isinstance(version, str) or re.fullmatch(pattern, version) is None:
            errors.append(f"{label} {version_label} conflicts with the workflow pin")
    if macos.get("architecture") != "arm64":
        errors.append(f"{label} macOS IPC architecture must be arm64")


def validate_qmd(value: Any, label: str, errors: list[str]) -> None:
    keys = {
        "tests",
        "allowed_skip_reason",
        "network_trap",
        "network_policy",
        "model_scan",
    }
    if not exact_keys(value, keys, f"{label} QMD source", errors):
        return
    tests = value["tests"]
    test_keys = {"tests", "pass", "fail", "cancelled", "skipped", "todo"}
    if exact_keys(tests, test_keys, f"{label} QMD tests", errors):
        if any(type(tests[key]) is not int for key in test_keys):
            errors.append(f"{label} QMD test counts must be non-boolean integers")
        else:
            if tests["tests"] <= 0 or tests["pass"] <= 0:
                errors.append(f"{label} QMD tests and pass count must be positive")
            if any(tests[key] < 0 for key in ("fail", "cancelled", "skipped", "todo")):
                errors.append(f"{label} QMD summary counts cannot be negative")
            if tests["tests"] != tests["pass"] + tests["skipped"]:
                errors.append(f"{label} QMD tests must equal pass + skipped")
            if tests["skipped"] != 1:
                errors.append(f"{label} QMD skipped count must be exactly one")
            for key in ("fail", "cancelled", "todo"):
                if tests[key] != 0:
                    errors.append(f"{label} QMD {key} count must be zero")
    if value["allowed_skip_reason"] != (
        "better-sqlite3 native binding is not built in source checkout"
    ):
        errors.append(f"{label} QMD allowlisted skip reason drifted")
    if value["network_trap"] != "active":
        errors.append(f"{label} QMD network trap must be active")
    if value["network_policy"] != "deny-external-allow-af-unix":
        errors.append(f"{label} QMD network policy drifted")
    scan = value["model_scan"]
    scan_keys = {
        "scope",
        "repository_worktree_scanned",
        "global_tmp_scanned",
        "model_files_created",
        "model_cache_paths_created",
        "scope_basis",
    }
    if exact_keys(scan, scan_keys, f"{label} QMD model scan", errors):
        if scan["scope"] != MODEL_SCAN_SCOPE:
            errors.append(f"{label} QMD model scan scope drifted")
        if scan["repository_worktree_scanned"] is not False:
            errors.append(f"{label} QMD repository scan scope is untruthful")
        if scan["global_tmp_scanned"] is not False:
            errors.append(f"{label} QMD global tmp scan scope is untruthful")
        if type(scan["model_files_created"]) is not int or scan["model_files_created"] != 0:
            errors.append(f"{label} QMD model-file delta must be zero")
        if (
            type(scan["model_cache_paths_created"]) is not int
            or scan["model_cache_paths_created"] != 0
        ):
            errors.append(f"{label} QMD model-cache delta must be zero")
        if not isinstance(scan["scope_basis"], str) or not scan["scope_basis"]:
            errors.append(f"{label} QMD model scan scope basis is missing")


def validate_execution(
    value: Any,
    label: str,
    errors: list[str],
    *,
    require_provenance: bool,
) -> None:
    keys = {
        "source_commit",
        "source_tree",
        "lifecycle_phase",
        "run",
        "payload_artifact",
        "provenance_artifact",
        "provenance_absence_reason",
        "technical_gate_results",
        "legacy_payload_canonical_gate_results",
        "tool_versions",
        "qmd_source",
        "guide_site",
    }
    if not exact_keys(value, keys, label, errors):
        return
    source_commit = value["source_commit"]
    full_sha(source_commit, f"{label} source commit", errors)
    full_sha(value["source_tree"], f"{label} source tree", errors)
    lifecycle_phase = value["lifecycle_phase"]
    if lifecycle_phase not in {"pull-request-candidate", "branch-candidate"}:
        errors.append(f"{label} lifecycle phase is unknown")
    validate_run(value["run"], source_commit, lifecycle_phase, label, errors)
    run_id = value["run"].get("id") if isinstance(value["run"], dict) else None
    payload_schema = validate_payload_artifact(
        value["payload_artifact"], source_commit, run_id, label, errors
    )
    if require_provenance:
        if payload_schema != 2:
            errors.append(f"{label} remediation payload must use schema version 2")
        if value["provenance_absence_reason"] is not None:
            errors.append(f"{label} cannot claim provenance is absent")
        required_payload_binding_fields = {
            "id",
            "name",
            "archive_sha256",
            "inner_json_sha256",
        }
        if isinstance(value["payload_artifact"], dict) and required_payload_binding_fields.issubset(
            value["payload_artifact"]
        ):
            validate_provenance_artifact(
                value["provenance_artifact"],
                value["payload_artifact"],
                source_commit,
                run_id,
                label,
                errors,
            )
    else:
        if value["provenance_artifact"] is not None:
            errors.append(f"{label} historical v1 execution must not invent provenance")
        if value["provenance_absence_reason"] != "pre-v2 single-artifact lifecycle":
            errors.append(f"{label} historical provenance absence reason drifted")
        if payload_schema != 1:
            errors.append(f"{label} historical payload schema version drifted")
    validate_gate_results(value["technical_gate_results"], "pass", f"{label} technical gates", errors)
    legacy = value["legacy_payload_canonical_gate_results"]
    if require_provenance:
        if legacy is not None:
            errors.append(f"{label} v2 execution cannot contain legacy canonical gate results")
    else:
        if not isinstance(legacy, dict):
            errors.append(f"{label} must preserve the historical v1 canonical output")
        elif set(legacy) != set(GATES):
            errors.append(f"{label} historical canonical gate set drifted")
    validate_tool_versions(value["tool_versions"], label, errors)
    validate_qmd(value["qmd_source"], label, errors)
    guide = value["guide_site"]
    if exact_keys(guide, {"disposition", "included", "validated"}, f"{label} guide-site", errors):
        if guide != {
            "disposition": "external-blocked",
            "included": False,
            "validated": False,
        }:
            errors.append(f"{label} guide-site disposition must remain external-blocked")


def canonical_object_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_old_history(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list) or len(value) != 1:
        errors.append("W01 candidate history must preserve exactly the original rejected candidate")
        return
    candidate = value[0]
    keys = {
        "candidate_id",
        "source_commit",
        "source_tree",
        "technical_source_result",
        "independent_acceptance",
        "canonical_activation",
        "rejection_reason_ids",
        "implementation_checkpoint",
        "final_source_execution",
    }
    if not exact_keys(candidate, keys, "old rejected candidate", errors):
        return
    expected_metadata = {
        "candidate_id": "W01-original-rejected-final",
        **OLD_CANDIDATE,
        "technical_source_result": "pass",
        "independent_acceptance": "fail",
    }
    for key, expected in expected_metadata.items():
        if candidate[key] != expected:
            errors.append(f"old rejected candidate {key} drifted from immutable history")
    activation = candidate["canonical_activation"]
    if not exact_keys(
        activation, {"status", "required_conditions"}, "old candidate activation", errors
    ):
        pass
    else:
        if activation["status"] != "not-eligible":
            errors.append("old rejected candidate cannot be changed to accepted/eligible")
        if activation["required_conditions"] != ACTIVATION_CONDITIONS:
            errors.append("old rejected candidate activation conditions drifted")
    if candidate["rejection_reason_ids"] != REJECTION_IDS:
        errors.append("old rejected candidate rejection reasons drifted")

    for name, expected in OLD_EXECUTIONS.items():
        execution = candidate[name]
        validate_execution(execution, f"old {name}", errors, require_provenance=False)
        if not isinstance(execution, dict):
            continue
        if canonical_object_digest(execution) != expected["record_sha256"]:
            errors.append(f"old {name} immutable normalized record digest drifted")
        comparisons = {
            "source_commit": execution.get("source_commit"),
            "source_tree": execution.get("source_tree"),
            "run_id": execution.get("run", {}).get("id"),
            "synthetic_context_sha": execution.get("run", {}).get("synthetic_context_sha"),
            "artifact_id": execution.get("payload_artifact", {}).get("id"),
            "archive_sha256": execution.get("payload_artifact", {}).get("archive_sha256"),
            "inner_json_sha256": execution.get("payload_artifact", {}).get(
                "inner_json_sha256"
            ),
        }
        for key, actual in comparisons.items():
            if actual != expected[key]:
                errors.append(f"old {name} immutable {key} drifted")
        legacy = execution.get("legacy_payload_canonical_gate_results", {})
        if any(result != expected["legacy_canonical"] for result in legacy.values()):
            errors.append(f"old {name} historical canonical output drifted")
    final_execution = candidate["final_source_execution"]
    if final_execution.get("source_commit") != candidate["source_commit"]:
        errors.append("old candidate and final execution source commits conflict")
    if final_execution.get("source_tree") != candidate["source_tree"]:
        errors.append("old candidate and final execution source trees conflict")


def validate_schema_document(schema: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, dict):
        return ["W01 schema-v2.json must be an object"]
    if canonical_object_digest(schema) != SCHEMA_OBJECT_SHA256:
        errors.append("W01 schema v2 immutable contract digest drifted")
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        errors.append("W01 schema must be a closed top-level object")
    properties = schema.get("properties", {})
    if properties.get("schema_version", {}).get("const") != 2:
        errors.append("W01 schema version contract drifted")
    if properties.get("repository", {}).get("const") != REPOSITORY:
        errors.append("W01 schema repository contract drifted")
    required = set(schema.get("required", []))
    if required != set(properties):
        errors.append("W01 schema top-level required/property sets differ")

    def validate_fixed_tuples(value: Any, path: str) -> None:
        if isinstance(value, dict):
            prefix_items = value.get("prefixItems")
            if isinstance(prefix_items, list) and value.get("items") is False:
                expected_length = len(prefix_items)
                if value.get("minItems") != expected_length:
                    errors.append(
                        f"W01 schema fixed tuple {path} must set minItems to "
                        f"{expected_length}"
                    )
                if value.get("maxItems") != expected_length:
                    errors.append(
                        f"W01 schema fixed tuple {path} must set maxItems to "
                        f"{expected_length}"
                    )
            for key, child in value.items():
                validate_fixed_tuples(child, f"{path}/{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                validate_fixed_tuples(child, f"{path}/{index}")

    validate_fixed_tuples(schema, "#")
    return errors


def validate_evidence(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    top_keys = {
        "schema_version",
        "schema_id",
        "repository",
        "work_id",
        "pull_request",
        "baseline",
        "candidate_history",
        "remediation",
        "canonical_main_source",
        "downstream_gate_results",
        "out_of_scope",
    }
    if not exact_keys(record, top_keys, "W01 evidence", errors):
        return errors
    expected_identity = {
        "schema_version": 2,
        "schema_id": "lcf.w01.lifecycle.v2",
        "repository": REPOSITORY,
        "work_id": "W01",
        "pull_request": 20,
        "baseline": BASELINE,
    }
    for key, expected in expected_identity.items():
        if record[key] != expected:
            errors.append(f"W01 evidence {key} drifted")
    validate_old_history(record["candidate_history"], errors)

    remediation = record["remediation"]
    remediation_keys = {
        "finding_ids",
        "checkpoint_a",
        "checkpoint_a_record_sha256",
        "technical_source_result",
        "independent_acceptance",
        "final_containing_head_binding",
        "canonical_activation",
    }
    if exact_keys(remediation, remediation_keys, "W01 remediation", errors):
        if remediation["finding_ids"] != REJECTION_IDS:
            errors.append("W01 remediation finding IDs drifted")
        if remediation["independent_acceptance"] != "pending":
            errors.append("new W01 candidate independent acceptance must remain pending")
        if remediation["final_containing_head_binding"] != FINAL_BINDING:
            errors.append("W01 final containing-head binding drifted")
        activation = remediation["canonical_activation"]
        if exact_keys(
            activation,
            {"status", "required_conditions"},
            "W01 remediation activation",
            errors,
        ):
            if activation["status"] != "blocked":
                errors.append("new W01 candidate canonical activation must remain blocked")
            if activation["required_conditions"] != ACTIVATION_CONDITIONS:
                errors.append("new W01 candidate canonical activation conditions drifted")
        checkpoint = remediation["checkpoint_a"]
        checkpoint_digest = remediation["checkpoint_a_record_sha256"]
        if checkpoint is None:
            if remediation["technical_source_result"] != "pending":
                errors.append("pre-checkpoint remediation technical result must be pending")
            if checkpoint_digest is not None:
                errors.append("absent remediation checkpoint cannot have a record digest")
        else:
            if remediation["technical_source_result"] != "pass":
                errors.append("closed remediation checkpoint technical result must be pass")
            validate_execution(
                checkpoint, "remediation checkpoint A", errors, require_provenance=True
            )
            if full_digest(
                checkpoint_digest, "remediation checkpoint A record digest", errors
            ) and checkpoint_digest != canonical_object_digest(checkpoint):
                errors.append("remediation checkpoint A record digest does not match its fields")

    canonical_main = record["canonical_main_source"]
    expected_canonical_main = {
        "status": "not-run",
        "source_commit": None,
        "source_tree": None,
        "run_id": None,
    }
    if canonical_main != expected_canonical_main:
        errors.append("canonical-main source result must remain explicitly not-run")
    downstream = record["downstream_gate_results"]
    if not exact_keys(downstream, DOWNSTREAM_GATES, "downstream gate results", errors):
        pass
    elif any(result != "not-run" for result in downstream.values()):
        errors.append("every downstream packaged/physical/formal gate must remain not-run")
    if record["out_of_scope"] != OUT_OF_SCOPE:
        errors.append("W01 out-of-scope list must match the closed v2 schema contract")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=EVIDENCE)
    parser.add_argument("--schema", type=Path, default=SCHEMA)
    arguments = parser.parse_args()
    try:
        record = json.loads(arguments.evidence.read_text(encoding="utf-8"))
        schema = json.loads(arguments.schema.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"ERROR: cannot load W01 evidence/schema: {error}")
        return 1
    errors = [*validate_schema_document(schema), *validate_evidence(record)]
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(
        "W01 evidence OK: immutable rejected history, remediation pending, "
        "canonical activation blocked; current Git ancestry is intentionally irrelevant"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

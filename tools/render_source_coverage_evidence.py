#!/usr/bin/env python3
"""Render exact-head W01 source coverage evidence from GitHub job results."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
W01_EVIDENCE = ROOT / "docs" / "development" / "evidence" / "W01" / "2026-08-04.json"
REQUIRED_OUTPUTS = {
    "python": ["python-version", "qmd-node-version", "npm-version", "uv-version"],
    "web": ["node-version", "npm-version"],
    "desktop": ["node-version", "npm-version"],
    "macos-ipc": ["architecture", "python-version", "uv-version"],
}


def canonical_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_report(
    manifest: dict[str, Any],
    needs: dict[str, Any],
    environment: dict[str, str],
    actual_head: str,
    *,
    range_check: str,
    evidence_status: str,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    aggregate = manifest["aggregate"]
    expected_head = environment.get("LCF_SOURCE_SHA", "")
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

    qmd_result: dict[str, Any] = {}
    python_outputs = needs.get("python", {}).get("outputs", {})
    serialized_qmd = python_outputs.get("qmd-result", "")
    try:
        qmd_result = json.loads(serialized_qmd)
    except (TypeError, json.JSONDecodeError):
        errors.append("python job did not expose valid qmd-result JSON")
    expected_qmd = {
        "result": "pass",
        "node_version": "22.23.2",
        "network_trap": "active",
        "network_policy": "deny-external-allow-af-unix",
        "model_files_created": 0,
        "model_cache_paths_created": 0,
        "isolated_home_xdg_tmp": True,
    }
    for key, expected in expected_qmd.items():
        if qmd_result.get(key) != expected:
            errors.append(
                f"QMD result {key}={qmd_result.get(key)!r}, expected {expected!r}"
            )
    tests = qmd_result.get("tests", {})
    if tests.get("skipped") != 1:
        errors.append("QMD result must retain exactly one allowlisted native skip")
    if tests.get("fail") != 0 or tests.get("cancelled") != 0 or tests.get("todo") != 0:
        errors.append("QMD result contains failed, cancelled, or todo tests")
    if tests.get("tests") != tests.get("pass", -1) + tests.get("skipped", -1):
        errors.append("QMD test totals are inconsistent")
    if range_check != "pass":
        errors.append(f"base-to-head diff check is {range_check!r}")
    if evidence_status not in {"not-run", "pass"}:
        errors.append(f"W01 evidence record status is invalid: {evidence_status!r}")

    guide = next(
        component for component in manifest["components"] if component["id"] == "guide-site"
    )
    report = {
        "schema_version": 1,
        "work_id": "W01",
        "repository": environment.get("GITHUB_REPOSITORY"),
        "source_commit": actual_head,
        "github_context_sha": environment.get("GITHUB_SHA"),
        "event": environment.get("GITHUB_EVENT_NAME"),
        "ref": environment.get("GITHUB_REF"),
        "head_ref": environment.get("GITHUB_HEAD_REF") or None,
        "workflow": environment.get("GITHUB_WORKFLOW"),
        "workflow_ref": environment.get("GITHUB_WORKFLOW_REF"),
        "workflow_sha": environment.get("GITHUB_WORKFLOW_SHA"),
        "run_id": environment.get("GITHUB_RUN_ID"),
        "run_attempt": environment.get("GITHUB_RUN_ATTEMPT"),
        "run_url": (
            f"{environment.get('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{environment.get('GITHUB_REPOSITORY')}/actions/runs/"
            f"{environment.get('GITHUB_RUN_ID')}"
        ),
        "recorded_at": environment.get("LCF_RECORDED_AT"),
        "baseline_commit": manifest["baseline_commit"],
        "base_to_head_diff_check": range_check,
        "manifest_sha256": environment.get("LCF_MANIFEST_SHA256"),
        "required_job_results": job_results,
        "tool_versions": tool_versions,
        "qmd_source": qmd_result,
        "guide_site": {
            "disposition": guide["disposition"],
            "included": guide["included"],
            "validated": guide["validated"],
            "reason": guide["reason"],
        },
        "technical_candidate_gate_results": {
            "VAL-PRE1-SEQUENCE-001": "pass" if not errors else "fail",
            "VAL-GOV-001": "pass" if not errors else "fail",
            "VAL-CI-COVERAGE-001": "pass" if not errors else "fail",
        },
        "evidence_record_status": evidence_status,
        "canonical_gate_results": {
            gate: (
                "pass"
                if not errors and evidence_status == "pass"
                else "not-run"
                if not errors
                else "fail"
            )
            for gate in (
                "VAL-PRE1-SEQUENCE-001",
                "VAL-GOV-001",
                "VAL-CI-COVERAGE-001",
            )
        },
        "out_of_scope_gates": {
            "VAL-PACKAGED-SMOKE-001": "not-run",
            "packaged_physical_native_model_release_control_plane": "not-run",
        },
        "result": "pass" if not errors else "fail",
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
    evidence_status = json.loads(W01_EVIDENCE.read_text(encoding="utf-8")).get("status", "")
    try:
        needs = json.loads(os.environ.get("NEEDS_JSON", ""))
    except json.JSONDecodeError:
        needs = {}
    actual_head = git_output("rev-parse", "HEAD")
    baseline = manifest["baseline_commit"]
    range_check = "fail"
    try:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", baseline, actual_head],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            ["git", "diff", "--check", baseline, actual_head],
            cwd=ROOT,
            check=True,
        )
        range_check = "pass"
    except subprocess.CalledProcessError:
        pass

    environment = dict(os.environ)
    environment["LCF_MANIFEST_SHA256"] = canonical_digest(arguments.manifest)
    environment["LCF_RECORDED_AT"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    report, errors = build_report(
        manifest,
        needs,
        environment,
        actual_head,
        range_check=range_check,
        evidence_status=evidence_status,
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

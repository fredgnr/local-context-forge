#!/usr/bin/env python3
"""Fail closed when the declared W01 source aggregate drifts from execution."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".github" / "ci" / "source-coverage.json"
MAKEFILE = ROOT / "Makefile"
WORKFLOW = ROOT / ".github" / "workflows" / "desktop-ci.yml"
QMD_PACKAGE = ROOT / "desktop" / "workers" / "qmd" / "package.json"
QMD_TRAP = ROOT / "desktop" / "scripts" / "qmdNetworkTrap.mjs"
STATUS = ROOT / "docs" / "development" / "status.md"
HANDBOOK = ROOT / "docs" / "development" / "contributor-handbook.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"

BASELINE_COMMIT = "3eff97d97b2de4484d568bab5ac96d63830c79ee"
SOURCE_EXPRESSION = "${{ github.event.pull_request.head.sha || github.sha }}"
REQUIRED_DEPENDENCIES = ["ci-python", "ci-qmd-worker", "ci-web", "desktop-ci"]
REQUIRED_JOBS = ["python", "web", "desktop", "macos-ipc"]
REQUIRED_COMPONENTS = {
    "python-mcp-host-governance": ("required", True, "ci-python", "python"),
    "demo-python-sdk": ("required", True, "ci-python", "python"),
    "web-renderer": ("required", True, "ci-web", "web"),
    "electron-desktop-companion": ("required", True, "desktop-ci", "desktop"),
    "qmd-worker": ("required", True, "ci-qmd-worker", "python"),
    "macos-source-ipc": (
        "supplemental-required-in-workflow",
        True,
        "ci-ipc-source",
        "macos-ipc",
    ),
    "guide-site": ("external-blocked", False, None, None),
    "legacy-container-install-operations": (
        "legacy-pending-removal",
        False,
        None,
        None,
    ),
}
GUIDE_STATUS_PHRASE = (
    "`guide-site/**` is excluded from `make ci-source` and Desktop source CI"
)
UPLOAD_ARTIFACT = (
    "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(read(path))


def target_dependencies(makefile: str, target: str) -> list[str] | None:
    match = re.search(rf"^{re.escape(target)}:\s*(.*?)\s*$", makefile, re.MULTILINE)
    return match.group(1).split() if match else None


def target_recipe(makefile: str, target: str) -> str:
    match = re.search(
        rf"^{re.escape(target)}:[^\n]*\n(?P<body>(?:\t[^\n]*(?:\n|$))*)",
        makefile,
        re.MULTILINE,
    )
    return match.group("body") if match else ""


def job_block(workflow: str, job: str) -> str:
    match = re.search(
        rf"^  {re.escape(job)}:\s*\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\s*\n|\Z)",
        workflow,
        re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else ""


def validate_contract(
    manifest: dict[str, Any],
    makefile: str,
    workflow: str,
    qmd_package: dict[str, Any],
    qmd_trap: str,
    status: str,
    handbook: str,
    contributing: str,
) -> list[str]:
    errors: list[str] = []

    if manifest.get("schema_version") != 1:
        errors.append("coverage manifest schema_version must be 1")
    if manifest.get("work_id") != "W01":
        errors.append("coverage manifest work_id must be W01")
    if manifest.get("repository") != "fredgnr/local-context-forge":
        errors.append("coverage manifest repository is wrong")
    if manifest.get("baseline_commit") != BASELINE_COMMIT:
        errors.append("coverage manifest baseline commit drifted")

    aggregate = manifest.get("aggregate", {})
    if aggregate.get("make_target") != "ci-source":
        errors.append("aggregate make target must be ci-source")
    if aggregate.get("required_make_dependencies") != REQUIRED_DEPENDENCIES:
        errors.append("manifest aggregate dependency list drifted")
    if aggregate.get("workflow_path") != ".github/workflows/desktop-ci.yml":
        errors.append("manifest workflow path drifted")
    if aggregate.get("required_jobs") != REQUIRED_JOBS:
        errors.append("manifest required workflow jobs drifted")
    if aggregate.get("summary_job") != "source-coverage":
        errors.append("manifest summary job must be source-coverage")
    if aggregate.get("exact_source_expression") != SOURCE_EXPRESSION:
        errors.append("manifest exact source expression drifted")

    components = manifest.get("components")
    if not isinstance(components, list):
        errors.append("manifest components must be a list")
        components = []
    component_by_id = {
        component.get("id"): component
        for component in components
        if isinstance(component, dict) and isinstance(component.get("id"), str)
    }
    if len(component_by_id) != len(components):
        errors.append("manifest component IDs must be present and unique")
    if set(component_by_id) != set(REQUIRED_COMPONENTS):
        errors.append(
            "manifest component universe drifted: "
            f"{sorted(component_by_id)} != {sorted(REQUIRED_COMPONENTS)}"
        )
    for component_id, expected in REQUIRED_COMPONENTS.items():
        component = component_by_id.get(component_id)
        if component is None:
            continue
        actual = (
            component.get("disposition"),
            component.get("included"),
            component.get("make_target"),
            component.get("workflow_job"),
        )
        if actual != expected:
            errors.append(f"component {component_id} mapping {actual!r} != {expected!r}")

    guide = component_by_id.get("guide-site", {})
    if guide.get("validated") is not False:
        errors.append("guide-site must remain explicitly unvalidated")
    guide_reason = str(guide.get("reason", ""))
    guide_unblock = str(guide.get("unblock_condition", ""))
    for phrase in ("guide-site/.openai/hosting.json", "no repository-owned"):
        if phrase not in guide_reason:
            errors.append(f"guide-site exclusion reason missing {phrase!r}")
    for phrase in ("exact Sites hosting identity", "commit-bound"):
        if phrase not in guide_unblock:
            errors.append(f"guide-site unblock condition missing {phrase!r}")

    qmd = component_by_id.get("qmd-worker", {})
    safety = qmd.get("safety", {})
    expected_safety = {
        "node_version": "22.23.2",
        "install_flags": [
            "--ignore-scripts",
            "--omit=optional",
            "--no-audit",
            "--no-fund",
        ],
        "network_policy": "deny-external-allow-af-unix",
        "model_files_created": 0,
        "model_cache_paths_created": 0,
        "allowed_skip_count": 1,
        "allowed_skip_reason": (
            "better-sqlite3 native binding is not built in source checkout"
        ),
    }
    if safety != expected_safety:
        errors.append("QMD safety contract drifted")

    if target_dependencies(makefile, "ci-source") != REQUIRED_DEPENDENCIES:
        errors.append("Make ci-source dependencies do not match the manifest")
    qmd_recipe = target_recipe(makefile, "ci-qmd-worker")
    for phrase in (
        "ci --ignore-scripts --omit=optional --no-audit --no-fund",
        "$(NPM) test",
        'NODE="$(NODE)"',
        "QMD_SOURCE_RESULT",
    ):
        if phrase not in qmd_recipe:
            errors.append(f"ci-qmd-worker recipe missing {phrase!r}")
    if "ci --ignore-scripts" not in qmd_recipe:
        errors.append("QMD dependency installation can execute lifecycle scripts")
    python_recipe = target_recipe(makefile, "ci-python")
    for phrase in (
        "examples/demo-python-sdk",
        "-m compileall -q mcp/mcp_server",
        "import mcp_server.client; import mcp_server.server",
        "tools/check_ci_coverage.py",
        "tools/check_w01_evidence.py",
    ):
        if phrase not in python_recipe:
            errors.append(f"ci-python recipe missing {phrase!r}")

    if qmd_package.get("engines", {}).get("node") != "22.23.2":
        errors.append("QMD package must pin exact Node 22.23.2")
    if qmd_package.get("scripts", {}).get("test") != (
        "python3 ../../../tools/run_qmd_source_ci.py"
    ):
        errors.append("QMD npm test must use the fail-closed source runner")
    for phrase in (
        'process.env.LCF_QMD_SOURCE_TEST === "1"',
        "LCF_QMD_NETWORK_TRAP=active:${gate}",
        "dgram.createSocket = rejectedOperation",
        "childProcess.spawn = rejectedOperation",
        "globalThis.fetch",
    ):
        if phrase not in qmd_trap:
            errors.append(f"QMD network trap missing {phrase!r}")

    if "pull_request_target:" in workflow:
        errors.append("source workflow must not use pull_request_target")
    if "continue-on-error:" in workflow:
        errors.append("source workflow must not make source execution optional")
    for required_job in [*REQUIRED_JOBS, "source-coverage"]:
        if not job_block(workflow, required_job):
            errors.append(f"workflow missing job {required_job}")

    checkout_count = workflow.count("uses: actions/checkout@")
    if checkout_count != 5:
        errors.append(f"workflow must have five exact-head checkouts, observed {checkout_count}")
    for phrase in (
        f"ref: {SOURCE_EXPRESSION}",
        "fetch-depth: 0",
        "persist-credentials: false",
    ):
        if workflow.count(phrase) != checkout_count:
            errors.append(f"every checkout must set {phrase!r}")

    python_job = job_block(workflow, "python")
    for phrase in (
        'node-version: "22.23.2"',
        "make ci-python",
        "make ci-qmd-worker",
        "qmd-result:",
        "git diff --check",
        BASELINE_COMMIT,
        SOURCE_EXPRESSION,
    ):
        if phrase not in python_job:
            errors.append(f"python job missing {phrase!r}")

    summary_job = job_block(workflow, "source-coverage")
    for phrase in (
        "if: ${{ always() }}",
        "needs: [python, web, desktop, macos-ipc]",
        "tools/render_source_coverage_evidence.py",
        "NEEDS_JSON: ${{ toJSON(needs) }}",
        UPLOAD_ARTIFACT,
        "if-no-files-found: error",
        SOURCE_EXPRESSION,
    ):
        if phrase not in summary_job:
            errors.append(f"source-coverage job missing {phrase!r}")

    for label, document in (
        ("status", status),
        ("handbook", handbook),
        ("CONTRIBUTING", contributing),
    ):
        if GUIDE_STATUS_PHRASE not in document:
            errors.append(f"{label} missing exact guide-site exclusion phrase")
    return errors


def main() -> int:
    errors = validate_contract(
        load_json(MANIFEST),
        read(MAKEFILE),
        read(WORKFLOW),
        load_json(QMD_PACKAGE),
        read(QMD_TRAP),
        read(STATUS),
        read(HANDBOOK),
        read(CONTRIBUTING),
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(
        "source coverage contract OK: QMD required/safe, exact-head workflow bound, "
        "guide-site external-blocked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

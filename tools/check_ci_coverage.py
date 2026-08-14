#!/usr/bin/env python3
"""Fail closed when W01 source execution or lifecycle semantics drift."""

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
QMD_RUNNER = ROOT / "tools" / "run_qmd_source_ci.py"
PAYLOAD_RENDERER = ROOT / "tools" / "render_source_coverage_evidence.py"
PROVENANCE_RENDERER = ROOT / "tools" / "render_source_coverage_provenance.py"
W01_SCHEMA = ROOT / "docs" / "development" / "evidence" / "W01" / "schema-v2.json"
W01_EVIDENCE_CHECKER = ROOT / "tools" / "check_w01_evidence.py"
STATUS = ROOT / "docs" / "development" / "status.md"
HANDBOOK = ROOT / "docs" / "development" / "contributor-handbook.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"

BASELINE_COMMIT = "3eff97d97b2de4484d568bab5ac96d63830c79ee"
SOURCE_EXPRESSION = "${{ github.event.pull_request.head.sha || github.sha }}"
REQUIRED_DEPENDENCIES = ["ci-python", "ci-qmd-worker", "ci-web", "desktop-ci"]
REQUIRED_JOBS = ["python", "web", "desktop", "macos-ipc"]
LIFECYCLE_PHASES = [
    "pull-request-candidate",
    "branch-candidate",
    "canonical-main-source",
]
ACTIVATION_STATES = ["blocked", "requires-external-conditions"]
MODEL_SCAN_SCOPE = [
    "isolated HOME",
    "isolated XDG_CACHE_HOME",
    "isolated XDG_CONFIG_HOME",
    "isolated XDG_DATA_HOME",
    "isolated TMPDIR",
]
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
    matches = re.findall(
        rf"^{re.escape(target)}:[ \t]*(.*?)[ \t]*$", makefile, re.MULTILINE
    )
    return matches[0].split() if len(matches) == 1 else None


def target_recipe(makefile: str, target: str) -> str:
    match = re.search(
        rf"^{re.escape(target)}:[^\n]*\n(?P<body>(?:\t[^\n]*(?:\n|$))*)",
        makefile,
        re.MULTILINE,
    )
    return match.group("body") if match else ""


def phony_targets(makefile: str) -> list[str] | None:
    lines = makefile.splitlines()
    starts = [index for index, line in enumerate(lines) if line.startswith(".PHONY:")]
    if len(starts) != 1:
        return None
    index = starts[0]
    parts: list[str] = []
    line = lines[index].split(":", 1)[1].strip()
    while True:
        continued = line.endswith("\\")
        parts.extend(line.removesuffix("\\").split())
        if not continued:
            return parts
        index += 1
        if index >= len(lines) or not lines[index].startswith("\t"):
            return None
        line = lines[index].strip()


def job_block(workflow: str, job: str) -> str:
    match = re.search(
        rf"^  {re.escape(job)}:\s*\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\s*\n|\Z)",
        workflow,
        re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else ""


def step_block(job: str, step_name: str) -> str:
    match = re.search(
        rf"^      - name: {re.escape(step_name)}\s*\n(?P<body>.*?)(?=^      - name: |\Z)",
        job,
        re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else ""


def validate_action_pins(workflow: str) -> list[str]:
    errors: list[str] = []
    uses = re.findall(r"^\s*uses:\s*([^@\s]+)@([^\s#]+)", workflow, re.MULTILINE)
    if not uses:
        return ["source workflow contains no external action uses"]
    for action, revision in uses:
        if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
            errors.append(f"workflow action {action} is not pinned to a full commit SHA")
    return errors


def validate_contract(
    manifest: dict[str, Any],
    makefile: str,
    workflow: str,
    qmd_package: dict[str, Any],
    qmd_trap: str,
    qmd_runner: str,
    payload_renderer: str,
    provenance_renderer: str,
    w01_schema: dict[str, Any],
    status: str,
    handbook: str,
    contributing: str,
    w01_evidence_checker: str,
) -> list[str]:
    errors: list[str] = []

    if manifest.get("schema_version") != 2:
        errors.append("coverage manifest schema_version must be 2")
    if manifest.get("work_id") != "W01":
        errors.append("coverage manifest work_id must be W01")
    if manifest.get("repository") != "fredgnr/local-context-forge":
        errors.append("coverage manifest repository is wrong")
    if manifest.get("baseline_commit") != BASELINE_COMMIT:
        errors.append("coverage manifest historical baseline commit drifted")

    aggregate = manifest.get("aggregate", {})
    expected_aggregate = {
        "make_target": "ci-source",
        "required_make_dependencies": REQUIRED_DEPENDENCIES,
        "workflow_path": ".github/workflows/desktop-ci.yml",
        "workflow_name": "Desktop source CI",
        "required_jobs": REQUIRED_JOBS,
        "summary_job": "source-coverage",
        "exact_source_expression": SOURCE_EXPRESSION,
        "payload_schema_version": 2,
        "payload_artifact_prefix": "w01-source-coverage-",
        "provenance_artifact_prefix": "w01-source-coverage-provenance-",
        "lifecycle_phases": LIFECYCLE_PHASES,
        "canonical_activation_states": ACTIVATION_STATES,
    }
    if aggregate != expected_aggregate:
        errors.append("coverage manifest aggregate/lifecycle contract drifted")

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
    if (ROOT / "guide-site" / ".openai" / "hosting.json").exists():
        errors.append("guide-site hosting identity now exists; external-blocked must be re-evaluated")
    guide_workflow_paths = {
        path
        for pattern in ("*.yml", "*.yaml")
        for path in (ROOT / ".github" / "workflows").glob(pattern)
    }
    guide_workflow_hits = [
        path.name
        for path in sorted(guide_workflow_paths)
        if path != WORKFLOW and "guide-site" in read(path)
    ]
    if guide_workflow_hits:
        errors.append(f"guide-site workflow now exists: {guide_workflow_hits}")

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
        "model_scan_scope": MODEL_SCAN_SCOPE,
        "repository_worktree_scanned": False,
        "global_tmp_scanned": False,
        "model_files_created": 0,
        "model_cache_paths_created": 0,
        "allowed_skip_count": 1,
        "allowed_skip_reason": (
            "better-sqlite3 native binding is not built in source checkout"
        ),
    }
    if safety != expected_safety:
        errors.append("QMD safety and scan-scope contract drifted")

    if target_dependencies(makefile, "ci-source") != REQUIRED_DEPENDENCIES:
        errors.append("Make ci-source dependencies do not match the manifest")
    qmd_recipe = target_recipe(makefile, "ci-qmd-worker")
    for phrase in (
        "ci --ignore-scripts --omit=optional --no-audit --no-fund",
        "$(NPM) test",
        '--node "$(NODE)"',
        "QMD_SOURCE_RESULT",
    ):
        if phrase not in qmd_recipe:
            errors.append(f"ci-qmd-worker recipe missing {phrase!r}")
    if "ci --ignore-scripts" not in qmd_recipe:
        errors.append("QMD dependency installation can execute lifecycle scripts")
    phony = phony_targets(makefile)
    if phony is None or phony.count("web-install") != 1:
        errors.append("web-install must be declared exactly once as phony")
    if target_dependencies(makefile, "web-install") != []:
        errors.append("web-install must not have prerequisites")
    if target_recipe(makefile, "web-install") != "\tcd web && $(NPM) ci\n":
        errors.append("web-install must run exactly the locked Web npm ci recipe")
    if target_dependencies(makefile, "ci-web") != ["web-install"]:
        errors.append("ci-web must depend exactly on web-install")
    web_recipe = target_recipe(makefile, "ci-web")
    for phrase in (
        "cd web && $(NPM) test",
        "cd web && $(NPM) run typecheck",
        "cd web && $(NPM) run build",
    ):
        if phrase not in web_recipe:
            errors.append(f"ci-web recipe missing {phrase!r}")
    if target_dependencies(makefile, "desktop-install") != []:
        errors.append("desktop-install must not have prerequisites")
    if target_recipe(makefile, "desktop-install") != (
        "\tcd desktop && ELECTRON_SKIP_BINARY_DOWNLOAD=1 "
        "$(NPM) ci --ignore-scripts\n"
    ):
        errors.append("desktop-install locked npm flags drifted")
    if target_dependencies(makefile, "desktop-ci") != [
        "web-install",
        "desktop-install",
    ]:
        errors.append("desktop-ci must install Web before Desktop dependencies")
    desktop_recipe = target_recipe(makefile, "desktop-ci")
    desktop_commands = (
        "$(MAKE) desktop-test",
        "$(MAKE) desktop-typecheck",
        "$(MAKE) desktop-build",
    )
    desktop_offsets: list[int] = []
    for phrase in desktop_commands:
        if phrase not in desktop_recipe:
            errors.append(f"desktop-ci recipe missing {phrase!r}")
        desktop_offsets.append(desktop_recipe.find(phrase))
    if (
        any(offset < 0 for offset in desktop_offsets)
        or desktop_offsets != sorted(desktop_offsets)
        or any(desktop_recipe.count(phrase) != 1 for phrase in desktop_commands)
    ):
        errors.append("desktop-ci test/typecheck/build order drifted")
    ipc_recipe = target_recipe(makefile, "ci-ipc-source")
    if "tests/backend/test_desktop_transport.py" not in ipc_recipe:
        errors.append("ci-ipc-source must run the desktop transport contract")
    python_recipe = target_recipe(makefile, "ci-python")
    for phrase in (
        "examples/demo-python-sdk",
        "-m compileall -q mcp/mcp_server",
        "import mcp_server.client; import mcp_server.server",
        "tools/check_ci_coverage.py",
        "tools/check_w01_evidence.py",
        "tools/check_pre1_work_plan.py",
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
        "LCF_QMD_NETWORK_POLICY=deny-external-allow-af-unix",
        "dgram.createSocket = rejectedOperation",
        "childProcess.execSync = rejectedOperation",
        "childProcess.execFileSync = rejectedOperation",
        "childProcess.spawn = rejectedOperation",
        "globalThis.fetch",
    ):
        if phrase not in qmd_trap:
            errors.append(f"QMD network/process trap missing {phrase!r}")
    for phrase in (
        '"isolated HOME"',
        '"isolated XDG_CACHE_HOME"',
        '"isolated XDG_CONFIG_HOME"',
        '"isolated XDG_DATA_HOME"',
        '"isolated TMPDIR"',
        '"repository_worktree_scanned": False',
        '"global_tmp_scanned": False',
        '"model_file_paths_created": created',
        '"model_cache_path_names_created": created_cache_paths',
    ):
        if phrase not in qmd_runner:
            errors.append(f"QMD runner scope/result wiring missing {phrase!r}")

    if "pull_request_target:" in workflow:
        errors.append("source workflow must not use pull_request_target")
    if "continue-on-error:" in workflow:
        errors.append("source workflow must not make source execution optional")
    if re.search(r"\bsecrets\.", workflow):
        errors.append("source workflow must not read GitHub secrets")
    permission_declarations = re.findall(
        r"^(?P<indent>[ ]*)permissions:\s*$", workflow, re.MULTILINE
    )
    top_permission = re.search(
        r"^permissions:\s*\n(?P<body>(?:  [^\n]+\n?)*)", workflow, re.MULTILINE
    )
    permission_lines = (
        [line.strip() for line in top_permission.group("body").splitlines()]
        if top_permission
        else []
    )
    if permission_declarations != [""] or permission_lines != ["contents: read"]:
        errors.append("source workflow permissions must be exactly top-level contents: read")
    if re.search(r"^[ ]{2,}environment:\s*", workflow, re.MULTILINE):
        errors.append("source workflow must not bind a GitHub Environment")
    errors.extend(validate_action_pins(workflow))
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
        "test -z \"$(git status --porcelain=v1)\"",
        SOURCE_EXPRESSION,
    ):
        if phrase not in python_job:
            errors.append(f"python job missing {phrase!r}")
    if "merge-base --is-ancestor" in python_job:
        errors.append("current source workflow must not depend on a historical W01 ancestry check")
    for job_name, required_phrases in {
        "web": ("make ci-web", 'node-version: "24"', SOURCE_EXPRESSION),
        "desktop": ("make desktop-ci", 'node-version: "24"', SOURCE_EXPRESSION),
        "macos-ipc": (
            "make ci-ipc-source",
            "runs-on: macos-15",
            'test "$(uname -m)" = "arm64"',
            SOURCE_EXPRESSION,
        ),
    }.items():
        block = job_block(workflow, job_name)
        for phrase in required_phrases:
            if phrase not in block:
                errors.append(f"{job_name} job missing {phrase!r}")

    desktop_job = job_block(workflow, "desktop")
    desktop_setup = step_block(desktop_job, "Set up Node")
    desktop_run = step_block(desktop_job, "Run desktop source checks")
    expected_desktop_cache = (
        '          node-version: "24"\n'
        "          cache: npm\n"
        "          cache-dependency-path: |\n"
        "            desktop/package-lock.json\n"
        "            web/package-lock.json\n"
    )
    if (
        not desktop_setup
        or desktop_setup.count(expected_desktop_cache) != 1
        or desktop_setup.count("desktop/package-lock.json") != 1
        or desktop_setup.count("web/package-lock.json") != 1
    ):
        errors.append("desktop job npm cache must bind exact Desktop and Web locks")
    setup_offset = desktop_job.find("      - name: Set up Node\n")
    run_offset = desktop_job.find("      - name: Run desktop source checks\n")
    if (
        not desktop_run
        or desktop_run.count("        run: make desktop-ci\n") != 1
        or setup_offset < 0
        or run_offset < 0
        or setup_offset >= run_offset
    ):
        errors.append("desktop job setup/run order drifted")

    summary_job = job_block(workflow, "source-coverage")
    for phrase in (
        "if: ${{ always() }}",
        "needs: [python, web, desktop, macos-ipc]",
        "tools/render_source_coverage_evidence.py",
        "tools/render_source_coverage_provenance.py",
        "NEEDS_JSON: ${{ toJSON(needs) }}",
        "id: payload-artifact",
        "steps.payload-artifact.outputs.artifact-id",
        "steps.payload-artifact.outputs.artifact-url",
        "steps.payload-artifact.outputs.artifact-digest",
        "w01-source-coverage-provenance-",
        "if-no-files-found: error",
        SOURCE_EXPRESSION,
    ):
        if phrase not in summary_job:
            errors.append(f"source-coverage job missing {phrase!r}")
    if summary_job.count(UPLOAD_ARTIFACT) != 2:
        errors.append("source-coverage must upload exactly payload and provenance artifacts")
    for step_name in (
        "Upload source payload even on failure",
        "Render non-self-referential payload provenance",
        "Upload payload provenance even on failure",
    ):
        block = step_block(summary_job, step_name)
        if not block:
            errors.append(f"source-coverage job missing step {step_name!r}")
        elif "if: ${{ always() }}" not in block:
            errors.append(f"source-coverage step {step_name!r} must run with always()")

    for phrase in (
        '"lifecycle_phase"',
        '"pull-request-candidate"',
        '"branch-candidate"',
        '"canonical-main-source"',
        '"technical_candidate_gate_results"',
        '"main_source_gate_results"',
        '"canonical_activation"',
        '"blocked"',
        '"requires-external-conditions"',
        '"synthetic_context_sha"',
        '"source_tree"',
        '"payload_artifact_name"',
        '"pull_request_number"',
    ):
        if phrase not in payload_renderer:
            errors.append(f"payload renderer lifecycle schema missing {phrase!r}")
    for forbidden in ("canonical_gate_results", "W01_EVIDENCE", "evidence_status"):
        if forbidden in payload_renderer:
            errors.append(f"payload renderer contains forbidden self-promotion field {forbidden!r}")
    for phrase in (
        '"payload_artifact"',
        '"archive_sha256"',
        '"sha256"',
        '"provenance_artifact_name"',
        "LCF_PAYLOAD_ARTIFACT_ID",
        "LCF_PAYLOAD_ARTIFACT_DIGEST",
        "validate_payload_schema",
    ):
        if phrase not in provenance_renderer:
            errors.append(f"provenance renderer binding missing {phrase!r}")
    for forbidden in ("provenance_archive_sha256", "provenance_artifact_id"):
        if forbidden in provenance_renderer:
            errors.append(f"provenance renderer is recursively self-referential: {forbidden}")

    if w01_schema.get("type") != "object" or w01_schema.get("additionalProperties") is not False:
        errors.append("W01 lifecycle schema must be a closed top-level object")
    if w01_schema.get("properties", {}).get("schema_version", {}).get("const") != 2:
        errors.append("W01 lifecycle schema version drifted")
    for forbidden in (
        "import subprocess",
        "subprocess.",
        "verify_git_binding",
        "merge-base",
        "--is-ancestor",
        "git diff",
        "ALLOWED_ATTESTATION_PATHS",
    ):
        if forbidden in w01_evidence_checker:
            errors.append(
                f"historical W01 checker regained a current-Git dependency: {forbidden!r}"
            )

    for label, document in (
        ("status", status),
        ("handbook", handbook),
        ("CONTRIBUTING", contributing),
    ):
        if GUIDE_STATUS_PHRASE not in document:
            errors.append(f"{label} missing exact guide-site exclusion phrase")
        for phrase in (
            "independent acceptance",
            "canonical-main",
            "canonical activation",
        ):
            if phrase not in document:
                errors.append(f"{label} missing W01 lifecycle phrase {phrase!r}")
    return errors


def main() -> int:
    errors = validate_contract(
        load_json(MANIFEST),
        read(MAKEFILE),
        read(WORKFLOW),
        load_json(QMD_PACKAGE),
        read(QMD_TRAP),
        read(QMD_RUNNER),
        read(PAYLOAD_RENDERER),
        read(PROVENANCE_RENDERER),
        load_json(W01_SCHEMA),
        read(STATUS),
        read(HANDBOOK),
        read(CONTRIBUTING),
        read(W01_EVIDENCE_CHECKER),
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(
        "source coverage contract OK: exact-head lifecycle separated, QMD scope bounded, "
        "payload/provenance fail closed, guide-site external-blocked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

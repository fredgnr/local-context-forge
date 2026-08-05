#!/usr/bin/env python3
"""Validate the canonical pre-1.0 work order and cross-document mappings."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs/development/work-plan.md"
TODO = ROOT / "docs/development/todo.md"
TRACE = ROOT / "docs/development/traceability.md"
ITERATION = ROOT / "docs/development/iterations/0008-incremental-retirement-engineering-package.md"
LEGACY_MANIFEST = ROOT / "docs/development/legacy-retirement.md"
ADR = ROOT / "docs/adr/0016-pre1-incremental-retirement-engineering-package.md"
STATUS = ROOT / "docs/development/status.md"
R13 = ROOT / "docs/development/iterations/0002-r13-pre1-incremental-retirement.md"
RELEASE_RUNBOOK = ROOT / "docs/development/desktop-release.md"
W01_EVIDENCE = ROOT / "docs/development/evidence/W01/2026-08-04.json"
W02_ENTRY = ROOT / "docs/development/evidence/W02/2026-08-05-entry.md"
W02_ASSEMBLY = (
    ROOT
    / "docs/development/evidence/W02/2026-08-06-08137c7-assembly.md"
)

EXPECTED_ORDER = [
    "W01",
    "W02",
    "W10",
    "W11",
    "W03",
    "W04",
    "W05",
    "W06",
    "W07",
    "W08",
    "W09",
    "W12",
    "W13",
    "W14",
    "W15",
    "W16",
]

EXPECTED_WORK: dict[str, dict[str, set[str]]] = {
    "W01": {
        "tasks": {
            "TODO-PRE1-SEQUENCING-001",
            "TODO-GOV-EVIDENCE-001",
            "TODO-CI-COVERAGE-001",
        },
        "gates": {"VAL-PRE1-SEQUENCE-001", "VAL-GOV-001", "VAL-CI-COVERAGE-001"},
    },
    "W02": {
        "tasks": {"TODO-PACKAGED-SMOKE-001"},
        "gates": {"VAL-PACKAGED-SMOKE-001"},
    },
    "W10": {
        "tasks": {
            "TODO-LEGACY-DECOUPLE-001",
            "TODO-LEGACY-REMOVE-TRANSPORT-001",
            "TODO-LEGACY-REMOVE-PROVIDER-001",
        },
        "gates": {
            "VAL-LEGACY-DECOUPLE-001",
            "VAL-LEGACY-TRANSPORT-001",
            "VAL-LEGACY-PROVIDER-001",
        },
    },
    "W11": {
        "tasks": {
            "TODO-LEGACY-REMOVE-DEPLOY-001",
            "TODO-LEGACY-REMOVE-RELEASE-001",
            "TODO-LEGACY-REMOVE-DOCS-001",
        },
        "gates": {
            "VAL-LEGACY-DEPLOY-001",
            "VAL-LEGACY-RELEASE-001",
            "VAL-LEGACY-DOCS-001",
        },
    },
    "W03": {
        "tasks": {"TODO-PACK-ENGINEERING-001"},
        "gates": {"VAL-ENGINEERING-PACKAGE-001"},
    },
    "W04": {
        "tasks": {"TODO-DATA-LAYOUT-001", "TODO-DATA-BACKUP-001"},
        "gates": {"VAL-DATA-001"},
    },
    "W05": {
        "tasks": {"TODO-MODEL-SUPPLY-001"},
        "gates": {"VAL-MODEL-001", "VAL-MODEL-EMBED-001"},
    },
    "W06": {
        "tasks": {
            "TODO-PHYS-TRUST-001",
            "TODO-PHYS-PY-001",
            "TODO-RUNTIME-CANCEL-001",
        },
        "gates": {
            "VAL-TRUST-001",
            "VAL-PY-001",
            "VAL-GIT-001",
            "VAL-IPC-001",
            "VAL-CANCEL-001",
        },
    },
    "W07": {
        "tasks": {
            "TODO-PHYS-QMD-001",
            "TODO-QMD-COMPACT-001",
            "TODO-EVAL-CORPUS-001",
        },
        "gates": {
            "VAL-QMD-001",
            "VAL-QMD-EMBED-001",
            "VAL-IPC-EMBED-001",
            "VAL-QMD-COMPACT-001",
            "VAL-EVAL-001",
        },
    },
    "W08": {
        "tasks": {"TODO-PHYS-CLI-001"},
        "gates": {"VAL-CLI-001"},
    },
    "W09": {
        "tasks": {"TODO-PHYS-MCP-001", "TODO-MCP-PAIRING-001"},
        "gates": {"VAL-MCP-001", "VAL-MCP-ONBOARD-001", "VAL-MCP-PAIRING-001"},
    },
    "W12": {
        "tasks": {
            "TODO-PHYS-LOCAL-001",
            "TODO-LOCAL-HARDEN-001",
            "TODO-OPS-DIAGNOSTICS-001",
        },
        "gates": {
            "VAL-LOCAL-SOURCE-003",
            "VAL-LOCAL-HARDEN-001",
            "VAL-DIAGNOSTICS-001",
        },
    },
    "W13": {
        "tasks": {"TODO-ELECTRON-CUTOVER-001", "TODO-LEGACY-ABSENCE-001"},
        "gates": {"VAL-ELECTRON-CUTOVER-001", "VAL-LEGACY-ABSENCE-001"},
    },
    "W14": {
        "tasks": {"TODO-REL-GOV-001"},
        "gates": {"VAL-SECRET-001"},
    },
    "W15": {
        "tasks": {"TODO-REL-KEYS-001", "TODO-PACK-ARM64-001", "TODO-REL-DRAFT-001"},
        "gates": {
            "VAL-SECRET-001",
            "VAL-RELEASE-CONTINUITY-001",
            "VAL-PACK-001",
            "VAL-RELEASE-001",
        },
    },
    "W16": {
        "tasks": {"TODO-REL-PROMOTE-001", "TODO-UPDATE-NMINUS1-001"},
        "gates": {
            "VAL-ELECTRON-CUTOVER-001",
            "VAL-LEGACY-ABSENCE-001",
            "VAL-RELEASE-CONTINUITY-001",
            "VAL-INSTALL-001",
            "VAL-RELEASE-001",
            "VAL-UPDATE-001",
        },
    },
}

EXPECTED_TASK_STATUS = {
    task: "planned"
    for work in EXPECTED_WORK.values()
    for task in work["tasks"]
}
EXPECTED_TASK_STATUS.update(
    {
        "TODO-PRE1-SEQUENCING-001": "done",
        "TODO-GOV-EVIDENCE-001": "done",
        "TODO-CI-COVERAGE-001": "done",
        "TODO-PACKAGED-SMOKE-001": "in-progress",
        "TODO-REL-GOV-001": "blocked",
        "TODO-REL-KEYS-001": "blocked",
        "TODO-REL-DRAFT-001": "blocked",
        "TODO-REL-PROMOTE-001": "blocked",
        "TODO-UPDATE-NMINUS1-001": "blocked",
    }
)

REQUIRED_REQUIREMENTS = {
    "REQ-PRE1-SEQUENCING-001",
    "REQ-PACKAGED-SMOKE-001",
    "REQ-LEGACY-SLICE-001",
    "REQ-ENGINEERING-PACKAGE-001",
}

NEW_TASKS = {
    "TODO-PRE1-SEQUENCING-001",
    "TODO-PACKAGED-SMOKE-001",
    "TODO-PACK-ENGINEERING-001",
    "TODO-LEGACY-REMOVE-PROVIDER-001",
}

NEW_VALIDATIONS = {
    "VAL-PRE1-SEQUENCE-001",
    "VAL-PACKAGED-SMOKE-001",
    "VAL-LEGACY-DECOUPLE-001",
    "VAL-LEGACY-DEPLOY-001",
    "VAL-LEGACY-TRANSPORT-001",
    "VAL-LEGACY-PROVIDER-001",
    "VAL-LEGACY-RELEASE-001",
    "VAL-LEGACY-DOCS-001",
    "VAL-ENGINEERING-PACKAGE-001",
    "VAL-RELEASE-CONTINUITY-001",
}

NEW_STABLE_IDS = REQUIRED_REQUIREMENTS | NEW_TASKS | NEW_VALIDATIONS

W01_EXIT_MARKER = (
    "<!-- pre1-w02-requires: "
    "VAL-PRE1-SEQUENCE-001,VAL-GOV-001,VAL-CI-COVERAGE-001,"
    "independent-acceptance-exact-final-head,accepted-candidate-merged-to-main,"
    "resulting-main-source-coverage -->"
)

OLD_REJECTED_TRACE_MARKER = (
    "旧候选 technical source `pass`；independent acceptance `fail`；"
    "canonical activation `not-eligible`"
)

W01_ACCEPTED_HEAD = "36885e04df09c4789d8ec3c9dc5c5e78a381a634"
W01_RESULTING_MAIN = "1786255b55dd1a78659ed92235893876175a0722"
W01_ACCEPTED_TREE = "1b9f3a34847fd3acc8b7f3a31ff19332d5328b64"
W01_RESULTING_MAIN_RUN = "30986208251"
W02_ENTRY_AUTHORITY_MARKER = (
    "<!-- w02-entry-authority: "
    "rejected=2b7629468c711d0db5107f7001aa90c0271079ae,"
    f"accepted={W01_ACCEPTED_HEAD},main={W01_RESULTING_MAIN},"
    f"tree={W01_ACCEPTED_TREE},source-run={W01_RESULTING_MAIN_RUN} -->"
)
CURRENT_W01_TRACE_MARKER = (
    f"accepted final `{W01_ACCEPTED_HEAD}` / tree `{W01_ACCEPTED_TREE}`："
    "PR/source、independent acceptance、canonical merge 与 resulting-main source 均 `pass`"
)
W02_PHASE_MARKERS = {
    "engineering-smoke boundary/assembly：本 Work，static assembly/bundle audit substage `pass`",
    "packaged App launch/runtime smoke：后续 Work，`not-run`",
    "W10/W11 保持 locked",
}
W02_ENTRY_REQUIRED_MARKERS = {
    "remediation final head 的 PR/source technical result：`pass`",
    "同一 exact final head 的 independent acceptance：`pass`",
    "accepted candidate 合入 canonical `main`：`pass`",
    "resulting exact main 的 `source-coverage`：`pass`",
    "W02 canonical activation：`pass`",
    "engineering-smoke `.app` assembly：`not-run`",
    "packaged App launch：`not-run`",
    "`VAL-PACKAGED-SMOKE-001`：`not-run`",
    "W10/W11 destructive slices：`not-run`",
    "public release：`NO-GO`",
    "Python source checks | `success`",
    "Web source checks | `success`",
    "Desktop source checks | `success`",
    "macOS 15 arm64 source IPC | `success`",
    "W01 exact-head source coverage evidence | `success`",
}
W02_ASSEMBLY_SOURCE = "08137c7bce5469350b861cef7960e4a0530151bf"
W02_ASSEMBLY_TREE = "d7814ac96136cea33fb7069d9538a4aad8dffa38"
W02_ASSEMBLY_RUN = "31024794972"
W02_ASSEMBLY_JOB = "92370351806"
W02_ASSEMBLY_SOURCE_RUN = "31024794734"
W02_ASSEMBLY_INVENTORY_SHA256 = (
    "7fcdb699ad367e7c7da28a074694c6fe8a0a67b54829173894d311de4f6ffe5c"
)
W02_ASSEMBLY_DOCUMENT_SHA256 = (
    "6404b2274348d10c5d1a4a18a3cf4ed15ae2cdfbddfa540b5f96b3ef600425a4"
)
W02_ASSEMBLY_AUTHORITY_MARKER = (
    "<!-- w02-assembly-authority: "
    f"source={W02_ASSEMBLY_SOURCE},tree={W02_ASSEMBLY_TREE},"
    f"assembly-run={W02_ASSEMBLY_RUN},assembly-job={W02_ASSEMBLY_JOB},"
    f"source-run={W02_ASSEMBLY_SOURCE_RUN},"
    f"inventory-sha256={W02_ASSEMBLY_INVENTORY_SHA256},"
    "inventory-entries=879,native-files=78,source-date-epoch=1785946811 -->"
)
W02_ASSEMBLY_REQUIRED_MARKERS = {
    "Draft #21",
    "assembly job conclusion | `success`；all steps `success`",
    "remote artifacts | empty",
    "| `assembly` | `pass` |",
    "| `bundleAudit` | `pass` |",
    "`identityName=-` / `identityHash=none`",
    "| notarization | `false` |",
    "pre-pack frozen sidecar staging smoke 已运行且成功",
    "sidecar 未从 assembled bundle 启动",
    "`packagedAppLaunch`：`not-run`",
    "`packagedSmokeValidation`：`not-run`",
    "`VAL-PACKAGED-SMOKE-001`：`not-run`",
    "W10/W11：`locked`",
    "public release：`NO-GO`",
    "没有可下载的 `.app` archive 或 package digest",
    f"| exact source commit | `{W02_ASSEMBLY_SOURCE}` |",
    f"| exact source tree | `{W02_ASSEMBLY_TREE}` |",
    (
        "| normalized inventory SHA-256 | "
        f"`{W02_ASSEMBLY_INVENTORY_SHA256}` |"
    ),
}
W02_ASSEMBLY_FORBIDDEN_CLAIMS = {
    "`VAL-PACKAGED-SMOKE-001`：`pass`",
    "VAL-PACKAGED-SMOKE-001: pass",
    "public release：`GO`",
    "public release: GO",
    "normalized inventory SHA-256 is the package digest",
}

CONTINUITY_COMPONENTS = {
    "W13 checkpoint commit/package digest",
    "formal tag commit",
    "allowlisted public pins/release metadata/version diff",
    "tag source/absence 重跑",
    "exact unique Draft digest",
    "完整 cutover/absence 重跑",
    "candidate manifest/Release ID 绑定",
}

FORMAL_NOT_RUN = {
    "VAL-PACKAGED-SMOKE-001",
    "VAL-LEGACY-DECOUPLE-001",
    "VAL-LEGACY-DEPLOY-001",
    "VAL-LEGACY-TRANSPORT-001",
    "VAL-LEGACY-PROVIDER-001",
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

TASK_PATTERN = re.compile(r"TODO-[A-Z0-9-]+-[0-9]{3}")
GATE_PATTERN = re.compile(r"VAL-[A-Z0-9-]+-[0-9]{3}")
STATUS_WORD_PATTERN = re.compile(r"(?<![A-Za-z-])(not-run|pass|fail)(?![A-Za-z-])")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def pipe_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def table_rows(text: str, first_cell_pattern: str, columns: int) -> list[list[str]]:
    pattern = re.compile(first_cell_pattern)
    rows: list[list[str]] = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = pipe_cells(line)
        if len(cells) == columns and pattern.fullmatch(cells[0]):
            rows.append(cells)
    return rows


def normalized_status(value: str) -> str:
    return value.strip().strip("`")


def only_work_id(value: str) -> str | None:
    matches = re.findall(r"W\d{2}", value)
    return matches[0] if len(matches) == 1 else None


def validate_documents(
    plan: str,
    todo: str,
    trace: str,
    iteration: str,
    legacy_manifest: str,
    adr: str,
    status: str,
    r13: str,
    release_runbook: str,
    w01_evidence: dict[str, object],
    w02_entry: str,
    w02_assembly: str,
) -> list[str]:
    errors: list[str] = []
    expected_task_status = dict(EXPECTED_TASK_STATUS)
    remediation = w01_evidence.get("remediation")
    remediation_technical = (
        remediation.get("technical_source_result")
        if isinstance(remediation, dict)
        else None
    )
    if remediation_technical != "pass":
        errors.append("historical W01 remediation technical result must remain pass")

    marker = re.search(r"<!-- pre1-work-order: ([A-Z0-9,]+) -->", plan)
    actual_order = marker.group(1).split(",") if marker else []
    if actual_order != EXPECTED_ORDER:
        errors.append(f"work order {actual_order!r} != {EXPECTED_ORDER!r}")

    plan_rows = table_rows(plan, r"\d+", 5)
    ranks = [int(row[0]) for row in plan_rows]
    work_ids = [row[1] for row in plan_rows]
    if ranks != list(range(1, 17)):
        errors.append(f"execution ranks {ranks!r} != 1..16")
    if work_ids != EXPECTED_ORDER:
        errors.append(f"ranked table {work_ids!r} != {EXPECTED_ORDER!r}")
    if set(work_ids) != {f"W{number:02d}" for number in range(1, 17)}:
        errors.append("ranked table must contain W01-W16 exactly once")
    for label, text in (("work plan", plan), ("TODO", todo)):
        if text.count(W01_EXIT_MARKER) != 1:
            errors.append(f"{label} must contain the exact W01-to-W02 exit marker once")

    plan_by_work = {row[1]: row for row in plan_rows}
    for work_id, expected in EXPECTED_WORK.items():
        row = plan_by_work.get(work_id)
        if row is None:
            errors.append(f"work plan missing {work_id}")
            continue
        actual_tasks = set(TASK_PATTERN.findall(row[3]))
        actual_gates = set(GATE_PATTERN.findall(row[4]))
        if actual_tasks != expected["tasks"]:
            errors.append(
                f"{work_id} tasks {sorted(actual_tasks)!r} != {sorted(expected['tasks'])!r}"
            )
        if actual_gates != expected["gates"]:
            errors.append(
                f"{work_id} gates {sorted(actual_gates)!r} != {sorted(expected['gates'])!r}"
            )

    todo_rows = table_rows(todo, r"TODO-[A-Z0-9-]+-[0-9]{3}", 7)
    trace_task_rows = table_rows(trace, r"TODO-[A-Z0-9-]+-[0-9]{3}", 6)
    todo_by_task = {row[0]: row for row in todo_rows}
    trace_by_task = {row[0]: row for row in trace_task_rows}
    if len(todo_by_task) != len(todo_rows):
        errors.append("TODO overview contains duplicate task IDs")
    if len(trace_by_task) != len(trace_task_rows):
        errors.append("traceability contains duplicate task IDs")

    expected_task_work = {
        task: work_id
        for work_id, work in EXPECTED_WORK.items()
        for task in work["tasks"]
    }
    for task, expected_work in expected_task_work.items():
        todo_row = todo_by_task.get(task)
        trace_row = trace_by_task.get(task)
        if todo_row is None:
            errors.append(f"TODO overview missing {task}")
            continue
        if trace_row is None:
            errors.append(f"traceability missing {task}")
            continue
        todo_work = only_work_id(todo_row[2])
        trace_work = only_work_id(trace_row[1])
        if todo_work != expected_work:
            errors.append(f"TODO {task} maps to {todo_work!r}, expected {expected_work}")
        if trace_work != expected_work:
            errors.append(f"traceability {task} maps to {trace_work!r}, expected {expected_work}")
        todo_status = normalized_status(todo_row[3])
        trace_status = normalized_status(trace_row[2])
        expected_status = expected_task_status[task]
        if todo_status != expected_status:
            errors.append(f"TODO {task} status {todo_status!r}, expected {expected_status!r}")
        if trace_status != expected_status:
            errors.append(
                f"traceability {task} status {trace_status!r}, expected {expected_status!r}"
            )

    todo_headings = re.findall(r"^### (TODO-[A-Z0-9-]+-[0-9]{3})", todo, re.MULTILINE)
    if len(todo_headings) != len(set(todo_headings)):
        errors.append("TODO headings contain duplicate task IDs")
    if set(todo_headings) != set(todo_by_task):
        errors.append("TODO headings and overview task sets differ")
    if set(todo_headings) != set(trace_by_task):
        errors.append("TODO and traceability task sets differ")

    detail_statuses: dict[str, str] = {}
    heading_matches = list(
        re.finditer(r"^### (TODO-[A-Z0-9-]+-[0-9]{3}).*$", todo, re.MULTILINE)
    )
    for index, match in enumerate(heading_matches):
        end = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(todo)
        block = todo[match.end() : end]
        status_match = re.search(r"^- 状态：`([^`]+)`\s*$", block, re.MULTILINE)
        if status_match:
            detail_statuses[match.group(1)] = status_match.group(1)
    for task, overview_row in todo_by_task.items():
        detail_status = detail_statuses.get(task)
        overview_status = normalized_status(overview_row[3])
        if detail_status is None:
            errors.append(f"TODO detail missing status for {task}")
        elif detail_status != overview_status:
            errors.append(
                f"TODO {task} detail status {detail_status!r} != overview {overview_status!r}"
            )

    requirement_rows = table_rows(trace, r"REQ-[A-Z0-9-]+-[0-9]{3}", 7)
    requirement_ids = [row[0] for row in requirement_rows]
    if len(requirement_ids) != len(set(requirement_ids)):
        errors.append("traceability contains duplicate requirement definitions")
    for requirement in sorted(REQUIRED_REQUIREMENTS - set(requirement_ids)):
        errors.append(f"traceability requirement definition missing {requirement}")

    validation_rows = table_rows(trace, r"VAL-[A-Z0-9-]+-[0-9]{3}", 3)
    validation_by_id = {row[0]: row for row in validation_rows}
    if len(validation_by_id) != len(validation_rows):
        errors.append("traceability contains duplicate validation definitions")
    required_gates = set().union(*(work["gates"] for work in EXPECTED_WORK.values()))
    for gate in sorted(required_gates - set(validation_by_id)):
        errors.append(f"traceability validation definition missing {gate}")
    expected_status_words = {gate: ["not-run"] for gate in FORMAL_NOT_RUN}
    expected_status_words.update(
        {
            "VAL-PACK-001": ["not-run", "pass"],
            "VAL-SECRET-001": ["not-run", "pass"],
        }
    )
    for gate, expected_words in sorted(expected_status_words.items()):
        row = validation_by_id.get(gate)
        if row is None:
            continue
        actual_words = STATUS_WORD_PATTERN.findall(row[2])
        if actual_words != expected_words:
            errors.append(
                f"{gate} status words {actual_words!r} != {expected_words!r}; "
                "gate must remain canonically not-run"
            )

    for gate in ("VAL-PRE1-SEQUENCE-001", "VAL-GOV-001", "VAL-CI-COVERAGE-001"):
        row = validation_by_id.get(gate)
        if row is None:
            continue
        for marker in (
            OLD_REJECTED_TRACE_MARKER,
            CURRENT_W01_TRACE_MARKER,
        ):
            if marker not in row[2]:
                errors.append(f"{gate} lifecycle result missing {marker!r}")

    if not isinstance(remediation, dict):
        errors.append("W01 evidence remediation lifecycle is missing")
    else:
        if remediation.get("independent_acceptance") != "pending":
            errors.append("historical W01 independent acceptance must remain pending")
        activation = remediation.get("canonical_activation")
        if not isinstance(activation, dict) or activation.get("status") != "blocked":
            errors.append("historical W01 canonical activation must remain blocked")
    canonical_main = w01_evidence.get("canonical_main_source")
    if not isinstance(canonical_main, dict) or canonical_main.get("status") != "not-run":
        errors.append("historical W01 canonical-main source result must remain not-run")

    candidate_history = w01_evidence.get("candidate_history")
    rejected = candidate_history[0] if isinstance(candidate_history, list) and candidate_history else None
    if not isinstance(rejected, dict) or rejected.get("source_commit") != (
        "2b7629468c711d0db5107f7001aa90c0271079ae"
    ):
        errors.append("historical W01 rejected final head drifted")
    if not isinstance(rejected, dict) or rejected.get("independent_acceptance") != "fail":
        errors.append("historical W01 rejected acceptance must remain fail")

    if w02_entry.count(W02_ENTRY_AUTHORITY_MARKER) != 1:
        errors.append("W02 entry must contain the exact external authority marker once")
    for marker in sorted(W02_ENTRY_REQUIRED_MARKERS):
        if marker not in w02_entry:
            errors.append(f"W02 entry missing required marker: {marker}")

    if w02_assembly.count(W02_ASSEMBLY_AUTHORITY_MARKER) != 1:
        errors.append("W02 assembly must contain the exact run authority marker once")
    if (
        hashlib.sha256(w02_assembly.encode("utf-8")).hexdigest()
        != W02_ASSEMBLY_DOCUMENT_SHA256
    ):
        errors.append("W02 assembly reviewed document drifted")
    for marker in sorted(W02_ASSEMBLY_REQUIRED_MARKERS):
        if marker not in w02_assembly:
            errors.append(f"W02 assembly missing required marker: {marker}")
    for forbidden in sorted(W02_ASSEMBLY_FORBIDDEN_CLAIMS):
        if forbidden in w02_assembly:
            errors.append(f"W02 assembly contains forbidden claim: {forbidden}")

    r13_status = re.search(r"^- 状态：`([^`]+)`", r13, re.MULTILINE)
    if r13_status is None or r13_status.group(1) != "completed":
        errors.append("R13 status must be completed after external W01 closeout")
    if "- [x] R13-06" not in r13 or "旧候选" not in r13:
        errors.append("R13-06 must preserve the old technical execution as rejected history")
    if "- [x] R13-07" not in r13:
        errors.append("R13-07 must preserve remediation technical closeout")
    if "- [x] R13-08" not in r13:
        errors.append("R13-08 must record external W01 closeout")

    iteration_status = re.search(r"^- 状态：`([^`]+)`", iteration, re.MULTILINE)
    if iteration_status is None or iteration_status.group(1) != "in-progress":
        errors.append("ITER-0008 status must be in-progress while W02 is active")
    for marker in sorted(W02_PHASE_MARKERS):
        if marker not in iteration:
            errors.append(f"ITER-0008 missing W02 phase marker: {marker}")

    continuity_row = validation_by_id.get("VAL-RELEASE-CONTINUITY-001")
    if continuity_row is not None:
        for component in sorted(CONTINUITY_COMPONENTS):
            if component not in continuity_row[1]:
                errors.append(f"release continuity definition missing {component}")

    for label, text in (
        ("TODO", todo),
        ("traceability", trace),
        ("iteration", iteration),
    ):
        for item in sorted(NEW_STABLE_IDS):
            if re.search(rf"(?<![A-Z0-9-]){re.escape(item)}(?![A-Z0-9-])", text) is None:
                errors.append(f"{label} stable ID missing {item}")

    for label, text in (
        ("work plan", plan),
        ("TODO", todo),
        ("traceability", trace),
        ("iteration", iteration),
        ("R13", r13),
        ("status", status),
        ("W02 entry", w02_entry),
        ("W02 assembly", w02_assembly),
    ):
        if re.search(r"(?:REQ|TODO|VAL|ITER)-W02A\b|\bW02A\b", text):
            errors.append(f"{label} must not create a W02A stable ID")

    authority_requirements = {
        "ADR-0016": (adr, {"VAL-RELEASE-CONTINUITY-001", "W13 checkpoint", "W16"}),
        "legacy manifest": (
            legacy_manifest,
            {"W01/W02 退出门禁\n  通过后，按 ADR-0016 的 slice eligibility 独立删除"},
        ),
        "status": (
            status,
            {
                "### 必须保持 `not-run`",
                "VAL-RELEASE-CONTINUITY-001",
                "W16 exact Draft",
                "W01 全部退出",
            },
        ),
        "R13": (
            r13,
            {"| `VAL-RELEASE-CONTINUITY-001` | `not-run` |"},
        ),
        "release runbook": (
            release_runbook,
            {
                "VAL-RELEASE-CONTINUITY-001",
                "continuity verifier/evidence 尚未实现且当前为 `not-run`",
                "现有 workflow 没有 checkpoint 输入",
                "W13 checkpoint",
            },
        ),
    }
    for label, (text, required) in authority_requirements.items():
        for phrase in sorted(required):
            if phrase not in text:
                errors.append(f"{label} missing required release-boundary phrase: {phrase}")

    required_edges = [
        ("W01", "W02"),
        ("W02", "W10"),
        ("W02", "W11"),
        ("W10", "W03"),
        ("W11", "W03"),
        ("W03", "W13"),
        ("W13", "W14"),
        ("W14", "W15"),
        ("W15", "W16"),
    ]
    order_index = {work_id: rank for rank, work_id in enumerate(actual_order)}
    for before, after in required_edges:
        if order_index.get(before, 99) >= order_index.get(after, -1):
            errors.append(f"required edge violated: {before} before {after}")

    if re.search(r"\bE05\b", legacy_manifest):
        errors.append("active legacy manifest must not use superseded ITER-0007 E05 coordinates")

    if "完整替代后删除" in legacy_manifest:
        errors.append("active legacy manifest must not require aggregate replacement before every slice")

    return errors


def main() -> int:
    errors = validate_documents(
        read(PLAN),
        read(TODO),
        read(TRACE),
        read(ITERATION),
        read(LEGACY_MANIFEST),
        read(ADR),
        read(STATUS),
        read(R13),
        read(RELEASE_RUNBOOK),
        json.loads(read(W01_EVIDENCE)),
        read(W02_ENTRY),
        read(W02_ASSEMBLY),
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(
        "pre-1.0 work plan OK: exact ranks, mappings, W02 static assembly evidence, "
        "packaged gate status, and release boundary"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

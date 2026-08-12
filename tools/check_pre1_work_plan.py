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
PARENT_ITERATION = ROOT / "docs/development/iterations/0002-bundled-runtimes.md"
R13 = ROOT / "docs/development/iterations/0002-r13-pre1-incremental-retirement.md"
RELEASE_RUNBOOK = ROOT / "docs/development/desktop-release.md"
EVIDENCE_INDEX = ROOT / "docs/development/evidence/README.md"
W01_EVIDENCE = ROOT / "docs/development/evidence/W01/2026-08-04.json"
W02_ENTRY = ROOT / "docs/development/evidence/W02/2026-08-05-entry.md"
W02_ASSEMBLY = (
    ROOT
    / "docs/development/evidence/W02/2026-08-06-08137c7-assembly.md"
)
W02_REMEDIATION = (
    ROOT
    / "docs/development/evidence/W02/2026-08-07-pr21-remediation.md"
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
    "engineering-smoke boundary/assembly：旧 static technical run 保留；PR #21 independent",
    "acceptance `NO-GO`；第一次至第八次 remediation technical attempts 均为 `fail` / `superseded`",
    "第九 exact candidate `not-run`。旧 exact Draft head",
    "packaged App launch/runtime smoke：八次 remediation 均未启动 bundle，第九 candidate 也尚未运行，\n"
    "    当前 `not-run`",
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

W02_PR21_CONTEXT = "CTX-PR21-NOGO-CURRENT"
W02_PR21_BASE = "1786255b55dd1a78659ed92235893876175a0722"
W02_PR21_REVIEWED_HEAD = "8c5fd23206b671b768fd21d253bf292642f93a51"
W02_PR21_REVIEWED_TREE = "785f4656de8a7233b6dd632fe4815976d33468fb"
W02_PR21_BRANCH = "agent/w02a-engineering-smoke-boundary"
W02_PR21_ASSEMBLY_RUN = "31026905444"
W02_PR21_ASSEMBLY_JOB = "92377586784"
W02_PR21_SOURCE_RUN = "31026907916"
W02_PR21_CONTAINER_RUN = "31026906777"
W02_PR21_FIRST_REMEDIATION_HEAD = "9f7d5d11225517ff5b1643d4bb71983346358ae0"
W02_PR21_FIRST_REMEDIATION_TREE = "ea8e62e9b76c3270d60135a8633f56db025ad921"
W02_PR21_FIRST_REMEDIATION_ASSEMBLY_RUN = "31181911570"
W02_PR21_FIRST_REMEDIATION_ASSEMBLY_JOB = "92876982671"
W02_PR21_FIRST_REMEDIATION_SOURCE_RUN = "31181911534"
W02_PR21_FIRST_REMEDIATION_CONTAINER_RUN = "31181911527"
W02_PR21_SECOND_REMEDIATION_HEAD = "9ecf0effaa48a8b010ff46ffb42afc57e0f3d948"
W02_PR21_SECOND_REMEDIATION_TREE = "ee82712c7874155eba038d1ce05d374416ed34e5"
W02_PR21_SECOND_REMEDIATION_ASSEMBLY_RUN = "31184441362"
W02_PR21_SECOND_REMEDIATION_ASSEMBLY_JOB = "92885372402"
W02_PR21_SECOND_REMEDIATION_SOURCE_RUN = "31184441306"
W02_PR21_SECOND_REMEDIATION_CONTAINER_RUN = "31184441281"
W02_PR21_THIRD_REMEDIATION_HEAD = "2665ec61712fe410608ac50c7a6d44fa35746092"
W02_PR21_THIRD_REMEDIATION_TREE = "c3cd1706838f7050533e2812dfdcad482aaedde5"
W02_PR21_THIRD_REMEDIATION_ASSEMBLY_RUN = "31258135925"
W02_PR21_THIRD_REMEDIATION_ASSEMBLY_JOB = "93104615763"
W02_PR21_THIRD_REMEDIATION_SOURCE_RUN = "31258135929"
W02_PR21_THIRD_REMEDIATION_CONTAINER_RUN = "31258135932"
W02_PR21_FOURTH_REMEDIATION_HEAD = "c2be665f5832c15064cae87c694a782e51351e7c"
W02_PR21_FOURTH_REMEDIATION_TREE = "f90b527b4de1a422f63c4bfeb01f9c1010e22b7d"
W02_PR21_FOURTH_REMEDIATION_ASSEMBLY_RUN = "31358373320"
W02_PR21_FOURTH_REMEDIATION_ASSEMBLY_JOB = "93362214499"
W02_PR21_FOURTH_REMEDIATION_SOURCE_RUN = "31358373316"
W02_PR21_FOURTH_REMEDIATION_CONTAINER_RUN = "31358373311"
W02_PR21_FIFTH_REMEDIATION_HEAD = "c04fe9fce2bc2f0f4350e080f7f02c44699c975d"
W02_PR21_FIFTH_REMEDIATION_PARENT = "c2be665f5832c15064cae87c694a782e51351e7c"
W02_PR21_FIFTH_REMEDIATION_TREE = "2f8b3aceb4caa2d71537cd51c3b3b985c55a3db5"
W02_PR21_FIFTH_REMEDIATION_ASSEMBLY_RUN = "31454826263"
W02_PR21_FIFTH_REMEDIATION_ASSEMBLY_JOB = "93666344718"
W02_PR21_FIFTH_REMEDIATION_SOURCE_RUN = "31454826261"
W02_PR21_FIFTH_REMEDIATION_SOURCE_JOB = "93666344561"
W02_PR21_FIFTH_REMEDIATION_CONTAINER_RUN = "31454826243"
W02_PR21_SIXTH_REMEDIATION_HEAD = "cc6ade1113d4753cc6094c5ee23a588dbbe8c18e"
W02_PR21_SIXTH_REMEDIATION_PARENT = "c04fe9fce2bc2f0f4350e080f7f02c44699c975d"
W02_PR21_SIXTH_REMEDIATION_TREE = "911e91d6849266fa75b0efde794ae9b5236f5504"
W02_PR21_SIXTH_REMEDIATION_CONTEXT = "d01c1b4d9ea2c5f77605859a9af8137580b52d8e"
W02_PR21_SIXTH_REMEDIATION_SOURCE_SNAPSHOT_SHA256 = (
    "dfed1f824a60ebcfb0e8e9facfb46e5552f412b273cb58979596eb3c26d97884"
)
W02_PR21_SIXTH_REMEDIATION_ASSEMBLY_RUN = "31460588223"
W02_PR21_SIXTH_REMEDIATION_ASSEMBLY_JOB = "93683139742"
W02_PR21_SIXTH_REMEDIATION_SOURCE_RUN = "31460588210"
W02_PR21_SIXTH_REMEDIATION_CONTAINER_RUN = "31460588212"
W02_PR21_SEVENTH_REMEDIATION_HEAD = "aaf3f51f69dfded82b8237e03a871017317e7158"
W02_PR21_SEVENTH_REMEDIATION_PARENT = "cc6ade1113d4753cc6094c5ee23a588dbbe8c18e"
W02_PR21_SEVENTH_REMEDIATION_TREE = "60c2c6c2553ff8d10c2faee47ec838b34e378fc5"
W02_PR21_SEVENTH_REMEDIATION_CONTEXT = "6f9a15f65301acd898109203c0ad9381d7290539"
W02_PR21_SEVENTH_REMEDIATION_ASSEMBLY_RUN = "31559498116"
W02_PR21_SEVENTH_REMEDIATION_ASSEMBLY_JOB = "93998717925"
W02_PR21_SEVENTH_REMEDIATION_SOURCE_RUN = "31559498106"
W02_PR21_SEVENTH_REMEDIATION_CONTAINER_RUN = "31559498070"
W02_PR21_EIGHTH_REMEDIATION_HEAD = "15336568c6fcf3a40eb051cdb2b90242ef1e1e09"
W02_PR21_EIGHTH_REMEDIATION_PARENT = "aaf3f51f69dfded82b8237e03a871017317e7158"
W02_PR21_EIGHTH_REMEDIATION_TREE = "66779e9ca8df445fb413e93faed4d265899fb1ec"
W02_PR21_EIGHTH_REMEDIATION_CONTEXT = "1c662735da0306027ec54641b8706130cf6b91dc"
W02_PR21_EIGHTH_REMEDIATION_ASSEMBLY_RUN = "31570734636"
W02_PR21_EIGHTH_REMEDIATION_ASSEMBLY_JOB = "94031972543"
W02_PR21_EIGHTH_REMEDIATION_SOURCE_RUN = "31570734560"
W02_PR21_EIGHTH_REMEDIATION_CONTAINER_RUN = "31570734580"
W02_PR21_AUTHORITY_MARKER = (
    "<!-- w02-pr21-nogo-authority: "
    f"context={W02_PR21_CONTEXT},base={W02_PR21_BASE},"
    f"merge-base={W02_PR21_BASE},reviewed-head={W02_PR21_REVIEWED_HEAD},"
    f"reviewed-tree={W02_PR21_REVIEWED_TREE},branch={W02_PR21_BRANCH},"
    "commits=26,files=54,additions=11527,deletions=392,"
    f"assembly-run={W02_PR21_ASSEMBLY_RUN},"
    f"assembly-job={W02_PR21_ASSEMBLY_JOB},source-run={W02_PR21_SOURCE_RUN},"
    f"container-run={W02_PR21_CONTAINER_RUN},decision=NO-GO -->"
)
W02_PR21_FIRST_REMEDIATION_AUTHORITY_MARKER = (
    "<!-- w02-pr21-first-remediation-authority: "
    f"source={W02_PR21_FIRST_REMEDIATION_HEAD},"
    f"tree={W02_PR21_FIRST_REMEDIATION_TREE},"
    f"assembly-run={W02_PR21_FIRST_REMEDIATION_ASSEMBLY_RUN},"
    f"assembly-job={W02_PR21_FIRST_REMEDIATION_ASSEMBLY_JOB},"
    f"source-run={W02_PR21_FIRST_REMEDIATION_SOURCE_RUN},"
    f"container-run={W02_PR21_FIRST_REMEDIATION_CONTAINER_RUN},result=fail -->"
)
W02_PR21_SECOND_REMEDIATION_AUTHORITY_MARKER = (
    "<!-- w02-pr21-second-remediation-authority: "
    f"source={W02_PR21_SECOND_REMEDIATION_HEAD},"
    f"tree={W02_PR21_SECOND_REMEDIATION_TREE},"
    f"assembly-run={W02_PR21_SECOND_REMEDIATION_ASSEMBLY_RUN},"
    f"assembly-job={W02_PR21_SECOND_REMEDIATION_ASSEMBLY_JOB},"
    f"source-run={W02_PR21_SECOND_REMEDIATION_SOURCE_RUN},"
    f"container-run={W02_PR21_SECOND_REMEDIATION_CONTAINER_RUN},result=fail -->"
)
W02_PR21_THIRD_REMEDIATION_AUTHORITY_MARKER = (
    "<!-- w02-pr21-third-remediation-authority: "
    f"source={W02_PR21_THIRD_REMEDIATION_HEAD},"
    f"tree={W02_PR21_THIRD_REMEDIATION_TREE},"
    f"assembly-run={W02_PR21_THIRD_REMEDIATION_ASSEMBLY_RUN},"
    f"assembly-job={W02_PR21_THIRD_REMEDIATION_ASSEMBLY_JOB},"
    f"source-run={W02_PR21_THIRD_REMEDIATION_SOURCE_RUN},"
    f"container-run={W02_PR21_THIRD_REMEDIATION_CONTAINER_RUN},result=fail -->"
)
W02_PR21_FOURTH_REMEDIATION_AUTHORITY_MARKER = (
    "<!-- w02-pr21-fourth-remediation-authority: "
    f"source={W02_PR21_FOURTH_REMEDIATION_HEAD},"
    f"tree={W02_PR21_FOURTH_REMEDIATION_TREE},"
    f"assembly-run={W02_PR21_FOURTH_REMEDIATION_ASSEMBLY_RUN},"
    f"assembly-job={W02_PR21_FOURTH_REMEDIATION_ASSEMBLY_JOB},"
    f"source-run={W02_PR21_FOURTH_REMEDIATION_SOURCE_RUN},"
    f"container-run={W02_PR21_FOURTH_REMEDIATION_CONTAINER_RUN},result=fail -->"
)
W02_PR21_FIFTH_REMEDIATION_AUTHORITY_MARKER = (
    "<!-- w02-pr21-fifth-remediation-authority: "
    f"source={W02_PR21_FIFTH_REMEDIATION_HEAD},"
    f"parent={W02_PR21_FIFTH_REMEDIATION_PARENT},"
    f"tree={W02_PR21_FIFTH_REMEDIATION_TREE},"
    f"assembly-run={W02_PR21_FIFTH_REMEDIATION_ASSEMBLY_RUN},"
    f"assembly-job={W02_PR21_FIFTH_REMEDIATION_ASSEMBLY_JOB},"
    f"source-run={W02_PR21_FIFTH_REMEDIATION_SOURCE_RUN},"
    f"source-job={W02_PR21_FIFTH_REMEDIATION_SOURCE_JOB},"
    f"container-run={W02_PR21_FIFTH_REMEDIATION_CONTAINER_RUN},result=fail -->"
)
W02_PR21_SIXTH_REMEDIATION_AUTHORITY_MARKER = (
    "<!-- w02-pr21-sixth-remediation-authority: "
    f"source={W02_PR21_SIXTH_REMEDIATION_HEAD},"
    f"parent={W02_PR21_SIXTH_REMEDIATION_PARENT},"
    f"tree={W02_PR21_SIXTH_REMEDIATION_TREE},"
    f"assembly-run={W02_PR21_SIXTH_REMEDIATION_ASSEMBLY_RUN},"
    f"assembly-job={W02_PR21_SIXTH_REMEDIATION_ASSEMBLY_JOB},"
    f"source-run={W02_PR21_SIXTH_REMEDIATION_SOURCE_RUN},"
    f"container-run={W02_PR21_SIXTH_REMEDIATION_CONTAINER_RUN},result=fail -->"
)
W02_PR21_SEVENTH_REMEDIATION_AUTHORITY_MARKER = (
    "<!-- w02-pr21-seventh-remediation-authority: "
    f"source={W02_PR21_SEVENTH_REMEDIATION_HEAD},"
    f"parent={W02_PR21_SEVENTH_REMEDIATION_PARENT},"
    f"tree={W02_PR21_SEVENTH_REMEDIATION_TREE},"
    f"context={W02_PR21_SEVENTH_REMEDIATION_CONTEXT},"
    f"assembly-run={W02_PR21_SEVENTH_REMEDIATION_ASSEMBLY_RUN},"
    f"assembly-job={W02_PR21_SEVENTH_REMEDIATION_ASSEMBLY_JOB},"
    f"source-run={W02_PR21_SEVENTH_REMEDIATION_SOURCE_RUN},"
    f"container-run={W02_PR21_SEVENTH_REMEDIATION_CONTAINER_RUN},result=fail -->"
)
W02_PR21_EIGHTH_REMEDIATION_AUTHORITY_MARKER = (
    "<!-- w02-pr21-eighth-remediation-authority: "
    f"source={W02_PR21_EIGHTH_REMEDIATION_HEAD},"
    f"parent={W02_PR21_EIGHTH_REMEDIATION_PARENT},"
    f"tree={W02_PR21_EIGHTH_REMEDIATION_TREE},"
    f"context={W02_PR21_EIGHTH_REMEDIATION_CONTEXT},"
    f"assembly-run={W02_PR21_EIGHTH_REMEDIATION_ASSEMBLY_RUN},"
    f"assembly-job={W02_PR21_EIGHTH_REMEDIATION_ASSEMBLY_JOB},"
    f"source-run={W02_PR21_EIGHTH_REMEDIATION_SOURCE_RUN},"
    f"container-run={W02_PR21_EIGHTH_REMEDIATION_CONTAINER_RUN},result=fail -->"
)
W02_PR21_FIFTH_ROOT_CAUSE_LIMIT_MARKER = (
    "这是高置信代码/时序归因，不是 raw log 直接输出的\n"
    "binding root cause"
)
W02_PR21_SIXTH_PRECOMMIT_NOT_RUN_MARKER = (
    "| PR #21 sixth remediation technical candidate | `not-run`"
)
W02_PR21_SEVENTH_PRECOMMIT_NOT_RUN_MARKER = (
    "| PR #21 seventh remediation technical candidate | `not-run`"
)
W02_PR21_SEVENTH_NOT_RUN_MARKER = W02_PR21_SEVENTH_PRECOMMIT_NOT_RUN_MARKER
W02_PR21_EIGHTH_PRECOMMIT_NOT_RUN_MARKER = (
    "第八次 remediation technical candidate：`not-run`"
)
W02_PR21_EIGHTH_NOT_RUN_MARKER = W02_PR21_EIGHTH_PRECOMMIT_NOT_RUN_MARKER
W02_PR21_NINTH_NOT_RUN_MARKER = (
    "第九次 remediation technical candidate：`not-run`"
)
W02_PR21_REMEDIATION_DOCUMENT_SHA256 = (
    "49a24644d98de7295f3c32562d965425ba34fea26fb208642b6d942b15da9c13"
)
W02_PR21_REMEDIATION_REQUIRED_MARKERS = {
    "PR #21 independent NO-GO 与 remediation 交接",
    f"| context | `{W02_PR21_CONTEXT}` |",
    f"| base / merge-base | `{W02_PR21_BASE}` |",
    f"| branch | `{W02_PR21_BRANCH}` |",
    f"| independently reviewed head | `{W02_PR21_REVIEWED_HEAD}` |",
    f"| independently reviewed tree | `{W02_PR21_REVIEWED_TREE}` |",
    "| reviewed topology | `26` commits；`54` changed files；`11527` additions / `392` deletions |",
    f"run `{W02_PR21_ASSEMBLY_RUN}`",
    f"job `{W02_PR21_ASSEMBLY_JOB}`",
    f"run `{W02_PR21_SOURCE_RUN}`",
    f"run `{W02_PR21_CONTAINER_RUN}`",
    "| independent decision | **`NO-GO`** |",
    "`H1 build scratch lifecycle / held dirfd / inode binding / publish / cleanup`",
    "`LCF_GITHUB_CONTEXT_SHA` 设为 PR context",
    "`fb3079b851362e2cdb8a6db21c2e071b9b07a842`",
    "job 末尾三条 `Post job cleanup` 属于 setup-python、setup-node 与 checkout action 的 post",
    "backend pytest `450` passed、Host Runner `8` tests、demo SDK `3` passed、tools unittest `152`",
    "QMD `10` passed / `1` allowlisted skip",
    "旧 PR body 的 `595 passed, 1 skipped` 聚合不能",
    "不得迁移为新 head\n的 `pass`",
    f"| exact head | `{W02_PR21_FIRST_REMEDIATION_HEAD}` |",
    f"| exact tree | `{W02_PR21_FIRST_REMEDIATION_TREE}` |",
    f"run `{W02_PR21_FIRST_REMEDIATION_ASSEMBLY_RUN}`",
    f"job `{W02_PR21_FIRST_REMEDIATION_ASSEMBLY_JOB}`",
    f"run `{W02_PR21_FIRST_REMEDIATION_SOURCE_RUN}`",
    f"run `{W02_PR21_FIRST_REMEDIATION_CONTAINER_RUN}`",
    "`Installed toolchain symlink is unsafe`",
    "| technical result | **`fail`**；第一次 remediation attempt 已 `superseded` |",
    "| PR #21 first remediation technical attempt | `fail` / `superseded`",
    f"| exact head | `{W02_PR21_SECOND_REMEDIATION_HEAD}` |",
    f"| exact tree | `{W02_PR21_SECOND_REMEDIATION_TREE}` |",
    f"run `{W02_PR21_SECOND_REMEDIATION_ASSEMBLY_RUN}`",
    f"job `{W02_PR21_SECOND_REMEDIATION_ASSEMBLY_JOB}`",
    f"run `{W02_PR21_SECOND_REMEDIATION_SOURCE_RUN}`",
    f"run `{W02_PR21_SECOND_REMEDIATION_CONTAINER_RUN}`",
    "`Installed toolchain file is unsafe`",
    "Python 为 `744` passed / `2` failed / `1` skipped /\n`2` warnings",
    "W01 evidence job 仍按 `always()` 运行并 fail closed",
    "| technical result | **`fail`**；第二次 remediation attempt 已 `superseded` |",
    "| PR #21 second remediation technical attempt | `fail` / `superseded`",
    "第三次 remediation candidate 的 producer 私有化边界：`not-run`",
    "**producer output privatization**",
    "Darwin `RENAME_SWAP` / Linux `RENAME_EXCHANGE`",
    "group/world-writable hardlink、atomic exchange 不可用",
    "technical result 在 fresh exact-head source/assembly 完成前仍是 `not-run`",
    f"| exact head | `{W02_PR21_THIRD_REMEDIATION_HEAD}` |",
    f"| exact tree | `{W02_PR21_THIRD_REMEDIATION_TREE}` |",
    f"run `{W02_PR21_THIRD_REMEDIATION_ASSEMBLY_RUN}`",
    f"job `{W02_PR21_THIRD_REMEDIATION_ASSEMBLY_JOB}`",
    f"run `{W02_PR21_THIRD_REMEDIATION_SOURCE_RUN}`",
    f"run `{W02_PR21_THIRD_REMEDIATION_CONTAINER_RUN}`",
    "`Exact uv runtime export failed`",
    "payload artifact `9022014613` 与 provenance artifact\n`9022014784`",
    "API 与 MCP jobs success",
    "| technical result | **`fail`**；第三次 remediation attempt 已 `superseded` |",
    "| PR #21 third remediation technical attempt | `fail` / `superseded`",
    "| PR #21 next exact remediation technical candidate | `not-run`",
    "第四次 remediation 技术执行：`fail` / `superseded`",
    f"| exact head | `{W02_PR21_FOURTH_REMEDIATION_HEAD}` |",
    f"| exact tree | `{W02_PR21_FOURTH_REMEDIATION_TREE}` |",
    f"run `{W02_PR21_FOURTH_REMEDIATION_ASSEMBLY_RUN}`",
    f"job `{W02_PR21_FOURTH_REMEDIATION_ASSEMBLY_JOB}`",
    f"run `{W02_PR21_FOURTH_REMEDIATION_SOURCE_RUN}`",
    f"run `{W02_PR21_FOURTH_REMEDIATION_CONTAINER_RUN}`",
    "`Exact Python sidecar inner build failed (exit=2; category=unclassified)`",
    "cleanup-only `always()` gate 也以 exit `1` 失败",
    "Actions 原始日志直接证明的是 inner `exit=2/category=unclassified` 与随后 cleanup gate `exit=1`",
    "Apple APFS reference 把 directory `nchildren` 定义为全部\n   directory entries",
    "没有找到公开 Apple/XNU source 对 `nchildren` 到 POSIX `st_nlink` 的直接",
    "source snapshot 已密封为 `0500`",
    "| technical result | **`fail`**；第四次 remediation attempt 已 `superseded` |",
    "| PR #21 fourth remediation technical attempt | `fail` / `superseded`",
    "第五次 remediation 技术执行：`fail` / `superseded`",
    f"| exact head | `{W02_PR21_FIFTH_REMEDIATION_HEAD}` |",
    f"| exact parent | `{W02_PR21_FIFTH_REMEDIATION_PARENT}` |",
    f"| exact tree | `{W02_PR21_FIFTH_REMEDIATION_TREE}` |",
    f"run `{W02_PR21_FIFTH_REMEDIATION_ASSEMBLY_RUN}`",
    f"job `{W02_PR21_FIFTH_REMEDIATION_ASSEMBLY_JOB}`",
    f"run `{W02_PR21_FIFTH_REMEDIATION_SOURCE_RUN}`",
    f"job `{W02_PR21_FIFTH_REMEDIATION_SOURCE_JOB}`",
    f"run `{W02_PR21_FIFTH_REMEDIATION_CONTAINER_RUN}`",
    "测试在 `0500` directory 中创建 `state` fixture 时已失败，尚未调用被测\nproduct cleanup",
    W02_PR21_FIFTH_ROOT_CAUSE_LIMIT_MARKER,
    "日志未记录 launcher 替换前后的 identity 或专用因果 enum",
    "| technical result | **`fail`**；第五次 remediation attempt 已 `superseded` |",
    "| PR #21 fifth remediation technical attempt | `fail` / `superseded`",
    "第六次 remediation technical candidate：`not-run`",
    W02_PR21_SIXTH_PRECOMMIT_NOT_RUN_MARKER,
    "无 committed exact head/tree；无 fresh exact-head Actions",
    "rebind/fixture focused tests `18 passed`",
    "packaging corpus `545 passed / 2 skipped`",
    "backend source suite `809 passed / 3 skipped`",
    "pre-1 policy/checker corpus `211 tests`",
    "| local validation date | `2026-08-11` |",
    "| local baseline | `HEAD c04fe9fce2bc2f0f4350e080f7f02c44699c975d` + 当前未提交的 `14` 个 tracked file bytes",
    "| local environment | `Linux 6.18.35 x86_64`；CPython `3.12.13` |",
    "不是 committed exact-head\nActions、macOS framework installer 或 packaged App launch/runtime evidence",
    "本地完整 Python packaging corpus 为 `533 passed / 2 skipped`",
    "两个 skip 分别是 foreign-owner\nfilesystem capability case 与 Darwin/APFS 真机 case，在当前 Linux 环境 `not-run`",
    "第六次 remediation 技术执行：`fail` / `superseded`",
    f"| exact head | `{W02_PR21_SIXTH_REMEDIATION_HEAD}` |",
    f"| exact parent | `{W02_PR21_SIXTH_REMEDIATION_PARENT}` |",
    f"| exact tree | `{W02_PR21_SIXTH_REMEDIATION_TREE}` |",
    f"| synthetic PR context SHA | `{W02_PR21_SIXTH_REMEDIATION_CONTEXT}` |",
    (
        "| committed-source snapshot SHA-256 | "
        f"`{W02_PR21_SIXTH_REMEDIATION_SOURCE_SNAPSHOT_SHA256}` |"
    ),
    f"run `{W02_PR21_SIXTH_REMEDIATION_ASSEMBLY_RUN}`",
    f"job `{W02_PR21_SIXTH_REMEDIATION_ASSEMBLY_JOB}`",
    f"run `{W02_PR21_SIXTH_REMEDIATION_SOURCE_RUN}`",
    f"run `{W02_PR21_SIXTH_REMEDIATION_CONTAINER_RUN}`",
    "packaged-smoke policy `67/67`",
    "exact-Git test `1/1`",
    "`Reviewed Python installer launcher is unsafe`",
    "cleanup-only `always()` step\n成功",
    "focused lifecycle tests 全部 skipped",
    "remote engineering product artifacts 为 `[]`",
    "| technical result | **`fail`**；第六次 remediation attempt 已 `superseded` |",
    "Desktop source run `31460588210` 的预期 jobs 全部 success",
    "Containers run\n`31460588212` 也成功，但 PR 路径保持 no publish",
    "第七次 remediation technical candidate：`not-run`",
    W02_PR21_SEVENTH_PRECOMMIT_NOT_RUN_MARKER,
    "六次\nremediation attempts `fail` / `superseded` 与第七次 exact candidate `not-run`",
    "第七次 remediation 技术执行：`fail` / `superseded`",
    f"| exact head | `{W02_PR21_SEVENTH_REMEDIATION_HEAD}` |",
    f"| exact parent | `{W02_PR21_SEVENTH_REMEDIATION_PARENT}` |",
    f"| exact tree | `{W02_PR21_SEVENTH_REMEDIATION_TREE}` |",
    f"| synthetic PR context SHA | `{W02_PR21_SEVENTH_REMEDIATION_CONTEXT}`",
    f"run `{W02_PR21_SEVENTH_REMEDIATION_ASSEMBLY_RUN}`",
    f"job `{W02_PR21_SEVENTH_REMEDIATION_ASSEMBLY_JOB}`",
    f"run `{W02_PR21_SEVENTH_REMEDIATION_SOURCE_RUN}`",
    f"run `{W02_PR21_SEVENTH_REMEDIATION_CONTAINER_RUN}`",
    "digest 加一个 ASCII 空格",
    "workflow 当时错误期待小写 digest 加两个空格",
    "cleanup-only `always()` gate 却无条件解引用该 success-only 环境变量",
    "| technical result | **`fail`**；第七次 remediation attempt 已 `superseded` |",
    W02_PR21_EIGHTH_NOT_RUN_MARKER,
    "它尚无 committed exact head/tree 或 fresh exact-head Actions",
    "第八候选仍为\n`not-run`",
    "第八候选 pre-commit local validation",
    "| local baseline | `HEAD aaf3f51f69dfded82b8237e03a871017317e7158` / tree `60c2c6c2553ff8d10c2faee47ec838b34e378fc5` + 未提交 `15`-file bytes",
    "direct checker pass、`53/53`",
    "默认 uv cache\n`/root/.cache/uv` 为只读",
    "| latest independent acceptance | `NO-GO`（仍绑定旧 `8c5fd…` / `785f46…`）；本候选 `pending` |",
    "| latest independent acceptance | `NO-GO`",
    "| W02 | `in-progress` |",
    "| `VAL-PACKAGED-SMOKE-001` | `not-run` |",
    "| W10/W11 | `locked` |",
    "| packaged App / bundle sidecar launch | `not-run` |",
    "| public release | `NO-GO` |",
    "第八次 remediation 技术执行：`fail` / `superseded`",
    f"| exact head | `{W02_PR21_EIGHTH_REMEDIATION_HEAD}` |",
    f"| exact parent | `{W02_PR21_EIGHTH_REMEDIATION_PARENT}` |",
    f"| exact tree | `{W02_PR21_EIGHTH_REMEDIATION_TREE}` |",
    f"| synthetic PR context SHA | `{W02_PR21_EIGHTH_REMEDIATION_CONTEXT}`",
    f"run `{W02_PR21_EIGHTH_REMEDIATION_ASSEMBLY_RUN}`",
    f"job `{W02_PR21_EIGHTH_REMEDIATION_ASSEMBLY_JOB}`",
    f"run `{W02_PR21_EIGHTH_REMEDIATION_SOURCE_RUN}`",
    f"run `{W02_PR21_EIGHTH_REMEDIATION_CONTAINER_RUN}`",
    "root-owned、不可由\n普通 runner 遍历的 `.lcf-python-quarantine.*` 空目录",
    "该 system-root quarantine\nresidue cleanup 明确为 `not-proven`",
    "success-only source provenance、renderer、Desktop profile、static assembly/bundle audit 与 focused\nlifecycle tests 全部 skipped",
    "assembled App 未启动",
    "| technical result | **`fail`**；第八次 remediation attempt 已 `superseded` |",
    W02_PR21_NINTH_NOT_RUN_MARKER,
    "第九候选 pre-commit local validation",
    "`HEAD 15336568c6fcf3a40eb051cdb2b90242ef1e1e09` / tree\n"
    "`66779e9ca8df445fb413e93faed4d265899fb1ec` 加当前 scoped `15`-file worktree",
    "placeholder state 在 EXIT trap 注册前覆盖 inherited values",
    "policy mutation `80/80`、exact-Git `1/1`",
    "direct checker pass、`55/55`",
    "当前汇总是八次 remediation attempts `fail` / `superseded` 与第九次 exact candidate `not-run`",
}
W02_PR21_REMEDIATION_FORBIDDEN_CLAIMS = {
    "decision=GO",
    "| independent acceptance | `pass`",
    "| latest independent acceptance | `pass`",
    "| W02 | `completed`",
    "| `VAL-PACKAGED-SMOKE-001` | `pass`",
    "| W10/W11 | `unlocked`",
    "| packaged App / bundle sidecar launch | `pass`",
    "| public release | `GO`",
    "| PR #21 sixth remediation technical candidate | `pass`",
    "| PR #21 sixth remediation technical attempt | `pass`",
    "| PR #21 seventh remediation technical candidate | `pass`",
    "| PR #21 seventh remediation technical attempt | `pass`",
    "| PR #21 eighth remediation technical candidate | `pass`",
    "第八次 remediation technical candidate：`pass`",
    "| PR #21 eighth remediation technical attempt | `pass`",
    "| PR #21 ninth remediation technical candidate | `pass`",
    "第九次 remediation technical candidate：`pass`",
    "raw log 直接证明 binding root cause",
}

W02_STATUS_CURRENT_SUMMARY = (
    "| 当前结论 | **W02 in-progress：latest independent `NO-GO`（仅绑定旧 reviewed "
    "head/tree）；eight remediation attempts `fail` / `superseded`；ninth exact "
    "candidate `not-run`（current worktree / pre-commit；无 committed exact head/tree；无 fresh exact-head Actions）；"
    "packaged launch/runtime `not-run`；W10/W11 locked；public release NO-GO** |"
)

W02_CURRENT_GOVERNANCE_REQUIREMENTS = {
    "work plan": {
        "evidence/W02/2026-08-07-pr21-remediation.md",
        "reviewed `8c5fd232…` / tree `785f4656…`",
        "独立判定为 `NO-GO`",
        W02_PR21_EIGHTH_REMEDIATION_HEAD,
        W02_PR21_EIGHTH_REMEDIATION_PARENT,
        W02_PR21_EIGHTH_REMEDIATION_TREE,
        "第八次已 technical `fail` / `superseded`",
        "第九次 exact\n  remediation technical candidate 是 current worktree / pre-commit，`not-run`",
        "`VAL-PACKAGED-SMOKE-001` 仍为 `not-run`",
    },
    "TODO": {
        W02_PR21_REVIEWED_HEAD,
        W02_PR21_REVIEWED_TREE,
        "独立判定为 `NO-GO`",
        "first remediation technical attempt `fail` / `superseded`",
        W02_PR21_EIGHTH_REMEDIATION_HEAD,
        W02_PR21_EIGHTH_REMEDIATION_PARENT,
        W02_PR21_EIGHTH_REMEDIATION_TREE,
        "eighth remediation exact",
        "ninth exact remediation technical candidate is\ncurrent worktree / pre-commit and remains `not-run`",
        "W10/W11 保持 locked",
    },
    "traceability": {
        W02_PR21_REVIEWED_HEAD,
        W02_PR21_REVIEWED_TREE,
        "independent `NO-GO`",
        W02_PR21_EIGHTH_REMEDIATION_HEAD,
        W02_PR21_EIGHTH_REMEDIATION_PARENT,
        W02_PR21_EIGHTH_REMEDIATION_TREE,
        "first through eighth remediations technical `fail` / `superseded`",
        "ninth exact candidate `not-run`",
        "W10/W11 locked",
    },
    "iteration": {
        W02_PR21_REVIEWED_HEAD,
        W02_PR21_REVIEWED_TREE,
        "latest independent `NO-GO`",
        W02_PR21_EIGHTH_REMEDIATION_HEAD,
        W02_PR21_EIGHTH_REMEDIATION_PARENT,
        W02_PR21_EIGHTH_REMEDIATION_TREE,
        "同样 technical `fail` / `superseded`；第九次 exact",
        "ninth exact remediation technical candidate | `not-run`",
        "W10/W11 保持 locked",
    },
    "status": {
        W02_PR21_REVIEWED_HEAD,
        W02_PR21_REVIEWED_TREE,
        "latest independent `NO-GO`",
        W02_PR21_EIGHTH_REMEDIATION_HEAD,
        W02_PR21_EIGHTH_REMEDIATION_PARENT,
        W02_PR21_EIGHTH_REMEDIATION_TREE,
        "eight remediation attempts `fail` / `superseded`",
        "ninth exact candidate `not-run`",
        "W10/W11 locked",
        "public release NO-GO",
    },
    "evidence index": {
        W02_PR21_REVIEWED_HEAD,
        W02_PR21_REVIEWED_TREE,
        "independent `NO-GO`",
        "first through eighth remediation technical attempts `fail` / `superseded`",
        W02_PR21_EIGHTH_REMEDIATION_HEAD,
        W02_PR21_EIGHTH_REMEDIATION_PARENT,
        W02_PR21_EIGHTH_REMEDIATION_TREE,
        "ninth exact candidate `not-run`",
        "W10/W11 locked",
    },
    "parent iteration": {
        "reviewed `8c5fd232…` / tree `785f4656…`",
        "independent `NO-GO`",
        "first through eighth attempts `fail` / `superseded`",
        "ninth `not-run`",
        "latest failed `1533656…` / parent `aaf3f51…` / tree `66779e9…`",
        "W10/W11 locked",
    },
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
    w02_remediation: str,
    evidence_index: str,
    parent_iteration: str,
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

    if w02_remediation.count(W02_PR21_AUTHORITY_MARKER) != 1:
        errors.append("W02 PR #21 remediation must contain the exact NO-GO authority marker once")
    if w02_remediation.count(W02_PR21_FIRST_REMEDIATION_AUTHORITY_MARKER) != 1:
        errors.append(
            "W02 PR #21 remediation must contain the exact first-attempt authority marker once"
        )
    if w02_remediation.count(W02_PR21_SECOND_REMEDIATION_AUTHORITY_MARKER) != 1:
        errors.append(
            "W02 PR #21 remediation must contain the exact second-attempt authority marker once"
        )
    if w02_remediation.count(W02_PR21_THIRD_REMEDIATION_AUTHORITY_MARKER) != 1:
        errors.append(
            "W02 PR #21 remediation must contain the exact third-attempt authority marker once"
        )
    if w02_remediation.count(W02_PR21_FOURTH_REMEDIATION_AUTHORITY_MARKER) != 1:
        errors.append(
            "W02 PR #21 remediation must contain the exact fourth-attempt authority marker once"
        )
    if w02_remediation.count(W02_PR21_FIFTH_REMEDIATION_AUTHORITY_MARKER) != 1:
        errors.append(
            "W02 PR #21 remediation must contain the exact fifth-attempt authority marker once"
        )
    if w02_remediation.count(W02_PR21_SIXTH_REMEDIATION_AUTHORITY_MARKER) != 1:
        errors.append(
            "W02 PR #21 remediation must contain the exact sixth-attempt authority marker once"
        )
    if w02_remediation.count(W02_PR21_SEVENTH_REMEDIATION_AUTHORITY_MARKER) != 1:
        errors.append(
            "W02 PR #21 remediation must contain the exact seventh-attempt authority marker once"
        )
    if w02_remediation.count(W02_PR21_EIGHTH_REMEDIATION_AUTHORITY_MARKER) != 1:
        errors.append(
            "W02 PR #21 remediation must contain the exact eighth-attempt authority marker once"
        )
    if (
        hashlib.sha256(w02_remediation.encode("utf-8")).hexdigest()
        != W02_PR21_REMEDIATION_DOCUMENT_SHA256
    ):
        errors.append("W02 PR #21 remediation reviewed document drifted")
    for marker in sorted(W02_PR21_REMEDIATION_REQUIRED_MARKERS):
        if marker not in w02_remediation:
            errors.append(f"W02 PR #21 remediation missing required marker: {marker}")
    for forbidden in sorted(W02_PR21_REMEDIATION_FORBIDDEN_CLAIMS):
        if forbidden in w02_remediation:
            errors.append(f"W02 PR #21 remediation contains forbidden claim: {forbidden}")

    current_governance_documents = {
        "work plan": plan,
        "TODO": todo,
        "traceability": trace,
        "iteration": iteration,
        "status": status,
        "evidence index": evidence_index,
        "parent iteration": parent_iteration,
    }
    for label, required in W02_CURRENT_GOVERNANCE_REQUIREMENTS.items():
        text = current_governance_documents[label]
        for marker in sorted(required):
            if marker not in text:
                errors.append(f"{label} missing current PR #21 NO-GO marker: {marker}")
    if status.count(W02_STATUS_CURRENT_SUMMARY) != 1:
        errors.append(
            "status must contain the exact eight-failure/ninth-candidate summary once"
        )

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
        ("W02 remediation", w02_remediation),
        ("evidence index", evidence_index),
        ("parent iteration", parent_iteration),
    ):
        if re.search(r"(?:REQ|TODO|VAL|ITER)-W02A\b|\bW02A\b", text):
            errors.append(f"{label} must not create a W02A stable ID")
        if re.search(r"\bW02-B\b|\bW02B\b", text):
            errors.append(f"{label} must not introduce W02-B/W02B")

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
        read(W02_REMEDIATION),
        read(EVIDENCE_INDEX),
        read(PARENT_ITERATION),
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(
        "pre-1.0 work plan OK: exact ranks, mappings, immutable W02 historical assembly "
        "and PR #21 NO-GO/remediation evidence, packaged gate status, and release boundary"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

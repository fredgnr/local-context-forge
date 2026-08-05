#!/usr/bin/env python3
"""Fail closed when the W02 engineering-smoke assembly boundary drifts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "packaged-smoke.yml"
EXPECTED_WORKFLOW_SHA256 = (
    "341aa99918d762f9d8a0e04aab1d53edb6e451773238c73891ba30e0c312956c"
)
MAKEFILE = ROOT / "Makefile"
DESKTOP_PACKAGE = ROOT / "desktop" / "package.json"
SMOKE_CONFIG = ROOT / "desktop" / "electron-builder.smoke.yml"
COMMON_AUDIT = ROOT / "desktop" / "scripts" / "packagingAuditCommon.cjs"
PREPARE = ROOT / "desktop" / "scripts" / "prepareEngineeringSmoke.cjs"
BEFORE_PACK = ROOT / "desktop" / "scripts" / "beforePackEngineeringSmoke.cjs"
AFTER_PACK = ROOT / "desktop" / "scripts" / "afterPackEngineeringSmoke.cjs"
BUNDLE_AUDIT = ROOT / "desktop" / "scripts" / "auditEngineeringSmokeBundle.cjs"
MANIFEST_SCHEMA = ROOT / "runtime" / "engineering-smoke-manifest.schema.json"
FORMAL_BASE_CONFIG = ROOT / "desktop" / "electron-builder.yml"
FORMAL_RELEASE_CONFIG = ROOT / "desktop" / "electron-builder.release.yml"
FORMAL_BEFORE_PACK = ROOT / "desktop" / "scripts" / "beforePack.cjs"
FORMAL_AFTER_PACK = ROOT / "desktop" / "scripts" / "afterPack.cjs"
FORMAL_WORKFLOW = ROOT / ".github" / "workflows" / "desktop-release.yml"
STATUS = ROOT / "docs" / "development" / "status.md"
TODO = ROOT / "docs" / "development" / "todo.md"
TRACE = ROOT / "docs" / "development" / "traceability.md"
ITERATION = (
    ROOT
    / "docs"
    / "development"
    / "iterations"
    / "0008-incremental-retirement-engineering-package.md"
)

SOURCE_EXPRESSION = "${{ github.event.pull_request.head.sha || github.sha }}"
EXPECTED_JOB_ENV = (
    '      CI: "true"\n'
    '      LCF_ENGINEERING_SMOKE: "true"\n'
    f"      LCF_SOURCE_SHA: {SOURCE_EXPRESSION}\n"
    "      LCF_GITHUB_CONTEXT_SHA: ${{ github.sha }}\n"
)
CHECKOUT_SHA = "de0fac2e4500dabe0009e67214ff5f5447ce83dd"
SETUP_NODE_SHA = "48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e"
SETUP_PYTHON_SHA = "a309ff8b426b58ec0e2a45f0f869d46889d02405"
ACTION_ALLOWLIST = {
    ("actions/checkout", CHECKOUT_SHA),
    ("actions/setup-node", SETUP_NODE_SHA),
    ("actions/setup-python", SETUP_PYTHON_SHA),
}
PYTHON_ARCHIVE_URL = (
    "https://github.com/actions/python-versions/releases/download/"
    "3.13.14-27320626148/python-3.13.14-darwin-arm64.tar.gz"
)
PYTHON_HASHES_URL = (
    "https://github.com/actions/python-versions/releases/download/"
    "3.13.14-27320626148/hashes.sha256"
)
PYTHON_ARCHIVE_SHA256 = (
    "839b14df8a24415e17d15f222e2ac01d3a90845deb39df642e2cc01869140a34"
)
PYTHON_HASHES_SHA256 = (
    "b4dd388b14ff20ced93003e31e2be8d486049456161fc1ea393aa7c64a000e17"
)
PYTHON_INSTALL_ROOT = "/Library/Frameworks/Python.framework/Versions/3.13"
PYTHON_RUNNER_INPUTS = (
    "LCF_PYTHON_DISTRIBUTION_ARCHIVE",
    "LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST",
    "LCF_PYTHON_INSTALL_ROOT",
)
EXPECTED_PYTHON_RUNNER_BINDING = '''{
  printf 'PYTHON_SIDECAR_ARCHIVE=%s\\n' "${python_archive}"
  printf 'PYTHON_SIDECAR_HASH_MANIFEST=%s\\n' "${python_hashes}"
  printf 'LCF_PYTHON_DISTRIBUTION_ARCHIVE=%s\\n' "${python_archive}"
  printf 'LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST=%s\\n' "${python_hashes}"
  printf 'LCF_PYTHON_INSTALL_ROOT=%s\\n' \\
    "/Library/Frameworks/Python.framework/Versions/3.13"
} >> "${GITHUB_ENV}"'''
EXPECTED_APP_ID = "dev.localcontextforge.engineering-smoke"
EXPECTED_PRODUCT_NAME = "Local Context Forge Engineering Smoke"
EXPECTED_MANIFEST_PATH = (
    "Contents/Resources/engineering-smoke/distribution.json"
)
EXPECTED_SMOKE_CONFIG = """appId: dev.localcontextforge.engineering-smoke
productName: Local Context Forge Engineering Smoke
asar: true
npmRebuild: false
electronVersion: 43.2.0
beforePack: scripts/beforePackEngineeringSmoke.cjs
afterPack: scripts/afterPackEngineeringSmoke.cjs
directories:
  output: release-smoke
files:
  - from: generated/engineering-smoke/app
    to: .
    filter:
      - dist/main/index.js
      - dist/preload/index.cjs
      - package.json
extraResources:
  - from: resources/renderer
    to: renderer
    filter:
      - "**/*"
  - from: generated/sidecar
    to: sidecar
    filter:
      - "**/*"
  - from: generated/engineering-smoke/distribution.json
    to: engineering-smoke/distribution.json
mac:
  category: public.app-category.developer-tools
  target:
    - target: dir
      arch: arm64
  identity: "-"
  timestamp: none
  hardenedRuntime: false
  gatekeeperAssess: false
  notarize: false
  signIgnore:
    - "/Contents/Resources/sidecar/"
  extendInfo:
    LCFDistributionClass: engineering-smoke
    LCFDistributionMarker: UNOFFICIAL
    LCFEngineeringOnly: true
    LCFPublishable: false
    LCFUpdaterMode: unavailable
    LCFNetworkAllowed: false
    LCFManualReleasePageAllowed: false
    LCFPackagedAppLaunch: not-run
    LCFPackagedSmokeValidation: not-run
publish: null
"""
EXPECTED_PACKAGE_SCRIPTS = {
    "build:main": (
        "esbuild src/main/index.ts --bundle --platform=node --format=cjs "
        "--target=node22 --external:electron "
        "--define:__LCF_DISTRIBUTION_PROFILE__='\"standard\"' "
        "--outfile=dist/main/index.js"
    ),
    "build:engineering-smoke": (
        "node scripts/prepareEngineeringSmoke.cjs --initialize && "
        "esbuild src/main/index.ts --bundle --platform=node --format=cjs "
        "--target=node22 --external:electron "
        "--define:__LCF_DISTRIBUTION_PROFILE__='\"engineering-smoke\"' "
        "--outfile=generated/engineering-smoke/build/dist/main/index.js && "
        "npm run build:preload:engineering-smoke"
    ),
    "build:preload:engineering-smoke": (
        "esbuild src/preload/index.ts --bundle --platform=node --format=cjs "
        "--target=node22 --external:electron "
        "--outfile=generated/engineering-smoke/build/dist/preload/index.cjs"
    ),
    "test:engineering-smoke": (
        "vitest run tests/engineeringSmokePackaging.test.ts"
    ),
    "prepare:engineering-smoke": "node scripts/prepareEngineeringSmoke.cjs",
    "pack:engineering-smoke": (
        "electron-builder --dir --mac --arm64 "
        "--config electron-builder.smoke.yml --publish never"
    ),
    "audit:engineering-smoke": (
        "node scripts/auditEngineeringSmokeBundle.cjs"
    ),
}
EXPECTED_RUN_BLOCK_SHA256 = (
    ("exact provenance", "3777a7ddc6ae77f06ef0ae683ceaa4e4b8a1491f7c6c1be763bda06dd5292588"),
    ("policy", "fd7b010b95d7af1e8f5954b7e3f863235aebb9ccd723ec84c2fd084ecdc1838b"),
    ("Python sources", "d60af92a5cfcf963ad99530243f3d5c00ea6e4910c863967667244229bce4495"),
    ("Python sidecar", "1047ddb0d37ac0cd187a065151c45a26aa2250f4303a6ac06f2689d896084710"),
    ("renderer", "5023492b7a69f172b1859fbcf6ffdc1089b2b655779b95770496afee816f44a7"),
    ("Desktop", "fbf322ed5f784aab2efc94a425944c3d61a25485bea226961c0ab746c21dc961"),
    ("assembly audit", "67a914452c62079632e208576ba4b19e302d246fedb3e124179164f20a689d88"),
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(read(path))


def load_inputs() -> dict[str, Any]:
    return {
        "workflow": read(WORKFLOW),
        "makefile": read(MAKEFILE),
        "package": load_json(DESKTOP_PACKAGE),
        "smoke_config": read(SMOKE_CONFIG),
        "common_audit": read(COMMON_AUDIT),
        "prepare": read(PREPARE),
        "before_pack": read(BEFORE_PACK),
        "after_pack": read(AFTER_PACK),
        "bundle_audit": read(BUNDLE_AUDIT),
        "schema": load_json(MANIFEST_SCHEMA),
        "formal_base_config": read(FORMAL_BASE_CONFIG),
        "formal_release_config": read(FORMAL_RELEASE_CONFIG),
        "formal_before_pack": read(FORMAL_BEFORE_PACK),
        "formal_after_pack": read(FORMAL_AFTER_PACK),
        "formal_workflow": read(FORMAL_WORKFLOW),
        "status": read(STATUS),
        "todo": read(TODO),
        "trace": read(TRACE),
        "iteration": read(ITERATION),
    }


def _job_names(workflow: str) -> set[str]:
    if "jobs:\n" not in workflow:
        return set()
    return set(
        re.findall(
            r"^  ([A-Za-z0-9_-]+):\s*$",
            workflow.split("jobs:\n", 1)[1],
            re.MULTILINE,
        )
    )


def _action_uses(workflow: str) -> list[tuple[str, str]]:
    return re.findall(
        r"^\s*uses:\s*([^@\s]+)@([^\s#]+)", workflow, re.MULTILINE
    )


def _run_blocks(workflow: str) -> list[str]:
    lines = workflow.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        match = re.match(r"^(?P<indent>\s*)run:\s*(?P<value>.*)$", lines[index])
        if match is None:
            index += 1
            continue
        value = match.group("value").strip()
        if value not in {"|", ">"}:
            blocks.append(value)
            index += 1
            continue
        indentation = len(match.group("indent"))
        index += 1
        body: list[str] = []
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                body.append("")
                index += 1
                continue
            leading = len(line) - len(line.lstrip())
            if leading <= indentation:
                break
            body.append(line[indentation + 2 :])
            index += 1
        blocks.append("\n".join(body))
    return blocks


def _target_recipe(makefile: str, target: str) -> str:
    match = re.search(
        rf"^{re.escape(target)}:[^\n]*\n(?P<body>(?:\t[^\n]*(?:\n|$))*)",
        makefile,
        re.MULTILINE,
    )
    return match.group("body") if match else ""


def _table_status(document: str, task: str) -> str | None:
    match = re.search(
        rf"^\| {re.escape(task)} \|[^\n]*?\| `([^`]+)` \|",
        document,
        re.MULTILINE,
    )
    return match.group(1) if match else None


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _validate_closed_schema(schema: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, Mapping):
        return ["engineering-smoke manifest schema must be an object"]

    def visit(value: Any, path: str) -> None:
        if not isinstance(value, Mapping):
            return
        if value.get("type") == "object" and value.get("additionalProperties") is not False:
            errors.append(f"manifest schema object {path} must reject additional properties")
        properties = value.get("properties")
        if isinstance(properties, Mapping):
            for key, child in properties.items():
                visit(child, f"{path}.{key}")

    visit(schema, "$")
    expected_constants = {
        ("properties", "$schema", "const"): "engineering-smoke-manifest.schema.json",
        ("properties", "kind", "const"): (
            "local-context-forge-engineering-smoke-distribution"
        ),
        (
            "properties",
            "distribution",
            "properties",
            "class",
            "const",
        ): "engineering-smoke",
        (
            "properties",
            "distribution",
            "properties",
            "marker",
            "const",
        ): "UNOFFICIAL",
        (
            "properties",
            "distribution",
            "properties",
            "engineeringOnly",
            "const",
        ): True,
        (
            "properties",
            "distribution",
            "properties",
            "publishable",
            "const",
        ): False,
        (
            "properties",
            "application",
            "properties",
            "appId",
            "const",
        ): EXPECTED_APP_ID,
        (
            "properties",
            "application",
            "properties",
            "productName",
            "const",
        ): EXPECTED_PRODUCT_NAME,
        (
            "properties",
            "assembly",
            "properties",
            "manifestPath",
            "const",
        ): EXPECTED_MANIFEST_PATH,
        (
            "properties",
            "components",
            "properties",
            "desktopApp",
            "properties",
            "asarPath",
            "const",
        ): "Contents/Resources/app.asar",
        (
            "properties",
            "components",
            "properties",
            "desktopApp",
            "properties",
            "mainPath",
            "const",
        ): "dist/main/index.js",
        (
            "properties",
            "components",
            "properties",
            "desktopApp",
            "properties",
            "preloadPath",
            "const",
        ): "dist/preload/index.cjs",
        (
            "properties",
            "components",
            "properties",
            "desktopApp",
            "properties",
            "packagePath",
            "const",
        ): "package.json",
        (
            "properties",
            "validation",
            "properties",
            "validationId",
            "const",
        ): "VAL-PACKAGED-SMOKE-001",
        (
            "properties",
            "validation",
            "properties",
            "packagedAppLaunch",
            "const",
        ): "not-run",
        (
            "properties",
            "validation",
            "properties",
            "packagedSmoke",
            "const",
        ): "not-run",
    }
    for keys, expected in expected_constants.items():
        if _nested(schema, *keys) != expected:
            errors.append(f"manifest schema constant {'.'.join(keys)} drifted")
    return errors


def validate_policy(inputs: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "workflow",
        "makefile",
        "package",
        "smoke_config",
        "common_audit",
        "prepare",
        "before_pack",
        "after_pack",
        "bundle_audit",
        "schema",
        "formal_base_config",
        "formal_release_config",
        "formal_before_pack",
        "formal_after_pack",
        "formal_workflow",
        "status",
        "todo",
        "trace",
        "iteration",
    }
    if set(inputs) != required:
        return ["packaged-smoke policy input set drifted"]

    workflow = str(inputs["workflow"])
    makefile = str(inputs["makefile"])
    package = inputs["package"]
    smoke_config = str(inputs["smoke_config"])
    common_audit = str(inputs["common_audit"])
    prepare = str(inputs["prepare"])
    before_pack = str(inputs["before_pack"])
    after_pack = str(inputs["after_pack"])
    bundle_audit = str(inputs["bundle_audit"])

    if hashlib.sha256(workflow.encode("utf-8")).hexdigest() != EXPECTED_WORKFLOW_SHA256:
        errors.append("workflow document contract drifted")

    trigger = workflow.split("concurrency:", 1)[0]
    exact_trigger = (
        "name: Engineering smoke bundle assembly\n\n"
        "on:\n"
        "  pull_request:\n"
        "  push:\n"
        "    branches:\n"
        "      - main\n\n"
    )
    if trigger != exact_trigger:
        errors.append("workflow triggers must be exactly pull_request plus main push")
    for top_level_key in ("name", "on", "concurrency", "permissions", "jobs"):
        if len(re.findall(rf"^{top_level_key}:\s*", workflow, re.MULTILINE)) != 1:
            errors.append(f"workflow top-level key {top_level_key!r} is ambiguous")
    for forbidden in (
        "pull_request_target:",
        "workflow_dispatch:",
        "schedule:",
        "tags:",
        "branches-ignore:",
        "continue-on-error:",
        "defaults:",
        "container:",
        "services:",
    ):
        if forbidden in workflow:
            errors.append(f"workflow contains forbidden control {forbidden}")
    if _job_names(workflow) != {"assemble"}:
        errors.append("workflow must contain exactly one assembly job")
    if len(re.findall(r"^\s+if:\s*", workflow, re.MULTILINE)) != 1:
        errors.append("workflow must contain only the reviewed repository guard")
    shell_values = re.findall(r"^\s+shell:\s*(\S+)\s*$", workflow, re.MULTILINE)
    if shell_values != ["bash"] * 5:
        errors.append("workflow shell selection drifted")
    permission_blocks = re.findall(r"^\s*permissions:\s*$", workflow, re.MULTILINE)
    permission_section = re.search(
        r"^permissions:\n(?P<body>(?:  [^\n]+\n)+)\njobs:\n",
        workflow,
        re.MULTILINE,
    )
    if (
        len(permission_blocks) != 1
        or permission_section is None
        or permission_section.group("body") != "  contents: read\n"
    ):
        errors.append("workflow permissions must be exactly top-level contents: read")
    if "contents: write" in workflow or "environment:" in workflow:
        errors.append("workflow must not gain write permissions or an Environment")
    if re.search(r"\bsecrets\b", workflow, re.IGNORECASE):
        errors.append("workflow must not read GitHub secrets")

    uses = _action_uses(workflow)
    if set(uses) != ACTION_ALLOWLIST or len(uses) != len(ACTION_ALLOWLIST):
        errors.append("workflow action allowlist or action count drifted")
    for action, revision in uses:
        if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
            errors.append(f"workflow action {action} is not full-SHA pinned")
    checkout = f"actions/checkout@{CHECKOUT_SHA}"
    if workflow.count(checkout) != 1:
        errors.append("workflow must check out exactly once")
    for marker in (
        f"ref: {SOURCE_EXPRESSION}",
        "fetch-depth: 0",
        "persist-credentials: false",
        f"LCF_SOURCE_SHA: {SOURCE_EXPRESSION}",
        "LCF_GITHUB_CONTEXT_SHA: ${{ github.sha }}",
        'runs-on: macos-15',
        'test "$(uname -m)" = "arm64"',
        'test "$(git rev-parse HEAD)" = "${LCF_SOURCE_SHA}"',
        "node-version: \"22.23.2\"",
        "python-version: \"3.13.14\"",
        "if: github.repository == 'fredgnr/local-context-forge'",
    ):
        if workflow.count(marker) != 1:
            errors.append(f"workflow exact-source/tool contract missing {marker!r}")
    if re.search(r"^\s+GITHUB_SHA:\s*", workflow, re.MULTILINE):
        errors.append("workflow must not overwrite the GitHub context SHA")
    job_env = re.search(
        r"^    env:\n(?P<body>(?:      [^\n]+\n)+)    steps:\n",
        workflow,
        re.MULTILINE,
    )
    if (
        len(re.findall(r"^\s+env\s*:", workflow, re.MULTILINE)) != 1
        or job_env is None
        or job_env.group("body") != EXPECTED_JOB_ENV
    ):
        errors.append("workflow environment surface drifted")
    if "cache:" in workflow or "actions/cache@" in workflow:
        errors.append("workflow must not use a mutable dependency cache")

    run_blocks = _run_blocks(workflow)
    actual_run_digests = tuple(
        hashlib.sha256(block.encode("utf-8")).hexdigest()
        for block in run_blocks
    )
    if actual_run_digests != tuple(
        digest for _, digest in EXPECTED_RUN_BLOCK_SHA256
    ):
        errors.append("workflow executable run-step contract drifted")
    run_lines = [
        line.strip()
        for block in run_blocks
        for line in block.splitlines()
        if line.strip()
    ]
    if any(line.startswith("#") for line in run_lines):
        errors.append("workflow run blocks must not use comments as policy evidence")
    required_commands = (
        "make packaged-smoke-policy-check",
        "make python-sidecar-build",
        "npm --prefix web ci --ignore-scripts --no-audit --no-fund",
        "npm --prefix web run build",
        "make renderer-stage",
        "npm --prefix desktop ci --ignore-scripts --no-audit --no-fund",
        "npm --prefix desktop run typecheck",
        "npm --prefix desktop run test:engineering-smoke",
        "npm --prefix desktop run build:engineering-smoke",
        "npm --prefix desktop run prepare:engineering-smoke",
        "npm --prefix desktop run pack:engineering-smoke",
        (
            "npm --prefix desktop --silent run audit:engineering-smoke "
            '> "${audit_json}"'
        ),
    )
    for command in required_commands:
        if run_lines.count(command) != 1:
            errors.append(f"workflow required command missing {command!r}")
    if re.search(r"npm --prefix desktop run build(?:\s|$)", workflow):
        errors.append("workflow must not use the companion-building generic build script")
    if "build:companion" in workflow or "audit:companion" in workflow:
        errors.append("workflow must not build or audit the MCP companion")
    for value in (
        PYTHON_ARCHIVE_URL,
        PYTHON_HASHES_URL,
        PYTHON_ARCHIVE_SHA256,
        PYTHON_HASHES_SHA256,
    ):
        if "\n".join(run_blocks).count(value) != 1:
            errors.append("workflow Python source lock drifted")

    python_source_blocks = [
        block for block in run_blocks if PYTHON_ARCHIVE_URL in block
    ]
    runner_binding_markers = (
        "printf 'LCF_PYTHON_DISTRIBUTION_ARCHIVE=%s\\n' \"${python_archive}\"",
        (
            "printf 'LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST=%s\\n' "
            '"${python_hashes}"'
        ),
        "printf 'LCF_PYTHON_INSTALL_ROOT=%s\\n' \\",
        f'    "{PYTHON_INSTALL_ROOT}"',
    )
    if len(python_source_blocks) != 1:
        errors.append("workflow Python runner input binding drifted")
    else:
        python_source_block = python_source_blocks[0]
        binding_offset = python_source_block.find(EXPECTED_PYTHON_RUNNER_BINDING)
        final_hash_check_offset = python_source_block.rfind(
            "shasum -a 256 --check"
        )
        if (
            binding_offset < 0
            or python_source_block.count(EXPECTED_PYTHON_RUNNER_BINDING) != 1
            or python_source_block.count("shasum -a 256 --check") != 2
            or final_hash_check_offset < 0
            or binding_offset <= final_hash_check_offset
            or python_source_block.count('} >> "${GITHUB_ENV}"') != 1
        ):
            errors.append("workflow Python runner input binding drifted")
    for marker in runner_binding_markers:
        if workflow.count(marker) != 1:
            errors.append("workflow Python runner input binding drifted")
    for input_name in PYTHON_RUNNER_INPUTS:
        if workflow.count(input_name) != 1:
            errors.append("workflow Python runner input binding drifted")

    forbidden_workflow = (
        "actions/upload-artifact@",
        "actions/download-artifact@",
        "gh release",
        "electron-builder.release.yml",
        "electron-builder.yml",
        "LCF_FORMAL_RELEASE",
        "DESKTOP_RELEASE_CREDENTIAL_BUNDLE_BASE64",
        "CSC_LINK",
        "/usr/bin/open",
        "open -a",
        "electron .",
        "npm start",
        "osascript",
        "launchctl",
        "Contents/MacOS/",
    )
    for marker in forbidden_workflow:
        if marker in workflow:
            errors.append(f"workflow contains forbidden release/launch marker {marker!r}")
    if re.search(r"\bspctl\b.*\.app\b", workflow, re.IGNORECASE):
        errors.append("workflow must not assess the assembled App with spctl")

    spctl_lines = [line.strip() for line in makefile.splitlines() if "spctl" in line]
    expected_spctl = (
        '/usr/sbin/spctl --assess --type install --verbose=4 "$(PYTHON_SIDECAR_INSTALLER)"'
    )
    if spctl_lines != [expected_spctl]:
        errors.append("Makefile spctl use must be the one locked Python installer assessment")
    policy_recipe = _target_recipe(makefile, "packaged-smoke-policy-check")
    for marker in (
        "tools/check_packaged_smoke_policy.py",
        "tools.tests.test_check_packaged_smoke_policy",
    ):
        if marker not in policy_recipe:
            errors.append(f"packaged-smoke policy Make target missing {marker!r}")

    if not isinstance(package, Mapping) or not isinstance(package.get("scripts"), Mapping):
        errors.append("desktop package scripts are missing")
        scripts: Mapping[str, Any] = {}
    else:
        scripts = package["scripts"]
    if _nested(package, "devDependencies", "@electron/asar") != "3.4.1":
        errors.append("Desktop ASAR auditor dependency must remain exact")
    required_scripts = set(EXPECTED_PACKAGE_SCRIPTS) | {"build:preload"}
    if not required_scripts.issubset(scripts):
        errors.append("desktop package omits an engineering-smoke script")
    for name, expected in EXPECTED_PACKAGE_SCRIPTS.items():
        if scripts.get(name) != expected:
            errors.append(f"desktop package script {name!r} drifted")
    standard_main = str(scripts.get("build:main", ""))
    engineering_build = str(scripts.get("build:engineering-smoke", ""))
    if "__LCF_DISTRIBUTION_PROFILE__" not in standard_main or "standard" not in standard_main:
        errors.append("standard Main build must explicitly compile the standard profile")
    if (
        "__LCF_DISTRIBUTION_PROFILE__" not in engineering_build
        or "engineering-smoke" not in engineering_build
        or "build:preload" not in engineering_build
        or "build:companion" in engineering_build
    ):
        errors.append("engineering build must compile only its Main profile and preload")
    pack_script = str(scripts.get("pack:engineering-smoke", ""))
    for marker in (
        "electron-builder",
        "--dir",
        "--mac",
        "--arm64",
        "--config electron-builder.smoke.yml",
        "--publish never",
    ):
        if marker not in pack_script:
            errors.append(f"engineering pack script missing {marker!r}")
    if any(
        marker in pack_script
        for marker in ("electron-builder.yml", "release.yml", " dmg", " zip", "start")
    ):
        errors.append("engineering pack script crosses the formal or launch boundary")

    if smoke_config != EXPECTED_SMOKE_CONFIG:
        errors.append("engineering builder config differs from the reviewed allowlist")
    required_config = (
        f"appId: {EXPECTED_APP_ID}",
        f"productName: {EXPECTED_PRODUCT_NAME}",
        "output: release-smoke",
        "asar: true",
        'identity: "-"',
        "hardenedRuntime: false",
        "notarize: false",
        "publish: null",
        "beforePack: scripts/beforePackEngineeringSmoke.cjs",
        "afterPack: scripts/afterPackEngineeringSmoke.cjs",
        "target: dir",
        "arch: arm64",
    )
    for marker in required_config:
        if marker not in smoke_config:
            errors.append(f"engineering builder config missing {marker!r}")
    if len(re.findall(r"^publish\s*:", smoke_config, re.MULTILINE)) != 1:
        errors.append("engineering builder config publish policy must be exactly null")
    if re.search(r"^extends\s*:", smoke_config, re.MULTILINE):
        errors.append("engineering builder config must not extend another config")
    for marker in (
        "electron-builder.yml",
        "electron-builder.release.yml",
        "generated/qmd",
        "generated/companion",
        "resources/update",
        "update-metadata-key.lock.json",
        "update-metadata-ed25519-public.pem",
        "macos-codesign-certificate.lock.json",
        "prepareRelease",
        " dmg",
        " zip",
        "blockmap",
    ):
        if marker in smoke_config:
            errors.append(f"engineering builder config contains forbidden resource {marker!r}")
    for source, destination in (
        ("resources/renderer", "renderer"),
        ("generated/sidecar", "sidecar"),
        (
            "generated/engineering-smoke/distribution.json",
            "engineering-smoke/distribution.json",
        ),
    ):
        if source not in smoke_config or destination not in smoke_config:
            errors.append("engineering builder resource allowlist drifted")

    formal_documents = {
        "formal base config": str(inputs["formal_base_config"]),
        "formal release config": str(inputs["formal_release_config"]),
        "formal beforePack": str(inputs["formal_before_pack"]),
        "formal afterPack": str(inputs["formal_after_pack"]),
        "formal workflow": str(inputs["formal_workflow"]),
    }
    for label, document in formal_documents.items():
        lowered = document.lower()
        if "engineering-smoke" in lowered or "electron-builder.smoke.yml" in lowered:
            errors.append(f"{label} must not reference the engineering boundary")

    engineering_scripts = {
        "prepare": prepare,
        "beforePack": before_pack,
        "afterPack": after_pack,
        "bundle audit": bundle_audit,
    }
    for label, document in engineering_scripts.items():
        for marker in (
            "prepareRelease.cjs",
            "auditUpdateTrust.cjs",
            "resealPackagedRuntimes.cjs",
            "LCF_FORMAL_RELEASE=true",
        ):
            if marker in document:
                errors.append(f"engineering {label} imports formal boundary {marker!r}")
    for marker in (
        "auditPythonSidecar",
        "auditRenderer",
        "LCF_SOURCE_SHA",
        EXPECTED_MANIFEST_PATH,
        "VAL-PACKAGED-SMOKE-001",
        '"not-run"',
    ):
        if marker not in prepare + before_pack + common_audit:
            errors.append(f"engineering staging/audit contract missing {marker!r}")
    if (
        "flipFuses" not in after_pack
        or "resealPackagedRuntimes" in after_pack
        or "assertEngineeringSmokeMode" not in after_pack
        or "assertNoProductionEnvironment" not in after_pack
    ):
        errors.append("engineering afterPack must only harden Electron fuses")
    for marker in (
        "Info.plist",
        "ElectronAsarIntegrity",
        "inspectAsarContents",
        "EXPECTED_ASAR_ENTRIES",
        "ALLOWED_ELECTRON_HELPER_APPS",
        "codesign",
        "lipo",
        EXPECTED_MANIFEST_PATH,
        "normalizedInventorySha256",
        "packagedAppLaunch",
        "packagedSmokeValidation",
        'assembly: "pass"',
        'bundleAudit: "pass"',
        'w10: "locked"',
        'w11: "locked"',
    ):
        if marker not in bundle_audit:
            errors.append(f"bundle auditor missing static assertion {marker!r}")
    engineering_package_scripts = "\n".join(
        str(scripts.get(name, "")) for name in EXPECTED_PACKAGE_SCRIPTS
    )
    launch_surface = (
        workflow
        + prepare
        + before_pack
        + after_pack
        + common_audit
        + bundle_audit
        + engineering_package_scripts
    )
    for pattern in (
        r"/usr/bin/open\b",
        r"\bopen\s+-a\b",
        r"\belectron\s+\.\b",
        r"\bosascript\b",
        r"\blaunchctl\b",
        r"spctl[^\n]*\.app\b",
        r"\bspctl\b",
        r"(?:spawn|execFile|execFileSync)[^\n]*Contents/MacOS",
    ):
        if re.search(pattern, launch_surface, re.IGNORECASE):
            errors.append("engineering assembly/audit contains an App launch/assessment surface")

    errors.extend(_validate_closed_schema(inputs["schema"]))

    status = str(inputs["status"])
    todo = str(inputs["todo"])
    trace = str(inputs["trace"])
    iteration = str(inputs["iteration"])
    if _table_status(todo, "TODO-PACKAGED-SMOKE-001") != "in-progress":
        errors.append("W02 TODO must remain in-progress across W02-A")
    if _table_status(trace, "TODO-PACKAGED-SMOKE-001") != "in-progress":
        errors.append("W02 trace task must remain in-progress across W02-A")
    for document in (status, todo, trace, iteration):
        if re.search(r"(?:REQ|TODO|VAL|ITER)-W02A\b|\bW02A\b", document):
            errors.append("W02-A must not become a new stable ID")
    for marker in (
        "VAL-PACKAGED-SMOKE-001",
        "not-run",
        "W10/W11",
        "locked",
        "public release NO-GO",
    ):
        if marker not in status + todo + trace + iteration:
            errors.append(f"governance boundary missing {marker!r}")
    validation_row = re.search(
        r"^\| VAL-PACKAGED-SMOKE-001 \|[^\n]*$", trace, re.MULTILINE
    )
    if validation_row is None or re.findall(
        r"(?<![A-Za-z-])(not-run|pass|fail)(?![A-Za-z-])",
        validation_row.group(0) if validation_row else "",
    ) != ["not-run"]:
        errors.append("VAL-PACKAGED-SMOKE-001 must remain canonically not-run")
    return errors


def main() -> int:
    errors = validate_policy(load_inputs())
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(
        "packaged-smoke policy OK: isolated arm64 dir assembly, no App launch, "
        "upload, production trust, or gate promotion"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

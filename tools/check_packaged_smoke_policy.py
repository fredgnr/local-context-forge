#!/usr/bin/env python3
"""Fail closed when the W02 engineering-smoke assembly boundary drifts."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "packaged-smoke.yml"
EXPECTED_WORKFLOW_SHA256 = (
    "9755cdb77f61b936f6f11f2869444a911ab7947a47545792fc6a242cd888e126"
)
MAKEFILE = ROOT / "Makefile"
BUILD_SCRIPT = ROOT / "tools" / "build_python_sidecar.py"
AUDIT_SCRIPT = ROOT / "tools" / "audit_python_sidecar.py"
PYTHON_BOOTSTRAP = ROOT / "tools" / "bootstrap_python_sidecar.py"
EXACT_GIT_CHECKER = ROOT / "tools" / "check_exact_git_provenance.py"
EXACT_GIT_CHECKER_TESTS = (
    ROOT / "tools" / "tests" / "test_check_exact_git_provenance.py"
)
EXACT_NODE_INSTALLER = ROOT / "tools" / "exact_node_install.cjs"
PYTHON_PACKAGING_TESTS = (
    ROOT / "tests" / "backend" / "test_python_sidecar_packaging.py"
)
GITIGNORE = ROOT / ".gitignore"
REMEDIATION_EVIDENCE = (
    ROOT
    / "docs"
    / "development"
    / "evidence"
    / "W02"
    / "2026-08-07-pr21-remediation.md"
)
EXPECTED_REVIEWED_INPUT_SHA256 = {
    "workflow": "9755cdb77f61b936f6f11f2869444a911ab7947a47545792fc6a242cd888e126",
    "makefile": "48f2dbbf50c027c15a5aed1eeca0416684f70e75e63a504fb1263dd60afad676",
    "build_script": "d026b147aa40b5a461d5516322d3ef43ea7081c6365d632b7830dba51e6f2e18",
    "audit_script": "7bd183332946a9497b11759e63ecd70c27125abe6cc7dcb6f736c7f40bba81ad",
    "python_bootstrap": "6ef757dd080bc61f6c9ac5252463fa80b5e1252a045db7a31511848b53734d0b",
    "exact_git_checker": "aa28265267e99f6fea379401783d6b7fbe76f43f0a6cf9f15485ebfcce057aac",
    "exact_git_checker_tests": "4e5afe7d4eefedd9e47a25c3dc1bb77ebc1977b0325382d3f766784e57fdf0d4",
    "exact_node_installer": "9c551014e06a3315d386eb1f418a6548fe6c92b653767da914b6ddaa99cb0849",
    "python_packaging_tests": "df5acdb263b50bcfc4b08b5e2aaf20f66c3de36294248ea98db047e22a0188a3",
    "gitignore": "eee9ec14df0b6a9cc4a6ede3020c5ab84373f6199e36ff3eafbaac832ecc1c1c",
    "remediation_evidence": "d5c1cd059bf09193991c8a2d9809f9b81149bd8831fd5ce1c4fcad22ca4eb58b",
    "package": "8572d59212b1233e701338d40bb3a47525db052a41b80b27e1a797d6e07fc712",
    "desktop_package_lock": "10f0dafcd0aecd24985c313209ff42e2759aabe3cdcf2b4e71ed6b6bbd317f60",
    "web_package": "0270e22c0745542be7ab5d792adef4a3d60b3565b85ec037db668e27c1a8e621",
    "web_package_lock": "ae4f9bdf4283763a980ee4b21f3fdd844d4de43a0b35fa7086406eddc2ab857f",
    "python_build_requirements_lock": "1e16e69c50364465e8587e58d4399c34146d11a91bfa3a2399e80e0741bf6342",
    "python_runtime_lock": "a961d5863a346c820cfdfa9daae0223672e761302b5f5aea92ef779c1b69f121",
    "python_toolchain_lock": "e409f11775f39d5da4c3b5df56ee147c54cd815c6b7cdba45c14b212c056b89d",
    "pyinstaller_spec": "db0eb516b82ff9a33164f6cfb95024cfabd8cb9fa8de643d46ee8763e6864366",
    "smoke_config": "b7b9dedb2fbe15cf5682ddd8255286feb799cc28eb2454c0ceaf4b5ec201b448",
    "common_audit": "1e754dc8f4d2e76f3a28a71f86622e6b0338feaf2ad4112fe6666d108c969398",
    "prepare": "8735b655e89565bd3209d3884d1e6ad75cd451357a0c528dbe5b78705a59c0d0",
    "desktop_entrypoint_builder": "aa6da03de871d8af03f544d2adca03772d6242ca23a8698a7c714ca79d84b1f1",
    "renderer_builder": "c7f60680717d80fd04303f87f8b4ca89895c03d7394738340c2dcf3c4b367b43",
    "stage_renderer": "853820c64eecd8c5126a0bb9cfded3b85f5be34fa3011f092cc0c73e7cf7fd9c",
    "audit_renderer": "d52fc0ba5feddd39311f800ad8d9a014695b0b45939d66a932e4c1e6ffe65d36",
    "engineering_packaging_tests": "af45aee101092d8eed9c91037b61db6499a156c9ec4a86232ff734faaac13354",
    "before_pack_tests": "34d06a8aaf729df7687bcc0f68eb895b79a35be332047c361f04bce84660b572",
    "renderer_packaging_tests": "4122f11a3bdfffd0b350aea7cd8027c8363527afb7fe3f61b3011d3c7b7df6ce",
    "before_pack": "526b7a4bf8af1c68a94ebfdf0ac624771719d2b1974c3ac0246022ccc3af1882",
    "after_pack": "d513011fcbc5252665f8ab73ae24bea36448821bffb3fbf9aa888b6a1f836d93",
    "bundle_audit": "6cf28dfd98d5f5ac26b71488a8a57696d0a110ee3f21c248669ae6b580ab1905",
    "schema": "50af250a3a9af04d50f9bb51c2dfc1b4a55bedd3b2d5ca6eae7c50b8d4248d9b",
    "renderer_schema": "f24c1abc32aae2bb033b455f730f523f66edbc2c4f8f738cbf2c5dec399ba34b",
    "python_sidecar_schema": "6c5c4fb707d29c02676a34c76f00c2e0eec509df2500be6d73b5f6aa8d97cb1c",
    "formal_base_config": "cede533e71bdfb00401451e3016b7c7032b5867b5ba0147682d72029d08cafb4",
    "formal_release_config": "72a80df25946ad9526a021efcf9f3295d2075c622f576508d7d400394adfdfcd",
    "formal_before_pack": "73a3bb2021dca4785fe2ca9ca23d6b693a6965351f0f4e8fa223c5afedb5fa16",
    "formal_after_pack": "30cc9387e456f09f5402a9fc551d115396150259f9e926bf82d6ba74660d23c5",
    "formal_prepare_release": "86f42e539c4c9825760de56ccd07409b1cec07ac588380f4e64da41612df3311",
    "formal_reseal": "ef9292505be5ced0fb5b464cc9f075d48a20f8b8ee41aa08a6c4c0fbbbd1091e",
    "formal_release_policy_tests": "73b336688aba5319407672bf80d235430fdcb427d5e32e2f0581e854ba8d7ead",
    "formal_workflow": "43c1e6be118b6997653d305a21dc7b86ad521e9efa48633dfe2f8f055c408aac",
    "status": "0ae1f6ffb1c505ec80fe1a9a9a7f1cd4666086460f8f7c46a7931b59eb45b09f",
    "todo": "5374575f0b6845e864ad669443e3c67bb8a332b4ed30b09c0a4e2418263e0485",
    "trace": "749cc37bd4d7751254a00a808fa947ff6cf7c029b222e31fa3229fe2cdd15473",
    "iteration": "82dbc149b2fd634b5ac182edf930cdb3f5b0c7e51d64f37891ee7c560691f51b",
}
DESKTOP_PACKAGE = ROOT / "desktop" / "package.json"
DESKTOP_PACKAGE_LOCK = ROOT / "desktop" / "package-lock.json"
WEB_PACKAGE = ROOT / "web" / "package.json"
WEB_PACKAGE_LOCK = ROOT / "web" / "package-lock.json"
PYTHON_BUILD_REQUIREMENTS_LOCK = (
    ROOT / "backend" / "packaging" / "build-requirements.lock"
)
PYTHON_RUNTIME_LOCK = ROOT / "backend" / "uv.lock"
PYTHON_TOOLCHAIN_LOCK = (
    ROOT / "backend" / "packaging" / "python-sidecar-toolchain.lock.json"
)
PYINSTALLER_SPEC = ROOT / "backend" / "packaging" / "lcf_sidecar.spec"
SMOKE_CONFIG = ROOT / "desktop" / "electron-builder.smoke.yml"
COMMON_AUDIT = ROOT / "desktop" / "scripts" / "packagingAuditCommon.cjs"
PREPARE = ROOT / "desktop" / "scripts" / "prepareEngineeringSmoke.cjs"
DESKTOP_ENTRYPOINT_BUILDER = (
    ROOT / "desktop" / "scripts" / "buildEngineeringSmokeEntrypoints.cjs"
)
RENDERER_BUILDER = ROOT / "web" / "scripts" / "buildEngineeringRenderer.cjs"
STAGE_RENDERER = ROOT / "desktop" / "scripts" / "stageRenderer.cjs"
AUDIT_RENDERER = ROOT / "desktop" / "scripts" / "auditRenderer.cjs"
ENGINEERING_PACKAGING_TESTS = (
    ROOT / "desktop" / "tests" / "engineeringSmokePackaging.test.ts"
)
BEFORE_PACK_TESTS = ROOT / "desktop" / "tests" / "beforePack.test.ts"
RENDERER_PACKAGING_TESTS = (
    ROOT / "desktop" / "tests" / "rendererPackaging.test.ts"
)
BEFORE_PACK = ROOT / "desktop" / "scripts" / "beforePackEngineeringSmoke.cjs"
AFTER_PACK = ROOT / "desktop" / "scripts" / "afterPackEngineeringSmoke.cjs"
BUNDLE_AUDIT = ROOT / "desktop" / "scripts" / "auditEngineeringSmokeBundle.cjs"
EXPECTED_COMMON_AUDIT_SHA256 = (
    "1e754dc8f4d2e76f3a28a71f86622e6b0338feaf2ad4112fe6666d108c969398"
)
EXPECTED_PREPARE_SHA256 = (
    "8735b655e89565bd3209d3884d1e6ad75cd451357a0c528dbe5b78705a59c0d0"
)
EXPECTED_PREPARE_ENVIRONMENT_FUNCTION_SHA256 = (
    "54e0bb6b7722aec67c7df07674604fcf83d7680f4e097c3366a89004be4bc48c"
)
EXPECTED_BUNDLE_AUDIT_SHA256 = (
    "6cf28dfd98d5f5ac26b71488a8a57696d0a110ee3f21c248669ae6b580ab1905"
)
EXPECTED_BEFORE_PACK_SHA256 = (
    "526b7a4bf8af1c68a94ebfdf0ac624771719d2b1974c3ac0246022ccc3af1882"
)
EXPECTED_AFTER_PACK_SHA256 = (
    "d513011fcbc5252665f8ab73ae24bea36448821bffb3fbf9aa888b6a1f836d93"
)
EXPECTED_INSTALL_ARTIFACT_FUNCTION_SHA256 = (
    "dd363bbe9ac46885f86c40f12a03570a6bec0bfb05ef6e019ce67974d84699b4"
)
EXPECTED_PREPARE_ENVIRONMENT_FUNCTION = '''function assertNoProductionEnvironment(environment) {
  if (
    Object.prototype.hasOwnProperty.call(environment, "CSC_FOR_PULL_REQUEST") &&
    environment.CSC_FOR_PULL_REQUEST !== "true"
  ) {
    fail("Engineering-smoke PR ad-hoc signing control is invalid");
  }
  const present = FORBIDDEN_PRODUCTION_ENVIRONMENT.filter(
    (name) => typeof environment[name] === "string" && environment[name].length > 0
  );
  if (present.length > 0) {
    fail("Engineering-smoke assembly rejects production or mutable release inputs");
  }
}
'''
EXPECTED_FORBIDDEN_PRODUCTION_ENVIRONMENT = '''const FORBIDDEN_PRODUCTION_ENVIRONMENT = Object.freeze([
  "APPLE_API_ISSUER",
  "APPLE_API_KEY",
  "APPLE_API_KEY_ID",
  "APPLE_APP_SPECIFIC_PASSWORD",
  "APPLE_ID",
  "APPLE_TEAM_ID",
  "APPLE_KEYCHAIN_PROFILE",
  "APPLE_NOTARIZATION_PASSWORD",
  "APPLE_NOTARIZE",
  "APPVEYOR_BUILD_NUMBER",
  "BUILD_BUILDNUMBER",
  "BUILD_NUMBER",
  "CIRCLE_BUILD_NUM",
  "CSC_IDENTITY",
  "CSC_IDENTITY_AUTO_DISCOVERY",
  "CSC_KEYCHAIN",
  "CSC_KEY_PASSWORD",
  "CSC_LINK",
  "CSC_NAME",
  "DESKTOP_RELEASE_CREDENTIAL_BUNDLE_BASE64",
  "GH_TOKEN",
  "GITHUB_TOKEN",
  "LCF_CODESIGN_CERTIFICATE_P12",
  "LCF_CODESIGN_CERTIFICATE_PASSWORD",
  "LCF_FORMAL_RELEASE",
  "LCF_UPDATE_METADATA_PRIVATE_KEY",
  "NPM_TOKEN",
  "TRAVIS_BUILD_NUMBER",
  "CI_PIPELINE_IID"
]);'''
EXPECTED_ELECTRON_HELPER_ALLOWLIST = '''const ALLOWED_ELECTRON_HELPER_APPS = Object.freeze([
  `${PRODUCT_NAME} Helper.app`,
  `${PRODUCT_NAME} Helper (GPU).app`,
  `${PRODUCT_NAME} Helper (Plugin).app`,
  `${PRODUCT_NAME} Helper (Renderer).app`
]);'''
EXPECTED_INSTALL_ARTIFACT_FUNCTION = r'''function assertNoInstallOrReleaseArtifacts(
  outputRoot,
  expectedAppRoot = APP_ROOT
) {
  const forbidden = [];
  const appBundles = [];
  const unexpectedNestedApps = [];
  const unexpectedSymlinks = [];
  let observedReviewedPyInstallerArchive = false;
  const expectedApp = path.resolve(expectedAppRoot);
  const expectedFrameworks = path.join(expectedApp, "Contents", "Frameworks");
  const allowedHelpers = new Set(ALLOWED_ELECTRON_HELPER_APPS);
  const observedHelpers = new Set();
  function visit(directory) {
    for (const name of fs.readdirSync(directory)) {
      const candidate = path.join(directory, name);
      const info = fs.lstatSync(candidate);
      const lower = name.toLowerCase();
      const resolvedCandidate = path.resolve(candidate);
      const appRelative = path
        .relative(expectedApp, resolvedCandidate)
        .split(path.sep)
        .join("/");
      const isReviewedPyInstallerArchive =
        appRelative === REVIEWED_PYINSTALLER_ARCHIVE &&
        info.isFile() &&
        !info.isSymbolicLink() &&
        info.nlink === 1 &&
        info.size > 0;
      if (isReviewedPyInstallerArchive) {
        observedReviewedPyInstallerArchive = true;
      }
      if (lower.endsWith(".app")) {
        if (
          resolvedCandidate === expectedApp ||
          !isContained(expectedApp, resolvedCandidate)
        ) {
          appBundles.push(candidate);
        } else if (
          path.dirname(resolvedCandidate) !== expectedFrameworks ||
          !allowedHelpers.has(name) ||
          !info.isDirectory() ||
          info.isSymbolicLink()
        ) {
          unexpectedNestedApps.push(candidate);
        } else {
          observedHelpers.add(name);
        }
      }
      if (
        lower.endsWith(".dmg") ||
        lower.endsWith(".pkg") ||
        (lower.endsWith(".zip") && !isReviewedPyInstallerArchive) ||
        lower.endsWith(".blockmap") ||
        /^(?:latest|alpha|beta|next)-mac\.yml$/.test(lower) ||
        lower === "release-manifest.json" ||
        lower === "update-manifest.json" ||
        lower === "update-manifest.json.sig"
      ) {
        forbidden.push(candidate);
      }
      if (info.isSymbolicLink()) {
        if (!isContained(expectedApp, resolvedCandidate)) {
          unexpectedSymlinks.push(candidate);
        }
        continue;
      }
      if (info.isDirectory()) {
        visit(candidate);
      }
    }
  }
  visit(outputRoot);
  if (forbidden.length > 0) {
    fail("Engineering-smoke output contains an install or release artifact");
  }
  if (unexpectedSymlinks.length > 0) {
    fail("Engineering-smoke output contains an unexpected symlink");
  }
  if (unexpectedNestedApps.length > 0) {
    fail("Engineering-smoke output contains an unexpected nested app");
  }
  if (!observedReviewedPyInstallerArchive) {
    fail("Engineering-smoke reviewed Python runtime archive is missing");
  }
  if (
    observedHelpers.size !== allowedHelpers.size ||
    [...allowedHelpers].some((name) => !observedHelpers.has(name))
  ) {
    fail("Engineering-smoke Electron helper app closure is incomplete");
  }
  if (
    appBundles.length !== 1 ||
    path.resolve(appBundles[0]) !== expectedApp
  ) {
    fail("Engineering-smoke output must contain exactly one canonical app");
  }
}
'''
MANIFEST_SCHEMA = ROOT / "runtime" / "engineering-smoke-manifest.schema.json"
RENDERER_MANIFEST_SCHEMA = (
    ROOT / "runtime" / "renderer-build-manifest.schema.json"
)
PYTHON_SIDECAR_MANIFEST_SCHEMA = (
    ROOT / "runtime" / "python-sidecar-build-manifest.schema.json"
)
FORMAL_BASE_CONFIG = ROOT / "desktop" / "electron-builder.yml"
FORMAL_RELEASE_CONFIG = ROOT / "desktop" / "electron-builder.release.yml"
FORMAL_BEFORE_PACK = ROOT / "desktop" / "scripts" / "beforePack.cjs"
FORMAL_AFTER_PACK = ROOT / "desktop" / "scripts" / "afterPack.cjs"
FORMAL_PREPARE_RELEASE = ROOT / "desktop" / "scripts" / "prepareRelease.cjs"
FORMAL_RESEAL = ROOT / "desktop" / "scripts" / "resealPackagedRuntimes.cjs"
FORMAL_RELEASE_POLICY_TESTS = ROOT / "desktop" / "tests" / "releasePolicy.test.ts"
FORMAL_WORKFLOW = ROOT / ".github" / "workflows" / "desktop-release.yml"
EXPECTED_FORMAL_BOUNDARY_SHA256 = {
    "formal base config": (
        "cede533e71bdfb00401451e3016b7c7032b5867b5ba0147682d72029d08cafb4"
    ),
    "formal release config": (
        "72a80df25946ad9526a021efcf9f3295d2075c622f576508d7d400394adfdfcd"
    ),
    "formal beforePack": (
        "73a3bb2021dca4785fe2ca9ca23d6b693a6965351f0f4e8fa223c5afedb5fa16"
    ),
    "formal afterPack": (
        "30cc9387e456f09f5402a9fc551d115396150259f9e926bf82d6ba74660d23c5"
    ),
    "formal workflow": (
        "43c1e6be118b6997653d305a21dc7b86ad521e9efa48633dfe2f8f055c408aac"
    ),
}
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
EXPECTED_WORKFLOW_STEPS = (
    "Check out exact source commit",
    "Set up reviewed build Python",
    "Bind exact source provenance",
    "Set up locked Node",
    "Enforce engineering-smoke packaging policy",
    "Download locked Python runtime sources",
    "Build and audit locked Python sidecar",
    "Validate Python scratch cleanup",
    "Validate Python sidecar provenance",
    "Build and stage audited renderer",
    "Build and test engineering-smoke Desktop profile",
    "Assemble and statically audit app directory",
    "Run focused Python sidecar lifecycle tests",
)
EXACT_PROVENANCE_ENV_KEYS = (
    "LCF_SOURCE_SHA",
    "LCF_SOURCE_TREE",
    "LCF_SOURCE_SNAPSHOT_SHA256",
    "LCF_SOURCE_DATE_EPOCH",
    "LCF_RENDERER_PACKAGE_LOCK_SHA256",
)
EXPECTED_LIFECYCLE_TEST_RUN = (
    'set -euo pipefail\n'
    'cd "${LCF_REVIEWED_SOURCE_ROOT}"\n'
    'export PYTHONDONTWRITEBYTECODE=1\n'
    'python -B -m pip install --disable-pip-version-check uv==0.11.29\n'
    'make ci-python-install\n'
    'backend/.venv/bin/python -B -m pytest -q \\\n'
    '  tests/backend/test_python_sidecar_packaging.py'
)
EXPECTED_POLICY_RUN = (
    'cd "${LCF_REVIEWED_SOURCE_ROOT}" && make packaged-smoke-policy-check'
)
EXPECTED_PYTHON_BUILD_RUN = (
    'cd "${LCF_REVIEWED_SOURCE_ROOT}" && make python-sidecar-build'
)
EXPECTED_POST_BUILD_CLEANUP_RUN = r'''set -euo pipefail
test -n "${RUNNER_TEMP:-}"
[[ "${RUNNER_TEMP}" = /* ]]
test -d "${RUNNER_TEMP}"
test ! -L "${RUNNER_TEMP}"
runner_temp_real="$(cd "${RUNNER_TEMP}" && /bin/pwd -P)"
test "${runner_temp_real}" = "${RUNNER_TEMP}"
test "$(/usr/bin/stat -f '%u' "${RUNNER_TEMP}")" = "$(/usr/bin/id -u)"
runner_temp_mode="$(/usr/bin/stat -f '%Lp' "${RUNNER_TEMP}")"
(( (8#${runner_temp_mode} & 0022) == 0 ))
! compgen -G "${RUNNER_TEMP}/python-sidecar-toolchain-*" > /dev/null
! compgen -G "${RUNNER_TEMP}/lcf-python-installer.*" > /dev/null
cd "${LCF_REVIEWED_SOURCE_ROOT:?reviewed source root was not bound}"
test ! -e desktop/generated/python-sidecar-build
test ! -L desktop/generated/python-sidecar-build
! compgen -G 'desktop/generated/python-sidecar-build-*' > /dev/null'''
EXPECTED_POST_BUILD_PROVENANCE_RUN = r'''set -euo pipefail
cd "${LCF_REVIEWED_SOURCE_ROOT}"
[[ "${LCF_SOURCE_SHA}" =~ ^[0-9a-f]{40}$ ]]
[[ "${LCF_SOURCE_TREE}" =~ ^[0-9a-f]{40}$ ]]
[[ "${LCF_SOURCE_SNAPSHOT_SHA256}" =~ ^[0-9a-f]{64}$ ]]
[[ "${LCF_SOURCE_DATE_EPOCH}" =~ ^[0-9]+$ ]]
[[ "${LCF_RENDERER_PACKAGE_LOCK_SHA256}" =~ ^[0-9a-f]{64}$ ]]
test "${LCF_REVIEWED_BUILD_PYTHON}" = \
  "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13"
test -f "${LCF_REVIEWED_BUILD_PYTHON}"
test ! -L "${LCF_REVIEWED_BUILD_PYTHON}"
test -x "${LCF_REVIEWED_BUILD_PYTHON}"
test "$("${LCF_REVIEWED_BUILD_PYTHON}" -I -c \
  'import os,sys; print(os.path.realpath(sys.executable))')" = \
  "${LCF_REVIEWED_BUILD_PYTHON}"
test "$("${LCF_REVIEWED_BUILD_PYTHON}" -I -c \
  'import platform; print(platform.python_version())')" = "3.13.14"'''
EXPECTED_FORMAL_JOB_ENV = (
    '      CI: "true"\n'
    '      LCF_FORMAL_RELEASE: "true"\n'
    "      LCF_SOURCE_SHA: ${{ github.sha }}\n"
)
EXPECTED_FORMAL_PROVENANCE_EXPORT = r'''"${bootstrap_python}" -I tools/check_exact_git_provenance.py \
    --expected-tag "${GITHUB_REF_NAME}" \
    --emit-github-env > "${provenance_env}"'''
EXPECTED_FORMAL_ANCESTRY_REPOSITORY = r'''readonly ancestry_prefix="${RUNNER_TEMP}/lcf-main-ancestry."
ancestry_repository="$(
  /usr/bin/mktemp -d "${ancestry_prefix}XXXXXXXXXX"
)"
readonly ancestry_repository
cleanup_ancestry_repository() {
  local exit_status=$?
  trap - EXIT
  if [[ "${ancestry_repository}" != "${ancestry_prefix}"* ]] ||
    [[ ! -d "${ancestry_repository}" ]] ||
    [[ -L "${ancestry_repository}" ]]; then
    exit 97
  fi
  rm -rf -- "${ancestry_repository}"
  if [[ -e "${ancestry_repository}" ]] ||
    [[ -L "${ancestry_repository}" ]]; then
    exit 97
  fi
  exit "${exit_status}"
}
trap cleanup_ancestry_repository EXIT'''
EXPECTED_FORMAL_GIT_SAFE_HELPER = r'''git_safe() {
  /usr/bin/env -i \
    PATH=/usr/bin:/bin \
    LANG=C \
    LC_ALL=C \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_CONFIG_SYSTEM=/dev/null \
    GIT_CONFIG_GLOBAL=/dev/null \
    GIT_ATTR_NOSYSTEM=1 \
    GIT_NO_REPLACE_OBJECTS=1 \
    GIT_OPTIONAL_LOCKS=0 \
    GIT_TERMINAL_PROMPT=0 \
    GIT_PROTOCOL_FROM_USER=0 \
    GIT_ALLOW_PROTOCOL=https \
    /usr/bin/git \
    --git-dir="${ancestry_repository}" \
    -c core.bare=true \
    -c core.fsmonitor=false \
    -c core.untrackedCache=false \
    -c core.excludesFile=/dev/null \
    -c core.attributesFile=/dev/null \
    -c core.hooksPath=/dev/null \
    -c core.fileMode=true \
    -c core.symlinks=true \
    "$@"
}'''
EXPECTED_FORMAL_MAIN_FETCH = r'''git_safe fetch --no-tags --force --no-write-fetch-head \
  "${canonical_repository_url}" \
  "+refs/heads/main:${reviewed_main_ref}"'''
EXPECTED_FORMAL_MAIN_ANCESTRY = r'''git_safe merge-base --is-ancestor \
  "${LCF_SOURCE_SHA}" \
  "${reviewed_main_ref}"'''
EXPECTED_FORMAL_QMD_EXPORT = '''{
  printf 'LCF_QMD_BUILD_PYTHON=%s\\n' "${bootstrap_python}"
} >> "${GITHUB_ENV}"'''
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
EXPECTED_POLICY_TARGET = (
    (),
    (
        "$(PYTHON) -B tools/check_packaged_smoke_policy.py",
        "$(PYTHON) -B -m unittest tools.tests.test_check_packaged_smoke_policy",
        "$(PYTHON) -B -m unittest tools.tests.test_check_exact_git_provenance",
    ),
)
EXPECTED_PYTHON_SOURCE_VERIFY_TARGET = (
    (),
    (
        '@test -n "$(LCF_REVIEWED_SOURCE_ROOT)" || { printf \'%s\\n\' '
        "'LCF_REVIEWED_SOURCE_ROOT is required'; exit 2; }",
        '@test -n "$(PYTHON_SIDECAR_ARCHIVE)" || { printf \'%s\\n\' '
        "'PYTHON_SIDECAR_ARCHIVE is required'; exit 2; }",
        '@test -n "$(PYTHON_SIDECAR_HASH_MANIFEST)" || { printf \'%s\\n\' '
        "'PYTHON_SIDECAR_HASH_MANIFEST is required'; exit 2; }",
        '$(PYTHON) -I "$(LCF_REVIEWED_SOURCE_ROOT)/tools/build_python_sidecar.py" '
        '--verify-source-only --archive "$(PYTHON_SIDECAR_ARCHIVE)" '
        '--hash-manifest "$(PYTHON_SIDECAR_HASH_MANIFEST)"',
    ),
)
EXPECTED_PYTHON_INSTALL_TARGET = (
    ("python-sidecar-source-verify",),
    (
        '$(PYTHON) -I "$(LCF_REVIEWED_SOURCE_ROOT)/tools/bootstrap_python_sidecar.py" '
        '--install-reviewed-python --archive "$(PYTHON_SIDECAR_ARCHIVE)" '
        '--hash-manifest "$(PYTHON_SIDECAR_HASH_MANIFEST)"',
    ),
)
EXPECTED_PYTHON_BUILD_TARGET = (
    ("python-sidecar-install-python",),
    (
        '@test -n "$(LCF_REVIEWED_SOURCE_ROOT)" || { printf \'%s\\n\' '
        "'LCF_REVIEWED_SOURCE_ROOT is required'; exit 2; }",
        '@test -n "$(LCF_REVIEWED_BUILD_PYTHON)" || { printf \'%s\\n\' '
        "'LCF_REVIEWED_BUILD_PYTHON is required'; exit 2; }",
        '@test "$(LCF_REVIEWED_BUILD_PYTHON)" = '
        '"$(PYTHON_SIDECAR_FRAMEWORK_PYTHON)" || { printf \'%s\\n\' '
        "'Reviewed build Python differs from the locked framework'; exit 2; }",
        'LCF_PYTHON_DISTRIBUTION_ARCHIVE="$(PYTHON_SIDECAR_ARCHIVE)" '
        'LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST="$(PYTHON_SIDECAR_HASH_MANIFEST)" '
        'LCF_PYTHON_INSTALL_ROOT="$(PYTHON_SIDECAR_INSTALL_ROOT)" '
        'LCF_REVIEWED_BUILD_PYTHON="$(LCF_REVIEWED_BUILD_PYTHON)" '
        'LCF_REVIEWED_SOURCE_ROOT="$(LCF_REVIEWED_SOURCE_ROOT)" '
        'LCF_SOURCE_SHA="$(LCF_SOURCE_SHA)" '
        'LCF_SOURCE_TREE="$(LCF_SOURCE_TREE)" '
        '"$(LCF_REVIEWED_BUILD_PYTHON)" -I '
        '"$(LCF_REVIEWED_SOURCE_ROOT)/tools/bootstrap_python_sidecar.py"',
    ),
)
EXPECTED_PYTHON_AUDIT_TARGET = (
    (),
    (
        '@test -n "$(LCF_REVIEWED_SOURCE_ROOT)" || { printf \'%s\\n\' '
        "'LCF_REVIEWED_SOURCE_ROOT is required'; exit 2; }",
        '@test -n "$(LCF_REVIEWED_BUILD_PYTHON)" || { printf \'%s\\n\' '
        "'LCF_REVIEWED_BUILD_PYTHON is required'; exit 2; }",
        '"$(LCF_REVIEWED_BUILD_PYTHON)" -I '
        '"$(LCF_REVIEWED_SOURCE_ROOT)/tools/audit_python_sidecar.py" '
        '--bundle "$(LCF_REVIEWED_SOURCE_ROOT)/desktop/generated/sidecar"',
    ),
)
EXPECTED_PYTHON_TEST_TARGET = (
    (),
    (
        "cd backend && .venv/bin/pytest "
        "../tests/backend/test_python_sidecar_packaging.py",
    ),
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
    "build:engineering-smoke": "node scripts/buildEngineeringSmokeEntrypoints.cjs",
    "test:engineering-smoke": (
        "vitest run tests/engineeringSmokePackaging.test.ts "
        "tests/beforePack.test.ts tests/rendererPackaging.test.ts"
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
EXPECTED_STANDALONE_AUDIT_SCRIPT = (
    '"$LCF_REVIEWED_BUILD_PYTHON" -I '
    '"$LCF_REVIEWED_SOURCE_ROOT/tools/audit_python_sidecar.py" --bundle '
    '"$LCF_REVIEWED_SOURCE_ROOT/desktop/generated/sidecar"'
)
EXPECTED_WEB_PACKAGE_SCRIPTS = {
    "build:packaging": "node scripts/buildEngineeringRenderer.cjs",
}
EXPECTED_RENDERER_RUN = '''set -euo pipefail
npm --prefix web ci --ignore-scripts --no-audit --no-fund
npm --prefix web run typecheck
npm --prefix web run build:packaging
make renderer-stage'''
EXPECTED_FORMAL_RENDERER_RUN = '''set -euo pipefail
npm --prefix web ci --ignore-scripts
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build:packaging
make renderer-stage'''
EXPECTED_FORMAL_DESKTOP_AUDIT_RUN = '''set -euo pipefail
npm --prefix desktop ci --ignore-scripts
npm --prefix desktop test
npm --prefix desktop run typecheck
npm --prefix desktop run build
npm --prefix desktop run audit:companion
npm --prefix desktop run audit:python-sidecar
make qmd-runtime-audit
make renderer-audit'''
EXPECTED_RUN_BLOCK_SHA256 = (
    ("exact provenance", "bdebfc8cc27ee93996a431bcbbb0687e77c097c396f45b4020866824a9899f4f"),
    ("policy", "dde289c56ef0fd9f70601af44d49578dddaddec8639538f89c33943aa073ca7d"),
    ("Python sources", "f01e0ddbe2fd917eb765723935eaceb7a606db3350a9ee059402032ff89789a7"),
    ("Python sidecar", "af4ac525fb69726e592d6b743fd4951b5c61b3ad611d4be1f9099aac362c1579"),
    ("Python cleanup", "e57ec8252683a0d4f2a22472c3fd0c2b1f0b642d0f19b5780cd0078152de018b"),
    ("Python provenance", "42242bf20c667175068a3e140aba6ed1947e69286cab3b9efedf1f9aca91fff0"),
    ("renderer", "2db53fd812c47c613361413200bfadec046be100dbb598a19c665d293bb6c024"),
    ("Desktop", "00cfc4213532da6e78034d720cb79f76a9e232c5f7dfa7f9262314f4e79478e2"),
    ("assembly audit", "771a55fcbac90395a359ea2d5f7e1836c9d2cbc591069dd3242dc168fc0b6fa1"),
    ("focused lifecycle tests", "0f0128a3ebe571e121a664b14311e7e98df6ef8dd8215dc960d70595de4af892"),
)
ENGINEERING_ADHOC_PACK_COMMAND = (
    "CSC_FOR_PULL_REQUEST=true \\\n"
    "    ./node_modules/.bin/electron-builder"
)
EXPECTED_PREPARE_PR_SIGNING_GUARD = '''if (
    Object.prototype.hasOwnProperty.call(environment, "CSC_FOR_PULL_REQUEST") &&
    environment.CSC_FOR_PULL_REQUEST !== "true"
  ) {
    fail("Engineering-smoke PR ad-hoc signing control is invalid");
  }'''
EXPECTED_PYINSTALLER_ARCHIVE_GUARD = '''const REVIEWED_PYINSTALLER_ARCHIVE =
  "Contents/Resources/sidecar/_internal/base_library.zip";'''
EXPECTED_PYINSTALLER_ARCHIVE_INITIALIZER = (
    "let observedReviewedPyInstallerArchive = false;"
)
EXPECTED_PYINSTALLER_ARCHIVE_PREDICATE = '''const isReviewedPyInstallerArchive =
        appRelative === REVIEWED_PYINSTALLER_ARCHIVE &&
        info.isFile() &&
        !info.isSymbolicLink() &&
        info.nlink === 1 &&
        info.size > 0;'''
EXPECTED_PYINSTALLER_ARCHIVE_CLOSURE = '''if (!observedReviewedPyInstallerArchive) {
    fail("Engineering-smoke reviewed Python runtime archive is missing");
  }'''
EXPECTED_INSTALL_ARTIFACT_DECISION = r'''if (
        lower.endsWith(".dmg") ||
        lower.endsWith(".pkg") ||
        (lower.endsWith(".zip") && !isReviewedPyInstallerArchive) ||
        lower.endsWith(".blockmap") ||
        /^(?:latest|alpha|beta|next)-mac\.yml$/.test(lower) ||
        lower === "release-manifest.json" ||
        lower === "update-manifest.json" ||
        lower === "update-manifest.json.sig"
      ) {
        forbidden.push(candidate);
      }'''


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(read(path))


def _reviewed_input_digest(value: Any) -> str:
    if isinstance(value, (Mapping, list)):
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    else:
        serialized = str(value)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _python_emitted_environment_keys(source: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Attribute):
            continue
        if (
            node.test.attr != "emit_github_env"
            or not isinstance(node.test.value, ast.Name)
            or node.test.value.id != "arguments"
        ):
            continue
        keys: list[str] = []
        for statement in node.body:
            if (
                not isinstance(statement, ast.Expr)
                or not isinstance(statement.value, ast.Call)
                or not isinstance(statement.value.func, ast.Name)
                or statement.value.func.id != "print"
                or len(statement.value.args) != 1
                or statement.value.keywords
            ):
                return ()
            argument = statement.value.args[0]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                prefix = argument.value
            elif (
                isinstance(argument, ast.JoinedStr)
                and argument.values
                and isinstance(argument.values[0], ast.Constant)
                and isinstance(argument.values[0].value, str)
            ):
                prefix = argument.values[0].value
            else:
                return ()
            match = re.match(r"^(LCF_[A-Z0-9_]+)=", prefix)
            if match is None:
                return ()
            keys.append(match.group(1))
        return tuple(keys)
    return ()


def load_inputs() -> dict[str, Any]:
    return {
        "workflow": read(WORKFLOW),
        "makefile": read(MAKEFILE),
        "build_script": read(BUILD_SCRIPT),
        "audit_script": read(AUDIT_SCRIPT),
        "python_bootstrap": read(PYTHON_BOOTSTRAP),
        "exact_git_checker": read(EXACT_GIT_CHECKER),
        "exact_git_checker_tests": read(EXACT_GIT_CHECKER_TESTS),
        "exact_node_installer": read(EXACT_NODE_INSTALLER),
        "python_packaging_tests": read(PYTHON_PACKAGING_TESTS),
        "gitignore": read(GITIGNORE),
        "remediation_evidence": read(REMEDIATION_EVIDENCE),
        "package": load_json(DESKTOP_PACKAGE),
        "desktop_package_lock": read(DESKTOP_PACKAGE_LOCK),
        "web_package": load_json(WEB_PACKAGE),
        "web_package_lock": read(WEB_PACKAGE_LOCK),
        "python_build_requirements_lock": read(PYTHON_BUILD_REQUIREMENTS_LOCK),
        "python_runtime_lock": read(PYTHON_RUNTIME_LOCK),
        "python_toolchain_lock": load_json(PYTHON_TOOLCHAIN_LOCK),
        "pyinstaller_spec": read(PYINSTALLER_SPEC),
        "smoke_config": read(SMOKE_CONFIG),
        "common_audit": read(COMMON_AUDIT),
        "prepare": read(PREPARE),
        "desktop_entrypoint_builder": read(DESKTOP_ENTRYPOINT_BUILDER),
        "renderer_builder": read(RENDERER_BUILDER),
        "stage_renderer": read(STAGE_RENDERER),
        "audit_renderer": read(AUDIT_RENDERER),
        "engineering_packaging_tests": read(ENGINEERING_PACKAGING_TESTS),
        "before_pack_tests": read(BEFORE_PACK_TESTS),
        "renderer_packaging_tests": read(RENDERER_PACKAGING_TESTS),
        "before_pack": read(BEFORE_PACK),
        "after_pack": read(AFTER_PACK),
        "bundle_audit": read(BUNDLE_AUDIT),
        "schema": load_json(MANIFEST_SCHEMA),
        "renderer_schema": load_json(RENDERER_MANIFEST_SCHEMA),
        "python_sidecar_schema": load_json(PYTHON_SIDECAR_MANIFEST_SCHEMA),
        "formal_base_config": read(FORMAL_BASE_CONFIG),
        "formal_release_config": read(FORMAL_RELEASE_CONFIG),
        "formal_before_pack": read(FORMAL_BEFORE_PACK),
        "formal_after_pack": read(FORMAL_AFTER_PACK),
        "formal_prepare_release": read(FORMAL_PREPARE_RELEASE),
        "formal_reseal": read(FORMAL_RESEAL),
        "formal_release_policy_tests": read(FORMAL_RELEASE_POLICY_TESTS),
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


def _workflow_job_slice(workflow: str, job_name: str) -> str:
    header = f"  {job_name}:\n"
    jobs_offset = workflow.find("jobs:\n")
    if jobs_offset < 0 or workflow.count(header, jobs_offset) != 1:
        return ""
    start = workflow.find(header, jobs_offset) + len(header)
    following = re.search(r"^  [A-Za-z0-9_-]+:\s*$", workflow[start:], re.MULTILINE)
    end = len(workflow) if following is None else start + following.start()
    return workflow[start:end]


def _workflow_steps(workflow: str, job_name: str) -> list[dict[str, str]]:
    job = _workflow_job_slice(workflow, job_name)
    marker = "    steps:\n"
    if job.count(marker) != 1:
        return []
    step_document = job.split(marker, 1)[1]
    starts = list(re.finditer(r"^      - ", step_document, re.MULTILINE))
    steps: list[dict[str, str]] = []
    for index, start_match in enumerate(starts):
        start = start_match.start()
        end = starts[index + 1].start() if index + 1 < len(starts) else len(step_document)
        document = step_document[start:end]
        name_match = re.match(r"^      - name:\s*(?P<name>[^\n]+)\n", document)
        if name_match is None:
            return []
        run_blocks = _run_blocks(document)
        if len(run_blocks) > 1:
            return []
        uses_match = re.search(r"^\s*uses:\s*(?P<uses>[^\s#]+)", document, re.MULTILINE)
        steps.append(
            {
                "name": name_match.group("name").strip(),
                "run": run_blocks[0].rstrip() if run_blocks else "",
                "uses": uses_match.group("uses") if uses_match else "",
                "document": document,
            }
        )
    return steps


def _canonical_signing_control_text(document: str) -> str:
    continued = re.sub(r"\\\r?\n[ \t]*", "", document)
    yaml_escape = re.compile(
        r"\\(?:x(?P<x>[0-9a-fA-F]{2})|u(?P<u>[0-9a-fA-F]{4})|"
        r"U(?P<U>[0-9a-fA-F]{8})|u\{(?P<ubrace>[0-9a-fA-F]{1,6})\})",
    )

    def decode(match: re.Match[str]) -> str:
        encoded = (
            match.group("x")
            or match.group("u")
            or match.group("U")
            or match.group("ubrace")
        )
        try:
            value = int(encoded, 16)
            if value > 0x10FFFF or 0xD800 <= value <= 0xDFFF:
                return "\ufffd"
            return chr(value)
        except (TypeError, ValueError):
            return "\ufffd"

    decoded = yaml_escape.sub(decode, continued)

    def decode_octal(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group("octal"), 8))
        except (TypeError, ValueError):
            return "\ufffd"

    decoded = re.sub(r"\\(?P<octal>[0-7]{1,3})", decode_octal, decoded)
    without_ansi_c_quotes = re.sub(
        r"\$'([^'\r\n]*)'",
        r"\1",
        decoded,
    )
    without_quoted_simple_parameters = re.sub(
        r'''([\"'])\$(?:[A-Za-z_][A-Za-z0-9_]*|[@*])\1''',
        "",
        without_ansi_c_quotes,
    )
    without_parameter_joins = re.sub(
        r"\$\{[^{}\r\n]*\}",
        "",
        without_quoted_simple_parameters,
    )
    without_string_joins = re.sub(r"\s*\+\s*", "", without_parameter_joins)
    return re.sub(
        r'''['\"\\]+''',
        "",
        without_string_joins,
    ).upper()


def _has_dynamic_signing_control_construction(document: str) -> bool:
    for line in document.splitlines():
        upper = line.upper()
        if (
            "CSC_" in upper
            and "$" in line
            and "FOR" in upper
            and "REQUEST" in upper
        ):
            return True
    return False


def _canonical_identifier_text(document: str) -> str:
    continued = re.sub(r"\\\r?\n[ \t]*", "", document)

    def decode(match: re.Match[str]) -> str:
        encoded = (
            match.group("x")
            or match.group("u")
            or match.group("U")
            or match.group("ubrace")
            or match.group("octal")
        )
        base = 8 if match.group("octal") else 16
        try:
            value = int(encoded, base)
            if value > 0x10FFFF or 0xD800 <= value <= 0xDFFF:
                return "\ufffd"
            return chr(value)
        except (TypeError, ValueError):
            return "\ufffd"

    decoded = re.sub(
        r"\\(?:x(?P<x>[0-9a-fA-F]{2})|u(?P<u>[0-9a-fA-F]{4})|"
        r"U(?P<U>[0-9a-fA-F]{8})|u\{(?P<ubrace>[0-9a-fA-F]{1,6})\}|"
        r"(?P<octal>[0-7]{1,3}))",
        decode,
        continued,
    )
    return re.sub(r'''[\s'"\\$\{\}\(\)\[\]+]+''', "", decoded).upper()


def _run_block_has_bypass(block: str) -> bool:
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.search(r"(?:^|[;&])\s*exit\s+0(?:\s|;|$)", line):
            return True
        if re.search(r"(?:^|[;&])\s*return(?:\s+0)?(?:\s|;|$)", line):
            return True
        if re.search(r"\|\|\s*(?:true|:)(?:\s|;|$)", line):
            return True
        if re.search(r"\bif\s+(?:\[\[?\s*)?false\b", line):
            return True
        if re.search(r"(?:^|[;&])\s*set\s+\+e(?:\s|;|$)", line):
            return True
        if re.search(r"(?<![&>])&\s*$", line):
            return True
    return False


def _source_block(document: str, start: str, end: str) -> str:
    if document.count(start) != 1 or document.count(end) != 1:
        return ""
    return start + document.split(start, 1)[1].split(end, 1)[0]


def _make_target_contract(
    makefile: str,
    target: str,
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    lines = makefile.splitlines()
    headers: list[tuple[int, str]] = []
    pattern = re.compile(rf"^{re.escape(target)}\s*:(?P<dependencies>[^\n]*)$")
    for index, line in enumerate(lines):
        match = pattern.fullmatch(line)
        if match is not None:
            headers.append((index, match.group("dependencies")))
    if len(headers) != 1:
        return None
    index, dependency_text = headers[0]
    if "#" in dependency_text or ";" in dependency_text:
        return None
    dependencies = tuple(dependency_text.split())
    recipe_lines: list[str] = []
    cursor = index + 1
    while cursor < len(lines) and lines[cursor].startswith("\t"):
        recipe_lines.append(lines[cursor][1:])
        cursor += 1

    commands: list[str] = []
    continued: list[str] = []
    for raw_line in recipe_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            continued.append(stripped[:-1].rstrip())
            continue
        continued.append(stripped)
        commands.append(" ".join(continued))
        continued = []
    if continued:
        return None
    return dependencies, tuple(commands)


def _target_recipe(makefile: str, target: str) -> str:
    contract = _make_target_contract(makefile, target)
    if contract is None:
        return ""
    return "\n".join(contract[1])


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
            "components",
            "properties",
            "desktopApp",
            "properties",
            "reviewedPackagePath",
            "const",
        ): "desktop/package.json",
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
            "components",
            "properties",
            "pythonSidecar",
            "properties",
            "pythonBuildToolchainPath",
            "const",
        ): "Contents/Resources/sidecar/python-build-toolchain.json",
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

    expected_required_properties = {
        ("properties", "source", "required"): [
            "repository",
            "commit",
            "tree",
            "sourceSnapshotSha256",
            "sourceDateEpoch",
        ],
        (
            "properties",
            "components",
            "properties",
            "desktopApp",
            "required",
        ): [
            "asarPath",
            "mainPath",
            "mainSha256",
            "mainBytes",
            "preloadPath",
            "preloadSha256",
            "preloadBytes",
            "packagePath",
            "packageSha256",
            "packageBytes",
            "reviewedPackagePath",
            "reviewedPackageSha256",
            "entrypointBuild",
        ],
        (
            "properties",
            "components",
            "properties",
            "desktopApp",
            "properties",
            "reviewedPackageSha256",
            "pattern",
        ): "^[0-9a-f]{64}$",
        (
            "properties",
            "components",
            "properties",
            "desktopApp",
            "properties",
            "entrypointBuild",
            "required",
        ): [
            "builder",
            "builderVersion",
            "nodeVersion",
            "npmVersion",
            "packageLockSha256",
            "installedContentSha256",
            "inputs",
            "inputsSha256",
        ],
        (
            "properties",
            "components",
            "properties",
            "desktopApp",
            "properties",
            "entrypointBuild",
            "properties",
            "nodeVersion",
            "const",
        ): "v22.23.2",
        (
            "properties",
            "components",
            "properties",
            "desktopApp",
            "properties",
            "entrypointBuild",
            "properties",
            "npmVersion",
            "const",
        ): "10.9.8",
        (
            "properties",
            "components",
            "properties",
            "renderer",
            "required",
        ): [
            "resourcePath",
            "manifestPath",
            "manifestSha256",
            "repositoryCommit",
            "repositoryTree",
            "sourceSnapshotSha256",
            "inputSnapshotSha256",
            "files",
            "bytes",
        ],
        (
            "properties",
            "components",
            "properties",
            "pythonSidecar",
            "required",
        ): [
            "resourcePath",
            "manifestPath",
            "manifestSha256",
            "normalizedInventorySha256",
            "repositoryCommit",
            "repositoryTree",
            "sourceSnapshotSha256",
            "pythonBuildToolchainPath",
            "pythonToolchain",
            "files",
            "nativeFiles",
            "components",
        ],
        (
            "properties",
            "components",
            "properties",
            "pythonSidecar",
            "properties",
            "pythonToolchain",
            "required",
        ): [
            "buildRequirementsLockSha256",
            "runtimeLockSha256",
            "runtimeRequirementsSha256",
            "installedTreeContentSha256",
            "buildTools",
        ],
    }
    for keys, expected in expected_required_properties.items():
        if _nested(schema, *keys) != expected:
            errors.append(
                f"manifest schema required properties {'.'.join(keys[:-1])} drifted"
            )

    expected_provenance_patterns = {
        (
            "properties",
            "source",
            "properties",
            "sourceSnapshotSha256",
            "pattern",
        ): "^[0-9a-f]{64}$",
        (
            "properties",
            "components",
            "properties",
            "desktopApp",
            "properties",
            "entrypointBuild",
            "properties",
            "packageLockSha256",
            "pattern",
        ): "^[0-9a-f]{64}$",
        (
            "properties",
            "components",
            "properties",
            "desktopApp",
            "properties",
            "entrypointBuild",
            "properties",
            "installedContentSha256",
            "pattern",
        ): "^[0-9a-f]{64}$",
        (
            "properties",
            "components",
            "properties",
            "desktopApp",
            "properties",
            "entrypointBuild",
            "properties",
            "inputsSha256",
            "pattern",
        ): "^[0-9a-f]{64}$",
        (
            "properties",
            "components",
            "properties",
            "renderer",
            "properties",
            "repositoryTree",
            "pattern",
        ): "^[0-9a-f]{40}$",
        (
            "properties",
            "components",
            "properties",
            "renderer",
            "properties",
            "sourceSnapshotSha256",
            "pattern",
        ): "^[0-9a-f]{64}$",
        (
            "properties",
            "components",
            "properties",
            "renderer",
            "properties",
            "inputSnapshotSha256",
            "pattern",
        ): "^[0-9a-f]{64}$",
        (
            "properties",
            "components",
            "properties",
            "pythonSidecar",
            "properties",
            "repositoryTree",
            "pattern",
        ): "^[0-9a-f]{40}$",
        (
            "properties",
            "components",
            "properties",
            "pythonSidecar",
            "properties",
            "sourceSnapshotSha256",
            "pattern",
        ): "^[0-9a-f]{64}$",
    }
    for keys, expected in expected_provenance_patterns.items():
        if _nested(schema, *keys) != expected:
            errors.append(f"manifest schema provenance pattern {'.'.join(keys)} drifted")
    expected_build_tools = {
        "altgraphVersion": "0.17.4",
        "macholibVersion": "1.16.3",
        "packagingVersion": "26.2",
        "pyinstallerVersion": "6.21.0",
        "pyinstallerHooksContribVersion": "2026.6",
        "setuptoolsVersion": "83.0.0",
        "uvVersion": "0.11.29",
    }
    toolchain_path = (
        "properties",
        "components",
        "properties",
        "pythonSidecar",
        "properties",
        "pythonToolchain",
    )
    if (
        _nested(schema, *toolchain_path, "additionalProperties") is not False
        or _nested(
            schema,
            *toolchain_path,
            "properties",
            "buildTools",
            "additionalProperties",
        )
        is not False
        or _nested(
            schema,
            *toolchain_path,
            "properties",
            "buildTools",
            "required",
        )
        != list(expected_build_tools)
        or any(
            _nested(
                schema,
                *toolchain_path,
                "properties",
                "buildTools",
                "properties",
                name,
                "const",
            )
            != version
            for name, version in expected_build_tools.items()
        )
    ):
        errors.append("engineering manifest Python toolchain schema drifted")
    return errors


def _validate_renderer_manifest_schema(schema: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, Mapping):
        return ["renderer manifest schema must be an object"]

    def visit(value: Any, path: str) -> None:
        if not isinstance(value, Mapping):
            return
        if value.get("type") == "object" and value.get("additionalProperties") is not False:
            errors.append(f"renderer schema object {path} must reject additional properties")
        properties = value.get("properties")
        if isinstance(properties, Mapping):
            for key, child in properties.items():
                visit(child, f"{path}.{key}")

    visit(schema, "$")
    expected = {
        ("required",): ["schemaVersion", "kind", "source", "builder", "files"],
        ("properties", "kind", "const"): "local-context-forge-renderer-build",
        ("properties", "source", "required"): [
            "repositoryCommit",
            "repositoryTree",
            "sourceSnapshotSha256",
            "sourceDateEpoch",
            "packageLockSha256",
            "inputSnapshotSha256",
            "inputFiles",
        ],
        (
            "properties",
            "source",
            "properties",
            "repositoryTree",
            "pattern",
        ): "^[0-9a-f]{40}$",
        (
            "properties",
            "source",
            "properties",
            "sourceSnapshotSha256",
            "pattern",
        ): "^[0-9a-f]{64}$",
        (
            "properties",
            "source",
            "properties",
            "packageLockSha256",
            "pattern",
        ): "^[0-9a-f]{64}$",
        (
            "properties",
            "source",
            "properties",
            "inputSnapshotSha256",
            "pattern",
        ): "^[0-9a-f]{64}$",
        (
            "properties",
            "source",
            "properties",
            "inputFiles",
            "minimum",
        ): 5,
        (
            "properties",
            "builder",
            "required",
        ): [
            "name",
            "version",
            "reactPluginVersion",
            "nodeVersion",
            "npmVersion",
            "installedContentSha256",
        ],
        (
            "properties",
            "builder",
            "properties",
            "nodeVersion",
            "const",
        ): "v22.23.2",
        (
            "properties",
            "builder",
            "properties",
            "npmVersion",
            "const",
        ): "10.9.8",
        (
            "properties",
            "builder",
            "properties",
            "installedContentSha256",
            "pattern",
        ): "^[0-9a-f]{64}$",
    }
    for keys, expected_value in expected.items():
        if _nested(schema, *keys) != expected_value:
            errors.append(f"renderer manifest schema contract {'.'.join(keys)} drifted")
    return errors


def _validate_python_sidecar_manifest_schema(schema: Any) -> list[str]:
    if not isinstance(schema, Mapping):
        return ["Python sidecar manifest schema must be an object"]
    errors: list[str] = []
    required = _nested(schema, "properties", "build", "required")
    for marker in (
        "repositoryCommit",
        "repositoryTree",
        "sourceSnapshotSha256",
        "pythonToolchain",
    ):
        if not isinstance(required, list) or required.count(marker) != 1:
            errors.append(f"Python sidecar manifest schema build contract missing {marker!r}")
    artifacts_required = _nested(schema, "properties", "artifacts", "required")
    if (
        not isinstance(artifacts_required, list)
        or artifacts_required.count("pythonBuildToolchain") != 1
        or _nested(
            schema,
            "properties",
            "artifacts",
            "properties",
            "pythonBuildToolchain",
            "$ref",
        )
        != "#/$defs/safePath"
    ):
        errors.append("Python sidecar manifest schema toolchain artifact drifted")
    if (
        _nested(
            schema,
            "properties",
            "build",
            "properties",
            "repositoryTree",
            "pattern",
        )
        != "^[0-9a-f]{40}$"
    ):
        errors.append("Python sidecar manifest schema pattern for 'repositoryTree' drifted")
    if (
        _nested(
            schema,
            "properties",
            "build",
            "properties",
            "sourceSnapshotSha256",
            "$ref",
        )
        != "#/$defs/sha256"
        or _nested(schema, "$defs", "sha256", "pattern") != "^[0-9a-f]{64}$"
    ):
        errors.append(
            "Python sidecar manifest schema pattern for 'sourceSnapshotSha256' drifted"
        )
    expected_toolchain_required = [
        "buildRequirementsLockSha256",
        "runtimeLockSha256",
        "runtimeRequirementsSha256",
        "installedTreeContentSha256",
        "buildTools",
    ]
    if (
        _nested(schema, "$defs", "pythonToolchain", "additionalProperties")
        is not False
        or _nested(schema, "$defs", "pythonToolchain", "required")
        != expected_toolchain_required
        or any(
            _nested(
                schema,
                "$defs",
                "pythonToolchain",
                "properties",
                name,
                "$ref",
            )
            != "#/$defs/sha256"
            for name in expected_toolchain_required[:-1]
        )
        or _nested(
            schema,
            "$defs",
            "pythonToolchain",
            "properties",
            "buildTools",
            "$ref",
        )
        != "#/$defs/buildTools"
    ):
        errors.append("Python sidecar manifest schema toolchain provenance drifted")
    expected_build_tools = {
        "altgraphVersion": "0.17.4",
        "macholibVersion": "1.16.3",
        "packagingVersion": "26.2",
        "pyinstallerVersion": "6.21.0",
        "pyinstallerHooksContribVersion": "2026.6",
        "setuptoolsVersion": "83.0.0",
        "uvVersion": "0.11.29",
    }
    if (
        _nested(schema, "$defs", "buildTools", "additionalProperties") is not False
        or _nested(schema, "$defs", "buildTools", "required")
        != list(expected_build_tools)
        or any(
            _nested(
                schema,
                "$defs",
                "buildTools",
                "properties",
                name,
                "const",
            )
            != version
            for name, version in expected_build_tools.items()
        )
    ):
        errors.append("Python sidecar manifest schema exact build tool versions drifted")
    return errors


def validate_policy(inputs: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "workflow",
        "makefile",
        "build_script",
        "audit_script",
        "python_bootstrap",
        "exact_git_checker",
        "exact_git_checker_tests",
        "exact_node_installer",
        "python_packaging_tests",
        "gitignore",
        "remediation_evidence",
        "package",
        "desktop_package_lock",
        "web_package",
        "web_package_lock",
        "python_build_requirements_lock",
        "python_runtime_lock",
        "python_toolchain_lock",
        "pyinstaller_spec",
        "smoke_config",
        "common_audit",
        "prepare",
        "desktop_entrypoint_builder",
        "renderer_builder",
        "stage_renderer",
        "audit_renderer",
        "engineering_packaging_tests",
        "before_pack_tests",
        "renderer_packaging_tests",
        "before_pack",
        "after_pack",
        "bundle_audit",
        "schema",
        "renderer_schema",
        "python_sidecar_schema",
        "formal_base_config",
        "formal_release_config",
        "formal_before_pack",
        "formal_after_pack",
        "formal_prepare_release",
        "formal_reseal",
        "formal_release_policy_tests",
        "formal_workflow",
        "status",
        "todo",
        "trace",
        "iteration",
    }
    if set(inputs) != required or set(EXPECTED_REVIEWED_INPUT_SHA256) != required:
        return ["packaged-smoke policy input set drifted"]

    workflow = str(inputs["workflow"])
    makefile = str(inputs["makefile"])
    build_script = str(inputs["build_script"])
    audit_script = str(inputs["audit_script"])
    python_bootstrap = str(inputs["python_bootstrap"])
    exact_git_checker = str(inputs["exact_git_checker"])
    exact_git_checker_tests = str(inputs["exact_git_checker_tests"])
    exact_node_installer = str(inputs["exact_node_installer"])
    python_packaging_tests = str(inputs["python_packaging_tests"])
    gitignore = str(inputs["gitignore"])
    remediation_evidence = str(inputs["remediation_evidence"])
    package = inputs["package"]
    web_package = inputs["web_package"]
    web_package_lock = str(inputs["web_package_lock"])
    smoke_config = str(inputs["smoke_config"])
    common_audit = str(inputs["common_audit"])
    prepare = str(inputs["prepare"])
    desktop_entrypoint_builder = str(inputs["desktop_entrypoint_builder"])
    renderer_builder = str(inputs["renderer_builder"])
    stage_renderer = str(inputs["stage_renderer"])
    audit_renderer = str(inputs["audit_renderer"])
    engineering_packaging_tests = str(inputs["engineering_packaging_tests"])
    before_pack_tests = str(inputs["before_pack_tests"])
    renderer_packaging_tests = str(inputs["renderer_packaging_tests"])
    before_pack = str(inputs["before_pack"])
    after_pack = str(inputs["after_pack"])
    bundle_audit = str(inputs["bundle_audit"])
    formal_before_pack = str(inputs["formal_before_pack"])
    formal_prepare_release = str(inputs["formal_prepare_release"])
    formal_reseal = str(inputs["formal_reseal"])
    formal_release_policy_tests = str(inputs["formal_release_policy_tests"])

    # These source/test/document bindings do not prove that a pathname race is
    # impossible. They make the reviewed implementation, adversarial test corpus,
    # exact ignore boundary, and independent NO-GO handoff part of the policy
    # universe; runtime proof still comes from executing the focused tests and
    # the build plus post-build cleanup validation below.
    for key, expected_digest in EXPECTED_REVIEWED_INPUT_SHA256.items():
        observed_digest = _reviewed_input_digest(inputs[key])
        if observed_digest != expected_digest:
            errors.append(f"reviewed packaged-smoke input {key!r} drifted")
    for marker in ("LCF_SOURCE_SHA", "LCF_SOURCE_TREE"):
        if marker not in build_script:
            errors.append(f"Python sidecar provenance implementation missing {marker!r}")
        if marker not in python_packaging_tests:
            errors.append(f"Python sidecar provenance tests missing {marker!r}")

    python_bootstrap_markers = (
        'TOOLCHAIN_ROOT_PREFIX = "python-sidecar-toolchain-"',
        'INSTALLER_ROOT_PREFIX = "lcf-python-installer."',
        'TOOLCHAIN_EVIDENCE_NAME = "python-build-toolchain.json"',
        '"LCF_REVIEWED_BUILD_PYTHON"',
        '"LCF_REVIEWED_SOURCE_ROOT"',
        '"RUNNER_TEMP"',
        '"backend/packaging/build-requirements.lock"',
        '"backend/uv.lock"',
        '"tools/bootstrap_python_sidecar.py"',
        '"tools/build_python_sidecar.py"',
        '"tools/audit_python_sidecar.py"',
        '"runtime/python-sidecar-build-manifest.schema.json"',
        "def _validate_source_root(",
        "expected_mode=0o700",
        "root != REPOSITORY_ROOT or root != cwd",
        "build._validate_repository_state(",
        "os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC",
        "os.pread(",
        "def _held_toolchain_root(",
        "build._create_bound_child_directory(",
        "build._rollback_bound_directory(",
        '"Python toolchain capability cleanup left a residue"',
        '"Python toolchain failed and exact cleanup failed"',
        "def seal_installed_tree(",
        "_chmod_installed_tree_read_only(descriptor)",
        "def verify_installed_tree(",
        "content_sha256",
        "identity_sha256",
        '"--isolated"',
        '"--only-binary=:all:"',
        '"--require-hashes"',
        '"UV_OFFLINE": "1"',
        '"PIP_CONFIG_FILE": "/dev/null"',
        '"UV_NO_CONFIG": "1"',
        '"UV_NO_BUILD": "1"',
        '"--frozen"',
        'f"/dev/fd/{build_lock.descriptor}"',
        'f"/dev/fd/{runtime_lock.descriptor}"',
        "start_new_session=True",
        "build._terminate_owned_process_group(",
        "process.communicate(timeout=timeout)",
        '"LCF_PYTHON_BUILD_VENV_FD"',
        '"LCF_PYTHON_TOOLCHAIN_EVIDENCE_FD"',
        "pass_fds=child_fds",
        'label="Exact Python sidecar inner build"',
        "verify_toolchain_environment(",
        '"buildRequirementsLockSha256"',
        '"runtimeLockSha256"',
        '"runtimeRequirementsSha256"',
        '"installedTreeContentSha256"',
        '"buildTools"',
        '"files"',
        "_make_installed_tree_cleanup_writable(descriptor)",
        "def install_reviewed_python(",
        "prefix=INSTALLER_ROOT_PREFIX",
        '"/usr/sbin/pkgutil"',
        '"/usr/sbin/spctl"',
        '"/usr/bin/sudo"',
        '"--non-interactive"',
        '"/usr/sbin/installer"',
        '"--install-reviewed-python"',
    )
    for marker in python_bootstrap_markers:
        if marker not in python_bootstrap:
            errors.append(f"exact Python toolchain bootstrap missing {marker!r}")
    exact_toolchain_build = _source_block(
        python_bootstrap,
        "def build_with_exact_toolchain(",
        "\ndef _parser()",
    )
    reviewed_python_install = _source_block(
        python_bootstrap,
        "def install_reviewed_python(",
        "\ndef build_with_exact_toolchain(",
    )
    exact_installer_commands = (
        '("/usr/sbin/pkgutil", "--check-signature", str(package_path))',
        '''(
                            "/usr/sbin/spctl",
                            "--assess",
                            "--type",
                            "install",
                            "--verbose=4",
                            str(package_path),
                        )''',
        '''(
                            "/usr/bin/sudo",
                            "--non-interactive",
                            "/usr/sbin/installer",
                            "-pkg",
                            str(package_path),
                            "-target",
                            "/",
                        )''',
    )
    if (
        "GITHUB_SHA" in _canonical_identifier_text(python_bootstrap)
        or "--no-binary" in python_bootstrap.split(
            "def _validate_exported_runtime_lock", 1
        )[0]
        or ".python-sidecar-build-venv" in python_bootstrap
        or python_bootstrap.count('"--require-hashes"') != 2
        or python_bootstrap.count("build._validate_repository_state(") != 2
        or python_bootstrap.count('"LCF_PYTHON_BUILD_VENV_FD"') != 2
        or exact_toolchain_build.count("installed_seal = seal_installed_tree(") != 1
        or exact_toolchain_build.count("bootstrap_seal = seal_installed_tree(") != 1
        or exact_toolchain_build.count("verify_installed_tree(") != 4
        or exact_toolchain_build.count("_revalidate_source_seal(") < 6
        or exact_toolchain_build.count("pass_fds=child_fds") != 1
        or exact_toolchain_build.count('label="Exact Python sidecar inner build"')
        != 1
        or reviewed_python_install.count("prefix=INSTALLER_ROOT_PREFIX") != 1
        or reviewed_python_install.count("_revalidate_bound_file(") != 2
        or reviewed_python_install.count("_revalidate_source_seal(") < 3
        or any(
            reviewed_python_install.count(command) != 1
            for command in exact_installer_commands
        )
        or python_bootstrap.count('"/usr/sbin/spctl"') != 1
        or "setup.sh" in reviewed_python_install
    ):
        errors.append("exact Python toolchain bootstrap/seal closure drifted")

    for marker in (
        "test_real_venv_seal_verify_execute_and_restore_for_exact_cleanup",
        "test_installed_tree_seal_rejects_same_version_content_drift",
        "test_installed_tree_seal_rejects_root_replacement",
        "test_held_toolchain_root_restores_seal_and_has_no_residue",
        "test_held_toolchain_root_replacement_is_preserved_and_cleanup_fails_closed",
        "test_held_toolchain_root_signal_cleanup_has_no_residue",
        "test_reviewed_python_installer_success_uses_exact_commands_and_cleans_root",
        "test_reviewed_python_installer_failure_cleans_exact_root",
        "test_reviewed_python_installer_signal_cleans_exact_root",
        "test_exact_toolchain_build_success_seals_and_cleans_root",
        "test_exact_toolchain_build_failure_cleans_root",
        "test_exact_toolchain_build_signal_cleans_root",
        "test_exact_source_bound_file_revalidation_rejects_pre_spawn_drift",
        "test_bootstrap_rejects_missing_or_non_module_exact_source_root",
        "test_toolchain_environment_is_closed_against_config_injection",
        "test_toolchain_evidence_rejects_owner_write_after_digest_reseal",
        "test_toolchain_evidence_rejects_symlink_escape_after_digest_reseal",
        "test_toolchain_evidence_rejects_manifest_tamper",
        "test_toolchain_evidence_rejects_impossible_inventory_hierarchy",
        "test_build_manifest_consumes_explicit_toolchain_evidence_without_environment",
        "test_make_uses_only_exact_bootstrap_without_repo_toolchain_scratch",
    ):
        if marker not in python_packaging_tests:
            errors.append(f"exact Python toolchain tests missing {marker!r}")

    python_toolchain_consumer_markers = {
        "Python inner builder": (
            build_script,
            (
                "def _verify_exact_toolchain_environment(",
                "bootstrap.verify_toolchain_environment(environment)",
                "def verify_exact_toolchain() -> None:",
                'raise BuildError("Installed Python toolchain evidence changed")',
                '"pythonToolchain": {',
                'artifacts["pythonBuildToolchain"] = _write_toolchain_evidence_artifact(',
            ),
        ),
        "standalone Python auditor": (
            audit_script,
            (
                "def _validate_manifest_toolchain_evidence(",
                "def _validate_toolchain_evidence_artifact(",
                'artifacts.get("pythonBuildToolchain")',
                '"python-build-toolchain.json"',
                'raise AuditError("Installed Python toolchain content digest is invalid")',
            ),
        ),
    }
    for label, (document, markers) in python_toolchain_consumer_markers.items():
        for marker in markers:
            if marker not in document:
                errors.append(f"{label} toolchain evidence contract missing {marker!r}")

    node_python_toolchain_consumers = {
        "formal/engineering beforePack": (
            formal_before_pack,
            (
                '"tools/bootstrap_python_sidecar.py"',
                '"pythonToolchain",\n      "inputDigests"',
                "function validatePythonToolchainSummary(value, repositoryRoot)",
                '"backend",\n          "packaging",\n          "build-requirements.lock"',
                'path.join(repositoryRoot, "backend", "uv.lock")',
                "function validateInstalledToolchainInventory(",
                "function validatePythonToolchainArtifact(root, manifest, repositoryRoot)",
                'manifest.artifacts.pythonBuildToolchain !== TOOLCHAIN_EVIDENCE_NAME',
                "loadCanonicalJsonAttestation(",
                "canonicalJson({ schemaVersion: 1, entries: value })",
                "validatePythonToolchainArtifact(root, manifest, repositoryRoot);",
            ),
        ),
        "engineering manifest validator": (
            common_audit,
            (
                '"pythonBuildToolchainPath"',
                '"pythonToolchain"',
                'python.pythonBuildToolchainPath !==',
                "const pythonToolchain = assertExactKeys(",
                "EXPECTED_PYTHON_BUILD_TOOLS",
                'uvVersion: "0.11.29"',
            ),
        ),
        "engineering prepare": (
            prepare,
            (
                "const pythonToolchain = pythonBuild.pythonToolchain;",
                'pythonManifest.artifacts.pythonBuildToolchain !==',
                '"Contents/Resources/sidecar/python-build-toolchain.json"',
                "pythonToolchain: JSON.parse(JSON.stringify(pythonToolchain))",
            ),
        ),
        "engineering bundle audit": (
            bundle_audit,
            (
                "const pythonManifest = python.manifest;",
                "python.manifestSha256",
                "manifest.components.pythonSidecar.pythonBuildToolchainPath !==",
                "canonicalJson(manifest.components.pythonSidecar.pythonToolchain) !==",
                "canonicalJson(pythonManifest.build.pythonToolchain)",
            ),
        ),
        "formal runtime reseal": (
            formal_reseal,
            (
                "const python = auditPythonSidecar({",
                "return {\n    formalRelease: true,",
            ),
        ),
    }
    for label, (document, markers) in node_python_toolchain_consumers.items():
        for marker in markers:
            if marker not in document:
                errors.append(
                    f"{label} Python toolchain consumer contract missing {marker!r}"
                )
    if formal_before_pack.count('"pythonToolchain",\n      "inputDigests"') != 2:
        errors.append(
            "formal/engineering beforePack Python toolchain closed build-key "
            "contract drifted"
        )
    for marker in (
        "binds Python toolchain summary, source locks, and canonical artifact inventory",
        "toolchain artifact differs from the manifest",
        "toolchain entry is malformed",
        "toolchain differs from reviewed source locks",
    ):
        if marker not in before_pack_tests:
            errors.append(f"beforePack Python toolchain integration tests missing {marker!r}")
    for marker in (
        "pythonBuildToolchainPath:",
        "installedTreeContentSha256",
        "buildTools: { uvVersion: \"0.11.29\" }",
    ):
        if marker not in engineering_packaging_tests:
            errors.append(f"engineering Python toolchain integration tests missing {marker!r}")

    pyinstaller_capabilities = _source_block(
        build_script,
        "def _prepare_pyinstaller_capabilities(",
        "\ndef run_pyinstaller(",
    )
    bundle_capability_constructor = _source_block(
        build_script,
        "def _create_bundle_capability(",
        "\ndef _validate_bundle_capability(",
    )
    run_pyinstaller_source = _source_block(
        build_script,
        "def run_pyinstaller(",
        "\ndef _license_sources",
    )
    build_sidecar_source = _source_block(
        build_script,
        "def _build_python_sidecar_impl(",
        "\ndef build_python_sidecar(",
    )
    scratch_cleanup_source = _source_block(
        build_script,
        "def _cleanup_scratch_capability(",
        "\ndef _finish_scratch_lifecycle",
    )
    for marker in (
        "class _BundleCapability:",
        "parent_descriptor: int",
        "descriptor: int",
        "snapshot: _DirectorySnapshot",
        "tree_snapshot: tuple[tuple[Any, ...], ...]",
        "def _bundle_capability_path(",
        "def _create_bundle_capability(",
        "def _validate_bundle_capability(",
        "def _verify_held_bundle_tree(",
        "def _close_published_bundle_capability(",
    ):
        if marker not in build_script:
            errors.append(f"Python sidecar candidate capability missing {marker!r}")
    ownership_offsets = [
        bundle_capability_constructor.find("bundle = _BundleCapability("),
        bundle_capability_constructor.find("_bundle_capability_path(bundle)"),
        bundle_capability_constructor.rfind("_validate_source_snapshot(scratch)"),
        bundle_capability_constructor.find("scratch.bundle = bundle"),
        bundle_capability_constructor.find("return bundle"),
    ]
    if (
        any(offset < 0 for offset in ownership_offsets)
        or ownership_offsets != sorted(ownership_offsets)
        or bundle_capability_constructor.count("scratch.bundle = bundle") != 1
    ):
        errors.append("Python sidecar candidate ownership transfer contract drifted")
    for marker in (
        'directory_names = ("dist", "work", "pyinstaller-config", "tmp")',
        'name="lcf-service"',
        "bundle_capability = _create_bundle_capability(",
        "descriptor=pending_bundle_descriptor",
        "producer_directories = {",
        'for name in ("work", "pyinstaller-config", "tmp")',
        "producer_capabilities = _PyInstallerProducerCapabilities(",
    ):
        if pyinstaller_capabilities.count(marker) != 1:
            errors.append(
                f"Python sidecar pre-producer capability binding missing {marker!r}"
            )
    for marker in (
        "_prepare_pyinstaller_capabilities(scratch)",
        "bundle_descriptor=bundle_capability.descriptor",
        "dist_descriptor=bundle_capability.parent_descriptor",
        "_bundle_capability_path(bundle_capability)",
        "return bundle_capability, evidence_capability",
    ):
        if run_pyinstaller_source.count(marker) != 1:
            errors.append(
                f"Python sidecar producer capability handoff missing {marker!r}"
            )
    if run_pyinstaller_source.count("_validate_bundle_capability(") != 2:
        errors.append("Python sidecar producer capability revalidation count drifted")

    candidate_consumer_order = (
        "bundle_capability, evidence = run_pyinstaller(",
        "frozen_smoke = run_frozen_smoke(",
        "components = build_components(",
        "artifacts = write_compliance_artifacts(",
        "normalize_tree(bundle, int(release[\"sourceDateEpoch\"]))",
        "manifest = _build_manifest(",
        "_write_canonical_json(manifest_path, manifest)",
        "summary = final_verifier(bundle)",
        "_publish_owned_bundle(",
    )
    candidate_consumer_offsets = [
        build_sidecar_source.find(marker) for marker in candidate_consumer_order
    ]
    if (
        any(offset < 0 for offset in candidate_consumer_offsets)
        or candidate_consumer_offsets != sorted(candidate_consumer_offsets)
        or build_sidecar_source.count("_validate_bundle_capability(") != 9
        or build_sidecar_source.count("_verify_held_bundle_tree(") != 2
        or build_sidecar_source.count("bundle_descriptor=bundle_capability.descriptor")
        != 1
        or build_sidecar_source.count("_publish_owned_bundle(") != 1
        or "def final_verifier(_candidate: Path)" not in build_sidecar_source
    ):
        errors.append(
            "Python sidecar held candidate producer/consumer/publish chain drifted"
        )
    for marker in (
        "_validate_bundle_capability(\n                capability,",
        "os.close(bundle.descriptor)",
        "os.close(bundle.parent_descriptor)",
        "_remove_tree_contents(\n                capability.build_root_descriptor,",
        "dir_fd=capability.scratch_parent_descriptor",
    ):
        if marker not in scratch_cleanup_source:
            errors.append(
                f"Python sidecar held candidate cleanup contract missing {marker!r}"
            )
    for marker in (
        "test_pyinstaller_first_open_replacement_poison_closes_and_preserves",
        "test_bundle_capability_precedes_producer_and_fd_consumers_ignore_root_aba",
        "test_publish_reuses_the_held_bundle_candidate",
        'in {"dist", "work", "pyinstaller-config", "tmp", "lcf-service"}',
        "held_candidate=capability",
        'assert observed == ["reviewed", "reviewed"]',
        "test_bundle_ownership_transfers_only_after_post_acquisition_validation",
        "assert scratch.bundle is None",
        "assert sentinel_descriptor == bundle_descriptor",
        "test_pyinstaller_command_inherits_source_and_all_private_output_fds",
        "test_pyinstaller_runner_passes_capability_fds_to_grandchildren",
        "test_native_tool_inherits_an_fd_backed_bundle_target",
        "test_source_snapshot_first_open_replacement_is_refused_and_preserved",
        "test_sealed_evidence_consumers_ignore_root_replacement_and_restore",
    ):
        if marker not in python_packaging_tests:
            errors.append(f"Python sidecar candidate capability tests missing {marker!r}")
    for marker in (
        '''capability_descriptors = (
    source_descriptor,
    bundle_descriptor,
    dist_descriptor,
    work_descriptor,
    config_descriptor,
    temp_descriptor,
)''',
        "os.set_inheritable(capability_descriptor, True)",
        "def capability_popen(*args, **kwargs):",
        'if kwargs.get("close_fds") is False and not kwargs.get("pass_fds"):',
        "inherited.update(capability_descriptors)",
        'kwargs["pass_fds"] = tuple(sorted(inherited))',
        'kwargs["close_fds"] = True',
        "subprocess.Popen = capability_popen",
    ):
        if build_script.count(marker) != 1:
            errors.append(f"PyInstaller grandchild capability wrapper missing {marker!r}")

    auditor_build_boundary = _source_block(
        audit_script,
        "def _reviewed_build_boundary(",
        "\ndef _git_provenance_output(",
    )
    auditor_git_output = _source_block(
        audit_script,
        "def _git_provenance_output(",
        "\ndef _git_tree_inventory_sha256(",
    )
    auditor_repository_provenance = _source_block(
        audit_script,
        "def _validate_repository_provenance(",
        "\ndef _validate_input_digests(",
    )
    for marker in (
        'build = importlib.import_module("build_python_sidecar")',
        'expected_module = TOOLS_ROOT / "build_python_sidecar.py"',
        "Path(build.__file__).resolve(strict=True) != expected_module",
        "return build",
    ):
        if auditor_build_boundary.count(marker) != 1:
            errors.append(
                f"standalone Python auditor reviewed module boundary missing {marker!r}"
            )
    for marker in (
        "build._validate_local_git_configuration(repository_root=repository_root)",
        "build._validate_git_info_overrides(repository_root=repository_root)",
        "return build._git_bytes(*arguments, repository_root=repository_root)",
        "return build._git_output(*arguments, repository_root=repository_root)",
    ):
        if auditor_git_output.count(marker) != 1:
            errors.append(f"standalone Python auditor Git boundary missing {marker!r}")
    for marker in (
        "_reviewed_build_boundary()._validate_repository_state(",
        '{"LCF_SOURCE_SHA": commit, "LCF_SOURCE_TREE": tree}',
        'verified.get("sourceSnapshotSha256") != snapshot_digest',
    ):
        if auditor_repository_provenance.count(marker) != 1:
            errors.append(
                f"standalone Python auditor raw repository validation missing {marker!r}"
            )
    for marker in (
        "test_standalone_auditor_reuses_the_exact_hostile_git_boundary",
        '@pytest.mark.parametrize("mutation", ["filter", "index-flag", "info-attributes"])',
        '"filter.hostile.clean"',
        '"--assume-unchanged"',
        'repository / ".git" / "info" / "attributes"',
        "audit._validate_repository_provenance(reviewed, repository)",
        "assert not marker.exists()",
    ):
        if marker not in python_packaging_tests:
            errors.append(f"standalone Python auditor hostile Git tests missing {marker!r}")
    for marker in (
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_GLOBAL",
        "GIT_ATTR_NOSYSTEM",
        "GIT_NO_REPLACE_OBJECTS",
        "core.fsmonitor=false",
        "core.excludesFile=/dev/null",
        "core.attributesFile=/dev/null",
        "core.hooksPath=/dev/null",
        "diff.ignoreSubmodules=none",
    ):
        if marker not in build_script:
            errors.append(
                f"Python sidecar Git provenance isolation missing {marker!r}"
            )
    python_local_git_configuration = _source_block(
        build_script,
        "def _validate_local_git_configuration(",
        "\ndef _validate_git_info_overrides(",
    )
    python_git_info_overrides = _source_block(
        build_script,
        "def _validate_git_info_overrides(",
        "\ndef _validate_git_index(",
    )
    python_git_index = _source_block(
        build_script,
        "def _validate_git_index(",
        "\ndef _validate_tracked_worktree(",
    )
    python_tracked_worktree = _source_block(
        build_script,
        "def _validate_tracked_worktree(",
        "\ndef _validate_repository_state(",
    )
    python_repository_state = _source_block(
        build_script,
        "def _validate_repository_state(",
        "\ndef validate_release_environment(",
    )
    for marker in (
        '"--no-includes"',
        '"--null"',
        '"--list"',
        '"gc.auto": frozenset({"0"})',
        're.fullmatch(r"remote\\..+\\.(?:url|pushurl|fetch)", key)',
        're.fullmatch(r"branch\\..+\\.(?:remote|merge|description)", key)',
        "if allowed_pattern is None:",
    ):
        if python_local_git_configuration.count(marker) != 1:
            errors.append(f"Python sidecar hostile local Git config missing {marker!r}")
    for marker in (
        'Path("info") / "attributes"',
        'Path("info") / "exclude"',
        'line.strip() and not line.lstrip().startswith("#")',
    ):
        if python_git_info_overrides.count(marker) != 1:
            errors.append(f"Python sidecar local Git info guard missing {marker!r}")
    for marker in (
        '"ls-files",\n        "--stage",\n        "-z"',
        'stage != "0"',
        '"ls-files",\n        "-v",\n        "-z"',
        'raw.startswith(b"H ")',
        "flagged_paths != set(expected)",
    ):
        if python_git_index.count(marker) != 1:
            errors.append(f"Python sidecar raw Git index guard missing {marker!r}")
    for marker in (
        "os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC",
        "os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC",
        "follow_symlinks=False",
        "_git_blob_digest(payload_size, payload_chunks) != entry.object_id",
        "_stat_metadata(repository_root.lstat())",
    ):
        if marker not in python_tracked_worktree:
            errors.append(f"Python sidecar raw tracked-worktree guard missing {marker!r}")
    for marker in (
        "_validate_local_git_configuration(repository_root=repository_root)",
        "_validate_git_info_overrides(repository_root=repository_root)",
        "_validate_git_index(inventory, repository_root=repository_root)",
        "_validate_tracked_worktree(inventory, repository_root=repository_root)",
        '"status",\n        "--porcelain=v2",\n        "--untracked-files=all"',
        '"submodule",\n        "status",\n        "--recursive"',
    ):
        if python_repository_state.count(marker) != 1:
            errors.append(f"Python sidecar exact repository gate missing {marker!r}")
    for marker in (
        "test_git_filter_configuration_is_rejected_without_executing_the_filter",
        "test_git_local_execution_and_visibility_keys_are_rejected",
        "test_git_index_hidden_flags_cannot_conceal_tracked_byte_drift",
        "test_git_info_attributes_and_excludes_must_be_comment_only",
        "test_git_info_object_overrides_must_be_empty",
        "test_git_provenance_drops_host_process_git_environment",
        "test_git_replace_refs_cannot_rebind_the_reviewed_commit_tree",
        "test_tracked_worktree_rejects_a_group_writable_parent_directory",
        "test_tracked_worktree_rejects_a_foreign_owned_parent_directory",
    ):
        if marker not in python_packaging_tests:
            errors.append(f"Python sidecar hostile Git tests missing {marker!r}")
    if "GITHUB_SHA" in build_script:
        errors.append("Python sidecar provenance must not fall back to GITHUB_SHA")
    for marker in (
        "_validate_repository_state",
        "LCF_SOURCE_SHA",
        "LCF_SOURCE_TREE",
        "LCF_SOURCE_SNAPSHOT_SHA256",
        "LCF_SOURCE_DATE_EPOCH",
        "repositoryCommit",
        "repositoryTree",
        "sourceSnapshotSha256",
        "web/package-lock.json",
        "package_lock_entry.object_id",
        "sidecar._git_bytes",
        "hashlib.sha1",
        "hashlib.sha256(package_lock_bytes)",
        "rendererPackageLockSha256",
        "LCF_RENDERER_PACKAGE_LOCK_SHA256",
        (
            'selected_package_lock = environment.get(\n'
            '        "LCF_RENDERER_PACKAGE_LOCK_SHA256", ""\n'
            "    ).lower()"
        ),
        "selected_package_lock != renderer_package_lock_sha256",
        "--emit-github-env",
        "--expected-tag",
        'f"refs/tags/{arguments.expected_tag}^{{commit}}"',
    ):
        if marker not in exact_git_checker:
            errors.append(f"exact Git provenance checker missing {marker!r}")
    if "GITHUB_SHA" in _canonical_identifier_text(exact_git_checker):
        errors.append("exact Git provenance checker must not fall back to GITHUB_SHA")
    if (
        _python_emitted_environment_keys(exact_git_checker)
        != EXACT_PROVENANCE_ENV_KEYS
    ):
        errors.append("exact Git provenance checker fixed output key set drifted")
    for marker in (
        "test_expected_tag_uses_the_fully_qualified_tag_ref",
        'self._git(root, "tag", "v1.2.3", tag_commit)',
        'self._git(root, "branch", "v1.2.3", "HEAD")',
        '("rev-parse", "refs/tags/v1.2.3^{commit}")',
    ):
        if exact_git_checker_tests.count(marker) != 1:
            errors.append(f"exact Git provenance tag tests missing {marker!r}")
    try:
        parsed_web_package_lock = json.loads(web_package_lock)
    except (TypeError, ValueError):
        parsed_web_package_lock = None
    if (
        not isinstance(parsed_web_package_lock, Mapping)
        or parsed_web_package_lock.get("lockfileVersion") != 3
        or _nested(
            parsed_web_package_lock,
            "packages",
            "node_modules/vite",
            "version",
        )
        != "7.3.6"
        or _nested(
            parsed_web_package_lock,
            "packages",
            "node_modules/@vitejs/plugin-react",
            "version",
        )
        != "4.7.0"
    ):
        errors.append("reviewed renderer package lock contract drifted")

    exact_node_installer_markers = (
        'const EXPECTED_NODE_VERSION = "v22.23.2";',
        'const EXPECTED_NPM_VERSION = "10.9.8";',
        "function requirePrivateRepositoryRoot(repositoryRoot)",
        "repositoryRoot !== fs.realpathSync.native(repositoryRoot)",
        "info.uid !== process.geteuid()",
        "(info.mode & 0o077) !== 0",
        "function openReviewedMetadataCapability(",
        "fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW",
        "readDescriptorBytes(",
        "stableIdentity(descriptorInfo) !== capability.identity",
        "stableIdentity(pathInfo) !== capability.identity",
        "const packageRootIdentity = stableDirectoryIdentity(packageRoot);",
        "stableDirectoryIdentity(packageRoot) !== packageRootIdentity",
        "const nodeRuntimeRoot = path.dirname(nodeDirectory);",
        "!executable.startsWith(`${nodeRuntimeRoot}${path.sep}`)",
        'const globalConfig = path.join(temporaryHome, "global.npmrc");',
        'const userConfig = path.join(temporaryHome, "user.npmrc");',
        "NPM_CONFIG_GLOBALCONFIG: globalConfig",
        "NPM_CONFIG_USERCONFIG: userConfig",
        '["ci", "--ignore-scripts", "--no-audit", "--no-fund"]',
        "resolvedReal = fs.realpathSync.native(candidate);",
        "!resolvedReal.startsWith(`${nodeModulesRoot}${path.sep}`)",
        "const contentRecords = records.map((record) => {",
        '} else if (record.type === "directory") {\n      content.mode = record.mode;',
        'record.type === "symlink"',
        "content.target = record.target;",
        "const identityRecords = records.map((record) => ({",
        "contentInventorySha256",
        "identitySnapshotSha256",
        "writeCanonicalSeal(sealPath, seal);",
        "verifyNodeInstallSeal({",
        'if (!["install", "verify", "clean", "discard-test"].includes(argv[0]))',
    )
    for marker in exact_node_installer_markers:
        if marker not in exact_node_installer:
            errors.append(f"exact Node installer contract missing {marker!r}")
    if (
        exact_node_installer.count("allowExternalNpmForTest") != 1
        or exact_node_installer.count("capabilities.forEach(revalidateMetadataCapability);")
        != 2
        or exact_node_installer.count("inventoryNodeInstall(nodeModulesRoot)") != 2
        or exact_node_installer.count("function verifyNodeInstallSeal") != 1
        or exact_node_installer.count("writeCanonicalSeal(sealPath, seal);") != 1
    ):
        errors.append("exact Node install capability/seal closure drifted")
    exact_node_test_markers = (
        "rejects a package-lock rename-replace-restore before exact npm can run",
        "rejects an npm executable outside the selected Node runtime before execution",
        "rejects a sealed install-root replacement even when package versions are unchanged",
        "rejects a lexical in-tree symlink whose real target escapes the install",
        "fails the final install postcheck before an artifact can be accepted",
        '"ln -s ../reviewed-tool/cli.js node_modules/.bin/reviewed-tool"',
        "allowExternalNpmForTest: true",
        "npm runtime is unsafe",
        "contentInventorySha256",
        "escaping symlink",
    )
    for marker in exact_node_test_markers:
        if marker not in engineering_packaging_tests:
            errors.append(f"exact Node installer tests missing {marker!r}")

    reviewed_builder_markers = {
        "Desktop exact entrypoint builder": (
            desktop_entrypoint_builder,
            (
                "prepare.readReviewedGitBlob(repositoryRoot, record.objectId)",
                'entryPoints: ["lcf-reviewed:desktop/src/main/index.ts"]',
                'entryPoints: ["lcf-reviewed:desktop/src/preload/index.ts"]',
                "sourceSnapshotSha256: snapshot.sourceSnapshotSha256",
                'const EXPECTED_NODE_VERSION = "v22.23.2";',
                'const EXPECTED_NPM_VERSION = "10.9.8";',
                "installedContentSha256: installSummary.installedContentSha256",
                'writeCanonicalJson(path.join(buildRoot, "entrypoint-build.json"), attestation);',
            ),
        ),
        "renderer exact builder": (
            renderer_builder,
            (
                "prepare.readReviewedGitBlob(repositoryRoot, record.objectId)",
                "input: `${VIRTUAL_PREFIX}web/src/main.tsx`",
                "snapshot.rendererPackageLockSha256 !== rendererPackageLockSha256",
                "repositoryTree: snapshot.tree",
                "sourceSnapshotSha256: snapshot.sourceSnapshotSha256",
                "packageLockSha256: rendererPackageLockSha256",
                'const EXPECTED_NODE_VERSION = "v22.23.2";',
                'const EXPECTED_NPM_VERSION = "10.9.8";',
                "installedContentSha256: installSummary.installedContentSha256",
                "inputsSha256: sha256Bytes(Buffer.from(canonicalJson(inputs), \"utf8\"))",
                "writeCanonicalJson(path.join(distRoot, ATTESTATION_NAME), attestation);",
            ),
        ),
        "renderer stage": (
            stage_renderer,
            (
                "const sourceBuild = validateSource(source, release, environment);",
                "repositoryTree: release.tree",
                "sourceSnapshotSha256: release.sourceSnapshotSha256",
                (
                    "attestation.source.packageLockSha256 !==\n"
                    "      release.rendererPackageLockSha256"
                ),
                "packageLockSha256: attestation.source.packageLockSha256",
                "packageLockSha256: sourceBuild.packageLockSha256",
                "inputSnapshotSha256: sourceBuild.inputsSha256",
            ),
        ),
        "renderer auditor": (
            audit_renderer,
            (
                '"repositoryTree"',
                '"sourceSnapshotSha256"',
                '"inputSnapshotSha256"',
                '"packageLockSha256"',
                "repositoryTree: manifest.source.repositoryTree",
                "sourceSnapshotSha256: manifest.source.sourceSnapshotSha256",
                "inputSnapshotSha256: manifest.source.inputSnapshotSha256",
                "packageLockSha256: manifest.source.packageLockSha256",
            ),
        ),
    }
    for label, (document, markers) in reviewed_builder_markers.items():
        if "GITHUB_SHA" in _canonical_identifier_text(document):
            errors.append(f"{label} must not fall back to GITHUB_SHA")
        for marker in markers:
            if document.count(marker) != 1:
                errors.append(f"{label} exact-source contract missing {marker!r}")

    exact_node_toolchain_consumers = {
        "engineering entrypoint validator": prepare,
        "engineering common audit": common_audit,
        "renderer stage": stage_renderer,
        "renderer audit": audit_renderer,
    }
    for label, document in exact_node_toolchain_consumers.items():
        for marker in (
            "nodeVersion",
            "npmVersion",
            "installedContentSha256",
            '"v22.23.2"',
            '"10.9.8"',
        ):
            if marker not in document:
                errors.append(
                    f"{label} exact Node toolchain value contract missing {marker!r}"
                )

    entrypoint_capability_markers = (
        "function loadEntrypointBuildAttestation(candidate)",
        "fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW",
        "function streamAttestedFile(sourcePath, expected, targetPath, dependencies = {})",
        "const before = fs.fstatSync(sourceDescriptor);",
        "before.nlink !== 1",
        "fs.fsyncSync(targetDescriptor);",
        "const after = fs.fstatSync(sourceDescriptor);",
        "function copyAttestedEntrypointOutputs(",
        "inspectAttestedEntrypointOutputs(destinationRoot, copied);",
        "const copiedEntrypointOutputs = copyAttestedEntrypointOutputs(",
        "const revalidatedEntrypointBuild = validateEntrypointBuild(",
        "function publishPreparedEngineeringSmoke(",
        "publishPreparedEngineeringSmoke(",
    )
    for marker in entrypoint_capability_markers:
        if marker not in prepare:
            errors.append(
                f"engineering held entrypoint/publish contract missing {marker!r}"
            )
    if "fs.copyFileSync" in prepare or "copyFileSync(" in prepare:
        errors.append("engineering entrypoint publish must not reopen source pathnames")

    component_manifest_attestation_markers = {
        "Python sidecar audit": (
            formal_before_pack,
            (
                "const manifestAttestation = loadCanonicalJsonAttestation(",
                "manifest: JSON.parse(JSON.stringify(manifest))",
                "manifestSha256: manifestAttestation.sha256",
            ),
        ),
        "renderer audit": (
            audit_renderer,
            (
                "const manifestAttestation = loadManifest(resolvedRoot);",
                "manifest: JSON.parse(JSON.stringify(manifest))",
                "manifestSha256: manifestAttestation.manifestSha256",
            ),
        ),
        "engineering prepare": (
            prepare,
            (
                "const pythonManifest = python.manifest;",
                "rendererManifestSha256: renderer.manifestSha256",
                "pythonManifestSha256: python.manifestSha256",
                "const revalidatedRenderer = auditExactRenderer(",
                "canonicalJson(revalidatedRenderer) !== canonicalJson(renderer)",
                "const revalidatedPython = auditExactPython(pythonAuditOptions);",
                "canonicalJson(revalidatedPython) !== canonicalJson(python)",
                "auditPrepared(",
                "publishPreparedEngineeringSmoke(",
            ),
        ),
    }
    for label, (document, markers) in component_manifest_attestation_markers.items():
        for marker in markers:
            if marker not in document:
                errors.append(
                    f"{label} single-read manifest attestation contract missing {marker!r}"
                )

    local_git_metadata_function = _source_block(
        prepare,
        "function assertSafeLocalGitMetadata",
        "\nfunction isolatedGitArguments",
    )
    raw_repository_state_function = _source_block(
        prepare,
        "function validateRawRepositoryState",
        "\nfunction inspectRepositorySourceSnapshot",
    )
    local_git_metadata_markers = (
        'const EXACT_LOCAL_GIT_CONFIG_VALUES = Object.freeze({',
        '"gc.auto": Object.freeze(["0"])',
        'const CANONICAL_REPOSITORY_URL =',
        "function isSafeLocalGitConfiguration(name, value)",
        "const reviewedValues = EXACT_LOCAL_GIT_CONFIG_VALUES[normalized];",
        "return reviewedValues.includes(value.toLowerCase());",
        'if (normalized === "remote.origin.url")',
        'if (normalized === "remote.origin.fetch")',
        'const branch = /^branch\\.(.+)\\.(remote|merge)$/.exec(normalized);',
        'const configPath = path.join(gitDirectory, "config");',
        'requireSafeGitControlFile(configPath, "Local Git config");',
        '"--no-includes"',
        'const separator = entry.indexOf("\\n");',
        "const name = entry.slice(0, separator);",
        "const value = entry.slice(separator + 1);",
        "!isSafeLocalGitConfiguration(normalized, value)",
        'for (const relative of ["info/attributes", "info/exclude"])',
        '"info/grafts"',
        '"objects/info/alternates"',
        '"objects/info/http-alternates"',
    )
    if (
        prepare.count("function assertSafeLocalGitMetadata") != 1
        or prepare.count("assertSafeLocalGitMetadata(repositoryRoot);") != 1
        or any(
            prepare.count(marker) != 1
            for marker in local_git_metadata_markers
        )
        or '"--name-only"' in local_git_metadata_function
        or local_git_metadata_function.count("commentsOnly: true") != 2
    ):
        errors.append("engineering hostile local Git metadata contract drifted")
    raw_repository_state_markers = (
        '["ls-files", "--stage", "-z"]',
        'stage !== "0"',
        '["ls-files", "-v", "-z"]',
        "raw[0] !== 0x48",
        "raw[1] !== 0x20",
        "indexRecord.objectId !== record.objectId",
        "fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW",
        "bytes = fs.readFileSync(descriptor);",
        'createHash("sha1")',
        'Buffer.from(`blob ${bytes.length}\\0`, "ascii")',
        "digest !== record.objectId",
    )
    if (
        prepare.count("function validateRawRepositoryState") != 1
        or prepare.count("validateRawRepositoryState(repositoryRoot, inventory);")
        != 2
        or any(
            raw_repository_state_function.count(marker) != 1
            for marker in raw_repository_state_markers
        )
    ):
        errors.append("engineering raw Git index/worktree validation contract drifted")

    desktop_package_chain = {
        "engineering prepare": (
            prepare,
            (
                'const DESKTOP_PACKAGE_PATH = "desktop/package.json";',
                "(record) => record.path === DESKTOP_PACKAGE_PATH",
                "readReviewedGitBlob(repositoryRoot, desktopPackage.objectId)",
                "    desktopPackageSha256,\n    inventory",
                "function loadReviewedDesktopPackageMetadata(",
                "bytes = readReviewedGitBlob(repositoryRoot, record.objectId);",
                "sha256Bytes(bytes) !== source.desktopPackageSha256",
                "const packageMetadata = loadReviewedDesktopPackageMetadata(source);",
                "reviewedPackagePath: DESKTOP_PACKAGE_PATH",
                "reviewedPackageSha256: source.desktopPackageSha256",
                '"desktopPackageSha256"',
            ),
        ),
        "engineering common audit": (
            common_audit,
            (
                '"reviewedPackagePath"',
                '"reviewedPackageSha256"',
                'desktopApp.reviewedPackagePath !== "desktop/package.json"',
                "!SHA256_PATTERN.test(desktopApp.reviewedPackageSha256 || \"\")",
            ),
        ),
        "engineering beforePack": (
            before_pack,
            (
                'desktopApp.reviewedPackagePath !== "desktop/package.json"',
                "desktopApp.reviewedPackageSha256 !== source.desktopPackageSha256",
            ),
        ),
        "engineering bundle audit": (
            bundle_audit,
            (
                "manifest.components.desktopApp.reviewedPackagePath !==",
                '"desktop/package.json"',
                "manifest.components.desktopApp.reviewedPackageSha256 !==",
                "source.desktopPackageSha256",
            ),
        ),
    }
    for label, (document, markers) in desktop_package_chain.items():
        for marker in markers:
            if document.count(marker) != 1:
                errors.append(
                    f"{label} reviewed Desktop package chain missing {marker!r}"
                )

    renderer_attestation_chain = {
        "renderer exact builder": (
            renderer_builder,
            (
                "repositoryTree: snapshot.tree",
                "sourceSnapshotSha256: snapshot.sourceSnapshotSha256",
                "packageLockSha256: rendererPackageLockSha256",
                'inputsSha256: sha256Bytes(Buffer.from(canonicalJson(inputs), "utf8"))',
                "writeCanonicalJson(path.join(distRoot, ATTESTATION_NAME), attestation);",
            ),
        ),
        "renderer stage": (
            stage_renderer,
            (
                "const sourceBuild = validateSource(source, release, environment);",
                "sourceBuild.outputs",
                "repositoryTree: release.tree",
                "sourceSnapshotSha256: release.sourceSnapshotSha256",
                "packageLockSha256: sourceBuild.packageLockSha256",
                "inputSnapshotSha256: sourceBuild.inputsSha256",
                "inputFiles: sourceBuild.inputs",
                "canonicalJson(actual) !== canonicalJson(copied)",
                'digest.digest("hex") !== expected.sha256',
                (
                    "canonicalJson(revalidatedSourceBuild) !== "
                    "canonicalJson(sourceBuild)"
                ),
            ),
        ),
        "renderer auditor": (
            audit_renderer,
            (
                "manifest.source.repositoryTree !== expectedTree",
                (
                    "manifest.source.sourceSnapshotSha256 !== "
                    "expectedSourceSnapshotSha256"
                ),
                "repositoryTree: manifest.source.repositoryTree",
                "sourceSnapshotSha256: manifest.source.sourceSnapshotSha256",
                "inputSnapshotSha256: manifest.source.inputSnapshotSha256",
                "manifest.source.packageLockSha256 !== expectedPackageLockSha256",
                "packageLockSha256: manifest.source.packageLockSha256",
                "process.env.LCF_RENDERER_PACKAGE_LOCK_SHA256",
            ),
        ),
        "engineering prepare": (
            prepare,
            (
                "renderer.repositoryTree !== source.tree",
                (
                    "renderer.sourceSnapshotSha256 !== "
                    "source.sourceSnapshotSha256"
                ),
                "inputSnapshotSha256: renderer.inputSnapshotSha256",
                "readReviewedGitBlob(repositoryRoot, rendererPackageLock.objectId)",
                (
                    "environment.LCF_RENDERER_PACKAGE_LOCK_SHA256 !==\n"
                    "      rendererPackageLockSha256"
                ),
                "expectedPackageLockSha256: source.rendererPackageLockSha256",
            ),
        ),
        "engineering common audit": (
            common_audit,
            (
                "renderer.repositoryTree !== source.tree",
                (
                    "renderer.sourceSnapshotSha256 !== "
                    "source.sourceSnapshotSha256"
                ),
                '!SHA256_PATTERN.test(renderer.inputSnapshotSha256 || "")',
            ),
        ),
        "engineering beforePack": (
            before_pack,
            (
                (
                    "manifest.components.renderer.repositoryTree !== "
                    "renderer.repositoryTree"
                ),
                "manifest.components.renderer.sourceSnapshotSha256 !==",
                "manifest.components.renderer.inputSnapshotSha256 !==",
                "expectedPackageLockSha256: source.rendererPackageLockSha256",
            ),
        ),
        "engineering bundle audit": (
            bundle_audit,
            (
                (
                    "manifest.components.renderer.repositoryTree !== "
                    "renderer.repositoryTree"
                ),
                "manifest.components.renderer.sourceSnapshotSha256 !==",
                "manifest.components.renderer.inputSnapshotSha256 !==",
                "expectedPackageLockSha256: source.rendererPackageLockSha256",
            ),
        ),
    }
    for label, (document, fragments) in renderer_attestation_chain.items():
        for fragment in fragments:
            if document.count(fragment) != 1:
                errors.append(
                    f"{label} producer/consumer attestation chain missing {fragment!r}"
                )
    if (
        stage_renderer.count(
            "const sourceBuild = validateSource(source, release, environment);"
        )
        != 1
        or stage_renderer.count(
            "const revalidatedSourceBuild = validateSource("
        )
        != 1
        or stage_renderer.count("fs.constants.O_NOFOLLOW") != 2
        or stage_renderer.count("fs.fstatSync(sourceDescriptor)") != 2
        or stage_renderer.count("expectedTree: release.tree") != 2
        or stage_renderer.count(
            "expectedSourceSnapshotSha256: release.sourceSnapshotSha256"
        )
        != 2
        or stage_renderer.count(
            "expectedPackageLockSha256: release.rendererPackageLockSha256"
        )
        != 2
    ):
        errors.append("renderer stage held-descriptor revalidation contract drifted")
    for fragment in (
        "const rename = dependencies.rename || fs.renameSync;",
        '`.renderer-previous-${crypto.randomBytes(16).toString("hex")}`',
        "rename(destination, previous);",
        "rename(temporary, destination);",
        "rename(destination, temporary);",
        "rename(previous, destination);",
        'fail("Renderer staging publish rollback failed");',
        'fail("Renderer previous staging cleanup failed");',
    ):
        if stage_renderer.count(fragment) != 1:
            errors.append(f"renderer stage rollback contract missing {fragment!r}")

    reviewed_builder_test_markers = {
        "engineering packaging tests": (
            engineering_packaging_tests,
            (
                "buildEngineeringSmokeEntrypoints.cjs",
                "buildEntrypointsFromSnapshot",
                "selects reviewed Git object bytes before the exact entrypoint build",
                "loadReviewedDesktopPackageMetadata(snapshot, root).version",
                '"9.9.9-transient"',
                ').toBe("0.0.0")',
                "copies held entrypoint descriptors across post-validation pathname replacement and restore",
                "fails closed on a mid-copy entrypoint mutation without touching old staging",
                "restores old engineering staging when the second candidate rename fails",
                "restores old engineering staging when post-publish audit fails",
                "rejects signed-commit gpg configuration without executing its program",
                'await expect(readFile(marker)).rejects.toMatchObject({ code: "ENOENT" });',
                "repositoryTree",
                "sourceSnapshotSha256",
                "LCF_RENDERER_PACKAGE_LOCK_SHA256",
            ),
        ),
        "beforePack tests": (
            before_pack_tests,
            (
                "rejects hostile local Git config before provenance commands can use it",
                '"filter.lcf-attack.clean"',
                '"--skip-worktree"',
                '"--assume-unchanged"',
                'path.join(root, ".git", "info", "attributes")',
                'path.join(root, ".git", "info", "exclude")',
                'git("config", "--local", "gc.auto", "0")',
                'git("config", "--local", "gc.auto", "1")',
                "await expect(readFile(filterMarker)).rejects.toThrow()",
                "LCF_SOURCE_SHA",
                "LCF_SOURCE_TREE",
                "repositoryTree",
                "sourceSnapshotSha256",
                "LCF_RENDERER_PACKAGE_LOCK_SHA256",
            ),
        ),
        "renderer packaging tests": (
            renderer_packaging_tests,
            (
                "buildEngineeringRenderer.cjs",
                "buildRendererFromSnapshot",
                "selects committed Git object bytes before the reviewed renderer build",
                "refuses source drift after attestation without replacing staged output",
                "restores the old staging directory when atomic publish fails",
                "expect(renameCount).toBe(3)",
                'expect(await readFile(oldFile, "utf8")).toBe("existing-staged-output\\n")',
                "repositoryTree",
                "sourceSnapshotSha256",
                "inputSnapshotSha256",
                "LCF_RENDERER_PACKAGE_LOCK_SHA256",
                "expectedPackageLockSha256",
            ),
        ),
    }
    for label, (document, markers) in reviewed_builder_test_markers.items():
        for marker in markers:
            if marker not in document:
                errors.append(f"{label} missing {marker!r}")
    if (
        before_pack_tests.count('git("config", "--local", "gc.auto", "0")')
        != 2
        or before_pack_tests.count(
            'git("config", "--local", "gc.auto", "1")'
        )
        != 1
    ):
        errors.append("beforePack tests missing exact gc.auto allow/reject fixture")
    ignore_rules = [
        line.strip()
        for line in gitignore.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if ignore_rules.count("desktop/generated/python-sidecar-build-*/") != 1:
        errors.append("Python sidecar scratch ignore rule must remain exact")
    for forbidden_rule in (
        "desktop/generated/",
        "desktop/generated/**",
        "desktop/generated/*",
        "desktop/generated/python-sidecar-*",
        "desktop/generated/python-sidecar-build/",
        "desktop/generated/python-sidecar-build*",
        "desktop/generated/python-sidecar-build/**",
    ):
        if forbidden_rule in ignore_rules:
            errors.append("Python sidecar scratch ignore boundary is too broad")
    for marker in (
        "w02-pr21-nogo-authority:",
        "reviewed-head=8c5fd23206b671b768fd21d253bf292642f93a51",
        "reviewed-tree=785f4656de8a7233b6dd632fe4815976d33468fb",
        "decision=NO-GO",
        "H1 build scratch lifecycle",
        "VAL-PACKAGED-SMOKE-001",
        "W10/W11",
        "locked",
        "server-reviewed workflow 与 system Git/runtime",
        "random、euid-owned、`0700` private root 成功后",
        "主动 same-UID namespace/content writer",
        "defense-in-depth",
        "process-level build CLI lifecycle",
        "same-process retry",
        "electron-builder 下载的",
        "base runtime 仍是既有 packager trust boundary",
        "python-sidecar-toolchain-*",
        "lcf-python-installer.*",
        "cleanup-only `always()` gate",
        "不依赖 framework interpreter 或 provenance",
        "success-only step",
        "最后一个 repo-code step",
        "PYTHONDONTWRITEBYTECODE=1",
        "`python -B`",
        "其后不再加载任何影响 production",
    ):
        if marker not in remediation_evidence:
            errors.append(f"PR #21 remediation evidence missing {marker!r}")

    if hashlib.sha256(workflow.encode("utf-8")).hexdigest() != EXPECTED_WORKFLOW_SHA256:
        errors.append("workflow document contract drifted")
    if (
        hashlib.sha256(common_audit.encode("utf-8")).hexdigest()
        != EXPECTED_COMMON_AUDIT_SHA256
    ):
        errors.append("engineering common auditor document contract drifted")
    if hashlib.sha256(prepare.encode("utf-8")).hexdigest() != EXPECTED_PREPARE_SHA256:
        errors.append("engineering prepare document contract drifted")
    if (
        hashlib.sha256(bundle_audit.encode("utf-8")).hexdigest()
        != EXPECTED_BUNDLE_AUDIT_SHA256
    ):
        errors.append("engineering bundle auditor document contract drifted")
    if (
        hashlib.sha256(before_pack.encode("utf-8")).hexdigest()
        != EXPECTED_BEFORE_PACK_SHA256
    ):
        errors.append("engineering beforePack document contract drifted")
    if (
        hashlib.sha256(after_pack.encode("utf-8")).hexdigest()
        != EXPECTED_AFTER_PACK_SHA256
    ):
        errors.append("engineering afterPack document contract drifted")
    if prepare.count(EXPECTED_FORBIDDEN_PRODUCTION_ENVIRONMENT) != 1:
        errors.append("engineering forbidden production environment set drifted")
    if bundle_audit.count(EXPECTED_ELECTRON_HELPER_ALLOWLIST) != 1:
        errors.append("engineering Electron helper allowlist drifted")
    if prepare.count(EXPECTED_PREPARE_PR_SIGNING_GUARD) != 1:
        errors.append("engineering PR signing guard drifted")
    prepare_environment_function = _source_block(
        prepare,
        "function assertNoProductionEnvironment",
        "\nfunction assertEngineeringSmokeMode",
    )
    if (
        hashlib.sha256(prepare_environment_function.encode("utf-8")).hexdigest()
        != EXPECTED_PREPARE_ENVIRONMENT_FUNCTION_SHA256
        or prepare_environment_function != EXPECTED_PREPARE_ENVIRONMENT_FUNCTION
        or re.search(r"\breturn\b", prepare_environment_function)
    ):
        errors.append("engineering production-environment control flow drifted")
    install_artifact_function = _source_block(
        bundle_audit,
        "function assertNoInstallOrReleaseArtifacts",
        "\nfunction writeExternalEvidence",
    )
    if (
        hashlib.sha256(install_artifact_function.encode("utf-8")).hexdigest()
        != EXPECTED_INSTALL_ARTIFACT_FUNCTION_SHA256
        or install_artifact_function != EXPECTED_INSTALL_ARTIFACT_FUNCTION
        or install_artifact_function.count("observedReviewedPyInstallerArchive") != 3
        or re.search(r"\breturn\b", install_artifact_function)
    ):
        errors.append("engineering install-artifact control flow drifted")
    if (
        prepare.count("assertNoProductionEnvironment") != 4
        or prepare.count("assertNoProductionEnvironment(environment);") != 2
        or before_pack.count("assertNoProductionEnvironment") != 2
        or before_pack.count("assertNoProductionEnvironment(environment);") != 1
        or after_pack.count("assertNoProductionEnvironment") != 2
        or after_pack.count("assertNoProductionEnvironment(environment);") != 1
        or bundle_audit.count("assertNoProductionEnvironment") != 2
        or bundle_audit.count("assertNoProductionEnvironment(environment);") != 1
    ):
        errors.append("engineering production-environment caller closure drifted")
    if (
        bundle_audit.count("assertNoInstallOrReleaseArtifacts") != 3
        or bundle_audit.count(
            "assertNoInstallOrReleaseArtifacts(outputRoot, appRoot);"
        )
        != 1
    ):
        errors.append("engineering install-artifact caller closure drifted")

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
    if (
        len(re.findall(r"^\s+if:\s*", workflow, re.MULTILINE)) != 2
        or workflow.count("        if: ${{ always() }}") != 1
    ):
        errors.append(
            "workflow must contain only the repository guard and final cleanup always gate"
        )
    shell_values = re.findall(r"^\s+shell:\s*(\S+)\s*$", workflow, re.MULTILINE)
    if shell_values != ["bash"] * 8:
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
    workflow_steps = _workflow_steps(workflow, "assemble")
    if tuple(step.get("name", "") for step in workflow_steps) != EXPECTED_WORKFLOW_STEPS:
        errors.append("workflow step order or step universe drifted")
    steps_by_name = {
        step.get("name", ""): step
        for step in workflow_steps
        if step.get("name", "")
    }
    expected_step_runs = {
        "Enforce engineering-smoke packaging policy": EXPECTED_POLICY_RUN,
        "Run focused Python sidecar lifecycle tests": EXPECTED_LIFECYCLE_TEST_RUN,
        "Build and audit locked Python sidecar": EXPECTED_PYTHON_BUILD_RUN,
        "Validate Python scratch cleanup": EXPECTED_POST_BUILD_CLEANUP_RUN,
        "Validate Python sidecar provenance": EXPECTED_POST_BUILD_PROVENANCE_RUN,
    }
    for step_name, expected_run in expected_step_runs.items():
        if steps_by_name.get(step_name, {}).get("run") != expected_run:
            errors.append(f"workflow critical step {step_name!r} drifted")
    focused_step_name = "Run focused Python sidecar lifecycle tests"
    focused_run = steps_by_name.get(focused_step_name, {}).get("run", "")
    if (
        not workflow_steps
        or workflow_steps[-1].get("name") != focused_step_name
        or any(
            marker not in focused_run
            for marker in (
                "export PYTHONDONTWRITEBYTECODE=1",
                "python -B -m pip install",
                "backend/.venv/bin/python -B -m pytest -q",
                "tests/backend/test_python_sidecar_packaging.py",
            )
        )
    ):
        errors.append(
            "workflow focused lifecycle tests must be the final repo-code step "
            "with bytecode writes disabled"
        )
    cleanup_step = steps_by_name.get("Validate Python scratch cleanup", {})
    provenance_step = steps_by_name.get("Validate Python sidecar provenance", {})
    if (
        cleanup_step.get("document", "").count("        if: ${{ always() }}")
        != 1
        or "LCF_REVIEWED_BUILD_PYTHON" in cleanup_step.get("run", "")
        or "LCF_SOURCE_" in cleanup_step.get("run", "")
        or re.search(r"^\s*if\s+", cleanup_step.get("run", ""), re.MULTILINE)
        or re.search(r"^\s*if:\s*", provenance_step.get("document", ""), re.MULTILINE)
    ):
        errors.append(
            "workflow cleanup-only always gate must precede and remain independent "
            "of provenance/framework validation"
        )
    bind_source_run = steps_by_name.get("Bind exact source provenance", {}).get(
        "run", ""
    )
    private_bootstrap_markers = (
        '[[ "${LCF_SOURCE_SHA}" =~ ^[0-9a-f]{40}$ ]]',
        'readonly source_prefix="${RUNNER_TEMP}/lcf-reviewed-source."',
        '/usr/bin/mktemp -d "${source_prefix}XXXXXXXXXX"',
        'chmod 0700 "${reviewed_source}"',
        "info.st_uid != os.geteuid()",
        "stat.S_IMODE(info.st_mode) != 0o700",
        "git_bootstrap() {",
        "/usr/bin/env -i \\",
        "GIT_CONFIG_NOSYSTEM=1",
        "GIT_CONFIG_GLOBAL=/dev/null",
        "GIT_ATTR_NOSYSTEM=1",
        "GIT_NO_REPLACE_OBJECTS=1",
        "GIT_PROTOCOL_FROM_USER=0",
        "GIT_ALLOW_PROTOCOL=https",
        "/usr/bin/git \\",
        "-c core.hooksPath=/dev/null",
        "-c gc.auto=0",
        'readonly canonical_repository_url="https://github.com/fredgnr/local-context-forge.git"',
        'readonly reviewed_source_ref="refs/lcf-reviewed/source"',
        '"+${LCF_SOURCE_SHA}:${reviewed_source_ref}"',
        'git_private checkout --quiet --detach "${reviewed_source_ref}"',
        'test "$(git_private rev-parse HEAD)" = "${LCF_SOURCE_SHA}"',
        'cd "${reviewed_source}"',
        '"${bootstrap_python}" -I tools/check_exact_git_provenance.py \\',
        "--emit-github-env > \"${provenance_env}\"",
        'test "$(wc -l < "${provenance_env}")" -eq 5',
        'cat "${provenance_env}" >> "${GITHUB_ENV}"',
        "printf 'LCF_REVIEWED_SOURCE_ROOT=%s\\n' \\",
        "printf 'LCF_REVIEWED_BUILD_PYTHON=%s\\n' \\",
        '"/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13"',
    )
    for marker in private_bootstrap_markers:
        if marker not in bind_source_run:
            errors.append(f"workflow private exact-source bootstrap missing {marker!r}")
    bootstrap_order = (
        'git_bootstrap init --quiet "${reviewed_source}"',
        "git_private fetch --no-tags --force --no-write-fetch-head",
        'git_private checkout --quiet --detach "${reviewed_source_ref}"',
        'test "$(git_private rev-parse HEAD)" = "${LCF_SOURCE_SHA}"',
        'cd "${reviewed_source}"',
        "tools/check_exact_git_provenance.py",
        'cat "${provenance_env}" >> "${GITHUB_ENV}"',
    )
    bootstrap_offsets = [bind_source_run.find(marker) for marker in bootstrap_order]
    if (
        any(offset < 0 for offset in bootstrap_offsets)
        or bootstrap_offsets != sorted(bootstrap_offsets)
        or bind_source_run.count("tools/check_exact_git_provenance.py") != 1
        or bind_source_run.count("git_private fetch") != 1
        or "GITHUB_WORKSPACE" in bind_source_run
        or re.search(r"(?m)^\s*(?:make|node|npm)\s+", bind_source_run)
    ):
        errors.append("workflow private exact-source bootstrap order/closure drifted")
    engineering_bind_offset = next(
        (
            index
            for index, step in enumerate(workflow_steps)
            if step.get("name") == "Bind exact source provenance"
        ),
        -1,
    )
    for step in workflow_steps[engineering_bind_offset + 1 :]:
        run = step.get("run", "")
        repo_command_offsets = [
            offset
            for marker in (
                "make ",
                "node ",
                "npm ",
                "./node_modules/",
                "tools/",
                "desktop/scripts/",
                "python -m ",
            )
            if (offset := run.find(marker)) >= 0
        ]
        if repo_command_offsets:
            reviewed_cwd_offsets = [
                offset
                for marker in (
                    'cd "${LCF_REVIEWED_SOURCE_ROOT}"',
                    "cd '${LCF_REVIEWED_SOURCE_ROOT}'",
                )
                if (offset := run.find(marker)) >= 0
            ]
            if (
                not reviewed_cwd_offsets
                or min(reviewed_cwd_offsets) > min(repo_command_offsets)
            ):
                errors.append(
                    "workflow repo-owned command escaped the private exact-source root"
                )

    renderer_run = steps_by_name.get("Build and stage audited renderer", {}).get(
        "run", ""
    )
    renderer_commands = (
        "node tools/exact_node_install.cjs install \\",
        "run_exact_npm_script web typecheck",
        "node tools/exact_node_install.cjs discard-test \\",
        "node tools/exact_node_install.cjs install \\",
        "run_exact_npm_script web build:packaging",
        "node tools/exact_node_install.cjs verify \\",
        "make renderer-stage",
        "node tools/exact_node_install.cjs verify \\",
    )
    renderer_offsets: list[int] = []
    search_offset = 0
    for command in renderer_commands:
        offset = renderer_run.find(command, search_offset)
        renderer_offsets.append(offset)
        if offset >= 0:
            search_offset = offset + len(command)
    if (
        any(offset < 0 for offset in renderer_offsets)
        or renderer_run.count("node tools/exact_node_install.cjs install \\") != 2
        or renderer_run.count("node tools/exact_node_install.cjs verify \\") != 2
        or renderer_run.count("node tools/exact_node_install.cjs discard-test \\")
        != 1
        or renderer_run.count("run_exact_npm_script web typecheck") != 1
        or renderer_run.count("run_exact_npm_script web build:packaging") != 1
        or "npm --prefix" in renderer_run
        or "npm ci" in renderer_run
    ):
        errors.append("workflow exact renderer install/build/stage order drifted")

    desktop_run = steps_by_name.get(
        "Build and test engineering-smoke Desktop profile", {}
    ).get("run", "")
    desktop_commands = (
        "node tools/exact_node_install.cjs install \\",
        "run_exact_npm_script desktop typecheck",
        "run_exact_npm_script desktop test:engineering-smoke",
        "node tools/exact_node_install.cjs discard-test \\",
        "node tools/exact_node_install.cjs install \\",
        "run_exact_npm_script desktop build:engineering-smoke",
        "node tools/exact_node_install.cjs verify \\",
    )
    desktop_offsets: list[int] = []
    search_offset = 0
    for command in desktop_commands:
        offset = desktop_run.find(command, search_offset)
        desktop_offsets.append(offset)
        if offset >= 0:
            search_offset = offset + len(command)
    if (
        any(offset < 0 for offset in desktop_offsets)
        or desktop_run.count("node tools/exact_node_install.cjs install \\") != 2
        or desktop_run.count("node tools/exact_node_install.cjs verify \\") != 1
        or desktop_run.count("node tools/exact_node_install.cjs discard-test \\")
        != 1
        or desktop_run.count("run_exact_npm_script desktop typecheck") != 1
        or desktop_run.count(
            "run_exact_npm_script desktop test:engineering-smoke"
        )
        != 1
        or desktop_run.count(
            "run_exact_npm_script desktop build:engineering-smoke"
        )
        != 1
        or "npm --prefix" in desktop_run
        or "npm ci" in desktop_run
    ):
        errors.append("workflow exact Desktop test/install/build order drifted")

    for label, block, mode_key, seal_key in (
        (
            "renderer",
            renderer_run,
            "LCF_ENGINEERING_SMOKE=true",
            "LCF_WEB_NODE_INSTALL_SEAL",
        ),
        (
            "Desktop",
            desktop_run,
            "LCF_ENGINEERING_SMOKE=true",
            "LCF_DESKTOP_NODE_INSTALL_SEAL",
        ),
    ):
        for marker in (
            "run_exact_npm_script() (",
            "/usr/bin/env -i \\",
            mode_key,
            *(f'{key}="${{{key}}}" \\' for key in EXACT_PROVENANCE_ENV_KEYS),
            'LCF_REVIEWED_BUILD_PYTHON="${LCF_REVIEWED_BUILD_PYTHON}" \\',
            'LCF_REVIEWED_SOURCE_ROOT="${LCF_REVIEWED_SOURCE_ROOT}" \\',
            f'{seal_key}="${{{seal_key}:-}}" \\',
            "NPM_CONFIG_GLOBALCONFIG=\"${npm_home}/global.npmrc\" \\",
            "NPM_CONFIG_USERCONFIG=\"${npm_home}/user.npmrc\" \\",
            'exit "${exit_status}"',
        ):
            if marker not in block:
                errors.append(f"workflow exact {label} npm boundary missing {marker!r}")

    assembly_run = steps_by_name.get(
        "Assemble and statically audit app directory", {}
    ).get("run", "")
    assembly_order = (
        "--package-root web",
        "--package-root desktop",
        "node desktop/scripts/prepareEngineeringSmoke.cjs",
        "CSC_FOR_PULL_REQUEST=true",
        "./node_modules/.bin/electron-builder",
        "node desktop/scripts/auditEngineeringSmokeBundle.cjs",
        "--package-root web",
        "--package-root desktop",
        "tools/check_exact_git_provenance.py",
    )
    assembly_offsets: list[int] = []
    search_offset = 0
    for command in assembly_order:
        offset = assembly_run.find(command, search_offset)
        assembly_offsets.append(offset)
        if offset >= 0:
            search_offset = offset + len(command)
    if (
        any(offset < 0 for offset in assembly_offsets)
        or assembly_run.count("CSC_FOR_PULL_REQUEST") != 1
        or assembly_run.count("tools/check_exact_git_provenance.py") != 1
        or assembly_run.count("node tools/exact_node_install.cjs verify \\") != 4
    ):
        errors.append("workflow sealed assembly/audit/post-provenance order drifted")
    for marker in (
        f"ref: {SOURCE_EXPRESSION}",
        "fetch-depth: 0",
        "persist-credentials: false",
        f"LCF_SOURCE_SHA: {SOURCE_EXPRESSION}",
        "LCF_GITHUB_CONTEXT_SHA: ${{ github.sha }}",
        'runs-on: macos-15',
        'test "$(uname -m)" = "arm64"',
        "node-version: \"22.23.2\"",
        "python-version: \"3.13.14\"",
        "if: github.repository == 'fredgnr/local-context-forge'",
    ):
        if workflow.count(marker) != 1:
            errors.append(f"workflow exact-source/tool contract missing {marker!r}")
    if workflow.count("tools/check_exact_git_provenance.py") != 2:
        errors.append("workflow exact Git provenance checker call closure drifted")
    for marker in (
        "git rev-parse",
        "git diff",
        "git status",
        "git submodule",
        "git write-tree",
    ):
        if marker in workflow:
            errors.append(f"workflow must not duplicate the exact Git gate with {marker!r}")
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
    if any(_run_block_has_bypass(block) for block in run_blocks):
        errors.append("workflow executable run steps contain a fail-open control")
    canonical_workflow_identifiers = _canonical_identifier_text(workflow)
    if (
        workflow.count('${GITHUB_ENV}') != 6
        or workflow.count('>> "${GITHUB_ENV}"') != 6
        or canonical_workflow_identifiers.count("GITHUB_ENV") != 6
    ):
        errors.append("workflow GITHUB_ENV export surface drifted")
    canonical_signing_controls = _canonical_signing_control_text(workflow)
    if (
        len(
            re.findall(
                r"(?<![A-Z0-9_])CSC_FOR_PULL_REQUEST(?![A-Z0-9_])",
                canonical_signing_controls,
            )
        )
        != 1
        or _has_dynamic_signing_control_construction(workflow)
    ):
        errors.append("workflow PR ad-hoc signing control drifted")
    run_lines = [
        line.strip()
        for block in run_blocks
        for line in block.splitlines()
        if line.strip()
    ]
    if any(line.startswith("#") for line in run_lines):
        errors.append("workflow run blocks must not use comments as policy evidence")
    if (
        workflow.count("CSC_FOR_PULL_REQUEST") != 1
        or assembly_run.count(ENGINEERING_ADHOC_PACK_COMMAND) != 1
    ):
        errors.append("workflow PR ad-hoc signing control drifted")
    if re.search(r"npm --prefix desktop run build(?:\s|$)", workflow):
        errors.append("workflow must not use the companion-building generic build script")
    if re.search(r"npm --prefix web run build(?:\s|$)", workflow):
        errors.append("workflow must not use the live-source generic renderer build script")
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

    if "spctl" in makefile or "spctl" in build_script or "spctl" in audit_script:
        errors.append(
            "spctl Python installer assessment must be delegated only to the exact "
            "bootstrap capability"
        )
    make_contracts = (
        (
            "packaged-smoke-policy-check",
            EXPECTED_POLICY_TARGET,
            "packaged-smoke policy Make target",
        ),
        (
            "python-sidecar-source-verify",
            EXPECTED_PYTHON_SOURCE_VERIFY_TARGET,
            "Python sidecar source-verify Make target",
        ),
        (
            "python-sidecar-install-python",
            EXPECTED_PYTHON_INSTALL_TARGET,
            "Python sidecar installer Make target",
        ),
        (
            "python-sidecar-build",
            EXPECTED_PYTHON_BUILD_TARGET,
            "Python sidecar build Make target",
        ),
        (
            "python-sidecar-audit",
            EXPECTED_PYTHON_AUDIT_TARGET,
            "Python sidecar audit Make target",
        ),
        (
            "python-sidecar-packaging-test",
            EXPECTED_PYTHON_TEST_TARGET,
            "Python sidecar focused-test Make target",
        ),
    )
    for target, expected_contract, label in make_contracts:
        if _make_target_contract(makefile, target) != expected_contract:
            errors.append(f"{label} dependency, command, or order drifted")
    if (
        _make_target_contract(makefile, "python-sidecar-toolchain") is not None
        or ".python-sidecar-build-venv" in makefile
        or ".python-sidecar-build/" in makefile
        or "PYTHON_SIDECAR_BUILD_VENV" in makefile
    ):
        errors.append("Makefile must not restore the repository-local Python toolchain")

    if not isinstance(package, Mapping) or not isinstance(package.get("scripts"), Mapping):
        errors.append("desktop package scripts are missing")
        scripts: Mapping[str, Any] = {}
    else:
        scripts = package["scripts"]
    if _nested(package, "devDependencies", "@electron/asar") != "3.4.1":
        errors.append("Desktop ASAR auditor dependency must remain exact")
    required_scripts = set(EXPECTED_PACKAGE_SCRIPTS) | {
        "build:preload",
        "audit:python-sidecar",
    }
    if not required_scripts.issubset(scripts):
        errors.append("desktop package omits an engineering-smoke script")
    for name, expected in EXPECTED_PACKAGE_SCRIPTS.items():
        if scripts.get(name) != expected:
            errors.append(f"desktop package script {name!r} drifted")
    if scripts.get("audit:python-sidecar") != EXPECTED_STANDALONE_AUDIT_SCRIPT:
        errors.append("Desktop standalone Python auditor script drifted")
    standard_main = str(scripts.get("build:main", ""))
    engineering_build = str(scripts.get("build:engineering-smoke", ""))
    if "__LCF_DISTRIBUTION_PROFILE__" not in standard_main or "standard" not in standard_main:
        errors.append("standard Main build must explicitly compile the standard profile")
    if (
        engineering_build != EXPECTED_PACKAGE_SCRIPTS["build:engineering-smoke"]
        or "esbuild" in engineering_build
        or "src/" in engineering_build
        or "build:preload" in engineering_build
        or "build:companion" in engineering_build
    ):
        errors.append("engineering build must use only the exact-source entrypoint builder")
    if not isinstance(web_package, Mapping) or not isinstance(
        web_package.get("scripts"), Mapping
    ):
        errors.append("web package scripts are missing")
        web_scripts: Mapping[str, Any] = {}
    else:
        web_scripts = web_package["scripts"]
    for name, expected in EXPECTED_WEB_PACKAGE_SCRIPTS.items():
        if web_scripts.get(name) != expected:
            errors.append(f"web package script {name!r} drifted")
    packaging_renderer_build = str(web_scripts.get("build:packaging", ""))
    if (
        packaging_renderer_build
        != EXPECTED_WEB_PACKAGE_SCRIPTS["build:packaging"]
        or "vite build" in packaging_renderer_build
        or "src/" in packaging_renderer_build
    ):
        errors.append("renderer packaging build must use only the exact-source builder")
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
    formal_workflow = formal_documents["formal workflow"]
    formal_build = _workflow_job_slice(formal_workflow, "build")
    formal_build_env = re.search(
        r"^    env:\n(?P<body>(?:      [^\n]+\n)+)\n    steps:\n",
        formal_build,
        re.MULTILINE,
    )
    if (
        formal_build_env is None
        or formal_build_env.group("body") != EXPECTED_FORMAL_JOB_ENV
        or formal_workflow.count("LCF_SOURCE_SHA: ${{ github.sha }}") != 1
    ):
        errors.append("formal workflow source provenance environment drifted")
    formal_build_run_blocks = _run_blocks(formal_build)
    if (
        formal_build.count('${GITHUB_ENV}') != 8
        or formal_build.count('>> "${GITHUB_ENV}"') != 8
        or _canonical_identifier_text(formal_build).count("GITHUB_ENV") != 8
    ):
        errors.append("formal workflow GITHUB_ENV provenance export surface drifted")
    formal_steps = _workflow_steps(formal_workflow, "build")
    formal_step_names = [step.get("name", "") for step in formal_steps]
    formal_critical_steps = (
        "Bind release provenance",
        "Build locked Python sidecar",
        "Validate Python scratch cleanup",
        "Validate Python sidecar provenance",
        "Build and stage production renderer",
        "Build and audit desktop sources",
    )
    try:
        formal_critical_offsets = [
            formal_step_names.index(step_name) for step_name in formal_critical_steps
        ]
    except ValueError:
        formal_critical_offsets = []
    if (
        any(formal_step_names.count(step_name) != 1 for step_name in formal_critical_steps)
        or formal_critical_offsets != sorted(formal_critical_offsets)
    ):
        errors.append("formal workflow Python provenance/build/cleanup order drifted")
    formal_steps_by_name = {
        step.get("name", ""): step
        for step in formal_steps
        if step.get("name", "")
    }
    if (
        formal_steps_by_name.get("Build locked Python sidecar", {}).get("run")
        != EXPECTED_PYTHON_BUILD_RUN
        or formal_steps_by_name.get(
            "Validate Python scratch cleanup",
            {},
        ).get("run")
        != EXPECTED_POST_BUILD_CLEANUP_RUN
        or formal_steps_by_name.get(
            "Validate Python sidecar provenance",
            {},
        ).get("run")
        != EXPECTED_POST_BUILD_PROVENANCE_RUN
    ):
        errors.append("formal workflow Python build/cleanup command drifted")
    formal_cleanup_step = formal_steps_by_name.get(
        "Validate Python scratch cleanup", {}
    )
    formal_provenance_step = formal_steps_by_name.get(
        "Validate Python sidecar provenance", {}
    )
    if (
        formal_build.count("        if: ${{ always() }}") != 1
        or formal_cleanup_step.get("document", "").count(
            "        if: ${{ always() }}"
        )
        != 1
        or "LCF_REVIEWED_BUILD_PYTHON" in formal_cleanup_step.get("run", "")
        or "LCF_SOURCE_" in formal_cleanup_step.get("run", "")
        or re.search(
            r"^\s*if\s+", formal_cleanup_step.get("run", ""), re.MULTILINE
        )
        or re.search(
            r"^\s*if:\s*",
            formal_provenance_step.get("document", ""),
            re.MULTILINE,
        )
    ):
        errors.append(
            "formal workflow cleanup-only always gate must precede and remain "
            "independent of provenance/framework validation"
        )
    if any(
        _run_block_has_bypass(
            formal_steps_by_name.get(step_name, {}).get("run", "")
        )
        for step_name in formal_critical_steps
    ):
        errors.append("formal workflow critical run steps contain a fail-open control")
    bind_release_run = formal_steps_by_name.get("Bind release provenance", {}).get(
        "run",
        "",
    )
    if (
        bind_release_run.count(EXPECTED_FORMAL_PROVENANCE_EXPORT) != 1
        or bind_release_run.count(EXPECTED_FORMAL_QMD_EXPORT) != 1
        or bind_release_run.count('${GITHUB_ENV}') != 4
        or bind_release_run.count('>> "${GITHUB_ENV}"') != 4
        or _canonical_identifier_text(bind_release_run).count("GITHUB_ENV") != 4
        or "${GITHUB_SHA}" in formal_build
    ):
        errors.append("formal workflow commit/tree provenance binding drifted")
    formal_bootstrap_markers = (
        'readonly source_prefix="${RUNNER_TEMP}/lcf-reviewed-source."',
        '/usr/bin/mktemp -d "${source_prefix}XXXXXXXXXX"',
        'chmod 0700 "${reviewed_source}"',
        "info.st_uid != os.geteuid()",
        "stat.S_IMODE(info.st_mode) != 0o700",
        "git_bootstrap() {",
        "/usr/bin/env -i \\",
        "GIT_CONFIG_NOSYSTEM=1",
        "GIT_CONFIG_GLOBAL=/dev/null",
        "GIT_ATTR_NOSYSTEM=1",
        "GIT_NO_REPLACE_OBJECTS=1",
        "GIT_PROTOCOL_FROM_USER=0",
        "GIT_ALLOW_PROTOCOL=https",
        'readonly canonical_repository_url="https://github.com/fredgnr/local-context-forge.git"',
        'readonly reviewed_source_ref="refs/lcf-reviewed/source"',
        '"+${LCF_SOURCE_SHA}:${reviewed_source_ref}"',
        '"+refs/tags/${GITHUB_REF_NAME}:refs/tags/${GITHUB_REF_NAME}"',
        'git_private checkout --quiet --detach "${reviewed_source_ref}"',
        'test "$(git_private rev-parse HEAD)" = "${LCF_SOURCE_SHA}"',
        'test "$(git_private rev-parse "refs/tags/${GITHUB_REF_NAME}^{commit}")" = \\',
        'cd "${reviewed_source}"',
        '"${bootstrap_python}" -I tools/check_exact_git_provenance.py \\',
        '--expected-tag "${GITHUB_REF_NAME}" \\',
        '--emit-github-env > "${provenance_env}"',
        'test "$(wc -l < "${provenance_env}")" -eq 5',
        'cat "${provenance_env}" >> "${GITHUB_ENV}"',
        "printf 'LCF_REVIEWED_SOURCE_ROOT=%s\\n' \\",
        "printf 'LCF_REVIEWED_BUILD_PYTHON=%s\\n' \\",
        '"/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13"',
    )
    for marker in formal_bootstrap_markers:
        if marker not in bind_release_run:
            errors.append(f"formal private exact-source bootstrap missing {marker!r}")
    formal_bootstrap_order = (
        'git_bootstrap init --quiet "${reviewed_source}"',
        "git_private fetch --no-tags --force --no-write-fetch-head",
        '"+${LCF_SOURCE_SHA}:${reviewed_source_ref}"',
        "git_private fetch --no-tags --force --no-write-fetch-head",
        '"+refs/tags/${GITHUB_REF_NAME}:refs/tags/${GITHUB_REF_NAME}"',
        'git_private checkout --quiet --detach "${reviewed_source_ref}"',
        'test "$(git_private rev-parse HEAD)" = "${LCF_SOURCE_SHA}"',
        'test "$(git_private rev-parse "refs/tags/${GITHUB_REF_NAME}^{commit}")"',
        'cd "${reviewed_source}"',
        "tools/check_exact_git_provenance.py",
        'cat "${provenance_env}" >> "${GITHUB_ENV}"',
        "git_safe init --bare --quiet",
        "git_safe fetch --no-tags --force --no-write-fetch-head",
        "git_safe merge-base --is-ancestor",
    )
    formal_bootstrap_offsets: list[int] = []
    search_offset = 0
    for marker in formal_bootstrap_order:
        offset = bind_release_run.find(marker, search_offset)
        formal_bootstrap_offsets.append(offset)
        if offset >= 0:
            search_offset = offset + len(marker)
    if (
        any(offset < 0 for offset in formal_bootstrap_offsets)
        or bind_release_run.count("git_private fetch") != 2
        or bind_release_run.count("tools/check_exact_git_provenance.py") != 1
        or "GITHUB_WORKSPACE" in bind_release_run
        or re.search(r"(?m)^\s*(?:make|node|npm)\s+", bind_release_run)
    ):
        errors.append("formal private exact-source bootstrap order/closure drifted")
    formal_bind_offset = next(
        (
            index
            for index, step in enumerate(formal_steps)
            if step.get("name") == "Bind release provenance"
        ),
        -1,
    )
    for step in formal_steps[formal_bind_offset + 1 :]:
        run = step.get("run", "")
        repo_command_offsets = [
            offset
            for marker in (
                "make ",
                "node ",
                "npm ",
                "./node_modules/",
                "tools/",
                "desktop/scripts/",
                "python -m ",
            )
            if (offset := run.find(marker)) >= 0
        ]
        if repo_command_offsets:
            reviewed_cwd_offsets = [
                offset
                for marker in (
                    'cd "${LCF_REVIEWED_SOURCE_ROOT}"',
                    "cd '${LCF_REVIEWED_SOURCE_ROOT}'",
                )
                if (offset := run.find(marker)) >= 0
            ]
            if (
                not reviewed_cwd_offsets
                or min(reviewed_cwd_offsets) > min(repo_command_offsets)
            ):
                errors.append(
                    "formal repo-owned command escaped the private exact-source root"
                )

    formal_renderer_run = formal_steps_by_name.get(
        "Build and stage production renderer", {}
    ).get("run", "")
    formal_renderer_commands = (
        "node tools/exact_node_install.cjs install \\",
        "run_exact_npm_script web test",
        "run_exact_npm_script web typecheck",
        "node tools/exact_node_install.cjs discard-test \\",
        "node tools/exact_node_install.cjs install \\",
        "run_exact_npm_script web build:packaging",
        "node tools/exact_node_install.cjs verify \\",
        "make renderer-stage",
        "node tools/exact_node_install.cjs verify \\",
    )
    search_offset = 0
    formal_renderer_offsets: list[int] = []
    for command in formal_renderer_commands:
        offset = formal_renderer_run.find(command, search_offset)
        formal_renderer_offsets.append(offset)
        if offset >= 0:
            search_offset = offset + len(command)
    if (
        any(offset < 0 for offset in formal_renderer_offsets)
        or formal_renderer_run.count("node tools/exact_node_install.cjs install \\")
        != 2
        or formal_renderer_run.count("node tools/exact_node_install.cjs verify \\")
        != 2
        or formal_renderer_run.count(
            "node tools/exact_node_install.cjs discard-test \\")
        != 1
        or "npm --prefix" in formal_renderer_run
        or "npm ci" in formal_renderer_run
    ):
        errors.append("formal exact renderer test/install/build/stage order drifted")

    formal_desktop_run = formal_steps_by_name.get(
        "Build and audit desktop sources", {}
    ).get("run", "")
    formal_desktop_commands = (
        "node tools/exact_node_install.cjs install \\",
        "run_exact_npm_script desktop test",
        "run_exact_npm_script desktop typecheck",
        "node tools/exact_node_install.cjs discard-test \\",
        "node tools/exact_node_install.cjs install \\",
        "run_exact_npm_script desktop build",
        "run_exact_npm_script desktop audit:companion",
        "run_exact_npm_script desktop audit:python-sidecar",
        "make qmd-runtime-audit",
        "make renderer-audit",
        "node tools/exact_node_install.cjs verify \\",
    )
    search_offset = 0
    formal_desktop_offsets: list[int] = []
    for command in formal_desktop_commands:
        offset = formal_desktop_run.find(command, search_offset)
        formal_desktop_offsets.append(offset)
        if offset >= 0:
            search_offset = offset + len(command)
    if (
        any(offset < 0 for offset in formal_desktop_offsets)
        or formal_desktop_run.count("node tools/exact_node_install.cjs install \\")
        != 2
        or formal_desktop_run.count("node tools/exact_node_install.cjs verify \\")
        != 1
        or formal_desktop_run.count(
            "node tools/exact_node_install.cjs discard-test \\")
        != 1
        or "npm --prefix" in formal_desktop_run
        or "npm ci" in formal_desktop_run
    ):
        errors.append("formal exact Desktop test/install/audit order drifted")

    for label, block, seal_key in (
        ("renderer", formal_renderer_run, "LCF_WEB_NODE_INSTALL_SEAL"),
        ("Desktop", formal_desktop_run, "LCF_DESKTOP_NODE_INSTALL_SEAL"),
    ):
        for marker in (
            "run_exact_npm_script() (",
            "/usr/bin/env -i \\",
            "LCF_FORMAL_RELEASE=true",
            *(f'{key}="${{{key}}}" \\' for key in EXACT_PROVENANCE_ENV_KEYS),
            'LCF_REVIEWED_BUILD_PYTHON="${LCF_REVIEWED_BUILD_PYTHON}" \\',
            'LCF_REVIEWED_SOURCE_ROOT="${LCF_REVIEWED_SOURCE_ROOT}" \\',
            f'{seal_key}="${{{seal_key}:-}}" \\',
            'exit "${exit_status}"',
        ):
            if marker not in block:
                errors.append(f"formal exact {label} npm boundary missing {marker!r}")

    formal_package_run = formal_steps_by_name.get(
        "Sign, package, and assemble formal assets", {}
    ).get("run", "")
    formal_package_order = (
        "--package-root web",
        "--package-root desktop",
        "./node_modules/.bin/electron-builder",
        "node desktop/scripts/prepareRelease.cjs assemble",
        "--package-root web",
        "--package-root desktop",
        "tools/check_exact_git_provenance.py",
    )
    search_offset = 0
    formal_package_offsets: list[int] = []
    for command in formal_package_order:
        offset = formal_package_run.find(command, search_offset)
        formal_package_offsets.append(offset)
        if offset >= 0:
            search_offset = offset + len(command)
    if (
        any(offset < 0 for offset in formal_package_offsets)
        or formal_package_run.count("node tools/exact_node_install.cjs verify \\")
        != 4
        or formal_package_run.count("tools/check_exact_git_provenance.py") != 1
    ):
        errors.append("formal sealed package/post-provenance order drifted")
    if (
        bind_release_run.count(
            'readonly canonical_repository_url="https://github.com/'
            'fredgnr/local-context-forge.git"'
        )
        != 1
        or bind_release_run.count(
            'readonly reviewed_main_ref="refs/lcf-reviewed/main"'
        )
        != 1
        or bind_release_run.count(EXPECTED_FORMAL_ANCESTRY_REPOSITORY) != 1
        or bind_release_run.count(EXPECTED_FORMAL_GIT_SAFE_HELPER) != 1
        or bind_release_run.count("git_safe init --bare --quiet") != 1
        or bind_release_run.count(EXPECTED_FORMAL_MAIN_FETCH) != 1
        or bind_release_run.count(EXPECTED_FORMAL_MAIN_ANCESTRY) != 1
        or bind_release_run.count("git_safe fetch") != 1
        or bind_release_run.count("git_safe merge-base") != 1
        or bind_release_run.count("/usr/bin/git") != 2
        or "${GITHUB_WORKSPACE}/.git" in bind_release_run
        or re.search(r"(?m)^\s*git\s+", bind_release_run)
        or re.search(r"(?m)^\s*export\s+GIT_", bind_release_run)
        or re.search(r"(?m)^\s*(?:git_safe\s+fetch.*\borigin\b|remote\s+get-url)", bind_release_run)
    ):
        errors.append("formal workflow sanitized canonical Git ancestry gate drifted")
    if formal_build.count("tools/check_exact_git_provenance.py") != 2:
        errors.append("formal workflow exact Git provenance checker call closure drifted")
    for marker in (
        "git rev-parse",
        "git diff",
        "git status",
        "git submodule",
        "git write-tree",
    ):
        if marker in formal_build:
            errors.append(
                f"formal workflow must not duplicate the exact Git gate with {marker!r}"
            )
    if sum(
        block.rstrip() == EXPECTED_POST_BUILD_CLEANUP_RUN
        for block in formal_build_run_blocks
    ) != 1:
        errors.append("formal workflow post-build cleanup validation drifted")
    if sum(
        block.rstrip() == EXPECTED_POST_BUILD_PROVENANCE_RUN
        for block in formal_build_run_blocks
    ) != 1:
        errors.append("formal workflow post-build provenance validation drifted")
    for label, document in formal_documents.items():
        lowered = document.lower()
        if (
            hashlib.sha256(document.encode("utf-8")).hexdigest()
            != EXPECTED_FORMAL_BOUNDARY_SHA256[label]
        ):
            errors.append(f"{label} document contract drifted")
        if "engineering-smoke" in lowered or "electron-builder.smoke.yml" in lowered:
            errors.append(f"{label} must not reference the engineering boundary")
        if (
            re.search(
                r"(?<![A-Z0-9_])CSC_FOR_PULL_REQUEST(?![A-Z0-9_])",
                _canonical_signing_control_text(document),
            )
            or _has_dynamic_signing_control_construction(document)
        ):
            errors.append(f"{label} must not use the engineering PR signing control")

    formal_before_pack = formal_documents["formal beforePack"]
    if "GITHUB_SHA" in _canonical_identifier_text(formal_before_pack):
        errors.append("formal beforePack must not fall back to GITHUB_SHA")
    for marker in (
        "LCF_SOURCE_SHA",
        "LCF_SOURCE_TREE",
        "LCF_RENDERER_PACKAGE_LOCK_SHA256",
        "repositoryTree",
        "sourceSnapshotSha256",
        "expectedPackageLockSha256",
    ):
        if marker not in formal_before_pack:
            errors.append(f"formal beforePack provenance contract missing {marker!r}")
    for marker in (
        'require("./prepareEngineeringSmoke.cjs")',
        ".inspectRepositorySourceSnapshot(repositoryRoot, environment)",
        "commit: snapshot.commit",
        "tree: snapshot.tree",
        "sourceDateEpoch: snapshot.sourceDateEpoch",
        "sourceSnapshotSha256: snapshot.sourceSnapshotSha256",
    ):
        if formal_before_pack.count(marker) != 1:
            errors.append(f"formal beforePack provenance contract missing {marker!r}")

    formal_renderer_options = _source_block(
        formal_prepare_release,
        "function packagedRendererAuditOptions",
        "\nfunction verifyApp",
    )
    for marker in (
        "LCF_SOURCE_TREE",
        "LCF_SOURCE_SNAPSHOT_SHA256",
        "LCF_RENDERER_PACKAGE_LOCK_SHA256",
        "expectedCommit: release.commit",
        "expectedTree: tree",
        "expectedSourceSnapshotSha256: sourceSnapshotSha256",
        "expectedSourceDateEpoch: release.sourceDateEpoch",
        "expectedPackageLockSha256: rendererPackageLockSha256",
    ):
        if formal_renderer_options.count(marker) != 1:
            errors.append(
                f"formal renderer audit provenance options missing {marker!r}"
            )
    if "GITHUB_SHA" in _canonical_identifier_text(formal_renderer_options):
        errors.append("formal renderer audit provenance must not fall back to GITHUB_SHA")
    for marker in (
        "environment.LCF_SOURCE_SHA",
        "environment.LCF_SOURCE_TREE",
        "environment.LCF_SOURCE_SNAPSHOT_SHA256",
        "environment.LCF_RENDERER_PACKAGE_LOCK_SHA256",
        '!/^[0-9a-f]{40}$/.test(environment.LCF_SOURCE_TREE || "")',
        (
            '!/^[0-9a-f]{64}$/.test(\n'
            '      environment.LCF_RENDERER_PACKAGE_LOCK_SHA256 || ""\n'
            "    )"
        ),
        "expectedCommit: environment.LCF_SOURCE_SHA",
        "expectedTree: environment.LCF_SOURCE_TREE",
        "expectedSourceSnapshotSha256:",
        "expectedPackageLockSha256:",
        (
            "expectedPackageLockSha256:\n"
            "      environment.LCF_RENDERER_PACKAGE_LOCK_SHA256"
        ),
    ):
        if marker not in formal_reseal:
            errors.append(f"formal runtime renderer reseal contract missing {marker!r}")
    for marker in (
        "packagedRendererAuditOptions",
        "LCF_SOURCE_TREE:'c'.repeat(40)",
        "LCF_SOURCE_SNAPSHOT_SHA256:'d'.repeat(64)",
        "LCF_RENDERER_PACKAGE_LOCK_SHA256:'e'.repeat(64)",
        "commit:options.expectedCommit",
        "tree:options.expectedTree",
        "snapshot:options.expectedSourceSnapshotSha256",
        "packageLock:options.expectedPackageLockSha256",
        "epoch:options.expectedSourceDateEpoch",
        'tree: "c".repeat(40)',
        'snapshot: "d".repeat(64)',
        'packageLock: "e".repeat(64)',
    ):
        if marker not in formal_release_policy_tests:
            errors.append(f"formal renderer provenance tests missing {marker!r}")

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
        if "GITHUB_SHA" in _canonical_identifier_text(document):
            errors.append(f"engineering {label} must not fall back to GITHUB_SHA")
    engineering_provenance_markers = {
        "prepare": (
            "LCF_SOURCE_SHA",
            "LCF_SOURCE_TREE",
            "LCF_RENDERER_PACKAGE_LOCK_SHA256",
            "rendererPackageLockSha256",
            "repositoryTree",
            "sourceSnapshotSha256",
            "GIT_ATTR_NOSYSTEM",
            "GIT_NO_REPLACE_OBJECTS",
            "core.fsmonitor=false",
            "core.excludesFile=/dev/null",
            "core.attributesFile=/dev/null",
            "core.hooksPath=/dev/null",
            "diff.ignoreSubmodules=none",
            '"write-tree"',
            '"ls-tree"',
            '"submodule"',
        ),
        "beforePack": ("repositoryTree", "sourceSnapshotSha256"),
        "bundle audit": ("repositoryTree", "sourceSnapshotSha256"),
        "common audit": ("repositoryTree", "sourceSnapshotSha256"),
    }
    engineering_provenance_documents = {
        **engineering_scripts,
        "common audit": common_audit,
    }
    for label, markers in engineering_provenance_markers.items():
        document = engineering_provenance_documents[label]
        for marker in markers:
            if marker not in document:
                errors.append(
                    f"engineering {label} provenance contract missing {marker!r}"
                )
    for marker in (
        "auditPythonSidecar",
        "auditRenderer",
        "LCF_SOURCE_SHA",
        "LCF_SOURCE_TREE",
        "repositoryTree",
        "sourceSnapshotSha256",
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
        "REVIEWED_PYINSTALLER_ARCHIVE",
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
    for reviewed_fragment in (
        EXPECTED_PYINSTALLER_ARCHIVE_GUARD,
        EXPECTED_PYINSTALLER_ARCHIVE_INITIALIZER,
        EXPECTED_PYINSTALLER_ARCHIVE_PREDICATE,
        EXPECTED_INSTALL_ARTIFACT_DECISION,
        EXPECTED_PYINSTALLER_ARCHIVE_CLOSURE,
    ):
        if bundle_audit.count(reviewed_fragment) != 1:
            errors.append("engineering PyInstaller archive exception drifted")
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
    errors.extend(_validate_renderer_manifest_schema(inputs["renderer_schema"]))
    errors.extend(
        _validate_python_sidecar_manifest_schema(inputs["python_sidecar_schema"])
    )

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
    for stale_claim in (
        "formal release path unchanged",
        "与 formal release 严格隔离",
        "建立与 formal release 隔离的 macOS arm64",
    ):
        if stale_claim in trace + todo + iteration:
            errors.append(f"governance contains stale formal-isolation claim {stale_claim!r}")
    for marker in (
        "shared exact provenance/build boundary",
        ".github/workflows/desktop-release.yml",
        "tools/{check_exact_git_provenance.py,exact_node_install.cjs,bootstrap_python_sidecar.py,build_python_sidecar.py,audit_python_sidecar.py}",
        "desktop/scripts/buildEngineeringSmokeEntrypoints.cjs",
        "web/scripts/buildEngineeringRenderer.cjs",
        "runtime/{engineering-smoke,renderer-build,python-sidecar-build-manifest}.schema.json",
        "formal Draft/promotion",
        "python-sidecar-toolchain-*",
        "lcf-python-installer.*",
        "首个 post-build cleanup-only `always()` gate",
        "不依赖 framework/provenance",
        "success-only provenance validation",
        "final repo-code",
        "PYTHONDONTWRITEBYTECODE=1",
        "`python -B`",
        "其后不再有 production repo Python load",
    ):
        if marker not in iteration:
            errors.append(f"W02 owned-path boundary missing {marker!r}")
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

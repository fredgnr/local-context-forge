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
    "fb30be64f717856b2f86c3f95911d549cda235779663ab7ee6334beab7159177"
)
MAKEFILE = ROOT / "Makefile"
BUILD_SCRIPT = ROOT / "tools" / "build_python_sidecar.py"
AUDIT_SCRIPT = ROOT / "tools" / "audit_python_sidecar.py"
PYTHON_BOOTSTRAP = ROOT / "tools" / "bootstrap_python_sidecar.py"
FRAMEWORK_VERIFIER = ROOT / "tools" / "verify_reviewed_python_framework.cjs"
FRAMEWORK_VERIFIER_TESTS = (
    ROOT / "tools" / "tests" / "verify_reviewed_python_framework.test.cjs"
)
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
    "workflow": "fb30be64f717856b2f86c3f95911d549cda235779663ab7ee6334beab7159177",
    "makefile": "0406bfd27e312250c48d27899ccff958f25b9fe347871e7643950c437f688977",
    "build_script": "3cc787877d1fb65b8b551911a132400a0fd8e2d3eaf543975eceb88b131d1c19",
    "audit_script": "d3b2d638e28981915f346ead114f86f8bc82ddbbfb91f15416bc3127866504c9",
    "python_bootstrap": "0a2e6671f7a765f09e31e20a306be48b3756f28b110ae7244a9eefa0ac4e45c4",
    "framework_verifier": "ffbf6ed2f41a35f44edda68bdd831be4d42384f9488dcdc93f8242abcfb9e218",
    "framework_verifier_tests": "59f34be890573a0759519022f5dac39572d5330d1f5192a518aa362a6844a46d",
    "exact_git_checker": "aa28265267e99f6fea379401783d6b7fbe76f43f0a6cf9f15485ebfcce057aac",
    "exact_git_checker_tests": "4e5afe7d4eefedd9e47a25c3dc1bb77ebc1977b0325382d3f766784e57fdf0d4",
    "exact_node_installer": "9c551014e06a3315d386eb1f418a6548fe6c92b653767da914b6ddaa99cb0849",
    "python_packaging_tests": "c89f4182106c65d4fa0d605ff3d235337a3d6dd3c65c675882e57d07b5ec9d11",
    "gitignore": "eee9ec14df0b6a9cc4a6ede3020c5ab84373f6199e36ff3eafbaac832ecc1c1c",
    "remediation_evidence": "81695dbc6c131270acef3d0f37ef52f34dcf7ecf345bfa0b1cf831c8bdaffd7d",
    "package": "7d4a247182d89a83734e151df373215f30c3932c7cb99c295c48900baea6e1e7",
    "desktop_package_lock": "10f0dafcd0aecd24985c313209ff42e2759aabe3cdcf2b4e71ed6b6bbd317f60",
    "web_package": "0270e22c0745542be7ab5d792adef4a3d60b3565b85ec037db668e27c1a8e621",
    "web_package_lock": "ae4f9bdf4283763a980ee4b21f3fdd844d4de43a0b35fa7086406eddc2ab857f",
    "python_build_requirements_lock": "1e16e69c50364465e8587e58d4399c34146d11a91bfa3a2399e80e0741bf6342",
    "python_runtime_lock": "a961d5863a346c820cfdfa9daae0223672e761302b5f5aea92ef779c1b69f121",
    "python_toolchain_lock": "07eea5053918470ec59c38bf8780df6de8871636278761b22a74ff7dbc4c0a8a",
    "pyinstaller_spec": "e61b437496bd243f1fcbf73fae3faae911199f4d5d0f352f6365d7828928289d",
    "smoke_config": "b7b9dedb2fbe15cf5682ddd8255286feb799cc28eb2454c0ceaf4b5ec201b448",
    "common_audit": "1e754dc8f4d2e76f3a28a71f86622e6b0338feaf2ad4112fe6666d108c969398",
    "prepare": "8735b655e89565bd3209d3884d1e6ad75cd451357a0c528dbe5b78705a59c0d0",
    "desktop_entrypoint_builder": "aa6da03de871d8af03f544d2adca03772d6242ca23a8698a7c714ca79d84b1f1",
    "renderer_builder": "c7f60680717d80fd04303f87f8b4ca89895c03d7394738340c2dcf3c4b367b43",
    "stage_renderer": "853820c64eecd8c5126a0bb9cfded3b85f5be34fa3011f092cc0c73e7cf7fd9c",
    "audit_renderer": "d52fc0ba5feddd39311f800ad8d9a014695b0b45939d66a932e4c1e6ffe65d36",
    "engineering_packaging_tests": "af45aee101092d8eed9c91037b61db6499a156c9ec4a86232ff734faaac13354",
    "before_pack_tests": "911301ab98467b9f502ebd97c319fc12720acd0590b1e09673e46f689992ac30",
    "renderer_packaging_tests": "4122f11a3bdfffd0b350aea7cd8027c8363527afb7fe3f61b3011d3c7b7df6ce",
    "before_pack": "526b7a4bf8af1c68a94ebfdf0ac624771719d2b1974c3ac0246022ccc3af1882",
    "after_pack": "d513011fcbc5252665f8ab73ae24bea36448821bffb3fbf9aa888b6a1f836d93",
    "bundle_audit": "6cf28dfd98d5f5ac26b71488a8a57696d0a110ee3f21c248669ae6b580ab1905",
    "schema": "50af250a3a9af04d50f9bb51c2dfc1b4a55bedd3b2d5ca6eae7c50b8d4248d9b",
    "renderer_schema": "f24c1abc32aae2bb033b455f730f523f66edbc2c4f8f738cbf2c5dec399ba34b",
    "python_sidecar_schema": "6c5c4fb707d29c02676a34c76f00c2e0eec509df2500be6d73b5f6aa8d97cb1c",
    "formal_base_config": "cede533e71bdfb00401451e3016b7c7032b5867b5ba0147682d72029d08cafb4",
    "formal_release_config": "72a80df25946ad9526a021efcf9f3295d2075c622f576508d7d400394adfdfcd",
    "formal_before_pack": "2e7ec5a008066f46024dfa9d3d063f55ff62dcf1dc484f20f53978843e8028c4",
    "formal_after_pack": "30cc9387e456f09f5402a9fc551d115396150259f9e926bf82d6ba74660d23c5",
    "formal_prepare_release": "86f42e539c4c9825760de56ccd07409b1cec07ac588380f4e64da41612df3311",
    "formal_reseal": "ef9292505be5ced0fb5b464cc9f075d48a20f8b8ee41aa08a6c4c0fbbbd1091e",
    "formal_release_policy_tests": "73b336688aba5319407672bf80d235430fdcb427d5e32e2f0581e854ba8d7ead",
    "formal_workflow": "fcaba8c76c6ad5b840c30ba60ca1eee7b90d2a67f1d1678ea44bd061034ecf85",
    "status": "05ddb9b308fba45d73a0b013949372f13416d6e9627297253c2ccf01ccaf1ee2",
    "todo": "d585d1f2e9dffb2934f8d28e83527a9d7e9cf7c02cfbe1ae185731cea27677f8",
    "trace": "23cac3d7c72704f549fdf84839c1d268d08f5ffdecd97e51c9d9b6d237450a93",
    "iteration": "68f10f1917605423e67a691fbc803d9407f42b373018382d55f7683ac359208c",
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
        "2e7ec5a008066f46024dfa9d3d063f55ff62dcf1dc484f20f53978843e8028c4"
    ),
    "formal afterPack": (
        "30cc9387e456f09f5402a9fc551d115396150259f9e926bf82d6ba74660d23c5"
    ),
    "formal workflow": (
        "fcaba8c76c6ad5b840c30ba60ca1eee7b90d2a67f1d1678ea44bd061034ecf85"
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
    "Set up locked Node",
    "Bind locked framework verifier Node",
    "Provision reviewed build Python without executing it",
    "Seal reviewed build Python framework",
    "Bind exact source provenance",
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
EXPECTED_FRAMEWORK_NODE_BIND_RUN_SHA256 = (
    "37b18d403af947f37679119bdec8309417ea7363139cd3db602d162b217da689"
)
EXPECTED_FRAMEWORK_PROVISION_RUN_SHA256 = (
    "099831784f1f5181d83042bb077d27265922cc23e7e129b97c8c01a6a0a24cec"
)
EXPECTED_FRAMEWORK_PLACEHOLDER_CLEANUP = r'''cleanup_producer() {
  readonly saved_status="$?"
  trap - EXIT
  cleanup_status=0
  cleanup_quarantine="${framework_quarantine_placeholder:-none}"
  cleanup_quarantine_prefix="${framework_quarantine_prefix:-none}"
  cleanup_quarantine_suffix="${cleanup_quarantine#"${cleanup_quarantine_prefix}"}"
  if test "${framework_quarantine_placeholder_identity:-none}" != "none"; then
    if test "${cleanup_quarantine%/*}" = "${framework_parent:-none}" && \
      test "${cleanup_quarantine}" = \
        "${cleanup_quarantine_prefix}${cleanup_quarantine_suffix}" && \
      [[ "${cleanup_quarantine_suffix}" =~ ^[A-Za-z0-9]{10}$ ]] && \
      test -d "${cleanup_quarantine}" && \
      test ! -L "${cleanup_quarantine}" && \
      test "$(/usr/bin/stat -f '%d:%i' "${cleanup_quarantine}")" = \
        "${framework_quarantine_placeholder_identity}"; then
      /usr/bin/sudo --non-interactive /bin/rmdir \
        "${cleanup_quarantine}" || {
          candidate_status="$?"
          if test "${cleanup_status}" -eq 0; then
            cleanup_status="${candidate_status}"
          fi
        }
    else
      cleanup_status=70
    fi
  fi
  /usr/bin/find -x "${producer_root}" -depth -delete || {
    candidate_status="$?"
    if test "${cleanup_status}" -eq 0; then
      cleanup_status="${candidate_status}"
    fi
  }
  if test "${saved_status}" -ne 0; then
    exit "${saved_status}"
  fi
  exit "${cleanup_status}"
}'''
EXPECTED_FRAMEWORK_QUARANTINE_TRANSITION = r'''readonly framework_quarantine_prefix="${framework_parent}/.lcf-python-quarantine."
framework_quarantine="none"
framework_quarantine_identity="none"
if test -e "${framework_root}" || test -L "${framework_root}"; then
  test -d "${framework_root}"
  test ! -L "${framework_root}"
  readonly previous_root_identity="$(/usr/bin/stat -f '%d:%i' "${framework_root}")"
  framework_quarantine="$(
    /usr/bin/sudo --non-interactive /usr/bin/mktemp -d \
      "${framework_quarantine_prefix}XXXXXXXXXX"
  )"
  framework_quarantine_suffix="${framework_quarantine#"${framework_quarantine_prefix}"}"
  readonly framework_quarantine_suffix
  test "${framework_quarantine%/*}" = "${framework_parent}"
  test "${framework_quarantine}" = \
    "${framework_quarantine_prefix}${framework_quarantine_suffix}"
  [[ "${framework_quarantine_suffix}" =~ ^[A-Za-z0-9]{10}$ ]]
  test -d "${framework_quarantine}"
  test ! -L "${framework_quarantine}"
  framework_quarantine_placeholder="${framework_quarantine}"
  framework_quarantine_placeholder_identity="$(/usr/bin/stat -f '%d:%i' \
    "${framework_quarantine_placeholder}")"
  test "$(/usr/bin/stat -f '%u' \
    "${framework_quarantine}")" = "0"
  test "$(/usr/bin/stat -f '%Lp' \
    "${framework_quarantine}")" = "700"
  /usr/bin/sudo --non-interactive /bin/rmdir "${framework_quarantine}"
  test ! -e "${framework_quarantine}"
  test ! -L "${framework_quarantine}"
  framework_quarantine_placeholder_identity="none"
  framework_quarantine_placeholder="none"
  /usr/bin/sudo --non-interactive /bin/mv \
    "${framework_root}" "${framework_quarantine}"
  test ! -e "${framework_root}"
  test ! -L "${framework_root}"
  test -d "${framework_quarantine}"
  test ! -L "${framework_quarantine}"
  test "$(/usr/bin/stat -f '%d:%i' \
    "${framework_quarantine}")" = "${previous_root_identity}"
  framework_quarantine_identity="${previous_root_identity}"
fi'''
EXPECTED_FRAMEWORK_SEAL_TRANSACTION_SENTINELS = r'''seal_transaction_phase="pending"
seal_installed_root_identity="none"
seal_quarantine_state="unvalidated"
seal_quarantine="none"
seal_quarantine_identity="none"'''
EXPECTED_FRAMEWORK_SEAL_TRANSACTION_CLEANUP = r'''cleanup_sealed_framework() {
  readonly saved_status="$?"
  trap - EXIT
  cleanup_status=0
  rollback_ready=1
  if test "${seal_transaction_phase:-unvalidated}" = "pending"; then
    if test "${seal_installed_root_identity:-none}" = "none" || \
      test ! -d "${framework_root}" || \
      test -L "${framework_root}" || \
      test "$(/usr/bin/stat -f '%u' "${framework_root}")" != "0" || \
      test "$(/usr/bin/stat -f '%d:%i' "${framework_root}")" != \
        "${seal_installed_root_identity}"; then
      rollback_ready=0
      cleanup_status=70
    fi
    if test "${seal_quarantine_state:-unvalidated}" = "active"; then
      if test "${seal_quarantine%/*}" != "${framework_parent}" || \
        test ! -d "${seal_quarantine}" || \
        test -L "${seal_quarantine}" || \
        test "$(/usr/bin/stat -f '%u' "${seal_quarantine}")" != "0" || \
        test "$(/usr/bin/stat -f '%d:%i' "${seal_quarantine}")" != \
          "${seal_quarantine_identity}"; then
        rollback_ready=0
        if test "${cleanup_status}" -eq 0; then
          cleanup_status=70
        fi
      fi
    elif test "${seal_quarantine_state:-unvalidated}" != "none"; then
      rollback_ready=0
      if test "${cleanup_status}" -eq 0; then
        cleanup_status=70
      fi
    fi
    if test "${rollback_ready}" -eq 1; then
      /usr/bin/sudo --non-interactive /usr/bin/find -P -x \
        "${framework_root}" -depth -delete || {
          candidate_status="$?"
          if test "${cleanup_status}" -eq 0; then
            cleanup_status="${candidate_status}"
          fi
        }
      if test -e "${framework_root}" || test -L "${framework_root}"; then
        if test "${cleanup_status}" -eq 0; then
          cleanup_status=70
        fi
      elif test "${seal_quarantine_state}" = "active"; then
        /usr/bin/sudo --non-interactive /bin/mv \
          "${seal_quarantine}" "${framework_root}" || {
            candidate_status="$?"
            if test "${cleanup_status}" -eq 0; then
              cleanup_status="${candidate_status}"
            fi
          }
        if test ! -d "${framework_root}" || \
          test -L "${framework_root}" || \
          test "$(/usr/bin/stat -f '%d:%i' "${framework_root}")" != \
            "${seal_quarantine_identity}" || \
          test -e "${seal_quarantine}" || \
          test -L "${seal_quarantine}"; then
          if test "${cleanup_status}" -eq 0; then
            cleanup_status=70
          fi
        fi
      fi
    fi
  elif test "${seal_transaction_phase:-unvalidated}" = "committed"; then
    if test "${seal_quarantine_state:-unvalidated}" = "active"; then
      if test "${seal_quarantine%/*}" = "${framework_parent}" && \
        test -d "${seal_quarantine}" && \
        test ! -L "${seal_quarantine}" && \
        test "$(/usr/bin/stat -f '%u' "${seal_quarantine}")" = "0" && \
        test "$(/usr/bin/stat -f '%d:%i' "${seal_quarantine}")" = \
          "${seal_quarantine_identity}"; then
        /usr/bin/sudo --non-interactive /usr/bin/find -P -x \
          "${seal_quarantine}" -depth -delete || {
            candidate_status="$?"
            if test "${cleanup_status}" -eq 0; then
              cleanup_status="${candidate_status}"
            fi
          }
        if test -e "${seal_quarantine}" || \
          test -L "${seal_quarantine}"; then
          if test "${cleanup_status}" -eq 0; then
            cleanup_status=70
          fi
        fi
      else
        cleanup_status=70
      fi
    elif test "${seal_quarantine_state:-unvalidated}" != "none"; then
      cleanup_status=70
    fi
  elif test "${seal_transaction_phase:-unvalidated}" != "complete"; then
    cleanup_status=70
  fi
  if test "${cleanup_status}" -ne 0; then
    printf 'lcf-framework-transaction-cleanup: phase=%s status=%s\n' \
      "${seal_transaction_phase:-unvalidated}" "${cleanup_status}" >&2
  fi
  if test "${saved_status}" -ne 0; then
    exit "${saved_status}"
  fi
  exit "${cleanup_status}"
}'''
EXPECTED_FRAMEWORK_SEAL_QUARANTINE_BINDING = r'''test -n "${LCF_REVIEWED_FRAMEWORK_QUARANTINE:-}"
test -n "${LCF_REVIEWED_FRAMEWORK_QUARANTINE_IDENTITY:-}"
if test "${LCF_REVIEWED_FRAMEWORK_QUARANTINE}" = "none"; then
  test "${LCF_REVIEWED_FRAMEWORK_QUARANTINE_IDENTITY}" = "none"
  seal_quarantine_state="none"
else
  readonly quarantine_prefix="${framework_parent}/.lcf-python-quarantine."
  quarantine_suffix="${LCF_REVIEWED_FRAMEWORK_QUARANTINE#"${quarantine_prefix}"}"
  readonly quarantine_suffix
  test "${LCF_REVIEWED_FRAMEWORK_QUARANTINE%/*}" = \
    "${framework_parent}"
  test "${LCF_REVIEWED_FRAMEWORK_QUARANTINE}" = \
    "${quarantine_prefix}${quarantine_suffix}"
  [[ "${quarantine_suffix}" =~ ^[A-Za-z0-9]{10}$ ]]
  [[ "${LCF_REVIEWED_FRAMEWORK_QUARANTINE_IDENTITY}" =~ \
    ^[0-9]+:[0-9]+$ ]]
  test -d "${LCF_REVIEWED_FRAMEWORK_QUARANTINE}"
  test ! -L "${LCF_REVIEWED_FRAMEWORK_QUARANTINE}"
  test "$(/usr/bin/stat -f '%u' \
    "${LCF_REVIEWED_FRAMEWORK_QUARANTINE}")" = "0"
  test "$(/usr/bin/stat -f '%d:%i' \
    "${LCF_REVIEWED_FRAMEWORK_QUARANTINE}")" = \
    "${LCF_REVIEWED_FRAMEWORK_QUARANTINE_IDENTITY}"
  seal_quarantine="${LCF_REVIEWED_FRAMEWORK_QUARANTINE}"
  seal_quarantine_identity="${LCF_REVIEWED_FRAMEWORK_QUARANTINE_IDENTITY}"
  seal_quarantine_state="active"
fi'''
EXPECTED_FRAMEWORK_SEAL_ROOT_BINDING = r'''test -d "${framework_root}"
test ! -L "${framework_root}"
test "$(cd "${framework_root}" && /bin/pwd -P)" = "${framework_root}"
readonly library_identity="$(/usr/bin/stat -f '%d:%i' "${library_root}")"
readonly container_identity="$(/usr/bin/stat -f '%d:%i' "${framework_container}")"
readonly anchor_identity="$(/usr/bin/stat -f '%d:%i' "${framework_anchor}")"
readonly parent_identity="$(/usr/bin/stat -f '%d:%i' "${framework_parent}")"
readonly root_identity="$(/usr/bin/stat -f '%d:%i' "${framework_root}")"
[[ "${root_identity}" =~ ^[0-9]+:[0-9]+$ ]]
test "$(/usr/bin/stat -f '%u' "${framework_root}")" = "0"
seal_installed_root_identity="${root_identity}"'''
EXPECTED_FRAMEWORK_SEAL_TRANSACTION_COMMIT = r'''seal_transaction_phase="committed"
if test "${seal_quarantine_state}" = "active"; then
  test "$(/usr/bin/stat -f '%d:%i' "${seal_quarantine}")" = \
    "${seal_quarantine_identity}"
  /usr/bin/sudo --non-interactive /usr/bin/find -P -x \
    "${seal_quarantine}" -depth -delete
  test ! -e "${seal_quarantine}"
  test ! -L "${seal_quarantine}"
  seal_quarantine_state="none"
  seal_quarantine="none"
  seal_quarantine_identity="none"
fi
seal_transaction_phase="complete"
trap - EXIT'''
EXPECTED_FRAMEWORK_SEAL_RUN_SHA256 = (
    "536e2ae21b659258032d1a8c9c0675f0ca4eaf6b7199c137158d4ced9c091de9"
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
EXPECTED_LIFECYCLE_TEST_RUN_SHA256 = (
    "b34dd22c51da9281dc85c2e6fadbf0810582a7c4bb5965643c57d9c306423beb"
)
EXPECTED_POLICY_RUN = '''set -euo pipefail
cd "${LCF_REVIEWED_SOURCE_ROOT}"
make packaged-smoke-policy-check \\
  PYTHON="${LCF_REVIEWED_BUILD_PYTHON}" \\
  NODE="${LCF_REVIEWED_FRAMEWORK_VERIFIER_NODE}"'''
EXPECTED_PYTHON_BUILD_RUN = (
    'cd "${LCF_REVIEWED_SOURCE_ROOT}" && make python-sidecar-build'
)
EXPECTED_POST_BUILD_CLEANUP_RUN = r'''set -euo pipefail
cleanup_assertion="runner-temp-present"
trap 'cleanup_status=$?; printf "lcf-scratch-cleanup: assertion=%s\n" "${cleanup_assertion}" >&2; exit "${cleanup_status}"' ERR
test -n "${RUNNER_TEMP:-}"
cleanup_assertion="runner-temp-absolute"
[[ "${RUNNER_TEMP}" = /* ]]
cleanup_assertion="runner-temp-directory"
test -d "${RUNNER_TEMP}"
cleanup_assertion="runner-temp-not-symlink"
test ! -L "${RUNNER_TEMP}"
cleanup_assertion="runner-temp-canonical"
runner_temp_real="$(cd "${RUNNER_TEMP}" && /bin/pwd -P)"
test "${runner_temp_real}" = "${RUNNER_TEMP}"
cleanup_assertion="runner-temp-owner"
test "$(/usr/bin/stat -f '%u' "${RUNNER_TEMP}")" = "$(/usr/bin/id -u)"
cleanup_assertion="runner-temp-mode"
runner_temp_mode="$(/usr/bin/stat -f '%Lp' "${RUNNER_TEMP}")"
(( (8#${runner_temp_mode} & 0022) == 0 ))
shopt -s nullglob
cleanup_assertion="runner-toolchain-residue"
runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)
test "${#runner_toolchain_residue[@]}" -eq 0
cleanup_assertion="runner-producer-residue"
runner_producer_residue=("${RUNNER_TEMP}"/lcf-python-producer.*)
test "${#runner_producer_residue[@]}" -eq 0
cleanup_assertion="runner-distribution-binding-residue"
runner_distribution_binding_residue=(
  "${RUNNER_TEMP}"/lcf-python-installer.*
)
test "${#runner_distribution_binding_residue[@]}" -eq 0
cleanup_assertion="runner-source-residue"
runner_source_residue=("${RUNNER_TEMP}"/lcf-reviewed-source.*)
if test -z "${LCF_REVIEWED_SOURCE_ROOT:-}"; then
  test "${#runner_source_residue[@]}" -eq 0
else
  cleanup_assertion="source-root-prefix"
  readonly source_prefix="${RUNNER_TEMP}/lcf-reviewed-source."
  source_suffix="${LCF_REVIEWED_SOURCE_ROOT#"${source_prefix}"}"
  readonly source_suffix
  test "${LCF_REVIEWED_SOURCE_ROOT}" = "${source_prefix}${source_suffix}"
  [[ "${source_suffix}" =~ ^[A-Za-z0-9]{10}$ ]]
  cleanup_assertion="source-root-directory"
  test -d "${LCF_REVIEWED_SOURCE_ROOT}"
  cleanup_assertion="source-root-not-symlink"
  test ! -L "${LCF_REVIEWED_SOURCE_ROOT}"
  cleanup_assertion="source-root-canonical"
  source_root_real="$(cd "${LCF_REVIEWED_SOURCE_ROOT}" && /bin/pwd -P)"
  test "${source_root_real}" = "${LCF_REVIEWED_SOURCE_ROOT}"
  cleanup_assertion="source-root-owner"
  test "$(/usr/bin/stat -f '%u' "${LCF_REVIEWED_SOURCE_ROOT}")" = \
    "$(/usr/bin/id -u)"
  cleanup_assertion="source-root-mode"
  test "$(/usr/bin/stat -f '%Lp' "${LCF_REVIEWED_SOURCE_ROOT}")" = \
    "700"
  readonly provenance_env="${RUNNER_TEMP}/lcf-reviewed-source-provenance.env"
  cleanup_assertion="source-provenance-file"
  test -f "${provenance_env}"
  cleanup_assertion="source-provenance-not-symlink"
  test ! -L "${provenance_env}"
  cleanup_assertion="source-provenance-owner"
  test "$(/usr/bin/stat -f '%u' "${provenance_env}")" = \
    "$(/usr/bin/id -u)"
  cleanup_assertion="runner-source-residue-closure"
  test "${#runner_source_residue[@]}" -eq 2
  for source_residue in "${runner_source_residue[@]}"; do
    case "${source_residue}" in
      "${LCF_REVIEWED_SOURCE_ROOT}"|"${provenance_env}") ;;
      *) false ;;
    esac
  done
  cleanup_assertion="source-root-enter"
  cd "${LCF_REVIEWED_SOURCE_ROOT}"
  cleanup_assertion="repo-fixed-directory-residue"
  test ! -e desktop/generated/python-sidecar-build
  cleanup_assertion="repo-fixed-symlink-residue"
  test ! -L desktop/generated/python-sidecar-build
  cleanup_assertion="repo-random-directory-residue"
  repo_random_residue=(desktop/generated/python-sidecar-build-*)
  test "${#repo_random_residue[@]}" -eq 0
fi
trap - ERR'''
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
test "$("${LCF_REVIEWED_BUILD_PYTHON}" -I -S -c \
  'import os,sys; print(os.path.realpath(sys.executable))')" = \
  "${LCF_REVIEWED_BUILD_PYTHON}"
test "$("${LCF_REVIEWED_BUILD_PYTHON}" -I -S -c \
  'import platform; print(platform.python_version())')" = "3.13.14"'''
EXPECTED_FORMAL_JOB_ENV = (
    '      CI: "true"\n'
    '      LCF_FORMAL_RELEASE: "true"\n'
    "      LCF_SOURCE_SHA: ${{ github.sha }}\n"
)
EXPECTED_FORMAL_PROVENANCE_EXPORT = r'''"${bootstrap_python}" -I -S tools/check_exact_git_provenance.py \
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
ACTION_ALLOWLIST = {
    ("actions/checkout", CHECKOUT_SHA),
    ("actions/setup-node", SETUP_NODE_SHA),
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
PYTHON_ARCHIVE_NAME = "python-3.13.14-darwin-arm64.tar.gz"
PYTHON_HASH_MANIFEST_ENTRY = (
    "839B14DF8A24415E17D15F222E2AC01D3A90845DEB39DF642E2CC01869140A34 "
    f"{PYTHON_ARCHIVE_NAME}"
)
EXPECTED_PYTHON_HASH_MANIFEST_BINDING = (
    'test "$(/usr/bin/grep -Fxc \\\n'
    f"  '{PYTHON_HASH_MANIFEST_ENTRY}' \\\n"
    '  "${hashes}")" = "1"'
)
PYTHON_INSTALL_ROOT = "/Library/Frameworks/Python.framework/Versions/3.13"
PYTHON_INTERPRETER_RELATIVE_PATH = "bin/python3.13"
PYTHON_INTERPRETER_SIZE = 119232
PYTHON_INTERPRETER_SHA256 = (
    "ee3c4103b97e32a98e98cfad7f6ca4d09b2ab2dc16f3d28e18b54a4a0244efe0"
)
PYTHON_FRAMEWORK_BINARY_RELATIVE_PATH = "Python"
PYTHON_FRAMEWORK_BINARY_SIZE = 13633312
PYTHON_FRAMEWORK_BINARY_SHA256 = (
    "db77544e7135af8478d62c7d1289581d83714a676c7d3f2b7a4b996bdfef5717"
)
PYTHON_FRAMEWORK_CORE_EXCLUDED_PATHS = (
    "Resources/English.lproj/Documentation",
    "bin/pip",
    "bin/pip3",
    "bin/pip3.13",
    "bin/python",
    "bin/python313",
    "etc/openssl/cert.pem",
    "lib/python3.13/site-packages",
    "share/doc/python3.13/html",
)
PYTHON_FRAMEWORK_CORE_FINGERPRINT_SHA256 = (
    "ba58cfb559f29c34beb962cb5d88587e9104f5610c255a58494c2945c1e863ec"
)
PYTHON_REVIEWED_BROKEN_SYMLINKS = (
    {
        "path": "Frameworks/Tcl.framework/PrivateHeaders",
        "target": "Versions/Current/PrivateHeaders",
    },
    {
        "path": "Frameworks/Tk.framework/PrivateHeaders",
        "target": "Versions/Current/PrivateHeaders",
    },
)
PYTHON_DISTRIBUTION_INSTALL_METHOD = (
    "macos-installer-no-op-framework-component"
)
PYTHON_FRAMEWORK_COMPONENT_CONTRACT = {
    "packageName": "Python_Framework.pkg",
    "bomSize": 1404518,
    "bomSha256": "4e49a4c96076a4855219461f721d510493c6d4f3a7a2a9ad7c981ced723d09bd",
    "packageInfoSize": 947,
    "packageInfoSha256": (
        "86938c44112e37c4791fdc15ee0d89777ed8b6d0a85bae37f7ebf09839072f5c"
    ),
    "payloadSize": 32739568,
    "payloadSha256": (
        "f922c9d7c78f3745dc453211677fbce2e4b415616556b11376a92ca7a17fc391"
    ),
    "scriptsSize": 380,
    "scriptsSha256": (
        "84fb517c2da6089848bfb6a0ab0e6c508351546d1df9d31abcadd5de4cd42bac"
    ),
    "postinstallSize": 894,
    "postinstallSha256": (
        "7821586a42b4d86b075ed2c87da0a5981e5372070b9c7f6141d09f77cb172417"
    ),
    "postinstallMode": "0755",
    "noOpPostinstallSize": 17,
    "noOpPostinstallSha256": (
        "306c6ca7407560340797866e077e053627ad409277d1b9da58106fce4cf717cb"
    ),
    "noOpPostinstallMode": "0755",
}
PYTHON_RUNNER_INPUTS = (
    "LCF_PYTHON_DISTRIBUTION_ARCHIVE",
    "LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST",
    "LCF_PYTHON_INSTALL_ROOT",
)
EXPECTED_POLICY_TARGET = (
    (),
    (
        "$(NODE) --test tools/tests/verify_reviewed_python_framework.test.cjs",
        "$(PYTHON) -S -B tools/check_packaged_smoke_policy.py",
        "$(PYTHON) -S -B -m unittest tools.tests.test_check_packaged_smoke_policy",
        "$(PYTHON) -S -B -m unittest tools.tests.test_check_exact_git_provenance",
    ),
)
EXPECTED_PYTHON_SOURCE_VERIFY_TARGET = (
    (),
    (
        '@test -n "$(LCF_REVIEWED_SOURCE_ROOT)" || { printf \'%s\\n\' '
        "'LCF_REVIEWED_SOURCE_ROOT is required'; exit 2; }",
        '@test -n "$(LCF_REVIEWED_BUILD_PYTHON)" || { printf \'%s\\n\' '
        "'LCF_REVIEWED_BUILD_PYTHON is required'; exit 2; }",
        '@test "$(LCF_REVIEWED_BUILD_PYTHON)" = '
        '"$(PYTHON_SIDECAR_FRAMEWORK_PYTHON)" || { printf \'%s\\n\' '
        "'Reviewed build Python differs from the locked framework'; exit 2; }",
        '@test -n "$(PYTHON_SIDECAR_ARCHIVE)" || { printf \'%s\\n\' '
        "'PYTHON_SIDECAR_ARCHIVE is required'; exit 2; }",
        '@test -n "$(PYTHON_SIDECAR_HASH_MANIFEST)" || { printf \'%s\\n\' '
        "'PYTHON_SIDECAR_HASH_MANIFEST is required'; exit 2; }",
        '"$(LCF_REVIEWED_BUILD_PYTHON)" -I -S '
        '"$(LCF_REVIEWED_SOURCE_ROOT)/tools/build_python_sidecar.py" '
        '--verify-source-only --archive "$(PYTHON_SIDECAR_ARCHIVE)" '
        '--hash-manifest "$(PYTHON_SIDECAR_HASH_MANIFEST)"',
    ),
)
EXPECTED_PYTHON_INSTALL_TARGET = (
    ("python-sidecar-source-verify",),
    (
        '"$(LCF_REVIEWED_BUILD_PYTHON)" -I -S '
        '"$(LCF_REVIEWED_SOURCE_ROOT)/tools/bootstrap_python_sidecar.py" '
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
        '"$(LCF_REVIEWED_BUILD_PYTHON)" -I -S '
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
        '"$(LCF_REVIEWED_BUILD_PYTHON)" -I -S '
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
    '"$LCF_REVIEWED_BUILD_PYTHON" -I -S '
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
    ("framework verifier Node", "6af8ddd6ea4c0c6de9bf63ec4a69b3365f6aa417d2b332748f80d192bd9897b5"),
    ("framework producer", "4f4e4303542f05c0f6e31c8b9566b16983a29878c5d657672730137caa3c86c1"),
    ("framework seal", "85a1253ea653f4ec6a3ada67f5f1c2c0c4dfc92d62c89d07602241fc5fd4dff9"),
    ("exact provenance", "9ea36480b4f4ff8d721fcd2c64cc1a2173a94c8185c3ee6a5e69a8fcf51b596f"),
    ("policy", "285e761f042ad2c44db94e38730f1d19c30c1db0851dc81539083cb6df5fc32b"),
    ("Python sources", "f01e0ddbe2fd917eb765723935eaceb7a606db3350a9ee059402032ff89789a7"),
    ("Python sidecar", "af4ac525fb69726e592d6b743fd4951b5c61b3ad611d4be1f9099aac362c1579"),
    ("Python cleanup", "cb5e6987f14d5bc6e7ea7d180b9967952677a0be9a1a25f9b874e31e1b192a4b"),
    ("Python provenance", "54db56d05ec592311d5245a8f6d0f4679838249bed827133567d1e9bfa920b40"),
    ("renderer", "2db53fd812c47c613361413200bfadec046be100dbb598a19c665d293bb6c024"),
    ("Desktop", "00cfc4213532da6e78034d720cb79f76a9e232c5f7dfa7f9262314f4e79478e2"),
    ("assembly audit", "4789375f1a2cd2cd87d579b69a5ac9883077f6aba79faf75c3cc9db27e4bee61"),
    ("focused lifecycle tests", "b34dd22c51da9281dc85c2e6fadbf0810582a7c4bb5965643c57d9c306423beb"),
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


def _python_exec_runner_signal_contract_is_semantic(source: str) -> bool:
    """Require every reviewed Python exec runner to reset and unblock signals."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    runners: dict[str, str] = {}
    expected_names = {
        "HELD_CWD_EXEC_RUNNER",
        "PATH_CAPABILITY_EXEC_RUNNER",
    }
    for statement in tree.body:
        if (
            not isinstance(statement, ast.Assign)
            or len(statement.targets) != 1
            or not isinstance(statement.targets[0], ast.Name)
            or statement.targets[0].id not in expected_names
        ):
            continue
        value = statement.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == "strip"
            and not value.args
            and not value.keywords
        ):
            value = value.func.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            return False
        runners[statement.targets[0].id] = value.value
    if set(runners) != expected_names:
        return False
    required_markers = (
        "signal.pthread_sigmask(",
        "signal.SIGINT",
        "signal.SIGTERM",
        'getattr(signal, "SIGHUP", signal.SIGTERM)',
        'getattr(signal, "SIGPIPE", signal.SIGTERM)',
        'getattr(signal, "SIGXFZ", signal.SIGTERM)',
        'getattr(signal, "SIGXFSZ", signal.SIGTERM)',
        "signal.signal(number, signal.SIG_DFL)",
        'fail("signal-reset")',
        "os.execve(",
    )
    for runner in runners.values():
        try:
            ast.parse(runner)
        except SyntaxError:
            return False
        if runner.count("signal.SIG_UNBLOCK") != 1:
            return False
        if any(marker not in runner for marker in required_markers):
            return False
    return True


def _python_installer_launcher_transition_is_semantic(source: str) -> bool:
    """Bind launcher-name replacement to the one reviewed installer producer."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    held = _python_function(tree, "_held_executable")
    revalidate = _python_function(tree, "_revalidate_held_executable")
    owned = _python_function(tree, "_run_owned_process")
    reviewed_installer = _python_function(
        tree,
        "_run_reviewed_framework_installer",
    )
    install = _python_function(tree, "install_reviewed_python")
    if any(
        item is None
        for item in (held, revalidate, owned, reviewed_installer, install)
    ):
        return False
    assert held is not None
    assert revalidate is not None
    assert owned is not None
    assert reviewed_installer is not None
    assert install is not None

    def exact_expression(node: ast.AST, expression: str) -> bool:
        expected = ast.parse(expression, mode="eval").body
        return ast.dump(node, include_attributes=False) == ast.dump(
            expected,
            include_attributes=False,
        )

    def direct_toolchain_raise(statement: ast.stmt) -> bool:
        return (
            isinstance(statement, ast.Raise)
            and isinstance(statement.exc, ast.Call)
            and _python_attribute_path(statement.exc.func)
            == ("ToolchainBootstrapError",)
        )

    if (
        source.count(
            'LAUNCHER_NAME_INSTALLER_REBIND = "installer-producer-rebind"'
        )
        != 1
        or source.count(
            'LAUNCHER_NAME_INSTALLER_PENDING_SEAL = '
            '"installer-produced-pending-seal"'
        )
        != 1
        or source.count("with _held_executable(") != 2
        or source.count(
            "launcher_name_policy=LAUNCHER_NAME_INSTALLER_PENDING_SEAL"
        )
        != 1
        or source.count(
            "launcher_rebind_authority="
            "_REVIEWED_INSTALLER_REBIND_AUTHORITY"
        )
        != 1
        or source.count("launcher_binding=") != 4
        or source.count("0o7002") != 1
        or not _python_exact_single_assignment(
            install,
            "active_launcher",
            "Path(sys.executable).resolve(strict=True)",
        )
        or not _python_exact_single_assignment(
            install,
            "installer_path_capabilities",
            "((capability.descriptor, str(capability.path), False), "
            "(cache_fd, str(cache_root), False), "
            "(package.descriptor, str(package_path), False))",
        )
        or not _python_exact_single_assignment(
            owned,
            "terminal_launcher_policy",
            "launcher_name_policy if "
            "(launcher_name_policy in "
            "{LAUNCHER_NAME_INSTALLER_REBIND, "
            "LAUNCHER_NAME_INSTALLER_PENDING_SEAL} "
            "and process.returncode == 0 and check) else LAUNCHER_NAME_SAME",
        )
        or not _python_exact_single_assignment(
            reviewed_installer,
            "package_capabilities",
            "tuple((descriptor, str(path), mutable) "
            "for descriptor, path, mutable in path_capabilities "
            "if descriptor == package.descriptor)",
        )
    ):
        return False

    owned_top_level_tries = [
        statement for statement in owned.body if isinstance(statement, ast.Try)
    ]
    if (
        len(owned_top_level_tries) != 1
        or owned.body[-1] is not owned_top_level_tries[0]
        or len(owned_top_level_tries[0].handlers) != 1
    ):
        return False
    owned_try = owned_top_level_tries[0]
    owned_handler = owned_try.handlers[0]
    if (
        _python_attribute_path(owned_handler.type) != ("BaseException",)
        or owned_handler.name != "exc"
        or tuple(type(statement) for statement in owned_handler.body)
        != (
            ast.AnnAssign,
            ast.If,
            ast.AnnAssign,
            ast.If,
            ast.If,
            ast.If,
            ast.If,
            ast.Raise,
        )
    ):
        return False
    exception_binding_if = owned_handler.body[3]
    if (
        not isinstance(exception_binding_if, ast.If)
        or not exact_expression(
            exception_binding_if.test,
            "process is not None",
        )
        or len(exception_binding_if.body) != 1
        or exception_binding_if.orelse
        or not isinstance(exception_binding_if.body[0], ast.Try)
    ):
        return False
    exception_binding_try = exception_binding_if.body[0]
    exception_binding_call = (
        exception_binding_try.body[0].value
        if len(exception_binding_try.body) == 1
        and isinstance(exception_binding_try.body[0], ast.Expr)
        and isinstance(exception_binding_try.body[0].value, ast.Call)
        else None
    )
    if (
        exception_binding_call is None
        or _python_attribute_path(exception_binding_call.func)
        != ("revalidate_owned_bindings",)
        or exception_binding_call.args
        or len(exception_binding_call.keywords) != 1
        or exception_binding_call.keywords[0].arg != "name_policy"
        or _python_attribute_path(exception_binding_call.keywords[0].value)
        != ("LAUNCHER_NAME_SAME",)
        or exception_binding_try.orelse
        or exception_binding_try.finalbody
        or len(exception_binding_try.handlers) != 1
    ):
        return False
    exception_binding_handler = exception_binding_try.handlers[0]
    expected_binding_assignment = ast.parse(
        "binding_error = observed_error"
    ).body[0]
    if (
        _python_attribute_path(exception_binding_handler.type)
        != ("BaseException",)
        or exception_binding_handler.name != "observed_error"
        or len(exception_binding_handler.body) != 1
        or ast.dump(
            exception_binding_handler.body[0],
            include_attributes=False,
        )
        != ast.dump(expected_binding_assignment, include_attributes=False)
    ):
        return False
    exception_revalidations = [
        node
        for node in ast.walk(owned_handler)
        if isinstance(node, ast.Call)
        and _python_attribute_path(node.func)
        == ("revalidate_owned_bindings",)
    ]
    if exception_revalidations != [exception_binding_call]:
        return False

    authority_guards = [
        node
        for node in ast.walk(owned)
        if isinstance(node, ast.If)
        and exact_expression(
            node.test,
            "(launcher_name_policy in "
            "{LAUNCHER_NAME_INSTALLER_REBIND, "
            "LAUNCHER_NAME_INSTALLER_PENDING_SEAL} "
            "and launcher_rebind_authority is not "
            "_REVIEWED_INSTALLER_REBIND_AUTHORITY) or "
            "(launcher_name_policy == LAUNCHER_NAME_SAME "
            "and launcher_rebind_authority is not None)",
        )
    ]
    if (
        len(authority_guards) != 1
        or len(authority_guards[0].body) != 1
        or not direct_toolchain_raise(authority_guards[0].body[0])
        or authority_guards[0].orelse
    ):
        return False

    held_body_types = (
        ast.Expr,
        ast.AnnAssign,
        ast.AnnAssign,
        ast.AnnAssign,
        ast.Try,
        ast.AnnAssign,
        ast.If,
        ast.AnnAssign,
        ast.If,
        ast.If,
        ast.If,
        ast.If,
    )
    if (
        tuple(type(statement) for statement in held.body) != held_body_types
        or len(held.decorator_list) != 1
        or _python_attribute_path(held.decorator_list[0])
        != ("contextlib", "contextmanager")
    ):
        return False
    terminal_if = held.body[6]
    assert isinstance(terminal_if, ast.If)
    if (
        not exact_expression(terminal_if.test, "binding is not None")
        or len(terminal_if.body) != 1
        or terminal_if.orelse
        or not isinstance(terminal_if.body[0], ast.Try)
    ):
        return False
    terminal_try = terminal_if.body[0]
    assert isinstance(terminal_try, ast.Try)
    terminal_call = (
        terminal_try.body[0].value
        if len(terminal_try.body) == 1
        and isinstance(terminal_try.body[0], ast.Expr)
        and isinstance(terminal_try.body[0].value, ast.Call)
        else None
    )
    if (
        terminal_call is None
        or _python_attribute_path(terminal_call.func)
        != ("_revalidate_held_executable",)
        or len(terminal_call.args) != 1
        or _python_attribute_path(terminal_call.args[0]) != ("binding",)
        or {
            keyword.arg: _python_attribute_path(keyword.value)
            for keyword in terminal_call.keywords
            if keyword.arg is not None
        }
        != {
            "name_policy": ("terminal_name_policy",),
            "error_message": ("error_message",),
        }
        or terminal_try.orelse
        or terminal_try.finalbody
        or len(terminal_try.handlers) != 1
    ):
        return False

    if (
        tuple(type(statement) for statement in revalidate.body)
        != (ast.Expr, ast.Try)
        or not isinstance(revalidate.body[1], ast.Try)
    ):
        return False
    revalidate_try = revalidate.body[1]
    assert isinstance(revalidate_try, ast.Try)
    if tuple(type(statement) for statement in revalidate_try.body) != (
        ast.Assign,
        ast.Assign,
        ast.Assign,
        ast.If,
        ast.Assign,
        ast.If,
    ):
        return False
    policy_if = revalidate_try.body[3]
    hash_if = revalidate_try.body[5]
    assert isinstance(policy_if, ast.If)
    assert isinstance(hash_if, ast.If)
    if (
        not exact_expression(
            policy_if.test,
            "name_policy == LAUNCHER_NAME_SAME",
        )
        or len(policy_if.body) != 1
        or not isinstance(policy_if.body[0], ast.If)
        or not exact_expression(
            policy_if.body[0].test,
            "held_identity != binding.identity "
            "or _identity(named) != binding.identity",
        )
        or len(policy_if.orelse) != 1
        or not isinstance(policy_if.orelse[0], ast.If)
    ):
        return False
    rebind_if = policy_if.orelse[0]
    assert isinstance(rebind_if, ast.If)
    if (
        not exact_expression(
            rebind_if.test,
            "name_policy in {LAUNCHER_NAME_INSTALLER_REBIND, "
            "LAUNCHER_NAME_INSTALLER_PENDING_SEAL}",
        )
        or tuple(type(statement) for statement in rebind_if.body)
        != (ast.Assign, ast.If)
        or len(rebind_if.orelse) != 1
        or not direct_toolchain_raise(rebind_if.orelse[0])
    ):
        return False
    named_if = rebind_if.body[1]
    assert isinstance(named_if, ast.If)
    if (
        not exact_expression(
            named_if.test,
            "_identity(named) == binding.identity",
        )
        or len(named_if.body) != 1
        or not isinstance(named_if.body[0], ast.If)
        or not exact_expression(
            named_if.body[0].test,
            "held_identity != binding.identity",
        )
        or len(named_if.orelse) != 2
        or not isinstance(named_if.orelse[0], ast.Assign)
        or not isinstance(named_if.orelse[1], ast.If)
        or not _python_exact_single_assignment(
            revalidate,
            "unsafe_mode_mask",
            "0o7022 if name_policy == LAUNCHER_NAME_INSTALLER_REBIND "
            "else 0o7002",
        )
        or not exact_expression(
            named_if.orelse[1].test,
            "tuple(held_identity[index] for index in stable_indexes) != "
            "tuple(binding.identity[index] for index in stable_indexes) "
            "or held.st_nlink != 0 "
            "or not stat.S_ISREG(named.st_mode) "
            "or stat.S_ISLNK(named.st_mode) "
            "or (named.st_uid != _reviewed_framework_owner() "
            "if name_policy == LAUNCHER_NAME_INSTALLER_PENDING_SEAL "
            "else named.st_uid not in {0, os.geteuid()}) "
            "or named.st_nlink != 1 "
            "or stat.S_IMODE(named.st_mode) & unsafe_mode_mask "
            "or not stat.S_IMODE(named.st_mode) & 0o111",
        )
        or len(named_if.orelse[1].body) != 1
        or not direct_toolchain_raise(named_if.orelse[1].body[0])
        or not exact_expression(
            hash_if.test,
            "hashlib.sha256(payload).hexdigest() != binding.sha256",
        )
        or len(hash_if.body) != 1
        or not direct_toolchain_raise(hash_if.body[0])
    ):
        return False

    held_source = ast.get_source_segment(source, held) or ""
    revalidate_source = ast.get_source_segment(source, revalidate) or ""
    owned_source = ast.get_source_segment(source, owned) or ""
    for marker in (
        "os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC",
        "_identity(held) != _identity(named)",
        "held.st_uid not in {0, os.geteuid()}",
        "held.st_nlink != 1",
        "stat.S_IMODE(held.st_mode) & 0o7022",
        "hashlib.sha256(payload).hexdigest()",
        "terminal_name_policy: str = LAUNCHER_NAME_SAME",
        "name_policy=terminal_name_policy",
        "and its terminal capability could not be verified",
    ):
        if marker not in held_source:
            return False
    for marker in (
        "stable_indexes = (0, 1, 2, 3, 4, 6, 7)",
        "if _identity(named) == binding.identity:",
        "held.st_nlink != 0",
        "named.st_uid != _reviewed_framework_owner()",
        "name_policy == LAUNCHER_NAME_INSTALLER_PENDING_SEAL",
        "else named.st_uid not in {0, os.geteuid()}",
        "named.st_nlink != 1",
        "0o7022",
        "else 0o7002",
        "stat.S_IMODE(named.st_mode) & unsafe_mode_mask",
        "hashlib.sha256(payload).hexdigest() != binding.sha256",
    ):
        if marker not in revalidate_source:
            return False
    for marker in (
        "launcher_name_policy: str = LAUNCHER_NAME_SAME",
        "launcher_rebind_authority: object | None = None",
        "is not _REVIEWED_INSTALLER_REBIND_AUTHORITY",
        "LAUNCHER_NAME_INSTALLER_PENDING_SEAL",
        "Path(str(arguments[4])) if len(arguments) == 7 else Path()",
        "Path(str(raw_path)) == package_argument and mutable is False",
        'label != "Python framework installation"',
        'tuple(arguments[5:]) != ("-target", "/")',
        "or not package_capability",
        "revalidate_owned_bindings(name_policy=terminal_launcher_policy)",
        "revalidate_owned_bindings(name_policy=LAUNCHER_NAME_SAME)",
    ):
        if marker not in owned_source:
            return False

    active_checks = [
        node
        for node in ast.walk(install)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "active_launcher"
        and len(node.test.ops) == 1
        and isinstance(node.test.ops[0], ast.NotEq)
        and len(node.test.comparators) == 1
        and isinstance(node.test.comparators[0], ast.Name)
        and node.test.comparators[0].id == "interpreter"
    ]
    if (
        len(active_checks) != 1
        or len(active_checks[0].body) != 1
        or not direct_toolchain_raise(active_checks[0].body[0])
        or active_checks[0].orelse
    ):
        return False

    def held_context(
        node: ast.AST,
        argument: str,
        binding: str,
    ) -> bool:
        if not isinstance(node, ast.With) or len(node.items) != 1:
            return False
        item = node.items[0]
        return (
            isinstance(item.context_expr, ast.Call)
            and _python_attribute_path(item.context_expr.func)
            == ("_held_executable",)
            and len(item.context_expr.args) == 1
            and isinstance(item.context_expr.args[0], ast.Name)
            and item.context_expr.args[0].id == argument
            and isinstance(item.optional_vars, ast.Name)
            and item.optional_vars.id == binding
        )

    old_contexts = [
        node
        for node in ast.walk(install)
        if held_context(node, "active_launcher", "old_launcher")
    ]
    if len(old_contexts) != 1:
        return False
    old_context = old_contexts[0]
    parents = {
        child: parent
        for parent in ast.walk(install)
        for child in ast.iter_child_nodes(parent)
    }
    active_check = active_checks[0]
    active_parent = parents.get(active_check)
    if (
        active_parent is None
        or active_parent is not parents.get(old_context)
        or not hasattr(active_parent, "body")
        or active_check not in active_parent.body
        or old_context not in active_parent.body
        or active_parent.body.index(active_check)
        >= active_parent.body.index(old_context)
        or _python_has_constant_false_ancestor(active_check, parents)
        or _python_has_constant_false_ancestor(old_context, parents)
    ):
        return False
    old_held_call = old_context.items[0].context_expr
    assert isinstance(old_held_call, ast.Call)
    old_held_keywords = {
        keyword.arg: keyword.value
        for keyword in old_held_call.keywords
        if keyword.arg is not None
    }
    if (
        len(old_held_keywords) != len(old_held_call.keywords)
        or _python_attribute_path(
            old_held_keywords.get("terminal_name_policy", ast.Constant(None))
        )
        != ("LAUNCHER_NAME_INSTALLER_REBIND",)
    ):
        return False
    installed_contexts = [
        node
        for node in ast.walk(old_context)
        if held_context(node, "interpreter", "installed_launcher")
    ]
    if len(installed_contexts) != 1:
        return False
    installed_context = installed_contexts[0]
    installed_held_call = installed_context.items[0].context_expr
    assert isinstance(installed_held_call, ast.Call)
    if any(
        keyword.arg == "terminal_name_policy"
        for keyword in installed_held_call.keywords
    ):
        return False

    install_run_calls = [
        node
        for node in ast.walk(install)
        if isinstance(node, ast.Call)
        and _python_attribute_path(node.func) == ("_run_owned_process",)
    ]
    reviewed_calls = [
        node
        for node in ast.walk(old_context)
        if isinstance(node, ast.Call)
        and _python_attribute_path(node.func)
        == ("_run_reviewed_framework_installer",)
    ]
    if len(install_run_calls) != 2 or len(reviewed_calls) != 1:
        return False
    reviewed_call = reviewed_calls[0]
    if reviewed_call.args or any(
        keyword.arg is None for keyword in reviewed_call.keywords
    ):
        return False
    reviewed_keywords = {
        keyword.arg: keyword.value for keyword in reviewed_call.keywords
    }
    expected_reviewed_names = {
        "package": ("package",),
        "expected_package_sha256": ("package_sha256",),
        "locked_framework_root": ("install_root",),
        "python_lock": ("python_lock",),
        "locked_interpreter": ("interpreter",),
        "launcher_binding": ("old_launcher",),
        "cwd": ("source", "root"),
        "environment": ("sanitized",),
        "pass_fds": ("source_child_fds",),
        "build": ("build",),
        "cwd_descriptor": ("source", "descriptor"),
        "path_capabilities": ("installer_path_capabilities",),
    }
    if (
        set(reviewed_keywords) != set(expected_reviewed_names)
        or any(
            _python_attribute_path(reviewed_keywords[key]) != expected
            for key, expected in expected_reviewed_names.items()
        )
    ):
        return False

    rebind_calls = [
        node
        for node in ast.walk(reviewed_installer)
        if isinstance(node, ast.Call)
        and _python_attribute_path(node.func) == ("_run_owned_process",)
    ]
    if len(rebind_calls) != 1:
        return False
    rebind_call = rebind_calls[0]
    if any(keyword.arg is None for keyword in rebind_call.keywords):
        return False
    rebind_keywords = {
        keyword.arg: keyword.value for keyword in rebind_call.keywords
    }
    expected_names = {
        "cwd": ("cwd",),
        "environment": ("environment",),
        "pass_fds": ("pass_fds",),
        "build": ("build",),
        "cwd_descriptor": ("cwd_descriptor",),
        "launcher_python": ("locked_interpreter",),
        "launcher_binding": ("launcher_binding",),
        "launcher_name_policy": (
            "LAUNCHER_NAME_INSTALLER_PENDING_SEAL",
        ),
        "launcher_rebind_authority": (
            "_REVIEWED_INSTALLER_REBIND_AUTHORITY",
        ),
        "path_capabilities": ("path_capabilities",),
    }
    expected_arguments = ast.parse(
        "('/usr/bin/sudo', '--non-interactive', '/usr/sbin/installer', "
        "'-pkg', str(package.path), '-target', '/')",
        mode="eval",
    ).body
    if (
        len(rebind_call.args) != 1
        or ast.dump(rebind_call.args[0], include_attributes=False)
        != ast.dump(expected_arguments, include_attributes=False)
        or set(rebind_keywords)
        != {
            "cwd",
            "environment",
            "pass_fds",
            "timeout",
            "label",
            "build",
            "cwd_descriptor",
            "launcher_python",
            "launcher_binding",
            "launcher_name_policy",
            "launcher_rebind_authority",
            "path_capabilities",
        }
        or any(
            _python_attribute_path(rebind_keywords[key]) != expected
            for key, expected in expected_names.items()
        )
        or not isinstance(rebind_keywords["timeout"], ast.Constant)
        or rebind_keywords["timeout"].value != 900
        or not isinstance(rebind_keywords["label"], ast.Constant)
        or rebind_keywords["label"].value != "Python framework installation"
    ):
        return False

    if tuple(type(statement) for statement in reviewed_installer.body) != (
        ast.Expr,
        ast.Assign,
        ast.If,
        ast.Expr,
        ast.Expr,
        ast.AnnAssign,
        ast.AnnAssign,
        ast.Try,
        ast.AnnAssign,
        ast.With,
        ast.If,
        ast.If,
        ast.Expr,
        ast.Expr,
        ast.Expr,
        ast.If,
        ast.Return,
    ):
        return False
    reviewed_contract_if = reviewed_installer.body[2]
    assert isinstance(reviewed_contract_if, ast.If)
    if (
        not exact_expression(
            reviewed_contract_if.test,
            "not locked_interpreter.is_absolute() "
            "or '..' in locked_interpreter.parts "
            "or locked_framework_root != locked_interpreter.parents[1] "
            "or launcher_binding.path != locked_interpreter "
            "or package.path != package.path.resolve(strict=True) "
            "or package.sha256 != expected_package_sha256 "
            "or package_capabilities != "
            "((package.descriptor, str(package.path), False),)",
        )
        or len(reviewed_contract_if.body) != 1
        or not direct_toolchain_raise(reviewed_contract_if.body[0])
        or reviewed_contract_if.orelse
    ):
        return False

    reviewed_source = ast.get_source_segment(source, reviewed_installer) or ""
    for marker in (
        "launcher_binding.path != locked_interpreter",
        "locked_framework_root != locked_interpreter.parents[1]",
        "package.path != package.path.resolve(strict=True)",
        "package.sha256 != expected_package_sha256",
        "((package.descriptor, str(package.path), False),)",
        "_revalidate_held_executable(",
        "launcher_name_policy=LAUNCHER_NAME_INSTALLER_PENDING_SEAL",
        "_seal_reviewed_framework_permissions(",
        "_verify_reviewed_framework_seal(",
        "_verify_reviewed_framework_core(",
        "name_policy=LAUNCHER_NAME_INSTALLER_REBIND",
        "_revalidate_bound_file(",
    ):
        if marker not in reviewed_source:
            return False

    reviewed_parents = {
        child: parent
        for parent in ast.walk(reviewed_installer)
        for child in ast.iter_child_nodes(parent)
    }
    seal_calls = [
        (node, node.value)
        for node in ast.walk(reviewed_installer)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and _python_attribute_path(node.value.func)
        == ("_seal_reviewed_framework_permissions",)
    ]
    framework_verifiers = [
        (node, node.value)
        for node in ast.walk(reviewed_installer)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and _python_attribute_path(node.value.func)
        == ("_verify_reviewed_framework_seal",)
    ]
    core_verifiers = [
        (node, node.value)
        for node in ast.walk(reviewed_installer)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and _python_attribute_path(node.value.func)
        == ("_verify_reviewed_framework_core",)
    ]
    strict_rebinds = [
        (node, node.value)
        for node in ast.walk(reviewed_installer)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and _python_attribute_path(node.value.func)
        == ("_revalidate_held_executable",)
        and any(
            keyword.arg == "name_policy"
            and _python_attribute_path(keyword.value)
            == ("LAUNCHER_NAME_INSTALLER_REBIND",)
            for keyword in node.value.keywords
        )
    ]
    if (
        len(seal_calls) != 1
        or len(framework_verifiers) != 1
        or len(core_verifiers) != 1
        or len(strict_rebinds) != 1
    ):
        return False
    seal_statement, seal_call = seal_calls[0]
    verify_statement, verify_call = framework_verifiers[0]
    core_statement, core_call = core_verifiers[0]
    strict_statement, strict_call = strict_rebinds[0]
    seal_try = reviewed_parents.get(seal_statement)
    seal_with = reviewed_parents.get(seal_try)
    if (
        not isinstance(seal_try, ast.Try)
        or not isinstance(seal_with, ast.With)
        or seal_try.body != [seal_statement]
        or seal_with.body != [seal_try]
        or seal_with not in reviewed_installer.body
        or not isinstance(reviewed_installer.body[7], ast.Try)
        or rebind_call not in set(ast.walk(reviewed_installer.body[7]))
        or reviewed_installer.body.index(seal_with) <= 7
        or verify_statement not in reviewed_installer.body
        or core_statement not in reviewed_installer.body
        or strict_statement not in reviewed_installer.body
        or reviewed_installer.body.index(verify_statement)
        >= reviewed_installer.body.index(core_statement)
        or reviewed_installer.body.index(core_statement)
        >= reviewed_installer.body.index(strict_statement)
        or reviewed_installer.body.index(strict_statement)
        >= len(reviewed_installer.body) - 1
        or _python_has_constant_false_ancestor(seal_statement, reviewed_parents)
        or _python_has_constant_false_ancestor(verify_statement, reviewed_parents)
        or _python_has_constant_false_ancestor(core_statement, reviewed_parents)
        or _python_has_constant_false_ancestor(strict_statement, reviewed_parents)
    ):
        return False
    seal_with_call = seal_with.items[0].context_expr
    if (
        len(seal_with.items) != 1
        or not isinstance(seal_with_call, ast.Call)
        or _python_attribute_path(seal_with_call.func)
        != ("build", "_defer_publish_signals")
        or seal_with_call.args
        or {
            keyword.arg: _python_attribute_path(keyword.value)
            for keyword in seal_with_call.keywords
            if keyword.arg is not None
        }
        != {"preserve_error": ("installer_error",)}
        or len(seal_call.args) != 1
        or _python_attribute_path(seal_call.args[0])
        != ("locked_framework_root",)
        or {
            keyword.arg: _python_attribute_path(keyword.value)
            for keyword in seal_call.keywords
            if keyword.arg is not None
        }
        != {"environment": ("environment",), "build": ("build",)}
        or len(verify_call.args) != 1
        or _python_attribute_path(verify_call.args[0])
        != ("locked_framework_root",)
        or {
            keyword.arg: _python_attribute_path(keyword.value)
            for keyword in verify_call.keywords
            if keyword.arg is not None
        }
        != {"python_lock": ("python_lock",)}
        or len(core_call.args) != 1
        or _python_attribute_path(core_call.args[0])
        != ("locked_framework_root",)
        or {
            keyword.arg: _python_attribute_path(keyword.value)
            for keyword in core_call.keywords
            if keyword.arg is not None
        }
        != {"python_lock": ("python_lock",), "build": ("build",)}
        or len(strict_call.args) != 1
        or _python_attribute_path(strict_call.args[0]) != ("launcher_binding",)
    ):
        return False

    installed_nodes = set(ast.walk(installed_context))
    observer_calls = [
        call
        for call in install_run_calls
        if any(
            keyword.arg == "launcher_binding"
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id == "installed_launcher"
            for keyword in call.keywords
        )
    ]
    binding_verifiers = [
        node
        for node in installed_nodes
        if isinstance(node, ast.Call)
        and _python_attribute_path(node.func)
        == ("build", "verify_python_install_binding")
    ]
    return (
        len(observer_calls) == 1
        and observer_calls[0] in installed_nodes
        and not any(
            keyword.arg == "launcher_name_policy"
            for keyword in observer_calls[0].keywords
        )
        and len(binding_verifiers) == 1
    )


def _legacy_python_reviewed_framework_security_is_semantic(source: str) -> bool:
    """Bind ACL/mode sealing and the complete reviewed framework byte closure."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    function_names = (
        "_reviewed_framework_security_contract",
        "_reviewed_framework_core_contract",
        "_reviewed_framework_owner",
        "_verify_locked_framework_regular",
        "_verify_reviewed_framework_acl_seal",
        "_verify_reviewed_framework_seal",
        "_verify_reviewed_framework_core",
        "_seal_reviewed_framework_permissions",
        "_run_reviewed_framework_installer",
        "install_reviewed_python",
        "build_with_exact_toolchain",
    )
    functions = {name: _python_function(tree, name) for name in function_names}
    if any(function is None for function in functions.values()):
        return False

    def exact_expression(node: ast.AST, expression: str) -> bool:
        expected = ast.parse(expression, mode="eval").body
        return ast.dump(node, include_attributes=False) == ast.dump(
            expected,
            include_attributes=False,
        )

    def direct_toolchain_raise(statement: ast.stmt) -> bool:
        return (
            isinstance(statement, ast.Raise)
            and isinstance(statement.exc, ast.Call)
            and _python_attribute_path(statement.exc.func)
            == ("ToolchainBootstrapError",)
        )

    def exact_direct_guard(
        function: ast.FunctionDef,
        expression: str,
    ) -> bool:
        parents = {
            child: parent
            for parent in ast.walk(function)
            for child in ast.iter_child_nodes(parent)
        }
        matches = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.If) and exact_expression(node.test, expression)
        ]
        return (
            len(matches) == 1
            and len(matches[0].body) == 1
            and direct_toolchain_raise(matches[0].body[0])
            and not matches[0].orelse
            and not _python_has_constant_false_ancestor(matches[0], parents)
        )

    def module_literal(name: str) -> Any:
        assignments = [
            statement
            for statement in tree.body
            if isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == name
        ]
        if len(assignments) != 1:
            return None
        try:
            return ast.literal_eval(assignments[0].value)
        except (TypeError, ValueError):
            return None

    default_root_assignments = [
        statement
        for statement in tree.body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == "DEFAULT_REVIEWED_FRAMEWORK_ROOT"
    ]
    if (
        len(default_root_assignments) != 1
        or not exact_expression(
            default_root_assignments[0].value,
            "PurePosixPath('/Library/Frameworks/Python.framework/Versions/3.13')",
        )
    ):
        return False

    expected_parent_commands = (
        (
            "/usr/bin/sudo",
            "--non-interactive",
            "/usr/sbin/chown",
            "-h",
            "0:0",
        ),
        (
            "/usr/bin/sudo",
            "--non-interactive",
            "/bin/chmod",
            "-h",
            "-N",
        ),
        (
            "/usr/bin/sudo",
            "--non-interactive",
            "/bin/chmod",
            "-h",
            "go-w",
        ),
    )
    expected_root_commands = (
        (
            "/usr/bin/sudo",
            "--non-interactive",
            "/usr/sbin/chown",
            "-R",
            "-P",
            "-h",
            "0:0",
        ),
        (
            "/usr/bin/sudo",
            "--non-interactive",
            "/bin/chmod",
            "-R",
            "-P",
            "-N",
        ),
        (
            "/usr/bin/sudo",
            "--non-interactive",
            "/bin/chmod",
            "-R",
            "-P",
            "go-w",
        ),
    )
    expected_cache_arguments = (
        (
            "-type",
            "f",
            "(",
            "-iname",
            "*.pyc",
            "-o",
            "-iname",
            "*.pyo",
            ")",
            "-delete",
        ),
        (
            "-depth",
            "-type",
            "d",
            "-iname",
            "__pycache__",
            "-delete",
        ),
    )
    if (
        module_literal("REVIEWED_FRAMEWORK_PARENT_PERMISSION_COMMANDS")
        != expected_parent_commands
        or module_literal("REVIEWED_FRAMEWORK_PERMISSION_COMMANDS")
        != expected_root_commands
        or module_literal("REVIEWED_FRAMEWORK_CACHE_REMOVAL_ARGUMENTS")
        != expected_cache_arguments
        or module_literal("REVIEWED_FRAMEWORK_CORE_EXCLUDED_PATHS")
        != PYTHON_FRAMEWORK_CORE_EXCLUDED_PATHS
        or source.count("REVIEWED_FRAMEWORK_PARENT_PERMISSION_COMMANDS") != 5
        or source.count("REVIEWED_FRAMEWORK_PERMISSION_COMMANDS") != 2
        or source.count("REVIEWED_FRAMEWORK_CACHE_REMOVAL_ARGUMENTS") != 2
        or source.count("REVIEWED_FRAMEWORK_CORE_EXCLUDED_PATHS") != 3
        or source.count("_verify_reviewed_framework_seal(") != 4
        or source.count("_verify_reviewed_framework_core(") != 4
        or source.count(
            "PurePosixPath(root.as_posix()) != DEFAULT_REVIEWED_FRAMEWORK_ROOT"
        )
        != 1
        or source.count(
            "PurePosixPath(install_root.as_posix())\n"
            "                != DEFAULT_REVIEWED_FRAMEWORK_ROOT"
        )
        != 2
    ):
        return False

    owner = functions["_reviewed_framework_owner"]
    assert owner is not None
    owner_statements = [
        statement
        for statement in owner.body
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
    ]
    if (
        len(owner_statements) != 1
        or not isinstance(owner_statements[0], ast.Return)
        or not isinstance(owner_statements[0].value, ast.Constant)
        or owner_statements[0].value.value != 0
    ):
        return False

    security_contract = functions["_reviewed_framework_security_contract"]
    core_contract = functions["_reviewed_framework_core_contract"]
    locked_regular = functions["_verify_locked_framework_regular"]
    acl_verifier = functions["_verify_reviewed_framework_acl_seal"]
    framework_seal = functions["_verify_reviewed_framework_seal"]
    core_verifier = functions["_verify_reviewed_framework_core"]
    permission_seal = functions["_seal_reviewed_framework_permissions"]
    reviewed_installer = functions["_run_reviewed_framework_installer"]
    install = functions["install_reviewed_python"]
    build_exact = functions["build_with_exact_toolchain"]
    assert security_contract is not None
    assert core_contract is not None
    assert locked_regular is not None
    assert acl_verifier is not None
    assert framework_seal is not None
    assert core_verifier is not None
    assert permission_seal is not None
    assert reviewed_installer is not None
    assert install is not None
    assert build_exact is not None

    security_assignments = {
        "interpreter_relative": "Path(str(python_lock['interpreterRelativePath']))",
        "interpreter_size": "int(python_lock['interpreterSize'])",
        "interpreter_sha256": "str(python_lock['interpreterSha256'])",
        "framework_relative": "Path(str(python_lock['frameworkBinaryRelativePath']))",
        "framework_size": "int(python_lock['frameworkBinarySize'])",
        "framework_sha256": "str(python_lock['frameworkBinarySha256'])",
        "entries": "((interpreter_relative, interpreter_size, interpreter_sha256), "
        "(framework_relative, framework_size, framework_sha256))",
    }
    if any(
        not _python_exact_single_assignment(security_contract, name, expression)
        for name, expression in security_assignments.items()
    ):
        return False
    security_source = ast.get_source_segment(source, security_contract) or ""
    for marker in (
        "relative.is_absolute()",
        'any(part in {"", ".", ".."} for part in relative.parts)',
        "size <= 0",
        "size > MAX_TREE_FILE_BYTES",
        "SHA256_PATTERN.fullmatch(digest) is None",
        "return entries",
    ):
        if marker not in security_source:
            return False

    if (
        tuple(type(statement) for statement in core_contract.body)
        != (ast.Expr, ast.Assign, ast.Assign, ast.If, ast.Return)
        or not _python_exact_single_assignment(
            core_contract,
            "raw_exclusions",
            "python_lock.get('frameworkCoreFingerprintExcludedPaths')",
        )
        or not _python_exact_single_assignment(
            core_contract,
            "digest",
            "str(python_lock.get('frameworkCoreFingerprintSha256', ''))",
        )
    ):
        return False
    core_guard = core_contract.body[3]
    core_return = core_contract.body[4]
    if (
        not isinstance(core_guard, ast.If)
        or not exact_expression(
            core_guard.test,
            "raw_exclusions != list(REVIEWED_FRAMEWORK_CORE_EXCLUDED_PATHS) "
            "or SHA256_PATTERN.fullmatch(digest) is None",
        )
        or len(core_guard.body) != 1
        or not direct_toolchain_raise(core_guard.body[0])
        or core_guard.orelse
        or not isinstance(core_return, ast.Return)
        or core_return.value is None
        or not exact_expression(
            core_return.value,
            "(REVIEWED_FRAMEWORK_CORE_EXCLUDED_PATHS, digest)",
        )
    ):
        return False

    locked_source = ast.get_source_segment(source, locked_regular) or ""
    locked_markers = (
        "os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC",
        "not stat.S_ISREG(held.st_mode)",
        "stat.S_ISLNK(named.st_mode)",
        "_identity(held) != _identity(named)",
        "held.st_uid != expected_owner",
        "held.st_nlink != 1",
        "held.st_size != expected_size",
        "stat.S_IMODE(held.st_mode) & 0o7022",
        "hashlib.sha256(payload).hexdigest() != expected_sha256",
        "_identity(os.fstat(descriptor)) != _identity(held)",
        "_identity(path.lstat()) != _identity(held)",
    )
    if any(marker not in locked_source for marker in locked_markers):
        return False

    if tuple(type(statement) for statement in acl_verifier.body) != (
        ast.Expr,
        ast.If,
        ast.Assign,
        ast.Assign,
        ast.For,
    ):
        return False
    acl_platform_guard = acl_verifier.body[1]
    acl_loop = acl_verifier.body[4]
    assert isinstance(acl_platform_guard, ast.If)
    assert isinstance(acl_loop, ast.For)
    if (
        not exact_expression(acl_platform_guard.test, "sys.platform != 'darwin'")
        or tuple(type(statement) for statement in acl_platform_guard.body)
        != (ast.Return,)
        or acl_platform_guard.orelse
        or not _python_exact_single_assignment(
            acl_verifier,
            "commands",
            "(('/bin/ls', '-led', str(root.parents[3]), "
            "str(root.parents[2]), str(root.parents[1]), str(root.parent), "
            "str(root)), ('/bin/ls', '-leR', str(root)))",
        )
        or not _python_exact_single_assignment(
            acl_verifier,
            "acl_entry",
            "re.compile(rb'(?m)^[ \\t]+[0-9]+: ')",
        )
        or not isinstance(acl_loop.target, ast.Name)
        or acl_loop.target.id != "command"
        or not isinstance(acl_loop.iter, ast.Name)
        or acl_loop.iter.id != "commands"
        or acl_loop.orelse
        or tuple(type(statement) for statement in acl_loop.body)
        != (ast.Assign, ast.Try, ast.If)
        or not _python_exact_single_assignment(
            acl_loop,
            "expected",
            "_exec_target_identity(Path(command[0]))",
        )
    ):
        return False
    acl_process_try = acl_loop.body[1]
    acl_mismatch = acl_loop.body[2]
    assert isinstance(acl_process_try, ast.Try)
    assert isinstance(acl_mismatch, ast.If)
    acl_process_assignment = (
        acl_process_try.body[0]
        if len(acl_process_try.body) == 1
        else None
    )
    acl_process_call = (
        acl_process_assignment.value
        if isinstance(acl_process_assignment, ast.Assign)
        and len(acl_process_assignment.targets) == 1
        and isinstance(acl_process_assignment.targets[0], ast.Name)
        and acl_process_assignment.targets[0].id == "process"
        and isinstance(acl_process_assignment.value, ast.Call)
        else None
    )
    if (
        acl_process_call is None
        or _python_attribute_path(acl_process_call.func)
        != ("subprocess", "run")
        or len(acl_process_call.args) != 1
        or _python_attribute_path(acl_process_call.args[0]) != ("command",)
        or {
            keyword.arg: ast.dump(keyword.value, include_attributes=False)
            for keyword in acl_process_call.keywords
            if keyword.arg is not None
        }
        != {
            "cwd": ast.dump(ast.parse("Path('/')", mode="eval").body, include_attributes=False),
            "env": ast.dump(ast.parse("{'LC_ALL': 'C', 'PATH': '/usr/bin:/bin'}", mode="eval").body, include_attributes=False),
            "stdin": ast.dump(ast.parse("subprocess.DEVNULL", mode="eval").body, include_attributes=False),
            "stdout": ast.dump(ast.parse("subprocess.PIPE", mode="eval").body, include_attributes=False),
            "stderr": ast.dump(ast.parse("subprocess.PIPE", mode="eval").body, include_attributes=False),
            "timeout": ast.dump(ast.Constant(value=120), include_attributes=False),
            "check": ast.dump(ast.Constant(value=False), include_attributes=False),
            "start_new_session": ast.dump(ast.Constant(value=True), include_attributes=False),
            "umask": ast.dump(ast.Constant(value=0o077), include_attributes=False),
        }
        or len(acl_process_try.handlers) != 1
        or acl_process_try.orelse
        or acl_process_try.finalbody
        or not exact_expression(
            acl_mismatch.test,
            "process.returncode != 0 or not process.stdout "
            "or process.stderr "
            "or len(process.stdout) > MAX_SUBPROCESS_OUTPUT_BYTES "
            "or acl_entry.search(process.stdout) is not None "
            "or expected != _exec_target_identity(Path(command[0]))",
        )
        or len(acl_mismatch.body) != 1
        or not direct_toolchain_raise(acl_mismatch.body[0])
        or acl_mismatch.orelse
        or any(
            isinstance(node, ast.keyword) and node.arg == "shell"
            for node in ast.walk(acl_verifier)
        )
    ):
        return False

    seal_source = ast.get_source_segment(source, framework_seal) or ""
    seal_markers = (
        "root.resolve(strict=True) != root",
        "root.parent.resolve(strict=True) != root.parent",
        "root_before = root.lstat()",
        "parent_before = root.parent.lstat()",
        "anchor_before = root.parents[1].lstat()",
        "container_before = root.parents[2].lstat()",
        "library_before = root.parents[3].lstat()",
        "root_before.st_uid != expected_owner",
        "parent_before.st_uid != expected_owner",
        "anchor_before.st_uid != expected_owner",
        "container_before.st_uid != expected_owner",
        "library_before.st_uid != expected_owner",
        "stat.S_IMODE(root_before.st_mode) & 0o7022",
        "stat.S_IMODE(parent_before.st_mode) & 0o7022",
        "stat.S_IMODE(anchor_before.st_mode) & 0o7022",
        "stat.S_IMODE(container_before.st_mode) & 0o7022",
        "stat.S_IMODE(library_before.st_mode) & 0o7022",
        "followlinks=False",
        "entry_count > MAX_TREE_ENTRIES",
        "info.st_uid != expected_owner",
        'part.casefold() for part in relative_path.parts',
        '"__pycache__" in folded_parts',
        'relative_path.name.casefold().endswith((".pyc", ".pyo"))',
        "info.st_nlink != 1",
        "target_path.is_absolute()",
        '"\\x00" in target',
        "root not in (unresolved, *unresolved.parents)",
        "root not in (resolved, *resolved.parents)",
        "mode & 0o7022",
        "not stat.S_ISREG(info.st_mode)",
        "info.st_nlink != 1 or info.st_size > MAX_TREE_FILE_BYTES",
        "total_size > MAX_TREE_TOTAL_BYTES",
        "observed_broken != broken",
        "_identity(root.lstat()) != _identity(root_before)",
        "_identity(root.parent.lstat()) != _identity(parent_before)",
        "_identity(root.parents[1].lstat()) != _identity(anchor_before)",
        "_identity(root.parents[2].lstat()) != _identity(container_before)",
        "_identity(root.parents[3].lstat()) != _identity(library_before)",
        "_reviewed_framework_security_contract(",
        "_verify_locked_framework_regular(",
    )
    if any(marker not in seal_source for marker in seal_markers):
        return False
    seal_parents = {
        child: parent
        for parent in ast.walk(framework_seal)
        for child in ast.iter_child_nodes(parent)
    }
    walks = [
        node
        for node in ast.walk(framework_seal)
        if isinstance(node, ast.For)
        and isinstance(node.iter, ast.Call)
        and _python_attribute_path(node.iter.func) == ("os", "walk")
        and len(node.iter.args) == 1
        and _python_attribute_path(node.iter.args[0]) == ("root",)
        and {
            keyword.arg: (
                keyword.value.value
                if isinstance(keyword.value, ast.Constant)
                else None
            )
            for keyword in node.iter.keywords
        }
        == {"topdown": True, "followlinks": False}
    ]
    locked_calls = [
        node
        for node in ast.walk(framework_seal)
        if isinstance(node, ast.Call)
        and _python_attribute_path(node.func)
        == ("_verify_locked_framework_regular",)
    ]
    acl_calls = [
        node
        for node in ast.walk(framework_seal)
        if isinstance(node, ast.Call)
        and _python_attribute_path(node.func)
        == ("_verify_reviewed_framework_acl_seal",)
    ]
    if (
        len(walks) != 1
        or len(locked_calls) != 1
        or len(acl_calls) != 1
        or not _python_exact_single_assignment(
            framework_seal,
            "relative_path",
            "PurePosixPath(relative)",
        )
        or not _python_exact_single_assignment(
            framework_seal,
            "folded_parts",
            "tuple(part.casefold() for part in relative_path.parts)",
        )
        or _python_has_constant_false_ancestor(walks[0], seal_parents)
        or _python_has_constant_false_ancestor(locked_calls[0], seal_parents)
        or _python_has_constant_false_ancestor(acl_calls[0], seal_parents)
        or acl_calls[0].lineno >= locked_calls[0].lineno
        or not exact_direct_guard(
            framework_seal,
            "root not in (resolved, *resolved.parents)",
        )
        or not exact_direct_guard(
            framework_seal,
            "not stat.S_ISREG(info.st_mode)",
        )
        or not exact_direct_guard(
            framework_seal,
            "'__pycache__' in folded_parts "
            "or relative_path.name.casefold().endswith(('.pyc', '.pyo'))",
        )
        or not exact_direct_guard(
            framework_seal,
            "info.st_nlink != 1 or info.st_size > MAX_TREE_FILE_BYTES",
        )
        or not exact_direct_guard(
            framework_seal,
            "_identity(root.lstat()) != _identity(root_before) "
            "or _identity(root.parent.lstat()) != _identity(parent_before) "
            "or _identity(root.parents[1].lstat()) != _identity(anchor_before) "
            "or _identity(root.parents[2].lstat()) != _identity(container_before) "
            "or _identity(root.parents[3].lstat()) != _identity(library_before)",
        )
    ):
        return False

    if tuple(type(statement) for statement in core_verifier.body) != (
        ast.Expr,
        ast.Assign,
        ast.Try,
        ast.If,
    ):
        return False
    core_binding = core_verifier.body[1]
    core_try = core_verifier.body[2]
    core_mismatch = core_verifier.body[3]
    if (
        not isinstance(core_binding, ast.Assign)
        or len(core_binding.targets) != 1
        or ast.unparse(core_binding.targets[0]) != "(exclusions, expected)"
        or not exact_expression(
            core_binding.value,
            "_reviewed_framework_core_contract(python_lock)",
        )
        or not isinstance(core_try, ast.Try)
        or len(core_try.body) != 1
        or not isinstance(core_try.body[0], ast.Assign)
        or not exact_expression(
            core_try.body[0].value,
            "build.fingerprint_install_root("
            "root, reviewed_broken_symlinks="
            "_reviewed_broken_framework_symlinks(python_lock), "
            "excluded_paths=exclusions)",
        )
        or len(core_try.handlers) != 1
        or _python_attribute_path(core_try.handlers[0].type)
        != ("build", "BuildError")
        or core_try.orelse
        or core_try.finalbody
        or not isinstance(core_mismatch, ast.If)
        or not exact_expression(core_mismatch.test, "observed != expected")
        or len(core_mismatch.body) != 1
        or not direct_toolchain_raise(core_mismatch.body[0])
        or core_mismatch.orelse
    ):
        return False

    if tuple(type(statement) for statement in permission_seal.body) != (
        ast.Expr,
        ast.If,
        ast.Assign,
        ast.AnnAssign,
        ast.AnnAssign,
        ast.FunctionDef,
        ast.FunctionDef,
        ast.Try,
        ast.Assign,
        ast.Assign,
        ast.Try,
    ):
        return False
    permission_guard = permission_seal.body[1]
    directory_binding = permission_seal.body[5]
    verify_targets = permission_seal.body[6]
    binding_try = permission_seal.body[7]
    command_try = permission_seal.body[10]
    assert isinstance(directory_binding, ast.FunctionDef)
    assert isinstance(verify_targets, ast.FunctionDef)
    assert isinstance(binding_try, ast.Try)
    assert isinstance(command_try, ast.Try)
    if (
        not isinstance(permission_guard, ast.If)
        or not exact_expression(
            permission_guard.test,
            "not root.is_absolute() or '..' in root.parts "
            "or PurePosixPath(root.as_posix()) "
            "!= DEFAULT_REVIEWED_FRAMEWORK_ROOT "
            "or root.resolve(strict=True) != root "
            "or root.parent.resolve(strict=True) != root.parent "
            "or root.parents[1].resolve(strict=True) != root.parents[1] "
            "or root.parents[2].resolve(strict=True) != root.parents[2] "
            "or root.parents[3].resolve(strict=True) != root.parents[3]",
        )
        or len(permission_guard.body) != 1
        or not direct_toolchain_raise(permission_guard.body[0])
        or permission_guard.orelse
        or not _python_exact_single_assignment(
            permission_seal,
            "targets",
            "(root.parents[3], root.parents[2], root.parents[1], "
            "root.parent, root)",
        )
        or directory_binding.name != "directory_binding"
        or tuple(type(statement) for statement in directory_binding.body)
        != (ast.Return,)
        or not isinstance(directory_binding.body[0], ast.Return)
        or directory_binding.body[0].value is None
        or not exact_expression(
            directory_binding.body[0].value,
            "(info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))",
        )
        or verify_targets.name != "verify_targets"
        or tuple(type(statement) for statement in verify_targets.body)
        != (ast.For,)
    ):
        return False

    verify_loop = verify_targets.body[0]
    assert isinstance(verify_loop, ast.For)
    if (
        ast.unparse(verify_loop.target) != "(target, descriptor, expected)"
        or not exact_expression(
            verify_loop.iter,
            "zip(targets, target_descriptors, target_bindings, strict=True)",
        )
        or verify_loop.orelse
        or tuple(type(statement) for statement in verify_loop.body)
        != (ast.Assign, ast.Assign, ast.If)
        or not _python_exact_single_assignment(
            verify_targets,
            "held",
            "os.fstat(descriptor)",
        )
        or not _python_exact_single_assignment(
            verify_targets,
            "named",
            "target.lstat()",
        )
        or not exact_direct_guard(
            verify_targets,
            "directory_binding(held) != expected "
            "or directory_binding(named) != expected "
            "or not stat.S_ISDIR(held.st_mode) "
            "or stat.S_ISLNK(named.st_mode) "
            "or target.resolve(strict=True) != target",
        )
    ):
        return False

    if (
        tuple(type(statement) for statement in binding_try.body)
        != (ast.For, ast.Expr)
        or binding_try.orelse
        or binding_try.finalbody
        or len(binding_try.handlers) != 2
    ):
        return False
    binding_loop = binding_try.body[0]
    binding_verify = binding_try.body[1]
    assert isinstance(binding_loop, ast.For)
    if (
        not isinstance(binding_loop.target, ast.Name)
        or binding_loop.target.id != "target"
        or not isinstance(binding_loop.iter, ast.Name)
        or binding_loop.iter.id != "targets"
        or binding_loop.orelse
        or tuple(type(statement) for statement in binding_loop.body)
        != (ast.Assign, ast.Expr, ast.Assign, ast.Assign, ast.If, ast.Expr)
        or not _python_exact_single_assignment(
            binding_loop,
            "descriptor",
            "os.open(target, os.O_RDONLY | os.O_DIRECTORY | "
            "os.O_NOFOLLOW | os.O_CLOEXEC)",
        )
        or not _python_exact_single_assignment(
            binding_loop,
            "held",
            "os.fstat(descriptor)",
        )
        or not _python_exact_single_assignment(
            binding_loop,
            "named",
            "target.lstat()",
        )
        or not exact_direct_guard(
            binding_loop,
            "not stat.S_ISDIR(held.st_mode) "
            "or stat.S_ISLNK(named.st_mode) "
            "or directory_binding(held) != directory_binding(named)",
        )
        or not isinstance(binding_verify, ast.Expr)
        or not isinstance(binding_verify.value, ast.Call)
        or _python_attribute_path(binding_verify.value.func)
        != ("verify_targets",)
        or binding_verify.value.args
        or binding_verify.value.keywords
        or _python_has_constant_false_ancestor(
            binding_loop,
            {
                child: parent
                for parent in ast.walk(permission_seal)
                for child in ast.iter_child_nodes(parent)
            },
        )
    ):
        return False

    if not _python_exact_single_assignment(
        permission_seal,
        "commands",
        "(*((*prefix, str(root.parents[3])) for prefix in "
        "REVIEWED_FRAMEWORK_PARENT_PERMISSION_COMMANDS), "
        "*((*prefix, str(root.parents[2])) for prefix in "
        "REVIEWED_FRAMEWORK_PARENT_PERMISSION_COMMANDS), "
        "*((*prefix, str(root.parents[1])) for prefix in "
        "REVIEWED_FRAMEWORK_PARENT_PERMISSION_COMMANDS), "
        "*((*prefix, str(root.parent)) for prefix in "
        "REVIEWED_FRAMEWORK_PARENT_PERMISSION_COMMANDS), "
        "*((*prefix, str(root)) for prefix in "
        "REVIEWED_FRAMEWORK_PERMISSION_COMMANDS), "
        "*((('/usr/bin/sudo', '--non-interactive', '/usr/bin/find', "
        "'-x', str(root), *arguments) for arguments in "
        "REVIEWED_FRAMEWORK_CACHE_REMOVAL_ARGUMENTS)))",
    ):
        return False
    expected_labels = (
        "Python framework library ownership normalization",
        "Python framework library ACL sealing",
        "Python framework library permission sealing",
        "Python framework container ownership normalization",
        "Python framework container ACL sealing",
        "Python framework container permission sealing",
        "Python framework anchor ownership normalization",
        "Python framework anchor ACL sealing",
        "Python framework anchor permission sealing",
        "Python framework parent ownership normalization",
        "Python framework parent ACL sealing",
        "Python framework parent permission sealing",
        "Python framework ownership normalization",
        "Python framework ACL sealing",
        "Python framework permission sealing",
        "Python framework bytecode cache file removal",
        "Python framework bytecode cache directory removal",
    )
    label_assignments = [
        statement
        for statement in permission_seal.body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == "labels"
    ]
    try:
        observed_labels = ast.literal_eval(label_assignments[0].value)
    except (IndexError, TypeError, ValueError):
        return False
    if observed_labels != expected_labels:
        return False
    if (
        tuple(type(statement) for statement in command_try.body) != (ast.For,)
        or command_try.handlers
        or command_try.orelse
        or tuple(type(statement) for statement in command_try.finalbody)
        != (ast.For,)
    ):
        return False
    permission_loop = command_try.body[0]
    assert isinstance(permission_loop, ast.For)
    if (
        ast.unparse(permission_loop.target) != "(command, label)"
        or not exact_expression(
            permission_loop.iter,
            "zip(commands, labels, strict=True)",
        )
        or permission_loop.orelse
        or tuple(type(statement) for statement in permission_loop.body)
        != (ast.Expr, ast.Assign, ast.Assign, ast.If, ast.Expr)
    ):
        return False
    verify_before = permission_loop.body[0]
    verify_after = permission_loop.body[4]
    if any(
        not isinstance(statement, ast.Expr)
        or not isinstance(statement.value, ast.Call)
        or _python_attribute_path(statement.value.func) != ("verify_targets",)
        or statement.value.args
        or statement.value.keywords
        for statement in (verify_before, verify_after)
    ):
        return False
    observed_assignment = permission_loop.body[2]
    if (
        not isinstance(observed_assignment, ast.Assign)
        or len(observed_assignment.targets) != 1
        or not isinstance(observed_assignment.targets[0], ast.Name)
        or observed_assignment.targets[0].id != "observed"
        or not isinstance(observed_assignment.value, ast.Call)
        or _python_attribute_path(observed_assignment.value.func)
        != ("_run_owned_process",)
        or len(observed_assignment.value.args) != 1
        or _python_attribute_path(observed_assignment.value.args[0])
        != ("command",)
        or {
            keyword.arg: ast.dump(keyword.value, include_attributes=False)
            for keyword in observed_assignment.value.keywords
            if keyword.arg is not None
        }
        != {
            "cwd": ast.dump(ast.parse("Path('/')", mode="eval").body, include_attributes=False),
            "environment": ast.dump(ast.Name(id="environment", ctx=ast.Load()), include_attributes=False),
            "pass_fds": ast.dump(ast.Tuple(elts=[], ctx=ast.Load()), include_attributes=False),
            "timeout": ast.dump(ast.Constant(value=300), include_attributes=False),
            "label": ast.dump(ast.Name(id="label", ctx=ast.Load()), include_attributes=False),
            "build": ast.dump(ast.Name(id="build", ctx=ast.Load()), include_attributes=False),
        }
    ):
        return False
    identity_calls = sorted(
        [
        node
        for node in ast.walk(permission_seal)
        if isinstance(node, ast.Call)
        and _python_attribute_path(node.func) == ("_exec_target_identity",)
        ],
        key=lambda call: (call.lineno, call.col_offset),
    )
    if (
        len(identity_calls) != 4
        or not all(call.lineno < observed_assignment.lineno for call in identity_calls[:2])
        or not all(call.lineno > observed_assignment.lineno for call in identity_calls[2:])
        or not exact_direct_guard(
            permission_seal,
            "not isinstance(observed, str) or expected_executables != ("
            "*_exec_target_identity(Path(command[0])), "
            "*_exec_target_identity(Path(command[2])))",
        )
        or len(
            [
                node
                for node in ast.walk(permission_seal)
                if isinstance(node, ast.Call)
                and _python_attribute_path(node.func) == ("verify_targets",)
            ]
        )
        != 3
        or not isinstance(command_try.finalbody[0], ast.For)
        or not isinstance(command_try.finalbody[0].target, ast.Name)
        or command_try.finalbody[0].target.id != "descriptor"
        or not isinstance(command_try.finalbody[0].iter, ast.Name)
        or command_try.finalbody[0].iter.id != "target_descriptors"
        or command_try.finalbody[0].orelse
        or any(
            isinstance(node, ast.Call)
            and _python_attribute_path(node.func)
            in {("subprocess", "Popen"), ("subprocess", "run")}
            for node in ast.walk(permission_seal)
        )
    ):
        return False

    def ordered_direct_pair(function: ast.FunctionDef) -> bool:
        parents = {
            child: parent
            for parent in ast.walk(function)
            for child in ast.iter_child_nodes(parent)
        }
        seals = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and _python_attribute_path(node.value.func)
            == ("_verify_reviewed_framework_seal",)
        ]
        cores = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and _python_attribute_path(node.value.func)
            == ("_verify_reviewed_framework_core",)
        ]
        return (
            len(seals) == 1
            and len(cores) == 1
            and parents.get(seals[0]) is parents.get(cores[0])
            and hasattr(parents.get(seals[0]), "body")
            and parents[seals[0]].body.index(seals[0])
            < parents[cores[0]].body.index(cores[0])
            and not _python_has_constant_false_ancestor(seals[0], parents)
            and not _python_has_constant_false_ancestor(cores[0], parents)
        )

    def exact_default_root_guard(function: ast.FunctionDef) -> bool:
        parents = {
            child: parent
            for parent in ast.walk(function)
            for child in ast.iter_child_nodes(parent)
        }
        comparisons = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Compare)
            and exact_expression(
                node,
                "PurePosixPath(install_root.as_posix()) "
                "!= DEFAULT_REVIEWED_FRAMEWORK_ROOT",
            )
        ]
        if len(comparisons) != 1:
            return False
        comparison = comparisons[0]
        child: ast.AST = comparison
        guard: ast.If | None = None
        while child in parents:
            parent = parents[child]
            if isinstance(parent, ast.If) and child in ast.walk(parent.test):
                guard = parent
                break
            child = parent
        return (
            guard is not None
            and isinstance(guard.test, ast.BoolOp)
            and isinstance(guard.test.op, ast.Or)
            and comparison in guard.test.values
            and len(guard.body) == 1
            and direct_toolchain_raise(guard.body[0])
            and not guard.orelse
            and not _python_has_constant_false_ancestor(guard, parents)
        )

    return (
        ordered_direct_pair(reviewed_installer)
        and ordered_direct_pair(install)
        and ordered_direct_pair(build_exact)
        and exact_default_root_guard(install)
        and exact_default_root_guard(build_exact)
    )


def _python_reviewed_framework_security_is_semantic(source: str) -> bool:
    """Require the post-provision framework proof without installer authority."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    forbidden = (
        "/usr/sbin/installer",
        "/usr/bin/sudo",
        "LAUNCHER_NAME_INSTALLER_REBIND",
        "LAUNCHER_NAME_INSTALLER_PENDING_SEAL",
        "installer-producer-rebind",
        "installer-produced-pending-seal",
        "_run_reviewed_framework_installer",
        "_seal_reviewed_framework_permissions",
        "REVIEWED_FRAMEWORK_PARENT_PERMISSION_COMMANDS",
        "REVIEWED_FRAMEWORK_PERMISSION_COMMANDS",
    )
    if any(marker in source for marker in forbidden):
        return False

    function_names = (
        "_reviewed_framework_security_contract",
        "_reviewed_framework_core_contract",
        "_reviewed_framework_owner",
        "_verify_locked_framework_regular",
        "_verify_reviewed_framework_acl_seal",
        "_verify_reviewed_framework_seal",
        "_verify_reviewed_framework_core",
        "install_reviewed_python",
        "build_with_exact_toolchain",
    )
    functions = {name: _python_function(tree, name) for name in function_names}
    if any(function is None for function in functions.values()):
        return False

    def exact_expression(node: ast.AST, expression: str) -> bool:
        expected = ast.parse(expression, mode="eval").body
        return ast.dump(node, include_attributes=False) == ast.dump(
            expected,
            include_attributes=False,
        )

    def direct_raise(statement: ast.stmt) -> bool:
        return (
            isinstance(statement, ast.Raise)
            and isinstance(statement.exc, ast.Call)
            and _python_attribute_path(statement.exc.func)
            == ("ToolchainBootstrapError",)
        )

    def exact_direct_guard_node(
        function: ast.FunctionDef,
        expression: str,
    ) -> ast.If | None:
        parents = {
            child: parent
            for parent in ast.walk(function)
            for child in ast.iter_child_nodes(parent)
        }
        guards = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.If) and exact_expression(node.test, expression)
        ]
        if (
            len(guards) == 1
            and len(guards[0].body) == 1
            and direct_raise(guards[0].body[0])
            and not guards[0].orelse
            and not _python_has_constant_false_ancestor(guards[0], parents)
        ):
            return guards[0]
        return None

    def exact_direct_guard(function: ast.FunctionDef, expression: str) -> bool:
        return exact_direct_guard_node(function, expression) is not None

    def exact_default_root_guard(function: ast.FunctionDef) -> bool:
        parents = {
            child: parent
            for parent in ast.walk(function)
            for child in ast.iter_child_nodes(parent)
        }
        comparisons = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Compare)
            and exact_expression(
                node,
                "PurePosixPath(install_root.as_posix()) "
                "!= DEFAULT_REVIEWED_FRAMEWORK_ROOT",
            )
        ]
        if len(comparisons) != 1:
            return False
        comparison = comparisons[0]
        child: ast.AST = comparison
        guard: ast.If | None = None
        while child in parents:
            parent = parents[child]
            if isinstance(parent, ast.If) and any(
                descendant is child for descendant in ast.walk(parent.test)
            ):
                guard = parent
                break
            child = parent
        return (
            guard is not None
            and isinstance(guard.test, ast.BoolOp)
            and isinstance(guard.test.op, ast.Or)
            and comparison in guard.test.values
            and len(guard.body) == 1
            and direct_raise(guard.body[0])
            and not guard.orelse
            and not _python_has_constant_false_ancestor(guard, parents)
        )

    default_roots = [
        statement
        for statement in tree.body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == "DEFAULT_REVIEWED_FRAMEWORK_ROOT"
    ]
    if (
        len(default_roots) != 1
        or not exact_expression(
            default_roots[0].value,
            "PurePosixPath('/Library/Frameworks/Python.framework/Versions/3.13')",
        )
        or source.count("_verify_reviewed_framework_seal(") != 4
        or source.count("_verify_reviewed_framework_core(") != 4
        or source.count("subprocess.run(") != 1
    ):
        return False

    owner = functions["_reviewed_framework_owner"]
    locked = functions["_verify_locked_framework_regular"]
    acl = functions["_verify_reviewed_framework_acl_seal"]
    seal = functions["_verify_reviewed_framework_seal"]
    core = functions["_verify_reviewed_framework_core"]
    install = functions["install_reviewed_python"]
    build_exact = functions["build_with_exact_toolchain"]
    assert owner is not None
    assert locked is not None
    assert acl is not None
    assert seal is not None
    assert core is not None
    assert install is not None
    assert build_exact is not None

    owner_body = [
        statement
        for statement in owner.body
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
    ]
    if (
        len(owner_body) != 1
        or not isinstance(owner_body[0], ast.Return)
        or not isinstance(owner_body[0].value, ast.Constant)
        or owner_body[0].value.value != 0
    ):
        return False

    locked_source = ast.get_source_segment(source, locked) or ""
    if any(
        marker not in locked_source
        for marker in (
            "os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC",
            "not stat.S_ISREG(held.st_mode)",
            "stat.S_ISLNK(named.st_mode)",
            "_identity(held) != _identity(named)",
            "held.st_uid != expected_owner",
            "held.st_nlink != 1",
            "held.st_size != expected_size",
            "stat.S_IMODE(held.st_mode) & 0o7022",
            "hashlib.sha256(payload).hexdigest() != expected_sha256",
            "_identity(os.fstat(descriptor)) != _identity(held)",
            "_identity(path.lstat()) != _identity(held)",
        )
    ):
        return False

    acl_source = ast.get_source_segment(source, acl) or ""
    acl_guard_expression = (
        "process.returncode != 0 or not process.stdout or process.stderr "
        "or len(process.stdout) > MAX_SUBPROCESS_OUTPUT_BYTES "
        "or acl_entry.search(process.stdout) is not None "
        "or expected != _exec_target_identity(Path(command[0]))"
    )
    if any(
        marker not in acl_source
        for marker in (
            "if sys.platform != \"darwin\":\n        return",
            '"/bin/ls",\n            "-led",',
            '("/bin/ls", "-leR", str(root))',
            're.compile(rb"(?m)^[ \\t]+[0-9]+: ")',
            "process = subprocess.run(",
            'cwd=Path("/")',
            'env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"}',
            "stdin=subprocess.DEVNULL",
            "stdout=subprocess.PIPE",
            "stderr=subprocess.PIPE",
            "timeout=120",
            "check=False",
            "start_new_session=True",
            "umask=0o077",
            "process.returncode != 0",
            "or not process.stdout",
            "or process.stderr",
            "len(process.stdout) > MAX_SUBPROCESS_OUTPUT_BYTES",
            "acl_entry.search(process.stdout) is not None",
            "expected != _exec_target_identity(Path(command[0]))",
        )
    ) or "shell=" in acl_source or not exact_direct_guard(
        acl,
        acl_guard_expression,
    ):
        return False

    seal_source = ast.get_source_segment(source, seal) or ""
    seal_markers = (
        "root_before = root.lstat()",
        "parent_before = root.parent.lstat()",
        "anchor_before = root.parents[1].lstat()",
        "container_before = root.parents[2].lstat()",
        "library_before = root.parents[3].lstat()",
        "stat.S_IMODE(root_before.st_mode) & 0o7022",
        "stat.S_IMODE(parent_before.st_mode) & 0o7022",
        "stat.S_IMODE(anchor_before.st_mode) & 0o7022",
        "stat.S_IMODE(container_before.st_mode) & 0o7022",
        "stat.S_IMODE(library_before.st_mode) & 0o7022",
        "followlinks=False",
        "part.casefold() for part in relative_path.parts",
        '"__pycache__" in folded_parts',
        'relative_path.name.casefold().endswith((".pyc", ".pyo"))',
        "root not in (unresolved, *unresolved.parents)",
        "root not in (resolved, *resolved.parents)",
        "mode & 0o7022",
        "not stat.S_ISREG(info.st_mode)",
        "info.st_nlink != 1 or info.st_size > MAX_TREE_FILE_BYTES",
        "total_size > MAX_TREE_TOTAL_BYTES",
        "observed_broken != broken",
        "_identity(root.lstat()) != _identity(root_before)",
        "_identity(root.parents[3].lstat()) != _identity(library_before)",
        "_verify_reviewed_framework_acl_seal(root)",
        "_verify_locked_framework_regular(",
    )
    if any(marker not in seal_source for marker in seal_markers):
        return False
    seal_parents = {
        child: parent
        for parent in ast.walk(seal)
        for child in ast.iter_child_nodes(parent)
    }
    acl_calls = [
        node
        for node in ast.walk(seal)
        if isinstance(node, ast.Call)
        and _python_attribute_path(node.func)
        == ("_verify_reviewed_framework_acl_seal",)
    ]
    locked_calls = [
        node
        for node in ast.walk(seal)
        if isinstance(node, ast.Call)
        and _python_attribute_path(node.func)
        == ("_verify_locked_framework_regular",)
    ]
    if (
        len(acl_calls) != 1
        or len(locked_calls) != 1
        or acl_calls[0].lineno >= locked_calls[0].lineno
        or _python_has_constant_false_ancestor(acl_calls[0], seal_parents)
        or _python_has_constant_false_ancestor(locked_calls[0], seal_parents)
        or not exact_direct_guard(
            seal,
            "'__pycache__' in folded_parts "
            "or relative_path.name.casefold().endswith(('.pyc', '.pyo'))",
        )
        or not exact_direct_guard(
            seal,
            "root not in (resolved, *resolved.parents)",
        )
        or not exact_direct_guard(
            seal,
            "not stat.S_ISREG(info.st_mode)",
        )
        or not exact_direct_guard(
            seal,
            "info.st_nlink != 1 or info.st_size > MAX_TREE_FILE_BYTES",
        )
        or not exact_direct_guard(
            seal,
            "_identity(root.lstat()) != _identity(root_before) "
            "or _identity(root.parent.lstat()) != _identity(parent_before) "
            "or _identity(root.parents[1].lstat()) != _identity(anchor_before) "
            "or _identity(root.parents[2].lstat()) != _identity(container_before) "
            "or _identity(root.parents[3].lstat()) != _identity(library_before)",
        )
    ):
        return False

    core_source = ast.get_source_segment(source, core) or ""
    if any(
        marker not in core_source
        for marker in (
            "exclusions, expected = _reviewed_framework_core_contract(python_lock)",
            "observed = build.fingerprint_install_root(",
            "reviewed_broken_symlinks=_reviewed_broken_framework_symlinks(",
            "excluded_paths=exclusions",
            "if observed != expected:",
        )
    ) or not exact_direct_guard(core, "observed != expected"):
        return False

    def relevant_call_sequence(function: ast.FunctionDef) -> list[str]:
        calls = sorted(
            (
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and _python_attribute_path(node.func)
                in {
                    ("_verify_reviewed_framework_seal",),
                    ("_verify_reviewed_framework_core",),
                    ("_run_owned_process",),
                }
            ),
            key=lambda node: (node.lineno, node.col_offset),
        )
        return [_python_attribute_path(node.func)[0] for node in calls]

    def verifier_pairs_are_direct(
        function: ast.FunctionDef,
        expected_pairs: int,
    ) -> bool:
        parents = {
            child: parent
            for parent in ast.walk(function)
            for child in ast.iter_child_nodes(parent)
        }
        calls = sorted(
            (
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and _python_attribute_path(node.value.func)
                in {
                    ("_verify_reviewed_framework_seal",),
                    ("_verify_reviewed_framework_core",),
                }
            ),
            key=lambda node: (node.lineno, node.col_offset),
        )
        if len(calls) != expected_pairs * 2:
            return False
        for index in range(0, len(calls), 2):
            seal_statement, core_statement = calls[index : index + 2]
            parent = parents.get(seal_statement)
            if (
                _python_attribute_path(seal_statement.value.func)
                != ("_verify_reviewed_framework_seal",)
                or _python_attribute_path(core_statement.value.func)
                != ("_verify_reviewed_framework_core",)
                or parent is not parents.get(core_statement)
                or not hasattr(parent, "body")
                or parent.body.index(core_statement)
                != parent.body.index(seal_statement) + 1
                or _python_has_constant_false_ancestor(seal_statement, parents)
                or _python_has_constant_false_ancestor(core_statement, parents)
            ):
                return False
        return True

    install_source = ast.get_source_segment(source, install) or ""
    active_guard = exact_direct_guard_node(install, "active_launcher != interpreter")
    install_parents = {
        child: parent
        for parent in ast.walk(install)
        for child in ast.iter_child_nodes(parent)
    }
    active_guard_parent = install_parents.get(active_guard) if active_guard else None
    active_guard_following: ast.stmt | None = None
    if active_guard is not None and hasattr(active_guard_parent, "body"):
        parent_body = active_guard_parent.body
        guard_index = parent_body.index(active_guard)
        if guard_index + 1 < len(parent_body):
            active_guard_following = parent_body[guard_index + 1]
    held_launcher_call = (
        active_guard_following.items[0].context_expr
        if isinstance(active_guard_following, ast.With)
        and len(active_guard_following.items) == 1
        and isinstance(active_guard_following.items[0].context_expr, ast.Call)
        else None
    )
    if (
        relevant_call_sequence(install)
        != [
            "_verify_reviewed_framework_seal",
            "_verify_reviewed_framework_core",
            "_run_owned_process",
            "_verify_reviewed_framework_seal",
            "_verify_reviewed_framework_core",
            "_run_owned_process",
        ]
        or not verifier_pairs_are_direct(install, 2)
        or active_guard is None
        or held_launcher_call is None
        or _python_attribute_path(held_launcher_call.func) != ("_held_executable",)
        or len(held_launcher_call.args) != 1
        or not isinstance(held_launcher_call.args[0], ast.Name)
        or held_launcher_call.args[0].id != "active_launcher"
        or not exact_default_root_guard(install)
        or any(
            marker not in install_source
            for marker in (
                "build.extract_reviewed_installer_package(",
                "if package.sha256 != package_sha256:",
                '"/usr/sbin/pkgutil",\n                                "--check-signature",',
                '"/usr/sbin/spctl",\n                                "--assess",',
                "with _held_executable(\n                    active_launcher,",
                "_revalidate_held_executable(\n                        old_launcher,",
                "with _held_executable(\n                        interpreter,",
                '(str(interpreter), "-I", "-S", "-c", observer)',
                "build.verify_python_install_binding(",
                "result = fingerprint",
                "PurePosixPath(install_root.as_posix())\n                != DEFAULT_REVIEWED_FRAMEWORK_ROOT",
            )
        )
    ):
        return False

    build_source = ast.get_source_segment(source, build_exact) or ""
    if (
        relevant_call_sequence(build_exact)[:2]
        != [
            "_verify_reviewed_framework_seal",
            "_verify_reviewed_framework_core",
        ]
        or not verifier_pairs_are_direct(build_exact, 1)
        or build_source.find("_verify_reviewed_framework_core(")
        >= build_source.find("active_python = Path(sys.executable).resolve(strict=True)")
        or "active_python != framework_python" not in build_source
        or not exact_default_root_guard(build_exact)
    ):
        return False
    return True


def _python_framework_fingerprint_exclusions_are_semantic(source: str) -> bool:
    """Require exact, ordered, non-overlapping framework fingerprint exclusions."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    fingerprint = _python_function(tree, "fingerprint_install_root")
    if fingerprint is None:
        return False

    def exact_expression(node: ast.AST, expression: str) -> bool:
        expected = ast.parse(expression, mode="eval").body
        return ast.dump(node, include_attributes=False) == ast.dump(
            expected,
            include_attributes=False,
        )

    def direct_build_raise(statement: ast.stmt, message: str) -> bool:
        return (
            isinstance(statement, ast.Raise)
            and isinstance(statement.exc, ast.Call)
            and _python_attribute_path(statement.exc.func) == ("BuildError",)
            and len(statement.exc.args) == 1
            and not statement.exc.keywords
            and isinstance(statement.exc.args[0], ast.Constant)
            and statement.exc.args[0].value == message
        )

    parents = {
        child: parent
        for parent in ast.walk(fingerprint)
        for child in ast.iter_child_nodes(parent)
    }
    exclusion_loops = [
        node
        for node in ast.walk(fingerprint)
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Name)
        and node.target.id == "raw_path"
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "excluded_paths"
        and not node.orelse
    ]
    order_guards = [
        node
        for node in ast.walk(fingerprint)
        if isinstance(node, ast.If)
        and exact_expression(
            node.test,
            "exclusion_names != sorted(exclusion_names) "
            "or len(exclusion_names) != len(set(exclusion_names))",
        )
    ]
    overlap_guards = [
        node
        for node in ast.walk(fingerprint)
        if isinstance(node, ast.If)
        and exact_expression(
            node.test,
            "any(candidate[:len(parent)] == parent "
            "for index, parent in enumerate(normalized_exclusions) "
            "for candidate in normalized_exclusions[index + 1:])",
        )
    ]
    applications = [
        node
        for node in ast.walk(fingerprint)
        if isinstance(node, ast.If)
        and exact_expression(
            node.test,
            "any(relative.parts[:len(excluded)] == excluded "
            "for excluded in normalized_exclusions)",
        )
        and len(node.body) == 1
        and isinstance(node.body[0], ast.Continue)
        and not node.orelse
    ]
    cache_applications = [
        node
        for node in ast.walk(fingerprint)
        if isinstance(node, ast.If)
        and exact_expression(
            node.test,
            "'__pycache__' in folded_parts "
            "or path.name.casefold().endswith(('.pyc', '.pyo'))",
        )
        and len(node.body) == 1
        and isinstance(node.body[0], ast.Continue)
        and not node.orelse
    ]
    selected = (
        *exclusion_loops,
        *order_guards,
        *overlap_guards,
        *applications,
        *cache_applications,
    )
    if (
        len(exclusion_loops) != 1
        or len(order_guards) != 1
        or len(overlap_guards) != 1
        or len(applications) != 1
        or len(cache_applications) != 1
        or not _python_exact_single_assignment(
            fingerprint,
            "folded_parts",
            "tuple(part.casefold() for part in relative.parts)",
        )
        or any(_python_has_constant_false_ancestor(node, parents) for node in selected)
        or any(
            len(node.body) != 1
            or not direct_build_raise(
                node.body[0],
                message,
            )
            or node.orelse
            for node, message in (
                (
                    order_guards[0],
                    "Python install root fingerprint exclusions are not ordered",
                ),
                (
                    overlap_guards[0],
                    "Python install root fingerprint exclusions overlap",
                ),
            )
        )
    ):
        return False
    source_block = ast.get_source_segment(source, fingerprint) or ""
    for marker in (
        "relative_path.is_absolute()",
        "relative_path.as_posix() != name",
        'any(part in {"", ".", ".."} for part in relative_path.parts)',
        '"\\\\" in name',
        '"\\x00" in name',
        "exclusion_names.append(name)",
        "normalized_exclusions.append(relative_path.parts)",
        'raise BuildError("Python install root fingerprint exclusion is unsafe")',
    ):
        if marker not in source_block:
            return False
    item_info_line = next(
        node.lineno
        for node in ast.walk(fingerprint)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "item_info"
            for target in node.targets
        )
    )
    return (
        applications[0].lineno < cache_applications[0].lineno < item_info_line
        and parents.get(applications[0]) is parents.get(cache_applications[0])
    )


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


def _python_attribute_path(node: ast.expr) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return (*_python_attribute_path(node.value), node.attr)
    return ()


def _python_name_arguments(call: ast.Call) -> tuple[str, ...]:
    if call.keywords or any(not isinstance(argument, ast.Name) for argument in call.args):
        return ()
    return tuple(argument.id for argument in call.args if isinstance(argument, ast.Name))


def _python_function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    return matches[0] if len(matches) == 1 else None


def _python_nested_function(
    function: ast.FunctionDef,
    name: str,
) -> ast.FunctionDef | None:
    matches = [
        node
        for node in function.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    return matches[0] if len(matches) == 1 else None


def _python_exact_single_assignment(
    function: ast.FunctionDef,
    target: str,
    expression: str,
) -> bool:
    stores = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Name)
        and node.id == target
        and isinstance(node.ctx, ast.Store)
    ]
    assignments = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == target
    ]
    expected = ast.parse(expression, mode="eval").body
    return (
        len(stores) == 1
        and len(assignments) == 1
        and ast.dump(assignments[0].value, include_attributes=False)
        == ast.dump(expected, include_attributes=False)
    )


def _python_rebinds_listing_primitives(function: ast.FunctionDef) -> bool:
    """Reject local or module-attribute rebinding of the exact tree listing."""

    protected_names = {"os", "sorted", "tuple"}
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Name)
            and node.id in protected_names
            and isinstance(node.ctx, (ast.Store, ast.Del))
        ):
            return True
        if isinstance(node, ast.arg) and node.arg in protected_names:
            return True
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node is not function
            and node.name in protected_names
        ):
            return True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound_name = alias.asname or alias.name.split(".", 1)[0]
                if bound_name in protected_names:
                    return True
        if (
            isinstance(node, ast.Attribute)
            and _python_attribute_path(node) == ("os", "listdir")
            and isinstance(node.ctx, (ast.Store, ast.Del))
        ):
            return True
    return False


def _python_direct_calls(
    function: ast.FunctionDef,
    path: tuple[str, ...],
) -> list[tuple[ast.Expr, ast.Call]]:
    return [
        (node, node.value)
        for node in ast.walk(function)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and _python_attribute_path(node.value.func) == path
    ]


def _python_compare_attribute_to_one(
    node: ast.expr,
    attribute: str,
) -> bool:
    return (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Attribute)
        and isinstance(node.left.value, ast.Name)
        and node.left.value.id == "before"
        and node.left.attr == attribute
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.NotEq)
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Constant)
        and node.comparators[0].value == 1
    )


def _python_stat_mode_predicate(node: ast.expr, name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and _python_attribute_path(node.func) == ("stat", name)
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], ast.Attribute)
        and isinstance(node.args[0].value, ast.Name)
        and node.args[0].value.id == "before"
        and node.args[0].attr == "st_mode"
    )


def _python_for_names(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.For)
        and isinstance(node.target, ast.Name)
        and node.target.id == "name"
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "names"
        and not node.orelse
    )


def _python_raise_message(statement: ast.stmt, message: str) -> bool:
    return (
        isinstance(statement, ast.Raise)
        and isinstance(statement.exc, ast.Call)
        and _python_attribute_path(statement.exc.func) == ("ToolchainBootstrapError",)
        and len(statement.exc.args) == 1
        and not statement.exc.keywords
        and isinstance(statement.exc.args[0], ast.Constant)
        and statement.exc.args[0].value == message
    )


def _python_literal_false(node: ast.expr) -> bool:
    try:
        return not bool(ast.literal_eval(node))
    except (ValueError, TypeError):
        return False


def _python_has_constant_false_ancestor(
    node: ast.AST,
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    child = node
    while child in parents:
        parent = parents[child]
        if (
            isinstance(parent, (ast.If, ast.While))
            and child in parent.body
            and _python_literal_false(parent.test)
        ):
            return True
        child = parent
    return False


def _python_outer_uv_capability_is_semantic(held_root: ast.With) -> bool:
    """Bind the held backend cwd through spawn, revalidation, and close."""

    def name(node: ast.AST | None, expected: str) -> bool:
        return isinstance(node, ast.Name) and node.id == expected

    def none(node: ast.AST | None) -> bool:
        return isinstance(node, ast.Constant) and node.value is None

    def assigned_name(statement: ast.stmt, target: str) -> ast.expr | None:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and name(statement.targets[0], target)
        ):
            return statement.value
        return None

    def annotated_none(statement: ast.stmt, target: str) -> bool:
        return (
            isinstance(statement, ast.AnnAssign)
            and statement.simple == 1
            and name(statement.target, target)
            and none(statement.value)
        )

    def identity_test(node: ast.expr, target: str, *, negate: bool) -> bool:
        return (
            isinstance(node, ast.Compare)
            and name(node.left, target)
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.IsNot if negate else ast.Is)
            and len(node.comparators) == 1
            and none(node.comparators[0])
        )

    def exception_assignment(
        handler: ast.ExceptHandler,
        exception: str,
        target: str,
        value: str,
    ) -> bool:
        return (
            name(handler.type, exception)
            and handler.name == "exc"
            and len(handler.body) == 1
            and name(assigned_name(handler.body[0], target), value)
        )

    def error_raise(statement: ast.stmt, cause: str) -> bool:
        return (
            isinstance(statement, ast.Raise)
            and isinstance(statement.exc, ast.Call)
            and _python_attribute_path(statement.exc.func)
            == ("ToolchainBootstrapError",)
            and name(statement.cause, cause)
        )

    openings = [
        (offset, statement)
        for offset, statement in enumerate(held_root.body)
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Tuple)
            and tuple(
                element.id
                for element in statement.targets[0].elts
                if isinstance(element, ast.Name)
            )
            == ("backend_fd", "backend_identity")
            and len(statement.targets[0].elts) == 2
            and isinstance(statement.value, ast.Call)
            and _python_attribute_path(statement.value.func)
            == ("_open_held_source_directory",)
            and len(statement.value.args) == 2
            and name(statement.value.args[0], "source")
            and isinstance(statement.value.args[1], ast.Constant)
            and statement.value.args[1].value == "backend"
            and not statement.value.keywords
        )
    ]
    if len(openings) != 1:
        return False
    start, _opening = openings[0]
    if start + 9 > len(held_root.body):
        return False
    block = held_root.body[start : start + 9]
    if (
        not annotated_none(block[1], "runtime_text")
        or not annotated_none(block[2], "runtime_error")
        or not isinstance(block[3], ast.Try)
        or not annotated_none(block[4], "capability_error")
        or not isinstance(block[5], ast.With)
        or not isinstance(block[6], ast.If)
        or not isinstance(block[7], ast.If)
        or not isinstance(block[8], ast.If)
    ):
        return False

    runtime_try = block[3]
    assert isinstance(runtime_try, ast.Try)
    if (
        len(runtime_try.body) != 1
        or runtime_try.orelse
        or runtime_try.finalbody
        or len(runtime_try.handlers) != 1
    ):
        return False
    runtime_call = assigned_name(runtime_try.body[0], "runtime_text")
    if (
        not isinstance(runtime_call, ast.Call)
        or _python_attribute_path(runtime_call.func) != ("_run_owned_process",)
        or any(keyword.arg is None for keyword in runtime_call.keywords)
        or {
            keyword.arg: _python_attribute_path(keyword.value)
            for keyword in runtime_call.keywords
            if keyword.arg in {"cwd_descriptor", "launcher_python"}
        }
        != {
            "cwd_descriptor": ("backend_fd",),
            "launcher_python": ("bootstrap_python",),
        }
        or not exception_assignment(
            runtime_try.handlers[0],
            "BaseException",
            "runtime_error",
            "exc",
        )
    ):
        return False

    cleanup_with = block[5]
    assert isinstance(cleanup_with, ast.With)
    if (
        len(cleanup_with.items) != 1
        or not isinstance(cleanup_with.items[0].context_expr, ast.Call)
        or _python_attribute_path(cleanup_with.items[0].context_expr.func)
        != ("build", "_defer_publish_signals")
        or cleanup_with.items[0].context_expr.args
        or len(cleanup_with.items[0].context_expr.keywords) != 1
        or cleanup_with.items[0].context_expr.keywords[0].arg != "preserve_error"
        or not name(
            cleanup_with.items[0].context_expr.keywords[0].value,
            "runtime_error",
        )
        or len(cleanup_with.body) != 2
        or any(not isinstance(statement, ast.Try) for statement in cleanup_with.body)
    ):
        return False
    revalidate_try, close_try = cleanup_with.body
    assert isinstance(revalidate_try, ast.Try)
    assert isinstance(close_try, ast.Try)
    if (
        len(revalidate_try.body) != 1
        or revalidate_try.orelse
        or revalidate_try.finalbody
        or len(revalidate_try.handlers) != 1
        or not isinstance(revalidate_try.body[0], ast.Expr)
        or not isinstance(revalidate_try.body[0].value, ast.Call)
        or _python_attribute_path(revalidate_try.body[0].value.func)
        != ("_revalidate_held_source_directory",)
        or len(revalidate_try.body[0].value.args) != 4
        or not name(revalidate_try.body[0].value.args[0], "source")
        or not isinstance(revalidate_try.body[0].value.args[1], ast.Constant)
        or revalidate_try.body[0].value.args[1].value != "backend"
        or not name(revalidate_try.body[0].value.args[2], "backend_fd")
        or not name(revalidate_try.body[0].value.args[3], "backend_identity")
        or revalidate_try.body[0].value.keywords
        or not exception_assignment(
            revalidate_try.handlers[0],
            "BaseException",
            "capability_error",
            "exc",
        )
        or len(close_try.body) != 1
        or close_try.orelse
        or close_try.finalbody
        or len(close_try.handlers) != 1
        or not isinstance(close_try.body[0], ast.Expr)
        or not isinstance(close_try.body[0].value, ast.Call)
        or _python_attribute_path(close_try.body[0].value.func) != ("os", "close")
        or _python_name_arguments(close_try.body[0].value) != ("backend_fd",)
    ):
        return False
    close_handler = close_try.handlers[0]
    close_value = (
        assigned_name(close_handler.body[0], "capability_error")
        if len(close_handler.body) == 1
        else None
    )
    if (
        not name(close_handler.type, "OSError")
        or close_handler.name != "exc"
        or not isinstance(close_value, ast.BoolOp)
        or not isinstance(close_value.op, ast.Or)
        or len(close_value.values) != 2
        or not name(close_value.values[0], "capability_error")
        or not name(close_value.values[1], "exc")
    ):
        return False

    capability_if = block[6]
    runtime_if = block[7]
    text_if = block[8]
    assert isinstance(capability_if, ast.If)
    assert isinstance(runtime_if, ast.If)
    assert isinstance(text_if, ast.If)
    return (
        identity_test(capability_if.test, "capability_error", negate=True)
        and not capability_if.orelse
        and len(capability_if.body) == 2
        and isinstance(capability_if.body[0], ast.If)
        and identity_test(
            capability_if.body[0].test,
            "runtime_error",
            negate=True,
        )
        and not capability_if.body[0].orelse
        and len(capability_if.body[0].body) == 1
        and error_raise(capability_if.body[0].body[0], "runtime_error")
        and error_raise(capability_if.body[1], "capability_error")
        and identity_test(runtime_if.test, "runtime_error", negate=True)
        and not runtime_if.orelse
        and len(runtime_if.body) == 1
        and isinstance(runtime_if.body[0], ast.Raise)
        and name(runtime_if.body[0].exc, "runtime_error")
        and runtime_if.body[0].cause is None
        and identity_test(text_if.test, "runtime_text", negate=False)
        and not text_if.orelse
        and len(text_if.body) == 1
        and isinstance(text_if.body[0], ast.Raise)
        and isinstance(text_if.body[0].exc, ast.Call)
        and _python_attribute_path(text_if.body[0].exc.func)
        == ("ToolchainBootstrapError",)
        and text_if.body[0].cause is None
        and [
            (offset, type(statement))
            for offset, statement in enumerate(held_root.body[:-1])
            if not isinstance(statement, (ast.Assign, ast.AnnAssign, ast.Expr))
        ]
        == [
            (start + 3, ast.Try),
            (start + 5, ast.With),
            (start + 6, ast.If),
            (start + 7, ast.If),
            (start + 8, ast.If),
        ]
    )


def _python_final_bundle_verifier_is_semantic(source: str) -> bool:
    """Bind both final audits to the pathname currently being published."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    implementation = _python_function(tree, "_build_python_sidecar_impl")
    held_verifier = _python_function(tree, "_verify_held_bundle_candidate")
    if implementation is None or held_verifier is None:
        return False
    verifiers = [
        node
        for node in ast.walk(implementation)
        if isinstance(node, ast.FunctionDef) and node.name == "final_verifier"
    ]
    if len(verifiers) != 1:
        return False
    verifier = verifiers[0]
    if (
        len(verifier.args.posonlyargs) != 0
        or len(verifier.args.args) != 1
        or verifier.args.args[0].arg != "candidate"
        or verifier.args.vararg is not None
        or verifier.args.kwonlyargs
        or verifier.args.kwarg is not None
        or verifier.args.defaults
        or len(verifier.body) != 8
        or any(
            isinstance(node, ast.Name)
            and node.id == "candidate"
            and isinstance(node.ctx, (ast.Store, ast.Del))
            for node in ast.walk(verifier)
        )
    ):
        return False

    def expression_call(
        statement: ast.stmt,
        path: tuple[str, ...],
        arguments: tuple[str, ...],
    ) -> ast.Call | None:
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and _python_attribute_path(statement.value.func) == path
            and tuple(
                argument.id
                for argument in statement.value.args
                if isinstance(argument, ast.Name)
            )
            == arguments
            and len(statement.value.args) == len(arguments)
        ):
            return statement.value
        return None

    def exact_no_keyword_call(
        statement: ast.stmt,
        path: tuple[str, ...],
        arguments: tuple[str, ...],
    ) -> bool:
        call = expression_call(statement, path, arguments)
        return call is not None and not call.keywords

    first_held = expression_call(
        verifier.body[3],
        ("_verify_held_bundle_candidate",),
        ("bundle_capability", "candidate"),
    )
    second_held = expression_call(
        verifier.body[5],
        ("_verify_held_bundle_candidate",),
        ("bundle_capability", "candidate"),
    )
    held_calls = (first_held, second_held)
    if any(
        call is None
        or len(call.keywords) != 1
        or call.keywords[0].arg != "error_message"
        or not isinstance(call.keywords[0].value, ast.Constant)
        or call.keywords[0].value.value
        != "Python sidecar bundle changed during final audit"
        for call in held_calls
    ):
        return False
    audit_value = (
        verifier.body[4].value
        if isinstance(verifier.body[4], ast.Assign)
        and len(verifier.body[4].targets) == 1
        and isinstance(verifier.body[4].targets[0], ast.Name)
        and verifier.body[4].targets[0].id == "result"
        and isinstance(verifier.body[4].value, ast.Call)
        else None
    )
    audit_keywords = (
        {keyword.arg: keyword.value for keyword in audit_value.keywords}
        if isinstance(audit_value, ast.Call)
        and all(keyword.arg is not None for keyword in audit_value.keywords)
        else {}
    )
    native_scanner = audit_keywords.get("native_scanner")
    native_body = (
        native_scanner.body
        if isinstance(native_scanner, ast.Lambda)
        and len(native_scanner.args.args) == 1
        and native_scanner.args.args[0].arg == "native_root"
        and native_scanner.args.vararg is None
        and native_scanner.args.kwarg is None
        and not native_scanner.args.kwonlyargs
        else None
    )
    native_root_descriptor = (
        native_body.keywords[0].value
        if isinstance(native_body, ast.Call)
        and _python_attribute_path(native_body.func)
        == ("audit", "scan_macho_inventory")
        and len(native_body.args) == 1
        and isinstance(native_body.args[0], ast.Name)
        and native_body.args[0].id == "native_root"
        and len(native_body.keywords) == 1
        and native_body.keywords[0].arg == "root_descriptor"
        else None
    )
    if (
        not exact_no_keyword_call(
            verifier.body[0],
            ("verify_exact_toolchain",),
            (),
        )
        or not exact_no_keyword_call(
            verifier.body[1],
            ("verify_repository_provenance",),
            ("release",),
        )
        or not exact_no_keyword_call(
            verifier.body[2],
            ("_validate_source_snapshot",),
            ("scratch",),
        )
        or not isinstance(audit_value, ast.Call)
        or _python_attribute_path(audit_value.func) != ("audit", "audit_bundle")
        or len(audit_value.args) != 1
        or not isinstance(audit_value.args[0], ast.Name)
        or audit_value.args[0].id != "candidate"
        or set(audit_keywords)
        != {"native_scanner", "repository_root", "verify_git_provenance"}
        or not isinstance(audit_keywords.get("repository_root"), ast.Name)
        or audit_keywords["repository_root"].id != "source_root"
        or not isinstance(
            audit_keywords.get("verify_git_provenance"),
            ast.Constant,
        )
        or audit_keywords["verify_git_provenance"].value is not False
        or _python_attribute_path(native_root_descriptor)
        != ("bundle_capability", "descriptor")
        or not exact_no_keyword_call(
            verifier.body[6],
            ("verify_exact_toolchain",),
            (),
        )
        or not isinstance(verifier.body[7], ast.Return)
        or not isinstance(verifier.body[7].value, ast.Name)
        or verifier.body[7].value.id != "result"
    ):
        return False

    held_arguments = (
        *held_verifier.args.posonlyargs,
        *held_verifier.args.args,
    )
    held_returns = [
        node
        for node in ast.walk(held_verifier)
        if isinstance(node, ast.Return)
    ]
    held_calls_by_path = {
        path: [
            node
            for node in ast.walk(held_verifier)
            if isinstance(node, ast.Call)
            and _python_attribute_path(node.func) == path
        ]
        for path in (
            ("_verify_held_bundle_tree",),
            ("candidate", "is_absolute"),
            ("candidate", "lstat"),
            ("os", "open"),
        )
    }
    open_calls = held_calls_by_path[("os", "open")]
    return (
        tuple(argument.arg for argument in held_arguments) == ("bundle", "candidate")
        and tuple(argument.arg for argument in held_verifier.args.kwonlyargs)
        == ("error_message",)
        and held_verifier.args.vararg is None
        and held_verifier.args.kwarg is None
        and not held_verifier.args.defaults
        and held_verifier.args.kw_defaults[0] is None
        and len(held_calls_by_path[("_verify_held_bundle_tree",)]) == 1
        and len(held_calls_by_path[("candidate", "is_absolute")]) == 1
        and len(held_calls_by_path[("candidate", "lstat")]) == 1
        and len(open_calls) == 1
        and len(open_calls[0].args) == 2
        and isinstance(open_calls[0].args[0], ast.Name)
        and open_calls[0].args[0].id == "candidate"
        and "O_NOFOLLOW" in ast.unparse(open_calls[0].args[1])
        and len(held_returns) == 1
        and isinstance(held_returns[0].value, ast.Name)
        and held_returns[0].value.id == "candidate"
        and not any(
            isinstance(node, ast.Name)
            and node.id == "candidate"
            and isinstance(node.ctx, (ast.Store, ast.Del))
            for node in ast.walk(held_verifier)
        )
    )


def _python_repository_gate_is_semantic(source: str) -> bool:
    """Bind every Git consumer to the held repository and .git descriptors."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    gate = _python_function(tree, "_validate_repository_state")
    if gate is None:
        return False

    def calls(path: tuple[str, ...]) -> list[ast.Call]:
        return [
            node
            for node in ast.walk(gate)
            if isinstance(node, ast.Call)
            and _python_attribute_path(node.func) == path
        ]

    def keywords(call: ast.Call) -> dict[str, ast.expr]:
        if any(keyword.arg is None for keyword in call.keywords):
            return {}
        return {str(keyword.arg): keyword.value for keyword in call.keywords}

    def name(value: ast.expr | None, expected: str) -> bool:
        return isinstance(value, ast.Name) and value.id == expected

    local_calls = calls(("_validate_local_git_configuration",))
    index_calls = calls(("_validate_git_index",))
    worktree_calls = calls(("_validate_tracked_worktree",))
    nested = [
        node
        for node in ast.walk(gate)
        if isinstance(node, ast.FunctionDef) and node.name == "git_output"
    ]
    if (
        len(local_calls) != 1
        or len(index_calls) != 1
        or len(worktree_calls) != 1
        or len(nested) != 1
    ):
        return False
    local_keywords = keywords(local_calls[0])
    index_keywords = keywords(index_calls[0])
    worktree_keywords = keywords(worktree_calls[0])
    if (
        local_calls[0].args
        or set(local_keywords)
        != {"repository_root", "repository_descriptor", "git_descriptor"}
        or not name(local_keywords.get("repository_root"), "repository_root")
        or not name(
            local_keywords.get("repository_descriptor"),
            "repository_descriptor",
        )
        or not name(local_keywords.get("git_descriptor"), "git_descriptor")
        or len(index_calls[0].args) != 1
        or not name(index_calls[0].args[0], "inventory")
        or set(index_keywords)
        != {"repository_root", "repository_descriptor", "git_descriptor"}
        or not name(index_keywords.get("repository_root"), "repository_root")
        or not name(
            index_keywords.get("repository_descriptor"),
            "repository_descriptor",
        )
        or not name(index_keywords.get("git_descriptor"), "git_descriptor")
        or len(worktree_calls[0].args) != 1
        or not name(worktree_calls[0].args[0], "inventory")
        or set(worktree_keywords)
        != {"repository_root", "repository_descriptor"}
        or not name(
            worktree_keywords.get("repository_root"),
            "repository_root",
        )
        or not name(
            worktree_keywords.get("repository_descriptor"),
            "repository_descriptor",
        )
    ):
        return False

    git_calls = [
        node
        for node in ast.walk(nested[0])
        if isinstance(node, ast.Call)
        and _python_attribute_path(node.func) == ("_git_output",)
    ]
    if len(git_calls) != 1:
        return False
    git_keywords = keywords(git_calls[0])
    if (
        set(git_keywords)
        != {"repository_root", "repository_descriptor", "git_descriptor"}
        or not name(git_keywords.get("repository_root"), "repository_root")
        or not name(
            git_keywords.get("repository_descriptor"),
            "repository_descriptor",
        )
        or not name(git_keywords.get("git_descriptor"), "git_descriptor")
    ):
        return False

    git_output_calls = calls(("git_output",))
    arguments = [
        tuple(
            item.value
            for item in call.args
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        )
        for call in git_output_calls
    ]
    return (
        ("status", "--porcelain=v2", "--untracked-files=all") in arguments
        and ("submodule", "status", "--recursive") in arguments
        and not any(values and values[0] == "write-tree" for values in arguments)
    )


def _python_producer_privatization_is_semantic(source: str) -> bool:
    """Validate executable AST structure beyond reviewed text/hash markers."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    parents: dict[ast.AST, ast.AST] = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    build_toolchain = _python_function(tree, "build_with_exact_toolchain")
    materializer = _python_function(tree, "_materialize_private_regular_file")
    privatizer = _python_function(tree, "_privatize_installed_tree")
    inventory = _python_function(tree, "_inventory_installed_tree")
    chmod_tree = _python_function(tree, "_chmod_installed_tree_read_only")
    if any(
        function is None
        for function in (
            build_toolchain,
            materializer,
            privatizer,
            inventory,
            chmod_tree,
        )
    ):
        return False
    assert build_toolchain is not None
    assert materializer is not None
    assert privatizer is not None
    assert inventory is not None
    assert chmod_tree is not None
    protected_callables = {
        "_privatize_installed_tree",
        "seal_installed_tree",
        "_run_owned_process",
    }
    if any(
        isinstance(node, ast.Name)
        and node.id in protected_callables
        and isinstance(node.ctx, (ast.Store, ast.Del))
        for node in ast.walk(build_toolchain)
    ):
        return False
    privatizer_visit = _python_nested_function(privatizer, "visit")
    inventory_visit_function = _python_nested_function(inventory, "visit")
    if (
        privatizer_visit is None
        or inventory_visit_function is None
        or _python_rebinds_listing_primitives(privatizer)
        or _python_rebinds_listing_primitives(inventory)
        or _python_rebinds_listing_primitives(chmod_tree)
        or not _python_exact_single_assignment(
            privatizer_visit,
            "names",
            "tuple(sorted(os.listdir(directory_descriptor)))",
        )
        or not _python_exact_single_assignment(
            inventory_visit_function,
            "names",
            "tuple(sorted(os.listdir(directory_descriptor)))",
        )
        or not _python_exact_single_assignment(
            chmod_tree,
            "names",
            "tuple(sorted(os.listdir(descriptor)))",
        )
    ):
        return False

    production_calls = _python_direct_calls(
        build_toolchain,
        ("_privatize_installed_tree",),
    )
    if (
        len(production_calls) != 2
        or {
            _python_name_arguments(call)
            for statement, call in production_calls
            if not _python_has_constant_false_ancestor(statement, parents)
        }
        != {
            ("bootstrap_root", "bootstrap_fd", "build"),
            ("build_root", "build_fd", "build"),
        }
    ):
        return False
    for statement, _call in production_calls:
        held_root_with = parents.get(statement)
        translated_cleanup_with = parents.get(held_root_with)
        enclosing_try = parents.get(translated_cleanup_with)
        if (
            not isinstance(held_root_with, ast.With)
            or len(held_root_with.items) != 1
            or not isinstance(held_root_with.items[0].context_expr, ast.Call)
            or _python_attribute_path(held_root_with.items[0].context_expr.func)
            != ("_held_toolchain_root",)
            or _python_name_arguments(held_root_with.items[0].context_expr)
            != ("runner_temp", "build")
            or not isinstance(translated_cleanup_with, ast.With)
            or len(translated_cleanup_with.items) != 1
            or not isinstance(
                translated_cleanup_with.items[0].context_expr,
                ast.Call,
            )
            or _python_attribute_path(
                translated_cleanup_with.items[0].context_expr.func
            )
            != ("build", "_translate_cleanup_signals")
            or translated_cleanup_with.items[0].context_expr.args
            or translated_cleanup_with.items[0].context_expr.keywords
            or not isinstance(enclosing_try, ast.Try)
            or parents.get(enclosing_try) is not build_toolchain
        ):
            return False
    held_root_bodies = {parents[statement] for statement, _call in production_calls}
    if len(held_root_bodies) != 1:
        return False
    held_root_body = next(iter(held_root_bodies))
    assert isinstance(held_root_body, ast.With)
    if (
        not held_root_body.body
        or not isinstance(held_root_body.body[-1], ast.Return)
        or not _python_outer_uv_capability_is_semantic(held_root_body)
    ):
        return False
    for statement, call in production_calls:
        offset = held_root_body.body.index(statement)
        call_arguments = _python_name_arguments(call)
        if call_arguments == ("bootstrap_root", "bootstrap_fd", "build"):
            expected_label = "Hash-locked Python bootstrap install"
            expected_seal_name = "bootstrap_seal"
            expected_seal_offset = offset + 2
            reviewed_root = held_root_body.body[offset + 1]
            if (
                not isinstance(reviewed_root, ast.Assign)
                or len(reviewed_root.targets) != 1
                or not isinstance(reviewed_root.targets[0], ast.Name)
                or reviewed_root.targets[0].id != "reviewed_framework_root"
                or not isinstance(reviewed_root.value, ast.Call)
                or _python_attribute_path(reviewed_root.value.func)
                != ("PurePosixPath",)
            ):
                return False
        else:
            expected_label = "Complete hash-locked Python build install"
            expected_seal_name = "installed_seal"
            expected_seal_offset = offset + 1
        previous = held_root_body.body[offset - 1] if offset else None
        previous_call = (
            previous.value
            if isinstance(previous, ast.Expr)
            and isinstance(previous.value, ast.Call)
            else None
        )
        previous_keywords = {
            keyword.arg: keyword.value
            for keyword in previous_call.keywords
            if keyword.arg is not None
        } if previous_call is not None else {}
        if (
            offset == 0
            or previous_call is None
            or _python_attribute_path(previous_call.func) != ("_run_owned_process",)
            or not isinstance(previous_keywords.get("label"), ast.Constant)
            or previous_keywords["label"].value != expected_label
        ):
            return False
        if expected_seal_offset >= len(held_root_body.body):
            return False
        seal_statement = held_root_body.body[expected_seal_offset]
        if (
            not isinstance(seal_statement, ast.Assign)
            or len(seal_statement.targets) != 1
            or not isinstance(seal_statement.targets[0], ast.Name)
            or seal_statement.targets[0].id != expected_seal_name
            or not isinstance(seal_statement.value, ast.Call)
            or _python_attribute_path(seal_statement.value.func)
            != ("seal_installed_tree",)
            or tuple(
                argument.id
                for argument in seal_statement.value.args
                if isinstance(argument, ast.Name)
            )
            != call_arguments[:2]
            or len(seal_statement.value.args) != 2
            or len(seal_statement.value.keywords) != 1
            or seal_statement.value.keywords[0].arg != "reviewed_framework_root"
            or not isinstance(seal_statement.value.keywords[0].value, ast.Name)
            or seal_statement.value.keywords[0].value.id
            != "reviewed_framework_root"
        ):
            return False

    exchange_calls = _python_direct_calls(
        materializer,
        ("build", "_exchange_at"),
    )
    if (
        len(exchange_calls) != 1
        or _python_name_arguments(exchange_calls[0][1])
        != (
            "directory_descriptor",
            "name",
            "directory_descriptor",
            "private_name",
        )
        or _python_has_constant_false_ancestor(exchange_calls[0][0], parents)
    ):
        return False
    exchange_parent = parents.get(exchange_calls[0][0])
    if (
        not isinstance(exchange_parent, ast.With)
        or len(exchange_parent.items) != 1
        or not isinstance(exchange_parent.items[0].context_expr, ast.Call)
        or _python_attribute_path(exchange_parent.items[0].context_expr.func)
        != ("build", "_defer_publish_signals")
        or exchange_parent.items[0].context_expr.args
        or exchange_parent.items[0].context_expr.keywords
        or not isinstance(parents.get(exchange_parent), ast.Try)
        or parents.get(parents.get(exchange_parent)) is not materializer
    ):
        return False

    hardlink_branches = [
        node
        for node in ast.walk(privatizer)
        if isinstance(node, ast.If)
        and _python_compare_attribute_to_one(node.test, "st_nlink")
    ]
    if len(hardlink_branches) != 1:
        return False
    hardlink_branch = hardlink_branches[0]
    writable_guards = [
        statement
        for statement in hardlink_branch.body
        if isinstance(statement, ast.If)
        and isinstance(statement.test, ast.BinOp)
        and isinstance(statement.test.left, ast.Name)
        and statement.test.left.id == "mode"
        and isinstance(statement.test.op, ast.BitAnd)
        and isinstance(statement.test.right, ast.Constant)
        and statement.test.right.value == 0o022
    ]
    hardlink_materializations = [
        statement.value
        for statement in hardlink_branch.body
        if isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and _python_attribute_path(statement.value.func)
        == ("_materialize_private_regular_file",)
    ]
    if (
        len(writable_guards) != 1
        or len(writable_guards[0].body) != 1
        or not _python_raise_message(
            writable_guards[0].body[0],
            "Installed toolchain producer hardlink is writable",
        )
        or len(hardlink_materializations) != 1
        or _python_name_arguments(hardlink_materializations[0])
        != (
            "directory_descriptor",
            "name",
            "before",
            "desired_mode",
            "build",
        )
    ):
        return False

    inventory_regular_guards = [
        node
        for node in ast.walk(inventory)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.BoolOp)
        and isinstance(node.test.op, ast.Or)
        and any(
            _python_compare_attribute_to_one(value, "st_nlink")
            for value in node.test.values
        )
        and len(node.body) == 1
        and _python_raise_message(
            node.body[0],
            "Installed toolchain file is unsafe",
        )
    ]
    inventory_symlink_guards = [
        node
        for node in ast.walk(inventory)
        if isinstance(node, ast.If)
        and _python_compare_attribute_to_one(node.test, "st_nlink")
        and len(node.body) == 1
        and _python_raise_message(
            node.body[0],
            "Installed toolchain symlink is unsafe",
        )
    ]
    chmod_hardlink_guards = [
        node
        for node in ast.walk(chmod_tree)
        if isinstance(node, ast.If)
        and _python_compare_attribute_to_one(node.test, "st_nlink")
        and len(node.body) == 1
        and _python_raise_message(
            node.body[0],
            "Installed toolchain hardlink is forbidden",
        )
    ]
    if (
        len(inventory_regular_guards) != 1
        or len(inventory_symlink_guards) != 1
        or len(chmod_hardlink_guards) != 1
    ):
        return False

    inventory_regular_branch = parents.get(inventory_regular_guards[0])
    inventory_regular_loop = parents.get(inventory_regular_branch)
    inventory_visit = parents.get(inventory_regular_loop)
    if (
        not isinstance(inventory_regular_branch, ast.If)
        or not _python_stat_mode_predicate(
            inventory_regular_branch.test,
            "S_ISREG",
        )
        or not _python_for_names(inventory_regular_loop)
        or not isinstance(inventory_visit, ast.FunctionDef)
        or inventory_visit.name != "visit"
        or inventory_visit is not inventory_visit_function
        or parents.get(inventory_visit) is not inventory
        or len(inventory_regular_loop.body) != 11
        or inventory_regular_loop.body[7] is not inventory_regular_branch
        or not inventory_regular_branch.body
        or inventory_regular_branch.body[0] is not inventory_regular_guards[0]
    ):
        return False

    inventory_symlink_branch = parents.get(inventory_symlink_guards[0])
    inventory_directory_branch = parents.get(inventory_symlink_branch)
    inventory_regular_parent = parents.get(inventory_directory_branch)
    inventory_symlink_loop = parents.get(inventory_regular_parent)
    if (
        not isinstance(inventory_symlink_branch, ast.If)
        or not _python_stat_mode_predicate(
            inventory_symlink_branch.test,
            "S_ISLNK",
        )
        or not isinstance(inventory_directory_branch, ast.If)
        or not isinstance(inventory_directory_branch.test, ast.BoolOp)
        or not isinstance(inventory_directory_branch.test.op, ast.And)
        or len(inventory_directory_branch.test.values) != 2
        or not _python_stat_mode_predicate(
            inventory_directory_branch.test.values[0],
            "S_ISDIR",
        )
        or not isinstance(
            inventory_directory_branch.test.values[1],
            ast.UnaryOp,
        )
        or not isinstance(
            inventory_directory_branch.test.values[1].op,
            ast.Not,
        )
        or not _python_stat_mode_predicate(
            inventory_directory_branch.test.values[1].operand,
            "S_ISLNK",
        )
        or inventory_regular_parent is not inventory_regular_branch
        or inventory_regular_branch.orelse != [inventory_directory_branch]
        or inventory_directory_branch.orelse != [inventory_symlink_branch]
        or not inventory_symlink_branch.body
        or inventory_symlink_branch.body[0] is not inventory_symlink_guards[0]
        or not _python_for_names(inventory_symlink_loop)
        or parents.get(inventory_symlink_loop) is not inventory_visit
    ):
        return False

    chmod_regular_branch = parents.get(chmod_hardlink_guards[0])
    chmod_loop = parents.get(chmod_regular_branch)
    chmod_try = parents.get(chmod_loop)
    if (
        not isinstance(chmod_regular_branch, ast.If)
        or not _python_stat_mode_predicate(
            chmod_regular_branch.test,
            "S_ISREG",
        )
        or not _python_for_names(chmod_loop)
        or len(chmod_loop.body) != 2
        or chmod_loop.body[1] is not chmod_regular_branch
        or len(chmod_regular_branch.body) < 2
        or chmod_regular_branch.body[1] is not chmod_hardlink_guards[0]
        or not isinstance(chmod_try, ast.Try)
        or parents.get(chmod_try) is not chmod_tree
    ):
        return False
    return True


def _reviewed_framework_node_verifier_is_semantic(
    source: str,
    tests: str,
) -> bool:
    exact_exclusions = (
        "Resources/English.lproj/Documentation",
        "bin/pip",
        "bin/pip3",
        "bin/pip3.13",
        "bin/python",
        "bin/python313",
        "etc/openssl/cert.pem",
        "lib/python3.13/site-packages",
        "share/doc/python3.13/html",
    )
    required_source_markers = (
        'const EXACT_ROOT = "/Library/Frameworks/Python.framework/Versions/3.13";',
        '  "ba58cfb559f29c34beb962cb5d88587e9104f5610c255a58494c2945c1e863ec";',
        "const CORE_EXCLUDED_PATHS = Object.freeze([",
        'const SITE_PACKAGES_PATH = "lib/python3.13/site-packages";',
        "const ABSENT_PRODUCTION_EXCLUSIONS = Object.freeze(",
        "const SITE_PACKAGES_README = Object.freeze({",
        "  size: 119,",
        '  sha256: "cba8fece8f62c36306ba27a128f124a257710e41fc619301ee97be93586917cb",',
        "const REVIEWED_BROKEN_SYMLINKS = Object.freeze([",
        '    path: "Frameworks/Tcl.framework/PrivateHeaders",',
        '    target: "Versions/Current/PrivateHeaders",',
        '    path: "Frameworks/Tk.framework/PrivateHeaders",',
        'const PRODUCER_INSTALL_METHOD = "macos-installer-no-op-framework-component";',
        "const FRAMEWORK_COMPONENT_CONTRACT = Object.freeze({",
        '  packageName: "Python_Framework.pkg",',
        "  noOpPostinstallSize: 17,",
        '    "306c6ca7407560340797866e077e053627ad409277d1b9da58106fce4cf717cb",',
        '  noOpPostinstallMode: "0755",',
        "function canonicalJsonBytes(value) {",
        "function normalizeExclusions(excludedPaths) {",
        "function requiredOpenFlag(name) {",
        "function openDirectoryNoFollow(pathname, before) {",
        "function hashRegularFile(pathname, before) {",
        "function fingerprintInstallRoot(",
        "function verifyProductionExclusionClosure(",
        "function verifyLockValue(lock) {",
        "function verifyLockContract(lockPath) {",
        "function verifyStartupEnvironment(environment) {",
        "function verifyReviewedPythonFramework(options) {",
        "if (require.main === module) {\n  main();\n}",
    )
    if any(marker not in source for marker in required_source_markers):
        return False

    component_contract = _source_block(
        source,
        "const FRAMEWORK_COMPONENT_CONTRACT = Object.freeze({",
        "\n\nconst MAX_LOCK_BYTES",
    )
    normalized_component_contract = re.sub(r"\s+", "", component_contract)
    expected_component_contract = (
        "constFRAMEWORK_COMPONENT_CONTRACT=Object.freeze({"
        + "".join(
            f"{name}:{json.dumps(value, ensure_ascii=False, separators=(',', ':'))},"
            for name, value in PYTHON_FRAMEWORK_COMPONENT_CONTRACT.items()
        )
        + "});"
    )
    if normalized_component_contract != expected_component_contract:
        return False
    if any(source.count(f'  "{path}",') != 1 for path in exact_exclusions):
        return False
    if (
        source.count('requiredOpenFlag("O_NOFOLLOW")') != 3
        or source.count('requiredOpenFlag("O_DIRECTORY")') != 1
        or source.count("openDirectoryNoFollow(") != 2
        or source.count("hashRegularFile(") != 3
        or source.count("isForbiddenBytecodeCachePath(") != 2
        or source.count("verifyStartupEnvironment(") != 2
    ):
        return False

    required_open_flag = _source_block(
        source,
        "function requiredOpenFlag(name) {",
        "\nfunction openDirectoryNoFollow(pathname, before) {",
    )
    if (
        "  const value = fs.constants[name];\n" not in required_open_flag
        or "  if (!Number.isInteger(value) || value === 0) {\n"
        not in required_open_flag
        or '    fail(`Required filesystem flag ${name} is unavailable`);\n'
        not in required_open_flag
        or "  return value;\n" not in required_open_flag
    ):
        return False

    lock_value_contract = _source_block(
        source,
        "function verifyLockValue(lock) {",
        "\nfunction verifyLockContract(lockPath) {",
    )
    if any(
        marker not in lock_value_contract
        for marker in (
            "python.installRoot !== EXACT_ROOT",
            "python.frameworkCoreFingerprintSha256 !== CORE_DIGEST",
            "!sameJson(python.frameworkCoreFingerprintExcludedPaths, CORE_EXCLUDED_PATHS)",
            "!sameJson(python.reviewedBrokenSymlinks, REVIEWED_BROKEN_SYMLINKS)",
            "distribution.installMethod !== PRODUCER_INSTALL_METHOD",
            "!sameJson(distribution.frameworkComponent, FRAMEWORK_COMPONENT_CONTRACT)",
            'fail("Reviewed Python lock differs from the hard-coded framework contract");',
            "return lock;",
        )
    ) or re.search(r"\bfalse\b", lock_value_contract):
        return False
    path_lock_contract = _source_block(
        source,
        "function verifyLockContract(lockPath) {",
        "\nfunction parseCliArguments(argv) {",
    )
    if re.sub(r"\s+", "", path_lock_contract) != (
        "functionverifyLockContract(lockPath){"
        "returnverifyLockValue(readLockFile(lockPath));}"
    ):
        return False

    startup_environment = _source_block(
        source,
        "function verifyStartupEnvironment(environment) {",
        "\nfunction verifyReviewedPythonFramework(options) {",
    )
    exact_startup_guard = (
        "  if (\n"
        '    (environment.NODE_OPTIONS !== undefined && environment.NODE_OPTIONS !== "") ||\n'
        '    (environment.NODE_PATH !== undefined && environment.NODE_PATH !== "")\n'
        "  ) {\n"
        '    fail("Node verifier must be started without NODE_OPTIONS or NODE_PATH");\n'
        "  }\n"
        "}"
    )
    if startup_environment.rstrip() != (
        "function verifyStartupEnvironment(environment) {\n" + exact_startup_guard
    ):
        return False

    fingerprint = _source_block(
        source,
        "function fingerprintInstallRoot(",
        "\nfunction readLockFile(lockPath) {",
    )
    cache_guard = (
        "        const forbiddenCachePath = isForbiddenBytecodeCachePath(childParts);\n"
        "        if (forbiddenCachePath && rejectBytecodeCaches) {\n"
        '          fail("Framework tree contains executable bytecode cache");\n'
        "        }\n"
    )
    cache_offset = fingerprint.find(cache_guard)
    exclusion_offset = fingerprint.find("        const excluded =\n")
    lstat_offset = fingerprint.find(
        '        const info = lstat(child, "Framework entry changed during traversal");'
    )
    if not (0 <= lstat_offset < cache_offset < exclusion_offset):
        return False
    if any(
        marker not in fingerprint
        for marker in (
            "const descriptor = openDirectoryNoFollow(directory, before);",
            "item.sha256 = reviewedDigest ?? hashRegularFile(child, info);",
            "!sameIdentity(before, heldAfter)",
            "!sameIdentity(before, namedAfter)",
            "inventory.sort((left, right) => comparePythonStrings(left.path, right.path));",
            'crypto.createHash("sha256").update(canonicalJsonBytes(inventory)).digest("hex")',
            "requireProductionExclusionClosure &&",
            "!observedSitePackages || !observedSitePackagesReadme",
            "relative === SITE_PACKAGES_README.path",
            "info.size !== BigInt(SITE_PACKAGES_README.size)",
            "reviewedDigest !== SITE_PACKAGES_README.sha256",
        )
    ):
        return False

    reviewed_verifier = _source_block(
        source,
        "function verifyReviewedPythonFramework(options) {",
        "\nfunction main() {",
    )
    if any(
        marker not in reviewed_verifier
        for marker in (
            'Object.hasOwn(options, "root")',
            'const hasLockPath = Object.hasOwn(options, "lock");',
            'const hasLockValue = Object.hasOwn(options, "lockValue");',
            "if (hasLockPath === hasLockValue) {",
            'fail("Provide exactly one of lock or lockValue");',
            'hasLockPath ? "lock" : "lockValue"',
            "if (root !== EXACT_ROOT) {",
            "verifyLockContract(options.lock);",
            "verifyLockValue(options.lockValue);",
            "const observed = verifyProductionExclusionClosure(root);",
            "if (observed !== CORE_DIGEST) {",
        )
    ) or re.search(r"\bfalse\b", reviewed_verifier):
        return False
    main = _source_block(source, "function main() {", "\nmodule.exports =")
    startup_offset = main.find("    verifyStartupEnvironment(process.env);")
    argv_offset = main.find(
        "    const argumentsValue = parseCliArguments(process.argv.slice(2));"
    )
    verify_offset = main.find(
        "    const digest = verifyReviewedPythonFramework(argumentsValue);"
    )
    if not (0 <= startup_offset < argv_offset < verify_offset):
        return False

    required_test_markers = (
        'test("hard-coded constants exactly match the repository lock", () => {',
        'test("a held parsed lock value satisfies the same hard-coded contract", () => {',
        'test("framework verification requires exactly one lock path or held value", () => {',
        'test("a mutable lock cannot override the hard-coded contract", () => {',
        'test("every producer-contract field is sealed against lock mutation", async (t) => {',
        'test("CLI parsing rejects duplicate, missing, and surplus arguments", () => {',
        'test("startup environment rejects Node preload controls", () => {',
        'test("known canonical inventory digest matches Python fingerprinting", () => {',
        'test("excluded subtree contents do not affect the digest", () => {',
        'test("escaping and absolute symlinks are rejected", () => {',
        'test("only the exact reviewed broken symlink set is accepted", () => {',
        'test("cache names are rejected case-insensitively for every file type", async (t) => {',
        'test("Python-compatible fingerprint mode skips casefolded caches", () => {',
        'test("production exclusion closure accepts only the reviewed site-packages README", (t) => {',
        'test("production exclusion closure rejects stale sitecustomize code", (t) => {',
        'test("production exclusion closure rejects README content tampering", (t) => {',
        'test("production exclusion closure rejects every other excluded path", (t) => {',
        'test("filesystem special entries are rejected", () => {',
    )
    return all(marker in tests for marker in required_test_markers)


def load_inputs() -> dict[str, Any]:
    return {
        "workflow": read(WORKFLOW),
        "makefile": read(MAKEFILE),
        "build_script": read(BUILD_SCRIPT),
        "audit_script": read(AUDIT_SCRIPT),
        "python_bootstrap": read(PYTHON_BOOTSTRAP),
        "framework_verifier": read(FRAMEWORK_VERIFIER),
        "framework_verifier_tests": read(FRAMEWORK_VERIFIER_TESTS),
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


def _workflow_python_producer_is_semantic(run: str) -> bool:
    """Require the exact no-Python framework component producer boundary."""

    manifest_parts = PYTHON_HASH_MANIFEST_ENTRY.split(" ")
    if (
        len(manifest_parts) != 2
        or manifest_parts[0].lower() != PYTHON_ARCHIVE_SHA256
        or manifest_parts[1] != PYTHON_ARCHIVE_NAME
        or not PYTHON_ARCHIVE_URL.endswith(f"/{PYTHON_ARCHIVE_NAME}")
        or run.count(EXPECTED_FRAMEWORK_PLACEHOLDER_CLEANUP) != 1
        or run.count(EXPECTED_FRAMEWORK_QUARANTINE_TRANSITION) != 1
    ):
        return False

    markers = (
        'readonly producer_prefix="${RUNNER_TEMP}/lcf-python-producer."',
        '/usr/bin/mktemp -d "${producer_prefix}XXXXXXXXXX"',
        '/bin/chmod 0700 "${producer_root}"',
        EXPECTED_FRAMEWORK_PLACEHOLDER_CLEANUP,
        'framework_quarantine_placeholder="none"\nframework_quarantine_placeholder_identity="none"\ntrap cleanup_producer EXIT',
        "trap cleanup_producer EXIT",
        'readonly archive="${producer_root}/python-3.13.14-darwin-arm64.tar.gz"',
        'readonly hashes="${producer_root}/hashes.sha256"',
        PYTHON_ARCHIVE_URL,
        PYTHON_HASHES_URL,
        'test "$(/usr/bin/stat -f \'%z\' "${archive}")" = "70956513"',
        'test "$(/usr/bin/stat -f \'%z\' "${hashes}")" = "2775"',
        PYTHON_ARCHIVE_SHA256,
        PYTHON_HASHES_SHA256,
        EXPECTED_PYTHON_HASH_MANIFEST_BINDING,
        "'./setup.sh' \\",
        "'./build_output.txt' \\",
        "'./python-3.13.14-macos11.pkg'",
        '/usr/bin/tar -xzf "${archive}" -C "${producer_root}" \\\n  "./python-3.13.14-macos11.pkg"',
        'test "$(/usr/bin/stat -f \'%z\' "${package}")" = "71544771"',
        "8e58affb218c155a1dfdc27b291f817129669f8760e7a297adb2e4439ba5d2e8",
        '/usr/sbin/pkgutil --check-signature "${package}"',
        '/usr/sbin/spctl --assess --type install --verbose=4 "${package}"',
        '/usr/sbin/pkgutil --expand "${package}" "${expanded}"',
        'readonly component="${expanded}/Python_Framework.pkg"',
        '"${component}/Bom" \\\n    "${component}/PackageInfo" \\\n    "${component}/Payload" \\\n    "${component}/Scripts"',
        'readonly postinstall="${component}/Scripts/postinstall"',
        'test "$(/usr/bin/stat -f \'%z\' "${component}/Bom")" = "1404518"',
        'test "$(/usr/bin/stat -f \'%z\' "${component}/PackageInfo")" = "947"',
        'test "$(/usr/bin/stat -f \'%z\' "${component}/Payload")" = "32739568"',
        'test "$(/usr/bin/stat -f \'%z\' "${postinstall}")" = "894"',
        'test "$(/usr/bin/stat -f \'%Lp\' "${postinstall}")" = "755"',
        "4e49a4c96076a4855219461f721d510493c6d4f3a7a2a9ad7c981ced723d09bd",
        "86938c44112e37c4791fdc15ee0d89777ed8b6d0a85bae37f7ebf09839072f5c",
        "f922c9d7c78f3745dc453211677fbce2e4b415616556b11376a92ca7a17fc391",
        "7821586a42b4d86b075ed2c87da0a5981e5372070b9c7f6141d09f77cb172417",
        "printf '#!/bin/sh\\nexit 0\\n' > \"${no_op_postinstall}\"",
        '/bin/chmod 0755 "${no_op_postinstall}"',
        'test "$(/usr/bin/stat -f \'%z\' "${no_op_postinstall}")" = "17"',
        "306c6ca7407560340797866e077e053627ad409277d1b9da58106fce4cf717cb",
        '/bin/mv -f "${no_op_postinstall}" "${postinstall}"',
        '/usr/sbin/pkgutil --flatten "${component}" "${no_op_package}"',
        'readonly no_op_identity="$(/usr/bin/stat -f \'%d:%i:%Lp:%u:%g:%l:%z:%m\' "${no_op_package}")"',
        'readonly no_op_sha256="$(/usr/bin/shasum -a 256 "${no_op_package}" | /usr/bin/awk \'{print $1}\')"',
        '/usr/sbin/pkgutil --expand "${no_op_package}" "${reviewed_no_op}"',
        'readonly reviewed_postinstall="${reviewed_no_op}/Scripts/postinstall"',
        'for existing_ancestor in \\\n  "/Library" \\\n  "/Library/Frameworks" \\\n  "/Library/Frameworks/Python.framework" \\\n  "/Library/Frameworks/Python.framework/Versions" \\\n  "/Library/Frameworks/Python.framework/Versions/3.13"; do',
        'if test ! -e "${existing_ancestor}" && \\\n    test ! -L "${existing_ancestor}"; then',
        'test "$(cd "${existing_ancestor}" && /bin/pwd -P)" = "${existing_ancestor}"',
        'existing_identity="$(/usr/bin/stat -f \'%d:%i\' "${existing_ancestor}")"',
        '/usr/bin/sudo --non-interactive /usr/sbin/chown -h 0:0 "${existing_ancestor}"',
        '/usr/bin/sudo --non-interactive /bin/chmod -h -N "${existing_ancestor}"',
        '/usr/bin/sudo --non-interactive /bin/chmod -h go-w "${existing_ancestor}"',
        'test "$(/usr/bin/stat -f \'%d:%i\' "${existing_ancestor}")" = "${existing_identity}"',
        'readonly framework_quarantine_prefix="${framework_parent}/.lcf-python-quarantine."',
        'readonly previous_root_identity="$(/usr/bin/stat -f \'%d:%i\' "${framework_root}")"',
        '"${framework_quarantine_prefix}XXXXXXXXXX"',
        'framework_quarantine_placeholder="${framework_quarantine}"',
        'framework_quarantine_placeholder_identity="$(/usr/bin/stat -f \'%d:%i\' \\\n    "${framework_quarantine_placeholder}")"',
        'framework_quarantine_suffix="${framework_quarantine#"${framework_quarantine_prefix}"}"',
        'readonly framework_quarantine_suffix',
        'test "${framework_quarantine%/*}" = "${framework_parent}"',
        'test "${framework_quarantine}" = \\\n    "${framework_quarantine_prefix}${framework_quarantine_suffix}"',
        '[[ "${framework_quarantine_suffix}" =~ ^[A-Za-z0-9]{10}$ ]]',
        'test -d "${framework_quarantine}"',
        'test ! -L "${framework_quarantine}"',
        'test "$(/usr/bin/stat -f \'%u\' \\\n    "${framework_quarantine}")" = "0"',
        'test "$(/usr/bin/stat -f \'%Lp\' \\\n    "${framework_quarantine}")" = "700"',
        '/usr/bin/sudo --non-interactive /bin/rmdir "${framework_quarantine}"',
        'test ! -e "${framework_quarantine}"',
        'test ! -L "${framework_quarantine}"',
        'framework_quarantine_placeholder_identity="none"',
        'framework_quarantine_placeholder="none"',
        '/usr/bin/sudo --non-interactive /bin/mv \\\n    "${framework_root}" "${framework_quarantine}"',
        'test ! -e "${framework_root}"',
        'test ! -L "${framework_root}"',
        '/usr/bin/sudo --non-interactive /usr/sbin/installer \\\n  -pkg "${no_op_package}" -target /',
        '"${framework_root}")" != "${framework_quarantine_identity}"',
        "printf 'LCF_REVIEWED_FRAMEWORK_QUARANTINE=%s\\n' \\",
        "printf 'LCF_REVIEWED_FRAMEWORK_QUARANTINE_IDENTITY=%s\\n' \\",
        "cleanup_producer",
    )
    if any(marker not in run for marker in markers):
        return False
    order = (
        'printf \'%s  %s\\n\' \\\n  "839b14df8a24415e17d15f222e2ac01d3a90845deb39df642e2cc01869140a34"',
        EXPECTED_PYTHON_HASH_MANIFEST_BINDING,
        '/usr/bin/tar -tzf "${archive}"',
        '/usr/bin/tar -xzf "${archive}"',
        '/usr/sbin/pkgutil --check-signature "${package}"',
        '/usr/sbin/spctl --assess --type install --verbose=4 "${package}"',
        '/usr/sbin/pkgutil --expand "${package}" "${expanded}"',
        '/bin/mv -f "${no_op_postinstall}" "${postinstall}"',
        '/usr/sbin/pkgutil --flatten "${component}" "${no_op_package}"',
        '/usr/sbin/pkgutil --expand "${no_op_package}" "${reviewed_no_op}"',
        'for existing_ancestor in \\',
        'test "$(cd "${existing_ancestor}" && /bin/pwd -P)" = "${existing_ancestor}"',
        'existing_identity="$(/usr/bin/stat -f \'%d:%i\' "${existing_ancestor}")"',
        '/usr/bin/sudo --non-interactive /usr/sbin/chown -h 0:0 "${existing_ancestor}"',
        '/usr/bin/sudo --non-interactive /bin/chmod -h -N "${existing_ancestor}"',
        '/usr/bin/sudo --non-interactive /bin/chmod -h go-w "${existing_ancestor}"',
        'test "$(/usr/bin/stat -f \'%d:%i\' "${existing_ancestor}")" = "${existing_identity}"',
        'readonly framework_quarantine_prefix="${framework_parent}/.lcf-python-quarantine."',
        'if test -e "${framework_root}" || test -L "${framework_root}"; then',
        '/usr/bin/sudo --non-interactive /usr/bin/mktemp -d \\',
        'framework_quarantine_suffix="${framework_quarantine#"${framework_quarantine_prefix}"}"',
        'readonly framework_quarantine_suffix',
        'test "${framework_quarantine%/*}" = "${framework_parent}"',
        'test "${framework_quarantine}" = \\\n    "${framework_quarantine_prefix}${framework_quarantine_suffix}"',
        '[[ "${framework_quarantine_suffix}" =~ ^[A-Za-z0-9]{10}$ ]]',
        'test -d "${framework_quarantine}"',
        'test ! -L "${framework_quarantine}"',
        'framework_quarantine_placeholder="${framework_quarantine}"',
        'framework_quarantine_placeholder_identity="$(/usr/bin/stat -f \'%d:%i\' \\',
        'test "$(/usr/bin/stat -f \'%u\' \\\n    "${framework_quarantine}")" = "0"',
        'test "$(/usr/bin/stat -f \'%Lp\' \\\n    "${framework_quarantine}")" = "700"',
        '/usr/bin/sudo --non-interactive /bin/rmdir "${framework_quarantine}"',
        'test ! -e "${framework_quarantine}"\n'
        '  test ! -L "${framework_quarantine}"\n'
        '  framework_quarantine_placeholder_identity="none"\n'
        '  framework_quarantine_placeholder="none"',
        '/usr/bin/sudo --non-interactive /bin/mv \\',
        'test ! -e "${framework_root}"',
        '/usr/bin/sudo --non-interactive /usr/sbin/installer \\',
        'test -d "/Library/Frameworks/Python.framework/Versions/3.13"',
    )
    offsets = [run.find(marker) for marker in order]
    return (
        all(offset >= 0 for offset in offsets)
        and offsets == sorted(offsets)
        and run.count("/usr/sbin/installer") == 1
        and run.count("/usr/sbin/pkgutil --flatten") == 1
        and run.count('/usr/sbin/pkgutil --expand "${no_op_package}"') == 1
        and run.count(PYTHON_ARCHIVE_URL) == 1
        and run.count(PYTHON_HASHES_URL) == 1
        and run.count(EXPECTED_PYTHON_HASH_MANIFEST_BINDING) == 1
        and run.count(PYTHON_HASH_MANIFEST_ENTRY) == 1
        and run.count("1404518") == 2
        and run.count("32739568") == 2
        and run.count("4e49a4c96076a4855219461f721d510493c6d4f3a7a2a9ad7c981ced723d09bd") == 2
        and run.count("86938c44112e37c4791fdc15ee0d89777ed8b6d0a85bae37f7ebf09839072f5c") == 2
        and run.count("f922c9d7c78f3745dc453211677fbce2e4b415616556b11376a92ca7a17fc391") == 2
        and run.count("7821586a42b4d86b075ed2c87da0a5981e5372070b9c7f6141d09f77cb172417") == 1
        and run.count("306c6ca7407560340797866e077e053627ad409277d1b9da58106fce4cf717cb") == 3
        and run.count("%d:%i:%Lp:%u:%g:%l:%z:%m") == 5
        and run.count('"${no_op_sha256}" "${no_op_package}"') == 2
        and run.count('test ! -e "${framework_root}"') == 2
        and run.count('test ! -L "${framework_root}"') == 3
        and run.count('test ! -e "${framework_quarantine}"') == 1
        and run.count('test ! -L "${framework_quarantine}"') == 3
        and run.count(
            'readonly framework_quarantine_prefix="${framework_parent}/.lcf-python-quarantine."'
        ) == 1
        and run.count(
            'framework_quarantine_suffix="${framework_quarantine#"${framework_quarantine_prefix}"}"'
        ) == 1
        and run.count("readonly framework_quarantine_suffix") == 1
        and run.count('test "$(cd "${existing_ancestor}"') == 1
        and run.count('"${existing_ancestor}")" = "${existing_identity}"') == 1
        and run.count('"${framework_quarantine}")" = "0"') == 1
        and run.count('"${framework_quarantine}")" = "700"') == 1
        and run.count(
            'test "${framework_quarantine}" = \\\n    "${framework_quarantine_prefix}${framework_quarantine_suffix}"'
        ) == 1
        and run.count(
            '[[ "${framework_quarantine_suffix}" =~ ^[A-Za-z0-9]{10}$ ]]'
        ) == 1
        and run.count(
            '/usr/bin/sudo --non-interactive /bin/rmdir "${framework_quarantine}"'
        ) == 1
        and run.count(
            '/usr/bin/sudo --non-interactive /bin/rmdir \\\n'
            '        "${cleanup_quarantine}"'
        ) == 1
        and run.count("cleanup_producer() {") == 1
        and run.count("trap - EXIT") == 1
        and run.count("trap cleanup_producer EXIT") == 1
        and run.count("cleanup_producer") == 3
        and len(re.findall(r"(?m)^\s*trap\s", run)) == 2
        and run.count("/bin/rmdir") == 2
        and run.count('framework_quarantine_placeholder="${framework_quarantine}"') == 1
        and run.count(
            'framework_quarantine_placeholder_identity="$(/usr/bin/stat -f \'%d:%i\' \\'
        ) == 1
        and run.count('framework_quarantine_placeholder_identity="none"') == 2
        and run.count('framework_quarantine_placeholder="none"') == 2
        and "readonly framework_quarantine_placeholder" not in run
        and not re.search(
            r"/bin/rm(?:\s|\\\n)[\s\S]{0,160}"
            r"(?:framework|cleanup)_quarantine",
            run,
        )
        and not re.search(
            r"/usr/bin/find[^\n]*(?:framework|cleanup)_quarantine", run
        )
        and 'cd "${framework_quarantine}"' not in run
        and run.count(
            'test "$(/usr/bin/stat -f \'%d:%i:%Lp:%u:%g:%l:%z:%m\' \\\n'
            '  "${no_op_package}")" = "${no_op_identity}"'
        ) == 2
        and "actions/setup-python" not in run
        and not re.search(r"(?m)^\s*(?:python|python3)(?:\s|$)", run)
        and "./setup.sh" not in run.replace("'./setup.sh'", "")
    )


def _workflow_held_framework_loader_is_semantic(run: str) -> bool:
    """Require verifier and lock bytes to remain held across Node verification."""

    loader_prefix = (
        "/usr/bin/env -i \\\n"
        '  HOME="${RUNNER_TEMP}" \\\n'
        '  PATH="/usr/bin:/bin" \\\n'
        "  NODE_OPTIONS= \\\n"
        "  NODE_PATH= \\\n"
        '  "${LCF_REVIEWED_FRAMEWORK_VERIFIER_NODE}" \\\n'
        "  -e '\n"
    )
    loader_suffix = (
        "\n' \\\n"
        '  "${framework_verifier}" \\\n'
        '  "${framework_verifier_size}" \\\n'
        '  "${framework_verifier_sha256}" \\\n'
        '  "${framework_lock}" \\\n'
        '  "${framework_lock_size}" \\\n'
        '  "${framework_lock_sha256}" \\\n'
        '  "${framework_root}"'
    )
    if run.count(loader_prefix) != 1 or run.count(loader_suffix) != 1:
        return False
    loader = run.split(loader_prefix, 1)[1].split(loader_suffix, 1)[0]
    markers = (
        '"use strict";',
        "const expectedArgumentCount = 7;",
        "const argumentsValue = process.argv.slice(1);",
        'typeof fs.constants.O_NOFOLLOW !== "number"',
        "function identity(info) {",
        "info.dev,\n    info.ino,\n    info.mode,\n    info.nlink,\n"
        "    info.uid,\n    info.gid,\n    info.size,\n    info.mtimeNs,\n"
        "    info.ctimeNs,",
        "function openPinned(pathname, sizeText, expectedSha256) {",
        "!path.posix.isAbsolute(pathname)",
        'pathname.includes("\\0")',
        "!/^[1-9][0-9]*$/.test(sizeText)",
        "!/^[0-9a-f]{64}$/.test(expectedSha256)",
        "const expectedSize = BigInt(sizeText);",
        "if (expectedSize > 1048576n) {",
        "const namedBefore = fs.lstatSync(pathname, { bigint: true });",
        "const unsafeMode = (namedBefore.mode & 0o7022n) !== 0n;",
        "!namedBefore.isFile()",
        "namedBefore.isSymbolicLink()",
        "namedBefore.uid !== BigInt(process.geteuid())",
        "namedBefore.nlink !== 1n",
        "namedBefore.size !== expectedSize",
        "fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW",
        "const heldBefore = fs.fstatSync(descriptor, { bigint: true });",
        "identity(heldBefore) !== identity(namedBefore)",
        "const content = Buffer.alloc(Number(expectedSize));",
        "while (offset < content.length) {",
        "const count = fs.readSync(",
        "if (count === 0) {",
        "const heldAfter = fs.fstatSync(descriptor, { bigint: true });",
        "const namedAfter = fs.lstatSync(pathname, { bigint: true });",
        "identity(heldAfter) !== identity(heldBefore)",
        "identity(namedAfter) !== identity(heldBefore)",
        'crypto.createHash("sha256").update(content).digest("hex") !==\n'
        "        expectedSha256",
        "function revalidate(binding) {",
        "identity(held) !== binding.identity",
        "identity(named) !== binding.identity",
        "verifierBinding = openPinned(",
        "lockBinding = openPinned(lockPath, lockSizeText, lockSha256);",
        "const reviewedModule = new Module(verifierPath);",
        "reviewedModule.filename = verifierPath;",
        "reviewedModule.paths = [];",
        "reviewedModule._compile(",
        "decoder.decode(verifierBinding.content)",
        "verifier.verifyStartupEnvironment(process.env);",
        "const lockValue = JSON.parse(decoder.decode(lockBinding.content));",
        "const digest = verifier.verifyReviewedPythonFramework({\n"
        "    root: frameworkRoot,\n    lockValue,\n  });",
        "revalidate(verifierBinding);",
        "revalidate(lockBinding);",
        "fs.closeSync(lockBinding.descriptor);",
        "fs.closeSync(verifierBinding.descriptor);",
    )
    if any(marker not in loader for marker in markers):
        return False
    verification_order = (
        "verifierBinding = openPinned(",
        "lockBinding = openPinned(lockPath, lockSizeText, lockSha256);",
        "const reviewedModule = new Module(verifierPath);",
        "reviewedModule._compile(",
        "const lockValue = JSON.parse(decoder.decode(lockBinding.content));",
        "const digest = verifier.verifyReviewedPythonFramework({",
        "revalidate(verifierBinding);",
        "revalidate(lockBinding);",
        "process.stdout.write(`${digest}\\n`);",
        "fs.closeSync(lockBinding.descriptor);",
        "fs.closeSync(verifierBinding.descriptor);",
    )
    offsets = [loader.find(marker) for marker in verification_order]
    return (
        all(offset >= 0 for offset in offsets)
        and offsets == sorted(offsets)
        and loader.count("openPinned(") == 3
        and loader.count("revalidate(") == 3
        and loader.count("fs.closeSync(") == 3
        and not re.search(r"false\s*&&|\|\|\s*true|if\s*\(\s*false", loader)
        and "require(verifierPath)" not in loader
        and "fs.readFileSync" not in loader
        and "child_process" not in loader
        and "lock: lockPath" not in loader
    )


def _workflow_python_seal_is_semantic(run: str) -> bool:
    """Require transactional framework sealing, rollback, and Node verification."""

    ancestor_targets = (
        ("library_root", "library_identity"),
        ("framework_container", "container_identity"),
        ("framework_anchor", "anchor_identity"),
        ("framework_parent", "parent_identity"),
    )
    ancestor_seal_commands = tuple(
        command
        for target, identity_name in ancestor_targets
        for command in (
            '/usr/bin/sudo --non-interactive /usr/sbin/chown \\\n'
            f'  -h 0:0 "${{{target}}}"',
            '/usr/bin/sudo --non-interactive /bin/chmod \\\n'
            f'  -h -N "${{{target}}}"',
            '/usr/bin/sudo --non-interactive /bin/chmod \\\n'
            f'  -h go-w "${{{target}}}"',
            'test "$(/usr/bin/stat -f \'%d:%i\' '
            f'"${{{target}}}")" = "${{{identity_name}}}"',
        )
    )
    root_find_commands = (
        '/usr/bin/sudo --non-interactive /usr/bin/find -P -x \\\n  "${framework_root}" \\( -type f -o -type d \\) \\\n  -exec /usr/sbin/chown 0:0 \'{}\' \'+\'',
        '/usr/bin/sudo --non-interactive /usr/bin/find -P -x \\\n  "${framework_root}" \\( -type f -o -type d \\) \\\n  -exec /bin/chmod -N \'{}\' \'+\'',
        '/usr/bin/sudo --non-interactive /usr/bin/find -P -x \\\n  "${framework_root}" \\( -type f -o -type d \\) \\\n  -exec /bin/chmod go-w \'{}\' \'+\'',
    )
    transaction_blocks = (
        EXPECTED_FRAMEWORK_SEAL_TRANSACTION_SENTINELS,
        EXPECTED_FRAMEWORK_SEAL_TRANSACTION_CLEANUP,
        "trap cleanup_sealed_framework EXIT",
        EXPECTED_FRAMEWORK_SEAL_QUARANTINE_BINDING,
        EXPECTED_FRAMEWORK_SEAL_ROOT_BINDING,
        EXPECTED_FRAMEWORK_SEAL_TRANSACTION_COMMIT,
    )
    markers = (
        *transaction_blocks,
        *ancestor_seal_commands,
        *root_find_commands,
        '/usr/bin/sudo --non-interactive /usr/bin/find -x \\\n  "${framework_root}" -type f \\\n  \\( -iname \'*.pyc\' -o -iname \'*.pyo\' \\) -delete',
        '/usr/bin/sudo --non-interactive /usr/bin/find -x \\\n  "${framework_root}" -depth -type d \\\n  -iname \'__pycache__\' -delete',
        "shopt -s nocasematch",
        "shopt -u nocasematch",
        "sealed_listing=\"$(/bin/ls -lde \"${sealed_directory}\")\"",
        "[[ \"${sealed_listing}\" != *$'\\n'* ]]",
        "entry_listing=\"$(/bin/ls -lde \"${entry}\")\"",
        "[[ \"${entry_listing}\" != *$'\\n'* ]]",
        'readonly framework_verifier="${GITHUB_WORKSPACE}/tools/verify_reviewed_python_framework.cjs"',
        'readonly framework_lock="${GITHUB_WORKSPACE}/backend/packaging/python-sidecar-toolchain.lock.json"',
        'readonly framework_verifier_size="27853"',
        'readonly framework_verifier_sha256="ffbf6ed2f41a35f44edda68bdd831be4d42384f9488dcdc93f8242abcfb9e218"',
        'readonly framework_lock_size="4198"',
        'readonly framework_lock_sha256="d5fb2f15b8e0440cdac44418c3a151605dd39f195c5a784d8d9f86b2c1623d97"',
        '"${LCF_REVIEWED_FRAMEWORK_VERIFIER_NODE_IDENTITY}"',
        '"${LCF_REVIEWED_FRAMEWORK_VERIFIER_NODE_SHA256}"',
    )
    if any(run.count(block) != 1 for block in transaction_blocks) or any(
        marker not in run for marker in markers[len(transaction_blocks) :]
    ):
        return False
    transaction_offsets = [run.find(block) for block in transaction_blocks]
    ancestor_offsets = [run.find(command) for command in ancestor_seal_commands]
    root_offsets = [run.find(command) for command in root_find_commands]
    cache_offset = run.find("\\( -iname '*.pyc' -o -iname '*.pyo' \\) -delete")
    verifier_offset = run.find("  -e '\n")
    commit_offset = run.find(EXPECTED_FRAMEWORK_SEAL_TRANSACTION_COMMIT)
    node_identity_check = (
        'test "$(/usr/bin/stat -f \'%d:%i:%Lp:%u:%g:%l:%z:%m\' \\\n'
        '  "${LCF_REVIEWED_FRAMEWORK_VERIFIER_NODE}")" = \\\n'
        '  "${LCF_REVIEWED_FRAMEWORK_VERIFIER_NODE_IDENTITY}"'
    )
    node_hash_check = (
        "printf '%s  %s\\n' \\\n"
        '  "${LCF_REVIEWED_FRAMEWORK_VERIFIER_NODE_SHA256}" \\\n'
        '  "${LCF_REVIEWED_FRAMEWORK_VERIFIER_NODE}" | \\\n'
        "  /usr/bin/shasum -a 256 --check"
    )
    first_identity = run.find(node_identity_check)
    last_identity = run.rfind(node_identity_check)
    first_hash = run.find(node_hash_check)
    last_hash = run.rfind(node_hash_check)
    return (
        transaction_offsets == sorted(transaction_offsets)
        and all(offset >= 0 for offset in transaction_offsets)
        and root_offsets == sorted(root_offsets)
        and all(offset >= 0 for offset in root_offsets)
        and ancestor_offsets == sorted(ancestor_offsets)
        and all(offset >= 0 for offset in ancestor_offsets)
        and transaction_offsets[4] < ancestor_offsets[0] < root_offsets[0]
        and all(
            run.count(
                'test "$(/usr/bin/stat -f \'%d:%i\' '
                f'"${{{target}}}")" = "${{{identity_name}}}"'
            )
            == 2
            for target, identity_name in ancestor_targets
        )
        and run.count(
            'test "$(/usr/bin/stat -f \'%d:%i\' "${framework_root}")" = '
            '"${root_identity}"'
        ) == 1
        and root_offsets[-1] < cache_offset < verifier_offset < commit_offset
        and first_identity < first_hash < verifier_offset
        < last_identity < last_hash < commit_offset
        and run.count(node_identity_check) == 2
        and run.count(node_hash_check) == 2
        and run.count("-exec /usr/sbin/chown 0:0 '{}' '+'") == 1
        and run.count("-exec /bin/chmod -N '{}' '+'") == 1
        and run.count("-exec /bin/chmod go-w '{}' '+'") == 1
        and run.count("cleanup_sealed_framework() {") == 1
        and run.count("cleanup_sealed_framework") == 2
        and run.count("trap cleanup_sealed_framework EXIT") == 1
        and run.count("trap - EXIT") == 2
        and len(re.findall(r"(?m)^\s*trap\s", run)) == 3
        and run.count('seal_transaction_phase="pending"') == 1
        and run.count('seal_transaction_phase="committed"') == 1
        and run.count('seal_transaction_phase="complete"') == 1
        and run.count('seal_installed_root_identity="${root_identity}"') == 1
        and run.count('seal_quarantine_state="active"') == 1
        and run.count('"${framework_root}" -depth -delete') == 1
        and run.count('"${seal_quarantine}" -depth -delete') == 2
        and run.count('"${seal_quarantine}" "${framework_root}"') == 1
        and not re.search(
            r"/bin/rm(?:\s|\\\n)[\s\S]{0,160}"
            r"(?:framework_root|seal_quarantine)",
            run,
        )
        and "-R -P" not in run
        and "actions/setup-python" not in run
        and not re.search(r"(?m)^\s*(?:python|python3)(?:\s|$)", run)
        and not _run_block_has_bypass(run)
        and _framework_seal_shell_control_surface_is_locked(run)
        and _workflow_held_framework_loader_is_semantic(run)
    )


def _framework_seal_shell_control_surface_is_locked(run: str) -> bool:
    """Allow only the reviewed seal's fixed shell control surface."""

    loader_prefix = "  -e '\n"
    loader_suffix = "\n' \\\n"
    if run.count(loader_prefix) != 1 or run.count(loader_suffix) != 1:
        return False
    shell = run.split(loader_prefix, 1)[0] + run.split(loader_suffix, 1)[1]
    shell = re.sub(r"\\\r?\n", "", shell)
    expected_controls = (
        "set -euo pipefail",
        "trap - EXIT",
        "trap cleanup_sealed_framework EXIT",
        "shopt -s nocasematch",
        "shopt -u nocasematch",
        "trap - EXIT",
    )
    controls: list[str] = []
    function_header = re.compile(
        r"(?:^|[;&|{(])\s*(?:"
        r"function\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(\s*\))?"
        r"|([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*\)"
        r")(?=\s|[({]|$)",
        re.MULTILINE,
    )
    dynamic_command = re.compile(
        r"\b(?:eval|builtin|command|enable|alias|unalias)\b|(?<!-)\bexec\b"
    )
    source_command = re.compile(r"(?:^|[;&|{(!])\s*(?:source|\.)(?:\s|$)")
    nested_shell = re.compile(r"\b(?:bash|dash|ksh|zsh|sh)\b\s+-c(?:\s|$)")
    functions = tuple(
        keyword_name or posix_name
        for keyword_name, posix_name in function_header.findall(shell)
    )
    for raw_line in shell.splitlines():
        line = raw_line.strip()
        if (
            dynamic_command.search(line)
            or source_command.search(line)
            or nested_shell.search(line)
        ):
            return False
        if re.search(r"\b(?:set|trap|shopt)\b", line):
            if line not in expected_controls:
                return False
            controls.append(line)
    return functions == ("cleanup_sealed_framework",) and tuple(controls) == expected_controls


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
    held_loader = _workflow_held_framework_loader_is_semantic(block)
    inside_held_loader = False
    for raw_line in block.splitlines():
        if held_loader and raw_line == "  -e '":
            inside_held_loader = True
            continue
        if held_loader and inside_held_loader:
            if raw_line == "' \\":
                inside_held_loader = False
            continue
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
        if re.search(
            r"(?:^|[;&])\s*set\s+(?:\+e|\+o\s+errexit)(?:\s|;|$)",
            line,
        ):
            return True
        if re.search(r"(?<![&>])&\s*$", line):
            return True
    return False


def _cleanup_shell_control_surface_is_locked(run: str) -> bool:
    """Reject shell-control resets and function shadowing in the cleanup gate."""

    expected_trap = (
        "trap 'cleanup_status=$?; printf \"lcf-scratch-cleanup: assertion=%s\\n\" "
        '"${cleanup_assertion}" >&2; exit "${cleanup_status}"\' ERR'
    )
    expected_controls = (
        "set -euo pipefail",
        expected_trap,
        "shopt -s nullglob",
        "trap - ERR",
    )
    controls: list[str] = []
    function_definition = re.compile(
        r"(?:^|[;&|{(])\s*(?:function\s+)?[A-Za-z_][A-Za-z0-9_]*"
        r"\s*(?:\(\s*\))?\s*\{"
    )
    dynamic_command = re.compile(
        r"\b(?:eval|builtin|command|exec|enable|alias|unalias)\b"
    )
    source_command = re.compile(
        r"(?:^|[\s;&|{(!])(?:source|\.)(?=\s|$)"
    )
    nested_shell = re.compile(
        r"\b(?:bash|dash|ksh|zsh|sh)\b\s+-c(?:\s|$)"
    )
    for raw_line in run.splitlines():
        line = raw_line.strip()
        if (
            function_definition.search(line)
            or dynamic_command.search(line)
            or source_command.search(line)
            or nested_shell.search(line)
        ):
            return False
        if re.search(r"\b(?:set|trap|shopt)\b", line):
            if line not in expected_controls:
                return False
            controls.append(line)
    return tuple(controls) == expected_controls


def _post_build_cleanup_is_semantic(run: str) -> bool:
    """Require a fail-closed cleanup gate for both source lifecycle states."""

    prelude = (
        'set -euo pipefail\n'
        'cleanup_assertion="runner-temp-present"\n'
        "trap 'cleanup_status=$?; printf \"lcf-scratch-cleanup: assertion=%s\\n\" "
        '"${cleanup_assertion}" >&2; exit "${cleanup_status}"\' ERR\n'
        'test -n "${RUNNER_TEMP:-}"'
    )
    state_branch = 'if test -z "${LCF_REVIEWED_SOURCE_ROOT:-}"; then'
    unbound_assertion = 'test "${#runner_source_residue[@]}" -eq 0'
    branch_else = "\nelse\n"
    branch_end = "\nfi\ntrap - ERR"
    if (
        not run.startswith(prelude)
        or run.count("set -euo pipefail") != 1
        or run.count("lcf-scratch-cleanup: assertion=%s") != 1
        or run.count("shopt -s nullglob") != 1
        or run.count(state_branch) != 1
        or run.count(branch_else) != 1
        or run.count(branch_end) != 1
        or len(re.findall(r"(?m)^\s*if\s+", run)) != 1
        or "LCF_REVIEWED_BUILD_PYTHON" in run
        or "LCF_SOURCE_" in run
        or ":?reviewed source root" in run
        or _run_block_has_bypass(run)
        or not _cleanup_shell_control_surface_is_locked(run)
    ):
        return False

    branch_offset = run.find(state_branch)
    else_offset = run.find(branch_else, branch_offset)
    end_offset = run.find(branch_end, else_offset)
    unbound_offset = run.find(unbound_assertion, branch_offset)
    if not (
        0 <= branch_offset < unbound_offset < else_offset < end_offset
        and run.count(unbound_assertion) == 1
    ):
        return False

    unconditional_order = (
        "set -euo pipefail",
        "lcf-scratch-cleanup: assertion=%s",
        'test -n "${RUNNER_TEMP:-}"',
        'test "${runner_temp_real}" = "${RUNNER_TEMP}"',
        "shopt -s nullglob",
        'runner_toolchain_residue=("${RUNNER_TEMP}"/python-sidecar-toolchain-*)',
        'test "${#runner_toolchain_residue[@]}" -eq 0',
        'runner_producer_residue=("${RUNNER_TEMP}"/lcf-python-producer.*)',
        'test "${#runner_producer_residue[@]}" -eq 0',
        'runner_distribution_binding_residue=(\n'
        '  "${RUNNER_TEMP}"/lcf-python-installer.*\n'
        ')',
        'test "${#runner_distribution_binding_residue[@]}" -eq 0',
        'runner_source_residue=("${RUNNER_TEMP}"/lcf-reviewed-source.*)',
        state_branch,
    )
    unconditional_offsets = [run.find(marker) for marker in unconditional_order]
    if (
        any(offset < 0 for offset in unconditional_offsets)
        or unconditional_offsets != sorted(unconditional_offsets)
    ):
        return False

    bound_order = (
        'cleanup_assertion="source-root-prefix"',
        'readonly source_prefix="${RUNNER_TEMP}/lcf-reviewed-source."',
        'source_suffix="${LCF_REVIEWED_SOURCE_ROOT#"${source_prefix}"}"',
        "readonly source_suffix",
        'test "${LCF_REVIEWED_SOURCE_ROOT}" = "${source_prefix}${source_suffix}"',
        '[[ "${source_suffix}" =~ ^[A-Za-z0-9]{10}$ ]]',
        'test -d "${LCF_REVIEWED_SOURCE_ROOT}"',
        'test ! -L "${LCF_REVIEWED_SOURCE_ROOT}"',
        'source_root_real="$(cd "${LCF_REVIEWED_SOURCE_ROOT}" && /bin/pwd -P)"',
        'test "${source_root_real}" = "${LCF_REVIEWED_SOURCE_ROOT}"',
        'test "$(/usr/bin/stat -f \'%u\' "${LCF_REVIEWED_SOURCE_ROOT}")" = \\\n'
        '    "$(/usr/bin/id -u)"',
        'test "$(/usr/bin/stat -f \'%Lp\' "${LCF_REVIEWED_SOURCE_ROOT}")" = \\\n'
        '    "700"',
        'readonly provenance_env="${RUNNER_TEMP}/lcf-reviewed-source-provenance.env"',
        'test -f "${provenance_env}"',
        'test ! -L "${provenance_env}"',
        'test "$(/usr/bin/stat -f \'%u\' "${provenance_env}")" = \\\n'
        '    "$(/usr/bin/id -u)"',
        'test "${#runner_source_residue[@]}" -eq 2',
        'for source_residue in "${runner_source_residue[@]}"; do',
        '"${LCF_REVIEWED_SOURCE_ROOT}"|"${provenance_env}") ;;',
        '*) false ;;',
        'cleanup_assertion="source-root-enter"',
        '\n  cd "${LCF_REVIEWED_SOURCE_ROOT}"',
        'test ! -e desktop/generated/python-sidecar-build',
        'test ! -L desktop/generated/python-sidecar-build',
        'test "${#repo_random_residue[@]}" -eq 0',
    )
    bound_offsets = [run.find(marker, else_offset) for marker in bound_order]
    return (
        all(else_offset < offset < end_offset for offset in bound_offsets)
        and bound_offsets == sorted(bound_offsets)
        and run.count('runner_source_residue=("${RUNNER_TEMP}"/lcf-reviewed-source.*)')
        == 1
        and run.count('test "${#runner_source_residue[@]}" -eq 2') == 1
        and run.count('\n  cd "${LCF_REVIEWED_SOURCE_ROOT}"') == 1
    )


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
        "framework_verifier",
        "framework_verifier_tests",
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
    framework_verifier = str(inputs["framework_verifier"])
    framework_verifier_tests = str(inputs["framework_verifier_tests"])
    exact_git_checker = str(inputs["exact_git_checker"])
    exact_git_checker_tests = str(inputs["exact_git_checker_tests"])
    exact_node_installer = str(inputs["exact_node_installer"])
    python_packaging_tests = str(inputs["python_packaging_tests"])
    python_toolchain_lock = inputs["python_toolchain_lock"]
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

    python_lock = (
        python_toolchain_lock.get("python")
        if isinstance(python_toolchain_lock, Mapping)
        else None
    )
    expected_framework_security_lock = {
        "installRoot": PYTHON_INSTALL_ROOT,
        "interpreterRelativePath": PYTHON_INTERPRETER_RELATIVE_PATH,
        "interpreterSize": PYTHON_INTERPRETER_SIZE,
        "interpreterSha256": PYTHON_INTERPRETER_SHA256,
        "frameworkBinaryRelativePath": PYTHON_FRAMEWORK_BINARY_RELATIVE_PATH,
        "frameworkBinarySize": PYTHON_FRAMEWORK_BINARY_SIZE,
        "frameworkBinarySha256": PYTHON_FRAMEWORK_BINARY_SHA256,
        "frameworkCoreFingerprintExcludedPaths": list(
            PYTHON_FRAMEWORK_CORE_EXCLUDED_PATHS
        ),
        "frameworkCoreFingerprintSha256": (
            PYTHON_FRAMEWORK_CORE_FINGERPRINT_SHA256
        ),
        "reviewedBrokenSymlinks": list(PYTHON_REVIEWED_BROKEN_SYMLINKS),
    }
    distribution_lock = (
        python_lock.get("distribution")
        if isinstance(python_lock, Mapping)
        else None
    )
    if (
        not isinstance(python_lock, Mapping)
        or any(
            python_lock.get(key) != expected
            for key, expected in expected_framework_security_lock.items()
        )
        or not isinstance(distribution_lock, Mapping)
        or distribution_lock.get("installMethod")
        != PYTHON_DISTRIBUTION_INSTALL_METHOD
        or distribution_lock.get("frameworkComponent")
        != PYTHON_FRAMEWORK_COMPONENT_CONTRACT
    ):
        errors.append("reviewed Python framework security lock drifted")

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
        'HELD_CWD_EXEC_RUNNER = r"""',
        'PATH_CAPABILITY_EXEC_RUNNER = r"""',
        "os.fchdir(cwd_fd)",
        "signal.SIG_UNBLOCK",
        "os.execve(target, target_arguments, dict(os.environ))",
        "def _held_cwd_exec_command(",
        "def _open_held_source_directory(",
        "cwd_descriptor=backend_fd",
        "launcher_python=bootstrap_python",
        "cwd_descriptor=source.descriptor",
        "launcher_python=build_python",
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
        "def _materialize_private_regular_file(",
        "def _privatize_installed_tree(",
        "build._exchange_at(",
        "os.O_EXCL",
        '"Installed toolchain producer hardlink is writable"',
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
        "def _communicate_bounded(",
        "def _held_executable(",
        "def _revalidate_held_executable(",
        "REVIEWED_FRAMEWORK_CORE_EXCLUDED_PATHS = (",
        "def _reviewed_framework_security_contract(",
        "def _reviewed_framework_core_contract(",
        "def _verify_reviewed_framework_acl_seal(",
        "def _verify_reviewed_framework_seal(",
        "def _verify_reviewed_framework_core(",
        'python_lock["interpreterSize"]',
        'python_lock["interpreterSha256"]',
        'python_lock["frameworkBinarySize"]',
        'python_lock["frameworkBinarySha256"]',
        'python_lock.get("frameworkCoreFingerprintExcludedPaths")',
        'python_lock.get("frameworkCoreFingerprintSha256", "")',
        "selectors.DefaultSelector()",
        "inner_build_diagnostic=True",
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
        '"--install-reviewed-python"',
    )
    for marker in python_bootstrap_markers:
        if marker not in python_bootstrap:
            errors.append(f"exact Python toolchain bootstrap missing {marker!r}")
    if not _python_exec_runner_signal_contract_is_semantic(python_bootstrap):
        errors.append("exact Python held-cwd launcher signal contract drifted")
    if not _python_reviewed_framework_security_is_semantic(python_bootstrap):
        errors.append("exact reviewed Python framework security closure drifted")
    if not _python_framework_fingerprint_exclusions_are_semantic(build_script):
        errors.append(
            "exact reviewed Python framework fingerprint exclusion closure drifted"
        )
    if not _reviewed_framework_node_verifier_is_semantic(
        framework_verifier,
        framework_verifier_tests,
    ):
        errors.append("exact reviewed Python framework Node verifier closure drifted")
    if (
        python_bootstrap.count("subprocess.Popen(") != 1
        or python_bootstrap.count("subprocess.run(") != 1
        or build_script.count("subprocess.Popen(") != 2
        or "subprocess.run(" in build_script
        or "subprocess.run(" in audit_script
        or "subprocess.Popen(" in audit_script
    ):
        errors.append("Python sidecar owned external-process inventory drifted")
    for marker in (
        "class _BoundedFrozenLogCollector:",
        "stdout=subprocess.PIPE",
        "log_collector.start()",
        "log_collector.assert_healthy()",
        "log_collector.finish()",
        '"Frozen sidecar log exceeded its size bound"',
    ):
        if marker not in build_script:
            errors.append(f"frozen sidecar bounded log owner missing {marker!r}")
    if (
        build_script.count("log_collector.start()") != 1
        or build_script.count("log_collector.finish()") != 6
    ):
        errors.append("frozen sidecar bounded log owner lifecycle drifted")
    if "stdout=log_handle" in build_script:
        errors.append("frozen sidecar output bypasses its bounded owner")
    exact_toolchain_build = _source_block(
        python_bootstrap,
        "def build_with_exact_toolchain(",
        "\ndef _parser()",
    )
    producer_materializer = _source_block(
        python_bootstrap,
        "def _materialize_private_regular_file(",
        "\ndef _privatize_installed_tree(",
    )
    producer_privatizer = _source_block(
        python_bootstrap,
        "def _privatize_installed_tree(",
        "\ndef _inventory_installed_tree(",
    )
    strict_installed_inventory = _source_block(
        python_bootstrap,
        "def _inventory_installed_tree(",
        "\ndef _chmod_installed_tree_read_only(",
    )
    reviewed_python_install = _source_block(
        python_bootstrap,
        "def install_reviewed_python(",
        "\ndef build_with_exact_toolchain(",
    )
    exact_installer_commands = (
        '''"/usr/sbin/pkgutil",
                                "--check-signature",
                                str(package_path),''',
        '''"/usr/sbin/spctl",
                                "--assess",
                                "--type",
                                "install",
                                "--verbose=4",
                                str(package_path),''',
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
        or exact_toolchain_build.count("_privatize_installed_tree(") != 2
        or exact_toolchain_build.count("verify_installed_tree(") != 4
        or exact_toolchain_build.count("_revalidate_source_seal(") < 6
        or exact_toolchain_build.count("pass_fds=child_fds") != 1
        or exact_toolchain_build.count('label="Exact Python sidecar inner build"')
        != 1
        or reviewed_python_install.count("prefix=INSTALLER_ROOT_PREFIX") != 1
        or reviewed_python_install.count("_revalidate_bound_file(") != 3
        or reviewed_python_install.count("_revalidate_source_seal(") < 3
        or reviewed_python_install.count(
            "path_capabilities=distribution_path_capabilities"
        )
        != 2
        or exact_toolchain_build.count(
            "path_capabilities=toolchain_path_capabilities"
        )
        != 6
        or "(capability.descriptor, str(capability.path), False)"
        not in reviewed_python_install
        or "(cache_fd, str(cache_root), False)"
        not in reviewed_python_install
        or "(capability.descriptor, str(capability.path), False)"
        not in exact_toolchain_build
        or "(cache_fd, str(cache_root), False)"
        not in exact_toolchain_build
        or any(
            reviewed_python_install.count(command) != 1
            for command in exact_installer_commands
        )
        or python_bootstrap.count('"/usr/sbin/spctl"') != 1
        or '"/usr/sbin/installer"' in python_bootstrap
        or '"/usr/bin/sudo"' in python_bootstrap
        or "LAUNCHER_NAME_INSTALLER_REBIND" in python_bootstrap
        or "LAUNCHER_NAME_INSTALLER_PENDING_SEAL" in python_bootstrap
        or "setup.sh" in reviewed_python_install
    ):
        errors.append("exact Python toolchain bootstrap/seal closure drifted")

    producer_privatization_markers = (
        "os.O_RDWR",
        "os.O_CREAT",
        "os.O_EXCL",
        "os.O_NOFOLLOW",
        "os.fsync(private_descriptor)",
        "with build._defer_publish_signals():",
        "build._exchange_at(",
        "private_cleanup_binding",
        "_node_binding(displaced)",
        "_node_binding(os.fstat(source_descriptor))",
        "os.unlink(private_name, dir_fd=directory_descriptor)",
        "os.fsync(directory_descriptor)",
        "if before.st_nlink != 1:",
        "if mode & 0o022:",
        "desired_mode = 0o700 if mode & 0o100 else 0o600",
        "os.fchmod(child, desired_mode)",
        "_materialize_private_regular_file(",
        "_symlink_identity(after) != _symlink_identity(before)",
        "tuple(sorted(os.listdir(directory_descriptor))) != names",
    )
    if (
        any(
            marker not in producer_materializer + producer_privatizer
            for marker in producer_privatization_markers
        )
        or producer_materializer.count("build._exchange_at(") != 1
        or "os.replace(" in producer_materializer
        or strict_installed_inventory.count("before.st_nlink != 1") != 2
        or "mode & 0o022" not in strict_installed_inventory
    ):
        errors.append("exact Python toolchain producer privatization drifted")
    if not _python_producer_privatization_is_semantic(python_bootstrap):
        errors.append(
            "exact Python toolchain producer privatization AST closure drifted"
        )
    producer_order = (
        'label="Hash-locked Python bootstrap install"',
        "_privatize_installed_tree(bootstrap_root, bootstrap_fd, build)",
        "bootstrap_seal = seal_installed_tree(",
        'label="Complete hash-locked Python build install"',
        "_privatize_installed_tree(build_root, build_fd, build)",
        "installed_seal = seal_installed_tree(",
    )
    search_offset = 0
    producer_offsets: list[int] = []
    for marker in producer_order:
        offset = exact_toolchain_build.find(marker, search_offset)
        producer_offsets.append(offset)
        if offset >= 0:
            search_offset = offset + len(marker)
    if any(offset < 0 for offset in producer_offsets):
        errors.append("exact Python toolchain producer privatization order drifted")

    for marker in (
        "test_real_venv_seal_verify_execute_and_restore_for_exact_cleanup",
        "test_installed_tree_seal_rejects_same_version_content_drift",
        "test_installed_tree_privatization_normalizes_modes_and_breaks_hardlinks",
        "test_installed_tree_privatization_canonicalizes_producer_file_modes",
        "test_installed_tree_privatization_breaks_two_internal_hardlinks",
        "test_installed_tree_privatization_rejects_writable_external_hardlink",
        "test_installed_tree_privatization_exchange_failure_removes_private_copy",
        "test_installed_tree_privatization_post_exchange_failure_removes_old_alias",
        "test_installed_tree_seal_rejects_regular_hardlink_without_privatization",
        "test_installed_tree_seal_rejects_root_replacement",
        "test_held_toolchain_root_restores_seal_and_has_no_residue",
        "test_held_toolchain_root_replacement_is_preserved_and_cleanup_fails_closed",
        "test_held_toolchain_root_signal_cleanup_has_no_residue",
        "test_reviewed_framework_seal_accepts_real_python_org_modes_only_after_seal",
        "test_reviewed_framework_core_fingerprint_rejects_unlisted_stdlib_drift",
        "test_reviewed_framework_acl_seal_reads_acl_entries_not_mode_suffix",
        "test_reviewed_framework_seal_rejects_dependency_alias_and_layout_drift",
        "test_install_root_fingerprint_excludes_only_exact_dynamic_paths",
        "test_install_root_fingerprint_rejects_unsafe_dynamic_exclusions",
        "test_reviewed_python_verification_uses_only_audit_commands_and_cleans_root",
        "test_reviewed_python_distribution_audit_failure_never_runs_observer",
        "test_reviewed_python_launcher_drift_is_rejected_before_observer",
        "test_reviewed_python_package_or_source_drift_cleans_private_root",
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
        "test_held_cwd_exec_runner_uses_renamed_inode_and_exact_fd_allowlist",
        "test_held_cwd_exec_runner_restores_real_signal_termination",
        "test_held_cwd_exec_runner_rejects_bad_cwd_and_target_drift",
        "test_run_owned_process_uses_fixed_held_cwd_spawn_contract",
        "test_path_capability_exec_runner_rejects_replaced_child_input",
        "test_owned_process_rejects_path_capability_without_held_cwd",
        "test_owned_process_rejects_regular_keep_fd_metadata_drift",
        "test_held_executable_rejects_launcher_name_replacement",
        "test_held_executable_still_rejects_group_writable_framework_launcher",
        "test_held_executable_rejects_hardlink_count_drift",
        "test_held_executable_terminal_revalidation_rejects_bytes_drift",
        "test_held_executable_rejects_privileged_mode_drift",
        "test_held_executable_combines_primary_and_terminal_failure",
        "test_inner_build_fixed_diagnostic_is_bounded_and_does_not_leak_stderr",
        "test_inner_build_rejects_unreviewed_diagnostic_enum_without_leaking",
        "test_inner_build_diagnostic_writer_emits_only_fixed_enums",
        "test_inner_build_diagnostic_reader_rejects_a_retained_writer_without_blocking",
        "test_owned_process_output_bound_terminates_without_echoing_payload",
        "test_owned_process_timeout_stops_and_reaps_the_exact_group",
        "test_process_group_cleanup_reaps_an_already_exited_leader",
        "test_exact_git_archive_pipe_reader_has_a_total_deadline",
        "test_pyinstaller_command_rejects_exec_target_identity_drift",
        "test_source_inventory_accepts_one_consistent_directory_link_model",
        "test_darwin_apfs_directory_link_count_includes_immediate_files",
        "test_source_inventory_rejects_mixed_directory_link_models",
        "test_remove_tree_restores_owner_write_before_directory_quarantine",
        "test_scratch_root_final_gate_preserves_a_quarantine_replacement",
        "test_build_lifecycle_classifies_source_materialization_and_clean_cleanup",
        "test_non_build_primary_keeps_its_fixed_stage_through_cleanup_failure",
    ):
        if marker not in python_packaging_tests:
            errors.append(f"exact Python toolchain tests missing {marker!r}")

    for forbidden in (
        'cwd=Path(f"/dev/fd/{source.descriptor}") / "backend"',
        "preexec_fn=",
        "shell=True",
    ):
        if forbidden in python_bootstrap:
            errors.append(
                f"exact Python held-cwd launcher retained {forbidden!r}"
            )
    if (
        python_bootstrap.count("cwd_descriptor=source.descriptor") != 7
        or python_bootstrap.count("cwd_descriptor=backend_fd") != 1
        or python_bootstrap.count("inner_build_diagnostic=True") != 1
    ):
        errors.append("exact Python held-cwd launcher call closure drifted")

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
                "const EXPECTED_PYTHON_EXECUTION_CLOSURE = Object.freeze({",
                "const EXPECTED_FRAMEWORK_CORE_EXCLUDED_PATHS = Object.freeze([",
                "const EXPECTED_FRAMEWORK_CORE_SHA256 =",
                "const EXPECTED_PYTHON_INSTALL_METHOD =",
                "const EXPECTED_FRAMEWORK_COMPONENT = Object.freeze({",
                "const executionClosure = {",
                "!sameJson(executionClosure, EXPECTED_PYTHON_EXECUTION_CLOSURE)",
                "python.frameworkCoreFingerprintExcludedPaths,",
                "EXPECTED_FRAMEWORK_CORE_EXCLUDED_PATHS",
                "python.frameworkCoreFingerprintSha256 !== EXPECTED_FRAMEWORK_CORE_SHA256",
                "const distribution = assertExactKeys(",
                '"frameworkComponent",',
                "const frameworkComponent = assertExactKeys(",
                "Object.keys(EXPECTED_FRAMEWORK_COMPONENT)",
                "const componentSizeFields = [",
                "const componentHashFields = [",
                "!sameJson(frameworkComponent, EXPECTED_FRAMEWORK_COMPONENT)",
                "distribution.installMethod !== EXPECTED_PYTHON_INSTALL_METHOD",
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
    expected_execution_closure = {
        "interpreterRelativePath": PYTHON_INTERPRETER_RELATIVE_PATH,
        "interpreterSize": PYTHON_INTERPRETER_SIZE,
        "interpreterSha256": PYTHON_INTERPRETER_SHA256,
        "frameworkBinaryRelativePath": PYTHON_FRAMEWORK_BINARY_RELATIVE_PATH,
        "frameworkBinarySize": PYTHON_FRAMEWORK_BINARY_SIZE,
        "frameworkBinarySha256": PYTHON_FRAMEWORK_BINARY_SHA256,
    }

    def compact_javascript(document: str) -> str:
        return re.sub(r"\s+", "", document)

    def expected_frozen_object(name: str, values: Mapping[str, Any]) -> str:
        return (
            f"const{name}=Object.freeze({{"
            + ",".join(
                f"{key}:{json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"
                for key, value in values.items()
            )
            + "});"
        )

    reviewed_before_pack_constants = (
        (
            _source_block(
                formal_before_pack,
                "const EXPECTED_PYTHON_EXECUTION_CLOSURE = Object.freeze({",
                "\nconst EXPECTED_FRAMEWORK_CORE_EXCLUDED_PATHS",
            ),
            expected_frozen_object(
                "EXPECTED_PYTHON_EXECUTION_CLOSURE",
                expected_execution_closure,
            ),
        ),
        (
            _source_block(
                formal_before_pack,
                "const EXPECTED_FRAMEWORK_CORE_EXCLUDED_PATHS = Object.freeze([",
                "\nconst EXPECTED_FRAMEWORK_CORE_SHA256",
            ),
            "constEXPECTED_FRAMEWORK_CORE_EXCLUDED_PATHS=Object.freeze(["
            + ",".join(
                json.dumps(path, separators=(",", ":"))
                for path in PYTHON_FRAMEWORK_CORE_EXCLUDED_PATHS
            )
            + "]);",
        ),
        (
            _source_block(
                formal_before_pack,
                "const EXPECTED_FRAMEWORK_CORE_SHA256 =",
                "\nconst EXPECTED_PYTHON_INSTALL_METHOD",
            ),
            "constEXPECTED_FRAMEWORK_CORE_SHA256="
            + json.dumps(PYTHON_FRAMEWORK_CORE_FINGERPRINT_SHA256)
            + ";",
        ),
        (
            _source_block(
                formal_before_pack,
                "const EXPECTED_PYTHON_INSTALL_METHOD =",
                "\nconst EXPECTED_FRAMEWORK_COMPONENT",
            ),
            "constEXPECTED_PYTHON_INSTALL_METHOD="
            + json.dumps(PYTHON_DISTRIBUTION_INSTALL_METHOD)
            + ";",
        ),
        (
            _source_block(
                formal_before_pack,
                "const EXPECTED_FRAMEWORK_COMPONENT = Object.freeze({",
                "\nconst EXPECTED_FROZEN_CHECKS",
            ),
            expected_frozen_object(
                "EXPECTED_FRAMEWORK_COMPONENT",
                PYTHON_FRAMEWORK_COMPONENT_CONTRACT,
            ),
        ),
    )
    if any(
        compact_javascript(observed) != expected
        for observed, expected in reviewed_before_pack_constants
    ):
        errors.append(
            "formal/engineering beforePack Python toolchain reviewed constants drifted"
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
        "toolchainMutationCases",
        "rejects reviewed Python toolchain mutation: $name",
        "missing Python field",
        "framework core exclusions",
        "install method",
        "missing framework component field",
        "framework component size",
        "framework component hash",
        "framework component mode",
        "framework component package",
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
        "def _verify_held_bundle_candidate(",
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
        or build_sidecar_source.count("_verify_held_bundle_candidate(") != 2
        or build_sidecar_source.count("bundle_descriptor=bundle_capability.descriptor")
        != 2
        or build_sidecar_source.count("_publish_owned_bundle(") != 1
        or build_sidecar_source.count("def final_verifier(candidate: Path)") != 1
        or build_sidecar_source.count(
            "audit.audit_bundle(\n                candidate,"
        )
        != 1
        or not _python_final_bundle_verifier_is_semantic(build_script)
    ):
        errors.append(
            "Python sidecar held candidate producer/consumer/publish chain drifted"
        )
    for marker in (
        "_validate_bundle_capability(\n                capability,",
        "os.close(bundle.descriptor)",
        "os.close(bundle.parent_descriptor)",
        'cleanup_stage = "build-root-quarantine"',
        "parent_descriptor=capability.scratch_parent_descriptor",
        'cleanup_stage = "scratch-root-quarantine"',
        "parent_descriptor=capability.destination_parent_descriptor",
    ):
        if marker not in scratch_cleanup_source:
            errors.append(
                f"Python sidecar held candidate cleanup contract missing {marker!r}"
            )
    for marker in (
        "test_pyinstaller_first_open_replacement_poison_closes_and_preserves",
        "test_bundle_capability_precedes_producer_and_fd_consumers_ignore_root_aba",
        "test_publish_reuses_the_held_bundle_candidate",
        "test_final_bundle_verifier_binds_pre_and_post_publish_candidate_paths",
        'in {"dist", "work", "pyinstaller-config", "tmp", "lcf-service"}',
        "held_candidate=capability",
        'assert observed == ["reviewed", "reviewed"]',
        "test_bundle_ownership_transfers_only_after_post_acquisition_validation",
        "assert scratch.bundle is None",
        "assert sentinel_descriptor == bundle_descriptor",
        "test_pyinstaller_command_inherits_source_and_all_private_output_fds",
        "test_pyinstaller_runner_validates_canonical_roots_and_closes_child_fds",
        "test_native_tool_rejects_an_fd_child_path_for_external_tools",
        "test_native_tool_uses_a_held_canonical_root",
        "test_native_input_exec_runner_binds_the_child_opened_target",
        "test_held_native_inventory_never_enumerates_a_replacement_root",
        "test_frozen_live_log_collector_bounds_output_before_owner_cleanup",
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
        "source_root = os.path.abspath(os.path.normpath(sys.argv.pop(1)))",
        "bundle_root = os.path.abspath(os.path.normpath(sys.argv.pop(1)))",
        "observed = os.lstat(capability_root)",
        '''probe = os.open(
        capability_root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )''',
        "os.set_inheritable(capability_descriptor, False)",
        'os.environ["LCF_PYINSTALLER_SOURCE_FD"] = str(source_descriptor)',
        'os.environ["LCF_PYINSTALLER_SOURCE_ROOT"] = source_root',
    ):
        if build_script.count(marker) != 1:
            errors.append(f"PyInstaller canonical capability runner missing {marker!r}")
    for forbidden in (
        'source_root = "/dev/fd/" + str(source_descriptor)',
        "def capability_popen(*args, **kwargs):",
        "subprocess.Popen = capability_popen",
    ):
        if forbidden in build_script:
            errors.append(
                f"PyInstaller canonical capability runner retained {forbidden!r}"
            )

    auditor_build_boundary = _source_block(
        audit_script,
        "def _reviewed_build_boundary(",
        "\ndef _git_provenance_output(",
    )
    auditor_held_git_boundary = _source_block(
        audit_script,
        "def _held_git_boundary(",
        "\ndef _git_provenance_output(",
    )
    auditor_git_output = _source_block(
        audit_script,
        "def _git_provenance_output(",
        "\ndef _git_tree_inventory_sha256(",
    )
    auditor_git_inventory = _source_block(
        audit_script,
        "def _git_tree_inventory_sha256(",
        "\ndef _validate_repository_provenance(",
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
        "with _held_git_boundary(repository_root)",
        "build._validate_local_git_configuration(",
        "repository_descriptor=repository_descriptor",
        "git_descriptor=git_descriptor",
        "build._validate_git_info_overrides(repository_root=repository_root)",
        "return build._git_bytes(",
        "return build._git_output(",
    ):
        if marker not in auditor_git_output:
            errors.append(f"standalone Python auditor Git boundary missing {marker!r}")
    if (
        auditor_git_output.count(
            "repository_descriptor=repository_descriptor"
        )
        != 3
        or auditor_git_output.count("git_descriptor=git_descriptor") != 3
    ):
        errors.append("standalone Python auditor Git descriptor threading drifted")
    for marker in (
        "repository_root.resolve(strict=True) != repository_root",
        "os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC",
        'os.open(\n            ".git"',
        "build._stat_metadata(os.fstat(repository_descriptor))",
        "build._stat_metadata(os.fstat(git_descriptor))",
        "os.close(descriptor)",
    ):
        if marker not in auditor_held_git_boundary:
            errors.append(
                f"standalone Python auditor held Git capability missing {marker!r}"
            )
    for marker in (
        "with _held_git_boundary(repository_root)",
        "build._validate_local_git_configuration(",
        "build._git_output(",
        "build._repository_tree_inventory(",
        "repository_descriptor=repository_descriptor",
        "git_descriptor=git_descriptor",
    ):
        if marker not in auditor_git_inventory:
            errors.append(
                f"standalone Python auditor Git inventory binding missing {marker!r}"
            )
    if (
        auditor_git_inventory.count(
            "repository_descriptor=repository_descriptor"
        )
        != 3
        or auditor_git_inventory.count("git_descriptor=git_descriptor") != 3
    ):
        errors.append(
            "standalone Python auditor Git inventory descriptor threading drifted"
        )
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
    if not _python_repository_gate_is_semantic(build_script):
        errors.append("Python sidecar exact repository gate is not descriptor-bound")
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
    real_renderer_builder_markers = (
        "const viteImplementation = await import(",
        'path.join(repositoryRoot, "web", "node_modules", "vite", "dist", "node", "index.js")',
        "const reactPluginModule = await import(",
        '          "@vitejs",\n          "plugin-react",\n          "dist",\n          "index.js"',
        "      viteImplementation,",
        "      reactPluginFactory: reactPluginModule.default,",
        'expect(outputText).toContain("reviewed-renderer-marker")',
        'expect(outputText).not.toContain("transient-renderer-marker")',
    )
    for marker in real_renderer_builder_markers:
        if renderer_packaging_tests.count(marker) != 1:
            errors.append(
                f"renderer packaging tests real Vite/ABA injection missing {marker!r}"
            )
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
        "producer output privatization",
        "`O_NOFOLLOW`",
        "`0600`",
        "`0700`",
        "`nlink > 1`",
        "`O_EXCL`",
        "atomic exchange",
        "`RENAME_SWAP`",
        "`RENAME_EXCHANGE`",
        "`nlink == 1`",
        "group/world-writable hardlink",
        "technical result 在 fresh exact-head source/assembly 完成前仍是 `not-run`",
        "<!-- w02-pr21-fifth-remediation-authority: "
        "source=c04fe9fce2bc2f0f4350e080f7f02c44699c975d,"
        "parent=c2be665f5832c15064cae87c694a782e51351e7c,"
        "tree=2f8b3aceb4caa2d71537cd51c3b3b985c55a3db5,"
        "assembly-run=31454826263,assembly-job=93666344718,"
        "source-run=31454826261,source-job=93666344561,"
        "container-run=31454826243,result=fail -->",
        "## 第五次 remediation 技术执行：`fail` / `superseded`",
        "## 第六次 remediation technical candidate：`not-run`",
        "尚未调用被测\nproduct cleanup",
        "这是高置信代码/时序归因，不是 raw log 直接输出的\n"
        "binding root cause",
        "rebind/fixture focused tests `18 passed`",
        "packaging corpus `545 passed / 2 skipped`",
        "backend source suite `809 passed / 3 skipped`",
        "pre-1 policy/checker corpus `211 tests`",
        "| local validation date | `2026-08-11` |",
        "| local baseline | `HEAD c04fe9fce2bc2f0f4350e080f7f02c44699c975d` + 当前未提交的 `14` 个 tracked file bytes",
        "| local environment | `Linux 6.18.35 x86_64`；CPython `3.12.13` |",
        "不是 committed exact-head\nActions、macOS framework installer 或 packaged App launch/runtime evidence",
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
    if shell_values != ["bash"] * 12:
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
        "Build and audit locked Python sidecar": EXPECTED_PYTHON_BUILD_RUN,
        "Validate Python scratch cleanup": EXPECTED_POST_BUILD_CLEANUP_RUN,
        "Validate Python sidecar provenance": EXPECTED_POST_BUILD_PROVENANCE_RUN,
    }
    for step_name, expected_run in expected_step_runs.items():
        if steps_by_name.get(step_name, {}).get("run") != expected_run:
            errors.append(f"workflow critical step {step_name!r} drifted")
    expected_step_run_sha256 = {
        "Bind locked framework verifier Node": (
            EXPECTED_FRAMEWORK_NODE_BIND_RUN_SHA256
        ),
        "Provision reviewed build Python without executing it": (
            EXPECTED_FRAMEWORK_PROVISION_RUN_SHA256
        ),
        "Seal reviewed build Python framework": (
            EXPECTED_FRAMEWORK_SEAL_RUN_SHA256
        ),
        "Run focused Python sidecar lifecycle tests": (
            EXPECTED_LIFECYCLE_TEST_RUN_SHA256
        ),
    }
    for step_name, expected_digest in expected_step_run_sha256.items():
        run = steps_by_name.get(step_name, {}).get("run", "")
        if hashlib.sha256(run.encode("utf-8")).hexdigest() != expected_digest:
            errors.append(f"workflow critical step {step_name!r} drifted")
    framework_setup_order = (
        "Set up locked Node",
        "Bind locked framework verifier Node",
        "Provision reviewed build Python without executing it",
        "Seal reviewed build Python framework",
        "Bind exact source provenance",
    )
    framework_setup_offsets = [
        next(
            (
                index
                for index, step in enumerate(workflow_steps)
                if step.get("name") == name
            ),
            -1,
        )
        for name in framework_setup_order
    ]
    framework_seal_step = steps_by_name.get(
        "Seal reviewed build Python framework",
        {},
    )
    framework_provision_step = steps_by_name.get(
        "Provision reviewed build Python without executing it",
        {},
    )
    if (
        framework_setup_offsets != sorted(framework_setup_offsets)
        or any(offset < 0 for offset in framework_setup_offsets)
        or hashlib.sha256(
            framework_seal_step.get("run", "").encode("utf-8")
        ).hexdigest()
        != EXPECTED_FRAMEWORK_SEAL_RUN_SHA256
        or framework_seal_step.get("document", "").count("        shell: bash")
        != 1
    ):
        errors.append("workflow reviewed Python setup/seal/provenance order drifted")
    if not _workflow_python_producer_is_semantic(
        framework_provision_step.get("run", "")
    ):
        errors.append("workflow reviewed Python no-exec producer closure drifted")
    if not _workflow_python_seal_is_semantic(
        framework_seal_step.get("run", "")
    ):
        errors.append("workflow reviewed Python no-follow seal closure drifted")
    focused_step_name = "Run focused Python sidecar lifecycle tests"
    focused_run = steps_by_name.get(focused_step_name, {}).get("run", "")
    if (
        not workflow_steps
        or workflow_steps[-1].get("name") != focused_step_name
        or any(
            marker not in focused_run
            for marker in (
                "export PYTHONDONTWRITEBYTECODE=1",
                'readonly lifecycle_prefix="${RUNNER_TEMP}/lcf-python-lifecycle."',
                '/usr/bin/mktemp -d "${lifecycle_prefix}XXXXXXXXXX"',
                'chmod 0700 "${lifecycle_root}"',
                "trap cleanup_lifecycle_root EXIT",
                "/usr/bin/env -i \\",
                '"${LCF_REVIEWED_BUILD_PYTHON}" -I -S -m venv \\',
                '"${lifecycle_root}/venv/bin/python" -I -m pip \\',
                "--isolated install \\",
                "--no-deps \\",
                "--no-compile \\",
                "--only-binary=:all: \\",
                "--require-hashes \\",
                "-r backend/packaging/build-requirements.lock",
                'UV="${lifecycle_root}/venv/bin/uv"',
                "/usr/bin/make ci-python-install \\",
                "backend/.venv/bin/python -B -m pytest -q",
                "tests/backend/test_python_sidecar_packaging.py",
            )
        )
        or "python -B -m pip install" in focused_run
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
        or not _post_build_cleanup_is_semantic(cleanup_step.get("run", ""))
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
        "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \\\n    -I -S -c 'import os,sys; print(os.path.realpath(sys.executable))'",
        '"${bootstrap_python}" -I -S -c '
        "'import platform; print(platform.python_version())'",
        '"${bootstrap_python}" -I -S - "${reviewed_source}" <<\'PY\'',
        'cd "${reviewed_source}"',
        '"${bootstrap_python}" -I -S tools/check_exact_git_provenance.py \\',
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
        "node-version: \"22.23.2\"",
        "if: github.repository == 'fredgnr/local-context-forge'",
    ):
        if workflow.count(marker) != 1:
            errors.append(f"workflow exact-source/tool contract missing {marker!r}")
    if (
        workflow.count('test "$(uname -m)" = "arm64"') != 2
        or "actions/setup-python@" in workflow
        or "python-version:" in workflow
    ):
        errors.append("workflow no-Python producer action boundary drifted")
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
        workflow.count('${GITHUB_ENV}') != 8
        or workflow.count('>> "${GITHUB_ENV}"') != 8
        or canonical_workflow_identifiers.count("GITHUB_ENV") != 8
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
    for value, expected_count in (
        (PYTHON_ARCHIVE_URL, 2),
        (PYTHON_HASHES_URL, 2),
        (PYTHON_ARCHIVE_SHA256, 3),
        (PYTHON_HASHES_SHA256, 2),
        (PYTHON_HASH_MANIFEST_ENTRY, 1),
    ):
        if "\n".join(run_blocks).count(value) != expected_count:
            errors.append("workflow Python source lock drifted")

    python_source_blocks = [
        block
        for block in run_blocks
        if EXPECTED_PYTHON_RUNNER_BINDING in block
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
    python_source_block = ""
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
        if python_source_block.count(marker) != 1:
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
    if (
        "actions/setup-python@" in formal_build
        or "python-version:" in formal_build
    ):
        errors.append("formal workflow no-Python producer action boundary drifted")
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
        formal_build.count('${GITHUB_ENV}') != 10
        or formal_build.count('>> "${GITHUB_ENV}"') != 10
        or _canonical_identifier_text(formal_build).count("GITHUB_ENV") != 10
    ):
        errors.append("formal workflow GITHUB_ENV provenance export surface drifted")
    formal_steps = _workflow_steps(formal_workflow, "build")
    formal_step_names = [step.get("name", "") for step in formal_steps]
    formal_critical_steps = (
        "Set up locked Node",
        "Bind locked framework verifier Node",
        "Provision reviewed build Python without executing it",
        "Seal reviewed build Python framework",
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
    formal_node_bind_step = formal_steps_by_name.get(
        "Bind locked framework verifier Node",
        {},
    )
    if (
        hashlib.sha256(
            formal_node_bind_step.get("run", "").encode("utf-8")
        ).hexdigest()
        != EXPECTED_FRAMEWORK_NODE_BIND_RUN_SHA256
        or formal_node_bind_step.get("document", "").count(
            "        shell: bash"
        )
        != 1
    ):
        errors.append("formal workflow reviewed framework verifier Node step drifted")
    formal_provision_step = formal_steps_by_name.get(
        "Provision reviewed build Python without executing it",
        {},
    )
    if (
        hashlib.sha256(
            formal_provision_step.get("run", "").encode("utf-8")
        ).hexdigest()
        != EXPECTED_FRAMEWORK_PROVISION_RUN_SHA256
        or formal_provision_step.get("document", "").count(
            "        shell: bash"
        )
        != 1
        or not _workflow_python_producer_is_semantic(
            formal_provision_step.get("run", "")
        )
    ):
        errors.append("formal workflow reviewed Python no-exec producer step drifted")
    formal_seal_step = formal_steps_by_name.get(
        "Seal reviewed build Python framework",
        {},
    )
    if (
        hashlib.sha256(
            formal_seal_step.get("run", "").encode("utf-8")
        ).hexdigest()
        != EXPECTED_FRAMEWORK_SEAL_RUN_SHA256
        or formal_seal_step.get("document", "").count("        shell: bash") != 1
        or not _workflow_python_seal_is_semantic(
            formal_seal_step.get("run", "")
        )
    ):
        errors.append("formal workflow reviewed Python framework seal step drifted")
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
        or not _post_build_cleanup_is_semantic(
            formal_cleanup_step.get("run", "")
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
        "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \\\n    -I -S -c 'import os,sys; print(os.path.realpath(sys.executable))'",
        '"${bootstrap_python}" -I -S -c '
        "'import platform; print(platform.python_version())'",
        '"${bootstrap_python}" -I -S - "${reviewed_source}" <<\'PY\'',
        'cd "${reviewed_source}"',
        '"${bootstrap_python}" -I -S tools/check_exact_git_provenance.py \\',
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
    producer_document = framework_provision_step.get("document", "")
    workflow_launch_surface = (
        workflow.replace(producer_document, "", 1)
        if producer_document and workflow.count(producer_document) == 1
        else workflow
    )
    launch_surface = (
        workflow_launch_surface
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
    governance_current_markers = (
        (
            "status",
            status,
            (
                "nine remediation attempts `fail` / `superseded`",
                "tenth exact candidate `not-run`",
            ),
        ),
        (
            "todo",
            todo,
            (
                "nine remediation attempts `fail` / `superseded`",
                "tenth exact candidate `not-run`",
            ),
        ),
        (
            "traceability",
            trace,
            (
                "first through ninth remediations failed and superseded",
                "tenth exact candidate not-run",
            ),
        ),
        (
            "iteration",
            iteration,
            (
                "第一次至第九次 remediation technical attempts 均为 "
                "`fail` / `superseded`",
                "第十 exact candidate `not-run`",
            ),
        ),
    )
    for label, document, markers in governance_current_markers:
        for marker in markers:
            if marker not in document:
                errors.append(
                    f"W02 current governance {label} missing {marker!r}"
                )
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
        "tools/{check_exact_git_provenance.py,exact_node_install.cjs,verify_reviewed_python_framework.cjs,bootstrap_python_sidecar.py,build_python_sidecar.py,audit_python_sidecar.py}",
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

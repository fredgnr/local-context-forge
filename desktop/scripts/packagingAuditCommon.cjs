"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const APP_ID = "dev.localcontextforge.engineering-smoke";
const PRODUCT_NAME = "Local Context Forge Engineering Smoke";
const REPOSITORY = "fredgnr/local-context-forge";
const DISTRIBUTION_MARKER = "UNOFFICIAL";
const MANIFEST_SCHEMA_NAME = "engineering-smoke-manifest.schema.json";
const MANIFEST_KIND = "local-context-forge-engineering-smoke-distribution";
const MANIFEST_RELATIVE_PATH =
  "Contents/Resources/engineering-smoke/distribution.json";
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const EXPECTED_PYTHON_BUILD_TOOLS = Object.freeze({
  altgraphVersion: "0.17.4",
  macholibVersion: "1.16.3",
  packagingVersion: "26.2",
  pyinstallerVersion: "6.21.0",
  pyinstallerHooksContribVersion: "2026.6",
  setuptoolsVersion: "83.0.0",
  uvVersion: "0.11.29"
});

const MANIFEST_KEYS = Object.freeze([
  "$schema",
  "schemaVersion",
  "kind",
  "distribution",
  "application",
  "target",
  "source",
  "assembly",
  "components",
  "security",
  "capabilities",
  "validation"
]);

class EngineeringSmokeAuditError extends Error {
  constructor(message) {
    super(message);
    this.name = "EngineeringSmokeAuditError";
  }
}

function fail(message) {
  throw new EngineeringSmokeAuditError(message);
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function compareCodePoints(left, right) {
  const leftPoints = Array.from(left, (value) => value.codePointAt(0));
  const rightPoints = Array.from(right, (value) => value.codePointAt(0));
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
    if (leftPoints[index] !== rightPoints[index]) {
      return leftPoints[index] - rightPoints[index];
    }
  }
  return leftPoints.length - rightPoints.length;
}

function sortJson(value) {
  if (Array.isArray(value)) {
    return value.map(sortJson);
  }
  if (!isObject(value)) {
    return value;
  }
  const result = {};
  for (const key of Object.keys(value).sort(compareCodePoints)) {
    result[key] = sortJson(value[key]);
  }
  return result;
}

function canonicalJson(value) {
  const encoded = JSON.stringify(sortJson(value));
  if (encoded === undefined) {
    fail("Engineering-smoke evidence is not JSON serializable");
  }
  return encoded;
}

function sameJson(left, right) {
  return canonicalJson(left) === canonicalJson(right);
}

function assertExactKeys(value, expected, label) {
  if (!isObject(value)) {
    fail(`${label} must be an object`);
  }
  const actual = Object.keys(value).sort(compareCodePoints);
  const reviewed = [...expected].sort(compareCodePoints);
  if (!sameJson(actual, reviewed)) {
    fail(`${label} does not match the reviewed contract`);
  }
  return value;
}

function sha256Bytes(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function sha256File(filePath) {
  const digest = crypto.createHash("sha256");
  let descriptor;
  try {
    descriptor = fs.openSync(filePath, "r");
    const buffer = Buffer.allocUnsafe(1024 * 1024);
    for (;;) {
      const count = fs.readSync(
        descriptor,
        buffer,
        0,
        buffer.length,
        null
      );
      if (count === 0) {
        break;
      }
      digest.update(buffer.subarray(0, count));
    }
  } catch {
    fail("Unable to hash an engineering-smoke file");
  } finally {
    if (descriptor !== undefined) {
      fs.closeSync(descriptor);
    }
  }
  return digest.digest("hex");
}

function requireRealDirectory(directoryPath, label) {
  const absolute = path.resolve(directoryPath);
  let info;
  try {
    info = fs.lstatSync(absolute);
  } catch {
    fail(`${label} is missing`);
  }
  if (
    !path.isAbsolute(directoryPath) ||
    absolute !== directoryPath ||
    !info.isDirectory() ||
    info.isSymbolicLink() ||
    fs.realpathSync.native(absolute) !== absolute
  ) {
    fail(`${label} must be a real canonical directory`);
  }
  return absolute;
}

function requireRegularFile(filePath, label, maximumBytes = Infinity) {
  let info;
  try {
    info = fs.lstatSync(filePath);
  } catch {
    fail(`${label} is missing`);
  }
  if (
    !info.isFile() ||
    info.isSymbolicLink() ||
    info.nlink !== 1 ||
    info.size > maximumBytes
  ) {
    fail(`${label} must be a bounded, unlinked regular file`);
  }
  return info;
}

function isContained(root, candidate) {
  const relative = path.relative(root, candidate);
  return (
    relative === "" ||
    (relative !== ".." &&
      !relative.startsWith(`..${path.sep}`) &&
      !path.isAbsolute(relative))
  );
}

function safeRelativePath(value, label) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.startsWith("/") ||
    value.includes("\\") ||
    value.includes("\0") ||
    value.split("/").some((part) => part === "" || part === "." || part === "..")
  ) {
    fail(`${label} path is unsafe`);
  }
  return value;
}

function relativeName(root, candidate) {
  if (!isContained(root, candidate)) {
    fail("Engineering-smoke inventory path escapes the bundle");
  }
  return safeRelativePath(
    path.relative(root, candidate).split(path.sep).join("/"),
    "Inventory"
  );
}

function modeString(mode) {
  return (mode & 0o7777).toString(8).padStart(4, "0");
}

function buildInventory(rootPath, { exclude = [] } = {}) {
  const root = requireRealDirectory(rootPath, "Inventory root");
  const excluded = new Set(exclude.map((item) => safeRelativePath(item, "Excluded")));
  const records = [];

  function visit(directory) {
    let names;
    try {
      names = fs.readdirSync(directory).sort(compareCodePoints);
    } catch {
      fail("Engineering-smoke inventory directory is unreadable");
    }
    for (const name of names) {
      const candidate = path.join(directory, name);
      const relative = relativeName(root, candidate);
      if (excluded.has(relative)) {
        continue;
      }
      let info;
      try {
        info = fs.lstatSync(candidate);
      } catch {
        fail("Engineering-smoke entry changed during inventory");
      }
      const common = { path: relative, mode: modeString(info.mode) };
      if (info.isSymbolicLink()) {
        let target;
        let resolved;
        try {
          target = fs.readlinkSync(candidate);
          if (!target || target.includes("\0") || path.isAbsolute(target)) {
            fail("Engineering-smoke bundle contains an unsafe symlink");
          }
          resolved = fs.realpathSync.native(candidate);
        } catch (error) {
          if (error instanceof EngineeringSmokeAuditError) {
            throw error;
          }
          fail("Engineering-smoke bundle contains a broken symlink");
        }
        if (!isContained(root, resolved)) {
          fail("Engineering-smoke symlink escapes the app bundle");
        }
        const encodedTarget = Buffer.from(target, "utf8");
        records.push({
          ...common,
          type: "symlink",
          size: encodedTarget.length,
          sha256: sha256Bytes(encodedTarget),
          linkTarget: target
        });
      } else if (info.isDirectory()) {
        if ((info.mode & 0o6002) !== 0) {
          fail("Engineering-smoke directory has privileged or world-writable mode");
        }
        records.push({ ...common, type: "directory", size: 0 });
        visit(candidate);
      } else if (info.isFile()) {
        if ((info.mode & 0o6002) !== 0) {
          fail("Engineering-smoke file has privileged or world-writable mode");
        }
        if (info.nlink !== 1) {
          fail("Engineering-smoke bundle contains a hard-linked file");
        }
        records.push({
          ...common,
          type: "file",
          size: info.size,
          sha256: sha256File(candidate)
        });
      } else {
        fail("Engineering-smoke bundle contains a special file");
      }
    }
  }

  visit(root);
  records.sort((left, right) => compareCodePoints(left.path, right.path));
  if (new Set(records.map((record) => record.path)).size !== records.length) {
    fail("Engineering-smoke inventory contains duplicate paths");
  }
  return records;
}

function normalizedInventorySha256(records) {
  if (!Array.isArray(records)) {
    fail("Engineering-smoke inventory must be an array");
  }
  return sha256Bytes(Buffer.from(canonicalJson(records), "utf8"));
}

function loadJson(filePath, label, maximumBytes = 16 * 1024 * 1024) {
  requireRegularFile(filePath, label, maximumBytes);
  let value;
  try {
    value = JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    fail(`${label} is not valid JSON`);
  }
  if (!isObject(value)) {
    fail(`${label} must be an object`);
  }
  return value;
}

function loadCanonicalJson(filePath, label, maximumBytes) {
  const value = loadJson(filePath, label, maximumBytes);
  if (fs.readFileSync(filePath, "utf8") !== `${canonicalJson(value)}\n`) {
    fail(`${label} is not canonical JSON`);
  }
  return value;
}

function writeCanonicalJson(filePath, value) {
  fs.writeFileSync(filePath, `${canonicalJson(value)}\n`, {
    encoding: "utf8",
    flag: "wx",
    mode: 0o644
  });
}

function assertPositiveInteger(value, label, { allowZero = false } = {}) {
  if (
    !Number.isSafeInteger(value) ||
    (allowZero ? value < 0 : value <= 0)
  ) {
    fail(`${label} must be a safe integer`);
  }
}

function validateManifestSchemaContract(schema) {
  assertExactKeys(
    schema,
    ["$schema", "$id", "type", "additionalProperties", "required", "properties"],
    "Engineering-smoke manifest schema"
  );
  if (
    schema.$schema !== "https://json-schema.org/draft/2020-12/schema" ||
    schema.$id !== MANIFEST_SCHEMA_NAME ||
    schema.type !== "object" ||
    schema.additionalProperties !== false ||
    !sameJson(schema.required, MANIFEST_KEYS) ||
    !isObject(schema.properties)
  ) {
    fail("Engineering-smoke manifest schema is not the reviewed contract");
  }
  for (const key of [
    "distribution",
    "application",
    "target",
    "source",
    "assembly",
    "components",
    "security",
    "capabilities",
    "validation"
  ]) {
    if (schema.properties[key]?.additionalProperties !== false) {
      fail("Engineering-smoke manifest schema permits unknown nested fields");
    }
  }
  if (
    schema.properties.$schema?.const !== MANIFEST_SCHEMA_NAME ||
    schema.properties.schemaVersion?.const !== 1 ||
    schema.properties.kind?.const !== MANIFEST_KIND ||
    schema.properties.application?.properties?.appId?.const !== APP_ID ||
    schema.properties.application?.properties?.productName?.const !== PRODUCT_NAME ||
    schema.properties.validation?.properties?.packagedAppLaunch?.const !== "not-run" ||
    schema.properties.validation?.properties?.packagedSmoke?.const !== "not-run"
  ) {
    fail("Engineering-smoke schema identity or validation state was weakened");
  }
}

function validateEngineeringSmokeManifest(manifest, schema) {
  validateManifestSchemaContract(schema);
  assertExactKeys(manifest, MANIFEST_KEYS, "Engineering-smoke manifest");
  if (
    manifest.$schema !== MANIFEST_SCHEMA_NAME ||
    manifest.schemaVersion !== 1 ||
    manifest.kind !== MANIFEST_KIND
  ) {
    fail("Engineering-smoke manifest identity is invalid");
  }

  const distribution = assertExactKeys(
    manifest.distribution,
    ["class", "marker", "engineeringOnly", "publishable"],
    "Engineering-smoke distribution"
  );
  if (
    distribution.class !== "engineering-smoke" ||
    distribution.marker !== DISTRIBUTION_MARKER ||
    distribution.engineeringOnly !== true ||
    distribution.publishable !== false
  ) {
    fail("Engineering-smoke distribution marker is invalid");
  }

  const application = assertExactKeys(
    manifest.application,
    ["appId", "productName", "version"],
    "Engineering-smoke application"
  );
  if (
    application.appId !== APP_ID ||
    application.productName !== PRODUCT_NAME ||
    typeof application.version !== "string" ||
    !/^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$/.test(
      application.version
    )
  ) {
    fail("Engineering-smoke application identity is invalid");
  }

  const target = assertExactKeys(
    manifest.target,
    ["os", "architecture", "artifact"],
    "Engineering-smoke target"
  );
  if (
    target.os !== "darwin" ||
    target.architecture !== "arm64" ||
    target.artifact !== "app-dir"
  ) {
    fail("Engineering-smoke target is invalid");
  }

  const source = assertExactKeys(
    manifest.source,
    [
      "repository",
      "commit",
      "tree",
      "sourceSnapshotSha256",
      "sourceDateEpoch"
    ],
    "Engineering-smoke source"
  );
  if (
    source.repository !== REPOSITORY ||
    !COMMIT_PATTERN.test(source.commit || "") ||
    !COMMIT_PATTERN.test(source.tree || "") ||
    !SHA256_PATTERN.test(source.sourceSnapshotSha256 || "")
  ) {
    fail("Engineering-smoke source provenance is invalid");
  }
  assertPositiveInteger(source.sourceDateEpoch, "Source date epoch");

  const assembly = assertExactKeys(
    manifest.assembly,
    ["builder", "mode", "asar", "outputDirectory", "manifestPath"],
    "Engineering-smoke assembly"
  );
  if (
    assembly.builder !== "electron-builder" ||
    assembly.mode !== "dir" ||
    assembly.asar !== true ||
    assembly.outputDirectory !== "release-smoke" ||
    assembly.manifestPath !== MANIFEST_RELATIVE_PATH
  ) {
    fail("Engineering-smoke assembly policy is invalid");
  }

  const components = assertExactKeys(
    manifest.components,
    ["desktopApp", "renderer", "pythonSidecar"],
    "Engineering-smoke components"
  );
  const desktopApp = assertExactKeys(
    components.desktopApp,
    [
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
      "entrypointBuild"
    ],
    "Engineering-smoke Desktop application component"
  );
  if (
    desktopApp.asarPath !== "Contents/Resources/app.asar" ||
    desktopApp.mainPath !== "dist/main/index.js" ||
    !SHA256_PATTERN.test(desktopApp.mainSha256 || "") ||
    desktopApp.preloadPath !== "dist/preload/index.cjs" ||
    !SHA256_PATTERN.test(desktopApp.preloadSha256 || "") ||
    desktopApp.packagePath !== "package.json" ||
    !SHA256_PATTERN.test(desktopApp.packageSha256 || "") ||
    desktopApp.reviewedPackagePath !== "desktop/package.json" ||
    !SHA256_PATTERN.test(desktopApp.reviewedPackageSha256 || "")
  ) {
    fail("Engineering-smoke Desktop application component is invalid");
  }
  for (const [label, value] of [
    ["Desktop Main byte count", desktopApp.mainBytes],
    ["Desktop preload byte count", desktopApp.preloadBytes],
    ["Desktop package byte count", desktopApp.packageBytes]
  ]) {
    assertPositiveInteger(value, label);
  }
  const entrypointBuild = assertExactKeys(
    desktopApp.entrypointBuild,
    [
      "builder",
      "builderVersion",
      "nodeVersion",
      "npmVersion",
      "packageLockSha256",
      "installedContentSha256",
      "inputs",
      "inputsSha256"
    ],
    "Engineering-smoke exact entrypoint build"
  );
  if (
    entrypointBuild.builder !== "esbuild" ||
    entrypointBuild.builderVersion !== "0.28.1" ||
    entrypointBuild.nodeVersion !== "v22.23.2" ||
    entrypointBuild.npmVersion !== "10.9.8" ||
    !SHA256_PATTERN.test(entrypointBuild.packageLockSha256 || "") ||
    !SHA256_PATTERN.test(entrypointBuild.installedContentSha256 || "") ||
    !SHA256_PATTERN.test(entrypointBuild.inputsSha256 || "")
  ) {
    fail("Engineering-smoke exact entrypoint build is invalid");
  }
  assertPositiveInteger(
    entrypointBuild.inputs,
    "Engineering-smoke exact entrypoint input count"
  );
  if (entrypointBuild.inputs < 3) {
    fail("Engineering-smoke exact entrypoint input closure is incomplete");
  }

  const renderer = assertExactKeys(
    components.renderer,
    [
      "resourcePath",
      "manifestPath",
      "manifestSha256",
      "repositoryCommit",
      "repositoryTree",
      "sourceSnapshotSha256",
      "inputSnapshotSha256",
      "files",
      "bytes"
    ],
    "Engineering-smoke renderer component"
  );
  if (
    renderer.resourcePath !== "Contents/Resources/renderer" ||
    renderer.manifestPath !==
      "Contents/Resources/renderer/renderer-build-manifest.json" ||
    !SHA256_PATTERN.test(renderer.manifestSha256 || "") ||
    renderer.repositoryCommit !== source.commit ||
    renderer.repositoryTree !== source.tree ||
    renderer.sourceSnapshotSha256 !== source.sourceSnapshotSha256 ||
    !SHA256_PATTERN.test(renderer.inputSnapshotSha256 || "")
  ) {
    fail("Engineering-smoke renderer component is invalid");
  }
  assertPositiveInteger(renderer.files, "Renderer file count");
  assertPositiveInteger(renderer.bytes, "Renderer byte count");

  const python = assertExactKeys(
    components.pythonSidecar,
    [
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
      "components"
    ],
    "Engineering-smoke Python component"
  );
  if (
    python.resourcePath !== "Contents/Resources/sidecar" ||
    python.manifestPath !== "Contents/Resources/sidecar/build-manifest.json" ||
    !SHA256_PATTERN.test(python.manifestSha256 || "") ||
    !SHA256_PATTERN.test(python.normalizedInventorySha256 || "") ||
    python.repositoryCommit !== source.commit ||
    python.repositoryTree !== source.tree ||
    python.sourceSnapshotSha256 !== source.sourceSnapshotSha256 ||
    python.pythonBuildToolchainPath !==
      "Contents/Resources/sidecar/python-build-toolchain.json"
  ) {
    fail("Engineering-smoke Python component is invalid");
  }
  const pythonToolchain = assertExactKeys(
    python.pythonToolchain,
    [
      "buildRequirementsLockSha256",
      "runtimeLockSha256",
      "runtimeRequirementsSha256",
      "installedTreeContentSha256",
      "buildTools"
    ],
    "Engineering-smoke Python toolchain summary"
  );
  if (
    [
      "buildRequirementsLockSha256",
      "runtimeLockSha256",
      "runtimeRequirementsSha256",
      "installedTreeContentSha256"
    ].some((key) => !SHA256_PATTERN.test(pythonToolchain[key] || "")) ||
    !sameJson(
      assertExactKeys(
        pythonToolchain.buildTools,
        Object.keys(EXPECTED_PYTHON_BUILD_TOOLS),
        "Engineering-smoke Python build tools"
      ),
      EXPECTED_PYTHON_BUILD_TOOLS
    )
  ) {
    fail("Engineering-smoke Python toolchain summary is invalid");
  }
  for (const [label, value] of [
    ["Python file count", python.files],
    ["Python native file count", python.nativeFiles],
    ["Python component count", python.components]
  ]) {
    assertPositiveInteger(value, label);
  }

  const security = assertExactKeys(
    manifest.security,
    [
      "signing",
      "identity",
      "hardenedRuntime",
      "notarized",
      "productionCredentialsUsed",
      "secureFusesRequired"
    ],
    "Engineering-smoke security"
  );
  if (
    security.signing !== "ad-hoc" ||
    security.identity !== "-" ||
    security.hardenedRuntime !== false ||
    security.notarized !== false ||
    security.productionCredentialsUsed !== false ||
    security.secureFusesRequired !== true
  ) {
    fail("Engineering-smoke security policy is invalid");
  }

  const capabilities = assertExactKeys(
    manifest.capabilities,
    [
      "updater",
      "networkAllowed",
      "manualReleasePageAllowed",
      "qmd",
      "mcp",
      "companion",
      "productionUpdateTrust",
      "releaseMetadata",
      "modelWeights"
    ],
    "Engineering-smoke capabilities"
  );
  if (
    capabilities.updater !== "unavailable" ||
    capabilities.networkAllowed !== false ||
    capabilities.manualReleasePageAllowed !== false ||
    capabilities.qmd !== "omitted" ||
    capabilities.mcp !== "omitted" ||
    capabilities.companion !== "omitted" ||
    capabilities.productionUpdateTrust !== "omitted" ||
    capabilities.releaseMetadata !== "omitted" ||
    capabilities.modelWeights !== "omitted"
  ) {
    fail("Engineering-smoke capability boundary is invalid");
  }

  const validation = assertExactKeys(
    manifest.validation,
    ["validationId", "packagedAppLaunch", "packagedSmoke", "unlocks"],
    "Engineering-smoke validation state"
  );
  if (
    validation.validationId !== "VAL-PACKAGED-SMOKE-001" ||
    validation.packagedAppLaunch !== "not-run" ||
    validation.packagedSmoke !== "not-run" ||
    !sameJson(validation.unlocks, [])
  ) {
    fail("Engineering-smoke manifest overclaims packaged validation");
  }
  return manifest;
}

module.exports = {
  APP_ID,
  COMMIT_PATTERN,
  DISTRIBUTION_MARKER,
  EngineeringSmokeAuditError,
  MANIFEST_KIND,
  MANIFEST_RELATIVE_PATH,
  MANIFEST_SCHEMA_NAME,
  PRODUCT_NAME,
  REPOSITORY,
  SHA256_PATTERN,
  assertExactKeys,
  buildInventory,
  canonicalJson,
  compareCodePoints,
  fail,
  isContained,
  isObject,
  loadCanonicalJson,
  loadJson,
  normalizedInventorySha256,
  requireRealDirectory,
  requireRegularFile,
  safeRelativePath,
  sameJson,
  sha256Bytes,
  sha256File,
  validateEngineeringSmokeManifest,
  validateManifestSchemaContract,
  writeCanonicalJson
};

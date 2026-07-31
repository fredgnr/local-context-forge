"use strict";

const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const MANIFEST_NAME = "build-manifest.json";
const MANIFEST_SCHEMA_NAME = "python-sidecar-build-manifest.schema.json";
const MANIFEST_SCHEMA_VERSION = 1;
const EXPECTED_KIND = "local-context-forge-python-sidecar";
const EXPECTED_EXECUTABLE = "lcf-service";
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const RUNNER_IMAGE_VERSION_PATTERN = /^[0-9]{8}\.[0-9]+\.[0-9]+$/;
const MACHO_MAGICS = new Set([
  "cafebabe",
  "bebafeca",
  "cafebabf",
  "bfbafeca",
  "feedface",
  "cefaedfe",
  "feedfacf",
  "cffaedfe"
]);
const REQUIRED_RUNTIME_COMPONENTS = new Set([
  "certifi",
  "cpython",
  "dulwich",
  "openssl",
  "pydantic-core",
  "pyinstaller-bootloader",
  "python-hashlib",
  "sqlite",
  "urllib3"
]);
const REQUIRED_BUILD_TOOLS = new Set([
  "pyinstaller",
  "pyinstaller-hooks-contrib",
  "uv"
]);
const EXPECTED_FROZEN_CHECKS = Object.freeze([
  "version",
  "doctor",
  "uds-handshake",
  "uds-health",
  "domain-ingest",
  "domain-publish",
  "domain-lint"
]);
const EXPECTED_FROZEN_SMOKE = Object.freeze({
  status: "pass",
  pathTrap: true,
  checks: EXPECTED_FROZEN_CHECKS
});

const FIXED_CRITICAL_INPUTS = Object.freeze([
  "Makefile",
  "backend/packaging/build-requirements.lock",
  "backend/packaging/frozen_entrypoint.py",
  "backend/packaging/lcf_sidecar.spec",
  "backend/packaging/license-policy.json",
  "backend/packaging/missing-imports-allowlist.json",
  "backend/packaging/python-sidecar-toolchain.lock.json",
  "backend/pyproject.toml",
  "backend/uv.lock",
  "desktop/electron-builder.yml",
  "desktop/package-lock.json",
  "desktop/package.json",
  "desktop/scripts/afterPack.cjs",
  "desktop/scripts/beforePack.cjs",
  "runtime/python-sidecar-build-manifest.schema.json",
  "runtime/version.json",
  "tools/audit_python_sidecar.py",
  "tools/build_python_sidecar.py"
]);

class BeforePackAuditError extends Error {
  constructor(message) {
    super(message);
    this.name = "BeforePackAuditError";
  }
}

function fail(message) {
  throw new BeforePackAuditError(message);
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
    fail("Unable to canonicalize audit evidence");
  }
  return encoded;
}

function sameJson(left, right) {
  return canonicalJson(left) === canonicalJson(right);
}

function sha256Bytes(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function sha256File(filePath) {
  let descriptor;
  try {
    descriptor = fs.openSync(filePath, "r");
    const digest = crypto.createHash("sha256");
    const buffer = Buffer.allocUnsafe(1024 * 1024);
    for (;;) {
      const bytesRead = fs.readSync(
        descriptor,
        buffer,
        0,
        buffer.length,
        null
      );
      if (bytesRead === 0) {
        break;
      }
      digest.update(buffer.subarray(0, bytesRead));
    }
    return digest.digest("hex");
  } catch (error) {
    fail("Unable to hash an audited file");
  } finally {
    if (descriptor !== undefined) {
      fs.closeSync(descriptor);
    }
  }
}

function loadJson(filePath, label) {
  let raw;
  try {
    const info = fs.lstatSync(filePath);
    if (!info.isFile() || info.isSymbolicLink()) {
      fail(`${label} must be a regular file`);
    }
    raw = fs.readFileSync(filePath, "utf8");
  } catch (error) {
    if (error instanceof BeforePackAuditError) {
      throw error;
    }
    fail(`${label} is unreadable`);
  }
  let value;
  try {
    value = JSON.parse(raw);
  } catch (error) {
    fail(`${label} is not valid JSON`);
  }
  if (!isObject(value)) {
    fail(`${label} must be an object`);
  }
  return value;
}

function assertObject(value, label) {
  if (!isObject(value)) {
    fail(`${label} must be an object`);
  }
  return value;
}

function assertExactKeys(value, required, optional, label) {
  const object = assertObject(value, label);
  const allowed = new Set([...required, ...optional]);
  const keys = Object.keys(object);
  if (
    required.some((key) => !Object.prototype.hasOwnProperty.call(object, key)) ||
    keys.some((key) => !allowed.has(key))
  ) {
    fail(`${label} does not match the reviewed schema`);
  }
  return object;
}

function safeRelativePath(value, label) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.startsWith("/") ||
    value.includes("\\") ||
    value.includes("\0") ||
    value.split("/").includes("..")
  ) {
    fail(`${label} path is unsafe`);
  }
  return value;
}

function isContained(root, candidate) {
  const relative = path.relative(root, candidate);
  return (
    relative === "" ||
    (!relative.startsWith(`..${path.sep}`) &&
      relative !== ".." &&
      !path.isAbsolute(relative))
  );
}

function relativeName(root, candidate) {
  const relative = path.relative(root, candidate).split(path.sep).join("/");
  if (!isContained(root, candidate)) {
    fail("Inventory path escapes the sidecar root");
  }
  return safeRelativePath(relative, "inventory");
}

function requireRealDirectory(directoryPath, label) {
  let info;
  try {
    info = fs.lstatSync(directoryPath);
  } catch (error) {
    fail(`${label} is missing`);
  }
  if (!info.isDirectory() || info.isSymbolicLink()) {
    fail(`${label} must be a real directory`);
  }
  let resolved;
  try {
    resolved = fs.realpathSync(directoryPath);
  } catch (error) {
    fail(`${label} is unreadable`);
  }
  return resolved;
}

function requireRegularFile(filePath, label) {
  let info;
  try {
    info = fs.lstatSync(filePath);
  } catch (error) {
    fail(`${label} is missing`);
  }
  if (!info.isFile() || info.isSymbolicLink()) {
    fail(`${label} must be a regular file`);
  }
  return info;
}

function resolveArtifact(root, value, label) {
  const relative = safeRelativePath(value, label);
  const artifact = path.join(root, ...relative.split("/"));
  requireRegularFile(artifact, `Manifest ${label} artifact`);
  let resolved;
  try {
    resolved = fs.realpathSync(artifact);
  } catch (error) {
    fail(`Manifest ${label} artifact is unreadable`);
  }
  if (!isContained(root, resolved)) {
    fail(`Manifest ${label} artifact escapes the sidecar`);
  }
  return artifact;
}

function modeString(mode) {
  return (mode & 0o7777).toString(8).padStart(4, "0");
}

function buildFileInventory(rootPath) {
  const root = requireRealDirectory(rootPath, "Sidecar root");
  const inventory = [];

  function walk(directory) {
    let children;
    try {
      children = fs
        .readdirSync(directory, { withFileTypes: true })
        .sort((left, right) => compareCodePoints(left.name, right.name));
    } catch (error) {
      fail("Sidecar directory is unreadable");
    }
    for (const child of children) {
      const childPath = path.join(directory, child.name);
      const relative = relativeName(root, childPath);
      if (relative === MANIFEST_NAME) {
        continue;
      }
      let info;
      try {
        info = fs.lstatSync(childPath);
      } catch (error) {
        fail("Sidecar entry changed during inventory");
      }
      const common = {
        path: relative,
        mode: modeString(info.mode)
      };
      if (info.isSymbolicLink()) {
        let target;
        let resolved;
        try {
          target = fs.readlinkSync(childPath);
          if (!target || target.includes("\0") || path.isAbsolute(target)) {
            fail("Sidecar contains an absolute or empty symlink");
          }
          resolved = fs.realpathSync(childPath);
        } catch (error) {
          if (error instanceof BeforePackAuditError) {
            throw error;
          }
          fail("Sidecar contains a broken or cyclic symlink");
        }
        if (!isContained(root, resolved)) {
          fail("Sidecar symlink escapes the bundle");
        }
        const encoded = Buffer.from(target, "utf8");
        inventory.push({
          ...common,
          type: "symlink",
          size: encoded.length,
          sha256: sha256Bytes(encoded),
          linkTarget: target
        });
      } else if (info.isDirectory()) {
        inventory.push({ ...common, type: "directory", size: 0 });
        walk(childPath);
      } else if (info.isFile()) {
        inventory.push({
          ...common,
          type: "file",
          size: info.size,
          sha256: sha256File(childPath)
        });
      } else {
        fail("Sidecar contains a special file");
      }
    }
  }

  walk(root);
  inventory.sort((left, right) => compareCodePoints(left.path, right.path));
  if (new Set(inventory.map((item) => item.path)).size !== inventory.length) {
    fail("Sidecar inventory contains duplicate paths");
  }
  return inventory;
}

function isMachO(filePath) {
  requireRegularFile(filePath, "Possible Mach-O");
  let descriptor;
  try {
    descriptor = fs.openSync(filePath, "r");
    const magic = Buffer.alloc(4);
    const bytesRead = fs.readSync(descriptor, magic, 0, 4, 0);
    return bytesRead === 4 && MACHO_MAGICS.has(magic.toString("hex"));
  } catch (error) {
    fail("Unable to inspect a possible Mach-O file");
  } finally {
    if (descriptor !== undefined) {
      fs.closeSync(descriptor);
    }
  }
}

function parseLipoArchitectures(output) {
  const values = output.trim().split(/\s+/).filter(Boolean);
  if (
    values.length === 0 ||
    values.some((value) => !/^[A-Za-z0-9_]+$/.test(value))
  ) {
    fail("Unable to parse Mach-O architectures");
  }
  return [...new Set(values)].sort(compareCodePoints);
}

function inspectMachOWithLipo(filePath, platformName = process.platform) {
  if (platformName !== "darwin") {
    fail("Production Mach-O inspection requires Darwin");
  }
  let output;
  try {
    output = childProcess.execFileSync(
      "/usr/bin/lipo",
      ["-archs", filePath],
      {
        encoding: "utf8",
        env: {
          PATH: "/usr/bin:/bin",
          LANG: "C",
          LC_ALL: "C"
        },
        stdio: ["ignore", "pipe", "pipe"],
        timeout: 30_000,
        maxBuffer: 1024 * 1024
      }
    );
  } catch (error) {
    fail("Native architecture inspection failed");
  }
  return parseLipoArchitectures(output);
}

function validateMinimumMacosVersion(value) {
  if (typeof value !== "string" || !/^[0-9]+(?:\.[0-9]+){1,2}$/.test(value)) {
    fail("Mach-O minimum macOS version evidence is malformed");
  }
  const parts = value.split(".").map(Number);
  while (parts.length < 3) {
    parts.push(0);
  }
  const exceedsTarget =
    parts[0] > 14 ||
    (parts[0] === 14 && parts[1] > 0) ||
    (parts[0] === 14 && parts[1] === 0 && parts[2] > 0);
  if (exceedsTarget) {
    fail("Mach-O minimum macOS exceeds the reviewed target");
  }
}

function validateNativeInventory(root, files, native, inspectNative) {
  if (!Array.isArray(native) || native.length === 0) {
    fail("Manifest native inventory is missing");
  }
  const actualMachOPaths = files
    .filter(
      (item) =>
        item.type === "file" &&
        isMachO(path.join(root, ...item.path.split("/")))
    )
    .map((item) => item.path)
    .sort(compareCodePoints);
  if (actualMachOPaths.length === 0) {
    fail("Sidecar contains no audited Mach-O files");
  }

  const recordedPaths = [];
  for (const rawRecord of native) {
    const record = assertExactKeys(
      rawRecord,
      [
        "path",
        "architectures",
        "dylibs",
        "rpaths",
        "platform",
        "minimumMacosVersion",
        "codeSignature"
      ],
      ["installName"],
      "Native inventory entry"
    );
    const relative = safeRelativePath(record.path, "native");
    recordedPaths.push(relative);
    if (!sameJson(record.architectures, ["arm64"])) {
      fail("Every Mach-O must be arm64-only");
    }
    if (record.platform !== "macos") {
      fail("Every Mach-O must target macOS");
    }
    validateMinimumMacosVersion(record.minimumMacosVersion);
    if (record.codeSignature !== "valid") {
      fail("Every Mach-O must have valid signature evidence");
    }
    for (const field of ["dylibs", "rpaths"]) {
      if (
        !Array.isArray(record[field]) ||
        record[field].some(
          (item) => typeof item !== "string" || item.length === 0
        ) ||
        new Set(record[field]).size !== record[field].length
      ) {
        fail(`Native ${field} evidence is malformed`);
      }
    }
    if (
      Object.prototype.hasOwnProperty.call(record, "installName") &&
      (typeof record.installName !== "string" ||
        record.installName.length === 0)
    ) {
      fail("Mach-O install name evidence is malformed");
    }
  }
  recordedPaths.sort(compareCodePoints);
  if (
    new Set(recordedPaths).size !== recordedPaths.length ||
    !sameJson(recordedPaths, actualMachOPaths)
  ) {
    fail("Mach-O magic coverage differs from the manifest");
  }
  if (!recordedPaths.includes(EXPECTED_EXECUTABLE)) {
    fail("Native inventory omits the sidecar entrypoint");
  }

  for (const relative of actualMachOPaths) {
    const absolute = path.join(root, ...relative.split("/"));
    const architectures = inspectNative(absolute, relative);
    if (!sameJson(architectures, ["arm64"])) {
      fail("Every staged Mach-O must independently inspect as arm64-only");
    }
  }
}

function normalizedInventorySha256(files, native) {
  return sha256Bytes(
    Buffer.from(canonicalJson({ files, native }), "utf8")
  );
}

function criticalInputPaths(repositoryRoot) {
  const root = requireRealDirectory(repositoryRoot, "Repository root");
  const relativePaths = [...FIXED_CRITICAL_INPUTS];
  const noticesDirectory = path.join(
    root,
    "backend",
    "packaging",
    "notices"
  );
  let notices;
  try {
    notices = fs
      .readdirSync(noticesDirectory, { withFileTypes: true })
      .filter((entry) => entry.name.endsWith(".txt"))
      .map((entry) => `backend/packaging/notices/${entry.name}`);
  } catch (error) {
    fail("Python packaging notices directory is missing");
  }
  return [...new Set([...relativePaths, ...notices])]
    .sort(compareCodePoints)
    .map((relative) => ({
      relative,
      absolute: path.join(root, ...relative.split("/"))
    }));
}

function criticalInputDigests(repositoryRoot) {
  const result = {};
  for (const input of criticalInputPaths(repositoryRoot)) {
    requireRegularFile(input.absolute, "Critical build input");
    result[input.relative] = sha256File(input.absolute);
  }
  return result;
}

function validateToolchainLock(toolchain) {
  assertExactKeys(
    toolchain,
    ["schemaVersion", "target", "python", "tools", "requiredCiInputs"],
    [],
    "Python toolchain lock"
  );
  if (toolchain.schemaVersion !== 1) {
    fail("Python toolchain lock schema is unsupported");
  }
  assertExactKeys(
    toolchain.target,
    ["os", "architecture", "runnerLabel", "deploymentTarget"],
    [],
    "Toolchain target"
  );
  assertExactKeys(
    toolchain.python,
    [
      "implementation",
      "version",
      "installRoot",
      "interpreterRelativePath",
      "distribution"
    ],
    [],
    "Toolchain Python"
  );
  assertExactKeys(
    toolchain.python.distribution,
    [
      "provider",
      "releaseTag",
      "releaseCommit",
      "archiveName",
      "archiveSource",
      "archiveSha256",
      "archiveSize",
      "archiveMembers",
      "installerPackageName",
      "installerPackageSha256",
      "installMethod",
      "hashManifestName",
      "hashManifestSource",
      "hashManifestSha256",
      "hashManifestSize"
    ],
    [],
    "Toolchain Python distribution"
  );
  assertExactKeys(
    toolchain.tools,
    ["uv", "pyinstaller", "pyinstallerHooksContrib"],
    [],
    "Toolchain build tools"
  );
  const mandatoryInputs = [
    "GITHUB_SHA",
    "LCF_SOURCE_DATE_EPOCH",
    "ImageVersion",
    "LCF_PYTHON_DISTRIBUTION_ARCHIVE",
    "LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST",
    "LCF_PYTHON_INSTALL_ROOT"
  ];
  if (
    !Array.isArray(toolchain.requiredCiInputs) ||
    new Set(toolchain.requiredCiInputs).size !==
      toolchain.requiredCiInputs.length ||
    mandatoryInputs.some(
      (input) => !toolchain.requiredCiInputs.includes(input)
    )
  ) {
    fail("Python toolchain required runner inputs are incomplete");
  }
  const distribution = toolchain.python.distribution;
  if (
    toolchain.python.interpreterRelativePath !== "bin/python3.13" ||
    !COMMIT_PATTERN.test(distribution.releaseCommit) ||
    !Number.isSafeInteger(distribution.archiveSize) ||
    distribution.archiveSize <= 0 ||
    !Number.isSafeInteger(distribution.hashManifestSize) ||
    distribution.hashManifestSize <= 0 ||
    distribution.installMethod !== "macos-installer-pkg-direct" ||
    !Array.isArray(distribution.archiveMembers) ||
    distribution.archiveMembers.length !== 3
  ) {
    fail("Python toolchain distribution evidence is incomplete");
  }
  const memberPaths = new Set();
  for (const rawMember of distribution.archiveMembers) {
    const member = assertExactKeys(
      rawMember,
      ["path", "size", "sha256"],
      [],
      "Toolchain archive member"
    );
    safeRelativePath(member.path, "Toolchain archive member");
    if (
      memberPaths.has(member.path) ||
      !Number.isSafeInteger(member.size) ||
      member.size < 0 ||
      !SHA256_PATTERN.test(member.sha256)
    ) {
      fail("Python toolchain archive member evidence is malformed");
    }
    memberPaths.add(member.path);
  }
  const installerMember = distribution.archiveMembers.find(
    (member) => member.path === distribution.installerPackageName
  );
  if (
    !installerMember ||
    installerMember.sha256 !== distribution.installerPackageSha256
  ) {
    fail("Python installer member differs from the reviewed distribution");
  }
}

function validateSchemaContract(schema, toolchain) {
  const topRequired = [
    "$schema",
    "schemaVersion",
    "kind",
    "entrypoint",
    "product",
    "target",
    "build",
    "components",
    "artifacts",
    "files",
    "native",
    "audit"
  ];
  if (
    schema.$schema !== "https://json-schema.org/draft/2020-12/schema" ||
    schema.$id !== MANIFEST_SCHEMA_NAME ||
    schema.type !== "object" ||
    schema.additionalProperties !== false ||
    !sameJson(schema.required, topRequired) ||
    !isObject(schema.properties) ||
    schema.properties.$schema?.const !== MANIFEST_SCHEMA_NAME ||
    schema.properties.schemaVersion?.const !== MANIFEST_SCHEMA_VERSION ||
    schema.properties.kind?.const !== EXPECTED_KIND ||
    schema.properties.entrypoint?.const !== EXPECTED_EXECUTABLE ||
    schema.properties.product?.additionalProperties !== false ||
    schema.properties.target?.additionalProperties !== false ||
    schema.properties.build?.additionalProperties !== false ||
    schema.properties.audit?.additionalProperties !== false ||
    !isObject(schema.$defs) ||
    schema.$defs.sha256?.pattern !== "^[0-9a-f]{64}$" ||
    schema.$defs.pythonProvenance?.additionalProperties !== false ||
    schema.$defs.nativeInventoryEntry?.additionalProperties !== false
  ) {
    fail("Python sidecar manifest schema is not the reviewed contract");
  }
  const buildProperties = schema.properties.build?.properties;
  const targetProperties = schema.properties.target?.properties;
  const pythonProperties = schema.$defs.pythonProvenance?.properties;
  const nativeProperties = schema.$defs.nativeInventoryEntry?.properties;
  const frozenSmokeProperties =
    schema.properties.audit?.properties?.frozenSmoke?.properties;
  const expectedPython = expectedPythonProvenance(toolchain);
  if (
    !isObject(buildProperties) ||
    !isObject(targetProperties) ||
    !isObject(pythonProperties) ||
    !isObject(nativeProperties) ||
    !isObject(frozenSmokeProperties) ||
    targetProperties.os?.const !== toolchain.target.os ||
    targetProperties.architecture?.const !==
      toolchain.target.architecture ||
    buildProperties.runnerImage?.const !== toolchain.target.runnerLabel ||
    buildProperties.macosDeploymentTarget?.const !==
      toolchain.target.deploymentTarget ||
    buildProperties.uvVersion?.const !== toolchain.tools.uv ||
    buildProperties.pyinstallerVersion?.const !==
      toolchain.tools.pyinstaller ||
    buildProperties.pyinstallerHooksContribVersion?.const !==
      toolchain.tools.pyinstallerHooksContrib ||
    Object.entries(expectedPython).some(
      ([key, expected]) => pythonProperties[key]?.const !== expected
    ) ||
    !sameJson(nativeProperties.architectures?.const, ["arm64"]) ||
    nativeProperties.platform?.const !== "macos" ||
    nativeProperties.codeSignature?.const !== "valid" ||
    frozenSmokeProperties.status?.const !==
      EXPECTED_FROZEN_SMOKE.status ||
    frozenSmokeProperties.pathTrap?.const !==
      EXPECTED_FROZEN_SMOKE.pathTrap ||
    !sameJson(
      frozenSmokeProperties.checks?.const,
      EXPECTED_FROZEN_SMOKE.checks
    )
  ) {
    fail("Python toolchain lock and manifest schema disagree");
  }
}

function validateProduct(manifest, versions) {
  const product = assertExactKeys(
    manifest.product,
    [
      "appVersion",
      "pythonDistributionVersion",
      "desktopProtocol",
      "databaseSchema"
    ],
    [],
    "Manifest product"
  );
  assertExactKeys(
    product.desktopProtocol,
    ["major", "minor"],
    [],
    "Manifest desktop protocol"
  );
  const expected = {
    appVersion: versions.productVersion,
    pythonDistributionVersion: versions.pythonDistributionVersion,
    desktopProtocol: versions.desktopProtocol,
    databaseSchema: versions.databaseSchema
  };
  if (!sameJson(product, expected)) {
    fail("Manifest product/protocol/schema versions are not canonical");
  }
}

function expectedPythonProvenance(toolchain) {
  const python = assertObject(toolchain.python, "Toolchain Python");
  const distribution = assertObject(
    python.distribution,
    "Toolchain Python distribution"
  );
  return {
    implementation: python.implementation,
    version: python.version,
    installRoot: python.installRoot,
    provider: distribution.provider,
    releaseTag: distribution.releaseTag,
    archiveName: distribution.archiveName,
    archiveSource: distribution.archiveSource,
    archiveSha256: distribution.archiveSha256,
    installerPackageName: distribution.installerPackageName,
    installerPackageSha256: distribution.installerPackageSha256,
    hashManifestName: distribution.hashManifestName,
    hashManifestSource: distribution.hashManifestSource,
    hashManifestSha256: distribution.hashManifestSha256
  };
}

function inspectSourceFiles(environment) {
  const archivePath = environment.LCF_PYTHON_DISTRIBUTION_ARCHIVE;
  const hashManifestPath =
    environment.LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST;
  if (
    typeof archivePath !== "string" ||
    !path.isAbsolute(archivePath) ||
    typeof hashManifestPath !== "string" ||
    !path.isAbsolute(hashManifestPath)
  ) {
    fail("Python source evidence paths must be absolute");
  }
  const archiveInfo = requireRegularFile(
    archivePath,
    "Python distribution archive"
  );
  const hashManifestInfo = requireRegularFile(
    hashManifestPath,
    "Python hash manifest"
  );
  if (archiveInfo.nlink !== 1 || hashManifestInfo.nlink !== 1) {
    fail("Python source evidence must not be hard-linked");
  }
  return {
    archiveSize: archiveInfo.size,
    archiveSha256: sha256File(archivePath),
    hashManifestSize: hashManifestInfo.size,
    hashManifestSha256: sha256File(hashManifestPath)
  };
}

function inspectRepositoryProvenance(repositoryRoot) {
  function git(commandArguments) {
    try {
      return childProcess
        .execFileSync(
          "/usr/bin/git",
          ["-C", repositoryRoot, ...commandArguments],
          {
            encoding: "utf8",
            env: {
              PATH: "/usr/bin:/bin",
              LANG: "C",
              LC_ALL: "C"
            },
            stdio: ["ignore", "pipe", "pipe"],
            timeout: 30_000,
            maxBuffer: 1024 * 1024
          }
        )
        .trim();
    } catch (error) {
      fail("Repository provenance inspection failed");
    }
  }
  const commit = git(["rev-parse", "HEAD"]).toLowerCase();
  const sourceDateEpoch = Number(git(["show", "-s", "--format=%ct", "HEAD"]));
  if (
    !COMMIT_PATTERN.test(commit) ||
    !Number.isSafeInteger(sourceDateEpoch) ||
    git(["status", "--porcelain", "--untracked-files=all"]) !== ""
  ) {
    fail("Repository is not a clean reviewed commit");
  }
  return { commit, sourceDateEpoch };
}

function validateEnvironment(
  environment,
  build,
  toolchain,
  inspectSource,
  inspectRepository,
  repositoryRoot
) {
  if (
    !Array.isArray(toolchain.requiredCiInputs) ||
    toolchain.requiredCiInputs.some(
      (name) =>
        typeof name !== "string" ||
        name.length === 0 ||
        typeof environment[name] !== "string" ||
        environment[name].length === 0
    )
  ) {
    fail("Required packaging runner inputs are missing");
  }
  if (!COMMIT_PATTERN.test(environment.GITHUB_SHA || "")) {
    fail("Current GITHUB_SHA is invalid");
  }
  if (build.repositoryCommit !== environment.GITHUB_SHA) {
    fail("Manifest commit differs from the current GITHUB_SHA");
  }
  if (!/^[0-9]+$/.test(environment.LCF_SOURCE_DATE_EPOCH || "")) {
    fail("Current source date epoch is invalid");
  }
  const epoch = Number(environment.LCF_SOURCE_DATE_EPOCH);
  if (!Number.isSafeInteger(epoch) || build.sourceDateEpoch !== epoch) {
    fail("Manifest source date epoch differs from the current runner input");
  }
  if (
    !RUNNER_IMAGE_VERSION_PATTERN.test(environment.ImageVersion || "") ||
    build.runnerImageVersion !== environment.ImageVersion
  ) {
    fail("Manifest runner image differs from the current runner input");
  }
  if (environment.LCF_PYTHON_INSTALL_ROOT !== toolchain.python.installRoot) {
    fail("Current Python install root differs from the reviewed lock");
  }
  const observedSource = assertExactKeys(
    inspectSource(environment),
    [
      "archiveSize",
      "archiveSha256",
      "hashManifestSize",
      "hashManifestSha256"
    ],
    [],
    "Observed Python source evidence"
  );
  const distribution = toolchain.python.distribution;
  if (
    observedSource.archiveSize !== distribution.archiveSize ||
    observedSource.archiveSha256 !== distribution.archiveSha256 ||
    observedSource.hashManifestSize !== distribution.hashManifestSize ||
    observedSource.hashManifestSha256 !==
      distribution.hashManifestSha256
  ) {
    fail("Current Python source bytes differ from the reviewed lock");
  }
  const repository = assertExactKeys(
    inspectRepository(repositoryRoot),
    ["commit", "sourceDateEpoch"],
    [],
    "Observed repository provenance"
  );
  if (
    repository.commit !== build.repositoryCommit ||
    repository.sourceDateEpoch !== build.sourceDateEpoch
  ) {
    fail("Manifest repository provenance differs from the checkout");
  }
}

function validateBuild(
  manifest,
  toolchain,
  environment,
  repositoryRoot,
  inspectSource,
  inspectRepository
) {
  const build = assertExactKeys(
    manifest.build,
    [
      "repositoryCommit",
      "sourceDateEpoch",
      "runnerImage",
      "runnerImageVersion",
      "macosDeploymentTarget",
      "xcodeVersion",
      "sdkVersion",
      "uvVersion",
      "pyinstallerVersion",
      "pyinstallerHooksContribVersion",
      "python",
      "inputDigests"
    ],
    [],
    "Manifest build"
  );
  if (
    !COMMIT_PATTERN.test(build.repositoryCommit) ||
    !Number.isSafeInteger(build.sourceDateEpoch) ||
    build.sourceDateEpoch < 100_000_000 ||
    !RUNNER_IMAGE_VERSION_PATTERN.test(build.runnerImageVersion) ||
    typeof build.xcodeVersion !== "string" ||
    build.xcodeVersion.length === 0 ||
    typeof build.sdkVersion !== "string" ||
    build.sdkVersion.length === 0
  ) {
    fail("Manifest build provenance is incomplete");
  }
  const target = assertObject(toolchain.target, "Toolchain target");
  const tools = assertObject(toolchain.tools, "Toolchain tools");
  const expectedPinnedBuild = {
    runnerImage: target.runnerLabel,
    macosDeploymentTarget: target.deploymentTarget,
    uvVersion: tools.uv,
    pyinstallerVersion: tools.pyinstaller,
    pyinstallerHooksContribVersion: tools.pyinstallerHooksContrib
  };
  for (const [key, expected] of Object.entries(expectedPinnedBuild)) {
    if (build[key] !== expected) {
      fail("Manifest build environment differs from reviewed pins");
    }
  }

  const python = assertExactKeys(
    build.python,
    [
      "implementation",
      "version",
      "installRoot",
      "provider",
      "releaseTag",
      "archiveName",
      "archiveSource",
      "archiveSha256",
      "installerPackageName",
      "installerPackageSha256",
      "hashManifestName",
      "hashManifestSource",
      "hashManifestSha256",
      "installRootFingerprintSha256"
    ],
    [],
    "Manifest Python provenance"
  );
  const expectedPython = expectedPythonProvenance(toolchain);
  for (const [key, expected] of Object.entries(expectedPython)) {
    if (python[key] !== expected) {
      fail("Manifest Python source provenance differs from the reviewed lock");
    }
  }
  if (!SHA256_PATTERN.test(python.installRootFingerprintSha256)) {
    fail("Manifest installed Python fingerprint is invalid");
  }

  const actualInputs = criticalInputDigests(repositoryRoot);
  if (!sameJson(build.inputDigests, actualInputs)) {
    fail("Manifest critical input digests are stale or incomplete");
  }
  validateEnvironment(
    environment,
    build,
    toolchain,
    inspectSource,
    inspectRepository,
    repositoryRoot
  );
}

function validateComponents(root, manifest, toolchain) {
  if (!Array.isArray(manifest.components) || manifest.components.length < 12) {
    fail("Manifest component inventory is missing");
  }
  const byName = new Map();
  for (const rawComponent of manifest.components) {
    const component = assertExactKeys(
      rawComponent,
      ["name", "version", "scope", "licenseExpression", "licenseFiles"],
      ["properties"],
      "Manifest component"
    );
    if (
      typeof component.name !== "string" ||
      component.name.length === 0 ||
      byName.has(component.name) ||
      typeof component.version !== "string" ||
      component.version.length === 0 ||
      !["runtime", "build-tool"].includes(component.scope) ||
      typeof component.licenseExpression !== "string" ||
      component.licenseExpression.length === 0 ||
      !Array.isArray(component.licenseFiles) ||
      component.licenseFiles.length === 0 ||
      new Set(component.licenseFiles).size !== component.licenseFiles.length
    ) {
      fail("Manifest component metadata is incomplete or duplicated");
    }
    for (const licensePath of component.licenseFiles) {
      resolveArtifact(root, licensePath, "license");
    }
    if (Object.prototype.hasOwnProperty.call(component, "properties")) {
      const properties = assertObject(
        component.properties,
        "Manifest component properties"
      );
      if (Object.values(properties).some((value) => typeof value !== "string")) {
        fail("Manifest component properties are malformed");
      }
    }
    byName.set(component.name, component);
  }

  for (const name of REQUIRED_RUNTIME_COMPONENTS) {
    if (!byName.has(name) || byName.get(name).scope !== "runtime") {
      fail("Manifest omits a required runtime component");
    }
  }
  for (const name of REQUIRED_BUILD_TOOLS) {
    if (!byName.has(name) || byName.get(name).scope !== "build-tool") {
      fail("Manifest omits a required build-tool component");
    }
  }
  if (
    byName.get("cpython").version !== toolchain.python.version ||
    byName.get("dulwich").version !== "1.2.11" ||
    byName.get("pyinstaller").version !== toolchain.tools.pyinstaller ||
    byName.get("pyinstaller-hooks-contrib").version !==
      toolchain.tools.pyinstallerHooksContrib ||
    byName.get("uv").version !== toolchain.tools.uv
  ) {
    fail("Manifest component versions differ from reviewed pins");
  }

  const certifiProperties = assertObject(
    byName.get("certifi").properties,
    "Certifi component properties"
  );
  const caBundle = resolveArtifact(
    root,
    certifiProperties.caBundlePath,
    "certifi CA bundle"
  );
  if (
    !SHA256_PATTERN.test(certifiProperties.caBundleSha256 || "") ||
    certifiProperties.caBundleSha256 !== sha256File(caBundle)
  ) {
    fail("Certifi CA bundle digest does not match manifest");
  }
}

function validateArtifacts(root, manifest) {
  const artifacts = assertExactKeys(
    manifest.artifacts,
    ["spdxSbom", "thirdPartyNotices", "licensesDirectory"],
    [],
    "Manifest artifacts"
  );
  const sbomPath = resolveArtifact(root, artifacts.spdxSbom, "SBOM");
  resolveArtifact(
    root,
    artifacts.thirdPartyNotices,
    "third-party notices"
  );
  const licensesRelative = safeRelativePath(
    artifacts.licensesDirectory,
    "licenses directory"
  );
  const licensesDirectory = path.join(
    root,
    ...licensesRelative.split("/")
  );
  const resolvedLicenses = requireRealDirectory(
    licensesDirectory,
    "Manifest licenses directory"
  );
  if (!isContained(root, resolvedLicenses)) {
    fail("Manifest licenses directory escapes the sidecar");
  }

  const sbom = loadJson(sbomPath, "SPDX SBOM");
  if (
    sbom.spdxVersion !== "SPDX-2.3" ||
    sbom.dataLicense !== "CC0-1.0" ||
    !Array.isArray(sbom.packages)
  ) {
    fail("SPDX SBOM has an unsupported or incomplete shape");
  }
  const sbomNames = new Set(
    sbom.packages
      .filter(isObject)
      .map((item) => item.name)
      .filter((item) => typeof item === "string")
  );
  for (const component of manifest.components) {
    if (!sbomNames.has(component.name)) {
      fail("SPDX SBOM does not cover every manifest component");
    }
  }
}

function validateManifestShape(manifest, versions, toolchain, schema) {
  assertExactKeys(
    manifest,
    [
      "$schema",
      "schemaVersion",
      "kind",
      "entrypoint",
      "product",
      "target",
      "build",
      "components",
      "artifacts",
      "files",
      "native",
      "audit"
    ],
    [],
    "Python sidecar manifest"
  );
  if (
    manifest.$schema !== MANIFEST_SCHEMA_NAME ||
    manifest.schemaVersion !== MANIFEST_SCHEMA_VERSION ||
    manifest.kind !== EXPECTED_KIND ||
    manifest.entrypoint !== EXPECTED_EXECUTABLE
  ) {
    fail("Python sidecar manifest identity is unsupported");
  }
  validateToolchainLock(toolchain);
  validateSchemaContract(schema, toolchain);
  validateProduct(manifest, versions);
  const target = assertExactKeys(
    manifest.target,
    ["os", "architecture"],
    [],
    "Manifest target"
  );
  if (
    !sameJson(target, {
      os: toolchain.target.os,
      architecture: toolchain.target.architecture
    })
  ) {
    fail("Manifest target differs from the reviewed lock");
  }
}

function validateAuditEvidence(manifest) {
  const audit = assertExactKeys(
    manifest.audit,
    ["status", "policyVersion", "normalizedInventorySha256", "frozenSmoke"],
    [],
    "Manifest audit"
  );
  assertExactKeys(
    audit.frozenSmoke,
    ["status", "pathTrap", "checks"],
    [],
    "Manifest frozen smoke"
  );
  if (
    audit.status !== "pass" ||
    audit.policyVersion !== 1 ||
    !sameJson(audit.frozenSmoke, EXPECTED_FROZEN_SMOKE)
  ) {
    fail("Manifest does not contain complete passing frozen smoke evidence");
  }
  if (!SHA256_PATTERN.test(audit.normalizedInventorySha256)) {
    fail("Manifest normalized inventory digest is malformed");
  }
}

function validateEntrypoint(root) {
  const executable = path.join(root, EXPECTED_EXECUTABLE);
  const info = requireRegularFile(executable, "Sidecar entrypoint");
  if ((info.mode & 0o111) === 0) {
    fail("Sidecar entrypoint must be executable");
  }
  if (!isMachO(executable)) {
    fail("Sidecar entrypoint must be a Mach-O executable");
  }
}

function auditPythonSidecar(options = {}) {
  const repositoryRoot = requireRealDirectory(
    options.repositoryRoot ||
      path.resolve(__dirname, "..", ".."),
    "Repository root"
  );
  const stagingRoot = requireRealDirectory(
    options.stagingRoot ||
      path.join(repositoryRoot, "desktop", "generated", "sidecar"),
    "Sidecar root"
  );
  const environment = options.environment || process.env;
  const platformName = options.platform || process.platform;
  const architecture = options.architecture || process.arch;
  if (platformName !== "darwin" || architecture !== "arm64") {
    fail("Python sidecar packaging requires a Darwin arm64 host");
  }

  const versionPath = path.join(repositoryRoot, "runtime", "version.json");
  const toolchainPath = path.join(
    repositoryRoot,
    "backend",
    "packaging",
    "python-sidecar-toolchain.lock.json"
  );
  const schemaPath = path.join(
    repositoryRoot,
    "runtime",
    MANIFEST_SCHEMA_NAME
  );
  const versions = loadJson(versionPath, "Canonical runtime versions");
  const toolchain = loadJson(toolchainPath, "Python toolchain lock");
  const schema = loadJson(schemaPath, "Python sidecar manifest schema");
  const manifest = loadJson(
    path.join(stagingRoot, MANIFEST_NAME),
    "Python sidecar build manifest"
  );

  validateManifestShape(manifest, versions, toolchain, schema);
  validateBuild(
    manifest,
    toolchain,
    environment,
    repositoryRoot,
    options.inspectSource || inspectSourceFiles,
    options.inspectRepository || inspectRepositoryProvenance
  );
  validateAuditEvidence(manifest);
  validateEntrypoint(stagingRoot);

  if (!Array.isArray(manifest.files)) {
    fail("Manifest file inventory is missing");
  }
  const actualFiles = buildFileInventory(stagingRoot);
  if (!sameJson(manifest.files, actualFiles)) {
    fail("Staged sidecar differs from its exact file inventory");
  }

  const inspectNative =
    options.inspectNative ||
    ((filePath) => inspectMachOWithLipo(filePath, platformName));
  validateNativeInventory(
    stagingRoot,
    actualFiles,
    manifest.native,
    inspectNative
  );
  if (
    manifest.audit.normalizedInventorySha256 !==
    normalizedInventorySha256(manifest.files, manifest.native)
  ) {
    fail("Manifest normalized inventory digest does not match");
  }

  validateComponents(stagingRoot, manifest, toolchain);
  validateArtifacts(stagingRoot, manifest);
  return {
    files: actualFiles.length,
    nativeFiles: manifest.native.length,
    components: manifest.components.length
  };
}

function createBeforePackHook(dependencies = {}) {
  return async function beforePack(context) {
    if (
      !context ||
      context.electronPlatformName !== "darwin" ||
      (dependencies.platform || process.platform) !== "darwin"
    ) {
      fail("beforePack only permits a Darwin packaging target and host");
    }
    if (context.arch !== 3 && context.arch !== "arm64") {
      fail("beforePack only permits an arm64 packaging target");
    }
    return auditPythonSidecar({
      repositoryRoot:
        dependencies.repositoryRoot ||
        path.resolve(__dirname, "..", ".."),
      stagingRoot:
        dependencies.stagingRoot ||
        path.resolve(__dirname, "..", "generated", "sidecar"),
      environment: dependencies.environment || process.env,
      platform: dependencies.platform || process.platform,
      architecture: dependencies.architecture || process.arch,
      inspectNative: dependencies.inspectNative,
      inspectSource: dependencies.inspectSource,
      inspectRepository: dependencies.inspectRepository
    });
  };
}

const beforePack = createBeforePackHook();

module.exports = beforePack;
module.exports.BeforePackAuditError = BeforePackAuditError;
module.exports.EXPECTED_FROZEN_SMOKE = EXPECTED_FROZEN_SMOKE;
module.exports.FIXED_CRITICAL_INPUTS = FIXED_CRITICAL_INPUTS;
module.exports.auditPythonSidecar = auditPythonSidecar;
module.exports.buildFileInventory = buildFileInventory;
module.exports.canonicalJson = canonicalJson;
module.exports.createBeforePackHook = createBeforePackHook;
module.exports.criticalInputDigests = criticalInputDigests;
module.exports.inspectMachOWithLipo = inspectMachOWithLipo;
module.exports.inspectRepositoryProvenance = inspectRepositoryProvenance;
module.exports.inspectSourceFiles = inspectSourceFiles;
module.exports.normalizedInventorySha256 = normalizedInventorySha256;

"use strict";

const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const {
  auditQmdRuntime
} = require("./auditQmdRuntime.cjs");
const {
  auditCompanion
} = require("./auditCompanion.cjs");
const {
  auditRenderer
} = require("./auditRenderer.cjs");
const {
  auditUpdateTrustAnchor
} = require("./auditUpdateTrust.cjs");

const MANIFEST_NAME = "build-manifest.json";
const MANIFEST_SCHEMA_NAME = "python-sidecar-build-manifest.schema.json";
const MANIFEST_SCHEMA_VERSION = 1;
const TOOLCHAIN_EVIDENCE_NAME = "python-build-toolchain.json";
const TOOLCHAIN_EVIDENCE_SCHEMA = "python-sidecar-toolchain-evidence.json";
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
const EXPECTED_PYTHON_BUILD_TOOLS = Object.freeze({
  altgraphVersion: "0.17.4",
  macholibVersion: "1.16.3",
  packagingVersion: "26.2",
  pyinstallerVersion: "6.21.0",
  pyinstallerHooksContribVersion: "2026.6",
  setuptoolsVersion: "83.0.0",
  uvVersion: "0.11.29"
});
const EXPECTED_PYTHON_EXECUTION_CLOSURE = Object.freeze({
  interpreterRelativePath: "bin/python3.13",
  interpreterSize: 119232,
  interpreterSha256:
    "ee3c4103b97e32a98e98cfad7f6ca4d09b2ab2dc16f3d28e18b54a4a0244efe0",
  frameworkBinaryRelativePath: "Python",
  frameworkBinarySize: 13633312,
  frameworkBinarySha256:
    "db77544e7135af8478d62c7d1289581d83714a676c7d3f2b7a4b996bdfef5717"
});
const EXPECTED_FRAMEWORK_CORE_EXCLUDED_PATHS = Object.freeze([
  "Resources/English.lproj/Documentation",
  "bin/pip",
  "bin/pip3",
  "bin/pip3.13",
  "bin/python",
  "bin/python313",
  "etc/openssl/cert.pem",
  "lib/python3.13/site-packages",
  "share/doc/python3.13/html"
]);
const EXPECTED_FRAMEWORK_CORE_SHA256 =
  "fdd600648dfce22601ceb0f5a8464d3784f58aa7d7dd09b288e1c942c14167f9";
const EXPECTED_FRAMEWORK_CORE_INVENTORY = Object.freeze({
  fileName: "python-framework-sealed-inventory.json",
  fileSize: 620662,
  fileSha256:
    "b8ef4275109642632e5b8e254156da410889f0bb38e95188321d602f20496eec",
  schemaVersion: 1,
  sourcePayloadSize: 32739568,
  sourcePayloadSha256:
    "f922c9d7c78f3745dc453211677fbce2e4b415616556b11376a92ca7a17fc391",
  sourceEntryCount: 3654,
  sourceInventorySha256:
    "863a6353e58b9c71dc44847051aa582519a66b9347d8c09915ef5254c694bb5d",
  transformationCount: 39,
  entryCount: 3648,
  inventorySha256: EXPECTED_FRAMEWORK_CORE_SHA256
});
const MAX_FRAMEWORK_CORE_INVENTORY_BYTES = 16 * 1024 * 1024;
const EXPECTED_PYTHON_INSTALL_METHOD =
  "macos-installer-no-op-framework-component";
const EXPECTED_FRAMEWORK_COMPONENT = Object.freeze({
  packageName: "Python_Framework.pkg",
  bomSize: 1404518,
  bomSha256:
    "4e49a4c96076a4855219461f721d510493c6d4f3a7a2a9ad7c981ced723d09bd",
  packageInfoSize: 947,
  packageInfoSha256:
    "86938c44112e37c4791fdc15ee0d89777ed8b6d0a85bae37f7ebf09839072f5c",
  payloadSize: 32739568,
  payloadSha256:
    "f922c9d7c78f3745dc453211677fbce2e4b415616556b11376a92ca7a17fc391",
  scriptsSize: 380,
  scriptsSha256:
    "84fb517c2da6089848bfb6a0ab0e6c508351546d1df9d31abcadd5de4cd42bac",
  postinstallSize: 894,
  postinstallSha256:
    "7821586a42b4d86b075ed2c87da0a5981e5372070b9c7f6141d09f77cb172417",
  postinstallMode: "0755",
  noOpPostinstallSize: 17,
  noOpPostinstallSha256:
    "306c6ca7407560340797866e077e053627ad409277d1b9da58106fce4cf717cb",
  noOpPostinstallMode: "0755"
});
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
  "backend/packaging/python-framework-sealed-inventory.json",
  "backend/packaging/python-sidecar-toolchain.lock.json",
  "backend/pyproject.toml",
  "backend/uv.lock",
  "desktop/electron-builder.yml",
  "desktop/electron-builder.release.yml",
  "desktop/package-lock.json",
  "desktop/package.json",
  "desktop/scripts/afterPack.cjs",
  "desktop/scripts/beforePack.cjs",
  "desktop/scripts/resealPackagedRuntimes.cjs",
  ".github/workflows/desktop-release.yml",
  "runtime/python-sidecar-build-manifest.schema.json",
  "runtime/version.json",
  "tools/audit_python_sidecar.py",
  "tools/bootstrap_python_sidecar.py",
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

function loadCanonicalJsonAttestation(filePath, label) {
  let descriptor;
  let bytes;
  try {
    descriptor = fs.openSync(
      filePath,
      fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW
    );
    const before = fs.fstatSync(descriptor);
    bytes = fs.readFileSync(descriptor);
    const after = fs.fstatSync(descriptor);
    if (
      !before.isFile() ||
      before.uid !== process.geteuid() ||
      before.nlink !== 1 ||
      before.size <= 0 ||
      before.size > 64 * 1024 * 1024 ||
      (before.mode & 0o7022) !== 0 ||
      before.dev !== after.dev ||
      before.ino !== after.ino ||
      before.mode !== after.mode ||
      before.nlink !== after.nlink ||
      before.size !== after.size ||
      before.mtimeMs !== after.mtimeMs ||
      before.ctimeMs !== after.ctimeMs
    ) {
      fail(`${label} must be a stable bounded regular file`);
    }
  } catch (error) {
    if (error instanceof BeforePackAuditError) {
      throw error;
    }
    fail(`${label} is unreadable`);
  } finally {
    if (descriptor !== undefined) {
      fs.closeSync(descriptor);
    }
  }
  let value;
  let text;
  try {
    text = bytes.toString("utf8");
    if (!Buffer.from(text, "utf8").equals(bytes)) {
      fail(`${label} is not valid UTF-8`);
    }
    value = JSON.parse(text);
  } catch (error) {
    if (error instanceof BeforePackAuditError) {
      throw error;
    }
    fail(`${label} is not valid JSON`);
  }
  if (!isObject(value) || text !== `${canonicalJson(value)}\n`) {
    fail(`${label} is not a canonical object`);
  }
  return {
    value,
    sha256: crypto.createHash("sha256").update(bytes).digest("hex")
  };
}

function loadBoundedJsonAttestation(filePath, label, maximumBytes) {
  let descriptor;
  let bytes;
  try {
    descriptor = fs.openSync(
      filePath,
      fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW
    );
    const before = fs.fstatSync(descriptor);
    if (
      !before.isFile() ||
      before.uid !== process.geteuid() ||
      before.nlink !== 1 ||
      before.size <= 0 ||
      before.size > maximumBytes ||
      (before.mode & 0o7022) !== 0
    ) {
      fail(`${label} must be a stable bounded regular file`);
    }
    bytes = fs.readFileSync(descriptor);
    const after = fs.fstatSync(descriptor);
    const namedAfter = fs.lstatSync(filePath);
    if (
      !namedAfter.isFile() ||
      namedAfter.isSymbolicLink() ||
      bytes.length !== before.size ||
      before.dev !== after.dev ||
      before.ino !== after.ino ||
      before.mode !== after.mode ||
      before.uid !== after.uid ||
      before.gid !== after.gid ||
      before.nlink !== after.nlink ||
      before.size !== after.size ||
      before.mtimeMs !== after.mtimeMs ||
      before.ctimeMs !== after.ctimeMs ||
      before.dev !== namedAfter.dev ||
      before.ino !== namedAfter.ino ||
      before.mode !== namedAfter.mode ||
      before.uid !== namedAfter.uid ||
      before.gid !== namedAfter.gid ||
      before.nlink !== namedAfter.nlink ||
      before.size !== namedAfter.size ||
      before.mtimeMs !== namedAfter.mtimeMs ||
      before.ctimeMs !== namedAfter.ctimeMs
    ) {
      fail(`${label} changed while being read`);
    }
  } catch (error) {
    if (error instanceof BeforePackAuditError) {
      throw error;
    }
    fail(`${label} is unreadable`);
  } finally {
    if (descriptor !== undefined) {
      fs.closeSync(descriptor);
    }
  }
  let value;
  try {
    const text = bytes.toString("utf8");
    if (!Buffer.from(text, "utf8").equals(bytes)) {
      fail(`${label} is not valid UTF-8`);
    }
    value = JSON.parse(text);
  } catch (error) {
    if (error instanceof BeforePackAuditError) {
      throw error;
    }
    fail(`${label} is not valid JSON`);
  }
  if (!isObject(value)) {
    fail(`${label} must be an object`);
  }
  return {
    value,
    size: bytes.length,
    sha256: crypto.createHash("sha256").update(bytes).digest("hex")
  };
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

function validateFrameworkCoreInventory(repositoryRoot, python) {
  const contract = assertExactKeys(
    python.frameworkCoreInventory,
    [
      "fileName",
      "fileSize",
      "fileSha256",
      "schemaVersion",
      "sourcePayloadSize",
      "sourcePayloadSha256",
      "sourceEntryCount",
      "sourceInventorySha256",
      "transformationCount",
      "entryCount",
      "inventorySha256"
    ],
    [],
    "Toolchain Python framework core inventory"
  );
  if (
    contract.fileName !== EXPECTED_FRAMEWORK_CORE_INVENTORY.fileName ||
    !Number.isSafeInteger(contract.fileSize) ||
    contract.fileSize <= 0 ||
    contract.fileSize > MAX_FRAMEWORK_CORE_INVENTORY_BYTES ||
    typeof contract.fileSha256 !== "string" ||
    !SHA256_PATTERN.test(contract.fileSha256) ||
    Object.entries(EXPECTED_FRAMEWORK_CORE_INVENTORY).some(
      ([key, expected]) => contract[key] !== expected
    ) ||
    contract.inventorySha256 !== python.frameworkCoreFingerprintSha256
  ) {
    fail("Python framework core inventory differs from the reviewed contract");
  }

  const inventoryDirectory = path.join(
    repositoryRoot,
    "backend",
    "packaging"
  );
  if (
    requireRealDirectory(
      inventoryDirectory,
      "Reviewed Python framework inventory directory"
    ) !== inventoryDirectory
  ) {
    fail("Reviewed Python framework inventory directory is not canonical");
  }
  const inventoryPath = path.join(inventoryDirectory, contract.fileName);
  const attestation = loadBoundedJsonAttestation(
    inventoryPath,
    "Reviewed Python framework core inventory",
    MAX_FRAMEWORK_CORE_INVENTORY_BYTES
  );
  if (
    attestation.size !== contract.fileSize ||
    attestation.sha256 !== contract.fileSha256
  ) {
    fail("Reviewed Python framework core inventory file differs from its lock");
  }
  const inventory = assertExactKeys(
    attestation.value,
    [
      "schemaVersion",
      "source",
      "transformations",
      "entryCount",
      "inventorySha256",
      "entries"
    ],
    [],
    "Reviewed Python framework core inventory"
  );
  const source = assertExactKeys(
    inventory.source,
    [
      "payloadSize",
      "payloadSha256",
      "coreEntryCount",
      "coreInventorySha256"
    ],
    [],
    "Reviewed Python framework source inventory"
  );
  if (
    inventory.schemaVersion !== contract.schemaVersion ||
    source.payloadSize !== contract.sourcePayloadSize ||
    source.payloadSha256 !== contract.sourcePayloadSha256 ||
    source.coreEntryCount !== contract.sourceEntryCount ||
    source.coreInventorySha256 !== contract.sourceInventorySha256 ||
    !Array.isArray(inventory.transformations) ||
    inventory.transformations.length !== contract.transformationCount ||
    inventory.entryCount !== contract.entryCount ||
    inventory.inventorySha256 !== contract.inventorySha256 ||
    !Array.isArray(inventory.entries) ||
    inventory.entries.length !== contract.entryCount ||
    sha256Bytes(Buffer.from(canonicalJson(inventory.entries), "utf8")) !==
      contract.inventorySha256
  ) {
    fail("Reviewed Python framework core inventory metadata is inconsistent");
  }
}

function validateToolchainLock(toolchain, repositoryRoot) {
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
  const python = assertExactKeys(
    toolchain.python,
    [
      "implementation",
      "version",
      "installRoot",
      "interpreterRelativePath",
      "interpreterSize",
      "interpreterSha256",
      "frameworkBinaryRelativePath",
      "frameworkBinarySize",
      "frameworkBinarySha256",
      "frameworkCoreFingerprintExcludedPaths",
      "frameworkCoreFingerprintSha256",
      "frameworkCoreInventory",
      "reviewedBrokenSymlinks",
      "distribution"
    ],
    [],
    "Toolchain Python"
  );
  const executionClosure = {
    interpreterRelativePath: python.interpreterRelativePath,
    interpreterSize: python.interpreterSize,
    interpreterSha256: python.interpreterSha256,
    frameworkBinaryRelativePath: python.frameworkBinaryRelativePath,
    frameworkBinarySize: python.frameworkBinarySize,
    frameworkBinarySha256: python.frameworkBinarySha256
  };
  if (!sameJson(executionClosure, EXPECTED_PYTHON_EXECUTION_CLOSURE)) {
    fail("Python toolchain execution closure differs from the reviewed lock");
  }
  if (
    !sameJson(
      python.frameworkCoreFingerprintExcludedPaths,
      EXPECTED_FRAMEWORK_CORE_EXCLUDED_PATHS
    ) ||
    python.frameworkCoreFingerprintSha256 !== EXPECTED_FRAMEWORK_CORE_SHA256
  ) {
    fail("Python toolchain framework core differs from the reviewed lock");
  }
  validateFrameworkCoreInventory(repositoryRoot, python);
  if (!Array.isArray(python.reviewedBrokenSymlinks)) {
    fail("Toolchain reviewed broken symlinks are malformed");
  }
  const reviewedBrokenPaths = [];
  for (const rawEntry of python.reviewedBrokenSymlinks) {
    const entry = assertExactKeys(
      rawEntry,
      ["path", "target"],
      [],
      "Toolchain reviewed broken symlink"
    );
    const relative = safeRelativePath(
      entry.path,
      "Toolchain reviewed broken symlink"
    );
    const target = entry.target;
    if (
      relative.split("/").some((part) => part === "" || part === ".") ||
      typeof target !== "string" ||
      target.length === 0 ||
      target.startsWith("/") ||
      target.includes("\\") ||
      target.includes("\0") ||
      target
        .split("/")
        .some((part) => part === "" || part === "." || part === "..") ||
      reviewedBrokenPaths.includes(relative)
    ) {
      fail("Toolchain reviewed broken symlink is unsafe");
    }
    reviewedBrokenPaths.push(relative);
  }
  if (
    !sameJson(
      reviewedBrokenPaths,
      [...reviewedBrokenPaths].sort(compareCodePoints)
    )
  ) {
    fail("Toolchain reviewed broken symlinks are not ordered");
  }
  const distribution = assertExactKeys(
    python.distribution,
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
      "frameworkComponent",
      "hashManifestName",
      "hashManifestSource",
      "hashManifestSha256",
      "hashManifestSize"
    ],
    [],
    "Toolchain Python distribution"
  );
  const frameworkComponent = assertExactKeys(
    distribution.frameworkComponent,
    Object.keys(EXPECTED_FRAMEWORK_COMPONENT),
    [],
    "Toolchain Python framework component"
  );
  const componentSizeFields = [
    "bomSize",
    "packageInfoSize",
    "payloadSize",
    "scriptsSize",
    "postinstallSize",
    "noOpPostinstallSize"
  ];
  const componentHashFields = [
    "bomSha256",
    "packageInfoSha256",
    "payloadSha256",
    "scriptsSha256",
    "postinstallSha256",
    "noOpPostinstallSha256"
  ];
  if (
    componentSizeFields.some(
      (key) =>
        !Number.isSafeInteger(frameworkComponent[key]) ||
        frameworkComponent[key] <= 0
    ) ||
    componentHashFields.some(
      (key) =>
        typeof frameworkComponent[key] !== "string" ||
        !SHA256_PATTERN.test(frameworkComponent[key])
    ) ||
    frameworkComponent.postinstallMode !== "0755" ||
    frameworkComponent.noOpPostinstallMode !== "0755" ||
    !sameJson(frameworkComponent, EXPECTED_FRAMEWORK_COMPONENT)
  ) {
    fail("Python framework component differs from the reviewed contract");
  }
  assertExactKeys(
    toolchain.tools,
    ["uv", "pyinstaller", "pyinstallerHooksContrib"],
    [],
    "Toolchain build tools"
  );
  const mandatoryInputs = [
    "LCF_SOURCE_SHA",
    "LCF_SOURCE_TREE",
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
  if (
    !COMMIT_PATTERN.test(distribution.releaseCommit) ||
    !Number.isSafeInteger(distribution.archiveSize) ||
    distribution.archiveSize <= 0 ||
    !Number.isSafeInteger(distribution.hashManifestSize) ||
    distribution.hashManifestSize <= 0 ||
    distribution.installMethod !== EXPECTED_PYTHON_INSTALL_METHOD ||
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
  const buildRequired = schema.properties.build?.required;
  const artifactsSchema = schema.properties.artifacts;
  const pythonToolchainSchema = schema.$defs.pythonToolchain;
  const buildToolsSchema = schema.$defs.buildTools;
  const targetProperties = schema.properties.target?.properties;
  const pythonProperties = schema.$defs.pythonProvenance?.properties;
  const nativeProperties = schema.$defs.nativeInventoryEntry?.properties;
  const frozenSmokeProperties =
    schema.properties.audit?.properties?.frozenSmoke?.properties;
  const expectedPython = expectedPythonProvenance(toolchain);
  if (
    !isObject(buildProperties) ||
    !sameJson(buildRequired, [
      "repositoryCommit",
      "repositoryTree",
      "sourceSnapshotSha256",
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
      "pythonToolchain",
      "inputDigests"
    ]) ||
    !isObject(artifactsSchema) ||
    artifactsSchema.additionalProperties !== false ||
    !sameJson(artifactsSchema.required, [
      "spdxSbom",
      "thirdPartyNotices",
      "licensesDirectory",
      "pythonBuildToolchain"
    ]) ||
    artifactsSchema.properties?.pythonBuildToolchain?.$ref !==
      "#/$defs/safePath" ||
    !isObject(pythonToolchainSchema) ||
    pythonToolchainSchema.additionalProperties !== false ||
    !sameJson(pythonToolchainSchema.required, [
      "buildRequirementsLockSha256",
      "runtimeLockSha256",
      "runtimeRequirementsSha256",
      "installedTreeContentSha256",
      "buildTools"
    ]) ||
    !isObject(buildToolsSchema) ||
    buildToolsSchema.additionalProperties !== false ||
    !sameJson(buildToolsSchema.required, Object.keys(EXPECTED_PYTHON_BUILD_TOOLS)) ||
    Object.entries(EXPECTED_PYTHON_BUILD_TOOLS).some(
      ([key, version]) => buildToolsSchema.properties?.[key]?.const !== version
    ) ||
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

function inspectRepositoryProvenance(
  repositoryRoot,
  environment = process.env
) {
  let snapshot;
  try {
    snapshot = require("./prepareEngineeringSmoke.cjs")
      .inspectRepositorySourceSnapshot(repositoryRoot, environment);
  } catch {
    fail("Repository provenance inspection failed");
  }
  return {
    commit: snapshot.commit,
    tree: snapshot.tree,
    sourceDateEpoch: snapshot.sourceDateEpoch,
    sourceSnapshotSha256: snapshot.sourceSnapshotSha256
  };
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
  if (!COMMIT_PATTERN.test(environment.LCF_SOURCE_SHA || "")) {
    fail("Current LCF_SOURCE_SHA is invalid");
  }
  if (!COMMIT_PATTERN.test(environment.LCF_SOURCE_TREE || "")) {
    fail("Current LCF_SOURCE_TREE is invalid");
  }
  if (build.repositoryCommit !== environment.LCF_SOURCE_SHA) {
    fail("Manifest commit differs from the explicit source commit");
  }
  if (build.repositoryTree !== environment.LCF_SOURCE_TREE) {
    fail("Manifest tree differs from the explicit source tree");
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
    inspectRepository(repositoryRoot, environment),
    ["commit", "tree", "sourceDateEpoch", "sourceSnapshotSha256"],
    [],
    "Observed repository provenance"
  );
  if (
    repository.commit !== build.repositoryCommit ||
    repository.tree !== build.repositoryTree ||
    repository.sourceDateEpoch !== build.sourceDateEpoch ||
    repository.sourceSnapshotSha256 !== build.sourceSnapshotSha256
  ) {
    fail("Manifest repository provenance differs from the checkout");
  }
}

function validatePythonToolchainSummary(value, repositoryRoot) {
  const summary = assertExactKeys(
    value,
    [
      "buildRequirementsLockSha256",
      "runtimeLockSha256",
      "runtimeRequirementsSha256",
      "installedTreeContentSha256",
      "buildTools"
    ],
    [],
    "Manifest Python toolchain evidence"
  );
  for (const key of [
    "buildRequirementsLockSha256",
    "runtimeLockSha256",
    "runtimeRequirementsSha256",
    "installedTreeContentSha256"
  ]) {
    if (!SHA256_PATTERN.test(summary[key] || "")) {
      fail("Manifest Python toolchain digest is malformed");
    }
  }
  const buildTools = assertExactKeys(
    summary.buildTools,
    Object.keys(EXPECTED_PYTHON_BUILD_TOOLS),
    [],
    "Manifest Python build tools"
  );
  if (!sameJson(buildTools, EXPECTED_PYTHON_BUILD_TOOLS)) {
    fail("Manifest Python build tool versions differ from reviewed pins");
  }
  if (
    summary.buildRequirementsLockSha256 !==
      sha256File(
        path.join(
          repositoryRoot,
          "backend",
          "packaging",
          "build-requirements.lock"
        )
      ) ||
    summary.runtimeLockSha256 !==
      sha256File(path.join(repositoryRoot, "backend", "uv.lock"))
  ) {
    fail("Manifest Python toolchain differs from reviewed source locks");
  }
  return summary;
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
      "repositoryTree",
      "sourceSnapshotSha256",
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
      "pythonToolchain",
      "inputDigests"
    ],
    [],
    "Manifest build"
  );
  if (
    !COMMIT_PATTERN.test(build.repositoryCommit) ||
    !COMMIT_PATTERN.test(build.repositoryTree) ||
    !SHA256_PATTERN.test(build.sourceSnapshotSha256) ||
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

  validatePythonToolchainSummary(
    build.pythonToolchain,
    repositoryRoot
  );

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

function safeToolchainSymlinkTarget(relative, target, reviewedFrameworkRoot) {
  if (
    typeof target !== "string" ||
    target.length === 0 ||
    target.includes("\0") ||
    target.includes("\\")
  ) {
    return false;
  }
  if (target.startsWith("/")) {
    const parts = target.split("/");
    if (
      parts[0] !== "" ||
      parts.slice(1).some((part) => ["", ".", ".."].includes(part))
    ) {
      return false;
    }
    return (
      target !== reviewedFrameworkRoot &&
      target.startsWith(`${reviewedFrameworkRoot}/`)
    );
  }
  const parts = path.posix.dirname(relative).split("/").filter(Boolean);
  for (const part of target.split("/")) {
    if (part === "" || part === ".") {
      continue;
    }
    if (part === "..") {
      if (parts.length === 0) {
        return false;
      }
      parts.pop();
    } else {
      parts.push(part);
    }
  }
  return parts.length > 0;
}

function validateInstalledToolchainInventory(
  value,
  reviewedFrameworkRoot
) {
  if (!Array.isArray(value) || value.length < 1 || value.length > 100_000) {
    fail("Installed Python toolchain inventory is invalid");
  }
  const paths = [];
  let totalSize = 0;
  for (const rawEntry of value) {
    const entry = assertObject(rawEntry, "Installed Python toolchain entry");
    const entryType = entry.type;
    const required = {
      directory: ["path", "type", "mode", "size"],
      file: ["path", "type", "mode", "size", "sha256"],
      symlink: ["path", "type", "mode", "size", "target"]
    }[entryType];
    if (!required) {
      fail("Installed Python toolchain entry type is invalid");
    }
    assertExactKeys(entry, required, [], "Installed Python toolchain entry");
    const relative = entry.path;
    if (
      typeof relative !== "string" ||
      relative.length === 0 ||
      (relative !== "." &&
        (safeRelativePath(relative, "Installed Python toolchain entry") !==
          relative ||
          path.posix.normalize(relative) !== relative)) ||
      !/^0[0-7]{3}$/.test(entry.mode || "") ||
      !Number.isSafeInteger(entry.size) ||
      entry.size < 0 ||
      entry.size > 256 * 1024 * 1024
    ) {
      fail("Installed Python toolchain entry is malformed");
    }
    const mode = Number.parseInt(entry.mode, 8);
    if (
      (entryType === "directory" &&
        (entry.size !== 0 || ![0o500, 0o555].includes(mode))) ||
      (entryType === "file" &&
        (![0o400, 0o444, 0o500, 0o555].includes(mode) ||
          !SHA256_PATTERN.test(entry.sha256 || ""))) ||
      (entryType === "symlink" &&
        (mode !== 0o777 ||
          typeof entry.target !== "string" ||
          Buffer.byteLength(entry.target || "", "utf8") !== entry.size ||
          !safeToolchainSymlinkTarget(
            relative,
            entry.target,
            reviewedFrameworkRoot
          )))
    ) {
      fail("Installed Python toolchain entry is malformed");
    }
    paths.push(relative);
    totalSize += entry.size;
    if (totalSize > 1024 * 1024 * 1024) {
      fail("Installed Python toolchain inventory exceeds its size bound");
    }
  }
  const sortedPaths = [...paths].sort(compareCodePoints);
  if (
    paths[0] !== "." ||
    new Set(paths).size !== paths.length ||
    !sameJson(paths, sortedPaths)
  ) {
    fail("Installed Python toolchain inventory paths are noncanonical");
  }
  return sha256Bytes(
    Buffer.from(
      canonicalJson({ schemaVersion: 1, entries: value }),
      "utf8"
    )
  );
}

function validatePythonToolchainArtifact(root, manifest, repositoryRoot) {
  const summary = validatePythonToolchainSummary(
    manifest.build.pythonToolchain,
    repositoryRoot
  );
  if (manifest.artifacts.pythonBuildToolchain !== TOOLCHAIN_EVIDENCE_NAME) {
    fail("Python build toolchain evidence path is unexpected");
  }
  const evidenceAttestation = loadCanonicalJsonAttestation(
    resolveArtifact(
      root,
      manifest.artifacts.pythonBuildToolchain,
      "Python build toolchain evidence"
    ),
    "Python build toolchain evidence"
  );
  const evidence = assertExactKeys(
    evidenceAttestation.value,
    [
      "$schema",
      "schemaVersion",
      "buildRequirementsLockSha256",
      "runtimeLockSha256",
      "runtimeRequirementsSha256",
      "installedTreeContentSha256",
      "buildTools",
      "files"
    ],
    [],
    "Python build toolchain evidence"
  );
  if (
    evidence.$schema !== TOOLCHAIN_EVIDENCE_SCHEMA ||
    evidence.schemaVersion !== 1 ||
    !sameJson(
      Object.fromEntries(
        [
          "buildRequirementsLockSha256",
          "runtimeLockSha256",
          "runtimeRequirementsSha256",
          "installedTreeContentSha256",
          "buildTools"
        ].map((key) => [key, evidence[key]])
      ),
      summary
    ) ||
    validateInstalledToolchainInventory(
      evidence.files,
      manifest.build.python.installRoot
    ) !== evidence.installedTreeContentSha256
  ) {
    fail("Python build toolchain artifact differs from the manifest");
  }
}

function validateArtifacts(root, manifest, repositoryRoot) {
  const artifacts = assertExactKeys(
    manifest.artifacts,
    [
      "spdxSbom",
      "thirdPartyNotices",
      "licensesDirectory",
      "pythonBuildToolchain"
    ],
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
  validatePythonToolchainArtifact(root, manifest, repositoryRoot);
}

function validateManifestShape(
  manifest,
  versions,
  toolchain,
  schema,
  repositoryRoot
) {
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
  validateToolchainLock(toolchain, repositoryRoot);
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
  const manifestAttestation = loadCanonicalJsonAttestation(
    path.join(stagingRoot, MANIFEST_NAME),
    "Python sidecar build manifest"
  );
  const manifest = manifestAttestation.value;

  validateManifestShape(
    manifest,
    versions,
    toolchain,
    schema,
    repositoryRoot
  );
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
  validateArtifacts(stagingRoot, manifest, repositoryRoot);
  return {
    files: actualFiles.length,
    nativeFiles: manifest.native.length,
    components: manifest.components.length,
    repositoryCommit: manifest.build.repositoryCommit,
    repositoryTree: manifest.build.repositoryTree,
    sourceSnapshotSha256: manifest.build.sourceSnapshotSha256,
    normalizedInventorySha256: manifest.audit.normalizedInventorySha256,
    manifest: JSON.parse(JSON.stringify(manifest)),
    manifestSha256: manifestAttestation.sha256
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
    const repositoryRoot =
      dependencies.repositoryRoot ||
      path.resolve(__dirname, "..", "..");
    const repository = (
      dependencies.inspectRepository || inspectRepositoryProvenance
    )(repositoryRoot, dependencies.environment || process.env);
    const python = (
      dependencies.auditPythonSidecar || auditPythonSidecar
    )({
      repositoryRoot:
        repositoryRoot,
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
    const qmd = (
      dependencies.auditQmdRuntime || auditQmdRuntime
    )({
      repositoryRoot,
      stagingRoot:
        dependencies.qmdStagingRoot ||
        path.resolve(__dirname, "..", "generated", "qmd"),
      environment: dependencies.environment || process.env,
      platform: dependencies.platform || process.platform,
      architecture: dependencies.architecture || process.arch,
      inspectNative: dependencies.inspectQmdNative,
      inspectSource: dependencies.inspectQmdSource,
      inspectRepository: dependencies.inspectQmdRepository
    });
    const companion = (
      dependencies.auditCompanion || auditCompanion
    )({
      repositoryRoot,
      stagingRoot:
        dependencies.companionStagingRoot ||
        path.resolve(__dirname, "..", "generated", "companion")
    });
    const renderer = (
      dependencies.auditRenderer || auditRenderer
    )(
      dependencies.rendererRoot ||
        path.resolve(__dirname, "..", "resources", "renderer"),
      {
        expectedCommit:
          (dependencies.environment || process.env).LCF_SOURCE_SHA,
        expectedTree: repository.tree,
        expectedSourceSnapshotSha256: repository.sourceSnapshotSha256,
        expectedSourceDateEpoch: Number(
          (dependencies.environment || process.env).LCF_SOURCE_DATE_EPOCH
        ),
        expectedPackageLockSha256:
          (dependencies.environment || process.env)
            .LCF_RENDERER_PACKAGE_LOCK_SHA256
      }
    );
    const updateTrust = (
      dependencies.auditUpdateTrustAnchor || auditUpdateTrustAnchor
    )({ repositoryRoot });
    return { python, qmd, companion, renderer, updateTrust };
  };
}

const beforePack = createBeforePackHook();

module.exports = beforePack;
module.exports.BeforePackAuditError = BeforePackAuditError;
module.exports.EXPECTED_FROZEN_SMOKE = EXPECTED_FROZEN_SMOKE;
module.exports.FIXED_CRITICAL_INPUTS = FIXED_CRITICAL_INPUTS;
module.exports.auditPythonSidecar = auditPythonSidecar;
module.exports.auditUpdateTrustAnchor = auditUpdateTrustAnchor;
module.exports.buildFileInventory = buildFileInventory;
module.exports.canonicalJson = canonicalJson;
module.exports.createBeforePackHook = createBeforePackHook;
module.exports.criticalInputDigests = criticalInputDigests;
module.exports.inspectMachOWithLipo = inspectMachOWithLipo;
module.exports.inspectRepositoryProvenance = inspectRepositoryProvenance;
module.exports.inspectSourceFiles = inspectSourceFiles;
module.exports.normalizedInventorySha256 = normalizedInventorySha256;

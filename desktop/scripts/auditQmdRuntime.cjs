"use strict";

const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const MANIFEST_NAME = "runtime-manifest.json";
const MANIFEST_DIGEST_NAME = "runtime-manifest.sha256";
const MANIFEST_SCHEMA_NAME = "qmd-runtime-build-manifest.schema.json";
const TOOLCHAIN_NAME = "qmd-runtime-toolchain.lock.json";
const EXPECTED_KIND = "local-context-forge-qmd-runtime";
const EXPECTED_NATIVE_SMOKE = Object.freeze({
  status: "pass",
  pathTrap: true,
  networkTrap: true,
  modelFilesCreated: 0,
  checks: Object.freeze([
    "node-version",
    "worker-contract",
    "better-sqlite3-native-load",
    "uds-health",
    "qmd-reconcile",
    "qmd-lexical-search",
    "offline-no-model"
  ])
});
const EXPECTED_WORKER_SOURCE_PATHS = Object.freeze([
  "desktop/workers/qmd/index.mjs",
  "desktop/workers/qmd/package.json",
  "desktop/workers/qmd/package-lock.json",
  "desktop/workers/qmd/src/contract.mjs",
  "desktop/workers/qmd/src/indexService.mjs",
  "desktop/workers/qmd/src/server.mjs",
  "desktop/workers/qmd/test/indexService.test.mjs",
  "desktop/workers/qmd/test/qmdSdkIntegration.test.mjs",
  "desktop/workers/qmd/test/server.test.mjs"
]);
const EXPECTED_REQUIRED_CI_INPUTS = Object.freeze([
  "GITHUB_SHA",
  "LCF_SOURCE_DATE_EPOCH",
  "ImageVersion",
  "LCF_QMD_NODE_ARCHIVE",
  "LCF_QMD_NODE_HASH_MANIFEST",
  "LCF_QMD_BUILD_PYTHON"
]);
const SHA1_PATTERN = /^[0-9a-f]{40}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const RUNNER_IMAGE_PATTERN = /^[0-9]{8}\.[0-9]+\.[0-9]+$/;
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
const REQUIRED_COMPONENTS = new Map([
  ["node", "22.23.2"],
  ["@tobilu/qmd", "2.5.3"],
  ["better-sqlite3", "12.10.0"]
]);
const FIXED_CRITICAL_INPUTS = Object.freeze([
  ".github/workflows/desktop-release.yml",
  "desktop/electron-builder.release.yml",
  "desktop/electron-builder.yml",
  "desktop/scripts/afterPack.cjs",
  "desktop/scripts/beforePack.cjs",
  "desktop/scripts/auditQmdRuntime.cjs",
  "desktop/scripts/buildQmdRuntime.cjs",
  "desktop/scripts/qmdNetworkTrap.mjs",
  "desktop/scripts/qmdRuntimeSmoke.mjs",
  "desktop/scripts/resealPackagedRuntimes.cjs",
  "runtime/qmd-runtime-build-manifest.schema.json",
  "runtime/qmd-runtime-toolchain.lock.json",
  "runtime/version.json"
]);

class QmdRuntimeAuditError extends Error {
  constructor(message) {
    super(message);
    this.name = "QmdRuntimeAuditError";
  }
}

function fail(message) {
  throw new QmdRuntimeAuditError(message);
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
    fail("Unable to canonicalize QMD runtime evidence");
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
    fail("Unable to hash an audited QMD runtime file");
  } finally {
    if (descriptor !== undefined) {
      fs.closeSync(descriptor);
    }
  }
  return digest.digest("hex");
}

function requireRealDirectory(directory, label) {
  let info;
  try {
    info = fs.lstatSync(directory);
  } catch {
    fail(`${label} is missing`);
  }
  if (!info.isDirectory() || info.isSymbolicLink()) {
    fail(`${label} must be a real directory`);
  }
  let resolved;
  try {
    resolved = fs.realpathSync.native(directory);
  } catch {
    fail(`${label} cannot be resolved`);
  }
  if (path.resolve(directory) !== resolved) {
    fail(`${label} must not contain a symlinked final component`);
  }
  return resolved;
}

function requireRegularFile(filePath, label) {
  let info;
  try {
    info = fs.lstatSync(filePath);
  } catch {
    fail(`${label} is missing`);
  }
  if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1) {
    fail(`${label} must be an unlinked regular file`);
  }
  return info;
}

function loadJson(filePath, label) {
  requireRegularFile(filePath, label);
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

function safeRelativePath(value, label) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.includes("\0") ||
    value.includes("\\") ||
    path.posix.isAbsolute(value)
  ) {
    fail(`${label} is not a safe relative path`);
  }
  const normalized = path.posix.normalize(value);
  if (
    normalized !== value ||
    normalized === "." ||
    normalized === ".." ||
    normalized.startsWith("../")
  ) {
    fail(`${label} is not a canonical relative path`);
  }
  return value;
}

function resolvePayload(root, relative, label) {
  const safe = safeRelativePath(relative, label);
  const candidate = path.join(root, ...safe.split("/"));
  requireRegularFile(candidate, label);
  const resolved = fs.realpathSync.native(candidate);
  if (
    resolved !== candidate ||
    !resolved.startsWith(`${root}${path.sep}`)
  ) {
    fail(`${label} escapes the QMD runtime`);
  }
  return candidate;
}

function isMachO(filePath) {
  const descriptor = fs.openSync(filePath, "r");
  try {
    const magic = Buffer.alloc(4);
    if (fs.readSync(descriptor, magic, 0, 4, 0) !== 4) {
      return false;
    }
    return MACHO_MAGICS.has(magic.toString("hex"));
  } finally {
    fs.closeSync(descriptor);
  }
}

function walkPayload(root) {
  const files = [];
  function visit(directory) {
    const names = fs.readdirSync(directory).sort(compareCodePoints);
    for (const name of names) {
      const candidate = path.join(directory, name);
      const relative = path.relative(root, candidate).split(path.sep).join("/");
      if (
        relative === MANIFEST_NAME ||
        relative === MANIFEST_DIGEST_NAME
      ) {
        continue;
      }
      const info = fs.lstatSync(candidate);
      if (info.isSymbolicLink()) {
        fail("QMD runtime payload must not contain symlinks");
      }
      if (info.isDirectory()) {
        visit(candidate);
        continue;
      }
      if (!info.isFile() || info.nlink !== 1) {
        fail("QMD runtime payload contains a special or hard-linked file");
      }
      files.push({ candidate, relative, info });
    }
  }
  visit(root);
  return files;
}

function buildFileInventory(root) {
  return walkPayload(root).map(({ candidate, relative, info }) => ({
    path: relative,
    size: info.size,
    mode: (info.mode & 0o7777).toString(8).padStart(4, "0"),
    sha256: sha256File(candidate)
  }));
}

function runTool(executable, arguments_, label) {
  try {
    return childProcess.execFileSync(executable, arguments_, {
      encoding: "utf8",
      env: {
        PATH: "/usr/bin:/bin",
        LANG: "C",
        LC_ALL: "C"
      },
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 30_000,
      maxBuffer: 4 * 1024 * 1024
    });
  } catch {
    fail(`${label} failed`);
  }
}

function inspectMachO(filePath, platformName = process.platform) {
  if (platformName !== "darwin") {
    fail("Mach-O inspection requires macOS");
  }
  const architectures = runTool(
    "/usr/bin/lipo",
    ["-archs", filePath],
    "lipo inspection"
  )
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .sort(compareCodePoints);
  if (!sameJson(architectures, ["arm64"])) {
    fail("QMD native payload is not arm64-only");
  }

  const dependencyLines = runTool(
    "/usr/bin/otool",
    ["-L", filePath],
    "Mach-O dependency inspection"
  )
    .split(/\r?\n/)
    .slice(1)
    .map((line) => line.trim())
    .filter(Boolean);
  const dependencies = dependencyLines.map((line) => line.split(" (", 1)[0]);
  for (const dependency of dependencies) {
    if (
      !dependency.startsWith("@rpath/") &&
      !dependency.startsWith("@loader_path/") &&
      !dependency.startsWith("@executable_path/") &&
      !dependency.startsWith("/usr/lib/") &&
      !dependency.startsWith("/System/Library/")
    ) {
      fail("QMD native payload links outside the controlled/system closure");
    }
  }

  const loadCommands = runTool(
    "/usr/bin/otool",
    ["-l", filePath],
    "Mach-O load-command inspection"
  ).split(/\r?\n/);
  const rpaths = [];
  for (let index = 0; index < loadCommands.length; index += 1) {
    if (loadCommands[index].trim() !== "cmd LC_RPATH") {
      continue;
    }
    const next = loadCommands
      .slice(index + 1, index + 5)
      .map((line) => line.trim())
      .find((line) => line.startsWith("path "));
    if (!next) {
      fail("QMD native payload contains a malformed LC_RPATH");
    }
    const rpath = next.slice("path ".length).split(" (offset", 1)[0];
    if (
      !rpath.startsWith("@loader_path") &&
      !rpath.startsWith("@executable_path")
    ) {
      fail("QMD native payload contains an unsafe LC_RPATH");
    }
    rpaths.push(rpath);
  }
  runTool(
    "/usr/bin/codesign",
    ["--verify", "--strict", "--verbose=2", filePath],
    "QMD native code-signature verification"
  );
  return {
    architectures,
    dependencies: dependencies.sort(compareCodePoints),
    rpaths: rpaths.sort(compareCodePoints),
    codeSignature: "valid"
  };
}

function buildNativeInventory(root, inspectNative = inspectMachO) {
  return walkPayload(root)
    .filter(({ candidate }) => isMachO(candidate))
    .map(({ candidate, relative }) => ({
      path: relative,
      ...inspectNative(candidate)
    }));
}

function validateToolchain(lock) {
  if (
    lock.schemaVersion !== 1 ||
    !isObject(lock.target) ||
    !isObject(lock.node) ||
    !isObject(lock.worker) ||
    !isObject(lock.buildPython) ||
    !Array.isArray(lock.requiredCiInputs) ||
    !sameJson(lock.target, {
      os: "darwin",
      architecture: "arm64",
      runnerLabel: "macos-15",
      deploymentTarget: "14.0"
    }) ||
    lock.node.version !== "22.23.2" ||
    lock.node.archiveName !==
      "node-v22.23.2-darwin-arm64.tar.gz" ||
    lock.node.archiveRoot !==
      "node-v22.23.2-darwin-arm64" ||
    lock.node.archiveSource !==
      "https://nodejs.org/download/release/v22.23.2/node-v22.23.2-darwin-arm64.tar.gz" ||
    lock.node.archiveSha256 !==
      "61130f394c1630d211dd50aecc4353d379480f36d3ac913cd85dbba1aed585c6" ||
    lock.node.archiveSize !== 50068815 ||
    lock.node.hashManifestName !== "SHASUMS256.txt" ||
    lock.node.hashManifestSource !==
      "https://nodejs.org/download/release/v22.23.2/SHASUMS256.txt" ||
    lock.node.hashManifestSha256 !==
      "778ac5b2fcdbd68d9c0ae9f4310674faa3af0910bd0d18e7f6597787c40a3e39" ||
    lock.node.hashManifestSize !== 3777 ||
    lock.worker.qmdVersion !== "2.5.3" ||
    lock.worker.betterSqlite3Version !== "12.10.0" ||
    !sameJson(lock.buildPython, {
      provider: "actions/setup-python",
      implementation: "CPython",
      version: "3.13.14"
    }) ||
    !SHA256_PATTERN.test(lock.worker.packageLockSha256 || "") ||
    !sameJson(lock.worker.sourcePaths, EXPECTED_WORKER_SOURCE_PATHS) ||
    !sameJson(lock.requiredCiInputs, EXPECTED_REQUIRED_CI_INPUTS)
  ) {
    fail("QMD toolchain lock differs from the accepted pins");
  }
}

function validateSchema(schema) {
  if (
    schema.$schema !== "https://json-schema.org/draft/2020-12/schema" ||
    schema.$id !== MANIFEST_SCHEMA_NAME ||
    schema.type !== "object" ||
    schema.additionalProperties !== false ||
    schema.properties?.kind?.const !== EXPECTED_KIND ||
    schema.properties?.target?.properties?.os?.const !== "darwin" ||
    schema.properties?.target?.properties?.architecture?.const !== "arm64" ||
    schema.properties?.build?.properties?.runnerImage?.const !== "macos-15" ||
    schema.properties?.build?.properties?.python?.properties?.provider?.const !==
      "actions/setup-python" ||
    schema.properties?.build?.properties?.python?.properties?.version?.const !==
      "3.13.14" ||
    schema.properties?.audit?.properties?.policyVersion?.const !== 1 ||
    !sameJson(
      schema.properties?.audit?.properties?.nativeSmoke?.properties?.checks
        ?.const,
      EXPECTED_NATIVE_SMOKE.checks
    )
  ) {
    fail("QMD runtime manifest schema is not the reviewed contract");
  }
}

function criticalInputPaths(lock) {
  const combined = [...FIXED_CRITICAL_INPUTS, ...lock.worker.sourcePaths];
  return [...new Set(combined)].sort(compareCodePoints);
}

function criticalInputDigests(repositoryRoot, lock) {
  const result = {};
  for (const relative of criticalInputPaths(lock)) {
    const safe = safeRelativePath(relative, "QMD critical input");
    const candidate = path.join(repositoryRoot, ...safe.split("/"));
    requireRegularFile(candidate, "QMD critical input");
    result[safe] = sha256File(candidate);
  }
  return result;
}

function inspectRepositoryProvenance(repositoryRoot) {
  function git(arguments_) {
    return runTool(
      "/usr/bin/git",
      ["-C", repositoryRoot, ...arguments_],
      "QMD repository provenance inspection"
    ).trim();
  }
  const commit = git(["rev-parse", "HEAD"]).toLowerCase();
  const sourceDateEpoch = Number(
    git(["show", "-s", "--format=%ct", "HEAD"])
  );
  if (
    !SHA1_PATTERN.test(commit) ||
    !Number.isSafeInteger(sourceDateEpoch) ||
    git(["status", "--porcelain", "--untracked-files=all"]) !== ""
  ) {
    fail("QMD packaging requires a clean reviewed commit");
  }
  return { commit, sourceDateEpoch };
}

function inspectSourceFiles(environment) {
  const archivePath = environment.LCF_QMD_NODE_ARCHIVE;
  const manifestPath = environment.LCF_QMD_NODE_HASH_MANIFEST;
  if (
    typeof archivePath !== "string" ||
    !path.isAbsolute(archivePath) ||
    typeof manifestPath !== "string" ||
    !path.isAbsolute(manifestPath)
  ) {
    fail("QMD Node source paths must be absolute");
  }
  const archiveInfo = requireRegularFile(
    archivePath,
    "QMD Node archive"
  );
  const manifestInfo = requireRegularFile(
    manifestPath,
    "QMD Node hash manifest"
  );
  return {
    archiveSize: archiveInfo.size,
    archiveSha256: sha256File(archivePath),
    hashManifestSize: manifestInfo.size,
    hashManifestSha256: sha256File(manifestPath)
  };
}

function inspectBuildPython(environment, lock) {
  const executable = environment.LCF_QMD_BUILD_PYTHON;
  if (
    typeof executable !== "string" ||
    !path.isAbsolute(executable) ||
    path.normalize(executable) !== executable
  ) {
    fail("QMD build Python path must be absolute and canonical");
  }
  const info = requireRegularFile(executable, "QMD build Python");
  if (
    fs.realpathSync.native(executable) !== executable ||
    (info.mode & 0o111) === 0
  ) {
    fail("QMD build Python must be a real executable file");
  }
  let observed;
  try {
    observed = JSON.parse(
      childProcess.execFileSync(
        executable,
        [
          "-I",
          "-c",
          "import json,platform,sys;print(json.dumps({" +
            "'implementation':platform.python_implementation()," +
            "'version':platform.python_version()," +
            "'system':platform.system()," +
            "'machine':platform.machine()," +
            "'executable':sys.executable" +
            "},sort_keys=True,separators=(',',':')))"
        ],
        {
          encoding: "utf8",
          env: {
            PATH: "/usr/bin:/bin",
            LANG: "C",
            LC_ALL: "C",
            PYTHONHASHSEED: "0",
            PYTHONNOUSERSITE: "1",
            PYTHONSAFEPATH: "1"
          },
          stdio: ["ignore", "pipe", "pipe"],
          timeout: 30_000,
          maxBuffer: 1024 * 1024
        }
      )
    );
  } catch {
    fail("QMD build Python provenance inspection failed");
  }
  if (
    observed.implementation !== lock.buildPython.implementation ||
    observed.version !== lock.buildPython.version ||
    observed.system !== "Darwin" ||
    observed.machine !== "arm64" ||
    path.resolve(observed.executable || "") !== executable
  ) {
    fail("QMD build Python differs from the reviewed native toolchain");
  }
  return {
    provider: lock.buildPython.provider,
    implementation: observed.implementation,
    version: observed.version,
    executableSha256: sha256File(executable)
  };
}

function validateBuild(
  manifest,
  lock,
  repositoryRoot,
  environment,
  inspectSource,
  inspectRepository,
  inspectPython
) {
  const build = manifest.build;
  if (
    !isObject(build) ||
    !SHA1_PATTERN.test(build.repositoryCommit || "") ||
    !Number.isSafeInteger(build.sourceDateEpoch) ||
    !RUNNER_IMAGE_PATTERN.test(build.runnerImageVersion || "") ||
    build.runnerImage !== lock.target.runnerLabel ||
    build.macosDeploymentTarget !== lock.target.deploymentTarget ||
    !isObject(build.node) ||
    build.node.version !== lock.node.version ||
    build.node.archiveName !== lock.node.archiveName ||
    build.node.archiveSource !== lock.node.archiveSource ||
    build.node.archiveSha256 !== lock.node.archiveSha256 ||
    build.node.hashManifestName !== lock.node.hashManifestName ||
    build.node.hashManifestSource !== lock.node.hashManifestSource ||
    build.node.hashManifestSha256 !== lock.node.hashManifestSha256 ||
    !sameJson(build.python, inspectPython(environment, lock))
  ) {
    fail("QMD manifest build provenance differs from the reviewed lock");
  }
  if (
    !Array.isArray(lock.requiredCiInputs) ||
    lock.requiredCiInputs.some(
      (name) =>
        typeof name !== "string" ||
        typeof environment[name] !== "string" ||
        environment[name].length === 0
    ) ||
    environment.GITHUB_SHA !== build.repositoryCommit ||
    environment.LCF_SOURCE_DATE_EPOCH !== String(build.sourceDateEpoch) ||
    environment.ImageVersion !== build.runnerImageVersion
  ) {
    fail("QMD packaging runner inputs are missing or inconsistent");
  }
  const observedSource = inspectSource(environment);
  if (
    observedSource.archiveSize !== lock.node.archiveSize ||
    observedSource.archiveSha256 !== lock.node.archiveSha256 ||
    observedSource.hashManifestSize !== lock.node.hashManifestSize ||
    observedSource.hashManifestSha256 !== lock.node.hashManifestSha256
  ) {
    fail("Current QMD Node source bytes differ from the reviewed lock");
  }
  const repository = inspectRepository(repositoryRoot);
  if (
    repository.commit !== build.repositoryCommit ||
    repository.sourceDateEpoch !== build.sourceDateEpoch
  ) {
    fail("QMD manifest repository provenance differs from the checkout");
  }
  const expectedInputs = criticalInputDigests(repositoryRoot, lock);
  if (!sameJson(build.inputDigests, expectedInputs)) {
    fail("QMD manifest critical inputs differ from the checkout");
  }
}

function validateManifestDigest(root, manifestPath) {
  const digestPath = path.join(root, MANIFEST_DIGEST_NAME);
  const info = requireRegularFile(
    digestPath,
    "QMD runtime manifest digest"
  );
  if (info.size !== 65) {
    fail("QMD runtime manifest digest has the wrong size");
  }
  let value;
  try {
    value = fs.readFileSync(digestPath, "ascii");
  } catch {
    fail("QMD runtime manifest digest is unreadable");
  }
  if (
    value !== `${sha256File(manifestPath)}\n` ||
    !SHA256_PATTERN.test(value.trim())
  ) {
    fail("QMD runtime manifest digest does not match");
  }
}

function validateComponents(root, manifest) {
  if (!Array.isArray(manifest.components)) {
    fail("QMD runtime component inventory is missing");
  }
  const versions = new Map(
    manifest.components.map((component) => [
      component?.name,
      component?.version
    ])
  );
  for (const [name, version] of REQUIRED_COMPONENTS) {
    if (versions.get(name) !== version) {
      fail("QMD runtime omits a required pinned component");
    }
  }
  const artifacts = manifest.artifacts;
  if (
    !isObject(artifacts) ||
    artifacts.spdxSbom !== "compliance/sbom.spdx.json" ||
    artifacts.thirdPartyNotices !==
      "compliance/THIRD-PARTY-NOTICES.txt" ||
    artifacts.licensesDirectory !== "compliance/licenses"
  ) {
    fail("QMD compliance artifact paths are incomplete");
  }
  const sbomPath = resolvePayload(
    root,
    artifacts.spdxSbom,
    "QMD SPDX SBOM"
  );
  resolvePayload(
    root,
    artifacts.thirdPartyNotices,
    "QMD third-party notices"
  );
  const licenses = path.join(
    root,
    ...safeRelativePath(
      artifacts.licensesDirectory,
      "QMD licenses directory"
    ).split("/")
  );
  requireRealDirectory(licenses, "QMD licenses directory");
  const sbom = loadJson(sbomPath, "QMD SPDX SBOM");
  if (
    sbom.spdxVersion !== "SPDX-2.3" ||
    sbom.dataLicense !== "CC0-1.0" ||
    !Array.isArray(sbom.packages)
  ) {
    fail("QMD SPDX SBOM has an incomplete shape");
  }
  const sbomNames = new Set(sbom.packages.map((item) => item?.name));
  for (const component of manifest.components) {
    if (
      !isObject(component) ||
      typeof component.name !== "string" ||
      typeof component.version !== "string" ||
      typeof component.license !== "string" ||
      !sbomNames.has(component.name)
    ) {
      fail("QMD component inventory is not covered by the SPDX SBOM");
    }
  }
}

function validateNoModelPayload(files) {
  const forbidden =
    /(?:^|\/)(?:model-weights|embedding-weights)(?:\/|$)|\.(?:gguf|onnx)$/i;
  if (files.some((entry) => forbidden.test(entry.path))) {
    fail("QMD lexical runtime must not bundle model weights");
  }
}

function validateManifestShape(manifest, versions, lock) {
  if (
    manifest.$schema !== MANIFEST_SCHEMA_NAME ||
    manifest.schemaVersion !== 1 ||
    manifest.kind !== EXPECTED_KIND ||
    !isObject(manifest.product) ||
    manifest.product.appVersion !== versions.productVersion ||
    !sameJson(
      manifest.product.desktopProtocol,
      versions.desktopProtocol
    ) ||
    manifest.product.databaseSchema !== versions.databaseSchema ||
    !sameJson(manifest.target, {
      os: lock.target.os,
      architecture: lock.target.architecture
    }) ||
    !isObject(manifest.audit) ||
    manifest.audit.status !== "pass" ||
    manifest.audit.policyVersion !== 1 ||
    !sameJson(manifest.audit.nativeSmoke, EXPECTED_NATIVE_SMOKE) ||
    !SHA256_PATTERN.test(
      manifest.audit.normalizedInventorySha256 || ""
    )
  ) {
    fail("QMD runtime build manifest has an unsupported shape");
  }
}

function auditQmdRuntime(options = {}) {
  const repositoryRoot = requireRealDirectory(
    options.repositoryRoot || path.resolve(__dirname, "..", ".."),
    "Repository root"
  );
  const stagingRoot = requireRealDirectory(
    options.stagingRoot ||
      path.join(repositoryRoot, "desktop", "generated", "qmd"),
    "QMD runtime root"
  );
  const platformName = options.platform || process.platform;
  const architecture = options.architecture || process.arch;
  if (platformName !== "darwin" || architecture !== "arm64") {
    fail("QMD runtime packaging requires a Darwin arm64 host");
  }
  const lock = loadJson(
    path.join(repositoryRoot, "runtime", TOOLCHAIN_NAME),
    "QMD runtime toolchain lock"
  );
  const schema = loadJson(
    path.join(repositoryRoot, "runtime", MANIFEST_SCHEMA_NAME),
    "QMD runtime manifest schema"
  );
  const versions = loadJson(
    path.join(repositoryRoot, "runtime", "version.json"),
    "Canonical runtime versions"
  );
  validateToolchain(lock);
  validateSchema(schema);

  const manifestPath = path.join(stagingRoot, MANIFEST_NAME);
  const manifest = loadJson(manifestPath, "QMD runtime build manifest");
  if (
    fs.readFileSync(manifestPath, "utf8") !==
    `${canonicalJson(manifest)}\n`
  ) {
    fail("QMD runtime build manifest is not canonical JSON");
  }
  validateManifestShape(manifest, versions, lock);
  validateManifestDigest(stagingRoot, manifestPath);
  validateBuild(
    manifest,
    lock,
    repositoryRoot,
    options.environment || process.env,
    options.inspectSource || inspectSourceFiles,
    options.inspectRepository || inspectRepositoryProvenance,
    options.inspectBuildPython || inspectBuildPython
  );

  const actualFiles = buildFileInventory(stagingRoot);
  if (!sameJson(manifest.files, actualFiles)) {
    fail("Staged QMD runtime differs from its exact file inventory");
  }
  validateNoModelPayload(actualFiles);
  resolvePayload(stagingRoot, "node/bin/node", "Bundled Node executable");
  resolvePayload(stagingRoot, "worker/index.mjs", "QMD worker entrypoint");
  const native = buildNativeInventory(
    stagingRoot,
    options.inspectNative ||
      ((filePath) => inspectMachO(filePath, platformName))
  );
  if (!sameJson(manifest.native, native)) {
    fail("Staged QMD native inventory differs from the manifest");
  }
  if (
    !native.some((item) => item.path === "node/bin/node") ||
    !native.some(
      (item) =>
        item.path.includes("/better-sqlite3/") &&
        item.path.endsWith(".node")
    )
  ) {
    fail("QMD native inventory omits Node or better-sqlite3");
  }
  if (
    manifest.audit.normalizedInventorySha256 !==
    sha256Bytes(
      Buffer.from(
        canonicalJson({ files: actualFiles, native }),
        "utf8"
      )
    )
  ) {
    fail("QMD normalized inventory digest does not match");
  }
  validateComponents(stagingRoot, manifest);
  return {
    files: actualFiles.length,
    nativeFiles: native.length,
    components: manifest.components.length
  };
}

module.exports = {
  EXPECTED_NATIVE_SMOKE,
  FIXED_CRITICAL_INPUTS,
  MANIFEST_DIGEST_NAME,
  MANIFEST_NAME,
  QmdRuntimeAuditError,
  auditQmdRuntime,
  buildFileInventory,
  buildNativeInventory,
  canonicalJson,
  criticalInputDigests,
  isMachO,
  inspectMachO,
  inspectBuildPython,
  inspectRepositoryProvenance,
  inspectSourceFiles,
  sha256Bytes,
  sha256File,
  validateToolchain
};

if (require.main === module) {
  try {
    const summary = auditQmdRuntime();
    process.stdout.write(`${JSON.stringify(summary)}\n`);
  } catch (error) {
    if (error instanceof QmdRuntimeAuditError) {
      process.stderr.write(`qmd-runtime audit failed: ${error.message}\n`);
      process.exitCode = 2;
    } else {
      throw error;
    }
  }
}

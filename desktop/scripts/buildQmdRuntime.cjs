"use strict";

const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {
  EXPECTED_NATIVE_SMOKE,
  MANIFEST_DIGEST_NAME,
  MANIFEST_NAME,
  QmdRuntimeAuditError,
  auditQmdRuntime,
  buildFileInventory,
  buildNativeInventory,
  canonicalJson,
  criticalInputDigests,
  inspectBuildPython,
  isMachO,
  sha256Bytes,
  sha256File,
  validateToolchain
} = require("./auditQmdRuntime.cjs");

const REPOSITORY_ROOT = path.resolve(__dirname, "..", "..");
const WORKER_SOURCE = path.join(
  REPOSITORY_ROOT,
  "desktop",
  "workers",
  "qmd"
);
const TOOLCHAIN_PATH = path.join(
  REPOSITORY_ROOT,
  "runtime",
  "qmd-runtime-toolchain.lock.json"
);
const VERSION_PATH = path.join(
  REPOSITORY_ROOT,
  "runtime",
  "version.json"
);
const DEFAULT_STAGING = path.join(
  REPOSITORY_ROOT,
  "desktop",
  "generated",
  "qmd"
);
const MAX_ARCHIVE_BYTES = 128 * 1024 * 1024;
const MAX_HASH_MANIFEST_BYTES = 1024 * 1024;
const SAFE_ARCHIVE_ROOT = /^node-v22\.23\.2-darwin-arm64(?:\/|$)/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const SHA512_INTEGRITY_PATTERN = /^sha512-[A-Za-z0-9+/]+={0,2}$/;
const WORKER_COPY_PATHS = Object.freeze([
  "index.mjs",
  "package.json",
  "package-lock.json",
  "src",
  "test"
]);

class QmdRuntimeBuildError extends Error {
  constructor(message) {
    super(message);
    this.name = "QmdRuntimeBuildError";
  }
}

function fail(message) {
  throw new QmdRuntimeBuildError(message);
}

function loadJson(filePath, label) {
  let value;
  try {
    const info = fs.lstatSync(filePath);
    if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1) {
      fail(`${label} must be an unlinked regular file`);
    }
    value = JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (error) {
    if (error instanceof QmdRuntimeBuildError) {
      throw error;
    }
    fail(`${label} is unreadable`);
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail(`${label} must be an object`);
  }
  return value;
}

function requireAbsoluteRegularFile(filePath, label, maximumSize) {
  if (typeof filePath !== "string" || !path.isAbsolute(filePath)) {
    fail(`${label} path must be absolute`);
  }
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
    info.size > maximumSize
  ) {
    fail(`${label} must be a bounded, unlinked regular file`);
  }
  return info;
}

function run(executable, arguments_, options = {}) {
  try {
    return childProcess.execFileSync(executable, arguments_, {
      cwd: options.cwd || REPOSITORY_ROOT,
      encoding: "utf8",
      env: options.env || process.env,
      stdio: ["ignore", "pipe", "pipe"],
      timeout: options.timeout || 120_000,
      maxBuffer: options.maxBuffer || 16 * 1024 * 1024
    });
  } catch {
    fail(options.label || "QMD runtime build command failed");
  }
}

function verifyHashManifest(hashManifestPath, lock) {
  const info = requireAbsoluteRegularFile(
    hashManifestPath,
    "Node hash manifest",
    MAX_HASH_MANIFEST_BYTES
  );
  if (
    info.size !== lock.node.hashManifestSize ||
    sha256File(hashManifestPath) !== lock.node.hashManifestSha256
  ) {
    fail("Node hash manifest differs from the reviewed lock");
  }
  let text;
  try {
    const bytes = fs.readFileSync(hashManifestPath);
    text = new TextDecoder("ascii", { fatal: true }).decode(bytes);
  } catch {
    fail("Node hash manifest must be strict ASCII");
  }
  const matches = [];
  const names = new Set();
  for (const line of text.split(/\r?\n/)) {
    if (line === "") {
      continue;
    }
    const match = /^([0-9a-fA-F]{64})[ \t]+\*?([^ \t]+)$/.exec(line);
    if (!match) {
      fail("Node hash manifest contains a malformed line");
    }
    const [, digest, name] = match;
    if (
      names.has(name) ||
      path.posix.isAbsolute(name) ||
      name.includes("\\") ||
      name.includes("\0") ||
      name
        .split("/")
        .some((part) => part === "" || part === "." || part === "..")
    ) {
      fail("Node hash manifest contains an unsafe duplicate");
    }
    names.add(name);
    if (name === lock.node.archiveName) {
      matches.push(digest.toLowerCase());
    }
  }
  if (
    matches.length !== 1 ||
    matches[0] !== lock.node.archiveSha256
  ) {
    fail("Node hash manifest target entry is absent or ambiguous");
  }
}

function verifyArchiveListing(archivePath) {
  const listing = run(
    "/usr/bin/tar",
    ["-tzf", archivePath],
    {
      env: { PATH: "/usr/bin:/bin", LANG: "C", LC_ALL: "C" },
      timeout: 120_000,
      maxBuffer: 32 * 1024 * 1024,
      label: "Node archive listing failed"
    }
  );
  const names = listing.split(/\r?\n/).filter(Boolean);
  if (names.length === 0) {
    fail("Node archive is empty");
  }
  for (const name of names) {
    const normalized = name.endsWith("/") ? name.slice(0, -1) : name;
    if (
      !SAFE_ARCHIVE_ROOT.test(normalized) ||
      normalized.startsWith("/") ||
      normalized.includes("\\") ||
      normalized.includes("\0") ||
      normalized.split("/").some((part) => part === "..")
    ) {
      fail("Node archive contains an unsafe path");
    }
  }
}

function verifyDistributionFiles(archivePath, hashManifestPath, lock) {
  validateToolchain(lock);
  const archiveInfo = requireAbsoluteRegularFile(
    archivePath,
    "Node distribution archive",
    MAX_ARCHIVE_BYTES
  );
  verifyHashManifest(hashManifestPath, lock);
  if (
    archiveInfo.size !== lock.node.archiveSize ||
    sha256File(archivePath) !== lock.node.archiveSha256
  ) {
    fail("Node distribution archive differs from the reviewed lock");
  }
  verifyArchiveListing(archivePath);
  return {
    version: lock.node.version,
    archiveName: lock.node.archiveName,
    archiveSha256: lock.node.archiveSha256,
    hashManifestName: lock.node.hashManifestName,
    hashManifestSha256: lock.node.hashManifestSha256
  };
}

function git(arguments_) {
  return run("/usr/bin/git", arguments_, {
    env: { PATH: "/usr/bin:/bin", LANG: "C", LC_ALL: "C" },
    label: "QMD Git provenance check failed"
  }).trim();
}

function validateReleaseEnvironment(environment, lock) {
  if (
    process.platform !== "darwin" ||
    process.arch !== "arm64" ||
    environment.GITHUB_ACTIONS !== "true" ||
    environment.RUNNER_OS !== "macOS" ||
    environment.RUNNER_ARCH !== "ARM64" ||
    !["macos15", "macos-15"].includes(environment.ImageOS) ||
    lock.target.runnerLabel !== "macos-15"
  ) {
    fail("QMD runtime builds require a native macos-15 arm64 runner");
  }
  const translated = run(
    "/usr/sbin/sysctl",
    ["-in", "sysctl.proc_translated"],
    {
      env: { PATH: "/usr/bin:/bin", LANG: "C", LC_ALL: "C" },
      label: "QMD Rosetta check failed"
    }
  ).trim();
  if (translated !== "" && translated !== "0") {
    fail("QMD runtime must not build under Rosetta");
  }
  const missing = lock.requiredCiInputs.filter(
    (name) =>
      typeof environment[name] !== "string" ||
      environment[name].length === 0
  );
  if (missing.length > 0) {
    fail("Required QMD runtime CI inputs are missing");
  }
  const commit = environment.GITHUB_SHA.toLowerCase();
  const sourceDateEpoch = Number(environment.LCF_SOURCE_DATE_EPOCH);
  if (
    !/^[0-9a-f]{40}$/.test(commit) ||
    !Number.isSafeInteger(sourceDateEpoch) ||
    sourceDateEpoch < 100_000_000 ||
    git(["-C", REPOSITORY_ROOT, "rev-parse", "HEAD"]).toLowerCase() !==
      commit ||
    Number(
      git([
        "-C",
        REPOSITORY_ROOT,
        "show",
        "-s",
        "--format=%ct",
        "HEAD"
      ])
    ) !== sourceDateEpoch ||
    git([
      "-C",
      REPOSITORY_ROOT,
      "status",
      "--porcelain",
      "--untracked-files=all"
    ]) !== ""
  ) {
    fail("QMD packaging source is not a clean reviewed commit");
  }
  if (!/^[0-9]{8}\.[0-9]+\.[0-9]+$/.test(environment.ImageVersion)) {
    fail("QMD runner image version is malformed");
  }
  return {
    repositoryCommit: commit,
    sourceDateEpoch,
    runnerImage: lock.target.runnerLabel,
    runnerImageVersion: environment.ImageVersion,
    macosDeploymentTarget: lock.target.deploymentTarget
  };
}

function validateWorkerLocks(lock) {
  const packageJsonPath = path.join(WORKER_SOURCE, "package.json");
  const packageLockPath = path.join(WORKER_SOURCE, "package-lock.json");
  const packageJson = loadJson(packageJsonPath, "QMD worker package");
  const packageLock = loadJson(packageLockPath, "QMD worker package lock");
  const packages = packageLock.packages;
  if (
    packageJson.version !== lock.worker.workerVersion &&
    packageJson.version !== lock.worker.version
  ) {
    fail("QMD worker version differs from the toolchain lock");
  }
  if (
    packageJson.engines?.node !== lock.node.version ||
    packageJson.dependencies?.["@tobilu/qmd"] !==
      lock.worker.qmdVersion ||
    sha256File(packageLockPath) !== lock.worker.packageLockSha256 ||
    packages?.["node_modules/@tobilu/qmd"]?.version !==
      lock.worker.qmdVersion ||
    packages?.["node_modules/better-sqlite3"]?.version !==
      lock.worker.betterSqlite3Version
  ) {
    fail("QMD npm lock differs from the reviewed versions");
  }
  return { packageJson, packageLock };
}

function copyWorkerSources(destination) {
  fs.mkdirSync(destination, { recursive: true, mode: 0o755 });
  function copyReviewed(source, target) {
    const info = fs.lstatSync(source);
    if (info.isSymbolicLink()) {
      fail("QMD worker source must not contain symlinks");
    }
    if (info.isDirectory()) {
      fs.mkdirSync(target, { mode: 0o755 });
      for (const name of fs.readdirSync(source).sort()) {
        copyReviewed(path.join(source, name), path.join(target, name));
      }
    } else if (info.isFile() && info.nlink === 1) {
      fs.copyFileSync(source, target, fs.constants.COPYFILE_EXCL);
    } else {
      fail("QMD worker source contains a special or hard-linked file");
    }
  }
  for (const relative of WORKER_COPY_PATHS) {
    const source = path.join(WORKER_SOURCE, relative);
    const target = path.join(destination, relative);
    copyReviewed(source, target);
  }
}

function npmEnvironment(nodeRoot, buildRoot, environment, scripts) {
  const npmCache = path.join(buildRoot, "npm-cache");
  const configRoot = path.join(buildRoot, "npm-config");
  const prefixRoot = path.join(buildRoot, "npm-prefix");
  const temporaryRoot = path.join(buildRoot, "npm-tmp");
  const userConfig = path.join(configRoot, "user.npmrc");
  const globalConfig = path.join(configRoot, "global.npmrc");
  fs.mkdirSync(npmCache, { recursive: true, mode: 0o700 });
  fs.mkdirSync(configRoot, { recursive: true, mode: 0o700 });
  fs.mkdirSync(prefixRoot, { recursive: true, mode: 0o700 });
  fs.mkdirSync(temporaryRoot, { recursive: true, mode: 0o700 });
  for (const config of [userConfig, globalConfig]) {
    if (!fs.existsSync(config)) {
      fs.writeFileSync(config, "", {
        encoding: "utf8",
        mode: 0o600,
        flag: "wx"
      });
    }
  }
  return {
    PATH: `${path.join(nodeRoot, "bin")}:/usr/bin:/bin`,
    LANG: "C",
    LC_ALL: "C",
    CI: "true",
    XDG_CACHE_HOME: npmCache,
    XDG_CONFIG_HOME: configRoot,
    npm_config_audit: "false",
    npm_config_fund: "false",
    npm_config_cache: npmCache,
    npm_config_globalconfig: globalConfig,
    npm_config_prefix: prefixRoot,
    npm_config_tmp: temporaryRoot,
    npm_config_update_notifier: "false",
    npm_config_userconfig: userConfig,
    npm_config_platform: "darwin",
    npm_config_arch: "arm64",
    npm_config_ignore_scripts: scripts ? "false" : "true",
    npm_config_nodedir: nodeRoot,
    npm_config_python: environment.LCF_QMD_BUILD_PYTHON
  };
}

function runNpm(nodeRoot, arguments_, options) {
  const npmCli = path.join(
    nodeRoot,
    "lib",
    "node_modules",
    "npm",
    "bin",
    "npm-cli.js"
  );
  return run(path.join(nodeRoot, "bin", "node"), [npmCli, ...arguments_], {
    cwd: options.cwd,
    env: options.env,
    timeout: options.timeout || 20 * 60_000,
    maxBuffer: 32 * 1024 * 1024,
    label: options.label
  });
}

function normalizeModesAndTimes(root, epoch) {
  function visit(candidate) {
    const info = fs.lstatSync(candidate);
    if (info.isSymbolicLink()) {
      fail("QMD staging must not contain symlinks");
    }
    if (info.isDirectory()) {
      fs.chmodSync(candidate, 0o755);
      for (const name of fs.readdirSync(candidate)) {
        visit(path.join(candidate, name));
      }
    } else if (info.isFile()) {
      const executable =
        candidate === path.join(root, "node", "bin", "node") ||
        isMachO(candidate);
      fs.chmodSync(candidate, executable ? 0o755 : 0o644);
    } else {
      fail("QMD staging contains a special file");
    }
    fs.utimesSync(candidate, epoch, epoch);
  }
  visit(root);
}

function signNativePayload(root) {
  const files = buildFileInventory(root)
    .map((entry) => path.join(root, ...entry.path.split("/")))
    .filter((candidate) => isMachO(candidate))
    .sort((left, right) => right.length - left.length);
  if (files.length < 2) {
    fail("QMD staging omits required native payloads");
  }
  for (const candidate of files) {
    run(
      "/usr/bin/codesign",
      ["--force", "--sign", "-", "--timestamp=none", candidate],
      {
        env: { PATH: "/usr/bin:/bin", LANG: "C", LC_ALL: "C" },
        label: "QMD ad-hoc staging signature failed"
      }
    );
  }
}

function packageNameFromLockPath(lockPath, metadata) {
  if (typeof metadata.name === "string" && metadata.name.length > 0) {
    return metadata.name;
  }
  const parts = lockPath.split("node_modules/").at(-1).split("/");
  return parts[0].startsWith("@") ? `${parts[0]}/${parts[1]}` : parts[0];
}

function safeComponentName(value) {
  return value.replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 160);
}

function findLicenseFile(packageRoot) {
  let names;
  try {
    names = fs.readdirSync(packageRoot);
  } catch {
    return undefined;
  }
  const candidates = names
    .filter((name) => /^(?:licen[cs]e|copying|notice)(?:\..+)?$/i.test(name))
    .sort();
  for (const name of candidates) {
    const candidate = path.join(packageRoot, name);
    const info = fs.lstatSync(candidate);
    if (info.isFile() && !info.isSymbolicLink() && info.size <= 1024 * 1024) {
      return candidate;
    }
  }
  return undefined;
}

function installedComponents(workerRoot, packageLock, lock) {
  const components = [
    {
      name: "node",
      version: lock.node.version,
      license: "MIT",
      integrity: `sha256-${lock.node.archiveSha256}`
    }
  ];
  for (const [lockPath, metadata] of Object.entries(packageLock.packages)) {
    if (
      lockPath === "" ||
      !lockPath.includes("node_modules/") ||
      metadata.dev === true
    ) {
      continue;
    }
    const packageRoot = path.join(
      workerRoot,
      ...lockPath.split("/")
    );
    if (!fs.existsSync(packageRoot)) {
      continue;
    }
    if (
      typeof metadata.version !== "string" ||
      typeof metadata.license !== "string"
    ) {
      fail("Installed QMD package lacks pinned version/license metadata");
    }
    if (
      metadata.integrity !== undefined &&
      !SHA512_INTEGRITY_PATTERN.test(metadata.integrity)
    ) {
      fail("Installed QMD package has malformed npm integrity metadata");
    }
    components.push({
      name: packageNameFromLockPath(lockPath, metadata),
      version: metadata.version,
      license: metadata.license,
      ...(metadata.integrity ? { integrity: metadata.integrity } : {})
    });
  }
  components.sort((left, right) => {
    const byName = left.name.localeCompare(right.name, "en");
    return byName || left.version.localeCompare(right.version, "en");
  });
  return components;
}

function writeComplianceArtifacts(
  runtimeRoot,
  workerRoot,
  packageLock,
  lock,
  release
) {
  const complianceRoot = path.join(runtimeRoot, "compliance");
  const licensesRoot = path.join(complianceRoot, "licenses");
  fs.mkdirSync(licensesRoot, { recursive: true, mode: 0o755 });
  const components = installedComponents(workerRoot, packageLock, lock);
  const notices = [
    "Local Context Forge bundled QMD runtime",
    "",
    "This inventory is generated from the reviewed npm lock and staged payload.",
    "It is not permission to redistribute a dependency contrary to its license.",
    ""
  ];

  const nodeLicense = path.join(runtimeRoot, "node", "LICENSE");
  fs.copyFileSync(
    nodeLicense,
    path.join(licensesRoot, "node-22.23.2-LICENSE.txt")
  );
  for (const component of components) {
    notices.push(
      `${component.name}@${component.version} — ${component.license}`
    );
  }
  for (const [lockPath, metadata] of Object.entries(packageLock.packages)) {
    if (lockPath === "" || !lockPath.includes("node_modules/")) {
      continue;
    }
    const packageRoot = path.join(workerRoot, ...lockPath.split("/"));
    if (!fs.existsSync(packageRoot)) {
      continue;
    }
    const license = findLicenseFile(packageRoot);
    if (!license) {
      continue;
    }
    const name = packageNameFromLockPath(lockPath, metadata);
    const destination = path.join(
      licensesRoot,
      `${safeComponentName(name)}-${safeComponentName(
        metadata.version || "unknown"
      )}-${path.basename(license)}`
    );
    if (!fs.existsSync(destination)) {
      fs.copyFileSync(license, destination);
    }
  }
  fs.writeFileSync(
    path.join(complianceRoot, "THIRD-PARTY-NOTICES.txt"),
    `${notices.join("\n")}\n`,
    { encoding: "utf8", mode: 0o644 }
  );

  const packages = components.map((component, index) => ({
    SPDXID: `SPDXRef-Package-${index + 1}`,
    name: component.name,
    versionInfo: component.version,
    downloadLocation: "NOASSERTION",
    filesAnalyzed: false,
    licenseConcluded: "NOASSERTION",
    licenseDeclared: component.license,
    copyrightText: "NOASSERTION",
    ...(component.integrity?.startsWith("sha512-")
      ? {
          checksums: [
            {
              algorithm: "SHA512",
              checksumValue: Buffer.from(
                component.integrity.slice("sha512-".length),
                "base64"
              ).toString("hex")
            }
          ]
        }
      : {})
  }));
  const sbom = {
    spdxVersion: "SPDX-2.3",
    dataLicense: "CC0-1.0",
    SPDXID: "SPDXRef-DOCUMENT",
    name: "Local Context Forge QMD runtime",
    documentNamespace: `https://local-context-forge.invalid/spdx/qmd/${release.repositoryCommit}`,
    creationInfo: {
      created: new Date(release.sourceDateEpoch * 1000).toISOString(),
      creators: ["Tool: desktop/scripts/buildQmdRuntime.cjs"]
    },
    packages
  };
  fs.writeFileSync(
    path.join(complianceRoot, "sbom.spdx.json"),
    `${canonicalJson(sbom)}\n`,
    { encoding: "utf8", mode: 0o644 }
  );
  return components;
}

function runNativeSmoke(runtimeRoot, manifestDigest, buildRoot) {
  const nodeBinary = path.join(runtimeRoot, "node", "bin", "node");
  const workerEntry = path.join(runtimeRoot, "worker", "index.mjs");
  const configRoot = path.join(buildRoot, "native-smoke-config");
  const cacheRoot = path.join(buildRoot, "native-smoke-cache");
  fs.mkdirSync(configRoot, { recursive: true, mode: 0o700 });
  fs.mkdirSync(cacheRoot, { recursive: true, mode: 0o700 });
  run(
    nodeBinary,
    [
      "-e",
      [
        "const Database=require('better-sqlite3');",
        "const db=new Database(':memory:');",
        "db.exec('create table gate(value text)');",
        "db.prepare('insert into gate values (?)').run('arm64');",
        "if(db.prepare('select value from gate').get().value!=='arm64')",
        "throw new Error('native sqlite smoke failed');",
        "db.close();"
      ].join("")
    ],
    {
      cwd: path.join(runtimeRoot, "worker"),
      env: {
        PATH: "/lcf-no-system-runtime",
        TMPDIR: os.tmpdir(),
        XDG_CACHE_HOME: cacheRoot,
        XDG_CONFIG_HOME: configRoot,
        LANG: "C",
        LC_ALL: "C"
      },
      label: "better-sqlite3 native load smoke failed"
    }
  );
  run(
    nodeBinary,
    [
      path.join(__dirname, "qmdRuntimeSmoke.mjs"),
      "--worker",
      workerEntry,
      "--manifest-sha256",
      manifestDigest
    ],
    {
      cwd: runtimeRoot,
      env: {
        PATH: "/lcf-no-system-runtime",
        TMPDIR: os.tmpdir(),
        XDG_CACHE_HOME: cacheRoot,
        XDG_CONFIG_HOME: configRoot,
        LANG: "C",
        LC_ALL: "C",
        CI: "true"
      },
      timeout: 120_000,
      label: "QMD UDS/native smoke failed"
    }
  );
}

function publishStaging(candidate, destination, environment) {
  const backup = `${destination}.previous-${crypto
    .randomBytes(8)
    .toString("hex")}`;
  const existing = fs.existsSync(destination);
  try {
    if (existing) {
      fs.renameSync(destination, backup);
    }
    fs.renameSync(candidate, destination);
    auditQmdRuntime({
      repositoryRoot: REPOSITORY_ROOT,
      stagingRoot: destination,
      environment
    });
    if (existing) {
      fs.rmSync(backup, { recursive: true, force: true });
    }
  } catch (error) {
    if (fs.existsSync(destination)) {
      fs.renameSync(destination, candidate);
    }
    if (existing && fs.existsSync(backup)) {
      fs.renameSync(backup, destination);
    }
    throw error;
  }
}

function buildQmdRuntime({
  archivePath,
  hashManifestPath,
  destination,
  environment
}) {
  const lock = loadJson(TOOLCHAIN_PATH, "QMD toolchain lock");
  const versions = loadJson(VERSION_PATH, "Canonical runtime versions");
  verifyDistributionFiles(archivePath, hashManifestPath, lock);
  const release = validateReleaseEnvironment(environment, lock);
  const buildPython = inspectBuildPython(environment, lock);
  const { packageLock } = validateWorkerLocks(lock);
  const destinationParent = path.dirname(destination);
  fs.mkdirSync(destinationParent, { recursive: true });
  const buildRoot = fs.mkdtempSync(
    path.join(destinationParent, ".qmd-runtime-build-")
  );
  const runtimeRoot = path.join(buildRoot, "runtime");
  const extractedRoot = path.join(buildRoot, lock.node.archiveRoot);
  try {
    run("/usr/bin/tar", ["-xzf", archivePath, "-C", buildRoot], {
      env: { PATH: "/usr/bin:/bin", LANG: "C", LC_ALL: "C" },
      timeout: 180_000,
      label: "Reviewed Node archive extraction failed"
    });
    const extractedNode = path.join(extractedRoot, "bin", "node");
    if (
      run(extractedNode, ["--version"], {
        env: { PATH: "/lcf-no-system-runtime", LANG: "C", LC_ALL: "C" },
        label: "Reviewed Node executable check failed"
      }).trim() !== `v${lock.node.version}` ||
      run(
        extractedNode,
        [
          "-p",
          "`${process.platform}/${process.arch}/${process.versions.modules}`"
        ],
        {
          env: { PATH: "/lcf-no-system-runtime", LANG: "C", LC_ALL: "C" },
          label: "Reviewed Node platform check failed"
        }
      ).trim() !== "darwin/arm64/127"
    ) {
      fail("Reviewed Node runtime has the wrong version, platform, arch, or ABI");
    }

    const stagedNode = path.join(runtimeRoot, "node");
    const stagedWorker = path.join(runtimeRoot, "worker");
    fs.mkdirSync(path.join(stagedNode, "bin"), {
      recursive: true,
      mode: 0o755
    });
    fs.copyFileSync(
      extractedNode,
      path.join(stagedNode, "bin", "node"),
      fs.constants.COPYFILE_EXCL
    );
    fs.copyFileSync(
      path.join(extractedRoot, "LICENSE"),
      path.join(stagedNode, "LICENSE"),
      fs.constants.COPYFILE_EXCL
    );
    copyWorkerSources(stagedWorker);

    runNpm(extractedRoot, ["ci", "--ignore-scripts", "--omit=dev"], {
      cwd: stagedWorker,
      env: npmEnvironment(extractedRoot, buildRoot, environment, false),
      label: "Hash-locked QMD production dependency install failed"
    });
    runNpm(
      extractedRoot,
      [
        "rebuild",
        "better-sqlite3",
        "--build-from-source",
        "--foreground-scripts"
      ],
      {
        cwd: stagedWorker,
        env: {
          ...npmEnvironment(
            extractedRoot,
            buildRoot,
            environment,
            true
          ),
          npm_config_build_from_source: "true"
        },
        label: "better-sqlite3 source rebuild failed"
      }
    );
    const workerTests = fs
      .readdirSync(path.join(stagedWorker, "test"))
      .filter((name) => name.endsWith(".test.mjs"))
      .sort()
      .map((name) => path.join("test", name));
    if (workerTests.length === 0) {
      fail("QMD worker contract test inventory is empty");
    }
    fs.mkdirSync(path.join(buildRoot, "worker-test-cache"), {
      recursive: true,
      mode: 0o700
    });
    fs.mkdirSync(path.join(buildRoot, "worker-test-config"), {
      recursive: true,
      mode: 0o700
    });
    run(extractedNode, ["--test", ...workerTests], {
      cwd: stagedWorker,
      env: {
        PATH: "/lcf-no-system-runtime",
        TMPDIR: os.tmpdir(),
        XDG_CACHE_HOME: path.join(buildRoot, "worker-test-cache"),
        XDG_CONFIG_HOME: path.join(buildRoot, "worker-test-config"),
        LANG: "C",
        LC_ALL: "C",
        CI: "true"
      },
      label: "QMD worker contract tests failed"
    });
    fs.rmSync(path.join(stagedWorker, "test"), {
      recursive: true,
      force: true
    });
    fs.rmSync(path.join(stagedWorker, "node_modules", ".bin"), {
      recursive: true,
      force: true
    });

    const components = writeComplianceArtifacts(
      runtimeRoot,
      stagedWorker,
      packageLock,
      lock,
      release
    );
    normalizeModesAndTimes(runtimeRoot, release.sourceDateEpoch);
    signNativePayload(runtimeRoot);
    normalizeModesAndTimes(runtimeRoot, release.sourceDateEpoch);
    const files = buildFileInventory(runtimeRoot);
    const native = buildNativeInventory(runtimeRoot);
    const manifest = {
      $schema: "qmd-runtime-build-manifest.schema.json",
      schemaVersion: 1,
      kind: "local-context-forge-qmd-runtime",
      product: {
        appVersion: versions.productVersion,
        desktopProtocol: versions.desktopProtocol,
        databaseSchema: versions.databaseSchema
      },
      target: {
        os: lock.target.os,
        architecture: lock.target.architecture
      },
      build: {
        ...release,
        node: {
          version: lock.node.version,
          archiveName: lock.node.archiveName,
          archiveSource: lock.node.archiveSource,
          archiveSha256: lock.node.archiveSha256,
          hashManifestName: lock.node.hashManifestName,
          hashManifestSource: lock.node.hashManifestSource,
          hashManifestSha256: lock.node.hashManifestSha256
        },
        python: buildPython,
        inputDigests: criticalInputDigests(REPOSITORY_ROOT, lock)
      },
      components,
      artifacts: {
        spdxSbom: "compliance/sbom.spdx.json",
        thirdPartyNotices: "compliance/THIRD-PARTY-NOTICES.txt",
        licensesDirectory: "compliance/licenses"
      },
      files,
      native,
      audit: {
        status: "pass",
        policyVersion: 1,
        normalizedInventorySha256: sha256Bytes(
          Buffer.from(canonicalJson({ files, native }), "utf8")
        ),
        nativeSmoke: EXPECTED_NATIVE_SMOKE
      }
    };
    const manifestBytes = Buffer.from(`${canonicalJson(manifest)}\n`, "utf8");
    const manifestPath = path.join(runtimeRoot, MANIFEST_NAME);
    fs.writeFileSync(manifestPath, manifestBytes, {
      mode: 0o644,
      flag: "wx"
    });
    const manifestDigest = sha256Bytes(manifestBytes);
    fs.writeFileSync(
      path.join(runtimeRoot, MANIFEST_DIGEST_NAME),
      `${manifestDigest}\n`,
      { encoding: "ascii", mode: 0o644, flag: "wx" }
    );
    fs.utimesSync(
      manifestPath,
      release.sourceDateEpoch,
      release.sourceDateEpoch
    );
    fs.utimesSync(
      path.join(runtimeRoot, MANIFEST_DIGEST_NAME),
      release.sourceDateEpoch,
      release.sourceDateEpoch
    );
    runNativeSmoke(runtimeRoot, manifestDigest, buildRoot);
    auditQmdRuntime({
      repositoryRoot: REPOSITORY_ROOT,
      stagingRoot: runtimeRoot,
      environment
    });
    publishStaging(runtimeRoot, destination, environment);
    return {
      files: files.length,
      nativeFiles: native.length,
      components: components.length,
      manifestSha256: manifestDigest
    };
  } finally {
    fs.rmSync(buildRoot, { recursive: true, force: true });
  }
}

function parseArguments(argv) {
  const options = {
    verifySourceOnly: false,
    archivePath: undefined,
    hashManifestPath: undefined,
    destination: DEFAULT_STAGING
  };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--verify-source-only") {
      options.verifySourceOnly = true;
    } else if (argument === "--archive") {
      options.archivePath = argv[++index];
    } else if (argument === "--hash-manifest") {
      options.hashManifestPath = argv[++index];
    } else if (argument === "--staging") {
      options.destination = path.resolve(argv[++index]);
    } else {
      fail("Unknown QMD runtime build argument");
    }
  }
  options.archivePath ||= process.env.LCF_QMD_NODE_ARCHIVE;
  options.hashManifestPath ||= process.env.LCF_QMD_NODE_HASH_MANIFEST;
  if (!options.archivePath || !options.hashManifestPath) {
    fail("QMD Node archive and hash manifest are required");
  }
  return options;
}

function main(argv = process.argv.slice(2)) {
  const options = parseArguments(argv);
  const lock = loadJson(TOOLCHAIN_PATH, "QMD toolchain lock");
  if (options.verifySourceOnly) {
    const provenance = verifyDistributionFiles(
      options.archivePath,
      options.hashManifestPath,
      lock
    );
    process.stdout.write(
      `${JSON.stringify({ ...provenance, status: "verified" })}\n`
    );
    return;
  }
  const summary = buildQmdRuntime({
    archivePath: options.archivePath,
    hashManifestPath: options.hashManifestPath,
    destination: options.destination,
    environment: process.env
  });
  process.stdout.write(`${JSON.stringify(summary)}\n`);
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    if (
      error instanceof QmdRuntimeBuildError ||
      error instanceof QmdRuntimeAuditError
    ) {
      process.stderr.write(`qmd-runtime build failed: ${error.message}\n`);
      process.exitCode = 2;
    } else {
      throw error;
    }
  }
}

module.exports = {
  QmdRuntimeBuildError,
  buildQmdRuntime,
  main,
  verifyDistributionFiles,
  verifyHashManifest
};

"use strict";

const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {
  auditRenderer
} = require("./auditRenderer.cjs");
const {
  auditPythonSidecar
} = require("./beforePack.cjs");
const {
  auditQmdRuntime
} = require("./auditQmdRuntime.cjs");
const {
  auditCompanion
} = require("./auditCompanion.cjs");

const REPOSITORY_ROOT = path.resolve(__dirname, "..", "..");
const CANONICAL_REPOSITORY = "fredgnr/local-context-forge";
const PRODUCT_NAME = "Local Context Forge";
const ARTIFACT_NAME_PREFIX = "local-context-forge";
const ARCHITECTURE = "arm64";
const UPDATE_MANIFEST_NAME = "update-manifest.json";
const UPDATE_SIGNATURE_NAME = "update-manifest.json.sig";
const RELEASE_MANIFEST_NAME = "release-manifest.json";
const CHECKSUMS_NAME = "SHA256SUMS";
const UPDATE_PUBLIC_KEY_RELATIVE =
  "desktop/resources/update/update-metadata-ed25519-public.pem";
const SIGNING_IDENTITY = "Local Context Forge Self Signed";
const MAX_DISK_IMAGE_BYTES = 2 * 1024 * 1024 * 1024;
const MAX_UPDATE_ZIP_BYTES = 2 * 1024 * 1024 * 1024;
const MAX_BLOCKMAP_BYTES = 64 * 1024 * 1024;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const SHA512_BASE64_PATTERN = /^[A-Za-z0-9+/]{86}==$/;
const SEMVER_PATTERN =
  /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;
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

class DesktopReleaseError extends Error {
  constructor(message) {
    super(message);
    this.name = "DesktopReleaseError";
  }
}

function fail(message) {
  throw new DesktopReleaseError(message);
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(value, expected) {
  if (!isObject(value)) {
    return false;
  }
  const actual = Object.keys(value).sort();
  const reviewed = [...expected].sort();
  return (
    actual.length === reviewed.length &&
    actual.every((key, index) => key === reviewed[index])
  );
}

function safeBasename(value, label = "Release asset") {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > 240 ||
    value === "." ||
    value === ".." ||
    value !== value.normalize("NFC") ||
    value.includes("/") ||
    value.includes("\\") ||
    value.includes("\0") ||
    path.basename(value) !== value
  ) {
    fail(`${label} name is unsafe`);
  }
  return value;
}

function isWithin(root, candidate) {
  const relative = path.relative(root, candidate);
  return (
    relative === "" ||
    (!relative.startsWith(`..${path.sep}`) &&
      relative !== ".." &&
      !path.isAbsolute(relative))
  );
}

function loadEd25519PublicKey(publicKeyPath) {
  let publicKey;
  try {
    publicKey = crypto.createPublicKey(
      fs.readFileSync(publicKeyPath)
    );
  } catch {
    fail("Update metadata public key is invalid");
  }
  if (publicKey.asymmetricKeyType !== "ed25519") {
    fail("Update metadata public key is not Ed25519");
  }
  return publicKey;
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
    fail("Unable to canonicalize desktop release metadata");
  }
  return encoded;
}

function sha256File(filePath) {
  const digest = crypto.createHash("sha256");
  const descriptor = fs.openSync(filePath, "r");
  try {
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
  } finally {
    fs.closeSync(descriptor);
  }
  return digest.digest("hex");
}

function sha512Base64File(filePath) {
  const digest = crypto.createHash("sha512");
  const descriptor = fs.openSync(filePath, "r");
  try {
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
  } finally {
    fs.closeSync(descriptor);
  }
  return digest.digest("base64");
}

function requireRealDirectory(directory, label) {
  if (!path.isAbsolute(directory)) {
    fail(`${label} path must be absolute`);
  }
  let info;
  try {
    info = fs.lstatSync(directory);
  } catch {
    fail(`${label} is missing`);
  }
  if (
    !info.isDirectory() ||
    info.isSymbolicLink() ||
    fs.realpathSync.native(directory) !== directory
  ) {
    fail(`${label} must be a real canonical directory`);
  }
  return directory;
}

function requireRegularFile(filePath, label, maximumSize = Infinity) {
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

function loadJson(filePath, label) {
  requireRegularFile(filePath, label, 16 * 1024 * 1024);
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

function run(executable, arguments_, options = {}) {
  try {
    return childProcess.execFileSync(executable, arguments_, {
      cwd: options.cwd || REPOSITORY_ROOT,
      encoding: options.encoding === null ? null : "utf8",
      env:
        options.env ||
        {
          PATH: "/usr/bin:/bin",
          LANG: "C",
          LC_ALL: "C"
        },
      stdio: ["ignore", "pipe", "pipe"],
      timeout: options.timeout || 120_000,
      maxBuffer: options.maxBuffer || 8 * 1024 * 1024
    });
  } catch {
    fail(options.label || "Desktop release command failed");
  }
}

function git(arguments_) {
  return run("/usr/bin/git", ["-C", REPOSITORY_ROOT, ...arguments_], {
    label: "Desktop release Git provenance check failed"
  }).trim();
}

function parseSemver(value) {
  if (typeof value !== "string" || value.length > 256) {
    fail("Desktop release version is not canonical SemVer");
  }
  const match = SEMVER_PATTERN.exec(value);
  if (!match) {
    fail("Desktop release version is not canonical SemVer");
  }
  const numericCore = [match[1], match[2], match[3]];
  const prerelease = match[4]?.split(".") || [];
  if (
    numericCore.some((part) => part.length > 64) ||
    prerelease.some((part) => part.length > 64) ||
    prerelease.some(
      (part) => /^[0-9]+$/.test(part) && part.length > 1 && part.startsWith("0")
    )
  ) {
    fail("Desktop release version is not canonical SemVer");
  }
  return {
    raw: value,
    core: numericCore.map((part) => BigInt(part)),
    prerelease
  };
}

function compareSemver(left, right) {
  for (let index = 0; index < 3; index += 1) {
    if (left.core[index] !== right.core[index]) {
      return left.core[index] < right.core[index] ? -1 : 1;
    }
  }
  if (left.prerelease.length === 0 || right.prerelease.length === 0) {
    return left.prerelease.length === right.prerelease.length
      ? 0
      : left.prerelease.length === 0
        ? 1
        : -1;
  }
  const length = Math.max(
    left.prerelease.length,
    right.prerelease.length
  );
  for (let index = 0; index < length; index += 1) {
    const leftPart = left.prerelease[index];
    const rightPart = right.prerelease[index];
    if (leftPart === undefined || rightPart === undefined) {
      return leftPart === rightPart ? 0 : leftPart === undefined ? -1 : 1;
    }
    if (leftPart === rightPart) {
      continue;
    }
    const leftNumeric = /^[0-9]+$/.test(leftPart);
    const rightNumeric = /^[0-9]+$/.test(rightPart);
    if (leftNumeric && rightNumeric) {
      const leftValue = BigInt(leftPart);
      const rightValue = BigInt(rightPart);
      return leftValue === rightValue ? 0 : leftValue < rightValue ? -1 : 1;
    }
    if (leftNumeric !== rightNumeric) {
      return leftNumeric ? -1 : 1;
    }
    return compareCodePoints(leftPart, rightPart);
  }
  return 0;
}

function validateTagAndVersion(tag) {
  if (typeof tag !== "string" || !tag.startsWith("v")) {
    fail("Desktop release requires a v-prefixed tag");
  }
  const version = tag.slice(1);
  const parsed = parseSemver(version);
  const runtime = loadJson(
    path.join(REPOSITORY_ROOT, "runtime", "version.json"),
    "Canonical runtime versions"
  );
  const desktop = loadJson(
    path.join(REPOSITORY_ROOT, "desktop", "package.json"),
    "Desktop package"
  );
  const qmd = loadJson(
    path.join(
      REPOSITORY_ROOT,
      "desktop",
      "workers",
      "qmd",
      "package.json"
    ),
    "QMD worker package"
  );
  if (
    runtime.productVersion !== version ||
    desktop.version !== version ||
    qmd.version !== version
  ) {
    fail("Release tag and canonical product/runtime versions disagree");
  }
  const commit = git(["rev-parse", "HEAD"]).toLowerCase();
  const taggedCommit = git(["rev-parse", `${tag}^{commit}`]).toLowerCase();
  const sourceDateEpoch = Number(
    git(["show", "-s", "--format=%ct", "HEAD"])
  );
  if (
    !/^[0-9a-f]{40}$/.test(commit) ||
    taggedCommit !== commit ||
    (process.env.GITHUB_SHA &&
      process.env.GITHUB_SHA.toLowerCase() !== commit) ||
    git(["status", "--porcelain", "--untracked-files=all"]) !== "" ||
    !Number.isSafeInteger(sourceDateEpoch) ||
    sourceDateEpoch < 100_000_000
  ) {
    fail("Release source is not the clean tagged commit");
  }
  const priorVersions = git(["tag", "--merged", "HEAD", "--list", "v*"])
    .split(/\r?\n/)
    .filter((candidate) => candidate && candidate !== tag)
    .map((candidate) => {
      try {
        return parseSemver(candidate.slice(1));
      } catch {
        return undefined;
      }
    })
    .filter(Boolean);
  if (priorVersions.some((prior) => compareSemver(parsed, prior) <= 0)) {
    fail("Release version is not monotonic over reachable SemVer tags");
  }
  return {
    tag,
    version,
    commit,
    sourceDateEpoch,
    channel: parsed.prerelease[0] || "latest",
    prerelease: parsed.prerelease.length > 0
  };
}

function validatePublicPins() {
  const updateLock = loadJson(
    path.join(
      REPOSITORY_ROOT,
      "runtime",
      "update-metadata-key.lock.json"
    ),
    "Update metadata key lock"
  );
  const codesignLock = loadJson(
    path.join(
      REPOSITORY_ROOT,
      "runtime",
      "macos-codesign-certificate.lock.json"
    ),
    "macOS code-signing certificate lock"
  );
  if (
    !hasExactKeys(updateLock, [
      "schemaVersion",
      "algorithm",
      "credentialGenerationId",
      "publicKeyPath",
      "publicKeySha256",
      "status"
    ]) ||
    updateLock.schemaVersion !== 1 ||
    updateLock.algorithm !== "Ed25519" ||
    !/^[0-9a-f]{32}$/.test(updateLock.credentialGenerationId || "") ||
    updateLock.publicKeyPath !== UPDATE_PUBLIC_KEY_RELATIVE ||
    updateLock.status !== "provisioned" ||
    !SHA256_PATTERN.test(updateLock.publicKeySha256 || "") ||
    !hasExactKeys(codesignLock, [
      "schemaVersion",
      "identity",
      "credentialGenerationId",
      "certificateSha256",
      "status"
    ]) ||
    codesignLock.schemaVersion !== 1 ||
    codesignLock.identity !== SIGNING_IDENTITY ||
    codesignLock.credentialGenerationId !==
      updateLock.credentialGenerationId ||
    codesignLock.status !== "provisioned" ||
    !SHA256_PATTERN.test(codesignLock.certificateSha256 || "")
  ) {
    fail(
      "Desktop release public pins are unprovisioned; run the administrator bootstrap"
    );
  }
  const publicKey = path.join(
    REPOSITORY_ROOT,
    ...UPDATE_PUBLIC_KEY_RELATIVE.split("/")
  );
  requireRegularFile(publicKey, "Update metadata public key", 16 * 1024);
  if (sha256File(publicKey) !== updateLock.publicKeySha256) {
    fail("Update metadata public key differs from its reviewed digest");
  }
  loadEd25519PublicKey(publicKey);
  return { updateLock, codesignLock, publicKey };
}

function validateNoTrackedPrivateKeys() {
  const tracked = git(["ls-files", "-z"])
    .split("\0")
    .filter(Boolean);
  for (const relative of tracked) {
    if (
      /\.(?:p12|pfx|key)$/i.test(relative) ||
      /(?:^|\/)(?:private[-_.].*)\.pem$/i.test(relative)
    ) {
      fail("Repository tracks a forbidden private-key filename");
    }
    const candidate = path.join(REPOSITORY_ROOT, relative);
    const info = fs.lstatSync(candidate);
    if (!info.isFile() || info.size > 4 * 1024 * 1024) {
      continue;
    }
    const contents = fs.readFileSync(candidate, "utf8");
    for (const label of [
      "PRIVATE KEY",
      "ENCRYPTED PRIVATE KEY",
      "RSA PRIVATE KEY"
    ]) {
      const begin = ["-----BEGIN", `${label}-----`].join(" ");
      const end = ["-----END", `${label}-----`].join(" ");
      const start = contents.indexOf(begin);
      const finish =
        start === -1 ? -1 : contents.indexOf(end, start + begin.length);
      if (finish !== -1) {
        const body = contents
          .slice(start + begin.length, finish)
          .replace(/\s+/g, "");
        if (
          body.length >= 32 &&
          /^[A-Za-z0-9+/]+={0,2}$/.test(body)
        ) {
          fail("Repository contains private-key PEM material");
        }
      }
    }
  }
}

function preflight(tag) {
  if (process.env.GITHUB_REPOSITORY &&
      process.env.GITHUB_REPOSITORY !== CANONICAL_REPOSITORY) {
    fail("Formal release is restricted to the canonical public repository");
  }
  const release = validateTagAndVersion(tag);
  const pins = validatePublicPins();
  validateNoTrackedPrivateKeys();
  return {
    ...release,
    updatePublicKeySha256: pins.updateLock.publicKeySha256,
    certificateSha256: pins.codesignLock.certificateSha256,
    credentialGenerationId:
      pins.updateLock.credentialGenerationId,
    signingIdentity: pins.codesignLock.identity
  };
}

function isMachO(filePath) {
  const descriptor = fs.openSync(filePath, "r");
  try {
    const magic = Buffer.alloc(4);
    return (
      fs.readSync(descriptor, magic, 0, 4, 0) === 4 &&
      MACHO_MAGICS.has(magic.toString("hex"))
    );
  } finally {
    fs.closeSync(descriptor);
  }
}

function walkAppPayload(root) {
  const canonicalRoot = requireRealDirectory(
    path.resolve(root),
    "Packaged app Contents"
  );
  const files = [];
  const symlinks = [];
  const visitedDirectories = new Set();
  function visit(directory) {
    const directoryInfo = fs.lstatSync(directory);
    const identity = `${directoryInfo.dev}:${directoryInfo.ino}`;
    if (visitedDirectories.has(identity)) {
      fail("Release payload directory graph is cyclic or aliased");
    }
    visitedDirectories.add(identity);
    for (const name of fs.readdirSync(directory).sort(compareCodePoints)) {
      const candidate = path.join(directory, name);
      const info = fs.lstatSync(candidate);
      if (info.isSymbolicLink()) {
        const target = fs.readlinkSync(candidate);
        if (
          path.isAbsolute(target) ||
          target.length === 0 ||
          target.includes("\0") ||
          target.includes("\\")
        ) {
          fail("Release payload contains an unsafe symlink target");
        }
        const lexicalTarget = path.resolve(path.dirname(candidate), target);
        let realTarget;
        try {
          realTarget = fs.realpathSync.native(candidate);
        } catch {
          fail("Release payload contains a dangling or cyclic symlink");
        }
        if (
          !isWithin(canonicalRoot, lexicalTarget) ||
          !isWithin(canonicalRoot, realTarget)
        ) {
          fail("Release payload symlink escapes the app Contents");
        }
        const targetInfo = fs.statSync(candidate);
        if (!targetInfo.isDirectory() && !targetInfo.isFile()) {
          fail("Release payload symlink targets a special file");
        }
        symlinks.push({
          path: path.relative(canonicalRoot, candidate),
          target
        });
      }
      else if (info.isDirectory()) {
        visit(candidate);
      } else if (info.isFile() && info.nlink === 1) {
        files.push(candidate);
      } else {
        fail("Release payload contains a special or hard-linked file");
      }
    }
  }
  visit(canonicalRoot);
  return { files, symlinks };
}

function certificateFingerprint(appPath) {
  const temporary = fs.mkdtempSync(
    path.join(os.tmpdir(), "lcf-codesign-cert-")
  );
  try {
    const prefix = path.join(temporary, "certificate");
    run(
      "/usr/bin/codesign",
      ["-d", "--extract-certificates", prefix, appPath],
      { label: "App signing certificate extraction failed" }
    );
    return sha256File(`${prefix}0`);
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
}

function verifyCodeSigningPolicy(codeObject, release) {
  const inspection = childProcess.spawnSync(
    "/usr/bin/codesign",
    ["-d", "--verbose=4", codeObject],
    {
      encoding: "utf8",
      env: { PATH: "/usr/bin:/bin", LANG: "C", LC_ALL: "C" },
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 30_000,
      maxBuffer: 4 * 1024 * 1024
    }
  );
  if (
    inspection.error ||
    inspection.status !== 0 ||
    inspection.signal !== null
  ) {
    fail("Code-signing policy inspection failed");
  }
  const details = `${inspection.stdout || ""}\n${inspection.stderr || ""}`;
  const authorities = [
    ...details.matchAll(/^Authority=(.+)$/gm)
  ].map((match) => match[1]);
  const flagMatches = [...details.matchAll(/\bflags=0x([0-9a-fA-F]+)\b/g)];
  if (
    authorities.length !== 1 ||
    authorities[0] !== SIGNING_IDENTITY ||
    flagMatches.length !== 1 ||
    (Number.parseInt(flagMatches[0][1], 16) & 0x10000) !== 0 ||
    certificateFingerprint(codeObject) !== release.certificateSha256
  ) {
    fail(
      "Code object identity, certificate, or hardened-runtime flags differ from policy"
    );
  }
}

function verifyApp(appPath, release) {
  requireRealDirectory(appPath, "Packaged macOS app");
  run(
    "/usr/bin/codesign",
    ["--verify", "--deep", "--strict", "--verbose=4", appPath],
    { label: "Packaged app code-signature verification failed" }
  );
  verifyCodeSigningPolicy(appPath, release);
  const executable = path.join(
    appPath,
    "Contents",
    "MacOS",
    PRODUCT_NAME
  );
  requireRegularFile(executable, "Packaged app executable");
  if (
    run("/usr/bin/lipo", ["-archs", executable], {
      label: "Packaged app architecture inspection failed"
    }).trim() !== ARCHITECTURE
  ) {
    fail("Packaged app is not arm64-only");
  }
  const payload = walkAppPayload(path.join(appPath, "Contents"));
  for (const candidate of payload.files.filter(isMachO)) {
    run(
      "/usr/bin/codesign",
      ["--verify", "--strict", "--verbose=2", candidate],
      { label: "Nested Mach-O signature verification failed" }
    );
    verifyCodeSigningPolicy(candidate, release);
    if (
      run("/usr/bin/lipo", ["-archs", candidate], {
        label: "Nested Mach-O architecture inspection failed"
      })
        .trim()
        .split(/\s+/)
        .some((architecture) => architecture !== ARCHITECTURE)
    ) {
      fail("Packaged app contains a non-arm64 Mach-O");
    }
  }
  if (certificateFingerprint(appPath) !== release.certificateSha256) {
    fail("Packaged app certificate differs from the reviewed fingerprint");
  }
  const resources = path.join(appPath, "Contents", "Resources");
  for (const relative of [
    "sidecar/build-manifest.json",
    "qmd/runtime-manifest.json",
    "qmd/runtime-manifest.sha256",
    "companion/build-manifest.json",
    "renderer/renderer-build-manifest.json",
    "update/update-metadata-ed25519-public.pem",
    "update/update-metadata-key.lock.json"
  ]) {
    requireRegularFile(
      path.join(resources, ...relative.split("/")),
      `Packaged resource ${relative}`
    );
  }
  auditRenderer(path.join(resources, "renderer"), {
    expectedCommit: release.commit,
    expectedSourceDateEpoch: release.sourceDateEpoch
  });
  auditPythonSidecar({
    repositoryRoot: REPOSITORY_ROOT,
    stagingRoot: path.join(resources, "sidecar"),
    environment: process.env,
    platform: "darwin",
    architecture: "arm64"
  });
  auditQmdRuntime({
    repositoryRoot: REPOSITORY_ROOT,
    stagingRoot: path.join(resources, "qmd"),
    environment: process.env,
    platform: "darwin",
    architecture: "arm64"
  });
  auditCompanion({
    repositoryRoot: REPOSITORY_ROOT,
    stagingRoot: path.join(resources, "companion")
  });
}

function verifyDmgAndZip(
  dmgPath,
  zipPath,
  release
) {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "lcf-release-"));
  const mountpoint = path.join(temporary, "dmg");
  const zipRoot = path.join(temporary, "zip");
  fs.mkdirSync(mountpoint, { mode: 0o700 });
  fs.mkdirSync(zipRoot, { mode: 0o700 });
  let mounted = false;
  try {
    run(
      "/usr/bin/hdiutil",
      [
        "attach",
        "-readonly",
        "-nobrowse",
        "-mountpoint",
        mountpoint,
        dmgPath
      ],
      { timeout: 180_000, label: "DMG mount verification failed" }
    );
    mounted = true;
    verifyApp(
      path.join(mountpoint, `${PRODUCT_NAME}.app`),
      release
    );
    run("/usr/bin/ditto", ["-x", "-k", zipPath, zipRoot], {
      timeout: 180_000,
      label: "Update ZIP extraction failed"
    });
    verifyApp(
      path.join(zipRoot, `${PRODUCT_NAME}.app`),
      release
    );
  } finally {
    if (mounted) {
      try {
        run("/usr/bin/hdiutil", ["detach", mountpoint], {
          label: "DMG detach failed"
        });
      } catch {
        // The runner is ephemeral; retain the original verification failure.
      }
    }
    fs.rmSync(temporary, { recursive: true, force: true });
  }
}

function copyAsset(source, destinationRoot, name = path.basename(source)) {
  safeBasename(name);
  requireRegularFile(source, `Release asset ${name}`);
  const destination = path.join(destinationRoot, name);
  fs.copyFileSync(source, destination, fs.constants.COPYFILE_EXCL);
  fs.chmodSync(destination, 0o644);
  return destination;
}

function parseUpdaterMetadata(metadataPath, release, zipPath) {
  requireRegularFile(
    metadataPath,
    "electron-updater metadata",
    128 * 1024
  );
  requireRegularFile(
    zipPath,
    "electron-updater ZIP",
    MAX_UPDATE_ZIP_BYTES
  );
  let raw;
  try {
    raw = fs.readFileSync(metadataPath, "utf8");
  } catch {
    fail("electron-updater metadata is invalid YAML");
  }
  const match =
    /^version: ([^\r\n]+)\nfiles:\n  - url: ([^\r\n]+)\n    sha512: ([A-Za-z0-9+/]{86}==)\n    size: ([0-9]+)\npath: ([^\r\n]+)\nsha512: ([A-Za-z0-9+/]{86}==)\nreleaseDate: ([^\r\n]+)\n$/.exec(
      raw
    );
  function scalar(value) {
    if (value.startsWith("'") && value.endsWith("'")) {
      return value.slice(1, -1).replaceAll("''", "'");
    }
    if (value.startsWith('"') && value.endsWith('"')) {
      try {
        return JSON.parse(value);
      } catch {
        fail("electron-updater metadata contains an invalid scalar");
      }
    }
    if (
      value !== value.trim() ||
      value.includes("#") ||
      /^[&*!|>@`{}[\]]/.test(value)
    ) {
      fail("electron-updater metadata contains an unsafe scalar");
    }
    return value;
  }
  if (!match) {
    fail("electron-updater metadata has an unexpected exact shape");
  }
  const metadata = {
    version: scalar(match[1]),
    files: [
      {
        url: scalar(match[2]),
        sha512: match[3],
        size: Number(match[4])
      }
    ],
    path: scalar(match[5]),
    sha512: match[6],
    releaseDate: scalar(match[7])
  };
  if (
    !hasExactKeys(metadata, [
      "version",
      "files",
      "path",
      "sha512",
      "releaseDate"
    ]) ||
    metadata.version !== release.version ||
    !Array.isArray(metadata.files) ||
    metadata.files.length !== 1 ||
    typeof metadata.releaseDate !== "string" ||
    Number.isNaN(Date.parse(metadata.releaseDate)) ||
    new Date(metadata.releaseDate).toISOString() !== metadata.releaseDate
  ) {
    fail("electron-updater metadata has an incomplete shape");
  }
  const zipName = safeBasename(path.basename(zipPath), "Update ZIP");
  const zip = metadata.files[0];
  const expectedSha512 = sha512Base64File(zipPath);
  const expectedSize = fs.statSync(zipPath).size;
  if (
    !hasExactKeys(zip, ["url", "sha512", "size"]) ||
    safeBasename(zip.url, "electron-updater ZIP") !== zipName ||
    !SHA512_BASE64_PATTERN.test(zip.sha512 || "") ||
    zip.sha512 !== expectedSha512 ||
    !Number.isSafeInteger(zip.size) ||
    zip.size <= 0 ||
    zip.size !== expectedSize ||
    safeBasename(metadata.path, "electron-updater path") !== zipName ||
    metadata.sha512 !== expectedSha512
  ) {
    fail("electron-updater metadata does not bind the exact update ZIP");
  }
  return metadata;
}

function assetRecord(filePath, kind) {
  const info = requireRegularFile(filePath, `Release ${kind}`);
  return {
    kind,
    name: path.basename(filePath),
    size: info.size,
    sha256: sha256File(filePath)
  };
}

function validateUpdatePrivateKey(privateKeyPath, publicKeyPath) {
  requireRegularFile(privateKeyPath, "Update metadata private key", 64 * 1024);
  const info = fs.lstatSync(privateKeyPath);
  if ((info.mode & 0o077) !== 0) {
    fail("Update metadata private key permissions are too broad");
  }
  let privateKey;
  try {
    privateKey = crypto.createPrivateKey(fs.readFileSync(privateKeyPath));
  } catch {
    fail("Update metadata private key is invalid");
  }
  if (privateKey.asymmetricKeyType !== "ed25519") {
    fail("Update metadata private key is not Ed25519");
  }
  const reviewedPublicKey = loadEd25519PublicKey(publicKeyPath);
  const derived = crypto
    .createPublicKey(privateKey)
    .export({ type: "spki", format: "der" });
  const reviewed = reviewedPublicKey.export({
    type: "spki",
    format: "der"
  });
  if (
    derived.length !== reviewed.length ||
    !crypto.timingSafeEqual(derived, reviewed)
  ) {
    fail("Update metadata private key does not match the reviewed public key");
  }
  return { privateKey, reviewedPublicKey };
}

function signUpdateManifest(
  manifestPath,
  signaturePath,
  privateKeyPath,
  publicKeyPath
) {
  const { privateKey, reviewedPublicKey } = validateUpdatePrivateKey(
    privateKeyPath,
    publicKeyPath
  );
  const message = fs.readFileSync(manifestPath);
  const signature = crypto.sign(null, message, privateKey);
  if (
    signature.length !== 64 ||
    !crypto.verify(null, message, reviewedPublicKey, signature)
  ) {
    fail("Update metadata Ed25519 signing self-check failed");
  }
  fs.writeFileSync(signaturePath, signature, {
    mode: 0o644,
    flag: "wx"
  });
  requireRegularFile(signaturePath, "Update metadata signature", 64);
}

function assemble({
  tag,
  releaseDirectory,
  outputDirectory,
  privateKeyPath
}) {
  if (process.platform !== "darwin" || process.arch !== "arm64") {
    fail("Desktop release assembly requires native macOS arm64");
  }
  const release = preflight(tag);
  requireRealDirectory(releaseDirectory, "electron-builder output");
  if (!path.isAbsolute(outputDirectory) || fs.existsSync(outputDirectory)) {
    fail("Release asset output must be a new absolute directory");
  }
  fs.mkdirSync(outputDirectory, { mode: 0o700 });
  const base =
    `${ARTIFACT_NAME_PREFIX}-${release.version}-${ARCHITECTURE}`;
  const dmgPath = path.join(releaseDirectory, `${base}.dmg`);
  const zipPath = path.join(releaseDirectory, `${base}.zip`);
  const blockmapPath = `${zipPath}.blockmap`;
  requireRegularFile(
    dmgPath,
    "Signed DMG",
    MAX_DISK_IMAGE_BYTES
  );
  requireRegularFile(
    zipPath,
    "Signed update ZIP",
    MAX_UPDATE_ZIP_BYTES
  );
  requireRegularFile(
    blockmapPath,
    "Update ZIP blockmap",
    MAX_BLOCKMAP_BYTES
  );
  const metadataCandidates = fs
    .readdirSync(releaseDirectory)
    .filter((name) => name.endsWith("-mac.yml"));
  if (metadataCandidates.length !== 1) {
    fail("electron-builder must emit exactly one macOS update metadata file");
  }
  const metadataName = metadataCandidates[0];
  if (metadataName !== `${release.channel}-mac.yml`) {
    fail("electron-updater metadata channel differs from the release version");
  }
  const metadataPath = path.join(releaseDirectory, metadataName);
  parseUpdaterMetadata(metadataPath, release, zipPath);
  const appPath = path.join(
    releaseDirectory,
    "mac-arm64",
    `${PRODUCT_NAME}.app`
  );
  verifyApp(appPath, release);
  verifyDmgAndZip(dmgPath, zipPath, release);
  const packagedResources = path.join(appPath, "Contents", "Resources");

  const copied = [
    copyAsset(dmgPath, outputDirectory),
    copyAsset(zipPath, outputDirectory),
    copyAsset(blockmapPath, outputDirectory),
    copyAsset(metadataPath, outputDirectory),
    copyAsset(
      path.join(
        REPOSITORY_ROOT,
        ...UPDATE_PUBLIC_KEY_RELATIVE.split("/")
      ),
      outputDirectory
    ),
    copyAsset(
      path.join(
        packagedResources,
        "sidecar",
        "build-manifest.json"
      ),
      outputDirectory,
      "python-sidecar-build-manifest.json"
    ),
    copyAsset(
      path.join(
        packagedResources,
        "sidecar",
        "compliance",
        "sbom.spdx.json"
      ),
      outputDirectory,
      "python-sidecar-sbom.spdx.json"
    ),
    copyAsset(
      path.join(
        packagedResources,
        "qmd",
        "runtime-manifest.json"
      ),
      outputDirectory,
      "qmd-runtime-build-manifest.json"
    ),
    copyAsset(
      path.join(
        packagedResources,
        "qmd",
        "compliance",
        "sbom.spdx.json"
      ),
      outputDirectory,
      "qmd-runtime-sbom.spdx.json"
    ),
    copyAsset(
      path.join(
        packagedResources,
        "companion",
        "build-manifest.json"
      ),
      outputDirectory,
      "mcp-companion-build-manifest.json"
    ),
    copyAsset(
      path.join(
        packagedResources,
        "renderer",
        "renderer-build-manifest.json"
      ),
      outputDirectory
    )
  ];
  const updateAssets = [
    assetRecord(copied[0], "dmg"),
    assetRecord(copied[1], "electron-updater-zip"),
    assetRecord(copied[2], "electron-updater-blockmap"),
    assetRecord(copied[3], "electron-updater-metadata")
  ];
  const updateManifest = {
    schemaVersion: 1,
    kind: "local-context-forge-desktop-update",
    repository: CANONICAL_REPOSITORY,
    channel: release.channel,
    version: release.version,
    architecture: ARCHITECTURE,
    source: {
      tag: release.tag,
      commit: release.commit,
      sourceDateEpoch: release.sourceDateEpoch
    },
    publicKey: {
      algorithm: "Ed25519",
      sha256: release.updatePublicKeySha256
    },
    assets: updateAssets
  };
  const updateManifestPath = path.join(
    outputDirectory,
    UPDATE_MANIFEST_NAME
  );
  fs.writeFileSync(
    updateManifestPath,
    `${canonicalJson(updateManifest)}\n`,
    { encoding: "utf8", mode: 0o644, flag: "wx" }
  );
  const signaturePath = path.join(
    outputDirectory,
    UPDATE_SIGNATURE_NAME
  );
  signUpdateManifest(
    updateManifestPath,
    signaturePath,
    privateKeyPath,
    path.join(
      REPOSITORY_ROOT,
      ...UPDATE_PUBLIC_KEY_RELATIVE.split("/")
    )
  );
  copied.push(updateManifestPath, signaturePath);

  const releaseFiles = copied
    .map((filePath) => assetRecord(filePath, "release-asset"))
    .sort((left, right) => compareCodePoints(left.name, right.name));
  const releaseManifest = {
    schemaVersion: 1,
    kind: "local-context-forge-desktop-release",
    repository: CANONICAL_REPOSITORY,
    tag: release.tag,
    version: release.version,
    architecture: ARCHITECTURE,
    commit: release.commit,
    sourceDateEpoch: release.sourceDateEpoch,
    credentialGenerationId: release.credentialGenerationId,
    codeSigning: {
      identity: SIGNING_IDENTITY,
      certificateSha256: release.certificateSha256,
      hardenedRuntime: false,
      notarized: false,
      stapled: false
    },
    automaticApply: {
      enabled: false,
      reason: "VAL-UPDATE-001 physical 0.0.1-to-0.0.2 gate is not passed"
    },
    updateMetadata: {
      manifest: UPDATE_MANIFEST_NAME,
      signature: UPDATE_SIGNATURE_NAME,
      algorithm: "Ed25519",
      publicKeySha256: release.updatePublicKeySha256
    },
    files: releaseFiles
  };
  const releaseManifestPath = path.join(
    outputDirectory,
    RELEASE_MANIFEST_NAME
  );
  fs.writeFileSync(
    releaseManifestPath,
    `${canonicalJson(releaseManifest)}\n`,
    { encoding: "utf8", mode: 0o644, flag: "wx" }
  );
  const checksumFiles = [...copied, releaseManifestPath].sort((left, right) =>
    compareCodePoints(path.basename(left), path.basename(right))
  );
  fs.writeFileSync(
    path.join(outputDirectory, CHECKSUMS_NAME),
    `${checksumFiles
      .map(
        (filePath) =>
          `${sha256File(filePath)}  ${path.basename(filePath)}`
      )
      .join("\n")}\n`,
    { encoding: "ascii", mode: 0o644, flag: "wx" }
  );
  verifyAssetDirectory(outputDirectory, tag);
  return {
    assets: fs.readdirSync(outputDirectory).length,
    version: release.version,
    channel: release.channel
  };
}

function expectedReleaseAssets(release) {
  const base =
    `${ARTIFACT_NAME_PREFIX}-${release.version}-${ARCHITECTURE}`;
  return [
    `${base}.dmg`,
    `${base}.zip`,
    `${base}.zip.blockmap`,
    `${release.channel}-mac.yml`,
    "update-metadata-ed25519-public.pem",
    "python-sidecar-build-manifest.json",
    "python-sidecar-sbom.spdx.json",
    "qmd-runtime-build-manifest.json",
    "qmd-runtime-sbom.spdx.json",
    "mcp-companion-build-manifest.json",
    "renderer-build-manifest.json",
    UPDATE_MANIFEST_NAME,
    UPDATE_SIGNATURE_NAME
  ].sort(compareCodePoints);
}

function validateAssetRecord(record, expectedKind, label) {
  const maximum = {
    dmg: MAX_DISK_IMAGE_BYTES,
    "electron-updater-zip": MAX_UPDATE_ZIP_BYTES,
    "electron-updater-blockmap": MAX_BLOCKMAP_BYTES,
    "electron-updater-metadata": 128 * 1024,
    "release-asset": Number.MAX_SAFE_INTEGER
  }[expectedKind];
  if (
    !hasExactKeys(record, ["kind", "name", "size", "sha256"]) ||
    record.kind !== expectedKind ||
    safeBasename(record.name, label) !== record.name ||
    !Number.isSafeInteger(record.size) ||
    record.size <= 0 ||
    record.size > maximum ||
    !SHA256_PATTERN.test(record.sha256 || "")
  ) {
    fail(`${label} record is malformed`);
  }
  return record;
}

function validateReleaseManifestShape(
  manifest,
  release,
  updateLock,
  codesignLock
) {
  const expectedNames = expectedReleaseAssets(release);
  if (
    !hasExactKeys(manifest, [
      "schemaVersion",
      "kind",
      "repository",
      "tag",
      "version",
      "architecture",
      "commit",
      "sourceDateEpoch",
      "credentialGenerationId",
      "codeSigning",
      "automaticApply",
      "updateMetadata",
      "files"
    ]) ||
    manifest.schemaVersion !== 1 ||
    manifest.kind !== "local-context-forge-desktop-release" ||
    manifest.repository !== CANONICAL_REPOSITORY ||
    manifest.tag !== release.tag ||
    manifest.version !== release.version ||
    manifest.architecture !== ARCHITECTURE ||
    manifest.commit !== release.commit ||
    manifest.sourceDateEpoch !== release.sourceDateEpoch ||
    manifest.credentialGenerationId !==
      updateLock.credentialGenerationId ||
    manifest.credentialGenerationId !==
      codesignLock.credentialGenerationId ||
    !hasExactKeys(manifest.codeSigning, [
      "identity",
      "certificateSha256",
      "hardenedRuntime",
      "notarized",
      "stapled"
    ]) ||
    manifest.codeSigning.identity !== SIGNING_IDENTITY ||
    manifest.codeSigning.certificateSha256 !==
      codesignLock.certificateSha256 ||
    manifest.codeSigning.hardenedRuntime !== false ||
    manifest.codeSigning.notarized !== false ||
    manifest.codeSigning.stapled !== false ||
    !hasExactKeys(manifest.automaticApply, ["enabled", "reason"]) ||
    manifest.automaticApply.enabled !== false ||
    manifest.automaticApply.reason !==
      "VAL-UPDATE-001 physical 0.0.1-to-0.0.2 gate is not passed" ||
    !hasExactKeys(manifest.updateMetadata, [
      "manifest",
      "signature",
      "algorithm",
      "publicKeySha256"
    ]) ||
    manifest.updateMetadata.manifest !== UPDATE_MANIFEST_NAME ||
    manifest.updateMetadata.signature !== UPDATE_SIGNATURE_NAME ||
    manifest.updateMetadata.algorithm !== "Ed25519" ||
    manifest.updateMetadata.publicKeySha256 !==
      updateLock.publicKeySha256 ||
    !Array.isArray(manifest.files) ||
    manifest.files.length !== expectedNames.length
  ) {
    fail("Desktop release manifest is incomplete or unsafe");
  }
  const names = manifest.files.map((record, index) => {
    validateAssetRecord(record, "release-asset", "Desktop release asset");
    if (record.name !== expectedNames[index]) {
      fail("Desktop release manifest asset ordering or membership is invalid");
    }
    return record.name;
  });
  if (new Set(names).size !== names.length) {
    fail("Desktop release manifest contains duplicate asset names");
  }
}

function validateUpdateManifestShape(manifest, release, updateLock) {
  const base =
    `${ARTIFACT_NAME_PREFIX}-${release.version}-${ARCHITECTURE}`;
  const expected = [
    { kind: "dmg", name: `${base}.dmg` },
    { kind: "electron-updater-zip", name: `${base}.zip` },
    {
      kind: "electron-updater-blockmap",
      name: `${base}.zip.blockmap`
    },
    {
      kind: "electron-updater-metadata",
      name: `${release.channel}-mac.yml`
    }
  ];
  if (
    !hasExactKeys(manifest, [
      "schemaVersion",
      "kind",
      "repository",
      "channel",
      "version",
      "architecture",
      "source",
      "publicKey",
      "assets"
    ]) ||
    manifest.schemaVersion !== 1 ||
    manifest.kind !== "local-context-forge-desktop-update" ||
    manifest.repository !== CANONICAL_REPOSITORY ||
    manifest.channel !== release.channel ||
    manifest.version !== release.version ||
    manifest.architecture !== ARCHITECTURE ||
    !hasExactKeys(manifest.source, [
      "tag",
      "commit",
      "sourceDateEpoch"
    ]) ||
    manifest.source.tag !== release.tag ||
    manifest.source.commit !== release.commit ||
    manifest.source.sourceDateEpoch !== release.sourceDateEpoch ||
    !hasExactKeys(manifest.publicKey, ["algorithm", "sha256"]) ||
    manifest.publicKey.algorithm !== "Ed25519" ||
    manifest.publicKey.sha256 !== updateLock.publicKeySha256 ||
    !Array.isArray(manifest.assets) ||
    manifest.assets.length !== expected.length
  ) {
    fail("Canonical update manifest is incomplete");
  }
  const names = manifest.assets.map((record, index) => {
    validateAssetRecord(
      record,
      expected[index].kind,
      "Canonical update asset"
    );
    if (record.name !== expected[index].name) {
      fail("Canonical update manifest asset membership is invalid");
    }
    return record.name;
  });
  if (new Set(names).size !== names.length) {
    fail("Canonical update manifest contains duplicate asset names");
  }
}

function verifyAssetDirectory(assetDirectory, tag) {
  requireRealDirectory(assetDirectory, "Desktop release asset directory");
  const release = validateTagAndVersion(tag);
  const { updateLock, codesignLock, publicKey } = validatePublicPins();
  const releaseManifestPath = path.join(
    assetDirectory,
    RELEASE_MANIFEST_NAME
  );
  const releaseManifest = loadJson(
    releaseManifestPath,
    "Desktop release manifest"
  );
  if (
    fs.readFileSync(releaseManifestPath, "utf8") !==
    `${canonicalJson(releaseManifest)}\n`
  ) {
    fail("Desktop release manifest is not canonical JSON");
  }
  validateReleaseManifestShape(
    releaseManifest,
    release,
    updateLock,
    codesignLock
  );
  const expectedNames = new Set([
    ...releaseManifest.files.map((item) => item?.name),
    RELEASE_MANIFEST_NAME,
    CHECKSUMS_NAME
  ]);
  const actualNames = fs
    .readdirSync(assetDirectory)
    .map((name) => safeBasename(name))
    .sort(compareCodePoints);
  if (
    expectedNames.has(undefined) ||
    expectedNames.size !== actualNames.length ||
    actualNames.some((name) => !expectedNames.has(name))
  ) {
    fail("Desktop release asset set is incomplete or contains extras");
  }
  for (const record of releaseManifest.files) {
    const candidate = path.join(assetDirectory, record.name);
    const info = requireRegularFile(candidate, "Desktop release asset");
    if (
      !SHA256_PATTERN.test(record.sha256 || "") ||
      record.size !== info.size ||
      record.sha256 !== sha256File(candidate)
    ) {
      fail("Desktop release asset differs from its release manifest");
    }
  }
  const updateManifestPath = path.join(
    assetDirectory,
    UPDATE_MANIFEST_NAME
  );
  const updateManifest = loadJson(
    updateManifestPath,
    "Canonical update manifest"
  );
  if (
    fs.readFileSync(updateManifestPath, "utf8") !==
    `${canonicalJson(updateManifest)}\n`
  ) {
    fail("Canonical update manifest is not canonical JSON");
  }
  validateUpdateManifestShape(updateManifest, release, updateLock);
  for (const record of updateManifest.assets) {
    const candidate = path.join(assetDirectory, record.name);
    const info = requireRegularFile(candidate, "Signed update asset");
    if (
      !SHA256_PATTERN.test(record.sha256 || "") ||
      record.size !== info.size ||
      record.sha256 !== sha256File(candidate)
    ) {
      fail("Signed update asset differs from its canonical manifest");
    }
  }
  const copiedPublicKey = path.join(
    assetDirectory,
    "update-metadata-ed25519-public.pem"
  );
  requireRegularFile(copiedPublicKey, "Release update public key", 16 * 1024);
  if (
    sha256File(copiedPublicKey) !== updateLock.publicKeySha256 ||
    !fs.readFileSync(copiedPublicKey).equals(fs.readFileSync(publicKey))
  ) {
    fail("Release update public key differs from the reviewed trust anchor");
  }
  const signaturePath = path.join(assetDirectory, UPDATE_SIGNATURE_NAME);
  requireRegularFile(signaturePath, "Detached update metadata signature", 64);
  const signature = fs.readFileSync(signaturePath);
  if (
    signature.length !== 64 ||
    !crypto.verify(
      null,
      fs.readFileSync(updateManifestPath),
      loadEd25519PublicKey(copiedPublicKey),
      signature
    )
  ) {
    fail("Detached update metadata signature verification failed");
  }
  const zipRecord = updateManifest.assets.find(
    (record) => record.kind === "electron-updater-zip"
  );
  const metadataRecord = updateManifest.assets.find(
    (record) => record.kind === "electron-updater-metadata"
  );
  parseUpdaterMetadata(
    path.join(assetDirectory, metadataRecord.name),
    release,
    path.join(assetDirectory, zipRecord.name)
  );

  const checksumPath = path.join(assetDirectory, CHECKSUMS_NAME);
  requireRegularFile(checksumPath, "Desktop release checksums", 1024 * 1024);
  const checksumBytes = fs.readFileSync(checksumPath);
  if (
    checksumBytes.length === 0 ||
    checksumBytes[checksumBytes.length - 1] !== 0x0a ||
    checksumBytes.includes(0x0d) ||
    [...checksumBytes].some((value) => value > 0x7f)
  ) {
    fail("Desktop release checksum manifest is not canonical ASCII");
  }
  const checksumLines = checksumBytes
    .toString("ascii")
    .slice(0, -1)
    .split("\n");
  const checksumNames = new Set();
  for (const line of checksumLines) {
    const match = /^([0-9a-f]{64})  ([^/\\\0]+)$/.exec(line);
    if (!match || checksumNames.has(match[2])) {
      fail("Desktop release checksum manifest is malformed");
    }
    checksumNames.add(match[2]);
    const candidate = path.join(
      assetDirectory,
      safeBasename(match[2], "Checksum asset")
    );
    requireRegularFile(candidate, "Checksummed desktop release asset");
    if (sha256File(candidate) !== match[1]) {
      fail("Desktop release checksum verification failed");
    }
  }
  const expectedChecksumNames = actualNames
    .filter((name) => name !== CHECKSUMS_NAME)
    .sort(compareCodePoints);
  if (
    checksumNames.size !== actualNames.length - 1 ||
    checksumNames.has(CHECKSUMS_NAME) ||
    checksumLines.some(
      (line, index) =>
        line.slice(66) !== expectedChecksumNames[index]
    )
  ) {
    fail("Desktop release checksum coverage is incomplete");
  }
  return { assets: actualNames.length, version: release.version };
}

function parseArguments(argv) {
  const [command, ...rest] = argv;
  const allowed = new Map([
    ["preflight", new Set(["--tag"])],
    ["verify-key", new Set(["--tag", "--private-key"])],
    [
      "assemble",
      new Set([
        "--tag",
        "--release-dir",
        "--output-dir",
        "--private-key"
      ])
    ],
    ["verify-assets", new Set(["--tag", "--asset-dir"])]
  ]);
  if (!allowed.has(command) || rest.length % 2 !== 0) {
    fail("Desktop release command is unsupported");
  }
  const values = new Map();
  for (let index = 0; index < rest.length; index += 2) {
    const name = rest[index];
    const value = rest[index + 1];
    if (
      !allowed.get(command).has(name) ||
      value === undefined ||
      values.has(name)
    ) {
      fail("Desktop release arguments are invalid");
    }
    values.set(name, value);
  }
  if (
    values.size !== allowed.get(command).size ||
    [...allowed.get(command)].some((name) => !values.has(name))
  ) {
    fail("Desktop release arguments are incomplete");
  }
  const tag = values.get("--tag");
  if (!tag) {
    fail("--tag is required");
  }
  return { command, values, tag };
}

function main(argv = process.argv.slice(2)) {
  const { command, values, tag } = parseArguments(argv);
  let summary;
  if (command === "preflight") {
    summary = preflight(tag);
  } else if (command === "verify-key") {
    const privateKeyPath = values.get("--private-key");
    const release = preflight(tag);
    const { publicKey } = validatePublicPins();
    validateUpdatePrivateKey(path.resolve(privateKeyPath), publicKey);
    summary = {
      algorithm: "Ed25519",
      publicKeySha256: release.updatePublicKeySha256,
      status: "verified"
    };
  } else if (command === "assemble") {
    const releaseDirectory = values.get("--release-dir");
    const outputDirectory = values.get("--output-dir");
    const privateKeyPath = values.get("--private-key");
    if (!releaseDirectory || !outputDirectory || !privateKeyPath) {
      fail("assemble requires release/output/private-key paths");
    }
    summary = assemble({
      tag,
      releaseDirectory: path.resolve(releaseDirectory),
      outputDirectory: path.resolve(outputDirectory),
      privateKeyPath: path.resolve(privateKeyPath)
    });
  } else {
    const assetDirectory = values.get("--asset-dir");
    if (!assetDirectory) {
      fail("verify-assets requires --asset-dir");
    }
    summary = verifyAssetDirectory(path.resolve(assetDirectory), tag);
  }
  process.stdout.write(`${JSON.stringify(summary)}\n`);
}

module.exports = {
  DesktopReleaseError,
  assemble,
  canonicalJson,
  compareSemver,
  main,
  parseSemver,
  preflight,
  sha256File,
  validateNoTrackedPrivateKeys,
  validateUpdatePrivateKey,
  validatePublicPins,
  validateTagAndVersion,
  validateReleaseManifestShape,
  validateUpdateManifestShape,
  walkAppPayload,
  parseUpdaterMetadata,
  verifyAssetDirectory
};

if (require.main === module) {
  try {
    main();
  } catch (error) {
    if (error instanceof DesktopReleaseError) {
      process.stderr.write(`desktop release failed: ${error.message}\n`);
      process.exitCode = 2;
    } else {
      throw error;
    }
  }
}

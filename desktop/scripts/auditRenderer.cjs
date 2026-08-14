"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const REPOSITORY_ROOT = path.resolve(__dirname, "..", "..");
const DEFAULT_RENDERER_ROOT = path.join(
  REPOSITORY_ROOT,
  "desktop",
  "resources",
  "renderer"
);
const WEB_PACKAGE_LOCK = path.join(
  REPOSITORY_ROOT,
  "web",
  "package-lock.json"
);
const MANIFEST_NAME = "renderer-build-manifest.json";
const MANIFEST_KIND = "local-context-forge-renderer-build";
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const SAFE_PATH_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._/-]*$/;
const ALLOWED_EXTENSIONS = new Set([
  ".css",
  ".gif",
  ".html",
  ".ico",
  ".jpeg",
  ".jpg",
  ".js",
  ".json",
  ".mjs",
  ".png",
  ".svg",
  ".ttf",
  ".wasm",
  ".webp",
  ".woff",
  ".woff2"
]);
const MAX_FILE_BYTES = 64 * 1024 * 1024;
const MAX_TOTAL_BYTES = 256 * 1024 * 1024;

class RendererAuditError extends Error {
  constructor(message) {
    super(message);
    this.name = "RendererAuditError";
  }
}

function fail(message) {
  throw new RendererAuditError(message);
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function exactKeys(value, expected) {
  if (!isObject(value)) {
    return false;
  }
  const actual = Object.keys(value).sort();
  return (
    actual.length === expected.length &&
    actual.every((key, index) => key === [...expected].sort()[index])
  );
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
  return JSON.stringify(sortJson(value));
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
}

function inventory(root, { excludeManifest = false } = {}) {
  const records = [];
  let totalBytes = 0;
  function visit(directory) {
    for (const name of fs.readdirSync(directory).sort(compareCodePoints)) {
      const candidate = path.join(directory, name);
      const info = fs.lstatSync(candidate);
      if (info.isSymbolicLink()) {
        fail("Renderer bundle must not contain symlinks");
      }
      if (info.isDirectory()) {
        visit(candidate);
        continue;
      }
      if (!info.isFile() || info.nlink !== 1 || info.size <= 0) {
        fail("Renderer bundle contains an empty, special, or hard-linked file");
      }
      const relative = path.relative(root, candidate).split(path.sep).join("/");
      if (excludeManifest && relative === MANIFEST_NAME) {
        continue;
      }
      if (
        !SAFE_PATH_PATTERN.test(relative) ||
        relative.includes("//") ||
        relative.split("/").some((part) => part === "." || part === "..") ||
        !ALLOWED_EXTENSIONS.has(path.extname(relative).toLowerCase()) ||
        info.size > MAX_FILE_BYTES
      ) {
        fail("Renderer bundle contains an unsafe path or file");
      }
      totalBytes += info.size;
      if (totalBytes > MAX_TOTAL_BYTES) {
        fail("Renderer bundle exceeds its reviewed size budget");
      }
      records.push({
        path: relative,
        size: info.size,
        sha256: sha256File(candidate)
      });
    }
  }
  visit(root);
  return records.sort((left, right) =>
    compareCodePoints(left.path, right.path)
  );
}

function validateIndex(root, records) {
  if (
    records.some((record) => /(?:^|\/)README(?:\.|$)/i.test(record.path)) ||
    records.some((record) => record.path.endsWith(".map"))
  ) {
    fail("Renderer bundle contains a placeholder README or source map");
  }
  const indexRecords = records.filter((record) => record.path === "index.html");
  if (indexRecords.length !== 1) {
    fail("Renderer bundle must contain exactly one root index.html");
  }
  const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
  if (
    !html.includes('<div id="root"></div>') ||
    /\/src\/main\.tsx|sourceMappingURL/i.test(html) ||
    /\b(?:src|href)\s*=\s*["'](?:https?:)?\/\//i.test(html)
  ) {
    fail("Renderer index is a development marker or references a remote origin");
  }
  const references = [
    ...html.matchAll(/\b(?:src|href)\s*=\s*(["'])(.*?)\1/g)
  ].map((match) => match[2]);
  if (references.length < 2) {
    fail("Renderer index does not reference its production assets");
  }
  const names = new Set(records.map((record) => record.path));
  for (const reference of references) {
    if (
      !reference.startsWith("/assets/") ||
      reference.includes("?") ||
      reference.includes("#") ||
      !names.has(reference.slice(1))
    ) {
      fail("Renderer index contains an unbound or unsafe asset reference");
    }
  }
}

function loadManifest(root) {
  const manifestPath = path.join(root, MANIFEST_NAME);
  let descriptor;
  let before;
  let bytes;
  try {
    descriptor = fs.openSync(
      manifestPath,
      fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW
    );
    before = fs.fstatSync(descriptor);
    bytes = fs.readFileSync(descriptor);
    const after = fs.fstatSync(descriptor);
    if (
      !before.isFile() ||
      before.uid !== process.geteuid() ||
      before.nlink !== 1 ||
      before.size <= 0 ||
      before.size > 8 * 1024 * 1024 ||
      (before.mode & 0o7022) !== 0 ||
      before.dev !== after.dev ||
      before.ino !== after.ino ||
      before.mode !== after.mode ||
      before.nlink !== after.nlink ||
      before.size !== after.size ||
      before.mtimeMs !== after.mtimeMs ||
      before.ctimeMs !== after.ctimeMs
    ) {
      fail("Renderer build manifest must be a stable bounded regular file");
    }
  } catch (error) {
    if (error instanceof RendererAuditError) {
      throw error;
    }
    fail("Renderer build manifest is unreadable");
  } finally {
    if (descriptor !== undefined) {
      fs.closeSync(descriptor);
    }
  }
  let manifest;
  let text;
  try {
    text = bytes.toString("utf8");
    if (!Buffer.from(text, "utf8").equals(bytes)) {
      fail("Renderer build manifest is not valid UTF-8");
    }
    manifest = JSON.parse(text);
  } catch (error) {
    if (error instanceof RendererAuditError) {
      throw error;
    }
    fail("Renderer build manifest is not valid JSON");
  }
  if (
    text !== `${canonicalJson(manifest)}\n` ||
    !exactKeys(manifest, ["schemaVersion", "kind", "source", "builder", "files"]) ||
    manifest.schemaVersion !== 1 ||
    manifest.kind !== MANIFEST_KIND ||
    !exactKeys(manifest.source, [
      "repositoryCommit",
      "repositoryTree",
      "sourceSnapshotSha256",
      "sourceDateEpoch",
      "packageLockSha256",
      "inputSnapshotSha256",
      "inputFiles"
    ]) ||
    !/^[0-9a-f]{40}$/.test(manifest.source.repositoryCommit || "") ||
    !/^[0-9a-f]{40}$/.test(manifest.source.repositoryTree || "") ||
    !SHA256_PATTERN.test(manifest.source.sourceSnapshotSha256 || "") ||
    !Number.isSafeInteger(manifest.source.sourceDateEpoch) ||
    manifest.source.sourceDateEpoch < 100_000_000 ||
    !SHA256_PATTERN.test(manifest.source.packageLockSha256 || "") ||
    !SHA256_PATTERN.test(manifest.source.inputSnapshotSha256 || "") ||
    !Number.isSafeInteger(manifest.source.inputFiles) ||
    manifest.source.inputFiles < 5 ||
    !exactKeys(manifest.builder, [
      "name",
      "version",
      "reactPluginVersion",
      "nodeVersion",
      "npmVersion",
      "installedContentSha256"
    ]) ||
    manifest.builder.name !== "vite" ||
    manifest.builder.version !== "7.3.6" ||
    manifest.builder.reactPluginVersion !== "4.7.0" ||
    manifest.builder.nodeVersion !== "v22.23.2" ||
    manifest.builder.npmVersion !== "10.9.8" ||
    !SHA256_PATTERN.test(manifest.builder.installedContentSha256 || "") ||
    !Array.isArray(manifest.files)
  ) {
    fail("Renderer build manifest has a non-canonical or invalid shape");
  }
  return {
    manifest,
    manifestSha256: crypto.createHash("sha256").update(bytes).digest("hex")
  };
}

function auditRenderer(
  rendererRoot = DEFAULT_RENDERER_ROOT,
  {
    expectedCommit,
    expectedTree,
    expectedSourceSnapshotSha256,
    expectedSourceDateEpoch,
    expectedPackageLockSha256,
    packageLockPath
  } = {}
) {
  const resolvedRoot = path.resolve(rendererRoot);
  requireRealDirectory(resolvedRoot, "Renderer bundle");
  const manifestAttestation = loadManifest(resolvedRoot);
  const manifest = manifestAttestation.manifest;
  const actual = inventory(resolvedRoot, { excludeManifest: true });
  validateIndex(resolvedRoot, actual);
  if (
    manifest.files.length !== actual.length ||
    manifest.files.some(
      (record, index) =>
        !exactKeys(record, ["path", "size", "sha256"]) ||
        record.path !== actual[index].path ||
        record.size !== actual[index].size ||
        record.sha256 !== actual[index].sha256
    )
  ) {
    fail("Renderer files differ from the canonical build inventory");
  }
  if (
    expectedTree !== undefined &&
    manifest.source.repositoryTree !== expectedTree
  ) {
    fail("Renderer source tree differs from the release tree");
  }
  if (
    expectedSourceSnapshotSha256 !== undefined &&
    manifest.source.sourceSnapshotSha256 !== expectedSourceSnapshotSha256
  ) {
    fail("Renderer source snapshot differs from the release snapshot");
  }
  if (
    expectedCommit !== undefined &&
    manifest.source.repositoryCommit !== expectedCommit
  ) {
    fail("Renderer source commit differs from the release commit");
  }
  if (
    expectedSourceDateEpoch !== undefined &&
    manifest.source.sourceDateEpoch !== expectedSourceDateEpoch
  ) {
    fail("Renderer source epoch differs from the release commit");
  }
  if (expectedPackageLockSha256 !== undefined) {
    if (
      !SHA256_PATTERN.test(expectedPackageLockSha256) ||
      manifest.source.packageLockSha256 !== expectedPackageLockSha256
    ) {
      fail("Renderer package lock differs from the reviewed source object");
    }
  } else if (packageLockPath !== null) {
    const lockPath = path.resolve(packageLockPath || WEB_PACKAGE_LOCK);
    let lockInfo;
    try {
      lockInfo = fs.lstatSync(lockPath);
    } catch {
      fail("Web package lock is missing");
    }
    if (
      !lockInfo.isFile() ||
      lockInfo.isSymbolicLink() ||
      lockInfo.nlink !== 1 ||
      manifest.source.packageLockSha256 !== sha256File(lockPath)
    ) {
      fail("Renderer package lock differs from the build manifest");
    }
  }
  return {
    files: actual.length,
    bytes: actual.reduce((total, record) => total + record.size, 0),
    repositoryCommit: manifest.source.repositoryCommit,
    repositoryTree: manifest.source.repositoryTree,
    sourceSnapshotSha256: manifest.source.sourceSnapshotSha256,
    inputSnapshotSha256: manifest.source.inputSnapshotSha256,
    packageLockSha256: manifest.source.packageLockSha256,
    installedContentSha256: manifest.builder.installedContentSha256,
    builder: { ...manifest.builder },
    manifest: JSON.parse(JSON.stringify(manifest)),
    manifestSha256: manifestAttestation.manifestSha256
  };
}

function main(argv = process.argv.slice(2)) {
  if (argv.length > 1 || (argv.length === 1 && !path.isAbsolute(argv[0]))) {
    fail("Usage: auditRenderer.cjs [absolute-renderer-root]");
  }
  const expectedCommit = (process.env.LCF_SOURCE_SHA || "").toLowerCase();
  const expectedTree = (process.env.LCF_SOURCE_TREE || "").toLowerCase();
  const expectedSourceSnapshotSha256 = (
    process.env.LCF_SOURCE_SNAPSHOT_SHA256 || ""
  ).toLowerCase();
  const expectedPackageLockSha256 = (
    process.env.LCF_RENDERER_PACKAGE_LOCK_SHA256 || ""
  ).toLowerCase();
  const expectedSourceDateEpoch = Number(process.env.LCF_SOURCE_DATE_EPOCH);
  if (
    !/^[0-9a-f]{40}$/.test(expectedCommit) ||
    !/^[0-9a-f]{40}$/.test(expectedTree) ||
    !SHA256_PATTERN.test(expectedSourceSnapshotSha256) ||
    !SHA256_PATTERN.test(expectedPackageLockSha256) ||
    !Number.isSafeInteger(expectedSourceDateEpoch) ||
    expectedSourceDateEpoch < 100_000_000
  ) {
    fail("Renderer exact source environment is incomplete");
  }
  const summary = auditRenderer(argv[0] || DEFAULT_RENDERER_ROOT, {
    expectedCommit,
    expectedTree,
    expectedSourceSnapshotSha256,
    expectedSourceDateEpoch,
    expectedPackageLockSha256
  });
  process.stdout.write(`${canonicalJson(summary)}\n`);
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    const message =
      error instanceof RendererAuditError
        ? error.message
        : "Renderer audit failed unexpectedly";
    process.stderr.write(`renderer audit failed: ${message}\n`);
    process.exitCode = 1;
  }
}

module.exports = {
  MANIFEST_KIND,
  MANIFEST_NAME,
  RendererAuditError,
  auditRenderer,
  canonicalJson,
  inventory,
  sha256File
};

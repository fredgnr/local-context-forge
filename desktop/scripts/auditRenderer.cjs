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
  let info;
  try {
    info = fs.lstatSync(manifestPath);
  } catch {
    fail("Renderer build manifest is missing");
  }
  if (
    !info.isFile() ||
    info.isSymbolicLink() ||
    info.nlink !== 1 ||
    info.size > 8 * 1024 * 1024
  ) {
    fail("Renderer build manifest must be a bounded regular file");
  }
  let manifest;
  try {
    manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  } catch {
    fail("Renderer build manifest is not valid JSON");
  }
  if (
    fs.readFileSync(manifestPath, "utf8") !==
      `${canonicalJson(manifest)}\n` ||
    !exactKeys(manifest, ["schemaVersion", "kind", "source", "files"]) ||
    manifest.schemaVersion !== 1 ||
    manifest.kind !== MANIFEST_KIND ||
    !exactKeys(manifest.source, [
      "repositoryCommit",
      "sourceDateEpoch",
      "packageLockSha256"
    ]) ||
    !/^[0-9a-f]{40}$/.test(manifest.source.repositoryCommit || "") ||
    !Number.isSafeInteger(manifest.source.sourceDateEpoch) ||
    manifest.source.sourceDateEpoch < 100_000_000 ||
    !SHA256_PATTERN.test(manifest.source.packageLockSha256 || "") ||
    !Array.isArray(manifest.files)
  ) {
    fail("Renderer build manifest has a non-canonical or invalid shape");
  }
  return manifest;
}

function auditRenderer(
  rendererRoot = DEFAULT_RENDERER_ROOT,
  {
    expectedCommit,
    expectedSourceDateEpoch,
    packageLockPath = WEB_PACKAGE_LOCK
  } = {}
) {
  const resolvedRoot = path.resolve(rendererRoot);
  requireRealDirectory(resolvedRoot, "Renderer bundle");
  const manifest = loadManifest(resolvedRoot);
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
  if (packageLockPath !== null) {
    const lockPath = path.resolve(packageLockPath);
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
    repositoryCommit: manifest.source.repositoryCommit
  };
}

function main(argv = process.argv.slice(2)) {
  if (argv.length > 1 || (argv.length === 1 && !path.isAbsolute(argv[0]))) {
    fail("Usage: auditRenderer.cjs [absolute-renderer-root]");
  }
  const summary = auditRenderer(argv[0] || DEFAULT_RENDERER_ROOT);
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

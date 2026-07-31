"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const MANIFEST_NAME = "build-manifest.json";
const ENTRYPOINT = "index.mjs";
const EXPECTED_KIND = "local-context-forge-mcp-companion";
const EXPECTED_DEPENDENCIES = Object.freeze({
  "@modelcontextprotocol/sdk": {
    license: "MIT",
    version: "1.30.0"
  },
  ajv: { license: "MIT", version: "8.20.0" },
  "ajv-formats": { license: "MIT", version: "3.0.1" },
  "fast-deep-equal": { license: "MIT", version: "3.1.3" },
  "fast-uri": { license: "BSD-3-Clause", version: "3.1.4" },
  "json-schema-traverse": { license: "MIT", version: "1.0.0" },
  zod: { license: "MIT", version: "4.4.3" },
  "zod-to-json-schema": { license: "ISC", version: "3.25.2" }
});
const NOTICE_LABELS = Object.freeze({
  "@modelcontextprotocol/sdk":
    "Model Context Protocol TypeScript SDK 1.30.0 license",
  ajv: "Ajv 8.20.0 license",
  "ajv-formats": "ajv-formats 3.0.1 license",
  "fast-deep-equal": "fast-deep-equal 3.1.3 license",
  "fast-uri": "fast-uri 3.1.4 license",
  "json-schema-traverse": "json-schema-traverse 1.0.0 license",
  zod: "Zod 4.4.3 license",
  "zod-to-json-schema": "zod-to-json-schema 3.25.2 license"
});
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const INTEGRITY_PATTERN = /^sha512-[A-Za-z0-9+/]+={0,2}$/;
const MAX_BUNDLE_BYTES = 4 * 1024 * 1024;
const FIXED_INPUTS = Object.freeze([
  "desktop/companion/THIRD_PARTY_NOTICES.txt",
  "desktop/companion/src/bridgeClient.ts",
  "desktop/companion/src/index.ts",
  "desktop/companion/src/server.ts",
  "desktop/companion/tsconfig.json",
  "desktop/electron-builder.yml",
  "desktop/package-lock.json",
  "desktop/package.json",
  "desktop/scripts/auditCompanion.cjs",
  "desktop/scripts/buildCompanion.cjs",
  "desktop/src/mcpProtocol.ts",
  "runtime/mcp-companion-build-manifest.schema.json",
  "runtime/version.json"
]);

class CompanionAuditError extends Error {
  constructor(message) {
    super(message);
    this.name = "CompanionAuditError";
  }
}

function fail(message) {
  throw new CompanionAuditError(message);
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function exactKeys(value, expected, label) {
  if (!isObject(value)) {
    fail(`${label} must be an object`);
  }
  const keys = Object.keys(value);
  if (
    keys.length !== expected.length ||
    keys.some((key) => !expected.includes(key))
  ) {
    fail(`${label} does not match the reviewed schema`);
  }
  return value;
}

function sortJson(value) {
  if (Array.isArray(value)) {
    return value.map(sortJson);
  }
  if (!isObject(value)) {
    return value;
  }
  const result = {};
  for (const key of Object.keys(value).sort()) {
    result[key] = sortJson(value[key]);
  }
  return result;
}

function canonicalJson(value) {
  return `${JSON.stringify(sortJson(value))}\n`;
}

function sha256File(filePath) {
  const info = requireRegularFile(filePath, "Audited file");
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
  return { sha256: digest.digest("hex"), size: info.size };
}

function requireRegularFile(filePath, label) {
  let info;
  try {
    info = fs.lstatSync(filePath);
  } catch {
    fail(`${label} is missing`);
  }
  if (!info.isFile() || info.isSymbolicLink()) {
    fail(`${label} must be a regular file`);
  }
  return info;
}

function requireRealDirectory(directoryPath, label) {
  let info;
  try {
    info = fs.lstatSync(directoryPath);
  } catch {
    fail(`${label} is missing`);
  }
  if (!info.isDirectory() || info.isSymbolicLink()) {
    fail(`${label} must be a real directory`);
  }
  return fs.realpathSync(directoryPath);
}

function loadJson(filePath, label) {
  requireRegularFile(filePath, label);
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    fail(`${label} is not valid JSON`);
  }
}

function inputDigests(repositoryRoot) {
  const result = {};
  for (const relative of FIXED_INPUTS) {
    const candidate = path.join(repositoryRoot, ...relative.split("/"));
    result[relative] = sha256File(candidate).sha256;
  }
  return result;
}

function validateLockedDependency(
  packageJson,
  packageLock,
  name,
  expected
) {
  const archiveName =
    name === "@modelcontextprotocol/sdk" ? "sdk" : name;
  const expectedResolved =
    `https://registry.npmjs.org/${name}/-/${archiveName}-${expected.version}.tgz`;
  if (
    ["@modelcontextprotocol/sdk", "zod"].includes(name) &&
    packageJson.devDependencies?.[name] !== expected.version
  ) {
    fail(`${name} must be exactly pinned in package.json`);
  }
  const entry = packageLock.packages?.[`node_modules/${name}`];
  if (
    !isObject(entry) ||
    entry.version !== expected.version ||
    entry.dev !== true ||
    entry.resolved !== expectedResolved ||
    entry.license !== expected.license ||
    !INTEGRITY_PATTERN.test(String(entry.integrity ?? ""))
  ) {
    fail(`${name} lock entry is not reproducible`);
  }
}

function validateNotices(repositoryRoot) {
  const noticePath = path.join(
    repositoryRoot,
    "desktop",
    "companion",
    "THIRD_PARTY_NOTICES.txt"
  );
  requireRegularFile(noticePath, "Companion third-party notices");
  const notices = fs.readFileSync(noticePath, "utf8");
  for (const name of Object.keys(EXPECTED_DEPENDENCIES)) {
    const licensePath = path.join(
      repositoryRoot,
      "desktop",
      "node_modules",
      ...name.split("/"),
      "LICENSE"
    );
    requireRegularFile(licensePath, `${name} license`);
    const license = fs.readFileSync(licensePath, "utf8").trim();
    if (
      !notices.includes(NOTICE_LABELS[name]) ||
      !notices.includes(license)
    ) {
      fail(`${name} license is missing from companion notices`);
    }
  }
}

function validateManifest(manifest, repositoryRoot, stagingRoot) {
  exactKeys(
    manifest,
    [
      "schemaVersion",
      "kind",
      "entrypoint",
      "product",
      "target",
      "dependencies",
      "tools",
      "sourceInputs",
      "bundle"
    ],
    "Companion manifest"
  );
  if (
    manifest.schemaVersion !== 1 ||
    manifest.kind !== EXPECTED_KIND ||
    manifest.entrypoint !== ENTRYPOINT
  ) {
    fail("Companion manifest identity is invalid");
  }
  const version = loadJson(
    path.join(repositoryRoot, "runtime", "version.json"),
    "Runtime version"
  );
  const product = exactKeys(
    manifest.product,
    ["appVersion", "mcpContract", "bridgeProtocol"],
    "Manifest product"
  );
  if (
    product.appVersion !== version.productVersion ||
    product.mcpContract !== version.mcpContract ||
    product.bridgeProtocol !== "1.0"
  ) {
    fail("Companion product/protocol version is stale");
  }
  const target = exactKeys(
    manifest.target,
    ["os", "architecture", "nodeMajor", "moduleFormat"],
    "Manifest target"
  );
  if (
    target.os !== "darwin" ||
    target.architecture !== "arm64" ||
    target.nodeMajor !== 22 ||
    target.moduleFormat !== "esm"
  ) {
    fail("Companion target is invalid");
  }
  const dependencies = exactKeys(
    manifest.dependencies,
    Object.keys(EXPECTED_DEPENDENCIES),
    "Manifest dependencies"
  );
  if (canonicalJson(dependencies) !== canonicalJson(EXPECTED_DEPENDENCIES)) {
    fail("Companion dependency versions are stale");
  }
  if (
    !Array.isArray(manifest.tools) ||
    manifest.tools.length !== 2 ||
    manifest.tools[0] !== "resolve-library-id" ||
    manifest.tools[1] !== "query-docs"
  ) {
    fail("Companion tool allowlist changed");
  }
  const expectedInputs = inputDigests(repositoryRoot);
  if (canonicalJson(manifest.sourceInputs) !== canonicalJson(expectedInputs)) {
    fail("Companion source input digest changed");
  }
  const bundle = exactKeys(
    manifest.bundle,
    ["files", "imports", "packages"],
    "Manifest bundle"
  );
  if (!Array.isArray(bundle.files) || bundle.files.length !== 1) {
    fail("Companion bundle inventory is invalid");
  }
  const file = exactKeys(
    bundle.files[0],
    ["path", "size", "sha256"],
    "Manifest bundle file"
  );
  const entrypoint = path.join(stagingRoot, ENTRYPOINT);
  const actual = sha256File(entrypoint);
  if (
    file.path !== ENTRYPOINT ||
    file.size !== actual.size ||
    file.sha256 !== actual.sha256 ||
    !SHA256_PATTERN.test(String(file.sha256)) ||
    actual.size < 1 ||
    actual.size > MAX_BUNDLE_BYTES
  ) {
    fail("Companion bundle bytes do not match the manifest");
  }
  if (
    !Array.isArray(bundle.imports) ||
    bundle.imports.some(
      (entry) =>
        !isObject(entry) ||
        typeof entry.kind !== "string" ||
        entry.kind.length === 0 ||
        entry.external !== true ||
        typeof entry.path !== "string" ||
        !entry.path.startsWith("node:")
    )
  ) {
    fail("Companion bundle has a non-Node external import");
  }
  if (
    !Array.isArray(bundle.packages) ||
    canonicalJson(bundle.packages) !==
      canonicalJson(Object.keys(EXPECTED_DEPENDENCIES))
  ) {
    fail("Companion bundled dependency closure changed");
  }
  const entries = fs.readdirSync(stagingRoot).sort();
  if (
    entries.length !== 2 ||
    entries[0] !== MANIFEST_NAME ||
    entries[1] !== ENTRYPOINT
  ) {
    fail("Companion staging contains unreviewed files");
  }
}

function auditCompanion(options) {
  const repositoryRoot = requireRealDirectory(
    options.repositoryRoot,
    "Repository root"
  );
  const stagingRoot = requireRealDirectory(
    options.stagingRoot,
    "Companion staging"
  );
  const packageJson = loadJson(
    path.join(repositoryRoot, "desktop", "package.json"),
    "Desktop package"
  );
  const packageLock = loadJson(
    path.join(repositoryRoot, "desktop", "package-lock.json"),
    "Desktop package lock"
  );
  for (const [name, expected] of Object.entries(EXPECTED_DEPENDENCIES)) {
    validateLockedDependency(packageJson, packageLock, name, expected);
  }
  validateNotices(repositoryRoot);
  const manifest = loadJson(
    path.join(stagingRoot, MANIFEST_NAME),
    "Companion manifest"
  );
  validateManifest(manifest, repositoryRoot, stagingRoot);
  return {
    files: manifest.bundle.files.length,
    imports: manifest.bundle.imports.length
  };
}

module.exports = {
  CompanionAuditError,
  ENTRYPOINT,
  EXPECTED_DEPENDENCIES,
  EXPECTED_KIND,
  FIXED_INPUTS,
  MANIFEST_NAME,
  auditCompanion,
  canonicalJson,
  inputDigests,
  sha256File
};

if (require.main === module) {
  const repositoryRoot = path.resolve(__dirname, "..", "..");
  const stagingRoot = path.join(
    repositoryRoot,
    "desktop",
    "generated",
    "companion"
  );
  try {
    auditCompanion({ repositoryRoot, stagingRoot });
  } catch {
    process.stderr.write("[lcf-mcp-audit] companion-audit-failed\n");
    process.exitCode = 1;
  }
}

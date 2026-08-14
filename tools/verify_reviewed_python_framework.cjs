#!/usr/bin/env node
"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { TextDecoder } = require("node:util");

const EXACT_ROOT = "/Library/Frameworks/Python.framework/Versions/3.13";
const CORE_DIGEST =
  "77b58098a5ebc6890e1335eed3afaa1b9bad96029b7b5ad42e45b270b6649d10";
// The complete production inventory is generated and pinned separately.  These
// constants bind the reviewed shape without embedding thousands of payload
// entries in executable verifier code.
const EXPECTED_INVENTORY_SCHEMA_VERSION = 1;
const EXPECTED_CORE_SOURCE_ENTRY_COUNT = 3654;
const EXPECTED_CORE_SOURCE_INVENTORY_SHA256 =
  "863a6353e58b9c71dc44847051aa582519a66b9347d8c09915ef5254c694bb5d";
const EXPECTED_CORE_ENTRY_COUNT = 3648;
const EXPECTED_CORE_INVENTORY_SHA256 =
  "77b58098a5ebc6890e1335eed3afaa1b9bad96029b7b5ad42e45b270b6649d10";
const EXPECTED_INSTALLER_APPLEDOUBLE_REMOVALS = 6;
const CORE_EXCLUDED_PATHS = Object.freeze([
  "Resources/English.lproj/Documentation",
  "bin/pip",
  "bin/pip3",
  "bin/pip3.13",
  "bin/python",
  "bin/python313",
  "etc/openssl/cert.pem",
  "lib/python3.13/site-packages",
  "share/doc/python3.13/html",
]);
const SITE_PACKAGES_PATH = "lib/python3.13/site-packages";
const ABSENT_PRODUCTION_EXCLUSIONS = Object.freeze(
  CORE_EXCLUDED_PATHS.filter((name) => name !== SITE_PACKAGES_PATH),
);
const SITE_PACKAGES_README = Object.freeze({
  path: `${SITE_PACKAGES_PATH}/README.txt`,
  size: 119,
  sha256: "cba8fece8f62c36306ba27a128f124a257710e41fc619301ee97be93586917cb",
});
const REVIEWED_BROKEN_SYMLINKS = Object.freeze([
  Object.freeze({
    path: "Frameworks/Tcl.framework/PrivateHeaders",
    target: "Versions/Current/PrivateHeaders",
  }),
  Object.freeze({
    path: "Frameworks/Tk.framework/PrivateHeaders",
    target: "Versions/Current/PrivateHeaders",
  }),
]);
const PRODUCER_INSTALL_METHOD = "macos-installer-no-op-framework-component";
const FRAMEWORK_COMPONENT_CONTRACT = Object.freeze({
  packageName: "Python_Framework.pkg",
  bomSize: 1404518,
  bomSha256: "4e49a4c96076a4855219461f721d510493c6d4f3a7a2a9ad7c981ced723d09bd",
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
  noOpPostinstallMode: "0755",
});
const EXPECTED_INVENTORY_CONTRACT = Object.freeze({
  schemaVersion: EXPECTED_INVENTORY_SCHEMA_VERSION,
  payloadSize: FRAMEWORK_COMPONENT_CONTRACT.payloadSize,
  payloadSha256: FRAMEWORK_COMPONENT_CONTRACT.payloadSha256,
  sourceEntryCount: EXPECTED_CORE_SOURCE_ENTRY_COUNT,
  sourceInventorySha256: EXPECTED_CORE_SOURCE_INVENTORY_SHA256,
  installedEntryCount: EXPECTED_CORE_ENTRY_COUNT,
  installedInventorySha256: EXPECTED_CORE_INVENTORY_SHA256,
  appleDoubleRemovals: EXPECTED_INSTALLER_APPLEDOUBLE_REMOVALS,
});
const FRAMEWORK_CORE_INVENTORY_LOCK_CONTRACT = Object.freeze({
  fileName: "python-framework-sealed-inventory.json",
  fileSize: 615969,
  fileSha256:
    "b145fe364990e1f029d2d628c03082b039a29704acdd13a11277d14c7d89a25f",
  schemaVersion: EXPECTED_INVENTORY_SCHEMA_VERSION,
  sourcePayloadSize: FRAMEWORK_COMPONENT_CONTRACT.payloadSize,
  sourcePayloadSha256: FRAMEWORK_COMPONENT_CONTRACT.payloadSha256,
  sourceEntryCount: EXPECTED_CORE_SOURCE_ENTRY_COUNT,
  sourceInventorySha256: EXPECTED_CORE_SOURCE_INVENTORY_SHA256,
  transformationCount: EXPECTED_INSTALLER_APPLEDOUBLE_REMOVALS,
  entryCount: EXPECTED_CORE_ENTRY_COUNT,
  inventorySha256: EXPECTED_CORE_INVENTORY_SHA256,
});

const MAX_LOCK_BYTES = 1024 * 1024;
const MAX_EXPECTED_INVENTORY_BYTES = 16 * 1024 * 1024;
const MAX_TREE_ENTRIES = 100_000;
const MAX_TREE_FILE_BYTES = 256 * 1024 * 1024;
const MAX_TREE_TOTAL_BYTES = 1024 * 1024 * 1024;
const MAX_SYMLINK_EXPANSIONS = 40;
const MAX_RELATIVE_PATH_BYTES = 4096;
const MAX_DIAGNOSTIC_PATH_BYTES = 256;
const MAX_DIAGNOSTIC_DIFFERENCES = 20;
const READ_BUFFER_BYTES = 1024 * 1024;
const UTF8_DECODER = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const MODE_PATTERN = /^[0-7]{4}$/;
const SECRET_LIKE_PATTERN =
  /(?:secret|token|nonce|passw(?:or)?d|credential|authorization|bearer|private[-_. ]?key|api[-_. ]?key|access[-_. ]?key)/iu;

class VerificationError extends Error {
  constructor(message, { cause, diagnostics } = {}) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "VerificationError";
    if (diagnostics !== undefined) {
      Object.defineProperty(this, "diagnostics", {
        configurable: false,
        enumerable: false,
        value: diagnostics,
        writable: false,
      });
    }
  }
}

function fail(message, cause) {
  throw new VerificationError(message, cause === undefined ? undefined : { cause });
}

function failWithDiagnostics(message, diagnostics) {
  throw new VerificationError(message, { diagnostics });
}

function comparePythonStrings(left, right) {
  const leftPoints = Array.from(left, (value) => value.codePointAt(0));
  const rightPoints = Array.from(right, (value) => value.codePointAt(0));
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
    if (leftPoints[index] !== rightPoints[index]) {
      return leftPoints[index] < rightPoints[index] ? -1 : 1;
    }
  }
  if (leftPoints.length === rightPoints.length) {
    return 0;
  }
  return leftPoints.length < rightPoints.length ? -1 : 1;
}

function canonicalJson(value) {
  if (value === null || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) {
      fail("Canonical JSON contains an unsafe number");
    }
    return String(value);
  }
  if (typeof value === "string") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  }
  if (typeof value === "object") {
    const keys = Object.keys(value).sort(comparePythonStrings);
    return `{${keys
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(",")}}`;
  }
  fail("Canonical JSON contains an unsupported value");
}

function canonicalJsonBytes(value) {
  return Buffer.from(canonicalJson(value), "utf8");
}

function decodeUtf8(value, label) {
  try {
    return UTF8_DECODER.decode(value);
  } catch (error) {
    fail(`${label} is not valid UTF-8`, error);
  }
}

function statIdentity(info) {
  return [
    info.dev,
    info.ino,
    info.mode,
    info.nlink,
    info.uid,
    info.gid,
    info.size,
    info.mtimeNs,
    info.ctimeNs,
  ];
}

function sameIdentity(left, right) {
  const leftIdentity = statIdentity(left);
  const rightIdentity = statIdentity(right);
  return leftIdentity.every((value, index) => value === rightIdentity[index]);
}

function lstat(pathname, message) {
  try {
    return fs.lstatSync(pathname, { bigint: true });
  } catch (error) {
    fail(message, error);
  }
}

function modeText(info) {
  return Number(info.mode & 0o7777n).toString(8).padStart(4, "0");
}

function splitSafeRelative(name, label) {
  if (
    typeof name !== "string" ||
    name.length === 0 ||
    Buffer.byteLength(name, "utf8") > MAX_RELATIVE_PATH_BYTES ||
    name.includes("\\") ||
    name.includes("\0") ||
    Array.from(name).some((character) => {
      const point = character.codePointAt(0);
      return point <= 0x1f || point === 0x7f;
    }) ||
    path.posix.isAbsolute(name)
  ) {
    fail(`${label} is unsafe`);
  }
  const parts = name.split("/");
  if (
    parts.some((part) => part === "" || part === "." || part === "..") ||
    parts.join("/") !== name
  ) {
    fail(`${label} is unsafe`);
  }
  return parts;
}

function normalizeExclusions(excludedPaths) {
  if (!Array.isArray(excludedPaths)) {
    fail("Framework fingerprint exclusions are malformed");
  }
  const normalized = excludedPaths.map((name) => ({
    name,
    parts: splitSafeRelative(name, "Framework fingerprint exclusion"),
  }));
  const names = normalized.map((item) => item.name);
  const sorted = [...names].sort(comparePythonStrings);
  if (
    names.length !== new Set(names).size ||
    names.some((name, index) => name !== sorted[index])
  ) {
    fail("Framework fingerprint exclusions are not ordered");
  }
  for (let parentIndex = 0; parentIndex < normalized.length; parentIndex += 1) {
    const parent = normalized[parentIndex].parts;
    for (
      let candidateIndex = parentIndex + 1;
      candidateIndex < normalized.length;
      candidateIndex += 1
    ) {
      const candidate = normalized[candidateIndex].parts;
      if (
        candidate.length >= parent.length &&
        parent.every((part, index) => candidate[index] === part)
      ) {
        fail("Framework fingerprint exclusions overlap");
      }
    }
  }
  return normalized.map((item) => item.parts);
}

function normalizeReviewedBrokenSymlinks(entries) {
  if (!Array.isArray(entries)) {
    fail("Reviewed broken symlinks are malformed");
  }
  const result = new Map();
  for (const entry of entries) {
    if (
      entry === null ||
      typeof entry !== "object" ||
      Array.isArray(entry) ||
      Object.keys(entry).sort().join(",") !== "path,target"
    ) {
      fail("Reviewed broken symlink is malformed");
    }
    splitSafeRelative(entry.path, "Reviewed broken symlink path");
    splitSafeRelative(entry.target, "Reviewed broken symlink target");
    if (result.has(entry.path)) {
      fail("Reviewed broken symlink is duplicated");
    }
    result.set(entry.path, entry.target);
  }
  const names = [...result.keys()];
  const sorted = [...names].sort(comparePythonStrings);
  if (names.some((name, index) => name !== sorted[index])) {
    fail("Reviewed broken symlinks are not ordered");
  }
  return result;
}

function pathIsContained(root, candidate) {
  return candidate === root || candidate.startsWith(`${root}/`);
}

function readLinkStable(pathname, before) {
  let value;
  try {
    value = fs.readlinkSync(pathname, { encoding: "buffer" });
  } catch (error) {
    fail("Framework symlink is unreadable", error);
  }
  const after = lstat(pathname, "Framework symlink changed while being read");
  if (!sameIdentity(before, after)) {
    fail("Framework symlink changed while being read");
  }
  return decodeUtf8(value, "Framework symlink target");
}

function absoluteStack(pathname) {
  if (!path.posix.isAbsolute(pathname)) {
    fail("Framework symlink base is not absolute");
  }
  return pathname
    .split("/")
    .filter((part) => part.length > 0)
    .map((name) => ({ name, known: true }));
}

function stackPath(stack) {
  return stack.length === 0 ? "/" : `/${stack.map((item) => item.name).join("/")}`;
}

function resolveSymlinkTarget(parent, target) {
  const stack = absoluteStack(parent);
  let pending = target.split("/");
  let expansions = 0;
  while (pending.length > 0) {
    const component = pending.shift();
    if (component === "" || component === ".") {
      continue;
    }
    if (component === "..") {
      stack.pop();
      continue;
    }
    if (stack.some((item) => !item.known)) {
      stack.push({ name: component, known: false });
      continue;
    }
    const candidate = path.posix.join(stackPath(stack), component);
    let info;
    try {
      info = fs.lstatSync(candidate, { bigint: true });
    } catch (error) {
      if (error && error.code === "ENOENT") {
        stack.push({ name: component, known: false });
        continue;
      }
      fail("Framework symlink target cannot be resolved", error);
    }
    if (!info.isSymbolicLink()) {
      stack.push({ name: component, known: true });
      continue;
    }
    expansions += 1;
    if (expansions > MAX_SYMLINK_EXPANSIONS) {
      fail("Framework symlink target contains a loop");
    }
    const nested = readLinkStable(candidate, info);
    if (nested.length === 0 || nested.includes("\0")) {
      fail("Framework symlink target is unsafe");
    }
    if (path.posix.isAbsolute(nested)) {
      stack.splice(0, stack.length);
    }
    pending = nested.split("/").concat(pending);
  }
  return {
    path: stackPath(stack),
    exists: stack.every((item) => item.known),
  };
}

function readDirectoryNames(pathname) {
  let rawNames;
  try {
    rawNames = fs.readdirSync(pathname, { encoding: "buffer" });
  } catch (error) {
    fail("Framework directory is unreadable", error);
  }
  const names = rawNames.map((value) => decodeUtf8(value, "Framework entry name"));
  if (
    names.some(
      (name) =>
        name.length === 0 ||
        name === "." ||
        name === ".." ||
        name.includes("/") ||
        name.includes("\0"),
    ) ||
    names.length !== new Set(names).size
  ) {
    fail("Framework directory contains an unsafe entry name");
  }
  names.sort(comparePythonStrings);
  return names;
}

function requiredOpenFlag(name) {
  const value = fs.constants[name];
  if (!Number.isInteger(value) || value === 0) {
    fail(`Required filesystem flag ${name} is unavailable`);
  }
  return value;
}

function openDirectoryNoFollow(pathname, before) {
  const flags =
    fs.constants.O_RDONLY |
    requiredOpenFlag("O_DIRECTORY") |
    requiredOpenFlag("O_NOFOLLOW");
  let descriptor;
  try {
    descriptor = fs.openSync(pathname, flags);
  } catch (error) {
    fail("Framework directory cannot be opened without following links", error);
  }
  const held = fs.fstatSync(descriptor, { bigint: true });
  if (!held.isDirectory() || !sameIdentity(before, held)) {
    fs.closeSync(descriptor);
    fail("Framework directory changed before traversal");
  }
  return descriptor;
}

function hashRegularFile(pathname, before) {
  const flags =
    fs.constants.O_RDONLY |
    requiredOpenFlag("O_NOFOLLOW");
  let descriptor;
  try {
    descriptor = fs.openSync(pathname, flags);
  } catch (error) {
    fail("Framework regular file cannot be opened without following links", error);
  }
  try {
    const heldBefore = fs.fstatSync(descriptor, { bigint: true });
    if (!heldBefore.isFile() || !sameIdentity(before, heldBefore)) {
      fail("Framework regular file changed before hashing");
    }
    if (heldBefore.size > BigInt(MAX_TREE_FILE_BYTES)) {
      fail("Framework regular file exceeds its size bound");
    }
    const digest = crypto.createHash("sha256");
    const buffer = Buffer.allocUnsafe(READ_BUFFER_BYTES);
    let total = 0n;
    for (;;) {
      const count = fs.readSync(descriptor, buffer, 0, buffer.length, null);
      if (count === 0) {
        break;
      }
      digest.update(buffer.subarray(0, count));
      total += BigInt(count);
      if (total > heldBefore.size) {
        fail("Framework regular file grew while hashing");
      }
    }
    const heldAfter = fs.fstatSync(descriptor, { bigint: true });
    const namedAfter = lstat(pathname, "Framework regular file changed while hashing");
    if (
      total !== heldBefore.size ||
      !sameIdentity(heldBefore, heldAfter) ||
      !sameIdentity(heldBefore, namedAfter)
    ) {
      fail("Framework regular file changed while hashing");
    }
    return digest.digest("hex");
  } finally {
    fs.closeSync(descriptor);
  }
}

function isExcluded(relativeParts, exclusions) {
  return exclusions.some(
    (excluded) =>
      relativeParts.length >= excluded.length &&
      excluded.every((part, index) => relativeParts[index] === part),
  );
}

function isForbiddenBytecodeCachePath(relativeParts) {
  const lowered = relativeParts.map((part) => part.toLowerCase());
  const basename = lowered[lowered.length - 1];
  return (
    lowered.includes("__pycache__") ||
    basename.endsWith(".pyc") ||
    basename.endsWith(".pyo")
  );
}

function isPythonFingerprintCachePath(relativeParts) {
  const lowered = relativeParts.map((part) => part.toLowerCase());
  const basename = lowered[lowered.length - 1];
  return (
    lowered.includes("__pycache__") ||
    basename.endsWith(".pyc") ||
    basename.endsWith(".pyo")
  );
}

function isPlainRecord(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function hasExactKeys(value, expectedKeys) {
  if (!isPlainRecord(value)) {
    return false;
  }
  const actual = Object.keys(value).sort(comparePythonStrings);
  const expected = [...expectedKeys].sort(comparePythonStrings);
  return (
    actual.length === expected.length &&
    actual.every((name, index) => name === expected[index])
  );
}

function isSafeSymlinkTarget(target) {
  return (
    typeof target === "string" &&
    target.length > 0 &&
    Buffer.byteLength(target, "utf8") <= MAX_RELATIVE_PATH_BYTES &&
    !target.includes("\0") &&
    !path.posix.isAbsolute(target) &&
    !Array.from(target).some((character) => {
      const point = character.codePointAt(0);
      return point <= 0x1f || point === 0x7f;
    })
  );
}

function digestInventory(inventory) {
  if (!Array.isArray(inventory)) {
    fail("Framework inventory is malformed");
  }
  return crypto
    .createHash("sha256")
    .update(canonicalJsonBytes(inventory))
    .digest("hex");
}

function validateInventoryEntries(entries, label = "Framework inventory") {
  if (
    !Array.isArray(entries) ||
    entries.length === 0 ||
    entries.length > MAX_TREE_ENTRIES
  ) {
    fail(`${label} is malformed`);
  }
  const result = [];
  let previousPath;
  let totalBytes = 0n;
  for (const entry of entries) {
    if (!isPlainRecord(entry)) {
      fail(`${label} entry is malformed`);
    }
    const relativeParts = splitSafeRelative(entry.path, `${label} entry path`);
    if (isForbiddenBytecodeCachePath(relativeParts)) {
      fail(`${label} contains executable bytecode cache`);
    }
    if (
      previousPath !== undefined &&
      comparePythonStrings(previousPath, entry.path) >= 0
    ) {
      fail(`${label} entries are not strictly ordered`);
    }
    previousPath = entry.path;
    if (typeof entry.type !== "string" || !MODE_PATTERN.test(entry.mode)) {
      fail(`${label} entry is malformed`);
    }

    let normalized;
    if (entry.type === "directory") {
      if (!hasExactKeys(entry, ["mode", "path", "type"])) {
        fail(`${label} directory entry is malformed`);
      }
      normalized = {
        path: entry.path,
        mode: entry.mode,
        type: "directory",
      };
    } else if (entry.type === "file") {
      if (
        !hasExactKeys(entry, ["mode", "path", "sha256", "size", "type"]) ||
        !Number.isSafeInteger(entry.size) ||
        entry.size < 0 ||
        entry.size > MAX_TREE_FILE_BYTES ||
        !SHA256_PATTERN.test(entry.sha256)
      ) {
        fail(`${label} regular-file entry is malformed`);
      }
      totalBytes += BigInt(entry.size);
      if (totalBytes > BigInt(MAX_TREE_TOTAL_BYTES)) {
        fail(`${label} exceeds its byte bound`);
      }
      normalized = {
        path: entry.path,
        mode: entry.mode,
        type: "file",
        size: entry.size,
        sha256: entry.sha256,
      };
    } else if (entry.type === "symlink") {
      const hasBroken = Object.hasOwn(entry, "broken");
      const keys = ["mode", "path", "sha256", "target", "type"];
      if (hasBroken) {
        keys.push("broken");
      }
      if (
        !hasExactKeys(entry, keys) ||
        (hasBroken && entry.broken !== true) ||
        !isSafeSymlinkTarget(entry.target) ||
        !SHA256_PATTERN.test(entry.sha256) ||
        entry.sha256 !==
          crypto.createHash("sha256").update(entry.target, "utf8").digest("hex")
      ) {
        fail(`${label} symlink entry is malformed`);
      }
      normalized = {
        path: entry.path,
        mode: entry.mode,
        type: "symlink",
        target: entry.target,
      };
      if (hasBroken) {
        normalized.broken = true;
      }
      normalized.sha256 = entry.sha256;
    } else {
      fail(`${label} entry type is unsupported`);
    }
    result.push(Object.freeze(normalized));
  }
  return Object.freeze(result);
}

function normalizeExpectedTransformations(transformations) {
  if (
    !Array.isArray(transformations) ||
    transformations.length > MAX_TREE_ENTRIES
  ) {
    fail("Expected framework inventory transformations are malformed");
  }
  const result = [];
  let previousPath;
  for (const transformation of transformations) {
    if (!isPlainRecord(transformation)) {
      fail("Expected framework inventory transformation is malformed");
    }
    splitSafeRelative(
      transformation.path,
      "Expected framework inventory transformation path",
    );
    if (
      previousPath !== undefined &&
      comparePythonStrings(previousPath, transformation.path) >= 0
    ) {
      fail("Expected framework inventory transformations are not strictly ordered");
    }
    previousPath = transformation.path;

    if (transformation.kind === "remove-appledouble") {
      if (
        !hasExactKeys(transformation, [
          "kind",
          "mode",
          "path",
          "sha256",
          "size",
          "type",
        ]) ||
        transformation.type !== "file" ||
        transformation.mode !== "0664" ||
        !Number.isSafeInteger(transformation.size) ||
        transformation.size < 0 ||
        transformation.size > MAX_TREE_FILE_BYTES ||
        !SHA256_PATTERN.test(transformation.sha256) ||
        !path.posix.basename(transformation.path).startsWith("._") ||
        path.posix.basename(transformation.path) === "._"
      ) {
        fail("Expected AppleDouble removal transformation is malformed");
      }
      result.push(
        Object.freeze({
          kind: "remove-appledouble",
          path: transformation.path,
          type: "file",
          mode: "0664",
          size: transformation.size,
          sha256: transformation.sha256,
        }),
      );
      continue;
    }

    fail("Expected framework inventory transformation kind is unsupported");
  }
  return Object.freeze(result);
}

function sealedNonSymlinkMode(mode) {
  if (!MODE_PATTERN.test(mode)) {
    fail("Expected non-symlink mode transformation is malformed");
  }
  return (Number.parseInt(mode, 8) & ~0o022).toString(8).padStart(4, "0");
}

function applyNormalizedExpectedInventoryTransformations(
  sourceInventory,
  transformations,
) {
  const byPath = new Map(
    sourceInventory.map((entry) => [entry.path, { ...entry }]),
  );
  for (const transformation of transformations) {
    const entry = byPath.get(transformation.path);
    if (entry === undefined || entry.type !== transformation.type) {
      fail("Expected framework inventory transformation does not match its entry");
    }
    if (transformation.kind === "remove-appledouble") {
      if (
        entry.mode !== sealedNonSymlinkMode(transformation.mode) ||
        entry.size !== transformation.size ||
        entry.sha256 !== transformation.sha256
      ) {
        fail("Expected AppleDouble removal source metadata changed");
      }
      byPath.delete(transformation.path);
      continue;
    }
    fail("Expected framework inventory transformation kind is unsupported");
  }
  const transformed = [...byPath.values()].sort((left, right) =>
    comparePythonStrings(left.path, right.path),
  );
  return validateInventoryEntries(
    transformed,
    "Transformed expected framework inventory",
  );
}

function applyExpectedInventoryTransformations(entries, transformations) {
  return applyNormalizedExpectedInventoryTransformations(
    validateInventoryEntries(entries, "Expected source framework inventory"),
    normalizeExpectedTransformations(transformations),
  );
}

function reconstructSourceInventory(installedInventory, transformations) {
  const byPath = new Map(
    installedInventory.map((entry) => [entry.path, { ...entry }]),
  );
  for (const transformation of transformations) {
    const installed = byPath.get(transformation.path);
    if (transformation.kind === "remove-appledouble") {
      if (installed !== undefined) {
        fail("Expected removed AppleDouble path still exists");
      }
      byPath.set(transformation.path, {
        path: transformation.path,
        mode: sealedNonSymlinkMode(transformation.mode),
        type: "file",
        size: transformation.size,
        sha256: transformation.sha256,
      });
      continue;
    }
    fail("Expected framework inventory transformation kind is unsupported");
  }
  return validateInventoryEntries(
    [...byPath.values()].sort((left, right) =>
      comparePythonStrings(left.path, right.path),
    ),
    "Reconstructed source framework inventory",
  );
}

function validateExpectedInventoryValue(value) {
  if (
    !hasExactKeys(value, [
      "entries",
      "entryCount",
      "inventorySha256",
      "schemaVersion",
      "source",
      "transformations",
    ]) ||
    value.schemaVersion !== EXPECTED_INVENTORY_SCHEMA_VERSION ||
    !hasExactKeys(value.source, [
      "coreEntryCount",
      "coreInventorySha256",
      "payloadSha256",
      "payloadSize",
    ]) ||
    !Number.isSafeInteger(value.source.payloadSize) ||
    value.source.payloadSize <= 0 ||
    value.source.payloadSize > MAX_TREE_FILE_BYTES ||
    !SHA256_PATTERN.test(value.source.payloadSha256) ||
    !Number.isSafeInteger(value.source.coreEntryCount) ||
    value.source.coreEntryCount <= 0 ||
    value.source.coreEntryCount > MAX_TREE_ENTRIES ||
    !SHA256_PATTERN.test(value.source.coreInventorySha256) ||
    !Number.isSafeInteger(value.entryCount) ||
    value.entryCount <= 0 ||
    value.entryCount > MAX_TREE_ENTRIES ||
    !SHA256_PATTERN.test(value.inventorySha256)
  ) {
    fail("Expected framework inventory is malformed");
  }

  const inventory = validateInventoryEntries(
    value.entries,
    "Expected installed framework inventory",
  );
  const inventoryDigest = digestInventory(inventory);
  if (
    value.entryCount !== inventory.length ||
    value.inventorySha256 !== inventoryDigest
  ) {
    fail("Expected installed framework inventory binding changed");
  }
  const transformations = normalizeExpectedTransformations(value.transformations);
  const sourceInventory = reconstructSourceInventory(
    inventory,
    transformations,
  );
  const sourceDigest = digestInventory(sourceInventory);
  if (
    value.source.coreEntryCount !== sourceInventory.length ||
    value.source.coreInventorySha256 !== sourceDigest
  ) {
    fail("Expected source framework inventory binding changed");
  }

  return Object.freeze({
    schemaVersion: value.schemaVersion,
    source: Object.freeze({
      payloadSize: value.source.payloadSize,
      payloadSha256: value.source.payloadSha256,
      coreEntryCount: value.source.coreEntryCount,
      coreInventorySha256: value.source.coreInventorySha256,
    }),
    transformations,
    entryCount: value.entryCount,
    inventorySha256: value.inventorySha256,
    sourceInventory,
    inventory,
  });
}

function verifyExpectedInventoryProductionContract(value) {
  const validated = validateExpectedInventoryValue(value);
  const removalCount = validated.transformations.filter(
    (item) => item.kind === "remove-appledouble",
  ).length;
  if (
    validated.source.payloadSize !== EXPECTED_INVENTORY_CONTRACT.payloadSize ||
    validated.source.payloadSha256 !== EXPECTED_INVENTORY_CONTRACT.payloadSha256 ||
    validated.source.coreEntryCount !== EXPECTED_INVENTORY_CONTRACT.sourceEntryCount ||
    validated.source.coreInventorySha256 !==
      EXPECTED_INVENTORY_CONTRACT.sourceInventorySha256 ||
    validated.entryCount !== EXPECTED_INVENTORY_CONTRACT.installedEntryCount ||
    validated.inventorySha256 !==
      EXPECTED_INVENTORY_CONTRACT.installedInventorySha256 ||
    removalCount !== EXPECTED_INVENTORY_CONTRACT.appleDoubleRemovals
  ) {
    fail("Expected framework inventory differs from the production contract");
  }
  return validated;
}

function inspectInstallRoot(
  root,
  {
    excludedPaths = CORE_EXCLUDED_PATHS,
    reviewedBrokenSymlinks = REVIEWED_BROKEN_SYMLINKS,
    rejectBytecodeCaches = true,
    requireProductionExclusionClosure = false,
  } = {},
) {
  if (typeof root !== "string" || !path.posix.isAbsolute(root) || root.includes("\0")) {
    fail("Framework root is unsafe");
  }
  let canonicalRoot;
  try {
    canonicalRoot = fs.realpathSync.native(root);
  } catch (error) {
    fail("Framework root is unavailable", error);
  }
  if (canonicalRoot !== root) {
    fail("Framework root is not canonical");
  }
  const rootBefore = lstat(root, "Framework root is unavailable");
  if (!rootBefore.isDirectory() || rootBefore.isSymbolicLink()) {
    fail("Framework root must be a real directory");
  }

  const exclusions = normalizeExclusions([...excludedPaths]);
  const reviewedBroken = normalizeReviewedBrokenSymlinks([
    ...reviewedBrokenSymlinks,
  ]);
  const observedBroken = new Map();
  const inventory = [];
  const absentProductionExclusions = new Set(ABSENT_PRODUCTION_EXCLUSIONS);
  const sitePackagesParts = SITE_PACKAGES_PATH.split("/");
  let observedSitePackages = false;
  let observedSitePackagesReadme = false;
  let entryCount = 0;
  let totalBytes = 0n;

  function visitDirectory(directory, relativeParts, before) {
    const descriptor = openDirectoryNoFollow(directory, before);
    try {
      const names = readDirectoryNames(directory);
      if (
        requireProductionExclusionClosure &&
        relativeParts.join("/") === SITE_PACKAGES_PATH &&
        (names.length !== 1 || names[0] !== "README.txt")
      ) {
        fail("Framework site-packages contains an unexpected entry");
      }
      for (const name of names) {
        const childParts = relativeParts.concat(name);
        const relative = childParts.join("/");
        const child = path.posix.join(directory, name);
        const info = lstat(child, "Framework entry changed during traversal");
        entryCount += 1;
        if (entryCount > MAX_TREE_ENTRIES) {
          fail("Framework tree exceeds its entry bound");
        }
        if (
          requireProductionExclusionClosure &&
          absentProductionExclusions.has(relative)
        ) {
          fail("Framework dynamic exclusion unexpectedly exists");
        }
        const insideSitePackages =
          childParts.length > sitePackagesParts.length &&
          sitePackagesParts.every(
            (part, index) => childParts[index] === part,
          );
        if (
          requireProductionExclusionClosure &&
          insideSitePackages &&
          relative !== SITE_PACKAGES_README.path
        ) {
          fail("Framework site-packages contains an unexpected entry");
        }
        const forbiddenCachePath = isForbiddenBytecodeCachePath(childParts);
        if (forbiddenCachePath && rejectBytecodeCaches) {
          fail("Framework tree contains executable bytecode cache");
        }
        const excluded =
          isExcluded(childParts, exclusions) ||
          (!rejectBytecodeCaches && isPythonFingerprintCachePath(childParts));
        const item = { path: relative, mode: modeText(info) };

        if (info.isSymbolicLink()) {
          const target = readLinkStable(child, info);
          if (
            target.length === 0 ||
            target.includes("\0") ||
            path.posix.isAbsolute(target)
          ) {
            fail("Framework tree contains an unsafe symlink");
          }
          const resolved = resolveSymlinkTarget(directory, target);
          if (!pathIsContained(root, resolved.path)) {
            fail("Framework tree contains an escaping symlink");
          }
          if (!resolved.exists) {
            if (reviewedBroken.get(relative) !== target) {
              fail("Framework tree contains an unreviewed broken symlink");
            }
            observedBroken.set(relative, target);
          }
          if (!excluded) {
            item.type = "symlink";
            item.target = target;
            if (!resolved.exists) {
              item.broken = true;
            }
            item.sha256 = crypto
              .createHash("sha256")
              .update(target, "utf8")
              .digest("hex");
            inventory.push(item);
          }
          continue;
        }

        if (info.isDirectory()) {
          if (
            requireProductionExclusionClosure &&
            relative === SITE_PACKAGES_PATH
          ) {
            if (
              info.uid !== 0n ||
              info.gid !== 0n ||
              modeText(info) !== "0755"
            ) {
              fail("Framework site-packages directory metadata changed");
            }
            observedSitePackages = true;
          }
          if (!excluded) {
            item.type = "directory";
            inventory.push(item);
          }
          visitDirectory(child, childParts, info);
          continue;
        }

        if (!info.isFile()) {
          fail("Framework tree contains a special file");
        }
        if (info.size > BigInt(MAX_TREE_FILE_BYTES)) {
          fail("Framework regular file exceeds its size bound");
        }
        totalBytes += info.size;
        if (totalBytes > BigInt(MAX_TREE_TOTAL_BYTES)) {
          fail("Framework tree exceeds its byte bound");
        }
        let reviewedDigest;
        if (
          requireProductionExclusionClosure &&
          relative === SITE_PACKAGES_README.path
        ) {
          if (
            info.uid !== 0n ||
            info.gid !== 0n ||
            modeText(info) !== "0644" ||
            info.nlink !== 1n ||
            info.size !== BigInt(SITE_PACKAGES_README.size)
          ) {
            fail("Framework site-packages README metadata changed");
          }
          reviewedDigest = hashRegularFile(child, info);
          if (reviewedDigest !== SITE_PACKAGES_README.sha256) {
            fail("Framework site-packages README content changed");
          }
          observedSitePackagesReadme = true;
        }
        if (!excluded) {
          item.type = "file";
          item.size = Number(info.size);
          item.sha256 = reviewedDigest ?? hashRegularFile(child, info);
          inventory.push(item);
        }
      }
      const heldAfter = fs.fstatSync(descriptor, { bigint: true });
      const namedAfter = lstat(directory, "Framework directory changed during traversal");
      if (
        !sameIdentity(before, heldAfter) ||
        !sameIdentity(before, namedAfter)
      ) {
        fail("Framework directory changed during traversal");
      }
    } finally {
      fs.closeSync(descriptor);
    }
  }

  visitDirectory(root, [], rootBefore);
  const rootAfter = lstat(root, "Framework root changed during traversal");
  if (!sameIdentity(rootBefore, rootAfter)) {
    fail("Framework root changed during traversal");
  }
  if (
    requireProductionExclusionClosure &&
    (!observedSitePackages || !observedSitePackagesReadme)
  ) {
    fail("Framework site-packages closure is incomplete");
  }
  if (
    observedBroken.size !== reviewedBroken.size ||
    [...reviewedBroken].some(
      ([relative, target]) => observedBroken.get(relative) !== target,
    )
  ) {
    fail("Reviewed framework broken symlink set changed");
  }
  if (inventory.length === 0) {
    fail("Framework fingerprint is empty");
  }
  inventory.sort((left, right) => comparePythonStrings(left.path, right.path));
  const reviewedInventory = validateInventoryEntries(
    inventory,
    "Observed framework inventory",
  );
  return Object.freeze({
    inventory: reviewedInventory,
    digest: digestInventory(reviewedInventory),
  });
}

function fingerprintInstallRoot(root, options = {}) {
  return inspectInstallRoot(root, options).digest;
}

function inspectProductionExclusionClosure(
  root,
  { reviewedBrokenSymlinks = REVIEWED_BROKEN_SYMLINKS } = {},
) {
  return inspectInstallRoot(root, {
    excludedPaths: CORE_EXCLUDED_PATHS,
    reviewedBrokenSymlinks,
    rejectBytecodeCaches: true,
    requireProductionExclusionClosure: true,
  });
}

function verifyProductionExclusionClosure(
  root,
  { reviewedBrokenSymlinks = REVIEWED_BROKEN_SYMLINKS } = {},
) {
  return inspectProductionExclusionClosure(root, { reviewedBrokenSymlinks }).digest;
}

function diagnosticPathRecord(relative, untrusted) {
  if (
    untrusted ||
    Buffer.byteLength(relative, "utf8") > MAX_DIAGNOSTIC_PATH_BYTES ||
    SECRET_LIKE_PATTERN.test(relative)
  ) {
    return Object.freeze({
      pathSha256: crypto.createHash("sha256").update(relative, "utf8").digest("hex"),
    });
  }
  return Object.freeze({ path: relative });
}

function compareInventories(
  expectedEntries,
  observedEntries,
  { limit = MAX_DIAGNOSTIC_DIFFERENCES } = {},
) {
  if (
    !Number.isSafeInteger(limit) ||
    limit < 0 ||
    limit > MAX_DIAGNOSTIC_DIFFERENCES
  ) {
    fail("Framework inventory diagnostic bound is unsafe");
  }
  const expected = validateInventoryEntries(
    expectedEntries,
    "Expected installed framework inventory",
  );
  const observed = validateInventoryEntries(
    observedEntries,
    "Observed framework inventory",
  );
  const differenceCounts = {
    missing: 0,
    extra: 0,
    type: 0,
    mode: 0,
    target: 0,
    size: 0,
    content: 0,
  };
  const firstDifferences = [];

  function record(kind, relative, untrusted = false) {
    differenceCounts[kind] += 1;
    if (firstDifferences.length < limit) {
      firstDifferences.push(
        Object.freeze({
          kind,
          ...diagnosticPathRecord(relative, untrusted),
        }),
      );
    }
  }

  let expectedIndex = 0;
  let observedIndex = 0;
  while (expectedIndex < expected.length || observedIndex < observed.length) {
    if (expectedIndex >= expected.length) {
      record("extra", observed[observedIndex].path, true);
      observedIndex += 1;
      continue;
    }
    if (observedIndex >= observed.length) {
      record("missing", expected[expectedIndex].path);
      expectedIndex += 1;
      continue;
    }
    const expectedEntry = expected[expectedIndex];
    const observedEntry = observed[observedIndex];
    const order = comparePythonStrings(expectedEntry.path, observedEntry.path);
    if (order < 0) {
      record("missing", expectedEntry.path);
      expectedIndex += 1;
      continue;
    }
    if (order > 0) {
      record("extra", observedEntry.path, true);
      observedIndex += 1;
      continue;
    }

    if (expectedEntry.type !== observedEntry.type) {
      record("type", expectedEntry.path);
    } else {
      if (expectedEntry.mode !== observedEntry.mode) {
        record("mode", expectedEntry.path);
      }
      if (expectedEntry.type === "file") {
        if (expectedEntry.size !== observedEntry.size) {
          record("size", expectedEntry.path);
        }
        if (expectedEntry.sha256 !== observedEntry.sha256) {
          record("content", expectedEntry.path);
        }
      } else if (
        expectedEntry.type === "symlink" &&
        (expectedEntry.target !== observedEntry.target ||
          expectedEntry.broken !== observedEntry.broken)
      ) {
        record("target", expectedEntry.path);
      }
    }
    expectedIndex += 1;
    observedIndex += 1;
  }

  const differenceTotal = Object.values(differenceCounts).reduce(
    (total, value) => total + value,
    0,
  );
  return Object.freeze({
    matches: differenceTotal === 0,
    expectedDigest: digestInventory(expected),
    observedDigest: digestInventory(observed),
    expectedEntries: expected.length,
    observedEntries: observed.length,
    differenceCounts: Object.freeze(differenceCounts),
    firstDifferences: Object.freeze(firstDifferences),
    truncated: differenceTotal > firstDifferences.length,
  });
}

function formatVerificationDiagnostics(diagnostics) {
  if (
    !isPlainRecord(diagnostics) ||
    !SHA256_PATTERN.test(diagnostics.expectedDigest) ||
    !SHA256_PATTERN.test(diagnostics.observedDigest) ||
    !Number.isSafeInteger(diagnostics.expectedEntries) ||
    !Number.isSafeInteger(diagnostics.observedEntries) ||
    !hasExactKeys(diagnostics.differenceCounts, [
      "content",
      "extra",
      "missing",
      "mode",
      "size",
      "target",
      "type",
    ]) ||
    Object.values(diagnostics.differenceCounts).some(
      (value) => !Number.isSafeInteger(value) || value < 0,
    ) ||
    !Array.isArray(diagnostics.firstDifferences) ||
    diagnostics.firstDifferences.length > MAX_DIAGNOSTIC_DIFFERENCES ||
    typeof diagnostics.truncated !== "boolean"
  ) {
    fail("Framework inventory diagnostics are malformed");
  }
  for (const difference of diagnostics.firstDifferences) {
    if (
      !isPlainRecord(difference) ||
      ![
        "missing",
        "extra",
        "type",
        "mode",
        "target",
        "size",
        "content",
      ].includes(difference.kind) ||
      (!hasExactKeys(difference, ["kind", "path"]) &&
        !hasExactKeys(difference, ["kind", "pathSha256"])) ||
      (Object.hasOwn(difference, "path") ===
        Object.hasOwn(difference, "pathSha256"))
    ) {
      fail("Framework inventory diagnostic record is malformed");
    }
    if (Object.hasOwn(difference, "path")) {
      splitSafeRelative(difference.path, "Framework inventory diagnostic path");
      if (
        SECRET_LIKE_PATTERN.test(difference.path) ||
        Buffer.byteLength(difference.path, "utf8") > MAX_DIAGNOSTIC_PATH_BYTES
      ) {
        fail("Framework inventory diagnostic path is unsafe");
      }
    } else if (!SHA256_PATTERN.test(difference.pathSha256)) {
      fail("Framework inventory diagnostic path digest is malformed");
    }
  }
  const counts = diagnostics.differenceCounts;
  return [
    `expected_digest=${diagnostics.expectedDigest}`,
    `observed_digest=${diagnostics.observedDigest}`,
    `expected_entries=${diagnostics.expectedEntries}`,
    `observed_entries=${diagnostics.observedEntries}`,
    "difference_counts=" +
      `missing:${counts.missing},extra:${counts.extra},type:${counts.type},` +
      `mode:${counts.mode},target:${counts.target},size:${counts.size},` +
      `content:${counts.content}`,
    `first_differences=${canonicalJson(diagnostics.firstDifferences)}`,
    `truncated=${diagnostics.truncated ? "true" : "false"}`,
  ].join("\n");
}

function verifyInventoryMatch(expectedEntries, observedEntries) {
  const diagnostics = compareInventories(expectedEntries, observedEntries);
  if (!diagnostics.matches) {
    failWithDiagnostics(
      "Reviewed Python framework core inventory changed",
      diagnostics,
    );
  }
  return diagnostics.observedDigest;
}

function readBoundedJsonFile(pathname, { label, maximumBytes }) {
  if (
    typeof pathname !== "string" ||
    pathname.length === 0 ||
    pathname.includes("\0")
  ) {
    fail(`${label} path is unsafe`);
  }
  const resolved = path.resolve(pathname);
  const before = lstat(resolved, `${label} is unavailable`);
  if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1n) {
    fail(`${label} must be one regular file`);
  }
  if (before.size <= 0n || before.size > BigInt(maximumBytes)) {
    fail(`${label} has an unsafe size`);
  }
  const flags =
    fs.constants.O_RDONLY |
    requiredOpenFlag("O_NOFOLLOW");
  let descriptor;
  try {
    descriptor = fs.openSync(resolved, flags);
  } catch (error) {
    fail(`${label} cannot be opened without following links`, error);
  }
  try {
    const heldBefore = fs.fstatSync(descriptor, { bigint: true });
    if (!heldBefore.isFile() || !sameIdentity(before, heldBefore)) {
      fail(`${label} changed before reading`);
    }
    const content = Buffer.alloc(Number(heldBefore.size));
    let offset = 0;
    while (offset < content.length) {
      const count = fs.readSync(
        descriptor,
        content,
        offset,
        content.length - offset,
        null,
      );
      if (count === 0) {
        fail(`${label} was truncated while reading`);
      }
      offset += count;
    }
    const heldAfter = fs.fstatSync(descriptor, { bigint: true });
    const namedAfter = lstat(resolved, `${label} changed while reading`);
    if (!sameIdentity(heldBefore, heldAfter) || !sameIdentity(heldBefore, namedAfter)) {
      fail(`${label} changed while reading`);
    }
    let value;
    try {
      value = JSON.parse(decodeUtf8(content, label));
    } catch (error) {
      if (error instanceof VerificationError) {
        throw error;
      }
      fail(`${label} is invalid JSON`, error);
    }
    return value;
  } finally {
    fs.closeSync(descriptor);
  }
}

function readLockFile(lockPath) {
  return readBoundedJsonFile(lockPath, {
    label: "Reviewed Python lock",
    maximumBytes: MAX_LOCK_BYTES,
  });
}

function readExpectedInventoryFile(inventoryPath) {
  const value = readBoundedJsonFile(inventoryPath, {
    label: "Expected framework inventory",
    maximumBytes: MAX_EXPECTED_INVENTORY_BYTES,
  });
  validateExpectedInventoryValue(value);
  return value;
}

function sameJson(left, right) {
  return canonicalJson(left) === canonicalJson(right);
}

function verifyLockValue(lock) {
  const python = lock && typeof lock === "object" ? lock.python : undefined;
  const distribution =
    python !== null && typeof python === "object"
      ? python.distribution
      : undefined;
  if (
    python === null ||
    typeof python !== "object" ||
    python.installRoot !== EXACT_ROOT ||
    python.frameworkCoreFingerprintSha256 !== CORE_DIGEST ||
    !sameJson(python.frameworkCoreFingerprintExcludedPaths, CORE_EXCLUDED_PATHS) ||
    !sameJson(
      python.frameworkCoreInventory,
      FRAMEWORK_CORE_INVENTORY_LOCK_CONTRACT,
    ) ||
    !sameJson(python.reviewedBrokenSymlinks, REVIEWED_BROKEN_SYMLINKS) ||
    distribution === null ||
    typeof distribution !== "object" ||
    distribution.installMethod !== PRODUCER_INSTALL_METHOD ||
    !sameJson(distribution.frameworkComponent, FRAMEWORK_COMPONENT_CONTRACT)
  ) {
    fail("Reviewed Python lock differs from the hard-coded framework contract");
  }
  return lock;
}

function verifyLockContract(lockPath) {
  return verifyLockValue(readLockFile(lockPath));
}

function parseCliArguments(argv) {
  const usage =
    "Usage: verify_reviewed_python_framework.cjs --root PATH --lock PATH --inventory PATH";
  if (!Array.isArray(argv) || argv.length !== 6) {
    fail(usage);
  }
  const result = Object.create(null);
  for (let index = 0; index < argv.length; index += 2) {
    const option = argv[index];
    const value = argv[index + 1];
    if (
      (option !== "--root" &&
        option !== "--lock" &&
        option !== "--inventory") ||
      Object.hasOwn(result, option) ||
      typeof value !== "string" ||
      value.length === 0 ||
      value.startsWith("--")
    ) {
      fail(usage);
    }
    result[option] = value;
  }
  if (
    !Object.hasOwn(result, "--root") ||
    !Object.hasOwn(result, "--lock") ||
    !Object.hasOwn(result, "--inventory")
  ) {
    fail(usage);
  }
  return {
    root: result["--root"],
    lock: result["--lock"],
    inventory: result["--inventory"],
  };
}

function verifyStartupEnvironment(environment) {
  if (
    (environment.NODE_OPTIONS !== undefined && environment.NODE_OPTIONS !== "") ||
    (environment.NODE_PATH !== undefined && environment.NODE_PATH !== "")
  ) {
    fail("Node verifier must be started without NODE_OPTIONS or NODE_PATH");
  }
}

function verifyReviewedPythonFramework(options) {
  if (
    options === null ||
    typeof options !== "object" ||
    Array.isArray(options) ||
    !Object.hasOwn(options, "root")
  ) {
    fail("Reviewed Python framework verification arguments are malformed");
  }
  const hasLockPath = Object.hasOwn(options, "lock");
  const hasLockValue = Object.hasOwn(options, "lockValue");
  if (hasLockPath === hasLockValue) {
    fail("Provide exactly one of lock or lockValue");
  }
  const hasInventoryPath = Object.hasOwn(options, "inventory");
  const hasInventoryValue = Object.hasOwn(options, "inventoryValue");
  if (hasInventoryPath === hasInventoryValue) {
    fail("Provide exactly one of inventory or inventoryValue");
  }
  const allowedKeys = new Set([
    "root",
    hasLockPath ? "lock" : "lockValue",
  ]);
  allowedKeys.add(hasInventoryPath ? "inventory" : "inventoryValue");
  if (Object.keys(options).some((name) => !allowedKeys.has(name))) {
    fail("Reviewed Python framework verification arguments are malformed");
  }
  const { root } = options;
  if (root !== EXACT_ROOT) {
    fail("Reviewed Python framework root differs from the hard-coded path");
  }
  const lockValue = hasLockPath
    ? verifyLockContract(options.lock)
    : verifyLockValue(options.lockValue);
  const inventoryValue = hasInventoryPath
    ? readExpectedInventoryFile(options.inventory)
    : options.inventoryValue;
  const expected = verifyExpectedInventoryProductionContract(inventoryValue);
  if (
    lockValue.python.frameworkCoreFingerprintSha256 !==
    expected.inventorySha256
  ) {
    fail("Reviewed Python lock and expected framework inventory disagree");
  }
  const observed = inspectProductionExclusionClosure(root);
  const digest = verifyInventoryMatch(expected.inventory, observed.inventory);
  if (digest !== observed.digest || digest !== CORE_DIGEST) {
    fail("Reviewed Python framework inventory digest changed");
  }
  return digest;
}

function main() {
  try {
    verifyStartupEnvironment(process.env);
    const argumentsValue = parseCliArguments(process.argv.slice(2));
    const digest = verifyReviewedPythonFramework(argumentsValue);
    process.stdout.write(`${digest}\n`);
  } catch (error) {
    process.stderr.write("Reviewed Python framework verification failed\n");
    if (error instanceof VerificationError && error.diagnostics !== undefined) {
      try {
        process.stderr.write(`${formatVerificationDiagnostics(error.diagnostics)}\n`);
      } catch (_diagnosticError) {
        // Never expose an unexpected error, cause, path, or stack while handling
        // a verification failure.
      }
    }
    process.exitCode = 1;
  }
}

module.exports = Object.freeze({
  ABSENT_PRODUCTION_EXCLUSIONS,
  CORE_DIGEST,
  CORE_EXCLUDED_PATHS,
  EXACT_ROOT,
  EXPECTED_CORE_ENTRY_COUNT,
  EXPECTED_CORE_INVENTORY_SHA256,
  EXPECTED_CORE_SOURCE_ENTRY_COUNT,
  EXPECTED_CORE_SOURCE_INVENTORY_SHA256,
  EXPECTED_INSTALLER_APPLEDOUBLE_REMOVALS,
  EXPECTED_INVENTORY_CONTRACT,
  EXPECTED_INVENTORY_SCHEMA_VERSION,
  FRAMEWORK_COMPONENT_CONTRACT,
  FRAMEWORK_CORE_INVENTORY_LOCK_CONTRACT,
  MAX_DIAGNOSTIC_DIFFERENCES,
  PRODUCER_INSTALL_METHOD,
  REVIEWED_BROKEN_SYMLINKS,
  SITE_PACKAGES_PATH,
  SITE_PACKAGES_README,
  VerificationError,
  applyExpectedInventoryTransformations,
  canonicalJsonBytes,
  compareInventories,
  comparePythonStrings,
  digestInventory,
  fingerprintInstallRoot,
  formatVerificationDiagnostics,
  inspectInstallRoot,
  inspectProductionExclusionClosure,
  parseCliArguments,
  readExpectedInventoryFile,
  sealedNonSymlinkMode,
  validateExpectedInventoryValue,
  validateInventoryEntries,
  verifyExpectedInventoryProductionContract,
  verifyInventoryMatch,
  verifyLockContract,
  verifyLockValue,
  verifyProductionExclusionClosure,
  verifyReviewedPythonFramework,
  verifyStartupEnvironment,
});

if (require.main === module) {
  main();
}

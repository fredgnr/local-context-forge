#!/usr/bin/env node
"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { TextDecoder } = require("node:util");

const EXACT_ROOT = "/Library/Frameworks/Python.framework/Versions/3.13";
const CORE_DIGEST =
  "ba58cfb559f29c34beb962cb5d88587e9104f5610c255a58494c2945c1e863ec";
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

const MAX_LOCK_BYTES = 1024 * 1024;
const MAX_TREE_ENTRIES = 100_000;
const MAX_TREE_FILE_BYTES = 256 * 1024 * 1024;
const MAX_TREE_TOTAL_BYTES = 1024 * 1024 * 1024;
const MAX_SYMLINK_EXPANSIONS = 40;
const READ_BUFFER_BYTES = 1024 * 1024;
const UTF8_DECODER = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });

class VerificationError extends Error {
  constructor(message, options) {
    super(message, options);
    this.name = "VerificationError";
  }
}

function fail(message, cause) {
  throw new VerificationError(message, cause === undefined ? undefined : { cause });
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
    name.includes("\\") ||
    name.includes("\0") ||
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

function fingerprintInstallRoot(
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
  return crypto.createHash("sha256").update(canonicalJsonBytes(inventory)).digest("hex");
}

function verifyProductionExclusionClosure(
  root,
  { reviewedBrokenSymlinks = REVIEWED_BROKEN_SYMLINKS } = {},
) {
  return fingerprintInstallRoot(root, {
    excludedPaths: CORE_EXCLUDED_PATHS,
    reviewedBrokenSymlinks,
    rejectBytecodeCaches: true,
    requireProductionExclusionClosure: true,
  });
}

function readLockFile(lockPath) {
  if (typeof lockPath !== "string" || lockPath.length === 0 || lockPath.includes("\0")) {
    fail("Reviewed Python lock path is unsafe");
  }
  const resolved = path.resolve(lockPath);
  const before = lstat(resolved, "Reviewed Python lock is unavailable");
  if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1n) {
    fail("Reviewed Python lock must be one regular file");
  }
  if (before.size <= 0n || before.size > BigInt(MAX_LOCK_BYTES)) {
    fail("Reviewed Python lock has an unsafe size");
  }
  const flags =
    fs.constants.O_RDONLY |
    requiredOpenFlag("O_NOFOLLOW");
  let descriptor;
  try {
    descriptor = fs.openSync(resolved, flags);
  } catch (error) {
    fail("Reviewed Python lock cannot be opened without following links", error);
  }
  try {
    const heldBefore = fs.fstatSync(descriptor, { bigint: true });
    if (!heldBefore.isFile() || !sameIdentity(before, heldBefore)) {
      fail("Reviewed Python lock changed before reading");
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
        fail("Reviewed Python lock was truncated while reading");
      }
      offset += count;
    }
    const heldAfter = fs.fstatSync(descriptor, { bigint: true });
    const namedAfter = lstat(resolved, "Reviewed Python lock changed while reading");
    if (!sameIdentity(heldBefore, heldAfter) || !sameIdentity(heldBefore, namedAfter)) {
      fail("Reviewed Python lock changed while reading");
    }
    let value;
    try {
      value = JSON.parse(decodeUtf8(content, "Reviewed Python lock"));
    } catch (error) {
      if (error instanceof VerificationError) {
        throw error;
      }
      fail("Reviewed Python lock is invalid JSON", error);
    }
    return value;
  } finally {
    fs.closeSync(descriptor);
  }
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
  if (!Array.isArray(argv) || argv.length !== 4) {
    fail("Usage: verify_reviewed_python_framework.cjs --root PATH --lock PATH");
  }
  const result = Object.create(null);
  for (let index = 0; index < argv.length; index += 2) {
    const option = argv[index];
    const value = argv[index + 1];
    if (
      (option !== "--root" && option !== "--lock") ||
      Object.hasOwn(result, option) ||
      typeof value !== "string" ||
      value.length === 0 ||
      value.startsWith("--")
    ) {
      fail("Usage: verify_reviewed_python_framework.cjs --root PATH --lock PATH");
    }
    result[option] = value;
  }
  if (!Object.hasOwn(result, "--root") || !Object.hasOwn(result, "--lock")) {
    fail("Usage: verify_reviewed_python_framework.cjs --root PATH --lock PATH");
  }
  return { root: result["--root"], lock: result["--lock"] };
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
  const allowedKeys = new Set([
    "root",
    hasLockPath ? "lock" : "lockValue",
  ]);
  if (Object.keys(options).some((name) => !allowedKeys.has(name))) {
    fail("Reviewed Python framework verification arguments are malformed");
  }
  const { root } = options;
  if (root !== EXACT_ROOT) {
    fail("Reviewed Python framework root differs from the hard-coded path");
  }
  if (hasLockPath) {
    verifyLockContract(options.lock);
  } else {
    verifyLockValue(options.lockValue);
  }
  const observed = verifyProductionExclusionClosure(root);
  if (observed !== CORE_DIGEST) {
    fail("Reviewed Python framework core fingerprint changed");
  }
  return observed;
}

function main() {
  try {
    verifyStartupEnvironment(process.env);
    const argumentsValue = parseCliArguments(process.argv.slice(2));
    const digest = verifyReviewedPythonFramework(argumentsValue);
    process.stdout.write(`${digest}\n`);
  } catch (error) {
    process.stderr.write("Reviewed Python framework verification failed\n");
    process.exitCode = 1;
  }
}

module.exports = Object.freeze({
  ABSENT_PRODUCTION_EXCLUSIONS,
  CORE_DIGEST,
  CORE_EXCLUDED_PATHS,
  EXACT_ROOT,
  FRAMEWORK_COMPONENT_CONTRACT,
  PRODUCER_INSTALL_METHOD,
  REVIEWED_BROKEN_SYMLINKS,
  SITE_PACKAGES_PATH,
  SITE_PACKAGES_README,
  VerificationError,
  canonicalJsonBytes,
  fingerprintInstallRoot,
  parseCliArguments,
  verifyLockContract,
  verifyLockValue,
  verifyProductionExclusionClosure,
  verifyReviewedPythonFramework,
  verifyStartupEnvironment,
});

if (require.main === module) {
  main();
}

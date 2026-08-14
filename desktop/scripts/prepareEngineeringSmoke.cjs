"use strict";

const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { auditRenderer } = require("./auditRenderer.cjs");
const { auditPythonSidecar } = require("./beforePack.cjs");
const {
  APP_ID,
  COMMIT_PATTERN,
  MANIFEST_KIND,
  MANIFEST_RELATIVE_PATH,
  MANIFEST_SCHEMA_NAME,
  PRODUCT_NAME,
  REPOSITORY,
  canonicalJson,
  fail,
  isContained,
  loadJson,
  requireRealDirectory,
  requireRegularFile,
  sha256Bytes,
  sha256File,
  validateEngineeringSmokeManifest,
  writeCanonicalJson
} = require("./packagingAuditCommon.cjs");

const REPOSITORY_ROOT = path.resolve(__dirname, "..", "..");
const DESKTOP_ROOT = path.join(REPOSITORY_ROOT, "desktop");
const ENGINEERING_ROOT = path.join(
  DESKTOP_ROOT,
  "generated",
  "engineering-smoke"
);
const BUILD_ROOT = path.join(ENGINEERING_ROOT, "build");
const BUILD_MAIN = path.join(BUILD_ROOT, "dist", "main", "index.js");
const BUILD_PRELOAD = path.join(
  BUILD_ROOT,
  "dist",
  "preload",
  "index.cjs"
);
const BUILD_ATTESTATION = path.join(BUILD_ROOT, "entrypoint-build.json");
const APP_STAGING_ROOT = path.join(ENGINEERING_ROOT, "app");
const DISTRIBUTION_MANIFEST = path.join(
  ENGINEERING_ROOT,
  "distribution.json"
);
const MAX_SOURCE_SNAPSHOT_FILES = 100_000;
const MAX_SOURCE_SNAPSHOT_BYTES = 512 * 1024 * 1024;
const RENDERER_ROOT = path.join(DESKTOP_ROOT, "resources", "renderer");
const SIDECAR_ROOT = path.join(DESKTOP_ROOT, "generated", "sidecar");
const SCHEMA_PATH = path.join(
  REPOSITORY_ROOT,
  "runtime",
  MANIFEST_SCHEMA_NAME
);
const DESKTOP_PACKAGE_PATH = "desktop/package.json";
const RENDERER_PACKAGE_LOCK_PATH = "web/package-lock.json";
const MAX_ENTRYPOINT_ATTESTATION_BYTES = 16 * 1024 * 1024;
const MAX_ENTRYPOINT_OUTPUT_BYTES = 256 * 1024 * 1024;
const ENTRYPOINT_OUTPUTS = Object.freeze([
  Object.freeze({ key: "main", path: "dist/main/index.js" }),
  Object.freeze({ key: "preload", path: "dist/preload/index.cjs" })
]);
const FORBIDDEN_PRODUCTION_ENVIRONMENT = Object.freeze([
  "APPLE_API_ISSUER",
  "APPLE_API_KEY",
  "APPLE_API_KEY_ID",
  "APPLE_APP_SPECIFIC_PASSWORD",
  "APPLE_ID",
  "APPLE_TEAM_ID",
  "APPLE_KEYCHAIN_PROFILE",
  "APPLE_NOTARIZATION_PASSWORD",
  "APPLE_NOTARIZE",
  "APPVEYOR_BUILD_NUMBER",
  "BUILD_BUILDNUMBER",
  "BUILD_NUMBER",
  "CIRCLE_BUILD_NUM",
  "CSC_IDENTITY",
  "CSC_IDENTITY_AUTO_DISCOVERY",
  "CSC_KEYCHAIN",
  "CSC_KEY_PASSWORD",
  "CSC_LINK",
  "CSC_NAME",
  "DESKTOP_RELEASE_CREDENTIAL_BUNDLE_BASE64",
  "GH_TOKEN",
  "GITHUB_TOKEN",
  "LCF_CODESIGN_CERTIFICATE_P12",
  "LCF_CODESIGN_CERTIFICATE_PASSWORD",
  "LCF_FORMAL_RELEASE",
  "LCF_UPDATE_METADATA_PRIVATE_KEY",
  "NPM_TOKEN",
  "TRAVIS_BUILD_NUMBER",
  "CI_PIPELINE_IID"
]);
const EXACT_LOCAL_GIT_CONFIG_VALUES = Object.freeze({
  "core.bare": Object.freeze(["false"]),
  "core.filemode": Object.freeze(["false", "true"]),
  "core.ignorecase": Object.freeze(["false", "true"]),
  "core.logallrefupdates": Object.freeze(["true"]),
  "core.precomposeunicode": Object.freeze(["false", "true"]),
  "core.repositoryformatversion": Object.freeze(["0"]),
  "core.symlinks": Object.freeze(["false", "true"]),
  "extensions.objectformat": Object.freeze(["sha1"]),
  "gc.auto": Object.freeze(["0"])
});
const CANONICAL_REPOSITORY_URL =
  `https://github.com/${REPOSITORY}.git`;

function isSafeGitBranchName(value) {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= 1024 &&
    /^[A-Za-z0-9][A-Za-z0-9._\/-]*$/.test(value) &&
    !value.includes("..") &&
    !value.includes("@{") &&
    !value.includes("//") &&
    !value.endsWith("/") &&
    !value.endsWith(".") &&
    !value.endsWith(".lock") &&
    !value.split("/").some((part) => part.startsWith(".") || part.endsWith("."))
  );
}

function isSafeLocalGitConfiguration(name, value) {
  const normalized = name.toLowerCase();
  const reviewedValues = EXACT_LOCAL_GIT_CONFIG_VALUES[normalized];
  if (reviewedValues !== undefined) {
    return reviewedValues.includes(value.toLowerCase());
  }
  if (normalized === "remote.origin.url") {
    return value === CANONICAL_REPOSITORY_URL;
  }
  if (normalized === "remote.origin.fetch") {
    if (value === "+refs/heads/*:refs/remotes/origin/*") {
      return true;
    }
    const match = /^\+refs\/heads\/(.+):refs\/remotes\/origin\/(.+)$/.exec(
      value
    );
    return (
      match !== null &&
      match[1] === match[2] &&
      isSafeGitBranchName(match[1])
    );
  }
  const branch = /^branch\.(.+)\.(remote|merge)$/.exec(normalized);
  if (branch === null || !isSafeGitBranchName(branch[1])) {
    return false;
  }
  if (branch[2] === "remote") {
    return value === "origin";
  }
  return value === `refs/heads/${branch[1]}`;
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

function requireSafeGitControlFile(candidate, label, { commentsOnly = false } = {}) {
  let info;
  let bytes;
  try {
    info = fs.lstatSync(candidate);
    bytes = fs.readFileSync(candidate);
  } catch {
    fail(`${label} is unsafe`);
  }
  if (
    !info.isFile() ||
    info.isSymbolicLink() ||
    info.uid !== process.geteuid() ||
    info.nlink !== 1 ||
    (info.mode & 0o022) !== 0 ||
    bytes.length > 4 * 1024 * 1024 ||
    !Buffer.from(bytes.toString("utf8"), "utf8").equals(bytes)
  ) {
    fail(`${label} is unsafe`);
  }
  if (
    commentsOnly &&
    bytes
      .toString("utf8")
      .split(/\r?\n/)
      .some((line) => line.trim().length > 0 && !line.trimStart().startsWith("#"))
  ) {
    fail(`${label} contains unreviewed semantics`);
  }
  return bytes;
}

function assertSafeLocalGitMetadata(repositoryRoot) {
  const gitDirectory = path.join(repositoryRoot, ".git");
  const configPath = path.join(gitDirectory, "config");
  requireSafeGitControlFile(configPath, "Local Git config");
  let rawConfiguration;
  try {
    rawConfiguration = childProcess.execFileSync(
      "/usr/bin/git",
      [
        "config",
        "--file",
        configPath,
        "--no-includes",
        "--null",
        "--list"
      ],
      {
        env: {
          PATH: "/usr/bin:/bin",
          LANG: "C",
          LC_ALL: "C",
          GIT_CONFIG_NOSYSTEM: "1",
          GIT_CONFIG_GLOBAL: "/dev/null",
          GIT_TERMINAL_PROMPT: "0"
        },
        cwd: repositoryRoot,
        stdio: ["ignore", "pipe", "pipe"],
        timeout: 30_000,
        maxBuffer: 4 * 1024 * 1024
      }
    );
  } catch {
    fail("Local Git config is unsafe");
  }
  const configurationText = rawConfiguration.toString("utf8");
  if (!Buffer.from(configurationText, "utf8").equals(rawConfiguration)) {
    fail("Local Git config is unsafe");
  }
  for (const entry of configurationText.split("\0").filter(Boolean)) {
    const separator = entry.indexOf("\n");
    if (separator <= 0) {
      fail("Local Git config is unsafe");
    }
    const name = entry.slice(0, separator);
    const value = entry.slice(separator + 1);
    const normalized = name.toLowerCase();
    if (
      !/^[^\x00-\x20=]+\.[^\x00-\x20=]+$/.test(normalized) ||
      !isSafeLocalGitConfiguration(normalized, value)
    ) {
      fail("Local Git config contains an unsafe key");
    }
  }
  for (const relative of ["info/attributes", "info/exclude"]) {
    const candidate = path.join(gitDirectory, ...relative.split("/"));
    if (fs.existsSync(candidate)) {
      requireSafeGitControlFile(candidate, `Local Git ${relative}`, {
        commentsOnly: true
      });
    }
  }
  for (const relative of [
    "info/grafts",
    "objects/info/alternates",
    "objects/info/http-alternates"
  ]) {
    const candidate = path.join(gitDirectory, ...relative.split("/"));
    if (fs.existsSync(candidate)) {
      const bytes = requireSafeGitControlFile(
        candidate,
        `Local Git ${relative}`,
        { commentsOnly: true }
      );
      if (bytes.toString("utf8").split(/\r?\n/).some((line) => line.trim())) {
        fail(`Local Git ${relative} contains unreviewed semantics`);
      }
    }
  }
}

function isolatedGitArguments(arguments_, repositoryRoot) {
  const gitDirectory = path.join(repositoryRoot, ".git");
  try {
    const rootInfo = fs.lstatSync(repositoryRoot);
    const gitInfo = fs.lstatSync(gitDirectory);
    if (
      !path.isAbsolute(repositoryRoot) ||
      fs.realpathSync.native(repositoryRoot) !== repositoryRoot ||
      !rootInfo.isDirectory() ||
      rootInfo.isSymbolicLink() ||
      rootInfo.uid !== process.geteuid() ||
      (rootInfo.mode & 0o022) !== 0 ||
      !gitInfo.isDirectory() ||
      gitInfo.isSymbolicLink() ||
      gitInfo.uid !== process.geteuid() ||
      (gitInfo.mode & 0o022) !== 0 ||
      fs.realpathSync.native(gitDirectory) !== gitDirectory
    ) {
      fail("Engineering-smoke Git provenance boundary is unsafe");
    }
  } catch (error) {
    if (error && error.name === "EngineeringSmokeAuditError") {
      throw error;
    }
    fail("Engineering-smoke Git provenance boundary is unsafe");
  }
  assertSafeLocalGitMetadata(repositoryRoot);
  return [
    `--git-dir=${gitDirectory}`,
    `--work-tree=${repositoryRoot}`,
    "-c",
    "core.bare=false",
    "-c",
    `core.worktree=${repositoryRoot}`,
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.untrackedCache=false",
    "-c",
    "core.excludesFile=/dev/null",
    "-c",
    "core.attributesFile=/dev/null",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fileMode=true",
    "-c",
    "core.symlinks=true",
    "-c",
    "status.showUntrackedFiles=all",
    "-c",
    "diff.ignoreSubmodules=none",
    ...arguments_
  ];
}

function runGit(arguments_, repositoryRoot = REPOSITORY_ROOT) {
  try {
    return childProcess
      .execFileSync("/usr/bin/git", isolatedGitArguments(arguments_, repositoryRoot), {
        encoding: "utf8",
        env: {
          PATH: "/usr/bin:/bin",
          LANG: "C",
          LC_ALL: "C",
          GIT_CONFIG_NOSYSTEM: "1",
          GIT_CONFIG_GLOBAL: "/dev/null",
          GIT_ATTR_NOSYSTEM: "1",
          GIT_NO_REPLACE_OBJECTS: "1",
          GIT_OPTIONAL_LOCKS: "0",
          GIT_TERMINAL_PROMPT: "0",
          GIT_DIR: path.join(repositoryRoot, ".git"),
          GIT_WORK_TREE: repositoryRoot
        },
        cwd: repositoryRoot,
        stdio: ["ignore", "pipe", "pipe"],
        timeout: 30_000,
        maxBuffer: 4 * 1024 * 1024
      })
      .trim();
  } catch (error) {
    if (error?.name === "EngineeringSmokeAuditError") {
      throw error;
    }
    fail("Engineering-smoke Git provenance inspection failed");
  }
}

function runGitBytes(arguments_, repositoryRoot = REPOSITORY_ROOT) {
  try {
    return childProcess.execFileSync(
      "/usr/bin/git",
      isolatedGitArguments(arguments_, repositoryRoot),
      {
        env: {
          PATH: "/usr/bin:/bin",
          LANG: "C",
          LC_ALL: "C",
          GIT_CONFIG_NOSYSTEM: "1",
          GIT_CONFIG_GLOBAL: "/dev/null",
          GIT_ATTR_NOSYSTEM: "1",
          GIT_NO_REPLACE_OBJECTS: "1",
          GIT_OPTIONAL_LOCKS: "0",
          GIT_TERMINAL_PROMPT: "0",
          GIT_DIR: path.join(repositoryRoot, ".git"),
          GIT_WORK_TREE: repositoryRoot
        },
        cwd: repositoryRoot,
        stdio: ["ignore", "pipe", "pipe"],
        timeout: 30_000,
        maxBuffer: 64 * 1024 * 1024
      }
    );
  } catch (error) {
    if (error?.name === "EngineeringSmokeAuditError") {
      throw error;
    }
    fail("Engineering-smoke Git provenance inspection failed");
  }
}

function selectedSourceCommit(environment) {
  const commit = (environment.LCF_SOURCE_SHA || "").toLowerCase();
  if (!COMMIT_PATTERN.test(commit)) {
    fail("Engineering-smoke source commit is missing or invalid");
  }
  return commit;
}

function selectedSourceTree(environment) {
  const tree = (environment.LCF_SOURCE_TREE || "").toLowerCase();
  if (!COMMIT_PATTERN.test(tree)) {
    fail("Engineering-smoke source tree is missing or invalid");
  }
  return tree;
}

function stableFileIdentity(info) {
  return [
    info.dev,
    info.ino,
    info.mode,
    info.nlink,
    info.size,
    info.mtimeMs,
    info.ctimeMs
  ].join(":");
}

function validateRawRepositoryState(repositoryRoot, inventory) {
  const byPath = new Map(inventory.map((record) => [record.path, record]));
  const staged = new Map();
  for (const encoded of runGitBytes(
    ["ls-files", "--stage", "-z"],
    repositoryRoot
  ).toString("binary").split("\0")) {
    if (encoded.length === 0) {
      continue;
    }
    const raw = Buffer.from(encoded, "binary");
    const separator = raw.indexOf(0x09);
    const header = raw.subarray(0, separator).toString("ascii");
    const rawPath = raw.subarray(separator + 1);
    const sourcePath = rawPath.toString("utf8");
    const [mode, objectId, stage, ...extra] = header.split(" ");
    if (
      separator <= 0 ||
      !Buffer.from(sourcePath, "utf8").equals(rawPath) ||
      extra.length !== 0 ||
      stage !== "0" ||
      staged.has(sourcePath)
    ) {
      fail("Engineering-smoke Git index is unsafe");
    }
    staged.set(sourcePath, { mode, objectId });
  }
  const flags = new Set();
  for (const encoded of runGitBytes(
    ["ls-files", "-v", "-z"],
    repositoryRoot
  ).toString("binary").split("\0")) {
    if (encoded.length === 0) {
      continue;
    }
    const raw = Buffer.from(encoded, "binary");
    const rawPath = raw.subarray(2);
    const sourcePath = rawPath.toString("utf8");
    if (
      raw.length <= 2 ||
      raw[0] !== 0x48 ||
      raw[1] !== 0x20 ||
      !Buffer.from(sourcePath, "utf8").equals(rawPath) ||
      flags.has(sourcePath)
    ) {
      fail("Engineering-smoke Git index contains hidden state");
    }
    flags.add(sourcePath);
  }
  if (staged.size !== byPath.size || flags.size !== byPath.size) {
    fail("Engineering-smoke Git index differs from the reviewed tree");
  }
  const checkedDirectories = new Map([
    [repositoryRoot, stableFileIdentity(fs.lstatSync(repositoryRoot))]
  ]);
  let totalBytes = 0;
  for (const record of inventory) {
    const indexRecord = staged.get(record.path);
    if (
      !indexRecord ||
      indexRecord.mode !== record.mode ||
      indexRecord.objectId !== record.objectId ||
      !flags.has(record.path)
    ) {
      fail("Engineering-smoke Git index differs from the reviewed tree");
    }
    const parts = record.path.split("/");
    let parent = repositoryRoot;
    for (const part of parts.slice(0, -1)) {
      parent = path.join(parent, part);
      if (checkedDirectories.has(parent)) {
        continue;
      }
      let parentInfo;
      try {
        parentInfo = fs.lstatSync(parent);
      } catch {
        fail("Engineering-smoke tracked worktree is incomplete");
      }
      if (
        !parentInfo.isDirectory() ||
        parentInfo.isSymbolicLink() ||
        parentInfo.uid !== process.geteuid() ||
        (parentInfo.mode & 0o022) !== 0
      ) {
        fail("Engineering-smoke tracked worktree has an unsafe parent");
      }
      checkedDirectories.set(parent, stableFileIdentity(parentInfo));
    }
    const candidate = path.join(repositoryRoot, ...parts);
    let bytes;
    if (record.mode === "120000") {
      let before;
      let after;
      try {
        before = fs.lstatSync(candidate);
        if (totalBytes + before.size > MAX_SOURCE_SNAPSHOT_BYTES) {
          fail("Engineering-smoke tracked worktree exceeds its byte bound");
        }
        bytes = fs.readlinkSync(candidate, { encoding: "buffer" });
        after = fs.lstatSync(candidate);
      } catch {
        fail("Engineering-smoke tracked symlink is unreadable");
      }
      if (
        !before.isSymbolicLink() ||
        before.uid !== process.geteuid() ||
        stableFileIdentity(before) !== stableFileIdentity(after)
      ) {
        fail("Engineering-smoke tracked symlink is unsafe");
      }
    } else {
      let descriptor;
      try {
        descriptor = fs.openSync(
          candidate,
          fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW
        );
        const before = fs.fstatSync(descriptor);
        if (totalBytes + before.size > MAX_SOURCE_SNAPSHOT_BYTES) {
          fail("Engineering-smoke tracked worktree exceeds its byte bound");
        }
        bytes = fs.readFileSync(descriptor);
        const after = fs.fstatSync(descriptor);
        const executable = (before.mode & 0o111) !== 0;
        if (
          !before.isFile() ||
          before.uid !== process.geteuid() ||
          before.nlink !== 1 ||
          (before.mode & 0o7000) !== 0 ||
          executable !== (record.mode === "100755") ||
          stableFileIdentity(before) !== stableFileIdentity(after)
        ) {
          fail("Engineering-smoke tracked file is unsafe");
        }
      } catch (error) {
        if (error?.name === "EngineeringSmokeAuditError") {
          throw error;
        }
        fail("Engineering-smoke tracked file is unreadable");
      } finally {
        if (descriptor !== undefined) {
          fs.closeSync(descriptor);
        }
      }
    }
    totalBytes += bytes.length;
    const digest = crypto
      .createHash("sha1")
      .update(Buffer.from(`blob ${bytes.length}\0`, "ascii"))
      .update(bytes)
      .digest("hex");
    if (digest !== record.objectId) {
      fail("Engineering-smoke tracked worktree bytes differ from the reviewed tree");
    }
    let rootCurrent;
    try {
      rootCurrent = fs.lstatSync(repositoryRoot);
    } catch {
      fail("Engineering-smoke tracked worktree parent changed");
    }
    if (
      !rootCurrent.isDirectory() ||
      rootCurrent.isSymbolicLink() ||
      rootCurrent.uid !== process.geteuid() ||
      (rootCurrent.mode & 0o022) !== 0 ||
      stableFileIdentity(rootCurrent) !== checkedDirectories.get(repositoryRoot)
    ) {
      fail("Engineering-smoke tracked worktree parent changed");
    }
    let revalidatedParent = repositoryRoot;
    for (const part of parts.slice(0, -1)) {
      revalidatedParent = path.join(revalidatedParent, part);
      let current;
      try {
        current = fs.lstatSync(revalidatedParent);
      } catch {
        fail("Engineering-smoke tracked worktree parent changed");
      }
      if (
        !current.isDirectory() ||
        current.isSymbolicLink() ||
        current.uid !== process.geteuid() ||
        (current.mode & 0o022) !== 0 ||
        stableFileIdentity(current) !== checkedDirectories.get(revalidatedParent)
      ) {
        fail("Engineering-smoke tracked worktree parent changed");
      }
    }
  }
}

function inspectRepositorySourceSnapshot(
  repositoryRoot = REPOSITORY_ROOT,
  environment = process.env
) {
  const commit = runGit(
    ["rev-parse", "--verify", "HEAD^{commit}"],
    repositoryRoot
  ).toLowerCase();
  const tree = runGit(
    ["rev-parse", "--verify", "HEAD^{tree}"],
    repositoryRoot
  ).toLowerCase();
  const sourceDateEpoch = Number(
    runGit(["show", "-s", "--format=%ct", "HEAD"], repositoryRoot)
  );
  if (
    commit !== selectedSourceCommit(environment) ||
    tree !== selectedSourceTree(environment) ||
    runGit(
      ["rev-parse", "--verify", `${commit}^{tree}`],
      repositoryRoot
    ).toLowerCase() !== tree ||
    runGit(["write-tree"], repositoryRoot).toLowerCase() !== tree ||
    !Number.isSafeInteger(sourceDateEpoch) ||
    sourceDateEpoch < 100_000_000 ||
    String(sourceDateEpoch) !== environment.LCF_SOURCE_DATE_EPOCH
  ) {
    fail("Engineering-smoke assembly requires a clean exact checkout");
  }
  runGit(["diff-files", "--quiet"], repositoryRoot);
  runGit(
    ["diff-index", "--cached", "--quiet", commit, "--"],
    repositoryRoot
  );
  if (
    runGit(
      [
        "status",
        "--porcelain=v2",
        "--untracked-files=all",
        "--ignore-submodules=none"
      ],
      repositoryRoot
    ) !== "" ||
    runGit(["submodule", "status", "--recursive"], repositoryRoot) !== ""
  ) {
    fail("Engineering-smoke assembly requires a clean exact checkout");
  }

  const inventory = [];
  const seen = new Set();
  const rawInventory = runGitBytes(
    ["ls-tree", "-r", "-z", "--full-tree", commit],
    repositoryRoot
  );
  for (const encoded of rawInventory.toString("binary").split("\0")) {
    if (encoded.length === 0) {
      continue;
    }
    const record = Buffer.from(encoded, "binary");
    const separator = record.indexOf(0x09);
    if (separator <= 0) {
      fail("Engineering-smoke source tree inventory is malformed");
    }
    const headerBytes = record.subarray(0, separator);
    const pathBytes = record.subarray(separator + 1);
    const header = headerBytes.toString("ascii");
    const sourcePath = pathBytes.toString("utf8");
    if (
      !Buffer.from(header, "ascii").equals(headerBytes) ||
      !Buffer.from(sourcePath, "utf8").equals(pathBytes)
    ) {
      fail("Engineering-smoke source tree inventory is malformed");
    }
    const [mode, type, objectId, ...extra] = header.split(" ");
    const parts = sourcePath.split("/");
    if (
      extra.length !== 0 ||
      !["100644", "100755", "120000"].includes(mode) ||
      type !== "blob" ||
      !COMMIT_PATTERN.test(objectId || "") ||
      sourcePath.length === 0 ||
      sourcePath.startsWith("/") ||
      sourcePath.includes("\\") ||
      parts.some(
        (part) => part.length === 0 || part === "." || part === ".." || part === ".git"
      ) ||
      Array.from(sourcePath).some((character) => character.codePointAt(0) < 0x20) ||
      seen.has(sourcePath)
    ) {
      fail("Engineering-smoke source tree inventory is unsafe");
    }
    seen.add(sourcePath);
    inventory.push({ mode, objectId, path: sourcePath, type });
    if (inventory.length > MAX_SOURCE_SNAPSHOT_FILES) {
      fail("Engineering-smoke source tree inventory exceeds its file bound");
    }
  }
  if (inventory.length === 0) {
    fail("Engineering-smoke source tree inventory is empty");
  }
  inventory.sort((left, right) => compareCodePoints(left.path, right.path));
  validateRawRepositoryState(repositoryRoot, inventory);
  const sourceSnapshotSha256 = sha256Bytes(
    Buffer.from(canonicalJson(inventory), "utf8")
  );
  const rendererPackageLock = inventory.find(
    (record) => record.path === RENDERER_PACKAGE_LOCK_PATH
  );
  const desktopPackage = inventory.find(
    (record) => record.path === DESKTOP_PACKAGE_PATH
  );
  if (
    !rendererPackageLock ||
    rendererPackageLock.mode !== "100644" ||
    rendererPackageLock.type !== "blob" ||
    !desktopPackage ||
    desktopPackage.mode !== "100644" ||
    desktopPackage.type !== "blob"
  ) {
    fail("Engineering-smoke reviewed package metadata is missing");
  }
  const rendererPackageLockSha256 = sha256Bytes(
    readReviewedGitBlob(repositoryRoot, rendererPackageLock.objectId)
  );
  const desktopPackageSha256 = sha256Bytes(
    readReviewedGitBlob(repositoryRoot, desktopPackage.objectId)
  );
  if (
    environment.LCF_SOURCE_SNAPSHOT_SHA256 !== sourceSnapshotSha256 ||
    environment.LCF_RENDERER_PACKAGE_LOCK_SHA256 !==
      rendererPackageLockSha256
  ) {
    fail("Engineering-smoke reviewed source digests differ from the commit");
  }
  if (
    runGit(
      ["rev-parse", "--verify", "HEAD^{commit}"],
      repositoryRoot
    ).toLowerCase() !== commit ||
    runGit(
      ["rev-parse", "--verify", "HEAD^{tree}"],
      repositoryRoot
    ).toLowerCase() !== tree ||
    runGit(["write-tree"], repositoryRoot).toLowerCase() !== tree ||
    runGit(
      [
        "status",
        "--porcelain=v2",
        "--untracked-files=all",
        "--ignore-submodules=none"
      ],
      repositoryRoot
    ) !== "" ||
    runGit(["submodule", "status", "--recursive"], repositoryRoot) !== ""
  ) {
    fail("Engineering-smoke source changed during provenance inspection");
  }
  validateRawRepositoryState(repositoryRoot, inventory);
  return {
    commit,
    tree,
    sourceDateEpoch,
    sourceSnapshotSha256,
    rendererPackageLockSha256,
    desktopPackageSha256,
    inventory
  };
}

function inspectRepositoryProvenance(
  repositoryRoot = REPOSITORY_ROOT,
  environment = process.env
) {
  const { inventory: _inventory, ...provenance } =
    inspectRepositorySourceSnapshot(repositoryRoot, environment);
  return provenance;
}

function readReviewedGitBlob(repositoryRoot, objectId) {
  if (!COMMIT_PATTERN.test(objectId || "")) {
    fail("Engineering-smoke source object id is invalid");
  }
  const bytes = runGitBytes(["cat-file", "blob", objectId], repositoryRoot);
  const digest = crypto
    .createHash("sha1")
    .update(Buffer.from(`blob ${bytes.length}\0`, "ascii"))
    .update(bytes)
    .digest("hex");
  if (digest !== objectId) {
    fail("Engineering-smoke source object differs from the reviewed tree");
  }
  return bytes;
}

function loadReviewedDesktopPackageMetadata(
  source,
  repositoryRoot = REPOSITORY_ROOT
) {
  if (!source || !Array.isArray(source.inventory)) {
    fail("Engineering-smoke exact source inventory is missing");
  }
  const record = source.inventory.find(
    (candidate) => candidate.path === DESKTOP_PACKAGE_PATH
  );
  let bytes;
  let metadata;
  try {
    bytes = readReviewedGitBlob(repositoryRoot, record.objectId);
    metadata = JSON.parse(bytes.toString("utf8"));
  } catch {
    fail("Reviewed desktop package metadata is unreadable");
  }
  if (
    !record ||
    record.mode !== "100644" ||
    record.type !== "blob" ||
    sha256Bytes(bytes) !== source.desktopPackageSha256 ||
    !metadata ||
    typeof metadata !== "object" ||
    Array.isArray(metadata) ||
    typeof metadata.version !== "string" ||
    metadata.version.length === 0
  ) {
    fail("Reviewed desktop package metadata is invalid");
  }
  return metadata;
}

function assertNoProductionEnvironment(environment) {
  if (
    Object.prototype.hasOwnProperty.call(environment, "CSC_FOR_PULL_REQUEST") &&
    environment.CSC_FOR_PULL_REQUEST !== "true"
  ) {
    fail("Engineering-smoke PR ad-hoc signing control is invalid");
  }
  const present = FORBIDDEN_PRODUCTION_ENVIRONMENT.filter(
    (name) => typeof environment[name] === "string" && environment[name].length > 0
  );
  if (present.length > 0) {
    fail("Engineering-smoke assembly rejects production or mutable release inputs");
  }
}

function assertEngineeringSmokeMode(environment) {
  if (environment.LCF_ENGINEERING_SMOKE !== "true") {
    fail("Engineering-smoke packaging mode is not explicitly enabled");
  }
}

function validateHost(platformName, architecture) {
  if (platformName !== "darwin" || architecture !== "arm64") {
    fail("Engineering-smoke assembly requires a Darwin arm64 host");
  }
}

function validateFixedGeneratedPath(candidate, expected, label) {
  if (
    candidate !== expected ||
    !isContained(path.join(DESKTOP_ROOT, "generated"), candidate)
  ) {
    fail(`${label} is outside the fixed engineering-smoke staging root`);
  }
  if (fs.existsSync(candidate)) {
    const info = fs.lstatSync(candidate);
    if (
      !info.isDirectory() ||
      info.isSymbolicLink() ||
      fs.realpathSync.native(candidate) !== candidate
    ) {
      fail(`${label} is not a real directory`);
    }
  }
}

function requireSafeGeneratedRoot(
  generatedRoot,
  desktopRoot = DESKTOP_ROOT
) {
  if (
    generatedRoot !== path.join(desktopRoot, "generated") ||
    !isContained(desktopRoot, generatedRoot)
  ) {
    fail("Engineering-smoke generated root is not fixed");
  }
  fs.mkdirSync(generatedRoot, { recursive: true, mode: 0o755 });
  requireRealDirectory(generatedRoot, "Engineering-smoke generated root");
}

function preflightEngineeringSmoke(options = {}) {
  const environment = options.environment || process.env;
  const platformName = options.platform || process.platform;
  const architecture = options.architecture || process.arch;
  validateHost(platformName, architecture);
  assertEngineeringSmokeMode(environment);
  assertNoProductionEnvironment(environment);
  return (options.inspectRepository || inspectRepositoryProvenance)(
    REPOSITORY_ROOT,
    environment
  );
}

function initializeBuildStaging(options = {}) {
  preflightEngineeringSmoke(options);
  const generatedRoot = path.join(DESKTOP_ROOT, "generated");
  requireSafeGeneratedRoot(generatedRoot);
  validateFixedGeneratedPath(
    ENGINEERING_ROOT,
    path.join(generatedRoot, "engineering-smoke"),
    "Engineering-smoke root"
  );
  if (fs.existsSync(ENGINEERING_ROOT)) {
    fs.rmSync(ENGINEERING_ROOT, { recursive: true });
  }
  fs.mkdirSync(BUILD_ROOT, { recursive: true, mode: 0o755 });
  return BUILD_ROOT;
}

function normalizeTree(root, epoch) {
  const timestamp = new Date(epoch * 1000);
  function visit(candidate) {
    const info = fs.lstatSync(candidate);
    if (info.isSymbolicLink()) {
      fail("Engineering-smoke staging must not contain symlinks");
    }
    if (info.isDirectory()) {
      fs.chmodSync(candidate, 0o755);
      for (const name of fs.readdirSync(candidate)) {
        visit(path.join(candidate, name));
      }
      fs.utimesSync(candidate, timestamp, timestamp);
      return;
    }
    if (!info.isFile() || info.nlink !== 1) {
      fail("Engineering-smoke staging contains a special or linked file");
    }
    fs.chmodSync(candidate, 0o644);
    fs.utimesSync(candidate, timestamp, timestamp);
  }
  visit(root);
}

function loadEntrypointBuildAttestation(candidate) {
  let descriptor;
  try {
    descriptor = fs.openSync(
      candidate,
      fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW
    );
    const before = fs.fstatSync(descriptor);
    if (
      !before.isFile() ||
      before.uid !== process.geteuid() ||
      before.nlink !== 1 ||
      before.size <= 0 ||
      before.size > MAX_ENTRYPOINT_ATTESTATION_BYTES ||
      (before.mode & 0o7022) !== 0
    ) {
      fail("Engineering-smoke entrypoint build attestation is unsafe");
    }
    const bytes = fs.readFileSync(descriptor);
    const after = fs.fstatSync(descriptor);
    if (stableFileIdentity(before) !== stableFileIdentity(after)) {
      fail("Engineering-smoke entrypoint build attestation changed while read");
    }
    const text = bytes.toString("utf8");
    if (!Buffer.from(text, "utf8").equals(bytes)) {
      fail("Engineering-smoke entrypoint build attestation is unreadable");
    }
    const attestation = JSON.parse(text);
    if (text !== `${canonicalJson(attestation)}\n`) {
      fail("Engineering-smoke entrypoint build attestation is not canonical");
    }
    return attestation;
  } catch (error) {
    if (error?.name === "EngineeringSmokeAuditError") {
      throw error;
    }
    fail("Engineering-smoke entrypoint build attestation is unreadable");
  } finally {
    if (descriptor !== undefined) {
      fs.closeSync(descriptor);
    }
  }
}

function validateEntrypointBuild(attestation, source) {
  const sha256Pattern = /^[0-9a-f]{64}$/;
  if (
    !attestation ||
    typeof attestation !== "object" ||
    Array.isArray(attestation) ||
    Object.keys(attestation).sort().join(",") !==
      "builder,inputs,inputsSha256,kind,outputs,schemaVersion,source" ||
    attestation.schemaVersion !== 1 ||
    attestation.kind !== "engineering-smoke-entrypoint-build" ||
    !attestation.source ||
    Object.keys(attestation.source).sort().join(",") !==
      "commit,sourceSnapshotSha256,tree" ||
    attestation.source.commit !== source.commit ||
    attestation.source.tree !== source.tree ||
    attestation.source.sourceSnapshotSha256 !== source.sourceSnapshotSha256 ||
    !attestation.builder ||
    Object.keys(attestation.builder).sort().join(",") !==
      "installedContentSha256,name,nodeVersion,npmVersion,packageLockSha256,version" ||
    attestation.builder.name !== "esbuild" ||
    attestation.builder.version !== "0.28.1" ||
    attestation.builder.nodeVersion !== "v22.23.2" ||
    attestation.builder.npmVersion !== "10.9.8" ||
    !sha256Pattern.test(attestation.builder.packageLockSha256 || "") ||
    !sha256Pattern.test(attestation.builder.installedContentSha256 || "") ||
    !Array.isArray(attestation.inputs) ||
    attestation.inputs.length === 0 ||
    !sha256Pattern.test(attestation.inputsSha256 || "") ||
    sha256Bytes(Buffer.from(canonicalJson(attestation.inputs), "utf8")) !==
      attestation.inputsSha256 ||
    !attestation.outputs ||
    Object.keys(attestation.outputs).sort().join(",") !== "main,preload"
  ) {
    fail("Engineering-smoke entrypoint build attestation is invalid");
  }
  const observedPaths = new Set();
  if (!Array.isArray(source.inventory)) {
    fail("Engineering-smoke exact source inventory is missing");
  }
  const reviewedInputs = new Map(
    source.inventory.map((record) => [record.path, record])
  );
  let previousPath = null;
  for (const input of attestation.inputs) {
    const reviewed = reviewedInputs.get(input.path);
    if (
      !input ||
      typeof input !== "object" ||
      Array.isArray(input) ||
      Object.keys(input).sort().join(",") !== "mode,objectId,path,type" ||
      !["100644", "100755"].includes(input.mode) ||
      input.type !== "blob" ||
      !COMMIT_PATTERN.test(input.objectId || "") ||
      typeof input.path !== "string" ||
      (input.path !== "desktop/tsconfig.json" &&
        !input.path.startsWith("desktop/src/")) ||
      input.path.includes("\\") ||
      input.path.split("/").some((part) => !part || part === "." || part === "..") ||
      observedPaths.has(input.path) ||
      (previousPath !== null && compareCodePoints(previousPath, input.path) >= 0) ||
      !reviewed ||
      reviewed.mode !== input.mode ||
      reviewed.objectId !== input.objectId ||
      reviewed.type !== input.type
    ) {
      fail("Engineering-smoke entrypoint build input closure is invalid");
    }
    observedPaths.add(input.path);
    previousPath = input.path;
  }
  for (const required of [
    "desktop/tsconfig.json",
    "desktop/src/main/index.ts",
    "desktop/src/preload/index.ts"
  ]) {
    if (!observedPaths.has(required)) {
      fail("Engineering-smoke entrypoint build input closure is incomplete");
    }
  }
  const outputs = {};
  for (const expected of ENTRYPOINT_OUTPUTS) {
    const record = attestation.outputs[expected.key];
    if (
      !record ||
      typeof record !== "object" ||
      Array.isArray(record) ||
      Object.keys(record).sort().join(",") !== "bytes,path,sha256" ||
      record.path !== expected.path ||
      !Number.isSafeInteger(record.bytes) ||
      record.bytes <= 0 ||
      record.bytes > MAX_ENTRYPOINT_OUTPUT_BYTES ||
      !sha256Pattern.test(record.sha256 || "")
    ) {
      fail("Engineering-smoke entrypoint output attestation is invalid");
    }
    outputs[expected.key] = {
      path: record.path,
      sha256: record.sha256,
      bytes: record.bytes
    };
  }
  return {
    builder: "esbuild",
    builderVersion: "0.28.1",
    nodeVersion: attestation.builder.nodeVersion,
    npmVersion: attestation.builder.npmVersion,
    packageLockSha256: attestation.builder.packageLockSha256,
    installedContentSha256: attestation.builder.installedContentSha256,
    inputs: attestation.inputs.length,
    inputsSha256: attestation.inputsSha256,
    outputs
  };
}

function streamAttestedFile(sourcePath, expected, targetPath, dependencies = {}) {
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  let sourceDescriptor;
  let targetDescriptor;
  try {
    sourceDescriptor = fs.openSync(
      sourcePath,
      fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW
    );
    const before = fs.fstatSync(sourceDescriptor);
    if (
      !before.isFile() ||
      before.uid !== process.geteuid() ||
      before.nlink !== 1 ||
      before.size !== expected.bytes ||
      (before.mode & 0o7022) !== 0
    ) {
      fail("Engineering-smoke entrypoint source capability is unsafe");
    }
    if (typeof dependencies.afterSourceOpen === "function") {
      dependencies.afterSourceOpen({
        descriptor: sourceDescriptor,
        expected: { ...expected },
        sourcePath
      });
    }
    if (targetPath !== undefined) {
      fs.mkdirSync(path.dirname(targetPath), { recursive: true, mode: 0o700 });
      targetDescriptor = fs.openSync(
        targetPath,
        fs.constants.O_WRONLY |
          fs.constants.O_CREAT |
          fs.constants.O_EXCL |
          fs.constants.O_NOFOLLOW,
        0o600
      );
    }
    const digest = crypto.createHash("sha256");
    let copiedBytes = 0;
    let chunk = 0;
    for (;;) {
      const count = fs.readSync(
        sourceDescriptor,
        buffer,
        0,
        buffer.length,
        null
      );
      if (count === 0) {
        break;
      }
      digest.update(buffer.subarray(0, count));
      if (targetDescriptor !== undefined) {
        let offset = 0;
        while (offset < count) {
          const written = fs.writeSync(
            targetDescriptor,
            buffer,
            offset,
            count - offset,
            null
          );
          if (written <= 0) {
            fail("Engineering-smoke entrypoint staged write made no progress");
          }
          offset += written;
        }
      }
      copiedBytes += count;
      chunk += 1;
      if (typeof dependencies.afterReadChunk === "function") {
        dependencies.afterReadChunk({
          bytes: copiedBytes,
          chunk,
          expected: { ...expected },
          sourcePath
        });
      }
    }
    if (targetDescriptor !== undefined) {
      fs.fsyncSync(targetDescriptor);
    }
    const after = fs.fstatSync(sourceDescriptor);
    if (
      [before.dev, before.ino, before.mode, before.nlink, before.size].join(":") !==
        [after.dev, after.ino, after.mode, after.nlink, after.size].join(":") ||
      copiedBytes !== expected.bytes ||
      digest.digest("hex") !== expected.sha256
    ) {
      fail("Engineering-smoke entrypoint source changed while copied");
    }
    return { ...expected };
  } catch (error) {
    if (error?.name === "EngineeringSmokeAuditError") {
      throw error;
    }
    fail("Engineering-smoke entrypoint source could not be copied safely");
  } finally {
    if (targetDescriptor !== undefined) {
      fs.closeSync(targetDescriptor);
    }
    if (sourceDescriptor !== undefined) {
      fs.closeSync(sourceDescriptor);
    }
  }
}

function inspectAttestedEntrypointOutputs(root, expectedOutputs) {
  const observed = {};
  for (const expected of ENTRYPOINT_OUTPUTS) {
    const record = expectedOutputs[expected.key];
    if (!record || record.path !== expected.path) {
      fail("Engineering-smoke entrypoint output inventory is invalid");
    }
    observed[expected.key] = streamAttestedFile(
      path.join(root, ...record.path.split("/")),
      record
    );
  }
  if (canonicalJson(observed) !== canonicalJson(expectedOutputs)) {
    fail("Engineering-smoke entrypoint output inventory differs from attestation");
  }
  return observed;
}

function copyAttestedEntrypointOutputs(
  sourceRoot,
  destinationRoot,
  expectedOutputs,
  dependencies = {}
) {
  const copied = {};
  for (const expected of ENTRYPOINT_OUTPUTS) {
    const record = expectedOutputs[expected.key];
    if (!record || record.path !== expected.path) {
      fail("Engineering-smoke entrypoint output inventory is invalid");
    }
    copied[expected.key] = streamAttestedFile(
      path.join(sourceRoot, ...record.path.split("/")),
      record,
      path.join(destinationRoot, ...record.path.split("/")),
      dependencies
    );
  }
  if (canonicalJson(copied) !== canonicalJson(expectedOutputs)) {
    fail("Engineering-smoke copied entrypoint inventory differs from attestation");
  }
  inspectAttestedEntrypointOutputs(destinationRoot, copied);
  return copied;
}

function createDistributionManifest({
  source,
  version,
  desktopApp,
  renderer,
  rendererManifestSha256,
  python,
  pythonManifest,
  pythonManifestSha256
}) {
  if (
    desktopApp.reviewedPackagePath !== DESKTOP_PACKAGE_PATH ||
    desktopApp.reviewedPackageSha256 !== source.desktopPackageSha256
  ) {
    fail("Desktop package metadata differs from the exact source snapshot");
  }
  const pythonBuild = pythonManifest && pythonManifest.build;
  if (
    !pythonBuild ||
    pythonBuild.repositoryCommit !== source.commit ||
    pythonBuild.repositoryTree !== source.tree ||
    pythonBuild.sourceSnapshotSha256 !== source.sourceSnapshotSha256
  ) {
    fail("Python sidecar provenance differs from the exact source snapshot");
  }
  const pythonToolchain = pythonBuild.pythonToolchain;
  if (
    !pythonToolchain ||
    typeof pythonToolchain !== "object" ||
    Array.isArray(pythonToolchain) ||
    !pythonManifest.artifacts ||
    pythonManifest.artifacts.pythonBuildToolchain !==
      "python-build-toolchain.json"
  ) {
    fail("Python sidecar toolchain evidence is incomplete");
  }
  if (
    !renderer ||
    renderer.repositoryCommit !== source.commit ||
    renderer.repositoryTree !== source.tree ||
    renderer.sourceSnapshotSha256 !== source.sourceSnapshotSha256 ||
    !/^[0-9a-f]{64}$/.test(renderer.inputSnapshotSha256 || "")
  ) {
    fail("Renderer provenance differs from the exact source snapshot");
  }
  return {
    $schema: MANIFEST_SCHEMA_NAME,
    schemaVersion: 1,
    kind: MANIFEST_KIND,
    distribution: {
      class: "engineering-smoke",
      marker: "UNOFFICIAL",
      engineeringOnly: true,
      publishable: false
    },
    application: {
      appId: APP_ID,
      productName: PRODUCT_NAME,
      version
    },
    target: {
      os: "darwin",
      architecture: "arm64",
      artifact: "app-dir"
    },
    source: {
      repository: REPOSITORY,
      commit: source.commit,
      tree: source.tree,
      sourceSnapshotSha256: source.sourceSnapshotSha256,
      sourceDateEpoch: source.sourceDateEpoch
    },
    assembly: {
      builder: "electron-builder",
      mode: "dir",
      asar: true,
      outputDirectory: "release-smoke",
      manifestPath: MANIFEST_RELATIVE_PATH
    },
    components: {
      desktopApp,
      renderer: {
        resourcePath: "Contents/Resources/renderer",
        manifestPath:
          "Contents/Resources/renderer/renderer-build-manifest.json",
        manifestSha256: rendererManifestSha256,
        repositoryCommit: source.commit,
        repositoryTree: source.tree,
        sourceSnapshotSha256: source.sourceSnapshotSha256,
        inputSnapshotSha256: renderer.inputSnapshotSha256,
        files: renderer.files,
        bytes: renderer.bytes
      },
      pythonSidecar: {
        resourcePath: "Contents/Resources/sidecar",
        manifestPath: "Contents/Resources/sidecar/build-manifest.json",
        manifestSha256: pythonManifestSha256,
        normalizedInventorySha256:
          pythonManifest.audit.normalizedInventorySha256,
        repositoryCommit: source.commit,
        repositoryTree: source.tree,
        sourceSnapshotSha256: source.sourceSnapshotSha256,
        pythonBuildToolchainPath:
          "Contents/Resources/sidecar/python-build-toolchain.json",
        pythonToolchain: JSON.parse(JSON.stringify(pythonToolchain)),
        files: python.files,
        nativeFiles: python.nativeFiles,
        components: python.components
      }
    },
    security: {
      signing: "ad-hoc",
      identity: "-",
      hardenedRuntime: false,
      notarized: false,
      productionCredentialsUsed: false,
      secureFusesRequired: true
    },
    capabilities: {
      updater: "unavailable",
      networkAllowed: false,
      manualReleasePageAllowed: false,
      qmd: "omitted",
      mcp: "omitted",
      companion: "omitted",
      productionUpdateTrust: "omitted",
      releaseMetadata: "omitted",
      modelWeights: "omitted"
    },
    validation: {
      validationId: "VAL-PACKAGED-SMOKE-001",
      packagedAppLaunch: "not-run",
      packagedSmoke: "not-run",
      unlocks: []
    }
  };
}

function preparedAppInventory(root) {
  const records = [];
  function visit(candidate, relative) {
    let info;
    try {
      info = fs.lstatSync(candidate);
    } catch {
      fail("Engineering-smoke prepared app inventory is unreadable");
    }
    if (
      info.isSymbolicLink() ||
      info.uid !== process.geteuid() ||
      (info.mode & 0o7022) !== 0
    ) {
      fail("Engineering-smoke prepared app inventory is unsafe");
    }
    if (relative !== "") {
      records.push({
        path: relative,
        type: info.isDirectory() ? "directory" : "file"
      });
    }
    if (info.isDirectory()) {
      for (const name of fs.readdirSync(candidate).sort(compareCodePoints)) {
        visit(
          path.join(candidate, name),
          relative === "" ? name : `${relative}/${name}`
        );
      }
      return;
    }
    if (!info.isFile() || info.nlink !== 1) {
      fail("Engineering-smoke prepared app inventory is unsafe");
    }
  }
  visit(root, "");
  return records;
}

function loadCanonicalJsonCapability(candidate, label) {
  let descriptor;
  try {
    descriptor = fs.openSync(
      candidate,
      fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW
    );
    const before = fs.fstatSync(descriptor);
    if (
      !before.isFile() ||
      before.uid !== process.geteuid() ||
      before.nlink !== 1 ||
      before.size <= 0 ||
      before.size > MAX_ENTRYPOINT_ATTESTATION_BYTES ||
      (before.mode & 0o7022) !== 0
    ) {
      fail(`${label} is unsafe`);
    }
    const bytes = fs.readFileSync(descriptor);
    const after = fs.fstatSync(descriptor);
    if (stableFileIdentity(before) !== stableFileIdentity(after)) {
      fail(`${label} changed while read`);
    }
    const text = bytes.toString("utf8");
    if (!Buffer.from(text, "utf8").equals(bytes)) {
      fail(`${label} is unreadable`);
    }
    const value = JSON.parse(text);
    if (text !== `${canonicalJson(value)}\n`) {
      fail(`${label} is not canonical`);
    }
    return value;
  } catch (error) {
    if (error?.name === "EngineeringSmokeAuditError") {
      throw error;
    }
    fail(`${label} is unreadable`);
  } finally {
    if (descriptor !== undefined) {
      fs.closeSync(descriptor);
    }
  }
}

function auditPreparedEngineeringSmoke(
  appRoot,
  manifestPath,
  { manifest, schema, attestedOutputs, stagedPackageBytes }
) {
  const observedManifest = loadCanonicalJsonCapability(
    manifestPath,
    "Prepared engineering-smoke distribution manifest"
  );
  if (canonicalJson(observedManifest) !== canonicalJson(manifest)) {
    fail("Prepared engineering-smoke manifest differs from assembly");
  }
  validateEngineeringSmokeManifest(observedManifest, schema);
  const expectedInventory = [
    { path: "dist", type: "directory" },
    { path: "dist/main", type: "directory" },
    { path: "dist/main/index.js", type: "file" },
    { path: "dist/preload", type: "directory" },
    { path: "dist/preload/index.cjs", type: "file" },
    { path: "package.json", type: "file" }
  ];
  if (
    canonicalJson(preparedAppInventory(appRoot)) !==
    canonicalJson(expectedInventory)
  ) {
    fail("Prepared engineering-smoke app inventory is not exact");
  }
  const desktopApp = observedManifest.components.desktopApp;
  const expectedFiles = {
    main: {
      path: desktopApp.mainPath,
      sha256: desktopApp.mainSha256,
      bytes: desktopApp.mainBytes
    },
    preload: {
      path: desktopApp.preloadPath,
      sha256: desktopApp.preloadSha256,
      bytes: desktopApp.preloadBytes
    }
  };
  const inspectedOutputs = inspectAttestedEntrypointOutputs(
    appRoot,
    expectedFiles
  );
  if (
    canonicalJson(inspectedOutputs) !== canonicalJson(attestedOutputs) ||
    desktopApp.packagePath !== "package.json"
  ) {
    fail("Prepared engineering-smoke entrypoints differ from attestation");
  }
  const expectedPackage = {
    path: "package.json",
    sha256: sha256Bytes(stagedPackageBytes),
    bytes: stagedPackageBytes.length
  };
  streamAttestedFile(
    path.join(appRoot, "package.json"),
    expectedPackage
  );
  if (
    desktopApp.packageSha256 !== expectedPackage.sha256 ||
    desktopApp.packageBytes !== expectedPackage.bytes
  ) {
    fail("Prepared engineering-smoke package metadata differs from manifest");
  }
  return {
    main: { ...inspectedOutputs.main },
    preload: { ...inspectedOutputs.preload },
    package: expectedPackage
  };
}

function publishPreparedEngineeringSmoke(
  {
    temporaryApp,
    temporaryManifest,
    appDestination,
    manifestDestination,
    auditPublished
  },
  dependencies = {}
) {
  const rename = dependencies.rename || fs.renameSync;
  const parent = path.dirname(appDestination);
  if (parent !== path.dirname(manifestDestination)) {
    fail("Engineering-smoke publish destinations do not share a fixed parent");
  }
  let previousApp;
  let previousManifest;
  let publishedApp = false;
  let publishedManifest = false;
  try {
    if (fs.existsSync(appDestination)) {
      const info = fs.lstatSync(appDestination);
      if (
        !info.isDirectory() ||
        info.isSymbolicLink() ||
        fs.realpathSync.native(appDestination) !== appDestination
      ) {
        fail("Existing engineering-smoke staging target is unsafe");
      }
      previousApp = path.join(
        parent,
        `.app-previous-${crypto.randomBytes(16).toString("hex")}`
      );
      rename(appDestination, previousApp);
    }
    if (fs.existsSync(manifestDestination)) {
      const info = fs.lstatSync(manifestDestination);
      if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1) {
        fail("Existing engineering-smoke staging target is unsafe");
      }
      previousManifest = path.join(
        parent,
        `.distribution-previous-${crypto.randomBytes(16).toString("hex")}.json`
      );
      rename(manifestDestination, previousManifest);
    }
    rename(temporaryApp, appDestination);
    publishedApp = true;
    rename(temporaryManifest, manifestDestination);
    publishedManifest = true;
    auditPublished();
  } catch (publishError) {
    let rollbackFailed = false;
    if (publishedManifest) {
      try {
        rename(manifestDestination, temporaryManifest);
        publishedManifest = false;
      } catch {
        rollbackFailed = true;
      }
    }
    if (publishedApp) {
      try {
        rename(appDestination, temporaryApp);
        publishedApp = false;
      } catch {
        rollbackFailed = true;
      }
    }
    if (previousManifest !== undefined) {
      try {
        rename(previousManifest, manifestDestination);
        previousManifest = undefined;
      } catch {
        rollbackFailed = true;
      }
    }
    if (previousApp !== undefined) {
      try {
        rename(previousApp, appDestination);
        previousApp = undefined;
      } catch {
        rollbackFailed = true;
      }
    }
    if (rollbackFailed) {
      fail("Engineering-smoke staging publish rollback failed");
    }
    throw publishError;
  }
  try {
    if (previousManifest !== undefined) {
      fs.rmSync(previousManifest);
      previousManifest = undefined;
    }
    if (previousApp !== undefined) {
      fs.rmSync(previousApp, { recursive: true });
      previousApp = undefined;
    }
  } catch {
    fail("Engineering-smoke previous staging cleanup failed");
  }
}

function createPrepareEngineeringSmoke(dependencies = {}) {
  return function prepareEngineeringSmoke(options = {}) {
    const environment = options.environment || process.env;
    const platformName = options.platform || process.platform;
    const architecture = options.architecture || process.arch;
    validateHost(platformName, architecture);
    assertEngineeringSmokeMode(environment);
    assertNoProductionEnvironment(environment);
    requireRealDirectory(
      ENGINEERING_ROOT,
      "Engineering-smoke staging root"
    );

    requireRegularFile(BUILD_MAIN, "Engineering-smoke Main bundle");
    requireRegularFile(BUILD_PRELOAD, "Engineering-smoke preload bundle");
    const inspectExactRepository =
      dependencies.inspectRepository || inspectRepositorySourceSnapshot;
    const source = inspectExactRepository(REPOSITORY_ROOT, environment);
    const rendererAuditOptions = {
      expectedCommit: source.commit,
      expectedTree: source.tree,
      expectedSourceSnapshotSha256: source.sourceSnapshotSha256,
      expectedSourceDateEpoch: source.sourceDateEpoch,
      expectedPackageLockSha256: source.rendererPackageLockSha256
    };
    const auditExactRenderer = dependencies.auditRenderer || auditRenderer;
    const renderer = auditExactRenderer(
      RENDERER_ROOT,
      rendererAuditOptions
    );
    const auditExactPython = dependencies.auditPythonSidecar ||
      auditPythonSidecar;
    const pythonAuditOptions = {
      repositoryRoot: REPOSITORY_ROOT,
      stagingRoot: SIDECAR_ROOT,
      environment,
      platform: platformName,
      architecture
    };
    const python = auditExactPython(pythonAuditOptions);
    const packageMetadata = loadReviewedDesktopPackageMetadata(source);
    const stagedPackageMetadata = {
      name: "local-context-forge-engineering-smoke",
      version: packageMetadata.version,
      private: true,
      description:
        "UNOFFICIAL engineering-only Local Context Forge smoke bundle",
      main: "dist/main/index.js"
    };
    const stagedPackageBytes = Buffer.from(
      `${canonicalJson(stagedPackageMetadata)}\n`,
      "utf8"
    );
    requireRegularFile(
      BUILD_ATTESTATION,
      "Engineering-smoke entrypoint build attestation"
    );
    const validatedEntrypointBuild = validateEntrypointBuild(
      loadEntrypointBuildAttestation(BUILD_ATTESTATION),
      source
    );
    const {
      outputs: attestedEntrypointOutputs,
      ...entrypointBuild
    } = validatedEntrypointBuild;
    const pythonManifest = python.manifest;
    const schema = loadJson(SCHEMA_PATH, "Engineering-smoke manifest schema");
    const temporaryRoot = fs.mkdtempSync(
      path.join(ENGINEERING_ROOT, ".prepared-")
    );
    const temporaryApp = path.join(temporaryRoot, "app");
    const temporaryManifest = path.join(temporaryRoot, "distribution.json");
    let manifest;
    try {
      const copiedEntrypointOutputs = copyAttestedEntrypointOutputs(
        BUILD_ROOT,
        temporaryApp,
        attestedEntrypointOutputs,
        {
          afterSourceOpen: dependencies.afterEntrypointSourceOpen,
          afterReadChunk: dependencies.afterEntrypointReadChunk
        }
      );
      manifest = createDistributionManifest({
        source,
        version: packageMetadata.version,
        desktopApp: {
          asarPath: "Contents/Resources/app.asar",
          mainPath: copiedEntrypointOutputs.main.path,
          mainSha256: copiedEntrypointOutputs.main.sha256,
          mainBytes: copiedEntrypointOutputs.main.bytes,
          preloadPath: copiedEntrypointOutputs.preload.path,
          preloadSha256: copiedEntrypointOutputs.preload.sha256,
          preloadBytes: copiedEntrypointOutputs.preload.bytes,
          packagePath: "package.json",
          packageSha256: sha256Bytes(stagedPackageBytes),
          packageBytes: stagedPackageBytes.length,
          reviewedPackagePath: DESKTOP_PACKAGE_PATH,
          reviewedPackageSha256: source.desktopPackageSha256,
          entrypointBuild
        },
        renderer,
        rendererManifestSha256: renderer.manifestSha256,
        python,
        pythonManifest,
        pythonManifestSha256: python.manifestSha256
      });
      validateEngineeringSmokeManifest(manifest, schema);
      writeCanonicalJson(
        path.join(temporaryApp, "package.json"),
        stagedPackageMetadata
      );
      writeCanonicalJson(temporaryManifest, manifest);
      normalizeTree(temporaryApp, source.sourceDateEpoch);
      fs.utimesSync(
        temporaryManifest,
        new Date(source.sourceDateEpoch * 1000),
        new Date(source.sourceDateEpoch * 1000)
      );

      const revalidatedSource = inspectExactRepository(
        REPOSITORY_ROOT,
        environment
      );
      for (const field of [
        "commit",
        "tree",
        "sourceDateEpoch",
        "sourceSnapshotSha256",
        "rendererPackageLockSha256",
        "desktopPackageSha256"
      ]) {
        if (revalidatedSource[field] !== source[field]) {
          fail("Engineering-smoke source changed during assembly");
        }
      }
      const revalidatedRenderer = auditExactRenderer(
        RENDERER_ROOT,
        rendererAuditOptions
      );
      if (canonicalJson(revalidatedRenderer) !== canonicalJson(renderer)) {
        fail("Engineering-smoke renderer attestation changed during assembly");
      }
      const revalidatedPython = auditExactPython(pythonAuditOptions);
      if (canonicalJson(revalidatedPython) !== canonicalJson(python)) {
        fail("Engineering-smoke Python attestation changed during assembly");
      }
      const revalidatedEntrypointBuild = validateEntrypointBuild(
        loadEntrypointBuildAttestation(BUILD_ATTESTATION),
        revalidatedSource
      );
      inspectAttestedEntrypointOutputs(
        BUILD_ROOT,
        revalidatedEntrypointBuild.outputs
      );
      if (
        canonicalJson(revalidatedEntrypointBuild) !==
        canonicalJson(validatedEntrypointBuild)
      ) {
        fail("Engineering-smoke entrypoint attestation changed during assembly");
      }
      const auditPrepared = dependencies.auditPrepared ||
        auditPreparedEngineeringSmoke;
      auditPrepared(
        temporaryApp,
        temporaryManifest,
        {
          manifest,
          schema,
          attestedOutputs: copiedEntrypointOutputs,
          stagedPackageBytes
        }
      );
      publishPreparedEngineeringSmoke(
        {
          temporaryApp,
          temporaryManifest,
          appDestination: APP_STAGING_ROOT,
          manifestDestination: DISTRIBUTION_MANIFEST,
          auditPublished: () => auditPrepared(
            APP_STAGING_ROOT,
            DISTRIBUTION_MANIFEST,
            {
              manifest,
              schema,
              attestedOutputs: copiedEntrypointOutputs,
              stagedPackageBytes
            }
          )
        },
        { rename: dependencies.rename }
      );
    } finally {
      fs.rmSync(temporaryRoot, { recursive: true, force: true });
    }
    return {
      kind: MANIFEST_KIND,
      source: {
        commit: source.commit,
        tree: source.tree,
        sourceSnapshotSha256: source.sourceSnapshotSha256
      },
      application: { appId: APP_ID, productName: PRODUCT_NAME },
      validation: manifest.validation
    };
  };
}

function main(argv = process.argv.slice(2)) {
  if (argv.length === 1 && argv[0] === "--initialize") {
    process.stdout.write(
      `${canonicalJson({ buildRoot: path.relative(REPOSITORY_ROOT, initializeBuildStaging()) })}\n`
    );
    return;
  }
  if (argv.length !== 0) {
    fail("Usage: prepareEngineeringSmoke.cjs [--initialize]");
  }
  process.stdout.write(
    `${canonicalJson(createPrepareEngineeringSmoke()())}\n`
  );
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    const message =
      error && typeof error.message === "string"
        ? error.message
        : "Engineering-smoke preparation failed unexpectedly";
    process.stderr.write(`engineering-smoke preparation failed: ${message}\n`);
    process.exitCode = 1;
  }
}

module.exports = {
  APP_STAGING_ROOT,
  BUILD_MAIN,
  BUILD_PRELOAD,
  BUILD_ATTESTATION,
  DISTRIBUTION_MANIFEST,
  ENGINEERING_ROOT,
  FORBIDDEN_PRODUCTION_ENVIRONMENT,
  auditPreparedEngineeringSmoke,
  assertNoProductionEnvironment,
  assertEngineeringSmokeMode,
  copyAttestedEntrypointOutputs,
  createDistributionManifest,
  createPrepareEngineeringSmoke,
  initializeBuildStaging,
  inspectRepositoryProvenance,
  inspectRepositorySourceSnapshot,
  loadReviewedDesktopPackageMetadata,
  preflightEngineeringSmoke,
  publishPreparedEngineeringSmoke,
  readReviewedGitBlob,
  requireSafeGeneratedRoot,
  runIsolatedGit: runGit,
  selectedSourceCommit,
  selectedSourceTree,
  validateEntrypointBuild,
  validateHost
};

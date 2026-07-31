"use strict";

const childProcess = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const {
  MANIFEST_KIND,
  MANIFEST_NAME,
  auditRenderer,
  canonicalJson,
  inventory,
  sha256File
} = require("./auditRenderer.cjs");

const REPOSITORY_ROOT = path.resolve(__dirname, "..", "..");
const SOURCE_ROOT = path.join(REPOSITORY_ROOT, "web", "dist");
const DESTINATION_ROOT = path.join(
  REPOSITORY_ROOT,
  "desktop",
  "resources",
  "renderer"
);
const PACKAGE_LOCK = path.join(REPOSITORY_ROOT, "web", "package-lock.json");

class RendererStageError extends Error {
  constructor(message) {
    super(message);
    this.name = "RendererStageError";
  }
}

function fail(message) {
  throw new RendererStageError(message);
}

function git(arguments_) {
  try {
    return childProcess
      .execFileSync("/usr/bin/git", ["-C", REPOSITORY_ROOT, ...arguments_], {
        encoding: "utf8",
        env: { PATH: "/usr/bin:/bin", LANG: "C", LC_ALL: "C" },
        stdio: ["ignore", "pipe", "pipe"],
        timeout: 30_000
      })
      .trim();
  } catch {
    fail("Renderer staging Git provenance check failed");
  }
}

function validateProvenance(environment = process.env) {
  const commit = (environment.GITHUB_SHA || "").toLowerCase();
  const sourceDateEpoch = Number(environment.LCF_SOURCE_DATE_EPOCH);
  if (
    !/^[0-9a-f]{40}$/.test(commit) ||
    !Number.isSafeInteger(sourceDateEpoch) ||
    sourceDateEpoch < 100_000_000 ||
    git(["rev-parse", "HEAD"]).toLowerCase() !== commit ||
    Number(git(["show", "-s", "--format=%ct", "HEAD"])) !== sourceDateEpoch ||
    git(["status", "--porcelain", "--untracked-files=all"]) !== ""
  ) {
    fail("Renderer staging requires a clean reviewed source commit");
  }
  if (git(["check-ignore", "-q", "desktop/resources/renderer"]) !== "") {
    fail("Renderer staging destination ignore policy is ambiguous");
  }
  return { commit, sourceDateEpoch };
}

function normalizeTree(root, epoch) {
  const timestamp = new Date(epoch * 1000);
  function visit(directory) {
    fs.chmodSync(directory, 0o755);
    fs.utimesSync(directory, timestamp, timestamp);
    for (const name of fs.readdirSync(directory)) {
      const candidate = path.join(directory, name);
      const info = fs.lstatSync(candidate);
      if (info.isDirectory()) {
        visit(candidate);
      } else if (info.isFile()) {
        fs.chmodSync(candidate, 0o644);
        fs.utimesSync(candidate, timestamp, timestamp);
      }
    }
  }
  visit(root);
}

function stageRenderer({
  sourceRoot = SOURCE_ROOT,
  destinationRoot = DESTINATION_ROOT,
  environment = process.env
} = {}) {
  const source = path.resolve(sourceRoot);
  const destination = path.resolve(destinationRoot);
  if (destination !== DESTINATION_ROOT) {
    fail("Renderer staging destination is fixed by packaging policy");
  }
  const release = validateProvenance(environment);
  let sourceInfo;
  try {
    sourceInfo = fs.lstatSync(source);
  } catch {
    fail("Web production build is missing");
  }
  if (
    source !== SOURCE_ROOT ||
    !sourceInfo.isDirectory() ||
    sourceInfo.isSymbolicLink() ||
    fs.realpathSync.native(source) !== source
  ) {
    fail("Web production build must be the canonical real web/dist directory");
  }
  const files = inventory(source);
  if (files.some((record) => record.path === MANIFEST_NAME)) {
    fail("Web production build contains a reserved renderer manifest");
  }

  const parent = path.dirname(destination);
  fs.mkdirSync(parent, { recursive: true, mode: 0o755 });
  const temporary = fs.mkdtempSync(path.join(parent, ".renderer-stage-"));
  try {
    for (const record of files) {
      const sourcePath = path.join(source, ...record.path.split("/"));
      const targetPath = path.join(temporary, ...record.path.split("/"));
      fs.mkdirSync(path.dirname(targetPath), { recursive: true, mode: 0o755 });
      fs.copyFileSync(sourcePath, targetPath, fs.constants.COPYFILE_EXCL);
    }
    const manifest = {
      schemaVersion: 1,
      kind: MANIFEST_KIND,
      source: {
        repositoryCommit: release.commit,
        sourceDateEpoch: release.sourceDateEpoch,
        packageLockSha256: sha256File(PACKAGE_LOCK)
      },
      files: inventory(temporary)
    };
    fs.writeFileSync(
      path.join(temporary, MANIFEST_NAME),
      `${canonicalJson(manifest)}\n`,
      { encoding: "utf8", mode: 0o644, flag: "wx" }
    );
    normalizeTree(temporary, release.sourceDateEpoch);
    auditRenderer(temporary, {
      expectedCommit: release.commit,
      expectedSourceDateEpoch: release.sourceDateEpoch
    });
    if (fs.existsSync(destination)) {
      const info = fs.lstatSync(destination);
      if (
        !info.isDirectory() ||
        info.isSymbolicLink() ||
        fs.realpathSync.native(destination) !== destination
      ) {
        fail("Existing renderer staging destination is unsafe");
      }
      fs.rmSync(destination, { recursive: true });
    }
    fs.renameSync(temporary, destination);
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
  return auditRenderer(destination, {
    expectedCommit: release.commit,
    expectedSourceDateEpoch: release.sourceDateEpoch
  });
}

function main() {
  if (process.argv.length !== 2) {
    fail("stageRenderer.cjs takes no arguments");
  }
  process.stdout.write(`${canonicalJson(stageRenderer())}\n`);
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    const message =
      error instanceof RendererStageError
        ? error.message
        : error?.message || "Renderer staging failed unexpectedly";
    process.stderr.write(`renderer staging failed: ${message}\n`);
    process.exitCode = 1;
  }
}

module.exports = { RendererStageError, stageRenderer, validateProvenance };

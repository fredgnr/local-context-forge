"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const {
  MANIFEST_KIND,
  MANIFEST_NAME,
  auditRenderer,
  canonicalJson,
  inventory
} = require("./auditRenderer.cjs");
const prepare = require("./prepareEngineeringSmoke.cjs");

const REPOSITORY_ROOT = path.resolve(__dirname, "..", "..");
const SOURCE_ROOT = path.join(REPOSITORY_ROOT, "web", "dist");
const DESTINATION_ROOT = path.join(
  REPOSITORY_ROOT,
  "desktop",
  "resources",
  "renderer"
);
const SOURCE_ATTESTATION_NAME = "renderer-source-attestation.json";
const DESTINATION_REPOSITORY_PATH = "desktop/resources/renderer";
const DESTINATION_REPOSITORY_DIRECTORY = `${DESTINATION_REPOSITORY_PATH}/`;
const REVIEWED_DESTINATION_IGNORE_EVIDENCE = new RegExp(
  "^\\.gitignore:[1-9][0-9]*:desktop/resources/renderer/\\t" +
    "desktop/resources/renderer/$"
);

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
    return prepare.runIsolatedGit(arguments_, REPOSITORY_ROOT);
  } catch {
    fail("Renderer staging Git provenance check failed");
  }
}

function selectSourceCommit(environment = process.env) {
  const sourceName = "LCF_SOURCE_SHA";
  const commit = (environment.LCF_SOURCE_SHA || "").toLowerCase();
  if (!/^[0-9a-f]{40}$/.test(commit)) {
    fail(`${sourceName} must be a full Git commit SHA`);
  }
  return commit;
}

function validateProvenance(
  environment = process.env,
  { gitCommand = git, inspectRepository } = {}
) {
  const checkedGit = (arguments_, failureMessage) => {
    try {
      return gitCommand(arguments_);
    } catch {
      fail(failureMessage);
    }
  };
  const provenanceFailure = "Renderer staging Git provenance check failed";
  const commit = selectSourceCommit(environment);
  const tree = (environment.LCF_SOURCE_TREE || "").toLowerCase();
  const sourceDateEpoch = Number(environment.LCF_SOURCE_DATE_EPOCH);
  const rendererPackageLockSha256 = (
    environment.LCF_RENDERER_PACKAGE_LOCK_SHA256 || ""
  ).toLowerCase();
  let sourceSnapshotSha256;
  if (inspectRepository !== undefined || gitCommand === git) {
    let inspected;
    try {
      inspected = (inspectRepository || prepare.inspectRepositoryProvenance)(
        REPOSITORY_ROOT,
        environment
      );
    } catch {
      fail(provenanceFailure);
    }
    if (
      inspected.commit !== commit ||
      inspected.tree !== tree ||
      inspected.sourceDateEpoch !== sourceDateEpoch ||
      !/^[0-9a-f]{64}$/.test(inspected.sourceSnapshotSha256 || "") ||
      inspected.rendererPackageLockSha256 !== rendererPackageLockSha256
    ) {
      fail("Renderer staging requires a clean reviewed source commit");
    }
    sourceSnapshotSha256 = inspected.sourceSnapshotSha256;
  } else {
    sourceSnapshotSha256 = environment.LCF_SOURCE_SNAPSHOT_SHA256;
  }
  if (
    !/^[0-9a-f]{40}$/.test(tree) ||
    !/^[0-9a-f]{64}$/.test(sourceSnapshotSha256 || "") ||
    !/^[0-9a-f]{64}$/.test(rendererPackageLockSha256) ||
    !Number.isSafeInteger(sourceDateEpoch) ||
    sourceDateEpoch < 100_000_000 ||
    checkedGit(["rev-parse", "HEAD"], provenanceFailure).toLowerCase() !==
      commit ||
    Number(
      checkedGit(
        ["show", "-s", "--format=%ct", "HEAD"],
        provenanceFailure
      )
    ) !== sourceDateEpoch ||
    checkedGit(
      ["status", "--porcelain=v1", "--untracked-files=all"],
      provenanceFailure
    ) !== ""
  ) {
    fail("Renderer staging requires a clean reviewed source commit");
  }
  const trackedDestinationFailure =
    "Renderer staging destination overlaps tracked source";
  if (
    checkedGit(
      ["ls-files", "--", DESTINATION_REPOSITORY_PATH],
      trackedDestinationFailure
    ) !== ""
  ) {
    fail(trackedDestinationFailure);
  }
  const ignorePolicyFailure =
    "Renderer staging destination is not covered by the reviewed Git ignore policy";
  const ignoreEvidence = checkedGit(
    ["check-ignore", "-v", "--", DESTINATION_REPOSITORY_DIRECTORY],
    ignorePolicyFailure
  );
  if (!REVIEWED_DESTINATION_IGNORE_EVIDENCE.test(ignoreEvidence)) {
    fail(ignorePolicyFailure);
  }
  return {
    commit,
    tree,
    sourceSnapshotSha256,
    sourceDateEpoch,
    rendererPackageLockSha256
  };
}

function exactKeys(value, expected) {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).sort().join("\0") === [...expected].sort().join("\0")
  );
}

function validateSourceAttestation(source, release, environment = process.env) {
  const attestationPath = path.join(source, SOURCE_ATTESTATION_NAME);
  let info;
  let raw;
  let attestation;
  try {
    info = fs.lstatSync(attestationPath);
    raw = fs.readFileSync(attestationPath, "utf8");
    attestation = JSON.parse(raw);
  } catch {
    fail("Renderer exact-source build attestation is unreadable");
  }
  if (
    !info.isFile() ||
    info.isSymbolicLink() ||
    info.nlink !== 1 ||
    info.size <= 0 ||
    info.size > 16 * 1024 * 1024 ||
    raw !== `${canonicalJson(attestation)}\n` ||
    !exactKeys(attestation, [
      "schemaVersion",
      "kind",
      "source",
      "builder",
      "inputs",
      "inputsSha256",
      "outputs"
    ]) ||
    attestation.schemaVersion !== 1 ||
    attestation.kind !== "reviewed-renderer-build" ||
    !exactKeys(attestation.source, [
      "repositoryCommit",
      "repositoryTree",
      "sourceSnapshotSha256",
      "sourceDateEpoch",
      "packageLockSha256"
    ]) ||
    attestation.source.repositoryCommit !== release.commit ||
    attestation.source.repositoryTree !== release.tree ||
    attestation.source.sourceSnapshotSha256 !== release.sourceSnapshotSha256 ||
    attestation.source.sourceDateEpoch !== release.sourceDateEpoch ||
    attestation.source.packageLockSha256 !==
      release.rendererPackageLockSha256 ||
    !exactKeys(attestation.builder, [
      "name",
      "version",
      "reactPluginVersion",
      "nodeVersion",
      "npmVersion",
      "installedContentSha256"
    ]) ||
    attestation.builder.name !== "vite" ||
    attestation.builder.version !== "7.3.6" ||
    attestation.builder.reactPluginVersion !== "4.7.0" ||
    attestation.builder.nodeVersion !== "v22.23.2" ||
    attestation.builder.npmVersion !== "10.9.8" ||
    !/^[0-9a-f]{64}$/.test(attestation.builder.installedContentSha256 || "") ||
    !Array.isArray(attestation.inputs) ||
    attestation.inputs.length < 5 ||
    !/^[0-9a-f]{64}$/.test(attestation.inputsSha256 || "") ||
    crypto
      .createHash("sha256")
      .update(Buffer.from(canonicalJson(attestation.inputs), "utf8"))
      .digest("hex") !== attestation.inputsSha256 ||
    !Array.isArray(attestation.outputs)
  ) {
    fail("Renderer exact-source build attestation is invalid");
  }
  const inputPaths = new Set();
  let reviewedSnapshot;
  try {
    reviewedSnapshot = prepare.inspectRepositorySourceSnapshot(
      REPOSITORY_ROOT,
      environment
    );
  } catch {
    fail("Renderer exact-source input closure cannot be rebound to Git");
  }
  if (
    reviewedSnapshot.commit !== release.commit ||
    reviewedSnapshot.tree !== release.tree ||
    reviewedSnapshot.sourceSnapshotSha256 !== release.sourceSnapshotSha256 ||
    reviewedSnapshot.rendererPackageLockSha256 !==
      release.rendererPackageLockSha256
  ) {
    fail("Renderer exact-source input closure differs from Git");
  }
  const reviewedInputs = new Map(
    reviewedSnapshot.inventory.map((record) => [record.path, record])
  );
  let previousInput = null;
  for (const input of attestation.inputs) {
    const reviewed = reviewedInputs.get(input.path);
    if (
      !exactKeys(input, ["mode", "objectId", "path", "type"]) ||
      !["100644", "100755"].includes(input.mode) ||
      input.type !== "blob" ||
      !/^[0-9a-f]{40}$/.test(input.objectId || "") ||
      typeof input.path !== "string" ||
      (input.path !== "web/index.html" &&
        input.path !== "web/package-lock.json" &&
        input.path !== "web/package.json" &&
        input.path !== "web/tsconfig.app.json" &&
        !input.path.startsWith("web/src/")) ||
      inputPaths.has(input.path) ||
      (previousInput !== null && previousInput >= input.path) ||
      !reviewed ||
      reviewed.mode !== input.mode ||
      reviewed.objectId !== input.objectId ||
      reviewed.type !== input.type
    ) {
      fail("Renderer exact-source input closure is invalid");
    }
    inputPaths.add(input.path);
    previousInput = input.path;
  }
  for (const required of [
    "web/index.html",
    "web/package-lock.json",
    "web/package.json",
    "web/tsconfig.app.json",
    "web/src/main.tsx"
  ]) {
    if (!inputPaths.has(required)) {
      fail("Renderer exact-source input closure is incomplete");
    }
  }
  const actualOutputs = inventory(source).filter(
    (record) => record.path !== SOURCE_ATTESTATION_NAME
  );
  if (canonicalJson(actualOutputs) !== canonicalJson(attestation.outputs)) {
    fail("Renderer output differs from its exact-source build attestation");
  }
  return {
    inputs: attestation.inputs.length,
    inputsSha256: attestation.inputsSha256,
    packageLockSha256: attestation.source.packageLockSha256,
    builder: {
      name: attestation.builder.name,
      version: attestation.builder.version,
      reactPluginVersion: attestation.builder.reactPluginVersion,
      nodeVersion: attestation.builder.nodeVersion,
      npmVersion: attestation.builder.npmVersion,
      installedContentSha256: attestation.builder.installedContentSha256
    },
    outputs: attestation.outputs.map((record) => ({ ...record }))
  };
}

function copyAttestedOutputs(source, destination, expectedOutputs) {
  const copied = [];
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  for (const expected of expectedOutputs) {
    const sourcePath = path.join(source, ...expected.path.split("/"));
    const targetPath = path.join(destination, ...expected.path.split("/"));
    fs.mkdirSync(path.dirname(targetPath), { recursive: true, mode: 0o700 });
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
        before.nlink !== 1 ||
        before.size !== expected.size
      ) {
        fail("Renderer source output capability is unsafe");
      }
      targetDescriptor = fs.openSync(
        targetPath,
        fs.constants.O_WRONLY |
          fs.constants.O_CREAT |
          fs.constants.O_EXCL |
          fs.constants.O_NOFOLLOW,
        0o600
      );
      const digest = crypto.createHash("sha256");
      let copiedBytes = 0;
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
            fail("Renderer staged output write did not make progress");
          }
          offset += written;
        }
        copiedBytes += count;
      }
      fs.fsyncSync(targetDescriptor);
      const after = fs.fstatSync(sourceDescriptor);
      if (
        after.dev !== before.dev ||
        after.ino !== before.ino ||
        after.mode !== before.mode ||
        after.nlink !== before.nlink ||
        after.size !== before.size ||
        copiedBytes !== expected.size ||
        digest.digest("hex") !== expected.sha256
      ) {
        fail("Renderer source output changed while it was copied");
      }
      copied.push({ ...expected });
    } catch (error) {
      if (error instanceof RendererStageError) {
        throw error;
      }
      fail("Renderer source output could not be copied safely");
    } finally {
      if (targetDescriptor !== undefined) {
        fs.closeSync(targetDescriptor);
      }
      if (sourceDescriptor !== undefined) {
        fs.closeSync(sourceDescriptor);
      }
    }
  }
  const actual = inventory(destination);
  if (canonicalJson(actual) !== canonicalJson(copied)) {
    fail("Renderer staged output differs from its exact-source attestation");
  }
  return actual;
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

function stageRendererTransaction(
  {
    source,
    destination,
    release,
    environment,
    afterSourceValidation
  },
  dependencies = {}
) {
  const validateSource =
    dependencies.validateSourceAttestation || validateSourceAttestation;
  const auditStagedRenderer = dependencies.auditRenderer || auditRenderer;
  const rename = dependencies.rename || fs.renameSync;
  const sourceFiles = inventory(source);
  if (sourceFiles.some((record) => record.path === MANIFEST_NAME)) {
    fail("Web production build contains a reserved renderer manifest");
  }
  const sourceBuild = validateSource(source, release, environment);
  if (typeof afterSourceValidation === "function") {
    afterSourceValidation();
  }

  const parent = path.dirname(destination);
  fs.mkdirSync(parent, { recursive: true, mode: 0o755 });
  const temporary = fs.mkdtempSync(path.join(parent, ".renderer-stage-"));
  let previous;
  let published = false;
  try {
    const copiedOutputs = copyAttestedOutputs(
      source,
      temporary,
      sourceBuild.outputs
    );
    const revalidatedSourceBuild = validateSource(
      source,
      release,
      environment
    );
    if (
      canonicalJson(revalidatedSourceBuild) !== canonicalJson(sourceBuild)
    ) {
      fail("Renderer source attestation changed while it was staged");
    }
    const manifest = {
      schemaVersion: 1,
      kind: MANIFEST_KIND,
      source: {
        repositoryCommit: release.commit,
        repositoryTree: release.tree,
        sourceSnapshotSha256: release.sourceSnapshotSha256,
        sourceDateEpoch: release.sourceDateEpoch,
        packageLockSha256: sourceBuild.packageLockSha256,
        inputSnapshotSha256: sourceBuild.inputsSha256,
        inputFiles: sourceBuild.inputs
      },
      builder: { ...sourceBuild.builder },
      files: copiedOutputs
    };
    fs.writeFileSync(
      path.join(temporary, MANIFEST_NAME),
      `${canonicalJson(manifest)}\n`,
      { encoding: "utf8", mode: 0o644, flag: "wx" }
    );
    normalizeTree(temporary, release.sourceDateEpoch);
    auditStagedRenderer(temporary, {
      expectedCommit: release.commit,
      expectedTree: release.tree,
      expectedSourceSnapshotSha256: release.sourceSnapshotSha256,
      expectedSourceDateEpoch: release.sourceDateEpoch,
      expectedPackageLockSha256: release.rendererPackageLockSha256
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
      previous = path.join(
        parent,
        `.renderer-previous-${crypto.randomBytes(16).toString("hex")}`
      );
      rename(destination, previous);
    }
    let summary;
    try {
      rename(temporary, destination);
      published = true;
      summary = auditStagedRenderer(destination, {
        expectedCommit: release.commit,
        expectedTree: release.tree,
        expectedSourceSnapshotSha256: release.sourceSnapshotSha256,
        expectedSourceDateEpoch: release.sourceDateEpoch,
        expectedPackageLockSha256: release.rendererPackageLockSha256
      });
    } catch (publishError) {
      let rollbackFailed = false;
      if (published) {
        try {
          rename(destination, temporary);
          published = false;
        } catch {
          rollbackFailed = true;
        }
      }
      if (previous !== undefined) {
        try {
          rename(previous, destination);
          previous = undefined;
        } catch {
          rollbackFailed = true;
        }
      }
      if (rollbackFailed) {
        fail("Renderer staging publish rollback failed");
      }
      throw publishError;
    }
    if (previous !== undefined) {
      try {
        fs.rmSync(previous, { recursive: true });
        previous = undefined;
      } catch {
        fail("Renderer previous staging cleanup failed");
      }
    }
    return summary;
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
}

function stageRenderer({
  sourceRoot = SOURCE_ROOT,
  destinationRoot = DESTINATION_ROOT,
  environment = process.env,
  afterSourceValidation
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
  return stageRendererTransaction({
    source,
    destination,
    release,
    environment,
    afterSourceValidation
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

module.exports = {
  RendererStageError,
  copyAttestedOutputs,
  selectSourceCommit,
  stageRenderer,
  stageRendererTransaction,
  validateProvenance,
  validateSourceAttestation
};

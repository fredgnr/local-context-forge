"use strict";

const fs = require("node:fs");
const { createRequire } = require("node:module");
const path = require("node:path");
const {
  canonicalJson,
  fail,
  requireRegularFile,
  sha256Bytes,
  sha256File,
  writeCanonicalJson
} = require("./packagingAuditCommon.cjs");
const prepare = require("./prepareEngineeringSmoke.cjs");
const {
  verifyNodeInstallSeal
} = require("../../tools/exact_node_install.cjs");

const REPOSITORY_ROOT = path.resolve(__dirname, "..", "..");
const DESKTOP_ROOT = path.join(REPOSITORY_ROOT, "desktop");
const BUILD_ROOT = path.join(
  DESKTOP_ROOT,
  "generated",
  "engineering-smoke",
  "build"
);
const BUILD_MAIN = path.join(BUILD_ROOT, "dist", "main", "index.js");
const BUILD_PRELOAD = path.join(
  BUILD_ROOT,
  "dist",
  "preload",
  "index.cjs"
);
const BUILD_ATTESTATION = path.join(BUILD_ROOT, "entrypoint-build.json");
const ENTRYPOINT_KIND = "engineering-smoke-entrypoint-build";
const ESBUILD_VERSION = "0.28.1";
const EXPECTED_NODE_VERSION = "v22.23.2";
const EXPECTED_NPM_VERSION = "10.9.8";
const SOURCE_PREFIX = "desktop/src/";
const TSCONFIG_PATH = "desktop/tsconfig.json";
const MAX_INPUT_FILE_BYTES = 4 * 1024 * 1024;
const MAX_INPUT_TOTAL_BYTES = 32 * 1024 * 1024;

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

function sourceRecordPayload(record) {
  return {
    mode: record.mode,
    objectId: record.objectId,
    path: record.path,
    type: record.type
  };
}

function selectReviewedInputs(snapshot, repositoryRoot) {
  if (!Array.isArray(snapshot.inventory)) {
    fail("Engineering-smoke exact source inventory is missing");
  }
  const records = snapshot.inventory.filter(
    (record) => record.path === TSCONFIG_PATH || record.path.startsWith(SOURCE_PREFIX)
  );
  const byPath = new Map();
  const bytesByPath = new Map();
  let totalBytes = 0;
  for (const record of records) {
    if (
      !record ||
      record.type !== "blob" ||
      !["100644", "100755"].includes(record.mode) ||
      typeof record.path !== "string" ||
      typeof record.objectId !== "string" ||
      byPath.has(record.path)
    ) {
      fail("Engineering-smoke reviewed entrypoint source inventory is unsafe");
    }
    const bytes = prepare.readReviewedGitBlob(repositoryRoot, record.objectId);
    totalBytes += bytes.length;
    if (bytes.length > MAX_INPUT_FILE_BYTES || totalBytes > MAX_INPUT_TOTAL_BYTES) {
      fail("Engineering-smoke reviewed entrypoint source exceeds its size bound");
    }
    byPath.set(record.path, record);
    bytesByPath.set(record.path, Buffer.from(bytes));
  }
  for (const required of [
    TSCONFIG_PATH,
    "desktop/src/main/index.ts",
    "desktop/src/preload/index.ts"
  ]) {
    if (!byPath.has(required)) {
      fail("Engineering-smoke reviewed entrypoint source is incomplete");
    }
  }
  return { byPath, bytesByPath };
}

function resolveReviewedImport(specifier, importer, byPath) {
  if (!specifier.startsWith(".")) {
    fail("Engineering-smoke entrypoint source imports an unreviewed package");
  }
  const base = path.posix.normalize(
    path.posix.join(path.posix.dirname(importer), specifier)
  );
  if (
    !base.startsWith(SOURCE_PREFIX) ||
    base.includes("\\") ||
    base.split("/").some((part) => part === "" || part === "." || part === "..")
  ) {
    fail("Engineering-smoke entrypoint import escapes the reviewed source closure");
  }
  const candidates = path.posix.extname(base)
    ? [base]
    : [
        `${base}.ts`,
        `${base}.tsx`,
        `${base}.js`,
        `${base}.jsx`,
        `${base}.json`,
        `${base}/index.ts`,
        `${base}/index.tsx`,
        `${base}/index.js`,
        `${base}/index.jsx`,
        `${base}/index.json`
      ];
  const matches = candidates.filter((candidate) => byPath.has(candidate));
  if (matches.length !== 1) {
    fail("Engineering-smoke entrypoint import is missing or ambiguous");
  }
  return matches[0];
}

function reviewedSourcePlugin(byPath, bytesByPath, loadedPaths) {
  return {
    name: "lcf-reviewed-git-source",
    setup(build) {
      build.onResolve({ filter: /^lcf-reviewed:/ }, (arguments_) => {
        const reviewedPath = arguments_.path.slice("lcf-reviewed:".length);
        if (!byPath.has(reviewedPath)) {
          fail("Engineering-smoke reviewed entrypoint is missing");
        }
        return { path: reviewedPath, namespace: "lcf-reviewed" };
      });
      build.onResolve(
        { filter: /.*/, namespace: "lcf-reviewed" },
        (arguments_) => {
          if (arguments_.path === "electron" || arguments_.path.startsWith("node:")) {
            return { path: arguments_.path, external: true };
          }
          return {
            path: resolveReviewedImport(arguments_.path, arguments_.importer, byPath),
            namespace: "lcf-reviewed"
          };
        }
      );
      build.onLoad(
        { filter: /.*/, namespace: "lcf-reviewed" },
        (arguments_) => {
          const bytes = bytesByPath.get(arguments_.path);
          if (!bytes) {
            fail("Engineering-smoke reviewed entrypoint bytes are missing");
          }
          loadedPaths.add(arguments_.path);
          const extension = path.posix.extname(arguments_.path);
          const loader = extension === ".json" ? "json" : extension.slice(1);
          if (!["ts", "tsx", "js", "jsx", "json"].includes(loader)) {
            fail("Engineering-smoke reviewed entrypoint loader is unsupported");
          }
          return { contents: bytes, loader };
        }
      );
    }
  };
}

function validateSameSource(before, after) {
  for (const field of [
    "commit",
    "tree",
    "sourceDateEpoch",
    "sourceSnapshotSha256",
    "rendererPackageLockSha256",
    "desktopPackageSha256"
  ]) {
    if (before[field] !== after[field]) {
      fail("Engineering-smoke source changed during exact entrypoint build");
    }
  }
}

async function buildEntrypointsFromSnapshot(options) {
  const {
    snapshot,
    repositoryRoot,
    buildRoot,
    environment,
    esbuildImplementation,
    installSummary,
    afterInputsCaptured
  } = options;
  if (
    esbuildImplementation.version !== ESBUILD_VERSION ||
    !installSummary ||
    !/^[0-9a-f]{64}$/.test(installSummary.lockSha256 || "") ||
    !/^[0-9a-f]{64}$/.test(installSummary.installedContentSha256 || "") ||
    installSummary.nodeVersion !== EXPECTED_NODE_VERSION ||
    installSummary.npmVersion !== EXPECTED_NPM_VERSION
  ) {
    fail("Engineering-smoke entrypoint builder version differs from its lock");
  }
  const { byPath, bytesByPath } = selectReviewedInputs(snapshot, repositoryRoot);
  if (typeof afterInputsCaptured === "function") {
    await afterInputsCaptured();
  }
  const loadedPaths = new Set();
  const plugin = reviewedSourcePlugin(byPath, bytesByPath, loadedPaths);
  const mainPath = path.join(buildRoot, "dist", "main", "index.js");
  const preloadPath = path.join(buildRoot, "dist", "preload", "index.cjs");
  const common = {
    bundle: true,
    platform: "node",
    format: "cjs",
    target: "node22",
    external: ["electron"],
    logLevel: "silent",
    plugins: [plugin],
    tsconfigRaw: bytesByPath.get(TSCONFIG_PATH).toString("utf8"),
    write: true
  };
  await esbuildImplementation.build({
    ...common,
    entryPoints: ["lcf-reviewed:desktop/src/main/index.ts"],
    define: {
      __LCF_DISTRIBUTION_PROFILE__: JSON.stringify("engineering-smoke")
    },
    outfile: mainPath
  });
  await esbuildImplementation.build({
    ...common,
    entryPoints: ["lcf-reviewed:desktop/src/preload/index.ts"],
    outfile: preloadPath
  });
  const after = prepare.inspectRepositoryProvenance(repositoryRoot, environment);
  validateSameSource(snapshot, after);
  const mainInfo = requireRegularFile(mainPath, "Engineering-smoke Main bundle");
  const preloadInfo = requireRegularFile(
    preloadPath,
    "Engineering-smoke preload bundle"
  );
  if (mainInfo.nlink !== 1 || preloadInfo.nlink !== 1) {
    fail("Engineering-smoke entrypoint output is linked");
  }
  const inputs = [...loadedPaths, TSCONFIG_PATH]
    .sort(compareCodePoints)
    .map((sourcePath) => sourceRecordPayload(byPath.get(sourcePath)));
  const inputsSha256 = sha256Bytes(Buffer.from(canonicalJson(inputs), "utf8"));
  const attestation = {
    schemaVersion: 1,
    kind: ENTRYPOINT_KIND,
    source: {
      commit: snapshot.commit,
      tree: snapshot.tree,
      sourceSnapshotSha256: snapshot.sourceSnapshotSha256
    },
    builder: {
      name: "esbuild",
      version: ESBUILD_VERSION,
      nodeVersion: installSummary.nodeVersion,
      npmVersion: installSummary.npmVersion,
      packageLockSha256: installSummary.lockSha256,
      installedContentSha256: installSummary.installedContentSha256
    },
    inputs,
    inputsSha256,
    outputs: {
      main: {
        path: "dist/main/index.js",
        sha256: sha256File(mainPath),
        bytes: mainInfo.size
      },
      preload: {
        path: "dist/preload/index.cjs",
        sha256: sha256File(preloadPath),
        bytes: preloadInfo.size
      }
    }
  };
  writeCanonicalJson(path.join(buildRoot, "entrypoint-build.json"), attestation);
  validateSameSource(
    snapshot,
    prepare.inspectRepositoryProvenance(repositoryRoot, environment)
  );
  return attestation;
}

function loadExactInstalledModule(packageRoot, specifier) {
  const nodeModulesRoot = fs.realpathSync.native(
    path.join(packageRoot, "node_modules")
  );
  const requireFromPackage = createRequire(path.join(packageRoot, "package.json"));
  let resolved;
  try {
    resolved = fs.realpathSync.native(requireFromPackage.resolve(specifier));
  } catch {
    fail("Engineering-smoke installed builder module is unavailable");
  }
  if (!resolved.startsWith(`${nodeModulesRoot}${path.sep}`)) {
    fail("Engineering-smoke installed builder module escaped its seal");
  }
  return requireFromPackage(resolved);
}

async function buildEngineeringSmokeEntrypoints(options = {}) {
  const environment = options.environment || process.env;
  const platformName = options.platform || process.platform;
  const architecture = options.architecture || process.arch;
  prepare.validateHost(platformName, architecture);
  prepare.assertEngineeringSmokeMode(environment);
  prepare.assertNoProductionEnvironment(environment);
  const snapshot = prepare.inspectRepositorySourceSnapshot(
    REPOSITORY_ROOT,
    environment
  );
  prepare.initializeBuildStaging({
    environment,
    platform: platformName,
    architecture,
    inspectRepository: () => {
      const { inventory: _inventory, ...provenance } = snapshot;
      return provenance;
    }
  });
  const sealPath = environment.LCF_DESKTOP_NODE_INSTALL_SEAL;
  if (!path.isAbsolute(sealPath || "")) {
    fail("Engineering-smoke Desktop Node install seal is missing");
  }
  const installBefore = verifyNodeInstallSeal({
    repositoryRoot: REPOSITORY_ROOT,
    packageName: "desktop",
    sealPath,
    snapshot
  });
  const esbuildImplementation = options.esbuildImplementation ||
    loadExactInstalledModule(DESKTOP_ROOT, "esbuild");
  const attestation = await buildEntrypointsFromSnapshot({
    snapshot,
    repositoryRoot: REPOSITORY_ROOT,
    buildRoot: BUILD_ROOT,
    environment,
    esbuildImplementation,
    installSummary: installBefore,
    afterInputsCaptured: options.afterInputsCaptured
  });
  const installAfter = verifyNodeInstallSeal({
    repositoryRoot: REPOSITORY_ROOT,
    packageName: "desktop",
    sealPath,
    snapshot
  });
  if (canonicalJson(installAfter) !== canonicalJson(installBefore)) {
    fail("Engineering-smoke Desktop Node install changed during build");
  }
  return attestation;
}

async function main(argv = process.argv.slice(2)) {
  if (argv.length !== 0) {
    fail("Usage: buildEngineeringSmokeEntrypoints.cjs");
  }
  const attestation = await buildEngineeringSmokeEntrypoints();
  process.stdout.write(
    `${canonicalJson({
      kind: attestation.kind,
      source: attestation.source,
      inputsSha256: attestation.inputsSha256,
      outputs: attestation.outputs
    })}\n`
  );
}

if (require.main === module) {
  main().catch((error) => {
    const message =
      error && typeof error.message === "string"
        ? error.message
        : "Engineering-smoke exact entrypoint build failed unexpectedly";
    process.stderr.write(`engineering-smoke entrypoint build failed: ${message}\n`);
    process.exitCode = 1;
  });
}

module.exports = {
  BUILD_ATTESTATION,
  BUILD_MAIN,
  BUILD_PRELOAD,
  BUILD_ROOT,
  ENTRYPOINT_KIND,
  ESBUILD_VERSION,
  buildEngineeringSmokeEntrypoints,
  buildEntrypointsFromSnapshot,
  resolveReviewedImport,
  selectReviewedInputs
};

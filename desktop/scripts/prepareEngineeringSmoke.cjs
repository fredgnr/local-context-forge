"use strict";

const childProcess = require("node:child_process");
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
const APP_STAGING_ROOT = path.join(ENGINEERING_ROOT, "app");
const DISTRIBUTION_MANIFEST = path.join(
  ENGINEERING_ROOT,
  "distribution.json"
);
const RENDERER_ROOT = path.join(DESKTOP_ROOT, "resources", "renderer");
const SIDECAR_ROOT = path.join(DESKTOP_ROOT, "generated", "sidecar");
const SCHEMA_PATH = path.join(
  REPOSITORY_ROOT,
  "runtime",
  MANIFEST_SCHEMA_NAME
);
const PACKAGE_PATH = path.join(DESKTOP_ROOT, "package.json");
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

function runGit(arguments_, repositoryRoot = REPOSITORY_ROOT) {
  try {
    return childProcess
      .execFileSync("/usr/bin/git", ["-C", repositoryRoot, ...arguments_], {
        encoding: "utf8",
        env: { PATH: "/usr/bin:/bin", LANG: "C", LC_ALL: "C" },
        stdio: ["ignore", "pipe", "pipe"],
        timeout: 30_000,
        maxBuffer: 4 * 1024 * 1024
      })
      .trim();
  } catch {
    fail("Engineering-smoke Git provenance inspection failed");
  }
}

function selectedSourceCommit(environment) {
  const commit = (
    environment.LCF_SOURCE_SHA || environment.GITHUB_SHA || ""
  ).toLowerCase();
  if (!COMMIT_PATTERN.test(commit)) {
    fail("Engineering-smoke source commit is missing or invalid");
  }
  return commit;
}

function inspectRepositoryProvenance(
  repositoryRoot = REPOSITORY_ROOT,
  environment = process.env
) {
  const commit = runGit(["rev-parse", "HEAD"], repositoryRoot).toLowerCase();
  const tree = runGit(["rev-parse", "HEAD^{tree}"], repositoryRoot).toLowerCase();
  const sourceDateEpoch = Number(
    runGit(["show", "-s", "--format=%ct", "HEAD"], repositoryRoot)
  );
  if (
    commit !== selectedSourceCommit(environment) ||
    !COMMIT_PATTERN.test(tree) ||
    !Number.isSafeInteger(sourceDateEpoch) ||
    sourceDateEpoch < 100_000_000 ||
    String(sourceDateEpoch) !== environment.LCF_SOURCE_DATE_EPOCH ||
    runGit(["status", "--porcelain", "--untracked-files=all"], repositoryRoot) !== ""
  ) {
    fail("Engineering-smoke assembly requires a clean exact checkout");
  }
  return { commit, tree, sourceDateEpoch };
}

function assertNoProductionEnvironment(environment) {
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
    const source = (
      dependencies.inspectRepository || inspectRepositoryProvenance
    )(REPOSITORY_ROOT, environment);
    const auditEnvironment = {
      ...environment,
      GITHUB_SHA: source.commit
    };
    const renderer = (dependencies.auditRenderer || auditRenderer)(
      RENDERER_ROOT,
      {
        expectedCommit: source.commit,
        expectedSourceDateEpoch: source.sourceDateEpoch
      }
    );
    const python = (
      dependencies.auditPythonSidecar || auditPythonSidecar
    )({
      repositoryRoot: REPOSITORY_ROOT,
      stagingRoot: SIDECAR_ROOT,
      environment: auditEnvironment,
      platform: platformName,
      architecture
    });
    const packageMetadata = loadJson(PACKAGE_PATH, "Desktop package metadata");
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
    const mainInfo = requireRegularFile(
      BUILD_MAIN,
      "Engineering-smoke Main bundle"
    );
    const preloadInfo = requireRegularFile(
      BUILD_PRELOAD,
      "Engineering-smoke preload bundle"
    );
    const rendererManifest = path.join(
      RENDERER_ROOT,
      "renderer-build-manifest.json"
    );
    const pythonManifestPath = path.join(SIDECAR_ROOT, "build-manifest.json");
    const pythonManifest = loadJson(
      pythonManifestPath,
      "Python sidecar build manifest"
    );
    const schema = loadJson(SCHEMA_PATH, "Engineering-smoke manifest schema");
    const manifest = createDistributionManifest({
      source,
      version: packageMetadata.version,
      desktopApp: {
        asarPath: "Contents/Resources/app.asar",
        mainPath: "dist/main/index.js",
        mainSha256: sha256File(BUILD_MAIN),
        mainBytes: mainInfo.size,
        preloadPath: "dist/preload/index.cjs",
        preloadSha256: sha256File(BUILD_PRELOAD),
        preloadBytes: preloadInfo.size,
        packagePath: "package.json",
        packageSha256: sha256Bytes(stagedPackageBytes),
        packageBytes: stagedPackageBytes.length
      },
      renderer,
      rendererManifestSha256: sha256File(rendererManifest),
      python,
      pythonManifest,
      pythonManifestSha256: sha256File(pythonManifestPath)
    });
    validateEngineeringSmokeManifest(manifest, schema);

    const temporaryRoot = fs.mkdtempSync(
      path.join(ENGINEERING_ROOT, ".prepared-")
    );
    const temporaryApp = path.join(temporaryRoot, "app");
    const temporaryManifest = path.join(temporaryRoot, "distribution.json");
    try {
      fs.mkdirSync(path.join(temporaryApp, "dist", "main"), {
        recursive: true,
        mode: 0o755
      });
      fs.mkdirSync(path.join(temporaryApp, "dist", "preload"), {
        recursive: true,
        mode: 0o755
      });
      fs.copyFileSync(
        BUILD_MAIN,
        path.join(temporaryApp, "dist", "main", "index.js"),
        fs.constants.COPYFILE_EXCL
      );
      fs.copyFileSync(
        BUILD_PRELOAD,
        path.join(temporaryApp, "dist", "preload", "index.cjs"),
        fs.constants.COPYFILE_EXCL
      );
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

      for (const candidate of [APP_STAGING_ROOT, DISTRIBUTION_MANIFEST]) {
        if (!fs.existsSync(candidate)) {
          continue;
        }
        const info = fs.lstatSync(candidate);
        if (info.isSymbolicLink()) {
          fail("Existing engineering-smoke staging target is unsafe");
        }
        fs.rmSync(candidate, { recursive: info.isDirectory() });
      }
      fs.renameSync(temporaryApp, APP_STAGING_ROOT);
      fs.renameSync(temporaryManifest, DISTRIBUTION_MANIFEST);
    } finally {
      fs.rmSync(temporaryRoot, { recursive: true, force: true });
    }
    return {
      kind: MANIFEST_KIND,
      source: { commit: source.commit, tree: source.tree },
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
  DISTRIBUTION_MANIFEST,
  ENGINEERING_ROOT,
  FORBIDDEN_PRODUCTION_ENVIRONMENT,
  assertNoProductionEnvironment,
  assertEngineeringSmokeMode,
  createDistributionManifest,
  createPrepareEngineeringSmoke,
  initializeBuildStaging,
  inspectRepositoryProvenance,
  preflightEngineeringSmoke,
  requireSafeGeneratedRoot,
  selectedSourceCommit,
  validateHost
};

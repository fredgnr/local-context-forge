"use strict";

const path = require("node:path");
const { auditRenderer } = require("./auditRenderer.cjs");
const { auditPythonSidecar } = require("./beforePack.cjs");
const {
  APP_ID,
  PRODUCT_NAME,
  loadCanonicalJson,
  loadJson,
  requireRealDirectory,
  requireRegularFile,
  sha256File,
  validateEngineeringSmokeManifest
} = require("./packagingAuditCommon.cjs");
const {
  APP_STAGING_ROOT,
  BUILD_MAIN,
  BUILD_PRELOAD,
  DISTRIBUTION_MANIFEST,
  assertEngineeringSmokeMode,
  assertNoProductionEnvironment,
  inspectRepositoryProvenance,
  validateHost
} = require("./prepareEngineeringSmoke.cjs");

const REPOSITORY_ROOT = path.resolve(__dirname, "..", "..");
const DESKTOP_ROOT = path.join(REPOSITORY_ROOT, "desktop");
const RENDERER_ROOT = path.join(DESKTOP_ROOT, "resources", "renderer");
const SIDECAR_ROOT = path.join(DESKTOP_ROOT, "generated", "sidecar");
const SCHEMA_PATH = path.join(
  REPOSITORY_ROOT,
  "runtime",
  "engineering-smoke-manifest.schema.json"
);

function assertContext(context) {
  if (!context || context.electronPlatformName !== "darwin") {
    throw new TypeError("Engineering-smoke beforePack requires Darwin");
  }
  if (context.arch !== 3 && context.arch !== "arm64") {
    throw new TypeError("Engineering-smoke beforePack requires arm64");
  }
  const productFilename = context.packager?.appInfo?.productFilename;
  if (productFilename !== PRODUCT_NAME) {
    throw new TypeError("Engineering-smoke product filename is invalid");
  }
  const configuration = context.packager?.config;
  if (
    configuration &&
    Object.prototype.hasOwnProperty.call(configuration, "publish") &&
    configuration.publish !== null
  ) {
    throw new TypeError("Engineering-smoke publishing must remain disabled");
  }
}

function comparePreparedManifest(
  manifest,
  source,
  renderer,
  python,
  pythonManifest
) {
  const stagedMain = path.join(
    APP_STAGING_ROOT,
    "dist",
    "main",
    "index.js"
  );
  const stagedPreload = path.join(
    APP_STAGING_ROOT,
    "dist",
    "preload",
    "index.cjs"
  );
  const stagedPackage = path.join(APP_STAGING_ROOT, "package.json");
  const desktopApp = manifest.components.desktopApp;
  const mainInfo = requireRegularFile(stagedMain, "Staged Main");
  const preloadInfo = requireRegularFile(stagedPreload, "Staged preload");
  const packageInfo = requireRegularFile(
    stagedPackage,
    "Staged package metadata"
  );
  const rendererManifestPath = path.join(
    RENDERER_ROOT,
    "renderer-build-manifest.json"
  );
  const pythonManifestPath = path.join(SIDECAR_ROOT, "build-manifest.json");
  if (
    manifest.application.appId !== APP_ID ||
    manifest.application.productName !== PRODUCT_NAME ||
    desktopApp.mainSha256 !== sha256File(BUILD_MAIN) ||
    desktopApp.mainSha256 !== sha256File(stagedMain) ||
    desktopApp.mainBytes !== mainInfo.size ||
    desktopApp.preloadSha256 !== sha256File(BUILD_PRELOAD) ||
    desktopApp.preloadSha256 !== sha256File(stagedPreload) ||
    desktopApp.preloadBytes !== preloadInfo.size ||
    desktopApp.packageSha256 !== sha256File(stagedPackage) ||
    desktopApp.packageBytes !== packageInfo.size ||
    manifest.source.commit !== source.commit ||
    manifest.source.tree !== source.tree ||
    manifest.source.sourceDateEpoch !== source.sourceDateEpoch ||
    manifest.components.renderer.manifestSha256 !==
      sha256File(rendererManifestPath) ||
    manifest.components.renderer.files !== renderer.files ||
    manifest.components.renderer.bytes !== renderer.bytes ||
    manifest.components.pythonSidecar.manifestSha256 !==
      sha256File(pythonManifestPath) ||
    manifest.components.pythonSidecar.normalizedInventorySha256 !==
      pythonManifest.audit.normalizedInventorySha256 ||
    manifest.components.pythonSidecar.files !== python.files ||
    manifest.components.pythonSidecar.nativeFiles !== python.nativeFiles ||
    manifest.components.pythonSidecar.components !== python.components
  ) {
    throw new TypeError(
      "Engineering-smoke prepared manifest differs from audited staging"
    );
  }
}

function createBeforePackEngineeringSmoke(dependencies = {}) {
  return async function beforePackEngineeringSmoke(context) {
    assertContext(context);
    const environment = dependencies.environment || process.env;
    const platformName = dependencies.platform || process.platform;
    const architecture = dependencies.architecture || process.arch;
    validateHost(platformName, architecture);
    assertEngineeringSmokeMode(environment);
    assertNoProductionEnvironment(environment);
    requireRealDirectory(APP_STAGING_ROOT, "Engineering-smoke app staging root");
    for (const [candidate, label] of [
      [BUILD_MAIN, "Engineering-smoke build Main"],
      [BUILD_PRELOAD, "Engineering-smoke build preload"],
      [path.join(APP_STAGING_ROOT, "dist", "main", "index.js"), "Staged Main"],
      [
        path.join(APP_STAGING_ROOT, "dist", "preload", "index.cjs"),
        "Staged preload"
      ],
      [path.join(APP_STAGING_ROOT, "package.json"), "Staged package metadata"]
    ]) {
      requireRegularFile(candidate, label);
    }
    const source = (
      dependencies.inspectRepository || inspectRepositoryProvenance
    )(REPOSITORY_ROOT, environment);
    const auditEnvironment = { ...environment, GITHUB_SHA: source.commit };
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
    const schema = loadJson(SCHEMA_PATH, "Engineering-smoke manifest schema");
    const manifest = loadCanonicalJson(
      DISTRIBUTION_MANIFEST,
      "Prepared engineering-smoke manifest"
    );
    validateEngineeringSmokeManifest(manifest, schema);
    const pythonManifest = loadJson(
      path.join(SIDECAR_ROOT, "build-manifest.json"),
      "Python sidecar build manifest"
    );
    comparePreparedManifest(
      manifest,
      source,
      renderer,
      python,
      pythonManifest
    );
    return {
      source: manifest.source,
      components: {
        renderer: renderer.files,
        pythonSidecar: python.files
      },
      validation: manifest.validation
    };
  };
}

const beforePackEngineeringSmoke = createBeforePackEngineeringSmoke();

module.exports = beforePackEngineeringSmoke;
module.exports.assertContext = assertContext;
module.exports.comparePreparedManifest = comparePreparedManifest;
module.exports.createBeforePackEngineeringSmoke =
  createBeforePackEngineeringSmoke;

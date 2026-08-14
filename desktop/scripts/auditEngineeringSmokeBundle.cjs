"use strict";

const childProcess = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const asar = require("@electron/asar");
const {
  getCurrentFuseWire,
  FuseState,
  FuseV1Options,
  FuseVersion
} = require("@electron/fuses");
const { auditRenderer } = require("./auditRenderer.cjs");
const { auditPythonSidecar } = require("./beforePack.cjs");
const {
  APP_ID,
  DISTRIBUTION_MARKER,
  MANIFEST_RELATIVE_PATH,
  PRODUCT_NAME,
  buildInventory,
  canonicalJson,
  fail,
  isContained,
  loadCanonicalJson,
  loadJson,
  normalizedInventorySha256,
  requireRealDirectory,
  requireRegularFile,
  sha256Bytes,
  sha256File,
  validateEngineeringSmokeManifest
} = require("./packagingAuditCommon.cjs");
const {
  assertEngineeringSmokeMode,
  assertNoProductionEnvironment,
  inspectRepositoryProvenance,
  validateHost
} = require("./prepareEngineeringSmoke.cjs");

const REPOSITORY_ROOT = path.resolve(__dirname, "..", "..");
const DESKTOP_ROOT = path.join(REPOSITORY_ROOT, "desktop");
const OUTPUT_ROOT = path.join(DESKTOP_ROOT, "release-smoke");
const APP_ROOT = path.join(
  OUTPUT_ROOT,
  "mac-arm64",
  `${PRODUCT_NAME}.app`
);
const EVIDENCE_PATH = path.join(
  OUTPUT_ROOT,
  "engineering-smoke-audit.json"
);
const SCHEMA_PATH = path.join(
  REPOSITORY_ROOT,
  "runtime",
  "engineering-smoke-manifest.schema.json"
);
const BUNDLED_MANIFEST_PATH =
  "Contents/Resources/engineering-smoke/distribution.json";
const MACHO_MAGICS = new Set([
  "cafebabe",
  "bebafeca",
  "cafebabf",
  "bfbafeca",
  "feedface",
  "cefaedfe",
  "feedfacf",
  "cffaedfe"
]);
const FORBIDDEN_RESOURCE_NAMES = Object.freeze([
  "qmd",
  "mcp",
  "companion",
  "node",
  "update",
  "models",
  "release"
]);
const EXPECTED_ASAR_ENTRIES = Object.freeze([
  "/dist",
  "/dist/main",
  "/dist/main/index.js",
  "/dist/preload",
  "/dist/preload/index.cjs",
  "/package.json"
]);
const ALLOWED_ELECTRON_HELPER_APPS = Object.freeze([
  `${PRODUCT_NAME} Helper.app`,
  `${PRODUCT_NAME} Helper (GPU).app`,
  `${PRODUCT_NAME} Helper (Plugin).app`,
  `${PRODUCT_NAME} Helper (Renderer).app`
]);
const REVIEWED_PYINSTALLER_ARCHIVE =
  "Contents/Resources/sidecar/_internal/base_library.zip";

function run(executable, arguments_, label) {
  try {
    return childProcess.execFileSync(executable, arguments_, {
      encoding: "utf8",
      env: { PATH: "/usr/bin:/bin", LANG: "C", LC_ALL: "C" },
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 120_000,
      maxBuffer: 16 * 1024 * 1024
    });
  } catch (error) {
    if (
      error &&
      typeof error === "object" &&
      Buffer.isBuffer(error.stderr)
    ) {
      error.stderr.fill(0);
    }
    fail(label);
  }
}

function runCodesign(arguments_, label) {
  try {
    return childProcess.execFileSync("/usr/bin/codesign", arguments_, {
      encoding: "utf8",
      env: { PATH: "/usr/bin:/bin", LANG: "C", LC_ALL: "C" },
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 120_000,
      maxBuffer: 16 * 1024 * 1024
    });
  } catch (error) {
    const stderr =
      error && typeof error === "object" && "stderr" in error
        ? String(error.stderr || "")
        : "";
    if (stderr.length > 0 && error && typeof error === "object") {
      error.stderr = "";
    }
    fail(label);
  }
}

function inspectInfoPlist(infoPlistPath) {
  const output = run(
    "/usr/bin/plutil",
    ["-convert", "json", "-o", "-", infoPlistPath],
    "Engineering-smoke Info.plist inspection failed"
  );
  let value;
  try {
    value = JSON.parse(output);
  } catch {
    fail("Engineering-smoke Info.plist is not valid JSON after inspection");
  }
  return value;
}

function validateInfoPlist(info, expectedVersion) {
  const expected = {
    CFBundleIdentifier: APP_ID,
    CFBundleName: PRODUCT_NAME,
    CFBundleDisplayName: PRODUCT_NAME,
    CFBundleExecutable: PRODUCT_NAME,
    CFBundlePackageType: "APPL",
    CFBundleShortVersionString: expectedVersion,
    CFBundleVersion: expectedVersion,
    LCFDistributionClass: "engineering-smoke",
    LCFDistributionMarker: DISTRIBUTION_MARKER,
    LCFEngineeringOnly: true,
    LCFPublishable: false,
    LCFUpdaterMode: "unavailable",
    LCFNetworkAllowed: false,
    LCFManualReleasePageAllowed: false,
    LCFPackagedAppLaunch: "not-run",
    LCFPackagedSmokeValidation: "not-run"
  };
  if (
    !info ||
    typeof expectedVersion !== "string" ||
    typeof info !== "object" ||
    Array.isArray(info) ||
    Object.entries(expected).some(([key, value]) => info[key] !== value)
  ) {
    fail("Engineering-smoke Info.plist identity or boundary marker is invalid");
  }
  return expected;
}

function validateAsarIntegrity(info, expectedHeaderSha256) {
  const expected = {
    "Resources/app.asar": {
      algorithm: "SHA256",
      hash: expectedHeaderSha256
    }
  };
  if (
    typeof expectedHeaderSha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(expectedHeaderSha256) ||
    canonicalJson(info?.ElectronAsarIntegrity) !== canonicalJson(expected)
  ) {
    fail("Engineering-smoke ElectronAsarIntegrity is invalid");
  }
  return expected;
}

function isMachO(filePath) {
  requireRegularFile(filePath, "Possible engineering-smoke Mach-O");
  let descriptor;
  try {
    descriptor = fs.openSync(filePath, "r");
    const magic = Buffer.alloc(4);
    const count = fs.readSync(descriptor, magic, 0, magic.length, 0);
    return count === 4 && MACHO_MAGICS.has(magic.toString("hex"));
  } finally {
    if (descriptor !== undefined) {
      fs.closeSync(descriptor);
    }
  }
}

function inspectMachOArchitectures(filePath) {
  const output = run(
    "/usr/bin/lipo",
    ["-archs", filePath],
    "Engineering-smoke Mach-O architecture inspection failed"
  ).trim();
  const architectures = output.split(/\s+/).filter(Boolean);
  if (
    architectures.length !== 1 ||
    architectures[0] !== "arm64"
  ) {
    fail("Engineering-smoke bundle contains a non-arm64 Mach-O");
  }
  return architectures;
}

function inspectCodeIdentity(appRoot) {
  runCodesign(
    ["--verify", "--deep", "--strict", "--verbose=4", appRoot],
    "Engineering-smoke code signature verification failed"
  );
  const inspected = childProcess.spawnSync(
    "/usr/bin/codesign",
    ["-d", "--verbose=4", appRoot],
    {
      encoding: "utf8",
      env: { PATH: "/usr/bin:/bin", LANG: "C", LC_ALL: "C" },
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 120_000,
      maxBuffer: 4 * 1024 * 1024
    }
  );
  if (inspected.status !== 0 || inspected.error) {
    fail("Engineering-smoke code identity inspection failed");
  }
  const output = `${inspected.stdout || ""}${inspected.stderr || ""}`;
  if (!output || !output.includes("Signature=adhoc")) {
    fail("Engineering-smoke app is not ad-hoc signed");
  }
  if (
    /(?:^|\n)Authority=/m.test(output) ||
    /(?:^|\n)TeamIdentifier=(?!not set)/m.test(output) ||
    /flags=.*\bruntime\b/i.test(output) ||
    /(?:^|\n)Timestamp=/m.test(output)
  ) {
    fail("Engineering-smoke app contains production signing semantics");
  }
  return { signing: "ad-hoc", hardenedRuntime: false, notarized: false };
}

async function inspectSecureFuses(executablePath, reader = getCurrentFuseWire) {
  const wire = await reader(executablePath);
  const expected = new Map([
    [FuseV1Options.RunAsNode, FuseState.DISABLE],
    [FuseV1Options.EnableCookieEncryption, FuseState.ENABLE],
    [FuseV1Options.EnableNodeOptionsEnvironmentVariable, FuseState.DISABLE],
    [FuseV1Options.EnableNodeCliInspectArguments, FuseState.DISABLE],
    [FuseV1Options.EnableEmbeddedAsarIntegrityValidation, FuseState.ENABLE],
    [FuseV1Options.OnlyLoadAppFromAsar, FuseState.ENABLE],
    [FuseV1Options.LoadBrowserProcessSpecificV8Snapshot, FuseState.ENABLE],
    [FuseV1Options.GrantFileProtocolExtraPrivileges, FuseState.DISABLE],
    [FuseV1Options.WasmTrapHandlers, FuseState.ENABLE]
  ]);
  if (
    wire.version !== FuseVersion.V1 ||
    [...expected].some(([option, state]) => wire[option] !== state)
  ) {
    fail("Engineering-smoke Electron secure fuses are incomplete");
  }
  return Object.fromEntries(
    [...expected].map(([option, state]) => [
      FuseV1Options[option],
      state === FuseState.ENABLE
    ])
  );
}

function assertResourceBoundary(resourcesRoot) {
  const forbiddenNames = new Set(FORBIDDEN_RESOURCE_NAMES);
  for (const name of fs.readdirSync(resourcesRoot)) {
    if (forbiddenNames.has(name.toLowerCase())) {
      fail("Engineering-smoke bundle contains an excluded resource class");
    }
  }
  const resourceNames = new Set(
    fs.readdirSync(resourcesRoot).map((name) => name.toLowerCase())
  );
  if (resourceNames.has("app") || resourceNames.has("app.asar.unpacked")) {
    fail("Engineering-smoke application code must be sealed in app.asar");
  }
  requireRegularFile(
    path.join(resourcesRoot, "app.asar"),
    "Engineering-smoke app.asar"
  );
}

function inspectAsarContents(
  asarPath,
  manifest,
  dependencies = {}
) {
  const listPackage = dependencies.listPackage || asar.listPackage;
  const extractFile = dependencies.extractFile || asar.extractFile;
  const getRawHeader = dependencies.getRawHeader || asar.getRawHeader;
  let entries;
  try {
    entries = listPackage(asarPath);
  } catch {
    fail("Engineering-smoke app.asar inventory inspection failed");
  }
  if (
    !Array.isArray(entries) ||
    canonicalJson([...entries].sort()) !==
      canonicalJson([...EXPECTED_ASAR_ENTRIES].sort())
  ) {
    fail("Engineering-smoke app.asar contains an unexpected entry");
  }
  let rawHeader;
  try {
    rawHeader = getRawHeader(asarPath);
  } catch {
    fail("Engineering-smoke app.asar header inspection failed");
  }
  if (
    !rawHeader ||
    typeof rawHeader.headerString !== "string" ||
    rawHeader.headerString.length === 0
  ) {
    fail("Engineering-smoke app.asar header is invalid");
  }
  const headerSha256 = sha256Bytes(
    Buffer.from(rawHeader.headerString, "utf8")
  );

  const desktopApp = manifest.components.desktopApp;
  const reviewed = [
    {
      path: desktopApp.mainPath,
      sha256: desktopApp.mainSha256,
      bytes: desktopApp.mainBytes
    },
    {
      path: desktopApp.preloadPath,
      sha256: desktopApp.preloadSha256,
      bytes: desktopApp.preloadBytes
    },
    {
      path: desktopApp.packagePath,
      sha256: desktopApp.packageSha256,
      bytes: desktopApp.packageBytes
    }
  ];
  const extracted = new Map();
  for (const item of reviewed) {
    let bytes;
    try {
      bytes = extractFile(asarPath, item.path);
    } catch {
      fail("Engineering-smoke app.asar extraction failed");
    }
    if (
      !Buffer.isBuffer(bytes) ||
      bytes.length !== item.bytes ||
      sha256Bytes(bytes) !== item.sha256
    ) {
      fail("Engineering-smoke app.asar differs from prepared Desktop bytes");
    }
    extracted.set(item.path, bytes);
  }

  let packageMetadata;
  const packageBytes = extracted.get(desktopApp.packagePath);
  try {
    packageMetadata = JSON.parse(packageBytes.toString("utf8"));
  } catch {
    fail("Engineering-smoke app.asar package metadata is invalid");
  }
  if (
    canonicalJson(packageMetadata) + "\n" !== packageBytes.toString("utf8") ||
    packageMetadata.name !== "local-context-forge-engineering-smoke" ||
    packageMetadata.version !== manifest.application.version ||
    packageMetadata.private !== true ||
    packageMetadata.main !== desktopApp.mainPath
  ) {
    fail("Engineering-smoke app.asar package metadata drifted");
  }
  return {
    entries: entries.length,
    headerSha256,
    mainSha256: desktopApp.mainSha256,
    preloadSha256: desktopApp.preloadSha256,
    packageSha256: desktopApp.packageSha256
  };
}

function assertNoInstallOrReleaseArtifacts(
  outputRoot,
  expectedAppRoot = APP_ROOT
) {
  const forbidden = [];
  const appBundles = [];
  const unexpectedNestedApps = [];
  const unexpectedSymlinks = [];
  let observedReviewedPyInstallerArchive = false;
  const expectedApp = path.resolve(expectedAppRoot);
  const expectedFrameworks = path.join(expectedApp, "Contents", "Frameworks");
  const allowedHelpers = new Set(ALLOWED_ELECTRON_HELPER_APPS);
  const observedHelpers = new Set();
  function visit(directory) {
    for (const name of fs.readdirSync(directory)) {
      const candidate = path.join(directory, name);
      const info = fs.lstatSync(candidate);
      const lower = name.toLowerCase();
      const resolvedCandidate = path.resolve(candidate);
      const appRelative = path
        .relative(expectedApp, resolvedCandidate)
        .split(path.sep)
        .join("/");
      const isReviewedPyInstallerArchive =
        appRelative === REVIEWED_PYINSTALLER_ARCHIVE &&
        info.isFile() &&
        !info.isSymbolicLink() &&
        info.nlink === 1 &&
        info.size > 0;
      if (isReviewedPyInstallerArchive) {
        observedReviewedPyInstallerArchive = true;
      }
      if (lower.endsWith(".app")) {
        if (
          resolvedCandidate === expectedApp ||
          !isContained(expectedApp, resolvedCandidate)
        ) {
          appBundles.push(candidate);
        } else if (
          path.dirname(resolvedCandidate) !== expectedFrameworks ||
          !allowedHelpers.has(name) ||
          !info.isDirectory() ||
          info.isSymbolicLink()
        ) {
          unexpectedNestedApps.push(candidate);
        } else {
          observedHelpers.add(name);
        }
      }
      if (
        lower.endsWith(".dmg") ||
        lower.endsWith(".pkg") ||
        (lower.endsWith(".zip") && !isReviewedPyInstallerArchive) ||
        lower.endsWith(".blockmap") ||
        /^(?:latest|alpha|beta|next)-mac\.yml$/.test(lower) ||
        lower === "release-manifest.json" ||
        lower === "update-manifest.json" ||
        lower === "update-manifest.json.sig"
      ) {
        forbidden.push(candidate);
      }
      if (info.isSymbolicLink()) {
        if (!isContained(expectedApp, resolvedCandidate)) {
          unexpectedSymlinks.push(candidate);
        }
        continue;
      }
      if (info.isDirectory()) {
        visit(candidate);
      }
    }
  }
  visit(outputRoot);
  if (forbidden.length > 0) {
    fail("Engineering-smoke output contains an install or release artifact");
  }
  if (unexpectedSymlinks.length > 0) {
    fail("Engineering-smoke output contains an unexpected symlink");
  }
  if (unexpectedNestedApps.length > 0) {
    fail("Engineering-smoke output contains an unexpected nested app");
  }
  if (!observedReviewedPyInstallerArchive) {
    fail("Engineering-smoke reviewed Python runtime archive is missing");
  }
  if (
    observedHelpers.size !== allowedHelpers.size ||
    [...allowedHelpers].some((name) => !observedHelpers.has(name))
  ) {
    fail("Engineering-smoke Electron helper app closure is incomplete");
  }
  if (
    appBundles.length !== 1 ||
    path.resolve(appBundles[0]) !== expectedApp
  ) {
    fail("Engineering-smoke output must contain exactly one canonical app");
  }
}

function writeExternalEvidence(evidencePath, evidence) {
  const temporary = `${evidencePath}.tmp`;
  if (fs.existsSync(temporary)) {
    const info = fs.lstatSync(temporary);
    if (!info.isFile() || info.isSymbolicLink()) {
      fail("Engineering-smoke evidence temporary path is unsafe");
    }
    fs.unlinkSync(temporary);
  }
  fs.writeFileSync(temporary, `${canonicalJson(evidence)}\n`, {
    encoding: "utf8",
    mode: 0o644,
    flag: "wx"
  });
  if (fs.existsSync(evidencePath)) {
    const info = fs.lstatSync(evidencePath);
    if (!info.isFile() || info.isSymbolicLink()) {
      fs.unlinkSync(temporary);
      fail("Engineering-smoke evidence destination is unsafe");
    }
    fs.unlinkSync(evidencePath);
  }
  fs.renameSync(temporary, evidencePath);
}

function createAuditEngineeringSmokeBundle(dependencies = {}) {
  return async function auditEngineeringSmokeBundle(options = {}) {
    const environment = options.environment || process.env;
    const platformName = options.platform || process.platform;
    const architecture = options.architecture || process.arch;
    validateHost(platformName, architecture);
    assertEngineeringSmokeMode(environment);
    assertNoProductionEnvironment(environment);
    const outputRoot = dependencies.outputRoot || OUTPUT_ROOT;
    const appRoot = dependencies.appRoot || APP_ROOT;
    requireRealDirectory(outputRoot, "Engineering-smoke output root");
    requireRealDirectory(appRoot, "Engineering-smoke app bundle");
    if (!isContained(outputRoot, appRoot)) {
      fail("Engineering-smoke app escapes its output root");
    }
    assertNoInstallOrReleaseArtifacts(outputRoot, appRoot);

    const source = (
      dependencies.inspectRepository || inspectRepositoryProvenance
    )(REPOSITORY_ROOT, environment);
    const contentsRoot = requireRealDirectory(
      path.join(appRoot, "Contents"),
      "Engineering-smoke Contents"
    );
    const resourcesRoot = requireRealDirectory(
      path.join(contentsRoot, "Resources"),
      "Engineering-smoke Resources"
    );
    const rendererRoot = requireRealDirectory(
      path.join(resourcesRoot, "renderer"),
      "Bundled renderer"
    );
    const sidecarRoot = requireRealDirectory(
      path.join(resourcesRoot, "sidecar"),
      "Bundled Python sidecar"
    );
    const markerRoot = requireRealDirectory(
      path.join(resourcesRoot, "engineering-smoke"),
      "Engineering-smoke marker directory"
    );
    assertResourceBoundary(resourcesRoot);
    const asarPath = path.join(resourcesRoot, "app.asar");

    const executablePath = path.join(
      contentsRoot,
      "MacOS",
      PRODUCT_NAME
    );
    requireRegularFile(executablePath, "Engineering-smoke Electron executable");
    const infoPlistPath = path.join(contentsRoot, "Info.plist");
    requireRegularFile(infoPlistPath, "Engineering-smoke Info.plist");
    const inspectPlist = dependencies.inspectInfoPlist || inspectInfoPlist;
    const inspectedInfo = inspectPlist(infoPlistPath);

    const schema = loadJson(SCHEMA_PATH, "Engineering-smoke manifest schema");
    const manifestPath = path.join(markerRoot, "distribution.json");
    if (
      BUNDLED_MANIFEST_PATH !== MANIFEST_RELATIVE_PATH ||
      path.relative(appRoot, manifestPath).split(path.sep).join("/") !==
      BUNDLED_MANIFEST_PATH
    ) {
      fail("Engineering-smoke manifest is not at its fixed bundle path");
    }
    const manifest = loadCanonicalJson(
      manifestPath,
      "Bundled engineering-smoke manifest"
    );
    validateEngineeringSmokeManifest(manifest, schema);
    const info = validateInfoPlist(
      inspectedInfo,
      manifest.application.version
    );
    if (
      manifest.source.commit !== source.commit ||
      manifest.source.tree !== source.tree ||
      manifest.source.sourceSnapshotSha256 !== source.sourceSnapshotSha256 ||
      manifest.source.sourceDateEpoch !== source.sourceDateEpoch ||
      manifest.components.desktopApp.reviewedPackagePath !==
        "desktop/package.json" ||
      manifest.components.desktopApp.reviewedPackageSha256 !==
        source.desktopPackageSha256
    ) {
      fail("Bundled engineering-smoke provenance differs from the checkout");
    }
    const desktopApp = inspectAsarContents(
      asarPath,
      manifest,
      dependencies.asar || {}
    );
    validateAsarIntegrity(inspectedInfo, desktopApp.headerSha256);

    const renderer = (dependencies.auditRenderer || auditRenderer)(
      rendererRoot,
      {
        expectedCommit: source.commit,
        expectedTree: source.tree,
        expectedSourceSnapshotSha256: source.sourceSnapshotSha256,
        expectedSourceDateEpoch: source.sourceDateEpoch,
        expectedPackageLockSha256: source.rendererPackageLockSha256
      }
    );
    const python = (
      dependencies.auditPythonSidecar || auditPythonSidecar
    )({
      repositoryRoot: REPOSITORY_ROOT,
      stagingRoot: sidecarRoot,
      environment,
      platform: platformName,
      architecture
    });
    const pythonManifest = python.manifest;
    if (
      !pythonManifest ||
      typeof pythonManifest !== "object" ||
      Array.isArray(pythonManifest)
    ) {
      fail("Bundled Python audit omitted its manifest attestation");
    }
    if (
      manifest.components.renderer.manifestSha256 !==
        sha256File(path.join(rendererRoot, "renderer-build-manifest.json")) ||
      manifest.components.renderer.files !== renderer.files ||
      manifest.components.renderer.bytes !== renderer.bytes ||
      manifest.components.renderer.repositoryTree !== renderer.repositoryTree ||
      manifest.components.renderer.sourceSnapshotSha256 !==
        renderer.sourceSnapshotSha256 ||
      manifest.components.renderer.inputSnapshotSha256 !==
        renderer.inputSnapshotSha256 ||
      manifest.components.pythonSidecar.manifestSha256 !==
        python.manifestSha256 ||
      manifest.components.pythonSidecar.normalizedInventorySha256 !==
        pythonManifest.audit.normalizedInventorySha256 ||
      manifest.components.pythonSidecar.repositoryTree !== source.tree ||
      manifest.components.pythonSidecar.sourceSnapshotSha256 !==
        source.sourceSnapshotSha256 ||
      manifest.components.pythonSidecar.pythonBuildToolchainPath !==
        "Contents/Resources/sidecar/python-build-toolchain.json" ||
      canonicalJson(manifest.components.pythonSidecar.pythonToolchain) !==
        canonicalJson(pythonManifest.build.pythonToolchain) ||
      manifest.components.pythonSidecar.files !== python.files ||
      manifest.components.pythonSidecar.nativeFiles !== python.nativeFiles ||
      manifest.components.pythonSidecar.components !== python.components
    ) {
      fail("Bundled resources differ from the engineering-smoke manifest");
    }

    const inventory = buildInventory(appRoot);
    const nativeFiles = [];
    const inspectNative =
      dependencies.inspectMachOArchitectures || inspectMachOArchitectures;
    for (const record of inventory) {
      if (record.type !== "file") {
        continue;
      }
      const candidate = path.join(appRoot, ...record.path.split("/"));
      if (isMachO(candidate)) {
        inspectNative(candidate);
        nativeFiles.push(record.path);
      }
    }
    if (
      nativeFiles.length === 0 ||
      !nativeFiles.includes(`Contents/MacOS/${PRODUCT_NAME}`)
    ) {
      fail("Engineering-smoke native inventory omits Electron");
    }
    const fuses = await inspectSecureFuses(
      executablePath,
      dependencies.getCurrentFuseWire || getCurrentFuseWire
    );
    const codeIdentity = (
      dependencies.inspectCodeIdentity || inspectCodeIdentity
    )(appRoot);

    const inventoryDigest = normalizedInventorySha256(inventory);
    const evidence = {
      schemaVersion: 1,
      kind: "local-context-forge-engineering-smoke-bundle-audit",
      distribution: {
        class: "engineering-smoke",
        marker: DISTRIBUTION_MARKER,
        engineeringOnly: true,
        publishable: false
      },
      source,
      application: {
        bundle: `mac-arm64/${PRODUCT_NAME}.app`,
        appId: info.CFBundleIdentifier,
        productName: info.CFBundleName
      },
      components: {
        desktopApp,
        renderer,
        pythonSidecar: python
      },
      security: {
        ...codeIdentity,
        fuses
      },
      inventory: {
        sha256: inventoryDigest,
        entries: inventory.length,
        files: inventory.filter((record) => record.type === "file").length,
        directories: inventory.filter((record) => record.type === "directory")
          .length,
        symlinks: inventory.filter((record) => record.type === "symlink").length,
        nativeFiles,
        records: inventory
      },
      validation: {
        assembly: "pass",
        bundleAudit: "pass",
        validationId: "VAL-PACKAGED-SMOKE-001",
        packagedAppLaunch: "not-run",
        packagedSmokeValidation: "not-run",
        w10: "locked",
        w11: "locked"
      }
    };
    const evidencePath = dependencies.evidencePath || EVIDENCE_PATH;
    writeExternalEvidence(evidencePath, evidence);
    return {
      kind: evidence.kind,
      source,
      inventorySha256: inventoryDigest,
      inventoryEntries: inventory.length,
      nativeFiles: nativeFiles.length,
      validation: evidence.validation
    };
  };
}

async function main(argv = process.argv.slice(2)) {
  if (argv.length !== 0) {
    fail("auditEngineeringSmokeBundle.cjs takes no arguments");
  }
  process.stdout.write(
    `${canonicalJson(await createAuditEngineeringSmokeBundle()())}\n`
  );
}

if (require.main === module) {
  main().catch((error) => {
    const message =
      error && typeof error.message === "string"
        ? error.message
        : "Engineering-smoke bundle audit failed unexpectedly";
    process.stderr.write(`engineering-smoke bundle audit failed: ${message}\n`);
    process.exitCode = 1;
  });
}

module.exports = {
  APP_ROOT,
  BUNDLED_MANIFEST_PATH,
  EVIDENCE_PATH,
  FORBIDDEN_RESOURCE_NAMES,
  ALLOWED_ELECTRON_HELPER_APPS,
  REVIEWED_PYINSTALLER_ARCHIVE,
  EXPECTED_ASAR_ENTRIES,
  OUTPUT_ROOT,
  assertNoInstallOrReleaseArtifacts,
  assertResourceBoundary,
  createAuditEngineeringSmokeBundle,
  inspectCodeIdentity,
  inspectAsarContents,
  inspectInfoPlist,
  inspectMachOArchitectures,
  inspectSecureFuses,
  isMachO,
  validateInfoPlist,
  validateAsarIntegrity,
  writeExternalEvidence
};

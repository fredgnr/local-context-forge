"use strict";

const fs = require("node:fs");
const { createRequire } = require("node:module");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const prepare = require("../../desktop/scripts/prepareEngineeringSmoke.cjs");
const {
  canonicalJson,
  fail,
  sha256Bytes,
  writeCanonicalJson
} = require("../../desktop/scripts/packagingAuditCommon.cjs");
const { inventory } = require("../../desktop/scripts/auditRenderer.cjs");
const {
  verifyNodeInstallSeal
} = require("../../tools/exact_node_install.cjs");

const REPOSITORY_ROOT = path.resolve(__dirname, "..", "..");
const WEB_ROOT = path.join(REPOSITORY_ROOT, "web");
const DIST_ROOT = path.join(WEB_ROOT, "dist");
const ATTESTATION_NAME = "renderer-source-attestation.json";
const ATTESTATION_KIND = "reviewed-renderer-build";
const VITE_VERSION = "7.3.6";
const REACT_PLUGIN_VERSION = "4.7.0";
const EXPECTED_NODE_VERSION = "v22.23.2";
const EXPECTED_NPM_VERSION = "10.9.8";
const SOURCE_PREFIX = "web/src/";
const INDEX_PATH = "web/index.html";
const PACKAGE_LOCK_PATH = "web/package-lock.json";
const PACKAGE_PATH = "web/package.json";
const TSCONFIG_PATH = "web/tsconfig.app.json";
const VIRTUAL_PREFIX = "\0lcf-reviewed:";
const MAX_INPUT_FILE_BYTES = 8 * 1024 * 1024;
const MAX_INPUT_TOTAL_BYTES = 64 * 1024 * 1024;
const ALLOWED_BARE_IMPORTS = new Set([
  "react",
  "react-dom/client",
  "react/jsx-runtime",
  "react/jsx-dev-runtime"
]);

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

function selectReviewedRendererInputs(snapshot, repositoryRoot) {
  if (!Array.isArray(snapshot.inventory)) {
    fail("Engineering-smoke renderer source inventory is missing");
  }
  const records = snapshot.inventory.filter(
    (record) =>
      record.path === INDEX_PATH ||
      record.path === PACKAGE_LOCK_PATH ||
      record.path === PACKAGE_PATH ||
      record.path === TSCONFIG_PATH ||
      record.path.startsWith(SOURCE_PREFIX)
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
      fail("Engineering-smoke renderer source inventory is unsafe");
    }
    const bytes = prepare.readReviewedGitBlob(repositoryRoot, record.objectId);
    totalBytes += bytes.length;
    if (bytes.length > MAX_INPUT_FILE_BYTES || totalBytes > MAX_INPUT_TOTAL_BYTES) {
      fail("Engineering-smoke renderer source exceeds its size bound");
    }
    byPath.set(record.path, record);
    bytesByPath.set(record.path, Buffer.from(bytes));
  }
  for (const required of [
    INDEX_PATH,
    PACKAGE_LOCK_PATH,
    PACKAGE_PATH,
    TSCONFIG_PATH,
    "web/src/main.tsx"
  ]) {
    if (!byPath.has(required)) {
      fail("Engineering-smoke renderer source closure is incomplete");
    }
  }
  return { byPath, bytesByPath };
}

function resolveReviewedImport(specifier, importer, byPath) {
  if (!specifier.startsWith(".")) {
    return null;
  }
  const base = path.posix.normalize(
    path.posix.join(path.posix.dirname(importer), specifier)
  );
  if (
    !base.startsWith(SOURCE_PREFIX) ||
    base.includes("\\") ||
    base.split("/").some((part) => !part || part === "." || part === "..")
  ) {
    fail("Engineering-smoke renderer import escapes its reviewed source closure");
  }
  const candidates = path.posix.extname(base)
    ? [base]
    : [
        `${base}.ts`,
        `${base}.tsx`,
        `${base}.js`,
        `${base}.jsx`,
        `${base}.json`,
        `${base}.css`,
        `${base}/index.ts`,
        `${base}/index.tsx`,
        `${base}/index.js`,
        `${base}/index.jsx`,
        `${base}/index.json`
      ];
  const matches = candidates.filter((candidate) => byPath.has(candidate));
  if (matches.length !== 1) {
    fail("Engineering-smoke renderer import is missing or ambiguous");
  }
  return matches[0];
}

function reviewedRendererPlugin(byPath, bytesByPath, loadedPaths, webRoot) {
  return {
    name: "lcf-reviewed-renderer-source",
    enforce: "pre",
    async resolveId(specifier, importer, options) {
      if (specifier.startsWith(VIRTUAL_PREFIX)) {
        const reviewedPath = specifier.slice(VIRTUAL_PREFIX.length);
        if (!byPath.has(reviewedPath)) {
          fail("Engineering-smoke renderer entrypoint is missing");
        }
        return `${VIRTUAL_PREFIX}${reviewedPath}`;
      }
      if (!importer || !importer.startsWith(VIRTUAL_PREFIX)) {
        return null;
      }
      const importerPath = importer.slice(VIRTUAL_PREFIX.length);
      const reviewedPath = resolveReviewedImport(specifier, importerPath, byPath);
      if (reviewedPath !== null) {
        return `${VIRTUAL_PREFIX}${reviewedPath}`;
      }
      if (!ALLOWED_BARE_IMPORTS.has(specifier)) {
        fail("Engineering-smoke renderer imports an unreviewed package");
      }
      const resolved = await this.resolve(
        specifier,
        path.join(webRoot, ...importerPath.slice("web/".length).split("/")),
        { ...options, skipSelf: true }
      );
      let resolvedReal;
      let nodeModulesReal;
      try {
        resolvedReal = fs.realpathSync.native(resolved?.id || "");
        nodeModulesReal = fs.realpathSync.native(
          path.join(webRoot, "node_modules")
        );
      } catch {
        fail("Engineering-smoke renderer package resolution is not canonical");
      }
      if (
        !resolved ||
        typeof resolved.id !== "string" ||
        !resolvedReal.startsWith(`${nodeModulesReal}${path.sep}`)
      ) {
        fail("Engineering-smoke renderer package resolution escaped its lock");
      }
      return { ...resolved, id: resolvedReal };
    },
    load(identifier) {
      if (!identifier.startsWith(VIRTUAL_PREFIX)) {
        return null;
      }
      const reviewedPath = identifier.slice(VIRTUAL_PREFIX.length);
      const bytes = bytesByPath.get(reviewedPath);
      if (!bytes) {
        fail("Engineering-smoke renderer source bytes are missing");
      }
      loadedPaths.add(reviewedPath);
      return { code: bytes.toString("utf8"), map: null };
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
      fail("Engineering-smoke renderer source changed during its exact build");
    }
  }
}

function renderReviewedIndex(template, entry) {
  const marker = '<script type="module" src="/src/main.tsx"></script>';
  const css = entry?.css === undefined ? [] : entry.css;
  if (template.split(marker).length !== 2) {
    fail("Engineering-smoke renderer index entrypoint is not exact");
  }
  if (
    !entry ||
    entry.isEntry !== true ||
    typeof entry.file !== "string" ||
    !/^assets\/[A-Za-z0-9_.-]+\.js$/.test(entry.file) ||
    !Array.isArray(css) ||
    !css.every((item) => /^assets\/[A-Za-z0-9_.-]+\.css$/.test(item))
  ) {
    fail("Engineering-smoke renderer asset manifest is invalid");
  }
  const tags = [
    ...css.map(
      (item) => `<link rel="stylesheet" crossorigin href="/${item}">`
    ),
    `<script type="module" crossorigin src="/${entry.file}"></script>`
  ].join("\n    ");
  return template.replace(marker, tags);
}

async function buildRendererFromSnapshot(options) {
  const {
    snapshot,
    repositoryRoot,
    webRoot,
    distRoot,
    environment,
    viteImplementation,
    reactPluginFactory,
    installSummary,
    afterInputsCaptured
  } = options;
  if (
    viteImplementation.version !== VITE_VERSION ||
    !installSummary ||
    !/^[0-9a-f]{64}$/.test(installSummary.lockSha256 || "") ||
    !/^[0-9a-f]{64}$/.test(installSummary.installedContentSha256 || "") ||
    installSummary.nodeVersion !== EXPECTED_NODE_VERSION ||
    installSummary.npmVersion !== EXPECTED_NPM_VERSION
  ) {
    fail("Engineering-smoke renderer builder version differs from its lock");
  }
  const { byPath, bytesByPath } = selectReviewedRendererInputs(
    snapshot,
    repositoryRoot
  );
  const rendererPackageLockSha256 = sha256Bytes(
    bytesByPath.get(PACKAGE_LOCK_PATH)
  );
  if (
    snapshot.rendererPackageLockSha256 !== rendererPackageLockSha256
  ) {
    fail("Engineering-smoke renderer package lock differs from the reviewed commit");
  }
  let packageLock;
  try {
    packageLock = JSON.parse(bytesByPath.get(PACKAGE_LOCK_PATH).toString("utf8"));
  } catch {
    fail("Engineering-smoke renderer package lock is unreadable");
  }
  if (
    packageLock?.packages?.["node_modules/vite"]?.version !== VITE_VERSION ||
    packageLock?.packages?.["node_modules/@vitejs/plugin-react"]?.version !==
      REACT_PLUGIN_VERSION
  ) {
    fail("Engineering-smoke renderer builders differ from the reviewed lock");
  }
  if (typeof afterInputsCaptured === "function") {
    await afterInputsCaptured();
  }
  const loadedPaths = new Set();
  fs.mkdirSync(distRoot, { recursive: true, mode: 0o700 });
  await viteImplementation.build({
    configFile: false,
    envFile: false,
    root: distRoot,
    publicDir: false,
    resolve: { alias: [] },
    esbuild: {
      tsconfigRaw: bytesByPath.get(TSCONFIG_PATH).toString("utf8")
    },
    css: { postcss: { plugins: [] } },
    plugins: [
      reviewedRendererPlugin(byPath, bytesByPath, loadedPaths, webRoot),
      reactPluginFactory()
    ],
    build: {
      outDir: distRoot,
      emptyOutDir: true,
      target: "es2022",
      cssTarget: "es2022",
      manifest: true,
      sourcemap: false,
      rollupOptions: {
        input: `${VIRTUAL_PREFIX}web/src/main.tsx`
      }
    }
  });
  const manifestPath = path.join(distRoot, ".vite", "manifest.json");
  let viteManifest;
  try {
    viteManifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  } catch {
    fail("Engineering-smoke renderer asset manifest is unreadable");
  }
  const entries = Object.values(viteManifest).filter(
    (value) => value && value.isEntry === true
  );
  if (entries.length !== 1) {
    fail("Engineering-smoke renderer asset manifest is ambiguous");
  }
  const template = bytesByPath.get(INDEX_PATH).toString("utf8");
  fs.writeFileSync(
    path.join(distRoot, "index.html"),
    renderReviewedIndex(template, entries[0]),
    { encoding: "utf8", flag: "wx", mode: 0o600 }
  );
  fs.rmSync(path.join(distRoot, ".vite"), { recursive: true });
  const after = prepare.inspectRepositoryProvenance(repositoryRoot, environment);
  validateSameSource(snapshot, after);
  const inputs = [...loadedPaths, INDEX_PATH, PACKAGE_LOCK_PATH, PACKAGE_PATH, TSCONFIG_PATH]
    .sort(compareCodePoints)
    .filter((value, index, values) => index === 0 || value !== values[index - 1])
    .map((sourcePath) => {
      const record = byPath.get(sourcePath);
      return {
        mode: record.mode,
        objectId: record.objectId,
        path: record.path,
        type: record.type
      };
    });
  const outputs = inventory(distRoot);
  const attestation = {
    schemaVersion: 1,
    kind: ATTESTATION_KIND,
    source: {
      repositoryCommit: snapshot.commit,
      repositoryTree: snapshot.tree,
      sourceSnapshotSha256: snapshot.sourceSnapshotSha256,
      sourceDateEpoch: snapshot.sourceDateEpoch,
      packageLockSha256: rendererPackageLockSha256
    },
    builder: {
      name: "vite",
      version: VITE_VERSION,
      reactPluginVersion: REACT_PLUGIN_VERSION,
      nodeVersion: installSummary.nodeVersion,
      npmVersion: installSummary.npmVersion,
      installedContentSha256: installSummary.installedContentSha256
    },
    inputs,
    inputsSha256: sha256Bytes(Buffer.from(canonicalJson(inputs), "utf8")),
    outputs
  };
  writeCanonicalJson(path.join(distRoot, ATTESTATION_NAME), attestation);
  validateSameSource(
    snapshot,
    prepare.inspectRepositoryProvenance(repositoryRoot, environment)
  );
  return attestation;
}

function resolveExactInstalledModule(packageRoot, specifier) {
  const nodeModulesRoot = fs.realpathSync.native(
    path.join(packageRoot, "node_modules")
  );
  const requireFromPackage = createRequire(path.join(packageRoot, "package.json"));
  let resolved;
  try {
    resolved = fs.realpathSync.native(requireFromPackage.resolve(specifier));
  } catch {
    fail("Engineering-smoke installed renderer module is unavailable");
  }
  if (!resolved.startsWith(`${nodeModulesRoot}${path.sep}`)) {
    fail("Engineering-smoke installed renderer module escaped its seal");
  }
  return resolved;
}

async function buildEngineeringRenderer(options = {}) {
  const environment = options.environment || process.env;
  if (environment.LCF_ENGINEERING_SMOKE === "true") {
    prepare.assertNoProductionEnvironment(environment);
  } else if (environment.LCF_FORMAL_RELEASE !== "true") {
    fail("Reviewed renderer build mode is not explicitly enabled");
  }
  const snapshot = prepare.inspectRepositorySourceSnapshot(
    REPOSITORY_ROOT,
    environment
  );
  const sealPath = environment.LCF_WEB_NODE_INSTALL_SEAL;
  if (!path.isAbsolute(sealPath || "")) {
    fail("Engineering-smoke Web Node install seal is missing");
  }
  const installBefore = verifyNodeInstallSeal({
    repositoryRoot: REPOSITORY_ROOT,
    packageName: "web",
    sealPath,
    snapshot
  });
  const viteImplementation = options.viteImplementation ||
    (await import(pathToFileURL(
      resolveExactInstalledModule(WEB_ROOT, "vite")
    ).href));
  const reactPluginModule = options.reactPluginModule ||
    (await import(pathToFileURL(
      resolveExactInstalledModule(WEB_ROOT, "@vitejs/plugin-react")
    ).href));
  const attestation = await buildRendererFromSnapshot({
    snapshot,
    repositoryRoot: REPOSITORY_ROOT,
    webRoot: WEB_ROOT,
    distRoot: DIST_ROOT,
    environment,
    viteImplementation,
    reactPluginFactory: reactPluginModule.default,
    installSummary: installBefore,
    afterInputsCaptured: options.afterInputsCaptured
  });
  const installAfter = verifyNodeInstallSeal({
    repositoryRoot: REPOSITORY_ROOT,
    packageName: "web",
    sealPath,
    snapshot
  });
  if (canonicalJson(installAfter) !== canonicalJson(installBefore)) {
    fail("Engineering-smoke Web Node install changed during build");
  }
  return attestation;
}

async function main(argv = process.argv.slice(2)) {
  if (argv.length !== 0) {
    fail("Usage: buildEngineeringRenderer.cjs");
  }
  const attestation = await buildEngineeringRenderer();
  process.stdout.write(
    `${canonicalJson({
      kind: attestation.kind,
      source: attestation.source,
      inputsSha256: attestation.inputsSha256,
      files: attestation.outputs.length
    })}\n`
  );
}

if (require.main === module) {
  main().catch((error) => {
    const message =
      error && typeof error.message === "string"
        ? error.message
        : "Engineering-smoke exact renderer build failed unexpectedly";
    process.stderr.write(`engineering-smoke renderer build failed: ${message}\n`);
    process.exitCode = 1;
  });
}

module.exports = {
  ATTESTATION_KIND,
  ATTESTATION_NAME,
  REACT_PLUGIN_VERSION,
  VITE_VERSION,
  buildEngineeringRenderer,
  buildRendererFromSnapshot,
  renderReviewedIndex,
  resolveReviewedImport,
  selectReviewedRendererInputs
};

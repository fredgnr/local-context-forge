"use strict";

const childProcess = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const {
  auditPythonSidecar
} = require("./beforePack.cjs");
const {
  MANIFEST_DIGEST_NAME,
  MANIFEST_NAME,
  auditQmdRuntime,
  buildFileInventory,
  buildNativeInventory,
  canonicalJson,
  sha256Bytes
} = require("./auditQmdRuntime.cjs");
const {
  auditCompanion
} = require("./auditCompanion.cjs");
const {
  auditRenderer
} = require("./auditRenderer.cjs");

const REPOSITORY_ROOT = path.resolve(__dirname, "..", "..");
const PRODUCT_NAME = "Local Context Forge";
const SIGNING_IDENTITY = "Local Context Forge Self Signed";
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

class RuntimeResealError extends Error {
  constructor(message) {
    super(message);
    this.name = "RuntimeResealError";
  }
}

function fail(message) {
  throw new RuntimeResealError(message);
}

function requireRealDirectory(directory, label) {
  const resolved = path.resolve(directory);
  let info;
  try {
    info = fs.lstatSync(resolved);
  } catch {
    fail(`${label} is missing`);
  }
  if (
    !info.isDirectory() ||
    info.isSymbolicLink() ||
    fs.realpathSync.native(resolved) !== resolved
  ) {
    fail(`${label} must be a real canonical directory`);
  }
  return resolved;
}

function requireRegularFile(filePath, label) {
  let info;
  try {
    info = fs.lstatSync(filePath);
  } catch {
    fail(`${label} is missing`);
  }
  if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1) {
    fail(`${label} must be an unlinked regular file`);
  }
  return info;
}

function isMachO(filePath) {
  const descriptor = fs.openSync(filePath, "r");
  try {
    const magic = Buffer.alloc(4);
    return (
      fs.readSync(descriptor, magic, 0, 4, 0) === 4 &&
      MACHO_MAGICS.has(magic.toString("hex"))
    );
  } finally {
    fs.closeSync(descriptor);
  }
}

function nativeFiles(root) {
  const result = [];
  function visit(directory) {
    for (const name of fs.readdirSync(directory).sort()) {
      const candidate = path.join(directory, name);
      const info = fs.lstatSync(candidate);
      if (info.isSymbolicLink()) {
        continue;
      }
      if (info.isDirectory()) {
        visit(candidate);
      } else if (info.isFile() && info.nlink === 1) {
        if (isMachO(candidate)) {
          result.push(candidate);
        }
      } else {
        fail("Packaged runtime contains a special or hard-linked file");
      }
    }
  }
  visit(root);
  return result;
}

function loadJson(filePath, label) {
  requireRegularFile(filePath, label);
  let value;
  try {
    value = JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    fail(`${label} is not valid JSON`);
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail(`${label} must be an object`);
  }
  return value;
}

function atomicWrite(filePath, contents, mode = 0o644) {
  const temporary = `${filePath}.reseal`;
  if (fs.existsSync(temporary)) {
    fail("Runtime reseal temporary path already exists");
  }
  try {
    fs.writeFileSync(temporary, contents, {
      mode,
      flag: "wx"
    });
    fs.chmodSync(temporary, mode);
    fs.renameSync(temporary, filePath);
  } finally {
    fs.rmSync(temporary, { force: true });
  }
}

function signRuntimeFiles(roots, keychain) {
  const candidates = roots
    .flatMap(nativeFiles)
    .sort((left, right) => right.length - left.length);
  if (candidates.length < 3) {
    fail("Packaged runtimes omit expected native code");
  }
  for (const candidate of candidates) {
    try {
      childProcess.execFileSync(
        "/usr/bin/codesign",
        [
          "--force",
          "--sign",
          SIGNING_IDENTITY,
          "--keychain",
          keychain,
          "--timestamp=none",
          candidate
        ],
        {
          encoding: "utf8",
          env: { PATH: "/usr/bin:/bin", LANG: "C", LC_ALL: "C" },
          stdio: ["ignore", "pipe", "pipe"],
          timeout: 60_000,
          maxBuffer: 4 * 1024 * 1024
        }
      );
    } catch {
      fail("Packaged runtime certificate signing failed");
    }
  }
  return candidates.length;
}

function resealQmdManifest(qmdRoot, sourceDateEpoch) {
  const manifestPath = path.join(qmdRoot, MANIFEST_NAME);
  const manifest = loadJson(manifestPath, "QMD runtime build manifest");
  const files = buildFileInventory(qmdRoot);
  const native = buildNativeInventory(qmdRoot);
  manifest.files = files;
  manifest.native = native;
  manifest.audit.normalizedInventorySha256 = sha256Bytes(
    Buffer.from(canonicalJson({ files, native }), "utf8")
  );
  const bytes = Buffer.from(`${canonicalJson(manifest)}\n`, "utf8");
  atomicWrite(manifestPath, bytes);
  const digestPath = path.join(qmdRoot, MANIFEST_DIGEST_NAME);
  atomicWrite(
    digestPath,
    Buffer.from(`${sha256Bytes(bytes)}\n`, "ascii")
  );
  fs.utimesSync(manifestPath, sourceDateEpoch, sourceDateEpoch);
  fs.utimesSync(digestPath, sourceDateEpoch, sourceDateEpoch);
}

function resealPythonManifest(sidecarRoot, buildPython, sourceDateEpoch) {
  requireRegularFile(buildPython, "Reviewed QMD build Python");
  try {
    childProcess.execFileSync(
      buildPython,
      [
        "-I",
        path.join(REPOSITORY_ROOT, "tools", "audit_python_sidecar.py"),
        "--bundle",
        sidecarRoot,
        "--reseal-manifest"
      ],
      {
        encoding: "utf8",
        cwd: REPOSITORY_ROOT,
        env: {
          PATH: "/usr/bin:/bin",
          LANG: "C",
          LC_ALL: "C",
          PYTHONHASHSEED: "0",
          PYTHONNOUSERSITE: "1",
          PYTHONSAFEPATH: "1"
        },
        stdio: ["ignore", "pipe", "pipe"],
        timeout: 120_000,
        maxBuffer: 4 * 1024 * 1024
      }
    );
  } catch {
    fail("Python sidecar post-sign inventory reseal failed");
  }
  fs.utimesSync(
    path.join(sidecarRoot, "build-manifest.json"),
    sourceDateEpoch,
    sourceDateEpoch
  );
}

function resealPackagedRuntimes(context, environment = process.env) {
  if (environment.LCF_FORMAL_RELEASE !== "true") {
    return { formalRelease: false };
  }
  if (
    process.platform !== "darwin" ||
    process.arch !== "arm64" ||
    context?.electronPlatformName !== "darwin"
  ) {
    fail("Formal runtime reseal requires native Darwin arm64 packaging");
  }
  if (
    environment.CSC_NAME !== SIGNING_IDENTITY ||
    typeof environment.CSC_KEYCHAIN !== "string" ||
    !path.isAbsolute(environment.CSC_KEYCHAIN) ||
    typeof environment.LCF_QMD_BUILD_PYTHON !== "string" ||
    !path.isAbsolute(environment.LCF_QMD_BUILD_PYTHON) ||
    !/^[0-9a-f]{40}$/.test(environment.LCF_SOURCE_SHA || "") ||
    !/^[0-9a-f]{40}$/.test(environment.LCF_SOURCE_TREE || "") ||
    !/^[0-9a-f]{64}$/.test(
      environment.LCF_SOURCE_SNAPSHOT_SHA256 || ""
    ) ||
    !/^[0-9a-f]{64}$/.test(
      environment.LCF_RENDERER_PACKAGE_LOCK_SHA256 || ""
    )
  ) {
    fail("Formal runtime reseal signing inputs are missing");
  }
  requireRegularFile(environment.CSC_KEYCHAIN, "Temporary signing keychain");
  const sourceDateEpoch = Number(environment.LCF_SOURCE_DATE_EPOCH);
  if (
    !Number.isSafeInteger(sourceDateEpoch) ||
    sourceDateEpoch < 100_000_000
  ) {
    fail("Formal runtime reseal source epoch is invalid");
  }
  const appRoot = requireRealDirectory(
    path.join(context.appOutDir, `${PRODUCT_NAME}.app`),
    "Packaged macOS app"
  );
  const resources = requireRealDirectory(
    path.join(appRoot, "Contents", "Resources"),
    "Packaged app Resources"
  );
  const sidecarRoot = requireRealDirectory(
    path.join(resources, "sidecar"),
    "Packaged Python sidecar"
  );
  const qmdRoot = requireRealDirectory(
    path.join(resources, "qmd"),
    "Packaged QMD runtime"
  );
  const signedNativeFiles = signRuntimeFiles(
    [sidecarRoot, qmdRoot],
    environment.CSC_KEYCHAIN
  );
  resealPythonManifest(
    sidecarRoot,
    environment.LCF_QMD_BUILD_PYTHON,
    sourceDateEpoch
  );
  resealQmdManifest(qmdRoot, sourceDateEpoch);

  const python = auditPythonSidecar({
    repositoryRoot: REPOSITORY_ROOT,
    stagingRoot: sidecarRoot,
    environment,
    platform: "darwin",
    architecture: "arm64"
  });
  const qmd = auditQmdRuntime({
    repositoryRoot: REPOSITORY_ROOT,
    stagingRoot: qmdRoot,
    environment,
    platform: "darwin",
    architecture: "arm64"
  });
  const companion = auditCompanion({
    repositoryRoot: REPOSITORY_ROOT,
    stagingRoot: path.join(resources, "companion")
  });
  const renderer = auditRenderer(path.join(resources, "renderer"), {
    expectedCommit: environment.LCF_SOURCE_SHA,
    expectedTree: environment.LCF_SOURCE_TREE,
    expectedSourceSnapshotSha256:
      environment.LCF_SOURCE_SNAPSHOT_SHA256,
    expectedSourceDateEpoch: sourceDateEpoch,
    expectedPackageLockSha256:
      environment.LCF_RENDERER_PACKAGE_LOCK_SHA256
  });
  return {
    formalRelease: true,
    signedNativeFiles,
    python,
    qmd,
    companion,
    renderer
  };
}

module.exports = {
  RuntimeResealError,
  resealPackagedRuntimes
};

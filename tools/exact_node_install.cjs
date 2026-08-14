"use strict";

const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {
  canonicalJson,
  fail,
  sha256Bytes
} = require("../desktop/scripts/packagingAuditCommon.cjs");
const prepare = require("../desktop/scripts/prepareEngineeringSmoke.cjs");

const REPOSITORY_ROOT = path.resolve(__dirname, "..");
const INSTALL_KIND = "lcf-exact-node-install";
const PACKAGE_ROOTS = Object.freeze({
  desktop: Object.freeze({
    lockPath: "desktop/package-lock.json",
    packagePath: "desktop/package.json"
  }),
  web: Object.freeze({
    lockPath: "web/package-lock.json",
    packagePath: "web/package.json"
  })
});
const MAX_INSTALL_ENTRIES = 500_000;
const MAX_INSTALL_BYTES = 4 * 1024 * 1024 * 1024;
const MAX_SEAL_BYTES = 1024 * 1024;
const MAX_PACKAGE_METADATA_BYTES = 64 * 1024 * 1024;
const EXPECTED_NODE_VERSION = "v22.23.2";
const EXPECTED_NPM_VERSION = "10.9.8";

function readDescriptorBytes(descriptor, size, label) {
  if (
    !Number.isSafeInteger(size) ||
    size <= 0 ||
    size > MAX_PACKAGE_METADATA_BYTES
  ) {
    fail(`${label} exceeds its byte bound`);
  }
  const bytes = Buffer.alloc(size);
  let offset = 0;
  while (offset < bytes.length) {
    const count = fs.readSync(
      descriptor,
      bytes,
      offset,
      bytes.length - offset,
      offset
    );
    if (count <= 0) {
      fail(`${label} ended before its reviewed size`);
    }
    offset += count;
  }
  return bytes;
}

function stableIdentity(info) {
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

function stableDirectoryIdentity(candidate) {
  const info = fs.lstatSync(candidate, { bigint: true });
  return [
    info.dev,
    info.ino,
    info.mode,
    info.nlink,
    info.size,
    info.mtimeNs,
    info.ctimeNs
  ].join(":");
}

function requirePrivateRepositoryRoot(repositoryRoot) {
  let info;
  try {
    info = fs.lstatSync(repositoryRoot);
  } catch {
    fail("Exact Node repository root is unavailable");
  }
  if (
    repositoryRoot !== fs.realpathSync.native(repositoryRoot) ||
    !info.isDirectory() ||
    info.isSymbolicLink() ||
    info.uid !== process.geteuid() ||
    (info.mode & 0o077) !== 0
  ) {
    fail("Exact Node repository root is not private");
  }
  return info;
}

function exactPackageDefinition(packageName) {
  const definition = PACKAGE_ROOTS[packageName];
  if (definition === undefined) {
    fail("Exact Node package root is not reviewed");
  }
  return definition;
}

function openReviewedMetadataCapability(
  repositoryRoot,
  relativePath,
  expectedBytes
) {
  const candidate = path.join(repositoryRoot, ...relativePath.split("/"));
  let descriptor;
  try {
    descriptor = fs.openSync(
      candidate,
      fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW
    );
    const before = fs.fstatSync(descriptor);
    const bytes = readDescriptorBytes(
      descriptor,
      before.size,
      "Exact Node package metadata"
    );
    const after = fs.fstatSync(descriptor);
    if (
      !before.isFile() ||
      before.uid !== process.geteuid() ||
      before.nlink !== 1 ||
      (before.mode & 0o7022) !== 0 ||
      stableIdentity(before) !== stableIdentity(after) ||
      !bytes.equals(expectedBytes)
    ) {
      fail("Exact Node package metadata capability is unsafe");
    }
    return {
      bytes,
      candidate,
      descriptor,
      identity: stableIdentity(before)
    };
  } catch (error) {
    if (descriptor !== undefined) {
      fs.closeSync(descriptor);
    }
    if (error?.name === "PackagingAuditError") {
      throw error;
    }
    fail("Exact Node package metadata capability is unavailable");
  }
}

function closeCapability(capability) {
  if (capability?.descriptor !== undefined) {
    fs.closeSync(capability.descriptor);
    capability.descriptor = undefined;
  }
}

function revalidateMetadataCapability(capability) {
  let pathInfo;
  try {
    const descriptorInfo = fs.fstatSync(capability.descriptor);
    pathInfo = fs.lstatSync(capability.candidate);
    const bytes = readDescriptorBytes(
      capability.descriptor,
      descriptorInfo.size,
      "Exact Node package metadata"
    );
    const descriptorAfter = fs.fstatSync(capability.descriptor);
    if (
      stableIdentity(descriptorInfo) !== capability.identity ||
      stableIdentity(descriptorAfter) !== capability.identity ||
      stableIdentity(pathInfo) !== capability.identity ||
      pathInfo.isSymbolicLink() ||
      !bytes.equals(capability.bytes)
    ) {
      fail("Exact Node package metadata changed during install");
    }
  } catch (error) {
    if (error?.name === "PackagingAuditError") {
      throw error;
    }
    fail("Exact Node package metadata changed during install");
  }
}

function inventoryNodeInstall(nodeModulesRoot) {
  let rootInfo;
  try {
    rootInfo = fs.lstatSync(nodeModulesRoot);
  } catch {
    fail("Exact Node install root is missing");
  }
  if (
    !rootInfo.isDirectory() ||
    rootInfo.isSymbolicLink() ||
    rootInfo.uid !== process.geteuid() ||
    (rootInfo.mode & 0o022) !== 0 ||
    fs.realpathSync.native(nodeModulesRoot) !== nodeModulesRoot
  ) {
    fail("Exact Node install root is unsafe");
  }
  const records = [];
  let files = 0;
  let directories = 0;
  let symlinks = 0;
  let bytes = 0;
  function visit(candidate, relative) {
    let info;
    try {
      info = fs.lstatSync(candidate, { bigint: true });
    } catch {
      fail("Exact Node install inventory is unreadable");
    }
    const base = {
      path: relative,
      device: info.dev.toString(),
      inode: info.ino.toString(),
      mode: Number(info.mode & 0o7777n),
      links: Number(info.nlink),
      size: Number(info.size),
      modifiedNs: info.mtimeNs.toString(),
      changedNs: info.ctimeNs.toString()
    };
    if (Number(info.uid) !== process.geteuid()) {
      fail("Exact Node install inventory contains unsafe ownership");
    }
    if (info.isDirectory()) {
      if ((base.mode & 0o7022) !== 0) {
        fail("Exact Node install inventory contains an unsafe directory mode");
      }
      directories += 1;
      records.push({ ...base, type: "directory" });
      for (const name of fs.readdirSync(candidate).sort()) {
        if (!name || name === "." || name === ".." || name.includes("/")) {
          fail("Exact Node install inventory contains an unsafe name");
        }
        visit(path.join(candidate, name), relative ? `${relative}/${name}` : name);
      }
    } else if (info.isSymbolicLink()) {
      const target = fs.readlinkSync(candidate);
      const resolved = path.resolve(path.dirname(candidate), target);
      let resolvedReal;
      try {
        resolvedReal = fs.realpathSync.native(candidate);
      } catch {
        fail("Exact Node install inventory contains a dangling symlink");
      }
      if (
        path.isAbsolute(target) ||
        (resolved !== nodeModulesRoot &&
          !resolved.startsWith(`${nodeModulesRoot}${path.sep}`)) ||
        (resolvedReal !== nodeModulesRoot &&
          !resolvedReal.startsWith(`${nodeModulesRoot}${path.sep}`))
      ) {
        fail("Exact Node install inventory contains an escaping symlink");
      }
      symlinks += 1;
      records.push({ ...base, type: "symlink", target });
    } else if (info.isFile()) {
      if (
        (base.mode & 0o7022) !== 0 ||
        info.nlink !== 1n ||
        info.size > BigInt(MAX_INSTALL_BYTES)
      ) {
        fail("Exact Node install inventory contains a linked or oversized file");
      }
      let descriptor;
      let payload;
      try {
        descriptor = fs.openSync(
          candidate,
          fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW
        );
        const before = fs.fstatSync(descriptor, { bigint: true });
        payload = fs.readFileSync(descriptor);
        const after = fs.fstatSync(descriptor, { bigint: true });
        if (
          before.dev !== info.dev ||
          before.ino !== info.ino ||
          before.mode !== info.mode ||
          before.nlink !== info.nlink ||
          before.size !== info.size ||
          before.mtimeNs !== info.mtimeNs ||
          before.ctimeNs !== info.ctimeNs ||
          after.dev !== before.dev ||
          after.ino !== before.ino ||
          after.mode !== before.mode ||
          after.nlink !== before.nlink ||
          after.size !== before.size ||
          after.mtimeNs !== before.mtimeNs ||
          after.ctimeNs !== before.ctimeNs
        ) {
          fail("Exact Node install file changed while inventoried");
        }
      } finally {
        if (descriptor !== undefined) {
          fs.closeSync(descriptor);
        }
      }
      files += 1;
      bytes += payload.length;
      if (bytes > MAX_INSTALL_BYTES) {
        fail("Exact Node install inventory exceeds its byte bound");
      }
      records.push({
        ...base,
        type: "file",
        sha256: sha256Bytes(payload)
      });
    } else {
      fail("Exact Node install inventory contains a special file");
    }
    if (records.length > MAX_INSTALL_ENTRIES) {
      fail("Exact Node install inventory exceeds its entry bound");
    }
  }
  visit(nodeModulesRoot, "");
  const contentRecords = records.map((record) => {
    const content = {
      path: record.path,
      type: record.type
    };
    if (record.type === "file") {
      content.mode = record.mode;
      content.size = record.size;
      content.sha256 = record.sha256;
    } else if (record.type === "directory") {
      content.mode = record.mode;
    } else if (record.type === "symlink") {
      content.target = record.target;
    }
    return content;
  });
  const identityRecords = records.map((record) => ({
    path: record.path,
    type: record.type,
    device: record.device,
    inode: record.inode,
    links: record.links,
    modifiedNs: record.modifiedNs,
    changedNs: record.changedNs
  }));
  const contentInventorySha256 = sha256Bytes(
    Buffer.from(canonicalJson(contentRecords), "utf8")
  );
  const identitySnapshotSha256 = sha256Bytes(
    Buffer.from(canonicalJson(identityRecords), "utf8")
  );
  return {
    bytes,
    contentInventorySha256,
    directories,
    entries: records.length,
    files,
    identitySnapshotSha256,
    symlinks
  };
}

function readCanonicalSeal(sealPath) {
  let descriptor;
  try {
    descriptor = fs.openSync(
      sealPath,
      fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW
    );
    const before = fs.fstatSync(descriptor);
    if (
      !before.isFile() ||
      before.uid !== process.geteuid() ||
      before.nlink !== 1 ||
      before.size <= 0 ||
      before.size > MAX_SEAL_BYTES ||
      (before.mode & 0o7077) !== 0
    ) {
      fail("Exact Node install seal is unsafe");
    }
    const payload = fs.readFileSync(descriptor);
    const after = fs.fstatSync(descriptor);
    if (stableIdentity(before) !== stableIdentity(after)) {
      fail("Exact Node install seal changed while read");
    }
    const text = payload.toString("utf8");
    const value = JSON.parse(text);
    if (
      !Buffer.from(text, "utf8").equals(payload) ||
      text !== `${canonicalJson(value)}\n`
    ) {
      fail("Exact Node install seal is not canonical");
    }
    return value;
  } catch (error) {
    if (error?.name === "PackagingAuditError") {
      throw error;
    }
    fail("Exact Node install seal is unreadable");
  } finally {
    if (descriptor !== undefined) {
      fs.closeSync(descriptor);
    }
  }
}

function validateSealShape(
  seal,
  packageName,
  snapshot,
  definition,
  runtimeContract
) {
  const exactKeys = (value, names) =>
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).sort().join("\0") === [...names].sort().join("\0");
  if (
    !exactKeys(seal, ["schemaVersion", "kind", "source", "package", "runtime", "install"]) ||
    seal.schemaVersion !== 1 ||
    seal.kind !== INSTALL_KIND ||
    !exactKeys(seal.source, ["commit", "tree", "sourceSnapshotSha256"]) ||
    seal.source.commit !== snapshot.commit ||
    seal.source.tree !== snapshot.tree ||
    seal.source.sourceSnapshotSha256 !== snapshot.sourceSnapshotSha256 ||
    !exactKeys(seal.package, ["root", "packagePath", "packageSha256", "lockPath", "lockSha256"]) ||
    seal.package.root !== packageName ||
    seal.package.packagePath !== definition.packagePath ||
    seal.package.lockPath !== definition.lockPath ||
    !/^[0-9a-f]{64}$/.test(seal.package.packageSha256 || "") ||
    !/^[0-9a-f]{64}$/.test(seal.package.lockSha256 || "") ||
    !exactKeys(seal.runtime, ["nodeVersion", "npmVersion"]) ||
    seal.runtime.nodeVersion !== runtimeContract.nodeVersion ||
    seal.runtime.npmVersion !== runtimeContract.npmVersion ||
    !exactKeys(seal.install, ["path", "bytes", "contentInventorySha256", "directories", "entries", "files", "identitySnapshotSha256", "symlinks"]) ||
    seal.install.path !== `${packageName}/node_modules` ||
    !Number.isSafeInteger(seal.install.bytes) ||
    !Number.isSafeInteger(seal.install.directories) ||
    !Number.isSafeInteger(seal.install.entries) ||
    !Number.isSafeInteger(seal.install.files) ||
    !Number.isSafeInteger(seal.install.symlinks) ||
    !/^[0-9a-f]{64}$/.test(seal.install.contentInventorySha256 || "") ||
    !/^[0-9a-f]{64}$/.test(seal.install.identitySnapshotSha256 || "")
  ) {
    fail("Exact Node install seal is invalid");
  }
}

function writeCanonicalSeal(sealPath, seal) {
  if (!path.isAbsolute(sealPath) || fs.existsSync(sealPath)) {
    fail("Exact Node install seal destination is unsafe");
  }
  const parent = path.dirname(sealPath);
  const parentInfo = fs.lstatSync(parent);
  if (
    !parentInfo.isDirectory() ||
    parentInfo.isSymbolicLink() ||
    parentInfo.uid !== process.geteuid() ||
    (parentInfo.mode & 0o022) !== 0
  ) {
    fail("Exact Node install seal parent is unsafe");
  }
  let descriptor;
  try {
    descriptor = fs.openSync(
      sealPath,
      fs.constants.O_WRONLY |
        fs.constants.O_CREAT |
        fs.constants.O_EXCL |
        fs.constants.O_NOFOLLOW,
      0o600
    );
    fs.writeFileSync(descriptor, `${canonicalJson(seal)}\n`, "utf8");
    fs.fsyncSync(descriptor);
  } finally {
    if (descriptor !== undefined) {
      fs.closeSync(descriptor);
    }
  }
}

function sanitizedNpmEnvironment(
  npmExecutable,
  temporaryHome,
  runtimeContract
) {
  const executable = fs.realpathSync.native(npmExecutable);
  const nodeExecutable = fs.realpathSync.native(process.execPath);
  const nodeDirectory = path.dirname(nodeExecutable);
  const nodeRuntimeRoot = path.dirname(nodeDirectory);
  if (
    !path.isAbsolute(executable) ||
    !fs.lstatSync(executable).isFile() ||
    (!runtimeContract.allowExternalNpmForTest &&
      !executable.startsWith(`${nodeRuntimeRoot}${path.sep}`))
  ) {
    fail("Exact Node npm runtime is unsafe");
  }
  const globalConfig = path.join(temporaryHome, "global.npmrc");
  const userConfig = path.join(temporaryHome, "user.npmrc");
  for (const configPath of [globalConfig, userConfig]) {
    let descriptor;
    try {
      descriptor = fs.openSync(
        configPath,
        fs.constants.O_WRONLY |
          fs.constants.O_CREAT |
          fs.constants.O_EXCL |
          fs.constants.O_NOFOLLOW,
        0o600
      );
      fs.fsyncSync(descriptor);
    } finally {
      if (descriptor !== undefined) {
        fs.closeSync(descriptor);
      }
    }
  }
  return {
    executable,
    environment: {
      PATH: `${nodeDirectory}:/usr/bin:/bin`,
      HOME: temporaryHome,
      LANG: "C",
      LC_ALL: "C",
      NPM_CONFIG_AUDIT: "false",
      NPM_CONFIG_CACHE: path.join(temporaryHome, "cache"),
      NPM_CONFIG_FUND: "false",
      NPM_CONFIG_GLOBALCONFIG: globalConfig,
      NPM_CONFIG_IGNORE_SCRIPTS: "true",
      NPM_CONFIG_REGISTRY: "https://registry.npmjs.org/",
      NPM_CONFIG_UPDATE_NOTIFIER: "false",
      NPM_CONFIG_USERCONFIG: userConfig,
      TMPDIR: temporaryHome
    }
  };
}

function runNpm(executable, arguments_, options) {
  const completed = childProcess.spawnSync(executable, arguments_, {
    cwd: options.cwd,
    env: options.environment,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    timeout: 20 * 60 * 1000,
    maxBuffer: 4 * 1024 * 1024
  });
  if (
    completed.error ||
    completed.signal !== null ||
    completed.status !== 0
  ) {
    fail("Exact Node dependency install failed");
  }
  return completed.stdout.trim();
}

function sameSnapshot(left, right) {
  return ["commit", "tree", "sourceSnapshotSha256"].every(
    (field) => left[field] === right[field]
  );
}

function installExactNodeDependencies(options) {
  const repositoryRoot = path.resolve(options.repositoryRoot || REPOSITORY_ROOT);
  const packageName = options.packageName;
  const sealPath = path.resolve(options.sealPath);
  const definition = exactPackageDefinition(packageName);
  const runtimeContract = options.runtimeContract || {
    nodeVersion: EXPECTED_NODE_VERSION,
    npmVersion: EXPECTED_NPM_VERSION
  };
  if (process.version !== runtimeContract.nodeVersion) {
    fail("Exact Node runtime version differs from policy");
  }
  requirePrivateRepositoryRoot(repositoryRoot);
  const packageRoot = path.join(repositoryRoot, packageName);
  const packageRootInfo = fs.lstatSync(packageRoot);
  if (
    !packageRootInfo.isDirectory() ||
    packageRootInfo.isSymbolicLink() ||
    packageRootInfo.uid !== process.geteuid() ||
    (packageRootInfo.mode & 0o022) !== 0 ||
    fs.realpathSync.native(packageRoot) !== packageRoot
  ) {
    fail("Exact Node package root is unsafe");
  }
  const nodeModulesRoot = path.join(packageRoot, "node_modules");
  if (fs.existsSync(nodeModulesRoot) || fs.existsSync(sealPath)) {
    fail("Exact Node install destination is not empty");
  }
  const snapshot = prepare.inspectRepositorySourceSnapshot(
    repositoryRoot,
    options.environment || process.env
  );
  const records = new Map(
    snapshot.inventory.map((record) => [record.path, record])
  );
  const capabilities = [];
  let temporaryHome;
  try {
    for (const relativePath of [definition.packagePath, definition.lockPath]) {
      const record = records.get(relativePath);
      if (
        !record ||
        record.mode !== "100644" ||
        record.type !== "blob"
      ) {
        fail("Exact Node reviewed package metadata is missing");
      }
      capabilities.push(
        openReviewedMetadataCapability(
          repositoryRoot,
          relativePath,
          prepare.readReviewedGitBlob(repositoryRoot, record.objectId)
        )
      );
    }
    const packageRootIdentity = stableDirectoryIdentity(packageRoot);
    if (typeof options.afterCapabilitiesBound === "function") {
      options.afterCapabilitiesBound({
        lockPath: capabilities[1].candidate,
        packagePath: capabilities[0].candidate
      });
    }
    if (stableDirectoryIdentity(packageRoot) !== packageRootIdentity) {
      fail("Exact Node package metadata parent changed before install");
    }
    capabilities.forEach(revalidateMetadataCapability);
    const temporaryParent = path.resolve(options.temporaryParent || os.tmpdir());
    const parentInfo = fs.lstatSync(temporaryParent);
    if (
      !parentInfo.isDirectory() ||
      parentInfo.isSymbolicLink() ||
      parentInfo.uid !== process.geteuid() ||
      (parentInfo.mode & 0o022) !== 0
    ) {
      fail("Exact Node temporary parent is unsafe");
    }
    temporaryHome = fs.mkdtempSync(
      path.join(temporaryParent, ".lcf-node-home-")
    );
    fs.chmodSync(temporaryHome, 0o700);
    const npm = sanitizedNpmEnvironment(
      options.npmExecutable,
      temporaryHome,
      runtimeContract
    );
    const npmVersion = runNpm(npm.executable, ["--version"], {
      cwd: packageRoot,
      environment: npm.environment
    });
    if (npmVersion !== runtimeContract.npmVersion) {
      fail("Exact Node npm runtime version differs from policy");
    }
    runNpm(
      npm.executable,
      ["ci", "--ignore-scripts", "--no-audit", "--no-fund"],
      { cwd: packageRoot, environment: npm.environment }
    );
    capabilities.forEach(revalidateMetadataCapability);
    const after = prepare.inspectRepositorySourceSnapshot(
      repositoryRoot,
      options.environment || process.env
    );
    if (!sameSnapshot(snapshot, after)) {
      fail("Exact Node source changed during dependency install");
    }
    const install = inventoryNodeInstall(nodeModulesRoot);
    const seal = {
      schemaVersion: 1,
      kind: INSTALL_KIND,
      source: {
        commit: snapshot.commit,
        tree: snapshot.tree,
        sourceSnapshotSha256: snapshot.sourceSnapshotSha256
      },
      package: {
        root: packageName,
        packagePath: definition.packagePath,
        packageSha256: sha256Bytes(capabilities[0].bytes),
        lockPath: definition.lockPath,
        lockSha256: sha256Bytes(capabilities[1].bytes)
      },
      runtime: {
        nodeVersion: process.version,
        npmVersion
      },
      install: {
        path: `${packageName}/node_modules`,
        ...install
      }
    };
    writeCanonicalSeal(sealPath, seal);
    if (typeof options.afterSealWritten === "function") {
      options.afterSealWritten({ nodeModulesRoot, sealPath });
    }
    verifyNodeInstallSeal({
      repositoryRoot,
      packageName,
      sealPath,
      snapshot,
      runtimeContract
    });
    return seal;
  } finally {
    capabilities.forEach(closeCapability);
    if (temporaryHome !== undefined) {
      fs.rmSync(temporaryHome, { recursive: true, force: false });
      if (fs.existsSync(temporaryHome)) {
        fail("Exact Node temporary state cleanup failed");
      }
    }
  }
}

function verifyNodeInstallSeal(options) {
  const repositoryRoot = path.resolve(options.repositoryRoot || REPOSITORY_ROOT);
  const packageName = options.packageName;
  const definition = exactPackageDefinition(packageName);
  const runtimeContract = options.runtimeContract || {
    nodeVersion: EXPECTED_NODE_VERSION,
    npmVersion: EXPECTED_NPM_VERSION
  };
  if (process.version !== runtimeContract.nodeVersion) {
    fail("Exact Node runtime version differs from policy");
  }
  requirePrivateRepositoryRoot(repositoryRoot);
  const snapshot = options.snapshot || prepare.inspectRepositorySourceSnapshot(
    repositoryRoot,
    options.environment || process.env
  );
  const seal = readCanonicalSeal(path.resolve(options.sealPath));
  validateSealShape(
    seal,
    packageName,
    snapshot,
    definition,
    runtimeContract
  );
  const records = new Map(
    snapshot.inventory.map((record) => [record.path, record])
  );
  const packageRecord = records.get(definition.packagePath);
  const lockRecord = records.get(definition.lockPath);
  if (!packageRecord || !lockRecord) {
    fail("Exact Node reviewed package metadata is missing");
  }
  if (
    seal.package.packageSha256 !== sha256Bytes(
      prepare.readReviewedGitBlob(repositoryRoot, packageRecord.objectId)
    ) ||
    seal.package.lockSha256 !== sha256Bytes(
      prepare.readReviewedGitBlob(repositoryRoot, lockRecord.objectId)
    )
  ) {
    fail("Exact Node install seal differs from reviewed package metadata");
  }
  const observed = inventoryNodeInstall(
    path.join(repositoryRoot, packageName, "node_modules")
  );
  if (canonicalJson(observed) !== canonicalJson({
    bytes: seal.install.bytes,
    contentInventorySha256: seal.install.contentInventorySha256,
    directories: seal.install.directories,
    entries: seal.install.entries,
    files: seal.install.files,
    identitySnapshotSha256: seal.install.identitySnapshotSha256,
    symlinks: seal.install.symlinks
  })) {
    fail("Exact Node install tree differs from its seal");
  }
  return {
    installedContentSha256: seal.install.contentInventorySha256,
    lockSha256: seal.package.lockSha256,
    nodeVersion: seal.runtime.nodeVersion,
    npmVersion: seal.runtime.npmVersion
  };
}

function cleanExactNodeDependencies(options) {
  const repositoryRoot = path.resolve(options.repositoryRoot || REPOSITORY_ROOT);
  const packageName = options.packageName;
  const sealPath = path.resolve(options.sealPath);
  verifyNodeInstallSeal({
    repositoryRoot,
    packageName,
    sealPath,
    environment: options.environment,
    runtimeContract: options.runtimeContract
  });
  const nodeModulesRoot = path.join(repositoryRoot, packageName, "node_modules");
  const packageRoot = path.join(repositoryRoot, packageName);
  if (
    path.dirname(nodeModulesRoot) !== packageRoot ||
    fs.realpathSync.native(packageRoot) !== packageRoot
  ) {
    fail("Exact Node cleanup target is unsafe");
  }
  const sealInfo = fs.lstatSync(sealPath);
  if (
    !sealInfo.isFile() ||
    sealInfo.isSymbolicLink() ||
    sealInfo.uid !== process.geteuid() ||
    sealInfo.nlink !== 1
  ) {
    fail("Exact Node cleanup seal is unsafe");
  }
  fs.rmSync(nodeModulesRoot, { recursive: true });
  fs.rmSync(sealPath);
  if (
    fs.existsSync(nodeModulesRoot) ||
    fs.existsSync(sealPath) ||
    fs.lstatSync(packageRoot).isSymbolicLink()
  ) {
    fail("Exact Node dependency cleanup failed");
  }
}

function discardExactNodeTestDependencies(options) {
  const repositoryRoot = path.resolve(options.repositoryRoot || REPOSITORY_ROOT);
  const packageName = options.packageName;
  const sealPath = path.resolve(options.sealPath);
  const definition = exactPackageDefinition(packageName);
  requirePrivateRepositoryRoot(repositoryRoot);
  const snapshot = prepare.inspectRepositorySourceSnapshot(
    repositoryRoot,
    options.environment || process.env
  );
  const runtimeContract = options.runtimeContract || {
    nodeVersion: EXPECTED_NODE_VERSION,
    npmVersion: EXPECTED_NPM_VERSION
  };
  const seal = readCanonicalSeal(sealPath);
  validateSealShape(
    seal,
    packageName,
    snapshot,
    definition,
    runtimeContract
  );
  const packageRoot = path.join(repositoryRoot, packageName);
  const nodeModulesRoot = path.join(packageRoot, "node_modules");
  let installInfo;
  try {
    installInfo = fs.lstatSync(nodeModulesRoot);
  } catch {
    fail("Exact Node test install cleanup target is missing");
  }
  if (
    path.dirname(nodeModulesRoot) !== packageRoot ||
    fs.realpathSync.native(packageRoot) !== packageRoot ||
    !installInfo.isDirectory() ||
    installInfo.isSymbolicLink() ||
    installInfo.uid !== process.geteuid()
  ) {
    fail("Exact Node test install cleanup target is unsafe");
  }
  const sealInfo = fs.lstatSync(sealPath);
  if (
    !sealInfo.isFile() ||
    sealInfo.isSymbolicLink() ||
    sealInfo.uid !== process.geteuid() ||
    sealInfo.nlink !== 1
  ) {
    fail("Exact Node test install cleanup seal is unsafe");
  }
  fs.rmSync(nodeModulesRoot, { recursive: true });
  fs.rmSync(sealPath);
  if (fs.existsSync(nodeModulesRoot) || fs.existsSync(sealPath)) {
    fail("Exact Node test dependency cleanup failed");
  }
}

function parseArguments(argv) {
  if (!["install", "verify", "clean", "discard-test"].includes(argv[0])) {
    fail("Usage: exact_node_install.cjs MODE --package-root NAME --seal PATH [--npm PATH]");
  }
  const values = { mode: argv[0] };
  for (let index = 1; index < argv.length; index += 2) {
    const name = argv[index];
    const value = argv[index + 1];
    if (!name?.startsWith("--") || value === undefined || values[name]) {
      fail("Exact Node install arguments are invalid");
    }
    values[name] = value;
  }
  if (
    Object.keys(values).filter((name) => name !== "mode").sort().join("\0") !==
      (values.mode === "install"
        ? ["--npm", "--package-root", "--seal"]
        : ["--package-root", "--seal"]).sort().join("\0")
  ) {
    fail("Exact Node install arguments are invalid");
  }
  return values;
}

function main(argv = process.argv.slice(2)) {
  const values = parseArguments(argv);
  const options = {
    repositoryRoot: REPOSITORY_ROOT,
    packageName: values["--package-root"],
    sealPath: values["--seal"],
    temporaryParent: process.env.RUNNER_TEMP,
    environment: process.env
  };
  if (values.mode === "clean") {
    cleanExactNodeDependencies(options);
    process.stdout.write(`${canonicalJson({ cleaned: values["--package-root"] })}\n`);
    return;
  }
  if (values.mode === "discard-test") {
    discardExactNodeTestDependencies(options);
    process.stdout.write(`${canonicalJson({ discardedTest: values["--package-root"] })}\n`);
    return;
  }
  if (values.mode === "verify") {
    const summary = verifyNodeInstallSeal(options);
    process.stdout.write(`${canonicalJson(summary)}\n`);
    return;
  }
  const seal = installExactNodeDependencies({
    ...options,
    npmExecutable: values["--npm"]
  });
  process.stdout.write(`${canonicalJson({
      kind: seal.kind,
      package: seal.package.root,
      lockSha256: seal.package.lockSha256,
      installedContentSha256: seal.install.contentInventorySha256
    })}\n`);
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    const message = error?.message || "Exact Node dependency install failed";
    process.stderr.write(`exact Node dependency install failed: ${message}\n`);
    process.exitCode = 1;
  }
}

module.exports = {
  EXPECTED_NODE_VERSION,
  EXPECTED_NPM_VERSION,
  INSTALL_KIND,
  cleanExactNodeDependencies,
  discardExactNodeTestDependencies,
  installExactNodeDependencies,
  inventoryNodeInstall,
  verifyNodeInstallSeal
};

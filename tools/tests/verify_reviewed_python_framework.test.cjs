"use strict";

const assert = require("node:assert/strict");
const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const verifier = require("../verify_reviewed_python_framework.cjs");

const REPOSITORY_ROOT = path.resolve(__dirname, "../..");
const TOOLCHAIN_LOCK = path.join(
  REPOSITORY_ROOT,
  "backend/packaging/python-sidecar-toolchain.lock.json",
);
const EXPECTED_INVENTORY = path.join(
  REPOSITORY_ROOT,
  "backend/packaging/python-framework-sealed-inventory.json",
);
const KNOWN_FIXTURE_DIGEST =
  "75bbd549d2dec5a10bad3d27f279a010e6fd5992de20dd79f5cf2f7284414735";
const SITE_PACKAGES_README_CONTENT =
  "This directory exists so that 3rd party packages can be installed\n" +
  "here.  Read the source for site.py for more details.\n";
const SYNTHETIC_PAYLOAD_SHA256 = "a".repeat(64);

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function sortEntries(entries) {
  return [...entries].sort((left, right) =>
    verifier.comparePythonStrings(left.path, right.path),
  );
}

function directoryEntry(entryPath, mode = "0755") {
  return { path: entryPath, mode, type: "directory" };
}

function fileEntry(entryPath, content, mode = "0644") {
  const value = Buffer.from(content);
  return {
    path: entryPath,
    mode,
    type: "file",
    size: value.length,
    sha256: sha256(value),
  };
}

function symlinkEntry(entryPath, target, mode = "0777", broken = false) {
  const entry = {
    path: entryPath,
    mode,
    type: "symlink",
    target,
    sha256: sha256(Buffer.from(target, "utf8")),
  };
  if (broken) {
    entry.broken = true;
  }
  return entry;
}

function expectedManifest(sourceEntries, transformations = []) {
  const source = verifier.validateInventoryEntries(
    sortEntries(sourceEntries),
    "Synthetic source framework inventory",
  );
  const entries = verifier.applyExpectedInventoryTransformations(
    source,
    transformations,
  );
  return {
    schemaVersion: verifier.EXPECTED_INVENTORY_SCHEMA_VERSION,
    source: {
      payloadSize: 123,
      payloadSha256: SYNTHETIC_PAYLOAD_SHA256,
      coreEntryCount: source.length,
      coreInventorySha256: verifier.digestInventory(source),
    },
    transformations,
    entryCount: entries.length,
    inventorySha256: verifier.digestInventory(entries),
    entries,
  };
}

function makeSandbox() {
  const temporary = fs.mkdtempSync(
    path.join(fs.realpathSync.native(os.tmpdir()), "lcf-framework-verifier-"),
  );
  const sandbox = fs.realpathSync.native(temporary);
  const root = path.join(sandbox, "root");
  fs.mkdirSync(root, { mode: 0o755 });
  fs.chmodSync(root, 0o755);
  return { root, sandbox };
}

function removeSandbox(sandbox) {
  fs.rmSync(sandbox, { recursive: true, force: true });
}

function withSandbox(callback) {
  const fixture = makeSandbox();
  try {
    return callback(fixture);
  } finally {
    removeSandbox(fixture.sandbox);
  }
}

function writeFile(pathname, content, mode = 0o644) {
  fs.writeFileSync(pathname, content, { mode });
  fs.chmodSync(pathname, mode);
}

function makeKnownFixture(root) {
  writeFile(path.join(root, "alpha.txt"), "alpha\n", 0o644);
  const nested = path.join(root, "nested");
  fs.mkdirSync(nested, { mode: 0o755 });
  fs.chmodSync(nested, 0o755);
  writeFile(path.join(nested, "tool"), "#!/bin/sh\nexit 0\n", 0o755);
}

function makeProductionExclusionFixture(root) {
  makeKnownFixture(root);
  const sitePackages = path.join(
    root,
    ...verifier.SITE_PACKAGES_PATH.split("/"),
  );
  fs.mkdirSync(sitePackages, { recursive: true, mode: 0o755 });
  fs.chmodSync(sitePackages, 0o755);
  writeFile(
    path.join(sitePackages, "README.txt"),
    SITE_PACKAGES_README_CONTENT,
    0o644,
  );
  return sitePackages;
}

function requireRootFixture(t) {
  if (typeof process.getuid !== "function" || process.getuid() !== 0) {
    t.skip("synthetic root-owned framework fixture requires uid 0");
    return false;
  }
  return true;
}

function fingerprint(root, overrides = {}) {
  return verifier.fingerprintInstallRoot(root, {
    excludedPaths: [],
    reviewedBrokenSymlinks: [],
    rejectBytecodeCaches: true,
    ...overrides,
  });
}

test("hard-coded constants exactly match the repository lock", () => {
  const lock = verifier.verifyLockContract(TOOLCHAIN_LOCK);
  assert.equal(lock.python.installRoot, verifier.EXACT_ROOT);
  assert.equal(
    lock.python.frameworkCoreFingerprintSha256,
    verifier.CORE_DIGEST,
  );
  assert.deepEqual(
    lock.python.frameworkCoreFingerprintExcludedPaths,
    verifier.CORE_EXCLUDED_PATHS,
  );
  assert.deepEqual(
    lock.python.frameworkCoreInventory,
    verifier.FRAMEWORK_CORE_INVENTORY_LOCK_CONTRACT,
  );
  assert.deepEqual(
    lock.python.reviewedBrokenSymlinks,
    verifier.REVIEWED_BROKEN_SYMLINKS,
  );
  assert.equal(
    lock.python.distribution.installMethod,
    verifier.PRODUCER_INSTALL_METHOD,
  );
  assert.deepEqual(
    lock.python.distribution.frameworkComponent,
    verifier.FRAMEWORK_COMPONENT_CONTRACT,
  );
  assert.deepEqual(verifier.EXPECTED_INVENTORY_CONTRACT, {
    schemaVersion: 1,
    payloadSize: 32739568,
    payloadSha256:
      "f922c9d7c78f3745dc453211677fbce2e4b415616556b11376a92ca7a17fc391",
    sourceEntryCount: 3654,
    sourceInventorySha256:
      "863a6353e58b9c71dc44847051aa582519a66b9347d8c09915ef5254c694bb5d",
    installedEntryCount: 3648,
    installedInventorySha256:
      "77b58098a5ebc6890e1335eed3afaa1b9bad96029b7b5ad42e45b270b6649d10",
    appleDoubleRemovals: 6,
  });
});

test("a held parsed lock value satisfies the same hard-coded contract", () => {
  const lockValue = JSON.parse(fs.readFileSync(TOOLCHAIN_LOCK, "utf8"));
  assert.equal(verifier.verifyLockValue(lockValue), lockValue);
});

test("the production expected inventory satisfies its exact file and schema contract", () => {
  const content = fs.readFileSync(EXPECTED_INVENTORY);
  assert.equal(
    content.length,
    verifier.FRAMEWORK_CORE_INVENTORY_LOCK_CONTRACT.fileSize,
  );
  assert.equal(
    sha256(content),
    verifier.FRAMEWORK_CORE_INVENTORY_LOCK_CONTRACT.fileSha256,
  );
  const value = verifier.readExpectedInventoryFile(EXPECTED_INVENTORY);
  const validated = verifier.verifyExpectedInventoryProductionContract(value);
  assert.equal(validated.sourceInventory.length, 3654);
  assert.equal(validated.inventory.length, 3648);
  assert.equal(validated.inventorySha256, verifier.CORE_DIGEST);
  assert.equal(validated.transformations.length, 6);
  assert.ok(
    validated.transformations.every(
      (transformation) => transformation.kind === "remove-appledouble",
    ),
  );
  assert.equal(
    validated.inventory.filter((entry) => entry.type === "symlink").length,
    33,
  );
  assert.ok(
    validated.inventory
      .filter((entry) => entry.type === "symlink")
      .every((entry) => entry.mode === "0775"),
  );
});

test("framework verification requires exactly one lock path or held value", () => {
  const lockValue = JSON.parse(fs.readFileSync(TOOLCHAIN_LOCK, "utf8"));
  assert.throws(
    () =>
      verifier.verifyReviewedPythonFramework({
        root: verifier.EXACT_ROOT,
        lock: TOOLCHAIN_LOCK,
        lockValue,
      }),
    /exactly one of lock or lockValue/,
  );
  assert.throws(
    () =>
      verifier.verifyReviewedPythonFramework({
        root: verifier.EXACT_ROOT,
      }),
    /exactly one of lock or lockValue/,
  );
  assert.throws(
    () =>
      verifier.verifyReviewedPythonFramework({
        root: verifier.EXACT_ROOT,
        lockValue,
      }),
    /exactly one of inventory or inventoryValue/,
  );
  assert.throws(
    () =>
      verifier.verifyReviewedPythonFramework({
        root: verifier.EXACT_ROOT,
        lockValue,
        inventory: "/tmp/inventory.json",
        inventoryValue: {},
      }),
    /exactly one of inventory or inventoryValue/,
  );
});

test("a mutable lock cannot override the hard-coded contract", () => {
  withSandbox(({ sandbox }) => {
    const lock = JSON.parse(fs.readFileSync(TOOLCHAIN_LOCK, "utf8"));
    lock.python.frameworkCoreFingerprintSha256 = "0".repeat(64);
    const altered = path.join(sandbox, "altered-lock.json");
    writeFile(altered, `${JSON.stringify(lock)}\n`);
    assert.throws(
      () => verifier.verifyLockContract(altered),
      /differs from the hard-coded framework contract/,
    );
  });
});

test("every producer-contract field is sealed against lock mutation", async (t) => {
  const componentFields = [
    "packageName",
    "bomSize",
    "bomSha256",
    "packageInfoSize",
    "packageInfoSha256",
    "payloadSize",
    "payloadSha256",
    "scriptsSize",
    "scriptsSha256",
    "postinstallSize",
    "postinstallSha256",
    "postinstallMode",
    "noOpPostinstallSize",
    "noOpPostinstallSha256",
    "noOpPostinstallMode",
  ];
  const mutations = [
    {
      name: "installMethod",
      apply(lock) {
        lock.python.distribution.installMethod = "macos-installer";
      },
    },
    ...componentFields.map((field) => ({
      name: `frameworkComponent.${field}`,
      apply(lock) {
        const current = lock.python.distribution.frameworkComponent[field];
        lock.python.distribution.frameworkComponent[field] =
          typeof current === "number" ? current + 1 : `${current}-mutated`;
      },
    })),
  ];

  for (const mutation of mutations) {
    await t.test(mutation.name, () => {
      withSandbox(({ sandbox }) => {
        const lock = JSON.parse(fs.readFileSync(TOOLCHAIN_LOCK, "utf8"));
        mutation.apply(lock);
        assert.throws(
          () => verifier.verifyLockValue(lock),
          /differs from the hard-coded framework contract/,
        );
        const altered = path.join(sandbox, "altered-lock.json");
        writeFile(altered, `${JSON.stringify(lock)}\n`);
        assert.throws(
          () => verifier.verifyLockContract(altered),
          /differs from the hard-coded framework contract/,
        );
      });
    });
  }
});

test("every expected-inventory lock field is sealed against mutation", async (t) => {
  for (const field of Object.keys(
    verifier.FRAMEWORK_CORE_INVENTORY_LOCK_CONTRACT,
  )) {
    await t.test(field, () => {
      const lock = JSON.parse(fs.readFileSync(TOOLCHAIN_LOCK, "utf8"));
      const current = lock.python.frameworkCoreInventory[field];
      lock.python.frameworkCoreInventory[field] =
        typeof current === "number" ? current + 1 : `${current}-mutated`;
      assert.throws(
        () => verifier.verifyLockValue(lock),
        /differs from the hard-coded framework contract/,
      );
    });
  }

  const lock = JSON.parse(fs.readFileSync(TOOLCHAIN_LOCK, "utf8"));
  lock.python.frameworkCoreInventory.unreviewed = true;
  assert.throws(
    () => verifier.verifyLockValue(lock),
    /differs from the hard-coded framework contract/,
  );
});

test("CLI parsing rejects duplicate, missing, and surplus arguments", () => {
  const inventory = path.join(REPOSITORY_ROOT, "expected-inventory.json");
  assert.deepEqual(
    verifier.parseCliArguments([
      "--lock",
      TOOLCHAIN_LOCK,
      "--root",
      verifier.EXACT_ROOT,
      "--inventory",
      inventory,
    ]),
    { root: verifier.EXACT_ROOT, lock: TOOLCHAIN_LOCK, inventory },
  );
  assert.throws(
    () =>
      verifier.parseCliArguments([
        "--root",
        verifier.EXACT_ROOT,
        "--root",
        verifier.EXACT_ROOT,
        "--inventory",
        inventory,
      ]),
    /Usage/,
  );
  assert.throws(
    () => verifier.parseCliArguments(["--root", verifier.EXACT_ROOT]),
    /Usage/,
  );
  assert.throws(
    () =>
      verifier.parseCliArguments([
        "--root",
        verifier.EXACT_ROOT,
        "--lock",
        TOOLCHAIN_LOCK,
        "--inventory",
        inventory,
        "extra",
      ]),
    /Usage/,
  );
});

test("startup environment rejects Node preload controls", () => {
  assert.doesNotThrow(() => verifier.verifyStartupEnvironment({ PATH: "/bin" }));
  assert.doesNotThrow(() =>
    verifier.verifyStartupEnvironment({ NODE_OPTIONS: "", NODE_PATH: "" }),
  );
  assert.throws(
    () => verifier.verifyStartupEnvironment({ NODE_OPTIONS: "--require=hook.cjs" }),
    /NODE_OPTIONS or NODE_PATH/,
  );
  assert.throws(
    () => verifier.verifyStartupEnvironment({ NODE_PATH: "/tmp/modules" }),
    /NODE_OPTIONS or NODE_PATH/,
  );
});

test("canonical JSON recursively sorts keys without ASCII escaping", () => {
  const value = {
    "é": "值",
    b: [{ y: 2, x: 1 }],
    a: { d: 4, c: 3 },
  };
  assert.equal(
    verifier.canonicalJsonBytes(value).toString("utf8"),
    '{"a":{"c":3,"d":4},"b":[{"x":1,"y":2}],"é":"值"}',
  );
});

test("known canonical inventory digest matches Python fingerprinting", () => {
  withSandbox(({ root }) => {
    makeKnownFixture(root);
    const inspected = verifier.inspectInstallRoot(root, {
      excludedPaths: [],
      reviewedBrokenSymlinks: [],
      rejectBytecodeCaches: true,
    });
    assert.equal(inspected.digest, KNOWN_FIXTURE_DIGEST);
    assert.equal(verifier.digestInventory(inspected.inventory), inspected.digest);
    assert.equal(fingerprint(root), inspected.digest);
    assert.deepEqual(
      inspected.inventory.map((entry) => entry.path),
      ["alpha.txt", "nested", "nested/tool"],
    );
  });
});

test("strict expected inventory accepts an exact synthetic manifest", () => {
  const source = sortEntries([
    directoryEntry("bin"),
    fileEntry("bin/python3.13", "synthetic interpreter\n", "0755"),
    directoryEntry("lib"),
  ]);
  const manifest = expectedManifest(source);
  const validated = verifier.validateExpectedInventoryValue(manifest);
  assert.equal(validated.source.coreEntryCount, source.length);
  assert.equal(
    validated.source.coreInventorySha256,
    verifier.digestInventory(source),
  );
  assert.deepEqual(validated.inventory, source);
  assert.equal(
    verifier.verifyInventoryMatch(validated.inventory, source),
    manifest.inventorySha256,
  );
});

test("strict expected inventory removes only exact Installer AppleDouble metadata", () => {
  const target = "Versions/Current/Headers";
  const source = sortEntries([
    fileEntry("Frameworks/Tcl.framework/._carrier", "appledouble\n"),
    symlinkEntry(
      "Frameworks/Tcl.framework/Headers",
      target,
      "0775",
    ),
    fileEntry("payload.txt", "payload\n"),
  ]);
  const carrier = source.find((entry) => entry.path.endsWith("._carrier"));
  const transformations = [
    {
      kind: "remove-appledouble",
      path: carrier.path,
      type: "file",
      mode: "0664",
      size: carrier.size,
      sha256: carrier.sha256,
    },
  ].sort((left, right) =>
    verifier.comparePythonStrings(left.path, right.path),
  );
  const manifest = expectedManifest(source, transformations);
  const validated = verifier.validateExpectedInventoryValue(manifest);
  assert.equal(validated.sourceInventory.length, 3);
  assert.equal(validated.inventory.length, 2);
  assert.equal(
    validated.inventory.find((entry) => entry.type === "symlink").mode,
    "0775",
  );
  assert.equal(
    validated.inventory.some((entry) => entry.path === carrier.path),
    false,
  );
});

test("expected inventory rejects transformations outside the exact contract", () => {
  const target = "payload";
  const source = [symlinkEntry("alias", target, "0775")];
  assert.throws(
    () =>
      verifier.applyExpectedInventoryTransformations(source, [
        {
          kind: "symlink-mode",
          path: "alias",
          type: "symlink",
          target,
          fromMode: "0775",
          toMode: "0777",
        },
      ]),
    /transformation kind is unsupported/,
  );
  assert.throws(
    () =>
      verifier.applyExpectedInventoryTransformations(
        [fileEntry("ordinary", "payload\n")],
        [
          {
            kind: "remove-appledouble",
            path: "ordinary",
            type: "file",
            mode: "0664",
            size: 8,
            sha256: sha256(Buffer.from("payload\n")),
          },
        ],
      ),
    /AppleDouble removal transformation is malformed/,
  );
});

test("inventory comparison classifies non-allowlisted mode and file drift", () => {
  const expected = [fileEntry("payload", "first\n", "0644")];
  const observed = [fileEntry("payload", "second payload\n", "0600")];
  const comparison = verifier.compareInventories(expected, observed);
  assert.equal(comparison.matches, false);
  assert.deepEqual(comparison.differenceCounts, {
    missing: 0,
    extra: 0,
    type: 0,
    mode: 1,
    target: 0,
    size: 1,
    content: 1,
  });
  assert.deepEqual(
    comparison.firstDifferences.map((item) => item.kind),
    ["mode", "size", "content"],
  );
});

test("inventory comparison classifies target, path, and type drift", () => {
  const expected = sortEntries([
    symlinkEntry("alias", "first"),
    directoryEntry("kind"),
    fileEntry("missing", "payload\n"),
  ]);
  const observed = sortEntries([
    symlinkEntry("alias", "second"),
    fileEntry("extra", "payload\n"),
    fileEntry("kind", "payload\n"),
  ]);
  const comparison = verifier.compareInventories(expected, observed);
  assert.deepEqual(comparison.differenceCounts, {
    missing: 1,
    extra: 1,
    type: 1,
    mode: 0,
    target: 1,
    size: 0,
    content: 0,
  });
  assert.equal(
    comparison.firstDifferences.find((item) => item.kind === "extra").path,
    undefined,
  );
  assert.match(
    comparison.firstDifferences.find((item) => item.kind === "extra")
      .pathSha256,
    /^[0-9a-f]{64}$/,
  );
});

test("verification errors carry only bounded sanitized inventory diagnostics", () => {
  const expected = [
    symlinkEntry("nonce-secret/alias", "SECRET_TOKEN_expected-value", "0777"),
  ];
  const observed = [
    symlinkEntry("nonce-secret/alias", "SECRET_TOKEN_observed-value", "0777"),
  ];
  let failure;
  try {
    verifier.verifyInventoryMatch(expected, observed);
  } catch (error) {
    failure = error;
  }
  assert.ok(failure instanceof verifier.VerificationError);
  assert.equal(failure.cause, undefined);
  assert.equal(failure.diagnostics.differenceCounts.target, 1);
  assert.deepEqual(failure.diagnostics.firstDifferences, [
    {
      kind: "target",
      pathSha256: sha256(Buffer.from("nonce-secret/alias", "utf8")),
    },
  ]);
  const formatted = verifier.formatVerificationDiagnostics(failure.diagnostics);
  assert.doesNotMatch(
    formatted,
    /SECRET_TOKEN|nonce-secret|\/Library|\/Users|\/tmp/,
  );
  assert.doesNotMatch(formatted, /expected-value|observed-value/);
  assert.match(formatted, /target:1/);
});

test("diagnostics truncate at twenty records and hash every extra path", () => {
  const expected = [fileEntry("anchor", "anchor\n")];
  const secretNames = Array.from(
    { length: verifier.MAX_DIAGNOSTIC_DIFFERENCES + 7 },
    (_value, index) => `extras/SECRET_TOKEN_value_${String(index).padStart(2, "0")}`,
  );
  const observed = sortEntries([
    ...expected,
    ...secretNames.map((entryPath) => fileEntry(entryPath, "extra\n")),
  ]);
  const comparison = verifier.compareInventories(expected, observed);
  assert.equal(comparison.differenceCounts.extra, secretNames.length);
  assert.equal(
    comparison.firstDifferences.length,
    verifier.MAX_DIAGNOSTIC_DIFFERENCES,
  );
  assert.equal(comparison.truncated, true);
  assert.ok(
    comparison.firstDifferences.every(
      (item) => item.kind === "extra" && item.path === undefined &&
        /^[0-9a-f]{64}$/.test(item.pathSha256),
    ),
  );
  const formatted = verifier.formatVerificationDiagnostics(comparison);
  assert.doesNotMatch(formatted, /SECRET_TOKEN|value_\d/);
  assert.match(formatted, /truncated=true/);
});

test("expected inventory reader rejects symlinks and hardlinks", () => {
  withSandbox(({ root }) => {
    const manifest = expectedManifest([fileEntry("payload", "payload\n")]);
    const source = path.join(root, "inventory.json");
    writeFile(source, `${JSON.stringify(manifest, null, 2)}\n`);
    assert.deepEqual(verifier.readExpectedInventoryFile(source), manifest);

    const symlink = path.join(root, "inventory-link.json");
    fs.symlinkSync("inventory.json", symlink);
    assert.throws(
      () => verifier.readExpectedInventoryFile(symlink),
      /must be one regular file/,
    );

    const hardlinkSource = path.join(root, "inventory-hard-source.json");
    const hardlink = path.join(root, "inventory-hard.json");
    writeFile(hardlinkSource, `${JSON.stringify(manifest)}\n`);
    fs.linkSync(hardlinkSource, hardlink);
    assert.throws(
      () => verifier.readExpectedInventoryFile(hardlink),
      /must be one regular file/,
    );
  });
});

test("expected inventory reader rejects pathname replacement and identity drift", () => {
  withSandbox(({ root }) => {
    const manifest = expectedManifest([fileEntry("payload", "payload\n")]);
    const content = `${JSON.stringify(manifest, null, 2)}\n`;
    const pathname = path.join(root, "inventory.json");
    const replacement = path.join(root, "replacement.json");
    writeFile(pathname, content);
    writeFile(replacement, content);

    const originalRead = fs.readSync;
    let replaced = false;
    fs.readSync = function replaceAfterRead(...args) {
      const count = originalRead.apply(this, args);
      if (!replaced) {
        replaced = true;
        fs.renameSync(replacement, pathname);
      }
      return count;
    };
    try {
      assert.throws(
        () => verifier.readExpectedInventoryFile(pathname),
        /changed while reading/,
      );
    } finally {
      fs.readSync = originalRead;
    }

    writeFile(replacement, content);
    let changedMode = false;
    fs.readSync = function changeModeAfterRead(...args) {
      const count = originalRead.apply(this, args);
      if (!changedMode) {
        changedMode = true;
        fs.chmodSync(pathname, 0o600);
      }
      return count;
    };
    try {
      assert.throws(
        () => verifier.readExpectedInventoryFile(pathname),
        /changed while reading/,
      );
    } finally {
      fs.readSync = originalRead;
    }
  });
});

test("excluded subtree contents do not affect the digest", () => {
  withSandbox(({ root }) => {
    makeKnownFixture(root);
    const options = { excludedPaths: ["dynamic"] };
    const before = fingerprint(root, options);
    const dynamic = path.join(root, "dynamic");
    fs.mkdirSync(dynamic, { mode: 0o700 });
    writeFile(path.join(dynamic, "mutable.txt"), "first\n", 0o600);
    const afterAddition = fingerprint(root, options);
    writeFile(path.join(dynamic, "mutable.txt"), "second\n", 0o755);
    fs.mkdirSync(path.join(dynamic, "nested"), { mode: 0o777 });
    const afterDrift = fingerprint(root, options);
    assert.equal(before, KNOWN_FIXTURE_DIGEST);
    assert.equal(afterAddition, before);
    assert.equal(afterDrift, before);
  });
});

test("regular-file byte drift changes the digest", () => {
  withSandbox(({ root }) => {
    makeKnownFixture(root);
    const before = fingerprint(root);
    writeFile(path.join(root, "alpha.txt"), "omega\n", 0o644);
    assert.notEqual(fingerprint(root), before);
  });
});

test("mode drift changes the digest", () => {
  withSandbox(({ root }) => {
    makeKnownFixture(root);
    const before = fingerprint(root);
    fs.chmodSync(path.join(root, "alpha.txt"), 0o600);
    assert.notEqual(fingerprint(root), before);
  });
});

test("contained symlink target drift changes the digest", () => {
  withSandbox(({ root }) => {
    writeFile(path.join(root, "first"), "same\n", 0o644);
    writeFile(path.join(root, "second"), "same\n", 0o644);
    const link = path.join(root, "alias");
    fs.symlinkSync("first", link);
    const before = fingerprint(root);
    fs.unlinkSync(link);
    fs.symlinkSync("second", link);
    assert.notEqual(fingerprint(root), before);
  });
});

test("escaping and absolute symlinks are rejected", () => {
  withSandbox(({ root, sandbox }) => {
    writeFile(path.join(root, "safe"), "safe\n");
    writeFile(path.join(sandbox, "outside"), "outside\n");
    fs.symlinkSync("../outside", path.join(root, "escape"));
    assert.throws(() => fingerprint(root), /escaping symlink/);
    fs.unlinkSync(path.join(root, "escape"));
    fs.symlinkSync(path.join(root, "safe"), path.join(root, "absolute"));
    assert.throws(() => fingerprint(root), /unsafe symlink/);
  });
});

test("only the exact reviewed broken symlink set is accepted", () => {
  withSandbox(({ root }) => {
    writeFile(path.join(root, "payload"), "payload\n");
    fs.symlinkSync("missing", path.join(root, "broken"));
    assert.throws(() => fingerprint(root), /unreviewed broken symlink/);
    const reviewed = [{ path: "broken", target: "missing" }];
    assert.match(
      fingerprint(root, { reviewedBrokenSymlinks: reviewed }),
      /^[0-9a-f]{64}$/,
    );
    fs.unlinkSync(path.join(root, "broken"));
    assert.throws(
      () => fingerprint(root, { reviewedBrokenSymlinks: reviewed }),
      /broken symlink set changed/,
    );
  });
});

test("cache names are rejected case-insensitively for every file type", async (t) => {
  const cases = [
    {
      name: "directory component",
      create(root) {
        fs.mkdirSync(path.join(root, "__pycache__"));
      },
    },
    {
      name: "bare .pyc regular file",
      create(root) {
        writeFile(path.join(root, ".pyc"), "cache\n");
      },
    },
    {
      name: "uppercase symlink suffix",
      create(root) {
        fs.symlinkSync("payload", path.join(root, "X.PYO"));
      },
    },
    {
      name: "uppercase cache subtree inside an exclusion",
      excludedPaths: ["dynamic"],
      create(root) {
        const cache = path.join(root, "dynamic", "__PYCACHE__");
        fs.mkdirSync(cache, { recursive: true });
        writeFile(path.join(cache, "X.PYC"), "cache\n");
      },
    },
  ];
  for (const item of cases) {
    await t.test(item.name, () => {
      withSandbox(({ root }) => {
        writeFile(path.join(root, "payload"), "payload\n");
        item.create(root);
        assert.throws(
          () =>
            fingerprint(root, {
              excludedPaths: item.excludedPaths || [],
            }),
          /bytecode cache/,
        );
      });
    });
  }
});

test("Python-compatible fingerprint mode skips casefolded caches", () => {
  withSandbox(({ root }) => {
    makeKnownFixture(root);
    const before = fingerprint(root, { rejectBytecodeCaches: false });
    const cache = path.join(root, "nested", "__PYCACHE__");
    fs.mkdirSync(cache);
    writeFile(path.join(cache, "TOOL.CPYTHON-313.PYC"), "cache\n");
    assert.equal(
      fingerprint(root, { rejectBytecodeCaches: false }),
      before,
    );
  });
});

test("production exclusion closure accepts only the reviewed site-packages README", (t) => {
  if (!requireRootFixture(t)) {
    return;
  }
  withSandbox(({ root }) => {
    makeProductionExclusionFixture(root);
    assert.match(
      verifier.verifyProductionExclusionClosure(root, {
        reviewedBrokenSymlinks: [],
      }),
      /^[0-9a-f]{64}$/,
    );
  });
});

test("production exclusion closure rejects stale sitecustomize code", (t) => {
  if (!requireRootFixture(t)) {
    return;
  }
  withSandbox(({ root }) => {
    const sitePackages = makeProductionExclusionFixture(root);
    writeFile(path.join(sitePackages, "sitecustomize.py"), "raise SystemExit\n");
    assert.throws(
      () =>
        verifier.verifyProductionExclusionClosure(root, {
          reviewedBrokenSymlinks: [],
        }),
      /site-packages contains an unexpected entry/,
    );
  });
});

test("production exclusion closure rejects README content tampering", (t) => {
  if (!requireRootFixture(t)) {
    return;
  }
  withSandbox(({ root }) => {
    const sitePackages = makeProductionExclusionFixture(root);
    const tampered = Buffer.from(SITE_PACKAGES_README_CONTENT, "utf8");
    tampered[0] ^= 1;
    writeFile(path.join(sitePackages, "README.txt"), tampered, 0o644);
    assert.throws(
      () =>
        verifier.verifyProductionExclusionClosure(root, {
          reviewedBrokenSymlinks: [],
        }),
      /README content changed/,
    );
  });
});

test("production exclusion closure rejects every other excluded path", (t) => {
  if (!requireRootFixture(t)) {
    return;
  }
  withSandbox(({ root }) => {
    makeProductionExclusionFixture(root);
    const unexpected = path.join(root, "bin", "pip");
    fs.mkdirSync(path.dirname(unexpected), { recursive: true, mode: 0o755 });
    writeFile(unexpected, "#!/bin/sh\n", 0o755);
    assert.throws(
      () =>
        verifier.verifyProductionExclusionClosure(root, {
          reviewedBrokenSymlinks: [],
        }),
      /dynamic exclusion unexpectedly exists/,
    );
  });
});

test("filesystem special entries are rejected", () => {
  withSandbox(({ root }) => {
    writeFile(path.join(root, "payload"), "payload\n");
    childProcess.execFileSync("/usr/bin/mkfifo", [path.join(root, "special.fifo")], {
      stdio: "ignore",
    });
    assert.throws(() => fingerprint(root), /special file/);
  });
});

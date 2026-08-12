"use strict";

const assert = require("node:assert/strict");
const childProcess = require("node:child_process");
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
const KNOWN_FIXTURE_DIGEST =
  "75bbd549d2dec5a10bad3d27f279a010e6fd5992de20dd79f5cf2f7284414735";
const SITE_PACKAGES_README_CONTENT =
  "This directory exists so that 3rd party packages can be installed\n" +
  "here.  Read the source for site.py for more details.\n";

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
});

test("a held parsed lock value satisfies the same hard-coded contract", () => {
  const lockValue = JSON.parse(fs.readFileSync(TOOLCHAIN_LOCK, "utf8"));
  assert.equal(verifier.verifyLockValue(lockValue), lockValue);
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

test("CLI parsing rejects duplicate, missing, and surplus arguments", () => {
  assert.deepEqual(
    verifier.parseCliArguments([
      "--lock",
      TOOLCHAIN_LOCK,
      "--root",
      verifier.EXACT_ROOT,
    ]),
    { root: verifier.EXACT_ROOT, lock: TOOLCHAIN_LOCK },
  );
  assert.throws(
    () =>
      verifier.parseCliArguments([
        "--root",
        verifier.EXACT_ROOT,
        "--root",
        verifier.EXACT_ROOT,
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
    assert.equal(fingerprint(root), KNOWN_FIXTURE_DIGEST);
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

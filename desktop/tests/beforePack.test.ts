import {
  appendFile,
  chmod,
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { afterEach, describe, expect, it } from "vitest";

type JsonObject = Record<string, any>;
type NativeInspector = (
  absolutePath: string,
  relativePath: string
) => string[];
type SourceInspector = (
  environment: NodeJS.ProcessEnv
) => {
  archiveSize: number;
  archiveSha256: string;
  hashManifestSize: number;
  hashManifestSha256: string;
};
type RepositoryInspector = (
  repositoryRoot: string
) => {
  commit: string;
  tree: string;
  sourceDateEpoch: number;
  sourceSnapshotSha256: string;
};

const gate = require("../scripts/beforePack.cjs") as {
  FIXED_CRITICAL_INPUTS: readonly string[];
  auditPythonSidecar(options: {
    repositoryRoot: string;
    stagingRoot: string;
    environment: NodeJS.ProcessEnv;
    platform: string;
    architecture: string;
    inspectNative: NativeInspector;
    inspectSource: SourceInspector;
    inspectRepository: RepositoryInspector;
  }): {
    files: number;
    nativeFiles: number;
    components: number;
    repositoryCommit: string;
    repositoryTree: string;
    sourceSnapshotSha256: string;
    normalizedInventorySha256: string;
    manifest: JsonObject;
    manifestSha256: string;
  };
  buildFileInventory(root: string): JsonObject[];
  canonicalJson(value: unknown): string;
  createBeforePackHook(dependencies: {
    platform: string;
    architecture?: string;
    inspectRepository?: RepositoryInspector;
    auditPythonSidecar?: () => JsonObject;
    auditQmdRuntime?: () => JsonObject;
    auditCompanion?: () => JsonObject;
    auditRenderer?: () => JsonObject;
    auditUpdateTrustAnchor?: () => JsonObject;
  }): (context: {
    electronPlatformName: string;
    arch?: number | string;
  }) => Promise<unknown>;
  criticalInputDigests(root: string): Record<string, string>;
  inspectRepositoryProvenance(
    repositoryRoot: string,
    environment?: NodeJS.ProcessEnv
  ): {
    commit: string;
    tree: string;
    sourceDateEpoch: number;
    sourceSnapshotSha256: string;
  };
  normalizedInventorySha256(
    files: JsonObject[],
    native: JsonObject[]
  ): string;
};

const repositoryRoot = path.resolve(__dirname, "..", "..");
const schemaSource = path.join(
  repositoryRoot,
  "runtime",
  "python-sidecar-build-manifest.schema.json"
);
const toolchainSource = path.join(
  repositoryRoot,
  "backend",
  "packaging",
  "python-sidecar-toolchain.lock.json"
);
const versionSource = path.join(repositoryRoot, "runtime", "version.json");
const temporaryDirectories: string[] = [];

interface Fixture {
  root: string;
  stagingRoot: string;
  manifestPath: string;
  executablePath: string;
  environment: NodeJS.ProcessEnv;
  toolchain: JsonObject;
}

interface ToolchainMutationCase {
  name: string;
  mutate: (toolchain: JsonObject) => void;
  expected: RegExp;
}

const toolchainMutationCases: ToolchainMutationCase[] = [
  {
    name: "missing Python field",
    mutate: (toolchain) => {
      delete toolchain.python.interpreterSize;
    },
    expected: /Toolchain Python does not match the reviewed schema/
  },
  {
    name: "extra Python field",
    mutate: (toolchain) => {
      toolchain.python.unreviewed = true;
    },
    expected: /Toolchain Python does not match the reviewed schema/
  },
  {
    name: "interpreter size",
    mutate: (toolchain) => {
      toolchain.python.interpreterSize += 1;
    },
    expected: /execution closure differs from the reviewed lock/
  },
  {
    name: "interpreter hash",
    mutate: (toolchain) => {
      toolchain.python.interpreterSha256 = "0".repeat(64);
    },
    expected: /execution closure differs from the reviewed lock/
  },
  {
    name: "framework binary size",
    mutate: (toolchain) => {
      toolchain.python.frameworkBinarySize += 1;
    },
    expected: /execution closure differs from the reviewed lock/
  },
  {
    name: "framework binary hash",
    mutate: (toolchain) => {
      toolchain.python.frameworkBinarySha256 = "0".repeat(64);
    },
    expected: /execution closure differs from the reviewed lock/
  },
  {
    name: "framework core exclusions",
    mutate: (toolchain) => {
      toolchain.python.frameworkCoreFingerprintExcludedPaths.pop();
    },
    expected: /framework core differs from the reviewed lock/
  },
  {
    name: "framework core hash",
    mutate: (toolchain) => {
      toolchain.python.frameworkCoreFingerprintSha256 = "0".repeat(64);
    },
    expected: /framework core differs from the reviewed lock/
  },
  {
    name: "install method",
    mutate: (toolchain) => {
      toolchain.python.distribution.installMethod =
        "macos-installer-pkg-direct";
    },
    expected: /distribution evidence is incomplete/
  },
  {
    name: "missing framework component field",
    mutate: (toolchain) => {
      delete toolchain.python.distribution.frameworkComponent.payloadSize;
    },
    expected: /framework component does not match the reviewed schema/
  },
  {
    name: "extra framework component field",
    mutate: (toolchain) => {
      toolchain.python.distribution.frameworkComponent.unreviewed = true;
    },
    expected: /framework component does not match the reviewed schema/
  },
  {
    name: "framework component size",
    mutate: (toolchain) => {
      toolchain.python.distribution.frameworkComponent.payloadSize += 1;
    },
    expected: /framework component differs from the reviewed contract/
  },
  {
    name: "framework component hash",
    mutate: (toolchain) => {
      toolchain.python.distribution.frameworkComponent.payloadSha256 =
        "0".repeat(64);
    },
    expected: /framework component differs from the reviewed contract/
  },
  {
    name: "framework component mode",
    mutate: (toolchain) => {
      toolchain.python.distribution.frameworkComponent.noOpPostinstallMode =
        "0700";
    },
    expected: /framework component differs from the reviewed contract/
  },
  {
    name: "framework component package",
    mutate: (toolchain) => {
      toolchain.python.distribution.frameworkComponent.packageName =
        "Unreviewed_Framework.pkg";
    },
    expected: /framework component differs from the reviewed contract/
  }
];

async function writeFixtureFile(
  root: string,
  relative: string,
  contents: string | Buffer,
  mode?: number
): Promise<void> {
  const destination = path.join(root, ...relative.split("/"));
  await mkdir(path.dirname(destination), { recursive: true });
  await writeFile(destination, contents, mode === undefined ? {} : { mode });
}

async function readJson(filePath: string): Promise<JsonObject> {
  return JSON.parse(await readFile(filePath, "utf8")) as JsonObject;
}

async function writeJson(
  filePath: string,
  value: JsonObject
): Promise<void> {
  await writeFile(filePath, `${gate.canonicalJson(value)}\n`);
}

async function mutateManifest(
  fixture: Fixture,
  mutate: (manifest: JsonObject) => void | Promise<void>
): Promise<JsonObject> {
  const manifest = await readJson(fixture.manifestPath);
  await mutate(manifest);
  await writeJson(fixture.manifestPath, manifest);
  return manifest;
}

function requiredComponents(toolchain: JsonObject): JsonObject[] {
  const versions: Record<string, string> = {
    certifi: "2026.7.22",
    cpython: toolchain.python.version,
    dulwich: "1.2.11",
    openssl: "3.5.4",
    "pydantic-core": "2.41.5",
    "pyinstaller-bootloader": toolchain.tools.pyinstaller,
    "python-hashlib": toolchain.python.version,
    sqlite: "3.50.4",
    urllib3: "2.7.0",
    pyinstaller: toolchain.tools.pyinstaller,
    "pyinstaller-hooks-contrib":
      toolchain.tools.pyinstallerHooksContrib,
    uv: toolchain.tools.uv
  };
  const buildTools = new Set([
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "uv"
  ]);
  return Object.entries(versions).map(([name, version]) => ({
    name,
    version,
    scope: buildTools.has(name) ? "build-tool" : "runtime",
    licenseExpression: "MIT",
    licenseFiles: ["licenses/NOTICE.txt"]
  }));
}

async function createFixture(): Promise<Fixture> {
  const root = await mkdtemp(path.join(os.tmpdir(), "lcf-before-pack-"));
  temporaryDirectories.push(root);
  const stagingRoot = path.join(root, "desktop", "generated", "sidecar");
  const manifestPath = path.join(stagingRoot, "build-manifest.json");
  const executablePath = path.join(stagingRoot, "lcf-service");

  for (const relative of gate.FIXED_CRITICAL_INPUTS) {
    await writeFixtureFile(root, relative, `fixture:${relative}\n`);
  }
  await writeFixtureFile(
    root,
    "backend/packaging/notices/fixture.txt",
    "fixture notice\n"
  );

  const [schemaBytes, toolchainBytes, versionBytes] = await Promise.all([
    readFile(schemaSource),
    readFile(toolchainSource),
    readFile(versionSource)
  ]);
  await Promise.all([
    writeFixtureFile(
      root,
      "runtime/python-sidecar-build-manifest.schema.json",
      schemaBytes
    ),
    writeFixtureFile(
      root,
      "backend/packaging/python-sidecar-toolchain.lock.json",
      toolchainBytes
    ),
    writeFixtureFile(root, "runtime/version.json", versionBytes)
  ]);

  const toolchain = JSON.parse(toolchainBytes.toString("utf8")) as JsonObject;
  const versions = JSON.parse(versionBytes.toString("utf8")) as JsonObject;
  const components = requiredComponents(toolchain);
  const caBundle = Buffer.from("fixture CA bundle\n", "utf8");
  const caBundleSha256 = require("node:crypto")
    .createHash("sha256")
    .update(caBundle)
    .digest("hex") as string;
  const certifi = components.find((component) => component.name === "certifi");
  if (!certifi) {
    throw new Error("fixture certifi component is missing");
  }
  certifi.properties = {
    caBundlePath: "certifi/cacert.pem",
    caBundleSha256
  };

  await Promise.all([
    writeFixtureFile(
      root,
      "desktop/generated/sidecar/lcf-service",
      Buffer.concat([
        Buffer.from([0xcf, 0xfa, 0xed, 0xfe]),
        Buffer.from("fixture-arm64-sidecar\n")
      ]),
      0o755
    ),
    writeFixtureFile(
      root,
      "desktop/generated/sidecar/licenses/NOTICE.txt",
      "fixture licenses\n"
    ),
    writeFixtureFile(
      root,
      "desktop/generated/sidecar/certifi/cacert.pem",
      caBundle
    ),
    writeFixtureFile(
      root,
      "desktop/generated/sidecar/THIRD-PARTY-NOTICES.txt",
      "fixture third-party notices\n"
    ),
    writeFixtureFile(
      root,
      "desktop/generated/sidecar/sbom.spdx.json",
      `${JSON.stringify({
        spdxVersion: "SPDX-2.3",
        dataLicense: "CC0-1.0",
        packages: components.map((component) => ({ name: component.name }))
      })}\n`
    )
  ]);
  await chmod(executablePath, 0o755);

  const environment: NodeJS.ProcessEnv = {
    GITHUB_SHA: "9".repeat(40),
    LCF_SOURCE_SHA: "a".repeat(40),
    LCF_SOURCE_TREE: "b".repeat(40),
    LCF_SOURCE_SNAPSHOT_SHA256: "c".repeat(64),
    LCF_SOURCE_DATE_EPOCH: "1700000000",
    LCF_RENDERER_PACKAGE_LOCK_SHA256: "d".repeat(64),
    ImageVersion: "20260731.1.0",
    LCF_PYTHON_DISTRIBUTION_ARCHIVE:
      "/private/fixture/python-distribution.tar.gz",
    LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST:
      "/private/fixture/hashes.sha256",
    LCF_PYTHON_INSTALL_ROOT: toolchain.python.installRoot
  };
  for (const input of toolchain.requiredCiInputs as string[]) {
    environment[input] ??= `fixture-${input}`;
  }

  const native = [
    {
      path: "lcf-service",
      architectures: ["arm64"],
      dylibs: ["/usr/lib/libSystem.B.dylib"],
      rpaths: [],
      platform: "macos",
      minimumMacosVersion: "13.0",
      codeSignature: "valid"
    }
  ];
  const inputDigests = gate.criticalInputDigests(root);
  const buildTools = {
    altgraphVersion: "0.17.4",
    macholibVersion: "1.16.3",
    packagingVersion: "26.2",
    pyinstallerVersion: "6.21.0",
    pyinstallerHooksContribVersion: "2026.6",
    setuptoolsVersion: "83.0.0",
    uvVersion: "0.11.29"
  };
  const toolchainFiles = [
    { path: ".", type: "directory", mode: "0555", size: 0 }
  ];
  const installedTreeContentSha256 = createHash("sha256")
    .update(
      Buffer.from(
        gate.canonicalJson({ schemaVersion: 1, entries: toolchainFiles }),
        "utf8"
      )
    )
    .digest("hex");
  const pythonToolchain = {
    buildRequirementsLockSha256:
      inputDigests["backend/packaging/build-requirements.lock"],
    runtimeLockSha256: inputDigests["backend/uv.lock"],
    runtimeRequirementsSha256: "e".repeat(64),
    installedTreeContentSha256,
    buildTools
  };
  await writeFixtureFile(
    root,
    "desktop/generated/sidecar/python-build-toolchain.json",
    `${gate.canonicalJson({
      $schema: "python-sidecar-toolchain-evidence.json",
      schemaVersion: 1,
      ...pythonToolchain,
      files: toolchainFiles
    })}\n`
  );
  const files = gate.buildFileInventory(stagingRoot);
  const distribution = toolchain.python.distribution;
  const manifest: JsonObject = {
    $schema: "python-sidecar-build-manifest.schema.json",
    schemaVersion: 1,
    kind: "local-context-forge-python-sidecar",
    entrypoint: "lcf-service",
    product: {
      appVersion: versions.productVersion,
      pythonDistributionVersion: versions.pythonDistributionVersion,
      desktopProtocol: versions.desktopProtocol,
      databaseSchema: versions.databaseSchema
    },
    target: {
      os: toolchain.target.os,
      architecture: toolchain.target.architecture
    },
    build: {
      repositoryCommit: environment.LCF_SOURCE_SHA,
      repositoryTree: environment.LCF_SOURCE_TREE,
      sourceSnapshotSha256: "c".repeat(64),
      sourceDateEpoch: Number(environment.LCF_SOURCE_DATE_EPOCH),
      runnerImage: toolchain.target.runnerLabel,
      runnerImageVersion: environment.ImageVersion,
      macosDeploymentTarget: toolchain.target.deploymentTarget,
      xcodeVersion: "16.4",
      sdkVersion: "15.5",
      uvVersion: toolchain.tools.uv,
      pyinstallerVersion: toolchain.tools.pyinstaller,
      pyinstallerHooksContribVersion:
        toolchain.tools.pyinstallerHooksContrib,
      python: {
        implementation: toolchain.python.implementation,
        version: toolchain.python.version,
        installRoot: toolchain.python.installRoot,
        provider: distribution.provider,
        releaseTag: distribution.releaseTag,
        archiveName: distribution.archiveName,
        archiveSource: distribution.archiveSource,
        archiveSha256: distribution.archiveSha256,
        installerPackageName: distribution.installerPackageName,
        installerPackageSha256: distribution.installerPackageSha256,
        hashManifestName: distribution.hashManifestName,
        hashManifestSource: distribution.hashManifestSource,
        hashManifestSha256: distribution.hashManifestSha256,
        installRootFingerprintSha256: "b".repeat(64)
      },
      pythonToolchain,
      inputDigests
    },
    components,
    artifacts: {
      spdxSbom: "sbom.spdx.json",
      thirdPartyNotices: "THIRD-PARTY-NOTICES.txt",
      licensesDirectory: "licenses",
      pythonBuildToolchain: "python-build-toolchain.json"
    },
    files,
    native,
    audit: {
      status: "pass",
      policyVersion: 1,
      normalizedInventorySha256:
        gate.normalizedInventorySha256(files, native),
      frozenSmoke: {
        status: "pass",
        pathTrap: true,
        checks: [
          "version",
          "doctor",
          "uds-handshake",
          "uds-health",
          "domain-ingest",
          "domain-publish",
          "domain-lint"
        ]
      }
    }
  };
  await writeJson(manifestPath, manifest);
  return {
    root,
    stagingRoot,
    manifestPath,
    executablePath,
    environment,
    toolchain
  };
}

function auditFixture(
  fixture: Fixture,
  inspectNative: NativeInspector = () => ["arm64"],
  inspectSource: SourceInspector = () => ({
    archiveSize: fixture.toolchain.python.distribution.archiveSize,
    archiveSha256:
      fixture.toolchain.python.distribution.archiveSha256,
    hashManifestSize:
      fixture.toolchain.python.distribution.hashManifestSize,
    hashManifestSha256:
      fixture.toolchain.python.distribution.hashManifestSha256
  }),
  inspectRepository: RepositoryInspector = () => ({
    commit: fixture.environment.LCF_SOURCE_SHA as string,
    tree: fixture.environment.LCF_SOURCE_TREE as string,
    sourceDateEpoch: Number(
      fixture.environment.LCF_SOURCE_DATE_EPOCH
    ),
    sourceSnapshotSha256: "c".repeat(64)
  })
): JsonObject {
  return gate.auditPythonSidecar({
    repositoryRoot: fixture.root,
    stagingRoot: fixture.stagingRoot,
    environment: fixture.environment,
    platform: "darwin",
    architecture: "arm64",
    inspectNative,
    inspectSource,
    inspectRepository
  });
}

afterEach(async () => {
  await Promise.all(
    temporaryDirectories
      .splice(0)
      .map((directory) => rm(directory, { recursive: true, force: true }))
  );
});

describe("Python sidecar beforePack gate", () => {
  it("runs Python, QMD, companion, and renderer audits in the native gate", async () => {
    const calls: string[] = [];
    const hook = gate.createBeforePackHook({
      platform: "darwin",
      architecture: "arm64",
      inspectRepository: () => {
        calls.push("repository");
        return {
          commit: "a".repeat(40),
          tree: "b".repeat(40),
          sourceDateEpoch: 1_800_000_000,
          sourceSnapshotSha256: "c".repeat(64)
        };
      },
      auditPythonSidecar: () => {
        calls.push("python");
        return { files: 1 };
      },
      auditQmdRuntime: () => {
        calls.push("qmd");
        return { files: 2 };
      },
      auditCompanion: () => {
        calls.push("companion");
        return { files: 3 };
      },
      auditRenderer: () => {
        calls.push("renderer");
        return { files: 4 };
      },
      auditUpdateTrustAnchor: () => {
        calls.push("update-trust");
        return { algorithm: "Ed25519" };
      }
    });

    await expect(
      hook({ electronPlatformName: "darwin", arch: "arm64" })
    ).resolves.toEqual({
      python: { files: 1 },
      qmd: { files: 2 },
      companion: { files: 3 },
      renderer: { files: 4 },
      updateTrust: { algorithm: "Ed25519" }
    });
    expect(calls).toEqual([
      "repository",
      "python",
      "qmd",
      "companion",
      "renderer",
      "update-trust"
    ]);
  });

  it("accepts one exact, canonical, arm64 audited staging", async () => {
    const fixture = await createFixture();
    const inspected: string[] = [];

    const summary = auditFixture(fixture, (_absolute, relative) => {
      inspected.push(relative);
      return ["arm64"];
    });

    expect(summary).toMatchObject({
      nativeFiles: 1,
      components: 12
    });
    expect(summary.files).toBeGreaterThan(5);
    expect(inspected).toEqual(["lcf-service"]);
  });

  it.each(toolchainMutationCases)(
    "rejects reviewed Python toolchain mutation: $name",
    async ({ mutate, expected }) => {
      const fixture = await createFixture();
      mutate(fixture.toolchain);
      await writeJson(
        path.join(
          fixture.root,
          "backend",
          "packaging",
          "python-sidecar-toolchain.lock.json"
        ),
        fixture.toolchain
      );

      expect(() => auditFixture(fixture)).toThrow(expected);
    }
  );

  it("rejects hostile local Git config before provenance commands can use it", async () => {
    const canonicalTemporaryParent = await realpath(os.tmpdir());
    const root = await mkdtemp(
      path.join(canonicalTemporaryParent, "lcf-before-pack-git-")
    );
    temporaryDirectories.push(root);
    const gitEnvironment = {
      PATH: "/usr/bin:/bin",
      LANG: "C",
      LC_ALL: "C",
      GIT_CONFIG_NOSYSTEM: "1",
      GIT_CONFIG_GLOBAL: "/dev/null",
      GIT_TERMINAL_PROMPT: "0"
    };
    const git = (...arguments_: string[]): string =>
      execFileSync("/usr/bin/git", ["-C", root, ...arguments_], {
        encoding: "utf8",
        env: gitEnvironment
      }).trim();
    git("init", "--quiet");
    await mkdir(path.join(root, "desktop"), { recursive: true });
    await mkdir(path.join(root, "web"), { recursive: true });
    await writeFile(path.join(root, "tracked.txt"), "reviewed\n");
    await writeFile(
      path.join(root, "desktop", "package.json"),
      '{"name":"fixture","version":"0.0.0"}\n'
    );
    const packageLock = path.join(root, "web", "package-lock.json");
    await writeFile(packageLock, '{"lockfileVersion":3}\n');
    git("add", "--all");
    git(
      "-c",
      "user.name=LCF Test",
      "-c",
      "user.email=lcf-test@example.invalid",
      "commit",
      "--quiet",
      "-m",
      "fixture"
    );
    const commit = git("rev-parse", "HEAD");
    const tree = git("rev-parse", "HEAD^{tree}");
    const sourceDateEpoch = git("show", "-s", "--format=%ct", "HEAD");
    const inventory = git("ls-tree", "-r", "--full-tree", "HEAD")
      .split("\n")
      .filter(Boolean)
      .map((line) => {
        const match = /^(\d+) (\w+) ([0-9a-f]{40})\t(.+)$/.exec(line);
        if (!match) {
          throw new Error("invalid Git fixture inventory");
        }
        return {
          mode: match[1],
          objectId: match[3],
          path: match[4],
          type: match[2]
        };
      });
    const environment = {
      LCF_SOURCE_SHA: commit,
      LCF_SOURCE_TREE: tree,
      LCF_SOURCE_DATE_EPOCH: sourceDateEpoch,
      LCF_SOURCE_SNAPSHOT_SHA256: createHash("sha256")
        .update(Buffer.from(JSON.stringify(inventory), "utf8"))
        .digest("hex"),
      LCF_RENDERER_PACKAGE_LOCK_SHA256: createHash("sha256")
        .update(await readFile(packageLock))
        .digest("hex")
    };
    git("config", "--local", "gc.auto", "0");
    expect(gate.inspectRepositoryProvenance(root, environment)).toMatchObject({
      commit,
      tree,
      sourceSnapshotSha256: expect.stringMatching(/^[0-9a-f]{64}$/)
    });
    git("config", "--local", "gc.auto", "1");
    expect(() => gate.inspectRepositoryProvenance(root, environment)).toThrow(
      /provenance inspection failed/
    );
    git("config", "--local", "gc.auto", "0");
    const filterMarker = path.join(root, "filter-must-not-run");
    git(
      "config",
      "--local",
      "filter.lcf-attack.clean",
      `/bin/sh -c 'touch ${filterMarker}; cat'`
    );
    const infoAttributes = path.join(root, ".git", "info", "attributes");
    await writeFile(infoAttributes, "* filter=lcf-attack\n");
    expect(() => gate.inspectRepositoryProvenance(root, environment)).toThrow(
      /provenance inspection failed/
    );
    await expect(readFile(filterMarker)).rejects.toThrow();
    git("config", "--local", "--unset-all", "filter.lcf-attack.clean");
    await writeFile(infoAttributes, "");

    const trackedPath = path.join(root, "tracked.txt");
    git("update-index", "--skip-worktree", "tracked.txt");
    await writeFile(trackedPath, "skip-worktree attack\n");
    expect(() => gate.inspectRepositoryProvenance(root, environment)).toThrow(
      /provenance inspection failed/
    );
    await writeFile(trackedPath, "reviewed\n");
    git("update-index", "--no-skip-worktree", "tracked.txt");

    git("update-index", "--assume-unchanged", "tracked.txt");
    await writeFile(trackedPath, "assume-unchanged attack\n");
    expect(() => gate.inspectRepositoryProvenance(root, environment)).toThrow(
      /provenance inspection failed/
    );
    await writeFile(trackedPath, "reviewed\n");
    git("update-index", "--no-assume-unchanged", "tracked.txt");

    const infoExclude = path.join(root, ".git", "info", "exclude");
    await writeFile(infoExclude, "hidden-by-local-exclude\n");
    expect(() => gate.inspectRepositoryProvenance(root, environment)).toThrow(
      /provenance inspection failed/
    );
    await writeFile(infoExclude, "# reviewed empty local exclude\n");

    const outside = await mkdtemp(
      path.join(canonicalTemporaryParent, "lcf-git-outside-")
    );
    temporaryDirectories.push(outside);
    const excludes = path.join(outside, "excludes");
    await writeFile(excludes, "ignored.txt\n");
    git("config", "--local", "core.excludesFile", excludes);
    git("config", "--local", "core.worktree", outside);

    expect(() => gate.inspectRepositoryProvenance(root, environment)).toThrow(
      /provenance inspection failed/
    );
  });

  it("rejects a non-Darwin production host before reading staging", async () => {
    const hook = gate.createBeforePackHook({
      platform: "linux",
      architecture: "x64"
    });
    await expect(
      hook({ electronPlatformName: "darwin" })
    ).rejects.toThrow(/only permits a Darwin packaging target and host/);

    const x64TargetHook = gate.createBeforePackHook({
      platform: "darwin",
      architecture: "arm64"
    });
    await expect(
      x64TargetHook({ electronPlatformName: "darwin", arch: 1 })
    ).rejects.toThrow(/only permits an arm64 packaging target/);
  });

  it("rejects payload tampering against the exact file inventory", async () => {
    const fixture = await createFixture();
    await appendFile(fixture.executablePath, "tampered\n");
    expect(() => auditFixture(fixture)).toThrow(/exact file inventory/);
  });

  it("rejects a stale normalized inventory digest", async () => {
    const fixture = await createFixture();
    await mutateManifest(fixture, (manifest) => {
      manifest.audit.normalizedInventorySha256 = "c".repeat(64);
    });
    expect(() => auditFixture(fixture)).toThrow(
      /normalized inventory digest does not match/
    );
  });

  it("rejects Python archive and installer provenance drift", async () => {
    const fixture = await createFixture();
    await mutateManifest(fixture, (manifest) => {
      manifest.build.python.archiveSha256 = "d".repeat(64);
      manifest.build.python.installerPackageSha256 = "e".repeat(64);
    });
    expect(() => auditFixture(fixture)).toThrow(
      /Python source provenance differs/
    );
  });

  it("independently rejects changed Python source bytes", async () => {
    const fixture = await createFixture();
    expect(() =>
      auditFixture(
        fixture,
        () => ["arm64"],
        () => ({
          archiveSize:
            fixture.toolchain.python.distribution.archiveSize,
          archiveSha256: "0".repeat(64),
          hashManifestSize:
            fixture.toolchain.python.distribution.hashManifestSize,
          hashManifestSha256:
            fixture.toolchain.python.distribution.hashManifestSha256
        })
      )
    ).toThrow(/source bytes differ from the reviewed lock/);
  });

  it("rejects product and protocol versions not sourced from runtime/version", async () => {
    const fixture = await createFixture();
    await mutateManifest(fixture, (manifest) => {
      manifest.product.appVersion = "99.0.0";
      manifest.product.desktopProtocol.major += 1;
    });
    expect(() => auditFixture(fixture)).toThrow(
      /versions are not canonical/
    );
  });

  it("rejects a critical input digest mismatch", async () => {
    const fixture = await createFixture();
    await mutateManifest(fixture, (manifest) => {
      const key = Object.keys(manifest.build.inputDigests)[0] as string;
      manifest.build.inputDigests[key] = "f".repeat(64);
    });
    expect(() => auditFixture(fixture)).toThrow(
      /critical input digests are stale or incomplete/
    );
  });

  it("rejects a manifest commit unlike the explicit source commit", async () => {
    const fixture = await createFixture();
    await mutateManifest(fixture, (manifest) => {
      manifest.build.repositoryCommit = "1".repeat(40);
    });
    expect(() => auditFixture(fixture)).toThrow(
      /commit differs from the explicit source commit/
    );
  });

  it("rejects manifest tree and source-snapshot provenance drift", async () => {
    const treeFixture = await createFixture();
    await mutateManifest(treeFixture, (manifest) => {
      manifest.build.repositoryTree = "1".repeat(40);
    });
    expect(() => auditFixture(treeFixture)).toThrow(
      /tree differs from the explicit source tree/
    );

    const snapshotFixture = await createFixture();
    expect(() =>
      auditFixture(
        snapshotFixture,
        () => ["arm64"],
        undefined,
        () => ({
          commit: snapshotFixture.environment.LCF_SOURCE_SHA as string,
          tree: snapshotFixture.environment.LCF_SOURCE_TREE as string,
          sourceDateEpoch: Number(
            snapshotFixture.environment.LCF_SOURCE_DATE_EPOCH
          ),
          sourceSnapshotSha256: "2".repeat(64)
        })
      )
    ).toThrow(/repository provenance differs from the checkout/);
  });

  it("independently rejects repository checkout provenance drift", async () => {
    const fixture = await createFixture();
    expect(() =>
      auditFixture(
        fixture,
        () => ["arm64"],
        undefined,
        () => ({
          commit: "9".repeat(40),
          tree: fixture.environment.LCF_SOURCE_TREE as string,
          sourceDateEpoch: Number(
            fixture.environment.LCF_SOURCE_DATE_EPOCH
          ),
          sourceSnapshotSha256: "c".repeat(64)
        })
      )
    ).toThrow(/repository provenance differs from the checkout/);
  });

  it("rejects stale or incomplete current runner inputs", async () => {
    const imageFixture = await createFixture();
    imageFixture.environment.ImageVersion = "20260731.2.0";
    expect(() => auditFixture(imageFixture)).toThrow(
      /runner image differs from the current runner input/
    );

    for (const input of [
      "LCF_SOURCE_SHA",
      "LCF_SOURCE_TREE",
      "LCF_PYTHON_DISTRIBUTION_ARCHIVE",
      "LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST",
      "LCF_PYTHON_INSTALL_ROOT"
    ]) {
      const missingFixture = await createFixture();
      delete missingFixture.environment[input];
      expect(() => auditFixture(missingFixture)).toThrow(
        /runner inputs are missing/
      );
    }
  });

  it("rejects unsafe reviewed Python framework broken symlinks", async () => {
    const fixture = await createFixture();
    fixture.toolchain.python.reviewedBrokenSymlinks[0].target = "../outside";
    await writeJson(
      path.join(
        fixture.root,
        "backend",
        "packaging",
        "python-sidecar-toolchain.lock.json"
      ),
      fixture.toolchain
    );

    expect(() => auditFixture(fixture)).toThrow(
      /reviewed broken symlink is unsafe/
    );
  });

  it("independently rejects an x86_64 Mach-O result", async () => {
    const fixture = await createFixture();
    expect(() => auditFixture(fixture, () => ["x86_64"])).toThrow(
      /independently inspect as arm64-only/
    );
  });

  it("requires the native manifest to cover every Mach-O magic file", async () => {
    const fixture = await createFixture();
    await writeFixtureFile(
      fixture.root,
      "desktop/generated/sidecar/extra.dylib",
      Buffer.concat([
        Buffer.from([0xcf, 0xfa, 0xed, 0xfe]),
        Buffer.from("second-mach-o\n")
      ])
    );
    await mutateManifest(fixture, (manifest) => {
      manifest.files = gate.buildFileInventory(fixture.stagingRoot);
      manifest.audit.normalizedInventorySha256 =
        gate.normalizedInventorySha256(manifest.files, manifest.native);
    });
    expect(() => auditFixture(fixture)).toThrow(/Mach-O magic coverage/);
  });

  it("rejects incomplete component, artifact, and frozen-smoke evidence", async () => {
    const componentFixture = await createFixture();
    await mutateManifest(componentFixture, (manifest) => {
      manifest.components = manifest.components.filter(
        (component: JsonObject) => component.name !== "dulwich"
      );
    });
    expect(() => auditFixture(componentFixture)).toThrow(
      /component inventory is missing/
    );

    const artifactFixture = await createFixture();
    await mutateManifest(artifactFixture, (manifest) => {
      manifest.artifacts.spdxSbom = "missing.spdx.json";
    });
    expect(() => auditFixture(artifactFixture)).toThrow(
      /SBOM artifact is missing/
    );

    const smokeFixture = await createFixture();
    await mutateManifest(smokeFixture, (manifest) => {
      manifest.audit.frozenSmoke.pathTrap = false;
    });
    expect(() => auditFixture(smokeFixture)).toThrow(
      /passing frozen smoke evidence/
    );

    const domainSmokeFixture = await createFixture();
    await mutateManifest(domainSmokeFixture, (manifest) => {
      manifest.audit.frozenSmoke.checks.pop();
    });
    expect(() => auditFixture(domainSmokeFixture)).toThrow(
      /passing frozen smoke evidence/
    );
  });

  it("binds Python toolchain summary, source locks, and canonical artifact inventory", async () => {
    const versionFixture = await createFixture();
    await mutateManifest(versionFixture, (manifest) => {
      manifest.build.pythonToolchain.buildTools.uvVersion = "0.0.0";
    });
    expect(() => auditFixture(versionFixture)).toThrow(
      /build tool versions differ from reviewed pins/
    );

    const artifactFixture = await createFixture();
    const artifactPath = path.join(
      artifactFixture.stagingRoot,
      "python-build-toolchain.json"
    );
    const artifact = await readJson(artifactPath);
    artifact.runtimeRequirementsSha256 = "f".repeat(64);
    await writeJson(artifactPath, artifact);
    await mutateManifest(artifactFixture, (manifest) => {
      manifest.files = gate.buildFileInventory(artifactFixture.stagingRoot);
      manifest.audit.normalizedInventorySha256 =
        gate.normalizedInventorySha256(manifest.files, manifest.native);
    });
    expect(() => auditFixture(artifactFixture)).toThrow(
      /toolchain artifact differs from the manifest/
    );

    const inventoryFixture = await createFixture();
    const inventoryArtifactPath = path.join(
      inventoryFixture.stagingRoot,
      "python-build-toolchain.json"
    );
    const inventoryArtifact = await readJson(inventoryArtifactPath);
    inventoryArtifact.files[0].mode = "0755";
    inventoryArtifact.installedTreeContentSha256 = createHash("sha256")
      .update(
        Buffer.from(
          gate.canonicalJson({
            schemaVersion: 1,
            entries: inventoryArtifact.files
          }),
          "utf8"
        )
      )
      .digest("hex");
    await writeJson(inventoryArtifactPath, inventoryArtifact);
    await mutateManifest(inventoryFixture, (manifest) => {
      manifest.build.pythonToolchain.installedTreeContentSha256 =
        inventoryArtifact.installedTreeContentSha256;
      manifest.files = gate.buildFileInventory(inventoryFixture.stagingRoot);
      manifest.audit.normalizedInventorySha256 =
        gate.normalizedInventorySha256(manifest.files, manifest.native);
    });
    expect(() => auditFixture(inventoryFixture)).toThrow(
      /toolchain entry is malformed/
    );

    const sourceLockFixture = await createFixture();
    const sourceLockArtifactPath = path.join(
      sourceLockFixture.stagingRoot,
      "python-build-toolchain.json"
    );
    const sourceLockArtifact = await readJson(sourceLockArtifactPath);
    sourceLockArtifact.buildRequirementsLockSha256 = "f".repeat(64);
    await writeJson(sourceLockArtifactPath, sourceLockArtifact);
    await mutateManifest(sourceLockFixture, (manifest) => {
      manifest.build.pythonToolchain.buildRequirementsLockSha256 =
        sourceLockArtifact.buildRequirementsLockSha256;
      manifest.files = gate.buildFileInventory(sourceLockFixture.stagingRoot);
      manifest.audit.normalizedInventorySha256 =
        gate.normalizedInventorySha256(manifest.files, manifest.native);
    });
    expect(() => auditFixture(sourceLockFixture)).toThrow(
      /toolchain differs from reviewed source locks/
    );
  });

  it("rejects a changed schema even when its input digest is refreshed", async () => {
    const fixture = await createFixture();
    const schemaPath = path.join(
      fixture.root,
      "runtime",
      "python-sidecar-build-manifest.schema.json"
    );
    const schema = await readJson(schemaPath);
    schema.$id = "unreviewed.schema.json";
    await writeJson(schemaPath, schema);
    await mutateManifest(fixture, (manifest) => {
      manifest.build.inputDigests =
        gate.criticalInputDigests(fixture.root);
    });
    expect(() => auditFixture(fixture)).toThrow(
      /schema is not the reviewed contract/
    );

    const smokeFixture = await createFixture();
    const smokeSchemaPath = path.join(
      smokeFixture.root,
      "runtime",
      "python-sidecar-build-manifest.schema.json"
    );
    const smokeSchema = await readJson(smokeSchemaPath);
    smokeSchema.properties.audit.properties.frozenSmoke.properties.checks.const.pop();
    await writeJson(smokeSchemaPath, smokeSchema);
    await mutateManifest(smokeFixture, (manifest) => {
      manifest.build.inputDigests =
        gate.criticalInputDigests(smokeFixture.root);
    });
    expect(() => auditFixture(smokeFixture)).toThrow(
      /toolchain lock and manifest schema disagree/
    );
  });

  it("rejects a sidecar symlink escaping staging", async () => {
    const fixture = await createFixture();
    await symlink(
      "../../../runtime/version.json",
      path.join(fixture.stagingRoot, "escape")
    );
    expect(() => auditFixture(fixture)).toThrow(/symlink escapes the bundle/);
  });
});

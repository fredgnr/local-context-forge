import {
  appendFile,
  chmod,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
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
) => { commit: string; sourceDateEpoch: number };

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
  }): { files: number; nativeFiles: number; components: number };
  buildFileInventory(root: string): JsonObject[];
  createBeforePackHook(dependencies: {
    platform: string;
    architecture?: string;
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
  await writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`);
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
    GITHUB_SHA: "a".repeat(40),
    LCF_SOURCE_DATE_EPOCH: "1700000000",
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
      repositoryCommit: environment.GITHUB_SHA,
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
      inputDigests: gate.criticalInputDigests(root)
    },
    components,
    artifacts: {
      spdxSbom: "sbom.spdx.json",
      thirdPartyNotices: "THIRD-PARTY-NOTICES.txt",
      licensesDirectory: "licenses"
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
    commit: fixture.environment.GITHUB_SHA as string,
    sourceDateEpoch: Number(
      fixture.environment.LCF_SOURCE_DATE_EPOCH
    )
  })
): { files: number; nativeFiles: number; components: number } {
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

  it("rejects a manifest commit unlike the current GITHUB_SHA", async () => {
    const fixture = await createFixture();
    await mutateManifest(fixture, (manifest) => {
      manifest.build.repositoryCommit = "1".repeat(40);
    });
    expect(() => auditFixture(fixture)).toThrow(
      /commit differs from the current GITHUB_SHA/
    );
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
          sourceDateEpoch: Number(
            fixture.environment.LCF_SOURCE_DATE_EPOCH
          )
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

    const missingFixture = await createFixture();
    delete missingFixture.environment.LCF_PYTHON_DISTRIBUTION_ARCHIVE;
    expect(() => auditFixture(missingFixture)).toThrow(
      /runner inputs are missing/
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

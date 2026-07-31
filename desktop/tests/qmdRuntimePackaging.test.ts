import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
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

const audit = require("../scripts/auditQmdRuntime.cjs") as {
  EXPECTED_NATIVE_SMOKE: JsonObject;
  QmdRuntimeAuditError: new (message: string) => Error;
  auditQmdRuntime(options: {
    repositoryRoot: string;
    stagingRoot: string;
    environment: NodeJS.ProcessEnv;
    platform: string;
    architecture: string;
    inspectNative: (filePath: string) => JsonObject;
    inspectSource: () => JsonObject;
    inspectRepository: () => JsonObject;
    inspectBuildPython: () => JsonObject;
  }): { files: number; nativeFiles: number; components: number };
  buildFileInventory(root: string): JsonObject[];
  buildNativeInventory(
    root: string,
    inspectNative: (filePath: string) => JsonObject
  ): JsonObject[];
  canonicalJson(value: unknown): string;
  criticalInputDigests(
    repositoryRoot: string,
    lock: JsonObject
  ): Record<string, string>;
  sha256Bytes(value: Buffer): string;
  validateToolchain(lock: JsonObject): void;
};

const build = require("../scripts/buildQmdRuntime.cjs") as {
  QmdRuntimeBuildError: new (message: string) => Error;
  verifyHashManifest(
    hashManifestPath: string,
    lock: JsonObject
  ): void;
};

const repositoryRoot = path.resolve(__dirname, "..", "..");
const temporaryDirectories: string[] = [];

async function readJson(filePath: string): Promise<JsonObject> {
  return JSON.parse(await readFile(filePath, "utf8")) as JsonObject;
}

function sha256(value: Buffer | string): string {
  return createHash("sha256").update(value).digest("hex");
}

async function writePayload(
  root: string,
  relative: string,
  value: Buffer | string,
  mode = 0o644
): Promise<void> {
  const destination = path.join(root, ...relative.split("/"));
  await mkdir(path.dirname(destination), { recursive: true });
  await writeFile(destination, value, { mode });
}

const nativeInspector = (): JsonObject => ({
  architectures: ["arm64"],
  dependencies: [],
  rpaths: [],
  codeSignature: "valid"
});

interface Fixture {
  stagingRoot: string;
  manifestPath: string;
  environment: NodeJS.ProcessEnv;
  inspectSource: () => JsonObject;
  inspectRepository: () => JsonObject;
  inspectBuildPython: () => JsonObject;
}

async function createFixture(): Promise<Fixture> {
  const root = await mkdtemp(path.join(os.tmpdir(), "lcf-qmd-audit-"));
  temporaryDirectories.push(root);
  const stagingRoot = path.join(root, "qmd");
  const lock = await readJson(
    path.join(
      repositoryRoot,
      "runtime",
      "qmd-runtime-toolchain.lock.json"
    )
  );
  const versions = await readJson(
    path.join(repositoryRoot, "runtime", "version.json")
  );
  const macho = Buffer.from("cffaedfe01020304", "hex");
  await writePayload(stagingRoot, "node/bin/node", macho, 0o755);
  await writePayload(stagingRoot, "node/LICENSE", "Node license\n");
  await writePayload(
    stagingRoot,
    "worker/index.mjs",
    "export const worker = true;\n"
  );
  await writePayload(
    stagingRoot,
    "worker/node_modules/better-sqlite3/build/Release/better_sqlite3.node",
    macho,
    0o755
  );
  await writePayload(
    stagingRoot,
    "compliance/THIRD-PARTY-NOTICES.txt",
    "reviewed notices\n"
  );
  await writePayload(
    stagingRoot,
    "compliance/licenses/node-LICENSE.txt",
    "Node license\n"
  );
  const components = [
    { name: "node", version: "22.23.2", license: "MIT" },
    { name: "@tobilu/qmd", version: "2.5.3", license: "MIT" },
    { name: "better-sqlite3", version: "12.10.0", license: "MIT" }
  ];
  await writePayload(
    stagingRoot,
    "compliance/sbom.spdx.json",
    `${JSON.stringify({
      spdxVersion: "SPDX-2.3",
      dataLicense: "CC0-1.0",
      packages: components.map((component) => ({
        name: component.name
      }))
    })}\n`
  );

  const files = audit.buildFileInventory(stagingRoot);
  const native = audit.buildNativeInventory(
    stagingRoot,
    nativeInspector
  );
  const commit = "a".repeat(40);
  const sourceDateEpoch = 1_700_000_000;
  const manifest: JsonObject = {
    $schema: "qmd-runtime-build-manifest.schema.json",
    schemaVersion: 1,
    kind: "local-context-forge-qmd-runtime",
    product: {
      appVersion: versions.productVersion,
      desktopProtocol: versions.desktopProtocol,
      databaseSchema: versions.databaseSchema
    },
    target: { os: "darwin", architecture: "arm64" },
    build: {
      repositoryCommit: commit,
      sourceDateEpoch,
      runnerImage: "macos-15",
      runnerImageVersion: "20260729.1.0",
      macosDeploymentTarget: "14.0",
      node: {
        version: lock.node.version,
        archiveName: lock.node.archiveName,
        archiveSource: lock.node.archiveSource,
        archiveSha256: lock.node.archiveSha256,
        hashManifestName: lock.node.hashManifestName,
        hashManifestSource: lock.node.hashManifestSource,
        hashManifestSha256: lock.node.hashManifestSha256
      },
      python: {
        provider: lock.buildPython.provider,
        implementation: lock.buildPython.implementation,
        version: lock.buildPython.version,
        executableSha256: "b".repeat(64)
      },
      inputDigests: audit.criticalInputDigests(repositoryRoot, lock)
    },
    components,
    artifacts: {
      spdxSbom: "compliance/sbom.spdx.json",
      thirdPartyNotices: "compliance/THIRD-PARTY-NOTICES.txt",
      licensesDirectory: "compliance/licenses"
    },
    files,
    native,
    audit: {
      status: "pass",
      policyVersion: 1,
      normalizedInventorySha256: audit.sha256Bytes(
        Buffer.from(audit.canonicalJson({ files, native }), "utf8")
      ),
      nativeSmoke: audit.EXPECTED_NATIVE_SMOKE
    }
  };
  const manifestPath = path.join(stagingRoot, "runtime-manifest.json");
  const encoded = `${audit.canonicalJson(manifest)}\n`;
  await writeFile(manifestPath, encoded);
  await writeFile(
    path.join(stagingRoot, "runtime-manifest.sha256"),
    `${sha256(encoded)}\n`
  );
  const environment = {
    GITHUB_SHA: commit,
    LCF_SOURCE_DATE_EPOCH: String(sourceDateEpoch),
    ImageVersion: "20260729.1.0",
    LCF_QMD_NODE_ARCHIVE: "/tmp/reviewed-node.tar.gz",
    LCF_QMD_NODE_HASH_MANIFEST: "/tmp/reviewed-SHASUMS256.txt",
    LCF_QMD_BUILD_PYTHON: "/tmp/reviewed-python"
  };
  return {
    stagingRoot,
    manifestPath,
    environment,
    inspectSource: () => ({
      archiveSize: lock.node.archiveSize,
      archiveSha256: lock.node.archiveSha256,
      hashManifestSize: lock.node.hashManifestSize,
      hashManifestSha256: lock.node.hashManifestSha256
    }),
    inspectRepository: () => ({ commit, sourceDateEpoch }),
    inspectBuildPython: () => ({
      provider: lock.buildPython.provider,
      implementation: lock.buildPython.implementation,
      version: lock.buildPython.version,
      executableSha256: "b".repeat(64)
    })
  };
}

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) =>
      rm(directory, { recursive: true, force: true })
    )
  );
});

describe("QMD runtime provenance", () => {
  it("synchronizes the process trap into builtin ESM named exports", () => {
    const trap = path.join(
      repositoryRoot,
      "desktop",
      "scripts",
      "qmdNetworkTrap.mjs"
    );
    const result = spawnSync(
      process.execPath,
      [
        "--import",
        trap,
        "--input-type=module",
        "-e",
        [
          "import { spawnSync as trappedSpawn } from 'node:child_process';",
          "let trapped=false;",
          "try { trappedSpawn('/usr/bin/true'); }",
          "catch (error) { trapped=/rejected/.test(String(error.message)); }",
          "if (!trapped) process.exit(7);"
        ].join("")
      ],
      {
        encoding: "utf8",
        env: {
          PATH: process.env.PATH ?? "/usr/bin:/bin",
          LANG: "C",
          LC_ALL: "C",
          LCF_QMD_NATIVE_SMOKE: "1"
        }
      }
    );

    expect(result.status, result.stderr).toBe(0);
  });

  it("accepts the reviewed Node/QMD toolchain lock", async () => {
    const lock = await readJson(
      path.join(
        repositoryRoot,
        "runtime",
        "qmd-runtime-toolchain.lock.json"
      )
    );

    expect(() => audit.validateToolchain(lock)).not.toThrow();
  });

  it("requires the independently pinned Node hash manifest", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lcf-node-hashes-"));
    temporaryDirectories.push(root);
    const archiveName = "node-v22.23.2-darwin-arm64.tar.gz";
    const archiveSha256 = "1".repeat(64);
    const contents = `${archiveSha256}  ${archiveName}\n`;
    const hashManifest = path.join(root, "SHASUMS256.txt");
    await writeFile(hashManifest, contents, "ascii");
    const lock = {
      node: {
        archiveName,
        archiveSha256,
        hashManifestSize: Buffer.byteLength(contents),
        hashManifestSha256: sha256(contents)
      }
    };

    expect(() =>
      build.verifyHashManifest(hashManifest, lock)
    ).not.toThrow();
    await appendFile(hashManifest, "tamper\n");
    expect(() => build.verifyHashManifest(hashManifest, lock)).toThrow(
      /differs from the reviewed lock/
    );
  });

  it("accepts safe official subpaths but rejects traversal entries", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lcf-node-hashes-"));
    temporaryDirectories.push(root);
    const archiveName = "node-v22.23.2-darwin-arm64.tar.gz";
    const archiveSha256 = "3".repeat(64);
    const accepted =
      `${archiveSha256}  ${archiveName}\n` +
      `${"4".repeat(64)}  win-arm64/node.exe\n`;
    const hashManifest = path.join(root, "SHASUMS256.txt");
    await writeFile(hashManifest, accepted, "ascii");
    const lock = {
      node: {
        archiveName,
        archiveSha256,
        hashManifestSize: Buffer.byteLength(accepted),
        hashManifestSha256: sha256(accepted)
      }
    };
    expect(() =>
      build.verifyHashManifest(hashManifest, lock)
    ).not.toThrow();

    const unsafe =
      `${archiveSha256}  ${archiveName}\n` +
      `${"4".repeat(64)}  win-arm64/../escape\n`;
    await writeFile(hashManifest, unsafe, "ascii");
    lock.node.hashManifestSize = Buffer.byteLength(unsafe);
    lock.node.hashManifestSha256 = sha256(unsafe);
    expect(() =>
      build.verifyHashManifest(hashManifest, lock)
    ).toThrow(/unsafe duplicate/);
  });

  it("rejects an exact-hash manifest with an ambiguous target", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lcf-node-hashes-"));
    temporaryDirectories.push(root);
    const archiveName = "node-v22.23.2-darwin-arm64.tar.gz";
    const archiveSha256 = "2".repeat(64);
    const contents =
      `${archiveSha256}  ${archiveName}\n` +
      `${archiveSha256}  ${archiveName}\n`;
    const hashManifest = path.join(root, "SHASUMS256.txt");
    await writeFile(hashManifest, contents, "ascii");
    const lock = {
      node: {
        archiveName,
        archiveSha256,
        hashManifestSize: Buffer.byteLength(contents),
        hashManifestSha256: sha256(contents)
      }
    };

    expect(() => build.verifyHashManifest(hashManifest, lock)).toThrow(
      /unsafe duplicate/
    );
  });
});

describe("QMD staged runtime audit", () => {
  it("accepts an exact arm64 payload with canonical manifest evidence", async () => {
    const fixture = await createFixture();

    expect(
      audit.auditQmdRuntime({
        repositoryRoot,
        stagingRoot: fixture.stagingRoot,
        environment: fixture.environment,
        platform: "darwin",
        architecture: "arm64",
        inspectNative: nativeInspector,
        inspectSource: fixture.inspectSource,
        inspectRepository: fixture.inspectRepository,
        inspectBuildPython: fixture.inspectBuildPython
      })
    ).toEqual({ files: 7, nativeFiles: 2, components: 3 });
  });

  it("rejects payload tampering after the native smoke", async () => {
    const fixture = await createFixture();
    await appendFile(
      path.join(fixture.stagingRoot, "worker", "index.mjs"),
      "// tamper\n"
    );

    expect(() =>
      audit.auditQmdRuntime({
        repositoryRoot,
        stagingRoot: fixture.stagingRoot,
        environment: fixture.environment,
        platform: "darwin",
        architecture: "arm64",
        inspectNative: nativeInspector,
        inspectSource: fixture.inspectSource,
        inspectRepository: fixture.inspectRepository,
        inspectBuildPython: fixture.inspectBuildPython
      })
    ).toThrow(/exact file inventory/);
  });

  it("rejects symlinked payloads even when they remain inside staging", async () => {
    const fixture = await createFixture();
    await symlink(
      "index.mjs",
      path.join(fixture.stagingRoot, "worker", "linked.mjs")
    );

    expect(() =>
      audit.auditQmdRuntime({
        repositoryRoot,
        stagingRoot: fixture.stagingRoot,
        environment: fixture.environment,
        platform: "darwin",
        architecture: "arm64",
        inspectNative: nativeInspector,
        inspectSource: fixture.inspectSource,
        inspectRepository: fixture.inspectRepository,
        inspectBuildPython: fixture.inspectBuildPython
      })
    ).toThrow(/must not contain symlinks/);
  });

  it("rejects non-canonical manifest bytes", async () => {
    const fixture = await createFixture();
    const manifest = JSON.parse(
      await readFile(fixture.manifestPath, "utf8")
    );
    const nonCanonical = `${JSON.stringify(manifest, null, 2)}\n`;
    await writeFile(fixture.manifestPath, nonCanonical);
    await writeFile(
      path.join(fixture.stagingRoot, "runtime-manifest.sha256"),
      `${sha256(nonCanonical)}\n`
    );

    expect(() =>
      audit.auditQmdRuntime({
        repositoryRoot,
        stagingRoot: fixture.stagingRoot,
        environment: fixture.environment,
        platform: "darwin",
        architecture: "arm64",
        inspectNative: nativeInspector,
        inspectSource: fixture.inspectSource,
        inspectRepository: fixture.inspectRepository,
        inspectBuildPython: fixture.inspectBuildPython
      })
    ).toThrow(/not canonical JSON/);
  });
});

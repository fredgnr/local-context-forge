import {
  chmod,
  link,
  readFile,
  mkdtemp,
  mkdir,
  realpath,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import { renameSync, rmSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { isUpdateStatus } from "../src/contracts";
import {
  COMPILED_DISTRIBUTION_PROFILE,
  resolveDistributionProfile
} from "../src/main/distribution";
import {
  UpdateClient,
  UpdateClientError,
  type UpdateFetchBytes,
  type UpdateStreamAsset
} from "../src/main/updateClient";

type JsonObject = Record<string, any>;

const common = require("../scripts/packagingAuditCommon.cjs") as {
  buildInventory(root: string): JsonObject[];
  normalizedInventorySha256(records: JsonObject[]): string;
  validateEngineeringSmokeManifest(
    manifest: JsonObject,
    schema: JsonObject
  ): JsonObject;
};
const prepare = require("../scripts/prepareEngineeringSmoke.cjs") as {
  copyAttestedEntrypointOutputs(
    sourceRoot: string,
    destinationRoot: string,
    expectedOutputs: JsonObject,
    dependencies?: {
      afterSourceOpen?: (context: JsonObject) => void;
      afterReadChunk?: (context: JsonObject) => void;
    }
  ): JsonObject;
  assertNoProductionEnvironment(environment: NodeJS.ProcessEnv): void;
  assertEngineeringSmokeMode(environment: NodeJS.ProcessEnv): void;
  createDistributionManifest(input: JsonObject): JsonObject;
  inspectRepositorySourceSnapshot(
    repositoryRoot: string,
    environment: NodeJS.ProcessEnv
  ): JsonObject;
  loadReviewedDesktopPackageMetadata(
    source: JsonObject,
    repositoryRoot: string
  ): JsonObject;
  preflightEngineeringSmoke(options: JsonObject): JsonObject;
  publishPreparedEngineeringSmoke(
    options: {
      temporaryApp: string;
      temporaryManifest: string;
      appDestination: string;
      manifestDestination: string;
      auditPublished: () => void;
    },
    dependencies?: {
      rename?: (source: string, destination: string) => void;
    }
  ): void;
  requireSafeGeneratedRoot(generatedRoot: string, desktopRoot: string): void;
  selectedSourceCommit(environment: NodeJS.ProcessEnv): string;
  selectedSourceTree(environment: NodeJS.ProcessEnv): string;
  validateHost(platform: string, architecture: string): void;
};
const entrypointBuilder = require(
  "../scripts/buildEngineeringSmokeEntrypoints.cjs"
) as {
  buildEntrypointsFromSnapshot(options: {
    snapshot: JsonObject;
    repositoryRoot: string;
    buildRoot: string;
    environment: NodeJS.ProcessEnv;
    esbuildImplementation: typeof import("esbuild");
    installSummary: JsonObject;
    afterInputsCaptured?: () => Promise<void>;
  }): Promise<JsonObject>;
  selectReviewedInputs(
    snapshot: JsonObject,
    repositoryRoot: string
  ): { byPath: Map<string, JsonObject>; bytesByPath: Map<string, Buffer> };
};
const exactNodeInstall = require("../../tools/exact_node_install.cjs") as {
  installExactNodeDependencies(options: JsonObject): JsonObject;
  inventoryNodeInstall(nodeModulesRoot: string): JsonObject;
  verifyNodeInstallSeal(options: JsonObject): JsonObject;
};
const beforePack = require("../scripts/beforePackEngineeringSmoke.cjs") as {
  assertContext(context: unknown): void;
};
const afterPack = require("../scripts/afterPackEngineeringSmoke.cjs") as {
  SECURE_FUSES: JsonObject;
  createAfterPackEngineeringSmoke(dependencies: {
    flipFuses(executable: string, config: JsonObject): Promise<number>;
    environment?: NodeJS.ProcessEnv;
    platform?: string;
    architecture?: string;
  }): (context: JsonObject) => Promise<JsonObject>;
};
const bundleAudit = require(
  "../scripts/auditEngineeringSmokeBundle.cjs"
) as {
  ALLOWED_ELECTRON_HELPER_APPS: readonly string[];
  REVIEWED_PYINSTALLER_ARCHIVE: string;
  assertNoInstallOrReleaseArtifacts(
    outputRoot: string,
    expectedAppRoot: string
  ): void;
  inspectSecureFuses(
    executable: string,
    reader: (executable: string) => Promise<JsonObject>
  ): Promise<JsonObject>;
  inspectAsarContents(
    asarPath: string,
    manifest: JsonObject
  ): JsonObject;
  validateAsarIntegrity(info: JsonObject, expected: string): JsonObject;
  validateInfoPlist(info: JsonObject, expectedVersion: string): JsonObject;
};
const asar = require("@electron/asar") as {
  createPackage(source: string, destination: string): Promise<void>;
};
const fuses = require("@electron/fuses") as {
  FuseState: JsonObject;
  FuseV1Options: JsonObject;
  FuseVersion: JsonObject;
};

const repositoryRoot = path.resolve(__dirname, "..", "..");
const temporaryRoots: string[] = [];

async function temporaryRoot(prefix: string): Promise<string> {
  const canonicalParent = await realpath(os.tmpdir());
  const root = await mkdtemp(path.join(canonicalParent, prefix));
  try {
    if (
      !path.isAbsolute(root) ||
      path.resolve(root) !== root ||
      (await realpath(root)) !== root
    ) {
      throw new Error("Engineering-smoke test root is not canonical");
    }
  } catch (error) {
    await rm(root, { recursive: true, force: true });
    throw error;
  }
  temporaryRoots.push(root);
  return root;
}

async function exactNodeInstallFixture(prefix: string): Promise<{
  workspace: string;
  repository: string;
  environment: NodeJS.ProcessEnv;
  npmExecutable: string;
  npmMarker: string;
  sealPath: string;
  runtimeContract: JsonObject;
}> {
  const workspace = await temporaryRoot(prefix);
  const repository = path.join(workspace, "repository");
  await mkdir(path.join(repository, "desktop"), { recursive: true });
  await mkdir(path.join(repository, "web"), { recursive: true });
  await writeFile(
    path.join(repository, ".gitignore"),
    "desktop/node_modules/\nweb/node_modules/\n"
  );
  for (const packageName of ["desktop", "web"]) {
    await writeFile(
      path.join(repository, packageName, "package.json"),
      `${JSON.stringify({ name: `${packageName}-fixture`, version: "1.0.0" })}\n`
    );
    await writeFile(
      path.join(repository, packageName, "package-lock.json"),
      `${JSON.stringify({
        name: `${packageName}-fixture`,
        version: "1.0.0",
        lockfileVersion: 3,
        requires: true,
        packages: {
          "": { name: `${packageName}-fixture`, version: "1.0.0" }
        }
      })}\n`
    );
  }
  const gitEnvironment = {
    PATH: "/usr/bin:/bin",
    LANG: "C",
    LC_ALL: "C",
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_CONFIG_GLOBAL: "/dev/null",
    GIT_TERMINAL_PROMPT: "0"
  };
  const git = (...arguments_: string[]): string =>
    execFileSync("/usr/bin/git", ["-C", repository, ...arguments_], {
      encoding: "utf8",
      env: gitEnvironment
    }).trim();
  git("init", "--quiet");
  git("add", "--all");
  git(
    "-c",
    "user.name=LCF Test",
    "-c",
    "user.email=lcf-test@example.invalid",
    "commit",
    "--quiet",
    "-m",
    "exact node fixture"
  );
  await chmod(repository, 0o700);
  const commit = git("rev-parse", "HEAD");
  const tree = git("rev-parse", "HEAD^{tree}");
  const sourceDateEpoch = git("show", "-s", "--format=%ct", "HEAD");
  const inventory = git("ls-tree", "-r", "--full-tree", "HEAD")
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      const match = /^(\d+) (\w+) ([0-9a-f]{40})\t(.+)$/.exec(line);
      if (!match) {
        throw new Error("invalid exact Node fixture inventory");
      }
      return {
        mode: match[1],
        objectId: match[3],
        path: match[4]!,
        type: match[2]
      };
    })
    .sort((left, right) =>
      left.path < right.path ? -1 : left.path > right.path ? 1 : 0
    );
  const webLock = await readFile(
    path.join(repository, "web", "package-lock.json")
  );
  const environment = {
    LCF_SOURCE_SHA: commit,
    LCF_SOURCE_TREE: tree,
    LCF_SOURCE_DATE_EPOCH: sourceDateEpoch,
    LCF_SOURCE_SNAPSHOT_SHA256: createHash("sha256")
      .update(Buffer.from(JSON.stringify(inventory), "utf8"))
      .digest("hex"),
    LCF_RENDERER_PACKAGE_LOCK_SHA256: createHash("sha256")
      .update(webLock)
      .digest("hex")
  };
  const npmMarker = path.join(workspace, "npm-ci-ran");
  const npmExecutable = path.join(workspace, "reviewed-npm.sh");
  await writeFile(
    npmExecutable,
    [
      "#!/bin/sh",
      "set -eu",
      "if [ \"${1:-}\" = \"--version\" ]; then",
      "  printf '10.9.8\\n'",
      "  exit 0",
      "fi",
      "test \"${1:-}\" = \"ci\"",
      `printf ran > ${JSON.stringify(npmMarker)}`,
      "mkdir -p node_modules/reviewed-tool node_modules/.bin",
      "printf '{\"name\":\"reviewed-tool\",\"version\":\"1.0.0\"}\\n' > node_modules/reviewed-tool/package.json",
      "printf 'module.exports = 1;\\n' > node_modules/reviewed-tool/index.js",
      "printf '#!/bin/sh\\nexit 0\\n' > node_modules/reviewed-tool/cli.js",
      "ln -s ../reviewed-tool/cli.js node_modules/.bin/reviewed-tool",
      ""
    ].join("\n")
  );
  await chmod(npmExecutable, 0o755);
  return {
    workspace,
    repository,
    environment,
    npmExecutable,
    npmMarker,
    sealPath: path.join(workspace, "node-install-seal.json"),
    runtimeContract: {
      nodeVersion: process.version,
      npmVersion: "10.9.8",
      allowExternalNpmForTest: true
    }
  };
}

async function loadSchema(): Promise<JsonObject> {
  return JSON.parse(
    await readFile(
      path.join(
        repositoryRoot,
        "runtime",
        "engineering-smoke-manifest.schema.json"
      ),
      "utf8"
    )
  ) as JsonObject;
}

function distributionManifest(): JsonObject {
  return prepare.createDistributionManifest({
    source: {
      commit: "a".repeat(40),
      tree: "b".repeat(40),
      sourceSnapshotSha256: "c".repeat(64),
      desktopPackageSha256: "7".repeat(64),
      sourceDateEpoch: 1_800_000_000
    },
    version: "0.3.0-alpha.1",
    desktopApp: {
      asarPath: "Contents/Resources/app.asar",
      mainPath: "dist/main/index.js",
      mainSha256: "1".repeat(64),
      mainBytes: 100,
      preloadPath: "dist/preload/index.cjs",
      preloadSha256: "2".repeat(64),
      preloadBytes: 80,
      packagePath: "package.json",
      packageSha256: "3".repeat(64),
      packageBytes: 60,
      reviewedPackagePath: "desktop/package.json",
      reviewedPackageSha256: "7".repeat(64),
      entrypointBuild: {
        builder: "esbuild",
        builderVersion: "0.28.1",
        nodeVersion: "v22.23.2",
        npmVersion: "10.9.8",
        packageLockSha256: "6".repeat(64),
        installedContentSha256: "5".repeat(64),
        inputs: 35,
        inputsSha256: "9".repeat(64)
      }
    },
    renderer: {
      files: 4,
      bytes: 4096,
      repositoryCommit: "a".repeat(40),
      repositoryTree: "b".repeat(40),
      sourceSnapshotSha256: "c".repeat(64),
      inputSnapshotSha256: "8".repeat(64)
    },
    rendererManifestSha256: "c".repeat(64),
    python: { files: 80, nativeFiles: 12, components: 19 },
    pythonManifest: {
      build: {
        repositoryCommit: "a".repeat(40),
        repositoryTree: "b".repeat(40),
        sourceSnapshotSha256: "c".repeat(64),
        pythonToolchain: {
          buildRequirementsLockSha256: "1".repeat(64),
          runtimeLockSha256: "2".repeat(64),
          runtimeRequirementsSha256: "3".repeat(64),
          installedTreeContentSha256: "4".repeat(64),
          buildTools: {
            altgraphVersion: "0.17.4",
            macholibVersion: "1.16.3",
            packagingVersion: "26.2",
            pyinstallerVersion: "6.21.0",
            pyinstallerHooksContribVersion: "2026.6",
            setuptoolsVersion: "83.0.0",
            uvVersion: "0.11.29"
          }
        }
      },
      artifacts: {
        pythonBuildToolchain: "python-build-toolchain.json"
      },
      audit: { normalizedInventorySha256: "d".repeat(64) }
    },
    pythonManifestSha256: "e".repeat(64)
  });
}

afterEach(async () => {
  await Promise.all(
    temporaryRoots
      .splice(0)
      .map((root) => rm(root, { recursive: true, force: true }))
  );
  vi.restoreAllMocks();
});

describe("engineering-smoke exact entrypoint build", () => {
  it("selects reviewed Git object bytes before the exact entrypoint build", async () => {
    const workspace = await temporaryRoot("lcf-entrypoint-git-");
    const root = path.join(workspace, "repository");
    const sourceRoot = path.join(root, "desktop", "src");
    const mainPath = path.join(sourceRoot, "main", "index.ts");
    await mkdir(path.dirname(mainPath), { recursive: true });
    await mkdir(path.join(sourceRoot, "preload"), { recursive: true });
    const reviewedMain = Buffer.from(
      'export const provenanceMarker = "reviewed-marker";\nconsole.log(provenanceMarker);\n',
      "utf8"
    );
    await writeFile(mainPath, reviewedMain);
    await writeFile(
      path.join(sourceRoot, "preload", "index.ts"),
      'import { provenanceMarker } from "../main/index";\nconsole.log(provenanceMarker);\n'
    );
    await writeFile(
      path.join(root, "desktop", "tsconfig.json"),
      '{"compilerOptions":{"target":"ES2022"}}\n'
    );
    const desktopPackagePath = path.join(root, "desktop", "package.json");
    const reviewedDesktopPackage =
      '{"name":"desktop-fixture","version":"0.0.0"}\n';
    await writeFile(
      desktopPackagePath,
      reviewedDesktopPackage
    );
    await mkdir(path.join(root, "web"), { recursive: true });
    const rendererPackageLockPath = path.join(root, "web", "package-lock.json");
    await writeFile(rendererPackageLockPath, '{"lockfileVersion":3}\n');
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
          path: match[4]!,
          type: match[2]
        };
      })
      .sort((left, right) =>
        left.path < right.path ? -1 : left.path > right.path ? 1 : 0
      );
    const environment = {
      LCF_SOURCE_SHA: commit,
      LCF_SOURCE_TREE: tree,
      LCF_SOURCE_DATE_EPOCH: sourceDateEpoch,
      LCF_SOURCE_SNAPSHOT_SHA256: createHash("sha256")
        .update(Buffer.from(JSON.stringify(inventory), "utf8"))
        .digest("hex"),
      LCF_RENDERER_PACKAGE_LOCK_SHA256: createHash("sha256")
        .update(await readFile(rendererPackageLockPath))
        .digest("hex")
    };
    const snapshot = prepare.inspectRepositorySourceSnapshot(root, environment);
    const buildRoot = path.join(workspace, "entrypoint-output");
    await mkdir(buildRoot, { recursive: true });
    const esbuildImplementation = await import("esbuild");
    const attestation = await entrypointBuilder.buildEntrypointsFromSnapshot({
      snapshot,
      repositoryRoot: root,
      buildRoot,
      environment,
      esbuildImplementation,
      installSummary: {
        installedContentSha256: "5".repeat(64),
        lockSha256: "6".repeat(64),
        nodeVersion: "v22.23.2",
        npmVersion: "10.9.8"
      }
    });
    const mainBundle = await readFile(
      path.join(buildRoot, "dist", "main", "index.js"),
      "utf8"
    );
    expect(mainBundle).toContain("reviewed-marker");
    expect(mainBundle).not.toContain("transient-marker");
    expect(attestation).toMatchObject({
      kind: "engineering-smoke-entrypoint-build",
      source: { commit, tree },
      builder: { name: "esbuild", version: "0.28.1" }
    });
    await writeFile(
      desktopPackagePath,
      '{"name":"desktop-fixture","version":"9.9.9-transient"}\n'
    );
    expect(
      prepare.loadReviewedDesktopPackageMetadata(snapshot, root).version
    ).toBe("0.0.0");
    await writeFile(desktopPackagePath, reviewedDesktopPackage);
    await writeFile(
      mainPath,
      'export const provenanceMarker = "transient-marker";\n'
    );
    const selectedInputs = entrypointBuilder.selectReviewedInputs(
      snapshot,
      root
    );
    expect(
      selectedInputs.bytesByPath.get("desktop/src/main/index.ts")
    ).toEqual(reviewedMain);
    await writeFile(mainPath, reviewedMain);
  });

  it("copies held entrypoint descriptors across post-validation pathname replacement and restore", async () => {
    const workspace = await temporaryRoot("lcf-entrypoint-held-copy-");
    const sourceRoot = path.join(workspace, "source");
    const destinationRoot = path.join(workspace, "destination");
    const mainPath = path.join(sourceRoot, "dist", "main", "index.js");
    const preloadPath = path.join(
      sourceRoot,
      "dist",
      "preload",
      "index.cjs"
    );
    const reviewedMain = Buffer.from("reviewed-main-entrypoint\n", "utf8");
    const reviewedPreload = Buffer.from(
      "reviewed-preload-entrypoint\n",
      "utf8"
    );
    await mkdir(path.dirname(mainPath), { recursive: true });
    await mkdir(path.dirname(preloadPath), { recursive: true });
    await writeFile(mainPath, reviewedMain);
    await writeFile(preloadPath, reviewedPreload);
    const outputs = {
      main: {
        path: "dist/main/index.js",
        sha256: createHash("sha256").update(reviewedMain).digest("hex"),
        bytes: reviewedMain.length
      },
      preload: {
        path: "dist/preload/index.cjs",
        sha256: createHash("sha256").update(reviewedPreload).digest("hex"),
        bytes: reviewedPreload.length
      }
    };
    const heldPath = `${mainPath}.held`;
    let replaced = false;
    let restored = false;

    const copied = prepare.copyAttestedEntrypointOutputs(
      sourceRoot,
      destinationRoot,
      outputs,
      {
        afterSourceOpen: ({ expected }: JsonObject) => {
          if (expected.path !== outputs.main.path) {
            return;
          }
          renameSync(mainPath, heldPath);
          writeFileSync(mainPath, "unreviewed-pathname-replacement\n");
          replaced = true;
        },
        afterReadChunk: ({ expected, chunk }: JsonObject) => {
          if (expected.path !== outputs.main.path || chunk !== 1) {
            return;
          }
          rmSync(mainPath);
          renameSync(heldPath, mainPath);
          restored = true;
        }
      }
    );

    expect(replaced).toBe(true);
    expect(restored).toBe(true);
    expect(copied).toEqual(outputs);
    expect(
      await readFile(
        path.join(destinationRoot, "dist", "main", "index.js")
      )
    ).toEqual(reviewedMain);
    expect(await readFile(mainPath)).toEqual(reviewedMain);
  });

  it("fails closed on a mid-copy entrypoint mutation without touching old staging", async () => {
    const workspace = await temporaryRoot("lcf-entrypoint-mid-copy-");
    const sourceRoot = path.join(workspace, "source");
    const temporaryApp = path.join(workspace, "temporary-app");
    const oldStaging = path.join(workspace, "old-staging");
    const mainPath = path.join(sourceRoot, "dist", "main", "index.js");
    const preloadPath = path.join(
      sourceRoot,
      "dist",
      "preload",
      "index.cjs"
    );
    const reviewedMain = Buffer.alloc(3 * 1024 * 1024, 0x41);
    const reviewedPreload = Buffer.from("reviewed-preload\n", "utf8");
    await mkdir(path.dirname(mainPath), { recursive: true });
    await mkdir(path.dirname(preloadPath), { recursive: true });
    await mkdir(oldStaging);
    await writeFile(path.join(oldStaging, "old.txt"), "old-staging\n");
    await writeFile(mainPath, reviewedMain);
    await writeFile(preloadPath, reviewedPreload);
    const outputs = {
      main: {
        path: "dist/main/index.js",
        sha256: createHash("sha256").update(reviewedMain).digest("hex"),
        bytes: reviewedMain.length
      },
      preload: {
        path: "dist/preload/index.cjs",
        sha256: createHash("sha256").update(reviewedPreload).digest("hex"),
        bytes: reviewedPreload.length
      }
    };
    let mutated = false;

    expect(() =>
      prepare.copyAttestedEntrypointOutputs(
        sourceRoot,
        temporaryApp,
        outputs,
        {
          afterReadChunk: ({ expected, chunk }: JsonObject) => {
            if (
              expected.path === outputs.main.path &&
              chunk === 1 &&
              !mutated
            ) {
              writeFileSync(mainPath, Buffer.alloc(reviewedMain.length, 0x42));
              mutated = true;
            }
          }
        }
      )
    ).toThrow(/entrypoint source changed while copied/);
    expect(mutated).toBe(true);
    expect(await readFile(path.join(oldStaging, "old.txt"), "utf8")).toBe(
      "old-staging\n"
    );
  });

  it("restores old engineering staging when the second candidate rename fails", async () => {
    const workspace = await temporaryRoot("lcf-engineering-publish-rename-");
    const temporaryApp = path.join(workspace, "temporary-app");
    const temporaryManifest = path.join(workspace, "temporary.json");
    const appDestination = path.join(workspace, "app");
    const manifestDestination = path.join(workspace, "distribution.json");
    await mkdir(temporaryApp);
    await mkdir(appDestination);
    await writeFile(path.join(temporaryApp, "new.txt"), "new\n");
    await writeFile(temporaryManifest, "new manifest\n");
    await writeFile(path.join(appDestination, "old.txt"), "old\n");
    await writeFile(manifestDestination, "old manifest\n");
    let renameCount = 0;

    expect(() =>
      prepare.publishPreparedEngineeringSmoke(
        {
          temporaryApp,
          temporaryManifest,
          appDestination,
          manifestDestination,
          auditPublished: () => {
            throw new Error("audit must not run");
          }
        },
        {
          rename: (source: string, destination: string) => {
            renameCount += 1;
            if (renameCount === 4) {
              throw new Error("injected second candidate rename failure");
            }
            renameSync(source, destination);
          }
        }
      )
    ).toThrow(/injected second candidate rename failure/);
    expect(renameCount).toBe(7);
    expect(await readFile(path.join(appDestination, "old.txt"), "utf8")).toBe(
      "old\n"
    );
    expect(await readFile(manifestDestination, "utf8")).toBe(
      "old manifest\n"
    );
  });

  it("restores old engineering staging when post-publish audit fails", async () => {
    const workspace = await temporaryRoot("lcf-engineering-publish-audit-");
    const temporaryApp = path.join(workspace, "temporary-app");
    const temporaryManifest = path.join(workspace, "temporary.json");
    const appDestination = path.join(workspace, "app");
    const manifestDestination = path.join(workspace, "distribution.json");
    await mkdir(temporaryApp);
    await mkdir(appDestination);
    await writeFile(path.join(temporaryApp, "new.txt"), "new\n");
    await writeFile(temporaryManifest, "new manifest\n");
    await writeFile(path.join(appDestination, "old.txt"), "old\n");
    await writeFile(manifestDestination, "old manifest\n");
    let renameCount = 0;

    expect(() =>
      prepare.publishPreparedEngineeringSmoke(
        {
          temporaryApp,
          temporaryManifest,
          appDestination,
          manifestDestination,
          auditPublished: () => {
            throw new Error("injected post-publish audit failure");
          }
        },
        {
          rename: (source: string, destination: string) => {
            renameCount += 1;
            renameSync(source, destination);
          }
        }
      )
    ).toThrow(/injected post-publish audit failure/);
    expect(renameCount).toBe(8);
    expect(await readFile(path.join(appDestination, "old.txt"), "utf8")).toBe(
      "old\n"
    );
    expect(await readFile(manifestDestination, "utf8")).toBe(
      "old manifest\n"
    );
  });

  it("rejects signed-commit gpg configuration without executing its program", async () => {
    const workspace = await temporaryRoot("lcf-git-gpg-config-");
    const root = path.join(workspace, "repository");
    await mkdir(root);
    await writeFile(path.join(root, "reviewed.txt"), "reviewed\n");
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
    const parent = git("rev-parse", "HEAD");
    const tree = git("rev-parse", "HEAD^{tree}");
    const signedCommitBytes = Buffer.from(
      [
        `tree ${tree}`,
        `parent ${parent}`,
        "author LCF Test <lcf-test@example.invalid> 1800000000 +0000",
        "committer LCF Test <lcf-test@example.invalid> 1800000000 +0000",
        "gpgsig -----BEGIN PGP SIGNATURE-----",
        " ",
        " ZmFrZQ==",
        " -----END PGP SIGNATURE-----",
        "",
        "signed fixture",
        ""
      ].join("\n"),
      "utf8"
    );
    const signedCommit = execFileSync(
      "/usr/bin/git",
      ["-C", root, "hash-object", "-t", "commit", "-w", "--stdin"],
      { encoding: "utf8", env: gitEnvironment, input: signedCommitBytes }
    ).trim();
    git("update-ref", "HEAD", signedCommit);
    const marker = path.join(workspace, "gpg-program-executed");
    const gpgProgram = path.join(workspace, "gpg-program.sh");
    await writeFile(
      gpgProgram,
      `#!/bin/sh\nprintf executed > ${JSON.stringify(marker)}\nexit 0\n`
    );
    await chmod(gpgProgram, 0o755);
    git("config", "--local", "log.showSignature", "true");
    git("config", "--local", "gpg.program", gpgProgram);

    expect(() =>
      prepare.inspectRepositorySourceSnapshot(root, {})
    ).toThrow(/^Local Git config contains an unsafe key$/);
    await expect(readFile(marker)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("rejects a package-lock rename-replace-restore before exact npm can run", async () => {
    const fixture = await exactNodeInstallFixture("lcf-node-lock-aba-");
    const lockPath = path.join(
      fixture.repository,
      "web",
      "package-lock.json"
    );
    const heldPath = `${lockPath}.held`;

    expect(() =>
      exactNodeInstall.installExactNodeDependencies({
        repositoryRoot: fixture.repository,
        packageName: "web",
        sealPath: fixture.sealPath,
        npmExecutable: fixture.npmExecutable,
        temporaryParent: fixture.workspace,
        environment: fixture.environment,
        runtimeContract: fixture.runtimeContract,
        afterCapabilitiesBound: () => {
          renameSync(lockPath, heldPath);
          writeFileSync(lockPath, "{\"transient\":true}\n");
          rmSync(lockPath);
          renameSync(heldPath, lockPath);
        }
      })
    ).toThrow(/metadata parent changed before install/);
    await expect(readFile(fixture.npmMarker)).rejects.toMatchObject({
      code: "ENOENT"
    });
    await expect(readFile(fixture.sealPath)).rejects.toMatchObject({
      code: "ENOENT"
    });
  });

  it("rejects an npm executable outside the selected Node runtime before execution", async () => {
    const fixture = await exactNodeInstallFixture(
      "lcf-node-external-npm-"
    );
    const productionRuntimeContract = {
      nodeVersion: process.version,
      npmVersion: "10.9.8"
    };

    expect(() =>
      exactNodeInstall.installExactNodeDependencies({
        repositoryRoot: fixture.repository,
        packageName: "web",
        sealPath: fixture.sealPath,
        npmExecutable: fixture.npmExecutable,
        temporaryParent: fixture.workspace,
        environment: fixture.environment,
        runtimeContract: productionRuntimeContract
      })
    ).toThrow(/npm runtime is unsafe/);
    await expect(readFile(fixture.npmMarker)).rejects.toMatchObject({
      code: "ENOENT"
    });
  });

  it("rejects a sealed install-root replacement even when package versions are unchanged", async () => {
    const fixture = await exactNodeInstallFixture(
      "lcf-node-install-replacement-"
    );
    const seal = exactNodeInstall.installExactNodeDependencies({
      repositoryRoot: fixture.repository,
      packageName: "web",
      sealPath: fixture.sealPath,
      npmExecutable: fixture.npmExecutable,
      temporaryParent: fixture.workspace,
      environment: fixture.environment,
      runtimeContract: fixture.runtimeContract
    });
    expect(seal.install.contentInventorySha256).toMatch(/^[0-9a-f]{64}$/);
    expect(seal.install.symlinks).toBe(1);
    const toolPath = path.join(
      fixture.repository,
      "web",
      "node_modules",
      "reviewed-tool",
      "index.js"
    );
    const replacement = `${toolPath}.replacement`;
    await writeFile(
      replacement,
      "module.exports = 2; // same package version, different bytes\n"
    );
    renameSync(replacement, toolPath);

    expect(() =>
      exactNodeInstall.verifyNodeInstallSeal({
        repositoryRoot: fixture.repository,
        packageName: "web",
        sealPath: fixture.sealPath,
        environment: fixture.environment,
        runtimeContract: fixture.runtimeContract
      })
    ).toThrow(/install tree differs from its seal/);
  });

  it("rejects a lexical in-tree symlink whose real target escapes the install", async () => {
    const fixture = await exactNodeInstallFixture(
      "lcf-node-realpath-escape-"
    );
    exactNodeInstall.installExactNodeDependencies({
      repositoryRoot: fixture.repository,
      packageName: "web",
      sealPath: fixture.sealPath,
      npmExecutable: fixture.npmExecutable,
      temporaryParent: fixture.workspace,
      environment: fixture.environment,
      runtimeContract: fixture.runtimeContract
    });
    const nodeModulesRoot = path.join(
      fixture.repository,
      "web",
      "node_modules"
    );
    const reviewedBin = path.join(nodeModulesRoot, ".bin", "reviewed-tool");
    rmSync(reviewedBin);
    await writeFile(path.join(fixture.workspace, "outside-cli.js"), "outside\n");
    await symlink(fixture.workspace, path.join(nodeModulesRoot, "escape-hop"));
    await symlink("../escape-hop/outside-cli.js", reviewedBin);

    expect(() =>
      exactNodeInstall.inventoryNodeInstall(nodeModulesRoot)
    ).toThrow(/escaping symlink/);
  });

  it("fails the final install postcheck before an artifact can be accepted", async () => {
    const fixture = await exactNodeInstallFixture(
      "lcf-node-postcheck-before-publish-"
    );
    let accepted = false;
    expect(() => {
      exactNodeInstall.installExactNodeDependencies({
        repositoryRoot: fixture.repository,
        packageName: "web",
        sealPath: fixture.sealPath,
        npmExecutable: fixture.npmExecutable,
        temporaryParent: fixture.workspace,
        environment: fixture.environment,
        runtimeContract: fixture.runtimeContract,
        afterSealWritten: ({ nodeModulesRoot }: JsonObject) => {
          writeFileSync(
            path.join(nodeModulesRoot, "reviewed-tool", "index.js"),
            "module.exports = 3;\n"
          );
        }
      });
      accepted = true;
    }).toThrow(/install tree differs from its seal/);
    expect(accepted).toBe(false);
  });
});

describe("engineering-smoke distribution profile", () => {
  it("keeps source tests standard while resolving a fixed isolated engineering profile", () => {
    expect(COMPILED_DISTRIBUTION_PROFILE).toEqual(
      resolveDistributionProfile("standard")
    );
    expect(resolveDistributionProfile("engineering-smoke")).toEqual({
      name: "engineering-smoke",
      productName: "Local Context Forge Engineering Smoke",
      dataDirectoryName: "Local Context Forge Engineering Smoke",
      cacheDirectoryName: "Local Context Forge Engineering Smoke",
      updaterPolicy: "engineering-disabled",
      engineeringOnly: true
    });
  });

  it("makes the engineering updater unavailable without touching trust, network, files, or shell", async () => {
    const root = await temporaryRoot("lcf-engineering-update-");
    const loadTrustAnchor = vi.fn(async () => {
      throw new Error("must not load production update trust");
    });
    const fetchBytes = vi.fn<UpdateFetchBytes>(async () => {
      throw new Error("must not fetch");
    });
    const streamAsset = vi.fn<UpdateStreamAsset>(async () => {
      throw new Error("must not stream");
    });
    const openPath = vi.fn(async () => "");
    const openExternal = vi.fn(async () => undefined);
    const client = await UpdateClient.create({
      packaged: true,
      platform: "darwin",
      architecture: "arm64",
      currentVersion: "0.3.0-alpha.1",
      resourcesPath: path.join(root, "Resources"),
      updateDirectory: path.join(root, "updates"),
      distributionPolicy: "engineering-disabled",
      loadTrustAnchor,
      fetchBytes,
      streamAsset,
      openPath,
      openExternal
    });

    const status = client.getStatus();
    expect(status).toMatchObject({
      state: "unavailable",
      unavailableReason: "engineering-smoke",
      canCheck: false,
      canDownloadOrOpen: false,
      canOpenReleasePage: false,
      automaticApply: false
    });
    expect(isUpdateStatus(status)).toBe(true);
    await expect(client.check()).rejects.toMatchObject({ code: "unavailable" });
    await expect(client.downloadOrOpen()).rejects.toMatchObject({
      code: "unavailable"
    });
    await expect(client.openReleasePage()).rejects.toMatchObject({
      code: "unavailable"
    });
    await client.cancel();
    await client.shutdown();
    for (const spy of [
      loadTrustAnchor,
      fetchBytes,
      streamAsset,
      openPath,
      openExternal
    ]) {
      expect(spy).not.toHaveBeenCalled();
    }
  });
});

describe("engineering-smoke manifest and boundary", () => {
  it("accepts only the strict UNOFFICIAL manifest with packaged validation not-run", async () => {
    const schema = await loadSchema();
    const manifest = distributionManifest();
    expect(
      common.validateEngineeringSmokeManifest(manifest, schema)
    ).toBe(manifest);
    expect(manifest.components.pythonSidecar).toMatchObject({
      pythonBuildToolchainPath:
        "Contents/Resources/sidecar/python-build-toolchain.json",
      pythonToolchain: {
        installedTreeContentSha256: "4".repeat(64),
        buildTools: { uvVersion: "0.11.29" }
      }
    });

    for (const mutate of [
      (value: JsonObject) => {
        value.unreviewed = true;
      },
      (value: JsonObject) => {
        value.capabilities.networkAllowed = true;
      },
      (value: JsonObject) => {
        value.validation.packagedSmoke = "pass";
      },
      (value: JsonObject) => {
        value.validation.unlocks = ["W10"];
      },
      (value: JsonObject) => {
        value.source.sourceSnapshotSha256 = "f".repeat(64);
      },
      (value: JsonObject) => {
        value.components.desktopApp.entrypointBuild.nodeVersion = "v22.23.3";
      },
      (value: JsonObject) => {
        value.components.desktopApp.entrypointBuild.npmVersion = "10.9.9";
      },
      (value: JsonObject) => {
        value.components.pythonSidecar.pythonToolchain.buildTools.uvVersion =
          "0.0.0";
      },
      (value: JsonObject) => {
        delete value.components.pythonSidecar.pythonBuildToolchainPath;
      },
      (value: JsonObject) => {
        value.components.pythonSidecar.pythonToolchain
          .installedTreeContentSha256 = "not-a-digest";
      }
    ]) {
      const changed = structuredClone(manifest);
      mutate(changed);
      expect(() =>
        common.validateEngineeringSmokeManifest(changed, schema)
      ).toThrow();
    }
  });

  it("rejects production credentials, non-arm64 hosts, and ambiguous source commits", () => {
    expect(() => prepare.assertNoProductionEnvironment({})).not.toThrow();
    expect(() =>
      prepare.assertNoProductionEnvironment({ CSC_FOR_PULL_REQUEST: "true" })
    ).not.toThrow();
    expect(() =>
      prepare.assertNoProductionEnvironment({ CSC_FOR_PULL_REQUEST: "1" })
    ).toThrow(/ad-hoc signing control/);
    expect(() =>
      prepare.assertNoProductionEnvironment({ CSC_LINK: "secret" })
    ).toThrow();
    expect(() => prepare.validateHost("darwin", "arm64")).not.toThrow();
    expect(() => prepare.validateHost("linux", "arm64")).toThrow();
    expect(() =>
      prepare.assertEngineeringSmokeMode({ LCF_ENGINEERING_SMOKE: "true" })
    ).not.toThrow();
    expect(() =>
      prepare.assertEngineeringSmokeMode({ LCF_ENGINEERING_SMOKE: "1" })
    ).toThrow();
    expect(
      prepare.selectedSourceCommit({
        GITHUB_SHA: "f".repeat(40),
        LCF_SOURCE_SHA: "a".repeat(40)
      })
    ).toBe("a".repeat(40));
    expect(() => prepare.selectedSourceCommit({ GITHUB_SHA: "merge" })).toThrow();
    expect(() =>
      prepare.selectedSourceCommit({ GITHUB_SHA: "f".repeat(40) })
    ).toThrow();
    expect(
      prepare.selectedSourceTree({ LCF_SOURCE_TREE: "b".repeat(40) })
    ).toBe("b".repeat(40));
    expect(() =>
      prepare.selectedSourceTree({ GITHUB_SHA: "f".repeat(40) })
    ).toThrow();
  });

  it("runs every initializer preflight before a staging deletion can be reached", () => {
    const inspectRepository = vi.fn(() => ({
      commit: "a".repeat(40),
      tree: "b".repeat(40),
      sourceSnapshotSha256: "c".repeat(64),
      sourceDateEpoch: 1_800_000_000
    }));
    expect(() =>
      prepare.preflightEngineeringSmoke({
        platform: "darwin",
        architecture: "arm64",
        environment: { LCF_ENGINEERING_SMOKE: "false" },
        inspectRepository
      })
    ).toThrow();
    expect(inspectRepository).not.toHaveBeenCalled();
    expect(
      prepare.preflightEngineeringSmoke({
        platform: "darwin",
        architecture: "arm64",
        environment: { LCF_ENGINEERING_SMOKE: "true" },
        inspectRepository
      })
    ).toMatchObject({ commit: "a".repeat(40) });
    expect(inspectRepository).toHaveBeenCalledOnce();
  });

  it("rejects a generated-root parent symlink before any fixed-tree deletion", async () => {
    const root = await temporaryRoot("lcf-engineering-generated-root-");
    const desktopRoot = path.join(root, "desktop");
    const outside = path.join(root, "outside");
    await mkdir(desktopRoot);
    await mkdir(outside);
    await symlink(outside, path.join(desktopRoot, "generated"));
    expect(await realpath(root)).toBe(root);
    expect(await realpath(desktopRoot)).toBe(desktopRoot);
    expect(await realpath(path.join(desktopRoot, "generated"))).toBe(outside);
    expect(() =>
      prepare.requireSafeGeneratedRoot(
        path.join(desktopRoot, "generated"),
        desktopRoot
      )
    ).toThrow(
      /^Engineering-smoke generated root must be a real canonical directory$/
    );
  });

  it("requires the exact smoke product and refuses publish-enabled contexts", () => {
    const context = {
      electronPlatformName: "darwin",
      arch: "arm64",
      packager: {
        appInfo: { productFilename: "Local Context Forge Engineering Smoke" },
        config: { publish: null }
      }
    };
    expect(() => beforePack.assertContext(context)).not.toThrow();
    expect(() =>
      beforePack.assertContext({
        ...context,
        packager: {
          ...context.packager,
          config: { publish: [{ provider: "github" }] }
        }
      })
    ).toThrow();
    expect(() =>
      beforePack.assertContext({
        ...context,
        packager: {
          ...context.packager,
          appInfo: { productFilename: "Local Context Forge" }
        }
      })
    ).toThrow();
  });

  it("records contained symlinks canonically and rejects an escaping symlink", async () => {
    const workspace = await temporaryRoot("lcf-engineering-inventory-");
    const root = path.join(workspace, "inventory");
    const outside = path.join(workspace, "outside");
    await mkdir(root);
    await mkdir(outside);
    await mkdir(path.join(root, "dir"));
    await writeFile(path.join(root, "dir", "payload"), "payload\n");
    await symlink("dir/payload", path.join(root, "payload-link"));
    const records = common.buildInventory(root);
    expect(records).toContainEqual(
      expect.objectContaining({
        path: "payload-link",
        type: "symlink",
        linkTarget: "dir/payload"
      })
    );
    expect(common.normalizedInventorySha256(records)).toMatch(/^[0-9a-f]{64}$/);
    await chmod(path.join(root, "dir", "payload"), 0o666);
    expect(() => common.buildInventory(root)).toThrow(/world-writable/);
    await chmod(path.join(root, "dir", "payload"), 0o644);
    await symlink("../outside", path.join(root, "escape"));
    expect(() => common.buildInventory(root)).toThrow(
      /^Engineering-smoke symlink escapes the app bundle$/
    );
  });

  it("keeps the inventory gate strict for a symlinked ancestor", async () => {
    const workspace = await temporaryRoot("lcf-engineering-alias-");
    const physical = path.join(workspace, "physical");
    const inventory = path.join(physical, "inventory");
    await mkdir(inventory, { recursive: true });
    await symlink("physical", path.join(workspace, "alias"));

    expect(() =>
      common.buildInventory(path.join(workspace, "alias", "inventory"))
    ).toThrow(/^Inventory root must be a real canonical directory$/);
  });
});

describe("engineering-smoke post-pack policy", () => {
  it("binds the exact app.asar entries and prepared Desktop byte hashes", async () => {
    const root = await temporaryRoot("lcf-engineering-asar-");
    const source = path.join(root, "source");
    const archive = path.join(root, "app.asar");
    const main = Buffer.from("engineering main\n", "utf8");
    const preload = Buffer.from("engineering preload\n", "utf8");
    const packageMetadata = {
      description:
        "UNOFFICIAL engineering-only Local Context Forge smoke bundle",
      main: "dist/main/index.js",
      name: "local-context-forge-engineering-smoke",
      private: true,
      version: "0.3.0-alpha.1"
    };
    const packageBytes = Buffer.from(
      `${JSON.stringify(packageMetadata)}\n`,
      "utf8"
    );
    await mkdir(path.join(source, "dist", "main"), { recursive: true });
    await mkdir(path.join(source, "dist", "preload"), { recursive: true });
    await writeFile(path.join(source, "dist", "main", "index.js"), main);
    await writeFile(
      path.join(source, "dist", "preload", "index.cjs"),
      preload
    );
    await writeFile(path.join(source, "package.json"), packageBytes);
    await asar.createPackage(source, archive);

    const manifest = distributionManifest();
    manifest.components.desktopApp = {
      asarPath: "Contents/Resources/app.asar",
      mainPath: "dist/main/index.js",
      mainSha256: createHash("sha256").update(main).digest("hex"),
      mainBytes: main.length,
      preloadPath: "dist/preload/index.cjs",
      preloadSha256: createHash("sha256").update(preload).digest("hex"),
      preloadBytes: preload.length,
      packagePath: "package.json",
      packageSha256: createHash("sha256").update(packageBytes).digest("hex"),
      packageBytes: packageBytes.length,
      entrypointBuild: {
        builder: "esbuild",
        builderVersion: "0.28.1",
        inputs: 35,
        inputsSha256: "9".repeat(64)
      }
    };
    const inspected = bundleAudit.inspectAsarContents(archive, manifest);
    expect(inspected).toMatchObject({
      entries: 6,
      mainSha256: manifest.components.desktopApp.mainSha256
    });
    expect(() =>
      bundleAudit.validateAsarIntegrity(
        {
          ElectronAsarIntegrity: {
            "Resources/app.asar": {
              algorithm: "SHA256",
              hash: inspected.headerSha256
            }
          }
        },
        inspected.headerSha256
      )
    ).not.toThrow();

    manifest.components.desktopApp.mainSha256 = "0".repeat(64);
    expect(() =>
      bundleAudit.inspectAsarContents(archive, manifest)
    ).toThrow(/prepared Desktop bytes/);
  });

  it("flips every reviewed Electron fuse without invoking the app", async () => {
    const root = await temporaryRoot("lcf-engineering-after-pack-");
    const appOutDir = path.join(root, "mac-arm64");
    const executable = path.join(
      appOutDir,
      "Local Context Forge Engineering Smoke.app",
      "Contents",
      "MacOS",
      "Local Context Forge Engineering Smoke"
    );
    await mkdir(path.dirname(executable), { recursive: true });
    await writeFile(executable, "fixture Electron executable");
    const flipFuses = vi.fn(async () => 1);
    const hook = afterPack.createAfterPackEngineeringSmoke({
      flipFuses,
      environment: { LCF_ENGINEERING_SMOKE: "true" },
      platform: "darwin",
      architecture: "arm64"
    });
    await hook({
      electronPlatformName: "darwin",
      arch: "arm64",
      appOutDir,
      packager: {
        appInfo: { productFilename: "Local Context Forge Engineering Smoke" }
      }
    });
    expect(flipFuses).toHaveBeenCalledOnce();
    expect(flipFuses).toHaveBeenCalledWith(executable, afterPack.SECURE_FUSES);
    expect(afterPack.SECURE_FUSES).toMatchObject({
      resetAdHocDarwinSignature: true,
      strictlyRequireAllFuses: true
    });
  });

  it("requires exact secure fuse states and exact Info.plist markers", async () => {
    const wire: JsonObject = { version: fuses.FuseVersion.V1 };
    const expected = new Map([
      [fuses.FuseV1Options.RunAsNode, fuses.FuseState.DISABLE],
      [fuses.FuseV1Options.EnableCookieEncryption, fuses.FuseState.ENABLE],
      [
        fuses.FuseV1Options.EnableNodeOptionsEnvironmentVariable,
        fuses.FuseState.DISABLE
      ],
      [
        fuses.FuseV1Options.EnableNodeCliInspectArguments,
        fuses.FuseState.DISABLE
      ],
      [
        fuses.FuseV1Options.EnableEmbeddedAsarIntegrityValidation,
        fuses.FuseState.ENABLE
      ],
      [fuses.FuseV1Options.OnlyLoadAppFromAsar, fuses.FuseState.ENABLE],
      [
        fuses.FuseV1Options.LoadBrowserProcessSpecificV8Snapshot,
        fuses.FuseState.ENABLE
      ],
      [
        fuses.FuseV1Options.GrantFileProtocolExtraPrivileges,
        fuses.FuseState.DISABLE
      ],
      [fuses.FuseV1Options.WasmTrapHandlers, fuses.FuseState.ENABLE]
    ]);
    for (const [key, value] of expected) wire[key] = value;
    await expect(
      bundleAudit.inspectSecureFuses("/fixture/Electron", async () => wire)
    ).resolves.toMatchObject({
      RunAsNode: false,
      EnableCookieEncryption: true,
      OnlyLoadAppFromAsar: true
    });
    const weakened = { ...wire, [fuses.FuseV1Options.RunAsNode]: fuses.FuseState.ENABLE };
    await expect(
      bundleAudit.inspectSecureFuses("/fixture/Electron", async () => weakened)
    ).rejects.toThrow();

    const info = {
      CFBundleIdentifier: "dev.localcontextforge.engineering-smoke",
      CFBundleName: "Local Context Forge Engineering Smoke",
      CFBundleDisplayName: "Local Context Forge Engineering Smoke",
      CFBundleExecutable: "Local Context Forge Engineering Smoke",
      CFBundlePackageType: "APPL",
      CFBundleShortVersionString: "0.3.0-alpha.1",
      CFBundleVersion: "0.3.0-alpha.1",
      LCFDistributionClass: "engineering-smoke",
      LCFDistributionMarker: "UNOFFICIAL",
      LCFEngineeringOnly: true,
      LCFPublishable: false,
      LCFUpdaterMode: "unavailable",
      LCFNetworkAllowed: false,
      LCFManualReleasePageAllowed: false,
      LCFPackagedAppLaunch: "not-run",
      LCFPackagedSmokeValidation: "not-run"
    };
    expect(() =>
      bundleAudit.validateInfoPlist(info, "0.3.0-alpha.1")
    ).not.toThrow();
    expect(() =>
      bundleAudit.validateInfoPlist(
        { ...info, LCFPublishable: true },
        "0.3.0-alpha.1"
      )
    ).toThrow();
  });

  it("requires exactly one canonical app and rejects package/install artifacts", async () => {
    const root = await temporaryRoot("lcf-engineering-output-");
    const appRoot = path.join(
      root,
      "mac-arm64",
      "Local Context Forge Engineering Smoke.app"
    );
    await mkdir(appRoot, { recursive: true });
    for (const helper of bundleAudit.ALLOWED_ELECTRON_HELPER_APPS) {
      await mkdir(
        path.join(appRoot, "Contents", "Frameworks", helper),
        { recursive: true }
      );
    }
    const reviewedArchive = path.join(
      appRoot,
      ...bundleAudit.REVIEWED_PYINSTALLER_ARCHIVE.split("/")
    );
    await mkdir(path.dirname(reviewedArchive), { recursive: true });
    await writeFile(reviewedArchive, "reviewed PyInstaller stdlib\n");
    expect(() =>
      bundleAudit.assertNoInstallOrReleaseArtifacts(root, appRoot)
    ).not.toThrow();
    await rm(reviewedArchive);
    expect(() =>
      bundleAudit.assertNoInstallOrReleaseArtifacts(root, appRoot)
    ).toThrow(/reviewed Python runtime archive is missing/);
    await writeFile(reviewedArchive, "reviewed PyInstaller stdlib\n");

    const unreviewedArchive = path.join(
      appRoot,
      "Contents",
      "Resources",
      "payload.zip"
    );
    await writeFile(unreviewedArchive, "unreviewed archive\n");
    expect(() =>
      bundleAudit.assertNoInstallOrReleaseArtifacts(root, appRoot)
    ).toThrow(/install or release/);
    await rm(unreviewedArchive);

    const sidecarArchive = path.join(
      path.dirname(reviewedArchive),
      "evil.zip"
    );
    await writeFile(sidecarArchive, "unreviewed sidecar archive\n");
    expect(() =>
      bundleAudit.assertNoInstallOrReleaseArtifacts(root, appRoot)
    ).toThrow(/install or release/);
    await rm(sidecarArchive);

    const archivePayload = path.join(
      path.dirname(reviewedArchive),
      "base_library.payload"
    );
    await writeFile(archivePayload, "archive payload\n");
    await rm(reviewedArchive);
    await symlink("base_library.payload", reviewedArchive);
    expect(() =>
      bundleAudit.assertNoInstallOrReleaseArtifacts(root, appRoot)
    ).toThrow(/install or release/);
    await rm(reviewedArchive);
    await link(archivePayload, reviewedArchive);
    expect(() =>
      bundleAudit.assertNoInstallOrReleaseArtifacts(root, appRoot)
    ).toThrow(/install or release/);
    await rm(reviewedArchive);
    await rm(archivePayload);
    await writeFile(reviewedArchive, "");
    expect(() =>
      bundleAudit.assertNoInstallOrReleaseArtifacts(root, appRoot)
    ).toThrow(/install or release/);
    await rm(reviewedArchive);
    await mkdir(reviewedArchive);
    expect(() =>
      bundleAudit.assertNoInstallOrReleaseArtifacts(root, appRoot)
    ).toThrow(/install or release/);
    await rm(reviewedArchive, { recursive: true });
    const caseDriftArchive = path.join(
      path.dirname(reviewedArchive),
      "base_library.ZIP"
    );
    await writeFile(caseDriftArchive, "case drift\n");
    expect(() =>
      bundleAudit.assertNoInstallOrReleaseArtifacts(root, appRoot)
    ).toThrow(/install or release/);
    await rm(caseDriftArchive);
    await writeFile(reviewedArchive, "reviewed PyInstaller stdlib\n");

    const missingHelper = path.join(
      appRoot,
      "Contents",
      "Frameworks",
      bundleAudit.ALLOWED_ELECTRON_HELPER_APPS[0]!
    );
    await rm(missingHelper, { recursive: true });
    expect(() =>
      bundleAudit.assertNoInstallOrReleaseArtifacts(root, appRoot)
    ).toThrow(/helper app closure/);
    await mkdir(missingHelper, { recursive: true });

    const nestedApp = path.join(
      appRoot,
      "Contents",
      "Resources",
      "Evil.app"
    );
    await mkdir(nestedApp, { recursive: true });
    expect(() =>
      bundleAudit.assertNoInstallOrReleaseArtifacts(root, appRoot)
    ).toThrow(/unexpected nested app/);
    await rm(nestedApp, { recursive: true });

    const extraApp = path.join(root, "Evil.APP");
    await mkdir(extraApp);
    expect(() =>
      bundleAudit.assertNoInstallOrReleaseArtifacts(root, appRoot)
    ).toThrow(/exactly one/);
    await rm(extraApp, { recursive: true });
    const payload = path.join(root, "payload");
    await writeFile(payload, "fixture\n");
    await symlink("payload", path.join(root, "unexpected.dmg"));
    expect(() =>
      bundleAudit.assertNoInstallOrReleaseArtifacts(root, appRoot)
    ).toThrow(/install or release/);
  });

  it("keeps the package command dir-only and routes engineering entrypoints through the exact builder", async () => {
    const packageMetadata = JSON.parse(
      await readFile(path.join(repositoryRoot, "desktop", "package.json"), "utf8")
    ) as JsonObject;
    const scripts = packageMetadata.scripts as Record<string, string>;
    expect(scripts["build:main"]).toContain("src/main/index.ts");
    expect(scripts["build:main"]).toContain(
      "__LCF_DISTRIBUTION_PROFILE__='\"standard\"'"
    );
    expect(scripts["build:engineering-smoke"]).toBe(
      "node scripts/buildEngineeringSmokeEntrypoints.cjs"
    );
    const exactBuilder = await readFile(
      path.join(
        repositoryRoot,
        "desktop",
        "scripts",
        "buildEngineeringSmokeEntrypoints.cjs"
      ),
      "utf8"
    );
    expect(exactBuilder).toContain(
      'entryPoints: ["lcf-reviewed:desktop/src/main/index.ts"]'
    );
    expect(exactBuilder).toContain(
      '__LCF_DISTRIBUTION_PROFILE__: JSON.stringify("engineering-smoke")'
    );
    expect(exactBuilder).toContain("verifyNodeInstallSeal");
    expect(scripts["pack:engineering-smoke"]).toContain(
      "electron-builder --dir --mac --arm64 --config electron-builder.smoke.yml --publish never"
    );
    expect(scripts["pack:engineering-smoke"]).not.toMatch(
      /(?:electron\s+\.|start:|open\s)/
    );
  });
});

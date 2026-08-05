import {
  chmod,
  readFile,
  mkdtemp,
  mkdir,
  realpath,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import { createHash } from "node:crypto";
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
  assertNoProductionEnvironment(environment: NodeJS.ProcessEnv): void;
  assertEngineeringSmokeMode(environment: NodeJS.ProcessEnv): void;
  createDistributionManifest(input: JsonObject): JsonObject;
  preflightEngineeringSmoke(options: JsonObject): JsonObject;
  requireSafeGeneratedRoot(generatedRoot: string, desktopRoot: string): void;
  selectedSourceCommit(environment: NodeJS.ProcessEnv): string;
  validateHost(platform: string, architecture: string): void;
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
      packageBytes: 60
    },
    renderer: {
      files: 4,
      bytes: 4096,
      repositoryCommit: "a".repeat(40)
    },
    rendererManifestSha256: "c".repeat(64),
    python: { files: 80, nativeFiles: 12, components: 19 },
    pythonManifest: {
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
  });

  it("runs every initializer preflight before a staging deletion can be reached", () => {
    const inspectRepository = vi.fn(() => ({
      commit: "a".repeat(40),
      tree: "b".repeat(40),
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
      packageBytes: packageBytes.length
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
    expect(() =>
      bundleAudit.assertNoInstallOrReleaseArtifacts(root, appRoot)
    ).not.toThrow();

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

  it("keeps the package command dir-only and compiles the same Main with explicit profiles", async () => {
    const packageMetadata = JSON.parse(
      await readFile(path.join(repositoryRoot, "desktop", "package.json"), "utf8")
    ) as JsonObject;
    const scripts = packageMetadata.scripts as Record<string, string>;
    expect(scripts["build:main"]).toContain("src/main/index.ts");
    expect(scripts["build:main"]).toContain(
      "__LCF_DISTRIBUTION_PROFILE__='\"standard\"'"
    );
    expect(scripts["build:engineering-smoke"]).toContain("src/main/index.ts");
    expect(scripts["build:engineering-smoke"]).toContain(
      "__LCF_DISTRIBUTION_PROFILE__='\"engineering-smoke\"'"
    );
    expect(scripts["pack:engineering-smoke"]).toContain(
      "electron-builder --dir --mac --arm64 --config electron-builder.smoke.yml --publish never"
    );
    expect(scripts["pack:engineering-smoke"]).not.toMatch(
      /(?:electron\s+\.|start:|open\s)/
    );
  });
});

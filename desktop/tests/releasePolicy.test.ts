import { createHash } from "node:crypto";
import {
  mkdir,
  mkdtemp,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";

type JsonObject = Record<string, any>;

const releasePolicy = require("../scripts/prepareRelease.cjs") as {
  compareSemver(left: JsonObject, right: JsonObject): number;
  parseSemver(value: string): JsonObject;
  parseUpdaterMetadata(
    metadataPath: string,
    release: JsonObject,
    zipPath: string
  ): JsonObject;
  validateReleaseManifestShape(
    manifest: JsonObject,
    release: JsonObject,
    updateLock: JsonObject,
    codesignLock: JsonObject
  ): void;
  validateUpdateManifestShape(
    manifest: JsonObject,
    release: JsonObject,
    updateLock: JsonObject
  ): void;
  walkAppPayload(root: string): {
    files: string[];
    symlinks: { path: string; target: string }[];
  };
};
const runtimeReseal = require(
  "../scripts/resealPackagedRuntimes.cjs"
) as {
  resealPackagedRuntimes(
    context: unknown,
    environment: NodeJS.ProcessEnv
  ): { formalRelease: boolean };
};

const roots: string[] = [];
const sha256 = "a".repeat(64);
const release = {
  tag: "v1.2.3-alpha.4",
  version: "1.2.3-alpha.4",
  channel: "alpha",
  commit: "b".repeat(40),
  sourceDateEpoch: 1_700_000_000,
  credentialGenerationId: "d".repeat(32)
};
const updateLock = {
  publicKeySha256: "c".repeat(64),
  credentialGenerationId: "d".repeat(32)
};
const codesignLock = {
  certificateSha256: "e".repeat(64),
  credentialGenerationId: "d".repeat(32)
};

afterEach(async () => {
  await Promise.all(
    roots.splice(0).map((root) =>
      rm(root, { recursive: true, force: true })
    )
  );
});

async function temporaryRoot(prefix: string): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), prefix));
  roots.push(root);
  return root;
}

function releaseAssetNames(): string[] {
  const base = "local-context-forge-1.2.3-alpha.4-arm64";
  return [
    `${base}.dmg`,
    `${base}.zip`,
    `${base}.zip.blockmap`,
    "alpha-mac.yml",
    "update-metadata-ed25519-public.pem",
    "python-sidecar-build-manifest.json",
    "python-sidecar-sbom.spdx.json",
    "qmd-runtime-build-manifest.json",
    "qmd-runtime-sbom.spdx.json",
    "mcp-companion-build-manifest.json",
    "renderer-build-manifest.json",
    "update-manifest.json",
    "update-manifest.json.sig"
  ].sort();
}

function releaseManifest(): JsonObject {
  return {
    schemaVersion: 1,
    kind: "local-context-forge-desktop-release",
    repository: "fredgnr/local-context-forge",
    tag: release.tag,
    version: release.version,
    architecture: "arm64",
    commit: release.commit,
    sourceDateEpoch: release.sourceDateEpoch,
    credentialGenerationId: release.credentialGenerationId,
    codeSigning: {
      identity: "Local Context Forge Self Signed",
      certificateSha256: codesignLock.certificateSha256,
      hardenedRuntime: false,
      notarized: false,
      stapled: false
    },
    automaticApply: {
      enabled: false,
      reason: "VAL-UPDATE-001 physical 0.0.1-to-0.0.2 gate is not passed"
    },
    updateMetadata: {
      manifest: "update-manifest.json",
      signature: "update-manifest.json.sig",
      algorithm: "Ed25519",
      publicKeySha256: updateLock.publicKeySha256
    },
    files: releaseAssetNames().map((name) => ({
      kind: "release-asset",
      name,
      size: 1,
      sha256
    }))
  };
}

function updateManifest(): JsonObject {
  const base = "local-context-forge-1.2.3-alpha.4-arm64";
  return {
    schemaVersion: 1,
    kind: "local-context-forge-desktop-update",
    repository: "fredgnr/local-context-forge",
    channel: "alpha",
    version: release.version,
    architecture: "arm64",
    source: {
      tag: release.tag,
      commit: release.commit,
      sourceDateEpoch: release.sourceDateEpoch
    },
    publicKey: {
      algorithm: "Ed25519",
      sha256: updateLock.publicKeySha256
    },
    assets: [
      { kind: "dmg", name: `${base}.dmg`, size: 1, sha256 },
      {
        kind: "electron-updater-zip",
        name: `${base}.zip`,
        size: 1,
        sha256
      },
      {
        kind: "electron-updater-blockmap",
        name: `${base}.zip.blockmap`,
        size: 1,
        sha256
      },
      {
        kind: "electron-updater-metadata",
        name: "alpha-mac.yml",
        size: 1,
        sha256
      }
    ]
  };
}

describe("desktop release portable policy", () => {
  it("never requires the formal identity for an ordinary build", () => {
    expect(
      runtimeReseal.resealPackagedRuntimes(
        { electronPlatformName: "darwin" },
        {}
      )
    ).toEqual({ formalRelease: false });
  });

  it("compares canonical SemVer without Number precision loss", () => {
    const lower = releasePolicy.parseSemver(
      `${"9".repeat(60)}.0.0-alpha.${"8".repeat(60)}`
    );
    const higher = releasePolicy.parseSemver(
      `1${"0".repeat(60)}.0.0-alpha.${"8".repeat(60)}`
    );
    expect(releasePolicy.compareSemver(lower, higher)).toBeLessThan(0);
    expect(() =>
      releasePolicy.parseSemver(`${"9".repeat(65)}.0.0`)
    ).toThrow(/canonical SemVer/);
    expect(() =>
      releasePolicy.parseSemver("1.2.3-alpha.01")
    ).toThrow(/canonical SemVer/);
  });

  it("accepts ordinary framework symlinks inside Contents", async () => {
    const root = await temporaryRoot("lcf-release-links-");
    const contents = path.join(root, "Contents");
    await mkdir(
      path.join(contents, "Frameworks", "Example.framework", "Versions", "A"),
      { recursive: true }
    );
    await writeFile(
      path.join(
        contents,
        "Frameworks",
        "Example.framework",
        "Versions",
        "A",
        "Example"
      ),
      "fixture"
    );
    await symlink(
      "A",
      path.join(
        contents,
        "Frameworks",
        "Example.framework",
        "Versions",
        "Current"
      )
    );
    await symlink(
      "Versions/Current/Example",
      path.join(contents, "Frameworks", "Example.framework", "Example")
    );

    const payload = releasePolicy.walkAppPayload(contents);
    expect(payload.files).toHaveLength(1);
    expect(payload.symlinks).toHaveLength(2);
  });

  it("rejects escaping, dangling, cyclic, and hard-linked payloads", async () => {
    const escapeRoot = await temporaryRoot("lcf-release-escape-");
    await mkdir(path.join(escapeRoot, "Contents"));
    await writeFile(path.join(escapeRoot, "outside"), "outside");
    await symlink(
      "../outside",
      path.join(escapeRoot, "Contents", "escape")
    );
    expect(() =>
      releasePolicy.walkAppPayload(path.join(escapeRoot, "Contents"))
    ).toThrow(/escapes/);

    const danglingRoot = await temporaryRoot("lcf-release-dangling-");
    await mkdir(path.join(danglingRoot, "Contents"));
    await symlink(
      "missing",
      path.join(danglingRoot, "Contents", "dangling")
    );
    expect(() =>
      releasePolicy.walkAppPayload(path.join(danglingRoot, "Contents"))
    ).toThrow(/dangling or cyclic/);

    const cyclicRoot = await temporaryRoot("lcf-release-cycle-");
    await mkdir(path.join(cyclicRoot, "Contents"));
    await symlink("b", path.join(cyclicRoot, "Contents", "a"));
    await symlink("a", path.join(cyclicRoot, "Contents", "b"));
    expect(() =>
      releasePolicy.walkAppPayload(path.join(cyclicRoot, "Contents"))
    ).toThrow(/dangling or cyclic/);

    const hardLinkRoot = await temporaryRoot("lcf-release-hardlink-");
    await mkdir(path.join(hardLinkRoot, "Contents"));
    const original = path.join(hardLinkRoot, "Contents", "one");
    await writeFile(original, "same inode");
    await import("node:fs/promises").then(({ link }) =>
      link(original, path.join(hardLinkRoot, "Contents", "two"))
    );
    expect(() =>
      releasePolicy.walkAppPayload(path.join(hardLinkRoot, "Contents"))
    ).toThrow(/hard-linked/);
  });

  it("parses only the exact updater metadata shape bound to one ZIP", async () => {
    const root = await temporaryRoot("lcf-updater-yaml-");
    const zipName = "local-context-forge-1.2.3-alpha.4-arm64.zip";
    const zipPath = path.join(root, zipName);
    const metadataPath = path.join(root, "alpha-mac.yml");
    const bytes = Buffer.from("portable ZIP fixture");
    const digest = createHash("sha512").update(bytes).digest("base64");
    await writeFile(zipPath, bytes);
    const metadata = [
      `version: ${release.version}`,
      "files:",
      `  - url: ${zipName}`,
      `    sha512: ${digest}`,
      `    size: ${bytes.length}`,
      `path: ${zipName}`,
      `sha512: ${digest}`,
      "releaseDate: 2026-07-31T00:00:00.000Z",
      ""
    ].join("\n");
    await writeFile(metadataPath, metadata);
    expect(
      releasePolicy.parseUpdaterMetadata(metadataPath, release, zipPath)
    ).toMatchObject({ version: release.version, path: zipName });

    await writeFile(metadataPath, `${metadata}extra: forbidden\n`);
    expect(() =>
      releasePolicy.parseUpdaterMetadata(metadataPath, release, zipPath)
    ).toThrow(/exact shape/);

    await writeFile(
      metadataPath,
      metadata.replace(`url: ${zipName}`, "url: ../escape.zip")
    );
    expect(() =>
      releasePolicy.parseUpdaterMetadata(metadataPath, release, zipPath)
    ).toThrow(/unsafe/);
  });

  it("requires exact, ordered, unique manifest records and safe basenames", () => {
    expect(() =>
      releasePolicy.validateReleaseManifestShape(
        releaseManifest(),
        release,
        updateLock,
        codesignLock
      )
    ).not.toThrow();
    expect(() =>
      releasePolicy.validateUpdateManifestShape(
        updateManifest(),
        release,
        updateLock
      )
    ).not.toThrow();

    const extra = releaseManifest();
    extra.unreviewed = true;
    expect(() =>
      releasePolicy.validateReleaseManifestShape(
        extra,
        release,
        updateLock,
        codesignLock
      )
    ).toThrow(/incomplete or unsafe/);

    const unsafe = releaseManifest();
    unsafe.files[0].name = "../escape.dmg";
    expect(() =>
      releasePolicy.validateReleaseManifestShape(
        unsafe,
        release,
        updateLock,
        codesignLock
      )
    ).toThrow(/unsafe/);

    const duplicate = updateManifest();
    duplicate.assets[1] = { ...duplicate.assets[0] };
    expect(() =>
      releasePolicy.validateUpdateManifestShape(
        duplicate,
        release,
        updateLock
      )
    ).toThrow(/malformed|membership/);
  });
});

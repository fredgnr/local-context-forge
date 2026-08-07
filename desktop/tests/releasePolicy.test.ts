import { createHash } from "node:crypto";
import { execFileSync, spawnSync } from "node:child_process";
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
  verifyGitHubRelease(options: {
    tag: string;
    assetDirectory: string;
    releaseJsonPath: string;
    expectedState: "draft" | "published";
    releaseNotesPath: string;
    candidateManifestSha256?: string;
  }): JsonObject;
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

interface GitHubReleaseFixture {
  assetDirectory: string;
  releaseJsonPath: string;
  releaseNotesPath: string;
  manifestSha256: string;
  remote: JsonObject;
}

function cloneJson(value: JsonObject): JsonObject {
  return JSON.parse(JSON.stringify(value)) as JsonObject;
}

function sha256Bytes(value: string | Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

function githubAssetUrl(tag: string, name: string): string {
  return (
    "https://github.com/fredgnr/local-context-forge/releases/download/" +
    `${encodeURIComponent(tag)}/${encodeURIComponent(name)}`
  );
}

async function githubReleaseFixture(): Promise<GitHubReleaseFixture> {
  const root = await temporaryRoot("lcf-github-release-");
  const assetDirectory = path.join(root, "assets");
  const releaseJsonPath = path.join(root, "release.json");
  const releaseNotesPath = path.join(root, "release-notes.md");
  const notes = [
    "Local Context Forge desktop release.",
    "",
    "Self-signed, not notarized, and automatic apply remains disabled.",
    ""
  ].join("\n");
  const files = new Map<string, Buffer>([
    [
      "release-manifest.json",
      Buffer.from('{"kind":"test-release-manifest"}\n')
    ],
    ["SHA256SUMS", Buffer.from("reviewed checksums\n")],
    [
      "local-context-forge-1.2.3-alpha.4-arm64.dmg",
      Buffer.from("reviewed dmg bytes")
    ]
  ]);
  await mkdir(assetDirectory);
  await writeFile(releaseNotesPath, notes);
  for (const [name, bytes] of files) {
    await writeFile(path.join(assetDirectory, name), bytes);
  }
  const assets = [...files.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([name, bytes], index) => ({
      id: 10_000 + index,
      name,
      state: "uploaded",
      size: bytes.length,
      digest: `sha256:${sha256Bytes(bytes)}`,
      browser_download_url: githubAssetUrl(release.tag, name)
    }));
  const remote = {
    id: 9_001,
    tag_name: release.tag,
    name: `Local Context Forge ${release.tag}`,
    draft: true,
    immutable: false,
    prerelease: true,
    published_at: null,
    body: notes,
    assets
  };
  await writeFile(releaseJsonPath, JSON.stringify(remote));
  return {
    assetDirectory,
    releaseJsonPath,
    releaseNotesPath,
    manifestSha256: sha256Bytes(files.get("release-manifest.json")!),
    remote
  };
}

async function writeRemoteRelease(
  fixture: GitHubReleaseFixture,
  remote: JsonObject
): Promise<void> {
  await writeFile(fixture.releaseJsonPath, JSON.stringify(remote));
}

function verifyRemoteOptions(
  fixture: GitHubReleaseFixture,
  overrides: Partial<{
    expectedState: "draft" | "published";
    candidateManifestSha256: string | undefined;
  }> = {}
): {
  tag: string;
  assetDirectory: string;
  releaseJsonPath: string;
  expectedState: "draft" | "published";
  releaseNotesPath: string;
  candidateManifestSha256?: string;
} {
  return {
    tag: release.tag,
    assetDirectory: fixture.assetDirectory,
    releaseJsonPath: fixture.releaseJsonPath,
    expectedState: overrides.expectedState ?? "draft",
    releaseNotesPath: fixture.releaseNotesPath,
    ...(overrides.candidateManifestSha256 === undefined
      ? {}
      : {
          candidateManifestSha256:
            overrides.candidateManifestSha256
        })
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
    expect(
      releasePolicy.parseSemver("1.2.3+reviewed-build-with-hyphen")
        .prerelease
    ).toEqual([]);
  });

  it("keeps the trusted verifier while binding the reviewed renderer lock", async () => {
    const sourceRoot = await temporaryRoot("lcf-release-source-");
    const lockPath = path.join(sourceRoot, "web", "package-lock.json");
    await mkdir(path.dirname(lockPath), { recursive: true });
    await writeFile(lockPath, "tag-specific-lock\n");
    execFileSync("/usr/bin/git", ["init", "--quiet", sourceRoot]);
    const script = path.resolve(
      __dirname,
      "../scripts/prepareRelease.cjs"
    );
    const output = execFileSync(
      process.execPath,
      [
        "-e",
        [
          "const policy=require(process.argv[1]);",
          "policy.configureRepositoryRoot(process.argv[2]);",
          "const options=policy.packagedRendererAuditOptions({",
          "commit:'b'.repeat(40),sourceDateEpoch:1700000000},{",
          "LCF_SOURCE_TREE:'c'.repeat(40),",
          "LCF_SOURCE_SNAPSHOT_SHA256:'d'.repeat(64),",
          "LCF_RENDERER_PACKAGE_LOCK_SHA256:'e'.repeat(64)});",
          "process.stdout.write(JSON.stringify({",
          "commit:options.expectedCommit,",
          "tree:options.expectedTree,",
          "snapshot:options.expectedSourceSnapshotSha256,",
          "packageLock:options.expectedPackageLockSha256,",
          "epoch:options.expectedSourceDateEpoch",
          "}));"
        ].join(""),
        script,
        sourceRoot
      ],
      { encoding: "utf8" }
    );
    expect(JSON.parse(output)).toEqual({
      commit: "b".repeat(40),
      tree: "c".repeat(40),
      snapshot: "d".repeat(64),
      packageLock: "e".repeat(64),
      epoch: 1_700_000_000
    });
  });

  it("rejects a stale Draft after a newer reachable release tag exists", async () => {
    const sourceRoot = await temporaryRoot("lcf-release-order-");
    const sourceFile = path.join(sourceRoot, "release-source.txt");
    execFileSync("/usr/bin/git", ["init", "--quiet", sourceRoot]);
    execFileSync("/usr/bin/git", [
      "-C",
      sourceRoot,
      "config",
      "user.name",
      "Release Test"
    ]);
    execFileSync("/usr/bin/git", [
      "-C",
      sourceRoot,
      "config",
      "user.email",
      "release-test@example.invalid"
    ]);
    await writeFile(sourceFile, "v1.2.0\n");
    execFileSync("/usr/bin/git", ["-C", sourceRoot, "add", "."]);
    execFileSync("/usr/bin/git", [
      "-C",
      sourceRoot,
      "commit",
      "--quiet",
      "-m",
      "v1.2.0"
    ]);
    execFileSync("/usr/bin/git", [
      "-C",
      sourceRoot,
      "tag",
      "v1.2.0"
    ]);
    const olderCommit = execFileSync(
      "/usr/bin/git",
      ["-C", sourceRoot, "rev-parse", "HEAD"],
      { encoding: "utf8" }
    ).trim();
    await writeFile(sourceFile, "v1.3.0\n");
    execFileSync("/usr/bin/git", ["-C", sourceRoot, "add", "."]);
    execFileSync("/usr/bin/git", [
      "-C",
      sourceRoot,
      "commit",
      "--quiet",
      "-m",
      "v1.3.0"
    ]);
    execFileSync("/usr/bin/git", [
      "-C",
      sourceRoot,
      "tag",
      "v1.3.0"
    ]);
    const latestCommit = execFileSync(
      "/usr/bin/git",
      ["-C", sourceRoot, "rev-parse", "HEAD"],
      { encoding: "utf8" }
    ).trim();
    const script = path.resolve(
      __dirname,
      "../scripts/prepareRelease.cjs"
    );
    const evaluate = [
      "const policy=require(process.argv[1]);",
      "policy.configureRepositoryRoot(process.argv[2]);",
      "process.stdout.write(JSON.stringify(",
      "policy.verifyPromotionOrder(",
      "process.argv[3],process.argv[4],process.argv[5])",
      "));"
    ].join("");
    const fixtureEnvironment = { ...process.env };
    delete fixtureEnvironment.GITHUB_SHA;

    execFileSync("/usr/bin/git", [
      "-C",
      sourceRoot,
      "checkout",
      "--quiet",
      olderCommit
    ]);
    const stale = spawnSync(
      process.execPath,
      [
        "-e",
        evaluate,
        script,
        sourceRoot,
        "v1.2.0",
        olderCommit,
        latestCommit
      ],
      { encoding: "utf8", env: fixtureEnvironment }
    );
    expect(stale.status).not.toBe(0);
    expect(stale.stderr).toContain(
      "A newer or equal release tag supersedes this Draft"
    );
    execFileSync("/usr/bin/git", [
      "-C",
      sourceRoot,
      "checkout",
      "--quiet",
      latestCommit
    ]);
    const latest = JSON.parse(
      execFileSync(
        process.execPath,
        [
          "-e",
          evaluate,
          script,
          sourceRoot,
          "v1.3.0",
          latestCommit,
          latestCommit
        ],
        { encoding: "utf8", env: fixtureEnvironment }
      )
    );
    expect(latest).toMatchObject({
      tag: "v1.3.0",
      commit: latestCommit,
      policyCommit: latestCommit,
      mainCommit: latestCommit,
      prerelease: false,
      makeLatest: "true"
    });
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

  it("verifies a strict draft release and exposes the candidate digest", async () => {
    const fixture = await githubReleaseFixture();
    expect(
      releasePolicy.verifyGitHubRelease(verifyRemoteOptions(fixture))
    ).toEqual({
      id: 9_001,
      tag: release.tag,
      state: "draft",
      prerelease: true,
      assets: 3,
      releaseManifestSha256: fixture.manifestSha256
    });
    expect(
      releasePolicy.verifyGitHubRelease(
        verifyRemoteOptions(fixture, {
          candidateManifestSha256: fixture.manifestSha256
        })
      )
    ).toMatchObject({ state: "draft" });
    expect(() =>
      releasePolicy.verifyGitHubRelease(
        verifyRemoteOptions(fixture, {
          candidateManifestSha256: "0".repeat(64)
        })
      )
    ).toThrow(/does not match/);
  });

  it("supports the verify-github-release CLI contract", async () => {
    const fixture = await githubReleaseFixture();
    const output = execFileSync(
      process.execPath,
      [
        path.resolve(__dirname, "../scripts/prepareRelease.cjs"),
        "verify-github-release",
        "--tag",
        release.tag,
        "--asset-dir",
        fixture.assetDirectory,
        "--release-json",
        fixture.releaseJsonPath,
        "--expected-state",
        "draft",
        "--release-notes",
        fixture.releaseNotesPath
      ],
      { encoding: "utf8" }
    );
    expect(JSON.parse(output)).toMatchObject({
      id: 9_001,
      state: "draft",
      releaseManifestSha256: fixture.manifestSha256
    });
  });

  it("requires the exact candidate manifest digest for published verification", async () => {
    const fixture = await githubReleaseFixture();
    const published = cloneJson(fixture.remote);
    published.draft = false;
    published.immutable = true;
    published.published_at = "2026-07-31T12:34:56Z";
    await writeRemoteRelease(fixture, published);

    expect(() =>
      releasePolicy.verifyGitHubRelease(
        verifyRemoteOptions(fixture, { expectedState: "published" })
      )
    ).toThrow(/requires a candidate manifest SHA-256/);
    expect(() =>
      releasePolicy.verifyGitHubRelease(
        verifyRemoteOptions(fixture, {
          expectedState: "published",
          candidateManifestSha256: "f".repeat(64)
        })
      )
    ).toThrow(/does not match/);
    expect(
      releasePolicy.verifyGitHubRelease(
        verifyRemoteOptions(fixture, {
          expectedState: "published",
          candidateManifestSha256: fixture.manifestSha256
        })
      )
    ).toMatchObject({ state: "published" });
  });

  it("rejects wrong release id, tag, title, and notes", async () => {
    const fixture = await githubReleaseFixture();
    const cases: Array<{
      mutate(remote: JsonObject): void;
      message: RegExp;
    }> = [
      {
        mutate: (remote) => {
          remote.id = 0;
        },
        message: /positive safe integer/
      },
      {
        mutate: (remote) => {
          remote.id = 1.5;
        },
        message: /positive safe integer/
      },
      {
        mutate: (remote) => {
          remote.tag_name = "v1.2.3-alpha.5";
        },
        message: /tag or title/
      },
      {
        mutate: (remote) => {
          remote.name = "Unreviewed title";
        },
        message: /tag or title/
      },
      {
        mutate: (remote) => {
          remote.body = `${remote.body}unreviewed`;
        },
        message: /reviewed notes/
      }
    ];
    for (const testCase of cases) {
      const remote = cloneJson(fixture.remote);
      testCase.mutate(remote);
      await writeRemoteRelease(fixture, remote);
      expect(() =>
        releasePolicy.verifyGitHubRelease(verifyRemoteOptions(fixture))
      ).toThrow(testCase.message);
    }
  });

  it("rejects wrong state, prerelease, and published_at combinations", async () => {
    const fixture = await githubReleaseFixture();
    const wrongDraftState = cloneJson(fixture.remote);
    wrongDraftState.draft = false;
    await writeRemoteRelease(fixture, wrongDraftState);
    expect(() =>
      releasePolicy.verifyGitHubRelease(verifyRemoteOptions(fixture))
    ).toThrow(/state differs/);

    const mutablePublished = cloneJson(fixture.remote);
    mutablePublished.draft = false;
    mutablePublished.published_at = "2026-07-31T12:34:56Z";
    await writeRemoteRelease(fixture, mutablePublished);
    expect(() =>
      releasePolicy.verifyGitHubRelease(
        verifyRemoteOptions(fixture, {
          expectedState: "published",
          candidateManifestSha256: fixture.manifestSha256
        })
      )
    ).toThrow(/state differs/);

    const wrongPrerelease = cloneJson(fixture.remote);
    wrongPrerelease.prerelease = false;
    await writeRemoteRelease(fixture, wrongPrerelease);
    expect(() =>
      releasePolicy.verifyGitHubRelease(verifyRemoteOptions(fixture))
    ).toThrow(/prerelease state/);

    const timestampedDraft = cloneJson(fixture.remote);
    timestampedDraft.published_at = "2026-07-31T12:34:56Z";
    await writeRemoteRelease(fixture, timestampedDraft);
    expect(() =>
      releasePolicy.verifyGitHubRelease(verifyRemoteOptions(fixture))
    ).toThrow(/published_at/);

    for (const invalid of [
      null,
      "not-a-date",
      "2026-02-30T12:34:56Z",
      "2026-07-31T12:34:56+01:00"
    ]) {
      const published = cloneJson(fixture.remote);
      published.draft = false;
      published.immutable = true;
      published.published_at = invalid;
      await writeRemoteRelease(fixture, published);
      expect(() =>
        releasePolicy.verifyGitHubRelease(
          verifyRemoteOptions(fixture, {
            expectedState: "published",
            candidateManifestSha256: fixture.manifestSha256
          })
        )
      ).toThrow(/published_at/);
    }
  });

  it("rejects missing, extra, and duplicate remote assets", async () => {
    const fixture = await githubReleaseFixture();

    const missing = cloneJson(fixture.remote);
    missing.assets.pop();
    await writeRemoteRelease(fixture, missing);
    expect(() =>
      releasePolicy.verifyGitHubRelease(verifyRemoteOptions(fixture))
    ).toThrow(/asset set differs/);

    const extra = cloneJson(fixture.remote);
    extra.assets.push({
      name: "unexpected.bin",
      state: "uploaded",
      size: 1,
      digest: `sha256:${"a".repeat(64)}`,
      browser_download_url: githubAssetUrl(
        release.tag,
        "unexpected.bin"
      )
    });
    await writeRemoteRelease(fixture, extra);
    expect(() =>
      releasePolicy.verifyGitHubRelease(verifyRemoteOptions(fixture))
    ).toThrow(/unexpected asset/);

    const duplicate = cloneJson(fixture.remote);
    duplicate.assets[1] = cloneJson(duplicate.assets[0]);
    await writeRemoteRelease(fixture, duplicate);
    expect(() =>
      releasePolicy.verifyGitHubRelease(verifyRemoteOptions(fixture))
    ).toThrow(/duplicate asset/);
  });

  it("rejects remote asset state, size, digest, and canonical URL drift", async () => {
    const fixture = await githubReleaseFixture();
    const cases: Array<(remote: JsonObject) => void> = [
      (remote) => {
        remote.assets[0].state = "new";
      },
      (remote) => {
        remote.assets[0].size += 1;
      },
      (remote) => {
        remote.assets[0].digest = `sha256:${"0".repeat(64)}`;
      },
      (remote) => {
        remote.assets[0].browser_download_url += "?redirect=1";
      }
    ];
    for (const mutate of cases) {
      const remote = cloneJson(fixture.remote);
      mutate(remote);
      await writeRemoteRelease(fixture, remote);
      expect(() =>
        releasePolicy.verifyGitHubRelease(verifyRemoteOptions(fixture))
      ).toThrow(/state, size, digest, or URL/);
    }
  });

  it("rejects local symlinks and unsafe asset names", async () => {
    const unsafeFixture = await githubReleaseFixture();
    await writeFile(
      path.join(unsafeFixture.assetDirectory, "unsafe\\asset"),
      "unsafe"
    );
    expect(() =>
      releasePolicy.verifyGitHubRelease(
        verifyRemoteOptions(unsafeFixture)
      )
    ).toThrow(/name is unsafe/);

    const symlinkFixture = await githubReleaseFixture();
    const dmgName = "local-context-forge-1.2.3-alpha.4-arm64.dmg";
    await rm(path.join(symlinkFixture.assetDirectory, dmgName));
    await symlink(
      "release-manifest.json",
      path.join(symlinkFixture.assetDirectory, dmgName)
    );
    expect(() =>
      releasePolicy.verifyGitHubRelease(
        verifyRemoteOptions(symlinkFixture)
      )
    ).toThrow(/bounded, unlinked regular file/);
  });
});

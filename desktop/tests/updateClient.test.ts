import {
  createHash,
  generateKeyPairSync,
  sign,
  type KeyObject
} from "node:crypto";
import {
  link,
  lstat,
  mkdtemp,
  readFile,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CANONICAL_RELEASES_URL,
  MAX_DMG_BYTES,
  UpdateClient,
  UpdateClientError,
  canonicalJson,
  compareSemver,
  contentLength,
  parseSemver,
  validateNetworkUrl,
  type UpdateClientOptions,
  type UpdateFetchBytes,
  type UpdateStreamAsset,
  type UpdateTrustAnchor
} from "../src/main/updateClient";

interface ReleaseFixture {
  readonly trustAnchor: UpdateTrustAnchor;
  readonly metadata: Buffer;
  readonly manifest: Buffer;
  readonly signature: Buffer;
  readonly dmg: Buffer;
  readonly version: string;
  readonly tag: string;
  readonly channel: string;
  readonly dmgName: string;
}

const roots: string[] = [];

function assetUrl(tag: string, name: string): string {
  return (
    "https://github.com/fredgnr/local-context-forge/releases/download/" +
    `${encodeURIComponent(tag)}/${encodeURIComponent(name)}`
  );
}

function releaseFixture(options: {
  version?: string;
  channel?: string;
  dmg?: Buffer;
  privateKey?: KeyObject;
  publicKey?: KeyObject;
  mutateManifest?: (manifest: Record<string, any>) => void;
  tamperSignature?: boolean;
  extraReleases?: Record<string, unknown>[];
} = {}): ReleaseFixture {
  const version = options.version ?? "1.1.0";
  const channel = options.channel ?? "latest";
  const tag = `v${version}`;
  const pair =
    options.privateKey && options.publicKey
      ? {
          privateKey: options.privateKey,
          publicKey: options.publicKey
        }
      : generateKeyPairSync("ed25519");
  const publicKeyBytes = pair.publicKey.export({
    format: "pem",
    type: "spki"
  }) as Buffer;
  const publicKeySha256 = createHash("sha256")
    .update(publicKeyBytes)
    .digest("hex");
  const dmg = options.dmg ?? Buffer.from("verified fixture dmg\n");
  const base = `local-context-forge-${version}-arm64`;
  const dmgName = `${base}.dmg`;
  const manifest: Record<string, any> = {
    schemaVersion: 1,
    kind: "local-context-forge-desktop-update",
    repository: "fredgnr/local-context-forge",
    channel,
    version,
    architecture: "arm64",
    source: {
      tag,
      commit: "a".repeat(40),
      sourceDateEpoch: 1_800_000_000
    },
    publicKey: {
      algorithm: "Ed25519",
      sha256: publicKeySha256
    },
    assets: [
      {
        kind: "dmg",
        name: dmgName,
        size: dmg.length,
        sha256: createHash("sha256").update(dmg).digest("hex")
      },
      {
        kind: "electron-updater-zip",
        name: `${base}.zip`,
        size: 123,
        sha256: "b".repeat(64)
      },
      {
        kind: "electron-updater-blockmap",
        name: `${base}.zip.blockmap`,
        size: 42,
        sha256: "c".repeat(64)
      },
      {
        kind: "electron-updater-metadata",
        name: `${channel}-mac.yml`,
        size: 99,
        sha256: "d".repeat(64)
      }
    ]
  };
  options.mutateManifest?.(manifest);
  const manifestBytes = Buffer.from(`${canonicalJson(manifest)}\n`);
  const signature = sign(null, manifestBytes, pair.privateKey);
  if (options.tamperSignature) {
    signature[0] = (signature[0] ?? 0) ^ 0xff;
  }
  const release = {
    tag_name: tag,
    draft: false,
    prerelease: version.includes("-"),
    assets: [
      {
        name: "update-manifest.json",
        size: manifestBytes.length,
        browser_download_url: assetUrl(tag, "update-manifest.json")
      },
      {
        name: "update-manifest.json.sig",
        size: signature.length,
        browser_download_url: assetUrl(tag, "update-manifest.json.sig")
      },
      {
        name: dmgName,
        size: dmg.length,
        browser_download_url: assetUrl(tag, dmgName)
      }
    ]
  };
  const metadataValue = options.extraReleases
    ? [...options.extraReleases, release]
    : release;
  return {
    trustAnchor: {
      publicKey: pair.publicKey,
      publicKeySha256
    },
    metadata: Buffer.from(JSON.stringify(metadataValue)),
    manifest: manifestBytes,
    signature,
    dmg,
    version,
    tag,
    channel,
    dmgName
  };
}

async function createClient(
  fixture: ReleaseFixture,
  overrides: Partial<UpdateClientOptions> = {}
): Promise<{
  client: UpdateClient;
  updateDirectory: string;
  opened: string[];
  external: string[];
  fetchBytes: ReturnType<typeof vi.fn<UpdateFetchBytes>>;
  streamAsset: ReturnType<typeof vi.fn<UpdateStreamAsset>>;
}> {
  const root = await mkdtemp(path.join(os.tmpdir(), "lcf-update-client-"));
  roots.push(root);
  const updateDirectory = path.join(root, "updates");
  const opened: string[] = [];
  const external: string[] = [];
  const fetchBytes = vi.fn<UpdateFetchBytes>(
    async (url, request) => {
      if (request.signal.aborted) {
        throw new UpdateClientError("cancelled");
      }
      if (url.includes("api.github.com")) {
        return fixture.metadata;
      }
      if (url.endsWith("update-manifest.json.sig")) {
        return fixture.signature;
      }
      if (url.endsWith("update-manifest.json")) {
        return fixture.manifest;
      }
      throw new UpdateClientError("network");
    }
  );
  const streamAsset = vi.fn<UpdateStreamAsset>(
    async (_url, request) => {
      await request.onChunk(fixture.dmg);
    }
  );
  const client = await UpdateClient.create({
    packaged: true,
    platform: "darwin",
    architecture: "arm64",
    currentVersion: "1.0.0",
    resourcesPath: path.join(root, "resources"),
    updateDirectory,
    openPath: async (filePath) => {
      opened.push(filePath);
      return "";
    },
    openExternal: async (url) => {
      external.push(url);
    },
    loadTrustAnchor: async () => fixture.trustAnchor,
    fetchBytes,
    streamAsset,
    ...overrides
  });
  return {
    client,
    updateDirectory,
    opened,
    external,
    fetchBytes,
    streamAsset
  };
}

afterEach(async () => {
  await Promise.all(
    roots
      .splice(0)
      .map((root) => rm(root, { recursive: true, force: true }))
  );
  vi.restoreAllMocks();
});

describe("Main-owned signed update client", () => {
  it("keeps signed updates unavailable but permits only the fixed manual release fallback", async () => {
    const fixture = releaseFixture();
    const base = await createClient(fixture, {
      packaged: false
    });
    expect(base.client.getStatus()).toMatchObject({
      state: "unavailable",
      unavailableReason: "source-build",
      automaticApply: false,
      automaticApplyReason: "val-update-001-not-passed",
      canCheck: false,
      canDownloadOrOpen: false,
      canOpenReleasePage: true
    });
    await expect(base.client.check()).rejects.toMatchObject({
      code: "unavailable"
    });
    await expect(base.client.downloadOrOpen()).rejects.toMatchObject({
      code: "unavailable"
    });
    expect(base.fetchBytes).not.toHaveBeenCalled();
    expect(base.streamAsset).not.toHaveBeenCalled();
    expect(base.opened).toEqual([]);
    expect(base.external).toEqual([]);
    await expect(base.client.openReleasePage()).resolves.toMatchObject({
      state: "unavailable",
      canCheck: false,
      canDownloadOrOpen: false,
      canOpenReleasePage: true,
      automaticApply: false
    });
    expect(base.external).toEqual([CANONICAL_RELEASES_URL]);
    await expect(base.client.downloadOrOpen()).rejects.toMatchObject({
      code: "unavailable"
    });

    const unsupported = await createClient(fixture, {
      platform: "linux"
    });
    expect(unsupported.client.getStatus()).toMatchObject({
      unavailableReason: "unsupported-platform",
      canCheck: false,
      canDownloadOrOpen: false,
      canOpenReleasePage: true,
      automaticApply: false
    });
    await unsupported.client.openReleasePage();
    expect(unsupported.external).toEqual([CANONICAL_RELEASES_URL]);

    const invalidVersion = await createClient(fixture, {
      currentVersion:
        "999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999"
    });
    expect(invalidVersion.client.getStatus()).toMatchObject({
      state: "unavailable",
      currentVersion: "0.0.0",
      unavailableReason: "version-invalid",
      canOpenReleasePage: true
    });
    expect(invalidVersion.fetchBytes).not.toHaveBeenCalled();
    await invalidVersion.client.openReleasePage();
    expect(invalidVersion.external).toEqual([CANONICAL_RELEASES_URL]);

    const unprovisioned = await createClient(fixture, {
      loadTrustAnchor: async () => {
        throw new UpdateClientError("unavailable");
      }
    });
    expect(unprovisioned.client.getStatus()).toMatchObject({
      unavailableReason: "key-unprovisioned",
      canCheck: false,
      canDownloadOrOpen: false,
      canOpenReleasePage: true,
      automaticApply: false
    });
    expect(unprovisioned.fetchBytes).not.toHaveBeenCalled();
    await unprovisioned.client.openReleasePage();
    expect(unprovisioned.external).toEqual([CANONICAL_RELEASES_URL]);

    const fallbackFailure = await createClient(fixture, {
      packaged: false,
      openExternal: async () => {
        throw new Error("browser unavailable");
      }
    });
    await expect(
      fallbackFailure.client.openReleasePage()
    ).rejects.toMatchObject({ code: "external-open-failed" });
    expect(fallbackFailure.client.getStatus()).toMatchObject({
      state: "unavailable",
      unavailableReason: "source-build",
      canCheck: false,
      canDownloadOrOpen: false,
      canOpenReleasePage: true,
      automaticApply: false
    });
    expect(fallbackFailure.fetchBytes).not.toHaveBeenCalled();
  });

  it("preserves signed-update status when opening the fixed release page fails and then succeeds", async () => {
    const fixture = releaseFixture();
    let attempts = 0;
    const value = await createClient(fixture, {
      packaged: false,
      openExternal: async (url) => {
        attempts += 1;
        expect(url).toBe(
          "https://github.com/fredgnr/local-context-forge/releases"
        );
        if (attempts === 1) {
          throw new Error("browser unavailable");
        }
      }
    });
    const before = value.client.getStatus();

    await expect(value.client.openReleasePage()).rejects.toMatchObject({
      code: "external-open-failed"
    });
    expect(value.client.getStatus()).toEqual(before);
    await expect(value.client.openReleasePage()).resolves.toEqual(before);
    expect(value.client.getStatus()).toEqual(before);
    expect(attempts).toBe(2);
  });

  it("verifies canonical signed metadata, downloads only the DMG, and opens it after revalidation", async () => {
    const fixture = releaseFixture();
    const value = await createClient(fixture);
    const statuses: unknown[] = [];
    value.client.subscribe((status) => statuses.push(status));

    await expect(value.client.check()).resolves.toMatchObject({
      state: "available",
      availableVersion: "1.1.0",
      canDownloadOrOpen: true
    });
    await expect(value.client.downloadOrOpen()).resolves.toMatchObject({
      state: "opened",
      availableVersion: "1.1.0"
    });

    expect(value.streamAsset).toHaveBeenCalledTimes(1);
    const streamedUrl = value.streamAsset.mock.calls[0]?.[0] ?? "";
    expect(streamedUrl).toBe(assetUrl(fixture.tag, fixture.dmgName));
    expect(streamedUrl).not.toMatch(/\.zip(?:\?|$)/);
    expect(value.opened).toHaveLength(1);
    expect(await readFile(value.opened[0] as string)).toEqual(fixture.dmg);
    expect((await lstat(value.opened[0] as string)).nlink).toBe(1);
    expect(
      JSON.stringify(statuses)
    ).not.toMatch(/github\.com|update-manifest|\.partial|\/tmp\//);

    await expect(value.client.downloadOrOpen()).resolves.toMatchObject({
      state: "opened"
    });
    expect(value.streamAsset).toHaveBeenCalledTimes(1);
    expect(value.opened).toHaveLength(2);
  });

  it("replaces only a private single-link cache entry whose hash is stale", async () => {
    const fixture = releaseFixture();
    const value = await createClient(fixture);
    await value.client.check();
    await import("node:fs/promises").then(({ mkdir }) =>
      mkdir(value.updateDirectory, { recursive: true, mode: 0o700 })
    );
    const cached = path.join(value.updateDirectory, fixture.dmgName);
    await writeFile(cached, Buffer.alloc(fixture.dmg.length, 0x78), {
      mode: 0o600
    });

    await value.client.downloadOrOpen();

    expect(await readFile(cached)).toEqual(fixture.dmg);
    expect(value.streamAsset).toHaveBeenCalledTimes(1);
    expect((await lstat(cached)).nlink).toBe(1);
  });

  it("rejects signature, canonical-shape, digest, and same/downgrade replay failures without opening", async () => {
    const checkFailureFixture = releaseFixture();
    const checkFailureClient = await createClient(checkFailureFixture, {
      fetchBytes: async () => {
        throw new UpdateClientError("network");
      }
    });
    await expect(checkFailureClient.client.check()).rejects.toMatchObject({
      code: "network"
    });
    expect(checkFailureClient.client.getStatus()).toMatchObject({
      state: "error",
      errorCode: "network",
      canDownloadOrOpen: false,
      canOpenReleasePage: true,
      automaticApply: false
    });
    expect(checkFailureClient.streamAsset).not.toHaveBeenCalled();
    expect(checkFailureClient.opened).toEqual([]);
    expect(checkFailureClient.external).toEqual([]);
    await checkFailureClient.client.openReleasePage();
    expect(checkFailureClient.external).toEqual([CANONICAL_RELEASES_URL]);
    await expect(
      checkFailureClient.client.downloadOrOpen()
    ).rejects.toMatchObject({ code: "asset-invalid" });

    const badSignature = releaseFixture({ tamperSignature: true });
    const signatureClient = await createClient(badSignature);
    await expect(signatureClient.client.check()).rejects.toMatchObject({
      code: "signature-invalid"
    });
    expect(signatureClient.client.getStatus()).toMatchObject({
      state: "error",
      errorCode: "signature-invalid",
      canDownloadOrOpen: false,
      canOpenReleasePage: true,
      automaticApply: false
    });
    expect(signatureClient.opened).toEqual([]);
    expect(signatureClient.external).toEqual([]);
    await signatureClient.client.openReleasePage();
    expect(signatureClient.external).toEqual([CANONICAL_RELEASES_URL]);
    await expect(
      signatureClient.client.downloadOrOpen()
    ).rejects.toMatchObject({ code: "asset-invalid" });

    const extraKey = releaseFixture({
      mutateManifest: (manifest) => {
        manifest.unreviewed = true;
      }
    });
    const shapeClient = await createClient(extraKey);
    await expect(shapeClient.client.check()).rejects.toMatchObject({
      code: "manifest-invalid"
    });

    const digestFixture = releaseFixture();
    const digestClient = await createClient(digestFixture, {
      streamAsset: async (_url, request) => {
        await request.onChunk(Buffer.from("wrong bytes"));
      }
    });
    await digestClient.client.check();
    await expect(
      digestClient.client.downloadOrOpen()
    ).rejects.toMatchObject({ code: "digest-mismatch" });
    expect(digestClient.opened).toEqual([]);
    await expect(
      lstat(path.join(digestClient.updateDirectory, `${digestFixture.dmgName}.partial`))
    ).rejects.toMatchObject({ code: "ENOENT" });

    for (const version of ["1.0.0", "0.9.9"]) {
      const replay = releaseFixture({ version });
      const replayClient = await createClient(replay);
      await expect(replayClient.client.check()).resolves.toMatchObject({
        state: "up-to-date",
        availableVersion: null
      });
      await expect(
        replayClient.client.downloadOrOpen()
      ).rejects.toMatchObject({ code: "asset-invalid" });
    }
  });

  it("keeps stable and prerelease channels isolated", async () => {
    const stableRelease = {
      tag_name: "v9.0.0",
      draft: false,
      prerelease: false,
      assets: []
    };
    const alpha = releaseFixture({
      version: "1.0.0-alpha.2",
      channel: "alpha",
      extraReleases: [stableRelease]
    });
    const alphaClient = await createClient(alpha, {
      currentVersion: "1.0.0-alpha.1"
    });
    await expect(alphaClient.client.check()).resolves.toMatchObject({
      state: "available",
      channel: "alpha",
      availableVersion: "1.0.0-alpha.2"
    });

    const beta = releaseFixture({
      version: "1.0.0-beta.2",
      channel: "beta",
      extraReleases: []
    });
    const wrongChannelClient = await createClient(beta, {
      currentVersion: "1.0.0-alpha.1"
    });
    await expect(wrongChannelClient.client.check()).rejects.toMatchObject({
      code: "channel-mismatch"
    });

    const stableList = releaseFixture({ extraReleases: [] });
    const stableListClient = await createClient(stableList);
    await expect(stableListClient.client.check()).rejects.toMatchObject({
      code: "metadata-invalid"
    });

    const prereleaseObject = releaseFixture({
      version: "1.0.0-alpha.2",
      channel: "alpha"
    });
    const prereleaseObjectClient = await createClient(prereleaseObject, {
      currentVersion: "1.0.0-alpha.1"
    });
    await expect(prereleaseObjectClient.client.check()).rejects.toMatchObject({
      code: "metadata-invalid"
    });
  });

  it("deduplicates equal operations and rejects conflicting concurrency", async () => {
    const fixture = releaseFixture();
    let releaseMetadata!: (value: Buffer) => void;
    const metadata = new Promise<Buffer>((resolve) => {
      releaseMetadata = resolve;
    });
    const base = await createClient(fixture, {
      fetchBytes: async (url) => {
        if (url.includes("api.github.com")) {
          return metadata;
        }
        return url.endsWith(".sig") ? fixture.signature : fixture.manifest;
      }
    });
    const first = base.client.check();
    const duplicate = base.client.check();
    expect(duplicate).toBe(first);
    await expect(base.client.downloadOrOpen()).rejects.toMatchObject({
      code: "busy"
    });
    releaseMetadata(fixture.metadata);
    await first;

    let releaseDownload!: () => void;
    const downloadGate = new Promise<void>((resolve) => {
      releaseDownload = resolve;
    });
    const streamMock = vi.fn<UpdateStreamAsset>(
      async (_url, request) => {
        await request.onChunk(fixture.dmg.subarray(0, 4));
        await downloadGate;
        await request.onChunk(fixture.dmg.subarray(4));
      }
    );
    const download = await createClient(fixture, {
      streamAsset: streamMock
    });
    await download.client.check();
    const downloadFirst = download.client.downloadOrOpen();
    const downloadDuplicate = download.client.downloadOrOpen();
    expect(downloadDuplicate).toBe(downloadFirst);
    await expect(download.client.check()).rejects.toMatchObject({
      code: "busy"
    });
    releaseDownload();
    await downloadFirst;
    expect(streamMock).toHaveBeenCalledTimes(1);
  });

  it("cleans partial files on cancellation and ENOSPC, and refuses linked cache targets", async () => {
    const fixture = releaseFixture();
    let started!: () => void;
    const didStart = new Promise<void>((resolve) => {
      started = resolve;
    });
    const cancelled = await createClient(fixture, {
      streamAsset: async (_url, request) => {
        await request.onChunk(fixture.dmg.subarray(0, 4));
        started();
        await new Promise<void>((_resolve, reject) => {
          request.signal.addEventListener(
            "abort",
            () => reject(new UpdateClientError("cancelled")),
            { once: true }
          );
        });
      }
    });
    await cancelled.client.check();
    const pending = cancelled.client.downloadOrOpen();
    await didStart;
    await cancelled.client.cancel();
    await expect(pending).rejects.toMatchObject({ code: "cancelled" });
    await expect(
      lstat(path.join(cancelled.updateDirectory, `${fixture.dmgName}.partial`))
    ).rejects.toMatchObject({ code: "ENOENT" });

    const noSpace = await createClient(fixture, {
      streamAsset: async () => {
        const error = new Error("disk full") as NodeJS.ErrnoException;
        error.code = "ENOSPC";
        throw error;
      }
    });
    await noSpace.client.check();
    await expect(noSpace.client.downloadOrOpen()).rejects.toMatchObject({
      code: "download-failed"
    });
    await expect(
      lstat(path.join(noSpace.updateDirectory, `${fixture.dmgName}.partial`))
    ).rejects.toMatchObject({ code: "ENOENT" });

    const linked = await createClient(fixture);
    await linked.client.check();
    await import("node:fs/promises").then(({ mkdir }) =>
      mkdir(linked.updateDirectory, { recursive: true, mode: 0o700 })
    );
    const outside = path.join(path.dirname(linked.updateDirectory), "outside");
    await writeFile(outside, fixture.dmg, { mode: 0o600 });
    const cached = path.join(linked.updateDirectory, fixture.dmgName);
    await link(outside, cached);
    await expect(linked.client.downloadOrOpen()).rejects.toMatchObject({
      code: "cache-unsafe"
    });
    expect(linked.opened).toEqual([]);

    await rm(cached);
    await symlink(outside, cached);
    await expect(linked.client.downloadOrOpen()).rejects.toMatchObject({
      code: "cache-unsafe"
    });
  });

  it("offers only the fixed release page after explicit user action", async () => {
    expect(CANONICAL_RELEASES_URL).toBe(
      "https://github.com/fredgnr/local-context-forge/releases"
    );
    const fixture = releaseFixture();
    const value = await createClient(fixture, {
      openPath: async () => "Finder refused"
    });
    await value.client.check();
    await expect(value.client.downloadOrOpen()).rejects.toMatchObject({
      code: "open-failed"
    });
    expect(value.client.getStatus()).toMatchObject({
      state: "error",
      errorCode: "open-failed",
      canOpenReleasePage: true
    });
    expect(value.external).toEqual([]);
    await value.client.openReleasePage();
    expect(value.external).toEqual([CANONICAL_RELEASES_URL]);
  });

  it("deduplicates the fixed release action and rejects it during another operation or shutdown", async () => {
    const fixture = releaseFixture();
    let finishOpen!: () => void;
    const openGate = new Promise<void>((resolve) => {
      finishOpen = resolve;
    });
    const openedUrls: string[] = [];
    const value = await createClient(fixture, {
      fetchBytes: async () => {
        throw new UpdateClientError("network");
      },
      openExternal: async (url) => {
        openedUrls.push(url);
        await openGate;
      }
    });
    await expect(value.client.check()).rejects.toMatchObject({
      code: "network"
    });

    const first = value.client.openReleasePage();
    const duplicate = value.client.openReleasePage();
    expect(duplicate).toBe(first);
    await expect(value.client.check()).rejects.toMatchObject({
      code: "busy"
    });
    finishOpen();
    await first;
    expect(openedUrls).toEqual([CANONICAL_RELEASES_URL]);

    await value.client.shutdown();
    await expect(value.client.openReleasePage()).rejects.toMatchObject({
      code: "cancelled"
    });
    expect(openedUrls).toEqual([CANONICAL_RELEASES_URL]);
  });
});

describe("bounded update network policy", () => {
  it("compares arbitrarily large SemVer identifiers without Number overflow", () => {
    const huge =
      "999999999999999999999999999999999999999999999999999999999999.0.0";
    expect(compareSemver(parseSemver(huge), parseSemver("2.0.0"))).toBe(1);
    expect(
      compareSemver(
        parseSemver(`1.0.0-alpha.${"9".repeat(80)}`),
        parseSemver("1.0.0-alpha.2")
      )
    ).toBe(1);
    expect(() => parseSemver("01.0.0")).toThrow();
    expect(() => parseSemver("1.0.0-alpha.01")).toThrow();
  });

  it("revalidates every redirect and rejects userinfo, arbitrary hosts, paths, and query credentials", () => {
    const purpose = {
      kind: "release-asset" as const,
      tag: "v1.1.0",
      name: "local-context-forge-1.1.0-arm64.dmg"
    };
    expect(() =>
      validateNetworkUrl(assetUrl(purpose.tag, purpose.name), purpose, false)
    ).not.toThrow();
    expect(() =>
      validateNetworkUrl(
        "https://user:pass@github.com/fredgnr/local-context-forge/releases/download/v1.1.0/local-context-forge-1.1.0-arm64.dmg",
        purpose,
        false
      )
    ).toThrow();
    expect(() =>
      validateNetworkUrl(
        "https://evil.example/github-production-release-asset/id?sig=x&se=y",
        purpose,
        true
      )
    ).toThrow();
    expect(() =>
      validateNetworkUrl(
        "https://release-assets.githubusercontent.com/github-production-release-asset/id?sig=x&se=y&token=secret",
        purpose,
        true
      )
    ).toThrow();
    expect(() =>
      validateNetworkUrl(
        "https://release-assets.githubusercontent.com/github-production-release-asset/id?sig=x&se=y",
        purpose,
        true
      )
    ).not.toThrow();
  });

  it("rejects missing, duplicate, conflicting, chunked, and oversized Content-Length", () => {
    const response = (
      rawHeaders: string[],
      headers: Record<string, string> = {}
    ) =>
      ({
        rawHeaders,
        headers
      }) as any;
    expect(() => contentLength(response([], {}), 100)).toThrow();
    expect(() =>
      contentLength(
        response([
          "Content-Length",
          "10",
          "content-length",
          "11"
        ]),
        100
      )
    ).toThrow();
    expect(() =>
      contentLength(
        response(["Content-Length", "10"], {
          "transfer-encoding": "chunked"
        }),
        100
      )
    ).toThrow();
    expect(() =>
      contentLength(response(["Content-Length", "101"]), 100)
    ).toThrowError(expect.objectContaining({ code: "response-too-large" }));
    expect(
      contentLength(response(["Content-Length", "10"]), MAX_DMG_BYTES, 10)
    ).toBe(10);
  });
});

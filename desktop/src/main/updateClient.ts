import {
  constants as fsConstants
} from "node:fs";
import {
  chmod,
  lstat,
  mkdir,
  open,
  readFile,
  realpath,
  rename,
  unlink,
  type FileHandle
} from "node:fs/promises";
import {
  createHash,
  createPublicKey,
  verify,
  type KeyObject
} from "node:crypto";
import https from "node:https";
import type { IncomingMessage } from "node:http";
import path from "node:path";
import {
  type UpdateErrorCode,
  type UpdateState,
  type UpdateStatus,
  type UpdateUnavailableReason
} from "../contracts";

export const CANONICAL_REPOSITORY = "fredgnr/local-context-forge";
export const CANONICAL_RELEASES_URL =
  "https://github.com/fredgnr/local-context-forge/releases";
export const UPDATE_MANIFEST_NAME = "update-manifest.json";
export const UPDATE_SIGNATURE_NAME = "update-manifest.json.sig";
export const MAX_RELEASE_METADATA_BYTES = 1024 * 1024;
export const MAX_UPDATE_MANIFEST_BYTES = 256 * 1024;
export const MAX_DMG_BYTES = 2 * 1024 * 1024 * 1024;

const UPDATE_KEY_LOCK_NAME = "update-metadata-key.lock.json";
const UPDATE_PUBLIC_KEY_NAME = "update-metadata-ed25519-public.pem";
const UPDATE_PUBLIC_KEY_REPOSITORY_PATH =
  `desktop/resources/update/${UPDATE_PUBLIC_KEY_NAME}`;
const USER_AGENT = "Local-Context-Forge-Desktop-Updater/1";
const NETWORK_TIMEOUT_MS = 15_000;
const MAX_REDIRECTS = 3;
const MAX_RELEASES = 20;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const CHANNEL_PATTERN = /^[0-9A-Za-z-]{1,64}$/;
const SEMVER_PATTERN =
  /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;
const REDIRECT_STATUS = new Set([301, 302, 303, 307, 308]);
const RELEASE_ASSET_QUERY_KEYS = new Set([
  "sp",
  "sv",
  "sr",
  "spr",
  "se",
  "rscd",
  "rsct",
  "skoid",
  "sktid",
  "skt",
  "ske",
  "sks",
  "skv",
  "sig"
]);

type PlainRecord = Record<string, unknown>;

interface ParsedSemver {
  readonly raw: string;
  readonly core: readonly [bigint, bigint, bigint];
  readonly prerelease: readonly string[];
}

interface ReleaseAssetMetadata {
  readonly name: string;
  readonly size: number;
  readonly browserDownloadUrl: string;
}

interface ReleaseMetadata {
  readonly tag: string;
  readonly version: string;
  readonly parsedVersion: ParsedSemver;
  readonly prerelease: boolean;
  readonly assets: ReadonlyMap<string, ReleaseAssetMetadata>;
}

interface ManifestAsset {
  readonly kind:
    | "dmg"
    | "electron-updater-zip"
    | "electron-updater-blockmap"
    | "electron-updater-metadata";
  readonly name: string;
  readonly size: number;
  readonly sha256: string;
}

interface VerifiedCandidate {
  readonly tag: string;
  readonly version: string;
  readonly dmg: ManifestAsset;
  readonly downloadUrl: string;
}

export interface UpdateTrustAnchor {
  readonly publicKey: KeyObject;
  readonly publicKeySha256: string;
}

interface FetchBytesOptions {
  readonly maximumBytes: number;
  readonly expectedBytes?: number;
  readonly signal: AbortSignal;
  readonly purpose: NetworkPurpose;
}

interface StreamAssetOptions {
  readonly maximumBytes: number;
  readonly expectedBytes: number;
  readonly signal: AbortSignal;
  readonly purpose: NetworkPurpose;
  readonly onChunk: (chunk: Buffer) => Promise<void>;
}

type NetworkPurpose =
  | { readonly kind: "api"; readonly channel: string }
  | {
      readonly kind: "release-asset";
      readonly tag: string;
      readonly name: string;
    };

export type UpdateFetchBytes = (
  url: string,
  options: FetchBytesOptions
) => Promise<Buffer>;

export type UpdateStreamAsset = (
  url: string,
  options: StreamAssetOptions
) => Promise<void>;

export interface UpdateClientOptions {
  readonly packaged: boolean;
  readonly platform: string;
  readonly architecture: string;
  readonly currentVersion: string;
  readonly resourcesPath: string;
  readonly updateDirectory: string;
  readonly openPath: (filePath: string) => Promise<string>;
  readonly openExternal: (url: string) => Promise<void>;
  readonly loadTrustAnchor?: () => Promise<UpdateTrustAnchor>;
  readonly fetchBytes?: UpdateFetchBytes;
  readonly streamAsset?: UpdateStreamAsset;
}

type OperationKind = "check" | "download-or-open" | "open-release-page";

interface ActiveOperation {
  readonly kind: OperationKind;
  readonly controller: AbortController;
  readonly promise: Promise<UpdateStatus>;
}

interface CreatedPartial {
  readonly path: string;
  readonly device: number;
  readonly inode: number;
}

export class UpdateClientError extends Error {
  constructor(readonly code: UpdateErrorCode) {
    super(`Desktop update failed (${code})`);
    this.name = "UpdateClientError";
  }
}

function isPlainRecord(value: unknown): value is PlainRecord {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function hasExactKeys(value: unknown, expected: readonly string[]): value is PlainRecord {
  if (!isPlainRecord(value)) {
    return false;
  }
  const actual = Object.keys(value).sort();
  const reviewed = [...expected].sort();
  return (
    actual.length === reviewed.length &&
    actual.every((key, index) => key === reviewed[index])
  );
}

function compareCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left, (value) => value.codePointAt(0) ?? 0);
  const rightPoints = Array.from(right, (value) => value.codePointAt(0) ?? 0);
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
    const difference = (leftPoints[index] ?? 0) - (rightPoints[index] ?? 0);
    if (difference !== 0) {
      return difference;
    }
  }
  return leftPoints.length - rightPoints.length;
}

function sortJson(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sortJson);
  }
  if (!isPlainRecord(value)) {
    return value;
  }
  const result: PlainRecord = {};
  for (const key of Object.keys(value).sort(compareCodePoints)) {
    result[key] = sortJson(value[key]);
  }
  return result;
}

export function canonicalJson(value: unknown): string {
  const encoded = JSON.stringify(sortJson(value));
  if (encoded === undefined) {
    throw new UpdateClientError("manifest-invalid");
  }
  return encoded;
}

export function parseSemver(value: unknown): ParsedSemver {
  if (typeof value !== "string" || value.length > 128) {
    throw new UpdateClientError("metadata-invalid");
  }
  const match = SEMVER_PATTERN.exec(value);
  if (!match) {
    throw new UpdateClientError("metadata-invalid");
  }
  const prerelease = match[4]?.split(".") ?? [];
  if (
    prerelease.some(
      (part) => /^[0-9]+$/.test(part) && part.length > 1 && part.startsWith("0")
    )
  ) {
    throw new UpdateClientError("metadata-invalid");
  }
  return {
    raw: value,
    core: [
      BigInt(match[1] as string),
      BigInt(match[2] as string),
      BigInt(match[3] as string)
    ],
    prerelease
  };
}

export function compareSemver(left: ParsedSemver, right: ParsedSemver): number {
  for (let index = 0; index < 3; index += 1) {
    const leftPart = left.core[index] ?? 0n;
    const rightPart = right.core[index] ?? 0n;
    if (leftPart !== rightPart) {
      return leftPart > rightPart ? 1 : -1;
    }
  }
  if (left.prerelease.length === 0 || right.prerelease.length === 0) {
    return left.prerelease.length === right.prerelease.length
      ? 0
      : left.prerelease.length === 0
        ? 1
        : -1;
  }
  const length = Math.max(left.prerelease.length, right.prerelease.length);
  for (let index = 0; index < length; index += 1) {
    const leftPart = left.prerelease[index];
    const rightPart = right.prerelease[index];
    if (leftPart === undefined || rightPart === undefined) {
      return leftPart === rightPart ? 0 : leftPart === undefined ? -1 : 1;
    }
    if (leftPart === rightPart) {
      continue;
    }
    const leftNumeric = /^[0-9]+$/.test(leftPart);
    const rightNumeric = /^[0-9]+$/.test(rightPart);
    if (leftNumeric && rightNumeric) {
      const leftNumber = BigInt(leftPart);
      const rightNumber = BigInt(rightPart);
      return leftNumber === rightNumber
        ? 0
        : leftNumber > rightNumber
          ? 1
          : -1;
    }
    if (leftNumeric !== rightNumeric) {
      return leftNumeric ? -1 : 1;
    }
    return compareCodePoints(leftPart, rightPart);
  }
  return 0;
}

function channelForVersion(version: ParsedSemver): string {
  const channel = version.prerelease[0] ?? "latest";
  if (!CHANNEL_PATTERN.test(channel)) {
    throw new UpdateClientError("metadata-invalid");
  }
  return channel;
}

function safeBasename(value: unknown): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    Buffer.byteLength(value, "utf8") > 240 ||
    value === "." ||
    value === ".." ||
    value !== value.normalize("NFC") ||
    value.includes("/") ||
    value.includes("\\") ||
    /[\u0000-\u001f\u007f]/.test(value) ||
    path.basename(value) !== value
  ) {
    throw new UpdateClientError("asset-invalid");
  }
  return value;
}

function releaseAssetUrl(tag: string, name: string): string {
  return (
    `https://github.com/${CANONICAL_REPOSITORY}/releases/download/` +
    `${encodeURIComponent(tag)}/${encodeURIComponent(name)}`
  );
}

function releaseApiUrl(channel: string): string {
  return channel === "latest"
    ? `https://api.github.com/repos/${CANONICAL_REPOSITORY}/releases/latest`
    : `https://api.github.com/repos/${CANONICAL_REPOSITORY}/releases?per_page=20&page=1`;
}

function decodedPathSegments(url: URL): string[] {
  try {
    return url.pathname
      .split("/")
      .filter((segment) => segment.length > 0)
      .map((segment) => decodeURIComponent(segment));
  } catch {
    throw new UpdateClientError("network");
  }
}

function validateCommonNetworkUrl(url: URL): void {
  if (
    url.protocol !== "https:" ||
    url.username !== "" ||
    url.password !== "" ||
    (url.port !== "" && url.port !== "443") ||
    url.hash !== "" ||
    url.href.length > 4096
  ) {
    throw new UpdateClientError("network");
  }
}

export function validateNetworkUrl(
  value: string | URL,
  purpose: NetworkPurpose,
  redirected: boolean
): URL {
  let url: URL;
  try {
    url = value instanceof URL ? new URL(value.href) : new URL(value);
  } catch {
    throw new UpdateClientError("network");
  }
  validateCommonNetworkUrl(url);

  if (purpose.kind === "api") {
    if (url.hostname !== "api.github.com") {
      throw new UpdateClientError("network");
    }
    const stablePath = `/repos/${CANONICAL_REPOSITORY}/releases/latest`;
    const prereleasePath = `/repos/${CANONICAL_REPOSITORY}/releases`;
    if (purpose.channel === "latest") {
      if (url.pathname !== stablePath || url.search !== "") {
        throw new UpdateClientError("network");
      }
    } else if (
      url.pathname !== prereleasePath ||
      url.searchParams.size !== 2 ||
      url.searchParams.get("per_page") !== "20" ||
      url.searchParams.get("page") !== "1"
    ) {
      throw new UpdateClientError("network");
    }
    return url;
  }

  if (url.hostname === "github.com") {
    if (url.search !== "") {
      throw new UpdateClientError("network");
    }
    const segments = decodedPathSegments(url);
    const [owner, repository] = CANONICAL_REPOSITORY.split("/");
    if (
      segments.length !== 6 ||
      segments[0] !== owner ||
      segments[1] !== repository ||
      segments[2] !== "releases" ||
      segments[3] !== "download" ||
      segments[4] !== purpose.tag ||
      segments[5] !== purpose.name
    ) {
      throw new UpdateClientError("network");
    }
    return url;
  }

  if (
    !redirected ||
    url.hostname !== "release-assets.githubusercontent.com" ||
    !url.pathname.startsWith("/github-production-release-asset/")
  ) {
    throw new UpdateClientError("network");
  }
  const queryKeys = [...url.searchParams.keys()];
  if (
    queryKeys.length === 0 ||
    new Set(queryKeys).size !== queryKeys.length ||
    queryKeys.some(
      (key) =>
        !RELEASE_ASSET_QUERY_KEYS.has(key) ||
        /token|authorization|credential|jwt/i.test(key)
    ) ||
    !url.searchParams.has("sig") ||
    !url.searchParams.has("se") ||
    url.searchParams.get("sig") === "" ||
    url.searchParams.get("se") === ""
  ) {
    throw new UpdateClientError("network");
  }
  return url;
}

function mappedNetworkError(
  error: unknown,
  signal: AbortSignal
): UpdateClientError {
  if (error instanceof UpdateClientError) {
    return error;
  }
  if (signal.aborted) {
    return new UpdateClientError("cancelled");
  }
  const code =
    error && typeof error === "object" && "code" in error
      ? String(error.code)
      : "";
  return new UpdateClientError(
    code === "ETIMEDOUT" || code === "ESOCKETTIMEDOUT"
      ? "timeout"
      : "network"
  );
}

async function openHttpsResponse(
  input: string,
  purpose: NetworkPurpose,
  signal: AbortSignal,
  redirectCount = 0,
  redirected = false
): Promise<IncomingMessage> {
  if (signal.aborted) {
    throw new UpdateClientError("cancelled");
  }
  const url = validateNetworkUrl(input, purpose, redirected);
  const response = await new Promise<IncomingMessage>((resolve, reject) => {
    const request = https.get(
      {
        protocol: "https:",
        hostname: url.hostname,
        port: url.port || 443,
        path: `${url.pathname}${url.search}`,
        headers: {
          Accept:
            purpose.kind === "api"
              ? "application/vnd.github+json"
              : "application/octet-stream",
          "Accept-Encoding": "identity",
          "User-Agent": USER_AGENT
        }
      },
      (incoming) => {
        clearTimeout(connectTimer);
        resolve(incoming);
      }
    );
    const connectTimer = setTimeout(() => {
      request.destroy(new UpdateClientError("timeout"));
    }, NETWORK_TIMEOUT_MS);
    connectTimer.unref();
    const abort = () => request.destroy(new UpdateClientError("cancelled"));
    signal.addEventListener("abort", abort, { once: true });
    request.setTimeout(NETWORK_TIMEOUT_MS, () => {
      request.destroy(new UpdateClientError("timeout"));
    });
    request.once("error", (error) => reject(mappedNetworkError(error, signal)));
    request.once("close", () => {
      clearTimeout(connectTimer);
      signal.removeEventListener("abort", abort);
    });
  });

  const status = response.statusCode ?? 0;
  if (REDIRECT_STATUS.has(status)) {
    const location = response.headers.location;
    response.destroy();
    if (
      redirectCount >= MAX_REDIRECTS ||
      typeof location !== "string" ||
      location.length === 0 ||
      location.length > 4096
    ) {
      throw new UpdateClientError("network");
    }
    let next: URL;
    try {
      next = new URL(location, url);
    } catch {
      throw new UpdateClientError("network");
    }
    validateNetworkUrl(next, purpose, true);
    return openHttpsResponse(
      next.href,
      purpose,
      signal,
      redirectCount + 1,
      true
    );
  }
  if (status !== 200) {
    response.destroy();
    throw new UpdateClientError("network");
  }
  return response;
}

export function contentLength(
  response: IncomingMessage,
  maximumBytes: number,
  expectedBytes?: number
): number {
  let count = 0;
  let rawValue = "";
  for (let index = 0; index < response.rawHeaders.length; index += 2) {
    if ((response.rawHeaders[index] ?? "").toLowerCase() === "content-length") {
      count += 1;
      rawValue = response.rawHeaders[index + 1] ?? "";
    }
  }
  if (
    count !== 1 ||
    !/^(0|[1-9][0-9]*)$/.test(rawValue) ||
    response.headers["transfer-encoding"] !== undefined ||
    response.headers["content-encoding"] !== undefined
  ) {
    throw new UpdateClientError("network");
  }
  const size = Number(rawValue);
  if (
    !Number.isSafeInteger(size) ||
    size <= 0 ||
    size > maximumBytes ||
    (expectedBytes !== undefined && size !== expectedBytes)
  ) {
    throw new UpdateClientError(
      size > maximumBytes ? "response-too-large" : "network"
    );
  }
  return size;
}

export const fetchHttpsBytes: UpdateFetchBytes = async (url, options) => {
  const response = await openHttpsResponse(
    url,
    options.purpose,
    options.signal
  );
  let expected: number;
  try {
    expected = contentLength(
      response,
      options.maximumBytes,
      options.expectedBytes
    );
  } catch (error) {
    response.destroy();
    throw error;
  }
  const chunks: Buffer[] = [];
  let received = 0;
  const abort = () => response.destroy(new UpdateClientError("cancelled"));
  options.signal.addEventListener("abort", abort, { once: true });
  try {
    for await (const rawChunk of response) {
      if (options.signal.aborted) {
        throw new UpdateClientError("cancelled");
      }
      const chunk = Buffer.isBuffer(rawChunk)
        ? rawChunk
        : Buffer.from(rawChunk as Uint8Array);
      received += chunk.length;
      if (received > expected || received > options.maximumBytes) {
        throw new UpdateClientError("response-too-large");
      }
      chunks.push(chunk);
    }
  } catch (error) {
    throw mappedNetworkError(error, options.signal);
  } finally {
    options.signal.removeEventListener("abort", abort);
    response.destroy();
  }
  if (received !== expected) {
    throw new UpdateClientError("network");
  }
  return Buffer.concat(chunks, received);
};

export const streamHttpsAsset: UpdateStreamAsset = async (url, options) => {
  const response = await openHttpsResponse(
    url,
    options.purpose,
    options.signal
  );
  let expected: number;
  try {
    expected = contentLength(
      response,
      options.maximumBytes,
      options.expectedBytes
    );
  } catch (error) {
    response.destroy();
    throw error;
  }
  let received = 0;
  const abort = () => response.destroy(new UpdateClientError("cancelled"));
  options.signal.addEventListener("abort", abort, { once: true });
  try {
    for await (const rawChunk of response) {
      if (options.signal.aborted) {
        throw new UpdateClientError("cancelled");
      }
      const chunk = Buffer.isBuffer(rawChunk)
        ? rawChunk
        : Buffer.from(rawChunk as Uint8Array);
      received += chunk.length;
      if (received > expected || received > options.maximumBytes) {
        throw new UpdateClientError("download-too-large");
      }
      await options.onChunk(chunk);
    }
  } catch (error) {
    if (error instanceof UpdateClientError) {
      throw error;
    }
    const code =
      error && typeof error === "object" && "code" in error
        ? String(error.code)
        : "";
    if (code === "ENOSPC") {
      throw new UpdateClientError("download-failed");
    }
    throw mappedNetworkError(error, options.signal);
  } finally {
    options.signal.removeEventListener("abort", abort);
    response.destroy();
  }
  if (received !== expected) {
    throw new UpdateClientError("download-failed");
  }
};

async function boundedRegularFile(
  filePath: string,
  maximumBytes: number
): Promise<Buffer> {
  let info;
  try {
    info = await lstat(filePath);
  } catch {
    throw new UpdateClientError("asset-invalid");
  }
  if (
    !info.isFile() ||
    info.isSymbolicLink() ||
    info.nlink !== 1 ||
    info.size <= 0 ||
    info.size > maximumBytes
  ) {
    throw new UpdateClientError("asset-invalid");
  }
  const bytes = await readFile(filePath);
  if (bytes.length !== info.size) {
    throw new UpdateClientError("asset-invalid");
  }
  return bytes;
}

export async function loadBundledTrustAnchor(
  resourcesPath: string
): Promise<UpdateTrustAnchor> {
  const updateRoot = path.join(resourcesPath, "update");
  const lockPath = path.join(updateRoot, UPDATE_KEY_LOCK_NAME);
  const publicKeyPath = path.join(updateRoot, UPDATE_PUBLIC_KEY_NAME);
  const lockBytes = await boundedRegularFile(lockPath, 16 * 1024);
  let lock: unknown;
  try {
    lock = JSON.parse(lockBytes.toString("utf8"));
  } catch {
    throw new UpdateClientError("asset-invalid");
  }
  if (
    !hasExactKeys(lock, [
      "schemaVersion",
      "algorithm",
      "credentialGenerationId",
      "publicKeyPath",
      "publicKeySha256",
      "status"
    ]) ||
    lock.schemaVersion !== 1 ||
    lock.algorithm !== "Ed25519" ||
    lock.publicKeyPath !== UPDATE_PUBLIC_KEY_REPOSITORY_PATH
  ) {
    throw new UpdateClientError("asset-invalid");
  }
  if (
    lock.status === "unprovisioned" &&
    lock.credentialGenerationId === null &&
    lock.publicKeySha256 === null
  ) {
    throw new UpdateClientError("unavailable");
  }
  if (
    lock.status !== "provisioned" ||
    typeof lock.credentialGenerationId !== "string" ||
    !/^[0-9a-f]{32}$/.test(lock.credentialGenerationId) ||
    typeof lock.publicKeySha256 !== "string"
  ) {
    throw new UpdateClientError("asset-invalid");
  }
  if (!SHA256_PATTERN.test(lock.publicKeySha256)) {
    throw new UpdateClientError("asset-invalid");
  }
  let publicKeyBytes: Buffer;
  try {
    publicKeyBytes = await boundedRegularFile(publicKeyPath, 16 * 1024);
  } catch {
    throw new UpdateClientError("asset-invalid");
  }
  const digest = createHash("sha256").update(publicKeyBytes).digest("hex");
  if (digest !== lock.publicKeySha256) {
    throw new UpdateClientError("asset-invalid");
  }
  let publicKey: KeyObject;
  try {
    publicKey = createPublicKey(publicKeyBytes);
  } catch {
    throw new UpdateClientError("asset-invalid");
  }
  if (publicKey.asymmetricKeyType !== "ed25519") {
    throw new UpdateClientError("asset-invalid");
  }
  return { publicKey, publicKeySha256: digest };
}

function parseReleaseAsset(value: unknown): ReleaseAssetMetadata {
  if (!isPlainRecord(value)) {
    throw new UpdateClientError("metadata-invalid");
  }
  const name = safeBasename(value.name);
  const size = value.size;
  const browserDownloadUrl = value.browser_download_url;
  if (
    !Number.isSafeInteger(size) ||
    (size as number) <= 0 ||
    (size as number) > MAX_DMG_BYTES ||
    typeof browserDownloadUrl !== "string" ||
    browserDownloadUrl.length === 0 ||
    browserDownloadUrl.length > 4096
  ) {
    throw new UpdateClientError("metadata-invalid");
  }
  return {
    name,
    size: size as number,
    browserDownloadUrl
  };
}

function parseRelease(value: unknown): ReleaseMetadata {
  if (!isPlainRecord(value)) {
    throw new UpdateClientError("metadata-invalid");
  }
  const tag = value.tag_name;
  if (
    typeof tag !== "string" ||
    tag.length < 2 ||
    tag.length > 129 ||
    !tag.startsWith("v") ||
    typeof value.draft !== "boolean" ||
    typeof value.prerelease !== "boolean" ||
    !Array.isArray(value.assets) ||
    value.assets.length > 64
  ) {
    throw new UpdateClientError("metadata-invalid");
  }
  const parsedVersion = parseSemver(tag.slice(1));
  if ((parsedVersion.prerelease.length > 0) !== value.prerelease) {
    throw new UpdateClientError("metadata-invalid");
  }
  const assets = new Map<string, ReleaseAssetMetadata>();
  for (const rawAsset of value.assets) {
    const asset = parseReleaseAsset(rawAsset);
    if (assets.has(asset.name)) {
      throw new UpdateClientError("metadata-invalid");
    }
    assets.set(asset.name, asset);
  }
  if (value.draft) {
    throw new UpdateClientError("metadata-invalid");
  }
  return {
    tag,
    version: parsedVersion.raw,
    parsedVersion,
    prerelease: value.prerelease,
    assets
  };
}

export function selectReleaseMetadata(
  value: unknown,
  currentVersion: ParsedSemver,
  channel: string
): ReleaseMetadata | undefined {
  const rawCandidates =
    channel === "latest"
      ? Array.isArray(value)
        ? undefined
        : [value]
      : Array.isArray(value)
        ? value
        : undefined;
  if (!rawCandidates) {
    throw new UpdateClientError("metadata-invalid");
  }
  if (rawCandidates.length === 0 || rawCandidates.length > MAX_RELEASES) {
    throw new UpdateClientError("metadata-invalid");
  }
  const candidates = rawCandidates.map(parseRelease);
  const matching = candidates.filter(
    (candidate) =>
      channelForVersion(candidate.parsedVersion) === channel &&
      (channel === "latest" ? !candidate.prerelease : candidate.prerelease)
  );
  if (matching.length === 0) {
    throw new UpdateClientError("channel-mismatch");
  }
  matching.sort((left, right) =>
    compareSemver(right.parsedVersion, left.parsedVersion)
  );
  const selected = matching[0];
  if (
    !selected ||
    compareSemver(selected.parsedVersion, currentVersion) <= 0
  ) {
    return undefined;
  }
  for (const name of [UPDATE_MANIFEST_NAME, UPDATE_SIGNATURE_NAME]) {
    const asset = selected.assets.get(name);
    if (!asset) {
      throw new UpdateClientError("metadata-invalid");
    }
    const expectedUrl = releaseAssetUrl(selected.tag, name);
    validateNetworkUrl(
      asset.browserDownloadUrl,
      { kind: "release-asset", tag: selected.tag, name },
      false
    );
    if (new URL(asset.browserDownloadUrl).href !== new URL(expectedUrl).href) {
      throw new UpdateClientError("metadata-invalid");
    }
  }
  return selected;
}

function maximumForAsset(kind: ManifestAsset["kind"]): number {
  switch (kind) {
    case "dmg":
    case "electron-updater-zip":
      return MAX_DMG_BYTES;
    case "electron-updater-blockmap":
      return 64 * 1024 * 1024;
    case "electron-updater-metadata":
      return 256 * 1024;
  }
}

function parseManifestAsset(
  value: unknown,
  expectedKind: ManifestAsset["kind"],
  expectedName: string
): ManifestAsset {
  if (
    !hasExactKeys(value, ["kind", "name", "size", "sha256"]) ||
    value.kind !== expectedKind ||
    safeBasename(value.name) !== expectedName ||
    !Number.isSafeInteger(value.size) ||
    (value.size as number) <= 0 ||
    (value.size as number) > maximumForAsset(expectedKind) ||
    typeof value.sha256 !== "string" ||
    !SHA256_PATTERN.test(value.sha256)
  ) {
    throw new UpdateClientError("manifest-invalid");
  }
  return {
    kind: expectedKind,
    name: expectedName,
    size: value.size as number,
    sha256: value.sha256
  };
}

export function verifyUpdateManifest(
  manifestBytes: Buffer,
  signatureBytes: Buffer,
  release: ReleaseMetadata,
  currentVersion: ParsedSemver,
  channel: string,
  trustAnchor: UpdateTrustAnchor
): VerifiedCandidate {
  if (
    manifestBytes.length === 0 ||
    manifestBytes.length > MAX_UPDATE_MANIFEST_BYTES ||
    signatureBytes.length !== 64 ||
    !verify(
      null,
      manifestBytes,
      trustAnchor.publicKey,
      signatureBytes
    )
  ) {
    throw new UpdateClientError("signature-invalid");
  }
  let value: unknown;
  try {
    value = JSON.parse(manifestBytes.toString("utf8"));
  } catch {
    throw new UpdateClientError("manifest-invalid");
  }
  if (
    !hasExactKeys(value, [
      "schemaVersion",
      "kind",
      "repository",
      "channel",
      "version",
      "architecture",
      "source",
      "publicKey",
      "assets"
    ]) ||
    value.schemaVersion !== 1 ||
    value.kind !== "local-context-forge-desktop-update" ||
    value.repository !== CANONICAL_REPOSITORY ||
    value.channel !== channel ||
    value.version !== release.version ||
    value.architecture !== "arm64" ||
    !hasExactKeys(value.source, [
      "tag",
      "commit",
      "sourceDateEpoch"
    ]) ||
    value.source.tag !== release.tag ||
    value.source.tag !== `v${value.version}` ||
    typeof value.source.commit !== "string" ||
    !COMMIT_PATTERN.test(value.source.commit) ||
    !Number.isSafeInteger(value.source.sourceDateEpoch) ||
    (value.source.sourceDateEpoch as number) < 100_000_000 ||
    !hasExactKeys(value.publicKey, ["algorithm", "sha256"]) ||
    value.publicKey.algorithm !== "Ed25519" ||
    value.publicKey.sha256 !== trustAnchor.publicKeySha256 ||
    !Array.isArray(value.assets) ||
    value.assets.length !== 4
  ) {
    throw new UpdateClientError("manifest-invalid");
  }
  let parsedVersion: ParsedSemver;
  try {
    parsedVersion = parseSemver(value.version);
  } catch {
    throw new UpdateClientError("manifest-invalid");
  }
  if (
    channelForVersion(parsedVersion) !== channel ||
    compareSemver(parsedVersion, currentVersion) <= 0
  ) {
    throw new UpdateClientError("manifest-invalid");
  }
  const base = `local-context-forge-${release.version}-arm64`;
  const expected: readonly [
    ManifestAsset["kind"],
    string
  ][] = [
    ["dmg", `${base}.dmg`],
    ["electron-updater-zip", `${base}.zip`],
    ["electron-updater-blockmap", `${base}.zip.blockmap`],
    ["electron-updater-metadata", `${channel}-mac.yml`]
  ];
  const assets = value.assets.map((asset, index) => {
    const reviewed = expected[index];
    if (!reviewed) {
      throw new UpdateClientError("manifest-invalid");
    }
    return parseManifestAsset(asset, reviewed[0], reviewed[1]);
  });
  if (new Set(assets.map((asset) => asset.name)).size !== assets.length) {
    throw new UpdateClientError("manifest-invalid");
  }
  const canonicalBytes = Buffer.from(`${canonicalJson(value)}\n`, "utf8");
  if (!manifestBytes.equals(canonicalBytes)) {
    throw new UpdateClientError("manifest-invalid");
  }
  const dmg = assets[0];
  if (!dmg || dmg.kind !== "dmg") {
    throw new UpdateClientError("manifest-invalid");
  }
  const releaseDmg = release.assets.get(dmg.name);
  if (!releaseDmg || releaseDmg.size !== dmg.size) {
    throw new UpdateClientError("asset-invalid");
  }
  const downloadUrl = releaseAssetUrl(release.tag, dmg.name);
  validateNetworkUrl(
    releaseDmg.browserDownloadUrl,
    { kind: "release-asset", tag: release.tag, name: dmg.name },
    false
  );
  if (
    new URL(releaseDmg.browserDownloadUrl).href !==
    new URL(downloadUrl).href
  ) {
    throw new UpdateClientError("asset-invalid");
  }
  return {
    tag: release.tag,
    version: release.version,
    dmg,
    downloadUrl
  };
}

function initialStatus(
  currentVersion: string,
  channel: string,
  reason: UpdateUnavailableReason
): UpdateStatus {
  return {
    state: "unavailable",
    currentVersion,
    channel,
    availableVersion: null,
    progress: null,
    errorCode: null,
    unavailableReason: reason,
    canCheck: false,
    canDownloadOrOpen: false,
    canOpenReleasePage: true,
    automaticApply: false,
    automaticApplyReason: "val-update-001-not-passed"
  };
}

function updateStatus(
  currentVersion: string,
  channel: string,
  state: UpdateState,
  options: {
    readonly availableVersion?: string | null;
    readonly progress?: UpdateStatus["progress"];
    readonly errorCode?: UpdateErrorCode | null;
    readonly canCheck?: boolean;
    readonly canDownloadOrOpen?: boolean;
    readonly canOpenReleasePage?: boolean;
  } = {}
): UpdateStatus {
  return {
    state,
    currentVersion,
    channel,
    availableVersion: options.availableVersion ?? null,
    progress: options.progress ?? null,
    errorCode: options.errorCode ?? null,
    unavailableReason: null,
    canCheck: options.canCheck ?? false,
    canDownloadOrOpen: options.canDownloadOrOpen ?? false,
    canOpenReleasePage: options.canOpenReleasePage ?? false,
    automaticApply: false,
    automaticApplyReason: "val-update-001-not-passed"
  };
}

function asUpdateError(error: unknown): UpdateClientError {
  if (error instanceof UpdateClientError) {
    return error;
  }
  const code =
    error && typeof error === "object" && "code" in error
      ? String(error.code)
      : "";
  return new UpdateClientError(
    code === "ENOSPC" ? "download-failed" : "download-failed"
  );
}

async function writeAll(handle: FileHandle, chunk: Buffer): Promise<void> {
  let offset = 0;
  while (offset < chunk.length) {
    const result = await handle.write(
      chunk,
      offset,
      chunk.length - offset,
      null
    );
    if (result.bytesWritten <= 0) {
      throw new UpdateClientError("download-failed");
    }
    offset += result.bytesWritten;
  }
}

async function ensurePrivateDirectory(directory: string): Promise<string> {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const info = await lstat(directory);
  const uid = process.geteuid?.() ?? process.getuid?.() ?? -1;
  if (
    !info.isDirectory() ||
    info.isSymbolicLink() ||
    info.uid !== uid
  ) {
    throw new UpdateClientError("cache-unsafe");
  }
  await chmod(directory, 0o700);
  const secured = await lstat(directory);
  const resolved = await realpath(directory);
  if (
    !secured.isDirectory() ||
    secured.isSymbolicLink() ||
    secured.uid !== uid ||
    secured.dev !== info.dev ||
    secured.ino !== info.ino ||
    (secured.mode & 0o077) !== 0 ||
    resolved !== path.resolve(directory)
  ) {
    throw new UpdateClientError("cache-unsafe");
  }
  return resolved;
}

async function removeStalePartial(partialPath: string): Promise<void> {
  let info;
  try {
    info = await lstat(partialPath);
  } catch (error) {
    const code =
      error && typeof error === "object" && "code" in error
        ? String(error.code)
        : "";
    if (code === "ENOENT") {
      return;
    }
    throw new UpdateClientError("cache-unsafe");
  }
  const uid = process.geteuid?.() ?? process.getuid?.() ?? -1;
  if (
    !info.isFile() ||
    info.isSymbolicLink() ||
    info.nlink !== 1 ||
    info.uid !== uid ||
    (info.mode & 0o077) !== 0
  ) {
    throw new UpdateClientError("cache-unsafe");
  }
  let handle: FileHandle | undefined;
  try {
    handle = await open(
      partialPath,
      fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW
    );
    const opened = await handle.stat();
    if (
      !opened.isFile() ||
      opened.nlink !== 1 ||
      opened.uid !== uid ||
      opened.dev !== info.dev ||
      opened.ino !== info.ino ||
      (opened.mode & 0o077) !== 0
    ) {
      throw new UpdateClientError("cache-unsafe");
    }
  } catch (error) {
    if (error instanceof UpdateClientError) {
      throw error;
    }
    throw new UpdateClientError("cache-unsafe");
  } finally {
    await handle?.close().catch(() => undefined);
  }
  const finalIdentity = await lstat(partialPath);
  if (
    !finalIdentity.isFile() ||
    finalIdentity.isSymbolicLink() ||
    finalIdentity.nlink !== 1 ||
    finalIdentity.uid !== uid ||
    finalIdentity.dev !== info.dev ||
    finalIdentity.ino !== info.ino ||
    (finalIdentity.mode & 0o077) !== 0
  ) {
    throw new UpdateClientError("cache-unsafe");
  }
  await unlink(partialPath);
}

async function cleanupCreatedPartial(created: CreatedPartial): Promise<void> {
  try {
    const info = await lstat(created.path);
    const uid = process.geteuid?.() ?? process.getuid?.() ?? -1;
    if (
      info.isFile() &&
      !info.isSymbolicLink() &&
      info.nlink === 1 &&
      info.uid === uid &&
      (info.mode & 0o077) === 0 &&
      info.dev === created.device &&
      info.ino === created.inode
    ) {
      await unlink(created.path);
    }
  } catch {
    // Cleanup is best-effort after a fail-closed operation.
  }
}

async function verifyRegularFile(
  filePath: string,
  expectedSize: number,
  expectedSha256: string,
  signal?: AbortSignal
): Promise<boolean> {
  let before;
  try {
    before = await lstat(filePath);
  } catch (error) {
    const code =
      error && typeof error === "object" && "code" in error
        ? String(error.code)
        : "";
    if (code === "ENOENT") {
      return false;
    }
    throw new UpdateClientError("cache-unsafe");
  }
  if (
    !before.isFile() ||
    before.isSymbolicLink() ||
    before.nlink !== 1 ||
    before.uid !== (process.geteuid?.() ?? process.getuid?.() ?? -1) ||
    before.size !== expectedSize ||
    (before.mode & 0o077) !== 0
  ) {
    throw new UpdateClientError("cache-unsafe");
  }
  const resolved = await realpath(filePath);
  if (resolved !== path.resolve(filePath)) {
    throw new UpdateClientError("cache-unsafe");
  }
  let handle: FileHandle | undefined;
  try {
    handle = await open(
      filePath,
      fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW
    );
    const after = await handle.stat();
    if (
      !after.isFile() ||
      after.nlink !== 1 ||
      after.uid !== before.uid ||
      after.dev !== before.dev ||
      after.ino !== before.ino ||
      after.size !== expectedSize
    ) {
      throw new UpdateClientError("cache-unsafe");
    }
    const digest = createHash("sha256");
    const buffer = Buffer.allocUnsafe(1024 * 1024);
    let offset = 0;
    while (offset < expectedSize) {
      if (signal?.aborted) {
        throw new UpdateClientError("cancelled");
      }
      const result = await handle.read(
        buffer,
        0,
        Math.min(buffer.length, expectedSize - offset),
        offset
      );
      if (result.bytesRead <= 0) {
        throw new UpdateClientError("digest-mismatch");
      }
      offset += result.bytesRead;
      digest.update(buffer.subarray(0, result.bytesRead));
    }
    return digest.digest("hex") === expectedSha256;
  } finally {
    await handle?.close().catch(() => undefined);
  }
}

async function fsyncDirectory(directory: string): Promise<void> {
  const handle = await open(directory, fsConstants.O_RDONLY);
  try {
    await handle.sync();
  } finally {
    await handle.close();
  }
}

export class UpdateClient {
  private status: UpdateStatus;
  private readonly listeners = new Set<(status: UpdateStatus) => void>();
  private readonly parsedCurrentVersion: ParsedSemver;
  private readonly currentVersionValid: boolean;
  private readonly channel: string;
  private readonly fetchBytes: UpdateFetchBytes;
  private readonly streamAsset: UpdateStreamAsset;
  private trustAnchor: UpdateTrustAnchor | undefined;
  private candidate: VerifiedCandidate | undefined;
  private active: ActiveOperation | undefined;
  private shuttingDown = false;
  private resolvedUpdateDirectory?: string;

  private constructor(private readonly options: UpdateClientOptions) {
    try {
      this.parsedCurrentVersion = parseSemver(options.currentVersion);
      this.channel = channelForVersion(this.parsedCurrentVersion);
      this.currentVersionValid = true;
    } catch {
      this.parsedCurrentVersion = {
        raw: "0.0.0",
        core: [0n, 0n, 0n],
        prerelease: []
      };
      this.channel = "latest";
      this.currentVersionValid = false;
    }
    this.fetchBytes = options.fetchBytes ?? fetchHttpsBytes;
    this.streamAsset = options.streamAsset ?? streamHttpsAsset;
    this.status = initialStatus(
      this.parsedCurrentVersion.raw,
      this.channel,
      "source-build"
    );
  }

  static async create(options: UpdateClientOptions): Promise<UpdateClient> {
    const client = new UpdateClient(options);
    await client.initialize();
    return client;
  }

  private async initialize(): Promise<void> {
    if (!this.options.packaged) {
      this.status = initialStatus(
        this.parsedCurrentVersion.raw,
        this.channel,
        "source-build"
      );
      return;
    }
    if (
      this.options.platform !== "darwin" ||
      this.options.architecture !== "arm64"
    ) {
      this.status = initialStatus(
        this.parsedCurrentVersion.raw,
        this.channel,
        "unsupported-platform"
      );
      return;
    }
    if (!this.currentVersionValid) {
      this.status = initialStatus(
        this.parsedCurrentVersion.raw,
        this.channel,
        "version-invalid"
      );
      return;
    }
    try {
      this.trustAnchor = await (
        this.options.loadTrustAnchor ??
        (() => loadBundledTrustAnchor(this.options.resourcesPath))
      )();
    } catch (error) {
      const reason: UpdateUnavailableReason =
        error instanceof UpdateClientError && error.code === "unavailable"
          ? "key-unprovisioned"
          : "key-invalid";
      this.status = initialStatus(
        this.parsedCurrentVersion.raw,
        this.channel,
        reason
      );
      return;
    }
    if (
      this.trustAnchor.publicKey.asymmetricKeyType !== "ed25519" ||
      !SHA256_PATTERN.test(this.trustAnchor.publicKeySha256)
    ) {
      this.trustAnchor = undefined;
      this.status = initialStatus(
        this.parsedCurrentVersion.raw,
        this.channel,
        "key-invalid"
      );
      return;
    }
    this.status = updateStatus(
      this.parsedCurrentVersion.raw,
      this.channel,
      "idle",
      { canCheck: true }
    );
  }

  getStatus(): UpdateStatus {
    return structuredClone(this.status);
  }

  subscribe(listener: (status: UpdateStatus) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private publish(status: UpdateStatus): UpdateStatus {
    this.status = status;
    const snapshot = this.getStatus();
    for (const listener of this.listeners) {
      listener(snapshot);
    }
    return snapshot;
  }

  private runOperation(
    kind: OperationKind,
    action: (signal: AbortSignal) => Promise<UpdateStatus>
  ): Promise<UpdateStatus> {
    if (this.shuttingDown) {
      return Promise.reject(new UpdateClientError("cancelled"));
    }
    if (this.active) {
      if (this.active.kind === kind) {
        return this.active.promise;
      }
      return Promise.reject(new UpdateClientError("busy"));
    }
    const controller = new AbortController();
    const promise = action(controller.signal).finally(() => {
      if (this.active?.promise === promise) {
        this.active = undefined;
      }
    });
    this.active = { kind, controller, promise };
    return promise;
  }

  private publishFailure(error: UpdateClientError): void {
    const candidate = this.candidate;
    this.publish(
      updateStatus(
        this.parsedCurrentVersion.raw,
        this.channel,
        "error",
        {
          availableVersion: candidate?.version ?? null,
          errorCode: error.code,
          canCheck: !this.shuttingDown && this.trustAnchor !== undefined,
          canDownloadOrOpen:
            !this.shuttingDown &&
            candidate !== undefined &&
            !["signature-invalid", "manifest-invalid", "asset-invalid"].includes(
              error.code
            ),
          canOpenReleasePage: !this.shuttingDown
        }
      )
    );
  }

  check(): Promise<UpdateStatus> {
    if (!this.trustAnchor || this.status.state === "unavailable") {
      return Promise.reject(new UpdateClientError("unavailable"));
    }
    return this.runOperation("check", async (signal) => {
      this.candidate = undefined;
      this.publish(
        updateStatus(
          this.parsedCurrentVersion.raw,
          this.channel,
          "checking"
        )
      );
      try {
        const metadataBytes = await this.fetchBytes(
          releaseApiUrl(this.channel),
          {
            maximumBytes: MAX_RELEASE_METADATA_BYTES,
            signal,
            purpose: { kind: "api", channel: this.channel }
          }
        );
        let metadata: unknown;
        try {
          metadata = JSON.parse(metadataBytes.toString("utf8"));
        } catch {
          throw new UpdateClientError("metadata-invalid");
        }
        const release = selectReleaseMetadata(
          metadata,
          this.parsedCurrentVersion,
          this.channel
        );
        if (!release) {
          return this.publish(
            updateStatus(
              this.parsedCurrentVersion.raw,
              this.channel,
              "up-to-date",
              { canCheck: true }
            )
          );
        }
        const manifestMetadata = release.assets.get(UPDATE_MANIFEST_NAME);
        const signatureMetadata = release.assets.get(UPDATE_SIGNATURE_NAME);
        if (
          !manifestMetadata ||
          !signatureMetadata ||
          manifestMetadata.size > MAX_UPDATE_MANIFEST_BYTES ||
          signatureMetadata.size !== 64
        ) {
          throw new UpdateClientError("metadata-invalid");
        }
        const [manifestBytes, signatureBytes] = await Promise.all([
          this.fetchBytes(
            releaseAssetUrl(release.tag, UPDATE_MANIFEST_NAME),
            {
              maximumBytes: MAX_UPDATE_MANIFEST_BYTES,
              expectedBytes: manifestMetadata.size,
              signal,
              purpose: {
                kind: "release-asset",
                tag: release.tag,
                name: UPDATE_MANIFEST_NAME
              }
            }
          ),
          this.fetchBytes(
            releaseAssetUrl(release.tag, UPDATE_SIGNATURE_NAME),
            {
              maximumBytes: 64,
              expectedBytes: 64,
              signal,
              purpose: {
                kind: "release-asset",
                tag: release.tag,
                name: UPDATE_SIGNATURE_NAME
              }
            }
          )
        ]);
        const candidate = verifyUpdateManifest(
          manifestBytes,
          signatureBytes,
          release,
          this.parsedCurrentVersion,
          this.channel,
          this.trustAnchor as UpdateTrustAnchor
        );
        this.candidate = candidate;
        return this.publish(
          updateStatus(
            this.parsedCurrentVersion.raw,
            this.channel,
            "available",
            {
              availableVersion: candidate.version,
              canCheck: true,
              canDownloadOrOpen: true
            }
          )
        );
      } catch (error) {
        const updateError =
          error instanceof UpdateClientError
            ? error
            : new UpdateClientError("metadata-invalid");
        this.publishFailure(updateError);
        throw updateError;
      }
    });
  }

  downloadOrOpen(): Promise<UpdateStatus> {
    if (!this.trustAnchor || this.status.state === "unavailable") {
      return Promise.reject(new UpdateClientError("unavailable"));
    }
    return this.runOperation("download-or-open", async (signal) => {
      const candidate = this.candidate;
      if (!candidate) {
        throw new UpdateClientError("asset-invalid");
      }
      let created: CreatedPartial | undefined;
      let handle: FileHandle | undefined;
      try {
        const directory =
          this.resolvedUpdateDirectory ??
          (await ensurePrivateDirectory(this.options.updateDirectory));
        this.resolvedUpdateDirectory = directory;
        const finalPath = path.join(directory, candidate.dmg.name);
        const partialPath = `${finalPath}.partial`;
        if (
          path.dirname(finalPath) !== directory ||
          path.basename(finalPath) !== candidate.dmg.name
        ) {
          throw new UpdateClientError("cache-unsafe");
        }
        let cached = await verifyRegularFile(
          finalPath,
          candidate.dmg.size,
          candidate.dmg.sha256,
          signal
        );
        if (!cached) {
          await removeStalePartial(finalPath);
          await removeStalePartial(partialPath);
          this.publish(
            updateStatus(
              this.parsedCurrentVersion.raw,
              this.channel,
              "downloading",
              {
                availableVersion: candidate.version,
                progress: {
                  receivedBytes: 0,
                  totalBytes: candidate.dmg.size
                }
              }
            )
          );
          handle = await open(
            partialPath,
            fsConstants.O_WRONLY |
              fsConstants.O_CREAT |
              fsConstants.O_EXCL |
              fsConstants.O_NOFOLLOW,
            0o600
          );
          const opened = await handle.stat();
          if (
            !opened.isFile() ||
            opened.nlink !== 1 ||
            opened.uid !==
              (process.geteuid?.() ?? process.getuid?.() ?? -1) ||
            (opened.mode & 0o077) !== 0 ||
            opened.size !== 0
          ) {
            throw new UpdateClientError("cache-unsafe");
          }
          created = {
            path: partialPath,
            device: opened.dev,
            inode: opened.ino
          };
          const digest = createHash("sha256");
          let received = 0;
          let lastPublished = 0;
          await this.streamAsset(candidate.downloadUrl, {
            maximumBytes: MAX_DMG_BYTES,
            expectedBytes: candidate.dmg.size,
            signal,
            purpose: {
              kind: "release-asset",
              tag: candidate.tag,
              name: candidate.dmg.name
            },
            onChunk: async (chunk) => {
              if (signal.aborted) {
                throw new UpdateClientError("cancelled");
              }
              received += chunk.length;
              if (
                received > candidate.dmg.size ||
                received > MAX_DMG_BYTES
              ) {
                throw new UpdateClientError("download-too-large");
              }
              await writeAll(handle as FileHandle, chunk);
              digest.update(chunk);
              if (
                received === candidate.dmg.size ||
                received - lastPublished >= 1024 * 1024
              ) {
                lastPublished = received;
                this.publish(
                  updateStatus(
                    this.parsedCurrentVersion.raw,
                    this.channel,
                    "downloading",
                    {
                      availableVersion: candidate.version,
                      progress: {
                        receivedBytes: received,
                        totalBytes: candidate.dmg.size
                      }
                    }
                  )
                );
              }
            }
          });
          if (
            received !== candidate.dmg.size ||
            digest.digest("hex") !== candidate.dmg.sha256
          ) {
            throw new UpdateClientError("digest-mismatch");
          }
          await handle.sync();
          await handle.close();
          handle = undefined;
          const completed = await lstat(partialPath);
          if (
            !created ||
            !completed.isFile() ||
            completed.isSymbolicLink() ||
            completed.nlink !== 1 ||
            completed.dev !== created.device ||
            completed.ino !== created.inode ||
            completed.size !== candidate.dmg.size
          ) {
            throw new UpdateClientError("cache-unsafe");
          }
          try {
            await lstat(finalPath);
            throw new UpdateClientError("cache-unsafe");
          } catch (error) {
            if (error instanceof UpdateClientError) {
              throw error;
            }
            const code =
              error && typeof error === "object" && "code" in error
                ? String(error.code)
                : "";
            if (code !== "ENOENT") {
              throw new UpdateClientError("cache-unsafe");
            }
          }
          await rename(partialPath, finalPath);
          created = undefined;
          await chmod(finalPath, 0o600);
          await fsyncDirectory(directory);
          cached = await verifyRegularFile(
            finalPath,
            candidate.dmg.size,
            candidate.dmg.sha256,
            signal
          );
          if (!cached) {
            throw new UpdateClientError("digest-mismatch");
          }
        }
        this.publish(
          updateStatus(
            this.parsedCurrentVersion.raw,
            this.channel,
            "ready",
            {
              availableVersion: candidate.version,
              canCheck: true,
              canDownloadOrOpen: true
            }
          )
        );

        // Revalidate immediately before crossing into Electron shell.
        const safeToOpen = await verifyRegularFile(
          finalPath,
          candidate.dmg.size,
          candidate.dmg.sha256,
          signal
        );
        if (!safeToOpen) {
          throw new UpdateClientError("cache-unsafe");
        }
        this.publish(
          updateStatus(
            this.parsedCurrentVersion.raw,
            this.channel,
            "opening",
            { availableVersion: candidate.version }
          )
        );
        let openError: string;
        try {
          openError = await this.options.openPath(finalPath);
        } catch {
          throw new UpdateClientError("open-failed");
        }
        if (openError !== "") {
          throw new UpdateClientError("open-failed");
        }
        return this.publish(
          updateStatus(
            this.parsedCurrentVersion.raw,
            this.channel,
            "opened",
            {
              availableVersion: candidate.version,
              canCheck: true,
              canDownloadOrOpen: true
            }
          )
        );
      } catch (error) {
        await handle?.close().catch(() => undefined);
        if (created) {
          await cleanupCreatedPartial(created);
        }
        const updateError = asUpdateError(error);
        this.publishFailure(updateError);
        throw updateError;
      }
    });
  }

  openReleasePage(): Promise<UpdateStatus> {
    if (!this.status.canOpenReleasePage) {
      return Promise.reject(new UpdateClientError("unavailable"));
    }
    return this.runOperation("open-release-page", async () => {
      try {
        await this.options.openExternal(CANONICAL_RELEASES_URL);
        return this.getStatus();
      } catch {
        throw new UpdateClientError("external-open-failed");
      }
    });
  }

  async cancel(): Promise<UpdateStatus> {
    const active = this.active;
    if (!active) {
      return this.getStatus();
    }
    active.controller.abort();
    await active.promise.catch(() => undefined);
    return this.getStatus();
  }

  async shutdown(): Promise<void> {
    this.shuttingDown = true;
    const active = this.active;
    active?.controller.abort();
    await active?.promise.catch(() => undefined);
    this.listeners.clear();
  }
}

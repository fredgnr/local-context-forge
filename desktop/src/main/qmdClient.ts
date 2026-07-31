import { randomUUID } from "node:crypto";
import http, {
  type ClientRequest,
  type IncomingMessage,
  type RequestOptions
} from "node:http";

export const QMD_WORKER_PROTOCOL_VERSION = "1.0" as const;
export const QMD_WORKER_VERSION = "2.5.3" as const;
export const QMD_NODE_VERSION = "22.23.2" as const;
export const MAX_QMD_COLLECTIONS = 256;
export const MAX_QMD_RESPONSE_BYTES = 2 * 1024 * 1024;

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const COLLECTION_PATTERN = /^[a-z0-9][a-z0-9._-]{0,118}$/;

export interface QmdConnection {
  socketPath: string;
  launchId: string;
  token: string;
  buildManifestSha256: string;
}

export interface QmdCollection {
  name: string;
  wiki_root: string;
}

export interface QmdHealth {
  service: "local-context-forge";
  role: "qmd-worker";
  protocol: { major: 1; minor: 0 };
  launch_id: string;
  transport: "uds";
  qmd_version: typeof QMD_WORKER_VERSION;
  node_version: typeof QMD_NODE_VERSION;
  build_manifest_sha256: string;
  revision: number | null;
  collections: number;
}

export interface QmdReconcileResponse {
  indexed: true;
  revision: number;
  collections: number;
  update: {
    indexed: number;
    updated: number;
    unchanged: number;
    removed: number;
  };
}

export interface QmdSearchResult {
  path: string;
  score: number;
  title: string;
}

export interface QmdSearchResponse {
  revision: number;
  results: QmdSearchResult[];
}

type RequestImplementation = (
  options: RequestOptions,
  callback: (response: IncomingMessage) => void
) => ClientRequest;

export class QmdClientError extends Error {
  constructor(
    readonly kind: "transport" | "invalid-response" | "remote",
    readonly code:
      | "transport"
      | "timeout"
      | "invalid_response"
      | "stale_index"
      | "too_many_collections"
      | "qmd_unavailable"
      | "worker_error"
  ) {
    super(`QMD worker request failed (${code})`);
    this.name = "QmdClientError";
  }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function exactKeys(
  value: Record<string, unknown>,
  expected: readonly string[]
): boolean {
  const keys = Object.keys(value);
  return (
    keys.length === expected.length &&
    keys.every((key) => expected.includes(key))
  );
}

function isRevision(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function isCount(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function isRelativePath(value: unknown): value is string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value !== value.normalize("NFC") ||
    value.startsWith("/") ||
    value.startsWith("\\") ||
    value.includes("\\") ||
    value.includes("\0") ||
    Buffer.byteLength(value, "utf8") > 800
  ) {
    return false;
  }
  return value
    .split("/")
    .every(
      (part) =>
        part.length > 0 &&
        part !== "." &&
        part !== ".." &&
        Buffer.byteLength(part, "utf8") <= 240
    );
}

export function isQmdCollectionName(value: unknown): value is string {
  return (
    typeof value === "string" &&
    COLLECTION_PATTERN.test(value) &&
    !value.includes("..")
  );
}

export function validateQmdCollections(
  value: readonly QmdCollection[]
): void {
  if (value.length > MAX_QMD_COLLECTIONS) {
    throw new QmdClientError("remote", "too_many_collections");
  }
  const names = new Set<string>();
  for (const collection of value) {
    if (
      !isPlainObject(collection) ||
      !exactKeys(collection, ["name", "wiki_root"]) ||
      !isQmdCollectionName(collection.name) ||
      !isRelativePath(collection.wiki_root) ||
      names.has(collection.name)
    ) {
      throw new QmdClientError("invalid-response", "invalid_response");
    }
    names.add(collection.name);
  }
}

function validateHealth(
  value: unknown,
  connection: QmdConnection
): QmdHealth {
  if (
    !isPlainObject(value) ||
    !exactKeys(value, [
      "service",
      "role",
      "protocol",
      "launch_id",
      "transport",
      "qmd_version",
      "node_version",
      "build_manifest_sha256",
      "revision",
      "collections"
    ]) ||
    value.service !== "local-context-forge" ||
    value.role !== "qmd-worker" ||
    !isPlainObject(value.protocol) ||
    !exactKeys(value.protocol, ["major", "minor"]) ||
    value.protocol.major !== 1 ||
    value.protocol.minor !== 0 ||
    value.launch_id !== connection.launchId ||
    value.transport !== "uds" ||
    value.qmd_version !== QMD_WORKER_VERSION ||
    value.node_version !== QMD_NODE_VERSION ||
    value.build_manifest_sha256 !== connection.buildManifestSha256 ||
    (value.revision !== null && !isRevision(value.revision)) ||
    !isCount(value.collections)
  ) {
    throw new QmdClientError("invalid-response", "invalid_response");
  }
  return value as unknown as QmdHealth;
}

function validateReconcile(
  value: unknown,
  expectedRevision: number,
  expectedCollections: number
): QmdReconcileResponse {
  if (
    !isPlainObject(value) ||
    !exactKeys(value, ["indexed", "revision", "collections", "update"]) ||
    value.indexed !== true ||
    value.revision !== expectedRevision ||
    value.collections !== expectedCollections ||
    !isPlainObject(value.update) ||
    !exactKeys(value.update, [
      "indexed",
      "updated",
      "unchanged",
      "removed"
    ]) ||
    !Object.values(value.update).every(isCount)
  ) {
    throw new QmdClientError("invalid-response", "invalid_response");
  }
  return value as unknown as QmdReconcileResponse;
}

function validateSearch(
  value: unknown,
  expectedRevision: number,
  limit: number
): QmdSearchResponse {
  if (
    !isPlainObject(value) ||
    !exactKeys(value, ["revision", "results"]) ||
    value.revision !== expectedRevision ||
    !Array.isArray(value.results) ||
    value.results.length > limit
  ) {
    throw new QmdClientError("invalid-response", "invalid_response");
  }
  const used = new Set<string>();
  for (const result of value.results) {
    if (
      !isPlainObject(result) ||
      !exactKeys(result, ["path", "score", "title"]) ||
      !isRelativePath(result.path) ||
      typeof result.score !== "number" ||
      !Number.isFinite(result.score) ||
      typeof result.title !== "string" ||
      Buffer.byteLength(result.title, "utf8") > 4_000 ||
      used.has(result.path)
    ) {
      throw new QmdClientError("invalid-response", "invalid_response");
    }
    used.add(result.path);
  }
  return value as unknown as QmdSearchResponse;
}

interface QmdClientDependencies {
  request?: RequestImplementation;
  now?: () => number;
  requestId?: () => string;
}

export class QmdClient {
  private readonly requestImplementation: RequestImplementation;
  private readonly now: () => number;
  private readonly requestId: () => string;

  constructor(
    private readonly connection: QmdConnection,
    dependencies: QmdClientDependencies = {}
  ) {
    if (
      !UUID_PATTERN.test(connection.launchId) ||
      !/^[A-Za-z0-9_-]{43}$/.test(connection.token) ||
      !SHA256_PATTERN.test(connection.buildManifestSha256)
    ) {
      throw new QmdClientError("invalid-response", "invalid_response");
    }
    this.requestImplementation = dependencies.request ?? http.request;
    this.now = dependencies.now ?? Date.now;
    this.requestId = dependencies.requestId ?? randomUUID;
  }

  async health(timeoutMs = 1_000): Promise<QmdHealth> {
    const response = await this.request("GET", "/health", undefined, timeoutMs);
    return validateHealth(response, this.connection);
  }

  async reconcile(
    revision: number,
    collections: readonly QmdCollection[],
    timeoutMs = 120_000
  ): Promise<QmdReconcileResponse> {
    if (!isRevision(revision)) {
      throw new QmdClientError("invalid-response", "invalid_response");
    }
    validateQmdCollections(collections);
    const response = await this.request(
      "POST",
      "/reconcile",
      { revision, collections },
      timeoutMs
    );
    return validateReconcile(response, revision, collections.length);
  }

  async search(
    input: {
      revision: number;
      collection: string;
      query: string;
      limit: number;
    },
    timeoutMs = 30_000
  ): Promise<QmdSearchResponse> {
    if (
      !isRevision(input.revision) ||
      !isQmdCollectionName(input.collection) ||
      typeof input.query !== "string" ||
      input.query.length === 0 ||
      input.query !== input.query.trim() ||
      Buffer.byteLength(input.query, "utf8") > 8 * 1024 ||
      !Number.isSafeInteger(input.limit) ||
      input.limit < 1 ||
      input.limit > 100
    ) {
      throw new QmdClientError("invalid-response", "invalid_response");
    }
    const response = await this.request("POST", "/search", input, timeoutMs);
    return validateSearch(response, input.revision, input.limit);
  }

  private request(
    method: "GET" | "POST",
    requestPath: string,
    body: Record<string, unknown> | undefined,
    timeoutMs: number
  ): Promise<unknown> {
    const payload =
      body === undefined ? undefined : Buffer.from(JSON.stringify(body), "utf8");
    const deadline = this.now() + timeoutMs;

    return new Promise((resolve, reject) => {
      let settled = false;
      let activeResponse: IncomingMessage | undefined;
      let request: ClientRequest | undefined;
      const timer = setTimeout(() => {
        if (!settled) {
          settled = true;
          activeResponse?.destroy();
          request?.destroy();
          reject(new QmdClientError("transport", "timeout"));
        }
      }, timeoutMs);
      request = this.requestImplementation(
        {
          socketPath: this.connection.socketPath,
          path: requestPath,
          method,
          agent: false,
          maxHeaderSize: 16 * 1024,
          headers: {
            Authorization: `Bearer ${this.connection.token}`,
            Accept: "application/json",
            ...(payload
              ? {
                  "Content-Type": "application/json",
                  "Content-Length": String(payload.length)
                }
              : {}),
            "X-LCF-Protocol-Version": QMD_WORKER_PROTOCOL_VERSION,
            "X-LCF-Launch-Id": this.connection.launchId,
            "X-LCF-Request-Id": this.requestId(),
            "X-LCF-Deadline-Ms": String(deadline)
          }
        },
        (response) => {
          activeResponse = response;
          const contentType = response.headers["content-type"];
          const normalizedContentType = Array.isArray(contentType)
            ? ""
            : (contentType ?? "").split(";", 1)[0]!.trim().toLowerCase();
          const declaredLength = response.headers["content-length"];
          if (
            normalizedContentType !== "application/json" ||
            (typeof declaredLength === "string" &&
              (!/^[0-9]+$/.test(declaredLength) ||
                Number(declaredLength) > MAX_QMD_RESPONSE_BYTES))
          ) {
            settled = true;
            clearTimeout(timer);
            response.destroy();
            reject(
              new QmdClientError("invalid-response", "invalid_response")
            );
            return;
          }
          const chunks: Buffer[] = [];
          let total = 0;
          response.on("data", (chunk: Buffer | string) => {
            const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
            total += buffer.length;
            if (total > MAX_QMD_RESPONSE_BYTES && !settled) {
              settled = true;
              clearTimeout(timer);
              response.destroy();
              reject(
                new QmdClientError("invalid-response", "invalid_response")
              );
              return;
            }
            chunks.push(buffer);
          });
          response.once("error", () => {
            if (!settled) {
              settled = true;
              clearTimeout(timer);
              reject(new QmdClientError("transport", "transport"));
            }
          });
          response.once("end", () => {
            if (settled) {
              return;
            }
            settled = true;
            clearTimeout(timer);
            let parsed: unknown;
            try {
              parsed = JSON.parse(
                Buffer.concat(chunks, total).toString("utf8")
              );
            } catch {
              reject(
                new QmdClientError("invalid-response", "invalid_response")
              );
              return;
            }
            const encoded = JSON.stringify(parsed);
            if (
              encoded.includes(this.connection.token) ||
              encoded.includes(this.connection.socketPath)
            ) {
              reject(
                new QmdClientError("invalid-response", "invalid_response")
              );
              return;
            }
            if (response.statusCode !== 200) {
              if (
                isPlainObject(parsed) &&
                exactKeys(parsed, ["error"]) &&
                typeof parsed.error === "string"
              ) {
                const code =
                  parsed.error === "stale_index"
                    ? "stale_index"
                    : parsed.error === "too_many_collections"
                      ? "too_many_collections"
                      : parsed.error === "qmd_unavailable"
                        ? "qmd_unavailable"
                        : "worker_error";
                reject(new QmdClientError("remote", code));
              } else {
                reject(
                  new QmdClientError("invalid-response", "invalid_response")
                );
              }
              return;
            }
            resolve(parsed);
          });
        }
      );
      request.once("error", () => {
        if (!settled) {
          settled = true;
          clearTimeout(timer);
          reject(new QmdClientError("transport", "transport"));
        }
      });
      request.setTimeout(timeoutMs, () => {
        if (!settled) {
          settled = true;
          clearTimeout(timer);
          request?.destroy();
          reject(new QmdClientError("transport", "timeout"));
        }
      });
      request.end(payload);
    });
  }
}

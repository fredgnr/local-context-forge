import {
  randomBytes as nodeRandomBytes,
  randomUUID,
  timingSafeEqual
} from "node:crypto";
import { chmod, lstat, realpath, unlink } from "node:fs/promises";
import http, {
  type IncomingMessage,
  type Server,
  type ServerResponse
} from "node:http";
import path from "node:path";
import {
  MAX_QMD_COLLECTIONS,
  QmdClientError,
  isQmdCollectionName,
  validateQmdCollections,
  type QmdClient,
  type QmdCollection
} from "./qmdClient";
import type { QmdSupervisor } from "./qmdSupervisor";

export const RETRIEVAL_BROKER_PROTOCOL_VERSION = "1.0" as const;
export const MAX_RETRIEVAL_REQUEST_BYTES = 256 * 1024;
export const MAX_RETRIEVAL_RESPONSE_BYTES = 2 * 1024 * 1024;
const MAX_UDS_PATH_BYTES = 100;
const BROKER_SOCKET_NAME = "broker.sock";
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export interface RetrievalBrokerSession {
  socketPath: string;
  capability: string;
  close(): Promise<void>;
}

export interface RetrievalBrokerSessionFactory {
  createSession(
    launchId: string,
    runtimeDirectory: string
  ): Promise<RetrievalBrokerSession>;
}

interface BrokerRequest {
  revision: number;
  collections?: QmdCollection[];
  collection?: string;
  query?: string;
  limit?: number;
}

class BrokerError extends Error {
  constructor(
    readonly status: number,
    readonly code:
      | "unauthorized"
      | "forbidden"
      | "protocol_mismatch"
      | "invalid_request"
      | "request_too_large"
      | "too_many_collections"
      | "stale_index"
      | "qmd_unavailable"
      | "invalid_response"
      | "broker_error"
  ) {
    super(`Retrieval broker request rejected (${code})`);
    this.name = "BrokerError";
  }
}

function effectiveUid(): number {
  return process.geteuid?.() ?? process.getuid?.() ?? -1;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function hasExactKeys(
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

function isRelativeWikiRoot(value: unknown): value is string {
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

function parseReconcile(value: unknown): {
  revision: number;
  collections: QmdCollection[];
} {
  if (
    !isPlainObject(value) ||
    !hasExactKeys(value, ["revision", "collections"]) ||
    !isRevision(value.revision) ||
    !Array.isArray(value.collections)
  ) {
    throw new BrokerError(422, "invalid_request");
  }
  if (value.collections.length > MAX_QMD_COLLECTIONS) {
    throw new BrokerError(422, "too_many_collections");
  }
  const collections: QmdCollection[] = [];
  const names = new Set<string>();
  for (const item of value.collections) {
    if (
      !isPlainObject(item) ||
      !hasExactKeys(item, ["name", "wiki_root"]) ||
      !isQmdCollectionName(item.name) ||
      !isRelativeWikiRoot(item.wiki_root) ||
      names.has(item.name)
    ) {
      throw new BrokerError(422, "invalid_request");
    }
    names.add(item.name);
    collections.push({ name: item.name, wiki_root: item.wiki_root });
  }
  return { revision: value.revision, collections };
}

function parseSearch(value: unknown): {
  revision: number;
  collection: string;
  query: string;
  limit: number;
} {
  if (
    !isPlainObject(value) ||
    !hasExactKeys(value, ["revision", "collection", "query", "limit"]) ||
    !isRevision(value.revision) ||
    !isQmdCollectionName(value.collection) ||
    typeof value.query !== "string" ||
    value.query.length === 0 ||
    value.query !== value.query.trim() ||
    value.query.includes("\0") ||
    Buffer.byteLength(value.query, "utf8") > 8 * 1024 ||
    typeof value.limit !== "number" ||
    !Number.isSafeInteger(value.limit) ||
    value.limit < 1 ||
    value.limit > 100
  ) {
    throw new BrokerError(422, "invalid_request");
  }
  return {
    revision: value.revision,
      collection: value.collection,
      query: value.query,
      limit: value.limit
  };
}

function headerValues(request: IncomingMessage, expectedName: string): string[] {
  const values: string[] = [];
  for (let index = 0; index < request.rawHeaders.length; index += 2) {
    if (request.rawHeaders[index]?.toLowerCase() === expectedName) {
      values.push(request.rawHeaders[index + 1] ?? "");
    }
  }
  return values;
}

function requiredHeader(request: IncomingMessage, name: string): string {
  const values = headerValues(request, name.toLowerCase());
  if (values.length !== 1 || values[0]!.length === 0) {
    throw new BrokerError(400, "invalid_request");
  }
  return values[0]!;
}

function validateHeaders(
  request: IncomingMessage,
  capability: string,
  launchId: string
): void {
  const authorization = requiredHeader(request, "authorization");
  const supplied = authorization.startsWith("Bearer ")
    ? authorization.slice("Bearer ".length)
    : "";
  const suppliedBytes = Buffer.from(supplied, "ascii");
  const expectedBytes = Buffer.from(capability, "ascii");
  if (
    suppliedBytes.length !== expectedBytes.length ||
    !timingSafeEqual(suppliedBytes, expectedBytes)
  ) {
    throw new BrokerError(401, "unauthorized");
  }
  if (
    requiredHeader(request, "x-lcf-protocol-version") !==
    RETRIEVAL_BROKER_PROTOCOL_VERSION
  ) {
    throw new BrokerError(426, "protocol_mismatch");
  }
  if (requiredHeader(request, "x-lcf-launch-id") !== launchId) {
    throw new BrokerError(403, "forbidden");
  }
  if (!UUID_PATTERN.test(requiredHeader(request, "x-lcf-request-id"))) {
    throw new BrokerError(400, "invalid_request");
  }
  const deadline = Number(requiredHeader(request, "x-lcf-deadline-ms"));
  const now = Date.now();
  if (
    !Number.isSafeInteger(deadline) ||
    deadline <= now ||
    deadline - now > 120_000
  ) {
    throw new BrokerError(deadline <= now ? 408 : 400, "invalid_request");
  }
}

async function readJsonBody(request: IncomingMessage): Promise<unknown> {
  const contentType = requiredHeader(request, "content-type")
    .split(";", 1)[0]!
    .trim()
    .toLowerCase();
  if (contentType !== "application/json") {
    throw new BrokerError(415, "invalid_request");
  }
  const declared = request.headers["content-length"];
  if (
    declared !== undefined &&
    (!/^[0-9]+$/.test(declared) ||
      Number(declared) > MAX_RETRIEVAL_REQUEST_BYTES)
  ) {
    throw new BrokerError(413, "request_too_large");
  }
  const chunks: Buffer[] = [];
  let total = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    total += buffer.length;
    if (total > MAX_RETRIEVAL_REQUEST_BYTES) {
      throw new BrokerError(413, "request_too_large");
    }
    chunks.push(buffer);
  }
  try {
    return JSON.parse(Buffer.concat(chunks, total).toString("utf8"));
  } catch {
    throw new BrokerError(400, "invalid_request");
  }
}

function sendJson(
  response: ServerResponse,
  status: number,
  value: Record<string, unknown>
): void {
  const payload = Buffer.from(JSON.stringify(value), "utf8");
  if (payload.length > MAX_RETRIEVAL_RESPONSE_BYTES) {
    throw new BrokerError(500, "broker_error");
  }
  response.writeHead(status, {
    "Cache-Control": "no-store",
    Connection: "close",
    "Content-Length": String(payload.length),
    "Content-Type": "application/json",
    "X-Content-Type-Options": "nosniff"
  });
  response.end(payload);
}

function isWithin(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return (
    relative !== "" &&
    relative !== ".." &&
    !relative.startsWith(`..${path.sep}`) &&
    !path.isAbsolute(relative)
  );
}

export async function resolveBrokerWikiRoot(
  wikiRoot: string,
  relativeRoot: string
): Promise<string> {
  if (!path.isAbsolute(wikiRoot) || !isRelativeWikiRoot(relativeRoot)) {
    throw new BrokerError(422, "invalid_request");
  }
  const rootInfo = await lstat(wikiRoot).catch(() => undefined);
  if (!rootInfo?.isDirectory() || rootInfo.isSymbolicLink()) {
    throw new BrokerError(422, "invalid_request");
  }
  const canonicalRoot = await realpath(wikiRoot);
  if (canonicalRoot !== wikiRoot) {
    throw new BrokerError(422, "invalid_request");
  }
  let candidate = canonicalRoot;
  for (const part of relativeRoot.split("/")) {
    candidate = path.join(candidate, part);
    if (!isWithin(canonicalRoot, candidate)) {
      throw new BrokerError(422, "invalid_request");
    }
    const info = await lstat(candidate).catch(() => undefined);
    if (!info?.isDirectory() || info.isSymbolicLink()) {
      throw new BrokerError(422, "invalid_request");
    }
  }
  const resolved = await realpath(candidate);
  if (resolved !== candidate || !isWithin(canonicalRoot, resolved)) {
    throw new BrokerError(422, "invalid_request");
  }
  return resolved;
}

function translateQmdError(error: unknown): BrokerError {
  if (!(error instanceof QmdClientError)) {
    return new BrokerError(503, "qmd_unavailable");
  }
  if (error.code === "stale_index") {
    return new BrokerError(409, "stale_index");
  }
  if (error.code === "too_many_collections") {
    return new BrokerError(422, "too_many_collections");
  }
  if (error.kind === "invalid-response") {
    return new BrokerError(502, "invalid_response");
  }
  return new BrokerError(503, "qmd_unavailable");
}

interface RetrievalBrokerDependencies {
  randomBytes?: (size: number) => Buffer;
}

export class RetrievalBroker implements RetrievalBrokerSessionFactory {
  private revision: number | undefined;
  private allowlist = new Set<string>();
  private readonly randomBytes: (size: number) => Buffer;

  constructor(
    private readonly supervisor: Pick<
      QmdSupervisor,
      "getClient" | "start" | "restart"
    >,
    private readonly wikiRoot: string,
    dependencies: RetrievalBrokerDependencies = {}
  ) {
    this.randomBytes = dependencies.randomBytes ?? nodeRandomBytes;
  }

  async createSession(
    launchId: string,
    runtimeDirectory: string
  ): Promise<RetrievalBrokerSession> {
    if (!UUID_PATTERN.test(launchId) || !path.isAbsolute(runtimeDirectory)) {
      throw new BrokerError(400, "invalid_request");
    }
    const directoryInfo = await lstat(runtimeDirectory).catch(() => undefined);
    if (
      !directoryInfo?.isDirectory() ||
      directoryInfo.isSymbolicLink() ||
      directoryInfo.uid !== effectiveUid() ||
      (directoryInfo.mode & 0o777) !== 0o700 ||
      (await realpath(runtimeDirectory)) !== runtimeDirectory
    ) {
      throw new BrokerError(400, "invalid_request");
    }
    const socketPath = path.join(runtimeDirectory, BROKER_SOCKET_NAME);
    if (
      Buffer.byteLength(socketPath, "utf8") > MAX_UDS_PATH_BYTES ||
      (await lstat(socketPath).catch(() => undefined))
    ) {
      throw new BrokerError(400, "invalid_request");
    }
    const rawCapability = this.randomBytes(32);
    if (rawCapability.length !== 32) {
      rawCapability.fill(0);
      throw new BrokerError(500, "broker_error");
    }
    let capability = rawCapability.toString("base64url");
    rawCapability.fill(0);
    if (capability.length !== 43) {
      capability = "";
      throw new BrokerError(500, "broker_error");
    }

    const server = this.createServer(launchId, () => capability);
    const identity = await this.listen(server, socketPath);
    let closed = false;
    const brokerSession: RetrievalBrokerSession = {
      socketPath,
      capability,
      close: async () => {
        if (closed) {
          return;
        }
        closed = true;
        capability = "";
        brokerSession.capability = "";
        await this.closeServer(server, socketPath, identity);
      }
    };
    return brokerSession;
  }

  private createServer(
    launchId: string,
    capability: () => string
  ): Server {
    return http.createServer(
      {
        keepAlive: false,
        maxHeaderSize: 16 * 1024,
        requestTimeout: 120_000
      },
      async (request, response) => {
        try {
          validateHeaders(request, capability(), launchId);
          const url = new URL(request.url ?? "", "http://localhost");
          if (
            request.method !== "POST" ||
            (url.pathname !== "/reconcile" && url.pathname !== "/search") ||
            url.search ||
            url.hash
          ) {
            throw new BrokerError(404, "invalid_request");
          }
          const body = await readJsonBody(request);
          const result =
            url.pathname === "/reconcile"
              ? await this.reconcile(parseReconcile(body))
              : await this.search(parseSearch(body));
          sendJson(response, 200, result);
        } catch (error) {
          const rejected =
            error instanceof BrokerError
              ? error
              : new BrokerError(500, "broker_error");
          if (!response.headersSent) {
            sendJson(response, rejected.status, { error: rejected.code });
          } else {
            response.destroy();
          }
        }
      }
    );
  }

  private async client(): Promise<QmdClient> {
    let client = this.supervisor.getClient();
    if (!client) {
      await this.supervisor.start();
      client = this.supervisor.getClient();
    }
    if (!client) {
      throw new BrokerError(503, "qmd_unavailable");
    }
    return client;
  }

  private async reconcile(input: {
    revision: number;
    collections: QmdCollection[];
  }): Promise<Record<string, unknown>> {
    validateQmdCollections(input.collections);
    for (const collection of input.collections) {
      await resolveBrokerWikiRoot(this.wikiRoot, collection.wiki_root);
    }
    const client = await this.client();
    let response;
    try {
      response = await client.reconcile(input.revision, input.collections);
    } catch (error) {
      // Reconcile is intentionally sent once. A transport failure is surfaced
      // to Python and never replayed across a worker restart.
      throw translateQmdError(error);
    }
    this.revision = response.revision;
    this.allowlist = new Set(input.collections.map((item) => item.name));
    return response as unknown as Record<string, unknown>;
  }

  private async search(input: {
    revision: number;
    collection: string;
    query: string;
    limit: number;
  }): Promise<Record<string, unknown>> {
    if (
      this.revision === undefined ||
      input.revision !== this.revision ||
      !this.allowlist.has(input.collection)
    ) {
      throw new BrokerError(409, "stale_index");
    }
    let client = await this.client();
    try {
      return (await client.search(input)) as unknown as Record<string, unknown>;
    } catch (error) {
      if (!(error instanceof QmdClientError) || error.kind !== "transport") {
        throw translateQmdError(error);
      }
    }

    // Search is the only operation which gets one bounded restart and one
    // retry. Persisted worker state supplies the committed revision/allowlist.
    await this.supervisor.restart();
    client = this.supervisor.getClient() as QmdClient;
    if (!client) {
      throw new BrokerError(503, "qmd_unavailable");
    }
    try {
      return (await client.search(input)) as unknown as Record<string, unknown>;
    } catch (error) {
      throw translateQmdError(error);
    }
  }

  private async listen(
    server: Server,
    socketPath: string
  ): Promise<{ device: number; inode: number }> {
    await new Promise<void>((resolve, reject) => {
      const onError = (error: Error) => {
        server.off("listening", onListening);
        reject(error);
      };
      const onListening = () => {
        server.off("error", onError);
        resolve();
      };
      server.once("error", onError);
      server.once("listening", onListening);
      server.listen(socketPath);
    });
    await chmod(socketPath, 0o600);
    const info = await lstat(socketPath);
    if (
      !info.isSocket() ||
      info.isSymbolicLink() ||
      info.uid !== effectiveUid() ||
      (info.mode & 0o777) !== 0o600
    ) {
      throw new BrokerError(500, "broker_error");
    }
    return { device: info.dev, inode: info.ino };
  }

  private async closeServer(
    server: Server,
    socketPath: string,
    identity: { device: number; inode: number }
  ): Promise<void> {
    const closed = new Promise<void>((resolve) =>
      server.close(() => resolve())
    );
    server.closeAllConnections();
    await closed;
    const info = await lstat(socketPath).catch(() => undefined);
    if (
      info?.isSocket() &&
      !info.isSymbolicLink() &&
      info.dev === identity.device &&
      info.ino === identity.inode
    ) {
      await unlink(socketPath).catch((error: NodeJS.ErrnoException) => {
        if (error.code !== "ENOENT") {
          throw error;
        }
      });
    }
  }
}

export const createBrokerRequestId = randomUUID;

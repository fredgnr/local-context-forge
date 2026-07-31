import {
  randomBytes as nodeRandomBytes,
  randomUUID as nodeRandomUUID,
  timingSafeEqual
} from "node:crypto";
import {
  constants as fsConstants
} from "node:fs";
import {
  chmod,
  lstat,
  mkdtemp,
  open,
  realpath,
  rename,
  rmdir,
  unlink
} from "node:fs/promises";
import http, {
  type IncomingMessage,
  type Server,
  type ServerResponse
} from "node:http";
import path from "node:path";
import type { Socket } from "node:net";
import {
  MAX_MCP_BRIDGE_REQUEST_BYTES,
  MAX_MCP_BRIDGE_RESPONSE_BYTES,
  MAX_MCP_LIBRARY_NAME_BYTES,
  MAX_MCP_QUERY_BYTES,
  MCP_BRIDGE_PROTOCOL_VERSION,
  MCP_BRIDGE_SOCKET_NAME,
  MCP_LAUNCH_FILE_NAME,
  MCP_RENDEZVOUS_FILE_NAME,
  MCP_RUNTIME_DIRECTORY_PREFIX,
  hasExactKeys,
  isBoundedText,
  isCorpusRevision,
  isMcpLibraryId,
  isPlainObject,
  type McpBridgeAuthorization,
  type McpBridgeErrorBody,
  type McpBridgeErrorCode,
  type McpClientDescriptor,
  type McpQueryInput,
  type McpResolveInput
} from "../mcpProtocol";
import {
  McpReadError,
  type McpReadPort
} from "./mcpSidecarRead";

const MAX_UDS_PATH_BYTES = 100;
const MAX_RENDEZVOUS_BYTES = 4 * 1024;
const DEFAULT_AUTHORIZATION_TIMEOUT_MS = 30_000;
const DEFAULT_OPERATION_TIMEOUT_MS = 120_000;
const DEFAULT_SESSION_LIFETIME_MS = 8 * 60 * 60 * 1_000;
const DEFAULT_SHUTDOWN_TIMEOUT_MS = 2_000;
const MAX_ACTIVE_SESSIONS = 4;
const MAX_PENDING_AUTHORIZATIONS = 1;
const MAX_REQUESTS_PER_MINUTE = 30;
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export interface McpBridgePaths {
  launchFilePath: string;
  launchId: string;
  rendezvousPath: string;
  runtimeDirectory: string;
  socketPath: string;
}

export interface McpBridgeClientState {
  authorizedAt: number;
  client: McpClientDescriptor;
  expiresAt: number;
  sessionId: string;
}

export interface McpBridgeServerOptions {
  authorizeClient: (
    client: McpClientDescriptor,
    signal: AbortSignal
  ) => Promise<boolean>;
  dataDir: string;
  tempRoot: string;
  readService: McpReadPort;
  authorizationTimeoutMs?: number;
  operationTimeoutMs?: number;
  sessionLifetimeMs?: number;
  shutdownTimeoutMs?: number;
}

export interface McpBridgeServerDependencies {
  createServer?: (
    handler: (
      request: IncomingMessage,
      response: ServerResponse
    ) => void
  ) => Server;
  now?: () => number;
  randomBytes?: (size: number) => Buffer;
  randomUUID?: () => string;
}

interface BridgeSession {
  activeAbort?: AbortController;
  activeRequest: boolean;
  authorizedAt: number;
  capability: string;
  client: McpClientDescriptor;
  expiresAt: number;
  rateRemaining: number;
  rateResetAt: number;
  sessionId: string;
  socket: Socket;
}

class BridgeFailure extends Error {
  constructor(
    readonly status: number,
    readonly code: McpBridgeErrorCode
  ) {
    super(`MCP bridge request rejected (${code})`);
    this.name = "BridgeFailure";
  }
}

function effectiveUid(): number {
  return process.geteuid?.() ?? process.getuid?.() ?? -1;
}

function fail(status: number, code: McpBridgeErrorCode): never {
  throw new BridgeFailure(status, code);
}

function requireAbsoluteNormalized(value: string): string {
  if (
    !path.isAbsolute(value) ||
    path.normalize(value) !== value ||
    value.includes("\0")
  ) {
    fail(500, "unavailable");
  }
  return value;
}

function isDirectRuntimeDirectory(
  tempRoot: string,
  runtimeDirectory: string
): boolean {
  return (
    path.dirname(runtimeDirectory) === tempRoot &&
    path.basename(runtimeDirectory).startsWith(
      MCP_RUNTIME_DIRECTORY_PREFIX
    ) &&
    /^lcf-mcp-[A-Za-z0-9_-]{6,80}$/.test(
      path.basename(runtimeDirectory)
    )
  );
}

export function resolveMcpBridgePaths(
  dataDir: string,
  runtimeDirectory: string,
  launchId: string
): McpBridgePaths {
  requireAbsoluteNormalized(dataDir);
  requireAbsoluteNormalized(runtimeDirectory);
  if (!UUID_PATTERN.test(launchId)) {
    fail(500, "unavailable");
  }
  const socketPath = path.join(runtimeDirectory, MCP_BRIDGE_SOCKET_NAME);
  if (Buffer.byteLength(socketPath, "utf8") > MAX_UDS_PATH_BYTES) {
    fail(500, "unavailable");
  }
  return {
    launchFilePath: path.join(
      runtimeDirectory,
      MCP_LAUNCH_FILE_NAME
    ),
    launchId,
    rendezvousPath: path.join(dataDir, MCP_RENDEZVOUS_FILE_NAME),
    runtimeDirectory,
    socketPath
  };
}

async function verifyPrivateDirectory(
  directory: string,
  allowChmod = false
): Promise<void> {
  const info = await lstat(directory).catch(() => undefined);
  if (
    !info?.isDirectory() ||
    info.isSymbolicLink() ||
    info.uid !== effectiveUid()
  ) {
    fail(500, "unavailable");
  }
  if (allowChmod) {
    await chmod(directory, 0o700);
  }
  const verified = await lstat(directory);
  if (
    (verified.mode & 0o777) !== 0o700 ||
    (await realpath(directory)) !== directory
  ) {
    fail(500, "unavailable");
  }
}

async function writePrivateFile(
  filePath: string,
  value: Record<string, unknown>
): Promise<void> {
  const payload = Buffer.from(`${JSON.stringify(value)}\n`, "utf8");
  if (payload.length > MAX_RENDEZVOUS_BYTES) {
    fail(500, "unavailable");
  }
  const handle = await open(
    filePath,
    fsConstants.O_WRONLY |
      fsConstants.O_CREAT |
      fsConstants.O_EXCL |
      fsConstants.O_NOFOLLOW,
    0o600
  ).catch(() => fail(500, "unavailable"));
  try {
    await handle.writeFile(payload);
    await handle.sync();
    await handle.chmod(0o600);
    const info = await handle.stat();
    if (
      !info.isFile() ||
      info.size !== payload.length ||
      info.uid !== effectiveUid() ||
      (info.mode & 0o777) !== 0o600
    ) {
      fail(500, "unavailable");
    }
  } finally {
    await handle.close().catch(() => undefined);
  }
}

async function readPrivateFile(filePath: string): Promise<unknown> {
  const handle = await open(
    filePath,
    fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW
  ).catch(() => fail(500, "unavailable"));
  try {
    const info = await handle.stat();
    if (
      !info.isFile() ||
      info.isSymbolicLink() ||
      info.uid !== effectiveUid() ||
      (info.mode & 0o777) !== 0o600 ||
      info.size <= 0 ||
      info.size > MAX_RENDEZVOUS_BYTES
    ) {
      fail(500, "unavailable");
    }
    const bytes = Buffer.alloc(info.size);
    const { bytesRead } = await handle.read(bytes, 0, info.size, 0);
    if (bytesRead !== info.size) {
      fail(500, "unavailable");
    }
    return JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(bytes)
    );
  } catch (error) {
    if (error instanceof BridgeFailure) {
      throw error;
    }
    fail(500, "unavailable");
  } finally {
    await handle.close().catch(() => undefined);
  }
}

function parseRendezvous(value: unknown): string {
  if (
    !isPlainObject(value) ||
    !hasExactKeys(value, ["runtimeDirectory", "schemaVersion"]) ||
    value.schemaVersion !== 1 ||
    typeof value.runtimeDirectory !== "string"
  ) {
    fail(500, "unavailable");
  }
  return requireAbsoluteNormalized(value.runtimeDirectory);
}

async function removeVerifiedRendezvous(
  rendezvousPath: string,
  expectedRuntimeDirectory?: string
): Promise<void> {
  const info = await lstat(rendezvousPath).catch(
    (error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") {
        return undefined;
      }
      throw error;
    }
  );
  if (!info) {
    return;
  }
  if (
    !info.isFile() ||
    info.isSymbolicLink() ||
    info.uid !== effectiveUid() ||
    (info.mode & 0o777) !== 0o600 ||
    (await realpath(rendezvousPath)) !== rendezvousPath
  ) {
    fail(500, "unavailable");
  }
  if (
    expectedRuntimeDirectory !== undefined &&
    parseRendezvous(await readPrivateFile(rendezvousPath)) !==
      expectedRuntimeDirectory
  ) {
    return;
  }
  await unlink(rendezvousPath);
}

export async function prepareMcpBridgeRuntime(
  dataDir: string,
  tempRoot: string,
  launchId: string = nodeRandomUUID()
): Promise<McpBridgePaths> {
  requireAbsoluteNormalized(dataDir);
  requireAbsoluteNormalized(tempRoot);
  await verifyPrivateDirectory(dataDir);
  const lexicalTempInfo = await lstat(tempRoot).catch(() => undefined);
  if (
    !lexicalTempInfo?.isDirectory() ||
    lexicalTempInfo.isSymbolicLink() ||
    lexicalTempInfo.uid !== effectiveUid()
  ) {
    fail(500, "unavailable");
  }
  const canonicalTempRoot = await realpath(tempRoot).catch(() =>
    fail(500, "unavailable")
  );
  requireAbsoluteNormalized(canonicalTempRoot);
  await verifyPrivateDirectory(canonicalTempRoot);
  await removeVerifiedRendezvous(
    path.join(dataDir, MCP_RENDEZVOUS_FILE_NAME)
  );
  const runtimeDirectory = await mkdtemp(
    path.join(canonicalTempRoot, MCP_RUNTIME_DIRECTORY_PREFIX)
  ).catch(() => fail(500, "unavailable"));
  let paths: McpBridgePaths | undefined;
  try {
    await chmod(runtimeDirectory, 0o700);
    const canonicalRuntimeDirectory = await realpath(runtimeDirectory);
    if (
      canonicalRuntimeDirectory !== runtimeDirectory ||
      !isDirectRuntimeDirectory(canonicalTempRoot, runtimeDirectory)
    ) {
      fail(500, "unavailable");
    }
    await verifyPrivateDirectory(runtimeDirectory);
    paths = resolveMcpBridgePaths(
      dataDir,
      runtimeDirectory,
      launchId
    );
    await writePrivateFile(paths.launchFilePath, {
      launchId,
      schemaVersion: 1,
      socketName: MCP_BRIDGE_SOCKET_NAME
    });
    return paths;
  } catch (error) {
    if (paths) {
      await unlink(paths.launchFilePath).catch(() => undefined);
    }
    await verifyPrivateDirectory(runtimeDirectory)
      .then(() => rmdir(runtimeDirectory))
      .catch(() => undefined);
    throw error;
  }
}

async function publishMcpRendezvous(
  paths: McpBridgePaths,
  temporaryName: string
): Promise<void> {
  if (!UUID_PATTERN.test(temporaryName)) {
    fail(500, "unavailable");
  }
  const temporaryPath = `${paths.rendezvousPath}.${temporaryName}.tmp`;
  await writePrivateFile(temporaryPath, {
    runtimeDirectory: paths.runtimeDirectory,
    schemaVersion: 1
  });
  try {
    await rename(temporaryPath, paths.rendezvousPath);
  } catch {
    await unlink(temporaryPath).catch(() => undefined);
    fail(500, "unavailable");
  }
  const info = await lstat(paths.rendezvousPath);
  if (
    !info.isFile() ||
    info.isSymbolicLink() ||
    info.uid !== effectiveUid() ||
    (info.mode & 0o777) !== 0o600 ||
    (await realpath(paths.rendezvousPath)) !== paths.rendezvousPath
  ) {
    fail(500, "unavailable");
  }
}

async function cleanupMcpBridgeRuntime(
  paths: McpBridgePaths
): Promise<void> {
  await removeVerifiedRendezvous(
    paths.rendezvousPath,
    paths.runtimeDirectory
  );
  const info = await lstat(paths.socketPath).catch(
    (error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") {
        return undefined;
      }
      throw error;
    }
  );
  if (info) {
    if (
      path.dirname(paths.socketPath) !== paths.runtimeDirectory ||
      path.basename(paths.socketPath) !== MCP_BRIDGE_SOCKET_NAME ||
      !info.isSocket() ||
      info.isSymbolicLink() ||
      info.uid !== effectiveUid() ||
      (info.mode & 0o777) !== 0o600
    ) {
      fail(500, "unavailable");
    }
    await unlink(paths.socketPath);
  }
  const launch = await lstat(paths.launchFilePath).catch(
    (error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") {
        return undefined;
      }
      throw error;
    }
  );
  if (launch) {
    if (
      !launch.isFile() ||
      launch.isSymbolicLink() ||
      launch.uid !== effectiveUid() ||
      (launch.mode & 0o777) !== 0o600 ||
      (await realpath(paths.launchFilePath)) !== paths.launchFilePath
    ) {
      fail(500, "unavailable");
    }
    await unlink(paths.launchFilePath);
  }
  await verifyPrivateDirectory(paths.runtimeDirectory);
  await rmdir(paths.runtimeDirectory);
}

function headerValues(
  request: IncomingMessage,
  expectedName: string
): string[] {
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
    fail(400, "invalid_request");
  }
  return values[0]!;
}

function validateCommonHeaders(
  request: IncomingMessage,
  now: number,
  maximumDeadlineMs: number
): number {
  if (
    requiredHeader(request, "x-lcf-mcp-protocol-version") !==
    MCP_BRIDGE_PROTOCOL_VERSION
  ) {
    fail(426, "protocol_mismatch");
  }
  if (!UUID_PATTERN.test(requiredHeader(request, "x-lcf-request-id"))) {
    fail(400, "invalid_request");
  }
  const deadline = Number(requiredHeader(request, "x-lcf-deadline-ms"));
  if (
    !Number.isSafeInteger(deadline) ||
    deadline <= now ||
    deadline - now > maximumDeadlineMs
  ) {
    fail(deadline <= now ? 408 : 400, deadline <= now ? "timeout" : "invalid_request");
  }
  return deadline;
}

async function readJsonBody(request: IncomingMessage): Promise<unknown> {
  const contentType = requiredHeader(request, "content-type")
    .split(";", 1)[0]!
    .trim()
    .toLowerCase();
  if (contentType !== "application/json") {
    fail(415, "invalid_request");
  }
  const declared = request.headers["content-length"];
  if (
    declared !== undefined &&
    (!/^[0-9]+$/.test(declared) ||
      Number(declared) > MAX_MCP_BRIDGE_REQUEST_BYTES)
  ) {
    fail(413, "request_too_large");
  }
  const chunks: Buffer[] = [];
  let total = 0;
  for await (const chunk of request) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    total += bytes.length;
    if (total > MAX_MCP_BRIDGE_REQUEST_BYTES) {
      fail(413, "request_too_large");
    }
    chunks.push(bytes);
  }
  if (total === 0) {
    fail(400, "invalid_request");
  }
  try {
    return JSON.parse(Buffer.concat(chunks, total).toString("utf8"));
  } catch {
    fail(400, "invalid_request");
  }
}

function sendJson(
  response: ServerResponse,
  status: number,
  value: Record<string, unknown>
): void {
  const payload = Buffer.from(JSON.stringify(value), "utf8");
  if (payload.length > MAX_MCP_BRIDGE_RESPONSE_BYTES) {
    fail(500, "invalid_response");
  }
  response.writeHead(status, {
    "Cache-Control": "no-store",
    Connection: "keep-alive",
    "Content-Length": String(payload.length),
    "Content-Type": "application/json",
    "X-Content-Type-Options": "nosniff"
  });
  response.end(payload);
}

function sendFailure(response: ServerResponse, error: BridgeFailure): void {
  if (response.headersSent || response.destroyed) {
    response.destroy();
    return;
  }
  const body: McpBridgeErrorBody = {
    error: { code: error.code }
  };
  try {
    sendJson(response, error.status, body as unknown as Record<string, unknown>);
  } catch {
    response.destroy();
  }
}

function parseClientDescriptor(value: unknown): McpClientDescriptor {
  if (
    !isPlainObject(value) ||
    !hasExactKeys(value, ["client"]) ||
    !isPlainObject(value.client) ||
    !hasExactKeys(value.client, ["name", "version"]) ||
    !isBoundedText(value.client.name, 256) ||
    !isBoundedText(value.client.version, 128) ||
    /[\r\n\u0001-\u001f\u007f]/.test(value.client.name) ||
    /[\r\n\u0001-\u001f\u007f]/.test(value.client.version)
  ) {
    fail(422, "invalid_request");
  }
  return {
    name: value.client.name,
    version: value.client.version
  };
}

function parseResolveInput(value: unknown): McpResolveInput {
  if (
    !isPlainObject(value) ||
    !hasExactKeys(value, ["corpusRevision", "libraryName", "query"]) ||
    !isCorpusRevision(value.corpusRevision) ||
    !isBoundedText(
      value.libraryName,
      MAX_MCP_LIBRARY_NAME_BYTES
    ) ||
    value.libraryName.trim() !== value.libraryName ||
    !isBoundedText(value.query, MAX_MCP_QUERY_BYTES, true) ||
    value.query.trim() !== value.query
  ) {
    fail(422, "invalid_request");
  }
  return {
    corpusRevision: value.corpusRevision,
    libraryName: value.libraryName,
    query: value.query
  };
}

function parseQueryInput(value: unknown): McpQueryInput {
  if (
    !isPlainObject(value) ||
    !hasExactKeys(value, ["corpusRevision", "libraryId", "query"]) ||
    !isCorpusRevision(value.corpusRevision) ||
    !isMcpLibraryId(value.libraryId) ||
    !isBoundedText(value.query, MAX_MCP_QUERY_BYTES) ||
    value.query.trim() !== value.query
  ) {
    fail(422, "invalid_request");
  }
  return {
    corpusRevision: value.corpusRevision,
    libraryId: value.libraryId,
    query: value.query
  };
}

function safeReadFailure(error: unknown): BridgeFailure {
  if (error instanceof BridgeFailure) {
    return error;
  }
  if (error instanceof McpReadError) {
    const statuses: Partial<Record<McpBridgeErrorCode, number>> = {
      busy: 429,
      invalid_request: 422,
      invalid_response: 502,
      not_found: 404,
      stale_revision: 409,
      timeout: 504,
      unavailable: 503
    };
    return new BridgeFailure(statuses[error.code] ?? 503, error.code);
  }
  return new BridgeFailure(503, "backend_unavailable");
}

function withAbortDeadline<T>(
  operation: (signal: AbortSignal) => Promise<T>,
  deadline: number,
  now: () => number,
  session?: BridgeSession
): Promise<T> {
  const remaining = deadline - now();
  if (remaining <= 0) {
    return Promise.reject(new BridgeFailure(408, "timeout"));
  }
  const controller = new AbortController();
  if (session) {
    session.activeAbort = controller;
  }
  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) {
        return;
      }
      settled = true;
      controller.abort();
      reject(new BridgeFailure(504, "timeout"));
    }, remaining);
    void operation(controller.signal).then(
      (value) => {
        if (!settled) {
          settled = true;
          clearTimeout(timer);
          resolve(value);
        }
      },
      (error: unknown) => {
        if (!settled) {
          settled = true;
          clearTimeout(timer);
          reject(error);
        }
      }
    ).finally(() => {
      if (session?.activeAbort === controller) {
        delete session.activeAbort;
      }
    });
  });
}

function defaultCreateServer(
  handler: (
    request: IncomingMessage,
    response: ServerResponse
  ) => void
): Server {
  return http.createServer(
    {
      headersTimeout: 10_000,
      keepAliveTimeout: DEFAULT_SESSION_LIFETIME_MS,
      maxHeaderSize: 16 * 1024,
      requestTimeout: DEFAULT_OPERATION_TIMEOUT_MS + 5_000
    },
    handler
  );
}

export class McpBridgeServer {
  private readonly dependencies: Required<McpBridgeServerDependencies>;
  private paths: McpBridgePaths | undefined;
  private readonly sessions = new Map<string, BridgeSession>();
  private readonly socketSessions = new WeakMap<Socket, BridgeSession>();
  private readonly pendingSockets = new WeakSet<Socket>();
  private readonly connections = new Set<Socket>();
  private server: Server | undefined;
  private pendingAuthorizations = 0;
  private globalActiveRequests = 0;
  private operation: Promise<void> | undefined;

  constructor(
    private readonly options: McpBridgeServerOptions,
    dependencies: McpBridgeServerDependencies = {}
  ) {
    this.dependencies = {
      createServer: dependencies.createServer ?? defaultCreateServer,
      now: dependencies.now ?? Date.now,
      randomBytes: dependencies.randomBytes ?? nodeRandomBytes,
      randomUUID: dependencies.randomUUID ?? nodeRandomUUID
    };
  }

  getSocketPath(): string {
    if (!this.paths) {
      fail(500, "unavailable");
    }
    return this.paths.socketPath;
  }

  getLaunchId(): string {
    if (!this.paths) {
      fail(500, "unavailable");
    }
    return this.paths.launchId;
  }

  listClients(): McpBridgeClientState[] {
    return [...this.sessions.values()].map((session) => ({
      authorizedAt: session.authorizedAt,
      client: { ...session.client },
      expiresAt: session.expiresAt,
      sessionId: session.sessionId
    }));
  }

  async start(): Promise<void> {
    if (this.operation) {
      return this.operation;
    }
    if (this.server) {
      return;
    }
    this.operation = this.startServer().finally(() => {
      this.operation = undefined;
    });
    return this.operation;
  }

  async shutdown(): Promise<void> {
    if (this.operation) {
      await this.operation.catch(() => undefined);
    }
    const server = this.server;
    this.server = undefined;
    this.revokeAll();
    for (const connection of this.connections) {
      connection.destroy();
    }
    this.connections.clear();
    if (server) {
      await new Promise<void>((resolve) => {
        let settled = false;
        const finish = () => {
          if (!settled) {
            settled = true;
            clearTimeout(timer);
            resolve();
          }
        };
        const timer = setTimeout(
          finish,
          this.options.shutdownTimeoutMs ?? DEFAULT_SHUTDOWN_TIMEOUT_MS
        );
        server.close(finish);
      });
    }
    const paths = this.paths;
    this.paths = undefined;
    if (paths) {
      await cleanupMcpBridgeRuntime(paths).catch(() => undefined);
    }
  }

  revoke(sessionId: string): boolean {
    const session = this.sessions.get(sessionId);
    if (!session) {
      return false;
    }
    this.removeSession(session, true);
    return true;
  }

  revokeAll(): void {
    for (const session of [...this.sessions.values()]) {
      this.removeSession(session, true);
    }
  }

  private async startServer(): Promise<void> {
    const launchId = this.dependencies.randomUUID();
    const paths = await prepareMcpBridgeRuntime(
      this.options.dataDir,
      this.options.tempRoot,
      launchId
    );
    this.paths = paths;
    const server = this.dependencies.createServer((request, response) => {
      void this.handleRequest(request, response).catch((error: unknown) => {
        sendFailure(response, safeReadFailure(error));
      });
    });
    server.maxConnections = MAX_ACTIVE_SESSIONS + MAX_PENDING_AUTHORIZATIONS;
    server.maxRequestsPerSocket = 0;
    server.keepAliveTimeout =
      this.options.sessionLifetimeMs ?? DEFAULT_SESSION_LIFETIME_MS;
    server.requestTimeout =
      (this.options.operationTimeoutMs ?? DEFAULT_OPERATION_TIMEOUT_MS) +
      5_000;
    server.on("connection", (socket: Socket) => {
      this.connections.add(socket);
      socket.setNoDelay(true);
      socket.once("close", () => {
        this.connections.delete(socket);
        const session = this.socketSessions.get(socket);
        if (session) {
          this.removeSession(session, false);
        }
      });
    });
    server.on("clientError", (_error, socket) => {
      socket.destroy();
    });

    try {
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
        server.listen(paths.socketPath);
      });
      await chmod(paths.socketPath, 0o600);
      const info = await lstat(paths.socketPath);
      if (
        !info.isSocket() ||
        info.isSymbolicLink() ||
        info.uid !== effectiveUid() ||
        (info.mode & 0o777) !== 0o600
      ) {
        fail(500, "unavailable");
      }
      await publishMcpRendezvous(
        paths,
        this.dependencies.randomUUID()
      );
      this.server = server;
      server.on("error", () => {
        if (this.server !== server) {
          return;
        }
        this.server = undefined;
        this.revokeAll();
        for (const connection of this.connections) {
          connection.destroy();
        }
        this.connections.clear();
        if (this.paths === paths) {
          this.paths = undefined;
        }
        void cleanupMcpBridgeRuntime(paths).catch(() => undefined);
      });
    } catch (error) {
      server.close();
      for (const connection of this.connections) {
        connection.destroy();
      }
      this.connections.clear();
      if (this.paths === paths) {
        this.paths = undefined;
      }
      await cleanupMcpBridgeRuntime(paths).catch(() => undefined);
      throw safeReadFailure(error);
    }
  }

  private async handleRequest(
    request: IncomingMessage,
    response: ServerResponse
  ): Promise<void> {
    if (
      request.method !== "POST" ||
      typeof request.url !== "string" ||
      request.url.includes("?") ||
      request.url.includes("#") ||
      request.url.includes("\\")
    ) {
      fail(request.method === "POST" ? 404 : 405, "forbidden");
    }
    const now = this.dependencies.now();
    const maximumDeadline =
      request.url === "/authorize"
        ? this.options.authorizationTimeoutMs ??
          DEFAULT_AUTHORIZATION_TIMEOUT_MS
        : this.options.operationTimeoutMs ?? DEFAULT_OPERATION_TIMEOUT_MS;
    const deadline = validateCommonHeaders(
      request,
      now,
      maximumDeadline
    );
    if (request.url === "/authorize") {
      await this.authorize(request, response, deadline);
      return;
    }

    const session = this.requireSession(request, now);
    this.consumeRate(session, now);
    if (
      session.activeRequest ||
      this.globalActiveRequests >= MAX_ACTIVE_SESSIONS
    ) {
      fail(429, "busy");
    }
    session.activeRequest = true;
    this.globalActiveRequests += 1;
    try {
      const body = await readJsonBody(request);
      const result =
        request.url === "/resolve-library-id"
          ? await withAbortDeadline(
              (signal) =>
                this.options.readService.resolveLibraryId(
                  parseResolveInput(body),
                  signal
                ),
              deadline,
              this.dependencies.now,
              session
            )
          : request.url === "/query-docs"
            ? await withAbortDeadline(
                (signal) =>
                  this.options.readService.queryDocs(
                    parseQueryInput(body),
                    signal
                  ),
                deadline,
                this.dependencies.now,
                session
              )
            : fail(404, "forbidden");
      sendJson(
        response,
        200,
        result as unknown as Record<string, unknown>
      );
    } finally {
      session.activeRequest = false;
      this.globalActiveRequests -= 1;
    }
  }

  private async authorize(
    request: IncomingMessage,
    response: ServerResponse,
    deadline: number
  ): Promise<void> {
    const socket = request.socket;
    if (
      this.socketSessions.has(socket) ||
      this.pendingSockets.has(socket)
    ) {
      fail(409, "forbidden");
    }
    if (
      headerValues(request, "authorization").length !== 0 ||
      headerValues(request, "x-lcf-mcp-session-id").length !== 0 ||
      requiredHeader(request, "x-lcf-mcp-launch-id") !==
        this.paths?.launchId
    ) {
      fail(401, "unauthorized");
    }
    if (
      this.sessions.size >= MAX_ACTIVE_SESSIONS ||
      this.pendingAuthorizations >= MAX_PENDING_AUTHORIZATIONS
    ) {
      fail(429, "busy");
    }
    const client = parseClientDescriptor(await readJsonBody(request));
    this.pendingSockets.add(socket);
    this.pendingAuthorizations += 1;
    let approved = false;
    try {
      approved = await withAbortDeadline(
        (signal) => this.options.authorizeClient(client, signal),
        deadline,
        this.dependencies.now
      );
    } finally {
      this.pendingSockets.delete(socket);
      this.pendingAuthorizations -= 1;
    }
    if (!approved || socket.destroyed) {
      fail(403, "approval_denied");
    }

    const revision = await withAbortDeadline(
      (signal) => this.options.readService.getRevision(signal),
      deadline,
      this.dependencies.now
    );
    if (!isCorpusRevision(revision)) {
      fail(502, "invalid_response");
    }
    const rawCapability = this.dependencies.randomBytes(32);
    if (rawCapability.length !== 32) {
      rawCapability.fill(0);
      fail(500, "unavailable");
    }
    const capability = rawCapability.toString("base64url");
    rawCapability.fill(0);
    const sessionId = this.dependencies.randomUUID();
    if (
      capability.length !== 43 ||
      !UUID_PATTERN.test(sessionId)
    ) {
      fail(500, "unavailable");
    }
    const authorizedAt = this.dependencies.now();
    const expiresAt =
      authorizedAt +
      (this.options.sessionLifetimeMs ?? DEFAULT_SESSION_LIFETIME_MS);
    const session: BridgeSession = {
      activeRequest: false,
      authorizedAt,
      capability,
      client,
      expiresAt,
      rateRemaining: MAX_REQUESTS_PER_MINUTE,
      rateResetAt: authorizedAt + 60_000,
      sessionId,
      socket
    };
    this.sessions.set(sessionId, session);
    this.socketSessions.set(socket, session);
    const authorization: McpBridgeAuthorization = {
      capability,
      corpusRevision: revision,
      expiresAt,
      protocol: MCP_BRIDGE_PROTOCOL_VERSION,
      role: "mcp-bridge",
      service: "local-context-forge",
      sessionId
    };
    sendJson(
      response,
      200,
      authorization as unknown as Record<string, unknown>
    );
  }

  private requireSession(
    request: IncomingMessage,
    now: number
  ): BridgeSession {
    if (headerValues(request, "x-lcf-mcp-launch-id").length !== 0) {
      fail(400, "invalid_request");
    }
    const sessionId = requiredHeader(
      request,
      "x-lcf-mcp-session-id"
    );
    if (!UUID_PATTERN.test(sessionId)) {
      fail(401, "unauthorized");
    }
    const session = this.sessions.get(sessionId);
    if (!session || session.socket !== request.socket) {
      fail(401, "unauthorized");
    }
    if (now >= session.expiresAt) {
      this.removeSession(session, true);
      fail(401, "expired");
    }
    const authorization = requiredHeader(request, "authorization");
    const supplied = authorization.startsWith("Bearer ")
      ? authorization.slice("Bearer ".length)
      : "";
    const suppliedBytes = Buffer.from(supplied, "ascii");
    const expectedBytes = Buffer.from(session.capability, "ascii");
    if (
      suppliedBytes.length !== expectedBytes.length ||
      !timingSafeEqual(suppliedBytes, expectedBytes)
    ) {
      fail(401, "unauthorized");
    }
    return session;
  }

  private consumeRate(session: BridgeSession, now: number): void {
    if (now >= session.rateResetAt) {
      session.rateRemaining = MAX_REQUESTS_PER_MINUTE;
      session.rateResetAt = now + 60_000;
    }
    if (session.rateRemaining <= 0) {
      fail(429, "rate_limited");
    }
    session.rateRemaining -= 1;
  }

  private removeSession(session: BridgeSession, destroy: boolean): void {
    if (this.sessions.get(session.sessionId) !== session) {
      return;
    }
    this.sessions.delete(session.sessionId);
    this.socketSessions.delete(session.socket);
    session.activeAbort?.abort();
    delete session.activeAbort;
    session.capability = "";
    if (destroy && !session.socket.destroyed) {
      session.socket.destroy();
    }
  }
}

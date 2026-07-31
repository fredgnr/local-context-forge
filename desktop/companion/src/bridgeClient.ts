import { randomUUID } from "node:crypto";
import { constants as fsConstants } from "node:fs";
import { lstat, open, realpath } from "node:fs/promises";
import http, {
  type ClientRequest,
  type IncomingMessage,
  type RequestOptions
} from "node:http";
import os from "node:os";
import path from "node:path";
import {
  MAX_MCP_BRIDGE_RESPONSE_BYTES,
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
  type McpBridgeErrorCode,
  type McpBridgeResult,
  type McpClientDescriptor
} from "../../src/mcpProtocol";

const AUTHORIZATION_TIMEOUT_MS = 30_000;
const RESOLVE_TIMEOUT_MS = 30_000;
const QUERY_TIMEOUT_MS = 120_000;
const MAX_RENDEZVOUS_BYTES = 4 * 1024;
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const ERROR_CODES = new Set<McpBridgeErrorCode>([
  "approval_denied",
  "backend_unavailable",
  "busy",
  "expired",
  "forbidden",
  "invalid_request",
  "invalid_response",
  "not_found",
  "protocol_mismatch",
  "rate_limited",
  "request_too_large",
  "revoked",
  "stale_revision",
  "timeout",
  "unauthorized",
  "unavailable"
]);

type RequestImplementation = (
  options: RequestOptions,
  callback: (response: IncomingMessage) => void
) => ClientRequest;

interface CompanionBridgeClientDependencies {
  agent?: http.Agent;
  now?: () => number;
  request?: RequestImplementation;
  requestId?: () => string;
}

interface BridgeSession {
  capability: string;
  client: McpClientDescriptor;
  corpusRevision: number;
  expiresAt: number;
  sessionId: string;
}

export interface CompanionBridgePort {
  authorize(
    client: McpClientDescriptor,
    signal?: AbortSignal
  ): Promise<void>;
  close(): void;
  queryDocs(
    libraryId: string,
    query: string,
    signal?: AbortSignal
  ): Promise<string>;
  resolveLibraryId(
    libraryName: string,
    query: string,
    signal?: AbortSignal
  ): Promise<string>;
}

export class CompanionBridgeError extends Error {
  constructor(readonly code: McpBridgeErrorCode) {
    super(`Desktop MCP bridge failed (${code})`);
    this.name = "CompanionBridgeError";
  }
}

function effectiveUid(): number {
  return process.geteuid?.() ?? process.getuid?.() ?? -1;
}

export interface McpBridgeEndpoint {
  readonly launchId: string;
  readonly rendezvousPath?: string;
  readonly runtimeDirectory: string;
  readonly socketPath: string;
  readonly tempRoot: string;
}

function requireAbsoluteNormalized(value: string): string {
  if (
    !path.isAbsolute(value) ||
    path.normalize(value) !== value ||
    value.includes("\0")
  ) {
    throw new CompanionBridgeError("unavailable");
  }
  return value;
}

function runtimeDirectoryIsExpected(
  tempRoot: string,
  runtimeDirectory: string
): boolean {
  return (
    path.dirname(runtimeDirectory) === tempRoot &&
    /^lcf-mcp-[A-Za-z0-9_-]{6,80}$/.test(
      path.basename(runtimeDirectory)
    ) &&
    path.basename(runtimeDirectory).startsWith(
      MCP_RUNTIME_DIRECTORY_PREFIX
    )
  );
}

async function verifyPrivateDirectory(directory: string): Promise<void> {
  const info = await lstat(directory).catch(() => undefined);
  if (
    !info?.isDirectory() ||
    info.isSymbolicLink() ||
    info.uid !== effectiveUid() ||
    (info.mode & 0o777) !== 0o700 ||
    (await realpath(directory)) !== directory
  ) {
    throw new CompanionBridgeError("unavailable");
  }
}

async function readPrivateJson(filePath: string): Promise<unknown> {
  const handle = await open(
    filePath,
    fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW
  ).catch(() => {
    throw new CompanionBridgeError("unavailable");
  });
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
      throw new CompanionBridgeError("unavailable");
    }
    const bytes = Buffer.alloc(info.size);
    const { bytesRead } = await handle.read(bytes, 0, info.size, 0);
    if (bytesRead !== info.size) {
      throw new CompanionBridgeError("unavailable");
    }
    return JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(bytes)
    );
  } catch (error) {
    if (error instanceof CompanionBridgeError) {
      throw error;
    }
    throw new CompanionBridgeError("unavailable");
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
    throw new CompanionBridgeError("unavailable");
  }
  return requireAbsoluteNormalized(value.runtimeDirectory);
}

function parseLaunch(value: unknown): {
  launchId: string;
  socketName: typeof MCP_BRIDGE_SOCKET_NAME;
} {
  if (
    !isPlainObject(value) ||
    !hasExactKeys(value, ["launchId", "schemaVersion", "socketName"]) ||
    value.schemaVersion !== 1 ||
    typeof value.launchId !== "string" ||
    !UUID_PATTERN.test(value.launchId) ||
    value.socketName !== MCP_BRIDGE_SOCKET_NAME
  ) {
    throw new CompanionBridgeError("unavailable");
  }
  return {
    launchId: value.launchId,
    socketName: MCP_BRIDGE_SOCKET_NAME
  };
}

export function resolveDefaultMcpRendezvousPath(
  homeDirectory = os.homedir(),
  platform = process.platform
): string {
  if (
    platform !== "darwin" ||
    !path.isAbsolute(homeDirectory) ||
    path.normalize(homeDirectory) !== homeDirectory ||
    homeDirectory.includes("\0") ||
    homeDirectory === path.parse(homeDirectory).root
  ) {
    throw new CompanionBridgeError("unavailable");
  }
  return path.join(
    homeDirectory,
    "Library",
    "Application Support",
    "Local Context Forge",
    MCP_RENDEZVOUS_FILE_NAME
  );
}

export async function resolveDefaultMcpBridgeEndpoint(
  homeDirectory = os.homedir(),
  tempRoot = os.tmpdir(),
  platform = process.platform
): Promise<McpBridgeEndpoint> {
  const rendezvousPath = resolveDefaultMcpRendezvousPath(
    homeDirectory,
    platform
  );
  const dataDirectory = path.dirname(rendezvousPath);
  await verifyPrivateDirectory(dataDirectory);
  if ((await realpath(rendezvousPath).catch(() => undefined)) !== rendezvousPath) {
    throw new CompanionBridgeError("unavailable");
  }
  const runtimeDirectory = parseRendezvous(
    await readPrivateJson(rendezvousPath)
  );
  const lexicalTempRoot = requireAbsoluteNormalized(tempRoot);
  await verifyPrivateDirectory(lexicalTempRoot);
  const canonicalTempRoot = await realpath(lexicalTempRoot).catch(() => {
    throw new CompanionBridgeError("unavailable");
  });
  if (canonicalTempRoot !== lexicalTempRoot) {
    throw new CompanionBridgeError("unavailable");
  }
  if (!runtimeDirectoryIsExpected(canonicalTempRoot, runtimeDirectory)) {
    throw new CompanionBridgeError("unavailable");
  }
  await verifyPrivateDirectory(runtimeDirectory);
  const launch = parseLaunch(
    await readPrivateJson(path.join(runtimeDirectory, MCP_LAUNCH_FILE_NAME))
  );
  const socketPath = path.join(runtimeDirectory, launch.socketName);
  if (Buffer.byteLength(socketPath, "utf8") > 100) {
    throw new CompanionBridgeError("unavailable");
  }
  return {
    launchId: launch.launchId,
    rendezvousPath,
    runtimeDirectory,
    socketPath,
    tempRoot: canonicalTempRoot
  };
}

export async function configuredMcpBridgeEndpoint(
  environment: NodeJS.ProcessEnv = process.env
): Promise<McpBridgeEndpoint> {
  const debugPath = environment.LCF_MCP_DEBUG_SOCKET;
  const debugLaunchId = environment.LCF_MCP_DEBUG_LAUNCH_ID;
  const debugTempRoot = environment.LCF_MCP_DEBUG_TEMP_ROOT;
  if (
    environment.LCF_MCP_DEBUG === "1" &&
    debugPath !== undefined &&
    debugLaunchId !== undefined &&
    debugTempRoot !== undefined
  ) {
    const socketPath = requireAbsoluteNormalized(debugPath);
    const tempRoot = requireAbsoluteNormalized(debugTempRoot);
    const runtimeDirectory = path.dirname(socketPath);
    if (
      path.basename(socketPath) !== MCP_BRIDGE_SOCKET_NAME ||
      !UUID_PATTERN.test(debugLaunchId) ||
      !runtimeDirectoryIsExpected(tempRoot, runtimeDirectory)
    ) {
      throw new CompanionBridgeError("unavailable");
    }
    return {
      launchId: debugLaunchId,
      runtimeDirectory,
      socketPath,
      tempRoot
    };
  }
  if (
    environment.LCF_MCP_DEBUG !== undefined ||
    debugPath !== undefined ||
    debugLaunchId !== undefined ||
    debugTempRoot !== undefined
  ) {
    throw new CompanionBridgeError("unavailable");
  }
  return await resolveDefaultMcpBridgeEndpoint();
}

export async function verifyMcpBridgeEndpoint(
  endpoint: McpBridgeEndpoint
): Promise<void> {
  const { socketPath, runtimeDirectory, tempRoot } = endpoint;
  if (
    requireAbsoluteNormalized(socketPath) !== socketPath ||
    path.basename(socketPath) !== MCP_BRIDGE_SOCKET_NAME ||
    path.dirname(socketPath) !== runtimeDirectory ||
    !UUID_PATTERN.test(endpoint.launchId)
  ) {
    throw new CompanionBridgeError("unavailable");
  }
  const canonicalTempRoot = await realpath(tempRoot).catch(() => undefined);
  if (
    canonicalTempRoot !== tempRoot ||
    !runtimeDirectoryIsExpected(tempRoot, runtimeDirectory)
  ) {
    throw new CompanionBridgeError("unavailable");
  }
  await verifyPrivateDirectory(tempRoot);
  await verifyPrivateDirectory(runtimeDirectory);
  const launch = parseLaunch(
    await readPrivateJson(path.join(runtimeDirectory, MCP_LAUNCH_FILE_NAME))
  );
  if (launch.launchId !== endpoint.launchId) {
    throw new CompanionBridgeError("unavailable");
  }
  if (endpoint.rendezvousPath) {
    const rendezvousPath = requireAbsoluteNormalized(
      endpoint.rendezvousPath
    );
    await verifyPrivateDirectory(path.dirname(rendezvousPath));
    if (
      (await realpath(rendezvousPath).catch(() => undefined)) !==
        rendezvousPath ||
      parseRendezvous(await readPrivateJson(rendezvousPath)) !==
        runtimeDirectory
    ) {
      throw new CompanionBridgeError("unavailable");
    }
  }
  const socketInfo = await lstat(socketPath).catch(() => undefined);
  if (
    !socketInfo?.isSocket() ||
    socketInfo.isSymbolicLink() ||
    socketInfo.uid !== effectiveUid() ||
    (socketInfo.mode & 0o777) !== 0o600 ||
    (await realpath(socketPath)) !== socketPath
  ) {
    throw new CompanionBridgeError("unavailable");
  }
}

function isBridgeErrorCode(value: unknown): value is McpBridgeErrorCode {
  return (
    typeof value === "string" &&
    ERROR_CODES.has(value as McpBridgeErrorCode)
  );
}

function parseAuthorization(value: unknown): McpBridgeAuthorization {
  if (
    !isPlainObject(value) ||
    !hasExactKeys(value, [
      "capability",
      "corpusRevision",
      "expiresAt",
      "protocol",
      "role",
      "service",
      "sessionId"
    ]) ||
    typeof value.capability !== "string" ||
    !/^[A-Za-z0-9_-]{43}$/.test(value.capability) ||
    !isCorpusRevision(value.corpusRevision) ||
    !Number.isSafeInteger(value.expiresAt) ||
    Number(value.expiresAt) <= 0 ||
    value.protocol !== MCP_BRIDGE_PROTOCOL_VERSION ||
    value.role !== "mcp-bridge" ||
    value.service !== "local-context-forge" ||
    typeof value.sessionId !== "string" ||
    !UUID_PATTERN.test(value.sessionId)
  ) {
    throw new CompanionBridgeError("invalid_response");
  }
  return value as unknown as McpBridgeAuthorization;
}

function parseResult(value: unknown, expectedRevision: number): string {
  if (
    !isPlainObject(value) ||
    !hasExactKeys(value, ["corpusRevision", "text"]) ||
    value.corpusRevision !== expectedRevision ||
    !isBoundedText(value.text, MAX_MCP_BRIDGE_RESPONSE_BYTES, true)
  ) {
    throw new CompanionBridgeError("invalid_response");
  }
  return value.text;
}

export class CompanionBridgeClient implements CompanionBridgePort {
  private readonly agent: http.Agent;
  private readonly now: () => number;
  private readonly requestImplementation: RequestImplementation;
  private readonly requestId: () => string;
  private session: BridgeSession | undefined;

  constructor(
    private readonly endpoint: McpBridgeEndpoint,
    dependencies: CompanionBridgeClientDependencies = {}
  ) {
    if (
      !path.isAbsolute(endpoint.socketPath) ||
      path.basename(endpoint.socketPath) !== MCP_BRIDGE_SOCKET_NAME ||
      path.dirname(endpoint.socketPath) !== endpoint.runtimeDirectory ||
      !UUID_PATTERN.test(endpoint.launchId)
    ) {
      throw new CompanionBridgeError("unavailable");
    }
    this.agent =
      dependencies.agent ??
      new http.Agent({
        keepAlive: true,
        maxFreeSockets: 1,
        maxSockets: 1,
        scheduling: "fifo"
      });
    this.now = dependencies.now ?? Date.now;
    this.requestImplementation = dependencies.request ?? http.request;
    this.requestId = dependencies.requestId ?? randomUUID;
  }

  async authorize(
    client: McpClientDescriptor,
    signal?: AbortSignal
  ): Promise<void> {
    if (
      !isBoundedText(client.name, 256) ||
      !isBoundedText(client.version, 128)
    ) {
      throw new CompanionBridgeError("invalid_request");
    }
    if (this.session) {
      if (
        this.session.client.name !== client.name ||
        this.session.client.version !== client.version ||
        this.now() >= this.session.expiresAt
      ) {
        throw new CompanionBridgeError(
          this.now() >= this.session.expiresAt ? "expired" : "forbidden"
        );
      }
      return;
    }
    await verifyMcpBridgeEndpoint(this.endpoint);
    const value = await this.request(
      "/authorize",
      { client },
      AUTHORIZATION_TIMEOUT_MS,
      signal
    );
    const authorization = parseAuthorization(value);
    if (authorization.expiresAt <= this.now()) {
      throw new CompanionBridgeError("invalid_response");
    }
    this.session = {
      capability: authorization.capability,
      client: { ...client },
      corpusRevision: authorization.corpusRevision,
      expiresAt: authorization.expiresAt,
      sessionId: authorization.sessionId
    };
  }

  async resolveLibraryId(
    libraryName: string,
    query: string,
    signal?: AbortSignal
  ): Promise<string> {
    const session = this.requireSession();
    const value = await this.request(
      "/resolve-library-id",
      {
        corpusRevision: session.corpusRevision,
        libraryName,
        query
      },
      RESOLVE_TIMEOUT_MS,
      signal,
      session
    );
    return parseResult(value, session.corpusRevision);
  }

  async queryDocs(
    libraryId: string,
    query: string,
    signal?: AbortSignal
  ): Promise<string> {
    if (!isMcpLibraryId(libraryId)) {
      throw new CompanionBridgeError("invalid_request");
    }
    const session = this.requireSession();
    const value = await this.request(
      "/query-docs",
      {
        corpusRevision: session.corpusRevision,
        libraryId,
        query
      },
      QUERY_TIMEOUT_MS,
      signal,
      session
    );
    return parseResult(value, session.corpusRevision);
  }

  close(): void {
    if (this.session) {
      this.session.capability = "";
      this.session = undefined;
    }
    this.agent.destroy();
  }

  private requireSession(): BridgeSession {
    const session = this.session;
    if (!session) {
      throw new CompanionBridgeError("unauthorized");
    }
    if (this.now() >= session.expiresAt) {
      session.capability = "";
      this.session = undefined;
      throw new CompanionBridgeError("expired");
    }
    return session;
  }

  private request(
    requestPath: string,
    payload: Record<string, unknown>,
    timeoutMs: number,
    signal?: AbortSignal,
    session?: BridgeSession
  ): Promise<unknown> {
    const body = Buffer.from(JSON.stringify(payload), "utf8");
    const now = this.now();
    const headers: Record<string, string> = {
      Accept: "application/json",
      Connection: "keep-alive",
      "Content-Length": String(body.length),
      "Content-Type": "application/json",
      "X-LCF-Deadline-Ms": String(now + timeoutMs),
      "X-LCF-MCP-Protocol-Version": MCP_BRIDGE_PROTOCOL_VERSION,
      "X-LCF-Request-ID": this.requestId()
    };
    if (session) {
      headers.Authorization = `Bearer ${session.capability}`;
      headers["X-LCF-MCP-Session-ID"] = session.sessionId;
    } else {
      headers["X-LCF-MCP-Launch-ID"] = this.endpoint.launchId;
    }

    return new Promise((resolve, reject) => {
      let request: ClientRequest | undefined;
      let response: IncomingMessage | undefined;
      let settled = false;
      const finish = (
        error?: CompanionBridgeError,
        value?: unknown
      ) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        signal?.removeEventListener("abort", onAbort);
        if (error) {
          response?.destroy();
          request?.destroy();
          reject(error);
        } else {
          resolve(value);
        }
      };
      const onAbort = () =>
        finish(new CompanionBridgeError("timeout"));
      const timer = setTimeout(
        () => finish(new CompanionBridgeError("timeout")),
        timeoutMs
      );
      if (signal?.aborted) {
        finish(new CompanionBridgeError("timeout"));
        return;
      }
      signal?.addEventListener("abort", onAbort, { once: true });

      try {
        request = this.requestImplementation(
          {
            agent: this.agent,
            headers,
            maxHeaderSize: 16 * 1024,
            method: "POST",
            path: requestPath,
            socketPath: this.endpoint.socketPath
          },
          (incoming) => {
            response = incoming;
            const chunks: Buffer[] = [];
            let total = 0;
            incoming.on("data", (chunk: Buffer | string) => {
              const bytes = Buffer.isBuffer(chunk)
                ? chunk
                : Buffer.from(chunk);
              total += bytes.length;
              if (total > MAX_MCP_BRIDGE_RESPONSE_BYTES) {
                finish(new CompanionBridgeError("invalid_response"));
                return;
              }
              chunks.push(bytes);
            });
            incoming.once("aborted", () =>
              finish(new CompanionBridgeError("unavailable"))
            );
            incoming.once("error", () =>
              finish(new CompanionBridgeError("unavailable"))
            );
            incoming.once("end", () => {
              if (settled) {
                return;
              }
              const contentType = String(
                incoming.headers["content-type"] ?? ""
              )
                .split(";", 1)[0]!
                .trim()
                .toLowerCase();
              if (
                contentType !== "application/json" &&
                !contentType.endsWith("+json")
              ) {
                finish(new CompanionBridgeError("invalid_response"));
                return;
              }
              let parsed: unknown;
              try {
                parsed = JSON.parse(
                  Buffer.concat(chunks, total).toString("utf8")
                );
              } catch {
                finish(new CompanionBridgeError("invalid_response"));
                return;
              }
              const status = incoming.statusCode;
              if (status === undefined || status < 200 || status >= 300) {
                if (
                  isPlainObject(parsed) &&
                  hasExactKeys(parsed, ["error"]) &&
                  isPlainObject(parsed.error) &&
                  hasExactKeys(parsed.error, ["code"]) &&
                  isBridgeErrorCode(parsed.error.code)
                ) {
                  finish(new CompanionBridgeError(parsed.error.code));
                } else {
                  finish(new CompanionBridgeError("unavailable"));
                }
                return;
              }
              finish(undefined, parsed);
            });
          }
        );
      } catch {
        finish(new CompanionBridgeError("unavailable"));
        return;
      }
      request.once("error", () =>
        finish(new CompanionBridgeError("unavailable"))
      );
      request.setTimeout(timeoutMs, () =>
        finish(new CompanionBridgeError("timeout"))
      );
      request.end(body);
    });
  }
}

import { randomUUID } from "node:crypto";
import http, {
  type ClientRequest,
  type IncomingMessage,
  type RequestOptions
} from "node:http";
import path from "node:path";
import {
  MAX_MCP_BRIDGE_RESPONSE_BYTES,
  MCP_QUERY_RESULT_LIMIT,
  MCP_RESOLVE_RESULT_LIMIT,
  isBoundedText,
  isCorpusRevision,
  isMcpLibraryId,
  isPlainObject,
  isSafeRepositoryPath,
  type McpBridgeErrorCode,
  type McpBridgeResult
} from "../mcpProtocol";
import { SIDECAR_PROTOCOL_VERSION } from "../contracts";
import type { SidecarConnection } from "./apiProxy";

const MAX_SIDECAR_RESPONSE_BYTES = MAX_MCP_BRIDGE_RESPONSE_BYTES;
const DEFAULT_SIDECAR_TIMEOUT_MS = 30_000;
const MAX_SIDECAR_TIMEOUT_MS = 120_000;
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const SHA_PATTERN = /^[0-9a-f]{7,64}$/;

type RequestImplementation = (
  options: RequestOptions,
  callback: (response: IncomingMessage) => void
) => ClientRequest;

export class McpReadError extends Error {
  constructor(readonly code: McpBridgeErrorCode) {
    super(`MCP read service failed (${code})`);
    this.name = "McpReadError";
  }
}

export interface McpReadPort {
  getRevision(signal?: AbortSignal): Promise<number>;
  resolveLibraryId(
    input: {
      corpusRevision: number;
      libraryName: string;
      query: string;
    },
    signal?: AbortSignal
  ): Promise<McpBridgeResult>;
  queryDocs(
    input: {
      corpusRevision: number;
      libraryId: string;
      query: string;
    },
    signal?: AbortSignal
  ): Promise<McpBridgeResult>;
}

interface SidecarMcpReadDependencies {
  request?: RequestImplementation;
  now?: () => number;
  requestId?: () => string;
}

interface LibraryRecord {
  context7Id: string;
  defaultVersion: string | null;
  description: string;
  name: string;
  pageCount: number;
  versionCount: number;
}

interface SourceReference {
  lineEnd: number;
  lineStart: number;
  path: string;
}

interface QueryHit {
  markdown: string;
  path: string;
  sourceRefs: SourceReference[];
  sourceSha: string;
  summary: string;
  title: string;
  version: string;
}

interface QueryResult {
  engine: string;
  hits: QueryHit[];
}

function validateConnection(connection: SidecarConnection): void {
  if (
    !path.isAbsolute(connection.socketPath) ||
    !UUID_PATTERN.test(connection.launchId) ||
    !/^[A-Za-z0-9_-]{43}$/.test(connection.token)
  ) {
    throw new McpReadError("unavailable");
  }
}

function boundedTimeout(value: number): number {
  if (!Number.isFinite(value)) {
    return DEFAULT_SIDECAR_TIMEOUT_MS;
  }
  return Math.max(1_000, Math.min(MAX_SIDECAR_TIMEOUT_MS, Math.trunc(value)));
}

function normalizeTransportError(error: unknown): McpReadError {
  if (error instanceof McpReadError) {
    return error;
  }
  return new McpReadError("backend_unavailable");
}

function requestSidecarJson(
  connection: SidecarConnection,
  method: "GET" | "POST",
  requestPath: string,
  payload: Record<string, unknown> | undefined,
  timeoutMs: number,
  signal: AbortSignal | undefined,
  dependencies: Required<SidecarMcpReadDependencies>
): Promise<unknown> {
  validateConnection(connection);
  if (
    !requestPath.startsWith("/api/") ||
    requestPath.includes("#") ||
    requestPath.includes("\\") ||
    Buffer.byteLength(requestPath, "utf8") > 16_384
  ) {
    throw new McpReadError("invalid_request");
  }

  const body =
    payload === undefined
      ? undefined
      : Buffer.from(JSON.stringify(payload), "utf8");
  const effectiveTimeout = boundedTimeout(timeoutMs);
  const now = dependencies.now();
  const headers: Record<string, string> = {
    Accept: "application/json",
    Authorization: `Bearer ${connection.token}`,
    "X-LCF-Deadline-Ms": String(now + effectiveTimeout),
    "X-LCF-Launch-ID": connection.launchId,
    "X-LCF-Protocol-Version": SIDECAR_PROTOCOL_VERSION,
    "X-LCF-Request-ID": dependencies.requestId()
  };
  if (body) {
    headers["Content-Length"] = String(body.length);
    headers["Content-Type"] = "application/json";
  }

  return new Promise((resolve, reject) => {
    let request: ClientRequest | undefined;
    let settled = false;
    let response: IncomingMessage | undefined;
    const finish = (error?: McpReadError, value?: unknown) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(deadlineTimer);
      signal?.removeEventListener("abort", onAbort);
      if (error) {
        response?.destroy();
        request?.destroy();
        reject(error);
      } else {
        resolve(value);
      }
    };
    const onAbort = () => finish(new McpReadError("timeout"));
    const deadlineTimer = setTimeout(
      () => finish(new McpReadError("timeout")),
      effectiveTimeout
    );

    if (signal?.aborted) {
      finish(new McpReadError("timeout"));
      return;
    }
    signal?.addEventListener("abort", onAbort, { once: true });

    try {
      request = dependencies.request(
        {
          agent: false,
          headers,
          maxHeaderSize: 16 * 1024,
          method,
          path: requestPath,
          socketPath: connection.socketPath
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
            if (total > MAX_SIDECAR_RESPONSE_BYTES) {
              finish(new McpReadError("invalid_response"));
              return;
            }
            chunks.push(bytes);
          });
          incoming.once("aborted", () =>
            finish(new McpReadError("backend_unavailable"))
          );
          incoming.once("error", () =>
            finish(new McpReadError("backend_unavailable"))
          );
          incoming.once("end", () => {
            if (settled) {
              return;
            }
            const status = incoming.statusCode;
            if (status === 404) {
              finish(new McpReadError("not_found"));
              return;
            }
            if (status === 408) {
              finish(new McpReadError("timeout"));
              return;
            }
            if (status === 429) {
              finish(new McpReadError("busy"));
              return;
            }
            if (status === undefined || status < 200 || status >= 300) {
              finish(new McpReadError("backend_unavailable"));
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
              finish(new McpReadError("invalid_response"));
              return;
            }
            const responseBody = Buffer.concat(chunks, total);
            if (
              responseBody.includes(
                Buffer.from(connection.token, "utf8")
              ) ||
              responseBody.includes(
                Buffer.from(connection.socketPath, "utf8")
              )
            ) {
              finish(new McpReadError("invalid_response"));
              return;
            }
            try {
              finish(undefined, JSON.parse(responseBody.toString("utf8")));
            } catch {
              finish(new McpReadError("invalid_response"));
            }
          });
        }
      );
    } catch {
      finish(new McpReadError("backend_unavailable"));
      return;
    }

    request.once("error", () =>
      finish(new McpReadError("backend_unavailable"))
    );
    request.setTimeout(effectiveTimeout, () =>
      finish(new McpReadError("timeout"))
    );
    request.end(body);
  });
}

function parseRevision(value: unknown): number {
  if (
    !isPlainObject(value) ||
    !isPlainObject(value.embedding) ||
    !isCorpusRevision(value.embedding.corpus_revision)
  ) {
    throw new McpReadError("invalid_response");
  }
  return value.embedding.corpus_revision;
}

function isDisplayText(
  value: unknown,
  maximumBytes: number,
  allowEmpty = false
): value is string {
  return (
    isBoundedText(value, maximumBytes, allowEmpty) &&
    !/[\u0001-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value)
  );
}

function isCount(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function parseLibraries(value: unknown): LibraryRecord[] {
  if (!Array.isArray(value) || value.length > 10_000) {
    throw new McpReadError("invalid_response");
  }
  return value.map((item) => {
    if (
      !isPlainObject(item) ||
      !isDisplayText(item.name, 1_024) ||
      !isMcpLibraryId(item.context7_id) ||
      !isDisplayText(item.description, 8_192, true) ||
      (item.default_version !== null &&
        item.default_version !== undefined &&
        !isDisplayText(item.default_version, 512)) ||
      !isCount(item.page_count) ||
      !isCount(item.version_count)
    ) {
      throw new McpReadError("invalid_response");
    }
    return {
      context7Id: item.context7_id,
      defaultVersion:
        typeof item.default_version === "string"
          ? item.default_version
          : null,
      description: item.description,
      name: item.name,
      pageCount: item.page_count,
      versionCount: item.version_count
    };
  });
}

function parseSourceReference(value: unknown): SourceReference {
  if (
    !isPlainObject(value) ||
    !isSafeRepositoryPath(value.path) ||
    !Number.isSafeInteger(value.line_start) ||
    Number(value.line_start) < 1 ||
    !Number.isSafeInteger(value.line_end) ||
    Number(value.line_end) < Number(value.line_start)
  ) {
    throw new McpReadError("invalid_response");
  }
  return {
    lineEnd: Number(value.line_end),
    lineStart: Number(value.line_start),
    path: value.path
  };
}

function parseQueryResult(value: unknown): QueryResult {
  if (
    !isPlainObject(value) ||
    !isDisplayText(value.engine, 128) ||
    !Array.isArray(value.results) ||
    value.results.length > MCP_QUERY_RESULT_LIMIT
  ) {
    throw new McpReadError("invalid_response");
  }
  const hits = value.results.map((item) => {
    if (
      !isPlainObject(item) ||
      !isSafeRepositoryPath(item.path) ||
      !isDisplayText(item.title, 4_096) ||
      !isDisplayText(item.summary, 32 * 1024, true) ||
      !isDisplayText(item.markdown, MAX_SIDECAR_RESPONSE_BYTES, true) ||
      !isDisplayText(item.version, 512) ||
      typeof item.source_sha !== "string" ||
      !SHA_PATTERN.test(item.source_sha) ||
      !Array.isArray(item.source_refs) ||
      item.source_refs.length > 256
    ) {
      throw new McpReadError("invalid_response");
    }
    return {
      markdown: item.markdown,
      path: item.path,
      sourceRefs: item.source_refs.map(parseSourceReference),
      sourceSha: item.source_sha,
      summary: item.summary,
      title: item.title,
      version: item.version
    };
  });
  return { engine: value.engine, hits };
}

function singleLine(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function inlineCode(value: string): string {
  return singleLine(value).replace(/`/g, "\u02bc");
}

export function formatMcpLibraries(
  libraries: readonly LibraryRecord[],
  libraryName: string,
  query: string
): string {
  if (libraries.length === 0) {
    return (
      `No local library matched "${singleLine(libraryName)}". Add and ` +
      "publish the repository in Local Context Forge, then call this tool again."
    );
  }
  const visible = libraries.slice(0, MCP_RESOLVE_RESULT_LIMIT);
  const lines = [
    "# Available local libraries",
    "",
    query
      ? `Selection context: \`${inlineCode(query)}\``
      : "Choose the library whose name and description match the task.",
    ""
  ];
  for (const library of visible) {
    lines.push(
      `- Title: ${singleLine(library.name)}`,
      `  - Context7-compatible library ID: \`${inlineCode(
        library.context7Id
      )}\``,
      `  - Description: ${
        singleLine(library.description) || "No description"
      }`,
      `  - Published pages: ${library.pageCount}`,
      `  - Published versions: ${library.versionCount}`,
      library.defaultVersion
        ? `  - Default version: \`${inlineCode(library.defaultVersion)}\``
        : "  - Default version: not published yet",
      ""
    );
  }
  if (libraries.length > visible.length) {
    lines.push(
      `Showing the first ${MCP_RESOLVE_RESULT_LIMIT} matching libraries.`,
      ""
    );
  }
  return lines.join("\n").trimEnd();
}

export function formatMcpQueryResult(result: QueryResult): string {
  if (result.hits.length === 0) {
    return (
      "No published local documentation matched this query. Try an exact " +
      "API symbol, publish pending Wiki proposals, or run ingest again."
    );
  }
  const lines = [
    "# Local documentation results",
    "",
    `Retrieval engine: \`${inlineCode(result.engine)}\``,
    ""
  ];
  result.hits.forEach((hit, index) => {
    const referenceText = hit.sourceRefs
      .slice(0, 8)
      .map(
        (reference) =>
          `${inlineCode(reference.path)}:${reference.lineStart}-${reference.lineEnd}`
      )
      .join(", ");
    lines.push(
      `## ${index + 1}. ${singleLine(hit.title)}`,
      "",
      `Wiki path: \`${inlineCode(hit.path)}\` · Version: \`${inlineCode(
        hit.version
      )}\` · Source: \`${hit.sourceSha.slice(0, 12)}\``,
      "",
      hit.summary,
      ""
    );
    const markdown = hit.markdown.trim();
    if (markdown) {
      lines.push(markdown, "");
    }
    if (referenceText) {
      lines.push(`Evidence: ${referenceText}`, "");
    }
  });
  return lines.join("\n").trimEnd();
}

export class SidecarMcpReadService implements McpReadPort {
  private readonly dependencies: Required<SidecarMcpReadDependencies>;

  constructor(
    private readonly getConnection: () => SidecarConnection | undefined,
    dependencies: SidecarMcpReadDependencies = {}
  ) {
    this.dependencies = {
      now: dependencies.now ?? Date.now,
      request: dependencies.request ?? http.request,
      requestId: dependencies.requestId ?? randomUUID
    };
  }

  async getRevision(signal?: AbortSignal): Promise<number> {
    const connection = this.requireConnection();
    return this.readRevision(connection, signal);
  }

  async resolveLibraryId(
    input: {
      corpusRevision: number;
      libraryName: string;
      query: string;
    },
    signal?: AbortSignal
  ): Promise<McpBridgeResult> {
    const connection = this.requireConnection();
    return this.withStableRevision(
      connection,
      input.corpusRevision,
      async () => {
        const search = new URLSearchParams({
          search: input.libraryName
        }).toString();
        const response = await this.request(
          connection,
          "GET",
          `/api/libraries?${search}`,
          undefined,
          30_000,
          signal
        );
        return formatMcpLibraries(
          parseLibraries(response),
          input.libraryName,
          input.query
        );
      },
      signal
    );
  }

  async queryDocs(
    input: {
      corpusRevision: number;
      libraryId: string;
      query: string;
    },
    signal?: AbortSignal
  ): Promise<McpBridgeResult> {
    const connection = this.requireConnection();
    return this.withStableRevision(
      connection,
      input.corpusRevision,
      async () => {
        const response = await this.request(
          connection,
          "POST",
          "/api/query",
          {
            library_id: input.libraryId,
            limit: MCP_QUERY_RESULT_LIMIT,
            query: input.query
          },
          120_000,
          signal
        );
        return formatMcpQueryResult(parseQueryResult(response));
      },
      signal
    );
  }

  private requireConnection(): SidecarConnection {
    const connection = this.getConnection();
    if (!connection) {
      throw new McpReadError("unavailable");
    }
    validateConnection(connection);
    return connection;
  }

  private request(
    connection: SidecarConnection,
    method: "GET" | "POST",
    requestPath: string,
    payload: Record<string, unknown> | undefined,
    timeoutMs: number,
    signal: AbortSignal | undefined
  ): Promise<unknown> {
    return requestSidecarJson(
      connection,
      method,
      requestPath,
      payload,
      timeoutMs,
      signal,
      this.dependencies
    ).catch((error: unknown) => {
      throw normalizeTransportError(error);
    });
  }

  private async readRevision(
    connection: SidecarConnection,
    signal?: AbortSignal
  ): Promise<number> {
    const response = await this.request(
      connection,
      "GET",
      "/api/health",
      undefined,
      5_000,
      signal
    );
    return parseRevision(response);
  }

  private async withStableRevision(
    connection: SidecarConnection,
    expectedRevision: number,
    operation: () => Promise<string>,
    signal?: AbortSignal
  ): Promise<McpBridgeResult> {
    if (!isCorpusRevision(expectedRevision)) {
      throw new McpReadError("invalid_request");
    }
    const before = await this.readRevision(connection, signal);
    if (before !== expectedRevision) {
      throw new McpReadError("stale_revision");
    }
    const text = await operation();
    const after = await this.readRevision(connection, signal);
    if (after !== expectedRevision) {
      throw new McpReadError("stale_revision");
    }
    if (
      !isBoundedText(text, MAX_MCP_BRIDGE_RESPONSE_BYTES, true)
    ) {
      throw new McpReadError("invalid_response");
    }
    return { corpusRevision: expectedRevision, text };
  }
}

import http, {
  type ClientRequest,
  type IncomingMessage,
  type RequestOptions
} from "node:http";
import { randomUUID } from "node:crypto";
import {
  MAX_REQUEST_BODY_BYTES,
  MAX_RESPONSE_BODY_BYTES,
  SIDECAR_PROTOCOL_VERSION,
  isJsonValue,
  serializedByteLength,
  type ApiRequest,
  type ApiResponse,
  type JsonValue
} from "../contracts";
import { isAllowedLibrarySource } from "./ipc";

export interface SidecarConnection {
  socketPath: string;
  launchId: string;
  token: string;
}

type RequestImplementation = (
  options: RequestOptions,
  callback: (response: IncomingMessage) => void
) => ClientRequest;

export interface ApiProxyDependencies {
  request?: RequestImplementation;
  now?: () => number;
  requestId?: () => string;
}

export class ApiProxyError extends Error {
  constructor(
    readonly code:
      | "unavailable"
      | "request-too-large"
      | "response-too-large"
      | "timeout"
      | "result-uncertain"
      | "busy"
      | "invalid-response"
      | "transport"
  ) {
    super(`Sidecar request failed (${code})`);
    this.name = "ApiProxyError";
  }
}

export function buildSidecarHeaders(
  connection: SidecarConnection,
  request: ApiRequest,
  now: number,
  requestId: string,
  bodyLength?: number
): Record<string, string> {
  return {
    Authorization: `Bearer ${connection.token}`,
    Accept: "application/json",
    ...(bodyLength === undefined
      ? {}
      : {
          "Content-Type": "application/json",
          "Content-Length": String(bodyLength)
        }),
    "X-LCF-Protocol-Version": SIDECAR_PROTOCOL_VERSION,
    "X-LCF-Launch-ID": connection.launchId,
    "X-LCF-Request-ID": requestId,
    "X-LCF-Deadline-Ms": String(now + (request.timeoutMs ?? 0))
  };
}

const FORBIDDEN_RESPONSE_KEYS = new Set([
  "authorization",
  "headers",
  "launch_id",
  "pid",
  "socket",
  "socket_path",
  "startup_token",
  "stderr",
  "child_stderr",
  "token",
  "uds"
]);

function sanitizeResponseValue(
  value: JsonValue,
  connection: SidecarConnection
): JsonValue {
  if (typeof value === "string") {
    if (
      value.includes(connection.token) ||
      value.includes(connection.socketPath)
    ) {
      throw new ApiProxyError("invalid-response");
    }
    return value;
  }
  if (value === null || typeof value !== "object") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeResponseValue(item, connection));
  }

  const sanitized: Record<string, JsonValue> = {};
  for (const [key, item] of Object.entries(value)) {
    if (!FORBIDDEN_RESPONSE_KEYS.has(key.toLowerCase())) {
      sanitized[key] = sanitizeResponseValue(item, connection);
    }
  }
  return sanitized;
}

const RESPONSE_FIELDS = {
  health: new Set([
    "status",
    "service",
    "version",
    "qmd",
    "embedding",
    "enabled",
    "available",
    "hybrid_enabled",
    "model",
    "dimensions",
    "ready"
  ]),
  system: new Set([
    "ready",
    "ok",
    "healthy",
    "initialized",
    "onboarding_complete",
    "version",
    "app_version",
    "checks",
    "services",
    "id",
    "key",
    "name",
    "label",
    "title",
    "status",
    "state",
    "message",
    "detail",
    "description",
    "action",
    "hint"
  ]),
  settings: new Set([
    "settings",
    "revision",
    "provider_policy",
    "cursor_fallback_consent",
    "subject",
    "version",
    "granted",
    "granted_at",
    "provider_order",
    "fallback_enabled",
    "embedding_model",
    "concurrency",
    "advanced",
    "maxConcurrency",
    "max_concurrency",
    "queryLimit",
    "query_limit",
    "generator",
    "fallbackGenerator",
    "fallback_generator"
  ]),
  models: new Set([
    "items",
    "models",
    "data",
    "id",
    "model",
    "name",
    "label",
    "provider",
    "dimensions",
    "dimension",
    "dims",
    "description",
    "summary",
    "recommended",
    "available",
    "installed",
    "valid",
    "ok",
    "message",
    "detail",
    "preset"
  ]),
  libraries: new Set([
    "id",
    "library_id",
    "slug",
    "name",
    "title",
    "sourceUrl",
    "source_url",
    "source",
    "repo_url",
    "url",
    "description",
    "summary",
    "defaultRef",
    "default_ref",
    "default_version",
    "ref",
    "branch",
    "version",
    "latest_version",
    "commitSha",
    "commit_sha",
    "source_sha",
    "sha",
    "status",
    "pageCount",
    "page_count",
    "pages",
    "updatedAt",
    "updated_at",
    "modified_at"
  ]),
  jobs: new Set([
    "items",
    "jobs",
    "data",
    "job",
    "id",
    "job_id",
    "libraryId",
    "library_id",
    "libraryName",
    "library_name",
    "kind",
    "type",
    "job_type",
    "queuePosition",
    "queue_position",
    "status",
    "state",
    "progress",
    "percent",
    "percentage",
    "phase",
    "stage",
    "current_step",
    "message",
    "detail",
    "requestedProvider",
    "requested_provider",
    "provider",
    "effectiveProvider",
    "effective_provider",
    "actual_provider",
    "fallbackReason",
    "fallback_reason",
    "attempt",
    "attempts",
    "cancellable",
    "retryable",
    "createdAt",
    "created_at",
    "startedAt",
    "started_at",
    "finishedAt",
    "finished_at",
    "updatedAt",
    "updated_at"
  ]),
  pages: new Set([
    "items",
    "pages",
    "documents",
    "data",
    "id",
    "page_id",
    "path",
    "slug",
    "file",
    "title",
    "name",
    "summary",
    "description",
    "kind",
    "type",
    "tags",
    "version",
    "sourceSha",
    "source_sha",
    "commit_sha",
    "sha",
    "markdown",
    "body",
    "content",
    "sourceRefs",
    "source_refs",
    "sources",
    "lineStart",
    "line_start",
    "start_line",
    "lineEnd",
    "line_end",
    "end_line",
    "updatedAt",
    "updated_at",
    "published_at",
    "metadata"
  ]),
  proposals: new Set([
    "items",
    "proposals",
    "data",
    "id",
    "proposal_id",
    "libraryId",
    "library_id",
    "title",
    "name",
    "path",
    "summary",
    "description",
    "status",
    "state",
    "markdown",
    "content",
    "body",
    "sourceRefs",
    "source_refs",
    "sources",
    "file",
    "lineStart",
    "line_start",
    "start_line",
    "lineEnd",
    "line_end",
    "end_line",
    "createdAt",
    "created_at",
    "metadata"
  ]),
  query: new Set([
    "answer",
    "summary",
    "engine",
    "hits",
    "results",
    "items",
    "id",
    "title",
    "name",
    "path",
    "file",
    "snippet",
    "text",
    "excerpt",
    "content",
    "markdown",
    "body",
    "score",
    "similarity",
    "rank",
    "sourceRefs",
    "source_refs",
    "sources",
    "lineStart",
    "line_start",
    "start_line",
    "lineEnd",
    "line_end",
    "end_line"
  ]),
  graph: new Set([
    "nodes",
    "edges",
    "links",
    "id",
    "path",
    "label",
    "title",
    "name",
    "type",
    "kind",
    "group",
    "category",
    "weight",
    "value",
    "size",
    "source",
    "from",
    "target",
    "to",
    "metadata"
  ]),
  lint: new Set([
    "ok",
    "errors",
    "error_count",
    "warnings",
    "warning_count",
    "issues",
    "code",
    "rule",
    "severity",
    "level",
    "message",
    "detail",
    "path",
    "file",
    "line",
    "line_number"
  ])
} as const;

type ResponseProfile = keyof typeof RESPONSE_FIELDS;

const REPOSITORY_PATH_PROFILES = new Set<ResponseProfile>([
  "pages",
  "proposals",
  "query",
  "graph",
  "lint"
]);

export function isSafeRepositoryRelativePath(value: unknown): value is string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    Buffer.byteLength(value, "utf8") > 8_192 ||
    value.startsWith("/") ||
    value.startsWith("~") ||
    /^[A-Za-z]:\//.test(value) ||
    value.includes("\\") ||
    /[\u0000-\u001f\u007f]/.test(value) ||
    value.normalize("NFC") !== value
  ) {
    return false;
  }
  return value
    .split("/")
    .every(
      (segment) =>
        segment !== "" &&
        segment !== "." &&
        segment !== ".."
    );
}

function responseProfile(request: ApiRequest): ResponseProfile {
  const pathname = request.path.split("?", 1)[0] ?? "";
  if (pathname === "/api/health") return "health";
  if (pathname === "/api/system/status") return "system";
  if (pathname === "/api/settings") return "settings";
  if (pathname.startsWith("/api/embedding/")) return "models";
  if (pathname === "/api/rebuilds") return "jobs";
  if (pathname === "/api/libraries") {
    return request.method === "POST" ? "libraries" : "libraries";
  }
  if (pathname === "/api/jobs" || pathname.startsWith("/api/jobs/")) {
    return "jobs";
  }
  if (pathname === "/api/query") return "query";
  if (pathname.startsWith("/api/proposals/")) return "proposals";
  if (pathname.endsWith("/pages") || pathname.endsWith("/page")) return "pages";
  if (pathname.endsWith("/proposals")) return "proposals";
  if (pathname.endsWith("/graph")) return "graph";
  if (pathname.endsWith("/lint")) return "lint";
  if (pathname.endsWith("/ingest")) return "jobs";
  throw new ApiProxyError("invalid-response");
}

function filterResponseFields(
  value: JsonValue,
  allowed: ReadonlySet<string>,
  profile: ResponseProfile
): JsonValue {
  if (value === null || typeof value !== "object") {
    return value;
  }
  if (Array.isArray(value)) {
    if (
      profile === "libraries" &&
      !value.every(
        (item) =>
          item !== null &&
          typeof item === "object" &&
          !Array.isArray(item)
      )
    ) {
      throw new ApiProxyError("invalid-response");
    }
    return value.map((item) => filterResponseFields(item, allowed, profile));
  }
  const filtered: Record<string, JsonValue> = {};
  for (const [key, item] of Object.entries(value)) {
    if (allowed.has(key)) {
      if (
        REPOSITORY_PATH_PROFILES.has(profile) &&
        (key === "path" || key === "file")
      ) {
        if (isSafeRepositoryRelativePath(item)) {
          filtered[key] = item;
        }
        continue;
      }
      if (
        profile === "libraries" &&
        [
          "source",
          "sourceUrl",
          "source_url",
          "repo_url",
          "url"
        ].includes(key)
      ) {
        if (isAllowedLibrarySource(item)) {
          filtered[key] = item;
        }
        continue;
      }
      filtered[key] = filterResponseFields(item, allowed, profile);
    }
  }
  return filtered;
}

function decodeResponse(
  response: IncomingMessage,
  body: Buffer,
  connection: SidecarConnection,
  request: ApiRequest
): ApiResponse {
  const status = response.statusCode;
  if (status === undefined || status < 100 || status > 599) {
    throw new ApiProxyError("invalid-response");
  }
  if (
    request.method !== "GET" &&
    (status === 408 || (status >= 500 && status <= 599))
  ) {
    throw new ApiProxyError("result-uncertain");
  }
  if (
    body.includes(Buffer.from(connection.token, "utf8")) ||
    body.includes(Buffer.from(connection.socketPath, "utf8"))
  ) {
    throw new ApiProxyError("invalid-response");
  }
  if (body.length === 0) {
    if (status >= 200 && status < 300) {
      throw new ApiProxyError("invalid-response");
    }
    return { status, body: { error: "sidecar-request-failed" } };
  }

  const contentType = String(response.headers["content-type"] ?? "")
    .split(";", 1)[0]
    ?.trim()
    .toLowerCase();
  if (contentType === "application/json" || contentType?.endsWith("+json")) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(body.toString("utf8"));
    } catch {
      throw new ApiProxyError("invalid-response");
    }
    if (!isJsonValue(parsed)) {
      throw new ApiProxyError("invalid-response");
    }
    if (status >= 400) {
      return {
        status,
        body: { error: "sidecar-request-failed" }
      };
    }
    const sanitized = sanitizeResponseValue(parsed, connection);
    const profile = responseProfile(request);
    if (
      profile === "libraries" &&
      (sanitized === null ||
        typeof sanitized !== "object" ||
        (request.method === "GET" && !Array.isArray(sanitized)) ||
        (request.method === "POST" && Array.isArray(sanitized)))
    ) {
      throw new ApiProxyError("invalid-response");
    }
    return {
      status,
      body: (() => {
        return filterResponseFields(
          sanitized,
          RESPONSE_FIELDS[profile],
          profile
        );
      })()
    };
  }

  const text = body.toString("utf8");
  if (status >= 400) {
    return { status, body: "Sidecar request failed" };
  }
  void text;
  throw new ApiProxyError("invalid-response");
}

function collectResponse(
  response: IncomingMessage,
  connection: SidecarConnection,
  request: ApiRequest
): Promise<ApiResponse> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let total = 0;
    let settled = false;

    const fail = (error: ApiProxyError) => {
      if (settled) {
        return;
      }
      settled = true;
      response.destroy();
      reject(error);
    };

    response.on("data", (chunk: Buffer | string) => {
      const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      total += buffer.length;
      if (total > MAX_RESPONSE_BODY_BYTES) {
        fail(new ApiProxyError("response-too-large"));
        return;
      }
      chunks.push(buffer);
    });
    response.once("aborted", () => fail(new ApiProxyError("transport")));
    response.once("error", () => fail(new ApiProxyError("transport")));
    response.once("end", () => {
      if (settled) {
        return;
      }
      settled = true;
      try {
        resolve(
          decodeResponse(
            response,
            Buffer.concat(chunks, total),
            connection,
            request
          )
        );
      } catch (error) {
        reject(
          error instanceof ApiProxyError
            ? error
            : new ApiProxyError("invalid-response")
        );
      }
    });
  });
}

export async function proxyApiRequest(
  request: ApiRequest,
  connection: SidecarConnection | undefined,
  dependencies: ApiProxyDependencies = {}
): Promise<ApiResponse> {
  if (!connection) {
    throw new ApiProxyError("unavailable");
  }

  let body: Buffer | undefined;
  if (request.body !== undefined) {
    if (
      !isJsonValue(request.body) ||
      serializedByteLength(request.body) > MAX_REQUEST_BODY_BYTES
    ) {
      throw new ApiProxyError("request-too-large");
    }
    body = Buffer.from(JSON.stringify(request.body), "utf8");
  }

  const now = (dependencies.now ?? Date.now)();
  const requestId = (dependencies.requestId ?? randomUUID)();
  const headers = buildSidecarHeaders(
    connection,
    request,
    now,
    requestId,
    body?.length
  );
  const requestImplementation = dependencies.request ?? http.request;

  return new Promise<ApiResponse>((resolve, reject) => {
    let settled = false;
    let sent = false;
    let clientRequest: ClientRequest | undefined;
    const timeoutError = new ApiProxyError(
      request.method === "GET" ? "timeout" : "result-uncertain"
    );
    const deadlineTimer = setTimeout(() => {
      if (settled) {
        return;
      }
      settled = true;
      clientRequest?.destroy(timeoutError);
      reject(timeoutError);
    }, request.timeoutMs ?? 0);
    const normalizeFailure = (error: unknown): ApiProxyError => {
      if (request.method !== "GET" && sent) {
        return new ApiProxyError("result-uncertain");
      }
      return error instanceof ApiProxyError
        ? error
        : new ApiProxyError("transport");
    };
    try {
      clientRequest = requestImplementation(
        {
          socketPath: connection.socketPath,
          path: request.path,
          method: request.method,
          headers,
          agent: false,
          maxHeaderSize: 16 * 1024
        },
        (response) => {
          void collectResponse(response, connection, request).then(
            (result) => {
              if (!settled) {
                settled = true;
                clearTimeout(deadlineTimer);
                resolve(result);
              }
            },
            (error: unknown) => {
              if (!settled) {
                settled = true;
                clearTimeout(deadlineTimer);
                reject(normalizeFailure(error));
              }
            }
          );
        }
      );
    } catch {
      clearTimeout(deadlineTimer);
      reject(new ApiProxyError("transport"));
      return;
    }

    clientRequest.once("error", (error) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(deadlineTimer);
      reject(normalizeFailure(error));
    });
    clientRequest.setTimeout(request.timeoutMs ?? 0, () => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(deadlineTimer);
      clientRequest.destroy(timeoutError);
      reject(timeoutError);
    });
    sent = true;
    clientRequest.end(body);
  });
}

export class ApiProxy {
  private activeRequests = 0;

  constructor(
    private readonly maxConcurrentRequests = 8,
    private readonly dependencies: ApiProxyDependencies = {}
  ) {
    if (
      !Number.isInteger(maxConcurrentRequests) ||
      maxConcurrentRequests < 1 ||
      maxConcurrentRequests > 32
    ) {
      throw new TypeError("Invalid API proxy concurrency");
    }
  }

  async request(
    input: ApiRequest,
    connection: SidecarConnection | undefined,
    prepareAfterAdmission?: (input: ApiRequest) => Promise<ApiRequest>
  ): Promise<ApiResponse> {
    if (!connection) {
      throw new ApiProxyError("unavailable");
    }
    if (this.activeRequests >= this.maxConcurrentRequests) {
      throw new ApiProxyError("busy");
    }
    this.activeRequests += 1;
    try {
      const reviewed = prepareAfterAdmission
        ? await prepareAfterAdmission(input)
        : input;
      if (
        reviewed.method !== input.method ||
        reviewed.path !== input.path ||
        reviewed.timeoutMs !== input.timeoutMs
      ) {
        throw new ApiProxyError("invalid-response");
      }
      return await proxyApiRequest(reviewed, connection, this.dependencies);
    } finally {
      this.activeRequests -= 1;
    }
  }
}

import type { IpcMain, IpcMainInvokeEvent } from "electron";
import {
  DEFAULT_API_TIMEOUT_MS,
  IPC_CHANNELS,
  MAX_API_TIMEOUT_MS,
  MAX_IPC_PAYLOAD_BYTES,
  MAX_REQUEST_BODY_BYTES,
  MIN_API_TIMEOUT_MS,
  isJsonValue,
  serializedByteLength,
  type ApiErrorCode,
  type ApiIpcResult,
  type ApiRequest,
  type ApiResponse,
  type LocalSourceErrorCode,
  type LocalSourceIpcResult,
  type LocalSourceSelection,
  type McpSetupErrorCode,
  type McpSetupIpcResult,
  type McpSetupStatus,
  type RuntimeStatus
} from "../contracts";
import { isLocalSourceGrant } from "./localSourceGrants";

const ENCODED_SEGMENT = "(?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2})+";
const route = (source: string): RegExp => new RegExp(`^${source}$`);

type QueryRule =
  | { type: "none" }
  | { type: "page-path" }
  | { type: "pending-proposals" };

interface RouteRule {
  method: ApiRequest["method"];
  pathname: RegExp;
  query: QueryRule;
}

const API_ROUTES: readonly RouteRule[] = [
  { method: "GET", pathname: route("/api/health"), query: { type: "none" } },
  {
    method: "GET",
    pathname: route("/api/system/status"),
    query: { type: "none" }
  },
  { method: "GET", pathname: route("/api/settings"), query: { type: "none" } },
  {
    method: "PATCH",
    pathname: route("/api/settings"),
    query: { type: "none" }
  },
  {
    method: "GET",
    pathname: route("/api/embedding/models"),
    query: { type: "none" }
  },
  {
    method: "POST",
    pathname: route("/api/embedding/models/validate"),
    query: { type: "none" }
  },
  {
    method: "POST",
    pathname: route("/api/rebuilds"),
    query: { type: "none" }
  },
  {
    method: "GET",
    pathname: route("/api/libraries"),
    query: { type: "none" }
  },
  {
    method: "POST",
    pathname: route("/api/libraries"),
    query: { type: "none" }
  },
  {
    method: "POST",
    pathname: route(`/api/libraries/${ENCODED_SEGMENT}/ingest`),
    query: { type: "none" }
  },
  { method: "GET", pathname: route("/api/jobs"), query: { type: "none" } },
  {
    method: "GET",
    pathname: route(`/api/jobs/${ENCODED_SEGMENT}`),
    query: { type: "none" }
  },
  {
    method: "POST",
    pathname: route(`/api/jobs/${ENCODED_SEGMENT}/cancel`),
    query: { type: "none" }
  },
  {
    method: "POST",
    pathname: route(`/api/jobs/${ENCODED_SEGMENT}/retry`),
    query: { type: "none" }
  },
  {
    method: "GET",
    pathname: route(`/api/libraries/${ENCODED_SEGMENT}/pages`),
    query: { type: "none" }
  },
  {
    method: "GET",
    pathname: route(`/api/libraries/${ENCODED_SEGMENT}/page`),
    query: { type: "page-path" }
  },
  {
    method: "GET",
    pathname: route(`/api/libraries/${ENCODED_SEGMENT}/proposals`),
    query: { type: "pending-proposals" }
  },
  {
    method: "POST",
    pathname: route(`/api/proposals/${ENCODED_SEGMENT}/publish`),
    query: { type: "none" }
  },
  {
    method: "POST",
    pathname: route(`/api/proposals/${ENCODED_SEGMENT}/reject`),
    query: { type: "none" }
  },
  { method: "POST", pathname: route("/api/query"), query: { type: "none" } },
  {
    method: "GET",
    pathname: route(`/api/libraries/${ENCODED_SEGMENT}/graph`),
    query: { type: "none" }
  },
  {
    method: "POST",
    pathname: route(`/api/libraries/${ENCODED_SEGMENT}/lint`),
    query: { type: "none" }
  }
];

export class IpcValidationError extends Error {
  constructor(readonly code: "forbidden" | "invalid-payload" | "unavailable") {
    super(`Desktop IPC ${code}`);
    this.name = "IpcValidationError";
  }
}

function validateEncodedPath(pathname: string): boolean {
  if (
    !pathname.startsWith("/api/") ||
    pathname.includes("\\") ||
    pathname.includes("//") ||
    /%(?![0-9a-fA-F]{2})/.test(pathname) ||
    /[\u0000-\u001f\u007f]/.test(pathname)
  ) {
    return false;
  }

  return pathname
    .split("/")
    .slice(1)
    .every((encodedSegment) => {
      if (!encodedSegment) {
        return false;
      }
      try {
        const decoded = decodeURIComponent(encodedSegment);
        return (
          !decoded.includes("/") &&
          !decoded.includes("\\") &&
          !/[\u0000-\u001f\u007f]/.test(decoded) &&
          decoded !== "." &&
          decoded !== ".." &&
          /^[A-Za-z0-9._~ -]+$/.test(decoded)
        );
      } catch {
        return false;
      }
    });
}

function validateQuery(rule: QueryRule, query: string): boolean {
  if (rule.type === "none") {
    return query === "";
  }
  if (/%(?![0-9a-fA-F]{2})/.test(query)) {
    return false;
  }

  const params = new URLSearchParams(query);
  const entries = [...params.entries()];
  if (rule.type === "pending-proposals") {
    return (
      entries.length === 1 &&
      entries[0]?.[0] === "status" &&
      entries[0]?.[1] === "pending"
    );
  }

  const value = entries[0]?.[1];
  return (
    entries.length === 1 &&
    entries[0]?.[0] === "path" &&
    typeof value === "string" &&
    value.length > 0 &&
    Buffer.byteLength(value, "utf8") <= 8_192 &&
    !value.startsWith("/") &&
    !value.includes("\\") &&
    !/[\u0000-\u001f\u007f]/.test(value) &&
    /^[A-Za-z0-9._~ /-]+$/.test(value) &&
    value.endsWith(".md") &&
    value
      .split("/")
      .every(
        (segment) =>
          segment !== "" && segment !== "." && segment !== ".."
      )
  );
}

export function isAllowedApiRoute(
  method: ApiRequest["method"],
  requestPath: string
): boolean {
  if (
    typeof requestPath !== "string" ||
    Buffer.byteLength(requestPath, "utf8") > 16_384 ||
    requestPath.includes("#")
  ) {
    return false;
  }
  const separator = requestPath.indexOf("?");
  const pathname =
    separator === -1 ? requestPath : requestPath.slice(0, separator);
  const query = separator === -1 ? "" : requestPath.slice(separator + 1);
  if (!validateEncodedPath(pathname)) {
    return false;
  }

  return API_ROUTES.some(
    (candidate) =>
      candidate.method === method &&
      candidate.pathname.test(pathname) &&
      validateQuery(candidate.query, query)
  );
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

type FieldValidator = (value: unknown) => boolean;

function exactObject(
  value: unknown,
  required: Record<string, FieldValidator>,
  optional: Record<string, FieldValidator> = {}
): boolean {
  if (!isPlainRecord(value)) {
    return false;
  }
  const keys = Object.keys(value);
  const allowed = new Set([...Object.keys(required), ...Object.keys(optional)]);
  return (
    keys.every((key) => allowed.has(key)) &&
    Object.entries(required).every(
      ([key, validator]) =>
        Object.prototype.hasOwnProperty.call(value, key) &&
        validator(value[key])
    ) &&
    Object.entries(optional).every(
      ([key, validator]) =>
        !Object.prototype.hasOwnProperty.call(value, key) ||
        validator(value[key])
    )
  );
}

const boundedString =
  (maximumCharacters: number, allowEmpty = false): FieldValidator =>
  (value) =>
    typeof value === "string" &&
    (allowEmpty || value.length > 0) &&
    value.length <= maximumCharacters &&
    !/[\u0000-\u001f\u007f]/.test(value);

const optionalIdentifier = boundedString(200);
const CURATED_EMBEDDING_MODELS = new Set([
  "embeddinggemma-300m-q8",
  "qwen3-embedding-0.6b-q8"
]);
const embeddingModel: FieldValidator = (value) => {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > 500 ||
    value.trim() !== value ||
    /\s|[\u0000-\u001f\u007f]/.test(value)
  ) {
    return false;
  }
  if (CURATED_EMBEDDING_MODELS.has(value)) {
    return true;
  }
  if (
    !/^hf:[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+\/[A-Za-z0-9._+/-]+\.gguf$/.test(
      value
    ) ||
    value.includes("//")
  ) {
    return false;
  }
  return value
    .slice(3)
    .split("/")
    .every((segment) => segment !== "" && segment !== "." && segment !== "..");
};
const ingestProvider: FieldValidator = (value) =>
  typeof value === "string" &&
  ["auto", "codex", "codex_cli"].includes(value);
const providerPolicy: FieldValidator = (value) =>
  value === "codex_only" || value === "codex_then_cursor";
const positiveInteger = (maximum: number): FieldValidator => (value) =>
  typeof value === "number" &&
  Number.isInteger(value) &&
  value >= 1 &&
  value <= maximum;

export function isAllowedLibrarySource(value: unknown): boolean {
  if (typeof value !== "string" || value.length > 2_048) {
    return false;
  }
  let source: URL;
  try {
    source = new URL(value);
  } catch {
    return false;
  }
  if (
    source.protocol !== "https:" ||
    source.hostname !== "github.com" ||
    source.username !== "" ||
    source.password !== "" ||
    (source.port !== "" && source.port !== "443") ||
    source.search !== "" ||
    source.hash !== ""
  ) {
    return false;
  }
  const segments = source.pathname.split("/").slice(1);
  if (segments.length !== 2) {
    return false;
  }
  const [owner, repository] = segments;
  return (
    typeof owner === "string" &&
    typeof repository === "string" &&
    /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/.test(owner) &&
    /^[A-Za-z0-9_.-]{1,100}(?:\.git)?$/.test(repository) &&
    !repository.includes("..")
  );
}

export function isAllowedLibrarySourceInput(value: unknown): boolean {
  return isAllowedLibrarySource(value) || isLocalSourceGrant(value);
}

function validateRequestBody(
  method: ApiRequest["method"],
  requestPath: string,
  body: unknown,
  present: boolean
): boolean {
  if (method === "GET") {
    return !present;
  }
  const pathname = requestPath.split("?", 1)[0] ?? "";

  if (method === "PATCH" && pathname === "/api/settings") {
    return (
      present &&
      exactObject(
        body,
        {},
        {
          provider_policy: providerPolicy,
          cursor_fallback_consent: (value) => typeof value === "boolean",
          concurrency: (value) => value === 1,
          embedding_model: embeddingModel,
          expected_revision: (value) =>
            typeof value === "number" &&
            Number.isInteger(value) &&
            value >= 1
        }
      ) &&
      Object.keys(body as Record<string, unknown>).length > 0
    );
  }
  if (method !== "POST") {
    return false;
  }

  if (pathname === "/api/embedding/models/validate") {
    return present && exactObject(body, { model: embeddingModel });
  }
  if (pathname === "/api/rebuilds") {
    return (
      present &&
      exactObject(
        body,
        {},
        {
          library_id: optionalIdentifier,
          model: embeddingModel
        }
      )
    );
  }
  if (pathname === "/api/libraries") {
    return (
      present &&
      exactObject(
        body,
        {
          name: boundedString(160),
          source: isAllowedLibrarySourceInput
        },
        {
          slug: boundedString(180),
          description: boundedString(4_000, true)
        }
      )
    );
  }
  if (new RegExp(`^/api/libraries/${ENCODED_SEGMENT}/ingest$`).test(pathname)) {
    return (
      present &&
      exactObject(
        body,
        {},
        {
          ref: boundedString(200),
          provider: ingestProvider,
          version: boundedString(160),
          auto_publish: (value) => typeof value === "boolean"
        }
      )
    );
  }
  if (pathname === "/api/query") {
    return (
      present &&
      exactObject(
        body,
        {
          query: boundedString(4_000)
        },
        {
          library_id: optionalIdentifier,
          version: boundedString(160),
          limit: positiveInteger(30)
        }
      )
    );
  }
  if (
    new RegExp(`^/api/proposals/${ENCODED_SEGMENT}/reject$`).test(pathname)
  ) {
    return present && exactObject(body, {});
  }
  if (
    new RegExp(`^/api/jobs/${ENCODED_SEGMENT}/(?:cancel|retry)$`).test(pathname) ||
    new RegExp(`^/api/proposals/${ENCODED_SEGMENT}/publish$`).test(pathname) ||
    new RegExp(`^/api/libraries/${ENCODED_SEGMENT}/lint$`).test(pathname)
  ) {
    return !present;
  }
  return false;
}

export function parseApiRequest(value: unknown): ApiRequest {
  try {
    if (serializedByteLength(value) > MAX_IPC_PAYLOAD_BYTES) {
      throw new IpcValidationError("invalid-payload");
    }
  } catch {
    throw new IpcValidationError("invalid-payload");
  }

  if (!isPlainRecord(value)) {
    throw new IpcValidationError("invalid-payload");
  }
  const allowedKeys = new Set(["method", "path", "body", "timeoutMs"]);
  if (Object.keys(value).some((key) => !allowedKeys.has(key))) {
    throw new IpcValidationError("invalid-payload");
  }

  const method = value.method;
  const requestPath = value.path;
  if (
    (method !== "GET" && method !== "POST" && method !== "PATCH") ||
    typeof requestPath !== "string" ||
    !isAllowedApiRoute(method, requestPath)
  ) {
    throw new IpcValidationError("invalid-payload");
  }

  const hasBody = Object.prototype.hasOwnProperty.call(value, "body");
  if (
    (hasBody &&
      (!isJsonValue(value.body) ||
        serializedByteLength(value.body) > MAX_REQUEST_BODY_BYTES)) ||
    !validateRequestBody(method, requestPath, value.body, hasBody)
  ) {
    throw new IpcValidationError("invalid-payload");
  }

  let timeoutMs = DEFAULT_API_TIMEOUT_MS;
  if (value.timeoutMs !== undefined) {
    if (
      typeof value.timeoutMs !== "number" ||
      !Number.isFinite(value.timeoutMs)
    ) {
      throw new IpcValidationError("invalid-payload");
    }
    timeoutMs = Math.max(
      MIN_API_TIMEOUT_MS,
      Math.min(MAX_API_TIMEOUT_MS, Math.trunc(value.timeoutMs))
    );
  }

  const parsed: ApiRequest = {
    method,
    path: requestPath,
    timeoutMs
  };
  if (hasBody) {
    parsed.body = value.body as NonNullable<ApiRequest["body"]>;
  }
  return parsed;
}

interface SenderLike {
  senderFrame?: { url: string } | null;
  sender: { mainFrame: { url: string } | null };
}

export function isTrustedIpcSender(event: SenderLike): boolean {
  const senderFrame = event.senderFrame;
  const mainFrame = event.sender.mainFrame;
  if (!senderFrame || !mainFrame || senderFrame !== mainFrame) {
    return false;
  }
  try {
    const senderUrl = new URL(senderFrame.url);
    return (
      senderUrl.protocol === "lcf:" &&
      senderUrl.hostname === "app" &&
      senderUrl.port === "" &&
      senderUrl.username === "" &&
      senderUrl.password === ""
    );
  } catch {
    return false;
  }
}

export interface IpcDependencies {
  apiRequest(input: ApiRequest): Promise<ApiResponse>;
  runtimeGet(): RuntimeStatus;
  runtimeRetry(): Promise<RuntimeStatus>;
  mcpSetupGet(): Promise<McpSetupStatus>;
  mcpSetupConfigure(): Promise<McpSetupStatus>;
  mcpSetupClear(): Promise<McpSetupStatus>;
  localSourceSelect(): Promise<LocalSourceSelection | null>;
  appVersion(): string;
}

function stableApiErrorCode(error: unknown): ApiErrorCode {
  const code =
    error &&
    typeof error === "object" &&
    "code" in error &&
    typeof error.code === "string"
      ? error.code
      : "unavailable";
  const allowed = new Set([
    "unavailable",
    "request-too-large",
    "response-too-large",
    "timeout",
    "result-uncertain",
    "busy",
    "invalid-response",
    "transport"
  ]);
  return (allowed.has(code) ? code : "unavailable") as ApiErrorCode;
}

function assertTrusted(event: IpcMainInvokeEvent): void {
  if (!isTrustedIpcSender(event)) {
    throw new IpcValidationError("forbidden");
  }
}

function assertNoArguments(values: readonly unknown[]): void {
  if (values.length !== 0) {
    throw new IpcValidationError("invalid-payload");
  }
}

function stableMcpSetupErrorCode(error: unknown): McpSetupErrorCode {
  const code =
    error &&
    typeof error === "object" &&
    "code" in error &&
    typeof error.code === "string"
      ? error.code
      : "unavailable";
  const allowed = new Set<McpSetupErrorCode>([
    "busy",
    "not-installed",
    "not-authenticated",
    "unsupported-installation",
    "move-to-applications",
    "source-debug",
    "bundle-invalid",
    "name-conflict",
    "timeout",
    "invalid-response",
    "unavailable"
  ]);
  return allowed.has(code as McpSetupErrorCode)
    ? (code as McpSetupErrorCode)
    : "unavailable";
}

function stableLocalSourceErrorCode(error: unknown): LocalSourceErrorCode {
  const code =
    error &&
    typeof error === "object" &&
    "code" in error &&
    typeof error.code === "string"
      ? error.code
      : "unavailable";
  const allowed = new Set<LocalSourceErrorCode>([
    "busy",
    "unsafe-selection",
    "invalid-response",
    "unavailable"
  ]);
  return allowed.has(code as LocalSourceErrorCode)
    ? (code as LocalSourceErrorCode)
    : "unavailable";
}

export function registerIpcHandlers(
  ipcMain: IpcMain,
  dependencies: IpcDependencies
): void {
  ipcMain.handle(IPC_CHANNELS.apiRequest, async (event, ...values: unknown[]) => {
    assertTrusted(event);
    if (values.length !== 1) {
      throw new IpcValidationError("invalid-payload");
    }
    const [value] = values;
    try {
      const response = await dependencies.apiRequest(parseApiRequest(value));
      return { ok: true, value: response } satisfies ApiIpcResult;
    } catch (error) {
      if (error instanceof IpcValidationError) {
        throw error;
      }
      return {
        ok: false,
        error: { code: stableApiErrorCode(error) }
      } satisfies ApiIpcResult;
    }
  });
  ipcMain.handle(IPC_CHANNELS.runtimeGet, (event, ...values: unknown[]) => {
    assertTrusted(event);
    assertNoArguments(values);
    return dependencies.runtimeGet();
  });
  ipcMain.handle(IPC_CHANNELS.runtimeRetry, async (event, ...values: unknown[]) => {
    assertTrusted(event);
    assertNoArguments(values);
    return dependencies.runtimeRetry();
  });
  const mcpSetupHandler =
    (
      operation: () => Promise<McpSetupStatus>
    ) =>
    async (
      event: IpcMainInvokeEvent,
      ...values: unknown[]
    ): Promise<McpSetupIpcResult> => {
      assertTrusted(event);
      assertNoArguments(values);
      try {
        return {
          ok: true,
          value: await operation()
        };
      } catch (error) {
        return {
          ok: false,
          error: { code: stableMcpSetupErrorCode(error) }
        };
      }
    };
  ipcMain.handle(
    IPC_CHANNELS.mcpSetupGet,
    mcpSetupHandler(dependencies.mcpSetupGet)
  );
  ipcMain.handle(
    IPC_CHANNELS.mcpSetupConfigure,
    mcpSetupHandler(dependencies.mcpSetupConfigure)
  );
  ipcMain.handle(
    IPC_CHANNELS.mcpSetupClear,
    mcpSetupHandler(dependencies.mcpSetupClear)
  );
  ipcMain.handle(
    IPC_CHANNELS.localSourceSelect,
    async (
      event: IpcMainInvokeEvent,
      ...values: unknown[]
    ): Promise<LocalSourceIpcResult> => {
      assertTrusted(event);
      assertNoArguments(values);
      try {
        return {
          ok: true,
          value: await dependencies.localSourceSelect()
        };
      } catch (error) {
        return {
          ok: false,
          error: { code: stableLocalSourceErrorCode(error) }
        };
      }
    }
  );
  ipcMain.handle(IPC_CHANNELS.appVersion, (event, ...values: unknown[]) => {
    assertTrusted(event);
    assertNoArguments(values);
    return dependencies.appVersion();
  });
}

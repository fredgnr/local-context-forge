export const MCP_BRIDGE_PROTOCOL_VERSION = "1.0" as const;
export const MCP_BRIDGE_SOCKET_NAME = "mcp.sock" as const;
export const MCP_LAUNCH_FILE_NAME = "launch.json" as const;
export const MCP_RENDEZVOUS_FILE_NAME = "mcp-rendezvous.json" as const;
export const MCP_RUNTIME_DIRECTORY_PREFIX = "lcf-mcp-" as const;

export const MAX_MCP_BRIDGE_REQUEST_BYTES = 16 * 1024;
export const MAX_MCP_BRIDGE_RESPONSE_BYTES = 4 * 1024 * 1024;
export const MAX_MCP_LIBRARY_NAME_BYTES = 512;
export const MAX_MCP_LIBRARY_ID_BYTES = 256;
export const MAX_MCP_QUERY_BYTES = 8 * 1024;
export const MCP_QUERY_RESULT_LIMIT = 8;
export const MCP_RESOLVE_RESULT_LIMIT = 20;

export type McpBridgeErrorCode =
  | "approval_denied"
  | "backend_unavailable"
  | "busy"
  | "expired"
  | "forbidden"
  | "invalid_request"
  | "invalid_response"
  | "not_found"
  | "protocol_mismatch"
  | "rate_limited"
  | "request_too_large"
  | "revoked"
  | "stale_revision"
  | "timeout"
  | "unauthorized"
  | "unavailable";

export interface McpClientDescriptor {
  name: string;
  version: string;
}

export interface McpBridgeAuthorization {
  capability: string;
  corpusRevision: number;
  expiresAt: number;
  protocol: typeof MCP_BRIDGE_PROTOCOL_VERSION;
  role: "mcp-bridge";
  service: "local-context-forge";
  sessionId: string;
}

export interface McpResolveInput {
  corpusRevision: number;
  libraryName: string;
  query: string;
}

export interface McpQueryInput {
  corpusRevision: number;
  libraryId: string;
  query: string;
}

export interface McpBridgeResult {
  corpusRevision: number;
  text: string;
}

export interface McpBridgeErrorBody {
  error: {
    code: McpBridgeErrorCode;
  };
}

export function isPlainObject(
  value: unknown
): value is Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

export function hasExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[]
): boolean {
  const keys = Object.keys(value);
  return (
    keys.length === expected.length &&
    keys.every((key) => expected.includes(key))
  );
}

export function isCorpusRevision(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

export function isBoundedText(
  value: unknown,
  maximumBytes: number,
  allowEmpty = false
): value is string {
  return (
    typeof value === "string" &&
    (allowEmpty || value.length > 0) &&
    Buffer.byteLength(value, "utf8") <= maximumBytes &&
    value === value.normalize("NFC") &&
    !value.includes("\0")
  );
}

export function isMcpLibraryId(value: unknown): value is string {
  return (
    isBoundedText(value, MAX_MCP_LIBRARY_ID_BYTES) &&
    /^\/local\/[a-z0-9][a-z0-9._-]{0,179}$/.test(value) &&
    !value.includes("..")
  );
}

export function isSafeRepositoryPath(value: unknown): value is string {
  if (
    !isBoundedText(value, 8_192) ||
    value.startsWith("/") ||
    value.startsWith("~") ||
    /^[A-Za-z]:\//.test(value) ||
    value.includes("\\") ||
    /[\u0001-\u001f\u007f]/.test(value)
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

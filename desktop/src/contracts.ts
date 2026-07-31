export const DESKTOP_BRIDGE_VERSION = "1.0" as const;
export const SIDECAR_PROTOCOL_VERSION = "1.0" as const;

export const IPC_CHANNELS = {
  apiRequest: "lcf:v1:api:request",
  runtimeGet: "lcf:v1:runtime:get",
  runtimeRetry: "lcf:v1:runtime:retry",
  runtimeChanged: "lcf:v1:runtime:changed",
  appVersion: "lcf:v1:app:version"
} as const;

export const MAX_REQUEST_BODY_BYTES = 256 * 1024;
export const MAX_IPC_PAYLOAD_BYTES = MAX_REQUEST_BODY_BYTES + 8 * 1024;
export const MAX_RESPONSE_BODY_BYTES = 16 * 1024 * 1024;
export const DEFAULT_API_TIMEOUT_MS = 30_000;
export const MIN_API_TIMEOUT_MS = 1_000;
export const MAX_API_TIMEOUT_MS = 120_000;

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue =
  | JsonPrimitive
  | JsonValue[]
  | { [key: string]: JsonValue };

export type ApiMethod = "GET" | "POST" | "PATCH";

export interface ApiRequest {
  method: ApiMethod;
  path: string;
  body?: JsonValue;
  timeoutMs?: number;
}

export interface ApiResponse {
  status: number;
  body: JsonValue | string | null;
}

export type ApiErrorCode =
  | "unavailable"
  | "request-too-large"
  | "response-too-large"
  | "timeout"
  | "result-uncertain"
  | "busy"
  | "invalid-response"
  | "transport";

export type ApiIpcResult =
  | { ok: true; value: ApiResponse }
  | { ok: false; error: { code: ApiErrorCode } };

export class DesktopApiError extends Error {
  constructor(readonly code: ApiErrorCode) {
    super(`Desktop API request failed (${code})`);
    this.name = "DesktopApiError";
  }
}

export type RuntimeState =
  | "stopped"
  | "starting"
  | "ready"
  | "stopping"
  | "failed";

export type RuntimeFailureReason =
  | "configuration"
  | "launch-failed"
  | "runtime-invalid"
  | "startup-timeout"
  | "handshake-rejected"
  | "sidecar-exited"
  | "shutdown-timeout";

export interface RuntimeStatus {
  state: RuntimeState;
  canRetry: boolean;
  reason?: RuntimeFailureReason;
}

export interface DesktopBridge {
  readonly version: typeof DESKTOP_BRIDGE_VERSION;
  readonly api: {
    request(input: ApiRequest): Promise<ApiResponse>;
  };
  readonly runtime: {
    get(): Promise<RuntimeStatus>;
    retry(): Promise<RuntimeStatus>;
    subscribe(listener: (status: RuntimeStatus) => void): () => void;
  };
  readonly app: {
    version(): Promise<string>;
  };
}

export function serializedByteLength(value: unknown): number {
  const serialized = JSON.stringify(value);
  if (serialized === undefined) {
    throw new TypeError("Value is not JSON serializable");
  }
  return Buffer.byteLength(serialized, "utf8");
}

export function isJsonValue(
  value: unknown,
  depth = 0,
  seen: WeakSet<object> = new WeakSet()
): value is JsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return true;
  }
  if (typeof value === "number") {
    return Number.isFinite(value);
  }
  if (typeof value !== "object" || depth > 32 || seen.has(value)) {
    return false;
  }

  seen.add(value);
  if (Array.isArray(value)) {
    const valid = value.every((item) => isJsonValue(item, depth + 1, seen));
    seen.delete(value);
    return valid;
  }

  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    seen.delete(value);
    return false;
  }
  const valid = Object.entries(value).every(
    ([key, item]) =>
      key.length <= 256 && isJsonValue(item, depth + 1, seen)
  );
  seen.delete(value);
  return valid;
}

export function isRuntimeStatus(value: unknown): value is RuntimeStatus {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    return false;
  }
  const candidate = value as Partial<RuntimeStatus>;
  const keys = Object.keys(value);
  const states: RuntimeState[] = [
    "stopped",
    "starting",
    "ready",
    "stopping",
    "failed"
  ];
  const reasons: RuntimeFailureReason[] = [
    "configuration",
    "launch-failed",
    "runtime-invalid",
    "startup-timeout",
    "handshake-rejected",
    "sidecar-exited",
    "shutdown-timeout"
  ];
  return (
    typeof candidate.state === "string" &&
    states.includes(candidate.state as RuntimeState) &&
    typeof candidate.canRetry === "boolean" &&
    keys.every((key) => key === "state" || key === "canRetry" || key === "reason") &&
    keys.length === (candidate.reason === undefined ? 2 : 3) &&
    (candidate.reason === undefined ||
      reasons.includes(candidate.reason as RuntimeFailureReason))
  );
}

export const DESKTOP_BRIDGE_VERSION = "1.0" as const;
export const SIDECAR_PROTOCOL_VERSION = "1.0" as const;

export const IPC_CHANNELS = {
  apiRequest: "lcf:v1:api:request",
  runtimeGet: "lcf:v1:runtime:get",
  runtimeRetry: "lcf:v1:runtime:retry",
  runtimeChanged: "lcf:v1:runtime:changed",
  mcpSetupGet: "lcf:v1:mcp-setup:get",
  mcpSetupConfigure: "lcf:v1:mcp-setup:configure",
  mcpSetupClear: "lcf:v1:mcp-setup:clear",
  updateStatus: "lcf:v1:update:status",
  updateCheck: "lcf:v1:update:check",
  updateDownloadOrOpen: "lcf:v1:update:download-or-open",
  updateCancel: "lcf:v1:update:cancel",
  updateOpenReleasePage: "lcf:v1:update:open-release-page",
  updateChanged: "lcf:v1:update:changed",
  localSourceSelect: "lcf:v1:local-source:select",
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

export type McpSetupCodexState =
  | "ready"
  | "not-installed"
  | "not-authenticated"
  | "unsupported-installation"
  | "unavailable";

export type McpSetupConfigurationState =
  | "configured"
  | "not-configured"
  | "needs-reconnect"
  | "name-conflict"
  | "unknown";

export type McpSetupInstallState =
  | "ready"
  | "move-to-applications"
  | "source-debug"
  | "bundle-invalid";

export interface McpSetupStatus {
  readonly provider: "codex_cli";
  readonly codexState: McpSetupCodexState;
  readonly configurationState: McpSetupConfigurationState;
  readonly installState: McpSetupInstallState;
  readonly canConfigure: boolean;
  readonly canClear: boolean;
  readonly restartRequired: boolean;
}

export type McpSetupErrorCode =
  | "busy"
  | "not-installed"
  | "not-authenticated"
  | "unsupported-installation"
  | "move-to-applications"
  | "source-debug"
  | "bundle-invalid"
  | "name-conflict"
  | "timeout"
  | "invalid-response"
  | "unavailable";

export type McpSetupIpcResult =
  | { ok: true; value: McpSetupStatus }
  | { ok: false; error: { code: McpSetupErrorCode } };

export class DesktopMcpSetupError extends Error {
  constructor(readonly code: McpSetupErrorCode) {
    super(`Desktop MCP setup failed (${code})`);
    this.name = "DesktopMcpSetupError";
  }
}

export type UpdateState =
  | "unavailable"
  | "idle"
  | "checking"
  | "up-to-date"
  | "available"
  | "downloading"
  | "ready"
  | "opening"
  | "opened"
  | "error";

export type UpdateUnavailableReason =
  | "source-build"
  | "unsupported-platform"
  | "version-invalid"
  | "key-unprovisioned"
  | "key-invalid";

export type UpdateErrorCode =
  | "unavailable"
  | "busy"
  | "cancelled"
  | "network"
  | "timeout"
  | "response-too-large"
  | "metadata-invalid"
  | "channel-mismatch"
  | "signature-invalid"
  | "manifest-invalid"
  | "asset-invalid"
  | "download-failed"
  | "download-too-large"
  | "digest-mismatch"
  | "cache-unsafe"
  | "open-failed"
  | "external-open-failed"
  | "invalid-response";

export interface UpdateProgress {
  readonly receivedBytes: number;
  readonly totalBytes: number;
}

export interface UpdateStatus {
  readonly state: UpdateState;
  readonly currentVersion: string;
  readonly channel: string;
  readonly availableVersion: string | null;
  readonly progress: UpdateProgress | null;
  readonly errorCode: UpdateErrorCode | null;
  readonly unavailableReason: UpdateUnavailableReason | null;
  readonly canCheck: boolean;
  readonly canDownloadOrOpen: boolean;
  readonly canOpenReleasePage: boolean;
  readonly automaticApply: false;
  readonly automaticApplyReason: "val-update-001-not-passed";
}

export type UpdateIpcResult =
  | { ok: true; value: UpdateStatus }
  | { ok: false; error: { code: UpdateErrorCode } };

export class DesktopUpdateError extends Error {
  constructor(readonly code: UpdateErrorCode) {
    super(`Desktop update request failed (${code})`);
    this.name = "DesktopUpdateError";
  }
}

export interface LocalSourceSelection {
  readonly grantId: string;
  readonly displayName: string;
}

export type LocalSourceErrorCode =
  | "busy"
  | "unsafe-selection"
  | "invalid-response"
  | "unavailable";

export type LocalSourceIpcResult =
  | { ok: true; value: LocalSourceSelection | null }
  | { ok: false; error: { code: LocalSourceErrorCode } };

export class DesktopLocalSourceError extends Error {
  constructor(readonly code: LocalSourceErrorCode) {
    super(`Desktop local source request failed (${code})`);
    this.name = "DesktopLocalSourceError";
  }
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
  readonly mcp: {
    status(): Promise<McpSetupStatus>;
    configure(): Promise<McpSetupStatus>;
    clear(): Promise<McpSetupStatus>;
  };
  readonly update: {
    status(): Promise<UpdateStatus>;
    check(): Promise<UpdateStatus>;
    downloadOrOpen(): Promise<UpdateStatus>;
    cancel(): Promise<UpdateStatus>;
    openReleasePage(): Promise<UpdateStatus>;
    subscribe(listener: (status: UpdateStatus) => void): () => void;
  };
  readonly sources: {
    selectRepository(): Promise<LocalSourceSelection | null>;
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

export function isLocalSourceSelection(
  value: unknown
): value is LocalSourceSelection {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    return false;
  }
  const candidate = value as Partial<LocalSourceSelection>;
  return (
    Object.keys(value).length === 2 &&
    Object.keys(value).every(
      (key) => key === "grantId" || key === "displayName"
    ) &&
    typeof candidate.grantId === "string" &&
    /^lcf-local:[0-9a-f]{64}$/.test(candidate.grantId) &&
    typeof candidate.displayName === "string" &&
    candidate.displayName.length > 0 &&
    Array.from(candidate.displayName).length <= 120 &&
    candidate.displayName.trim() === candidate.displayName &&
    candidate.displayName !== "." &&
    candidate.displayName !== ".." &&
    !candidate.displayName.includes("/") &&
    !candidate.displayName.includes("\\") &&
    candidate.displayName.normalize("NFC") === candidate.displayName &&
    !/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/.test(
      candidate.displayName
    )
  );
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

export function isMcpSetupStatus(value: unknown): value is McpSetupStatus {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    return false;
  }
  const candidate = value as Partial<McpSetupStatus>;
  const codexStates: readonly McpSetupCodexState[] = [
    "ready",
    "not-installed",
    "not-authenticated",
    "unsupported-installation",
    "unavailable"
  ];
  const configurationStates: readonly McpSetupConfigurationState[] = [
    "configured",
    "not-configured",
    "needs-reconnect",
    "name-conflict",
    "unknown"
  ];
  const installStates: readonly McpSetupInstallState[] = [
    "ready",
    "move-to-applications",
    "source-debug",
    "bundle-invalid"
  ];
  return (
    Object.keys(value).length === 7 &&
    Object.keys(value).every((key) =>
      [
        "provider",
        "codexState",
        "configurationState",
        "installState",
        "canConfigure",
        "canClear",
        "restartRequired"
      ].includes(key)
    ) &&
    candidate.provider === "codex_cli" &&
    codexStates.includes(candidate.codexState as McpSetupCodexState) &&
    configurationStates.includes(
      candidate.configurationState as McpSetupConfigurationState
    ) &&
    installStates.includes(
      candidate.installState as McpSetupInstallState
    ) &&
    typeof candidate.canConfigure === "boolean" &&
    typeof candidate.canClear === "boolean" &&
    typeof candidate.restartRequired === "boolean"
  );
}

export function isUpdateStatus(value: unknown): value is UpdateStatus {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    return false;
  }
  const candidate = value as Partial<UpdateStatus>;
  const keys = [
    "state",
    "currentVersion",
    "channel",
    "availableVersion",
    "progress",
    "errorCode",
    "unavailableReason",
    "canCheck",
    "canDownloadOrOpen",
    "canOpenReleasePage",
    "automaticApply",
    "automaticApplyReason"
  ];
  const states: readonly UpdateState[] = [
    "unavailable",
    "idle",
    "checking",
    "up-to-date",
    "available",
    "downloading",
    "ready",
    "opening",
    "opened",
    "error"
  ];
  const unavailableReasons: readonly UpdateUnavailableReason[] = [
    "source-build",
    "unsupported-platform",
    "version-invalid",
    "key-unprovisioned",
    "key-invalid"
  ];
  const errorCodes: readonly UpdateErrorCode[] = [
    "unavailable",
    "busy",
    "cancelled",
    "network",
    "timeout",
    "response-too-large",
    "metadata-invalid",
    "channel-mismatch",
    "signature-invalid",
    "manifest-invalid",
    "asset-invalid",
    "download-failed",
    "download-too-large",
    "digest-mismatch",
    "cache-unsafe",
    "open-failed",
    "external-open-failed",
    "invalid-response"
  ];
  const progress = candidate.progress;
  const progressValid =
    progress === null ||
    (progress !== undefined &&
      Object.getPrototypeOf(progress) === Object.prototype &&
      Object.keys(progress).length === 2 &&
      Object.keys(progress).every(
        (key) => key === "receivedBytes" || key === "totalBytes"
      ) &&
      Number.isSafeInteger(progress.receivedBytes) &&
      progress.receivedBytes >= 0 &&
      Number.isSafeInteger(progress.totalBytes) &&
      progress.totalBytes > 0 &&
      progress.receivedBytes <= progress.totalBytes);
  return (
    Object.keys(value).length === keys.length &&
    Object.keys(value).every((key) => keys.includes(key)) &&
    states.includes(candidate.state as UpdateState) &&
    typeof candidate.currentVersion === "string" &&
    candidate.currentVersion.length > 0 &&
    candidate.currentVersion.length <= 128 &&
    typeof candidate.channel === "string" &&
    /^[0-9A-Za-z-]{1,64}$/.test(candidate.channel) &&
    (candidate.availableVersion === null ||
      (typeof candidate.availableVersion === "string" &&
        candidate.availableVersion.length > 0 &&
        candidate.availableVersion.length <= 128)) &&
    progressValid &&
    (candidate.errorCode === null ||
      errorCodes.includes(candidate.errorCode as UpdateErrorCode)) &&
    (candidate.unavailableReason === null ||
      unavailableReasons.includes(
        candidate.unavailableReason as UpdateUnavailableReason
      )) &&
    typeof candidate.canCheck === "boolean" &&
    typeof candidate.canDownloadOrOpen === "boolean" &&
    typeof candidate.canOpenReleasePage === "boolean" &&
    candidate.automaticApply === false &&
    candidate.automaticApplyReason === "val-update-001-not-passed"
  );
}

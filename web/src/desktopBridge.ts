export const DESKTOP_BRIDGE_VERSION = "1.0" as const;
export const MAX_DESKTOP_API_TIMEOUT_MS = 120_000;

export type DesktopApiMethod = "GET" | "POST" | "PATCH";

export interface DesktopApiRequest {
  method: DesktopApiMethod;
  path: string;
  body?: unknown;
  timeoutMs: number;
}

export interface DesktopApiResponse {
  status: number;
  body: unknown;
}

export type DesktopMcpCodexState =
  | "ready"
  | "not-installed"
  | "not-authenticated"
  | "unsupported-installation"
  | "unavailable";

export type DesktopMcpConfigurationState =
  | "configured"
  | "not-configured"
  | "needs-reconnect"
  | "name-conflict"
  | "unknown";

export type DesktopMcpInstallState =
  | "ready"
  | "move-to-applications"
  | "source-debug"
  | "bundle-invalid";

export interface DesktopMcpSetupStatus {
  provider: "codex_cli";
  codexState: DesktopMcpCodexState;
  configurationState: DesktopMcpConfigurationState;
  installState: DesktopMcpInstallState;
  canConfigure: boolean;
  canClear: boolean;
  restartRequired: boolean;
}

export type DesktopMcpSetupErrorCode =
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

export type DesktopUpdateState =
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

export type DesktopUpdateErrorCode =
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

export interface DesktopUpdateStatus {
  state: DesktopUpdateState;
  currentVersion: string;
  channel: string;
  availableVersion: string | null;
  progress: { receivedBytes: number; totalBytes: number } | null;
  errorCode: DesktopUpdateErrorCode | null;
  unavailableReason:
    | "source-build"
    | "engineering-smoke"
    | "unsupported-platform"
    | "version-invalid"
    | "key-unprovisioned"
    | "key-invalid"
    | null;
  canCheck: boolean;
  canDownloadOrOpen: boolean;
  canOpenReleasePage: boolean;
  automaticApply: false;
  automaticApplyReason: "val-update-001-not-passed";
}

export interface DesktopLocalSourceSelection {
  grantId: string;
  displayName: string;
}

export interface LocalContextForgeBridge {
  readonly version: typeof DESKTOP_BRIDGE_VERSION;
  api: {
    request(input: DesktopApiRequest): Promise<DesktopApiResponse>;
  };
  mcp?: {
    status(): Promise<DesktopMcpSetupStatus>;
    configure(): Promise<DesktopMcpSetupStatus>;
    clear(): Promise<DesktopMcpSetupStatus>;
  };
  update?: {
    status(): Promise<DesktopUpdateStatus>;
    check(): Promise<DesktopUpdateStatus>;
    downloadOrOpen(): Promise<DesktopUpdateStatus>;
    cancel(): Promise<DesktopUpdateStatus>;
    openReleasePage(): Promise<DesktopUpdateStatus>;
    subscribe(listener: (status: DesktopUpdateStatus) => void): () => void;
  };
  sources?: {
    selectRepository(): Promise<DesktopLocalSourceSelection | null>;
  };
}

declare global {
  interface Window {
    localContextForge?: LocalContextForgeBridge;
  }
}

export function isDesktopRuntime(): boolean {
  return window.location.protocol === "lcf:" || "localContextForge" in window;
}

export function desktopApiBridge(): LocalContextForgeBridge["api"] | undefined {
  if (!isDesktopRuntime()) return undefined;

  const bridge = window.localContextForge;
  if (
    !bridge ||
    bridge.version !== DESKTOP_BRIDGE_VERSION ||
    typeof bridge.api?.request !== "function"
  ) {
    throw new Error("桌面 API bridge 不可用");
  }
  return bridge.api;
}

export function desktopMcpBridge():
  | NonNullable<LocalContextForgeBridge["mcp"]>
  | undefined {
  if (!isDesktopRuntime()) return undefined;

  const bridge = window.localContextForge;
  if (
    !bridge ||
    bridge.version !== DESKTOP_BRIDGE_VERSION ||
    typeof bridge.mcp?.status !== "function" ||
    typeof bridge.mcp.configure !== "function" ||
    typeof bridge.mcp.clear !== "function"
  ) {
    throw new Error("桌面 MCP bridge 不可用");
  }
  return bridge.mcp;
}

export function desktopUpdateBridge():
  | NonNullable<LocalContextForgeBridge["update"]>
  | undefined {
  if (!isDesktopRuntime()) return undefined;

  const bridge = window.localContextForge;
  if (
    !bridge ||
    bridge.version !== DESKTOP_BRIDGE_VERSION ||
    typeof bridge.update?.status !== "function" ||
    typeof bridge.update.check !== "function" ||
    typeof bridge.update.downloadOrOpen !== "function" ||
    typeof bridge.update.cancel !== "function" ||
    typeof bridge.update.openReleasePage !== "function" ||
    typeof bridge.update.subscribe !== "function"
  ) {
    throw new Error("桌面更新 bridge 不可用");
  }
  return bridge.update;
}

export function desktopSourcesBridge():
  | NonNullable<LocalContextForgeBridge["sources"]>
  | undefined {
  if (!isDesktopRuntime()) return undefined;

  const bridge = window.localContextForge;
  if (
    !bridge ||
    bridge.version !== DESKTOP_BRIDGE_VERSION ||
    typeof bridge.sources?.selectRepository !== "function"
  ) {
    throw new Error("桌面本地仓库 bridge 不可用");
  }
  return bridge.sources;
}

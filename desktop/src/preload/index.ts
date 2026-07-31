import { contextBridge, ipcRenderer } from "electron";
import {
  DESKTOP_BRIDGE_VERSION,
  IPC_CHANNELS,
  MAX_RESPONSE_BODY_BYTES,
  DesktopApiError,
  DesktopLocalSourceError,
  DesktopMcpSetupError,
  DesktopUpdateError,
  isJsonValue,
  isLocalSourceSelection,
  isMcpSetupStatus,
  isRuntimeStatus,
  isUpdateStatus,
  serializedByteLength,
  type ApiErrorCode,
  type ApiRequest,
  type ApiResponse,
  type DesktopBridge,
  type LocalSourceErrorCode,
  type LocalSourceSelection,
  type McpSetupErrorCode,
  type McpSetupStatus,
  type RuntimeStatus,
  type UpdateErrorCode,
  type UpdateStatus
} from "../contracts";
import { parseApiRequest } from "../main/ipc";

async function runtimeStatus(channel: string): Promise<RuntimeStatus> {
  const value: unknown = await ipcRenderer.invoke(channel);
  if (!isRuntimeStatus(value)) {
    throw new Error("Invalid desktop runtime response");
  }
  return value;
}

const API_ERROR_CODES = new Set<ApiErrorCode>([
  "unavailable",
  "request-too-large",
  "response-too-large",
  "timeout",
  "result-uncertain",
  "busy",
  "invalid-response",
  "transport"
]);

const MCP_SETUP_ERROR_CODES = new Set<McpSetupErrorCode>([
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

const UPDATE_ERROR_CODES = new Set<UpdateErrorCode>([
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
]);

const LOCAL_SOURCE_ERROR_CODES = new Set<LocalSourceErrorCode>([
  "busy",
  "unsafe-selection",
  "invalid-response",
  "unavailable"
]);

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function validatedApiResult(value: unknown): ApiResponse {
  if (!isPlainRecord(value) || typeof value.ok !== "boolean") {
    throw new DesktopApiError("invalid-response");
  }
  if (value.ok === false) {
    if (
      Object.keys(value).length !== 2 ||
      !isPlainRecord(value.error) ||
      Object.keys(value.error).length !== 1 ||
      typeof value.error.code !== "string" ||
      !API_ERROR_CODES.has(value.error.code as ApiErrorCode)
    ) {
      throw new DesktopApiError("invalid-response");
    }
    throw new DesktopApiError(value.error.code as ApiErrorCode);
  }
  if (
    Object.keys(value).length !== 2 ||
    !isPlainRecord(value.value) ||
    Object.keys(value.value).length !== 2 ||
    Object.keys(value.value).some(
      (key) => key !== "status" && key !== "body"
    ) ||
    typeof value.value.status !== "number" ||
    !Number.isInteger(value.value.status) ||
    value.value.status < 100 ||
    value.value.status > 599 ||
    !isJsonValue(value.value.body)
  ) {
    throw new DesktopApiError("invalid-response");
  }
  try {
    if (serializedByteLength(value.value.body) > MAX_RESPONSE_BODY_BYTES) {
      throw new DesktopApiError("response-too-large");
    }
  } catch (error) {
    if (error instanceof DesktopApiError) {
      throw error;
    }
    throw new DesktopApiError("invalid-response");
  }
  return value.value as unknown as ApiResponse;
}

async function mcpSetupStatus(channel: string): Promise<McpSetupStatus> {
  const value: unknown = await ipcRenderer.invoke(channel);
  if (
    !isPlainRecord(value) ||
    typeof value.ok !== "boolean" ||
    Object.keys(value).length !== 2
  ) {
    throw new DesktopMcpSetupError("invalid-response");
  }
  if (value.ok === false) {
    if (
      !isPlainRecord(value.error) ||
      Object.keys(value.error).length !== 1 ||
      typeof value.error.code !== "string" ||
      !MCP_SETUP_ERROR_CODES.has(value.error.code as McpSetupErrorCode)
    ) {
      throw new DesktopMcpSetupError("invalid-response");
    }
    throw new DesktopMcpSetupError(value.error.code as McpSetupErrorCode);
  }
  if (!isMcpSetupStatus(value.value)) {
    throw new DesktopMcpSetupError("invalid-response");
  }
  return value.value;
}

async function updateAction(channel: string): Promise<UpdateStatus> {
  const value: unknown = await ipcRenderer.invoke(channel);
  if (
    !isPlainRecord(value) ||
    typeof value.ok !== "boolean" ||
    Object.keys(value).length !== 2
  ) {
    throw new DesktopUpdateError("invalid-response");
  }
  if (value.ok === false) {
    if (
      !isPlainRecord(value.error) ||
      Object.keys(value.error).length !== 1 ||
      typeof value.error.code !== "string" ||
      !UPDATE_ERROR_CODES.has(value.error.code as UpdateErrorCode)
    ) {
      throw new DesktopUpdateError("invalid-response");
    }
    throw new DesktopUpdateError(value.error.code as UpdateErrorCode);
  }
  if (!isUpdateStatus(value.value)) {
    throw new DesktopUpdateError("invalid-response");
  }
  return value.value;
}

async function selectLocalSource(): Promise<LocalSourceSelection | null> {
  const value: unknown = await ipcRenderer.invoke(
    IPC_CHANNELS.localSourceSelect
  );
  if (
    !isPlainRecord(value) ||
    typeof value.ok !== "boolean" ||
    Object.keys(value).length !== 2
  ) {
    throw new DesktopLocalSourceError("invalid-response");
  }
  if (value.ok === false) {
    if (
      !isPlainRecord(value.error) ||
      Object.keys(value.error).length !== 1 ||
      typeof value.error.code !== "string" ||
      !LOCAL_SOURCE_ERROR_CODES.has(
        value.error.code as LocalSourceErrorCode
      )
    ) {
      throw new DesktopLocalSourceError("invalid-response");
    }
    throw new DesktopLocalSourceError(
      value.error.code as LocalSourceErrorCode
    );
  }
  if (value.value !== null && !isLocalSourceSelection(value.value)) {
    throw new DesktopLocalSourceError("invalid-response");
  }
  return value.value;
}

const bridge: DesktopBridge = Object.freeze({
  version: DESKTOP_BRIDGE_VERSION,
  api: Object.freeze({
    async request(input: ApiRequest): Promise<ApiResponse> {
      const validated = parseApiRequest(input);
      const result: unknown = await ipcRenderer.invoke(
        IPC_CHANNELS.apiRequest,
        validated
      );
      return validatedApiResult(result);
    }
  }),
  runtime: Object.freeze({
    get(): Promise<RuntimeStatus> {
      return runtimeStatus(IPC_CHANNELS.runtimeGet);
    },
    retry(): Promise<RuntimeStatus> {
      return runtimeStatus(IPC_CHANNELS.runtimeRetry);
    },
    subscribe(listener: (status: RuntimeStatus) => void): () => void {
      if (typeof listener !== "function") {
        throw new TypeError("Runtime listener must be a function");
      }
      const wrapped = (_event: Electron.IpcRendererEvent, value: unknown) => {
        if (isRuntimeStatus(value)) {
          listener(value);
        }
      };
      ipcRenderer.on(IPC_CHANNELS.runtimeChanged, wrapped);
      return () => ipcRenderer.removeListener(IPC_CHANNELS.runtimeChanged, wrapped);
    }
  }),
  mcp: Object.freeze({
    status(): Promise<McpSetupStatus> {
      return mcpSetupStatus(IPC_CHANNELS.mcpSetupGet);
    },
    configure(): Promise<McpSetupStatus> {
      return mcpSetupStatus(IPC_CHANNELS.mcpSetupConfigure);
    },
    clear(): Promise<McpSetupStatus> {
      return mcpSetupStatus(IPC_CHANNELS.mcpSetupClear);
    }
  }),
  update: Object.freeze({
    status(): Promise<UpdateStatus> {
      return updateAction(IPC_CHANNELS.updateStatus);
    },
    check(): Promise<UpdateStatus> {
      return updateAction(IPC_CHANNELS.updateCheck);
    },
    downloadOrOpen(): Promise<UpdateStatus> {
      return updateAction(IPC_CHANNELS.updateDownloadOrOpen);
    },
    cancel(): Promise<UpdateStatus> {
      return updateAction(IPC_CHANNELS.updateCancel);
    },
    openReleasePage(): Promise<UpdateStatus> {
      return updateAction(IPC_CHANNELS.updateOpenReleasePage);
    },
    subscribe(listener: (status: UpdateStatus) => void): () => void {
      if (typeof listener !== "function") {
        throw new TypeError("Update listener must be a function");
      }
      const wrapped = (_event: Electron.IpcRendererEvent, value: unknown) => {
        if (isUpdateStatus(value)) {
          listener(value);
        }
      };
      ipcRenderer.on(IPC_CHANNELS.updateChanged, wrapped);
      return () =>
        ipcRenderer.removeListener(IPC_CHANNELS.updateChanged, wrapped);
    }
  }),
  sources: Object.freeze({
    selectRepository(): Promise<LocalSourceSelection | null> {
      return selectLocalSource();
    }
  }),
  app: Object.freeze({
    async version(): Promise<string> {
      const value: unknown = await ipcRenderer.invoke(IPC_CHANNELS.appVersion);
      if (
        typeof value !== "string" ||
        value.length === 0 ||
        value.length > 128
      ) {
        throw new Error("Invalid desktop app version");
      }
      return value;
    }
  })
});

contextBridge.exposeInMainWorld("localContextForge", bridge);

import { contextBridge, ipcRenderer } from "electron";
import {
  DESKTOP_BRIDGE_VERSION,
  IPC_CHANNELS,
  MAX_RESPONSE_BODY_BYTES,
  DesktopApiError,
  isJsonValue,
  isRuntimeStatus,
  serializedByteLength,
  type ApiErrorCode,
  type ApiRequest,
  type ApiResponse,
  type DesktopBridge,
  type RuntimeStatus
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

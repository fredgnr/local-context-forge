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

export interface LocalContextForgeBridge {
  readonly version: typeof DESKTOP_BRIDGE_VERSION;
  api: {
    request(input: DesktopApiRequest): Promise<DesktopApiResponse>;
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

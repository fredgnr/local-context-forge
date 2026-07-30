import { beforeAll, describe, expect, it, vi } from "vitest";
import {
  IPC_CHANNELS,
  MAX_RESPONSE_BODY_BYTES,
  type DesktopBridge
} from "../src/contracts";

const electronMocks = vi.hoisted(() => {
  const invoke = vi.fn();
  const on = vi.fn();
  const removeListener = vi.fn();
  const exposeInMainWorld = vi.fn();
  return { invoke, on, removeListener, exposeInMainWorld };
});

vi.mock("electron", () => ({
  contextBridge: {
    exposeInMainWorld: electronMocks.exposeInMainWorld
  },
  ipcRenderer: {
    invoke: electronMocks.invoke,
    on: electronMocks.on,
    removeListener: electronMocks.removeListener
  }
}));

let bridge: DesktopBridge;
let exposedName: string;

beforeAll(async () => {
  await import("../src/preload/index");
  const call = electronMocks.exposeInMainWorld.mock.calls[0];
  exposedName = call?.[0] as string;
  bridge = call?.[1] as DesktopBridge;
});

describe("versioned preload facade", () => {
  it("exposes only the exact versioned facade under window.localContextForge", () => {
    expect(exposedName).toBe("localContextForge");
    expect(bridge.version).toBe("1.0");
    expect(Object.keys(bridge).sort()).toEqual([
      "api",
      "app",
      "runtime",
      "version"
    ]);
    expect(Object.keys(bridge.api)).toEqual(["request"]);
    expect(Object.keys(bridge.runtime).sort()).toEqual([
      "get",
      "retry",
      "subscribe"
    ]);
    expect(Object.keys(bridge.app)).toEqual(["version"]);
    expect(bridge).not.toHaveProperty("ipcRenderer");
    expect(bridge).not.toHaveProperty("filesystem");
    expect(bridge).not.toHaveProperty("shell");
  });

  it("validates the exact API response envelope before returning it", async () => {
    electronMocks.invoke.mockResolvedValueOnce({
      ok: true,
      value: { status: 200, body: { status: "ok" } }
    });
    await expect(
      bridge.api.request({ method: "GET", path: "/api/health" })
    ).resolves.toEqual({ status: 200, body: { status: "ok" } });
    expect(electronMocks.invoke).toHaveBeenLastCalledWith(
      IPC_CHANNELS.apiRequest,
      {
        method: "GET",
        path: "/api/health",
        timeoutMs: 30_000
      }
    );

    electronMocks.invoke.mockResolvedValueOnce({
      ok: true,
      value: {
        status: 200,
        body: null,
        headers: { authorization: "secret" }
      }
    });
    await expect(
      bridge.api.request({ method: "GET", path: "/api/health" })
    ).rejects.toMatchObject({ code: "invalid-response" });
  });

  it("turns a structured Main failure into a stable renderer error", async () => {
    electronMocks.invoke.mockResolvedValueOnce({
      ok: false,
      error: { code: "result-uncertain" }
    });
    await expect(
      bridge.api.request({
        method: "POST",
        path: "/api/query",
        body: { query: "needle" }
      })
    ).rejects.toMatchObject({
      name: "DesktopApiError",
      code: "result-uncertain"
    });
  });

  it("rejects oversized or malformed Main responses", async () => {
    electronMocks.invoke.mockResolvedValueOnce({
      ok: true,
      value: {
        status: 200,
        body: "x".repeat(MAX_RESPONSE_BODY_BYTES + 1)
      }
    });
    await expect(
      bridge.api.request({ method: "GET", path: "/api/health" })
    ).rejects.toMatchObject({ code: "response-too-large" });

    electronMocks.invoke.mockResolvedValueOnce({
      ok: true,
      value: { status: 99, body: null }
    });
    await expect(
      bridge.api.request({ method: "GET", path: "/api/health" })
    ).rejects.toMatchObject({ code: "invalid-response" });
  });
});

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
      "mcp",
      "runtime",
      "sources",
      "update",
      "version"
    ]);
    expect(Object.keys(bridge.api)).toEqual(["request"]);
    expect(Object.keys(bridge.runtime).sort()).toEqual([
      "get",
      "retry",
      "subscribe"
    ]);
    expect(Object.keys(bridge.mcp).sort()).toEqual([
      "clear",
      "configure",
      "status"
    ]);
    expect(Object.keys(bridge.update).sort()).toEqual([
      "cancel",
      "check",
      "downloadOrOpen",
      "openReleasePage",
      "status",
      "subscribe"
    ]);
    expect(Object.keys(bridge.sources)).toEqual(["selectRepository"]);
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

  it("exposes fixed MCP setup operations and validates their exact result", async () => {
    const status = {
      provider: "codex_cli" as const,
      codexState: "ready" as const,
      configurationState: "configured" as const,
      installState: "ready" as const,
      canConfigure: false,
      canClear: true,
      restartRequired: true
    };
    electronMocks.invoke.mockResolvedValueOnce({ ok: true, value: status });
    await expect(bridge.mcp.status()).resolves.toEqual(status);
    expect(electronMocks.invoke).toHaveBeenLastCalledWith(
      IPC_CHANNELS.mcpSetupGet
    );

    electronMocks.invoke.mockResolvedValueOnce({
      ok: false,
      error: {
        code: "name-conflict",
        executablePath: "/private/codex"
      }
    });
    await expect(bridge.mcp.configure()).rejects.toMatchObject({
      name: "DesktopMcpSetupError",
      code: "invalid-response"
    });

    electronMocks.invoke.mockResolvedValueOnce({
      ok: false,
      error: { code: "move-to-applications" }
    });
    await expect(bridge.mcp.configure()).rejects.toMatchObject({
      name: "DesktopMcpSetupError",
      code: "move-to-applications"
    });
    expect(electronMocks.invoke).toHaveBeenLastCalledWith(
      IPC_CHANNELS.mcpSetupConfigure
    );

    electronMocks.invoke.mockResolvedValueOnce({
      ok: true,
      value: { ...status, executablePath: "/private/node" }
    });
    await expect(bridge.mcp.clear()).rejects.toMatchObject({
      code: "invalid-response"
    });
  });

  it("validates bounded update status and errors without exposing updater internals", async () => {
    const status = {
      state: "available" as const,
      currentVersion: "1.0.0",
      channel: "latest",
      availableVersion: "1.1.0",
      progress: null,
      errorCode: null,
      unavailableReason: null,
      canCheck: true,
      canDownloadOrOpen: true,
      canOpenReleasePage: false,
      automaticApply: false as const,
      automaticApplyReason: "val-update-001-not-passed" as const
    };
    electronMocks.invoke.mockResolvedValueOnce({ ok: true, value: status });
    await expect(bridge.update.status()).resolves.toEqual(status);
    expect(electronMocks.invoke).toHaveBeenLastCalledWith(
      IPC_CHANNELS.updateStatus
    );

    electronMocks.invoke.mockResolvedValueOnce({
      ok: false,
      error: { code: "digest-mismatch" }
    });
    await expect(bridge.update.downloadOrOpen()).rejects.toMatchObject({
      name: "DesktopUpdateError",
      code: "digest-mismatch"
    });
    expect(electronMocks.invoke).toHaveBeenLastCalledWith(
      IPC_CHANNELS.updateDownloadOrOpen
    );

    electronMocks.invoke.mockResolvedValueOnce({
      ok: true,
      value: {
        ...status,
        localPath: "/private/update.dmg"
      }
    });
    await expect(bridge.update.check()).rejects.toMatchObject({
      code: "invalid-response"
    });
  });

  it("returns only an opaque local-source grant and validates the exact envelope", async () => {
    const selection = {
      grantId: `lcf-local:${"c".repeat(64)}`,
      displayName: "private-repository"
    };
    electronMocks.invoke.mockResolvedValueOnce({
      ok: true,
      value: selection
    });
    await expect(bridge.sources.selectRepository()).resolves.toEqual(
      selection
    );
    expect(electronMocks.invoke).toHaveBeenLastCalledWith(
      IPC_CHANNELS.localSourceSelect
    );

    electronMocks.invoke.mockResolvedValueOnce({ ok: true, value: null });
    await expect(bridge.sources.selectRepository()).resolves.toBeNull();

    electronMocks.invoke.mockResolvedValueOnce({
      ok: false,
      error: { code: "unsafe-selection" }
    });
    await expect(bridge.sources.selectRepository()).rejects.toMatchObject({
      name: "DesktopLocalSourceError",
      code: "unsafe-selection"
    });

    electronMocks.invoke.mockResolvedValueOnce({
      ok: true,
      value: {
        ...selection,
        absolutePath: "/Users/test/private-repository"
      }
    });
    await expect(bridge.sources.selectRepository()).rejects.toMatchObject({
      code: "invalid-response"
    });

    electronMocks.invoke.mockResolvedValueOnce({
      ok: true,
      value: {
        ...selection,
        displayName: "/Users/test/private-repository"
      }
    });
    await expect(bridge.sources.selectRepository()).rejects.toMatchObject({
      code: "invalid-response"
    });
  });

  it("filters update progress events and supports explicit cancellation", async () => {
    const listener = vi.fn();
    const unsubscribe = bridge.update.subscribe(listener);
    const registration = electronMocks.on.mock.calls.find(
      ([channel]) => channel === IPC_CHANNELS.updateChanged
    );
    const wrapped = registration?.[1] as
      | ((_event: unknown, value: unknown) => void)
      | undefined;
    wrapped?.(undefined, {
      state: "downloading",
      currentVersion: "1.0.0",
      channel: "latest",
      availableVersion: "1.1.0",
      progress: { receivedBytes: 4, totalBytes: 10 },
      errorCode: null,
      unavailableReason: null,
      canCheck: false,
      canDownloadOrOpen: false,
      canOpenReleasePage: false,
      automaticApply: false,
      automaticApplyReason: "val-update-001-not-passed"
    });
    wrapped?.(undefined, {
      url: "https://evil.example",
      progress: { receivedBytes: 999, totalBytes: 1 }
    });
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    expect(electronMocks.removeListener).toHaveBeenCalledWith(
      IPC_CHANNELS.updateChanged,
      wrapped
    );

    electronMocks.invoke.mockResolvedValueOnce({
      ok: false,
      error: { code: "cancelled" }
    });
    await expect(bridge.update.cancel()).rejects.toMatchObject({
      code: "cancelled"
    });
    expect(electronMocks.invoke).toHaveBeenLastCalledWith(
      IPC_CHANNELS.updateCancel
    );
  });
});

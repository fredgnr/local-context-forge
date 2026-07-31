import type { IpcMain, IpcMainInvokeEvent } from "electron";
import { describe, expect, it, vi } from "vitest";
import {
  IPC_CHANNELS,
  MAX_API_TIMEOUT_MS,
  MAX_REQUEST_BODY_BYTES,
  MIN_API_TIMEOUT_MS,
  type ApiMethod
} from "../src/contracts";
import {
  isAllowedApiRoute,
  isAllowedLibrarySource,
  isTrustedIpcSender,
  parseApiRequest,
  registerIpcHandlers
} from "../src/main/ipc";

describe("renderer IPC validation", () => {
  it("allows exactly the route templates used by web/src/api.ts", () => {
    const routes: Array<[ApiMethod, string]> = [
      ["GET", "/api/health"],
      ["GET", "/api/system/status"],
      ["GET", "/api/settings"],
      ["PATCH", "/api/settings"],
      ["GET", "/api/embedding/models"],
      ["POST", "/api/embedding/models/validate"],
      ["POST", "/api/rebuilds"],
      ["GET", "/api/libraries"],
      ["POST", "/api/libraries"],
      ["POST", "/api/libraries/library%20one/ingest"],
      ["GET", "/api/jobs"],
      ["GET", "/api/jobs/job-1"],
      ["POST", "/api/jobs/job-1/cancel"],
      ["POST", "/api/jobs/job-1/retry"],
      ["GET", "/api/libraries/library-1/pages"],
      [
        "GET",
        "/api/libraries/library-1/page?path=guide%2Fintro.md"
      ],
      [
        "GET",
        "/api/libraries/library%20with%20spaces/proposals?status=pending"
      ],
      ["POST", "/api/proposals/proposal-1/publish"],
      ["POST", "/api/proposals/proposal-1/reject"],
      ["POST", "/api/query"],
      ["GET", "/api/libraries/library-1/graph"],
      ["POST", "/api/libraries/library-1/lint"]
    ];
    for (const [method, requestPath] of routes) {
      expect(isAllowedApiRoute(method, requestPath), requestPath).toBe(true);
    }
  });

  it("rejects admin, unknown methods, route smuggling and extra query keys", () => {
    expect(isAllowedApiRoute("POST", "/api/admin/reindex")).toBe(false);
    expect(
      isAllowedApiRoute("DELETE" as ApiMethod, "/api/libraries/library-1")
    ).toBe(false);
    expect(
      isAllowedApiRoute("GET", "/api/libraries/../admin/reindex")
    ).toBe(false);
    expect(
      isAllowedApiRoute(
        "GET",
        "/api/libraries/library%2Fsmuggled/proposals?status=pending"
      )
    ).toBe(false);
    expect(
      isAllowedApiRoute(
        "GET",
        "/api/libraries/id/page?path=a.md&debug=true"
      )
    ).toBe(false);
    expect(
      isAllowedApiRoute(
        "GET",
        "/api/libraries/id/proposals?status=approved"
      )
    ).toBe(false);
    for (const unsafePagePath of [
      "%2Fabsolute.md",
      "..%2Fsecret.md",
      "guide%2F..%2Fsecret.md",
      "guide%5Csecret.md",
      "guide%2F",
      "guide%2Fpage.txt",
      "guide%252Fsecret.md"
    ]) {
      expect(
        isAllowedApiRoute(
          "GET",
          `/api/libraries/id/page?path=${unsafePagePath}`
        ),
        unsafePagePath
      ).toBe(false);
    }
  });

  it("clamps timeout and enforces route-specific body schemas", () => {
    expect(
      parseApiRequest({
        method: "GET",
        path: "/api/health",
        timeoutMs: 1
      }).timeoutMs
    ).toBe(MIN_API_TIMEOUT_MS);
    expect(
      parseApiRequest({
        method: "GET",
        path: "/api/health",
        timeoutMs: 999_999
      }).timeoutMs
    ).toBe(MAX_API_TIMEOUT_MS);

    expect(
      parseApiRequest({
        method: "POST",
        path: "/api/query",
        body: { library_id: "library", query: "needle", limit: 30 }
      })
    ).toMatchObject({ timeoutMs: 30_000 });
    expect(() =>
      parseApiRequest({
        method: "POST",
        path: "/api/query",
        body: { library_id: "library", query: "needle", limit: 31 }
      })
    ).toThrow(/invalid-payload/);
    expect(() =>
      parseApiRequest({
        method: "PATCH",
        path: "/api/settings",
        body: {
          expected_revision: 0,
          provider_policy: "codex_only",
          concurrency: 2
        }
      })
    ).toThrow(/invalid-payload/);
    expect(
      parseApiRequest({
        method: "PATCH",
        path: "/api/settings",
        body: {
          expected_revision: 1,
          provider_policy: "codex_then_cursor",
          cursor_fallback_consent: true,
          concurrency: 1,
          embedding_model: "embeddinggemma-300m-q8"
        }
      })
    ).toMatchObject({ timeoutMs: 30_000 });
    expect(() =>
      parseApiRequest({
        method: "PATCH",
        path: "/api/settings",
        body: {
          expected_revision: 1,
          provider_policy: "cursor_only",
          cursor_fallback_consent: true
        }
      })
    ).toThrow(/invalid-payload/);
    expect(() =>
      parseApiRequest({
        method: "PATCH",
        path: "/api/settings",
        body: {
          expected_revision: 1,
          provider_order: ["codex_cli", "cursor_cli"],
          fallback_enabled: true
        }
      })
    ).toThrow(/invalid-payload/);
    expect(() =>
      parseApiRequest({
        method: "PATCH",
        path: "/api/settings",
        body: {
          expected_revision: 1,
          provider_policy: "codex_then_cursor",
          cursor_fallback_consent: "yes"
        }
      })
    ).toThrow(/invalid-payload/);
    expect(
      parseApiRequest({
        method: "POST",
        path: "/api/libraries/library-1/ingest",
        body: {
          ref: "main",
          provider: "codex",
          version: "1.0.0"
        }
      })
    ).toMatchObject({ timeoutMs: 30_000 });
    for (const provider of ["cursor", "cursor_cli", "mock", "ollama"]) {
      expect(() =>
        parseApiRequest({
          method: "POST",
          path: "/api/libraries/library-1/ingest",
          body: {
            ref: "main",
            provider,
            version: "1.0.0"
          }
        })
      ).toThrow(/invalid-payload/);
    }
    expect(
      parseApiRequest({
        method: "POST",
        path: "/api/embedding/models/validate",
        body: {
          model: "hf:example/code-embedding/model-q8.gguf"
        }
      })
    ).toMatchObject({ timeoutMs: 30_000 });
    for (const model of [
      "https://example.com/model.gguf",
      "hf:example/repository/../model.gguf",
      "hf:example/repository/model.bin"
    ]) {
      expect(() =>
        parseApiRequest({
          method: "POST",
          path: "/api/rebuilds",
          body: { model }
        })
      ).toThrow(/invalid-payload/);
    }
    expect(() =>
      parseApiRequest({
        method: "POST",
        path: "/api/libraries",
        body: {
          name: "library",
          source: "https://github.com/example/library.git",
          command: "open"
        }
      })
    ).toThrow(/invalid-payload/);
  });

  it("allows only a narrow GitHub HTTPS source and rejects local/SSRF forms", () => {
    expect(
      isAllowedLibrarySource("https://github.com/example/library.git")
    ).toBe(true);
    expect(
      isAllowedLibrarySource("https://github.com:443/example/library")
    ).toBe(true);
    for (const source of [
      "/private/repository",
      "file:///private/repository",
      "ssh://github.com/example/library",
      "https://user@github.com/example/library",
      "https://github.com:8443/example/library",
      "https://github.com/example/library?ref=main",
      "https://github.com/example/library#readme",
      "https://example.com/example/library",
      "https://github.com/example/library/extra"
    ]) {
      expect(isAllowedLibrarySource(source), source).toBe(false);
    }
  });

  it("rejects headers, GET bodies, cyclic and oversized payloads", () => {
    expect(() =>
      parseApiRequest({
        method: "GET",
        path: "/api/health",
        headers: { Authorization: "Bearer renderer-value" }
      })
    ).toThrow(/invalid-payload/);
    expect(() =>
      parseApiRequest({
        method: "GET",
        path: "/api/health",
        body: null
      })
    ).toThrow(/invalid-payload/);

    const cyclic: Record<string, unknown> = {
      method: "POST",
      path: "/api/query"
    };
    cyclic.body = cyclic;
    expect(() => parseApiRequest(cyclic)).toThrow(/invalid-payload/);

    expect(() =>
      parseApiRequest({
        method: "POST",
        path: "/api/query",
        body: {
          query: "x".repeat(MAX_REQUEST_BODY_BYTES),
          library_id: "library"
        }
      })
    ).toThrow(/invalid-payload/);
  });

  it("accepts only the main frame at the exact lcf://app origin", () => {
    const mainFrame = { url: "lcf://app/index.html" };
    expect(
      isTrustedIpcSender({
        senderFrame: mainFrame,
        sender: { mainFrame }
      })
    ).toBe(true);
    expect(
      isTrustedIpcSender({
        senderFrame: { url: "lcf://app/frame.html" },
        sender: { mainFrame }
      })
    ).toBe(false);
    for (const url of [
      "https://app/index.html",
      "lcf://evil/index.html",
      "lcf://app.evil/index.html",
      "not a url"
    ]) {
      const frame = { url };
      expect(
        isTrustedIpcSender({
          senderFrame: frame,
          sender: { mainFrame: frame }
        })
      ).toBe(false);
    }
  });

  it("returns a stable IPC error code without propagating transport details", async () => {
    const handlers = new Map<
      string,
      (event: IpcMainInvokeEvent, value?: unknown) => unknown
    >();
    const ipcMain = {
      handle: vi.fn(
        (
          channel: string,
          handler: (event: IpcMainInvokeEvent, value?: unknown) => unknown
        ) => handlers.set(channel, handler)
      )
    } as unknown as IpcMain;
    registerIpcHandlers(ipcMain, {
      apiRequest: async () => {
        throw { code: "result-uncertain", socketPath: "/private/socket" };
      },
      runtimeGet: () => ({ state: "ready", canRetry: false }),
      runtimeRetry: async () => ({ state: "ready", canRetry: false }),
      appVersion: () => "0.3.0-alpha.1"
    });

    const frame = { url: "lcf://app/" };
    const event = {
      senderFrame: frame,
      sender: { mainFrame: frame }
    } as unknown as IpcMainInvokeEvent;
    await expect(
      handlers.get(IPC_CHANNELS.apiRequest)?.(event, {
        method: "GET",
        path: "/api/health"
      })
    ).resolves.toEqual({
      ok: false,
      error: { code: "result-uncertain" }
    });
  });
});

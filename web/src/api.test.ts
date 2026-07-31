import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, formatApiError, normalizeJob } from "./api";
import type { LocalContextForgeBridge } from "./desktopBridge";

afterEach(() => {
  delete window.localContextForge;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function installDesktopBridge(
  request: LocalContextForgeBridge["api"]["request"]
) {
  window.localContextForge = { version: "1.0", api: { request } };
}

describe("API transports", () => {
  it("keeps browser and Docker deployments on fetch", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{"status":"ok"}', {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.health()).resolves.toBe(true);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/health");
  });

  it("uses the typed desktop bridge with parsed JSON and route timeout", async () => {
    const bridgeRequest = vi.fn().mockResolvedValue({
      status: 202,
      body: { id: "desktop-job", status: "queued" }
    });
    const fetchMock = vi.fn();
    installDesktopBridge(bridgeRequest);
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      api.ingest("library-a", {
        ref: "main",
        generator: "mock",
        version: "1.0.0"
      })
    ).resolves.toMatchObject({ id: "desktop-job", status: "queued" });

    expect(bridgeRequest).toHaveBeenCalledWith({
      method: "POST",
      path: "/api/libraries/library-a/ingest",
      body: {
        ref: "main",
        provider: "mock",
        version: "1.0.0"
      },
      timeoutMs: 60_000
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("never falls back to fetch when the desktop bridge rejects", async () => {
    const bridgeError = new Error("sidecar unavailable");
    const fetchMock = vi.fn();
    installDesktopBridge(vi.fn().mockRejectedValue(bridgeError));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.health()).rejects.toBe(bridgeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("preserves desktop response status and never retries through fetch", async () => {
    const fetchMock = vi.fn();
    installDesktopBridge(
      vi.fn().mockResolvedValue({
        status: 409,
        body: { detail: "Settings revision changed" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const error = await api.settings().catch((reason: unknown) => reason);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 409,
      message: "Settings revision changed"
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails closed when the desktop bridge shape is invalid", async () => {
    const fetchMock = vi.fn();
    Object.defineProperty(window, "localContextForge", {
      configurable: true,
      value: {}
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.health()).rejects.toThrow("桌面 API bridge 不可用");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("caps long desktop operations at the frozen sidecar deadline", async () => {
    const bridgeRequest = vi.fn().mockResolvedValue({
      status: 200,
      body: { query: "needle", engine: "qmd", results: [] }
    });
    installDesktopBridge(bridgeRequest);

    await api.query({ libraryId: "library-a", query: "needle" });

    expect(bridgeRequest).toHaveBeenCalledWith(
      expect.objectContaining({ timeoutMs: 120_000 })
    );
  });
});

describe("API contract normalization", () => {
  it("formats FastAPI validation arrays into useful field messages", () => {
    expect(
      formatApiError(
        {
          detail: [
            { loc: ["body", "source"], msg: "Field required", type: "missing" },
            {
              loc: ["body", "limit"],
              msg: "Input should be less than or equal to 50",
              type: "less_than_equal"
            }
          ]
        },
        422
      )
    ).toBe(
      "source：Field required；limit：Input should be less than or equal to 50"
    );
  });

  it("preserves HTTP status on API errors for conflict recovery", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response('{"detail":"Settings revision changed"}', {
          status: 409,
          headers: { "Content-Type": "application/json" }
        })
      )
    );

    const error = await api.settings().catch((reason: unknown) => reason);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 409,
      message: "Settings revision changed"
    });
  });

  it("keeps the detailed job error separate and treats backend progress=1 as 1%", () => {
    expect(
      normalizeJob({
        id: "job-1",
        status: "failed",
        stage: "failed",
        progress: 1,
        message: "Ingest failed",
        error: "ValidationError: invalid source reference"
      })
    ).toMatchObject({
      id: "job-1",
      status: "failed",
      phase: "failed",
      progress: 1,
      message: "Ingest failed",
      error: "ValidationError: invalid source reference"
    });
  });

  it("requests only pending proposals for the review queue", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("[]", {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.proposals("library/with spaces");

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "/api/libraries/library%2Fwith%20spaces/proposals?status=pending"
    );
  });

  it("sends an explicit immutable version during re-ingest", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{"id":"job","status":"queued"}', {
        status: 202,
        headers: { "Content-Type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.ingest("library-a", {
      ref: "release/v2",
      generator: "ollama",
      version: "2.0.0"
    });

    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body).toEqual({
      ref: "release/v2",
      provider: "ollama",
      version: "2.0.0"
    });
  });

  it("normalizes system status and settings compatibility fields", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            healthy: true,
            app_version: "0.2.0",
            data_dir: "/data/forge",
            services: [{ key: "queue", name: "Queue", state: "online" }]
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            revision: 4,
            provider_order: ["codex_cli", "cursor_cli"],
            fallback_enabled: true,
            embedding_model:
              "hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf",
            concurrency: 1
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.systemStatus()).resolves.toMatchObject({
      ready: true,
      version: "0.2.0",
      dataDir: "/data/forge",
      checks: [{ id: "queue", label: "Queue", status: "ready" }]
    });
    await expect(api.settings()).resolves.toMatchObject({
      generator: "codex",
      fallbackGenerator: "cursor",
      embeddingModel: "embeddinggemma-300m-q8",
      revision: 4,
      advanced: { maxConcurrency: 1 }
    });
  });

  it("uses the job control and rebuild endpoints", async () => {
    const fetchMock = vi.fn().mockImplementation(async () =>
      new Response('{"job":{"id":"job-2","status":"queued"}}', {
        status: 202,
        headers: { "Content-Type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.cancelJob("job / 1");
    await api.retryJob("job / 1");
    await api.rebuild("library-a", "embeddinggemma-300m-q8");

    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "/api/jobs/job%20%2F%201/cancel"
    );
    expect(String(fetchMock.mock.calls[1][0])).toContain(
      "/api/jobs/job%20%2F%201/retry"
    );
    expect(fetchMock.mock.calls[0][1]?.body).toBeUndefined();
    expect(fetchMock.mock.calls[1][1]?.body).toBeUndefined();
    expect(String(fetchMock.mock.calls[2][0])).toContain("/api/rebuilds");
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({
      library_id: "library-a",
      model: "embeddinggemma-300m-q8"
    });
  });

  it("does not invent a hidden CLI fallback for a single-provider setting", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            revision: 2,
            provider_order: ["mock"],
            fallback_enabled: true,
            concurrency: 1,
            embedding_model: "embeddinggemma-300m-q8"
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      )
    );

    await expect(api.settings()).resolves.toMatchObject({
      generator: "mock",
      fallbackGenerator: "none"
    });
  });

  it("saves normalized settings and validates an embedding model", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            revision: 9,
            provider_order: ["codex_cli", "cursor_cli"],
            fallback_enabled: true,
            embedding_model:
              "hf:example/Qwen3-Embedding-Code/Qwen3-Embedding-Code-Q8_0.gguf",
            concurrency: 1
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      )
      .mockResolvedValueOnce(
        new Response('{"valid":true,"dimensions":768}', {
          status: 200,
          headers: { "Content-Type": "application/json" }
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    await api.updateSettings({
      generator: "codex",
      fallbackGenerator: "cursor",
      embeddingModel: "custom",
      customEmbeddingModel:
        "hf:example/Qwen3-Embedding-Code/Qwen3-Embedding-Code-Q8_0.gguf",
      revision: 8,
      advanced: { maxConcurrency: 1 }
    });
    await expect(
      api.validateEmbeddingModel({
        model:
          "hf:example/Qwen3-Embedding-Code/Qwen3-Embedding-Code-Q8_0.gguf"
      })
    ).resolves.toEqual({ valid: true, dimensions: 768 });

    const saveBody = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(saveBody).toMatchObject({
      expected_revision: 8,
      provider_order: ["codex_cli", "cursor_cli"],
      fallback_enabled: true,
      concurrency: 1,
      embedding_model:
        "hf:example/Qwen3-Embedding-Code/Qwen3-Embedding-Code-Q8_0.gguf"
    });
    expect(String(fetchMock.mock.calls[1][0])).toContain(
      "/api/embedding/models/validate"
    );
  });
});

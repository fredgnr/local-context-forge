import { EventEmitter } from "node:events";
import type {
  ClientRequest,
  IncomingMessage,
  RequestOptions
} from "node:http";
import { PassThrough } from "node:stream";
import { describe, expect, it, vi } from "vitest";
import type { SidecarConnection } from "../src/main/apiProxy";
import { SidecarMcpReadService } from "../src/main/mcpSidecarRead";

const connection: SidecarConnection = {
  launchId: "00000000-0000-4000-8000-000000000001",
  socketPath: "/private/lcf/py.sock",
  token: "A".repeat(43)
};

interface RecordedRequest {
  body: Buffer | undefined;
  options: RequestOptions;
}

interface FakeTransport {
  recorded: RecordedRequest[];
  request: (
    options: RequestOptions,
    callback: (response: IncomingMessage) => void
  ) => ClientRequest;
}

function respond(
  callback: (response: IncomingMessage) => void,
  status: number,
  value: unknown
): void {
  const stream = new PassThrough() as PassThrough & IncomingMessage;
  stream.statusCode = status;
  stream.headers = { "content-type": "application/json" };
  callback(stream);
  stream.end(
    Buffer.isBuffer(value)
      ? value
      : Buffer.from(JSON.stringify(value), "utf8")
  );
}

function fakeTransport(
  responder: (
    callback: (response: IncomingMessage) => void,
    request: RecordedRequest
  ) => void
): FakeTransport {
  const recorded: RecordedRequest[] = [];
  return {
    recorded,
    request(options, callback) {
      const emitter = new EventEmitter() as ClientRequest & EventEmitter;
      Object.assign(emitter, {
        destroy: vi.fn(() => emitter),
        end: vi.fn((body?: Buffer) => {
          const current = { body, options };
          recorded.push(current);
          queueMicrotask(() => responder(callback, current));
          return emitter;
        }),
        setTimeout: vi.fn(() => emitter)
      });
      return emitter;
    }
  };
}

function defaultResponse(
  callback: (response: IncomingMessage) => void,
  request: RecordedRequest,
  revision: number
): void {
  if (request.options.path === "/api/health") {
    respond(callback, 200, {
      embedding: { corpus_revision: revision },
      status: "ok"
    });
    return;
  }
  if (String(request.options.path).startsWith("/api/libraries?")) {
    respond(callback, 200, [
      {
        context7_id: "/local/widgets",
        default_version: "1.0.0",
        description: "Widget API",
        name: "Widgets",
        page_count: 4,
        source: "/private/repository",
        version_count: 1
      }
    ]);
    return;
  }
  if (request.options.path === "/api/query") {
    respond(callback, 200, {
      engine: "lexical",
      query: "build_widget",
      results: [
        {
          library_id: "library-secret-id",
          markdown: "## `build_widget`\n\nBuild a widget.",
          path: "api/widgets.md",
          score: 1,
          snippet: "Build a widget.",
          source_refs: [
            {
              line_end: 20,
              line_start: 18,
              path: "widgets.py"
            }
          ],
          source_sha: "1234567890abcdef",
          summary: "Public Widget API",
          title: "widgets.py",
          version: "1.0.0"
        }
      ]
    });
    return;
  }
  respond(callback, 404, { detail: "not found" });
}

describe("MCP sidecar read adapter", () => {
  it("formats resolve/query in Main and never returns raw sidecar paths or credentials", async () => {
    const transport = fakeTransport((callback, request) =>
      defaultResponse(callback, request, 7)
    );
    const service = new SidecarMcpReadService(
      () => connection,
      {
        now: () => 1_000,
        request: transport.request,
        requestId: () =>
          "00000000-0000-4000-8000-000000000002"
      }
    );

    const resolved = await service.resolveLibraryId({
      corpusRevision: 7,
      libraryName: "widgets & clients",
      query: "build widgets"
    });
    expect(resolved.corpusRevision).toBe(7);
    expect(resolved.text).toContain(
      "Context7-compatible library ID: `/local/widgets`"
    );
    expect(resolved.text).toContain("Published pages: 4");
    expect(resolved.text).not.toContain("/private/repository");
    expect(
      transport.recorded.find((request) =>
        String(request.options.path).startsWith("/api/libraries?")
      )?.options.path
    ).toBe("/api/libraries?search=widgets+%26+clients");

    const queried = await service.queryDocs({
      corpusRevision: 7,
      libraryId: "/local/widgets",
      query: "build_widget"
    });
    expect(queried.text).toContain("build_widget");
    expect(queried.text).toContain("widgets.py:18-20");
    expect(queried.text).toContain("1234567890ab");
    expect(queried.text).not.toContain("library-secret-id");
    const queryRequest = transport.recorded.find(
      (request) => request.options.path === "/api/query"
    );
    expect(JSON.parse(queryRequest!.body!.toString("utf8"))).toEqual({
      library_id: "/local/widgets",
      limit: 8,
      query: "build_widget"
    });
    expect(
      transport.recorded.every(
        (request) =>
          (request.options.headers as Record<string, string>)
            .Authorization === `Bearer ${connection.token}`
      )
    ).toBe(true);
    const serialized = JSON.stringify({ queried, resolved });
    expect(serialized).not.toContain(connection.token);
    expect(serialized).not.toContain(connection.socketPath);
  });

  it("fails closed when the corpus changes during a resolve operation", async () => {
    let revision = 7;
    const transport = fakeTransport((callback, request) => {
      if (request.options.path === "/api/health") {
        respond(callback, 200, {
          embedding: { corpus_revision: revision }
        });
      } else {
        revision += 1;
        respond(callback, 200, []);
      }
    });
    const service = new SidecarMcpReadService(
      () => connection,
      { request: transport.request }
    );
    await expect(
      service.resolveLibraryId({
        corpusRevision: 7,
        libraryName: "widgets",
        query: ""
      })
    ).rejects.toMatchObject({ code: "stale_revision" });
  });

  it("rejects malformed paths, oversized responses, cancellation, and unavailable sidecars", async () => {
    const malformed = fakeTransport((callback, request) => {
      if (request.options.path === "/api/health") {
        respond(callback, 200, {
          embedding: { corpus_revision: 7 }
        });
        return;
      }
      respond(callback, 200, {
        engine: "lexical",
        results: [
          {
            markdown: "private",
            path: "/Users/example/private.md",
            source_refs: [],
            source_sha: "1234567890abcdef",
            summary: "",
            title: "private",
            version: "1.0.0"
          }
        ]
      });
    });
    const malformedService = new SidecarMcpReadService(
      () => connection,
      { request: malformed.request }
    );
    await expect(
      malformedService.queryDocs({
        corpusRevision: 7,
        libraryId: "/local/widgets",
        query: "widgets"
      })
    ).rejects.toMatchObject({ code: "invalid_response" });

    const oversized = fakeTransport((callback, request) => {
      if (request.options.path === "/api/health") {
        respond(callback, 200, {
          embedding: { corpus_revision: 7 }
        });
        return;
      }
      respond(
        callback,
        200,
        Buffer.alloc(4 * 1024 * 1024 + 1, 0x78)
      );
    });
    const oversizedService = new SidecarMcpReadService(
      () => connection,
      { request: oversized.request }
    );
    await expect(
      oversizedService.queryDocs({
        corpusRevision: 7,
        libraryId: "/local/widgets",
        query: "widgets"
      })
    ).rejects.toMatchObject({ code: "invalid_response" });

    const controller = new AbortController();
    controller.abort();
    await expect(
      oversizedService.getRevision(controller.signal)
    ).rejects.toMatchObject({ code: "timeout" });
    const unavailable = new SidecarMcpReadService(() => undefined);
    await expect(unavailable.getRevision()).rejects.toMatchObject({
      code: "unavailable"
    });
  });
});

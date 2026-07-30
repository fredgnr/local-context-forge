import { EventEmitter } from "node:events";
import type {
  ClientRequest,
  IncomingMessage,
  RequestOptions
} from "node:http";
import { PassThrough } from "node:stream";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  MAX_RESPONSE_BODY_BYTES,
  type ApiRequest
} from "../src/contracts";
import {
  ApiProxy,
  ApiProxyError,
  isSafeRepositoryRelativePath,
  proxyApiRequest,
  type SidecarConnection
} from "../src/main/apiProxy";

const connection: SidecarConnection = {
  socketPath: "/private/lcf/py.sock",
  launchId: "00000000-0000-4000-8000-000000000001",
  token: "A".repeat(43)
};

interface FakeTransport {
  request: (
    options: RequestOptions,
    callback: (response: IncomingMessage) => void
  ) => ClientRequest;
  options: RequestOptions[];
  bodies: Array<Buffer | undefined>;
  requests: Array<ClientRequest & EventEmitter>;
}

function response(
  callback: (response: IncomingMessage) => void,
  status: number,
  body: Buffer | string,
  headers: Record<string, string> = { "content-type": "application/json" }
): void {
  const stream = new PassThrough() as PassThrough & IncomingMessage;
  stream.statusCode = status;
  stream.headers = headers;
  callback(stream);
  stream.end(body);
}

function fakeTransport(
  responder?: (
    callback: (response: IncomingMessage) => void,
    request: ClientRequest & EventEmitter
  ) => void
): FakeTransport {
  const options: RequestOptions[] = [];
  const bodies: Array<Buffer | undefined> = [];
  const requests: Array<ClientRequest & EventEmitter> = [];
  return {
    options,
    bodies,
    requests,
    request(requestOptions, callback) {
      options.push(requestOptions);
      const emitter = new EventEmitter() as ClientRequest & EventEmitter;
      Object.assign(emitter, {
        destroyed: false,
        setTimeout: vi.fn(() => emitter),
        destroy: vi.fn(() => {
          Object.defineProperty(emitter, "destroyed", { value: true });
          return emitter;
        }),
        end: vi.fn((body?: Buffer) => {
          bodies.push(body);
          queueMicrotask(() => responder?.(callback, emitter));
          return emitter;
        })
      });
      requests.push(emitter);
      return emitter;
    }
  };
}

const healthRequest: ApiRequest = {
  method: "GET",
  path: "/api/health",
  timeoutMs: 1_000
};

afterEach(() => {
  vi.useRealTimers();
});

describe("UDS API proxy", () => {
  it("adds only Main-owned headers and never returns raw response headers", async () => {
    const transport = fakeTransport((callback) =>
      response(
        callback,
        200,
        JSON.stringify({
          jobs: [
            {
              id: "job-1",
              status: "queued",
              error: "/private/repository/error",
              request: { source: "/private/repository" },
              pid: 123
            }
          ]
        }),
        {
          "content-type": "application/json",
          authorization: `Bearer ${connection.token}`,
          connection: "keep-alive",
          "set-cookie": "secret=true"
        }
      )
    );

    const result = await proxyApiRequest(
      { method: "GET", path: "/api/jobs", timeoutMs: 1_000 },
      connection,
      {
        request: transport.request,
        now: () => 1_000,
        requestId: () => "00000000-0000-4000-8000-000000000002"
      }
    );

    expect(transport.options[0]).toMatchObject({
      socketPath: connection.socketPath,
      path: "/api/jobs",
      method: "GET",
      agent: false
    });
    expect(transport.options[0]?.headers).toEqual({
      Authorization: `Bearer ${connection.token}`,
      Accept: "application/json",
      "X-LCF-Protocol-Version": "1.0",
      "X-LCF-Launch-ID": connection.launchId,
      "X-LCF-Request-ID": "00000000-0000-4000-8000-000000000002",
      "X-LCF-Deadline-Ms": "2000"
    });
    expect(result).toEqual({
      status: 200,
      body: { jobs: [{ id: "job-1", status: "queued" }] }
    });
    expect(result).not.toHaveProperty("headers");
    expect(JSON.stringify(result)).not.toContain(connection.token);
    expect(JSON.stringify(result)).not.toContain(connection.socketPath);
  });

  it("never exposes a local library source path in a remodeled response", async () => {
    const transport = fakeTransport((callback) =>
      response(
        callback,
        200,
        JSON.stringify([
          { id: "local", name: "Local", source: "/private/repository" },
          {
            id: "remote",
            name: "Remote",
            source: "https://github.com/example/library.git"
          }
        ])
      )
    );
    await expect(
      proxyApiRequest(
        { method: "GET", path: "/api/libraries", timeoutMs: 1_000 },
        connection,
        { request: transport.request }
      )
    ).resolves.toEqual({
      status: 200,
      body: [
        { id: "local", name: "Local" },
        {
          id: "remote",
          name: "Remote",
          source: "https://github.com/example/library.git"
        }
      ]
    });
  });

  it("keeps only canonical repo-relative path and file response fields", async () => {
    for (const safe of [
      "README.md",
      "docs/guide/intro.md",
      "src/components/view.tsx",
      "资料/说明.md"
    ]) {
      expect(isSafeRepositoryRelativePath(safe), safe).toBe(true);
    }
    for (const unsafe of [
      "/Users/example/private.md",
      "C:/Users/example/private.md",
      "~/private.md",
      "../private.md",
      "docs/../private.md",
      "docs//private.md",
      "docs\\private.md",
      "docs/\u0000private.md"
    ]) {
      expect(isSafeRepositoryRelativePath(unsafe), unsafe).toBe(false);
    }

    const transport = fakeTransport((callback) =>
      response(
        callback,
        200,
        JSON.stringify({
          results: [
            {
              title: "safe",
              path: "docs/guide.md",
              file: "src/index.ts",
              source_refs: [
                { path: "src/source.ts" },
                { path: "../../private" }
              ]
            },
            {
              title: "unsafe",
              path: "/Users/example/private.md",
              file: "C:/Users/example/private.ts"
            }
          ]
        })
      )
    );
    const result = await proxyApiRequest(
      {
        method: "POST",
        path: "/api/query",
        body: { query: "needle" },
        timeoutMs: 1_000
      },
      connection,
      { request: transport.request }
    );
    expect(result).toEqual({
      status: 200,
      body: {
        results: [
          {
            title: "safe",
            path: "docs/guide.md",
            file: "src/index.ts",
            source_refs: [{ path: "src/source.ts" }, {}]
          },
          { title: "unsafe" }
        ]
      }
    });
    expect(JSON.stringify(result)).not.toContain("/Users/");
    expect(JSON.stringify(result)).not.toContain("../../");
  });

  it("does not follow redirects", async () => {
    let calls = 0;
    const transport = fakeTransport((callback) => {
      calls += 1;
      response(callback, 302, '{"status":"moved"}', {
        "content-type": "application/json",
        location: "https://attacker.invalid/"
      });
    });
    await expect(
      proxyApiRequest(healthRequest, connection, { request: transport.request })
    ).resolves.toEqual({ status: 302, body: { status: "moved" } });
    expect(calls).toBe(1);
  });

  it("fails closed on non-JSON success and uncertain mutating 5xx", async () => {
    const textTransport = fakeTransport((callback) =>
      response(callback, 200, "not json", {
        "content-type": "text/plain"
      })
    );
    await expect(
      proxyApiRequest(healthRequest, connection, {
        request: textTransport.request
      })
    ).rejects.toMatchObject({ code: "invalid-response" });

    const serverErrorTransport = fakeTransport((callback) =>
      response(callback, 500, '{"detail":"write may have completed"}')
    );
    await expect(
      proxyApiRequest(
        {
          method: "POST",
          path: "/api/proposals/proposal-1/publish",
          timeoutMs: 1_000
        },
        connection,
        { request: serverErrorTransport.request }
      )
    ).rejects.toMatchObject({ code: "result-uncertain" });
  });

  it("enforces the response size bound", async () => {
    const transport = fakeTransport((callback) =>
      response(
        callback,
        200,
        Buffer.alloc(MAX_RESPONSE_BODY_BYTES + 1, 0x61),
        { "content-type": "text/plain" }
      )
    );
    await expect(
      proxyApiRequest(healthRequest, connection, { request: transport.request })
    ).rejects.toMatchObject({ code: "response-too-large" });
  });

  it("uses an absolute wall-clock timer and marks non-idempotent outcomes uncertain", async () => {
    vi.useFakeTimers();
    const transport = fakeTransport();
    const promise = proxyApiRequest(
      {
        method: "POST",
        path: "/api/query",
        body: { query: "needle" },
        timeoutMs: 1_000
      },
      connection,
      { request: transport.request }
    );
    const rejection = expect(promise).rejects.toMatchObject({
      code: "result-uncertain"
    });
    await vi.advanceTimersByTimeAsync(1_000);
    await rejection;
    expect(transport.requests[0]?.destroy).toHaveBeenCalled();
  });

  it("marks post-send transport failure uncertain for POST but not GET", async () => {
    const postTransport = fakeTransport((_callback, request) => {
      request.emit("error", new Error("socket path and secret"));
    });
    await expect(
      proxyApiRequest(
        {
          method: "POST",
          path: "/api/query",
          body: { query: "needle" },
          timeoutMs: 1_000
        },
        connection,
        { request: postTransport.request }
      )
    ).rejects.toMatchObject({ code: "result-uncertain" });

    const getTransport = fakeTransport((_callback, request) => {
      request.emit("error", new Error("socket path and secret"));
    });
    await expect(
      proxyApiRequest(healthRequest, connection, {
        request: getTransport.request
      })
    ).rejects.toEqual(new ApiProxyError("transport"));
  });

  it("bounds Main-side concurrency before opening another socket", async () => {
    let firstCallback: ((response: IncomingMessage) => void) | undefined;
    const transport = fakeTransport((callback) => {
      firstCallback ??= callback;
    });
    const proxy = new ApiProxy(1, { request: transport.request });
    const first = proxy.request(healthRequest, connection);
    await Promise.resolve();
    await expect(proxy.request(healthRequest, connection)).rejects.toMatchObject({
      code: "busy"
    });
    expect(transport.options).toHaveLength(1);

    response(firstCallback!, 200, '{"status":"ok"}');
    await expect(first).resolves.toMatchObject({ status: 200 });
  });
});

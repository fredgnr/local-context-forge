import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import type {
  ClientRequest,
  IncomingMessage,
  RequestOptions
} from "node:http";
import { describe, expect, it, vi } from "vitest";
import {
  MAX_QMD_COLLECTIONS,
  QmdClient,
  QmdClientError,
  type QmdConnection
} from "../src/main/qmdClient";

const connection: QmdConnection = {
  socketPath: "/tmp/qmd.sock",
  launchId: "01234567-89ab-4cde-8fab-0123456789ab",
  token: "a".repeat(43),
  buildManifestSha256: "b".repeat(64)
};

function responseRequest(
  status: number,
  value: unknown
): (
  options: RequestOptions,
  callback: (response: IncomingMessage) => void
) => ClientRequest {
  return (_options, callback) => {
    const request = new EventEmitter() as ClientRequest & EventEmitter;
    Object.assign(request, {
      setTimeout: vi.fn(() => request),
      destroy: vi.fn(() => request),
      end: vi.fn(() => {
        const stream = new PassThrough();
        const response = stream as unknown as IncomingMessage;
        response.statusCode = status;
        response.headers = { "content-type": "application/json" };
        callback(response);
        stream.end(JSON.stringify(value));
        return request;
      })
    });
    return request;
  };
}

describe("QmdClient", () => {
  it("accepts only the pinned worker, Node, launch, and manifest handshake", async () => {
    const request = vi.fn(
      responseRequest(200, {
        service: "local-context-forge",
        role: "qmd-worker",
        protocol: { major: 1, minor: 0 },
        launch_id: connection.launchId,
        transport: "uds",
        qmd_version: "2.5.3",
        node_version: "22.23.2",
        build_manifest_sha256: connection.buildManifestSha256,
        revision: null,
        collections: 0
      })
    );
    const client = new QmdClient(connection, {
      request,
      now: () => 1_000,
      requestId: () => "12345678-9abc-4def-8abc-123456789abc"
    });

    await expect(client.health()).resolves.toMatchObject({
      role: "qmd-worker",
      node_version: "22.23.2",
      qmd_version: "2.5.3"
    });
    const options = request.mock.calls[0]![0];
    expect(options.socketPath).toBe(connection.socketPath);
    expect(options.headers).toMatchObject({
      Authorization: `Bearer ${connection.token}`,
      "X-LCF-Launch-Id": connection.launchId
    });
  });

  it("rejects a mismatched worker runtime as an invalid response", async () => {
    const client = new QmdClient(connection, {
      request: responseRequest(200, {
        service: "local-context-forge",
        role: "qmd-worker",
        protocol: { major: 1, minor: 0 },
        launch_id: connection.launchId,
        transport: "uds",
        qmd_version: "2.5.3",
        node_version: "24.0.0",
        build_manifest_sha256: connection.buildManifestSha256,
        revision: null,
        collections: 0
      })
    });
    await expect(client.health()).rejects.toMatchObject({
      kind: "invalid-response",
      code: "invalid_response"
    });
  });

  it("rejects revision-mismatched search results", async () => {
    const client = new QmdClient(connection, {
      request: responseRequest(200, { revision: 8, results: [] })
    });
    await expect(
      client.search({
        revision: 7,
        collection: "collection",
        query: "widgets",
        limit: 5
      })
    ).rejects.toBeInstanceOf(QmdClientError);
  });

  it("rejects too many collections before making any transport request", async () => {
    const request = vi.fn(responseRequest(200, {}));
    const client = new QmdClient(connection, { request });
    const collections = Array.from(
      { length: MAX_QMD_COLLECTIONS + 1 },
      (_, index) => ({
        name: `collection-${index}`,
        wiki_root: "widgets/versions/v1"
      })
    );

    await expect(client.reconcile(1, collections)).rejects.toMatchObject({
      code: "too_many_collections"
    });
    expect(request).not.toHaveBeenCalled();
  });
});

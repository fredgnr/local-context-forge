import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CompanionBridgeError,
  discardMcpTargetOwnerMarker,
  type CompanionBridgePort
} from "../companion/src/bridgeClient";
import { createCompanionServer } from "../companion/src/server";

class FakeBridge implements CompanionBridgePort {
  readonly authorize = vi.fn(async () => undefined);
  readonly close = vi.fn();
  readonly queryDocs = vi.fn(
    async (libraryId: string, query: string) =>
      `query:${libraryId}:${query}`
  );
  readonly resolveLibraryId = vi.fn(
    async (libraryName: string, query: string) =>
      `resolve:${libraryName}:${query}`
  );
}

const cleanups: Array<() => Promise<void>> = [];

async function fixture(bridge: CompanionBridgePort = new FakeBridge()) {
  const server = createCompanionServer(bridge);
  const client = new Client({
    name: "official-sdk-contract-client",
    version: "1.0.0"
  });
  const [clientTransport, serverTransport] =
    InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  cleanups.push(async () => {
    await client.close().catch(() => undefined);
    await server.close().catch(() => undefined);
    bridge.close();
  });
  return { bridge, client, server };
}

afterEach(async () => {
  while (cleanups.length > 0) {
    await cleanups.pop()?.();
  }
});

describe("Context7-compatible MCP companion", () => {
  it("discards the onboarding ownership marker before bridge startup", () => {
    const environment = {
      LCF_MCP_OWNER_ID: "marker-must-not-reach-runtime",
      SAFE_VALUE: "preserved"
    };
    discardMcpTargetOwnerMarker(environment);
    expect(environment).toEqual({ SAFE_VALUE: "preserved" });
    expect(JSON.stringify(environment)).not.toContain(
      "marker-must-not-reach-runtime"
    );
  });

  it("replays list/call through the official SDK with exactly two read-only tools", async () => {
    const bridge = new FakeBridge();
    const { client } = await fixture(bridge);
    await vi.waitFor(() =>
      expect(bridge.authorize).toHaveBeenCalledWith(
        {
          name: "official-sdk-contract-client",
          version: "1.0.0"
        }
      )
    );

    const listed = await client.listTools();
    expect(listed.nextCursor).toBeUndefined();
    expect(listed.tools.map((tool) => tool.name)).toEqual([
      "resolve-library-id",
      "query-docs"
    ]);
    for (const tool of listed.tools) {
      expect(tool.annotations).toMatchObject({
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
        readOnlyHint: true
      });
    }
    expect(listed.tools[0]!.inputSchema).toMatchObject({
      additionalProperties: false,
      properties: {
        libraryName: { type: "string" },
        query: { type: "string" }
      },
      required: ["libraryName"],
      type: "object"
    });
    expect(listed.tools[1]!.inputSchema).toMatchObject({
      additionalProperties: false,
      properties: {
        libraryId: { type: "string" },
        query: { type: "string" }
      },
      required: ["libraryId", "query"],
      type: "object"
    });

    const resolved = await client.callTool({
      arguments: {
        libraryName: "widgets",
        query: "create a client"
      },
      name: "resolve-library-id"
    });
    expect(resolved).toMatchObject({
      content: [
        {
          text: "resolve:widgets:create a client",
          type: "text"
        }
      ]
    });
    expect(bridge.resolveLibraryId).toHaveBeenCalledWith(
      "widgets",
      "create a client",
      expect.any(AbortSignal)
    );

    const queried = await client.callTool({
      arguments: {
        libraryId: "/local/widgets",
        query: "build_widget"
      },
      name: "query-docs"
    });
    expect(queried).toMatchObject({
      content: [
        {
          text: "query:/local/widgets:build_widget",
          type: "text"
        }
      ]
    });
    expect(bridge.queryDocs).toHaveBeenCalledTimes(1);
  });

  it("keeps list pagination bounded and never advertises privileged operations", async () => {
    const { client } = await fixture();
    const first = await client.listTools();
    const replay = await client.listTools({ cursor: "opaque-replay-cursor" });
    expect(replay.tools).toEqual(first.tools);
    expect(replay.nextCursor).toBeUndefined();
    expect(
      replay.tools.some((tool) =>
        /ingest|review|publish|settings|provider|model|update|path/i.test(
          tool.name
        )
      )
    ).toBe(false);
  });

  it("rejects unknown tools, extra fields, invalid IDs, and over-limit inputs before the bridge", async () => {
    const bridge = new FakeBridge();
    const { client } = await fixture(bridge);

    await expect(
      client.callTool({
        arguments: {},
        name: "publish"
      })
    ).resolves.toMatchObject({ isError: true });
    await expect(
      client.callTool({
        arguments: {
          libraryName: "widgets",
          query: "",
          unexpected: true
        },
        name: "resolve-library-id"
      })
    ).resolves.toMatchObject({ isError: true });
    await expect(
      client.callTool({
        arguments: {
          libraryId: "../../private",
          query: "widgets"
        },
        name: "query-docs"
      })
    ).resolves.toMatchObject({ isError: true });
    await expect(
      client.callTool({
        arguments: {
          libraryName: "w".repeat(201),
          query: ""
        },
        name: "resolve-library-id"
      })
    ).resolves.toMatchObject({ isError: true });
    expect(bridge.resolveLibraryId).not.toHaveBeenCalled();
    expect(bridge.queryDocs).not.toHaveBeenCalled();
  });

  it("returns bounded generic failures without leaking bridge diagnostics", async () => {
    const bridge = new FakeBridge();
    bridge.queryDocs.mockRejectedValueOnce(
      new Error("private data /tmp/repository capability=secret")
    );
    const { client } = await fixture(bridge);
    const result = await client.callTool({
      arguments: {
        libraryId: "/local/widgets",
        query: "widgets"
      },
      name: "query-docs"
    });
    expect(result.isError).toBe(true);
    const serialized = JSON.stringify(result);
    expect(serialized).toContain("Start Local Context Forge");
    expect(serialized).not.toContain("/tmp/repository");
    expect(serialized).not.toContain("capability");

    bridge.resolveLibraryId.mockRejectedValueOnce(
      new CompanionBridgeError("stale_revision")
    );
    const stale = await client.callTool({
      arguments: {
        libraryName: "widgets"
      },
      name: "resolve-library-id"
    });
    expect(stale.isError).toBe(true);
    expect(JSON.stringify(stale)).toContain("corpus changed");
  });
});

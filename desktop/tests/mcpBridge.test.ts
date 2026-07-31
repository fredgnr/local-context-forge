import {
  chmod,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import net from "node:net";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CompanionBridgeClient,
  CompanionBridgeError,
  configuredMcpBridgeEndpoint,
  resolveDefaultMcpBridgeEndpoint,
  type McpBridgeEndpoint
} from "../companion/src/bridgeClient";
import {
  MCP_LAUNCH_FILE_NAME,
  MCP_RENDEZVOUS_FILE_NAME,
  MCP_RUNTIME_DIRECTORY_PREFIX
} from "../src/mcpProtocol";
import {
  McpBridgeServer,
  prepareMcpBridgeRuntime
} from "../src/main/mcpBridge";
import {
  McpReadError,
  type McpReadPort
} from "../src/main/mcpSidecarRead";

class FakeReadService implements McpReadPort {
  revision = 7;
  readonly getRevision = vi.fn(async () => this.revision);
  readonly resolveLibraryId = vi.fn(
    async (input: {
      corpusRevision: number;
      libraryName: string;
      query: string;
    }) => ({
      corpusRevision: input.corpusRevision,
      text: `resolved:${input.libraryName}:${input.query}`
    })
  );
  readonly queryDocs = vi.fn(
    async (input: {
      corpusRevision: number;
      libraryId: string;
      query: string;
    }) => ({
      corpusRevision: input.corpusRevision,
      text: `queried:${input.libraryId}:${input.query}`
    })
  );
}

interface BridgeFixture {
  client: CompanionBridgeClient;
  dataDir: string;
  readService: FakeReadService;
  root: string;
  server: McpBridgeServer;
  tempRoot: string;
}

const cleanups: Array<() => Promise<void>> = [];

async function probeUnixSockets(): Promise<boolean> {
  const root = await mkdtemp(path.join(os.tmpdir(), "lcf-mcp-probe-"));
  const socketPath = path.join(root, "probe.sock");
  const server = net.createServer();
  try {
    const outcome = await new Promise<"listening" | NodeJS.ErrnoException>(
      (resolve) => {
        server.once("listening", () => resolve("listening"));
        server.once("error", (error: NodeJS.ErrnoException) =>
          resolve(error)
        );
        server.listen(socketPath);
      }
    );
    if (outcome !== "listening") {
      if (process.env.CI === "true") {
        throw outcome;
      }
      expect(outcome.code).toBe("EPERM");
      return false;
    }
    await new Promise<void>((resolve) => server.close(() => resolve()));
    return true;
  } finally {
    if (server.listening) {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
    await rm(root, { force: true, recursive: true });
  }
}

let unixSocketProbe: Promise<boolean> | undefined;

function unixSocketsAvailable(): Promise<boolean> {
  unixSocketProbe ??= probeUnixSockets();
  return unixSocketProbe;
}

async function fixture(options: {
  approve?: boolean;
  authorizationTimeoutMs?: number;
  operationTimeoutMs?: number;
} = {}): Promise<BridgeFixture> {
  const root = await mkdtemp(path.join(os.tmpdir(), "lcf-mcp-bridge-"));
  const dataDir = path.join(root, "data");
  const tempRoot = path.join(root, "temp");
  await mkdir(dataDir, { mode: 0o700 });
  await mkdir(tempRoot, { mode: 0o700 });
  await chmod(dataDir, 0o700);
  await chmod(tempRoot, 0o700);
  const readService = new FakeReadService();
  const server = new McpBridgeServer({
    ...(options.authorizationTimeoutMs === undefined
      ? {}
      : { authorizationTimeoutMs: options.authorizationTimeoutMs }),
    ...(options.operationTimeoutMs === undefined
      ? {}
      : { operationTimeoutMs: options.operationTimeoutMs }),
    authorizeClient: vi.fn(async () => options.approve ?? true),
    dataDir,
    tempRoot,
    readService
  });
  await server.start();
  const client = new CompanionBridgeClient(endpoint(server, dataDir, tempRoot));
  cleanups.push(async () => {
    client.close();
    await server.shutdown();
    await rm(root, { force: true, recursive: true });
  });
  return { client, dataDir, readService, root, server, tempRoot };
}

function endpoint(
  server: McpBridgeServer,
  dataDir: string,
  tempRoot: string
): McpBridgeEndpoint {
  const socketPath = server.getSocketPath();
  return {
    launchId: server.getLaunchId(),
    rendezvousPath: path.join(dataDir, MCP_RENDEZVOUS_FILE_NAME),
    runtimeDirectory: path.dirname(socketPath),
    socketPath,
    tempRoot
  };
}

afterEach(async () => {
  while (cleanups.length > 0) {
    await cleanups.pop()?.();
  }
});

describe("MCP Main bridge UDS lifecycle", () => {
  it("requires explicit approval, binds a capability to one connection, and exposes only read results", async (context) => {
    if (!(await unixSocketsAvailable())) {
      context.skip();
      return;
    }
    const { client, readService, server } = await fixture();
    await client.authorize({
      name: "contract-client",
      version: "1.0.0"
    });
    const clients = server.listClients();
    expect(clients).toHaveLength(1);
    expect(clients[0]).toMatchObject({
      client: {
        name: "contract-client",
        version: "1.0.0"
      }
    });
    const serializedClients = JSON.stringify(clients);
    expect(serializedClients).not.toContain("capability");
    expect(serializedClients).not.toContain(server.getSocketPath());

    await expect(
      client.resolveLibraryId("widgets", "create a client")
    ).resolves.toBe("resolved:widgets:create a client");
    await expect(
      client.queryDocs("/local/widgets", "build_widget")
    ).resolves.toBe("queried:/local/widgets:build_widget");
    expect(readService.resolveLibraryId).toHaveBeenCalledWith(
      {
        corpusRevision: 7,
        libraryName: "widgets",
        query: "create a client"
      },
      expect.any(AbortSignal)
    );
    expect(readService.queryDocs).toHaveBeenCalledTimes(1);
  });

  it("fails closed when approval is denied or the app is not running", async (context) => {
    if (!(await unixSocketsAvailable())) {
      context.skip();
      return;
    }
    const denied = await fixture({ approve: false });
    await expect(
      denied.client.authorize({
        name: "denied-client",
        version: "1.0.0"
      })
    ).rejects.toMatchObject({ code: "approval_denied" });
    expect(denied.server.listClients()).toEqual([]);

    const missingRoot = await mkdtemp(
      path.join(os.tmpdir(), "lcf-mcp-missing-")
    );
    const missingTemp = path.join(missingRoot, "temp");
    await mkdir(missingTemp, { mode: 0o700 });
    await chmod(missingTemp, 0o700);
    const missingDirectory = await mkdtemp(
      path.join(missingTemp, MCP_RUNTIME_DIRECTORY_PREFIX)
    );
    await chmod(missingDirectory, 0o700);
    const launchId = "00000000-0000-4000-8000-000000000001";
    await writeFile(
      path.join(missingDirectory, MCP_LAUNCH_FILE_NAME),
      `${JSON.stringify({
        launchId,
        schemaVersion: 1,
        socketName: "mcp.sock"
      })}\n`,
      { mode: 0o600 }
    );
    const missing = new CompanionBridgeClient({
      launchId,
      runtimeDirectory: missingDirectory,
      socketPath: path.join(missingDirectory, "mcp.sock"),
      tempRoot: missingTemp
    });
    try {
      await expect(
        missing.authorize({
          name: "missing-client",
          version: "1.0.0"
        })
      ).rejects.toMatchObject({ code: "unavailable" });
    } finally {
      missing.close();
      await rm(missingRoot, { force: true, recursive: true });
    }
  });

  it("rejects a stolen or incorrect capability on another UDS connection", async (context) => {
    if (!(await unixSocketsAvailable())) {
      context.skip();
      return;
    }
    const { client, dataDir, server, tempRoot } = await fixture();
    await client.authorize({
      name: "first-client",
      version: "1.0.0"
    });
    const internal = client as unknown as {
      session: {
        capability: string;
        client: { name: string; version: string };
        corpusRevision: number;
        expiresAt: number;
        sessionId: string;
      };
    };
    const originalCapability = internal.session.capability;
    internal.session.capability = "A".repeat(43);
    await expect(
      client.queryDocs("/local/widgets", "widgets")
    ).rejects.toMatchObject({ code: "unauthorized" });
    internal.session.capability = originalCapability;

    const thief = new CompanionBridgeClient(
      endpoint(server, dataDir, tempRoot)
    );
    const thiefInternal = thief as unknown as {
      session?: typeof internal.session;
    };
    thiefInternal.session = { ...internal.session };
    try {
      await expect(
        thief.queryDocs("/local/widgets", "widgets")
      ).rejects.toMatchObject({ code: "unauthorized" });
    } finally {
      thief.close();
    }
  });

  it("rejects authorization that is not bound to the current launch marker", async (context) => {
    if (!(await unixSocketsAvailable())) {
      context.skip();
      return;
    }
    const { dataDir, server, tempRoot } = await fixture();
    const wrongLaunch = new CompanionBridgeClient(
      endpoint(server, dataDir, tempRoot),
      {
        request: (options, callback) =>
          http.request(
            {
              ...options,
              headers: {
                ...options.headers,
                "X-LCF-MCP-Launch-ID":
                  "00000000-0000-4000-8000-000000000099"
              }
            },
            callback
          )
      }
    );
    try {
      await expect(
        wrongLaunch.authorize({
          name: "stale-launch-client",
          version: "1.0.0"
        })
      ).rejects.toMatchObject({ code: "unauthorized" });
      expect(server.listClients()).toEqual([]);
    } finally {
      wrongLaunch.close();
    }
  });

  it("revokes active clients and aborts further access without stopping the bridge", async (context) => {
    if (!(await unixSocketsAvailable())) {
      context.skip();
      return;
    }
    const { client, dataDir, server, tempRoot } = await fixture();
    await client.authorize({
      name: "revoked-client",
      version: "1.0.0"
    });
    const sessionId = server.listClients()[0]!.sessionId;
    expect(server.revoke(sessionId)).toBe(true);
    await expect(
      client.resolveLibraryId("widgets", "")
    ).rejects.toSatisfy(
      (error: unknown) =>
        error instanceof CompanionBridgeError &&
        ["unauthorized", "unavailable", "revoked"].includes(error.code)
    );

    const replacement = new CompanionBridgeClient(
      endpoint(server, dataDir, tempRoot)
    );
    try {
      await replacement.authorize({
        name: "replacement-client",
        version: "1.0.0"
      });
      await expect(
        replacement.resolveLibraryId("widgets", "")
      ).resolves.toBe("resolved:widgets:");
    } finally {
      replacement.close();
    }
  });

  it("propagates stale revision, timeout, and backend failure as bounded error codes", async (context) => {
    if (!(await unixSocketsAvailable())) {
      context.skip();
      return;
    }
    const { client, readService } = await fixture();
    await client.authorize({
      name: "failure-client",
      version: "1.0.0"
    });
    readService.queryDocs.mockRejectedValueOnce(
      new McpReadError("stale_revision")
    );
    await expect(
      client.queryDocs("/local/widgets", "widgets")
    ).rejects.toMatchObject({ code: "stale_revision" });
    readService.queryDocs.mockRejectedValueOnce(
      new Error("private /tmp/repository capability=secret")
    );
    const failure = await client
      .queryDocs("/local/widgets", "widgets")
      .catch((error: unknown) => error);
    expect(failure).toMatchObject({ code: "backend_unavailable" });
    expect(JSON.stringify(failure)).not.toContain("/tmp/repository");
    expect(JSON.stringify(failure)).not.toContain("secret");
  });

});

describe("MCP Main bridge runtime validation", () => {
  it("publishes a private rendezvous to a per-launch temp directory and cleans it", async (context) => {
    if (!(await unixSocketsAvailable())) {
      context.skip();
      return;
    }
    const { client, dataDir, server, tempRoot } = await fixture();
    const socketPath = server.getSocketPath();
    const runtimeDirectory = path.dirname(socketPath);
    const rendezvousPath = path.join(
      dataDir,
      MCP_RENDEZVOUS_FILE_NAME
    );
    expect(path.dirname(runtimeDirectory)).toBe(tempRoot);
    expect(path.basename(runtimeDirectory)).toMatch(/^lcf-mcp-/);
    expect(socketPath.startsWith(dataDir)).toBe(false);

    const rendezvousInfo = await lstat(rendezvousPath);
    expect(rendezvousInfo.mode & 0o777).toBe(0o600);
    const rendezvousText = await readFile(rendezvousPath, "utf8");
    expect(JSON.parse(rendezvousText)).toEqual({
      runtimeDirectory,
      schemaVersion: 1
    });
    expect(rendezvousText).not.toContain("capability");
    expect(rendezvousText).not.toContain("launchId");
    expect(rendezvousText).not.toContain("mcp.sock");

    client.close();
    await server.shutdown();
    await expect(lstat(rendezvousPath)).rejects.toMatchObject({
      code: "ENOENT"
    });
    await expect(lstat(runtimeDirectory)).rejects.toMatchObject({
      code: "ENOENT"
    });
  });

  it("fails runtime preparation on symlinked roots and unsafe rendezvous targets", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lcf-mcp-runtime-"));
    const dataDir = path.join(root, "data");
    const tempRoot = path.join(root, "temp");
    const outside = path.join(root, "outside");
    await mkdir(dataDir, { mode: 0o700 });
    await mkdir(tempRoot, { mode: 0o700 });
    await mkdir(outside, { mode: 0o700 });
    await chmod(dataDir, 0o700);
    await chmod(tempRoot, 0o700);
    await chmod(outside, 0o700);
    const linkedTemp = path.join(root, "linked-temp");
    await symlink(outside, linkedTemp, "dir");
    await expect(
      prepareMcpBridgeRuntime(dataDir, linkedTemp)
    ).rejects.toMatchObject({
      code: "unavailable"
    });

    const outsideFile = path.join(outside, "rendezvous.json");
    await writeFile(outsideFile, "{}", { mode: 0o600 });
    await symlink(
      outsideFile,
      path.join(dataDir, MCP_RENDEZVOUS_FILE_NAME)
    );
    await expect(
      prepareMcpBridgeRuntime(dataDir, tempRoot)
    ).rejects.toMatchObject({
      code: "unavailable"
    });
    await rm(root, { force: true, recursive: true });
  });
});

describe("MCP companion rendezvous validation", () => {
  it("accepts only a private direct child of the expected temp root", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lcf-mcp-rendezvous-"));
    const home = path.join(root, "home");
    const dataDir = path.join(
      home,
      "Library",
      "Application Support",
      "Local Context Forge"
    );
    const tempRoot = path.join(root, "temp");
    await mkdir(dataDir, { recursive: true, mode: 0o700 });
    await mkdir(tempRoot, { mode: 0o700 });
    await chmod(dataDir, 0o700);
    await chmod(tempRoot, 0o700);
    const runtimeDirectory = await mkdtemp(
      path.join(tempRoot, MCP_RUNTIME_DIRECTORY_PREFIX)
    );
    await chmod(runtimeDirectory, 0o700);
    const launchId = "00000000-0000-4000-8000-000000000002";
    await writeFile(
      path.join(runtimeDirectory, MCP_LAUNCH_FILE_NAME),
      `${JSON.stringify({
        launchId,
        schemaVersion: 1,
        socketName: "mcp.sock"
      })}\n`,
      { mode: 0o600 }
    );
    const rendezvousPath = path.join(
      dataDir,
      MCP_RENDEZVOUS_FILE_NAME
    );
    await writeFile(
      rendezvousPath,
      `${JSON.stringify({ runtimeDirectory, schemaVersion: 1 })}\n`,
      { mode: 0o600 }
    );

    await expect(
      resolveDefaultMcpBridgeEndpoint(home, tempRoot, "darwin")
    ).resolves.toEqual({
      launchId,
      rendezvousPath,
      runtimeDirectory,
      socketPath: path.join(runtimeDirectory, "mcp.sock"),
      tempRoot
    });

    const linkedTempRoot = path.join(root, "linked-temp");
    await symlink(tempRoot, linkedTempRoot, "dir");
    await expect(
      resolveDefaultMcpBridgeEndpoint(home, linkedTempRoot, "darwin")
    ).rejects.toMatchObject({ code: "unavailable" });

    await writeFile(
      rendezvousPath,
      `${JSON.stringify({
        runtimeDirectory: path.join(root, "outside"),
        schemaVersion: 1
      })}\n`
    );
    await expect(
      resolveDefaultMcpBridgeEndpoint(home, tempRoot, "darwin")
    ).rejects.toMatchObject({ code: "unavailable" });
    await rm(root, { force: true, recursive: true });
  });

  it("rejects symlinked rendezvous and launch marker files", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lcf-mcp-links-"));
    const home = path.join(root, "home");
    const dataDir = path.join(
      home,
      "Library",
      "Application Support",
      "Local Context Forge"
    );
    const tempRoot = path.join(root, "temp");
    await mkdir(dataDir, { recursive: true, mode: 0o700 });
    await mkdir(tempRoot, { mode: 0o700 });
    await chmod(dataDir, 0o700);
    await chmod(tempRoot, 0o700);
    const runtimeDirectory = await mkdtemp(
      path.join(tempRoot, MCP_RUNTIME_DIRECTORY_PREFIX)
    );
    await chmod(runtimeDirectory, 0o700);
    const outside = path.join(root, "outside.json");
    await writeFile(outside, "{}", { mode: 0o600 });
    await symlink(
      outside,
      path.join(dataDir, MCP_RENDEZVOUS_FILE_NAME)
    );
    await expect(
      resolveDefaultMcpBridgeEndpoint(home, tempRoot, "darwin")
    ).rejects.toMatchObject({ code: "unavailable" });
    await rm(path.join(dataDir, MCP_RENDEZVOUS_FILE_NAME));
    await writeFile(
      path.join(dataDir, MCP_RENDEZVOUS_FILE_NAME),
      `${JSON.stringify({ runtimeDirectory, schemaVersion: 1 })}\n`,
      { mode: 0o600 }
    );
    await symlink(
      outside,
      path.join(runtimeDirectory, MCP_LAUNCH_FILE_NAME)
    );
    await expect(
      resolveDefaultMcpBridgeEndpoint(home, tempRoot, "darwin")
    ).rejects.toMatchObject({ code: "unavailable" });
    await rm(root, { force: true, recursive: true });
  });

  it("rejects incomplete or partially injected debug discovery", async () => {
    await expect(
      configuredMcpBridgeEndpoint({
        LCF_MCP_DEBUG: "1",
        LCF_MCP_DEBUG_SOCKET: "/tmp/lcf-mcp-test/mcp.sock"
      })
    ).rejects.toMatchObject({ code: "unavailable" });
    await expect(
      configuredMcpBridgeEndpoint({
        LCF_MCP_DEBUG_SOCKET: "/tmp/lcf-mcp-test/mcp.sock"
      })
    ).rejects.toMatchObject({ code: "unavailable" });
  });
});

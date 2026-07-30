import { EventEmitter, once } from "node:events";
import { chmod, lstat, mkdtemp, rm, symlink } from "node:fs/promises";
import type { ClientRequest, IncomingMessage, RequestOptions } from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { PassThrough } from "node:stream";
import type { SpawnOptions } from "node:child_process";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SidecarSupervisor,
  buildSidecarEnvironment,
  cleanupPrivateRuntime,
  createPrivateRuntime,
  hasPrivateSocketMetadata,
  inspectPrivateSocket,
  requestHandshake,
  type HandshakeResponse,
  type RuntimePaths
} from "../src/main/sidecar";
import type { SidecarConnection } from "../src/main/apiProxy";

class FakeChild extends EventEmitter {
  readonly pid: number | undefined;
  exitCode: number | null = null;
  signalCode: NodeJS.Signals | null = null;
  readonly controlPipe = new PassThrough();
  readonly stdio = [null, null, null, this.controlPipe] as const;
  readonly signals: Array<NodeJS.Signals | number | undefined> = [];

  constructor(readonly exitsWhenKilled = true, pid: number | null = 101) {
    super();
    this.pid = pid === null ? undefined : pid;
  }

  kill(signal?: NodeJS.Signals | number): boolean {
    this.signals.push(signal);
    if (this.exitsWhenKilled) {
      this.exitNow(null, typeof signal === "string" ? signal : null);
    }
    return true;
  }

  exitNow(
    code: number | null = 0,
    signal: NodeJS.Signals | null = null
  ): void {
    if (this.exitCode !== null || this.signalCode !== null) {
      return;
    }
    this.exitCode = code;
    this.signalCode = signal;
    this.emit("exit", code, signal);
  }
}

const expectedHandshake = (
  connection: SidecarConnection,
  overrides: Partial<HandshakeResponse> = {}
): HandshakeResponse => ({
  service: "local-context-forge",
  role: "python-sidecar",
  app_version: "0.3.0-alpha.1",
  sidecar_version: "0.3.0-alpha.1",
  protocol: { major: 1, minor: 0 },
  launch_id: connection.launchId,
  transport: "uds",
  schema_version: 3,
  capabilities: ["desktop-handshake", "health", "library-api"],
  ...overrides
});

function supervisorOptions() {
  return {
    executablePath: "/opt/lcf/lcf-service",
    dataDir: "/private/data",
    appVersion: "0.3.0-alpha.1",
    sidecarVersion: "0.3.0-alpha.1",
    schemaVersion: 3,
    requiredCapabilities: [
      "desktop-handshake",
      "health",
      "library-api"
    ] as const,
    startupTimeoutMs: 500,
    pollIntervalMs: 10,
    shutdownTimeoutMs: 10
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("SidecarSupervisor", () => {
  it("writes one unique framed token to fd3, keeps liveness open, and hides it from argv/env", async () => {
    const children: FakeChild[] = [];
    const spawnCalls: Array<{
      args: readonly string[];
      options: SpawnOptions;
    }> = [];
    const tokens: string[] = [];
    const cleanups: string[] = [];
    let uuidIndex = 0;
    const uuids = [
      "00000000-0000-4000-8000-000000000001",
      "00000000-0000-4000-8000-000000000002"
    ];
    const supervisor = new SidecarSupervisor(supervisorOptions(), {
      validateExecutable: async () => undefined,
      randomUUID: () => uuids[uuidIndex++]!,
      randomBytes: () => Buffer.alloc(32, uuidIndex),
      createRuntime: async (launchId) => ({
        directory: `/tmp/${launchId}`,
        socketPath: `/tmp/${launchId}/py.sock`
      }),
      inspectSocket: async () => "valid",
      handshake: async (connection) => {
        tokens.push(connection.token);
        return expectedHandshake(connection);
      },
      spawn: (_executable, args, options) => {
        const child = new FakeChild();
        children.push(child);
        spawnCalls.push({ args, options });
        return child as never;
      },
      cleanupRuntime: async (runtime) => {
        cleanups.push(runtime.directory);
      },
      wait: async () => undefined,
      now: () => 0
    });

    const firstTokenBytes: Buffer[] = [];
    const start = supervisor.start();
    await vi.waitFor(() => expect(children).toHaveLength(1));
    children[0]!.controlPipe.on("data", (chunk) =>
      firstTokenBytes.push(Buffer.from(chunk))
    );
    await expect(start).resolves.toEqual({
      state: "ready",
      canRetry: false
    });
    await new Promise((resolve) => setImmediate(resolve));

    const framedToken = Buffer.concat(firstTokenBytes).toString("utf8");
    expect(framedToken).toMatch(/^[A-Za-z0-9_-]{43}\n$/);
    expect(children[0]!.controlPipe.writableEnded).toBe(false);
    expect(spawnCalls[0]?.options).toMatchObject({
      shell: false,
      stdio: ["ignore", "ignore", "ignore", "pipe"]
    });
    expect(spawnCalls[0]?.args).toEqual([
      "api",
      "--uds",
      "/tmp/00000000-0000-4000-8000-000000000001/py.sock",
      "--launch-id",
      "00000000-0000-4000-8000-000000000001",
      "--token-fd",
      "3",
      "--data-dir",
      "/private/data"
    ]);
    expect(JSON.stringify(spawnCalls[0])).not.toContain(tokens[0]);

    children[0]!.exitNow(1);
    await vi.waitFor(() =>
      expect(supervisor.getStatus()).toMatchObject({
        state: "failed",
        canRetry: true,
        reason: "sidecar-exited"
      })
    );
    await expect(supervisor.retry()).resolves.toMatchObject({ state: "ready" });
    expect(tokens).toHaveLength(2);
    expect(tokens[1]).not.toBe(tokens[0]);
    expect(cleanups).toContain(
      "/tmp/00000000-0000-4000-8000-000000000001"
    );
    await supervisor.shutdown();
  });

  it("fails closed on handshake launch/version/capability mismatch and cleans up", async () => {
    const child = new FakeChild();
    const cleanups: RuntimePaths[] = [];
    const supervisor = new SidecarSupervisor(supervisorOptions(), {
      validateExecutable: async () => undefined,
      randomUUID: () => "00000000-0000-4000-8000-000000000001",
      randomBytes: () => Buffer.alloc(32, 1),
      createRuntime: async () => ({
        directory: "/tmp/runtime",
        socketPath: "/tmp/runtime/py.sock"
      }),
      inspectSocket: async () => "valid",
      handshake: async (connection) =>
        expectedHandshake(connection, {
          launch_id: "00000000-0000-4000-8000-000000000099",
          sidecar_version: "9.9.9",
          capabilities: []
        }),
      spawn: () => child as never,
      cleanupRuntime: async (runtime) => {
        cleanups.push(runtime);
      },
      wait: async () => undefined,
      now: () => 0
    });

    await expect(supervisor.start()).resolves.toEqual({
      state: "failed",
      canRetry: true,
      reason: "handshake-rejected"
    });
    expect(child.signals).toContain("SIGTERM");
    expect(child.controlPipe.writableEnded).toBe(true);
    expect(cleanups).toHaveLength(1);
    expect(supervisor.getConnection()).toBeUndefined();
  });

  it("treats exit before readiness as failed and cleans only that launch", async () => {
    const child = new FakeChild();
    const cleanups: string[] = [];
    const supervisor = new SidecarSupervisor(supervisorOptions(), {
      validateExecutable: async () => undefined,
      randomUUID: () => "00000000-0000-4000-8000-000000000001",
      randomBytes: () => Buffer.alloc(32, 1),
      createRuntime: async () => ({
        directory: "/tmp/early-exit",
        socketPath: "/tmp/early-exit/py.sock"
      }),
      spawn: () => child as never,
      inspectSocket: async () => {
        child.exitNow(1);
        return "missing";
      },
      cleanupRuntime: async (runtime) => {
        cleanups.push(runtime.directory);
      },
      wait: async () => undefined,
      now: () => 0
    });

    await expect(supervisor.start()).resolves.toEqual({
      state: "failed",
      canRetry: true,
      reason: "sidecar-exited"
    });
    expect(cleanups).toEqual(["/tmp/early-exit"]);
    expect(supervisor.getConnection()).toBeUndefined();
  });

  it("confirms an async spawn error with no PID, then cleans and allows retry", async () => {
    const child = new FakeChild(false, null);
    const cleanups: string[] = [];
    let emitted = false;
    const supervisor = new SidecarSupervisor(supervisorOptions(), {
      validateExecutable: async () => undefined,
      randomUUID: () => "00000000-0000-4000-8000-000000000001",
      randomBytes: () => Buffer.alloc(32, 1),
      createRuntime: async () => ({
        directory: "/tmp/no-child",
        socketPath: "/tmp/no-child/py.sock"
      }),
      spawn: () => child as never,
      inspectSocket: async () => {
        if (!emitted) {
          emitted = true;
          queueMicrotask(() =>
            child.emit(
              "error",
              new Error("spawn failed at /private/path with secret")
            )
          );
        }
        return "missing";
      },
      cleanupRuntime: async (runtime) => {
        cleanups.push(runtime.directory);
      },
      wait: async () => {
        await Promise.resolve();
      },
      now: () => 0
    });

    await expect(supervisor.start()).resolves.toEqual({
      state: "failed",
      canRetry: true,
      reason: "launch-failed"
    });
    expect(cleanups).toEqual(["/tmp/no-child"]);
    expect(JSON.stringify(supervisor.getStatus())).not.toContain(
      "/private/path"
    );
  });

  it("handles fd3 EPIPE without an uncaught error and retains PID authority", async () => {
    const child = new FakeChild(false);
    const cleanups: string[] = [];
    const supervisor = new SidecarSupervisor(supervisorOptions(), {
      validateExecutable: async () => undefined,
      randomUUID: () => "00000000-0000-4000-8000-000000000001",
      randomBytes: () => Buffer.alloc(32, 1),
      createRuntime: async () => ({
        directory: "/tmp/fd3-error",
        socketPath: "/tmp/fd3-error/py.sock"
      }),
      spawn: () => child as never,
      inspectSocket: async () => "valid",
      handshake: async (connection) => expectedHandshake(connection),
      cleanupRuntime: async (runtime) => {
        cleanups.push(runtime.directory);
      },
      wait: async () => undefined,
      now: () => 0
    });
    await supervisor.start();
    expect(child.controlPipe.listenerCount("error")).toBeGreaterThan(0);

    expect(() =>
      child.controlPipe.emit(
        "error",
        new Error("EPIPE token=/secret socket=/private/socket")
      )
    ).not.toThrow();
    expect(supervisor.getStatus()).toEqual({
      state: "failed",
      canRetry: false,
      reason: "launch-failed"
    });
    await expect(supervisor.retry()).resolves.toMatchObject({
      canRetry: false
    });
    expect(cleanups).toHaveLength(0);
    expect(JSON.stringify(supervisor.getStatus())).not.toContain("EPIPE");

    child.exitNow(1);
    await vi.waitFor(() =>
      expect(supervisor.getStatus()).toEqual({
        state: "failed",
        canRetry: true,
        reason: "sidecar-exited"
      })
    );
    expect(cleanups).toEqual(["/tmp/fd3-error"]);
  });

  it("does not retry or clean runtime until an unkillable authoritative child exits", async () => {
    const child = new FakeChild(false);
    const cleanups: string[] = [];
    let spawnCount = 0;
    const supervisor = new SidecarSupervisor(supervisorOptions(), {
      validateExecutable: async () => undefined,
      randomUUID: () => "00000000-0000-4000-8000-000000000001",
      randomBytes: () => Buffer.alloc(32, 1),
      createRuntime: async () => ({
        directory: "/tmp/runtime",
        socketPath: "/tmp/runtime/py.sock"
      }),
      inspectSocket: async () => "valid",
      handshake: async (connection) => expectedHandshake(connection),
      spawn: () => {
        spawnCount += 1;
        return child as never;
      },
      cleanupRuntime: async (runtime) => {
        cleanups.push(runtime.directory);
      },
      wait: async () => undefined,
      now: () => 0
    });
    await supervisor.start();

    await expect(supervisor.shutdown()).resolves.toEqual({
      state: "failed",
      canRetry: false,
      reason: "shutdown-timeout"
    });
    expect(cleanups).toHaveLength(0);
    await expect(supervisor.retry()).resolves.toMatchObject({
      state: "failed",
      canRetry: false
    });
    expect(spawnCount).toBe(1);

    child.exitNow(null, "SIGKILL");
    await vi.waitFor(() =>
      expect(supervisor.getStatus()).toEqual({
        state: "failed",
        canRetry: true,
        reason: "sidecar-exited"
      })
    );
    expect(cleanups).toEqual(["/tmp/runtime"]);
  });

  it("does not report stopped while a pre-session child remains unconfirmed", async () => {
    const child = new FakeChild(false);
    Object.defineProperty(child, "stdio", {
      value: [null, null, null, null]
    });
    const cleanups: string[] = [];
    const supervisor = new SidecarSupervisor(supervisorOptions(), {
      validateExecutable: async () => undefined,
      randomUUID: () => "00000000-0000-4000-8000-000000000001",
      randomBytes: () => Buffer.alloc(32, 1),
      createRuntime: async () => ({
        directory: "/tmp/unconfirmed",
        socketPath: "/tmp/unconfirmed/py.sock"
      }),
      spawn: () => child as never,
      cleanupRuntime: async (runtime) => {
        cleanups.push(runtime.directory);
      },
      wait: async () => undefined
    });

    await expect(supervisor.start()).resolves.toEqual({
      state: "failed",
      canRetry: false,
      reason: "shutdown-timeout"
    });
    await expect(supervisor.shutdown()).resolves.toEqual({
      state: "failed",
      canRetry: false,
      reason: "shutdown-timeout"
    });
    expect(cleanups).toHaveLength(0);

    child.exitNow(null, "SIGKILL");
    await vi.waitFor(() => expect(cleanups).toEqual(["/tmp/unconfirmed"]));
  });

  it("cleans a runtime created before spawn throws", async () => {
    const cleanups: string[] = [];
    const supervisor = new SidecarSupervisor(supervisorOptions(), {
      validateExecutable: async () => undefined,
      randomUUID: () => "00000000-0000-4000-8000-000000000001",
      randomBytes: () => Buffer.alloc(32, 1),
      createRuntime: async () => ({
        directory: "/tmp/runtime-before-spawn",
        socketPath: "/tmp/runtime-before-spawn/py.sock"
      }),
      spawn: () => {
        throw new Error("spawn failed with sensitive path");
      },
      cleanupRuntime: async (runtime) => {
        cleanups.push(runtime.directory);
      }
    });
    await expect(supervisor.start()).resolves.toMatchObject({
      state: "failed",
      canRetry: true,
      reason: "launch-failed"
    });
    expect(cleanups).toEqual(["/tmp/runtime-before-spawn"]);
  });
});

describe("sidecar primitives", () => {
  it("requires socket type, owner, non-symlink metadata and exact 0600 mode", () => {
    const metadata = (
      overrides: Partial<{
        socket: boolean;
        symlink: boolean;
        uid: number;
        mode: number;
      }> = {}
    ) => ({
      isSocket: () => overrides.socket ?? true,
      isSymbolicLink: () => overrides.symlink ?? false,
      uid: overrides.uid ?? 501,
      mode: overrides.mode ?? 0o140600
    });
    expect(hasPrivateSocketMetadata(metadata(), 501)).toBe(true);
    expect(hasPrivateSocketMetadata(metadata({ socket: false }), 501)).toBe(
      false
    );
    expect(hasPrivateSocketMetadata(metadata({ symlink: true }), 501)).toBe(
      false
    );
    expect(hasPrivateSocketMetadata(metadata({ uid: 502 }), 501)).toBe(false);
    expect(hasPrivateSocketMetadata(metadata({ mode: 0o140644 }), 501)).toBe(
      false
    );
  });

  it("passes only the explicit non-secret environment allowlist", () => {
    expect(
      buildSidecarEnvironment({
        HOME: "/Users/example",
        LANG: "en_US.UTF-8",
        PATH: "/attacker/bin",
        LCF_TOKEN: "secret",
        PYTHONPATH: "/injected",
        GITHUB_TOKEN: "secret"
      })
    ).toEqual({
      HOME: "/Users/example",
      LANG: "en_US.UTF-8"
    });
  });

  it("enforces runtime modes and socket owner/type/mode, then cleans only its runtime", async () => {
    const tempRoot = await mkdtemp(path.join(os.tmpdir(), "lcf-runtime-test-"));
    const launchId = "00000000-0000-4000-8000-000000000001";
    const runtime = await createPrivateRuntime(launchId, tempRoot);
    try {
      expect(Buffer.byteLength(runtime.socketPath, "utf8")).toBeLessThanOrEqual(
        100
      );
      expect((await lstat(runtime.directory)).mode & 0o777).toBe(0o700);

      const server = net.createServer();
      const outcomePromise = Promise.race([
        once(server, "listening").then(() => "listening" as const),
        once(server, "error").then(
          ([error]) => error as NodeJS.ErrnoException
        )
      ]);
      let outcome: "listening" | NodeJS.ErrnoException;
      try {
        server.listen(runtime.socketPath);
        outcome = await outcomePromise;
      } catch (error) {
        outcome = error as NodeJS.ErrnoException;
      }
      if (outcome === "listening") {
        await chmod(runtime.socketPath, 0o600);
        await expect(inspectPrivateSocket(runtime.socketPath)).resolves.toBe(
          "valid"
        );
        await chmod(runtime.socketPath, 0o644);
        await expect(inspectPrivateSocket(runtime.socketPath)).rejects.toThrow(
          /runtime-invalid/
        );
        server.close();
        await once(server, "close");
      } else {
        if (process.env.CI === "true") {
          throw outcome;
        }
        expect(outcome.code).toBe("EPERM");
      }
    } finally {
      await chmod(runtime.directory, 0o700);
      await cleanupPrivateRuntime(runtime);
      await rm(tempRoot, { recursive: true, force: true });
    }
  });

  it("rejects a symlink temp root", async () => {
    const realRoot = await mkdtemp(path.join(os.tmpdir(), "lcf-real-root-"));
    const linkRoot = `${realRoot}-link`;
    await symlink(realRoot, linkRoot, "dir");
    try {
      await expect(
        createPrivateRuntime(
          "00000000-0000-4000-8000-000000000001",
          linkRoot
        )
      ).rejects.toThrow(/runtime-invalid/);
    } finally {
      await rm(linkRoot, { force: true });
      await rm(realRoot, { recursive: true, force: true });
    }
  });

  it("gives handshake an absolute deadline even if no bytes arrive", async () => {
    vi.useFakeTimers();
    const request = new EventEmitter() as ClientRequest & EventEmitter;
    Object.assign(request, {
      setTimeout: vi.fn(() => request),
      destroy: vi.fn(() => request),
      end: vi.fn(() => request)
    });
    const connection: SidecarConnection = {
      socketPath: "/tmp/runtime/py.sock",
      launchId: "00000000-0000-4000-8000-000000000001",
      token: "A".repeat(43)
    };
    const promise = requestHandshake(connection, 100, {
      request: (
        _options: RequestOptions,
        _callback: (response: IncomingMessage) => void
      ) => request
    });
    const rejection = expect(promise).rejects.toThrow(/launch-failed/);
    await vi.advanceTimersByTimeAsync(100);
    await rejection;
    expect(request.destroy).toHaveBeenCalled();
  });
});

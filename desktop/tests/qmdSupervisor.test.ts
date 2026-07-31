import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import type { SpawnOptions } from "node:child_process";
import { describe, expect, it, vi } from "vitest";
import {
  QmdSupervisor,
  resolveQmdRuntimeConfiguration
} from "../src/main/qmdSupervisor";
import type { QmdClient } from "../src/main/qmdClient";

class FakeChild extends EventEmitter {
  readonly pid = 101;
  exitCode: number | null = null;
  signalCode: NodeJS.Signals | null = null;
  readonly controlPipe = new PassThrough();
  readonly stdio = [null, null, null, this.controlPipe] as const;
  readonly signals: Array<NodeJS.Signals | number | undefined> = [];
  readonly tokenBytes: Buffer[] = [];

  constructor() {
    super();
    this.controlPipe.on("data", (chunk) =>
      this.tokenBytes.push(Buffer.from(chunk))
    );
  }

  kill(signal?: NodeJS.Signals | number): boolean {
    this.signals.push(signal);
    this.exitNow(null, typeof signal === "string" ? signal : null);
    return true;
  }

  exitNow(
    code: number | null = 0,
    signal: NodeJS.Signals | null = null
  ): void {
    this.exitCode = code;
    this.signalCode = signal;
    this.emit("exit", code, signal);
  }
}

function options() {
  return {
    runtime: {
      nodeExecutable: "/opt/lcf/node",
      workerEntry: "/opt/lcf/qmd/index.mjs",
      buildManifestSha256: "b".repeat(64)
    },
    appDataDir: "/private/data",
    dataDir: "/private/data/qmd/worker",
    wikiRoot: "/private/data/wiki",
    startupTimeoutMs: 500,
    pollIntervalMs: 10,
    shutdownTimeoutMs: 10
  };
}

describe("QmdSupervisor", () => {
  it("passes the unique QMD token only through fd3 and keeps liveness open", async () => {
    const child = new FakeChild();
    const spawnCalls: Array<{
      executable: string;
      args: readonly string[];
      options: SpawnOptions;
    }> = [];
    const client = {
      health: vi.fn(async () => ({
        role: "qmd-worker"
      }))
    };
    const supervisor = new QmdSupervisor(options(), {
      validateRuntime: async () => undefined,
      prepareDataPaths: async () => undefined,
      randomUUID: () => "01234567-89ab-4cde-8fab-0123456789ab",
      randomBytes: () => Buffer.alloc(32, 7),
      createRuntime: async () => ({
        directory: "/tmp/qmd-runtime",
        socketPath: "/tmp/qmd-runtime/qmd.sock"
      }),
      inspectSocket: async () => "valid",
      cleanupRuntime: async () => undefined,
      createClient: () => client as unknown as QmdClient,
      spawn: (executable, args, spawnOptions) => {
        spawnCalls.push({ executable, args, options: spawnOptions });
        return child;
      },
      wait: async () => undefined,
      now: () => 0
    });

    await expect(supervisor.start()).resolves.toEqual({
      state: "ready",
      canRetry: false
    });
    await new Promise((resolve) => setImmediate(resolve));
    const token = Buffer.concat(child.tokenBytes).toString("utf8");
    expect(token).toMatch(/^[A-Za-z0-9_-]{43}\n$/);
    expect(child.controlPipe.writableEnded).toBe(false);
    expect(spawnCalls[0]).toMatchObject({
      executable: "/opt/lcf/node",
      options: {
        shell: false,
        stdio: ["ignore", "ignore", "ignore", "pipe"]
      }
    });
    expect(spawnCalls[0]!.args).toEqual([
      "/opt/lcf/qmd/index.mjs",
      "--uds",
      "/tmp/qmd-runtime/qmd.sock",
      "--launch-id",
      "01234567-89ab-4cde-8fab-0123456789ab",
      "--token-fd",
      "3",
      "--wiki-root",
      "/private/data/wiki",
      "--data-dir",
      "/private/data/qmd/worker",
      "--build-manifest-sha256",
      "b".repeat(64)
    ]);
    expect(JSON.stringify(spawnCalls)).not.toContain(token.trim());
    await supervisor.shutdown();
  });

  it("requires all three explicit source runtime inputs", async () => {
    await expect(
      resolveQmdRuntimeConfiguration({
        packaged: false,
        resourcesPath: "/resources",
        environment: {
          LCF_QMD_NODE_BIN: "/opt/lcf/node",
          LCF_QMD_WORKER_ENTRY: "/opt/lcf/qmd/index.mjs"
        }
      })
    ).rejects.toThrow(/configuration/);

    await expect(
      resolveQmdRuntimeConfiguration({
        packaged: false,
        resourcesPath: "/resources",
        environment: {
          LCF_QMD_NODE_BIN: "/opt/lcf/node",
          LCF_QMD_WORKER_ENTRY: "/opt/lcf/qmd/index.mjs",
          LCF_QMD_BUILD_MANIFEST_SHA256: "c".repeat(64)
        }
      })
    ).resolves.toEqual({
      nodeExecutable: "/opt/lcf/node",
      workerEntry: "/opt/lcf/qmd/index.mjs",
      buildManifestSha256: "c".repeat(64)
    });
  });
});

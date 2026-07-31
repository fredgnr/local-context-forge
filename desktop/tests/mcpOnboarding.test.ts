import { chmod, mkdir, mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CodexInstallation } from "../src/main/providers/contracts";
import type { BoundedProcessResult } from "../src/main/providers/processRunner";
import {
  MCP_SERVER_NAME,
  McpOnboardingService,
  resolveBundledCompanionTarget,
  type BundledCompanionTarget,
  type McpOnboardingDependencies
} from "../src/main/mcpOnboarding";

const executablePath = "/verified/codex";
const target: BundledCompanionTarget = {
  nodeExecutable:
    "/Applications/Local Context Forge.app/Contents/Resources/qmd/node/bin/node",
  companionEntry:
    "/Applications/Local Context Forge.app/Contents/Resources/companion/index.mjs"
};
const installation: CodexInstallation = {
  provider: "codex_cli",
  installationKind: "npm",
  packageVersion: "0.146.0",
  packageRoot: "/verified/package",
  managedPackageRoot: "/verified/package",
  wrapperPath: "/verified/package/bin/codex.js",
  executable: {
    canonicalPath: executablePath,
    sha256: "a".repeat(64),
    size: 1,
    mtimeMs: 1,
    device: 1,
    inode: 1,
    mode: 0o100755
  },
  auxiliaryExecutables: []
};

function commandResult(
  overrides: Partial<BoundedProcessResult> = {}
): BoundedProcessResult {
  return {
    exitCode: 0,
    signal: null,
    stdout: "",
    stderr: "",
    cancelled: false,
    timedOut: false,
    outputLimitExceeded: false,
    ...overrides
  };
}

function config(
  command = target.nodeExecutable,
  arguments_ = [target.companionEntry],
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    name: MCP_SERVER_NAME,
    enabled: true,
    disabled_reason: null,
    transport: {
      type: "stdio",
      command,
      args: arguments_,
      env: null,
      env_vars: [],
      cwd: null
    },
    startup_timeout_sec: null,
    tool_timeout_sec: null,
    auth_status: "unsupported",
    ...overrides
  };
}

function listResult(entries: readonly unknown[]): BoundedProcessResult {
  return commandResult({ stdout: JSON.stringify(entries) });
}

function readyDependencies(
  results: BoundedProcessResult[]
): {
  dependencies: McpOnboardingDependencies;
  revalidateCodex: ReturnType<typeof vi.fn>;
  run: ReturnType<typeof vi.fn>;
} {
  const run = vi.fn(async () => {
    const next = results.shift();
    if (!next) {
      throw new Error("Unexpected process invocation");
    }
    return next;
  });
  const revalidateCodex = vi.fn(async () => undefined);
  return {
    dependencies: {
      resolver: {
        codex: async () => ({
          installation,
          preflight: {
            provider: "codex_cli",
            state: "ready",
            version: "0.146.0"
          }
        })
      },
      runner: { run },
      environment: {},
      packaged: true,
      isInApplicationsFolder: () => true,
      resourcesPath:
        "/Applications/Local Context Forge.app/Contents/Resources",
      resolveTarget: async () => target,
      revalidateCodex
    },
    revalidateCodex,
    run
  };
}

describe("Codex MCP onboarding", () => {
  it("registers with fixed argv, preserves spaces, and verifies via list JSON", async () => {
    const { dependencies, revalidateCodex, run } = readyDependencies([
      listResult([]),
      commandResult(),
      listResult([config()])
    ]);
    const service = new McpOnboardingService(dependencies);

    await expect(service.configure()).resolves.toMatchObject({
      configurationState: "configured",
      canConfigure: false,
      canClear: true,
      restartRequired: true
    });
    expect(run.mock.calls.map((call) => call[1])).toEqual([
      ["mcp", "list", "--json"],
      [
        "mcp",
        "add",
        MCP_SERVER_NAME,
        "--",
        target.nodeExecutable,
        target.companionEntry
      ],
      ["mcp", "list", "--json"]
    ]);
    expect(run.mock.calls[1]?.[0]).toBe(executablePath);
    expect(revalidateCodex).toHaveBeenCalledTimes(3);
    expect(
      revalidateCodex.mock.calls.every(
        (call) => call[0] === installation
      )
    ).toBe(true);
    expect(run.mock.calls[1]?.[2]).toMatchObject({
      timeoutMs: 10_000,
      outputLimitBytes: 64 * 1024,
      environment: {
        PATH: "/usr/bin:/bin:/usr/sbin:/sbin",
        CODEX_MANAGED_PACKAGE_ROOT: "/verified/package",
        CODEX_MANAGED_BY_NPM: "1"
      }
    });
  });

  it("uses add as an atomic replacement for an owned path after the app moves", async () => {
    const oldRoot =
      "/Users/person/Applications/Local Context Forge.app/Contents/Resources";
    const { dependencies, run } = readyDependencies([
      listResult([
        config(
          path.join(oldRoot, "qmd", "node", "bin", "node"),
          [path.join(oldRoot, "companion", "index.mjs")]
        )
      ]),
      commandResult(),
      listResult([config()])
    ]);
    const service = new McpOnboardingService(dependencies);

    await expect(service.configure()).resolves.toMatchObject({
      configurationState: "configured",
      restartRequired: true
    });
    expect(run.mock.calls.map((call) => call[1][1])).toEqual([
      "list",
      "add",
      "list"
    ]);
    expect(
      run.mock.calls.some((call) => call[1][1] === "remove")
    ).toBe(false);
  });

  it("never overwrites or clears an arbitrary same-name server", async () => {
    const { dependencies, run } = readyDependencies([
      listResult([config("/usr/bin/node", ["/tmp/custom.mjs"])]),
      listResult([config("/usr/bin/node", ["/tmp/custom.mjs"])])
    ]);
    const service = new McpOnboardingService(dependencies);

    await expect(service.configure()).rejects.toMatchObject({
      code: "name-conflict"
    });
    await expect(service.clear()).rejects.toMatchObject({
      code: "name-conflict"
    });
    expect(run).toHaveBeenCalledTimes(2);
    expect(
      run.mock.calls.some(
        (call) => call[1][1] === "add" || call[1][1] === "remove"
      )
    ).toBe(false);
  });

  it("clears only an owned entry and verifies that it is absent", async () => {
    const { dependencies, run } = readyDependencies([
      listResult([config()]),
      commandResult(),
      listResult([])
    ]);
    const service = new McpOnboardingService(dependencies);

    await expect(service.clear()).resolves.toMatchObject({
      configurationState: "not-configured",
      canClear: false,
      restartRequired: true
    });
    expect(run.mock.calls.map((call) => call[1])).toEqual([
      ["mcp", "list", "--json"],
      ["mcp", "remove", MCP_SERVER_NAME],
      ["mcp", "list", "--json"]
    ]);
  });

  it("leaves the owned entry recoverable when replacement or removal fails", async () => {
    const staleRoot =
      "/Applications/Archive/Local Context Forge.app/Contents/Resources";
    const stale = config(
      path.join(staleRoot, "qmd", "node", "bin", "node"),
      [path.join(staleRoot, "companion", "index.mjs")]
    );
    const addSetup = readyDependencies([
      listResult([stale]),
      commandResult({ exitCode: 2, stderr: "private failure" })
    ]);
    const addService = new McpOnboardingService(addSetup.dependencies);
    await expect(addService.configure()).rejects.toMatchObject({
      code: "unavailable"
    });
    expect(addSetup.run.mock.calls.map((call) => call[1][1])).toEqual([
      "list",
      "add"
    ]);

    const clearSetup = readyDependencies([
      listResult([config()]),
      commandResult({ exitCode: 2, stderr: "private failure" })
    ]);
    const clearService = new McpOnboardingService(clearSetup.dependencies);
    await expect(clearService.clear()).rejects.toMatchObject({
      code: "unavailable"
    });
    expect(clearSetup.run.mock.calls.map((call) => call[1][1])).toEqual([
      "list",
      "remove"
    ]);
  });

  it("blocks packaged apps outside Applications without resolving bundle paths", async () => {
    const { dependencies, run } = readyDependencies([
      listResult([]),
      listResult([])
    ]);
    const resolveTarget = vi.fn(async () => target);
    const service = new McpOnboardingService({
      ...dependencies,
      isInApplicationsFolder: () => false,
      resolveTarget
    });

    await expect(service.status()).resolves.toMatchObject({
      installState: "move-to-applications",
      canConfigure: false
    });
    await expect(service.configure()).rejects.toMatchObject({
      code: "move-to-applications"
    });
    expect(resolveTarget).not.toHaveBeenCalled();
    expect(run.mock.calls.every((call) => call[1][1] === "list")).toBe(true);
  });

  it("reports missing and logged-out Codex without attempting registration", async () => {
    const missingRun = vi.fn();
    const missing = new McpOnboardingService({
      ...readyDependencies([]).dependencies,
      resolver: {
        codex: async () => ({
          preflight: { provider: "codex_cli", state: "not_installed" }
        })
      },
      runner: { run: missingRun }
    });
    await expect(missing.status()).resolves.toMatchObject({
      codexState: "not-installed",
      configurationState: "unknown",
      canConfigure: false
    });
    expect(missingRun).not.toHaveBeenCalled();

    const loggedOutSetup = readyDependencies([listResult([])]);
    const loggedOut = new McpOnboardingService({
      ...loggedOutSetup.dependencies,
      resolver: {
        codex: async () => ({
          installation,
          preflight: {
            provider: "codex_cli",
            state: "not_authenticated",
            version: "0.146.0"
          }
        })
      }
    });
    await expect(loggedOut.configure()).rejects.toMatchObject({
      code: "not-authenticated"
    });
    expect(loggedOutSetup.run.mock.calls.every(
      (call) => call[1][1] === "list"
    )).toBe(true);
  });

  it("fails closed on malformed list output, timeout, and custom execution fields", async () => {
    for (const result of [
      commandResult({ stdout: "not-json" }),
      commandResult({ timedOut: true, exitCode: null }),
      listResult([
        config(target.nodeExecutable, [target.companionEntry], {
          startup_timeout_sec: 12
        })
      ])
    ]) {
      const { dependencies } = readyDependencies([result]);
      const service = new McpOnboardingService(dependencies);
      await expect(service.status()).rejects.toMatchObject({
        code:
          result.timedOut
            ? "timeout"
            : "invalid-response"
      });
    }
  });

  it("serializes operations and aborts an active command during shutdown", async () => {
    let finish:
      | ((result: BoundedProcessResult) => void)
      | undefined;
    const run = vi.fn(
      async (
        _executable: string,
        _arguments: readonly string[],
        options: { signal?: AbortSignal }
      ) =>
        await new Promise<BoundedProcessResult>((resolve) => {
          finish = resolve;
          options.signal?.addEventListener(
            "abort",
            () => resolve(commandResult({ cancelled: true, exitCode: null })),
            { once: true }
          );
        })
    );
    const service = new McpOnboardingService({
      ...readyDependencies([]).dependencies,
      runner: { run }
    });
    const pending = service.status();
    await vi.waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    await expect(service.configure()).rejects.toMatchObject({ code: "busy" });
    await service.shutdown();
    await expect(pending).rejects.toMatchObject({ code: "unavailable" });
    expect(finish).toBeTypeOf("function");
  });
});

const temporaryRoots: string[] = [];

afterEach(async () => {
  await Promise.all(
    temporaryRoots.splice(0).map((root) =>
      rm(root, { recursive: true, force: true })
    )
  );
});

describe("bundled companion target validation", () => {
  async function bundledRoot(): Promise<string> {
    const root = await mkdtemp(path.join(os.tmpdir(), "lcf mcp target "));
    temporaryRoots.push(root);
    await mkdir(path.join(root, "qmd", "node", "bin"), { recursive: true });
    await mkdir(path.join(root, "companion"), { recursive: true });
    const node = path.join(root, "qmd", "node", "bin", "node");
    const companion = path.join(root, "companion", "index.mjs");
    await writeFile(node, "#!/bin/sh\nexit 0\n", { mode: 0o755 });
    await writeFile(companion, "process.exit(0);\\n", { mode: 0o644 });
    await chmod(node, 0o755);
    await chmod(companion, 0o644);
    return root;
  }

  it("accepts regular, non-writable files under a resources path with spaces", async () => {
    const root = await bundledRoot();
    await expect(resolveBundledCompanionTarget(root)).resolves.toEqual({
      nodeExecutable: path.join(root, "qmd", "node", "bin", "node"),
      companionEntry: path.join(root, "companion", "index.mjs")
    });
  });

  it("rejects a symlinked companion or group-writable runtime", async () => {
    const symlinkRoot = await bundledRoot();
    const companion = path.join(symlinkRoot, "companion", "index.mjs");
    const outside = path.join(symlinkRoot, "outside.mjs");
    await writeFile(outside, "process.exit(0);\\n", { mode: 0o644 });
    await rm(companion);
    await symlink(outside, companion);
    await expect(
      resolveBundledCompanionTarget(symlinkRoot)
    ).rejects.toThrow();

    const writableRoot = await bundledRoot();
    await chmod(
      path.join(writableRoot, "qmd", "node", "bin", "node"),
      0o775
    );
    await expect(
      resolveBundledCompanionTarget(writableRoot)
    ).rejects.toThrow();
  });
});

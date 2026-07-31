import {
  chmod,
  lstat,
  mkdir,
  mkdtemp,
  realpath,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import type { Stats } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CodexInstallation } from "../src/main/providers/contracts";
import type { BoundedProcessResult } from "../src/main/providers/processRunner";
import {
  MCP_SERVER_NAME,
  McpOnboardingService,
  resolveCodexOwnershipScope,
  resolveBundledCompanionTarget,
  type BundledCompanionTarget,
  type McpOnboardingDependencies
} from "../src/main/mcpOnboarding";
import {
  MCP_TARGET_OWNER_ENV,
  sameMcpTargetOwnership,
  type McpOwnedTarget,
  type McpTargetOwnership,
  type McpTargetOwnershipStore
} from "../src/main/mcpTargetOwnership";

const executablePath = "/verified/codex";
const ownerMarker = `lcf-mcp-v1-${"a".repeat(64)}`;
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

function ownedTarget(
  bundled: BundledCompanionTarget
): McpOwnedTarget {
  return {
    command: bundled.nodeExecutable,
    arguments_: [bundled.companionEntry]
  };
}

class MemoryOwnershipStore implements McpTargetOwnershipStore {
  readonly stageCalls: Array<readonly McpOwnedTarget[]> = [];
  readonly removeCalls: McpTargetOwnership[] = [];
  invalid = false;

  constructor(
    public state: McpTargetOwnership | undefined = undefined
  ) {}

  async read(): Promise<McpTargetOwnership | undefined> {
    if (this.invalid) {
      throw new TypeError("invalid ownership fixture");
    }
    return this.state;
  }

  async stage(
    expected: McpTargetOwnership | undefined,
    targets: readonly McpOwnedTarget[]
  ): Promise<McpTargetOwnership> {
    if (
      this.invalid ||
      !sameMcpTargetOwnership(this.state, expected)
    ) {
      throw new TypeError("ownership fixture changed");
    }
    this.stageCalls.push(targets);
    this.state = {
      marker: this.state?.marker ?? ownerMarker,
      targets: targets.map((entry) => ({
        command: entry.command,
        arguments_: [entry.arguments_[0]]
      }))
    };
    return this.state;
  }

  async remove(expected: McpTargetOwnership): Promise<void> {
    if (
      this.invalid ||
      !sameMcpTargetOwnership(this.state, expected)
    ) {
      throw new TypeError("ownership fixture changed");
    }
    this.removeCalls.push(expected);
    this.state = undefined;
  }
}

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
  overrides: Record<string, unknown> = {},
  marker: string | null = ownerMarker
): Record<string, unknown> {
  return {
    name: MCP_SERVER_NAME,
    enabled: true,
    disabled_reason: null,
    transport: {
      type: "stdio",
      command,
      args: arguments_,
      env:
        marker === null
          ? null
          : { [MCP_TARGET_OWNER_ENV]: marker },
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
  results: BoundedProcessResult[],
  ownedTargets: readonly McpOwnedTarget[] = []
): {
  dependencies: McpOnboardingDependencies;
  ownershipStore: MemoryOwnershipStore;
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
  const ownershipStore = new MemoryOwnershipStore(
    ownedTargets.length > 0
      ? { marker: ownerMarker, targets: ownedTargets }
      : undefined
  );
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
      environment: { HOME: "/Users/test" },
      packaged: true,
      isInApplicationsFolder: () => true,
      dataDirectory: "/private/app-support",
      resourcesPath:
        "/Applications/Local Context Forge.app/Contents/Resources",
      ownershipStore,
      resolveTarget: async () => target,
      revalidateCodex
    },
    ownershipStore,
    revalidateCodex,
    run
  };
}

describe("Codex MCP onboarding", () => {
  it("hashes one validated scope for default and explicit default CODEX_HOME", () => {
    const defaultScope = resolveCodexOwnershipScope({
      HOME: "/Users/test"
    });
    const explicitDefaultScope = resolveCodexOwnershipScope({
      HOME: "/Users/test",
      CODEX_HOME: "/Users/test/.codex"
    });
    const customScope = resolveCodexOwnershipScope({
      HOME: "/Users/test",
      CODEX_HOME: "/private/codex-home"
    });
    expect(defaultScope).toMatch(/^[0-9a-f]{64}$/);
    expect(defaultScope).toBe(explicitDefaultScope);
    expect(customScope).toMatch(/^[0-9a-f]{64}$/);
    expect(customScope).not.toBe(defaultScope);
    expect(defaultScope).not.toContain("/Users/test");
    expect(
      resolveCodexOwnershipScope({
        HOME: "/Users/test",
        CODEX_HOME: "relative/codex-home"
      })
    ).toBeUndefined();
    expect(
      resolveCodexOwnershipScope({ HOME: "/Users/test/../other" })
    ).toBeUndefined();
  });

  it("registers with fixed argv, preserves spaces, and verifies via list JSON", async () => {
    const { dependencies, revalidateCodex, run } = readyDependencies([
      listResult([]),
      listResult([]),
      commandResult(),
      listResult([config()])
    ]);
    const service = new McpOnboardingService(dependencies);

    const status = await service.configure();
    expect(status).toMatchObject({
      configurationState: "configured",
      canConfigure: false,
      canClear: true,
      restartRequired: true
    });
    const serializedStatus = JSON.stringify(status);
    expect(serializedStatus).not.toContain(ownerMarker);
    expect(serializedStatus).not.toContain(target.nodeExecutable);
    expect(serializedStatus).not.toContain(target.companionEntry);
    expect(serializedStatus).not.toContain(MCP_TARGET_OWNER_ENV);
    expect(run.mock.calls.map((call) => call[1])).toEqual([
      ["mcp", "list", "--json"],
      ["mcp", "list", "--json"],
      [
        "mcp",
        "add",
        MCP_SERVER_NAME,
        "--env",
        `${MCP_TARGET_OWNER_ENV}=${ownerMarker}`,
        "--",
        target.nodeExecutable,
        target.companionEntry
      ],
      ["mcp", "list", "--json"]
    ]);
    expect(run.mock.calls[1]?.[0]).toBe(executablePath);
    expect(revalidateCodex).toHaveBeenCalledTimes(4);
    expect(
      revalidateCodex.mock.calls.every(
        (call) => call[0] === installation
      )
    ).toBe(true);
    expect(run.mock.calls[1]?.[2]).toMatchObject({
      timeoutMs: 10_000,
      outputLimitBytes: 64 * 1024,
      cwd: "/private/app-support",
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
    const oldTarget: McpOwnedTarget = {
      command: path.join(oldRoot, "qmd", "node", "bin", "node"),
      arguments_: [path.join(oldRoot, "companion", "index.mjs")]
    };
    const { dependencies, run } = readyDependencies(
      [
        listResult([
          config(oldTarget.command, [...oldTarget.arguments_])
        ]),
        listResult([
          config(oldTarget.command, [...oldTarget.arguments_])
        ]),
        commandResult(),
        listResult([config()])
      ],
      [oldTarget]
    );
    const service = new McpOnboardingService(dependencies);

    await expect(service.configure()).resolves.toMatchObject({
      configurationState: "configured",
      restartRequired: true
    });
    expect(run.mock.calls.map((call) => call[1][1])).toEqual([
      "list",
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

  it("does not claim a legacy or lookalike target from its path shape", async () => {
    const legacy = config(
      target.nodeExecutable,
      [target.companionEntry],
      {},
      null
    );
    const { dependencies, run } = readyDependencies(
      [listResult([legacy]), listResult([legacy])],
      [ownedTarget(target)]
    );
    const service = new McpOnboardingService(dependencies);

    await expect(service.configure()).rejects.toMatchObject({
      code: "name-conflict"
    });
    await expect(service.clear()).rejects.toMatchObject({
      code: "name-conflict"
    });
    expect(run.mock.calls.map((call) => call[1])).toEqual([
      ["mcp", "list", "--json"],
      ["mcp", "list", "--json"]
    ]);
  });

  it("fails closed when ownership state is missing, damaged, or marker-mismatched", async () => {
    const missing = readyDependencies([listResult([config()])]);
    const damaged = readyDependencies(
      [listResult([config()])],
      [ownedTarget(target)]
    );
    damaged.ownershipStore.invalid = true;
    const mismatched = readyDependencies(
      [
        listResult([
          config(
            target.nodeExecutable,
            [target.companionEntry],
            {},
            `lcf-mcp-v1-${"b".repeat(64)}`
          )
        ])
      ],
      [ownedTarget(target)]
    );

    for (const setup of [missing, damaged, mismatched]) {
      const service = new McpOnboardingService(setup.dependencies);
      await expect(service.configure()).rejects.toMatchObject({
        code: "name-conflict"
      });
      expect(
        setup.run.mock.calls.some(
          (call) =>
            call[1][1] === "add" || call[1][1] === "remove"
        )
      ).toBe(false);
    }
  });

  it("does not ignore prototype-named or other extra target environment", async () => {
    const environment = Object.create(null) as Record<string, string>;
    environment[MCP_TARGET_OWNER_ENV] = ownerMarker;
    environment.__proto__ = "must-remain-visible";
    const entry = config();
    const transport = entry.transport as Record<string, unknown>;
    transport.env = environment;
    const { dependencies, run } = readyDependencies(
      [listResult([entry])],
      [ownedTarget(target)]
    );
    const service = new McpOnboardingService(dependencies);

    await expect(service.configure()).rejects.toMatchObject({
      code: "name-conflict"
    });
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("rechecks target ownership immediately before add or remove", async () => {
    const thirdParty = config(
      "/usr/bin/node",
      ["/tmp/custom.mjs"],
      {},
      null
    );
    const configureSetup = readyDependencies([
      listResult([]),
      listResult([thirdParty])
    ]);
    const configureService = new McpOnboardingService(
      configureSetup.dependencies
    );
    await expect(configureService.configure()).rejects.toMatchObject({
      code: "name-conflict"
    });
    expect(
      configureSetup.run.mock.calls.some(
        (call) => call[1][1] === "add"
      )
    ).toBe(false);

    const clearSetup = readyDependencies(
      [listResult([config()]), listResult([thirdParty])],
      [ownedTarget(target)]
    );
    const clearService = new McpOnboardingService(
      clearSetup.dependencies
    );
    await expect(clearService.clear()).rejects.toMatchObject({
      code: "name-conflict"
    });
    expect(
      clearSetup.run.mock.calls.some(
        (call) => call[1][1] === "remove"
      )
    ).toBe(false);
  });

  it("clears only an owned entry and verifies that it is absent", async () => {
    const { dependencies, ownershipStore, run } = readyDependencies(
      [
        listResult([config()]),
        listResult([config()]),
        commandResult(),
        listResult([])
      ],
      [ownedTarget(target)]
    );
    const service = new McpOnboardingService(dependencies);

    await expect(service.clear()).resolves.toMatchObject({
      configurationState: "not-configured",
      canClear: false,
      restartRequired: true
    });
    expect(run.mock.calls.map((call) => call[1])).toEqual([
      ["mcp", "list", "--json"],
      ["mcp", "list", "--json"],
      ["mcp", "remove", MCP_SERVER_NAME],
      ["mcp", "list", "--json"]
    ]);
    expect(ownershipStore.state).toBeUndefined();
  });

  it("leaves the owned entry recoverable when replacement or removal fails", async () => {
    const staleRoot =
      "/Applications/Archive/Local Context Forge.app/Contents/Resources";
    const stale = config(
      path.join(staleRoot, "qmd", "node", "bin", "node"),
      [path.join(staleRoot, "companion", "index.mjs")]
    );
    const staleTarget: McpOwnedTarget = {
      command: path.join(staleRoot, "qmd", "node", "bin", "node"),
      arguments_: [path.join(staleRoot, "companion", "index.mjs")]
    };
    const addSetup = readyDependencies(
      [
        listResult([stale]),
        listResult([stale]),
        commandResult({ exitCode: 2, stderr: "private failure" }),
        listResult([stale]),
        listResult([stale]),
        listResult([stale]),
        commandResult(),
        listResult([config()])
      ],
      [staleTarget]
    );
    const addService = new McpOnboardingService(addSetup.dependencies);
    await expect(addService.configure()).rejects.toMatchObject({
      code: "unavailable"
    });
    expect(addSetup.run.mock.calls.map((call) => call[1][1])).toEqual([
      "list",
      "list",
      "add"
    ]);
    expect(addSetup.ownershipStore.state?.targets).toEqual([
      staleTarget,
      ownedTarget(target)
    ]);
    await expect(addService.status()).resolves.toMatchObject({
      configurationState: "needs-reconnect",
      canConfigure: true
    });
    await expect(addService.configure()).resolves.toMatchObject({
      configurationState: "configured"
    });
    expect(addSetup.ownershipStore.state?.targets).toEqual([
      ownedTarget(target)
    ]);
    expect(addSetup.run.mock.calls.map((call) => call[1][1])).toEqual([
      "list",
      "list",
      "add",
      "list",
      "list",
      "list",
      "add",
      "list"
    ]);

    const clearSetup = readyDependencies(
      [
        listResult([config()]),
        listResult([config()]),
        commandResult({ exitCode: 2, stderr: "private failure" })
      ],
      [ownedTarget(target)]
    );
    const clearService = new McpOnboardingService(clearSetup.dependencies);
    await expect(clearService.clear()).rejects.toMatchObject({
      code: "unavailable"
    });
    expect(clearSetup.run.mock.calls.map((call) => call[1][1])).toEqual([
      "list",
      "list",
      "remove"
    ]);
  });

  it("self-heals a post-add crash window without rerunning Codex add", async () => {
    const oldRoot =
      "/Users/person/Applications/Local Context Forge.app/Contents/Resources";
    const oldTarget: McpOwnedTarget = {
      command: path.join(oldRoot, "qmd", "node", "bin", "node"),
      arguments_: [path.join(oldRoot, "companion", "index.mjs")]
    };
    const { dependencies, ownershipStore, run } = readyDependencies(
      [listResult([config()])],
      [oldTarget, ownedTarget(target)]
    );
    const service = new McpOnboardingService(dependencies);

    await expect(service.status()).resolves.toMatchObject({
      configurationState: "configured",
      canConfigure: false
    });
    expect(ownershipStore.state?.targets).toEqual([
      ownedTarget(target)
    ]);
    expect(run.mock.calls.map((call) => call[1])).toEqual([
      ["mcp", "list", "--json"]
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

  it("does not mutate an owned target from source/debug mode", async () => {
    const { dependencies, run } = readyDependencies(
      [listResult([config()]), listResult([config()])],
      [ownedTarget(target)]
    );
    const resolveTarget = vi.fn(async () => target);
    const service = new McpOnboardingService({
      ...dependencies,
      packaged: false,
      resolveTarget
    });

    await expect(service.status()).resolves.toMatchObject({
      installState: "source-debug",
      configurationState: "needs-reconnect",
      canConfigure: false,
      canClear: false
    });
    await expect(service.clear()).rejects.toMatchObject({
      code: "source-debug"
    });
    expect(resolveTarget).not.toHaveBeenCalled();
    expect(run.mock.calls.map((call) => call[1])).toEqual([
      ["mcp", "list", "--json"],
      ["mcp", "list", "--json"]
    ]);
  });

  it("fails closed on an invalid Codex configuration scope", async () => {
    const setup = readyDependencies([], [ownedTarget(target)]);
    const service = new McpOnboardingService({
      ...setup.dependencies,
      environment: {
        HOME: "/Users/test",
        CODEX_HOME: "../untrusted"
      }
    });

    await expect(service.status()).resolves.toMatchObject({
      codexState: "unavailable",
      configurationState: "unknown",
      canConfigure: false,
      canClear: false
    });
    await expect(service.configure()).rejects.toMatchObject({
      code: "unavailable"
    });
    expect(setup.run).not.toHaveBeenCalled();
    expect(setup.ownershipStore.state?.targets).toEqual([
      ownedTarget(target)
    ]);
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
    const setup = readyDependencies([], [ownedTarget(target)]);
    const persistedBeforeShutdown = setup.ownershipStore.state;
    const service = new McpOnboardingService({
      ...setup.dependencies,
      runner: { run }
    });
    const pending = service.status();
    await vi.waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    await expect(service.configure()).rejects.toMatchObject({ code: "busy" });
    await service.shutdown();
    await expect(pending).rejects.toMatchObject({ code: "unavailable" });
    expect(finish).toBeTypeOf("function");
    expect(setup.ownershipStore.state).toEqual(
      persistedBeforeShutdown
    );
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
    const fixtureRoot = await realpath(
      await mkdtemp(path.join(os.tmpdir(), "lcf mcp target "))
    );
    temporaryRoots.push(fixtureRoot);
    const root = path.join(
      fixtureRoot,
      "Local Context Forge.app",
      "Contents",
      "Resources"
    );
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

  function metadataOverride(
    info: Stats,
    overrides: { readonly mode?: number; readonly uid?: number }
  ): Stats {
    return new Proxy(info, {
      get(targetInfo, property) {
        if (property === "mode" && overrides.mode !== undefined) {
          return overrides.mode;
        }
        if (property === "uid" && overrides.uid !== undefined) {
          return overrides.uid;
        }
        const value = Reflect.get(targetInfo, property, targetInfo);
        return typeof value === "function"
          ? value.bind(targetInfo)
          : value;
      }
    });
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

  it("rejects group/world-writable directories throughout the bundle chain", async () => {
    for (const relative of [
      ["qmd", "node"],
      ["companion"],
      []
    ]) {
      const root = await bundledRoot();
      await chmod(path.join(root, ...relative), 0o777);
      await expect(
        resolveBundledCompanionTarget(root)
      ).rejects.toThrow();
    }

    const root = await bundledRoot();
    await chmod(path.dirname(path.dirname(root)), 0o775);
    await expect(
      resolveBundledCompanionTarget(root)
    ).rejects.toThrow();
  });

  it("rejects setuid, setgid, or sticky bundle components", async () => {
    for (const [relative, mode] of [
      [["qmd", "node", "bin", "node"], 0o4755],
      [["companion", "index.mjs"], 0o2644],
      [["qmd", "node"], 0o1755]
    ] as const) {
      const root = await bundledRoot();
      await chmod(path.join(root, ...relative), mode);
      await expect(
        resolveBundledCompanionTarget(root)
      ).rejects.toThrow();
    }
  });

  it("rejects wrong-owner bundled files and intermediate directories", async () => {
    const effectiveUid = 41_000;
    const wrongUid = 41_001;
    for (const rejectedPath of [
      ["qmd", "node", "bin", "node"],
      ["companion"]
    ]) {
      const root = await bundledRoot();
      const rejected = path.join(root, ...rejectedPath);
      await expect(
        resolveBundledCompanionTarget(root, {
          effectiveUid,
          lstat: async (candidate) =>
            metadataOverride(await lstat(candidate), {
              uid: candidate === rejected ? wrongUid : effectiveUid
            })
        })
      ).rejects.toThrow();
    }
  });

  it("accepts root-owned or current-user-owned bundle components", async () => {
    const root = await bundledRoot();
    const currentUid = 42_000;
    await expect(
      resolveBundledCompanionTarget(root, {
        effectiveUid: currentUid,
        lstat: async (candidate) =>
          metadataOverride(await lstat(candidate), {
            uid: candidate.includes(`${path.sep}companion${path.sep}`)
              ? currentUid
              : 0
          })
      })
    ).resolves.toEqual({
      nodeExecutable: path.join(root, "qmd", "node", "bin", "node"),
      companionEntry: path.join(root, "companion", "index.mjs")
    });
  });

  it("rejects a non-canonical resources root", async () => {
    const root = await bundledRoot();
    const fixtureRoot = path.dirname(
      path.dirname(path.dirname(root))
    );
    const aliasRoot = path.join(fixtureRoot, "alias");
    await mkdir(aliasRoot);
    const linkedBundle = path.join(
      aliasRoot,
      "Local Context Forge.app"
    );
    await symlink(path.dirname(path.dirname(root)), linkedBundle);
    await expect(
      resolveBundledCompanionTarget(
        path.join(linkedBundle, "Contents", "Resources")
      )
    ).rejects.toThrow();
  });
});

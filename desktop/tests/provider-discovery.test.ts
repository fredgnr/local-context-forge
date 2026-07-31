import {
  chmod,
  mkdir,
  mkdtemp,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  discoverCodexInstallation,
  discoverCursorInstallation,
  findCommandCandidates,
  findCommandOnPath,
  revalidateExecutableIdentity
} from "../src/main/providers/discovery";
import { ProviderResolver } from "../src/main/providers/providerResolver";
import {
  preflightCodex,
  preflightCursor,
  type BoundedCommandResult,
  type ProviderPreflightRunner
} from "../src/main/providers/preflight";

const temporaryDirectories: string[] = [];

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) =>
      rm(directory, { recursive: true, force: true })
    )
  );
});

async function createCodexFixture(): Promise<{
  commandPath: string;
  nativePath: string;
}> {
  const prefix = await mkdtemp(path.join(os.tmpdir(), "lcf-codex-"));
  temporaryDirectories.push(prefix);
  const packageRoot = path.join(
    prefix,
    "lib",
    "node_modules",
    "@openai",
    "codex"
  );
  const wrapperPath = path.join(packageRoot, "bin", "codex.js");
  const platformRoot = path.join(
    packageRoot,
    "node_modules",
    "@openai",
    "codex-darwin-arm64"
  );
  const nativePath = path.join(
    platformRoot,
    "vendor",
    "aarch64-apple-darwin",
    "bin",
    "codex"
  );
  const commandPath = path.join(prefix, "bin", "codex");
  await mkdir(path.dirname(wrapperPath), { recursive: true });
  await mkdir(path.dirname(nativePath), { recursive: true });
  await mkdir(path.dirname(commandPath), { recursive: true });
  await writeFile(wrapperPath, "#!/usr/bin/env node\n", { mode: 0o755 });
  await writeFile(
    path.join(packageRoot, "package.json"),
    JSON.stringify({
      name: "@openai/codex",
      version: "0.146.0",
      repository: {
        type: "git",
        url: "git+https://github.com/openai/codex.git",
        directory: "codex-cli"
      },
      optionalDependencies: {
        "@openai/codex-darwin-arm64":
          "npm:@openai/codex@0.146.0-darwin-arm64"
      }
    })
  );
  await writeFile(
    path.join(platformRoot, "package.json"),
    JSON.stringify({
      name: "@openai/codex",
      version: "0.146.0-darwin-arm64",
      os: ["darwin"],
      cpu: ["arm64"],
      repository: {
        type: "git",
        url: "git+https://github.com/openai/codex.git",
        directory: "codex-cli"
      }
    })
  );
  await writeFile(nativePath, "native-codex-fixture\n", { mode: 0o755 });
  await symlink(wrapperPath, commandPath);
  return { commandPath, nativePath };
}

class QueueRunner implements ProviderPreflightRunner {
  readonly calls: Array<{
    executablePath: string;
    arguments_: readonly string[];
    environment: NodeJS.ProcessEnv;
  }> = [];

  constructor(private readonly results: BoundedCommandResult[]) {}

  async run(
    executablePath: string,
    arguments_: readonly string[],
    options: {
      environment: NodeJS.ProcessEnv;
      timeoutMs: number;
      outputLimitBytes: number;
    }
  ): Promise<BoundedCommandResult> {
    this.calls.push({
      executablePath,
      arguments_,
      environment: options.environment
    });
    const result = this.results.shift();
    if (!result) {
      throw new Error("Unexpected command");
    }
    return result;
  }
}

describe("provider discovery", () => {
  it("resolves the official npm wrapper to a pinned native arm64 identity", async () => {
    const fixture = await createCodexFixture();
    const installation = await discoverCodexInstallation(fixture.commandPath);
    expect(installation).toMatchObject({
      provider: "codex_cli",
      packageVersion: "0.146.0",
      wrapperPath: expect.stringMatching(/codex\/bin\/codex\.js$/),
      executable: {
        canonicalPath: fixture.nativePath,
        sha256: expect.stringMatching(/^[a-f0-9]{64}$/)
      }
    });
    await expect(
      revalidateExecutableIdentity(installation.executable)
    ).resolves.toBeUndefined();
  });

  it("rejects metadata spoofing and executable identity drift", async () => {
    const fixture = await createCodexFixture();
    const installation = await discoverCodexInstallation(fixture.commandPath);
    await writeFile(fixture.nativePath, "changed\n", { mode: 0o755 });
    await expect(
      revalidateExecutableIdentity(installation.executable)
    ).rejects.toThrow(/identity changed/);

    const packageJson = path.join(
      path.dirname(path.dirname(installation.wrapperPath)),
      "package.json"
    );
    await writeFile(
      packageJson,
      JSON.stringify({
        name: "@openai/codex-fake",
        version: "0.146.0"
      })
    );
    await expect(
      discoverCodexInstallation(fixture.commandPath)
    ).rejects.toThrow(/official package/);
  });

  it("rejects writable provider executables", async () => {
    const prefix = await mkdtemp(path.join(os.tmpdir(), "lcf-cursor-"));
    temporaryDirectories.push(prefix);
    const commandPath = path.join(prefix, "cursor-agent");
    await writeFile(commandPath, "cursor\n", { mode: 0o777 });
    await chmod(commandPath, 0o777);
    await expect(discoverCursorInstallation(commandPath)).rejects.toThrow(
      /group- or world-writable/
    );
  });

  it("finds commands without invoking a shell and checks Cursor's documented path", async () => {
    const prefix = await mkdtemp(path.join(os.tmpdir(), "lcf-path-"));
    temporaryDirectories.push(prefix);
    const bin = path.join(prefix, "bin");
    const cursorBin = path.join(prefix, ".local", "bin");
    await mkdir(bin, { recursive: true });
    await mkdir(cursorBin, { recursive: true });
    await writeFile(path.join(bin, "codex"), "", { mode: 0o755 });
    await writeFile(path.join(cursorBin, "cursor-agent"), "", { mode: 0o755 });
    await expect(
      findCommandOnPath("codex", {
        PATH: `relative${path.delimiter}${bin}`
      })
    ).resolves.toBe(path.join(bin, "codex"));
    await expect(
      findCommandOnPath("cursor-agent", {
        PATH: "",
        HOME: prefix
      })
    ).resolves.toBe(path.join(cursorBin, "cursor-agent"));
  });

  it("discovers version-manager installs when a Finder launch has no shell PATH", async () => {
    const home = "/Users/example";
    const nvmRoot = path.join(home, ".nvm", "versions", "node");
    const expected = path.join(
      nvmRoot,
      "v22.17.0",
      "bin",
      "codex"
    );
    const candidates = await findCommandCandidates(
      "codex",
      { PATH: "/usr/bin:/bin", HOME: home },
      {
        readDirectory: async (directory) =>
          directory === nvmRoot
            ? ["../escape", "v22.17.0", "too many spaces"]
            : [],
        access: async (candidate) => {
          if (candidate !== expected) {
            throw new Error("missing");
          }
        }
      }
    );
    expect(candidates).toEqual([expected]);
  });

  it("skips a PATH spoof and selects the next official Codex package", async () => {
    const invalid = await mkdtemp(path.join(os.tmpdir(), "lcf-spoof-"));
    temporaryDirectories.push(invalid);
    await mkdir(path.join(invalid, "bin"), { recursive: true });
    await writeFile(path.join(invalid, "bin", "codex"), "spoof", {
      mode: 0o755
    });
    const fixture = await createCodexFixture();
    const runner = new QueueRunner([
      { exitCode: 0, stdout: "codex-cli 0.146.0\n", stderr: "" },
      { exitCode: 0, stdout: "Logged in using ChatGPT\n", stderr: "" }
    ]);
    const resolver = new ProviderResolver(runner, {
      PATH: `${path.join(invalid, "bin")}${path.delimiter}${path.dirname(fixture.commandPath)}`
    });
    await expect(resolver.codex()).resolves.toMatchObject({
      preflight: { provider: "codex_cli", state: "ready" },
      installation: {
        executable: { canonicalPath: fixture.nativePath }
      }
    });
  });
});

describe("provider preflight", () => {
  it("requires Codex package and native versions to match before auth status", async () => {
    const fixture = await createCodexFixture();
    const installation = await discoverCodexInstallation(fixture.commandPath);
    const ready = new QueueRunner([
      { exitCode: 0, stdout: "codex-cli 0.146.0\n", stderr: "" },
      { exitCode: 0, stdout: "Logged in using ChatGPT\n", stderr: "" }
    ]);
    await expect(
      preflightCodex(installation, ready, {
        HOME: "/Users/test",
        CODEX_HOME: "/Users/test/.codex",
        OPENAI_API_KEY: "must-not-pass"
      })
    ).resolves.toEqual({
      provider: "codex_cli",
      state: "ready",
      version: "0.146.0"
    });
    expect(ready.calls.map((call) => call.arguments_)).toEqual([
      ["--version"],
      ["login", "status"]
    ]);
    expect(ready.calls[0]?.environment).not.toHaveProperty("OPENAI_API_KEY");

    const mismatch = new QueueRunner([
      { exitCode: 0, stdout: "codex-cli 0.145.0\n", stderr: "" }
    ]);
    await expect(
      preflightCodex(installation, mismatch, {})
    ).resolves.toEqual({
      provider: "codex_cli",
      state: "unsupported_installation"
    });
  });

  it("distinguishes saved-login absence from preflight unavailability", async () => {
    const fixture = await createCodexFixture();
    const installation = await discoverCodexInstallation(fixture.commandPath);
    const loggedOut = new QueueRunner([
      { exitCode: 0, stdout: "codex-cli 0.146.0\n", stderr: "" },
      { exitCode: 1, stdout: "Not logged in\n", stderr: "" }
    ]);
    await expect(
      preflightCodex(installation, loggedOut, {})
    ).resolves.toMatchObject({
      provider: "codex_cli",
      state: "not_authenticated"
    });

    const timeout = new QueueRunner([
      {
        exitCode: null,
        stdout: "",
        stderr: "",
        timedOut: true
      }
    ]);
    await expect(preflightCodex(installation, timeout, {})).resolves.toEqual({
      provider: "codex_cli",
      state: "unavailable"
    });
  });

  it("uses Cursor's documented version and status commands without API keys", async () => {
    const prefix = await mkdtemp(path.join(os.tmpdir(), "lcf-cursor-"));
    temporaryDirectories.push(prefix);
    const commandPath = path.join(prefix, "cursor-agent");
    await writeFile(commandPath, "cursor\n", { mode: 0o755 });
    const installation = await discoverCursorInstallation(commandPath);
    const runner = new QueueRunner([
      { exitCode: 0, stdout: "2026.07.31-a1b2c3\n", stderr: "" },
      { exitCode: 0, stdout: "Authenticated\n", stderr: "" }
    ]);
    await expect(
      preflightCursor(installation, runner, {
        HOME: "/Users/test",
        CURSOR_API_KEY: "must-not-pass"
      })
    ).resolves.toEqual({
      provider: "cursor_cli",
      state: "ready",
      version: "2026.07.31-a1b2c3"
    });
    expect(runner.calls.map((call) => call.arguments_)).toEqual([
      ["--version"],
      ["status"]
    ]);
    expect(runner.calls[0]?.environment).not.toHaveProperty("CURSOR_API_KEY");
  });
});

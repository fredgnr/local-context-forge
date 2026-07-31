import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { discoverCursorInstallation } from "../src/main/providers/discovery";
import { executeCommittedProviderAttempt } from "../src/main/providers/execution";
import { BoundedProcessRunner } from "../src/main/providers/processRunner";
import type {
  CursorInstallation,
  ProviderExecutionCommitReceipt
} from "../src/main/providers/contracts";

const temporaryDirectories: string[] = [];

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) =>
      rm(directory, { recursive: true, force: true })
    )
  );
});

describe("BoundedProcessRunner", () => {
  it("uses stdin, a fixed environment, and captures bounded output", async () => {
    const runner = new BoundedProcessRunner();
    const result = await runner.run(
      process.execPath,
      [
        "-e",
        "process.stdin.setEncoding('utf8');let s='';process.stdin.on('data',c=>s+=c);process.stdin.on('end',()=>process.stdout.write(`${process.env.LCF_TEST}:${s}`))"
      ],
      {
        environment: { LCF_TEST: "fixed" },
        timeoutMs: 5_000,
        outputLimitBytes: 1_024,
        input: "private prompt"
      }
    );
    expect(result).toMatchObject({
      exitCode: 0,
      stdout: "fixed:private prompt",
      stderr: "",
      timedOut: false,
      outputLimitExceeded: false,
      cancelled: false
    });
  });

  it("terminates a process group on timeout", async () => {
    const signals: NodeJS.Signals[] = [];
    const runner = new BoundedProcessRunner({
      killGraceMs: 25,
      killProcessGroup: (child, signal) => {
        signals.push(signal);
        child.kill(signal);
      }
    });
    const result = await runner.run(
      process.execPath,
      ["-e", "setInterval(()=>{},1000)"],
      {
        environment: {},
        timeoutMs: 100,
        outputLimitBytes: 1_024
      }
    );
    expect(result.timedOut).toBe(true);
    expect(signals).toContain("SIGTERM");
  });

  it("terminates instead of returning partial output after the cap", async () => {
    const runner = new BoundedProcessRunner({ killGraceMs: 25 });
    const result = await runner.run(
      process.execPath,
      ["-e", "process.stdout.write('x'.repeat(4096));setInterval(()=>{},1000)"],
      {
        environment: {},
        timeoutMs: 5_000,
        outputLimitBytes: 128
      }
    );
    expect(result.outputLimitExceeded).toBe(true);
    expect(Buffer.byteLength(result.stdout)).toBe(128);
  });

  it("returns cancellation without spawning when already aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    const runner = new BoundedProcessRunner();
    await expect(
      runner.run(process.execPath, ["--version"], {
        environment: {},
        timeoutMs: 5_000,
        outputLimitBytes: 1_024,
        signal: controller.signal
      })
    ).resolves.toMatchObject({
      exitCode: null,
      cancelled: true
    });
  });
});

describe("committed provider execution", () => {
  async function cursorFixture() {
    const directory = await mkdtemp(path.join(os.tmpdir(), "lcf-exec-"));
    temporaryDirectories.push(directory);
    const executable = path.join(directory, "cursor-agent");
    await writeFile(
      executable,
      "#!/bin/sh\nprintf '{\"type\":\"result\",\"result\":\"ok\"}\\n'\n",
      { mode: 0o755 }
    );
    await chmod(executable, 0o755);
    return {
      directory,
      executable,
      installation: await discoverCursorInstallation(executable)
    };
  }

  function receipt(
    installation: CursorInstallation
  ): ProviderExecutionCommitReceipt {
    return {
      attemptId: "attempt-1",
      claimId: "claim-1",
      selectedProvider: "cursor_cli",
      executableSha256: installation.executable.sha256,
      executionCommittedAt: "2026-07-31T12:00:00Z"
    };
  }

  it("requires a disposable Cursor workspace", async () => {
    const fixture = await cursorFixture();
    await expect(
      executeCommittedProviderAttempt({
        installation: fixture.installation,
        commitReceipt: receipt(fixture.installation),
        sourceEnvironment: {},
        cwd: fixture.directory,
        prompt: "Analyze without writing",
        timeoutMs: 5_000,
        outputLimitBytes: 1_024
      })
    ).rejects.toThrow(/disposable workspace/);
  });

  it("rejects a commit receipt for another executable", async () => {
    const fixture = await cursorFixture();
    await expect(
      executeCommittedProviderAttempt({
        installation: fixture.installation,
        commitReceipt: {
          ...receipt(fixture.installation),
          executableSha256: "0".repeat(64)
        },
        sourceEnvironment: {},
        cwd: fixture.directory,
        prompt: "Analyze",
        timeoutMs: 5_000,
        outputLimitBytes: 1_024,
        cursorWorkspaceIsDisposable: true
      })
    ).rejects.toThrow(/commit receipt/);
  });

  it("runs once with the fixed Cursor argv after identity revalidation", async () => {
    const fixture = await cursorFixture();
    await expect(
      executeCommittedProviderAttempt({
        installation: fixture.installation,
        commitReceipt: receipt(fixture.installation),
        sourceEnvironment: {},
        cwd: fixture.directory,
        prompt: "Analyze without writing",
        timeoutMs: 5_000,
        outputLimitBytes: 1_024,
        cursorWorkspaceIsDisposable: true
      })
    ).resolves.toEqual({
      ok: true,
      provider: "cursor_cli",
      stdout: "{\"type\":\"result\",\"result\":\"ok\"}\n"
    });
  });

  it("fails before spawn if the pinned executable changes", async () => {
    const fixture = await cursorFixture();
    await writeFile(fixture.executable, "#!/bin/sh\nexit 0\n", {
      mode: 0o755
    });
    await expect(
      executeCommittedProviderAttempt({
        installation: fixture.installation,
        commitReceipt: receipt(fixture.installation),
        sourceEnvironment: {},
        cwd: fixture.directory,
        prompt: "Analyze",
        timeoutMs: 5_000,
        outputLimitBytes: 1_024,
        cursorWorkspaceIsDisposable: true
      })
    ).resolves.toEqual({
      ok: false,
      provider: "cursor_cli",
      failure: "identity-changed"
    });
  });
});

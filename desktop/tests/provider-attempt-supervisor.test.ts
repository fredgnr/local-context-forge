import { createHash } from "node:crypto";
import {
  chmod,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SidecarConnection } from "../src/main/apiProxy";
import {
  createDisposableCursorWorkspace,
  inspectProviderOutput,
  verifyClaimedAttemptFiles,
  writeCursorOutput
} from "../src/main/providers/attemptFiles";
import type {
  CodexInstallation,
  CursorInstallation,
  ProviderExecutionCommitReceipt
} from "../src/main/providers/contracts";
import { discoverCursorInstallation } from "../src/main/providers/discovery";
import type { ClaimedProviderAttempt } from "../src/main/providers/providerAttemptClient";
import {
  ProviderAttemptSupervisor,
  type ProviderAttemptGateway,
  type ProviderResolutionSource
} from "../src/main/providers/providerAttemptSupervisor";

const temporaryDirectories: string[] = [];
const connection: SidecarConnection = {
  socketPath: "/private/lcf/py.sock",
  launchId: "00000000-0000-4000-8000-000000000001",
  token: "A".repeat(43)
};
const yieldEventLoop = async (): Promise<void> =>
  await new Promise((resolve) => setImmediate(resolve));

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) =>
      rm(directory, { recursive: true, force: true })
    )
  );
});

function digest(value: Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

async function writePrivate(filePath: string, body: Buffer): Promise<void> {
  await writeFile(filePath, body, { mode: 0o600 });
  await chmod(filePath, 0o600);
}

async function createAttemptFixture(input?: {
  consent?: boolean;
}): Promise<ClaimedProviderAttempt> {
  const data = await mkdtemp(path.join(os.tmpdir(), "lcf-attempt-data-"));
  temporaryDirectories.push(data);
  const attemptDirectory = path.join(data, "provider-attempts", "attempt-1");
  await mkdir(attemptDirectory, { recursive: true, mode: 0o700 });
  await chmod(attemptDirectory, 0o700);
  const files = {
    "evidence.json": Buffer.from('{"files":[]}\n'),
    "schema.json": Buffer.from(
      '{"type":"object","required":["pages"]}\n'
    ),
    "prompt.txt": Buffer.from(
      "Read evidence.json and return only JSON matching schema.json.\n"
    )
  };
  await Promise.all(
    Object.entries(files).map(([name, body]) =>
      writePrivate(path.join(attemptDirectory, name), body)
    )
  );
  const request = Buffer.from(
    JSON.stringify({
      schema_version: 1,
      job_id: "b".repeat(32),
      files: Object.fromEntries(
        Object.entries(files).map(([name, body]) => [
          name,
          { sha256: digest(body), size: body.length }
        ])
      )
    })
  );
  await writePrivate(path.join(attemptDirectory, "request.json"), request);
  return {
    attemptId: "a".repeat(32),
    jobId: "b".repeat(32),
    claimId: "c".repeat(32),
    policy: "codex_then_cursor",
    candidates: ["codex_cli", "cursor_cli"],
    ...(input?.consent === false
      ? {}
      : {
          cursorConsent: {
            subject: "cursor_cli_fallback",
            version: 1,
            granted: true,
            grantedAt: "2026-07-31T12:00:00Z"
          } as const
        }),
    inputSha256: digest(request),
    attemptDirectory,
    requestPath: path.join(attemptDirectory, "request.json"),
    evidencePath: path.join(attemptDirectory, "evidence.json"),
    schemaPath: path.join(attemptDirectory, "schema.json"),
    promptPath: path.join(attemptDirectory, "prompt.txt"),
    outputPath: path.join(attemptDirectory, "result.json")
  };
}

async function executableFixture(
  body: string
): Promise<CursorInstallation> {
  const directory = await mkdtemp(path.join(os.tmpdir(), "lcf-provider-bin-"));
  temporaryDirectories.push(directory);
  const executable = path.join(directory, "provider");
  await writeFile(executable, body, { mode: 0o755 });
  await chmod(executable, 0o755);
  return await discoverCursorInstallation(executable);
}

class FakeGateway implements ProviderAttemptGateway {
  readonly selected: Array<Parameters<ProviderAttemptGateway["select"]>[2]> =
    [];
  readonly failedPreflights: string[] = [];
  readonly completions: Array<
    Parameters<ProviderAttemptGateway["complete"]>[2]
  > = [];
  commitCount = 0;

  constructor(private next: ClaimedProviderAttempt | undefined) {}

  async claimNext(): Promise<ClaimedProviderAttempt | undefined> {
    const value = this.next;
    this.next = undefined;
    return value;
  }

  async select(
    _connection: SidecarConnection | undefined,
    _attempt: ClaimedProviderAttempt,
    input: Parameters<ProviderAttemptGateway["select"]>[2]
  ): Promise<void> {
    this.selected.push(input);
  }

  async failPreflight(
    _connection: SidecarConnection | undefined,
    _attempt: ClaimedProviderAttempt,
    diagnostic: Parameters<ProviderAttemptGateway["failPreflight"]>[2]
  ): Promise<void> {
    this.failedPreflights.push(diagnostic);
  }

  async commit(
    _connection: SidecarConnection | undefined,
    attempt: ClaimedProviderAttempt
  ): Promise<ProviderExecutionCommitReceipt> {
    this.commitCount += 1;
    const selected = this.selected.at(-1);
    if (!selected) {
      throw new Error("select must precede commit");
    }
    return {
      attemptId: attempt.attemptId,
      claimId: attempt.claimId,
      selectedProvider: selected.provider,
      executableSha256: selected.identity.sha256,
      executionCommittedAt: "2026-07-31T12:01:00Z"
    };
  }

  async complete(
    _connection: SidecarConnection | undefined,
    _attempt: ClaimedProviderAttempt,
    input: Parameters<ProviderAttemptGateway["complete"]>[2]
  ): Promise<void> {
    this.completions.push(input);
  }

  async cancellationRequested(): Promise<boolean> {
    return false;
  }
}

describe("provider attempt files", () => {
  it("verifies every immutable input before exposing the prompt", async () => {
    const attempt = await createAttemptFixture();
    await expect(verifyClaimedAttemptFiles(attempt)).resolves.toMatchObject({
      prompt: expect.stringContaining("return only JSON"),
      workingDirectory: attempt.attemptDirectory,
      outputPath: attempt.outputPath
    });
    await writePrivate(attempt.evidencePath, Buffer.from('{"changed":true}'));
    await expect(verifyClaimedAttemptFiles(attempt)).rejects.toThrow(
      /metadata|digest/
    );
  });

  it("copies only evidence and schema into a disposable Cursor workspace", async () => {
    const attempt = await createAttemptFixture();
    const workspace = await createDisposableCursorWorkspace(attempt);
    temporaryDirectories.push(workspace.path);
    expect(await readFile(path.join(workspace.path, "evidence.json"), "utf8")).toBe(
      '{"files":[]}\n'
    );
    expect(
      await lstat(path.join(workspace.path, "evidence.json"))
    ).toMatchObject({ mode: expect.any(Number) });
    await expect(
      lstat(path.join(workspace.path, "prompt.txt"))
    ).rejects.toMatchObject({ code: "ENOENT" });
    await workspace.cleanup();
  });

  it("normalizes Cursor's result envelope into a private output evidence file", async () => {
    const attempt = await createAttemptFixture();
    await writeCursorOutput(
      attempt.outputPath,
      JSON.stringify({
        type: "result",
        result: '{"pages":[{"path":"overview.md"}]}'
      })
    );
    await expect(inspectProviderOutput(attempt.outputPath)).resolves.toEqual({
      sha256: digest(
        Buffer.from('{"pages":[{"path":"overview.md"}]}')
      ),
      size: Buffer.byteLength('{"pages":[{"path":"overview.md"}]}')
    });
    await expect(
      writeCursorOutput(
        attempt.outputPath,
        '{"type":"message","result":"bad"}'
      )
    ).rejects.toThrow(/unsupported shape|EEXIST/);
  });
});

describe("ProviderAttemptSupervisor", () => {
  it("falls back to Cursor only before commit with current consent", async () => {
    const attempt = await createAttemptFixture();
    const cursor = await executableFixture(
      "#!/bin/sh\nprintf '%s\\n' '{\"type\":\"result\",\"result\":\"{\\\"pages\\\":[]}\"}'\n"
    );
    const resolver: ProviderResolutionSource = {
      codex: vi.fn(async () => ({
        preflight: {
          provider: "codex_cli" as const,
          state: "not_authenticated" as const,
          version: "0.146.0"
        }
      })),
      cursor: vi.fn(async () => ({
        installation: cursor,
        preflight: {
          provider: "cursor_cli" as const,
          state: "ready" as const,
          version: "2026.07.31"
        }
      }))
    };
    const gateway = new FakeGateway(attempt);
    const supervisor = new ProviderAttemptSupervisor(
      gateway,
      () => connection,
      {
        resolver,
        wait: yieldEventLoop
      }
    );
    await expect(supervisor.processNext()).resolves.toBe(true);
    expect(gateway.selected).toHaveLength(1);
    expect(gateway.selected[0]).toMatchObject({
      provider: "cursor_cli",
      fallbackReason: "codex_not_authenticated"
    });
    expect(gateway.commitCount).toBe(1);
    expect(gateway.completions).toHaveLength(1);
    expect(gateway.completions[0]).toMatchObject({ status: "succeeded" });
  });

  it("does not even preflight Cursor without current consent", async () => {
    const attempt = await createAttemptFixture({ consent: false });
    const cursor = vi.fn();
    const resolver: ProviderResolutionSource = {
      codex: vi.fn(async () => ({
        preflight: {
          provider: "codex_cli" as const,
          state: "not_authenticated" as const
        }
      })),
      cursor
    };
    const gateway = new FakeGateway(attempt);
    const supervisor = new ProviderAttemptSupervisor(
      gateway,
      () => connection,
      {
        resolver,
        wait: yieldEventLoop
      }
    );
    await supervisor.processNext();
    expect(cursor).not.toHaveBeenCalled();
    expect(gateway.failedPreflights).toEqual(["cursor-consent-required"]);
    expect(gateway.commitCount).toBe(0);
  });

  it("fails invalid attempt inputs before any provider discovery", async () => {
    const attempt = await createAttemptFixture();
    await writePrivate(attempt.promptPath, Buffer.from("tampered"));
    const resolver: ProviderResolutionSource = {
      codex: vi.fn(),
      cursor: vi.fn()
    };
    const gateway = new FakeGateway(attempt);
    const supervisor = new ProviderAttemptSupervisor(
      gateway,
      () => connection,
      {
        resolver,
        wait: yieldEventLoop
      }
    );
    await supervisor.processNext();
    expect(resolver.codex).not.toHaveBeenCalled();
    expect(resolver.cursor).not.toHaveBeenCalled();
    expect(gateway.failedPreflights).toEqual(["attempt-input-invalid"]);
    expect(gateway.commitCount).toBe(0);
  });

  it("never switches provider after a committed Codex execution fails", async () => {
    const attempt = await createAttemptFixture();
    const executable = await executableFixture("#!/bin/sh\nexit 7\n");
    const codex: CodexInstallation = {
      provider: "codex_cli",
      installationKind: "npm",
      packageVersion: "0.146.0",
      packageRoot: "/opt/codex",
      managedPackageRoot: "/opt/codex",
      wrapperPath: "/opt/codex/bin/codex.js",
      executable: executable.executable,
      auxiliaryExecutables: []
    };
    const cursor = vi.fn();
    const resolver: ProviderResolutionSource = {
      codex: vi.fn(async () => ({
        installation: codex,
        preflight: {
          provider: "codex_cli" as const,
          state: "ready" as const,
          version: "0.146.0"
        }
      })),
      cursor
    };
    const gateway = new FakeGateway(attempt);
    const supervisor = new ProviderAttemptSupervisor(
      gateway,
      () => connection,
      {
        resolver,
        wait: yieldEventLoop
      }
    );
    await supervisor.processNext();
    expect(gateway.selected[0]?.provider).toBe("codex_cli");
    expect(gateway.commitCount).toBe(1);
    expect(cursor).not.toHaveBeenCalled();
    expect(gateway.completions).toEqual([
      { status: "failed", errorCode: "non-zero-exit" }
    ]);
  });
});

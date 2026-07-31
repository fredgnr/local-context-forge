import {
  spawn as nodeSpawn,
  type ChildProcessWithoutNullStreams,
  type SpawnOptionsWithoutStdio
} from "node:child_process";
import type {
  BoundedCommandResult,
  ProviderPreflightRunner
} from "./preflight";

export interface BoundedRunOptions {
  readonly environment: NodeJS.ProcessEnv;
  readonly timeoutMs: number;
  readonly outputLimitBytes: number;
  readonly cwd?: string;
  readonly input?: string | Buffer;
  readonly inputLimitBytes?: number;
  readonly signal?: AbortSignal;
}

export interface BoundedProcessResult extends BoundedCommandResult {
  readonly signal: NodeJS.Signals | null;
  readonly outputLimitExceeded: boolean;
  readonly cancelled: boolean;
}

type SpawnProcess = (
  executablePath: string,
  arguments_: readonly string[],
  options: SpawnOptionsWithoutStdio
) => ChildProcessWithoutNullStreams;

export interface BoundedProcessRunnerDependencies {
  readonly spawn?: SpawnProcess;
  readonly killProcessGroup?: (
    child: ChildProcessWithoutNullStreams,
    signal: NodeJS.Signals
  ) => void;
  readonly killGraceMs?: number;
}

function defaultKillProcessGroup(
  child: ChildProcessWithoutNullStreams,
  signal: NodeJS.Signals
): void {
  if (process.platform !== "win32" && typeof child.pid === "number") {
    try {
      process.kill(-child.pid, signal);
      return;
    } catch {
      // Fall back to the direct child when the group has already disappeared.
    }
  }
  try {
    child.kill(signal);
  } catch {
    // Exit and error events own the final result.
  }
}

function validatedPositiveInteger(
  value: number,
  label: string,
  maximum: number
): number {
  if (!Number.isSafeInteger(value) || value < 1 || value > maximum) {
    throw new TypeError(`${label} is outside the supported range`);
  }
  return value;
}

export class BoundedProcessRunner implements ProviderPreflightRunner {
  private readonly spawn: SpawnProcess;
  private readonly killProcessGroup: NonNullable<
    BoundedProcessRunnerDependencies["killProcessGroup"]
  >;
  private readonly killGraceMs: number;

  constructor(dependencies: BoundedProcessRunnerDependencies = {}) {
    this.spawn = dependencies.spawn ?? (nodeSpawn as SpawnProcess);
    this.killProcessGroup =
      dependencies.killProcessGroup ?? defaultKillProcessGroup;
    this.killGraceMs = dependencies.killGraceMs ?? 2_000;
  }

  async run(
    executablePath: string,
    arguments_: readonly string[],
    options: BoundedRunOptions
  ): Promise<BoundedProcessResult> {
    const timeoutMs = validatedPositiveInteger(
      options.timeoutMs,
      "Process timeout",
      24 * 60 * 60 * 1_000
    );
    const outputLimitBytes = validatedPositiveInteger(
      options.outputLimitBytes,
      "Process output limit",
      64 * 1024 * 1024
    );
    const input = options.input ?? Buffer.alloc(0);
    const inputBytes = Buffer.isBuffer(input)
      ? input.length
      : Buffer.byteLength(input, "utf8");
    const inputLimitBytes = options.inputLimitBytes ?? 16 * 1024 * 1024;
    validatedPositiveInteger(
      inputLimitBytes,
      "Process input limit",
      64 * 1024 * 1024
    );
    if (inputBytes > inputLimitBytes) {
      throw new TypeError("Process input exceeds the configured limit");
    }
    if (options.signal?.aborted) {
      return {
        exitCode: null,
        signal: null,
        stdout: "",
        stderr: "",
        cancelled: true,
        timedOut: false,
        outputLimitExceeded: false
      };
    }

    return await new Promise<BoundedProcessResult>((resolve) => {
      let child: ChildProcessWithoutNullStreams;
      try {
        child = this.spawn(executablePath, [...arguments_], {
          cwd: options.cwd,
          env: options.environment,
          shell: false,
          detached: process.platform !== "win32",
          windowsHide: true,
          stdio: ["pipe", "pipe", "pipe"]
        });
      } catch (error) {
        const code =
          error && typeof error === "object" && "code" in error
            ? String(error.code)
            : "spawn";
        resolve({
          exitCode: null,
          signal: null,
          stdout: "",
          stderr: "",
          cancelled: false,
          timedOut: false,
          outputLimitExceeded: false,
          spawnErrorCode: code
        });
        return;
      }

      const stdout: Buffer[] = [];
      const stderr: Buffer[] = [];
      let capturedBytes = 0;
      let timedOut = false;
      let cancelled = false;
      let outputLimitExceeded = false;
      let spawnErrorCode: string | undefined;
      let terminating = false;
      let settled = false;
      let escalation: NodeJS.Timeout | undefined;

      const terminate = (): void => {
        if (terminating) {
          return;
        }
        terminating = true;
        this.killProcessGroup(child, "SIGTERM");
        escalation = setTimeout(() => {
          this.killProcessGroup(child, "SIGKILL");
        }, this.killGraceMs);
        escalation.unref?.();
      };

      const capture = (target: Buffer[], value: Buffer | string): void => {
        const chunk = Buffer.isBuffer(value) ? value : Buffer.from(value);
        const remaining = outputLimitBytes - capturedBytes;
        if (remaining > 0) {
          const accepted =
            chunk.length <= remaining ? chunk : chunk.subarray(0, remaining);
          target.push(Buffer.from(accepted));
          capturedBytes += accepted.length;
        }
        if (chunk.length > remaining) {
          outputLimitExceeded = true;
          terminate();
        }
      };

      child.stdout.on("data", (chunk: Buffer | string) =>
        capture(stdout, chunk)
      );
      child.stderr.on("data", (chunk: Buffer | string) =>
        capture(stderr, chunk)
      );
      child.once("error", (error: NodeJS.ErrnoException) => {
        spawnErrorCode = error.code ?? "spawn";
      });

      const timeout = setTimeout(() => {
        timedOut = true;
        terminate();
      }, timeoutMs);
      timeout.unref?.();

      const abort = (): void => {
        cancelled = true;
        terminate();
      };
      options.signal?.addEventListener("abort", abort, { once: true });

      child.once("close", (exitCode, signal) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timeout);
        if (escalation) {
          clearTimeout(escalation);
        }
        options.signal?.removeEventListener("abort", abort);
        resolve({
          exitCode,
          signal,
          stdout: Buffer.concat(stdout).toString("utf8"),
          stderr: Buffer.concat(stderr).toString("utf8"),
          cancelled,
          timedOut,
          outputLimitExceeded,
          ...(spawnErrorCode ? { spawnErrorCode } : {})
        });
      });

      child.stdin.once("error", () => {
        // EPIPE is expected when a child exits before consuming the prompt.
      });
      child.stdin.end(input);
    });
  }
}

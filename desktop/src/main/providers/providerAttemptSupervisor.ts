import type { SidecarConnection } from "../apiProxy";
import type {
  ProviderInstallation,
  ProviderPreflight
} from "./contracts";
import {
  createDisposableCursorWorkspace,
  inspectProviderOutput,
  verifyClaimedAttemptFiles,
  writeCursorOutput
} from "./attemptFiles";
import { executeCommittedProviderAttempt } from "./execution";
import {
  hasCurrentCursorConsent,
  selectProviderBeforeCommit
} from "./policy";
import {
  ProviderAttemptClient,
  ProviderAttemptClientError,
  type ClaimedProviderAttempt
} from "./providerAttemptClient";
import {
  ProviderResolver,
  type ResolvedCodex,
  type ResolvedCursor
} from "./providerResolver";
import { BoundedProcessRunner } from "./processRunner";

const EXECUTION_TIMEOUT_MS = 30 * 60 * 1_000;
const OUTPUT_LIMIT_BYTES = 16 * 1024 * 1024;

interface SelectedRuntime {
  readonly installation: ProviderInstallation;
  readonly version: string;
  readonly preflight: ProviderPreflight;
}

function selectedRuntime(
  provider: "codex_cli" | "cursor_cli",
  codex: ResolvedCodex,
  cursor?: ResolvedCursor
): SelectedRuntime {
  if (provider === "codex_cli") {
    if (
      codex.preflight.state !== "ready" ||
      !codex.preflight.version ||
      !("installation" in codex)
    ) {
      throw new TypeError("Selected provider lost its ready installation");
    }
    return {
      installation: codex.installation,
      version: codex.preflight.version,
      preflight: codex.preflight
    };
  }
  if (
    !cursor ||
    cursor.preflight.state !== "ready" ||
    !cursor.preflight.version ||
    !("installation" in cursor)
  ) {
    throw new TypeError("Selected provider lost its ready installation");
  }
  return {
    installation: cursor.installation,
    version: cursor.preflight.version,
    preflight: cursor.preflight
  };
}

export interface ProviderAttemptSupervisorDependencies {
  readonly resolver?: ProviderResolutionSource;
  readonly runner?: BoundedProcessRunner;
  readonly wait?: (milliseconds: number) => Promise<void>;
  readonly pollIntervalMs?: number;
  readonly cancellationPollIntervalMs?: number;
}

export interface ProviderResolutionSource {
  codex(): Promise<ResolvedCodex>;
  cursor(): Promise<ResolvedCursor>;
}

export interface ProviderAttemptGateway {
  claimNext(
    connection: SidecarConnection | undefined,
    leaseSeconds?: number
  ): Promise<ClaimedProviderAttempt | undefined>;
  select(
    connection: SidecarConnection | undefined,
    attempt: ClaimedProviderAttempt,
    input: {
      provider: "codex_cli" | "cursor_cli";
      identity: ProviderInstallation["executable"];
      version: string;
      fallbackReason?: "codex_not_installed" | "codex_not_authenticated";
    }
  ): Promise<void>;
  failPreflight(
    connection: SidecarConnection | undefined,
    attempt: ClaimedProviderAttempt,
    diagnostic:
      | "codex-not-installed"
      | "codex-not-authenticated"
      | "codex-installation-unsupported"
      | "codex-unavailable"
      | "cursor-consent-required"
      | "cursor-not-installed"
      | "cursor-not-authenticated"
      | "cursor-installation-unsupported"
      | "cursor-unavailable"
      | "attempt-input-invalid"
  ): Promise<void>;
  commit(
    connection: SidecarConnection | undefined,
    attempt: ClaimedProviderAttempt
  ): ReturnType<ProviderAttemptClient["commit"]>;
  complete(
    connection: SidecarConnection | undefined,
    attempt: ClaimedProviderAttempt,
    input:
      | {
          status: "succeeded";
          outputSha256: string;
          outputSize: number;
        }
      | {
          status: "failed" | "cancelled";
          errorCode: string;
        }
  ): Promise<void>;
  cancellationRequested(
    connection: SidecarConnection | undefined,
    attempt: ClaimedProviderAttempt
  ): Promise<boolean>;
}

export class ProviderAttemptSupervisor {
  private readonly resolver: ProviderResolutionSource;
  private readonly runner: BoundedProcessRunner;
  private readonly wait: (milliseconds: number) => Promise<void>;
  private readonly pollIntervalMs: number;
  private readonly cancellationPollIntervalMs: number;
  private stopping = false;
  private loop: Promise<void> | undefined;
  private executionAbort: AbortController | undefined;

  constructor(
    private readonly client: ProviderAttemptGateway,
    private readonly connection: () => SidecarConnection | undefined,
    dependencies: ProviderAttemptSupervisorDependencies = {}
  ) {
    this.runner = dependencies.runner ?? new BoundedProcessRunner();
    this.resolver =
      dependencies.resolver ?? new ProviderResolver(this.runner, process.env);
    this.wait =
      dependencies.wait ??
      ((milliseconds) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds)));
    this.pollIntervalMs = dependencies.pollIntervalMs ?? 500;
    this.cancellationPollIntervalMs =
      dependencies.cancellationPollIntervalMs ?? 500;
  }

  start(): void {
    if (this.loop) {
      return;
    }
    this.stopping = false;
    this.loop = this.runLoop().finally(() => {
      this.loop = undefined;
    });
  }

  async shutdown(): Promise<void> {
    this.stopping = true;
    this.executionAbort?.abort();
    await this.loop;
  }

  private async runLoop(): Promise<void> {
    while (!this.stopping) {
      let worked = false;
      try {
        worked = await this.processNext();
      } catch {
        // A failed internal transport leaves pre-commit work lease-reclaimable
        // and committed work recoverable as uncertain. Never log private paths,
        // process stderr, prompts, or credentials here.
      }
      if (!worked && !this.stopping) {
        await this.wait(this.pollIntervalMs);
      }
    }
  }

  async processNext(): Promise<boolean> {
    const connection = this.connection();
    if (!connection) {
      return false;
    }
    const attempt = await this.client.claimNext(connection);
    if (!attempt) {
      return false;
    }
    await this.processClaim(attempt);
    return true;
  }

  private async processClaim(attempt: ClaimedProviderAttempt): Promise<void> {
    const connection = this.connection();
    if (!connection) {
      return;
    }
    try {
      await verifyClaimedAttemptFiles(attempt);
    } catch {
      await this.client.failPreflight(
        connection,
        attempt,
        "attempt-input-invalid"
      );
      return;
    }
    let codex: ResolvedCodex;
    try {
      codex = await this.resolver.codex();
    } catch {
      await this.client.failPreflight(
        connection,
        attempt,
        "codex-unavailable"
      );
      return;
    }

    let cursor: ResolvedCursor | undefined;
    if (
      attempt.policy === "codex_then_cursor" &&
      hasCurrentCursorConsent(attempt.cursorConsent) &&
      (codex.preflight.state === "not_installed" ||
        codex.preflight.state === "not_authenticated")
    ) {
      try {
        cursor = await this.resolver.cursor();
      } catch {
        cursor = {
          preflight: { provider: "cursor_cli", state: "unavailable" }
        };
      }
    }
    const selection = selectProviderBeforeCommit({
      policy: attempt.policy,
      ...(attempt.cursorConsent ? { consent: attempt.cursorConsent } : {}),
      codex: codex.preflight,
      ...(cursor ? { cursor: cursor.preflight } : {})
    });
    if (!selection.selected) {
      await this.client.failPreflight(
        connection,
        attempt,
        !selection.diagnostic ||
          selection.diagnostic === "result-uncertain"
          ? "codex-unavailable"
          : selection.diagnostic
      );
      return;
    }
    const runtime = selectedRuntime(selection.selected, codex, cursor);
    await this.client.select(connection, attempt, {
      provider: selection.selected,
      identity: runtime.installation.executable,
      version: runtime.version,
      ...(selection.fallbackReason
        ? { fallbackReason: selection.fallbackReason }
        : {})
    });
    const receipt = await this.client.commit(connection, attempt);
    const controller = new AbortController();
    this.executionAbort = controller;
    let cursorWorkspace:
      | Awaited<ReturnType<typeof createDisposableCursorWorkspace>>
      | undefined;
    try {
      const verified = await verifyClaimedAttemptFiles(attempt);
      if (runtime.installation.provider === "cursor_cli") {
        cursorWorkspace = await createDisposableCursorWorkspace(attempt);
      }
      let executionFinished = false;
      const cancellationMonitor = (async () => {
        while (!executionFinished && !controller.signal.aborted) {
          await this.wait(this.cancellationPollIntervalMs);
          if (executionFinished || controller.signal.aborted) {
            return;
          }
          try {
            if (
              await this.client.cancellationRequested(
                this.connection(),
                attempt
              )
            ) {
              controller.abort();
            }
          } catch {
            // Losing the sidecar does not prove that cancellation was
            // requested. The eventual missing completion is recovered as
            // uncertain instead of killing a potentially successful result.
          }
        }
      })();
      const result = await executeCommittedProviderAttempt(
        {
          installation: runtime.installation,
          commitReceipt: receipt,
          sourceEnvironment: process.env,
          cwd: cursorWorkspace?.path ?? verified.workingDirectory,
          prompt: verified.prompt,
          timeoutMs: EXECUTION_TIMEOUT_MS,
          outputLimitBytes: OUTPUT_LIMIT_BYTES,
          signal: controller.signal,
          ...(runtime.installation.provider === "codex_cli"
            ? {
                codexOutputSchemaPath: verified.schemaPath,
                codexOutputMessagePath: verified.outputPath
              }
            : { cursorWorkspaceIsDisposable: true })
        },
        this.runner
      ).finally(() => {
        executionFinished = true;
      });
      await cancellationMonitor;
      if (!result.ok) {
        await this.client.complete(this.connection(), attempt, {
          status: result.failure === "cancelled" ? "cancelled" : "failed",
          errorCode: result.failure
        });
        return;
      }
      if (runtime.installation.provider === "cursor_cli") {
        await writeCursorOutput(verified.outputPath, result.stdout);
      }
      const output = await inspectProviderOutput(verified.outputPath);
      await this.client.complete(this.connection(), attempt, {
        status: "succeeded",
        outputSha256: output.sha256,
        outputSize: output.size
      });
    } catch (error) {
      try {
        await this.client.complete(this.connection(), attempt, {
          status: controller.signal.aborted ? "cancelled" : "failed",
          errorCode:
            error instanceof ProviderAttemptClientError
              ? "sidecar-unavailable"
              : "execution-invalid"
        });
      } catch {
        // A missing completion acknowledgement is intentionally left in
        // executing; sidecar restart marks it uncertain and never replays it.
      }
    } finally {
      this.executionAbort = undefined;
      await cursorWorkspace?.cleanup().catch(() => undefined);
    }
  }
}

import type {
  CodexInstallation,
  CursorInstallation,
  ProviderExecutionCommitReceipt,
  ProviderInstallation
} from "./contracts";
import {
  revalidateCodexInstallation,
  revalidateExecutableIdentity
} from "./discovery";
import { buildProviderEnvironment } from "./environment";
import {
  buildCodexExecutionArguments,
  buildCursorExecutionArguments
} from "./invocation";
import {
  BoundedProcessRunner,
  type BoundedProcessResult
} from "./processRunner";

export type ProviderExecutionFailure =
  | "identity-changed"
  | "spawn-failed"
  | "timed-out"
  | "cancelled"
  | "output-limit"
  | "non-zero-exit";

export type ProviderExecutionResult =
  | {
      readonly ok: true;
      readonly provider: ProviderInstallation["provider"];
      readonly stdout: string;
    }
  | {
      readonly ok: false;
      readonly provider: ProviderInstallation["provider"];
      readonly failure: ProviderExecutionFailure;
    };

export interface ProviderExecutionInput {
  readonly installation: ProviderInstallation;
  readonly commitReceipt: ProviderExecutionCommitReceipt;
  readonly sourceEnvironment: NodeJS.ProcessEnv;
  readonly cwd: string;
  readonly prompt: string;
  readonly timeoutMs: number;
  readonly outputLimitBytes: number;
  readonly signal?: AbortSignal;
  readonly codexOutputSchemaPath?: string;
  readonly codexOutputMessagePath?: string;
  readonly cursorWorkspaceIsDisposable?: boolean;
}

function codexArguments(
  input: ProviderExecutionInput,
  installation: CodexInstallation
): readonly string[] {
  void installation;
  if (!input.codexOutputSchemaPath || !input.codexOutputMessagePath) {
    throw new TypeError("Codex execution requires trusted output paths");
  }
  return buildCodexExecutionArguments({
    outputSchemaPath: input.codexOutputSchemaPath,
    outputMessagePath: input.codexOutputMessagePath
  });
}

function cursorArguments(
  input: ProviderExecutionInput,
  installation: CursorInstallation
): readonly string[] {
  void installation;
  if (input.cursorWorkspaceIsDisposable !== true) {
    throw new TypeError(
      "Cursor execution requires an explicitly disposable workspace"
    );
  }
  return buildCursorExecutionArguments();
}

function classifyFailure(
  result: BoundedProcessResult
): ProviderExecutionFailure | undefined {
  if (result.cancelled) {
    return "cancelled";
  }
  if (result.timedOut) {
    return "timed-out";
  }
  if (result.outputLimitExceeded) {
    return "output-limit";
  }
  if (result.spawnErrorCode) {
    return "spawn-failed";
  }
  if (result.exitCode !== 0) {
    return "non-zero-exit";
  }
  return undefined;
}

export async function executeCommittedProviderAttempt(
  input: ProviderExecutionInput,
  runner: BoundedProcessRunner = new BoundedProcessRunner()
): Promise<ProviderExecutionResult> {
  const { installation } = input;
  if (
    input.commitReceipt.selectedProvider !== installation.provider ||
    input.commitReceipt.executableSha256 !== installation.executable.sha256 ||
    !input.commitReceipt.attemptId ||
    !input.commitReceipt.claimId ||
    !Number.isFinite(Date.parse(input.commitReceipt.executionCommittedAt))
  ) {
    throw new TypeError(
      "Provider execution commit receipt does not match the pinned installation"
    );
  }
  try {
    // The database commit point must already exist when this function is
    // entered. Revalidation immediately before spawn closes the common update
    // race; a crash after commit remains uncertain and is never replayed.
    if (installation.provider === "codex_cli") {
      await revalidateCodexInstallation(installation);
    } else {
      await revalidateExecutableIdentity(installation.executable);
    }
  } catch {
    return {
      ok: false,
      provider: installation.provider,
      failure: "identity-changed"
    };
  }

  const arguments_ =
    installation.provider === "codex_cli"
      ? codexArguments(input, installation)
      : cursorArguments(input, installation);
  const environment = buildProviderEnvironment({
    provider: installation.provider,
    source: input.sourceEnvironment,
    ...(installation.provider === "codex_cli"
      ? { codex: installation }
      : {})
  });
  const result = await runner.run(
    installation.executable.canonicalPath,
    arguments_,
    {
      cwd: input.cwd,
      environment,
      timeoutMs: input.timeoutMs,
      outputLimitBytes: input.outputLimitBytes,
      input: input.prompt,
      inputLimitBytes: 16 * 1024 * 1024,
      ...(input.signal ? { signal: input.signal } : {})
    }
  );
  const failure = classifyFailure(result);
  if (failure) {
    return {
      ok: false,
      provider: installation.provider,
      failure
    };
  }
  return {
    ok: true,
    provider: installation.provider,
    stdout: result.stdout
  };
}

import type {
  CodexInstallation,
  CursorInstallation,
  ProviderPreflight
} from "./contracts";
import { revalidateExecutableIdentity } from "./discovery";
import { buildProviderEnvironment } from "./environment";
import {
  buildCodexLoginStatusArguments,
  buildCursorStatusArguments
} from "./invocation";

const VERSION_PATTERN = /(?:codex-cli\s+)?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)/i;
const CURSOR_VERSION_PATTERN = /(\d{4}\.\d{2}\.\d{2}(?:-[0-9A-Za-z.-]+)?|\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)/;

export interface BoundedCommandResult {
  readonly exitCode: number | null;
  readonly stdout: string;
  readonly stderr: string;
  readonly timedOut?: boolean;
  readonly spawnErrorCode?: string;
  readonly outputLimitExceeded?: boolean;
}

export interface ProviderPreflightRunner {
  run(
    executablePath: string,
    arguments_: readonly string[],
    options: {
      readonly environment: NodeJS.ProcessEnv;
      readonly timeoutMs: number;
      readonly outputLimitBytes: number;
    }
  ): Promise<BoundedCommandResult>;
}

const PREFLIGHT_TIMEOUT_MS = 10_000;
const PREFLIGHT_OUTPUT_LIMIT = 64 * 1024;

function unavailable(
  provider: ProviderPreflight["provider"]
): ProviderPreflight {
  return { provider, state: "unavailable" };
}

export async function preflightCodex(
  installation: CodexInstallation,
  runner: ProviderPreflightRunner,
  sourceEnvironment: NodeJS.ProcessEnv
): Promise<ProviderPreflight> {
  try {
    await revalidateExecutableIdentity(installation.executable);
  } catch {
    return {
      provider: "codex_cli",
      state: "unsupported_installation"
    };
  }
  const environment = buildProviderEnvironment({
    provider: "codex_cli",
    source: sourceEnvironment,
    codex: installation
  });
  const version = await runner.run(
    installation.executable.canonicalPath,
    ["--version"],
    {
      environment,
      timeoutMs: PREFLIGHT_TIMEOUT_MS,
      outputLimitBytes: PREFLIGHT_OUTPUT_LIMIT
    }
  );
  if (
    version.timedOut ||
    version.spawnErrorCode ||
    version.outputLimitExceeded ||
    version.exitCode !== 0
  ) {
    return unavailable("codex_cli");
  }
  const reportedVersion = VERSION_PATTERN.exec(version.stdout)?.[1];
  if (reportedVersion !== installation.packageVersion) {
    return {
      provider: "codex_cli",
      state: "unsupported_installation"
    };
  }

  const status = await runner.run(
    installation.executable.canonicalPath,
    buildCodexLoginStatusArguments(),
    {
      environment,
      timeoutMs: PREFLIGHT_TIMEOUT_MS,
      outputLimitBytes: PREFLIGHT_OUTPUT_LIMIT
    }
  );
  if (
    status.timedOut ||
    status.spawnErrorCode ||
    status.outputLimitExceeded
  ) {
    return unavailable("codex_cli");
  }
  return status.exitCode === 0
    ? {
        provider: "codex_cli",
        state: "ready",
        version: reportedVersion
      }
    : {
        provider: "codex_cli",
        state: "not_authenticated",
        version: reportedVersion
      };
}

export async function preflightCursor(
  installation: CursorInstallation,
  runner: ProviderPreflightRunner,
  sourceEnvironment: NodeJS.ProcessEnv
): Promise<ProviderPreflight> {
  try {
    await revalidateExecutableIdentity(installation.executable);
  } catch {
    return {
      provider: "cursor_cli",
      state: "unsupported_installation"
    };
  }
  const environment = buildProviderEnvironment({
    provider: "cursor_cli",
    source: sourceEnvironment
  });
  const version = await runner.run(
    installation.executable.canonicalPath,
    ["--version"],
    {
      environment,
      timeoutMs: PREFLIGHT_TIMEOUT_MS,
      outputLimitBytes: PREFLIGHT_OUTPUT_LIMIT
    }
  );
  if (
    version.timedOut ||
    version.spawnErrorCode ||
    version.outputLimitExceeded ||
    version.exitCode !== 0
  ) {
    return unavailable("cursor_cli");
  }
  const reportedVersion = CURSOR_VERSION_PATTERN.exec(version.stdout)?.[1];
  if (!reportedVersion) {
    return {
      provider: "cursor_cli",
      state: "unsupported_installation"
    };
  }

  const status = await runner.run(
    installation.executable.canonicalPath,
    buildCursorStatusArguments(),
    {
      environment,
      timeoutMs: PREFLIGHT_TIMEOUT_MS,
      outputLimitBytes: PREFLIGHT_OUTPUT_LIMIT
    }
  );
  if (
    status.timedOut ||
    status.spawnErrorCode ||
    status.outputLimitExceeded
  ) {
    return unavailable("cursor_cli");
  }
  return status.exitCode === 0
    ? {
        provider: "cursor_cli",
        state: "ready",
        version: reportedVersion
      }
    : {
        provider: "cursor_cli",
        state: "not_authenticated",
        version: reportedVersion
      };
}

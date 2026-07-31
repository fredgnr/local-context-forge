import type {
  CodexInstallation,
  CursorInstallation,
  ProviderPreflight
} from "./contracts";
import {
  discoverCodexInstallation,
  discoverCursorInstallation,
  findCommandOnPath
} from "./discovery";
import {
  preflightCodex,
  preflightCursor,
  type ProviderPreflightRunner
} from "./preflight";

export type ResolvedCodex =
  | {
      readonly preflight: ProviderPreflight;
      readonly installation: CodexInstallation;
    }
  | { readonly preflight: ProviderPreflight };

export type ResolvedCursor =
  | {
      readonly preflight: ProviderPreflight;
      readonly installation: CursorInstallation;
    }
  | { readonly preflight: ProviderPreflight };

export class ProviderResolver {
  constructor(
    private readonly runner: ProviderPreflightRunner,
    private readonly environment: NodeJS.ProcessEnv
  ) {}

  async codex(): Promise<ResolvedCodex> {
    const command = await findCommandOnPath("codex", this.environment);
    if (!command) {
      return {
        preflight: { provider: "codex_cli", state: "not_installed" }
      };
    }
    let installation: CodexInstallation;
    try {
      installation = await discoverCodexInstallation(command);
    } catch {
      return {
        preflight: {
          provider: "codex_cli",
          state: "unsupported_installation"
        }
      };
    }
    return {
      installation,
      preflight: await preflightCodex(
        installation,
        this.runner,
        this.environment
      )
    };
  }

  async cursor(): Promise<ResolvedCursor> {
    const command = await findCommandOnPath("cursor-agent", this.environment);
    if (!command) {
      return {
        preflight: { provider: "cursor_cli", state: "not_installed" }
      };
    }
    let installation: CursorInstallation;
    try {
      installation = await discoverCursorInstallation(command);
    } catch {
      return {
        preflight: {
          provider: "cursor_cli",
          state: "unsupported_installation"
        }
      };
    }
    return {
      installation,
      preflight: await preflightCursor(
        installation,
        this.runner,
        this.environment
      )
    };
  }
}

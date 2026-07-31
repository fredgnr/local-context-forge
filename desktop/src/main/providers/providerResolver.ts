import type {
  CodexInstallation,
  CursorInstallation,
  ProviderPreflight
} from "./contracts";
import {
  discoverCodexInstallation,
  discoverCursorInstallation,
  findCommandCandidates
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
    const commands = await findCommandCandidates(
      "codex",
      this.environment
    );
    if (!commands.length) {
      return {
        preflight: { provider: "codex_cli", state: "not_installed" }
      };
    }
    for (const command of commands) {
      let installation: CodexInstallation;
      try {
        installation = await discoverCodexInstallation(command, {
          environment: this.environment
        });
      } catch {
        continue;
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
    return {
      preflight: {
        provider: "codex_cli",
        state: "unsupported_installation"
      }
    };
  }

  async cursor(): Promise<ResolvedCursor> {
    const commands = await findCommandCandidates(
      "cursor-agent",
      this.environment
    );
    if (!commands.length) {
      return {
        preflight: { provider: "cursor_cli", state: "not_installed" }
      };
    }
    for (const command of commands) {
      let installation: CursorInstallation;
      try {
        installation = await discoverCursorInstallation(command);
      } catch {
        continue;
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
    return {
      preflight: {
        provider: "cursor_cli",
        state: "unsupported_installation"
      }
    };
  }
}

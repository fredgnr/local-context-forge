export const CURSOR_FALLBACK_CONSENT_VERSION = 1 as const;

export type ProviderId = "codex_cli" | "cursor_cli";
export type ProviderPolicy = "codex_only" | "codex_then_cursor";

export type ProviderPreflightState =
  | "ready"
  | "not_installed"
  | "not_authenticated"
  | "unsupported_installation"
  | "unavailable";

export type ProviderDiagnosticCode =
  | "codex-not-installed"
  | "codex-not-authenticated"
  | "codex-installation-unsupported"
  | "codex-unavailable"
  | "cursor-consent-required"
  | "cursor-not-installed"
  | "cursor-not-authenticated"
  | "cursor-installation-unsupported"
  | "cursor-unavailable"
  | "result-uncertain";

export interface CursorFallbackConsent {
  readonly subject: "cursor_cli_fallback";
  readonly version: typeof CURSOR_FALLBACK_CONSENT_VERSION;
  readonly granted: true;
  readonly grantedAt: string;
}

export interface ProviderPreflight {
  readonly provider: ProviderId;
  readonly state: ProviderPreflightState;
  readonly version?: string;
}

export interface FileIdentity {
  readonly canonicalPath: string;
  readonly sha256: string;
  readonly size: number;
  readonly mtimeMs: number;
  readonly device: number;
  readonly inode: number;
  readonly mode: number;
}

export interface CodexInstallation {
  readonly provider: "codex_cli";
  readonly packageVersion: string;
  readonly packageRoot: string;
  readonly managedPackageRoot: string;
  readonly wrapperPath: string;
  readonly executable: FileIdentity;
}

export interface CursorInstallation {
  readonly provider: "cursor_cli";
  readonly executable: FileIdentity;
}

export type ProviderInstallation = CodexInstallation | CursorInstallation;

export interface ProviderSelection {
  readonly selected?: ProviderId;
  readonly fallbackReason?:
    | "codex_not_installed"
    | "codex_not_authenticated";
  readonly diagnostic?: ProviderDiagnosticCode;
}

export type ProviderAttemptStatus =
  | "pending"
  | "claimed"
  | "selected"
  | "executing"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "uncertain";

export interface ProviderAttemptRecord {
  readonly id: string;
  readonly jobId: string;
  readonly policy: ProviderPolicy;
  readonly status: ProviderAttemptStatus;
  readonly selectedProvider?: ProviderId;
  readonly fallbackReason?: ProviderSelection["fallbackReason"];
  readonly diagnostic?: ProviderDiagnosticCode;
  readonly claimedAt?: string;
  readonly claimExpiresAt?: string;
  readonly executionCommittedAt?: string;
  readonly finishedAt?: string;
}

export interface ProviderAttemptView {
  readonly id: string;
  readonly jobId: string;
  readonly policy: ProviderPolicy;
  readonly status: ProviderAttemptStatus;
  readonly selectedProvider?: ProviderId;
  readonly fallbackReason?: ProviderSelection["fallbackReason"];
  readonly diagnostic?: ProviderDiagnosticCode;
  readonly requiresExplicitRetry: boolean;
}

export interface ProviderExecutionCommitReceipt {
  readonly attemptId: string;
  readonly claimId: string;
  readonly selectedProvider: ProviderId;
  readonly executableSha256: string;
  readonly executionCommittedAt: string;
}

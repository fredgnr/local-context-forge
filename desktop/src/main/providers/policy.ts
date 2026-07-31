import {
  CURSOR_FALLBACK_CONSENT_VERSION,
  type CursorFallbackConsent,
  type ProviderDiagnosticCode,
  type ProviderPolicy,
  type ProviderPreflight,
  type ProviderSelection
} from "./contracts";

const ISO_INSTANT =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/;

export function isProviderPolicy(value: unknown): value is ProviderPolicy {
  return value === "codex_only" || value === "codex_then_cursor";
}

export function hasCurrentCursorConsent(
  value: unknown
): value is CursorFallbackConsent {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const candidate = value as Partial<CursorFallbackConsent>;
  if (
    candidate.subject !== "cursor_cli_fallback" ||
    candidate.version !== CURSOR_FALLBACK_CONSENT_VERSION ||
    candidate.granted !== true ||
    typeof candidate.grantedAt !== "string" ||
    !ISO_INSTANT.test(candidate.grantedAt)
  ) {
    return false;
  }
  return !Number.isNaN(Date.parse(candidate.grantedAt));
}

export function effectiveProviderPolicy(
  requested: ProviderPolicy,
  consent: unknown
): {
  policy: ProviderPolicy;
  diagnostic?: "cursor-consent-required";
} {
  if (
    requested === "codex_then_cursor" &&
    !hasCurrentCursorConsent(consent)
  ) {
    return {
      policy: "codex_only",
      diagnostic: "cursor-consent-required"
    };
  }
  return { policy: requested };
}

function diagnosticFor(
  provider: ProviderPreflight["provider"],
  state: Exclude<ProviderPreflight["state"], "ready">
): ProviderDiagnosticCode {
  const prefix = provider === "codex_cli" ? "codex" : "cursor";
  const suffix = {
    not_installed: "not-installed",
    not_authenticated: "not-authenticated",
    unsupported_installation: "installation-unsupported",
    unavailable: "unavailable"
  }[state];
  return `${prefix}-${suffix}` as ProviderDiagnosticCode;
}

export function selectProviderBeforeCommit(input: {
  readonly policy: ProviderPolicy;
  readonly consent?: unknown;
  readonly codex: ProviderPreflight;
  readonly cursor?: ProviderPreflight;
}): ProviderSelection {
  if (input.codex.provider !== "codex_cli") {
    throw new TypeError("Codex preflight result has the wrong provider");
  }
  if (input.cursor && input.cursor.provider !== "cursor_cli") {
    throw new TypeError("Cursor preflight result has the wrong provider");
  }
  if (input.codex.state === "ready") {
    return { selected: "codex_cli" };
  }

  const effective = effectiveProviderPolicy(input.policy, input.consent);
  if (effective.policy === "codex_only") {
    return {
      diagnostic:
        effective.diagnostic ??
        diagnosticFor("codex_cli", input.codex.state)
    };
  }

  if (
    input.codex.state !== "not_installed" &&
    input.codex.state !== "not_authenticated"
  ) {
    return {
      diagnostic: diagnosticFor("codex_cli", input.codex.state)
    };
  }
  if (!input.cursor) {
    throw new TypeError(
      "Cursor preflight is required after an eligible Codex failure"
    );
  }
  if (input.cursor.state !== "ready") {
    return {
      diagnostic: diagnosticFor("cursor_cli", input.cursor.state)
    };
  }
  return {
    selected: "cursor_cli",
    fallbackReason:
      input.codex.state === "not_installed"
        ? "codex_not_installed"
        : "codex_not_authenticated"
  };
}

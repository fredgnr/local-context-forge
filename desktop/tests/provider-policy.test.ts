import { describe, expect, it } from "vitest";
import {
  assertProviderAttemptTransition,
  canClaimProviderAttempt,
  recoverInterruptedProviderAttempt,
  toProviderAttemptView
} from "../src/main/providers/attempt";
import {
  CURSOR_FALLBACK_CONSENT_VERSION,
  type CursorFallbackConsent,
  type ProviderAttemptRecord,
  type ProviderPreflight
} from "../src/main/providers/contracts";
import { buildProviderEnvironment } from "../src/main/providers/environment";
import {
  buildCodexExecutionArguments,
  buildCursorExecutionArguments
} from "../src/main/providers/invocation";
import {
  effectiveProviderPolicy,
  hasCurrentCursorConsent,
  selectProviderBeforeCommit
} from "../src/main/providers/policy";

const consent: CursorFallbackConsent = {
  subject: "cursor_cli_fallback",
  version: CURSOR_FALLBACK_CONSENT_VERSION,
  granted: true,
  grantedAt: "2026-07-31T12:00:00Z"
};

const preflight = (
  provider: ProviderPreflight["provider"],
  state: ProviderPreflight["state"]
): ProviderPreflight => ({ provider, state });

describe("provider policy", () => {
  it("accepts only current, explicit Cursor fallback consent", () => {
    expect(hasCurrentCursorConsent(consent)).toBe(true);
    expect(hasCurrentCursorConsent({ ...consent, version: 0 })).toBe(false);
    expect(hasCurrentCursorConsent({ ...consent, granted: false })).toBe(false);
    expect(hasCurrentCursorConsent({ ...consent, grantedAt: "yesterday" })).toBe(
      false
    );
  });

  it("degrades codex_then_cursor to codex_only without current consent", () => {
    expect(effectiveProviderPolicy("codex_then_cursor", undefined)).toEqual({
      policy: "codex_only",
      diagnostic: "cursor-consent-required"
    });
  });

  it("always selects ready Codex without probing fallback state", () => {
    expect(
      selectProviderBeforeCommit({
        policy: "codex_then_cursor",
        consent,
        codex: preflight("codex_cli", "ready")
      })
    ).toEqual({ selected: "codex_cli" });
  });

  it.each([
    ["not_installed", "codex_not_installed"],
    ["not_authenticated", "codex_not_authenticated"]
  ] as const)(
    "permits Cursor only for the eligible pre-spawn Codex state %s",
    (codexState, fallbackReason) => {
      expect(
        selectProviderBeforeCommit({
          policy: "codex_then_cursor",
          consent,
          codex: preflight("codex_cli", codexState),
          cursor: preflight("cursor_cli", "ready")
        })
      ).toEqual({ selected: "cursor_cli", fallbackReason });
    }
  );

  it.each(["unsupported_installation", "unavailable"] as const)(
    "does not fall back after Codex %s",
    (codexState) => {
      expect(
        selectProviderBeforeCommit({
          policy: "codex_then_cursor",
          consent,
          codex: preflight("codex_cli", codexState),
          cursor: preflight("cursor_cli", "ready")
        })
      ).toEqual({
        diagnostic:
          codexState === "unavailable"
            ? "codex-unavailable"
            : "codex-installation-unsupported"
      });
    }
  );

  it("reports the Cursor preflight failure without exposing process details", () => {
    expect(
      selectProviderBeforeCommit({
        policy: "codex_then_cursor",
        consent,
        codex: preflight("codex_cli", "not_installed"),
        cursor: preflight("cursor_cli", "not_authenticated")
      })
    ).toEqual({ diagnostic: "cursor-not-authenticated" });
  });
});

describe("provider attempt state", () => {
  const base: ProviderAttemptRecord = {
    id: "attempt-1",
    jobId: "job-1",
    policy: "codex_only",
    status: "pending"
  };

  it("allows only directed state transitions", () => {
    expect(() => assertProviderAttemptTransition("pending", "claimed")).not.toThrow();
    expect(() =>
      assertProviderAttemptTransition("selected", "executing")
    ).not.toThrow();
    expect(() =>
      assertProviderAttemptTransition("executing", "uncertain")
    ).not.toThrow();
    expect(() =>
      assertProviderAttemptTransition("executing", "selected")
    ).toThrow(/Invalid provider attempt transition/);
    expect(() =>
      assertProviderAttemptTransition("succeeded", "executing")
    ).toThrow(/Invalid provider attempt transition/);
  });

  it("reclaims only an uncommitted expired lease", () => {
    const now = new Date("2026-07-31T12:00:00Z");
    expect(canClaimProviderAttempt(base, now)).toBe(true);
    expect(
      canClaimProviderAttempt(
        {
          status: "selected",
          claimExpiresAt: "2026-07-31T11:59:59Z"
        },
        now
      )
    ).toBe(true);
    expect(
      canClaimProviderAttempt(
        {
          status: "selected",
          claimExpiresAt: "2026-07-31T12:00:01Z"
        },
        now
      )
    ).toBe(false);
    expect(
      canClaimProviderAttempt(
        {
          status: "executing",
          executionCommittedAt: "2026-07-31T11:59:00Z"
        },
        now
      )
    ).toBe(false);
  });

  it("recovers a committed non-terminal attempt as uncertain", () => {
    const interrupted: ProviderAttemptRecord = {
      ...base,
      status: "executing",
      selectedProvider: "codex_cli",
      executionCommittedAt: "2026-07-31T11:59:00Z"
    };
    expect(recoverInterruptedProviderAttempt(interrupted)).toBe("uncertain");
    expect(
      toProviderAttemptView({ ...interrupted, status: "uncertain" })
    ).toEqual({
      id: "attempt-1",
      jobId: "job-1",
      policy: "codex_only",
      status: "uncertain",
      selectedProvider: "codex_cli",
      requiresExplicitRetry: true
    });
    expect(JSON.stringify(toProviderAttemptView(interrupted))).not.toContain(
      "executionCommittedAt"
    );
  });
});

describe("fixed provider invocation", () => {
  it("builds a fixed Codex read-only, ephemeral exec contract", () => {
    expect(
      buildCodexExecutionArguments({
        outputSchemaPath: "/private/attempt/schema.json",
        outputMessagePath: "/private/attempt/result.json"
      })
    ).toEqual([
      "exec",
      "--ephemeral",
      "--ignore-user-config",
      "--ignore-rules",
      "--skip-git-repo-check",
      "--sandbox",
      "read-only",
      "--output-schema",
      "/private/attempt/schema.json",
      "--output-last-message",
      "/private/attempt/result.json",
      "-"
    ]);
  });

  it("never gives Cursor --force and keeps the prompt out of argv", () => {
    const arguments_ = buildCursorExecutionArguments();
    expect(arguments_).toEqual(["--print", "--output-format", "json"]);
    expect(arguments_).not.toContain("--force");
  });

  it("passes saved-login locations but strips API keys and user PATH", () => {
    const environment = buildProviderEnvironment({
      provider: "codex_cli",
      source: {
        HOME: "/Users/test",
        PATH: "/untrusted/repository/bin",
        CODEX_HOME: "/Users/test/.codex",
        OPENAI_API_KEY: "secret",
        CURSOR_API_KEY: "also-secret"
      },
      codex: {
        provider: "codex_cli",
        packageVersion: "0.146.0",
        packageRoot: "/opt/codex",
        managedPackageRoot: "/opt/codex",
        wrapperPath: "/opt/codex/bin/codex.js",
        executable: {
          canonicalPath: "/opt/codex/vendor/codex",
          sha256: "a".repeat(64),
          size: 1,
          mtimeMs: 1,
          device: 1,
          inode: 1,
          mode: 0o100755
        }
      }
    });
    expect(environment).toMatchObject({
      HOME: "/Users/test",
      CODEX_HOME: "/Users/test/.codex",
      PATH: "/usr/bin:/bin:/usr/sbin:/sbin",
      CODEX_MANAGED_PACKAGE_ROOT: "/opt/codex",
      CODEX_MANAGED_BY_NPM: "1"
    });
    expect(environment).not.toHaveProperty("OPENAI_API_KEY");
    expect(environment).not.toHaveProperty("CURSOR_API_KEY");
  });
});

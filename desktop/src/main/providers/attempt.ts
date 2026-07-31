import type {
  ProviderAttemptRecord,
  ProviderAttemptStatus,
  ProviderAttemptView
} from "./contracts";

const TERMINAL_STATUSES = new Set<ProviderAttemptStatus>([
  "succeeded",
  "failed",
  "cancelled",
  "uncertain"
]);

const ALLOWED_TRANSITIONS: Readonly<
  Record<ProviderAttemptStatus, ReadonlySet<ProviderAttemptStatus>>
> = {
  pending: new Set(["claimed", "cancelled"]),
  claimed: new Set(["selected", "failed", "cancelled"]),
  selected: new Set(["claimed", "executing", "failed", "cancelled"]),
  executing: new Set(["succeeded", "failed", "cancelled", "uncertain"]),
  succeeded: new Set(),
  failed: new Set(),
  cancelled: new Set(),
  uncertain: new Set()
};

export function assertProviderAttemptTransition(
  current: ProviderAttemptStatus,
  next: ProviderAttemptStatus
): void {
  if (!ALLOWED_TRANSITIONS[current].has(next)) {
    throw new TypeError(`Invalid provider attempt transition: ${current} -> ${next}`);
  }
}

export function canClaimProviderAttempt(
  attempt: Pick<
    ProviderAttemptRecord,
    "status" | "executionCommittedAt" | "claimExpiresAt"
  >,
  now: Date
): boolean {
  if (attempt.executionCommittedAt !== undefined) {
    return false;
  }
  if (attempt.status === "pending") {
    return true;
  }
  if (attempt.status !== "claimed" && attempt.status !== "selected") {
    return false;
  }
  if (!attempt.claimExpiresAt) {
    return false;
  }
  const expiry = Date.parse(attempt.claimExpiresAt);
  return Number.isFinite(expiry) && expiry <= now.getTime();
}

export function recoverInterruptedProviderAttempt(
  attempt: ProviderAttemptRecord
): ProviderAttemptStatus {
  if (
    attempt.executionCommittedAt !== undefined &&
    !TERMINAL_STATUSES.has(attempt.status)
  ) {
    return "uncertain";
  }
  return attempt.status;
}

export function toProviderAttemptView(
  attempt: ProviderAttemptRecord
): ProviderAttemptView {
  const view: ProviderAttemptView = {
    id: attempt.id,
    jobId: attempt.jobId,
    policy: attempt.policy,
    status: attempt.status,
    requiresExplicitRetry: attempt.status === "uncertain"
  };
  return {
    ...view,
    ...(attempt.selectedProvider
      ? { selectedProvider: attempt.selectedProvider }
      : {}),
    ...(attempt.fallbackReason
      ? { fallbackReason: attempt.fallbackReason }
      : {}),
    ...(attempt.diagnostic ? { diagnostic: attempt.diagnostic } : {})
  };
}

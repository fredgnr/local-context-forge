import { randomUUID } from "node:crypto";
import http, {
  type ClientRequest,
  type IncomingMessage,
  type RequestOptions
} from "node:http";
import path from "node:path";
import { SIDECAR_PROTOCOL_VERSION } from "../../contracts";
import type { SidecarConnection } from "../apiProxy";
import type {
  CursorFallbackConsent,
  FileIdentity,
  ProviderDiagnosticCode,
  ProviderExecutionCommitReceipt,
  ProviderId,
  ProviderPolicy,
  ProviderSelection
} from "./contracts";

const MAX_INTERNAL_RESPONSE_BYTES = 256 * 1024;
const MAX_INTERNAL_REQUEST_BYTES = 32 * 1024;
const INTERNAL_TIMEOUT_MS = 15_000;
const HEX_ID = /^[0-9a-f]{32}$/;
const SHA256 = /^[0-9a-f]{64}$/;

type RequestImplementation = (
  options: RequestOptions,
  callback: (response: IncomingMessage) => void
) => ClientRequest;

export interface ClaimedProviderAttempt {
  readonly attemptId: string;
  readonly jobId: string;
  readonly claimId: string;
  readonly policy: ProviderPolicy;
  readonly candidates: readonly ProviderId[];
  readonly cursorConsent?: CursorFallbackConsent;
  readonly inputSha256: string;
  readonly attemptDirectory: string;
  readonly requestPath: string;
  readonly evidencePath: string;
  readonly schemaPath: string;
  readonly promptPath: string;
  readonly outputPath: string;
}

export interface ProviderAttemptClientDependencies {
  readonly request?: RequestImplementation;
  readonly now?: () => number;
  readonly requestId?: () => string;
}

export class ProviderAttemptClientError extends Error {
  constructor(
    readonly code:
      | "unavailable"
      | "timeout"
      | "transport"
      | "invalid-response"
      | "conflict"
  ) {
    super(`Provider attempt sidecar request failed (${code})`);
    this.name = "ProviderAttemptClientError";
  }
}

function plainRecord(value: unknown): value is Record<string, unknown> {
  return (
    !!value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    (Object.getPrototypeOf(value) === Object.prototype ||
      Object.getPrototypeOf(value) === null)
  );
}

function exactKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[] = []
): boolean {
  const allowed = new Set([...required, ...optional]);
  return (
    Object.keys(value).every((key) => allowed.has(key)) &&
    required.every((key) => Object.prototype.hasOwnProperty.call(value, key))
  );
}

function requirePrivatePath(
  value: unknown,
  dataDirectory: string,
  attemptDirectory?: string
): string {
  if (
    typeof value !== "string" ||
    !path.isAbsolute(value) ||
    value.includes("\0")
  ) {
    throw new ProviderAttemptClientError("invalid-response");
  }
  const normalized = path.normalize(value);
  if (normalized !== value) {
    throw new ProviderAttemptClientError("invalid-response");
  }
  const root = path.resolve(dataDirectory);
  const relative = path.relative(root, normalized);
  if (
    !relative ||
    relative === ".." ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw new ProviderAttemptClientError("invalid-response");
  }
  if (
    attemptDirectory !== undefined &&
    path.dirname(normalized) !== attemptDirectory
  ) {
    throw new ProviderAttemptClientError("invalid-response");
  }
  return normalized;
}

function parseConsent(value: unknown): CursorFallbackConsent | undefined {
  if (value === null) {
    return undefined;
  }
  if (
    !plainRecord(value) ||
    !exactKeys(value, [
      "subject",
      "version",
      "granted",
      "granted_at"
    ]) ||
    value.subject !== "cursor_cli_fallback" ||
    value.version !== 1 ||
    value.granted !== true ||
    typeof value.granted_at !== "string" ||
    !Number.isFinite(Date.parse(value.granted_at))
  ) {
    throw new ProviderAttemptClientError("invalid-response");
  }
  return {
    subject: "cursor_cli_fallback",
    version: 1,
    granted: true,
    grantedAt: value.granted_at
  };
}

function parseClaim(
  value: unknown,
  dataDirectory: string
): ClaimedProviderAttempt {
  const keys = [
    "attempt_id",
    "job_id",
    "claim_id",
    "policy",
    "candidates",
    "cursor_consent",
    "input_sha256",
    "attempt_directory",
    "request_path",
    "evidence_path",
    "schema_path",
    "prompt_path",
    "output_path"
  ] as const;
  if (!plainRecord(value) || !exactKeys(value, keys)) {
    throw new ProviderAttemptClientError("invalid-response");
  }
  if (
    typeof value.attempt_id !== "string" ||
    !HEX_ID.test(value.attempt_id) ||
    typeof value.job_id !== "string" ||
    !HEX_ID.test(value.job_id) ||
    typeof value.claim_id !== "string" ||
    !HEX_ID.test(value.claim_id) ||
    (value.policy !== "codex_only" &&
      value.policy !== "codex_then_cursor") ||
    !Array.isArray(value.candidates) ||
    (value.candidates.length !== 1 && value.candidates.length !== 2) ||
    value.candidates[0] !== "codex_cli" ||
    (value.candidates.length === 2 &&
      value.candidates[1] !== "cursor_cli") ||
    typeof value.input_sha256 !== "string" ||
    !SHA256.test(value.input_sha256)
  ) {
    throw new ProviderAttemptClientError("invalid-response");
  }
  const attemptDirectory = requirePrivatePath(
    value.attempt_directory,
    dataDirectory
  );
  const cursorConsent = parseConsent(value.cursor_consent);
  return {
    attemptId: value.attempt_id,
    jobId: value.job_id,
    claimId: value.claim_id,
    policy: value.policy,
    candidates: value.candidates as ProviderId[],
    ...(cursorConsent ? { cursorConsent } : {}),
    inputSha256: value.input_sha256,
    attemptDirectory,
    requestPath: requirePrivatePath(
      value.request_path,
      dataDirectory,
      attemptDirectory
    ),
    evidencePath: requirePrivatePath(
      value.evidence_path,
      dataDirectory,
      attemptDirectory
    ),
    schemaPath: requirePrivatePath(
      value.schema_path,
      dataDirectory,
      attemptDirectory
    ),
    promptPath: requirePrivatePath(
      value.prompt_path,
      dataDirectory,
      attemptDirectory
    ),
    outputPath: requirePrivatePath(
      value.output_path,
      dataDirectory,
      attemptDirectory
    )
  };
}

function identityPayload(provider: ProviderId, identity: FileIdentity, version: string) {
  return {
    provider,
    canonical_path: identity.canonicalPath,
    sha256: identity.sha256,
    size: identity.size,
    mtime_ms: identity.mtimeMs,
    device: identity.device,
    inode: identity.inode,
    mode: identity.mode,
    version
  };
}

export class ProviderAttemptClient {
  private readonly requestImplementation: RequestImplementation;
  private readonly now: () => number;
  private readonly requestId: () => string;

  constructor(
    private readonly dataDirectory: string,
    dependencies: ProviderAttemptClientDependencies = {}
  ) {
    if (!path.isAbsolute(dataDirectory)) {
      throw new TypeError("Provider attempt data directory must be absolute");
    }
    this.requestImplementation = dependencies.request ?? http.request;
    this.now = dependencies.now ?? Date.now;
    this.requestId = dependencies.requestId ?? randomUUID;
  }

  private async request(
    connection: SidecarConnection | undefined,
    requestPath: string,
    body: Record<string, unknown>
  ): Promise<{ status: number; value?: unknown }> {
    if (!connection) {
      throw new ProviderAttemptClientError("unavailable");
    }
    const serialized = Buffer.from(JSON.stringify(body), "utf8");
    if (serialized.length > MAX_INTERNAL_REQUEST_BYTES) {
      throw new TypeError("Provider attempt request is too large");
    }
    return await new Promise((resolve, reject) => {
      const request = this.requestImplementation(
        {
          socketPath: connection.socketPath,
          path: requestPath,
          method: "POST",
          headers: {
            Authorization: `Bearer ${connection.token}`,
            Accept: "application/json",
            "Content-Type": "application/json",
            "Content-Length": String(serialized.length),
            "X-LCF-Protocol-Version": SIDECAR_PROTOCOL_VERSION,
            "X-LCF-Launch-ID": connection.launchId,
            "X-LCF-Request-ID": this.requestId(),
            "X-LCF-Deadline-Ms": String(this.now() + INTERNAL_TIMEOUT_MS)
          }
        },
        (response) => {
          const chunks: Buffer[] = [];
          let size = 0;
          response.on("data", (chunk: Buffer | string) => {
            const data = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
            size += data.length;
            if (size > MAX_INTERNAL_RESPONSE_BYTES) {
              request.destroy();
              reject(new ProviderAttemptClientError("invalid-response"));
              return;
            }
            chunks.push(data);
          });
          response.once("end", () => {
            const statusCode = response.statusCode ?? 0;
            if (statusCode === 204) {
              resolve({ status: 204 });
              return;
            }
            let value: unknown;
            try {
              value = JSON.parse(Buffer.concat(chunks).toString("utf8"));
            } catch {
              reject(new ProviderAttemptClientError("invalid-response"));
              return;
            }
            if (statusCode === 409) {
              reject(new ProviderAttemptClientError("conflict"));
              return;
            }
            if (statusCode < 200 || statusCode >= 300) {
              reject(new ProviderAttemptClientError("transport"));
              return;
            }
            resolve({ status: statusCode, value });
          });
        }
      );
      request.setTimeout(INTERNAL_TIMEOUT_MS, () => {
        request.destroy();
        reject(new ProviderAttemptClientError("timeout"));
      });
      request.once("error", () => {
        reject(new ProviderAttemptClientError("transport"));
      });
      request.end(serialized);
    });
  }

  async claimNext(
    connection: SidecarConnection | undefined,
    leaseSeconds = 120
  ): Promise<ClaimedProviderAttempt | undefined> {
    const response = await this.request(
      connection,
      "/api/desktop/provider-attempts/claim-next",
      { lease_seconds: leaseSeconds }
    );
    return response.status === 204
      ? undefined
      : parseClaim(response.value, this.dataDirectory);
  }

  async select(
    connection: SidecarConnection | undefined,
    attempt: ClaimedProviderAttempt,
    input: {
      provider: ProviderId;
      identity: FileIdentity;
      version: string;
      fallbackReason?: ProviderSelection["fallbackReason"];
    }
  ): Promise<void> {
    await this.request(
      connection,
      `/api/desktop/provider-attempts/${attempt.attemptId}/select`,
      {
        claim_id: attempt.claimId,
        provider: input.provider,
        executable_identity: identityPayload(
          input.provider,
          input.identity,
          input.version
        ),
        fallback_reason: input.fallbackReason ?? null
      }
    );
  }

  async failPreflight(
    connection: SidecarConnection | undefined,
    attempt: ClaimedProviderAttempt,
    diagnostic: Exclude<ProviderDiagnosticCode, "result-uncertain">
  ): Promise<void> {
    await this.request(
      connection,
      `/api/desktop/provider-attempts/${attempt.attemptId}/fail-preflight`,
      {
        claim_id: attempt.claimId,
        diagnostic
      }
    );
  }

  async commit(
    connection: SidecarConnection | undefined,
    attempt: ClaimedProviderAttempt
  ): Promise<ProviderExecutionCommitReceipt> {
    const response = await this.request(
      connection,
      `/api/desktop/provider-attempts/${attempt.attemptId}/commit`,
      { claim_id: attempt.claimId }
    );
    const value = response.value;
    if (
      !plainRecord(value) ||
      !exactKeys(value, [
        "attempt_id",
        "claim_id",
        "selected_provider",
        "executable_sha256",
        "execution_committed_at"
      ]) ||
      value.attempt_id !== attempt.attemptId ||
      value.claim_id !== attempt.claimId ||
      (value.selected_provider !== "codex_cli" &&
        value.selected_provider !== "cursor_cli") ||
      typeof value.executable_sha256 !== "string" ||
      !SHA256.test(value.executable_sha256) ||
      typeof value.execution_committed_at !== "string" ||
      !Number.isFinite(Date.parse(value.execution_committed_at))
    ) {
      throw new ProviderAttemptClientError("invalid-response");
    }
    return {
      attemptId: value.attempt_id,
      claimId: value.claim_id,
      selectedProvider: value.selected_provider,
      executableSha256: value.executable_sha256,
      executionCommittedAt: value.execution_committed_at
    };
  }

  async complete(
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
  ): Promise<void> {
    await this.request(
      connection,
      `/api/desktop/provider-attempts/${attempt.attemptId}/complete`,
      {
        claim_id: attempt.claimId,
        status: input.status,
        ...(input.status === "succeeded"
          ? {
              output_sha256: input.outputSha256,
              output_size: input.outputSize,
              error_code: null
            }
          : {
              output_sha256: null,
              output_size: null,
              error_code: input.errorCode
            })
      }
    );
  }

  async cancellationRequested(
    connection: SidecarConnection | undefined,
    attempt: ClaimedProviderAttempt
  ): Promise<boolean> {
    const response = await this.request(
      connection,
      `/api/desktop/provider-attempts/${attempt.attemptId}/cancellation-state`,
      { claim_id: attempt.claimId }
    );
    const value = response.value;
    if (
      !plainRecord(value) ||
      !exactKeys(value, [
        "attempt_id",
        "cancel_requested",
        "status"
      ]) ||
      value.attempt_id !== attempt.attemptId ||
      typeof value.cancel_requested !== "boolean" ||
      ![
        "pending",
        "claimed",
        "selected",
        "executing",
        "succeeded",
        "failed",
        "cancelled",
        "uncertain"
      ].includes(String(value.status))
    ) {
      throw new ProviderAttemptClientError("invalid-response");
    }
    return value.cancel_requested;
  }
}

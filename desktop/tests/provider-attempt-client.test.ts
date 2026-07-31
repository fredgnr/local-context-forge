import { EventEmitter } from "node:events";
import type {
  ClientRequest,
  IncomingMessage,
  RequestOptions
} from "node:http";
import { PassThrough } from "node:stream";
import { describe, expect, it, vi } from "vitest";
import type { SidecarConnection } from "../src/main/apiProxy";
import {
  ProviderAttemptClient,
  type ProviderAttemptClientDependencies
} from "../src/main/providers/providerAttemptClient";

const connection: SidecarConnection = {
  socketPath: "/private/lcf/py.sock",
  launchId: "00000000-0000-4000-8000-000000000001",
  token: "A".repeat(43)
};

function response(
  callback: (response: IncomingMessage) => void,
  status: number,
  body = ""
): void {
  const stream = new PassThrough() as PassThrough & IncomingMessage;
  stream.statusCode = status;
  callback(stream);
  stream.end(body);
}

function transport(
  queued: Array<{ status: number; body?: unknown }>
): ProviderAttemptClientDependencies & {
  readonly options: RequestOptions[];
  readonly bodies: Buffer[];
} {
  const options: RequestOptions[] = [];
  const bodies: Buffer[] = [];
  return {
    options,
    bodies,
    now: () => 1_000,
    requestId: () => "00000000-0000-4000-8000-000000000002",
    request(requestOptions, callback) {
      options.push(requestOptions);
      const request = new EventEmitter() as ClientRequest & EventEmitter;
      Object.assign(request, {
        setTimeout: vi.fn(() => request),
        destroy: vi.fn(() => request),
        end: vi.fn((body?: Buffer) => {
          bodies.push(body ?? Buffer.alloc(0));
          const next = queued.shift();
          if (!next) {
            throw new Error("Unexpected HTTP request");
          }
          queueMicrotask(() =>
            response(
              callback,
              next.status,
              next.body === undefined ? "" : JSON.stringify(next.body)
            )
          );
          return request;
        })
      });
      return request;
    }
  };
}

function claimBody(overrides: Record<string, unknown> = {}) {
  const root = "/private/data/provider-attempts/attempt-1";
  return {
    attempt_id: "a".repeat(32),
    job_id: "b".repeat(32),
    claim_id: "c".repeat(32),
    policy: "codex_then_cursor",
    candidates: ["codex_cli", "cursor_cli"],
    cursor_consent: {
      subject: "cursor_cli_fallback",
      version: 1,
      granted: true,
      granted_at: "2026-07-31T12:00:00+00:00"
    },
    input_sha256: "d".repeat(64),
    attempt_directory: root,
    request_path: `${root}/request.json`,
    evidence_path: `${root}/evidence.json`,
    schema_path: `${root}/schema.json`,
    prompt_path: `${root}/prompt.txt`,
    output_path: `${root}/result.json`,
    ...overrides
  };
}

describe("ProviderAttemptClient", () => {
  it("returns no work for 204 and authenticates only to the sidecar UDS", async () => {
    const fake = transport([{ status: 204 }]);
    const client = new ProviderAttemptClient("/private/data", fake);
    await expect(client.claimNext(connection)).resolves.toBeUndefined();
    expect(fake.options[0]).toMatchObject({
      socketPath: connection.socketPath,
      path: "/api/desktop/provider-attempts/claim-next",
      method: "POST",
      headers: {
        Authorization: `Bearer ${connection.token}`,
        "X-LCF-Protocol-Version": "1.0",
        "X-LCF-Launch-ID": connection.launchId
      }
    });
    expect(JSON.parse(fake.bodies[0]!.toString("utf8"))).toEqual({
      lease_seconds: 120
    });
  });

  it("parses a strict private claim and converts consent spelling", async () => {
    const fake = transport([{ status: 200, body: claimBody() }]);
    const client = new ProviderAttemptClient("/private/data", fake);
    await expect(client.claimNext(connection)).resolves.toMatchObject({
      attemptId: "a".repeat(32),
      jobId: "b".repeat(32),
      claimId: "c".repeat(32),
      policy: "codex_then_cursor",
      candidates: ["codex_cli", "cursor_cli"],
      cursorConsent: {
        subject: "cursor_cli_fallback",
        version: 1,
        granted: true,
        grantedAt: "2026-07-31T12:00:00+00:00"
      },
      outputPath: "/private/data/provider-attempts/attempt-1/result.json"
    });
  });

  it.each([
    { attempt_directory: "/outside/attempt" },
    { prompt_path: "/private/data/provider-attempts/other/prompt.txt" },
    { output_path: "/private/data/provider-attempts/attempt-1/../result.json" },
    { extra: "field" }
  ])("rejects an invalid private claim %#", async (overrides) => {
    const fake = transport([
      { status: 200, body: claimBody(overrides) }
    ]);
    const client = new ProviderAttemptClient("/private/data", fake);
    await expect(client.claimNext(connection)).rejects.toMatchObject({
      code: "invalid-response"
    });
  });

  it("sends a bounded executable identity and validates the commit receipt", async () => {
    const fake = transport([
      { status: 200, body: {} },
      {
        status: 200,
        body: {
          attempt_id: "a".repeat(32),
          claim_id: "c".repeat(32),
          selected_provider: "codex_cli",
          executable_sha256: "e".repeat(64),
          execution_committed_at: "2026-07-31T12:01:00+00:00"
        }
      }
    ]);
    const client = new ProviderAttemptClient("/private/data", fake);
    const attempt = {
      attemptId: "a".repeat(32),
      jobId: "b".repeat(32),
      claimId: "c".repeat(32),
      policy: "codex_only" as const,
      candidates: ["codex_cli" as const],
      inputSha256: "d".repeat(64),
      attemptDirectory: "/private/data/provider-attempts/attempt-1",
      requestPath: "/private/data/provider-attempts/attempt-1/request.json",
      evidencePath: "/private/data/provider-attempts/attempt-1/evidence.json",
      schemaPath: "/private/data/provider-attempts/attempt-1/schema.json",
      promptPath: "/private/data/provider-attempts/attempt-1/prompt.txt",
      outputPath: "/private/data/provider-attempts/attempt-1/result.json"
    };
    await client.select(connection, attempt, {
      provider: "codex_cli",
      version: "0.146.0",
      identity: {
        canonicalPath: "/opt/codex",
        sha256: "e".repeat(64),
        size: 100,
        mtimeMs: 123,
        device: 1,
        inode: 2,
        mode: 0o100755
      }
    });
    expect(JSON.parse(fake.bodies[0]!.toString("utf8"))).toMatchObject({
      claim_id: "c".repeat(32),
      provider: "codex_cli",
      fallback_reason: null,
      executable_identity: {
        canonical_path: "/opt/codex",
        sha256: "e".repeat(64),
        version: "0.146.0"
      }
    });
    await expect(client.commit(connection, attempt)).resolves.toEqual({
      attemptId: "a".repeat(32),
      claimId: "c".repeat(32),
      selectedProvider: "codex_cli",
      executableSha256: "e".repeat(64),
      executionCommittedAt: "2026-07-31T12:01:00+00:00"
    });
  });
});

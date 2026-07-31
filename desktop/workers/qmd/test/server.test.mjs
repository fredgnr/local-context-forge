import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { chmod, lstat, mkdtemp, realpath, rm } from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  closePrivateSocket,
  createWorkerServer,
  listenOnPrivateSocket
} from "../src/server.mjs";

const TOKEN = "a".repeat(43);
const LAUNCH_ID = "01234567-89ab-4cde-8fab-0123456789ab";
const SHA256 = "b".repeat(64);

function request(socketPath, { method = "GET", requestPath = "/health", token = TOKEN, body }) {
  return new Promise((resolve, reject) => {
    const payload = body === undefined ? undefined : Buffer.from(JSON.stringify(body));
    const request = http.request(
      {
        socketPath,
        path: requestPath,
        method,
        agent: false,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(payload
            ? {
                "Content-Type": "application/json",
                "Content-Length": String(payload.length)
              }
            : {}),
          "X-LCF-Protocol-Version": "1.1",
          "X-LCF-Launch-Id": LAUNCH_ID,
          "X-LCF-Request-Id": randomUUID(),
          "X-LCF-Deadline-Ms": String(Date.now() + 5_000)
        }
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
        response.on("end", () =>
          resolve({
            status: response.statusCode,
            body: JSON.parse(Buffer.concat(chunks).toString("utf8"))
          })
        );
      }
    );
    request.once("error", reject);
    request.end(payload);
  });
}

async function bindOrSkip(t, server, socketPath) {
  try {
    return await listenOnPrivateSocket(server, socketPath);
  } catch (error) {
    if (error?.code === "EPERM" && process.env.CI?.toLowerCase() !== "true") {
      t.skip("execution sandbox prohibits AF_UNIX socket creation");
      return undefined;
    }
    throw error;
  }
}

test("real UDS server requires authentication and binds mode 0600", async (t) => {
  const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), "lcf-qmd-uds-"));
  const root = await realpath(temporaryRoot);
  await chmod(root, 0o700);
  const socketPath = path.join(root, "qmd.sock");
  const service = {
    status: () => ({
      revision: null,
      collections: 0,
      embedding: {
        status: "stale",
        profile: null,
        revision: null,
        model_status: "not_requested",
        error: null
      },
      activity: "idle"
    }),
    reconcile: async (body) => ({ indexed: true, ...body }),
    search: async (body) => ({
      revision: body.revision,
      mode: body.mode,
      results: []
    })
  };
  const server = createWorkerServer({
    token: TOKEN,
    launchId: LAUNCH_ID,
    buildManifestSha256: SHA256,
    service
  });
  const identity = await bindOrSkip(t, server, socketPath);
  if (!identity) {
    await rm(temporaryRoot, { recursive: true, force: true });
    return;
  }
  t.after(async () => {
    await closePrivateSocket(server, socketPath, identity).catch(() => undefined);
    await rm(temporaryRoot, { recursive: true, force: true });
  });

  const metadata = await lstat(socketPath);
  assert.equal(metadata.mode & 0o777, 0o600);
  assert.equal(
    (await request(socketPath, { token: "z".repeat(43) })).status,
    401
  );
  const health = await request(socketPath, {});
  assert.equal(health.status, 200);
  assert.equal(health.body.role, "qmd-worker");
  assert.equal(health.body.launch_id, LAUNCH_ID);
  assert.equal(JSON.stringify(health.body).includes(TOKEN), false);
});

test("worker HTTP contract returns explicit too_many_collections without calling service", async (t) => {
  const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), "lcf-qmd-uds-"));
  const root = await realpath(temporaryRoot);
  await chmod(root, 0o700);
  const socketPath = path.join(root, "qmd.sock");
  let calls = 0;
  const server = createWorkerServer({
    token: TOKEN,
    launchId: LAUNCH_ID,
    buildManifestSha256: SHA256,
    service: {
      status: () => ({
        revision: null,
        collections: 0,
        embedding: {
          status: "stale",
          profile: null,
          revision: null,
          model_status: "not_requested",
          error: null
        },
        activity: "idle"
      }),
      reconcile: async () => {
        calls += 1;
        return {};
      },
      search: async () => ({})
    }
  });
  const identity = await bindOrSkip(t, server, socketPath);
  if (!identity) {
    await rm(temporaryRoot, { recursive: true, force: true });
    return;
  }
  t.after(async () => {
    await closePrivateSocket(server, socketPath, identity).catch(() => undefined);
    await rm(temporaryRoot, { recursive: true, force: true });
  });

  const response = await request(socketPath, {
    method: "POST",
    requestPath: "/reconcile",
    body: {
      revision: 1,
      collections: Array.from({ length: 257 }, (_, index) => ({
        name: `collection-${index}`,
        wiki_root: "alpha/versions/v1"
      })),
      embedding: { mode: "lexical", profile: null }
    }
  });
  assert.deepEqual(response, {
    status: 422,
    body: { error: "too_many_collections" }
  });
  assert.equal(calls, 0);
});

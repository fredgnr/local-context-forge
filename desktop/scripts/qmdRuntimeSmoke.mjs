import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import {
  chmod,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rm,
  writeFile
} from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const EXPECTED_NODE_VERSION = "v22.23.2";
const EXPECTED_QMD_VERSION = "2.5.3";
const PROTOCOL_VERSION = "1.1";
const DEADLINE_MS = 15_000;
const STARTUP_TIMEOUT_MS = 45_000;

function parseArguments(argv) {
  if (argv.length !== 4) {
    throw new Error("native smoke requires --worker and --manifest-sha256");
  }
  const values = new Map();
  for (let index = 0; index < argv.length; index += 2) {
    values.set(argv[index], argv[index + 1]);
  }
  if (
    values.size !== 2 ||
    !values.has("--worker") ||
    !values.has("--manifest-sha256")
  ) {
    throw new Error("native smoke arguments are invalid");
  }
  const worker = values.get("--worker");
  const manifestSha256 = values.get("--manifest-sha256");
  if (
    !path.isAbsolute(worker) ||
    path.normalize(worker) !== worker ||
    !SHA256_PATTERN.test(manifestSha256)
  ) {
    throw new Error("native smoke inputs are invalid");
  }
  return { worker, manifestSha256 };
}

function request(
  socketPath,
  { token, launchId, method = "GET", requestPath = "/health", body }
) {
  return new Promise((resolve, reject) => {
    const payload =
      body === undefined
        ? undefined
        : Buffer.from(JSON.stringify(body), "utf8");
    const request_ = http.request(
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
          "X-LCF-Protocol-Version": PROTOCOL_VERSION,
          "X-LCF-Launch-Id": launchId,
          "X-LCF-Request-Id": randomUUID(),
          "X-LCF-Deadline-Ms": String(Date.now() + DEADLINE_MS)
        },
        timeout: DEADLINE_MS
      },
      (response) => {
        const chunks = [];
        let length = 0;
        response.on("data", (chunk) => {
          length += chunk.length;
          if (length > 2 * 1024 * 1024) {
            request_.destroy(new Error("native smoke response is too large"));
            return;
          }
          chunks.push(Buffer.from(chunk));
        });
        response.on("end", () => {
          try {
            resolve({
              status: response.statusCode,
              body: JSON.parse(Buffer.concat(chunks).toString("utf8"))
            });
          } catch (error) {
            reject(error);
          }
        });
      }
    );
    request_.once("error", reject);
    request_.once("timeout", () => {
      request_.destroy(new Error("native smoke request timed out"));
    });
    request_.end(payload);
  });
}

async function waitForHealth(socketPath, token, launchId) {
  const deadline = Date.now() + STARTUP_TIMEOUT_MS;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await request(socketPath, { token, launchId });
      if (response.status === 200) {
        return response;
      }
      lastError = new Error(`unexpected health status ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw lastError ?? new Error("QMD worker did not become ready");
}

async function listModelPayloads(root) {
  const matches = [];
  async function visit(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const candidate = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) {
        matches.push(candidate);
      } else if (entry.isDirectory()) {
        if (/^(?:models?|embeddings?)$/i.test(entry.name)) {
          matches.push(candidate);
        }
        await visit(candidate);
      } else if (/\.(?:gguf|onnx)$/i.test(entry.name)) {
        matches.push(candidate);
      }
    }
  }
  await visit(root);
  return matches;
}

async function waitForExit(child, timeoutMs) {
  if (child.exitCode !== null) {
    return child.exitCode;
  }
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error("QMD worker did not stop after control-pipe EOF"));
    }, timeoutMs);
    child.once("exit", (code) => {
      clearTimeout(timer);
      resolve(code);
    });
  });
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  assert.equal(process.version, EXPECTED_NODE_VERSION);
  const workerInfo = await lstat(options.worker);
  assert.equal(workerInfo.isFile(), true);
  assert.equal(workerInfo.isSymbolicLink(), false);
  assert.equal(await realpath(options.worker), options.worker);

  const temporaryRoot = await mkdtemp("/tmp/lcf-qmd-native-");
  await chmod(temporaryRoot, 0o700);
  const wikiRoot = path.join(temporaryRoot, "wiki");
  const collectionRoot = path.join(wikiRoot, "alpha", "versions", "v1");
  const dataRoot = path.join(temporaryRoot, "data");
  const cacheRoot = path.join(temporaryRoot, "cache");
  const configRoot = path.join(temporaryRoot, "config");
  await mkdir(collectionRoot, { recursive: true, mode: 0o700 });
  await mkdir(dataRoot, { recursive: true, mode: 0o700 });
  await mkdir(cacheRoot, { recursive: true, mode: 0o700 });
  await mkdir(configRoot, { recursive: true, mode: 0o700 });
  await writeFile(
    path.join(collectionRoot, "widget.md"),
    "# Widget API\n\nThe forge widget supports deterministic lexical lookup.\n",
    { encoding: "utf8", mode: 0o600 }
  );

  const socketPath = path.join(temporaryRoot, "q.sock");
  const launchId = randomUUID();
  const token = randomBytes(32).toString("base64url");
  assert.equal(token.length, 43);
  const trap = path.join(
    path.dirname(fileURLToPath(import.meta.url)),
    "qmdNetworkTrap.mjs"
  );
  const child = spawn(
    process.execPath,
    [
      "--import",
      trap,
      options.worker,
      "--uds",
      socketPath,
      "--launch-id",
      launchId,
      "--token-fd",
      "3",
      "--wiki-root",
      wikiRoot,
      "--data-dir",
      dataRoot,
      "--cache-root",
      cacheRoot,
      "--build-manifest-sha256",
      options.manifestSha256
    ],
    {
      cwd: temporaryRoot,
      env: {
        PATH: "/lcf-no-system-runtime",
        TMPDIR: temporaryRoot,
        XDG_CACHE_HOME: cacheRoot,
        XDG_CONFIG_HOME: configRoot,
        LANG: "C",
        LC_ALL: "C",
        CI: "true",
        LCF_QMD_NATIVE_SMOKE: "1"
      },
      stdio: ["ignore", "ignore", "pipe", "pipe"]
    }
  );
  let stderr = "";
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => {
    if (stderr.length < 32 * 1024) {
      stderr += chunk;
    }
  });

  try {
    child.stdio[3].write(`${token}\n`, "ascii");
    const health = await waitForHealth(socketPath, token, launchId);
    assert.equal(health.body.role, "qmd-worker");
    assert.equal(health.body.transport, "uds");
    assert.equal(health.body.launch_id, launchId);
    assert.equal(health.body.node_version, EXPECTED_NODE_VERSION.slice(1));
    assert.equal(health.body.qmd_version, EXPECTED_QMD_VERSION);
    assert.deepEqual(health.body.embedding, {
      status: "stale",
      profile: null,
      revision: null,
      model_status: "not_requested",
      error: null
    });
    assert.equal(health.body.activity, "idle");
    assert.equal(
      health.body.build_manifest_sha256,
      options.manifestSha256
    );
    assert.equal(JSON.stringify(health.body).includes(token), false);

    const rejected = await request(socketPath, {
      token: "z".repeat(43),
      launchId
    });
    assert.equal(rejected.status, 401);

    const collection = "lcf-alpha-v1-0123456789ab";
    const reconcile = await request(socketPath, {
      token,
      launchId,
      method: "POST",
      requestPath: "/reconcile",
      body: {
        revision: 7,
        collections: [
          {
            name: collection,
            wiki_root: "alpha/versions/v1"
          }
        ],
        embedding: {
          mode: "lexical",
          profile: null
        }
      }
    });
    assert.equal(reconcile.status, 200);
    assert.equal(reconcile.body.indexed, true);
    assert.equal(reconcile.body.revision, 7);
    assert.equal(reconcile.body.collections, 1);
    assert.deepEqual(reconcile.body.embedding, {
      status: "stale",
      profile: null,
      revision: null,
      model_status: "not_requested",
      error: null
    });

    const search = await request(socketPath, {
      token,
      launchId,
      method: "POST",
      requestPath: "/search",
      body: {
        revision: 7,
        collection,
        query: "deterministic widget",
        limit: 5,
        mode: "lexical",
        profile: null
      }
    });
    assert.equal(search.status, 200);
    assert.equal(search.body.revision, 7);
    assert.equal(search.body.mode, "lexical");
    assert.equal(Array.isArray(search.body.results), true);
    assert.equal(
      search.body.results.some(
        (item) =>
          typeof item.path === "string" &&
          item.path.endsWith("widget.md")
      ),
      true
    );

    assert.deepEqual(await listModelPayloads(temporaryRoot), []);
    assert.deepEqual(await listModelPayloads(cacheRoot), []);
    const socketInfo = await lstat(socketPath);
    assert.equal(socketInfo.isSocket(), true);
    assert.equal(socketInfo.mode & 0o777, 0o600);
  } catch (error) {
    if (stderr) {
      error.message = `${error.message}; worker stderr was captured (${stderr.length} bytes)`;
    }
    throw error;
  } finally {
    child.stdio[3].end();
    await waitForExit(child, 10_000).catch(() => undefined);
    child.kill("SIGKILL");
    await rm(temporaryRoot, { recursive: true, force: true });
  }

  if (child.exitCode !== 0) {
    throw new Error("QMD worker exited unsuccessfully");
  }
  process.stdout.write(
    `${JSON.stringify({
      status: "pass",
      pathTrap: true,
      networkTrap: true,
      modelFilesCreated: 0
    })}\n`
  );
}

await main();

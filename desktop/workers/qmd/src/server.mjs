import { timingSafeEqual } from "node:crypto";
import { chmod, lstat, realpath, unlink } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import {
  ContractError,
  MAX_REQUEST_BODY_BYTES,
  MAX_RESPONSE_BODY_BYTES,
  QMD_VERSION,
  QMD_WORKER_PROTOCOL_VERSION,
  isPlainObject,
  parseReconcileBody,
  parseSearchBody,
  validateSha256,
  validateSocketPath,
  validateToken,
  validateUuid
} from "./contract.mjs";

const REQUEST_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const MAX_DEADLINE_MS = 35 * 60 * 1_000;

function headerValues(request, expectedName) {
  const values = [];
  for (let index = 0; index < request.rawHeaders.length; index += 2) {
    if (request.rawHeaders[index]?.toLowerCase() === expectedName) {
      values.push(request.rawHeaders[index + 1] ?? "");
    }
  }
  return values;
}

function requiredHeader(request, name) {
  const values = headerValues(request, name.toLowerCase());
  if (values.length !== 1 || values[0].length === 0) {
    throw new ContractError(400, "invalid_request");
  }
  return values[0];
}

function authorized(request, expectedToken) {
  const authorization = requiredHeader(request, "authorization");
  const supplied = authorization.startsWith("Bearer ")
    ? authorization.slice("Bearer ".length)
    : "";
  const left = Buffer.from(supplied, "ascii");
  const right = Buffer.from(expectedToken, "ascii");
  return left.length === right.length && timingSafeEqual(left, right);
}

function validateHeaders(request, token, launchId) {
  if (!authorized(request, token)) {
    throw new ContractError(401, "unauthorized");
  }
  if (
    requiredHeader(request, "x-lcf-protocol-version") !==
    QMD_WORKER_PROTOCOL_VERSION
  ) {
    throw new ContractError(426, "protocol_mismatch");
  }
  if (requiredHeader(request, "x-lcf-launch-id") !== launchId) {
    throw new ContractError(403, "forbidden");
  }
  const requestId = requiredHeader(request, "x-lcf-request-id");
  if (!REQUEST_ID_PATTERN.test(requestId)) {
    throw new ContractError(400, "invalid_request");
  }
  const deadline = Number(requiredHeader(request, "x-lcf-deadline-ms"));
  const now = Date.now();
  if (
    !Number.isSafeInteger(deadline) ||
    deadline <= now ||
    deadline - now > MAX_DEADLINE_MS
  ) {
    throw new ContractError(deadline <= now ? 408 : 400, "invalid_request");
  }
}

async function readJsonBody(request) {
  const contentType = requiredHeader(request, "content-type")
    .split(";", 1)[0]
    .trim()
    .toLowerCase();
  if (contentType !== "application/json") {
    throw new ContractError(415, "invalid_request");
  }
  const declared = request.headers["content-length"];
  if (
    declared !== undefined &&
    (!/^[0-9]+$/.test(declared) ||
      Number(declared) > MAX_REQUEST_BODY_BYTES)
  ) {
    throw new ContractError(413, "request_too_large");
  }
  const chunks = [];
  let total = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    total += buffer.length;
    if (total > MAX_REQUEST_BODY_BYTES) {
      throw new ContractError(413, "request_too_large");
    }
    chunks.push(buffer);
  }
  let value;
  try {
    value = JSON.parse(Buffer.concat(chunks, total).toString("utf8"));
  } catch {
    throw new ContractError(400, "invalid_request");
  }
  if (!isPlainObject(value)) {
    throw new ContractError(422, "invalid_request");
  }
  return value;
}

function sendJson(response, status, value) {
  const body = Buffer.from(JSON.stringify(value), "utf8");
  if (body.length > MAX_RESPONSE_BODY_BYTES) {
    throw new ContractError(500, "response_too_large");
  }
  response.writeHead(status, {
    "Cache-Control": "no-store",
    Connection: "close",
    "Content-Length": String(body.length),
    "Content-Type": "application/json",
    "X-Content-Type-Options": "nosniff"
  });
  response.end(body);
}

export function createWorkerServer({
  token,
  launchId,
  buildManifestSha256,
  service
}) {
  validateToken(token);
  validateUuid(launchId);
  validateSha256(buildManifestSha256);

  return http.createServer(
    {
      keepAlive: false,
      maxHeaderSize: 16 * 1024,
      requestTimeout: MAX_DEADLINE_MS
    },
    async (request, response) => {
      try {
        validateHeaders(request, token, launchId);
        const url = new URL(request.url ?? "", "http://localhost");
        if (url.search || url.hash) {
          throw new ContractError(404, "not_found");
        }
        if (request.method === "GET" && url.pathname === "/health") {
          sendJson(response, 200, {
            service: "local-context-forge",
            role: "qmd-worker",
            protocol: { major: 1, minor: 1 },
            launch_id: launchId,
            transport: "uds",
            qmd_version: QMD_VERSION,
            node_version: process.versions.node,
            build_manifest_sha256: buildManifestSha256,
            ...service.status()
          });
          return;
        }
        if (
          request.method === "POST" &&
          (url.pathname === "/reconcile" || url.pathname === "/search")
        ) {
          const body = await readJsonBody(request);
          const result =
            url.pathname === "/reconcile"
              ? await service.reconcile(parseReconcileBody(body))
              : await service.search(parseSearchBody(body));
          sendJson(response, 200, result);
          return;
        }
        throw new ContractError(404, "not_found");
      } catch (error) {
        const rejected =
          error instanceof ContractError
            ? error
            : new ContractError(500, "worker_error");
        if (!response.headersSent) {
          sendJson(response, rejected.status, { error: rejected.code });
        } else {
          response.destroy();
        }
      }
    }
  );
}

function effectiveUid() {
  return process.geteuid?.() ?? process.getuid?.() ?? -1;
}

export async function listenOnPrivateSocket(server, socketPath) {
  validateSocketPath(socketPath);
  const parent = path.dirname(socketPath);
  const parentInfo = await lstat(parent).catch(() => undefined);
  if (
    !parentInfo?.isDirectory() ||
    parentInfo.isSymbolicLink() ||
    parentInfo.uid !== effectiveUid() ||
    (parentInfo.mode & 0o777) !== 0o700 ||
    (await realpath(parent)) !== parent
  ) {
    throw new ContractError(400, "invalid_path");
  }
  if (await lstat(socketPath).catch(() => undefined)) {
    throw new ContractError(400, "invalid_path");
  }

  await new Promise((resolve, reject) => {
    const onError = (error) => {
      server.off("listening", onListening);
      reject(error);
    };
    const onListening = () => {
      server.off("error", onError);
      resolve();
    };
    server.once("error", onError);
    server.once("listening", onListening);
    server.listen(socketPath);
  });
  await chmod(socketPath, 0o600);
  const info = await lstat(socketPath);
  if (
    !info.isSocket() ||
    info.isSymbolicLink() ||
    info.uid !== effectiveUid() ||
    (info.mode & 0o777) !== 0o600
  ) {
    throw new ContractError(500, "invalid_path");
  }
  return { device: info.dev, inode: info.ino };
}

export async function closePrivateSocket(server, socketPath, identity) {
  const closed = new Promise((resolve) => server.close(() => resolve()));
  server.closeAllConnections();
  await closed;
  const info = await lstat(socketPath).catch(() => undefined);
  if (
    info?.isSocket() &&
    !info.isSymbolicLink() &&
    info.dev === identity.device &&
    info.ino === identity.inode
  ) {
    await unlink(socketPath).catch((error) => {
      if (error?.code !== "ENOENT") {
        throw error;
      }
    });
  }
}

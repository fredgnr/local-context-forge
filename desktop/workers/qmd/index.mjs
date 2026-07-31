#!/usr/bin/env node

import { createReadStream, readSync } from "node:fs";
import { chmod, lstat, mkdir, realpath } from "node:fs/promises";
import path from "node:path";
import {
  ContractError,
  validateAbsolutePath,
  validateSha256,
  validateSocketPath,
  validateToken,
  validateUuid
} from "./src/contract.mjs";
import { FileStateStore, QmdIndexService } from "./src/indexService.mjs";
import {
  closePrivateSocket,
  createWorkerServer,
  listenOnPrivateSocket
} from "./src/server.mjs";

function parseArguments(argv) {
  const allowed = new Set([
    "--uds",
    "--launch-id",
    "--token-fd",
    "--wiki-root",
    "--data-dir",
    "--cache-root",
    "--build-manifest-sha256"
  ]);
  if (argv.length !== allowed.size * 2) {
    throw new ContractError(400, "invalid_request");
  }
  const values = new Map();
  for (let index = 0; index < argv.length; index += 2) {
    const name = argv[index];
    const value = argv[index + 1];
    if (!allowed.has(name) || values.has(name) || value === undefined) {
      throw new ContractError(400, "invalid_request");
    }
    values.set(name, value);
  }
  if (values.get("--token-fd") !== "3") {
    throw new ContractError(400, "invalid_request");
  }
  return {
    socketPath: validateSocketPath(values.get("--uds")),
    launchId: validateUuid(values.get("--launch-id")),
    tokenFd: 3,
    wikiRoot: validateAbsolutePath(values.get("--wiki-root")),
    dataDir: validateAbsolutePath(values.get("--data-dir")),
    cacheRoot: validateAbsolutePath(values.get("--cache-root")),
    buildManifestSha256: validateSha256(
      values.get("--build-manifest-sha256")
    )
  };
}

function readFramedToken(fd) {
  const bytes = [];
  const one = Buffer.allocUnsafe(1);
  try {
    for (;;) {
      const count = readSync(fd, one, 0, 1, null);
      if (count === 0) {
        throw new ContractError(400, "invalid_request");
      }
      if (one[0] === 0x0a) {
        break;
      }
      bytes.push(one[0]);
      if (bytes.length > 43) {
        throw new ContractError(400, "invalid_request");
      }
    }
    return validateToken(Buffer.from(bytes).toString("ascii"));
  } finally {
    one.fill(0);
    bytes.fill(0);
  }
}

async function validatePrivateDirectory(directory) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const info = await lstat(directory);
  const uid = process.geteuid?.() ?? process.getuid?.() ?? -1;
  if (
    !info.isDirectory() ||
    info.isSymbolicLink() ||
    info.uid !== uid ||
    (await realpath(directory)) !== directory
  ) {
    throw new ContractError(400, "invalid_path");
  }
  await chmod(directory, 0o700);
}

async function main() {
  process.umask(0o077);
  const options = parseArguments(process.argv.slice(2));
  await validatePrivateDirectory(options.dataDir);
  await validatePrivateDirectory(options.cacheRoot);
  const token = readFramedToken(options.tokenFd);
  process.env.XDG_CACHE_HOME = options.cacheRoot;
  const { createStore } = await import("@tobilu/qmd");
  const dbPath = path.join(options.dataDir, "index.sqlite");
  const store = await createStore({
    dbPath
  });
  const service = new QmdIndexService({
    store,
    openStore: async (profile, collections) =>
      createStore({
        dbPath,
        config: {
          collections: Object.fromEntries(
            collections.map((item) => [
              item.name,
              {
                path: item.absoluteRoot,
                pattern: "**/*.md"
              }
            ])
          ),
          ...(profile ? { models: { embed: profile.model } } : {})
        }
      }),
    wikiRoot: options.wikiRoot,
    modelCacheDir: path.join(options.cacheRoot, "qmd", "models"),
    stateStore: new FileStateStore(path.join(options.dataDir, "state.json"))
  });
  await service.initialize();
  const server = createWorkerServer({
    token,
    launchId: options.launchId,
    buildManifestSha256: options.buildManifestSha256,
    service
  });
  const identity = await listenOnPrivateSocket(server, options.socketPath);
  let closing = false;
  const shutdown = async () => {
    if (closing) {
      return;
    }
    closing = true;
    await closePrivateSocket(server, options.socketPath, identity).catch(
      () => undefined
    );
    await service.close().catch(() => undefined);
  };
  const liveness = createReadStream("", {
    fd: options.tokenFd,
    autoClose: true
  });
  liveness.once("data", () => void shutdown());
  liveness.once("end", () => void shutdown());
  liveness.once("error", () => void shutdown());
  process.once("SIGTERM", () => void shutdown());
  process.once("SIGINT", () => void shutdown());
}

main().catch(() => {
  process.exitCode = 2;
});

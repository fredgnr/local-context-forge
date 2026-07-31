import {
  randomBytes as nodeRandomBytes,
  randomUUID as nodeRandomUUID
} from "node:crypto";
import { constants as fsConstants } from "node:fs";
import {
  access,
  chmod,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rm
} from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import {
  spawn as nodeSpawn,
  type ChildProcess,
  type SpawnOptions
} from "node:child_process";
import type { Writable } from "node:stream";
import {
  QMD_NODE_VERSION,
  QMD_WORKER_VERSION,
  QmdClient,
  QmdClientError,
  type QmdConnection
} from "./qmdClient";

const RUNTIME_DIRECTORY_NAME = "dev.local-context-forge.desktop";
const QMD_SOCKET_NAME = "qmd.sock";
const MAX_UDS_PATH_BYTES = 100;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export interface QmdRuntimeConfiguration {
  nodeExecutable: string;
  workerEntry: string;
  buildManifestSha256: string;
}

export interface QmdRuntimePaths {
  directory: string;
  socketPath: string;
}

export type QmdRuntimeState =
  | "stopped"
  | "starting"
  | "ready"
  | "stopping"
  | "failed";

export type QmdRuntimeFailureReason =
  | "configuration"
  | "launch-failed"
  | "runtime-invalid"
  | "startup-timeout"
  | "handshake-rejected"
  | "worker-exited"
  | "shutdown-timeout";

export interface QmdRuntimeStatus {
  state: QmdRuntimeState;
  canRetry: boolean;
  reason?: QmdRuntimeFailureReason;
}

interface QmdChild {
  readonly pid?: number;
  readonly exitCode: number | null;
  readonly signalCode: NodeJS.Signals | null;
  readonly stdio: readonly (NodeJS.ReadableStream | Writable | null)[];
  once(
    event: "exit",
    listener: (code: number | null, signal: NodeJS.Signals | null) => void
  ): this;
  once(event: "error", listener: (error: Error) => void): this;
  kill(signal?: NodeJS.Signals | number): boolean;
}

type SpawnQmd = (
  executable: string,
  args: readonly string[],
  options: SpawnOptions
) => QmdChild;

interface QmdSession {
  launchId: string;
  token: string;
  runtime: QmdRuntimePaths;
  child: QmdChild;
  controlPipe: Writable;
  client: QmdClient;
  exit: Promise<void>;
  exited: boolean;
  processError: boolean;
  intentionalStop: boolean;
}

export interface QmdSupervisorOptions {
  runtime: QmdRuntimeConfiguration;
  appDataDir: string;
  dataDir: string;
  wikiRoot: string;
  tempRoot?: string;
  startupTimeoutMs?: number;
  pollIntervalMs?: number;
  shutdownTimeoutMs?: number;
}

export interface QmdSupervisorDependencies {
  spawn?: SpawnQmd;
  randomBytes?: (size: number) => Buffer;
  randomUUID?: () => string;
  createRuntime?: (
    launchId: string,
    tempRoot: string
  ) => Promise<QmdRuntimePaths>;
  inspectSocket?: (socketPath: string) => Promise<"missing" | "valid">;
  cleanupRuntime?: (runtime: QmdRuntimePaths) => Promise<void>;
  validateRuntime?: (runtime: QmdRuntimeConfiguration) => Promise<void>;
  prepareDataPaths?: (
    appDataDir: string,
    dataDir: string,
    wikiRoot: string
  ) => Promise<void>;
  createClient?: (connection: QmdConnection) => QmdClient;
  wait?: (milliseconds: number) => Promise<void>;
  now?: () => number;
}

class QmdSupervisorFailure extends Error {
  constructor(readonly reason: QmdRuntimeFailureReason) {
    super(`QMD supervisor failure (${reason})`);
    this.name = "QmdSupervisorFailure";
  }
}

function effectiveUid(): number {
  return process.geteuid?.() ?? process.getuid?.() ?? -1;
}

async function verifyPrivateDirectory(directory: string): Promise<void> {
  const info = await lstat(directory).catch(() => undefined);
  if (
    !info?.isDirectory() ||
    info.isSymbolicLink() ||
    info.uid !== effectiveUid()
  ) {
    throw new QmdSupervisorFailure("runtime-invalid");
  }
  await chmod(directory, 0o700);
  const verified = await lstat(directory);
  if ((verified.mode & 0o777) !== 0o700) {
    throw new QmdSupervisorFailure("runtime-invalid");
  }
}

async function assertNoSymlinkComponents(
  absolutePath: string,
  finalKind: "file" | "directory"
): Promise<void> {
  if (!path.isAbsolute(absolutePath) || path.normalize(absolutePath) !== absolutePath) {
    throw new QmdSupervisorFailure("configuration");
  }
  const parsed = path.parse(absolutePath);
  let current = parsed.root;
  for (const part of absolutePath.slice(parsed.root.length).split(path.sep)) {
    if (!part) {
      continue;
    }
    current = path.join(current, part);
    const info = await lstat(current).catch(() => undefined);
    if (!info || info.isSymbolicLink()) {
      throw new QmdSupervisorFailure("configuration");
    }
  }
  const final = await lstat(absolutePath);
  if (
    (finalKind === "file" && !final.isFile()) ||
    (finalKind === "directory" && !final.isDirectory()) ||
    (await realpath(absolutePath)) !== absolutePath
  ) {
    throw new QmdSupervisorFailure("configuration");
  }
}

export async function resolveQmdRuntimeConfiguration(input: {
  packaged: boolean;
  resourcesPath: string;
  environment?: NodeJS.ProcessEnv;
}): Promise<QmdRuntimeConfiguration> {
  if (input.packaged) {
    if (!path.isAbsolute(input.resourcesPath)) {
      throw new QmdSupervisorFailure("configuration");
    }
    const root = path.join(input.resourcesPath, "qmd");
    const digestPath = path.join(root, "runtime-manifest.sha256");
    await assertNoSymlinkComponents(digestPath, "file");
    const digestContents = await readFile(digestPath, "utf8");
    if (!/^[0-9a-f]{64}\n?$/.test(digestContents)) {
      throw new QmdSupervisorFailure("configuration");
    }
    return {
      nodeExecutable: path.join(root, "node", "bin", "node"),
      workerEntry: path.join(root, "worker", "index.mjs"),
      buildManifestSha256: digestContents.trim()
    };
  }

  const nodeExecutable = input.environment?.LCF_QMD_NODE_BIN;
  const workerEntry = input.environment?.LCF_QMD_WORKER_ENTRY;
  const buildManifestSha256 =
    input.environment?.LCF_QMD_BUILD_MANIFEST_SHA256;
  if (
    !nodeExecutable ||
    !workerEntry ||
    !path.isAbsolute(nodeExecutable) ||
    !path.isAbsolute(workerEntry) ||
    !SHA256_PATTERN.test(buildManifestSha256 ?? "")
  ) {
    throw new QmdSupervisorFailure("configuration");
  }
  return {
    nodeExecutable: path.normalize(nodeExecutable),
    workerEntry: path.normalize(workerEntry),
    buildManifestSha256: buildManifestSha256!
  };
}

export async function validateQmdRuntime(
  runtime: QmdRuntimeConfiguration
): Promise<void> {
  if (!SHA256_PATTERN.test(runtime.buildManifestSha256)) {
    throw new QmdSupervisorFailure("configuration");
  }
  await assertNoSymlinkComponents(runtime.nodeExecutable, "file");
  await assertNoSymlinkComponents(runtime.workerEntry, "file");
  await access(runtime.nodeExecutable, fsConstants.X_OK).catch(() => {
    throw new QmdSupervisorFailure("configuration");
  });
  await access(runtime.workerEntry, fsConstants.R_OK).catch(() => {
    throw new QmdSupervisorFailure("configuration");
  });
}

export async function prepareQmdDataPaths(
  appDataDir: string,
  dataDir: string,
  wikiRoot: string
): Promise<void> {
  if (
    !path.isAbsolute(appDataDir) ||
    !path.isAbsolute(dataDir) ||
    !path.isAbsolute(wikiRoot)
  ) {
    throw new QmdSupervisorFailure("configuration");
  }
  await verifyPrivateDirectory(appDataDir);
  const canonicalRoot = await realpath(appDataDir);
  if (canonicalRoot !== appDataDir) {
    throw new QmdSupervisorFailure("configuration");
  }
  for (const target of [dataDir, wikiRoot]) {
    const relative = path.relative(canonicalRoot, target);
    if (
      relative === "" ||
      relative === ".." ||
      relative.startsWith(`..${path.sep}`) ||
      path.isAbsolute(relative)
    ) {
      throw new QmdSupervisorFailure("configuration");
    }
    let current = canonicalRoot;
    for (const part of relative.split(path.sep)) {
      current = path.join(current, part);
      await mkdir(current, { mode: 0o700 }).catch(
        (error: NodeJS.ErrnoException) => {
          if (error.code !== "EEXIST") {
            throw error;
          }
        }
      );
      await verifyPrivateDirectory(current);
    }
  }
}

export async function createPrivateQmdRuntime(
  launchId: string,
  tempRoot: string
): Promise<QmdRuntimePaths> {
  if (!UUID_PATTERN.test(launchId) || !path.isAbsolute(tempRoot)) {
    throw new QmdSupervisorFailure("configuration");
  }
  const tempInfo = await lstat(tempRoot).catch(() => undefined);
  if (!tempInfo?.isDirectory() || tempInfo.isSymbolicLink()) {
    throw new QmdSupervisorFailure("runtime-invalid");
  }
  const canonicalTempRoot = await realpath(tempRoot);
  const base = path.join(canonicalTempRoot, RUNTIME_DIRECTORY_NAME);
  await mkdir(base, { recursive: true, mode: 0o700 });
  await verifyPrivateDirectory(base);

  let directory = path.join(base, `${launchId}-qmd`);
  await mkdir(directory, { mode: 0o700 });
  await verifyPrivateDirectory(directory);
  let socketPath = path.join(directory, QMD_SOCKET_NAME);
  if (Buffer.byteLength(socketPath, "utf8") > MAX_UDS_PATH_BYTES) {
    await cleanupPrivateQmdRuntime({ directory, socketPath });
    directory = await mkdtemp(path.join(canonicalTempRoot, "lcf-q-"));
    await verifyPrivateDirectory(directory);
    socketPath = path.join(directory, QMD_SOCKET_NAME);
  }
  if (Buffer.byteLength(socketPath, "utf8") > MAX_UDS_PATH_BYTES) {
    await cleanupPrivateQmdRuntime({ directory, socketPath });
    throw new QmdSupervisorFailure("runtime-invalid");
  }
  return { directory, socketPath };
}

export async function inspectPrivateQmdSocket(
  socketPath: string
): Promise<"missing" | "valid"> {
  const info = await lstat(socketPath).catch(
    (error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") {
        return undefined;
      }
      throw error;
    }
  );
  if (!info) {
    return "missing";
  }
  if (
    !info.isSocket() ||
    info.isSymbolicLink() ||
    info.uid !== effectiveUid() ||
    (info.mode & 0o777) !== 0o600
  ) {
    throw new QmdSupervisorFailure("runtime-invalid");
  }
  return "valid";
}

export async function cleanupPrivateQmdRuntime(
  runtime: QmdRuntimePaths
): Promise<void> {
  const info = await lstat(runtime.directory).catch(
    (error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") {
        return undefined;
      }
      throw error;
    }
  );
  if (!info) {
    return;
  }
  if (
    !info.isDirectory() ||
    info.isSymbolicLink() ||
    info.uid !== effectiveUid() ||
    (info.mode & 0o777) !== 0o700 ||
    path.dirname(runtime.socketPath) !== runtime.directory ||
    path.basename(runtime.socketPath) !== QMD_SOCKET_NAME
  ) {
    throw new QmdSupervisorFailure("runtime-invalid");
  }
  await rm(runtime.directory, { recursive: true, force: true });
}

const QMD_ENVIRONMENT_KEYS = [
  "HOME",
  "USER",
  "LOGNAME",
  "TMPDIR",
  "LANG",
  "LC_ALL",
  "LC_CTYPE",
  "TZ"
] as const;

export function buildQmdEnvironment(
  source: NodeJS.ProcessEnv
): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = {};
  for (const key of QMD_ENVIRONMENT_KEYS) {
    const value = source[key];
    if (typeof value === "string") {
      environment[key] = value;
    }
  }
  return environment;
}

function defaultSpawn(
  executable: string,
  args: readonly string[],
  options: SpawnOptions
): QmdChild {
  return nodeSpawn(executable, [...args], options) as ChildProcess as QmdChild;
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function writeToken(pipe: Writable, token: string): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    pipe.write(`${token}\n`, "utf8", (error) => {
      if (error) {
        reject(new QmdSupervisorFailure("launch-failed"));
      } else {
        resolve();
      }
    });
  });
}

export class QmdSupervisor {
  private status: QmdRuntimeStatus = { state: "stopped", canRetry: true };
  private session: QmdSession | undefined;
  private operation: Promise<QmdRuntimeStatus> | undefined;
  private unconfirmedChild = false;
  private readonly dependencies: Required<QmdSupervisorDependencies>;

  constructor(
    private readonly options: QmdSupervisorOptions,
    dependencies: QmdSupervisorDependencies = {}
  ) {
    this.dependencies = {
      spawn: dependencies.spawn ?? defaultSpawn,
      randomBytes: dependencies.randomBytes ?? nodeRandomBytes,
      randomUUID: dependencies.randomUUID ?? nodeRandomUUID,
      createRuntime:
        dependencies.createRuntime ?? createPrivateQmdRuntime,
      inspectSocket:
        dependencies.inspectSocket ?? inspectPrivateQmdSocket,
      cleanupRuntime:
        dependencies.cleanupRuntime ?? cleanupPrivateQmdRuntime,
      validateRuntime: dependencies.validateRuntime ?? validateQmdRuntime,
      prepareDataPaths:
        dependencies.prepareDataPaths ?? prepareQmdDataPaths,
      createClient:
        dependencies.createClient ??
        ((connection) => new QmdClient(connection)),
      wait: dependencies.wait ?? wait,
      now: dependencies.now ?? Date.now
    };
  }

  getStatus(): QmdRuntimeStatus {
    return { ...this.status };
  }

  getClient(): QmdClient | undefined {
    return this.status.state === "ready" ? this.session?.client : undefined;
  }

  async start(): Promise<QmdRuntimeStatus> {
    if (this.operation) {
      return this.operation;
    }
    if (this.status.state === "ready" || this.session || this.unconfirmedChild) {
      return this.getStatus();
    }
    this.operation = this.launch().finally(() => {
      this.operation = undefined;
    });
    return this.operation;
  }

  async restart(): Promise<QmdRuntimeStatus> {
    await this.shutdown();
    if (this.status.state === "failed" && !this.status.canRetry) {
      return this.getStatus();
    }
    return this.start();
  }

  async shutdown(): Promise<QmdRuntimeStatus> {
    if (this.operation) {
      await this.operation;
    }
    const current = this.session;
    if (!current) {
      if (this.unconfirmedChild) {
        this.status = {
          state: "failed",
          canRetry: false,
          reason: "shutdown-timeout"
        };
        return this.getStatus();
      }
      this.status = { state: "stopped", canRetry: true };
      return this.getStatus();
    }
    this.status = { state: "stopping", canRetry: false };
    current.intentionalStop = true;
    const exited = await this.terminate(current);
    if (exited) {
      if (this.session === current) {
        this.session = undefined;
      }
      this.status = { state: "stopped", canRetry: true };
    } else {
      this.status = {
        state: "failed",
        canRetry: false,
        reason: "shutdown-timeout"
      };
    }
    return this.getStatus();
  }

  private async launch(): Promise<QmdRuntimeStatus> {
    this.status = { state: "starting", canRetry: false };
    let runtime: QmdRuntimePaths | undefined;
    let session: QmdSession | undefined;
    let untrackedChild: QmdChild | undefined;
    try {
      await this.dependencies.validateRuntime(this.options.runtime);
      await this.dependencies.prepareDataPaths(
        this.options.appDataDir,
        this.options.dataDir,
        this.options.wikiRoot
      );
      const launchId = this.dependencies.randomUUID();
      if (!UUID_PATTERN.test(launchId)) {
        throw new QmdSupervisorFailure("launch-failed");
      }
      const rawToken = this.dependencies.randomBytes(32);
      if (rawToken.length !== 32) {
        rawToken.fill(0);
        throw new QmdSupervisorFailure("launch-failed");
      }
      const token = rawToken.toString("base64url");
      rawToken.fill(0);
      if (token.length !== 43) {
        throw new QmdSupervisorFailure("launch-failed");
      }
      runtime = await this.dependencies.createRuntime(
        launchId,
        this.options.tempRoot ?? os.tmpdir()
      );
      const args = [
        this.options.runtime.workerEntry,
        "--uds",
        runtime.socketPath,
        "--launch-id",
        launchId,
        "--token-fd",
        "3",
        "--wiki-root",
        this.options.wikiRoot,
        "--data-dir",
        this.options.dataDir,
        "--build-manifest-sha256",
        this.options.runtime.buildManifestSha256
      ] as const;
      const child = this.dependencies.spawn(
        this.options.runtime.nodeExecutable,
        args,
        {
          shell: false,
          windowsHide: true,
          stdio: ["ignore", "ignore", "ignore", "pipe"],
          env: buildQmdEnvironment(process.env)
        }
      );
      untrackedChild = child;
      const controlPipe = child.stdio[3];
      if (!controlPipe || typeof (controlPipe as Writable).write !== "function") {
        throw new QmdSupervisorFailure("launch-failed");
      }
      const connection: QmdConnection = {
        socketPath: runtime.socketPath,
        launchId,
        token,
        buildManifestSha256: this.options.runtime.buildManifestSha256
      };
      session = this.createSession(
        launchId,
        token,
        runtime,
        child,
        controlPipe as Writable,
        this.dependencies.createClient(connection)
      );
      untrackedChild = undefined;
      this.session = session;
      await writeToken(controlPipe as Writable, token);
      await this.waitUntilReady(session);
      if (session.exited) {
        throw new QmdSupervisorFailure("worker-exited");
      }
      this.status = { state: "ready", canRetry: false };
      return this.getStatus();
    } catch (error) {
      const reason =
        error instanceof QmdSupervisorFailure
          ? error.reason
          : error instanceof QmdClientError &&
              error.kind === "invalid-response"
            ? "handshake-rejected"
            : "launch-failed";
      if (session) {
        session.intentionalStop = true;
        const exited = await this.terminate(session).catch(() => false);
        if (!exited) {
          this.status = {
            state: "failed",
            canRetry: false,
            reason: "shutdown-timeout"
          };
          return this.getStatus();
        }
      } else if (untrackedChild) {
        const termination = await this.terminateUntrackedChild(untrackedChild);
        if (runtime && termination.exited) {
          await this.dependencies.cleanupRuntime(runtime).catch(
            () => undefined
          );
        } else if (runtime) {
          this.unconfirmedChild = true;
          void termination.exit.then(async () => {
            await this.dependencies.cleanupRuntime(runtime!).catch(
              () => undefined
            );
            this.unconfirmedChild = false;
            if (!this.session) {
              this.status = {
                state: "failed",
                canRetry: true,
                reason: "worker-exited"
              };
            }
          });
          this.status = {
            state: "failed",
            canRetry: false,
            reason: "shutdown-timeout"
          };
          return this.getStatus();
        }
      } else if (runtime) {
        await this.dependencies.cleanupRuntime(runtime).catch(() => undefined);
      }
      if (this.session === session) {
        this.session = undefined;
      }
      this.status = { state: "failed", canRetry: true, reason };
      return this.getStatus();
    }
  }

  private createSession(
    launchId: string,
    token: string,
    runtime: QmdRuntimePaths,
    child: QmdChild,
    controlPipe: Writable,
    client: QmdClient
  ): QmdSession {
    const session: QmdSession = {
      launchId,
      token,
      runtime,
      child,
      controlPipe,
      client,
      exited: child.exitCode !== null,
      processError: false,
      intentionalStop: false,
      exit: Promise.resolve()
    };
    session.exit = new Promise<void>((resolve) => {
      let settled = session.exited;
      const complete = () => {
        if (settled) {
          return;
        }
        settled = true;
        session.exited = true;
        resolve();
        if (!session.intentionalStop && this.session === session) {
          void this.handleUnexpectedExit(session);
        }
      };
      const processError = () => {
        session.processError = true;
        if (child.pid === undefined) {
          complete();
        }
      };
      controlPipe.on("error", processError);
      if (session.exited) {
        resolve();
      } else {
        child.once("exit", complete);
        child.once("error", processError);
      }
    });
    return session;
  }

  private async waitUntilReady(session: QmdSession): Promise<void> {
    const timeout = this.options.startupTimeoutMs ?? 15_000;
    const poll = this.options.pollIntervalMs ?? 100;
    const deadline = this.dependencies.now() + timeout;
    while (this.dependencies.now() < deadline) {
      if (session.processError) {
        throw new QmdSupervisorFailure("launch-failed");
      }
      if (session.exited) {
        throw new QmdSupervisorFailure("worker-exited");
      }
      const socket = await this.dependencies.inspectSocket(
        session.runtime.socketPath
      );
      if (socket === "valid") {
        try {
          await session.client.health(
            Math.max(1, Math.min(1_000, deadline - this.dependencies.now()))
          );
          return;
        } catch (error) {
          if (
            error instanceof QmdClientError &&
            error.kind === "invalid-response"
          ) {
            throw new QmdSupervisorFailure("handshake-rejected");
          }
        }
      }
      await this.dependencies.wait(poll);
    }
    throw new QmdSupervisorFailure("startup-timeout");
  }

  private async terminate(session: QmdSession): Promise<boolean> {
    session.intentionalStop = true;
    if (!session.controlPipe.destroyed) {
      session.controlPipe.end();
    }
    if (!session.exited) {
      await Promise.race([
        session.exit,
        this.dependencies.wait(this.options.shutdownTimeoutMs ?? 12_000)
      ]);
      if (!session.exited) {
        session.child.kill("SIGTERM");
        await Promise.race([session.exit, this.dependencies.wait(3_000)]);
      }
      if (!session.exited) {
        session.child.kill("SIGKILL");
        await Promise.race([session.exit, this.dependencies.wait(1_000)]);
      }
    }
    session.token = "";
    if (session.exited) {
      await this.dependencies.cleanupRuntime(session.runtime);
      return true;
    }
    void session.exit.then(async () => {
      await this.dependencies.cleanupRuntime(session.runtime).catch(
        () => undefined
      );
      if (this.session === session) {
        this.session = undefined;
        this.status = {
          state: "failed",
          canRetry: true,
          reason: "worker-exited"
        };
      }
    });
    return false;
  }

  private async terminateUntrackedChild(
    child: QmdChild
  ): Promise<{ exited: boolean; exit: Promise<void> }> {
    if (child.exitCode !== null) {
      return { exited: true, exit: Promise.resolve() };
    }
    let exited = false;
    const exit = new Promise<void>((resolve) => {
      child.once("exit", () => {
        exited = true;
        resolve();
      });
    });
    await Promise.race([
      exit,
      this.dependencies.wait(this.options.shutdownTimeoutMs ?? 12_000)
    ]);
    if (!exited) {
      child.kill("SIGTERM");
      await Promise.race([exit, this.dependencies.wait(3_000)]);
    }
    if (!exited) {
      child.kill("SIGKILL");
      await Promise.race([exit, this.dependencies.wait(1_000)]);
    }
    return { exited, exit };
  }

  private async handleUnexpectedExit(session: QmdSession): Promise<void> {
    if (this.session !== session) {
      return;
    }
    if (!session.controlPipe.destroyed) {
      session.controlPipe.end();
    }
    session.token = "";
    await this.dependencies.cleanupRuntime(session.runtime).catch(
      () => undefined
    );
    if (this.session === session) {
      this.session = undefined;
      this.status = {
        state: "failed",
        canRetry: true,
        reason: "worker-exited"
      };
    }
  }
}

export const QMD_RUNTIME_VERSIONS = {
  node: QMD_NODE_VERSION,
  qmd: QMD_WORKER_VERSION
} as const;

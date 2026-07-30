import { randomBytes as nodeRandomBytes, randomUUID as nodeRandomUUID } from "node:crypto";
import {
  access,
  chmod,
  lstat,
  mkdir,
  mkdtemp,
  realpath,
  rm
} from "node:fs/promises";
import { constants as fsConstants } from "node:fs";
import http, {
  type ClientRequest,
  type IncomingMessage,
  type RequestOptions
} from "node:http";
import os from "node:os";
import path from "node:path";
import {
  spawn as nodeSpawn,
  type ChildProcess,
  type SpawnOptions
} from "node:child_process";
import type { Writable } from "node:stream";
import {
  SIDECAR_PROTOCOL_VERSION,
  type RuntimeFailureReason,
  type RuntimeStatus
} from "../contracts";
import type { SidecarConnection } from "./apiProxy";

const RUNTIME_DIRECTORY_NAME = "dev.local-context-forge.desktop";
const SIDECAR_SOCKET_NAME = "py.sock";
const MAX_UDS_PATH_BYTES = 100;
const HANDSHAKE_PATH = "/api/desktop/handshake";
const HANDSHAKE_RESPONSE_LIMIT = 64 * 1024;

export interface RuntimePaths {
  directory: string;
  socketPath: string;
}

export interface HandshakeResponse {
  service: string;
  role: string;
  app_version: string;
  sidecar_version: string;
  protocol: {
    major: number;
    minor: number;
  };
  launch_id: string;
  transport: string;
  schema_version: number;
  capabilities: string[];
}

interface SidecarChild {
  readonly pid?: number;
  readonly exitCode: number | null;
  readonly signalCode: NodeJS.Signals | null;
  readonly stdio: readonly (NodeJS.ReadableStream | Writable | null)[];
  once(event: "exit", listener: (code: number | null, signal: NodeJS.Signals | null) => void): this;
  once(event: "error", listener: (error: Error) => void): this;
  kill(signal?: NodeJS.Signals | number): boolean;
}

type SpawnSidecar = (
  executable: string,
  args: readonly string[],
  options: SpawnOptions
) => SidecarChild;

interface Session {
  generation: number;
  launchId: string;
  token: string;
  runtime: RuntimePaths;
  child: SidecarChild;
  controlPipe: Writable;
  exit: Promise<void>;
  exited: boolean;
  processError: boolean;
  intentionalStop: boolean;
}

export interface SidecarSupervisorOptions {
  executablePath: string;
  dataDir: string;
  appVersion: string;
  sidecarVersion: string;
  schemaVersion: number;
  requiredCapabilities: readonly string[];
  tempRoot?: string;
  startupTimeoutMs?: number;
  pollIntervalMs?: number;
  shutdownTimeoutMs?: number;
}

export interface SidecarSupervisorDependencies {
  spawn?: SpawnSidecar;
  randomBytes?: (size: number) => Buffer;
  randomUUID?: () => string;
  createRuntime?: (launchId: string, tempRoot: string) => Promise<RuntimePaths>;
  inspectSocket?: (socketPath: string) => Promise<"missing" | "valid">;
  handshake?: (
    connection: SidecarConnection,
    timeoutMs: number
  ) => Promise<HandshakeResponse>;
  cleanupRuntime?: (runtime: RuntimePaths) => Promise<void>;
  validateExecutable?: (executablePath: string) => Promise<void>;
  wait?: (milliseconds: number) => Promise<void>;
  now?: () => number;
}

const SIDECAR_ENVIRONMENT_KEYS = [
  "HOME",
  "USER",
  "LOGNAME",
  "TMPDIR",
  "LANG",
  "LC_ALL",
  "LC_CTYPE",
  "TZ"
] as const;

export function buildSidecarEnvironment(
  source: NodeJS.ProcessEnv
): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = {};
  for (const key of SIDECAR_ENVIRONMENT_KEYS) {
    const value = source[key];
    if (typeof value === "string") {
      environment[key] = value;
    }
  }
  return environment;
}

class SupervisorFailure extends Error {
  constructor(readonly reason: RuntimeFailureReason) {
    super(`Sidecar supervisor failure (${reason})`);
    this.name = "SupervisorFailure";
  }
}

function effectiveUid(): number {
  return process.geteuid?.() ?? process.getuid?.() ?? -1;
}

async function verifyPrivateDirectory(directory: string): Promise<void> {
  const info = await lstat(directory);
  if (
    !info.isDirectory() ||
    info.isSymbolicLink() ||
    info.uid !== effectiveUid()
  ) {
    throw new SupervisorFailure("runtime-invalid");
  }
  await chmod(directory, 0o700);
  const verified = await lstat(directory);
  if ((verified.mode & 0o777) !== 0o700) {
    throw new SupervisorFailure("runtime-invalid");
  }
}

export async function createPrivateRuntime(
  launchId: string,
  tempRoot: string
): Promise<RuntimePaths> {
  if (
    !path.isAbsolute(tempRoot) ||
    !/^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(launchId)
  ) {
    throw new SupervisorFailure("configuration");
  }

  const tempInfo = await lstat(tempRoot).catch(() => undefined);
  if (!tempInfo?.isDirectory() || tempInfo.isSymbolicLink()) {
    throw new SupervisorFailure("runtime-invalid");
  }
  const canonicalTempRoot = await realpath(tempRoot);
  const baseDirectory = path.join(canonicalTempRoot, RUNTIME_DIRECTORY_NAME);
  await mkdir(baseDirectory, { recursive: true, mode: 0o700 });
  await verifyPrivateDirectory(baseDirectory);

  let directory = path.join(baseDirectory, launchId);
  await mkdir(directory, { mode: 0o700 });
  await verifyPrivateDirectory(directory);
  let socketPath = path.join(directory, SIDECAR_SOCKET_NAME);

  if (Buffer.byteLength(socketPath, "utf8") > MAX_UDS_PATH_BYTES) {
    await cleanupPrivateRuntime({ directory, socketPath });
    directory = await mkdtemp(path.join(canonicalTempRoot, "lcf-"));
    await verifyPrivateDirectory(directory);
    socketPath = path.join(directory, SIDECAR_SOCKET_NAME);
  }

  if (Buffer.byteLength(socketPath, "utf8") > MAX_UDS_PATH_BYTES) {
    await cleanupPrivateRuntime({ directory, socketPath });
    throw new SupervisorFailure("runtime-invalid");
  }
  return { directory, socketPath };
}

export async function inspectPrivateSocket(
  socketPath: string
): Promise<"missing" | "valid"> {
  const info = await lstat(socketPath).catch((error: NodeJS.ErrnoException) => {
    if (error.code === "ENOENT") {
      return undefined;
    }
    throw error;
  });
  if (!info) {
    return "missing";
  }
  if (!hasPrivateSocketMetadata(info, effectiveUid())) {
    throw new SupervisorFailure("runtime-invalid");
  }
  return "valid";
}

export function hasPrivateSocketMetadata(
  info: {
    isSocket(): boolean;
    isSymbolicLink(): boolean;
    uid: number;
    mode: number;
  },
  expectedUid: number
): boolean {
  return (
    info.isSocket() &&
    !info.isSymbolicLink() &&
    info.uid === expectedUid &&
    (info.mode & 0o777) === 0o600
  );
}

export async function cleanupPrivateRuntime(
  runtime: RuntimePaths
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
    path.basename(runtime.socketPath) !== SIDECAR_SOCKET_NAME
  ) {
    throw new SupervisorFailure("runtime-invalid");
  }
  await rm(runtime.directory, { recursive: true, force: true });
}

export async function validateSidecarExecutable(
  executablePath: string
): Promise<void> {
  if (!path.isAbsolute(executablePath)) {
    throw new SupervisorFailure("configuration");
  }
  const info = await lstat(executablePath).catch(() => undefined);
  if (!info?.isFile() || info.isSymbolicLink()) {
    throw new SupervisorFailure("configuration");
  }
  await access(executablePath, fsConstants.X_OK).catch(() => {
    throw new SupervisorFailure("configuration");
  });
}

export function resolveSidecarExecutable(input: {
  packaged: boolean;
  resourcesPath: string;
  environment?: NodeJS.ProcessEnv;
}): string {
  if (input.packaged) {
    if (!path.isAbsolute(input.resourcesPath)) {
      throw new SupervisorFailure("configuration");
    }
    return path.join(input.resourcesPath, "sidecar", "lcf-service");
  }

  const configured = input.environment?.LCF_SIDECAR_BIN;
  if (!configured || !path.isAbsolute(configured)) {
    throw new SupervisorFailure("configuration");
  }
  return path.normalize(configured);
}

function validateHandshake(
  value: HandshakeResponse,
  launchId: string,
  options: SidecarSupervisorOptions
): boolean {
  return (
    value !== null &&
    typeof value === "object" &&
    value.service === "local-context-forge" &&
    value.role === "python-sidecar" &&
    value.launch_id === launchId &&
    value.transport === "uds" &&
    value.protocol?.major === 1 &&
    value.protocol?.minor === 0 &&
    value.app_version === options.appVersion &&
    value.sidecar_version === options.sidecarVersion &&
    value.schema_version === options.schemaVersion &&
    Array.isArray(value.capabilities) &&
    value.capabilities.every((item) => typeof item === "string") &&
    options.requiredCapabilities.every((item) =>
      value.capabilities.includes(item)
    )
  );
}

interface HandshakeRequestDependencies {
  request?: (
    options: RequestOptions,
    callback: (response: IncomingMessage) => void
  ) => ClientRequest;
  now?: () => number;
  requestId?: () => string;
}

export function requestHandshake(
  connection: SidecarConnection,
  timeoutMs: number,
  dependencies: HandshakeRequestDependencies = {}
): Promise<HandshakeResponse> {
  const now = (dependencies.now ?? Date.now)();
  const requestId = (dependencies.requestId ?? nodeRandomUUID)();
  const requestImplementation = dependencies.request ?? http.request;

  return new Promise((resolve, reject) => {
    let settled = false;
    let request: ClientRequest | undefined;
    let activeResponse: IncomingMessage | undefined;
    const deadlineTimer = setTimeout(() => {
      if (!settled) {
        settled = true;
        activeResponse?.destroy();
        request?.destroy();
        reject(new SupervisorFailure("launch-failed"));
      }
    }, timeoutMs);
    request = requestImplementation(
      {
        socketPath: connection.socketPath,
        path: HANDSHAKE_PATH,
        method: "GET",
        agent: false,
        maxHeaderSize: 16 * 1024,
        headers: {
          Authorization: `Bearer ${connection.token}`,
          Accept: "application/json",
          "X-LCF-Protocol-Version": SIDECAR_PROTOCOL_VERSION,
          "X-LCF-Launch-ID": connection.launchId,
          "X-LCF-Request-ID": requestId,
          "X-LCF-Deadline-Ms": String(now + timeoutMs)
        }
      },
      (response) => {
        activeResponse = response;
        const chunks: Buffer[] = [];
        let total = 0;
        response.on("data", (chunk: Buffer | string) => {
          const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
          total += buffer.length;
          if (total > HANDSHAKE_RESPONSE_LIMIT && !settled) {
            settled = true;
            clearTimeout(deadlineTimer);
            response.destroy();
            reject(new SupervisorFailure("handshake-rejected"));
            return;
          }
          chunks.push(buffer);
        });
        response.once("error", () => {
          if (!settled) {
            settled = true;
            clearTimeout(deadlineTimer);
            reject(new SupervisorFailure("launch-failed"));
          }
        });
        response.once("end", () => {
          if (settled) {
            return;
          }
          settled = true;
          clearTimeout(deadlineTimer);
          if (response.statusCode !== 200) {
            reject(new SupervisorFailure("handshake-rejected"));
            return;
          }
          try {
            resolve(
              JSON.parse(
                Buffer.concat(chunks, total).toString("utf8")
              ) as HandshakeResponse
            );
          } catch {
            reject(new SupervisorFailure("handshake-rejected"));
          }
        });
      }
    );
    request.once("error", () => {
      if (!settled) {
        settled = true;
        clearTimeout(deadlineTimer);
        reject(new SupervisorFailure("launch-failed"));
      }
    });
    request.setTimeout(timeoutMs, () => {
      if (!settled) {
        settled = true;
        clearTimeout(deadlineTimer);
        request.destroy();
        reject(new SupervisorFailure("launch-failed"));
      }
    });
    request.end();
  });
}

function defaultSpawn(
  executable: string,
  args: readonly string[],
  options: SpawnOptions
): SidecarChild {
  return nodeSpawn(executable, [...args], options) as ChildProcess as SidecarChild;
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function writeControlToken(pipe: Writable, token: string): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    pipe.write(`${token}\n`, "utf8", (error) => {
      if (error) {
        reject(new SupervisorFailure("launch-failed"));
      } else {
        resolve();
      }
    });
  });
}

export class SidecarSupervisor {
  private readonly dependencies: Required<SidecarSupervisorDependencies>;
  private readonly listeners = new Set<(status: RuntimeStatus) => void>();
  private status: RuntimeStatus = { state: "stopped", canRetry: true };
  private session: Session | undefined;
  private generation = 0;
  private operation: Promise<RuntimeStatus> | undefined;
  private unconfirmedChild = false;

  constructor(
    private readonly options: SidecarSupervisorOptions,
    dependencies: SidecarSupervisorDependencies = {}
  ) {
    this.dependencies = {
      spawn: dependencies.spawn ?? defaultSpawn,
      randomBytes: dependencies.randomBytes ?? nodeRandomBytes,
      randomUUID: dependencies.randomUUID ?? nodeRandomUUID,
      createRuntime: dependencies.createRuntime ?? createPrivateRuntime,
      inspectSocket: dependencies.inspectSocket ?? inspectPrivateSocket,
      handshake: dependencies.handshake ?? requestHandshake,
      cleanupRuntime: dependencies.cleanupRuntime ?? cleanupPrivateRuntime,
      validateExecutable:
        dependencies.validateExecutable ?? validateSidecarExecutable,
      wait: dependencies.wait ?? wait,
      now: dependencies.now ?? Date.now
    };
  }

  getStatus(): RuntimeStatus {
    return { ...this.status };
  }

  subscribe(listener: (status: RuntimeStatus) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  getConnection(): SidecarConnection | undefined {
    if (this.status.state !== "ready" || !this.session) {
      return undefined;
    }
    return {
      socketPath: this.session.runtime.socketPath,
      launchId: this.session.launchId,
      token: this.session.token
    };
  }

  async start(): Promise<RuntimeStatus> {
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

  async retry(): Promise<RuntimeStatus> {
    if (
      (this.status.state !== "failed" && this.status.state !== "stopped") ||
      !this.status.canRetry ||
      this.session ||
      this.unconfirmedChild
    ) {
      return this.getStatus();
    }
    return this.start();
  }

  async shutdown(): Promise<RuntimeStatus> {
    if (this.operation) {
      await this.operation;
    }
    const current = this.session;
    if (!current) {
      if (this.unconfirmedChild) {
        this.updateStatus({
          state: "failed",
          canRetry: false,
          reason: "shutdown-timeout"
        });
        return this.getStatus();
      }
      this.updateStatus({ state: "stopped", canRetry: true });
      return this.getStatus();
    }
    this.updateStatus({ state: "stopping", canRetry: false });
    current.intentionalStop = true;
    const exited = await this.terminateSession(current);
    if (exited) {
      if (this.session === current) {
        this.session = undefined;
      }
      this.updateStatus({ state: "stopped", canRetry: true });
    } else {
      this.updateStatus({
        state: "failed",
        canRetry: false,
        reason: "shutdown-timeout"
      });
    }
    return this.getStatus();
  }

  private updateStatus(status: RuntimeStatus): void {
    this.status = status;
    const snapshot = this.getStatus();
    for (const listener of this.listeners) {
      try {
        listener(snapshot);
      } catch {
        // Status observers cannot alter the supervisor state machine.
      }
    }
  }

  private async launch(): Promise<RuntimeStatus> {
    this.updateStatus({ state: "starting", canRetry: false });
    let session: Session | undefined;
    let runtime: RuntimePaths | undefined;
    let untrackedChild: SidecarChild | undefined;
    try {
      if (
        !path.isAbsolute(this.options.dataDir) ||
        !path.isAbsolute(this.options.executablePath)
      ) {
        throw new SupervisorFailure("configuration");
      }
      await this.dependencies.validateExecutable(this.options.executablePath);

      const launchId = this.dependencies.randomUUID();
      const rawToken = this.dependencies.randomBytes(32);
      if (rawToken.length !== 32) {
        rawToken.fill(0);
        throw new SupervisorFailure("launch-failed");
      }
      const token = rawToken.toString("base64url");
      rawToken.fill(0);
      if (token.length !== 43) {
        throw new SupervisorFailure("launch-failed");
      }

      runtime = await this.dependencies.createRuntime(
        launchId,
        this.options.tempRoot ?? os.tmpdir()
      );
      const args = [
        "api",
        "--uds",
        runtime.socketPath,
        "--launch-id",
        launchId,
        "--token-fd",
        "3",
        "--data-dir",
        this.options.dataDir
      ] as const;
      const child = this.dependencies.spawn(
        this.options.executablePath,
        args,
        {
          shell: false,
          windowsHide: true,
          stdio: ["ignore", "ignore", "ignore", "pipe"],
          env: buildSidecarEnvironment(process.env)
        }
      );
      untrackedChild = child;
      const controlPipe = child.stdio[3];
      if (!controlPipe || typeof (controlPipe as Writable).write !== "function") {
        throw new SupervisorFailure("launch-failed");
      }

      session = this.createSession(
        launchId,
        token,
        runtime,
        child,
        controlPipe as Writable
      );
      untrackedChild = undefined;
      this.session = session;
      await writeControlToken(session.controlPipe, token);
      await this.waitUntilReady(session);
      if (session.exited) {
        throw new SupervisorFailure("sidecar-exited");
      }
      this.updateStatus({ state: "ready", canRetry: false });
      return this.getStatus();
    } catch (error) {
      const reason =
        error instanceof SupervisorFailure ? error.reason : "launch-failed";
      if (session) {
        session.intentionalStop = true;
        const exited = await this.terminateSession(session).catch(() => false);
        if (!exited) {
          this.updateStatus({
            state: "failed",
            canRetry: false,
            reason: "shutdown-timeout"
          });
          return this.getStatus();
        }
      } else if (untrackedChild) {
        const termination = await this.terminateUntrackedChild(untrackedChild);
        if (runtime && termination.exited) {
          await this.dependencies.cleanupRuntime(runtime).catch(() => undefined);
        } else if (runtime) {
          this.unconfirmedChild = true;
          void termination.exit.then(async () => {
            await this.dependencies.cleanupRuntime(runtime!).catch(() => undefined);
            this.unconfirmedChild = false;
            if (!this.session) {
              this.updateStatus({
                state: "failed",
                canRetry: true,
                reason: "sidecar-exited"
              });
            }
          });
          this.updateStatus({
            state: "failed",
            canRetry: false,
            reason: "shutdown-timeout"
          });
          return this.getStatus();
        }
      } else if (runtime) {
        await this.dependencies.cleanupRuntime(runtime).catch(() => undefined);
      }
      if (this.session === session) {
        this.session = undefined;
      }
      this.updateStatus({ state: "failed", canRetry: true, reason });
      return this.getStatus();
    }
  }

  private createSession(
    launchId: string,
    token: string,
    runtime: RuntimePaths,
    child: SidecarChild,
    controlPipe: Writable
  ): Session {
    const session: Session = {
      generation: ++this.generation,
      launchId,
      token,
      runtime,
      child,
      controlPipe,
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
        if (
          !session.intentionalStop &&
          this.session === session &&
          (this.status.state === "ready" ||
            (this.status.state === "failed" && !this.status.canRetry))
        ) {
          void this.handleUnexpectedExit(session);
        }
      };
      const processError = () => {
        session.processError = true;
        if (child.pid === undefined) {
          complete();
          return;
        }
        if (
          !session.intentionalStop &&
          this.session === session &&
          this.status.state === "ready"
        ) {
          this.updateStatus({
            state: "failed",
            canRetry: false,
            reason: "launch-failed"
          });
        }
      };
      // fd3 can report EPIPE after a fast child failure or during shutdown.
      // Keep a permanent, non-logging listener so no secret-bearing Error can
      // escape as an uncaught exception.
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

  private async waitUntilReady(session: Session): Promise<void> {
    const startupTimeout = this.options.startupTimeoutMs ?? 15_000;
    const pollInterval = this.options.pollIntervalMs ?? 100;
    const deadline = this.dependencies.now() + startupTimeout;
    let sawRejectedHandshake = false;

    while (this.dependencies.now() < deadline) {
      if (session.processError) {
        throw new SupervisorFailure("launch-failed");
      }
      if (session.exited) {
        throw new SupervisorFailure("sidecar-exited");
      }

      const socket = await this.dependencies.inspectSocket(
        session.runtime.socketPath
      );
      if (socket === "valid") {
        try {
          const remaining = Math.max(
            1,
            Math.min(1_000, deadline - this.dependencies.now())
          );
          const handshake = await this.dependencies.handshake(
            {
              socketPath: session.runtime.socketPath,
              launchId: session.launchId,
              token: session.token
            },
            remaining
          );
          if (!validateHandshake(handshake, session.launchId, this.options)) {
            sawRejectedHandshake = true;
            break;
          }
          return;
        } catch (error) {
          if (
            error instanceof SupervisorFailure &&
            error.reason === "handshake-rejected"
          ) {
            sawRejectedHandshake = true;
            break;
          }
        }
      }
      await this.dependencies.wait(pollInterval);
    }

    throw new SupervisorFailure(
      sawRejectedHandshake ? "handshake-rejected" : "startup-timeout"
    );
  }

  private async terminateSession(session: Session): Promise<boolean> {
    session.intentionalStop = true;
    if (!session.controlPipe.destroyed) {
      session.controlPipe.end();
    }
    if (!session.exited) {
      const gracefulTimeout = this.options.shutdownTimeoutMs ?? 12_000;
      await Promise.race([
        session.exit,
        this.dependencies.wait(gracefulTimeout)
      ]);
      if (!session.exited) {
        session.child.kill("SIGTERM");
        await Promise.race([
          session.exit,
          this.dependencies.wait(3_000)
        ]);
        if (!session.exited) {
          session.child.kill("SIGKILL");
          await Promise.race([
            session.exit,
            this.dependencies.wait(1_000)
          ]);
        }
      }
    }
    session.token = "";
    if (session.exited) {
      await this.dependencies.cleanupRuntime(session.runtime);
      return true;
    }
    void session.exit.then(async () => {
      await this.dependencies.cleanupRuntime(session.runtime).catch(() => undefined);
      if (this.session === session) {
        this.session = undefined;
        if (
          this.status.state === "failed" &&
          this.status.reason === "shutdown-timeout"
        ) {
          this.updateStatus({
            state: "failed",
            canRetry: true,
            reason: "sidecar-exited"
          });
        }
      }
    });
    return false;
  }

  private async terminateUntrackedChild(
    child: SidecarChild
  ): Promise<{ exited: boolean; exit: Promise<void> }> {
    if (child.exitCode !== null) {
      return { exited: true, exit: Promise.resolve() };
    }
    let exited = false;
    const exit = new Promise<void>((resolve) => {
      const complete = () => {
        if (!exited) {
          exited = true;
          resolve();
        }
      };
      child.once("exit", complete);
    });
    await Promise.race([
      exit,
      this.dependencies.wait(this.options.shutdownTimeoutMs ?? 12_000)
    ]);
    if (!exited) {
      child.kill("SIGTERM");
      await Promise.race([exit, this.dependencies.wait(3_000)]);
      if (!exited) {
        child.kill("SIGKILL");
        await Promise.race([exit, this.dependencies.wait(1_000)]);
      }
    }
    return { exited, exit };
  }

  private async handleUnexpectedExit(session: Session): Promise<void> {
    if (this.session !== session || session.generation !== this.generation) {
      return;
    }
    if (!session.controlPipe.destroyed) {
      session.controlPipe.end();
    }
    session.token = "";
    await this.dependencies.cleanupRuntime(session.runtime).catch(() => undefined);
    if (this.session === session) {
      this.session = undefined;
      this.updateStatus({
        state: "failed",
        canRetry: true,
        reason: "sidecar-exited"
      });
    }
  }
}

import { randomBytes as systemRandomBytes } from "node:crypto";
import { constants as fsConstants } from "node:fs";
import {
  lstat,
  open,
  realpath,
  rename,
  unlink
} from "node:fs/promises";
import path from "node:path";
import { MCP_TARGET_OWNER_ENV } from "../mcpProtocol";

export { MCP_TARGET_OWNER_ENV };
export const MCP_TARGET_OWNERSHIP_FILE_NAME =
  "mcp-target-ownership.json";

const OWNERSHIP_SCHEMA_VERSION = 1;
const MAX_OWNERSHIP_STATE_BYTES = 32 * 1024;
const MAX_TARGET_PATH_BYTES = 8 * 1024;
const OWNER_MARKER_PATTERN = /^lcf-mcp-v1-[0-9a-f]{64}$/;
const APPLICATION_BUNDLE_NAME = "Local Context Forge.app";

export interface McpOwnedTarget {
  readonly command: string;
  readonly arguments_: readonly [string];
}

export interface McpTargetOwnership {
  readonly marker: string;
  readonly targets: readonly McpOwnedTarget[];
}

export interface McpTargetOwnershipStore {
  read(): Promise<McpTargetOwnership | undefined>;
  stage(
    expected: McpTargetOwnership | undefined,
    targets: readonly McpOwnedTarget[]
  ): Promise<McpTargetOwnership>;
  remove(expected: McpTargetOwnership): Promise<void>;
}

export interface FileMcpTargetOwnershipStoreDependencies {
  readonly effectiveUid?: () => number;
  readonly randomBytes?: (size: number) => Buffer;
  readonly scopeId?: string;
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return (
    !!value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    (Object.getPrototypeOf(value) === Object.prototype ||
      Object.getPrototypeOf(value) === null)
  );
}

function hasExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[]
): boolean {
  const keys = Object.keys(value);
  return (
    keys.length === expected.length &&
    expected.every((key) => Object.hasOwn(value, key))
  );
}

function isAbsoluteNormalizedPath(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    Buffer.byteLength(value, "utf8") <= MAX_TARGET_PATH_BYTES &&
    !value.includes("\0") &&
    path.isAbsolute(value) &&
    path.normalize(value) === value
  );
}

function isFixedBundledTarget(target: McpOwnedTarget): boolean {
  const companion = target.arguments_[0];
  const nodeResources = path.resolve(
    target.command,
    "..",
    "..",
    "..",
    ".."
  );
  const companionResources = path.resolve(companion, "..", "..");
  return (
    nodeResources === companionResources &&
    path.basename(nodeResources) === "Resources" &&
    path.basename(path.dirname(nodeResources)) === "Contents" &&
    path.basename(path.dirname(path.dirname(nodeResources))) ===
      APPLICATION_BUNDLE_NAME &&
    target.command ===
      path.join(nodeResources, "qmd", "node", "bin", "node") &&
    companion ===
      path.join(nodeResources, "companion", "index.mjs")
  );
}

function parseTarget(value: unknown): McpOwnedTarget {
  if (
    !isPlainRecord(value) ||
    !hasExactKeys(value, ["arguments", "command"]) ||
    !isAbsoluteNormalizedPath(value.command) ||
    !Array.isArray(value.arguments) ||
    value.arguments.length !== 1 ||
    !isAbsoluteNormalizedPath(value.arguments[0])
  ) {
    throw new TypeError("MCP target ownership state is invalid");
  }
  const target: McpOwnedTarget = {
    command: value.command,
    arguments_: [value.arguments[0]]
  };
  if (!isFixedBundledTarget(target)) {
    throw new TypeError("MCP target ownership state is invalid");
  }
  return target;
}

function normalizeTargets(
  values: readonly McpOwnedTarget[]
): readonly McpOwnedTarget[] {
  if (values.length < 1 || values.length > 2) {
    throw new TypeError("MCP target ownership state is invalid");
  }
  const targets = values.map((value) =>
    parseTarget({
      command: value.command,
      arguments: [...value.arguments_]
    })
  );
  if (
    targets.some((target, index) =>
      targets.slice(0, index).some(
        (prior) =>
          prior.command === target.command &&
          prior.arguments_[0] === target.arguments_[0]
      )
    )
  ) {
    throw new TypeError("MCP target ownership state is invalid");
  }
  return targets;
}

function parseOwnershipState(value: unknown): McpTargetOwnership {
  if (
    !isPlainRecord(value) ||
    !hasExactKeys(value, ["marker", "schemaVersion", "targets"]) ||
    value.schemaVersion !== OWNERSHIP_SCHEMA_VERSION ||
    typeof value.marker !== "string" ||
    !OWNER_MARKER_PATTERN.test(value.marker) ||
    !Array.isArray(value.targets)
  ) {
    throw new TypeError("MCP target ownership state is invalid");
  }
  return {
    marker: value.marker,
    targets: normalizeTargets(value.targets.map(parseTarget))
  };
}

function serializeOwnershipState(state: McpTargetOwnership): Buffer {
  const normalized = parseOwnershipState({
    schemaVersion: OWNERSHIP_SCHEMA_VERSION,
    marker: state.marker,
    targets: state.targets.map((target) => ({
      command: target.command,
      arguments: [...target.arguments_]
    }))
  });
  const payload = Buffer.from(
    `${JSON.stringify({
      schemaVersion: OWNERSHIP_SCHEMA_VERSION,
      marker: normalized.marker,
      targets: normalized.targets.map((target) => ({
        command: target.command,
        arguments: [...target.arguments_]
      }))
    })}\n`,
    "utf8"
  );
  if (payload.length > MAX_OWNERSHIP_STATE_BYTES) {
    throw new TypeError("MCP target ownership state is invalid");
  }
  return payload;
}

export function sameMcpTargetOwnership(
  left: McpTargetOwnership | undefined,
  right: McpTargetOwnership | undefined
): boolean {
  if (!left || !right) {
    return left === right;
  }
  return (
    left.marker === right.marker &&
    left.targets.length === right.targets.length &&
    left.targets.every(
      (target, index) =>
        target.command === right.targets[index]?.command &&
        target.arguments_[0] ===
          right.targets[index]?.arguments_[0]
    )
  );
}

export function isMcpTargetOwned(
  state: McpTargetOwnership,
  marker: string | undefined,
  target: McpOwnedTarget
): boolean {
  return (
    marker === state.marker &&
    state.targets.some(
      (candidate) =>
        candidate.command === target.command &&
        candidate.arguments_[0] === target.arguments_[0]
    )
  );
}

function errno(error: unknown): string | undefined {
  return error &&
    typeof error === "object" &&
    "code" in error &&
    typeof error.code === "string"
    ? error.code
    : undefined;
}

export class FileMcpTargetOwnershipStore
  implements McpTargetOwnershipStore
{
  private readonly effectiveUid: () => number;
  private readonly randomBytes: (size: number) => Buffer;
  private readonly statePath: string;

  constructor(
    private readonly dataDirectory: string,
    dependencies: FileMcpTargetOwnershipStoreDependencies = {}
  ) {
    if (
      !path.isAbsolute(dataDirectory) ||
      path.normalize(dataDirectory) !== dataDirectory ||
      dataDirectory.includes("\0") ||
      dataDirectory === path.parse(dataDirectory).root
    ) {
      throw new TypeError("MCP target ownership directory is invalid");
    }
    const scopeId = dependencies.scopeId;
    if (
      scopeId !== undefined &&
      !/^[0-9a-f]{64}$/.test(scopeId)
    ) {
      throw new TypeError("MCP target ownership scope is invalid");
    }
    this.statePath = path.join(
      dataDirectory,
      scopeId === undefined
        ? MCP_TARGET_OWNERSHIP_FILE_NAME
        : `mcp-target-ownership-${scopeId}.json`
    );
    this.effectiveUid =
      dependencies.effectiveUid ??
      (() => process.geteuid?.() ?? process.getuid?.() ?? -1);
    this.randomBytes =
      dependencies.randomBytes ?? systemRandomBytes;
  }

  async read(): Promise<McpTargetOwnership | undefined> {
    await this.requirePrivateDirectory();
    const lexicalInfo = await lstat(this.statePath).catch((error) => {
      if (errno(error) === "ENOENT") {
        return undefined;
      }
      throw error;
    });
    if (!lexicalInfo) {
      return undefined;
    }
    if (
      !lexicalInfo.isFile() ||
      lexicalInfo.isSymbolicLink() ||
      lexicalInfo.uid !== this.requireEffectiveUid() ||
      lexicalInfo.nlink !== 1 ||
      (lexicalInfo.mode & 0o7777) !== 0o600 ||
      lexicalInfo.size <= 0 ||
      lexicalInfo.size > MAX_OWNERSHIP_STATE_BYTES ||
      (await realpath(this.statePath).catch(() => undefined)) !==
        this.statePath
    ) {
      throw new TypeError("MCP target ownership file is invalid");
    }
    const handle = await open(
      this.statePath,
      fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW
    );
    try {
      const info = await handle.stat();
      if (
        !info.isFile() ||
        info.uid !== lexicalInfo.uid ||
        info.dev !== lexicalInfo.dev ||
        info.ino !== lexicalInfo.ino ||
        info.nlink !== 1 ||
        (info.mode & 0o7777) !== 0o600 ||
        info.size !== lexicalInfo.size
      ) {
        throw new TypeError("MCP target ownership file is invalid");
      }
      const bytes = Buffer.alloc(info.size);
      const { bytesRead } = await handle.read(
        bytes,
        0,
        bytes.length,
        0
      );
      if (bytesRead !== bytes.length) {
        throw new TypeError("MCP target ownership file is invalid");
      }
      let value: unknown;
      try {
        value = JSON.parse(
          new TextDecoder("utf-8", { fatal: true }).decode(bytes)
        );
      } catch {
        throw new TypeError("MCP target ownership file is invalid");
      }
      return parseOwnershipState(value);
    } finally {
      await handle.close();
    }
  }

  async stage(
    expected: McpTargetOwnership | undefined,
    targets: readonly McpOwnedTarget[]
  ): Promise<McpTargetOwnership> {
    const current = await this.read();
    if (!sameMcpTargetOwnership(current, expected)) {
      throw new TypeError("MCP target ownership state changed");
    }
    const next: McpTargetOwnership = {
      marker: current?.marker ?? this.createMarker(),
      targets: normalizeTargets(targets)
    };
    const payload = serializeOwnershipState(next);
    const temporaryPath = path.join(
      this.dataDirectory,
      `.mcp-target-ownership-${this.randomHex(16)}.tmp`
    );
    let temporaryReady = false;
    try {
      await this.writeNewPrivateFile(temporaryPath, payload);
      temporaryReady = true;
      const revalidated = await this.read();
      if (!sameMcpTargetOwnership(revalidated, expected)) {
        throw new TypeError("MCP target ownership state changed");
      }
      await rename(temporaryPath, this.statePath);
      await this.syncDirectory();
      const persisted = await this.read();
      if (!persisted || !sameMcpTargetOwnership(persisted, next)) {
        throw new TypeError("MCP target ownership state changed");
      }
      return persisted;
    } finally {
      if (temporaryReady) {
        await unlink(temporaryPath).catch((error) => {
          if (errno(error) !== "ENOENT") {
            throw error;
          }
        });
      }
    }
  }

  async remove(expected: McpTargetOwnership): Promise<void> {
    const current = await this.read();
    if (!sameMcpTargetOwnership(current, expected)) {
      throw new TypeError("MCP target ownership state changed");
    }
    const before = await lstat(this.statePath);
    if (
      !before.isFile() ||
      before.isSymbolicLink() ||
      before.uid !== this.requireEffectiveUid() ||
      before.nlink !== 1 ||
      (before.mode & 0o7777) !== 0o600
    ) {
      throw new TypeError("MCP target ownership file is invalid");
    }
    await unlink(this.statePath);
    await this.syncDirectory();
  }

  private requireEffectiveUid(): number {
    const uid = this.effectiveUid();
    if (!Number.isSafeInteger(uid) || uid < 0) {
      throw new TypeError("Effective uid is unavailable");
    }
    return uid;
  }

  private async requirePrivateDirectory(): Promise<void> {
    const info = await lstat(this.dataDirectory);
    if (
      !info.isDirectory() ||
      info.isSymbolicLink() ||
      info.uid !== this.requireEffectiveUid() ||
      (info.mode & 0o7777) !== 0o700 ||
      (await realpath(this.dataDirectory)) !== this.dataDirectory
    ) {
      throw new TypeError("MCP target ownership directory is invalid");
    }
  }

  private createMarker(): string {
    return `lcf-mcp-v1-${this.randomHex(32)}`;
  }

  private randomHex(size: number): string {
    const entropy = this.randomBytes(size);
    if (entropy.length !== size) {
      entropy.fill(0);
      throw new TypeError("MCP target ownership entropy is invalid");
    }
    const value = entropy.toString("hex");
    entropy.fill(0);
    return value;
  }

  private async writeNewPrivateFile(
    filePath: string,
    payload: Buffer
  ): Promise<void> {
    const handle = await open(
      filePath,
      fsConstants.O_WRONLY |
        fsConstants.O_CREAT |
        fsConstants.O_EXCL |
        fsConstants.O_NOFOLLOW,
      0o600
    );
    let identity:
      | { readonly dev: number; readonly ino: number }
      | undefined;
    try {
      const created = await handle.stat();
      identity = { dev: created.dev, ino: created.ino };
      await handle.writeFile(payload);
      await handle.sync();
      await handle.chmod(0o600);
      const info = await handle.stat();
      if (
        !info.isFile() ||
        info.uid !== this.requireEffectiveUid() ||
        info.nlink !== 1 ||
        (info.mode & 0o7777) !== 0o600 ||
        info.size !== payload.length
      ) {
        throw new TypeError("MCP target ownership file is invalid");
      }
    } catch (error) {
      await handle.close().catch(() => undefined);
      if (identity) {
        const current = await lstat(filePath).catch(() => undefined);
        if (
          current &&
          current.dev === identity.dev &&
          current.ino === identity.ino
        ) {
          await unlink(filePath).catch(() => undefined);
        }
      }
      throw error;
    }
    await handle.close();
  }

  private async syncDirectory(): Promise<void> {
    const handle = await open(this.dataDirectory, fsConstants.O_RDONLY);
    try {
      await handle.sync();
    } finally {
      await handle.close();
    }
  }
}

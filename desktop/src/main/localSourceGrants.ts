import { randomBytes as systemRandomBytes } from "node:crypto";
import { lstat as systemLstat, realpath as systemRealpath } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { performance as systemPerformance } from "node:perf_hooks";

export const LOCAL_SOURCE_GRANT_PREFIX = "lcf-local:";
export const LOCAL_SOURCE_GRANT_PATTERN = /^lcf-local:[0-9a-f]{64}$/;
export const LOCAL_SOURCE_GRANT_TTL_MS = 5 * 60 * 1_000;

export interface LocalSourceSelection {
  readonly grantId: string;
  readonly displayName: string;
}

export type LocalSourceGrantErrorCode =
  | "invalid-grant"
  | "unsafe-selection";

export class LocalSourceGrantError extends Error {
  constructor(readonly code: LocalSourceGrantErrorCode) {
    super(`Local source authorization failed (${code})`);
    this.name = "LocalSourceGrantError";
  }
}

interface FileIdentity {
  readonly path: string;
  readonly device: number;
  readonly inode: number;
  readonly expiresAt: number;
}

interface FileInfo {
  readonly dev: number;
  readonly ino: number;
  readonly uid: number;
  isDirectory(): boolean;
  isSymbolicLink(): boolean;
}

export interface LocalSourceGrantDependencies {
  readonly lstat?: (candidate: string) => Promise<FileInfo>;
  readonly realpath?: (candidate: string) => Promise<string>;
  readonly randomBytes?: (size: number) => Buffer;
  readonly now?: () => number;
  readonly effectiveUserId?: () => number;
}

export interface LocalSourceGrantOptions {
  readonly dataDirectory: string;
  readonly homeDirectory?: string;
  readonly volumesDirectory?: string;
  readonly excludedDirectories?: readonly string[];
  readonly ttlMs?: number;
}

function pathsOverlap(left: string, right: string): boolean {
  const relative = path.relative(left, right);
  if (
    relative === "" ||
    (!relative.startsWith(`..${path.sep}`) &&
      relative !== ".." &&
      !path.isAbsolute(relative))
  ) {
    return true;
  }
  const reverse = path.relative(right, left);
  return (
    reverse === "" ||
    (!reverse.startsWith(`..${path.sep}`) &&
      reverse !== ".." &&
      !path.isAbsolute(reverse))
  );
}

function isStrictDescendant(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return (
    relative !== "" &&
    relative !== ".." &&
    !relative.startsWith(`..${path.sep}`) &&
    !path.isAbsolute(relative)
  );
}

function safeDisplayName(candidate: string): string {
  const normalized = path
    .basename(candidate)
    .normalize("NFC")
    .replace(
      /[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g,
      "\ufffd"
    );
  const points = Array.from(normalized).slice(0, 120).join("");
  return points.trim() || "Local repository";
}

export function isLocalSourceGrant(value: unknown): value is string {
  return typeof value === "string" && LOCAL_SOURCE_GRANT_PATTERN.test(value);
}

export class LocalSourceGrantManager {
  private readonly grants = new Map<string, FileIdentity>();
  private readonly lstat: (candidate: string) => Promise<FileInfo>;
  private readonly realpath: (candidate: string) => Promise<string>;
  private readonly randomBytes: (size: number) => Buffer;
  private readonly now: () => number;
  private readonly effectiveUserId: () => number;
  private readonly ttlMs: number;
  private readonly dataDirectory: string;
  private readonly homeDirectory: string;
  private readonly volumesDirectory: string;
  private readonly excludedDirectories: readonly string[];

  constructor(
    options: LocalSourceGrantOptions,
    dependencies: LocalSourceGrantDependencies = {}
  ) {
    if (
      !path.isAbsolute(options.dataDirectory) ||
      (options.homeDirectory !== undefined &&
        !path.isAbsolute(options.homeDirectory)) ||
      (options.volumesDirectory !== undefined &&
        !path.isAbsolute(options.volumesDirectory)) ||
      (options.excludedDirectories?.some(
        (candidate) => !path.isAbsolute(candidate)
      ) ??
        false)
    ) {
      throw new LocalSourceGrantError("unsafe-selection");
    }
    this.dataDirectory = path.resolve(options.dataDirectory);
    this.homeDirectory = path.resolve(
      options.homeDirectory ?? os.homedir()
    );
    this.volumesDirectory = path.resolve(
      options.volumesDirectory ?? "/Volumes"
    );
    this.excludedDirectories = Object.freeze(
      (options.excludedDirectories ?? []).map((candidate) =>
        path.resolve(candidate)
      )
    );
    this.ttlMs = options.ttlMs ?? LOCAL_SOURCE_GRANT_TTL_MS;
    if (
      !Number.isSafeInteger(this.ttlMs) ||
      this.ttlMs < 1_000 ||
      this.ttlMs > LOCAL_SOURCE_GRANT_TTL_MS
    ) {
      throw new LocalSourceGrantError("unsafe-selection");
    }
    this.lstat = dependencies.lstat ?? systemLstat;
    this.realpath = dependencies.realpath ?? systemRealpath;
    this.randomBytes = dependencies.randomBytes ?? systemRandomBytes;
    this.now = dependencies.now ?? (() => systemPerformance.now());
    this.effectiveUserId =
      dependencies.effectiveUserId ??
      (() => process.geteuid?.() ?? process.getuid?.() ?? -1);
  }

  private purgeExpired(): void {
    const now = this.now();
    for (const [grantId, record] of this.grants) {
      if (record.expiresAt <= now) {
        this.grants.delete(grantId);
      }
    }
  }

  private async inspect(candidate: string): Promise<{
    readonly path: string;
    readonly device: number;
    readonly inode: number;
  }> {
    if (
      typeof candidate !== "string" ||
      candidate.length === 0 ||
      Buffer.byteLength(candidate, "utf8") > 4_096 ||
      candidate.includes("\0") ||
      !path.isAbsolute(candidate)
    ) {
      throw new LocalSourceGrantError("unsafe-selection");
    }

    const lexical = path.resolve(candidate);
    let resolved: string;
    let info: FileInfo;
    let parentInfo: FileInfo;
    try {
      [resolved, info, parentInfo] = await Promise.all([
        this.realpath(lexical),
        this.lstat(lexical),
        this.lstat(path.dirname(lexical))
      ]);
    } catch {
      throw new LocalSourceGrantError("unsafe-selection");
    }
    if (
      resolved !== lexical ||
      !info.isDirectory() ||
      info.isSymbolicLink() ||
      info.uid !== this.effectiveUserId() ||
      !Number.isSafeInteger(info.dev) ||
      info.dev < 0 ||
      !Number.isSafeInteger(info.ino) ||
      info.ino < 0 ||
      !Number.isSafeInteger(parentInfo.dev) ||
      parentInfo.dev < 0 ||
      info.dev !== parentInfo.dev ||
      resolved === path.parse(resolved).root ||
      pathsOverlap(resolved, this.dataDirectory) ||
      this.excludedDirectories.some((excluded) =>
        pathsOverlap(resolved, excluded)
      )
    ) {
      throw new LocalSourceGrantError("unsafe-selection");
    }

    const underHome = isStrictDescendant(this.homeDirectory, resolved);
    const underVolumes = isStrictDescendant(
      this.volumesDirectory,
      resolved
    );
    if (!underHome && !underVolumes) {
      throw new LocalSourceGrantError("unsafe-selection");
    }
    if (underVolumes) {
      const relative = path.relative(this.volumesDirectory, resolved);
      if (relative.split(path.sep).filter(Boolean).length < 2) {
        throw new LocalSourceGrantError("unsafe-selection");
      }
    }

    return {
      path: resolved,
      device: info.dev,
      inode: info.ino
    };
  }

  async issue(candidate: string): Promise<LocalSourceSelection> {
    this.purgeExpired();
    const identity = await this.inspect(candidate);
    const entropy = this.randomBytes(32);
    if (entropy.length !== 32) {
      entropy.fill(0);
      throw new LocalSourceGrantError("unsafe-selection");
    }
    const grantId = `${LOCAL_SOURCE_GRANT_PREFIX}${entropy.toString("hex")}`;
    entropy.fill(0);
    if (!isLocalSourceGrant(grantId) || this.grants.has(grantId)) {
      throw new LocalSourceGrantError("unsafe-selection");
    }
    this.grants.set(grantId, {
      ...identity,
      expiresAt: this.now() + this.ttlMs
    });
    return {
      grantId,
      displayName: safeDisplayName(identity.path)
    };
  }

  async consume(grantId: unknown): Promise<string> {
    if (!isLocalSourceGrant(grantId)) {
      throw new LocalSourceGrantError("invalid-grant");
    }
    const record = this.grants.get(grantId);
    this.grants.delete(grantId);
    if (!record || record.expiresAt <= this.now()) {
      throw new LocalSourceGrantError("invalid-grant");
    }
    const current = await this.inspect(record.path);
    if (
      current.device !== record.device ||
      current.inode !== record.inode
    ) {
      throw new LocalSourceGrantError("invalid-grant");
    }
    return current.path;
  }

  clear(): void {
    this.grants.clear();
  }
}

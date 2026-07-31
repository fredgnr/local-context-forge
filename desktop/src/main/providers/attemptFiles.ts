import { createHash } from "node:crypto";
import { constants as fsConstants } from "node:fs";
import {
  chmod,
  copyFile,
  lstat,
  mkdtemp,
  open,
  realpath,
  rm
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type { ClaimedProviderAttempt } from "./providerAttemptClient";

const SHA256 = /^[0-9a-f]{64}$/;
const MAX_REQUEST_BYTES = 64 * 1024;
const MAX_PROMPT_BYTES = 2 * 1024 * 1024;
const MAX_SCHEMA_BYTES = 256 * 1024;
const MAX_EVIDENCE_BYTES = 16 * 1024 * 1024;
export const MAX_PROVIDER_OUTPUT_BYTES = 16 * 1024 * 1024;

interface FileManifestEntry {
  readonly sha256: string;
  readonly size: number;
}

interface AttemptRequestManifest {
  readonly schema_version: 1;
  readonly job_id: string;
  readonly files: {
    readonly "evidence.json": FileManifestEntry;
    readonly "schema.json": FileManifestEntry;
    readonly "prompt.txt": FileManifestEntry;
  };
}

export interface VerifiedAttemptInput {
  readonly prompt: string;
  readonly schemaPath: string;
  readonly outputPath: string;
  readonly workingDirectory: string;
}

export interface ProviderOutputEvidence {
  readonly sha256: string;
  readonly size: number;
}

function effectiveUid(): number {
  return process.geteuid?.() ?? process.getuid?.() ?? -1;
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

function parseFileEntry(value: unknown): FileManifestEntry {
  if (
    !plainRecord(value) ||
    Object.keys(value).length !== 2 ||
    typeof value.sha256 !== "string" ||
    !SHA256.test(value.sha256) ||
    typeof value.size !== "number" ||
    !Number.isSafeInteger(value.size) ||
    value.size < 0
  ) {
    throw new TypeError("Provider attempt file manifest is invalid");
  }
  return { sha256: value.sha256, size: value.size };
}

function parseRequestManifest(
  serialized: Buffer,
  expectedJobId: string
): AttemptRequestManifest {
  let value: unknown;
  try {
    value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(serialized));
  } catch {
    throw new TypeError("Provider attempt request manifest is invalid");
  }
  if (
    !plainRecord(value) ||
    Object.keys(value).length !== 3 ||
    value.schema_version !== 1 ||
    value.job_id !== expectedJobId ||
    !plainRecord(value.files) ||
    Object.keys(value.files).length !== 3
  ) {
    throw new TypeError("Provider attempt request manifest is invalid");
  }
  return {
    schema_version: 1,
    job_id: expectedJobId,
    files: {
      "evidence.json": parseFileEntry(value.files["evidence.json"]),
      "schema.json": parseFileEntry(value.files["schema.json"]),
      "prompt.txt": parseFileEntry(value.files["prompt.txt"])
    }
  };
}

async function readPrivateFile(
  filePath: string,
  attemptDirectory: string,
  maximumBytes: number,
  expected: FileManifestEntry
): Promise<Buffer> {
  if (path.dirname(filePath) !== attemptDirectory) {
    throw new TypeError("Provider attempt file escapes its directory");
  }
  const canonical = await realpath(filePath);
  const handle = await open(
    filePath,
    fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW
  );
  try {
    const info = await handle.stat();
    if (
      !info.isFile() ||
      info.uid !== effectiveUid() ||
      (info.mode & 0o022) !== 0 ||
      canonical !== filePath ||
      info.size !== expected.size ||
      info.size > maximumBytes
    ) {
      throw new TypeError("Provider attempt file metadata is invalid");
    }
    const value = await handle.readFile();
    if (
      value.length !== expected.size ||
      createHash("sha256").update(value).digest("hex") !== expected.sha256
    ) {
      throw new TypeError("Provider attempt file digest changed");
    }
    return value;
  } finally {
    await handle.close();
  }
}

export async function verifyClaimedAttemptFiles(
  attempt: ClaimedProviderAttempt
): Promise<VerifiedAttemptInput> {
  const directoryInfo = await lstat(attempt.attemptDirectory);
  const canonicalDirectory = await realpath(attempt.attemptDirectory);
  if (
    !directoryInfo.isDirectory() ||
    directoryInfo.isSymbolicLink() ||
    directoryInfo.uid !== effectiveUid() ||
    (directoryInfo.mode & 0o777) !== 0o700 ||
    canonicalDirectory !== attempt.attemptDirectory
  ) {
    throw new TypeError("Provider attempt directory is invalid");
  }

  if (path.dirname(attempt.requestPath) !== attempt.attemptDirectory) {
    throw new TypeError("Provider attempt request manifest is invalid");
  }
  const request = await open(
    attempt.requestPath,
    fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW
  );
  let requestBytes: Buffer;
  try {
    const requestInfo = await request.stat();
    if (
      !requestInfo.isFile() ||
      requestInfo.uid !== effectiveUid() ||
      (requestInfo.mode & 0o022) !== 0 ||
      requestInfo.size > MAX_REQUEST_BYTES
    ) {
      throw new TypeError("Provider attempt request manifest is invalid");
    }
    requestBytes = await request.readFile();
  } finally {
    await request.close();
  }
  if (
    createHash("sha256").update(requestBytes).digest("hex") !==
    attempt.inputSha256
  ) {
    throw new TypeError("Provider attempt input digest changed");
  }
  const manifest = parseRequestManifest(requestBytes, attempt.jobId);
  const promptBytes = await readPrivateFile(
    attempt.promptPath,
    attempt.attemptDirectory,
    MAX_PROMPT_BYTES,
    manifest.files["prompt.txt"]
  );
  await readPrivateFile(
    attempt.schemaPath,
    attempt.attemptDirectory,
    MAX_SCHEMA_BYTES,
    manifest.files["schema.json"]
  );
  await readPrivateFile(
    attempt.evidencePath,
    attempt.attemptDirectory,
    MAX_EVIDENCE_BYTES,
    manifest.files["evidence.json"]
  );
  const output = await lstat(attempt.outputPath).catch(
    (error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") {
        return undefined;
      }
      throw error;
    }
  );
  if (output) {
    throw new TypeError("Provider output exists before execution");
  }
  let prompt: string;
  try {
    prompt = new TextDecoder("utf-8", { fatal: true }).decode(promptBytes);
  } catch {
    throw new TypeError("Provider prompt is not valid UTF-8");
  }
  return {
    prompt,
    schemaPath: attempt.schemaPath,
    outputPath: attempt.outputPath,
    workingDirectory: attempt.attemptDirectory
  };
}

export interface DisposableCursorWorkspace {
  readonly path: string;
  cleanup(): Promise<void>;
}

export async function createDisposableCursorWorkspace(
  attempt: ClaimedProviderAttempt,
  tempRoot = os.tmpdir()
): Promise<DisposableCursorWorkspace> {
  const directory = await mkdtemp(path.join(tempRoot, "lcf-cursor-"));
  await chmod(directory, 0o700);
  try {
    await Promise.all([
      copyFile(attempt.evidencePath, path.join(directory, "evidence.json")),
      copyFile(attempt.schemaPath, path.join(directory, "schema.json"))
    ]);
    await Promise.all([
      chmod(path.join(directory, "evidence.json"), 0o400),
      chmod(path.join(directory, "schema.json"), 0o400)
    ]);
  } catch (error) {
    await rm(directory, { recursive: true, force: true });
    throw error;
  }
  return {
    path: directory,
    async cleanup(): Promise<void> {
      await rm(directory, { recursive: true, force: true });
    }
  };
}

export async function writeCursorOutput(
  outputPath: string,
  stdout: string
): Promise<void> {
  if (Buffer.byteLength(stdout, "utf8") > MAX_PROVIDER_OUTPUT_BYTES) {
    throw new TypeError("Cursor response exceeds the output limit");
  }
  let outer: unknown;
  try {
    outer = JSON.parse(stdout);
  } catch {
    throw new TypeError("Cursor response is not JSON");
  }
  if (
    !plainRecord(outer) ||
    outer.type !== "result" ||
    typeof outer.result !== "string"
  ) {
    throw new TypeError("Cursor response has an unsupported shape");
  }
  const value = Buffer.from(outer.result, "utf8");
  if (value.length < 2 || value.length > MAX_PROVIDER_OUTPUT_BYTES) {
    throw new TypeError("Cursor result exceeds the output limit");
  }
  const handle = await open(outputPath, "wx", 0o600);
  try {
    await handle.writeFile(value);
    await handle.sync();
  } finally {
    await handle.close();
  }
}

export async function inspectProviderOutput(
  outputPath: string
): Promise<ProviderOutputEvidence> {
  const canonical = await realpath(outputPath);
  const handle = await open(
    outputPath,
    fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW
  );
  try {
    const info = await handle.stat();
    if (
      !info.isFile() ||
      info.uid !== effectiveUid() ||
      canonical !== outputPath ||
      info.size < 2 ||
      info.size > MAX_PROVIDER_OUTPUT_BYTES
    ) {
      throw new TypeError("Provider output metadata is invalid");
    }
    const value = await handle.readFile();
    if (value.length !== info.size) {
      throw new TypeError("Provider output changed while being inspected");
    }
    await handle.chmod(0o600);
    return {
      sha256: createHash("sha256").update(value).digest("hex"),
      size: value.length
    };
  } finally {
    await handle.close();
  }
}

import { constants as fsConstants } from "node:fs";
import {
  lstat,
  open,
  realpath,
  type FileHandle
} from "node:fs/promises";
import path from "node:path";
import type { Protocol } from "electron";

export const APP_SCHEME = "lcf";
export const APP_ORIGIN = "lcf://app";

export const CONTENT_SECURITY_POLICY = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'none'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-src 'none'",
  "frame-ancestors 'none'",
  "worker-src 'none'",
  "media-src 'none'",
  "manifest-src 'none'"
].join("; ");

const MIME_TYPES = new Map<string, string>([
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".mjs", "text/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".map", "application/json; charset=utf-8"],
  [".svg", "image/svg+xml"],
  [".png", "image/png"],
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".gif", "image/gif"],
  [".webp", "image/webp"],
  [".ico", "image/x-icon"],
  [".woff", "font/woff"],
  [".woff2", "font/woff2"],
  [".ttf", "font/ttf"],
  [".wasm", "application/wasm"]
]);

export class StaticProtocolError extends Error {
  constructor(readonly status: 400 | 403 | 404 | 405 | 415) {
    super(`Static protocol request rejected (${status})`);
    this.name = "StaticProtocolError";
  }
}

export interface StaticAsset {
  filePath: string;
  mimeType: string;
  html: boolean;
}

interface ParsedAppUrl {
  segments: string[];
}

export function parseAppUrl(rawUrl: string): ParsedAppUrl {
  if (typeof rawUrl !== "string" || rawUrl.length > 8_192) {
    throw new StaticProtocolError(400);
  }

  const match = /^lcf:\/\/([^/?#]*)(\/[^?#]*)?(\?[^#]*)?(#.*)?$/.exec(rawUrl);
  if (!match || match[1] !== "app" || match[3] || match[4]) {
    throw new StaticProtocolError(403);
  }

  const encodedPath = match[2] || "/";
  if (
    encodedPath.includes("\\") ||
    encodedPath.includes("//") ||
    /%(?:2f|5c)/i.test(encodedPath) ||
    /%(?![0-9a-fA-F]{2})/.test(encodedPath)
  ) {
    throw new StaticProtocolError(403);
  }

  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(encodedPath);
  } catch {
    throw new StaticProtocolError(400);
  }

  if (
    !decodedPath.startsWith("/") ||
    decodedPath.includes("\\") ||
    /[\u0000-\u001f\u007f]/.test(decodedPath)
  ) {
    throw new StaticProtocolError(403);
  }

  const rawSegments = decodedPath.slice(1).split("/");
  const segments = rawSegments.length === 1 && rawSegments[0] === ""
    ? ["index.html"]
    : rawSegments;
  if (
    segments.some(
      (segment) =>
        segment === "" ||
        segment === "." ||
        segment === ".." ||
        segment.includes("/") ||
        segment.normalize("NFC") !== segment
    )
  ) {
    throw new StaticProtocolError(403);
  }
  if (segments[0] === "api") {
    throw new StaticProtocolError(404);
  }

  return { segments };
}

function isWithin(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return (
    relative !== "" &&
    !relative.startsWith(`..${path.sep}`) &&
    relative !== ".." &&
    !path.isAbsolute(relative)
  );
}

async function openStaticFile(filePath: string): Promise<FileHandle> {
  const noFollow =
    typeof fsConstants.O_NOFOLLOW === "number" ? fsConstants.O_NOFOLLOW : 0;
  return open(filePath, fsConstants.O_RDONLY | noFollow);
}

export async function resolveStaticAsset(
  rendererRoot: string,
  rawUrl: string
): Promise<StaticAsset> {
  if (!path.isAbsolute(rendererRoot)) {
    throw new StaticProtocolError(403);
  }

  const rootInfo = await lstat(rendererRoot).catch(() => undefined);
  if (!rootInfo?.isDirectory() || rootInfo.isSymbolicLink()) {
    throw new StaticProtocolError(404);
  }
  const rootRealPath = await realpath(rendererRoot);
  const { segments } = parseAppUrl(rawUrl);

  let candidate = rootRealPath;
  for (const segment of segments) {
    candidate = path.join(candidate, segment);
    if (!isWithin(rootRealPath, candidate)) {
      throw new StaticProtocolError(403);
    }
    const info = await lstat(candidate).catch(() => undefined);
    if (!info) {
      throw new StaticProtocolError(404);
    }
    if (info.isSymbolicLink()) {
      throw new StaticProtocolError(403);
    }
  }

  const candidateRealPath = await realpath(candidate).catch(() => undefined);
  if (!candidateRealPath || !isWithin(rootRealPath, candidateRealPath)) {
    throw new StaticProtocolError(403);
  }
  const finalInfo = await lstat(candidateRealPath);
  if (!finalInfo.isFile() || finalInfo.isSymbolicLink()) {
    throw new StaticProtocolError(404);
  }

  const extension = path.extname(candidateRealPath).toLowerCase();
  const mimeType = MIME_TYPES.get(extension);
  if (!mimeType) {
    throw new StaticProtocolError(415);
  }

  return {
    filePath: candidateRealPath,
    mimeType,
    html: extension === ".html"
  };
}

export function registerPrivilegedScheme(
  register: Protocol["registerSchemesAsPrivileged"]
): void {
  register([
    {
      scheme: APP_SCHEME,
      privileges: {
        standard: true,
        secure: true,
        supportFetchAPI: true
      }
    }
  ]);
}

export function createStaticProtocolHandler(rendererRoot: string) {
  return async (request: Request): Promise<Response> => {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response(null, { status: 405 });
    }

    let handle: FileHandle | undefined;
    try {
      const asset = await resolveStaticAsset(rendererRoot, request.url);
      handle = await openStaticFile(asset.filePath);
      const body = request.method === "HEAD" ? null : await handle.readFile();
      const headers = new Headers({
        "Content-Type": asset.mimeType,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store"
      });
      if (asset.html) {
        headers.set("Content-Security-Policy", CONTENT_SECURITY_POLICY);
      }
      return new Response(body, { status: 200, headers });
    } catch (error) {
      const status =
        error instanceof StaticProtocolError ? error.status : 404;
      return new Response(null, {
        status,
        headers: {
          "Cache-Control": "no-store",
          "X-Content-Type-Options": "nosniff"
        }
      });
    } finally {
      await handle?.close().catch(() => undefined);
    }
  };
}

export async function installStaticProtocol(
  electronProtocol: Protocol,
  rendererRoot: string
): Promise<void> {
  await electronProtocol.handle(
    APP_SCHEME,
    createStaticProtocolHandler(rendererRoot)
  );
}

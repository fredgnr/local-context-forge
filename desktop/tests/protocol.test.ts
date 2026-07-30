import {
  mkdtemp,
  mkdir,
  symlink,
  writeFile
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  CONTENT_SECURITY_POLICY,
  StaticProtocolError,
  createStaticProtocolHandler,
  parseAppUrl,
  resolveStaticAsset
} from "../src/main/protocol";

describe("lcf static protocol", () => {
  let root: string;

  beforeEach(async () => {
    root = await mkdtemp(path.join(os.tmpdir(), "lcf-protocol-test-"));
    await mkdir(path.join(root, "assets"));
    await writeFile(path.join(root, "index.html"), "<!doctype html>");
    await writeFile(path.join(root, "assets", "app.js"), "export {};");
  });

  afterEach(async () => {
    const { rm } = await import("node:fs/promises");
    await rm(root, { recursive: true, force: true });
  });

  it("accepts only the exact app host and rejects query/userinfo/ports", () => {
    expect(parseAppUrl("lcf://app/")).toEqual({ segments: ["index.html"] });
    for (const url of [
      "lcf://evil/index.html",
      "lcf://app.evil/index.html",
      "lcf://user@app/index.html",
      "lcf://app:443/index.html",
      "lcf://app/index.html?debug=1"
    ]) {
      let error: unknown;
      try {
        parseAppUrl(url);
      } catch (caught) {
        error = caught;
      }
      expect(error, url).toBeInstanceOf(StaticProtocolError);
    }
  });

  it("rejects encoded traversal, separators, malformed encoding and /api", () => {
    for (const url of [
      "lcf://app/../secret",
      "lcf://app/%2e%2e/secret",
      "lcf://app/assets%2fsecret",
      "lcf://app/assets%5csecret",
      "lcf://app/%GG",
      "lcf://app/api/health"
    ]) {
      let error: unknown;
      try {
        parseAppUrl(url);
      } catch (caught) {
        error = caught;
      }
      expect(error, url).toBeInstanceOf(StaticProtocolError);
    }
  });

  it("resolves regular files with explicit MIME and rejects symlinks", async () => {
    await expect(
      resolveStaticAsset(root, "lcf://app/assets/app.js")
    ).resolves.toMatchObject({
      mimeType: "text/javascript; charset=utf-8",
      html: false
    });

    await symlink(
      path.join(root, "assets"),
      path.join(root, "linked-assets"),
      "dir"
    );
    await expect(
      resolveStaticAsset(root, "lcf://app/linked-assets/app.js")
    ).rejects.toMatchObject({ status: 403 });
  });

  it("adds the strict HTML CSP and never turns /api into a proxy", async () => {
    const handler = createStaticProtocolHandler(root);
    const response = await handler(new Request("lcf://app/"));
    expect(response.status).toBe(200);
    expect(response.headers.get("content-security-policy")).toBe(
      CONTENT_SECURITY_POLICY
    );
    for (const directive of [
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
    ]) {
      expect(CONTENT_SECURITY_POLICY).toContain(directive);
    }

    const apiResponse = await handler(new Request("lcf://app/api/health"));
    expect(apiResponse.status).toBe(404);
  });
});

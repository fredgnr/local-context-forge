import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = fileURLToPath(new URL("../", import.meta.url));
const guidePath = fileURLToPath(new URL("../app/guide.tsx", import.meta.url));
const pagePath = fileURLToPath(new URL("../app/page.tsx", import.meta.url));
const downloadRoot = fileURLToPath(
  new URL("../public/downloads/", import.meta.url),
);
const zipName = "local-context-forge-complete.zip";
const zipPath = `${downloadRoot}${zipName}`;
const checksumPath = `${zipPath}.sha256`;

const developmentPreviewMeta =
  /<meta(?=[^>]*\bname=["']codex-preview["'])(?=[^>]*\bcontent=["']development["'])[^>]*>/i;

let renderedHtmlPromise;

async function renderedHtml() {
  if (!renderedHtmlPromise) {
    renderedHtmlPromise = (async () => {
      const workerUrl = new URL("../dist/server/index.js", import.meta.url);
      workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
      const { default: worker } = await import(workerUrl.href);
      const response = await worker.fetch(
        new Request("http://localhost/", {
          headers: { accept: "text/html" },
        }),
        {
          ASSETS: {
            fetch: async () => new Response("Not found", { status: 404 }),
          },
        },
        {
          waitUntil() {},
          passThroughOnException() {},
        },
      );

      assert.equal(response.status, 200);
      assert.match(
        response.headers.get("content-type") ?? "",
        /^text\/html\b/i,
      );
      return response.text();
    })();
  }
  return renderedHtmlPromise;
}

test("renders development preview metadata", async () => {
  assert.match(await renderedHtml(), developmentPreviewMeta);
});

test("renders the all-in-one, queue, provider, model, and security contracts", async () => {
  const html = await renderedHtml();

  for (const expected of [
    "一个脚本",
    "FIFO",
    "Codex CLI",
    "Cursor CLI",
    "Host Runner",
    "EmbeddingGemma 300M",
    "失败不覆盖旧索引",
    "人工审核",
    "Context7-compatible MCP",
    "受信任的单用户 localhost",
    "约 640 MB 的重排模型",
    "约 1.1 GB 的查询扩展模型",
    "本次交付不生成 PDF",
  ]) {
    assert.match(html, new RegExp(expected));
  }

  assert.doesNotMatch(html, /~\/\.codex\/auth\.json/);
  assert.doesNotMatch(html, /\bappgprj_[a-z0-9]+\b/i);
});

test("keeps the novice and advanced operations copyable", async () => {
  const guide = await readFile(guidePath, "utf8");

  for (const expected of [
    "./install.sh",
    "./scripts/lcf status",
    "./scripts/lcf doctor",
    "./scripts/lcf logs",
    "--runtime docker-desktop",
    "--runtime colima",
    "--provider mock",
    "codex login status",
    "cursor-agent status",
    "http://127.0.0.1:8001/mcp",
    "./scripts/backup.sh",
    "./scripts/lcf uninstall",
  ]) {
    assert.ok(guide.includes(expected), `missing command fragment: ${expected}`);
  }

  assert.ok(!guide.includes("docker.sock"));
  assert.ok(!guide.includes("cursor-agent -p --force"));
});

test("links every downloadable artifact from the rendered page", async () => {
  const html = await renderedHtml();

  for (const href of [
    "/downloads/local-context-forge-complete.zip",
    "/downloads/local-context-forge-complete.zip.sha256",
  ]) {
    assert.match(html, new RegExp(`href="${href}"`));
  }
});

test("verifies the published ZIP and checksum without changing them", async (t) => {
  let zip;
  let checksum;
  let zipStats;
  try {
    [zip, checksum, zipStats] = await Promise.all([
      readFile(zipPath),
      readFile(checksumPath, "utf8"),
      stat(zipPath),
    ]);
  } catch (error) {
    if (error?.code === "ENOENT") {
      t.skip("release downloads are injected after building the self-contained source ZIP");
      return;
    }
    throw error;
  }

  assert.ok(zipStats.size > 0, "ZIP must not be empty");
  assert.deepEqual([...zip.subarray(0, 4)], [0x50, 0x4b, 0x03, 0x04]);

  const checksumMatch = checksum.match(
    /^([0-9a-f]{64}) {2}local-context-forge-complete\.zip\n?$/i,
  );
  assert.ok(checksumMatch, "checksum sidecar must name exactly the ZIP");
  assert.equal(createHash("sha256").update(zip).digest("hex"), checksumMatch[1]);

  const unzip = spawnSync("unzip", ["-t", zipPath], {
    cwd: root,
    encoding: "utf8",
  });
  assert.equal(
    unzip.status,
    0,
    `ZIP integrity check failed:\n${unzip.stdout}\n${unzip.stderr}`,
  );
});

test("does not place opaque hosting identity in user-facing source", async () => {
  const [guide, page] = await Promise.all([
    readFile(guidePath, "utf8"),
    readFile(pagePath, "utf8"),
  ]);
  assert.doesNotMatch(`${guide}\n${page}`, /\bappgprj_[a-z0-9]+\b/i);
});

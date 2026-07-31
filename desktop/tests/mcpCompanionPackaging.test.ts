import {
  cp,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  symlink,
  unlink,
  writeFile
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { afterEach, describe, expect, it } from "vitest";
import {
  MCP_LAUNCH_FILE_NAME,
  MCP_RUNTIME_DIRECTORY_PREFIX
} from "../src/mcpProtocol";

const audit = require("../scripts/auditCompanion.cjs") as {
  auditCompanion(options: {
    repositoryRoot: string;
    stagingRoot: string;
  }): { files: number; imports: number };
};

const repositoryRoot = path.resolve(__dirname, "..", "..");
const generatedRoot = path.join(
  repositoryRoot,
  "desktop",
  "generated",
  "companion"
);
const temporaryRoots: string[] = [];

async function copiedStaging(): Promise<string> {
  const root = await mkdtemp(
    path.join(os.tmpdir(), "lcf-mcp-packaging-")
  );
  temporaryRoots.push(root);
  const staging = path.join(root, "companion");
  await cp(generatedRoot, staging, {
    dereference: false,
    recursive: true
  });
  return staging;
}

afterEach(async () => {
  while (temporaryRoots.length > 0) {
    await rm(temporaryRoots.pop()!, {
      force: true,
      recursive: true
    });
  }
});

describe("MCP companion packaging audit", () => {
  it("serves the audited bundle over stdio without diagnostic bytes on stdout", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lcf-mcp-stdio-"));
    temporaryRoots.push(root);
    const tempRoot = path.join(root, "temp");
    await mkdir(tempRoot, { mode: 0o700 });
    const runtimeDirectory = await mkdtemp(
      path.join(tempRoot, MCP_RUNTIME_DIRECTORY_PREFIX)
    );
    const launchId = "00000000-0000-4000-8000-000000000001";
    await writeFile(
      path.join(runtimeDirectory, MCP_LAUNCH_FILE_NAME),
      `${JSON.stringify({
        launchId,
        schemaVersion: 1,
        socketName: "mcp.sock"
      })}\n`,
      { mode: 0o600 }
    );
    const transport = new StdioClientTransport({
      args: [path.join(generatedRoot, "index.mjs")],
      command: process.execPath,
      cwd: repositoryRoot,
      env: {
        LCF_MCP_DEBUG: "1",
        LCF_MCP_DEBUG_LAUNCH_ID: launchId,
        LCF_MCP_DEBUG_SOCKET: path.join(runtimeDirectory, "mcp.sock"),
        LCF_MCP_DEBUG_TEMP_ROOT: tempRoot
      },
      stderr: "pipe"
    });
    const stderr: Buffer[] = [];
    transport.stderr?.on("data", (chunk: Buffer | string) => {
      stderr.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    });
    const client = new Client({
      name: "packaged-entrypoint-contract-client",
      version: "1.0.0"
    });
    try {
      await client.connect(transport);
      const listed = await client.listTools();
      expect(listed.tools.map((tool) => tool.name)).toEqual([
        "resolve-library-id",
        "query-docs"
      ]);
      const unavailable = await client.callTool({
        arguments: { libraryName: "widgets" },
        name: "resolve-library-id"
      });
      expect(unavailable).toMatchObject({ isError: true });
      expect(JSON.stringify(unavailable)).toContain(
        "Start Local Context Forge"
      );
      expect(Buffer.concat(stderr).toString("utf8")).toBe("");
    } finally {
      await client.close().catch(() => undefined);
    }
  });

  it("accepts the reproducible SDK bundle and exact two-tool manifest", () => {
    expect(
      audit.auditCompanion({
        repositoryRoot,
        stagingRoot: generatedRoot
      })
    ).toMatchObject({
      files: 1
    });
  });

  it("rejects bundle, manifest, symlink, and inventory tampering", async () => {
    const bundleTamper = await copiedStaging();
    await writeFile(
      path.join(bundleTamper, "index.mjs"),
      "\n// tampered\n",
      { flag: "a" }
    );
    expect(() =>
      audit.auditCompanion({
        repositoryRoot,
        stagingRoot: bundleTamper
      })
    ).toThrow(/bundle bytes/);

    const manifestTamper = await copiedStaging();
    const manifestPath = path.join(
      manifestTamper,
      "build-manifest.json"
    );
    const manifest = JSON.parse(
      await readFile(manifestPath, "utf8")
    ) as Record<string, any>;
    manifest.tools = ["resolve-library-id", "publish"];
    await writeFile(manifestPath, JSON.stringify(manifest));
    expect(() =>
      audit.auditCompanion({
        repositoryRoot,
        stagingRoot: manifestTamper
      })
    ).toThrow(/tool allowlist/);

    const symlinkTamper = await copiedStaging();
    await unlink(path.join(symlinkTamper, "index.mjs"));
    await symlink(
      path.join(generatedRoot, "index.mjs"),
      path.join(symlinkTamper, "index.mjs")
    );
    expect(() =>
      audit.auditCompanion({
        repositoryRoot,
        stagingRoot: symlinkTamper
      })
    ).toThrow(/regular file/);

    const inventoryTamper = await copiedStaging();
    await writeFile(path.join(inventoryTamper, "unexpected.txt"), "extra");
    expect(() =>
      audit.auditCompanion({
        repositoryRoot,
        stagingRoot: inventoryTamper
      })
    ).toThrow(/unreviewed files/);
  });
});

import { createHash } from "node:crypto";
import {
  mkdir,
  mkdtemp,
  readFile,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";

type JsonObject = Record<string, any>;

const renderer = require("../scripts/auditRenderer.cjs") as {
  auditRenderer(
    root: string,
    options: {
      expectedCommit: string;
      expectedSourceDateEpoch: number;
      packageLockPath: string;
    }
  ): JsonObject;
  canonicalJson(value: unknown): string;
  inventory(root: string, options?: { excludeManifest?: boolean }): JsonObject[];
};
const rendererStage = require("../scripts/stageRenderer.cjs") as {
  selectSourceCommit(environment: NodeJS.ProcessEnv): string;
};

const roots: string[] = [];
const commit = "a".repeat(40);
const sourceDateEpoch = 1_700_000_000;

afterEach(async () => {
  await Promise.all(
    roots.splice(0).map((root) =>
      rm(root, { recursive: true, force: true })
    )
  );
});

async function fixture(): Promise<{
  root: string;
  packageLock: string;
  manifestPath: string;
}> {
  const workspace = await mkdtemp(path.join(os.tmpdir(), "lcf-renderer-"));
  roots.push(workspace);
  const root = path.join(workspace, "renderer");
  const assets = path.join(root, "assets");
  const packageLock = path.join(workspace, "package-lock.json");
  await mkdir(assets, { recursive: true });
  await Promise.all([
    writeFile(packageLock, '{"lockfileVersion":3}\n'),
    writeFile(
      path.join(root, "index.html"),
      [
        '<div id="root"></div>',
        '<script type="module" src="/assets/app.js"></script>',
        '<link rel="stylesheet" href="/assets/app.css">'
      ].join("\n")
    ),
    writeFile(path.join(assets, "app.js"), "globalThis.LCF = true;\n"),
    writeFile(path.join(assets, "app.css"), ":root { color: #111; }\n")
  ]);
  const files = renderer.inventory(root);
  const packageLockSha256 = createHash("sha256")
    .update(await readFile(packageLock))
    .digest("hex");
  const manifest = {
    schemaVersion: 1,
    kind: "local-context-forge-renderer-build",
    source: {
      repositoryCommit: commit,
      sourceDateEpoch,
      packageLockSha256
    },
    files
  };
  const manifestPath = path.join(root, "renderer-build-manifest.json");
  await writeFile(
    manifestPath,
    `${renderer.canonicalJson(manifest)}\n`
  );
  return { root, packageLock, manifestPath };
}

function auditOptions(packageLockPath: string) {
  return {
    expectedCommit: commit,
    expectedSourceDateEpoch: sourceDateEpoch,
    packageLockPath
  };
}

describe("production renderer packaging audit", () => {
  it("accepts a canonical manifest binding every production file", async () => {
    const value = await fixture();
    expect(
      renderer.auditRenderer(value.root, auditOptions(value.packageLock))
    ).toMatchObject({ files: 3 });
  });

  it("rejects byte tamper, manifest extras, and placeholder README files", async () => {
    const tampered = await fixture();
    await writeFile(
      path.join(tampered.root, "assets", "app.js"),
      "tampered\n"
    );
    expect(() =>
      renderer.auditRenderer(
        tampered.root,
        auditOptions(tampered.packageLock)
      )
    ).toThrow(/inventory/);

    const extra = await fixture();
    const manifest = JSON.parse(
      await readFile(extra.manifestPath, "utf8")
    ) as JsonObject;
    manifest.unreviewed = true;
    await writeFile(
      extra.manifestPath,
      `${renderer.canonicalJson(manifest)}\n`
    );
    expect(() =>
      renderer.auditRenderer(extra.root, auditOptions(extra.packageLock))
    ).toThrow(/invalid shape/);

    const readme = await fixture();
    await writeFile(path.join(readme.root, "README.html"), "placeholder\n");
    const readmeManifest = JSON.parse(
      await readFile(readme.manifestPath, "utf8")
    ) as JsonObject;
    readmeManifest.files = renderer.inventory(readme.root, {
      excludeManifest: true
    });
    await writeFile(
      readme.manifestPath,
      `${renderer.canonicalJson(readmeManifest)}\n`
    );
    expect(() =>
      renderer.auditRenderer(
        readme.root,
        auditOptions(readme.packageLock)
      )
    ).toThrow(/placeholder README/);
  });

  it("rejects symlinks and remote or development index references", async () => {
    const linked = await fixture();
    await symlink(
      "app.js",
      path.join(linked.root, "assets", "linked.js")
    );
    expect(() =>
      renderer.auditRenderer(linked.root, auditOptions(linked.packageLock))
    ).toThrow(/symlinks/);

    const remote = await fixture();
    await writeFile(
      path.join(remote.root, "index.html"),
      [
        '<div id="root"></div>',
        "<script type=\"module\" src='//example.invalid/app.js'></script>",
        '<link rel="stylesheet" href="/assets/app.css">'
      ].join("\n")
    );
    const remoteManifest = JSON.parse(
      await readFile(remote.manifestPath, "utf8")
    ) as JsonObject;
    remoteManifest.files = renderer.inventory(remote.root, {
      excludeManifest: true
    });
    await writeFile(
      remote.manifestPath,
      `${renderer.canonicalJson(remoteManifest)}\n`
    );
    expect(() =>
      renderer.auditRenderer(remote.root, auditOptions(remote.packageLock))
    ).toThrow(/development marker|remote origin/);
  });
});

describe("renderer staging source provenance", () => {
  it("prefers the exact source SHA over a synthetic GitHub SHA", () => {
    expect(
      rendererStage.selectSourceCommit({
        LCF_SOURCE_SHA: "a".repeat(40),
        GITHUB_SHA: "b".repeat(40)
      })
    ).toBe("a".repeat(40));
  });

  it("preserves formal-workflow fallback to GITHUB_SHA", () => {
    expect(
      rendererStage.selectSourceCommit({
        GITHUB_SHA: "b".repeat(40)
      })
    ).toBe("b".repeat(40));
    expect(
      rendererStage.selectSourceCommit({
        LCF_SOURCE_SHA: "",
        GITHUB_SHA: "b".repeat(40)
      })
    ).toBe("b".repeat(40));
  });

  it("rejects an invalid explicit source SHA instead of falling back", () => {
    expect(() =>
      rendererStage.selectSourceCommit({
        LCF_SOURCE_SHA: "not-a-commit",
        GITHUB_SHA: "b".repeat(40)
      })
    ).toThrow(/LCF_SOURCE_SHA/);
  });
});

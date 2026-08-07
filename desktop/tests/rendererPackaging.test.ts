import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { renameSync, writeFileSync } from "node:fs";
import {
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";

type JsonObject = Record<string, any>;

const renderer = require("../scripts/auditRenderer.cjs") as {
  auditRenderer(
    root: string,
    options: {
      expectedCommit: string;
      expectedTree: string;
      expectedSourceSnapshotSha256: string;
      expectedSourceDateEpoch: number;
      expectedPackageLockSha256: string;
    }
  ): JsonObject;
  canonicalJson(value: unknown): string;
  inventory(root: string, options?: { excludeManifest?: boolean }): JsonObject[];
};
const rendererStage = require("../scripts/stageRenderer.cjs") as {
  selectSourceCommit(environment: NodeJS.ProcessEnv): string;
  validateProvenance(
    environment: NodeJS.ProcessEnv,
    dependencies?: {
      gitCommand(arguments_: string[]): string;
    }
  ): JsonObject;
  stageRendererTransaction(
    options: {
      source: string;
      destination: string;
      release: JsonObject;
      environment: NodeJS.ProcessEnv;
      afterSourceValidation?: () => void;
    },
    dependencies?: {
      validateSourceAttestation?: () => JsonObject;
      auditRenderer?: () => JsonObject;
      rename?: (source: string, destination: string) => void;
    }
  ): JsonObject;
};
const prepare = require("../scripts/prepareEngineeringSmoke.cjs") as {
  inspectRepositorySourceSnapshot(
    repositoryRoot: string,
    environment: NodeJS.ProcessEnv
  ): JsonObject;
};
const rendererBuilder = require(
  "../../web/scripts/buildEngineeringRenderer.cjs"
) as {
  buildRendererFromSnapshot(options: JsonObject): Promise<JsonObject>;
  selectReviewedRendererInputs(
    snapshot: JsonObject,
    repositoryRoot: string
  ): { byPath: Map<string, JsonObject>; bytesByPath: Map<string, Buffer> };
};

const roots: string[] = [];
const repositoryRoot = path.resolve(__dirname, "..", "..");
const commit = "a".repeat(40);
const tree = "b".repeat(40);
const sourceSnapshotSha256 = "c".repeat(64);
const inputSnapshotSha256 = "d".repeat(64);
const rendererPackageLockSha256 = "e".repeat(64);
const sourceDateEpoch = 1_700_000_000;
const sealedRendererBuilder = {
  name: "vite",
  version: "7.3.6",
  reactPluginVersion: "4.7.0",
  nodeVersion: "v22.23.2",
  npmVersion: "10.9.8",
  installedContentSha256: "f".repeat(64)
};

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
  packageLockSha256: string;
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
      repositoryTree: tree,
      sourceSnapshotSha256,
      sourceDateEpoch,
      packageLockSha256,
      inputSnapshotSha256,
      inputFiles: 12
    },
    builder: sealedRendererBuilder,
    files
  };
  const manifestPath = path.join(root, "renderer-build-manifest.json");
  await writeFile(
    manifestPath,
    `${renderer.canonicalJson(manifest)}\n`
  );
  return { root, packageLock, packageLockSha256, manifestPath };
}

function auditOptions(packageLockSha256: string) {
  return {
    expectedCommit: commit,
    expectedTree: tree,
    expectedSourceSnapshotSha256: sourceSnapshotSha256,
    expectedSourceDateEpoch: sourceDateEpoch,
    expectedPackageLockSha256: packageLockSha256
  };
}

function provenanceGit(
  overrides: Map<string, string | Error> = new Map()
): {
  calls: string[][];
  gitCommand(arguments_: string[]): string;
} {
  const calls: string[][] = [];
  const outputs = new Map<string, string | Error>([
    [["rev-parse", "HEAD"].join("\0"), commit],
    [
      ["show", "-s", "--format=%ct", "HEAD"].join("\0"),
      String(sourceDateEpoch)
    ],
    [
      ["status", "--porcelain=v1", "--untracked-files=all"].join("\0"),
      ""
    ],
    [
      ["ls-files", "--", "desktop/resources/renderer"].join("\0"),
      ""
    ],
    [
      [
        "check-ignore",
        "-v",
        "--",
        "desktop/resources/renderer/"
      ].join("\0"),
      ".gitignore:26:desktop/resources/renderer/\tdesktop/resources/renderer/"
    ],
    ...overrides
  ]);
  return {
    calls,
    gitCommand(arguments_: string[]): string {
      calls.push([...arguments_]);
      const result = outputs.get(arguments_.join("\0"));
      if (result instanceof Error) {
        throw result;
      }
      if (result === undefined) {
        throw new Error("unexpected Git command");
      }
      return result;
    }
  };
}

describe("reviewed renderer build provenance", () => {
  it("selects committed Git object bytes before the reviewed renderer build", async () => {
    const canonicalTemporaryParent = await realpath(os.tmpdir());
    const workspace = await mkdtemp(
      path.join(canonicalTemporaryParent, "lcf-renderer-build-")
    );
    roots.push(workspace);
    const repository = path.join(workspace, "repository");
    const webRoot = path.join(repository, "web");
    const sourceRoot = path.join(webRoot, "src");
    await mkdir(sourceRoot, { recursive: true });
    await mkdir(path.join(repository, "desktop"), { recursive: true });
    const markerPath = path.join(sourceRoot, "marker.ts");
    const reviewedMarker = 'export const marker = "reviewed-renderer-marker";\n';
    await Promise.all([
      writeFile(
        path.join(webRoot, "index.html"),
        '<!doctype html>\n<div id="root"></div>\n<script type="module" src="/src/main.tsx"></script>\n'
      ),
      writeFile(
        path.join(webRoot, "package.json"),
        '{"name":"renderer-fixture","private":true,"type":"module"}\n'
      ),
      writeFile(
        path.join(repository, "desktop", "package.json"),
        '{"name":"desktop-fixture","version":"0.0.0"}\n'
      ),
      writeFile(
        path.join(webRoot, "package-lock.json"),
        `${JSON.stringify({
          lockfileVersion: 3,
          packages: {
            "node_modules/vite": { version: "7.3.6" },
            "node_modules/@vitejs/plugin-react": { version: "4.7.0" }
          }
        })}\n`
      ),
      writeFile(
        path.join(webRoot, "tsconfig.app.json"),
        '{"compilerOptions":{"target":"ES2022","jsx":"react-jsx"}}\n'
      ),
      writeFile(
        path.join(sourceRoot, "main.tsx"),
        'import { marker } from "./marker";\ndocument.body.dataset.marker = marker;\n'
      ),
      writeFile(markerPath, reviewedMarker)
    ]);
    const gitEnvironment = {
      PATH: "/usr/bin:/bin",
      LANG: "C",
      LC_ALL: "C",
      GIT_CONFIG_NOSYSTEM: "1",
      GIT_CONFIG_GLOBAL: "/dev/null",
      GIT_TERMINAL_PROMPT: "0"
    };
    const git = (...arguments_: string[]): string =>
      execFileSync("/usr/bin/git", ["-C", repository, ...arguments_], {
        encoding: "utf8",
        env: gitEnvironment
      }).trim();
    git("init", "--quiet");
    git("add", "--all");
    git(
      "-c",
      "user.name=LCF Test",
      "-c",
      "user.email=lcf-test@example.invalid",
      "commit",
      "--quiet",
      "-m",
      "fixture"
    );
    const sourceCommit = git("rev-parse", "HEAD");
    const sourceTree = git("rev-parse", "HEAD^{tree}");
    const sourceEpoch = git("show", "-s", "--format=%ct", "HEAD");
    const environment = {
      LCF_SOURCE_SHA: sourceCommit,
      LCF_SOURCE_TREE: sourceTree,
      LCF_SOURCE_DATE_EPOCH: sourceEpoch,
      LCF_SOURCE_SNAPSHOT_SHA256: createHash("sha256")
        .update(
          Buffer.from(
            renderer.canonicalJson(
              git("ls-tree", "-r", "--full-tree", "HEAD")
                .split("\n")
                .filter(Boolean)
                .map((line) => {
                  const match = /^(\d+) (\w+) ([0-9a-f]{40})\t(.+)$/.exec(line);
                  if (!match) {
                    throw new Error("invalid Git fixture inventory");
                  }
                  return {
                    mode: match[1],
                    type: match[2],
                    objectId: match[3],
                    path: match[4]!
                  };
                })
                .sort((left, right) =>
                  left.path < right.path ? -1 : left.path > right.path ? 1 : 0
                )
            ),
            "utf8"
          )
        )
        .digest("hex"),
      LCF_RENDERER_PACKAGE_LOCK_SHA256: createHash("sha256")
        .update(await readFile(path.join(webRoot, "package-lock.json")))
        .digest("hex")
    };
    const snapshot = prepare.inspectRepositorySourceSnapshot(
      repository,
      environment
    );
    const viteImplementation = await import(
      pathToFileURL(
        path.join(repositoryRoot, "web", "node_modules", "vite", "dist", "node", "index.js")
      ).href
    );
    const reactPluginModule = await import(
      pathToFileURL(
        path.join(
          repositoryRoot,
          "web",
          "node_modules",
          "@vitejs",
          "plugin-react",
          "dist",
          "index.js"
        )
      ).href
    );
    const distRoot = path.join(workspace, "renderer-output");
    const attestation = await rendererBuilder.buildRendererFromSnapshot({
      snapshot,
      repositoryRoot: repository,
      webRoot,
      distRoot,
      environment,
      viteImplementation,
      reactPluginFactory: reactPluginModule.default,
      installSummary: {
        installedContentSha256: "f".repeat(64),
        lockSha256: environment.LCF_RENDERER_PACKAGE_LOCK_SHA256,
        nodeVersion: "v22.23.2",
        npmVersion: "10.9.8"
      }
    });
    const outputText = (
      await Promise.all(
        renderer
          .inventory(distRoot)
          .filter((record) => /\.(?:html|js|css)$/.test(record.path))
          .map((record) => readFile(path.join(distRoot, record.path), "utf8"))
      )
    ).join("\n");
    expect(outputText).toContain("reviewed-renderer-marker");
    expect(outputText).not.toContain("transient-renderer-marker");
    expect(attestation).toMatchObject({
      kind: "reviewed-renderer-build",
      source: { repositoryCommit: sourceCommit, repositoryTree: sourceTree },
      builder: { name: "vite", version: "7.3.6" }
    });
    await writeFile(
      markerPath,
      'export const marker = "transient-renderer-marker";\n'
    );
    const selectedInputs = rendererBuilder.selectReviewedRendererInputs(
      snapshot,
      repository
    );
    expect(selectedInputs.bytesByPath.get("web/src/marker.ts")).toEqual(
      Buffer.from(reviewedMarker, "utf8")
    );
    await writeFile(markerPath, reviewedMarker);
  });

  it("refuses source drift after attestation without replacing staged output", async () => {
    const workspace = await mkdtemp(
      path.join(await realpath(os.tmpdir()), "lcf-renderer-stage-race-")
    );
    roots.push(workspace);
    const source = path.join(workspace, "source");
    const destination = path.join(workspace, "destination");
    await mkdir(path.join(source, "assets"), { recursive: true });
    await mkdir(destination, { recursive: true });
    const sourceFile = path.join(source, "assets", "app.js");
    const oldFile = path.join(destination, "old.js");
    await writeFile(sourceFile, "reviewed-renderer-output\n");
    await writeFile(oldFile, "existing-staged-output\n");
    const expectedOutputs = renderer.inventory(source);
    const audit = vi.fn(() => {
      throw new Error("publish audit must not run after source drift");
    });

    expect(() =>
      rendererStage.stageRendererTransaction(
        {
          source,
          destination,
          release: {
            commit,
            tree,
            sourceSnapshotSha256,
            sourceDateEpoch,
            rendererPackageLockSha256
          },
          environment: {},
          afterSourceValidation: () => {
            writeFileSync(sourceFile, "transient-unreviewed-renderer-output\n");
          }
        },
        {
          validateSourceAttestation: () => ({
            inputs: 5,
            inputsSha256: inputSnapshotSha256,
            packageLockSha256: rendererPackageLockSha256,
            builder: sealedRendererBuilder,
            outputs: expectedOutputs
          }),
          auditRenderer: audit
        }
      )
    ).toThrow(/source output/);
    expect(await readFile(oldFile, "utf8")).toBe("existing-staged-output\n");
    expect(audit).not.toHaveBeenCalled();
  });

  it("restores the old staging directory when atomic publish fails", async () => {
    const workspace = await mkdtemp(
      path.join(await realpath(os.tmpdir()), "lcf-renderer-publish-race-")
    );
    roots.push(workspace);
    const source = path.join(workspace, "source");
    const destination = path.join(workspace, "destination");
    await mkdir(path.join(source, "assets"), { recursive: true });
    await mkdir(destination, { recursive: true });
    await writeFile(path.join(source, "assets", "app.js"), "reviewed\n");
    const oldFile = path.join(destination, "old.js");
    await writeFile(oldFile, "existing-staged-output\n");
    const outputs = renderer.inventory(source);
    let renameCount = 0;

    expect(() =>
      rendererStage.stageRendererTransaction(
        {
          source,
          destination,
          release: {
            commit,
            tree,
            sourceSnapshotSha256,
            sourceDateEpoch,
            rendererPackageLockSha256
          },
          environment: {}
        },
        {
          validateSourceAttestation: () => ({
            inputs: 5,
            inputsSha256: inputSnapshotSha256,
            packageLockSha256: rendererPackageLockSha256,
            builder: sealedRendererBuilder,
            outputs
          }),
          auditRenderer: () => ({ files: outputs.length }),
          rename: (from, to) => {
            renameCount += 1;
            if (renameCount === 2) {
              throw new Error("injected renderer publish failure");
            }
            renameSync(from, to);
          }
        }
      )
    ).toThrow(/injected renderer publish failure/);
    expect(renameCount).toBe(3);
    expect(await readFile(oldFile, "utf8")).toBe("existing-staged-output\n");
  });
});

describe("production renderer packaging audit", () => {
  it("accepts a canonical manifest binding every production file", async () => {
    const value = await fixture();
    expect(
      renderer.auditRenderer(value.root, auditOptions(value.packageLockSha256))
    ).toMatchObject({ files: 3 });
  });

  it("uses the reviewed lock digest instead of a mutable live lock path", async () => {
    const value = await fixture();
    await writeFile(value.packageLock, '{"lockfileVersion":999}\n');
    expect(
      renderer.auditRenderer(
        value.root,
        auditOptions(value.packageLockSha256)
      )
    ).toMatchObject({
      packageLockSha256: value.packageLockSha256
    });
    expect(() =>
      renderer.auditRenderer(
        value.root,
        auditOptions("f".repeat(64))
      )
    ).toThrow(/reviewed source object/);
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
        auditOptions(tampered.packageLockSha256)
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
      renderer.auditRenderer(extra.root, auditOptions(extra.packageLockSha256))
    ).toThrow(/invalid shape/);

    const versionDrift = await fixture();
    const versionManifest = JSON.parse(
      await readFile(versionDrift.manifestPath, "utf8")
    ) as JsonObject;
    versionManifest.builder.nodeVersion = "v22.23.3";
    versionManifest.builder.npmVersion = "10.9.9";
    await writeFile(
      versionDrift.manifestPath,
      `${renderer.canonicalJson(versionManifest)}\n`
    );
    expect(() =>
      renderer.auditRenderer(
        versionDrift.root,
        auditOptions(versionDrift.packageLockSha256)
      )
    ).toThrow(/invalid shape|builder is invalid/);

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
        auditOptions(readme.packageLockSha256)
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
      renderer.auditRenderer(linked.root, auditOptions(linked.packageLockSha256))
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
      renderer.auditRenderer(remote.root, auditOptions(remote.packageLockSha256))
    ).toThrow(/development marker|remote origin/);
  });
});

describe("renderer staging source provenance", () => {
  it("checks the exact clean source and ignored destination boundary", () => {
    const fake = provenanceGit();

    expect(
      rendererStage.validateProvenance(
        {
          LCF_SOURCE_SHA: commit,
          LCF_SOURCE_TREE: tree,
          LCF_SOURCE_SNAPSHOT_SHA256: sourceSnapshotSha256,
          LCF_SOURCE_DATE_EPOCH: String(sourceDateEpoch),
          LCF_RENDERER_PACKAGE_LOCK_SHA256: rendererPackageLockSha256
        },
        { gitCommand: fake.gitCommand }
      )
    ).toEqual({
      commit,
      tree,
      sourceSnapshotSha256,
      sourceDateEpoch,
      rendererPackageLockSha256
    });
    expect(fake.calls).toEqual([
      ["rev-parse", "HEAD"],
      ["show", "-s", "--format=%ct", "HEAD"],
      ["status", "--porcelain=v1", "--untracked-files=all"],
      ["ls-files", "--", "desktop/resources/renderer"],
      [
        "check-ignore",
        "-v",
        "--",
        "desktop/resources/renderer/"
      ]
    ]);
  });

  it("still rejects dirty source outside ignored build outputs", () => {
    const status = [
      "status",
      "--porcelain=v1",
      "--untracked-files=all"
    ].join("\0");
    const fake = provenanceGit(
      new Map([[status, "?? /private/token-must-not-leak"]])
    );

    expect(() =>
      rendererStage.validateProvenance(
        {
          LCF_SOURCE_SHA: commit,
          LCF_SOURCE_TREE: tree,
          LCF_SOURCE_SNAPSHOT_SHA256: sourceSnapshotSha256,
          LCF_SOURCE_DATE_EPOCH: String(sourceDateEpoch),
          LCF_RENDERER_PACKAGE_LOCK_SHA256: rendererPackageLockSha256
        },
        { gitCommand: fake.gitCommand }
      )
    ).toThrow(/^Renderer staging requires a clean reviewed source commit$/);
  });

  it("rejects a tracked renderer destination without leaking its path", () => {
    const trackedDestination = [
      "ls-files",
      "--",
      "desktop/resources/renderer"
    ].join("\0");
    const fake = provenanceGit(
      new Map([
        [
          trackedDestination,
          "desktop/resources/renderer/token-must-not-leak.js"
        ]
      ])
    );

    expect(() =>
      rendererStage.validateProvenance(
        {
          LCF_SOURCE_SHA: commit,
          LCF_SOURCE_TREE: tree,
          LCF_SOURCE_SNAPSHOT_SHA256: sourceSnapshotSha256,
          LCF_SOURCE_DATE_EPOCH: String(sourceDateEpoch),
          LCF_RENDERER_PACKAGE_LOCK_SHA256: rendererPackageLockSha256
        },
        { gitCommand: fake.gitCommand }
      )
    ).toThrow(/^Renderer staging destination overlaps tracked source$/);
  });

  it("rejects a missing destination ignore policy with a fixed error", () => {
    const ignoreProbe = [
      "check-ignore",
      "-v",
      "--",
      "desktop/resources/renderer/"
    ].join("\0");
    const fake = provenanceGit(
      new Map([
        [
          ignoreProbe,
          new Error("token-must-not-leak /private/path-must-not-leak")
        ]
      ])
    );

    expect(() =>
      rendererStage.validateProvenance(
        {
          LCF_SOURCE_SHA: commit,
          LCF_SOURCE_TREE: tree,
          LCF_SOURCE_SNAPSHOT_SHA256: sourceSnapshotSha256,
          LCF_SOURCE_DATE_EPOCH: String(sourceDateEpoch),
          LCF_RENDERER_PACKAGE_LOCK_SHA256: rendererPackageLockSha256
        },
        { gitCommand: fake.gitCommand }
      )
    ).toThrow(
      /^Renderer staging destination is not covered by the reviewed Git ignore policy$/
    );
  });

  it("rejects ignore evidence from outside the reviewed root rule", () => {
    const ignoreDirectory = [
      "check-ignore",
      "-v",
      "--",
      "desktop/resources/renderer/"
    ].join("\0");
    const fake = provenanceGit(
      new Map([
        [
          ignoreDirectory,
          "/private/global-ignore:1:desktop/resources/renderer/\t" +
            "desktop/resources/renderer/"
        ]
      ])
    );

    expect(() =>
      rendererStage.validateProvenance(
        {
          LCF_SOURCE_SHA: commit,
          LCF_SOURCE_TREE: tree,
          LCF_SOURCE_SNAPSHOT_SHA256: sourceSnapshotSha256,
          LCF_SOURCE_DATE_EPOCH: String(sourceDateEpoch),
          LCF_RENDERER_PACKAGE_LOCK_SHA256: rendererPackageLockSha256
        },
        { gitCommand: fake.gitCommand }
      )
    ).toThrow(
      /^Renderer staging destination is not covered by the reviewed Git ignore policy$/
    );
  });

  it("prefers the exact source SHA over a synthetic GitHub SHA", () => {
    expect(
      rendererStage.selectSourceCommit({
        LCF_SOURCE_SHA: "a".repeat(40),
        GITHUB_SHA: "b".repeat(40)
      })
    ).toBe("a".repeat(40));
  });

  it("rejects synthetic-context fallback when exact source SHA is absent", () => {
    expect(() =>
      rendererStage.selectSourceCommit({
        GITHUB_SHA: "b".repeat(40)
      })
    ).toThrow(/LCF_SOURCE_SHA/);
    expect(() =>
      rendererStage.selectSourceCommit({
        LCF_SOURCE_SHA: "",
        GITHUB_SHA: "b".repeat(40)
      })
    ).toThrow(/LCF_SOURCE_SHA/);
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

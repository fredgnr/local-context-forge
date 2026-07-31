"use strict";

const fs = require("node:fs");
const path = require("node:path");
const esbuild = require("esbuild");
const {
  ENTRYPOINT,
  EXPECTED_DEPENDENCIES,
  EXPECTED_KIND,
  MANIFEST_NAME,
  auditCompanion,
  canonicalJson,
  inputDigests,
  sha256File
} = require("./auditCompanion.cjs");

async function buildCompanion() {
  const repositoryRoot = path.resolve(__dirname, "..", "..");
  const desktopRoot = path.join(repositoryRoot, "desktop");
  const stagingRoot = path.join(desktopRoot, "generated", "companion");
  const expectedRoot = path.join(
    repositoryRoot,
    "desktop",
    "generated",
    "companion"
  );
  if (stagingRoot !== expectedRoot) {
    throw new Error("Unexpected companion staging path");
  }
  fs.rmSync(stagingRoot, { force: true, recursive: true });
  fs.mkdirSync(stagingRoot, { mode: 0o700, recursive: true });
  const outputPath = path.join(stagingRoot, ENTRYPOINT);
  const result = await esbuild.build({
    bundle: true,
    entryPoints: [path.join(desktopRoot, "companion", "src", "index.ts")],
    format: "esm",
    legalComments: "none",
    logLevel: "silent",
    metafile: true,
    minify: false,
    outfile: outputPath,
    platform: "node",
    sourcemap: false,
    target: ["node22"]
  });
  const relativeOutput = Object.keys(result.metafile.outputs).find(
    (candidate) => path.resolve(candidate) === outputPath
  );
  if (!relativeOutput) {
    throw new Error("Companion output metadata is missing");
  }
  const imports = result.metafile.outputs[relativeOutput].imports
    .map((entry) => ({
      path: entry.path,
      kind: entry.kind,
      external: entry.external
    }))
    .sort((left, right) =>
      `${left.path}:${left.kind}`.localeCompare(`${right.path}:${right.kind}`)
    );
  if (
    imports.some(
      (entry) => entry.external !== true || !entry.path.startsWith("node:")
    )
  ) {
    throw new Error("Companion has an unexpected external import");
  }
  const packages = [
    ...new Set(
      Object.keys(result.metafile.inputs)
        .map((input) =>
          input.match(
            /node_modules\/((?:@[^/]+\/)?[^/]+)/
          )?.[1]
        )
        .filter((name) => name !== undefined)
    )
  ].sort();
  if (
    canonicalJson(packages) !==
    canonicalJson(Object.keys(EXPECTED_DEPENDENCIES))
  ) {
    throw new Error("Companion bundled dependency closure changed");
  }
  const versions = JSON.parse(
    fs.readFileSync(
      path.join(repositoryRoot, "runtime", "version.json"),
      "utf8"
    )
  );
  const bundle = sha256File(outputPath);
  const manifest = {
    schemaVersion: 1,
    kind: EXPECTED_KIND,
    entrypoint: ENTRYPOINT,
    product: {
      appVersion: versions.productVersion,
      mcpContract: versions.mcpContract,
      bridgeProtocol: "1.0"
    },
    target: {
      os: "darwin",
      architecture: "arm64",
      nodeMajor: 22,
      moduleFormat: "esm"
    },
    dependencies: EXPECTED_DEPENDENCIES,
    tools: ["resolve-library-id", "query-docs"],
    sourceInputs: inputDigests(repositoryRoot),
    bundle: {
      files: [
        {
          path: ENTRYPOINT,
          size: bundle.size,
          sha256: bundle.sha256
        }
      ],
      imports,
      packages
    }
  };
  fs.writeFileSync(
    path.join(stagingRoot, MANIFEST_NAME),
    canonicalJson(manifest),
    { encoding: "utf8", mode: 0o600 }
  );
  auditCompanion({ repositoryRoot, stagingRoot });
}

buildCompanion().catch(() => {
  process.stderr.write("[lcf-mcp-build] companion-build-failed\n");
  process.exitCode = 1;
});

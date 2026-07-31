import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createStore } from "@tobilu/qmd";

const MODEL =
  "hf:ggml-org/embeddinggemma-300M-GGUF/" +
  "embeddinggemma-300M-Q8_0.gguf";

test("locked QMD SDK accepts the model-aware store config and lexical API without loading a model", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "lcf-qmd-sdk-"));
  const docs = path.join(root, "docs");
  await mkdir(docs);
  await writeFile(
    path.join(docs, "widgets.md"),
    "# Widgets\n\nBuild a semantic widget safely.\n",
    "utf8"
  );
  let store;
  try {
    store = await createStore({
      dbPath: path.join(root, "index.sqlite"),
      config: {
        collections: {
          docs: { path: docs, pattern: "**/*.md" }
        },
        models: { embed: MODEL }
      }
    });
  } catch (error) {
    if (String(error).includes("Could not locate the bindings file")) {
      await rm(root, { recursive: true, force: true });
      t.skip("better-sqlite3 native binding is not built in source checkout");
      return;
    }
    throw error;
  }
  t.after(async () => {
    await store.close().catch(() => undefined);
    await rm(root, { recursive: true, force: true });
  });

  assert.equal(store.internal.llm.embedModelName, MODEL);
  const update = await store.update({ collections: ["docs"] });
  assert.equal(update.collections, 1);
  assert.equal(update.indexed, 1);
  const results = await store.searchLex("semantic widget", {
    collection: "docs",
    limit: 5
  });
  assert.equal(results.length, 1);
  assert.equal(results[0].collectionName, "docs");
  assert.equal(results[0].displayPath, "docs/widgets.md");
});

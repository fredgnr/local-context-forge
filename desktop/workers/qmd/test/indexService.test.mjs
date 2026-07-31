import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, symlink } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { ContractError, MAX_COLLECTIONS } from "../src/contract.mjs";
import {
  QmdIndexService,
  resolveCollectionRoot
} from "../src/indexService.mjs";

const PROFILE = {
  kind: "curated",
  model:
    "hf:ggml-org/embeddinggemma-300M-GGUF/" +
    "embeddinggemma-300M-Q8_0.gguf"
};
const SECOND_PROFILE = {
  kind: "curated",
  model:
    "hf:Qwen/Qwen3-Embedding-0.6B-GGUF/" +
    "Qwen3-Embedding-0.6B-Q8_0.gguf"
};
const LEXICAL = { mode: "lexical", profile: null };

class MemoryStateStore {
  value;
  saves = [];

  async load() {
    return this.value;
  }

  async save(value) {
    this.value = structuredClone(value);
    this.saves.push(structuredClone(value));
  }
}

class FakeStore {
  collections = new Map();
  calls = [];
  lexicalResults = [];
  hybridResults = [];
  embedResult = {
    docsProcessed: 1,
    chunksEmbedded: 1,
    errors: 0,
    durationMs: 5
  };
  embedError = null;
  health = { needsEmbedding: 0, totalDocs: 1, daysStale: 0 };

  async listCollections() {
    return [...this.collections.entries()].map(([name, value]) => ({
      name,
      pwd: value.path,
      glob_pattern: value.pattern
    }));
  }

  async addCollection(name, options) {
    this.calls.push(["add", name, options.path]);
    this.collections.set(name, options);
  }

  async removeCollection(name) {
    this.calls.push(["remove", name]);
    return this.collections.delete(name);
  }

  async update(options) {
    this.calls.push(["update", [...options.collections]]);
    return {
      collections: options.collections.length,
      indexed: 1,
      updated: 0,
      unchanged: 0,
      removed: 0,
      needsEmbedding: 1
    };
  }

  async embed(options) {
    this.calls.push(["embed", options]);
    if (this.embedError) {
      throw this.embedError;
    }
    options.onProgress?.({
      chunksEmbedded: 1,
      totalChunks: 1,
      bytesProcessed: 10,
      totalBytes: 10,
      errors: 0
    });
    return this.embedResult;
  }

  async getIndexHealth() {
    this.calls.push(["health"]);
    return this.health;
  }

  async searchLex(query, options) {
    this.calls.push(["searchLex", query, options]);
    return this.lexicalResults;
  }

  async search(options) {
    this.calls.push(["searchHybrid", options]);
    return this.hybridResults;
  }

  async close() {
    this.calls.push(["close"]);
  }
}

async function fixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "lcf-qmd-worker-"));
  const wiki = path.join(root, "wiki");
  await mkdir(path.join(wiki, "alpha", "versions", "v1"), {
    recursive: true
  });
  await mkdir(path.join(wiki, "beta", "versions", "v2"), {
    recursive: true
  });
  const store = new FakeStore();
  const stateStore = new MemoryStateStore();
  const service = new QmdIndexService({
    store,
    openStore: async () => store,
    wikiRoot: wiki,
    modelCacheDir: path.join(root, "cache", "qmd", "models"),
    stateStore,
    inspectModelCache: async () => true
  });
  return { root, wiki, store, stateStore, service };
}

test("reconcile commits the complete allowlist and revision before lexical search", async (t) => {
  const current = await fixture();
  t.after(() => rm(current.root, { recursive: true, force: true }));
  current.store.collections.set("removed", {
    path: "/old",
    pattern: "**/*.md"
  });

  const result = await current.service.reconcile({
    revision: 7,
    collections: [
      {
        name: "lcf-alpha-v1-0123456789ab",
        wiki_root: "alpha/versions/v1"
      }
    ],
    embedding: LEXICAL
  });
  assert.equal(result.indexed, true);
  assert.equal(result.revision, 7);
  assert.deepEqual(current.stateStore.value, {
    revision: 7,
    collections: [
      {
        name: "lcf-alpha-v1-0123456789ab",
        wiki_root: "alpha/versions/v1"
      }
    ],
    embedding: {
      status: "stale",
      profile: null,
      revision: null,
      model_status: "not_requested",
      error: null
    }
  });
  assert.deepEqual(
    current.store.calls.map((call) => call[0]),
    ["add", "remove", "update"]
  );

  current.store.lexicalResults = [
    {
      displayPath: "qmd://lcf-alpha-v1-0123456789ab/api/widgets.md",
      collectionName: "lcf-alpha-v1-0123456789ab",
      title: "Widgets",
      score: 2.5
    }
  ];
  assert.deepEqual(
    await current.service.search({
      revision: 7,
      collection: "lcf-alpha-v1-0123456789ab",
      query: "widgets",
      limit: 5,
      mode: "lexical",
      profile: null
    }),
    {
      revision: 7,
      mode: "lexical",
      results: [{ path: "api/widgets.md", score: 2.5, title: "Widgets" }]
    }
  );
});

test("model switch closes and reopens a profile-configured store before forced embed and hybrid query", async (t) => {
  const current = await fixture();
  t.after(() => rm(current.root, { recursive: true, force: true }));
  const modelStore = new FakeStore();
  const opened = [];
  const service = new QmdIndexService({
    store: current.store,
    openStore: async (profile, collections) => {
      opened.push({
        profile: structuredClone(profile),
        collections: collections.map((item) => item.name)
      });
      return modelStore;
    },
    wikiRoot: current.wiki,
    modelCacheDir: path.join(current.root, "cache", "qmd", "models"),
    stateStore: current.stateStore,
    inspectModelCache: async (_cache, profile) =>
      profile.model === PROFILE.model
  });

  const rebuilt = await service.reconcile({
    revision: 11,
    collections: [
      {
        name: "alpha",
        wiki_root: "alpha/versions/v1"
      }
    ],
    embedding: { mode: "rebuild", profile: PROFILE }
  });

  assert.deepEqual(opened, [
    { profile: PROFILE, collections: ["alpha"] }
  ]);
  const embedOptions = modelStore.calls.find(
    (call) => call[0] === "embed"
  )[1];
  assert.equal(typeof embedOptions.onProgress, "function");
  assert.deepEqual(
    {
      force: embedOptions.force,
      model: embedOptions.model,
      chunkStrategy: embedOptions.chunkStrategy,
      maxDocsPerBatch: embedOptions.maxDocsPerBatch,
      maxBatchBytes: embedOptions.maxBatchBytes
    },
    {
      force: true,
      model: PROFILE.model,
      chunkStrategy: "auto",
      maxDocsPerBatch: 50,
      maxBatchBytes: 64 * 1024 * 1024
    }
  );
  assert.equal(rebuilt.embedding.status, "ready");
  assert.equal(rebuilt.embedding.revision, 11);
  assert.deepEqual(rebuilt.embedding.profile, PROFILE);

  modelStore.hybridResults = [
    {
      file: "qmd://alpha/api/semantic.md",
      title: "Semantic",
      score: 0.9
    }
  ];
  const result = await service.search({
    revision: 11,
    collection: "alpha",
    query: "meaning",
    limit: 5,
    mode: "hybrid",
    profile: PROFILE
  });
  assert.equal(result.mode, "hybrid");
  assert.deepEqual(result.results.map((item) => item.path), [
    "api/semantic.md"
  ]);
  const hybridCall = modelStore.calls.find(
    (call) => call[0] === "searchHybrid"
  );
  assert.deepEqual(hybridCall[1].queries, [
    { type: "lex", query: "meaning" },
    { type: "vec", query: "meaning" }
  ]);
  assert.equal(hybridCall[1].rerank, false);
  assert.equal(
    current.store.calls.some((call) => call[0] === "searchHybrid"),
    false
  );
});

test("switch failure persists stale then failed and keeps the reopened lexical store usable", async (t) => {
  const current = await fixture();
  t.after(() => rm(current.root, { recursive: true, force: true }));
  const lexicalStore = new FakeStore();
  let opens = 0;
  const service = new QmdIndexService({
    store: current.store,
    openStore: async (profile) => {
      opens += 1;
      if (profile) {
        throw new Error("/private/cache/model failed");
      }
      return lexicalStore;
    },
    wikiRoot: current.wiki,
    modelCacheDir: path.join(current.root, "cache", "qmd", "models"),
    stateStore: current.stateStore,
    inspectModelCache: async () => false
  });

  const rebuilt = await service.reconcile({
    revision: 12,
    collections: [
      {
        name: "alpha",
        wiki_root: "alpha/versions/v1"
      }
    ],
    embedding: { mode: "rebuild", profile: SECOND_PROFILE }
  });

  assert.equal(opens, 2);
  assert.equal(rebuilt.indexed, true);
  assert.deepEqual(rebuilt.embedding, {
    status: "failed",
    profile: SECOND_PROFILE,
    revision: null,
    model_status: "unavailable",
    error: "model_unavailable"
  });
  assert.equal(JSON.stringify(rebuilt).includes("/private"), false);
  assert.equal(
    lexicalStore.calls.some((call) => call[0] === "embed"),
    false
  );
  assert.equal(current.stateStore.saves[0].embedding.status, "stale");
  assert.equal(current.stateStore.saves.at(-1).embedding.status, "failed");

  await assert.rejects(
    service.search({
      revision: 12,
      collection: "alpha",
      query: "meaning",
      limit: 5,
      mode: "hybrid",
      profile: SECOND_PROFILE
    }),
    (error) =>
      error instanceof ContractError && error.code === "stale_index"
  );
  assert.equal(
    (
      await service.search({
        revision: 12,
        collection: "alpha",
        query: "meaning",
        limit: 5,
        mode: "lexical",
        profile: null
      })
    ).mode,
    "lexical"
  );
});

test("disk-full or partial-cache embedding errors never leak paths or restore ready state", async (t) => {
  const current = await fixture();
  t.after(() => rm(current.root, { recursive: true, force: true }));
  const modelStore = new FakeStore();
  modelStore.embedError = new Error(
    "ENOSPC while writing /private/cache/qmd/models/model.partial"
  );
  const service = new QmdIndexService({
    store: current.store,
    openStore: async () => modelStore,
    wikiRoot: current.wiki,
    modelCacheDir: path.join(current.root, "cache", "qmd", "models"),
    stateStore: current.stateStore,
    // A valid cached GGUF may exist even when vector DB writes run out of
    // space. It still cannot make the partial vector rebuild ready.
    inspectModelCache: async () => true
  });

  const rebuilt = await service.reconcile({
    revision: 18,
    collections: [
      {
        name: "alpha",
        wiki_root: "alpha/versions/v1"
      }
    ],
    embedding: { mode: "rebuild", profile: PROFILE }
  });

  assert.equal(current.stateStore.saves[0].embedding.status, "stale");
  assert.deepEqual(rebuilt.embedding, {
    status: "failed",
    profile: PROFILE,
    revision: null,
    model_status: "ready",
    error: "embedding_failed"
  });
  assert.equal(JSON.stringify(rebuilt).includes("/private/cache"), false);
  assert.equal(current.stateStore.value.embedding.status, "failed");
});

test("oversize reconcile and unsafe model profiles fail before mutating QMD", async (t) => {
  const current = await fixture();
  t.after(() => rm(current.root, { recursive: true, force: true }));
  const collections = Array.from(
    { length: MAX_COLLECTIONS + 1 },
    (_, index) => ({
      name: `collection-${index}`,
      wiki_root: "alpha/versions/v1"
    })
  );

  assert.throws(
    () =>
      current.service.reconcile({
        revision: 1,
        collections,
        embedding: LEXICAL
      }),
    (error) =>
      error instanceof ContractError &&
      error.code === "too_many_collections"
  );
  assert.throws(
    () =>
      current.service.reconcile({
        revision: 1,
        collections: [],
        embedding: {
          mode: "rebuild",
          profile: {
            kind: "custom",
            model: "https://example.invalid/model.gguf"
          }
        }
      }),
    (error) =>
      error instanceof ContractError &&
      error.code === "invalid_model_profile"
  );
  assert.deepEqual(current.store.calls, []);
  assert.equal(current.stateStore.value, undefined);
});

test("stale revisions, removed collections, and mismatched profiles never reach hybrid search", async (t) => {
  const current = await fixture();
  t.after(() => rm(current.root, { recursive: true, force: true }));
  await current.service.reconcile({
    revision: 1,
    collections: [
      {
        name: "alpha",
        wiki_root: "alpha/versions/v1"
      }
    ],
    embedding: LEXICAL
  });
  current.store.calls = [];

  for (const input of [
    {
      revision: 2,
      collection: "alpha",
      query: "widgets",
      limit: 5,
      mode: "lexical",
      profile: null
    },
    {
      revision: 1,
      collection: "beta",
      query: "widgets",
      limit: 5,
      mode: "lexical",
      profile: null
    },
    {
      revision: 1,
      collection: "alpha",
      query: "widgets",
      limit: 5,
      mode: "hybrid",
      profile: PROFILE
    }
  ]) {
    await assert.rejects(
      current.service.search(input),
      (error) =>
        error instanceof ContractError && error.code === "stale_index"
    );
  }
  assert.deepEqual(current.store.calls, []);
});

test("wiki roots reject traversal and every symlink component", async (t) => {
  const current = await fixture();
  t.after(() => rm(current.root, { recursive: true, force: true }));
  await symlink(
    path.join(current.wiki, "alpha"),
    path.join(current.wiki, "linked"),
    "dir"
  );

  await assert.rejects(resolveCollectionRoot(current.wiki, "../outside"));
  await assert.rejects(
    resolveCollectionRoot(current.wiki, "linked/versions/v1"),
    (error) =>
      error instanceof ContractError && error.code === "invalid_path"
  );
});

test("a persisted lexical allowlist restores after a worker restart", async (t) => {
  const current = await fixture();
  t.after(() => rm(current.root, { recursive: true, force: true }));
  const name = "lcf-alpha-v1-0123456789ab";
  await current.service.reconcile({
    revision: 9,
    collections: [{ name, wiki_root: "alpha/versions/v1" }],
    embedding: LEXICAL
  });

  const restarted = new QmdIndexService({
    store: current.store,
    openStore: async () => current.store,
    wikiRoot: current.wiki,
    modelCacheDir: path.join(current.root, "cache", "qmd", "models"),
    stateStore: current.stateStore,
    inspectModelCache: async () => true
  });
  await restarted.initialize();
  current.store.lexicalResults = [];
  assert.deepEqual(
    await restarted.search({
      revision: 9,
      collection: name,
      query: "widgets",
      limit: 5,
      mode: "lexical",
      profile: null
    }),
    { revision: 9, mode: "lexical", results: [] }
  );
});

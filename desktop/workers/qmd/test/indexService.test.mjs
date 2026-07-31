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

class MemoryStateStore {
  value;

  async load() {
    return this.value;
  }

  async save(value) {
    this.value = structuredClone(value);
  }
}

class FakeStore {
  collections = new Map();
  calls = [];
  results = [];

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

  async searchLex(query, options) {
    this.calls.push(["search", query, options.collection, options.limit]);
    return this.results;
  }

  async close() {}
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
    wikiRoot: wiki,
    stateStore
  });
  return { root, wiki, store, stateStore, service };
}

test("reconcile commits the complete allowlist and revision before search", async (t) => {
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
    ]
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
    ]
  });
  assert.deepEqual(
    current.store.calls.map((call) => call[0]),
    ["add", "remove", "update"]
  );

  current.store.results = [
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
      limit: 5
    }),
    {
      revision: 7,
      results: [{ path: "api/widgets.md", score: 2.5, title: "Widgets" }]
    }
  );
});

test("oversize reconcile fails before mutating the fake store", async (t) => {
  const current = await fixture();
  t.after(() => rm(current.root, { recursive: true, force: true }));
  const collections = Array.from({ length: MAX_COLLECTIONS + 1 }, (_, index) => ({
    name: `collection-${index}`,
    wiki_root: "alpha/versions/v1"
  }));

  assert.throws(
    () => current.service.reconcile({ revision: 1, collections }),
    (error) =>
      error instanceof ContractError &&
      error.code === "too_many_collections"
  );
  assert.deepEqual(current.store.calls, []);
  assert.equal(current.stateStore.value, undefined);
});

test("stale revisions and removed collections never reach QMD search", async (t) => {
  const current = await fixture();
  t.after(() => rm(current.root, { recursive: true, force: true }));
  await current.service.reconcile({
    revision: 1,
    collections: [
      {
        name: "alpha",
        wiki_root: "alpha/versions/v1"
      }
    ]
  });
  current.store.calls = [];

  await assert.rejects(
    current.service.search({
      revision: 2,
      collection: "alpha",
      query: "widgets",
      limit: 5
    }),
    (error) =>
      error instanceof ContractError && error.code === "stale_index"
  );
  await assert.rejects(
    current.service.search({
      revision: 1,
      collection: "beta",
      query: "widgets",
      limit: 5
    }),
    (error) =>
      error instanceof ContractError && error.code === "stale_index"
  );
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

test("a persisted committed allowlist restores after a worker restart", async (t) => {
  const current = await fixture();
  t.after(() => rm(current.root, { recursive: true, force: true }));
  const name = "lcf-alpha-v1-0123456789ab";
  await current.service.reconcile({
    revision: 9,
    collections: [
      { name, wiki_root: "alpha/versions/v1" }
    ]
  });

  const restarted = new QmdIndexService({
    store: current.store,
    wikiRoot: current.wiki,
    stateStore: current.stateStore
  });
  await restarted.initialize();
  current.store.results = [];
  assert.deepEqual(
    await restarted.search({
      revision: 9,
      collection: name,
      query: "widgets",
      limit: 5
    }),
    { revision: 9, results: [] }
  );
});

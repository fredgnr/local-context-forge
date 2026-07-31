import {
  lstat,
  mkdir,
  open,
  readFile,
  readdir,
  realpath,
  rename,
  writeFile
} from "node:fs/promises";
import path from "node:path";
import {
  ContractError,
  hasExactKeys,
  parseReconcileBody,
  parseSearchBody,
  sameModelProfile,
  validateModelProfile,
  validateRelativeWikiRoot,
  validateResultPath,
  validateRevision
} from "./contract.mjs";

const STATE_SCHEMA_VERSION = 2;
const MARKDOWN_PATTERN = "**/*.md";
const MAX_EMBED_DOCS_PER_BATCH = 50;
const MAX_EMBED_BATCH_BYTES = 64 * 1024 * 1024;
const EMBEDDING_ERROR_CODES = new Set([
  "model_unavailable",
  "embedding_failed"
]);

function isWithin(root, candidate) {
  const relative = path.relative(root, candidate);
  return (
    relative !== "" &&
    relative !== ".." &&
    !relative.startsWith(`..${path.sep}`) &&
    !path.isAbsolute(relative)
  );
}

async function validateDirectory(pathname) {
  const metadata = await lstat(pathname).catch(() => undefined);
  if (!metadata?.isDirectory() || metadata.isSymbolicLink()) {
    throw new ContractError(422, "invalid_path");
  }
}

export async function canonicalWikiRoot(wikiRoot) {
  await validateDirectory(wikiRoot);
  return realpath(wikiRoot);
}

export async function resolveCollectionRoot(wikiRoot, relativeRoot) {
  validateRelativeWikiRoot(relativeRoot);
  const canonicalRoot = await canonicalWikiRoot(wikiRoot);
  let candidate = canonicalRoot;
  for (const part of relativeRoot.split("/")) {
    candidate = path.join(candidate, part);
    if (!isWithin(canonicalRoot, candidate)) {
      throw new ContractError(422, "invalid_path");
    }
    await validateDirectory(candidate);
  }
  const resolved = await realpath(candidate);
  if (!isWithin(canonicalRoot, resolved) || resolved !== candidate) {
    throw new ContractError(422, "invalid_path");
  }
  return resolved;
}

function staleEmbedding(profile = null, modelStatus = "not_requested") {
  return {
    status: "stale",
    profile,
    revision: null,
    model_status: modelStatus,
    error: null
  };
}

function failedEmbedding(profile, modelStatus, error) {
  return {
    status: "failed",
    profile,
    revision: null,
    model_status: modelStatus,
    error
  };
}

function cloneProfile(profile) {
  return profile ? { kind: profile.kind, model: profile.model } : null;
}

function cloneEmbedding(embedding) {
  return {
    status: embedding.status,
    profile: cloneProfile(embedding.profile),
    revision: embedding.revision,
    model_status: embedding.model_status,
    error: embedding.error
  };
}

function validateStoredEmbedding(value) {
  if (
    !hasExactKeys(value, [
      "status",
      "profile",
      "revision",
      "model_status",
      "error"
    ]) ||
    !["ready", "stale", "failed"].includes(value.status) ||
    !["not_requested", "ready", "unavailable"].includes(
      value.model_status
    ) ||
    (value.profile !== null && typeof value.profile !== "object") ||
    (value.revision !== null &&
      (!Number.isSafeInteger(value.revision) || value.revision < 0)) ||
    (value.error !== null && !EMBEDDING_ERROR_CODES.has(value.error))
  ) {
    throw new ContractError(500, "invalid_state");
  }
  const profile =
    value.profile === null ? null : validateModelProfile(value.profile);
  if (
    (value.status === "ready" &&
      (!profile ||
        value.revision === null ||
        value.model_status !== "ready" ||
        value.error !== null)) ||
    (value.status === "failed" &&
      (!profile ||
        value.revision !== null ||
        value.error === null)) ||
    (value.status === "stale" &&
      (value.revision !== null || value.error !== null))
  ) {
    throw new ContractError(500, "invalid_state");
  }
  return {
    status: value.status,
    profile,
    revision: value.revision,
    model_status: value.model_status,
    error: value.error
  };
}

function validateStoredState(value) {
  if (
    !hasExactKeys(
      value,
      ["schema_version", "revision", "collections"],
      ["embedding"]
    ) ||
    ![1, STATE_SCHEMA_VERSION].includes(value.schema_version) ||
    !Array.isArray(value.collections) ||
    (value.schema_version === 1 && value.embedding !== undefined) ||
    (value.schema_version === STATE_SCHEMA_VERSION &&
      value.embedding === undefined)
  ) {
    throw new ContractError(500, "invalid_state");
  }
  const reconciled = parseReconcileBody({
    revision: validateRevision(value.revision),
    collections: value.collections,
    embedding: { mode: "lexical", profile: null }
  });
  return {
    revision: reconciled.revision,
    collections: reconciled.collections,
    embedding:
      value.schema_version === 1
        ? staleEmbedding()
        : validateStoredEmbedding(value.embedding)
  };
}

export class FileStateStore {
  constructor(statePath) {
    this.statePath = statePath;
  }

  async load() {
    let contents;
    try {
      contents = await readFile(this.statePath, "utf8");
    } catch (error) {
      if (error?.code === "ENOENT") {
        return undefined;
      }
      throw error;
    }
    return validateStoredState(JSON.parse(contents));
  }

  async save(state) {
    const payload = `${JSON.stringify({
      schema_version: STATE_SCHEMA_VERSION,
      revision: state.revision,
      collections: state.collections,
      embedding: state.embedding
    })}\n`;
    const temporary = `${this.statePath}.tmp`;
    await mkdir(path.dirname(this.statePath), {
      recursive: true,
      mode: 0o700
    });
    await writeFile(temporary, payload, { encoding: "utf8", mode: 0o600 });
    await rename(temporary, this.statePath);
  }
}

export async function hasCachedModel(modelCacheDir, profile) {
  const filename = profile.model.split("/").at(-1);
  if (!filename) {
    return false;
  }
  const entries = await readdir(modelCacheDir, {
    withFileTypes: true
  }).catch((error) => {
    if (error?.code === "ENOENT") {
      return [];
    }
    throw error;
  });
  for (const entry of entries) {
    if (
      !entry.isFile() ||
      entry.isSymbolicLink() ||
      !entry.name.includes(filename)
    ) {
      continue;
    }
    const candidate = path.join(modelCacheDir, entry.name);
    const metadata = await lstat(candidate).catch(() => undefined);
    if (
      !metadata?.isFile() ||
      metadata.isSymbolicLink() ||
      metadata.size < 4 ||
      (await realpath(candidate).catch(() => "")) !== candidate
    ) {
      continue;
    }
    const handle = await open(candidate, "r").catch(() => undefined);
    if (!handle) {
      continue;
    }
    try {
      const header = Buffer.alloc(4);
      const { bytesRead } = await handle.read(header, 0, 4, 0);
      if (bytesRead === 4 && header.toString("ascii") === "GGUF") {
        return true;
      }
    } finally {
      await handle.close();
    }
  }
  return false;
}

function candidatePath(item) {
  for (const key of ["displayPath", "filepath", "path", "file"]) {
    if (typeof item?.[key] === "string") {
      return validateResultPath(item[key]);
    }
  }
  throw new ContractError(502, "invalid_response");
}

function normalizeSearchResults(items, collection, limit) {
  if (!Array.isArray(items) || items.length > limit) {
    throw new ContractError(502, "invalid_response");
  }
  const results = [];
  const used = new Set();
  for (const item of items) {
    if (
      item === null ||
      typeof item !== "object" ||
      (item.collectionName !== undefined &&
        item.collectionName !== collection)
    ) {
      throw new ContractError(502, "invalid_response");
    }
    const resultPath = candidatePath(item);
    if (used.has(resultPath)) {
      continue;
    }
    const score = Number(item.score);
    if (!Number.isFinite(score)) {
      throw new ContractError(502, "invalid_response");
    }
    const title =
      typeof item.title === "string"
        ? item.title.replaceAll("\0", "").slice(0, 1_000)
        : "";
    results.push({ path: resultPath, score, title });
    used.add(resultPath);
  }
  return results;
}

function validateUpdate(update) {
  if (update === null || typeof update !== "object") {
    throw new ContractError(502, "invalid_response");
  }
  const normalized = {};
  for (const name of [
    "indexed",
    "updated",
    "unchanged",
    "removed",
    "needsEmbedding"
  ]) {
    const value = Number(update[name] ?? 0);
    if (!Number.isSafeInteger(value) || value < 0) {
      throw new ContractError(502, "invalid_response");
    }
    normalized[name] = value;
  }
  return normalized;
}

function validateHealth(health) {
  if (
    health === null ||
    typeof health !== "object" ||
    !Number.isSafeInteger(health.needsEmbedding) ||
    health.needsEmbedding < 0
  ) {
    throw new ContractError(502, "invalid_response");
  }
  return health;
}

function reconcileResponse(committed, update) {
  return {
    indexed: true,
    revision: committed.revision,
    collections: committed.collections.length,
    update: {
      indexed: update.indexed,
      updated: update.updated,
      unchanged: update.unchanged,
      removed: update.removed
    },
    embedding: cloneEmbedding(committed.embedding)
  };
}

export class QmdIndexService {
  constructor({
    store,
    openStore,
    wikiRoot,
    modelCacheDir,
    stateStore,
    inspectModelCache = hasCachedModel
  }) {
    this.store = store;
    this.openStore = openStore;
    this.wikiRoot = wikiRoot;
    this.modelCacheDir = modelCacheDir;
    this.stateStore = stateStore;
    this.inspectModelCache = inspectModelCache;
    this.loadedProfile = null;
    this.revision = undefined;
    this.collections = new Map();
    this.embedding = staleEmbedding();
    this.activity = "idle";
    this.operation = Promise.resolve();
  }

  async desiredCollections(collections) {
    const desired = [];
    for (const collection of collections) {
      desired.push({
        ...collection,
        absoluteRoot: await resolveCollectionRoot(
          this.wikiRoot,
          collection.wiki_root
        )
      });
    }
    return desired;
  }

  async replaceStore(profile, desired) {
    if (sameModelProfile(this.loadedProfile, profile)) {
      return true;
    }
    this.activity = "switching_model";
    await this.store.close();
    try {
      this.store = await this.openStore(profile, desired);
      this.loadedProfile = cloneProfile(profile);
      return true;
    } catch {
      try {
        this.store = await this.openStore(null, desired);
        this.loadedProfile = null;
      } catch {
        throw new ContractError(503, "qmd_unavailable");
      }
      return false;
    } finally {
      this.activity = "idle";
    }
  }

  async initialize() {
    const state = await this.stateStore.load().catch(() => undefined);
    if (!state) {
      return;
    }
    const desired = await this.desiredCollections(state.collections);
    let modelOpened = true;
    if (state.embedding.profile) {
      modelOpened = await this.replaceStore(
        state.embedding.profile,
        desired
      );
    }
    const listed = await this.store.listCollections();
    const names = new Set(
      Array.isArray(listed) ? listed.map((item) => item?.name) : []
    );
    const restored = new Map();
    for (const collection of state.collections) {
      if (!names.has(collection.name)) {
        return;
      }
      await resolveCollectionRoot(this.wikiRoot, collection.wiki_root);
      restored.set(collection.name, collection.wiki_root);
    }
    let embedding = cloneEmbedding(state.embedding);
    if (embedding.status === "ready") {
      const cached =
        modelOpened &&
        (await this.inspectModelCache(
          this.modelCacheDir,
          embedding.profile
        ).catch(() => false));
      const health = cached
        ? await this.store.getIndexHealth().catch(() => undefined)
        : undefined;
      if (
        !cached ||
        !health ||
        !Number.isSafeInteger(health.needsEmbedding) ||
        health.needsEmbedding !== 0
      ) {
        embedding = staleEmbedding(
          embedding.profile,
          cached ? "ready" : "unavailable"
        );
      }
    }
    this.collections = restored;
    this.revision = state.revision;
    this.embedding = embedding;
    if (
      embedding.status !== state.embedding.status ||
      embedding.model_status !== state.embedding.model_status
    ) {
      await this.persist();
    }
  }

  runExclusive(operation) {
    const result = this.operation.then(operation, operation);
    this.operation = result.catch(() => undefined);
    return result;
  }

  committedState() {
    return {
      revision: this.revision,
      collections: [...this.collections].map(([name, wiki_root]) => ({
        name,
        wiki_root
      })),
      embedding: cloneEmbedding(this.embedding)
    };
  }

  async persist() {
    if (this.revision === undefined) {
      return;
    }
    await this.stateStore.save(this.committedState());
  }

  async syncCollections(desired) {
    const existingList = await this.store.listCollections();
    if (!Array.isArray(existingList)) {
      throw new ContractError(502, "invalid_response");
    }
    const existing = new Map(
      existingList
        .filter((item) => item && typeof item.name === "string")
        .map((item) => [item.name, item])
    );
    const desiredNames = new Set(desired.map((item) => item.name));

    for (const item of desired) {
      const current = existing.get(item.name);
      if (
        !current ||
        current.pwd !== item.absoluteRoot ||
        current.glob_pattern !== MARKDOWN_PATTERN
      ) {
        await this.store.addCollection(item.name, {
          path: item.absoluteRoot,
          pattern: MARKDOWN_PATTERN
        });
      }
    }
    for (const name of existing.keys()) {
      if (!desiredNames.has(name)) {
        await this.store.removeCollection(name);
      }
    }
    return validateUpdate(
      desired.length === 0
        ? {
            indexed: 0,
            updated: 0,
            unchanged: 0,
            removed: 0,
            needsEmbedding: 0
          }
        : await this.store.update({
            collections: desired.map((item) => item.name)
          })
    );
  }

  reconcile(input) {
    const request = parseReconcileBody(input);
    return this.runExclusive(async () => {
      const desired = await this.desiredCollections(request.collections);
      let modelOpened = true;
      if (
        request.embedding.mode === "rebuild" &&
        !sameModelProfile(this.loadedProfile, request.embedding.profile)
      ) {
        modelOpened = await this.replaceStore(
          request.embedding.profile,
          desired
        );
      }
      const update = await this.syncCollections(desired);
      const previous = cloneEmbedding(this.embedding);
      this.revision = request.revision;
      this.collections = new Map(
        desired.map((item) => [item.name, item.wiki_root])
      );

      if (request.embedding.mode === "lexical") {
        let embedding = staleEmbedding(
          previous.profile,
          previous.profile ? previous.model_status : "not_requested"
        );
        if (
          previous.status === "ready" &&
          previous.revision === request.revision &&
          update.needsEmbedding === 0 &&
          sameModelProfile(this.loadedProfile, previous.profile)
        ) {
          const cached = await this.inspectModelCache(
            this.modelCacheDir,
            previous.profile
          ).catch(() => false);
          const health = cached
            ? await this.store.getIndexHealth().catch(() => undefined)
            : undefined;
          if (cached && health && validateHealth(health).needsEmbedding === 0) {
            embedding = previous;
          } else {
            embedding.model_status = cached ? "ready" : "unavailable";
          }
        }
        this.embedding = embedding;
        await this.persist();
        return reconcileResponse(this.committedState(), update);
      }

      const profile = request.embedding.profile;
      const cachedBefore = await this.inspectModelCache(
        this.modelCacheDir,
        profile
      ).catch(() => false);
      this.embedding = staleEmbedding(
        profile,
        cachedBefore ? "ready" : "unavailable"
      );
      // A model switch or force rebuild can clear incompatible vectors. Commit
      // stale before invoking QMD so a crash can never restore a ready marker.
      await this.persist();

      if (!modelOpened) {
        this.embedding = failedEmbedding(
          profile,
          "unavailable",
          "model_unavailable"
        );
        await this.persist();
        return reconcileResponse(this.committedState(), update);
      }

      try {
        this.activity = "preparing_model";
        const result = await this.store.embed({
          force: true,
          model: profile.model,
          chunkStrategy: "auto",
          maxDocsPerBatch: MAX_EMBED_DOCS_PER_BATCH,
          maxBatchBytes: MAX_EMBED_BATCH_BYTES,
          onProgress: () => {
            this.activity = "embedding";
          }
        });
        const cached = await this.inspectModelCache(
          this.modelCacheDir,
          profile
        ).catch(() => false);
        if (
          result === null ||
          typeof result !== "object" ||
          !Number.isSafeInteger(result.errors) ||
          result.errors !== 0
        ) {
          this.embedding = failedEmbedding(
            profile,
            cached ? "ready" : "unavailable",
            cached ? "embedding_failed" : "model_unavailable"
          );
        } else {
          const health = validateHealth(await this.store.getIndexHealth());
          if (!cached || health.needsEmbedding !== 0) {
            this.embedding = failedEmbedding(
              profile,
              cached ? "ready" : "unavailable",
              cached ? "embedding_failed" : "model_unavailable"
            );
          } else {
            this.embedding = {
              status: "ready",
              profile: cloneProfile(profile),
              revision: request.revision,
              model_status: "ready",
              error: null
            };
          }
        }
      } catch {
        const cached = await this.inspectModelCache(
          this.modelCacheDir,
          profile
        ).catch(() => false);
        this.embedding = failedEmbedding(
          profile,
          cached ? "ready" : "unavailable",
          cached ? "embedding_failed" : "model_unavailable"
        );
      } finally {
        this.activity = "idle";
      }
      await this.persist();
      return reconcileResponse(this.committedState(), update);
    });
  }

  search(input) {
    const request = parseSearchBody(input);
    return this.runExclusive(async () => {
      if (
        this.revision === undefined ||
        request.revision !== this.revision ||
        !this.collections.has(request.collection)
      ) {
        throw new ContractError(409, "stale_index");
      }
      let raw;
      if (request.mode === "hybrid") {
        if (
          this.embedding.status !== "ready" ||
          this.embedding.revision !== request.revision ||
          !sameModelProfile(this.embedding.profile, request.profile) ||
          !sameModelProfile(this.loadedProfile, request.profile)
        ) {
          throw new ContractError(409, "stale_index");
        }
        const cached = await this.inspectModelCache(
          this.modelCacheDir,
          request.profile
        ).catch(() => false);
        const health = cached
          ? await this.store.getIndexHealth().catch(() => undefined)
          : undefined;
        if (
          !cached ||
          !health ||
          !Number.isSafeInteger(health.needsEmbedding) ||
          health.needsEmbedding !== 0
        ) {
          this.embedding = staleEmbedding(
            request.profile,
            cached ? "ready" : "unavailable"
          );
          await this.persist();
          throw new ContractError(409, "stale_index");
        }
        try {
          raw = await this.store.search({
            queries: [
              { type: "lex", query: request.query },
              { type: "vec", query: request.query }
            ],
            rerank: false,
            collection: request.collection,
            limit: request.limit,
            candidateLimit: Math.min(
              Math.max(request.limit * 4, 20),
              100
            )
          });
        } catch {
          const stillCached = await this.inspectModelCache(
            this.modelCacheDir,
            request.profile
          ).catch(() => false);
          this.embedding = failedEmbedding(
            request.profile,
            stillCached ? "ready" : "unavailable",
            stillCached ? "embedding_failed" : "model_unavailable"
          );
          await this.persist();
          throw new ContractError(
            503,
            stillCached ? "embedding_failed" : "model_unavailable"
          );
        }
      } else {
        raw = await this.store.searchLex(request.query, {
          collection: request.collection,
          limit: request.limit
        });
      }
      return {
        revision: this.revision,
        mode: request.mode,
        results: normalizeSearchResults(
          raw,
          request.collection,
          request.limit
        )
      };
    });
  }

  status() {
    return {
      revision: this.revision ?? null,
      collections: this.collections.size,
      embedding: cloneEmbedding(this.embedding),
      activity: this.activity
    };
  }

  async close() {
    await this.operation.catch(() => undefined);
    await this.store.close();
  }
}

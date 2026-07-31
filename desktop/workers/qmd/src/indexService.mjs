import { lstat, mkdir, readFile, realpath, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import {
  ContractError,
  hasExactKeys,
  parseReconcileBody,
  parseSearchBody,
  validateRelativeWikiRoot,
  validateResultPath,
  validateRevision
} from "./contract.mjs";

const STATE_SCHEMA_VERSION = 1;
const MARKDOWN_PATTERN = "**/*.md";

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

function validateStoredState(value) {
  if (
    !hasExactKeys(value, ["schema_version", "revision", "collections"]) ||
    value.schema_version !== STATE_SCHEMA_VERSION ||
    !Array.isArray(value.collections)
  ) {
    throw new ContractError(500, "invalid_state");
  }
  return parseReconcileBody({
    revision: validateRevision(value.revision),
    collections: value.collections
  });
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
      collections: state.collections
    })}\n`;
    const temporary = `${this.statePath}.tmp`;
    await mkdir(path.dirname(this.statePath), { recursive: true, mode: 0o700 });
    await writeFile(temporary, payload, { encoding: "utf8", mode: 0o600 });
    await rename(temporary, this.statePath);
  }
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
      (item.collectionName !== undefined && item.collectionName !== collection)
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

export class QmdIndexService {
  constructor({ store, wikiRoot, stateStore }) {
    this.store = store;
    this.wikiRoot = wikiRoot;
    this.stateStore = stateStore;
    this.revision = undefined;
    this.collections = new Map();
    this.operation = Promise.resolve();
  }

  async initialize() {
    const state = await this.stateStore.load().catch(() => undefined);
    if (!state) {
      return;
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
    this.collections = restored;
    this.revision = state.revision;
  }

  runExclusive(operation) {
    const result = this.operation.then(operation, operation);
    this.operation = result.catch(() => undefined);
    return result;
  }

  reconcile(input) {
    const request = parseReconcileBody(input);
    return this.runExclusive(async () => {
      const desired = [];
      for (const collection of request.collections) {
        desired.push({
          ...collection,
          absoluteRoot: await resolveCollectionRoot(
            this.wikiRoot,
            collection.wiki_root
          )
        });
      }

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

      const update =
        desired.length === 0
          ? {
              collections: 0,
              indexed: 0,
              updated: 0,
              unchanged: 0,
              removed: 0,
              needsEmbedding: 0
            }
          : await this.store.update({
              collections: desired.map((item) => item.name)
            });
      if (update === null || typeof update !== "object") {
        throw new ContractError(502, "invalid_response");
      }

      const committed = {
        revision: request.revision,
        collections: desired.map(({ name, wiki_root }) => ({
          name,
          wiki_root
        }))
      };
      await this.stateStore.save(committed);
      this.revision = committed.revision;
      this.collections = new Map(
        committed.collections.map((item) => [item.name, item.wiki_root])
      );
      return {
        indexed: true,
        revision: committed.revision,
        collections: committed.collections.length,
        update: {
          indexed: Number(update.indexed ?? 0),
          updated: Number(update.updated ?? 0),
          unchanged: Number(update.unchanged ?? 0),
          removed: Number(update.removed ?? 0)
        }
      };
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
      const raw = await this.store.searchLex(request.query, {
        collection: request.collection,
        limit: request.limit
      });
      return {
        revision: this.revision,
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
      collections: this.collections.size
    };
  }

  async close() {
    await this.operation.catch(() => undefined);
    await this.store.close();
  }
}

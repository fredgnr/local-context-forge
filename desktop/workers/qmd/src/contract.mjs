import path from "node:path";

export const QMD_WORKER_PROTOCOL_VERSION = "1.1";
export const QMD_VERSION = "2.5.3";
export const MAX_COLLECTIONS = 256;
export const MAX_REQUEST_BODY_BYTES = 256 * 1024;
export const MAX_RESPONSE_BODY_BYTES = 2 * 1024 * 1024;
export const MAX_UDS_PATH_BYTES = 100;
export const MAX_QUERY_BYTES = 8 * 1024;
export const MAX_RESULTS = 100;

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const COLLECTION_PATTERN = /^[a-z0-9][a-z0-9._-]{0,118}$/;
const CUSTOM_EMBEDDING_MODEL_PATTERN =
  /^hf:[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+\/[A-Za-z0-9._+/-]+\.gguf$/;
const CURATED_EMBEDDING_MODELS = new Set([
  "hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf",
  "hf:Qwen/Qwen3-Embedding-0.6B-GGUF/Qwen3-Embedding-0.6B-Q8_0.gguf"
]);

export class ContractError extends Error {
  constructor(status, code) {
    super(`QMD worker request rejected (${code})`);
    this.name = "ContractError";
    this.status = status;
    this.code = code;
  }
}

export function isPlainObject(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

export function hasExactKeys(value, required, optional = []) {
  if (!isPlainObject(value)) {
    return false;
  }
  const allowed = new Set([...required, ...optional]);
  const keys = Object.keys(value);
  return (
    required.every((key) => Object.hasOwn(value, key)) &&
    keys.every((key) => allowed.has(key))
  );
}

export function validateUuid(value) {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    throw new ContractError(400, "invalid_request");
  }
  return value;
}

export function validateToken(value) {
  if (typeof value !== "string" || !TOKEN_PATTERN.test(value)) {
    throw new ContractError(400, "invalid_request");
  }
  return value;
}

export function validateSha256(value) {
  if (typeof value !== "string" || !SHA256_PATTERN.test(value)) {
    throw new ContractError(400, "invalid_request");
  }
  return value;
}

export function validateRevision(value) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new ContractError(422, "invalid_request");
  }
  return value;
}

export function validateCollectionName(value) {
  if (
    typeof value !== "string" ||
    !COLLECTION_PATTERN.test(value) ||
    value.includes("..")
  ) {
    throw new ContractError(422, "invalid_request");
  }
  return value;
}

export function validateModelProfile(value) {
  if (!hasExactKeys(value, ["kind", "model"])) {
    throw new ContractError(422, "invalid_model_profile");
  }
  const model = value.model;
  if (
    typeof model !== "string" ||
    model.length === 0 ||
    model.length > 500 ||
    model !== model.trim() ||
    /[\s\0\r\n]/u.test(model) ||
    !CUSTOM_EMBEDDING_MODEL_PATTERN.test(model) ||
    model.includes("//") ||
    model
      .slice("hf:".length)
      .split("/")
      .some((segment) => segment === "" || segment === "." || segment === "..")
  ) {
    throw new ContractError(422, "invalid_model_profile");
  }
  const curated = CURATED_EMBEDDING_MODELS.has(model);
  const lowered = model.toLowerCase();
  if (
    value.kind !== (curated ? "curated" : "custom") ||
    (!lowered.includes("embeddinggemma") &&
      !lowered.includes("qwen3-embedding"))
  ) {
    throw new ContractError(422, "invalid_model_profile");
  }
  return { kind: value.kind, model };
}

export function sameModelProfile(left, right) {
  return (
    left !== null &&
    right !== null &&
    left !== undefined &&
    right !== undefined &&
    left.kind === right.kind &&
    left.model === right.model
  );
}

function parseEmbeddingDirective(value) {
  if (!hasExactKeys(value, ["mode", "profile"])) {
    throw new ContractError(422, "invalid_request");
  }
  if (value.mode === "lexical" && value.profile === null) {
    return { mode: "lexical", profile: null };
  }
  if (value.mode === "rebuild") {
    return {
      mode: "rebuild",
      profile: validateModelProfile(value.profile)
    };
  }
  throw new ContractError(422, "invalid_request");
}

export function validateRelativeWikiRoot(value) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value !== value.normalize("NFC") ||
    value.startsWith("/") ||
    value.startsWith("\\") ||
    value.includes("\\") ||
    value.includes("\0") ||
    Buffer.byteLength(value, "utf8") > 800
  ) {
    throw new ContractError(422, "invalid_request");
  }
  const parts = value.split("/");
  if (
    parts.some(
      (part) =>
        part.length === 0 ||
        part === "." ||
        part === ".." ||
        Buffer.byteLength(part, "utf8") > 240
    )
  ) {
    throw new ContractError(422, "invalid_request");
  }
  const normalized = path.posix.normalize(value);
  if (normalized !== value || normalized.startsWith("../")) {
    throw new ContractError(422, "invalid_request");
  }
  return value;
}

export function validateResultPath(value) {
  if (typeof value !== "string") {
    throw new ContractError(502, "invalid_response");
  }
  let candidate = value.replaceAll("\\", "/");
  if (candidate.startsWith("qmd://")) {
    const withoutScheme = candidate.slice("qmd://".length);
    const slash = withoutScheme.indexOf("/");
    candidate = slash >= 0 ? withoutScheme.slice(slash + 1) : "";
  }
  candidate = candidate.replace(/^\.\/+/, "");
  return validateRelativeWikiRoot(candidate);
}

export function parseReconcileBody(value) {
  if (!hasExactKeys(value, ["revision", "collections", "embedding"])) {
    throw new ContractError(422, "invalid_request");
  }
  const revision = validateRevision(value.revision);
  if (!Array.isArray(value.collections)) {
    throw new ContractError(422, "invalid_request");
  }
  if (value.collections.length > MAX_COLLECTIONS) {
    throw new ContractError(422, "too_many_collections");
  }
  const seen = new Set();
  const collections = value.collections.map((item) => {
    if (!hasExactKeys(item, ["name", "wiki_root"])) {
      throw new ContractError(422, "invalid_request");
    }
    const name = validateCollectionName(item.name);
    if (seen.has(name)) {
      throw new ContractError(422, "invalid_request");
    }
    seen.add(name);
    return {
      name,
      wiki_root: validateRelativeWikiRoot(item.wiki_root)
    };
  });
  return {
    revision,
    collections,
    embedding: parseEmbeddingDirective(value.embedding)
  };
}

export function parseSearchBody(value) {
  if (
    !hasExactKeys(value, [
      "revision",
      "collection",
      "query",
      "limit",
      "mode",
      "profile"
    ])
  ) {
    throw new ContractError(422, "invalid_request");
  }
  const query = value.query;
  if (
    typeof query !== "string" ||
    query.length === 0 ||
    query !== query.trim() ||
    query.includes("\0") ||
    Buffer.byteLength(query, "utf8") > MAX_QUERY_BYTES
  ) {
    throw new ContractError(422, "invalid_request");
  }
  if (
    !Number.isSafeInteger(value.limit) ||
    value.limit < 1 ||
    value.limit > MAX_RESULTS
  ) {
    throw new ContractError(422, "invalid_request");
  }
  let profile = null;
  if (value.mode === "hybrid") {
    profile = validateModelProfile(value.profile);
  } else if (value.mode !== "lexical" || value.profile !== null) {
    throw new ContractError(422, "invalid_request");
  }
  return {
    revision: validateRevision(value.revision),
    collection: validateCollectionName(value.collection),
    query,
    limit: value.limit,
    mode: value.mode,
    profile
  };
}

export function validateAbsolutePath(value) {
  if (
    typeof value !== "string" ||
    !path.isAbsolute(value) ||
    value.includes("\0") ||
    path.normalize(value) !== value
  ) {
    throw new ContractError(400, "invalid_request");
  }
  return value;
}

export function validateSocketPath(value) {
  validateAbsolutePath(value);
  if (Buffer.byteLength(value, "utf8") > MAX_UDS_PATH_BYTES) {
    throw new ContractError(400, "invalid_request");
  }
  return value;
}

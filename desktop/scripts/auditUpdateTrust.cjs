"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const LOCK_RELATIVE = "runtime/update-metadata-key.lock.json";
const PUBLIC_KEY_RELATIVE =
  "desktop/resources/update/update-metadata-ed25519-public.pem";
const SHA256_PATTERN = /^[0-9a-f]{64}$/;

class UpdateTrustAuditError extends Error {
  constructor(message) {
    super(message);
    this.name = "UpdateTrustAuditError";
  }
}

function fail(message) {
  throw new UpdateTrustAuditError(message);
}

function exactObject(value, keys) {
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Object.prototype
  ) {
    return false;
  }
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return (
    actual.length === expected.length &&
    actual.every((key, index) => key === expected[index])
  );
}

function boundedRegularFile(filePath, label, maximumBytes) {
  let info;
  try {
    info = fs.lstatSync(filePath);
  } catch {
    fail(`${label} is missing`);
  }
  if (
    !info.isFile() ||
    info.isSymbolicLink() ||
    info.nlink !== 1 ||
    info.size <= 0 ||
    info.size > maximumBytes
  ) {
    fail(`${label} must be a bounded, unlinked regular file`);
  }
  return fs.readFileSync(filePath);
}

function auditUpdateTrustAnchor(options = {}) {
  const repositoryRoot =
    options.repositoryRoot || path.resolve(__dirname, "..", "..");
  const lockPath = path.join(
    repositoryRoot,
    ...LOCK_RELATIVE.split("/")
  );
  const publicKeyPath = path.join(
    repositoryRoot,
    ...PUBLIC_KEY_RELATIVE.split("/")
  );
  const lockBytes = boundedRegularFile(
    lockPath,
    "Update metadata key lock",
    16 * 1024
  );
  let lock;
  try {
    lock = JSON.parse(lockBytes.toString("utf8"));
  } catch {
    fail("Update metadata key lock is not valid JSON");
  }
  if (
    !exactObject(lock, [
      "schemaVersion",
      "algorithm",
      "credentialGenerationId",
      "publicKeyPath",
      "publicKeySha256",
      "status"
    ]) ||
    lock.schemaVersion !== 1 ||
    lock.algorithm !== "Ed25519" ||
    typeof lock.credentialGenerationId !== "string" ||
    !/^[0-9a-f]{32}$/.test(lock.credentialGenerationId) ||
    lock.publicKeyPath !== PUBLIC_KEY_RELATIVE ||
    lock.status !== "provisioned" ||
    typeof lock.publicKeySha256 !== "string" ||
    !SHA256_PATTERN.test(lock.publicKeySha256)
  ) {
    fail("Update metadata trust anchor is not provisioned");
  }
  const publicKeyBytes = boundedRegularFile(
    publicKeyPath,
    "Update metadata public key",
    16 * 1024
  );
  const digest = crypto
    .createHash("sha256")
    .update(publicKeyBytes)
    .digest("hex");
  if (digest !== lock.publicKeySha256) {
    fail("Update metadata public key differs from its reviewed digest");
  }
  let publicKey;
  try {
    publicKey = crypto.createPublicKey(publicKeyBytes);
  } catch {
    fail("Update metadata public key is invalid");
  }
  if (publicKey.asymmetricKeyType !== "ed25519") {
    fail("Update metadata public key is not Ed25519");
  }
  return {
    algorithm: "Ed25519",
    publicKeySha256: digest,
    lock: LOCK_RELATIVE,
    publicKey: PUBLIC_KEY_RELATIVE
  };
}

module.exports = {
  LOCK_RELATIVE,
  PUBLIC_KEY_RELATIVE,
  UpdateTrustAuditError,
  auditUpdateTrustAnchor
};

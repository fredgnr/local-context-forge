import { createHash, generateKeyPairSync } from "node:crypto";
import {
  mkdir,
  mkdtemp,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";

const audit = require("../scripts/auditUpdateTrust.cjs") as {
  auditUpdateTrustAnchor(options: {
    repositoryRoot: string;
  }): {
    algorithm: string;
    publicKeySha256: string;
  };
};

const roots: string[] = [];

async function fixture(): Promise<{
  root: string;
  lockPath: string;
  publicKeyPath: string;
  publicKeyPem: Buffer;
}> {
  const root = await mkdtemp(path.join(os.tmpdir(), "lcf-update-trust-"));
  roots.push(root);
  const lockPath = path.join(
    root,
    "runtime",
    "update-metadata-key.lock.json"
  );
  const publicKeyPath = path.join(
    root,
    "desktop",
    "resources",
    "update",
    "update-metadata-ed25519-public.pem"
  );
  await Promise.all([
    mkdir(path.dirname(lockPath), { recursive: true }),
    mkdir(path.dirname(publicKeyPath), { recursive: true })
  ]);
  const { publicKey } = generateKeyPairSync("ed25519");
  const publicKeyPem = publicKey.export({
    format: "pem",
    type: "spki"
  }) as Buffer;
  const digest = createHash("sha256").update(publicKeyPem).digest("hex");
  await Promise.all([
    writeFile(publicKeyPath, publicKeyPem),
    writeFile(
      lockPath,
      `${JSON.stringify({
        schemaVersion: 1,
        algorithm: "Ed25519",
        credentialGenerationId: "a".repeat(32),
        publicKeyPath:
          "desktop/resources/update/update-metadata-ed25519-public.pem",
        publicKeySha256: digest,
        status: "provisioned"
      })}\n`
    )
  ]);
  return { root, lockPath, publicKeyPath, publicKeyPem };
}

afterEach(async () => {
  await Promise.all(
    roots
      .splice(0)
      .map((root) => rm(root, { recursive: true, force: true }))
  );
});

describe("packaged update trust anchor audit", () => {
  it("accepts only a provisioned Ed25519 key matching the reviewed digest", async () => {
    const value = await fixture();
    expect(
      audit.auditUpdateTrustAnchor({ repositoryRoot: value.root })
    ).toMatchObject({
      algorithm: "Ed25519",
      publicKeySha256: createHash("sha256")
        .update(value.publicKeyPem)
        .digest("hex")
    });
  });

  it("rejects unprovisioned, mismatched, extra-key, and symlink inputs", async () => {
    const unprovisioned = await fixture();
    await writeFile(
      unprovisioned.lockPath,
      `${JSON.stringify({
        schemaVersion: 1,
        algorithm: "Ed25519",
        credentialGenerationId: null,
        publicKeyPath:
          "desktop/resources/update/update-metadata-ed25519-public.pem",
        publicKeySha256: null,
        status: "unprovisioned"
      })}\n`
    );
    expect(() =>
      audit.auditUpdateTrustAnchor({ repositoryRoot: unprovisioned.root })
    ).toThrow(/not provisioned/);

    const mismatched = await fixture();
    await writeFile(mismatched.publicKeyPath, "not the reviewed key\n");
    expect(() =>
      audit.auditUpdateTrustAnchor({ repositoryRoot: mismatched.root })
    ).toThrow(/differs from its reviewed digest/);

    const extra = await fixture();
    const lock = JSON.parse(
      await import("node:fs/promises").then(({ readFile }) =>
        readFile(extra.lockPath, "utf8")
      )
    ) as Record<string, unknown>;
    lock.privateKey = "forbidden";
    await writeFile(extra.lockPath, `${JSON.stringify(lock)}\n`);
    expect(() =>
      audit.auditUpdateTrustAnchor({ repositoryRoot: extra.root })
    ).toThrow(/not provisioned/);

    const linked = await fixture();
    const realKey = `${linked.publicKeyPath}.real`;
    await writeFile(realKey, linked.publicKeyPem);
    await rm(linked.publicKeyPath);
    await symlink(realKey, linked.publicKeyPath);
    expect(() =>
      audit.auditUpdateTrustAnchor({ repositoryRoot: linked.root })
    ).toThrow(/regular file/);
  });
});

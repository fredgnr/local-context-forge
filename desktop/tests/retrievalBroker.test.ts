import {
  mkdir,
  mkdtemp,
  realpath,
  rm,
  symlink
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";
import {
  QmdClientError,
  type QmdClient,
  type QmdReconcileResponse,
  type QmdSearchResponse
} from "../src/main/qmdClient";
import {
  RetrievalBroker,
  resolveBrokerWikiRoot
} from "../src/main/retrievalBroker";

interface BrokerInternals {
  reconcile(input: {
    revision: number;
    collections: Array<{ name: string; wiki_root: string }>;
    embedding:
      | { mode: "lexical"; profile: null }
      | {
          mode: "rebuild";
          profile: typeof profile;
        };
  }): Promise<Record<string, unknown>>;
  search(input: {
    revision: number;
    collection: string;
    query: string;
    limit: number;
    mode: "lexical" | "hybrid";
    profile: typeof profile | null;
  }): Promise<Record<string, unknown>>;
}

const profile = {
  kind: "curated" as const,
  model:
    "hf:ggml-org/embeddinggemma-300M-GGUF/" +
    "embeddinggemma-300M-Q8_0.gguf"
};

async function wikiFixture() {
  const temporaryRoot = await mkdtemp(
    path.join(os.tmpdir(), "lcf-broker-")
  );
  const root = await realpath(temporaryRoot);
  const wiki = path.join(root, "wiki");
  await mkdir(path.join(wiki, "widgets", "versions", "v1"), {
    recursive: true
  });
  return { root, temporaryRoot, wiki };
}

function reconcileResponse(
  revision: number,
  ready = false
): QmdReconcileResponse {
  return {
    indexed: true,
    revision,
    collections: 1,
    update: { indexed: 1, updated: 0, unchanged: 0, removed: 0 },
    embedding: ready
      ? {
          status: "ready",
          profile,
          revision,
          model_status: "ready",
          error: null
        }
      : {
          status: "stale",
          profile: null,
          revision: null,
          model_status: "not_requested",
          error: null
        }
  };
}

describe("RetrievalBroker", () => {
  it("restarts and retries exactly once only after search transport failure", async () => {
    const fixture = await wikiFixture();
    try {
      const first = {
        reconcile: vi.fn(async () => reconcileResponse(7)),
        search: vi.fn(async () => {
          throw new QmdClientError("transport", "transport");
        })
      };
      const secondResponse: QmdSearchResponse = {
        revision: 7,
        mode: "lexical",
        results: []
      };
      const second = {
        search: vi.fn(async () => secondResponse)
      };
      let client: unknown = first;
      const supervisor = {
        getClient: vi.fn(() => client as QmdClient),
        start: vi.fn(async () => ({ state: "ready" })),
        restart: vi.fn(async () => {
          client = second;
          return { state: "ready" };
        })
      };
      const broker = new RetrievalBroker(
        supervisor as never,
        fixture.wiki
      ) as unknown as BrokerInternals;
      await broker.reconcile({
        revision: 7,
        collections: [
          {
            name: "lcf-widgets-v1-0123456789ab",
            wiki_root: "widgets/versions/v1"
          }
        ],
        embedding: { mode: "lexical", profile: null }
      });

      await expect(
        broker.search({
          revision: 7,
          collection: "lcf-widgets-v1-0123456789ab",
          query: "widgets",
          limit: 5,
          mode: "lexical",
          profile: null
        })
      ).resolves.toEqual(secondResponse);
      expect(first.search).toHaveBeenCalledTimes(1);
      expect(supervisor.restart).toHaveBeenCalledTimes(1);
      expect(second.search).toHaveBeenCalledTimes(1);
    } finally {
      await rm(fixture.temporaryRoot, { recursive: true, force: true });
    }
  });

  it("replaces an unavailable worker without replaying reconcile", async () => {
    const fixture = await wikiFixture();
    try {
      const first = {
        reconcile: vi.fn(async () => {
          throw new QmdClientError("remote", "qmd_unavailable");
        })
      };
      const second = {
        reconcile: vi.fn(async () => reconcileResponse(7))
      };
      let client: unknown = first;
      const supervisor = {
        getClient: vi.fn(() => client as QmdClient),
        start: vi.fn(),
        restart: vi.fn(async () => {
          client = second;
          return { state: "ready" };
        })
      };
      const broker = new RetrievalBroker(
        supervisor as never,
        fixture.wiki
      ) as unknown as BrokerInternals;

      await expect(
        broker.reconcile({
          revision: 7,
          collections: [
            {
              name: "lcf-widgets-v1-0123456789ab",
              wiki_root: "widgets/versions/v1"
            }
          ],
          embedding: { mode: "lexical", profile: null }
        })
      ).rejects.toThrow(/qmd_unavailable/);
      expect(first.reconcile).toHaveBeenCalledTimes(1);
      expect(second.reconcile).not.toHaveBeenCalled();
      expect(supervisor.restart).toHaveBeenCalledTimes(1);

      await expect(
        broker.reconcile({
          revision: 7,
          collections: [
            {
              name: "lcf-widgets-v1-0123456789ab",
              wiki_root: "widgets/versions/v1"
            }
          ],
          embedding: { mode: "lexical", profile: null }
        })
      ).resolves.toMatchObject({ indexed: true, revision: 7 });
      expect(first.reconcile).toHaveBeenCalledTimes(1);
      expect(second.reconcile).toHaveBeenCalledTimes(1);
    } finally {
      await rm(fixture.temporaryRoot, { recursive: true, force: true });
    }
  });

  it("allows hybrid search only for the atomically committed profile and revision", async () => {
    const fixture = await wikiFixture();
    try {
      const response: QmdSearchResponse = {
        revision: 13,
        mode: "hybrid",
        results: []
      };
      const client = {
        reconcile: vi.fn(async () => reconcileResponse(13, true)),
        search: vi.fn(async () => response)
      };
      const supervisor = {
        getClient: vi.fn(() => client as unknown as QmdClient),
        start: vi.fn(),
        restart: vi.fn()
      };
      const broker = new RetrievalBroker(
        supervisor as never,
        fixture.wiki
      ) as unknown as BrokerInternals;
      await broker.reconcile({
        revision: 13,
        collections: [
          {
            name: "lcf-widgets-v1-0123456789ab",
            wiki_root: "widgets/versions/v1"
          }
        ],
        embedding: { mode: "rebuild", profile }
      });

      await expect(
        broker.search({
          revision: 13,
          collection: "lcf-widgets-v1-0123456789ab",
          query: "meaning",
          limit: 5,
          mode: "hybrid",
          profile
        })
      ).resolves.toEqual(response);
      await expect(
        broker.search({
          revision: 13,
          collection: "lcf-widgets-v1-0123456789ab",
          query: "meaning",
          limit: 5,
          mode: "hybrid",
          profile: {
            kind: "curated",
            model:
              "hf:Qwen/Qwen3-Embedding-0.6B-GGUF/" +
              "Qwen3-Embedding-0.6B-Q8_0.gguf"
          }
        })
      ).rejects.toThrow(/stale_index/);
      expect(client.search).toHaveBeenCalledTimes(1);
    } finally {
      await rm(fixture.temporaryRoot, { recursive: true, force: true });
    }
  });

  it("rejects symlinked or escaping Wiki roots in Main", async () => {
    const fixture = await wikiFixture();
    const linked = path.join(fixture.wiki, "linked");
    await symlink(
      path.join(fixture.wiki, "widgets"),
      linked,
      "dir"
    );
    try {
      await expect(
        resolveBrokerWikiRoot(fixture.wiki, "../outside")
      ).rejects.toThrow(/invalid_request/);
      await expect(
        resolveBrokerWikiRoot(fixture.wiki, "linked/versions/v1")
      ).rejects.toThrow(/invalid_request/);
    } finally {
      await rm(fixture.temporaryRoot, { recursive: true, force: true });
    }
  });
});

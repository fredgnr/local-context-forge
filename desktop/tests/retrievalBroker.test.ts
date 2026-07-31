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
  }): Promise<Record<string, unknown>>;
  search(input: {
    revision: number;
    collection: string;
    query: string;
    limit: number;
  }): Promise<Record<string, unknown>>;
}

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

function reconcileResponse(revision: number): QmdReconcileResponse {
  return {
    indexed: true,
    revision,
    collections: 1,
    update: { indexed: 1, updated: 0, unchanged: 0, removed: 0 }
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
        ]
      });

      await expect(
        broker.search({
          revision: 7,
          collection: "lcf-widgets-v1-0123456789ab",
          query: "widgets",
          limit: 5
        })
      ).resolves.toEqual(secondResponse);
      expect(first.search).toHaveBeenCalledTimes(1);
      expect(supervisor.restart).toHaveBeenCalledTimes(1);
      expect(second.search).toHaveBeenCalledTimes(1);
    } finally {
      await rm(fixture.temporaryRoot, { recursive: true, force: true });
    }
  });

  it("never restarts or replays reconcile after a transport failure", async () => {
    const fixture = await wikiFixture();
    try {
      const client = {
        reconcile: vi.fn(async () => {
          throw new QmdClientError("transport", "transport");
        })
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

      await expect(
        broker.reconcile({
          revision: 7,
          collections: [
            {
              name: "lcf-widgets-v1-0123456789ab",
              wiki_root: "widgets/versions/v1"
            }
          ]
        })
      ).rejects.toThrow(/qmd_unavailable/);
      expect(client.reconcile).toHaveBeenCalledTimes(1);
      expect(supervisor.restart).not.toHaveBeenCalled();
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

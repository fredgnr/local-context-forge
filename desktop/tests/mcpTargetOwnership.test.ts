import {
  chmod,
  link,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  FileMcpTargetOwnershipStore,
  MCP_TARGET_OWNERSHIP_FILE_NAME,
  sameMcpTargetOwnership,
  type McpOwnedTarget
} from "../src/main/mcpTargetOwnership";

const currentTarget: McpOwnedTarget = {
  command:
    "/Applications/Local Context Forge.app/Contents/Resources/qmd/node/bin/node",
  arguments_: [
    "/Applications/Local Context Forge.app/Contents/Resources/companion/index.mjs"
  ]
};
const previousTarget: McpOwnedTarget = {
  command:
    "/Users/example/Applications/Local Context Forge.app/Contents/Resources/qmd/node/bin/node",
  arguments_: [
    "/Users/example/Applications/Local Context Forge.app/Contents/Resources/companion/index.mjs"
  ]
};

const temporaryRoots: string[] = [];

async function privateDataDirectory(): Promise<string> {
  const lexicalRoot = await mkdtemp(
    path.join(os.tmpdir(), "lcf-mcp-owner-")
  );
  const root = await realpath(lexicalRoot);
  temporaryRoots.push(root);
  const dataDirectory = path.join(root, "Application Support");
  await mkdir(dataDirectory, { mode: 0o700 });
  await chmod(dataDirectory, 0o700);
  return dataDirectory;
}

function store(
  dataDirectory: string,
  scopeId?: string
): FileMcpTargetOwnershipStore {
  return new FileMcpTargetOwnershipStore(dataDirectory, {
    randomBytes: (size) => Buffer.alloc(size, 0x5a),
    ...(scopeId === undefined ? {} : { scopeId })
  });
}

afterEach(async () => {
  await Promise.all(
    temporaryRoots.splice(0).map((root) =>
      rm(root, { force: true, recursive: true })
    )
  );
});

describe("MCP target ownership persistence", () => {
  it("rejects a non-digest scope identifier", async () => {
    const dataDirectory = await privateDataDirectory();
    expect(
      () =>
        new FileMcpTargetOwnershipStore(dataDirectory, {
          scopeId: "/Users/test/.codex"
        })
    ).toThrow(/scope/);
  });

  it("creates a private marker, persists exact move targets, and survives restart", async () => {
    const dataDirectory = await privateDataDirectory();
    const firstStore = store(dataDirectory);
    await expect(firstStore.read()).resolves.toBeUndefined();

    const initial = await firstStore.stage(undefined, [previousTarget]);
    expect(initial.marker).toBe(`lcf-mcp-v1-${"5a".repeat(32)}`);
    const statePath = path.join(
      dataDirectory,
      MCP_TARGET_OWNERSHIP_FILE_NAME
    );
    const info = await lstat(statePath);
    expect(info.isFile()).toBe(true);
    expect(info.nlink).toBe(1);
    expect(info.mode & 0o777).toBe(0o600);

    const staged = await firstStore.stage(initial, [
      previousTarget,
      currentTarget
    ]);
    expect(staged.marker).toBe(initial.marker);
    expect(staged.targets).toEqual([previousTarget, currentTarget]);

    const restarted = store(dataDirectory);
    await expect(restarted.read()).resolves.toEqual(staged);
    const finalized = await restarted.stage(staged, [currentTarget]);
    expect(finalized).toEqual({
      marker: initial.marker,
      targets: [currentTarget]
    });
    expect(
      JSON.parse(await readFile(statePath, "utf8"))
    ).toMatchObject({
      schemaVersion: 1,
      marker: initial.marker,
      targets: [
        {
          command: currentTarget.command,
          arguments: [...currentTarget.arguments_]
        }
      ]
    });
  });

  it("removes only the exact expected private state", async () => {
    const dataDirectory = await privateDataDirectory();
    const ownershipStore = store(dataDirectory);
    const state = await ownershipStore.stage(undefined, [currentTarget]);
    await expect(
      ownershipStore.remove({
        marker: `lcf-mcp-v1-${"b".repeat(64)}`,
        targets: [currentTarget]
      })
    ).rejects.toThrow(/changed/);
    await expect(ownershipStore.read()).resolves.toEqual(state);
    await expect(
      ownershipStore.stage(
        {
          marker: `lcf-mcp-v1-${"b".repeat(64)}`,
          targets: [currentTarget]
        },
        [previousTarget]
      )
    ).rejects.toThrow(/changed/);
    await expect(ownershipStore.read()).resolves.toEqual(state);

    await ownershipStore.remove(state);
    await expect(ownershipStore.read()).resolves.toBeUndefined();
  });

  it("keeps independent Codex configuration scopes isolated", async () => {
    const dataDirectory = await privateDataDirectory();
    const scopeA = "a".repeat(64);
    const scopeB = "b".repeat(64);
    const legacyStore = store(dataDirectory);
    const legacyState = await legacyStore.stage(undefined, [
      previousTarget
    ]);
    const storeA = store(dataDirectory, scopeA);
    await expect(storeA.read()).resolves.toBeUndefined();
    const stateA = await storeA.stage(undefined, [previousTarget]);
    const storeB = store(dataDirectory, scopeB);
    await expect(storeB.read()).resolves.toBeUndefined();
    const stateB = await storeB.stage(undefined, [currentTarget]);
    await storeB.remove(stateB);

    await expect(storeA.read()).resolves.toEqual(stateA);
    await expect(storeB.read()).resolves.toBeUndefined();
    await expect(legacyStore.read()).resolves.toEqual(legacyState);
  });

  it("rejects malformed, writable, or symlinked ownership files", async () => {
    for (const mutation of [
      "hardlink",
      "invalid-utf8",
      "malformed",
      "oversize",
      "writable",
      "symlink"
    ] as const) {
      const dataDirectory = await privateDataDirectory();
      const statePath = path.join(
        dataDirectory,
        MCP_TARGET_OWNERSHIP_FILE_NAME
      );
      if (mutation === "symlink") {
        const outside = path.join(path.dirname(dataDirectory), "outside");
        await writeFile(outside, "{}\n", { mode: 0o600 });
        await symlink(outside, statePath);
      } else {
        const payload =
          mutation === "invalid-utf8"
            ? Buffer.from([0xff])
            : mutation === "oversize"
              ? Buffer.alloc(32 * 1024 + 1, 0x61)
              : "{}\n";
        await writeFile(statePath, payload, {
          mode: mutation === "writable" ? 0o666 : 0o600
        });
        if (mutation === "writable") {
          await chmod(statePath, 0o666);
        } else if (mutation === "hardlink") {
          await link(
            statePath,
            path.join(dataDirectory, "ownership-hardlink")
          );
        }
      }
      await expect(store(dataDirectory).read()).rejects.toThrow();
    }
  });

  it("rejects privilege bits on ownership state and its private directory", async () => {
    const fileDirectory = await privateDataDirectory();
    const fileStore = store(fileDirectory);
    await fileStore.stage(undefined, [currentTarget]);
    await chmod(
      path.join(fileDirectory, MCP_TARGET_OWNERSHIP_FILE_NAME),
      0o4600
    );
    await expect(fileStore.read()).rejects.toThrow(/file/);

    const stickyDirectory = await privateDataDirectory();
    await chmod(stickyDirectory, 0o1700);
    await expect(store(stickyDirectory).read()).rejects.toThrow(
      /directory/
    );
  });

  it("rejects an insecure or wrong-owner Application Support directory", async () => {
    const writableDirectory = await privateDataDirectory();
    await chmod(writableDirectory, 0o755);
    await expect(store(writableDirectory).read()).rejects.toThrow(
      /directory/
    );

    const wrongOwnerDirectory = await privateDataDirectory();
    const currentUid =
      process.geteuid?.() ?? process.getuid?.() ?? 0;
    const wrongEffectiveUid = currentUid === 99_999 ? 99_998 : 99_999;
    const wrongOwnerStore = new FileMcpTargetOwnershipStore(
      wrongOwnerDirectory,
      {
        effectiveUid: () => wrongEffectiveUid
      }
    );
    await expect(wrongOwnerStore.read()).rejects.toThrow(/directory/);
  });

  it("compares the marker, target order, command, and companion exactly", () => {
    const state = {
      marker: `lcf-mcp-v1-${"c".repeat(64)}`,
      targets: [previousTarget, currentTarget]
    };
    expect(sameMcpTargetOwnership(state, { ...state })).toBe(true);
    expect(
      sameMcpTargetOwnership(state, {
        ...state,
        targets: [currentTarget, previousTarget]
      })
    ).toBe(false);
    expect(
      sameMcpTargetOwnership(state, {
        ...state,
        marker: `lcf-mcp-v1-${"d".repeat(64)}`
      })
    ).toBe(false);
  });
});

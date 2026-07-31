import { describe, expect, it } from "vitest";
import {
  LOCAL_SOURCE_GRANT_PATTERN,
  LocalSourceGrantManager
} from "../src/main/localSourceGrants";

function fileInfo(
  overrides: Partial<{
    dev: number;
    ino: number;
    uid: number;
    directory: boolean;
    symlink: boolean;
  }> = {}
) {
  return {
    dev: overrides.dev ?? 10,
    ino: overrides.ino ?? 20,
    uid: overrides.uid ?? 501,
    isDirectory: () => overrides.directory ?? true,
    isSymbolicLink: () => overrides.symlink ?? false
  };
}

function manager(
  options: {
    now?: () => number;
    realpath?: (candidate: string) => Promise<string>;
    lstat?: (candidate: string) => Promise<ReturnType<typeof fileInfo>>;
    excludedDirectories?: readonly string[];
  } = {}
) {
  return new LocalSourceGrantManager(
    {
      dataDirectory:
        "/Users/test/Library/Application Support/Local Context Forge",
      homeDirectory: "/Users/test",
      volumesDirectory: "/Volumes",
      ...(options.excludedDirectories
        ? { excludedDirectories: options.excludedDirectories }
        : {}),
      ttlMs: 1_000
    },
    {
      effectiveUserId: () => 501,
      randomBytes: () => Buffer.alloc(32, 0x4a),
      realpath: options.realpath ?? (async (candidate) => candidate),
      lstat: options.lstat ?? (async () => fileInfo()),
      now: options.now ?? (() => 1_000)
    }
  );
}

describe("local source grants", () => {
  it("returns an opaque label-only selection and consumes it once", async () => {
    const grants = manager();
    const selection = await grants.issue("/Users/test/code/private-repo");

    expect(selection).toEqual({
      grantId: expect.stringMatching(LOCAL_SOURCE_GRANT_PATTERN),
      displayName: "private-repo"
    });
    expect(JSON.stringify(selection)).not.toContain("/Users/test");
    await expect(grants.consume(selection.grantId)).resolves.toBe(
      "/Users/test/code/private-repo"
    );
    await expect(grants.consume(selection.grantId)).rejects.toMatchObject({
      code: "invalid-grant"
    });
  });

  it("expires grants and clears them without exposing a path", async () => {
    let now = 5_000;
    const grants = manager({ now: () => now });
    const selection = await grants.issue("/Users/test/code/repository");
    now = 6_000;

    await expect(grants.consume(selection.grantId)).rejects.toMatchObject({
      code: "invalid-grant"
    });

    const next = await grants.issue("/Users/test/code/repository");
    grants.clear();
    await expect(grants.consume(next.grantId)).rejects.toMatchObject({
      code: "invalid-grant"
    });
  });

  it("revalidates the directory identity before consuming", async () => {
    let inode = 20;
    const grants = manager({
      lstat: async () => fileInfo({ ino: inode })
    });
    const selection = await grants.issue("/Users/test/code/repository");
    inode = 21;

    await expect(grants.consume(selection.grantId)).rejects.toMatchObject({
      code: "invalid-grant"
    });
  });

  it("allows a repository below a mounted volume but not the volume root", async () => {
    const grants = manager();
    const selection = await grants.issue("/Volumes/External/repository");
    await expect(grants.consume(selection.grantId)).resolves.toBe(
      "/Volumes/External/repository"
    );
    await expect(grants.issue("/Volumes/External")).rejects.toMatchObject({
      code: "unsafe-selection"
    });
  });

  it("rejects a nested mount root and unsafe filesystem identity numbers", async () => {
    await expect(
      manager({
        lstat: async (candidate) =>
          fileInfo({ dev: candidate.endsWith("/repository") ? 22 : 10 })
      }).issue("/Users/test/code/repository")
    ).rejects.toMatchObject({ code: "unsafe-selection" });
    await expect(
      manager({
        lstat: async () => fileInfo({ ino: Number.MAX_SAFE_INTEGER + 1 })
      }).issue("/Users/test/code/repository")
    ).rejects.toMatchObject({ code: "unsafe-selection" });
  });

  it.each([
    "/",
    "/Users/test",
    "/Users/test/Library",
    "/Users/test/Library/Application Support/Local Context Forge",
    "/tmp/repository",
    "/Volumes"
  ])("rejects an overbroad or unauthorized selection: %s", async (candidate) => {
    await expect(manager().issue(candidate)).rejects.toMatchObject({
      code: "unsafe-selection"
    });
  });

  it.each([
    "/Users/test/Library/Caches",
    "/Users/test/Library/Caches/Local Context Forge",
    "/Users/test/Library/Caches/Local Context Forge/qmd-runtime"
  ])("rejects a source that contains or enters a product cache: %s", async (candidate) => {
    await expect(
      manager({
        excludedDirectories: [
          "/Users/test/Library/Caches/Local Context Forge"
        ]
      }).issue(candidate)
    ).rejects.toMatchObject({ code: "unsafe-selection" });
  });

  it("rejects symlinks, non-directories, owner changes and non-canonical paths", async () => {
    await expect(
      manager({
        lstat: async () => fileInfo({ symlink: true })
      }).issue("/Users/test/code/link")
    ).rejects.toMatchObject({ code: "unsafe-selection" });
    await expect(
      manager({
        lstat: async () => fileInfo({ directory: false })
      }).issue("/Users/test/code/file")
    ).rejects.toMatchObject({ code: "unsafe-selection" });
    await expect(
      manager({
        lstat: async () => fileInfo({ uid: 0 })
      }).issue("/Users/test/code/root-owned")
    ).rejects.toMatchObject({ code: "unsafe-selection" });
    await expect(
      manager({
        realpath: async () => "/Users/test/code/real"
      }).issue("/Users/test/code/link-parent")
    ).rejects.toMatchObject({ code: "unsafe-selection" });
  });

  it("rejects malformed grant identifiers without touching the filesystem", async () => {
    await expect(
      manager({
        lstat: async () => {
          throw new Error("must not be called");
        }
      }).consume("lcf-local:not-random")
    ).rejects.toMatchObject({ code: "invalid-grant" });
  });
});

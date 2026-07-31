import { describe, expect, it } from "vitest";
import {
  resolveLocalSourceExcludedDirectories,
  SENSITIVE_LOCAL_SOURCE_DIRECTORY_NAMES
} from "../src/main/localSourcePolicy";

describe("local source exclusion policy", () => {
  it("excludes product, known credential and configured Codex roots", async () => {
    const exclusions = await resolveLocalSourceExcludedDirectories(
      {
        homeDirectory: "/Users/test",
        productCacheDirectory:
          "/Users/test/Library/Caches/Local Context Forge",
        environment: {
          CODEX_HOME: "/Users/test/Library/Application Support/Codex"
        }
      },
      {
        realpath: async (candidate) =>
          candidate === "/Users/test/.codex"
            ? "/Users/test/private/codex-data"
            : candidate
      }
    );

    expect(exclusions).toContain(
      "/Users/test/Library/Caches/Local Context Forge"
    );
    for (const name of SENSITIVE_LOCAL_SOURCE_DIRECTORY_NAMES) {
      expect(exclusions).toContain(`/Users/test/${name}`);
    }
    expect(exclusions).toContain("/Users/test/private/codex-data");
    expect(exclusions).toContain(
      "/Users/test/Library/Application Support/Codex"
    );
  });

  it("ignores a malformed CODEX_HOME without weakening default exclusions", async () => {
    const exclusions = await resolveLocalSourceExcludedDirectories(
      {
        homeDirectory: "/Users/test",
        productCacheDirectory:
          "/Users/test/Library/Caches/Local Context Forge",
        environment: { CODEX_HOME: "relative/codex" }
      },
      {
        realpath: async () => {
          throw new Error("not present");
        }
      }
    );

    expect(exclusions).toContain("/Users/test/.codex");
    expect(exclusions).not.toContain("relative/codex");
  });
});

import { describe, expect, it, vi } from "vitest";
import type { LocalSourceGrantManager } from "../src/main/localSourceGrants";
import {
  LocalSourcePicker,
  LocalSourcePickerError
} from "../src/main/localSourcePicker";

function grants() {
  return {
    issue: vi.fn(async () => ({
      grantId: `lcf-local:${"a".repeat(64)}`,
      displayName: "repository"
    })),
    clear: vi.fn()
  } as unknown as LocalSourceGrantManager;
}

describe("LocalSourcePicker", () => {
  it("returns an opaque grant for one selected directory", async () => {
    const grantManager = grants();
    const picker = new LocalSourcePicker({
      grants: grantManager,
      openDirectory: async () => ({
        canceled: false,
        filePaths: ["/Users/test/repository"]
      })
    });

    await expect(picker.select()).resolves.toEqual({
      grantId: `lcf-local:${"a".repeat(64)}`,
      displayName: "repository"
    });
    expect(grantManager.issue).toHaveBeenCalledWith(
      "/Users/test/repository"
    );
    expect(grantManager.clear).toHaveBeenCalledOnce();
  });

  it("maps a clean cancellation to null without issuing a grant", async () => {
    const grantManager = grants();
    const picker = new LocalSourcePicker({
      grants: grantManager,
      openDirectory: async () => ({ canceled: true, filePaths: [] })
    });

    await expect(picker.select()).resolves.toBeNull();
    expect(grantManager.issue).not.toHaveBeenCalled();
  });

  it("rejects concurrent dialogs and malformed dialog results", async () => {
    let release!: (value: {
      canceled: boolean;
      filePaths: readonly string[];
    }) => void;
    const pending = new Promise<{
      canceled: boolean;
      filePaths: readonly string[];
    }>((resolve) => {
      release = resolve;
    });
    const picker = new LocalSourcePicker({
      grants: grants(),
      openDirectory: async () => pending
    });

    const first = picker.select();
    await expect(picker.select()).rejects.toEqual(
      new LocalSourcePickerError("busy")
    );
    release({ canceled: true, filePaths: [] });
    await first;

    const malformed = new LocalSourcePicker({
      grants: grants(),
      openDirectory: async () => ({
        canceled: false,
        filePaths: []
      })
    });
    await expect(malformed.select()).rejects.toMatchObject({
      code: "unavailable"
    });
  });

  it("clears every outstanding grant on shutdown", () => {
    const grantManager = grants();
    const picker = new LocalSourcePicker({
      grants: grantManager,
      openDirectory: async () => ({ canceled: true, filePaths: [] })
    });

    picker.shutdown();
    expect(grantManager.clear).toHaveBeenCalledOnce();
  });

  it("cannot issue a grant after shutdown races a pending dialog", async () => {
    let release!: (value: {
      canceled: boolean;
      filePaths: readonly string[];
    }) => void;
    const pending = new Promise<{
      canceled: boolean;
      filePaths: readonly string[];
    }>((resolve) => {
      release = resolve;
    });
    const grantManager = grants();
    const picker = new LocalSourcePicker({
      grants: grantManager,
      openDirectory: async () => pending
    });

    const selection = picker.select();
    picker.shutdown();
    release({
      canceled: false,
      filePaths: ["/Users/test/repository"]
    });

    await expect(selection).rejects.toMatchObject({ code: "unavailable" });
    expect(grantManager.issue).not.toHaveBeenCalled();
    await expect(picker.select()).rejects.toMatchObject({
      code: "unavailable"
    });
  });
});

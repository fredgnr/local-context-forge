import type {
  IpcMain,
  IpcMainInvokeEvent
} from "electron";
import { describe, expect, it, vi } from "vitest";
import {
  IPC_CHANNELS,
  type UpdateStatus
} from "../src/contracts";
import { registerUpdateIpcHandlers } from "../src/main/updateIpc";
import { UpdateClientError } from "../src/main/updateClient";

const idle: UpdateStatus = {
  state: "idle",
  currentVersion: "1.0.0",
  channel: "latest",
  availableVersion: null,
  progress: null,
  errorCode: null,
  unavailableReason: null,
  canCheck: true,
  canDownloadOrOpen: false,
  canOpenReleasePage: false,
  automaticApply: false,
  automaticApplyReason: "val-update-001-not-passed"
};

function setup() {
  const handlers = new Map<
    string,
    (event: IpcMainInvokeEvent, payload?: unknown) => unknown
  >();
  const ipcMain = {
    handle: vi.fn(
      (
        channel: string,
        handler: (
          event: IpcMainInvokeEvent,
          payload?: unknown
        ) => unknown
      ) => handlers.set(channel, handler)
    )
  } as unknown as IpcMain;
  const dependencies = {
    status: vi.fn(() => idle),
    check: vi.fn(async () => idle),
    downloadOrOpen: vi.fn(async () => idle),
    cancel: vi.fn(async () => idle),
    openReleasePage: vi.fn(async () => idle)
  };
  registerUpdateIpcHandlers(ipcMain, dependencies);
  const frame = { url: "lcf://app/" };
  const event = {
    senderFrame: frame,
    sender: { mainFrame: frame }
  } as unknown as IpcMainInvokeEvent;
  return { handlers, dependencies, event };
}

describe("typed update IPC", () => {
  it("exposes only fixed no-payload operations to the trusted main frame", async () => {
    const { handlers, dependencies, event } = setup();
    expect([...handlers.keys()].sort()).toEqual(
      [
        IPC_CHANNELS.updateStatus,
        IPC_CHANNELS.updateCheck,
        IPC_CHANNELS.updateDownloadOrOpen,
        IPC_CHANNELS.updateCancel,
        IPC_CHANNELS.updateOpenReleasePage
      ].sort()
    );

    await expect(
      handlers.get(IPC_CHANNELS.updateCheck)?.(event)
    ).resolves.toEqual({ ok: true, value: idle });
    expect(dependencies.check).toHaveBeenCalledTimes(1);

    expect(() =>
      handlers.get(IPC_CHANNELS.updateDownloadOrOpen)?.(event, {
        url: "https://evil.example",
        path: "/tmp/evil.dmg",
        version: "999.0.0"
      })
    ).toThrow(/invalid-payload/);
    expect(dependencies.downloadOrOpen).not.toHaveBeenCalled();

    expect(() =>
      handlers.get(IPC_CHANNELS.updateOpenReleasePage)?.(event, {
        url: "https://evil.example/releases"
      })
    ).toThrow(/invalid-payload/);
    expect(dependencies.openReleasePage).not.toHaveBeenCalled();

    await expect(
      handlers.get(IPC_CHANNELS.updateOpenReleasePage)?.(event)
    ).resolves.toEqual({ ok: true, value: idle });
    expect(dependencies.openReleasePage).toHaveBeenCalledTimes(1);

    const child = { url: "lcf://app/frame.html" };
    expect(() =>
      handlers.get(IPC_CHANNELS.updateStatus)?.(
        {
          senderFrame: child,
          sender: { mainFrame: event.sender.mainFrame }
        } as unknown as IpcMainInvokeEvent
      )
    ).toThrow(/forbidden/);
  });

  it("returns only stable error codes and never transport details", async () => {
    const { handlers, dependencies, event } = setup();
    dependencies.downloadOrOpen.mockRejectedValueOnce(
      Object.assign(new UpdateClientError("digest-mismatch"), {
        path: "/private/user/update.dmg",
        url: "https://release-assets.githubusercontent.com/secret",
        headers: { authorization: "secret" }
      })
    );

    await expect(
      handlers.get(IPC_CHANNELS.updateDownloadOrOpen)?.(event)
    ).resolves.toEqual({
      ok: false,
      error: { code: "digest-mismatch" }
    });

    dependencies.check.mockRejectedValueOnce({
      code: "ECONNRESET",
      response: "private proxy body"
    });
    await expect(
      handlers.get(IPC_CHANNELS.updateCheck)?.(event)
    ).resolves.toEqual({
      ok: false,
      error: { code: "unavailable" }
    });
  });
});

import type { IpcMain, IpcMainInvokeEvent } from "electron";
import {
  IPC_CHANNELS,
  type UpdateErrorCode,
  type UpdateIpcResult,
  type UpdateStatus
} from "../contracts";
import {
  IpcValidationError,
  isTrustedIpcSender
} from "./ipc";
import { UpdateClientError } from "./updateClient";

export interface UpdateIpcDependencies {
  status(): UpdateStatus;
  check(): Promise<UpdateStatus>;
  downloadOrOpen(): Promise<UpdateStatus>;
  cancel(): Promise<UpdateStatus>;
  openReleasePage(): Promise<UpdateStatus>;
}

function assertTrustedNoPayload(
  event: IpcMainInvokeEvent,
  payloads: readonly unknown[]
): void {
  if (!isTrustedIpcSender(event)) {
    throw new IpcValidationError("forbidden");
  }
  if (payloads.length !== 0) {
    throw new IpcValidationError("invalid-payload");
  }
}

function stableError(error: unknown): UpdateErrorCode {
  return error instanceof UpdateClientError
    ? error.code
    : "unavailable";
}

async function actionResult(
  action: () => Promise<UpdateStatus>
): Promise<UpdateIpcResult> {
  try {
    return { ok: true, value: await action() };
  } catch (error) {
    return {
      ok: false,
      error: { code: stableError(error) }
    };
  }
}

export function registerUpdateIpcHandlers(
  ipcMain: IpcMain,
  dependencies: UpdateIpcDependencies
): void {
  ipcMain.handle(IPC_CHANNELS.updateStatus, (event, ...payloads: unknown[]) => {
    assertTrustedNoPayload(event, payloads);
    return {
      ok: true,
      value: dependencies.status()
    } satisfies UpdateIpcResult;
  });
  ipcMain.handle(IPC_CHANNELS.updateCheck, (event, ...payloads: unknown[]) => {
    assertTrustedNoPayload(event, payloads);
    return actionResult(() => dependencies.check());
  });
  ipcMain.handle(
    IPC_CHANNELS.updateDownloadOrOpen,
    (event, ...payloads: unknown[]) => {
      assertTrustedNoPayload(event, payloads);
      return actionResult(() => dependencies.downloadOrOpen());
    }
  );
  ipcMain.handle(IPC_CHANNELS.updateCancel, (event, ...payloads: unknown[]) => {
    assertTrustedNoPayload(event, payloads);
    return actionResult(() => dependencies.cancel());
  });
  ipcMain.handle(
    IPC_CHANNELS.updateOpenReleasePage,
    (event, ...payloads: unknown[]) => {
      assertTrustedNoPayload(event, payloads);
      return actionResult(() => dependencies.openReleasePage());
    }
  );
}

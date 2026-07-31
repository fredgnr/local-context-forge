import type { LocalSourceSelection } from "../contracts";
import { LocalSourceGrantManager } from "./localSourceGrants";

export interface LocalSourceDialogResult {
  readonly canceled: boolean;
  readonly filePaths: readonly string[];
}

export interface LocalSourcePickerOptions {
  readonly grants: LocalSourceGrantManager;
  readonly openDirectory: () => Promise<LocalSourceDialogResult>;
}

export class LocalSourcePickerError extends Error {
  constructor(readonly code: "busy" | "unavailable") {
    super(`Local source picker failed (${code})`);
    this.name = "LocalSourcePickerError";
  }
}

export class LocalSourcePicker {
  private selecting = false;
  private closed = false;

  constructor(private readonly options: LocalSourcePickerOptions) {}

  async select(): Promise<LocalSourceSelection | null> {
    if (this.closed) {
      throw new LocalSourcePickerError("unavailable");
    }
    if (this.selecting) {
      throw new LocalSourcePickerError("busy");
    }
    this.selecting = true;
    try {
      let result: LocalSourceDialogResult;
      try {
        result = await this.options.openDirectory();
      } catch {
        throw new LocalSourcePickerError("unavailable");
      }
      if (
        typeof result.canceled !== "boolean" ||
        !Array.isArray(result.filePaths) ||
        !result.filePaths.every((item) => typeof item === "string")
      ) {
        throw new LocalSourcePickerError("unavailable");
      }
      if (result.canceled) {
        if (result.filePaths.length !== 0) {
          throw new LocalSourcePickerError("unavailable");
        }
        return null;
      }
      if (result.filePaths.length !== 1) {
        throw new LocalSourcePickerError("unavailable");
      }
      if (this.closed) {
        throw new LocalSourcePickerError("unavailable");
      }
      this.options.grants.clear();
      const selection = await this.options.grants.issue(
        result.filePaths[0] as string
      );
      if (this.closed) {
        this.options.grants.clear();
        throw new LocalSourcePickerError("unavailable");
      }
      return selection;
    } finally {
      this.selecting = false;
    }
  }

  shutdown(): void {
    this.closed = true;
    this.options.grants.clear();
  }
}

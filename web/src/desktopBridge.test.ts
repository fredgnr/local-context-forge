import { afterEach, expect, it, vi } from "vitest";
import { desktopApiBridge, isDesktopRuntime } from "./desktopBridge";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("fails closed on the desktop scheme when preload did not expose a bridge", () => {
  vi.stubGlobal("window", {
    location: { protocol: "lcf:" }
  });

  expect(isDesktopRuntime()).toBe(true);
  expect(() => desktopApiBridge()).toThrow("桌面 API bridge 不可用");
});

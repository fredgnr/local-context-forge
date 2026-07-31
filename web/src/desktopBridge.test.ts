import { afterEach, expect, it, vi } from "vitest";
import {
  desktopApiBridge,
  desktopMcpBridge,
  desktopSourcesBridge,
  isDesktopRuntime
} from "./desktopBridge";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("fails closed on the desktop scheme when preload did not expose a bridge", () => {
  vi.stubGlobal("window", {
    location: { protocol: "lcf:" }
  });

  expect(isDesktopRuntime()).toBe(true);
  expect(() => desktopApiBridge()).toThrow("桌面 API bridge 不可用");
  expect(() => desktopMcpBridge()).toThrow("桌面 MCP bridge 不可用");
  expect(() => desktopSourcesBridge()).toThrow("桌面本地仓库 bridge 不可用");
});

it("accepts only the fixed MCP facade methods", () => {
  const mcp = {
    status: vi.fn(),
    configure: vi.fn(),
    clear: vi.fn()
  };
  vi.stubGlobal("window", {
    location: { protocol: "lcf:" },
    localContextForge: {
      version: "1.0",
      api: { request: vi.fn() },
      mcp
    }
  });

  expect(desktopMcpBridge()).toBe(mcp);
  delete (mcp as { clear?: unknown }).clear;
  expect(() => desktopMcpBridge()).toThrow("桌面 MCP bridge 不可用");
});

it("accepts only the fixed local repository selection facade", () => {
  const sources = {
    selectRepository: vi.fn()
  };
  vi.stubGlobal("window", {
    location: { protocol: "lcf:" },
    localContextForge: {
      version: "1.0",
      api: { request: vi.fn() },
      sources
    }
  });

  expect(desktopSourcesBridge()).toBe(sources);
  delete (sources as { selectRepository?: unknown }).selectRepository;
  expect(() => desktopSourcesBridge()).toThrow(
    "桌面本地仓库 bridge 不可用"
  );
});

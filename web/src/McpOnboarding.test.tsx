import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  type DesktopMcpSetupStatus,
  type LocalContextForgeBridge
} from "./desktopBridge";
import { McpOnboarding } from "./McpOnboarding";

const baseStatus: DesktopMcpSetupStatus = {
  provider: "codex_cli",
  codexState: "ready",
  configurationState: "not-configured",
  installState: "ready",
  canConfigure: true,
  canClear: false,
  restartRequired: false
};

function exposeBridge(input: {
  status?: DesktopMcpSetupStatus;
  configure?: DesktopMcpSetupStatus;
  clear?: DesktopMcpSetupStatus;
}) {
  const status = vi.fn(async () => input.status ?? baseStatus);
  const configure = vi.fn(async () => ({
    ...baseStatus,
    configurationState: "configured" as const,
    canConfigure: false,
    canClear: true,
    restartRequired: true,
    ...input.configure
  }));
  const clear = vi.fn(async () => ({
    ...baseStatus,
    restartRequired: true,
    ...input.clear
  }));
  const bridge: LocalContextForgeBridge = {
    version: "1.0",
    api: { request: vi.fn() },
    mcp: { status, configure, clear }
  };
  Object.defineProperty(window, "localContextForge", {
    configurable: true,
    value: bridge
  });
  return { status, configure, clear };
}

afterEach(() => {
  cleanup();
  delete window.localContextForge;
  vi.restoreAllMocks();
});

describe("desktop MCP onboarding", () => {
  it("connects with one explicit action and tells the user to restart Codex", async () => {
    const calls = exposeBridge({});
    render(<McpOnboarding />);

    const connect = await screen.findByRole("button", {
      name: "连接 Codex"
    });
    fireEvent.click(connect);

    await screen.findByText("已连接 Codex");
    expect(
      screen.getByText(/请重启 Codex（或新建 CLI 会话）/)
    ).not.toBeNull();
    expect(calls.configure).toHaveBeenCalledTimes(1);
    expect(calls.configure).toHaveBeenCalledWith();
    expect(document.body.textContent).not.toContain("/Applications/");
    expect(document.body.textContent).not.toContain("index.mjs");
  });

  it("blocks automation outside Applications and gives drag instructions", async () => {
    const calls = exposeBridge({
      status: {
        ...baseStatus,
        installState: "move-to-applications",
        canConfigure: false
      }
    });
    render(<McpOnboarding />);

    await screen.findByText("先移动应用");
    expect(
      screen.getByText(/拖入“应用程序 \(Applications\)”文件夹/)
    ).not.toBeNull();
    expect(
      screen.queryByRole("button", { name: "连接 Codex" })
    ).toBeNull();
    expect(calls.configure).not.toHaveBeenCalled();
  });

  it("requires an explicit reconnect after the app moves", async () => {
    const calls = exposeBridge({
      status: {
        ...baseStatus,
        configurationState: "needs-reconnect",
        canConfigure: true,
        canClear: true
      }
    });
    render(<McpOnboarding />);

    fireEvent.click(
      await screen.findByRole("button", { name: "重新连接 Codex" })
    );
    await waitFor(() => expect(calls.configure).toHaveBeenCalledTimes(1));
  });

  it("does not offer overwrite or clear for an arbitrary same-name entry", async () => {
    const calls = exposeBridge({
      status: {
        ...baseStatus,
        configurationState: "name-conflict",
        canConfigure: false,
        canClear: false
      }
    });
    render(<McpOnboarding />);

    await screen.findByText("同名配置冲突");
    expect(
      screen.queryByRole("button", { name: /连接 Codex/ })
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "清除本应用的连接" })
    ).toBeNull();
    expect(calls.configure).not.toHaveBeenCalled();
    expect(calls.clear).not.toHaveBeenCalled();
  });

  it("presents Cursor only as a manual, non-silent fallback", async () => {
    exposeBridge({});
    render(<McpOnboarding />);

    await screen.findByText("尚未连接 Codex");
    expect(screen.getByText("Cursor：仅手动后备")).not.toBeNull();
    expect(
      screen.getByText(/不会自动配置 Cursor，也不会静默运行 Cursor CLI/)
    ).not.toBeNull();
    expect(
      screen.queryByRole("button", { name: /Cursor/ })
    ).toBeNull();
  });

  it("maps Main errors to stable copy without rendering private details", async () => {
    const calls = exposeBridge({});
    calls.configure.mockRejectedValueOnce({
      code: "name-conflict",
      executablePath: "/private/Codex With Spaces/codex",
      arguments: ["--secret"]
    });
    render(<McpOnboarding />);
    fireEvent.click(
      await screen.findByRole("button", { name: "连接 Codex" })
    );

    await screen.findByRole("alert");
    expect(screen.getByText(/为避免覆盖/)).not.toBeNull();
    expect(document.body.textContent).not.toContain("/private/");
    expect(document.body.textContent).not.toContain("--secret");
  });
});

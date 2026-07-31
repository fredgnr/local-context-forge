import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App, {
  DesktopUpdatePanel,
  LintBanner,
  Overview,
  QueryWorkspace,
  SettingsWorkspace
} from "./App";
import { ApiError, api } from "./api";
import type { AppSettings, Job, Library, LintReport } from "./types";

const libraries: Library[] = [
  { id: "library-a", name: "Library A", version: "v1" },
  { id: "library-b", name: "Library B", version: "v2" }
];

afterEach(() => {
  cleanup();
  delete window.localContextForge;
  vi.restoreAllMocks();
  vi.useRealTimers();
});

async function runQuery() {
  fireEvent.change(screen.getByLabelText("你想了解这个代码库的什么？"), {
    target: { value: "How do I create a client?" }
  });
  fireEvent.click(screen.getByRole("button", { name: "查询" }));
}

describe("query result ownership", () => {
  it("clears a successful result when the selected library changes", async () => {
    vi.spyOn(api, "query").mockResolvedValue({
      hits: [{ title: "Library A result", path: "api/a.md" }]
    });
    const view = render(
      <QueryWorkspace libraries={libraries} selectedLibraryId="library-a" />
    );

    await runQuery();
    await screen.findByText("Library A result");

    view.rerender(
      <QueryWorkspace libraries={libraries} selectedLibraryId="library-b" />
    );

    await waitFor(() =>
      expect(screen.queryByText("Library A result")).toBeNull()
    );
  });

  it("clears the last successful result before showing a later request error", async () => {
    vi.spyOn(api, "query")
      .mockResolvedValueOnce({
        hits: [{ title: "Previous result", path: "api/old.md" }]
      })
      .mockRejectedValueOnce(new Error("backend unavailable"));
    render(<QueryWorkspace libraries={libraries} selectedLibraryId="library-a" />);

    await runQuery();
    await screen.findByText("Previous result");
    await runQuery();

    expect(screen.queryByText("Previous result")).toBeNull();
    await screen.findByText("backend unavailable");
  });
});

describe("operational states", () => {
  it("keeps polling after an initial jobs failure and refreshes dependent data on recovery", async () => {
    vi.useFakeTimers();
    const librariesSpy = vi.spyOn(api, "libraries").mockResolvedValue(libraries);
    vi.spyOn(api, "health").mockResolvedValue(true);
    vi.spyOn(api, "jobs")
      .mockRejectedValueOnce(new Error("temporary jobs failure"))
      .mockResolvedValueOnce([]);

    render(<App />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(librariesSpy).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });

    expect(api.jobs).toHaveBeenCalledTimes(2);
    expect(librariesSpy).toHaveBeenCalledTimes(2);
  });

  it("refreshes dependent data when an active job becomes terminal", async () => {
    vi.useFakeTimers();
    const runningJob: Job = { id: "job-1", status: "running" };
    const completedJob: Job = { id: "job-1", status: "completed" };
    const librariesSpy = vi.spyOn(api, "libraries").mockResolvedValue(libraries);
    vi.spyOn(api, "health").mockResolvedValue(true);
    vi.spyOn(api, "jobs")
      .mockResolvedValueOnce([runningJob])
      .mockResolvedValueOnce([completedJob]);

    render(<App />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(librariesSpy).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });

    expect(librariesSpy).toHaveBeenCalledTimes(2);
  });

  it("renders backend job errors separately from the generic phase", () => {
    const failedJob: Job = {
      id: "job-failed-1",
      status: "failed",
      phase: "failed",
      message: "Ingest failed",
      error: "ValidationError: source line is outside the file",
      progress: 42
    };
    render(
      <Overview
        libraries={[]}
        jobs={[failedJob]}
        selectedLibraryId=""
        loading={false}
        onSelect={() => undefined}
        onCreate={() => undefined}
        onIngest={async () => undefined}
        onNavigate={() => undefined}
      />
    );

    expect(screen.getByText("错误详情")).not.toBeNull();
    expect(
      screen.getByText("ValidationError: source line is outside the file")
    ).not.toBeNull();
    expect(screen.getByText(/显式选择 provider、ref/)).not.toBeNull();
  });

  it("describes public GitHub and native local repository sources in desktop mode", () => {
    Object.defineProperty(window, "localContextForge", {
      configurable: true,
      value: undefined
    });
    render(
      <Overview
        libraries={[]}
        jobs={[]}
        selectedLibraryId=""
        loading={false}
        onSelect={() => undefined}
        onCreate={() => undefined}
        onIngest={async () => undefined}
        onNavigate={() => undefined}
      />
    );

    expect(
      screen.getByText("粘贴公开 GitHub HTTPS 地址，或选择 Mac 上已克隆的仓库。")
    ).not.toBeNull();
    expect(
      screen.getByText(
        "支持公开 GitHub HTTPS 地址，以及经系统选择器授权的本地仓库。"
      )
    ).not.toBeNull();
    expect(screen.queryByText("本地目录和远程 Git 地址都可以。")).toBeNull();
  });

  it("offers only the default policy or Codex when adding a repository", async () => {
    Object.defineProperty(window, "localContextForge", {
      configurable: true,
      value: undefined
    });
    vi.spyOn(api, "libraries").mockResolvedValue([]);
    vi.spyOn(api, "jobs").mockResolvedValue([]);
    vi.spyOn(api, "health").mockResolvedValue(true);

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "添加代码仓库" })
    );
    await screen.findByRole("heading", { name: "添加代码仓库" });
    fireEvent.click(screen.getByText("采集选项"));

    const providerSelect = screen.getByLabelText("文档生成器");
    expect(
      [...(providerSelect as HTMLSelectElement).options].map(
        (option) => option.value
      )
    ).toEqual(["auto", "codex"]);
  });

  it("submits an opaque one-time grant without exposing the local path", async () => {
    const selectRepository = vi.fn().mockResolvedValue({
      grantId: `lcf-local:${"ab".repeat(32)}`,
      displayName: "private-repository"
    });
    Object.defineProperty(window, "localContextForge", {
      configurable: true,
      value: {
        version: "1.0",
        api: { request: vi.fn() },
        sources: { selectRepository }
      }
    });
    vi.spyOn(api, "libraries").mockResolvedValue([]);
    vi.spyOn(api, "jobs").mockResolvedValue([]);
    vi.spyOn(api, "health").mockResolvedValue(true);
    const create = vi.spyOn(api, "createLibrary").mockResolvedValue({
      id: "private-repository",
      name: "private-repository"
    });
    const ingest = vi.spyOn(api, "ingest").mockResolvedValue({
      id: "job-local",
      status: "queued"
    });

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "添加代码仓库" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "选择本地仓库" })
    );
    await screen.findByText("private-repository");
    expect(screen.queryByText(/\/Users\//)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "添加并采集" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        name: "private-repository",
        sourceUrl: `lcf-local:${"ab".repeat(32)}`
      })
    );
    await waitFor(() =>
      expect(ingest).toHaveBeenCalledWith("private-repository", {
        generator: "auto",
        ref: "HEAD"
      })
    );
    expect(selectRepository).toHaveBeenCalledTimes(1);
  });

  it("keeps legacy provider choices in browser and Docker mode", async () => {
    vi.spyOn(api, "libraries").mockResolvedValue([]);
    vi.spyOn(api, "jobs").mockResolvedValue([]);
    vi.spyOn(api, "health").mockResolvedValue(true);

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "添加代码仓库" })
    );
    fireEvent.click(screen.getByText("采集选项"));

    const providerSelect = screen.getByLabelText("文档生成器");
    expect(
      [...(providerSelect as HTMLSelectElement).options].map(
        (option) => option.value
      )
    ).toEqual(["auto", "codex", "cursor", "mock", "ollama"]);
  });

  it("presents empty-wiki lint as neutral rather than passed", () => {
    const report: LintReport = {
      ok: true,
      errors: 0,
      warnings: 1,
      issues: [
        {
          code: "empty-wiki",
          severity: "warning",
          message: "No published pages"
        }
      ]
    };
    render(<LintBanner report={report} />);

    expect(screen.getByText("暂无已发布页面可校验")).not.toBeNull();
    expect(screen.queryByText("Wiki 校验通过")).toBeNull();
  });

  it("offers only the default policy or Codex for re-ingest", async () => {
    Object.defineProperty(window, "localContextForge", {
      configurable: true,
      value: undefined
    });
    vi.spyOn(api, "libraries").mockResolvedValue([libraries[0]]);
    vi.spyOn(api, "jobs").mockResolvedValue([]);
    vi.spyOn(api, "health").mockResolvedValue(true);
    const ingest = vi.spyOn(api, "ingest").mockResolvedValue({
      id: "new-job",
      status: "queued"
    });

    render(<App />);
    const open = await screen.findByRole("button", {
      name: "重新采集 Library A"
    });
    fireEvent.click(open);
    await screen.findByRole("heading", { name: "重新采集 Library A" });

    fireEvent.change(screen.getByLabelText(/分支/), {
      target: { value: "release/v2" }
    });
    fireEvent.change(screen.getByLabelText(/新版本标签/), {
      target: { value: "2.0.0" }
    });
    fireEvent.change(screen.getByLabelText(/文档生成器/), {
      target: { value: "codex" }
    });
    expect(screen.queryByRole("option", { name: /Cursor/ })).toBeNull();
    expect(screen.queryByRole("option", { name: /Mock/ })).toBeNull();
    expect(screen.queryByRole("option", { name: /Ollama/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "开始采集" }));

    await waitFor(() =>
      expect(ingest).toHaveBeenCalledWith("library-a", {
        generator: "codex",
        ref: "release/v2",
        version: "2.0.0"
      })
    );
  });
});

describe("runtime settings", () => {
  const currentSettings: AppSettings = {
    revision: 4,
    providerPolicy: "codex_then_cursor",
    cursorFallbackConsent: {
      subject: "cursor_cli_fallback",
      version: 1,
      granted: true,
      grantedAt: "2026-07-31T08:00:00Z"
    },
    generator: "codex",
    fallbackGenerator: "cursor",
    embeddingModel: "embeddinggemma-300m-q8",
    advanced: { maxConcurrency: 1 }
  };

  it("keeps the saved revision and reports a rebuild enqueue failure precisely", async () => {
    Object.defineProperty(window, "localContextForge", {
      configurable: true,
      value: undefined
    });
    vi.spyOn(api, "settings").mockResolvedValue(currentSettings);
    vi.spyOn(api, "embeddingModels").mockResolvedValue([
      {
        id: "embeddinggemma-300m-q8",
        model:
          "hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf",
        name: "EmbeddingGemma"
      }
    ]);
    const saved = { ...currentSettings, revision: 5 };
    const update = vi.spyOn(api, "updateSettings").mockResolvedValue(saved);
    const rebuild = vi
      .spyOn(api, "rebuild")
      .mockRejectedValue(new ApiError("Embedding rebuild already active", 409));
    const notice = vi.fn();

    render(
      <SettingsWorkspace
        libraries={[]}
        onJob={() => undefined}
        onNotice={notice}
      />
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "保存并重建全部" })
    );

    await waitFor(() => expect(update).toHaveBeenCalledWith(currentSettings));
    await waitFor(() =>
      expect(rebuild).toHaveBeenCalledWith(
        undefined,
        "embeddinggemma-300m-q8"
      )
    );
    await waitFor(() =>
      expect(notice).toHaveBeenCalledWith({
        tone: "error",
        message:
          "设置已保存，但重建未入队：Embedding rebuild already active"
      })
    );

    fireEvent.click(screen.getByRole("button", { name: "仅保存" }));
    await waitFor(() => expect(update).toHaveBeenLastCalledWith(saved));
  });

  it("requires explicit Cursor fallback consent and deduplicates saves", async () => {
    Object.defineProperty(window, "localContextForge", {
      configurable: true,
      value: undefined
    });
    const codexOnlySettings: AppSettings = {
      ...currentSettings,
      providerPolicy: "codex_only",
      cursorFallbackConsent: {
        ...currentSettings.cursorFallbackConsent,
        granted: false,
        grantedAt: null
      }
    };
    vi.spyOn(api, "settings").mockResolvedValue(codexOnlySettings);
    vi.spyOn(api, "embeddingModels").mockResolvedValue([]);
    let resolveSave!: (settings: AppSettings) => void;
    const pendingSave = new Promise<AppSettings>((resolve) => {
      resolveSave = resolve;
    });
    const update = vi
      .spyOn(api, "updateSettings")
      .mockReturnValue(pendingSave);

    render(
      <SettingsWorkspace
        libraries={[]}
        onJob={() => undefined}
        onNotice={() => undefined}
      />
    );
    const save = await screen.findByRole("button", { name: "仅保存" });
    const consent = screen.getByRole("checkbox", {
      name: /Codex 预检不可用时，允许改用 Cursor CLI/
    });
    expect((consent as HTMLInputElement).checked).toBe(false);
    expect(screen.getByText(/单独登录的 Cursor 账户和额度/)).not.toBeNull();
    expect(screen.getByText(/绝不会切换到 Cursor/)).not.toBeNull();
    expect(screen.queryByRole("radio", { name: /Cursor/ })).toBeNull();
    expect(screen.queryByText("Mock")).toBeNull();
    expect(screen.queryByText("Ollama")).toBeNull();
    fireEvent.click(consent);
    expect((consent as HTMLInputElement).checked).toBe(true);

    fireEvent.click(save);
    fireEvent.click(save);
    expect(update).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledWith({
      ...codexOnlySettings,
      providerPolicy: "codex_then_cursor",
      cursorFallbackConsent: {
        ...codexOnlySettings.cursorFallbackConsent,
        granted: true
      }
    });

    await act(async () => resolveSave({ ...currentSettings, revision: 5 }));
  });
});

describe("desktop update settings", () => {
  const idle = {
    state: "idle" as const,
    currentVersion: "1.0.0",
    channel: "latest",
    availableVersion: null,
    progress: null,
    errorCode: null,
    unavailableReason: null,
    canCheck: true,
    canDownloadOrOpen: false,
    canOpenReleasePage: false,
    automaticApply: false as const,
    automaticApplyReason: "val-update-001-not-passed" as const
  };

  it("states that automatic apply is not deliverable and opens only a verified DMG on user action", async () => {
    const available = {
      ...idle,
      state: "available" as const,
      availableVersion: "1.1.0",
      canDownloadOrOpen: true
    };
    const opened = {
      ...available,
      state: "opened" as const
    };
    const check = vi.fn().mockResolvedValue(available);
    const downloadOrOpen = vi.fn().mockResolvedValue(opened);
    let listener: ((status: typeof idle) => void) | undefined;
    Object.defineProperty(window, "localContextForge", {
      configurable: true,
      value: {
        version: "1.0",
        api: { request: vi.fn() },
        update: {
          status: vi.fn().mockResolvedValue(idle),
          check,
          downloadOrOpen,
          cancel: vi.fn().mockResolvedValue(idle),
          openReleasePage: vi.fn().mockResolvedValue(idle),
          subscribe: vi.fn((next) => {
            listener = next;
            return () => undefined;
          })
        }
      }
    });

    render(<DesktopUpdatePanel />);
    expect(await screen.findByText("自动应用未交付")).not.toBeNull();
    expect(screen.getByText(/不会静默安装/)).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "检查更新" }));
    await screen.findByText(/有可用更新/);
    fireEvent.click(
      screen.getByRole("button", { name: "下载并打开已验证 DMG" })
    );
    await screen.findByText(/请在系统打开的 DMG 中手动拖拽替换应用/);
    expect(check).toHaveBeenCalledTimes(1);
    expect(downloadOrOpen).toHaveBeenCalledTimes(1);
    expect(listener).toBeTypeOf("function");
  });

  it("shows a manual fixed-release escape only after Main permits it", async () => {
    const failed = {
      ...idle,
      state: "error" as const,
      errorCode: "open-failed" as const,
      availableVersion: "1.1.0",
      canOpenReleasePage: true
    };
    const openReleasePage = vi.fn().mockResolvedValue(failed);
    Object.defineProperty(window, "localContextForge", {
      configurable: true,
      value: {
        version: "1.0",
        api: { request: vi.fn() },
        update: {
          status: vi.fn().mockResolvedValue(failed),
          check: vi.fn().mockResolvedValue(failed),
          downloadOrOpen: vi.fn().mockRejectedValue(new Error("open failed")),
          cancel: vi.fn().mockResolvedValue(failed),
          openReleasePage,
          subscribe: vi.fn(() => () => undefined)
        }
      }
    });

    render(<DesktopUpdatePanel />);
    const manual = await screen.findByRole("button", {
      name: "手动打开官方 Release 页面"
    });
    fireEvent.click(manual);
    await waitFor(() => expect(openReleasePage).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/github\.com/)).toBeNull();
    expect(screen.queryByText(/\.dmg/)).toBeNull();
  });
});

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

  it("requires explicit provider, ref, and version for re-ingest", async () => {
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
      target: { value: "mock" }
    });
    fireEvent.click(screen.getByRole("button", { name: "开始采集" }));

    await waitFor(() =>
      expect(ingest).toHaveBeenCalledWith("library-a", {
        generator: "mock",
        ref: "release/v2",
        version: "2.0.0"
      })
    );
  });
});

describe("runtime settings", () => {
  const currentSettings: AppSettings = {
    revision: 4,
    generator: "codex",
    fallbackGenerator: "cursor",
    embeddingModel: "embeddinggemma-300m-q8",
    advanced: { maxConcurrency: 1 }
  };

  it("keeps the saved revision and reports a rebuild enqueue failure precisely", async () => {
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

  it("deduplicates concurrent save clicks and explains the Host Runner requirement", async () => {
    vi.spyOn(api, "settings").mockResolvedValue(currentSettings);
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
    expect(screen.getByText(/重新运行 installer/)).not.toBeNull();

    fireEvent.click(save);
    fireEvent.click(save);
    expect(update).toHaveBeenCalledTimes(1);

    await act(async () => resolveSave({ ...currentSettings, revision: 5 }));
  });
});

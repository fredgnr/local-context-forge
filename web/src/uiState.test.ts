import { describe, expect, it } from "vitest";
import type { DocPage, Job, LintReport } from "./types";
import {
  hasTerminalTransition,
  isEmptyWikiReport,
  selectPageAfterRefresh
} from "./uiState";

function job(id: string, status: string): Job {
  return { id, status };
}

describe("UI refresh state", () => {
  it("detects an existing active job entering a terminal state", () => {
    expect(
      hasTerminalTransition(
        [job("active", "running"), job("done", "completed")],
        [job("active", "failed"), job("done", "completed")]
      )
    ).toBe(true);
    expect(
      hasTerminalTransition([job("done", "completed")], [job("done", "completed")])
    ).toBe(false);
    expect(hasTerminalTransition([], [job("new", "completed")])).toBe(false);
  });

  it("reselects the fresh document object by path and falls back safely", () => {
    const previous: DocPage = { path: "api/client.md", title: "Old title" };
    const refreshed: DocPage[] = [
      { path: "index.md", title: "Overview" },
      { path: "api/client.md", title: "New title" }
    ];

    expect(selectPageAfterRefresh(previous, refreshed)).toBe(refreshed[1]);
    expect(
      selectPageAfterRefresh(
        { path: "removed.md", title: "Removed" },
        refreshed
      )
    ).toBe(refreshed[0]);
    expect(selectPageAfterRefresh(previous, [])).toBeUndefined();
  });

  it("recognizes the backend empty-wiki lint response as a neutral state", () => {
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

    expect(isEmptyWikiReport(report)).toBe(true);
  });
});

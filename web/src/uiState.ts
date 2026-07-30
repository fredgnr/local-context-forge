import type { DocPage, Job, LintReport } from "./types";

export const terminalStatuses = new Set([
  "succeeded",
  "completed",
  "failed",
  "rejected",
  "published"
]);

export function hasTerminalTransition(previous: Job[], next: Job[]): boolean {
  const previousStatuses = new Map(
    previous.map((job) => [job.id, job.status.toLowerCase()])
  );
  return next.some((job) => {
    const previousStatus = previousStatuses.get(job.id);
    return (
      previousStatus !== undefined &&
      !terminalStatuses.has(previousStatus) &&
      terminalStatuses.has(job.status.toLowerCase())
    );
  });
}

export function selectPageAfterRefresh(
  current: DocPage | undefined,
  nextPages: DocPage[]
): DocPage | undefined {
  if (!nextPages.length) return undefined;
  if (!current) return nextPages[0];
  return nextPages.find((page) => page.path === current.path) ?? nextPages[0];
}

export function isEmptyWikiReport(report: LintReport): boolean {
  return report.issues.some(
    (issue) => issue.code?.trim().toLowerCase() === "empty-wiki"
  );
}

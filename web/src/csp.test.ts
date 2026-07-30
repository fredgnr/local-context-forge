import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const rendererFiles = [
  join(process.cwd(), "src/App.tsx"),
  join(process.cwd(), "src/components/KnowledgeGraph.tsx"),
  join(process.cwd(), "src/components/MarkdownView.tsx")
];

describe("renderer CSP compatibility", () => {
  it("does not use JSX inline style attributes", () => {
    for (const file of rendererFiles) {
      expect(readFileSync(file, "utf8")).not.toMatch(/\bstyle\s*=/);
    }
  });

  it("does not add a CSP meta tag that would break the Vite browser workflow", () => {
    const html = readFileSync(join(process.cwd(), "index.html"), "utf8");
    expect(html).not.toMatch(/http-equiv=["']Content-Security-Policy["']/i);
  });
});

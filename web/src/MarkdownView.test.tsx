import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MarkdownView } from "./components/MarkdownView";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("only activates bounded relative Wiki links", () => {
  const openInternal = vi.fn();
  render(
    <MarkdownView
      source={[
        "[safe](api/widgets.md)",
        "[escape](../secret.md)",
        "[script](javascript:alert(1))"
      ].join(" ")}
      onInternalLink={openInternal}
    />
  );

  const safe = screen.getByRole("link", { name: "safe" });
  const escape = screen.getByRole("link", { name: "escape" });
  const script = screen.getByRole("link", { name: "script" });

  expect(safe.getAttribute("href")).toBe("#wiki/api%2Fwidgets.md");
  expect(escape.getAttribute("href")).toBe("#");
  expect(script.getAttribute("href")).toBe("#");

  fireEvent.click(safe);
  expect(openInternal).toHaveBeenCalledWith("api/widgets.md");
  fireEvent.click(escape);
  fireEvent.click(script);
  expect(openInternal).toHaveBeenCalledTimes(1);
});

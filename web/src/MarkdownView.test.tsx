import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MarkdownView } from "./components/MarkdownView";

afterEach(() => {
  cleanup();
  delete window.localContextForge;
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

it("keeps external links in the legacy browser renderer", () => {
  render(
    <MarkdownView source="[web](https://example.com) [mail](mailto:test@example.com)" />
  );

  const web = screen.getByRole("link", { name: "web" });
  const mail = screen.getByRole("link", { name: "mail" });
  expect(web.getAttribute("href")).toBe("https://example.com");
  expect(web.getAttribute("target")).toBe("_blank");
  expect(mail.getAttribute("href")).toBe("mailto:test@example.com");
});

it("renders desktop external links as blocked text while keeping Wiki links", () => {
  window.localContextForge = {
    version: "1.0",
    api: {
      request: vi.fn()
    }
  };
  const openInternal = vi.fn();
  render(
    <MarkdownView
      source="[web](https://example.com) [wiki](api/widgets.md)"
      onInternalLink={openInternal}
    />
  );

  const web = screen.getByText("web");
  expect(web.tagName).toBe("SPAN");
  expect(web.className).toContain("markdown-link--blocked");
  expect(screen.queryByRole("link", { name: "web" })).toBeNull();

  const wiki = screen.getByRole("link", { name: "wiki" });
  expect(wiki.getAttribute("href")).toBe("#wiki/api%2Fwidgets.md");
  fireEvent.click(wiki);
  expect(openInternal).toHaveBeenCalledWith("api/widgets.md");
});

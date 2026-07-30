import { Fragment, type ReactNode } from "react";

function safeRelativeWikiLink(value: string) {
  const path = value.split("#", 1)[0];
  if (
    !path ||
    path.startsWith("/") ||
    path.includes("\\") ||
    /[\u0000-\u001f]/.test(path) ||
    !path.endsWith(".md")
  ) {
    return false;
  }
  return !path
    .split("/")
    .some((part) => part === "" || part === "." || part === "..");
}

function inline(
  text: string,
  onInternalLink?: (target: string) => void
): ReactNode[] {
  const parts = text.split(/(`[^`]+`|\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link) {
      const target = link[2];
      const isExternal = /^(https?:|mailto:)/.test(target);
      const isAnchor = target.startsWith("#");
      const isInternal = safeRelativeWikiLink(target);
      const safeHref = isExternal || isAnchor
        ? target
        : isInternal
          ? `#wiki/${encodeURIComponent(target)}`
          : "#";
      return (
        <a
          key={index}
          href={safeHref}
          target={safeHref.startsWith("http") ? "_blank" : undefined}
          rel="noreferrer"
          onClick={
            isInternal && onInternalLink
              ? (event) => {
                  event.preventDefault();
                  onInternalLink(target);
                }
              : undefined
          }
        >
          {link[1]}
        </a>
      );
    }
    return <Fragment key={index}>{part}</Fragment>;
  });
}

export function MarkdownView({
  source,
  onInternalLink
}: {
  source: string;
  onInternalLink?: (target: string) => void;
}) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (line.startsWith("```")) {
      const language = line.slice(3).trim();
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        code.push(lines[index]);
        index += 1;
      }
      blocks.push(
        <div className="markdown-code" key={`code-${index}`}>
          {language && <span className="markdown-code__lang">{language}</span>}
          <pre>
            <code>{code.join("\n")}</code>
          </pre>
        </div>
      );
      index += 1;
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      const children = inline(heading[2], onInternalLink);
      blocks.push(
        level === 1 ? (
          <h1 key={index}>{children}</h1>
        ) : level === 2 ? (
          <h2 key={index}>{children}</h2>
        ) : level === 3 ? (
          <h3 key={index}>{children}</h3>
        ) : (
          <h4 key={index}>{children}</h4>
        )
      );
      index += 1;
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^[-*]\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ul key={`list-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{inline(item, onInternalLink)}</li>
          ))}
        </ul>
      );
      continue;
    }
    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\d+\.\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ol key={`ordered-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{inline(item, onInternalLink)}</li>
          ))}
        </ol>
      );
      continue;
    }
    if (line.startsWith("> ")) {
      blocks.push(
        <blockquote key={index}>{inline(line.slice(2), onInternalLink)}</blockquote>
      );
      index += 1;
      continue;
    }
    if (/^---+$/.test(line)) {
      blocks.push(<hr key={index} />);
      index += 1;
      continue;
    }
    if (line.trim()) {
      const paragraph = [line];
      index += 1;
      while (
        index < lines.length &&
        lines[index].trim() &&
        !/^(#{1,4})\s+|^```|^[-*]\s+|^\d+\.\s+|^>\s+|^---+$/.test(lines[index])
      ) {
        paragraph.push(lines[index]);
        index += 1;
      }
      blocks.push(
        <p key={`paragraph-${index}`}>
          {inline(paragraph.join(" "), onInternalLink)}
        </p>
      );
      continue;
    }
    index += 1;
  }

  return <article className="markdown">{blocks}</article>;
}

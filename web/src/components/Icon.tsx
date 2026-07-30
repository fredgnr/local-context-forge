import type { SVGProps } from "react";

export type IconName =
  | "books"
  | "check"
  | "chevron"
  | "code"
  | "copy"
  | "database"
  | "document"
  | "git"
  | "graph"
  | "home"
  | "lint"
  | "plus"
  | "refresh"
  | "review"
  | "search"
  | "settings"
  | "spark"
  | "terminal"
  | "x";

const paths: Record<IconName, React.ReactNode> = {
  books: (
    <>
      <path d="M4 5.5h5v13H4zM9 4h5v14.5H9zM15 6l4-1 2.5 12.5-4 1z" />
      <path d="M6.5 8.5h0M11.5 7h0M18.2 8.2h0" />
    </>
  ),
  check: <path d="m5 12.5 4.2 4L19 6.8" />,
  chevron: <path d="m9 6 6 6-6 6" />,
  code: (
    <>
      <path d="m9 7-5 5 5 5M15 7l5 5-5 5M13.5 4l-3 16" />
    </>
  ),
  copy: (
    <>
      <rect x="8" y="8" width="11" height="11" rx="2" />
      <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" />
    </>
  ),
  database: (
    <>
      <ellipse cx="12" cy="5.5" rx="7.5" ry="3" />
      <path d="M4.5 5.5v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6M4.5 11.5v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6" />
    </>
  ),
  document: (
    <>
      <path d="M6 3.5h8l4 4V21H6z" />
      <path d="M14 3.5v4h4M9 12h6M9 16h6" />
    </>
  ),
  git: (
    <>
      <circle cx="6" cy="5" r="2" />
      <circle cx="18" cy="6" r="2" />
      <circle cx="8" cy="19" r="2" />
      <path d="M6 7v4a4 4 0 0 0 4 4h4a4 4 0 0 0 4-4V8M8 17v-2" />
    </>
  ),
  graph: (
    <>
      <circle cx="5" cy="12" r="2.5" />
      <circle cx="18.5" cy="6" r="2.5" />
      <circle cx="18.5" cy="18" r="2.5" />
      <path d="m7.3 10.9 8.9-3.8M7.3 13.1l8.9 3.8" />
    </>
  ),
  home: (
    <>
      <path d="m3.5 10 8.5-7 8.5 7v10.5h-17z" />
      <path d="M9 20.5v-7h6v7" />
    </>
  ),
  lint: (
    <>
      <path d="M12 3 3.5 19h17z" />
      <path d="M12 9v4M12 16.5h0" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  refresh: (
    <>
      <path d="M20 7v5h-5M4 17v-5h5" />
      <path d="M6.1 8.2A7 7 0 0 1 18.6 7L20 12M4 12l1.4 5A7 7 0 0 0 18 15.8" />
    </>
  ),
  review: (
    <>
      <rect x="4" y="3.5" width="16" height="17" rx="2" />
      <path d="M8 8h8M8 12h5M8 16h3M16 15l1.5 1.5L20 14" />
    </>
  ),
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m15.5 15.5 5 5" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" />
    </>
  ),
  spark: (
    <>
      <path d="m12 2 1.5 5.1L18 10l-4.5 2.9L12 18l-1.5-5.1L6 10l4.5-2.9zM19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7zM5 2l.7 2.3L8 5l-2.3.7L5 8l-.7-2.3L2 5l2.3-.7z" />
    </>
  ),
  terminal: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="m7 9 3 3-3 3M13 15h4" />
    </>
  ),
  x: <path d="m6 6 12 12M18 6 6 18" />
};

export function Icon({
  name,
  size = 20,
  ...props
}: { name: IconName; size?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {paths[name]}
    </svg>
  );
}

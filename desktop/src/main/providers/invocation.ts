import path from "node:path";

function requireAbsoluteFile(value: string, label: string): string {
  if (!path.isAbsolute(value) || path.basename(value) === "." || value.includes("\0")) {
    throw new TypeError(`${label} must be an absolute path`);
  }
  return path.normalize(value);
}

export function buildCodexLoginStatusArguments(): readonly string[] {
  return ["login", "status"];
}

export function buildCodexExecutionArguments(input: {
  readonly outputSchemaPath: string;
  readonly outputMessagePath: string;
}): readonly string[] {
  return [
    "exec",
    "--ephemeral",
    "--ignore-user-config",
    "--ignore-rules",
    "--skip-git-repo-check",
    "--sandbox",
    "read-only",
    "--output-schema",
    requireAbsoluteFile(input.outputSchemaPath, "Output schema path"),
    "--output-last-message",
    requireAbsoluteFile(input.outputMessagePath, "Output message path"),
    "-"
  ];
}

export function buildCursorStatusArguments(): readonly string[] {
  return ["status"];
}

export function buildCursorExecutionArguments(): readonly string[] {
  // Cursor infers the prompt from piped stdin. Never use --force: the official
  // CLI documents that print mode otherwise has write/bash capabilities.
  return ["--print", "--output-format", "json"];
}

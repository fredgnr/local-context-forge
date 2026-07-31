import { realpath as systemRealpath } from "node:fs/promises";
import path from "node:path";

export const SENSITIVE_LOCAL_SOURCE_DIRECTORY_NAMES = Object.freeze([
  ".aws",
  ".azure",
  ".codex",
  ".gcp",
  ".kube",
  ".secrets",
  ".ssh",
  "secrets"
] as const);

interface LocalSourceExclusionOptions {
  readonly homeDirectory: string;
  readonly productCacheDirectory: string;
  readonly environment: NodeJS.ProcessEnv;
}

interface LocalSourceExclusionDependencies {
  readonly realpath?: (candidate: string) => Promise<string>;
}

function isCanonicalAbsolute(candidate: unknown): candidate is string {
  return (
    typeof candidate === "string" &&
    path.isAbsolute(candidate) &&
    path.resolve(candidate) === candidate &&
    candidate !== path.parse(candidate).root &&
    !candidate.includes("\0") &&
    Buffer.byteLength(candidate, "utf8") <= 4_096
  );
}

/**
 * Resolve host configuration roots that must never be treated as repositories.
 *
 * Both the lexical and real paths are retained. This covers the common case
 * where a configuration root such as ~/.codex is itself a symlink.
 */
export async function resolveLocalSourceExcludedDirectories(
  options: LocalSourceExclusionOptions,
  dependencies: LocalSourceExclusionDependencies = {}
): Promise<readonly string[]> {
  if (
    !isCanonicalAbsolute(options.homeDirectory) ||
    !isCanonicalAbsolute(options.productCacheDirectory)
  ) {
    throw new Error("Invalid local source exclusion root");
  }
  const candidates = [
    options.productCacheDirectory,
    ...SENSITIVE_LOCAL_SOURCE_DIRECTORY_NAMES.map((name) =>
      path.join(options.homeDirectory, name)
    )
  ];
  if (isCanonicalAbsolute(options.environment.CODEX_HOME)) {
    candidates.push(options.environment.CODEX_HOME);
  }

  const canonicalize = dependencies.realpath ?? systemRealpath;
  const exclusions = new Set<string>();
  for (const candidate of candidates) {
    exclusions.add(candidate);
    try {
      const resolved = await canonicalize(candidate);
      if (isCanonicalAbsolute(resolved)) {
        exclusions.add(resolved);
      }
    } catch {
      // A missing optional configuration directory is still excluded by its
      // lexical path and may safely be created after application startup.
    }
  }
  return Object.freeze([...exclusions]);
}

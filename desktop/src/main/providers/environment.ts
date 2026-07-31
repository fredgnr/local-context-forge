import type { CodexInstallation, ProviderId } from "./contracts";

const COMMON_KEYS = [
  "HOME",
  "USER",
  "LOGNAME",
  "TMPDIR",
  "LANG",
  "LC_ALL",
  "LC_CTYPE",
  "TZ"
] as const;

const SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin";

export function buildProviderEnvironment(input: {
  readonly provider: ProviderId;
  readonly source: NodeJS.ProcessEnv;
  readonly codex?: CodexInstallation;
}): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = {
    PATH: SYSTEM_PATH
  };
  for (const key of COMMON_KEYS) {
    const value = input.source[key];
    if (typeof value === "string") {
      environment[key] = value;
    }
  }
  if (
    input.provider === "codex_cli" &&
    typeof input.source.CODEX_HOME === "string"
  ) {
    environment.CODEX_HOME = input.source.CODEX_HOME;
  }
  if (input.provider === "codex_cli" && input.codex) {
    environment.CODEX_MANAGED_PACKAGE_ROOT =
      input.codex.managedPackageRoot;
    environment.CODEX_MANAGED_BY_NPM = "1";
  }
  return environment;
}

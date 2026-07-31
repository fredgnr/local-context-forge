import { constants as fsConstants, type Stats } from "node:fs";
import { access, lstat, realpath } from "node:fs/promises";
import path from "node:path";
import type {
  McpSetupCodexState,
  McpSetupConfigurationState,
  McpSetupErrorCode,
  McpSetupInstallState,
  McpSetupStatus
} from "../contracts";
import type { CodexInstallation } from "./providers/contracts";
import { revalidateCodexInstallation } from "./providers/discovery";
import { buildProviderEnvironment } from "./providers/environment";
import type { ResolvedCodex } from "./providers/providerResolver";
import {
  BoundedProcessRunner,
  type BoundedProcessResult
} from "./providers/processRunner";

export const MCP_SERVER_NAME = "local-context-forge" as const;

const COMMAND_TIMEOUT_MS = 10_000;
const COMMAND_OUTPUT_LIMIT_BYTES = 64 * 1024;
const NODE_MAX_BYTES = 512 * 1024 * 1024;
const COMPANION_MAX_BYTES = 16 * 1024 * 1024;
const APPLICATION_BUNDLE_NAME = "Local Context Forge.app";

export interface BundledCompanionTarget {
  readonly nodeExecutable: string;
  readonly companionEntry: string;
}

interface TargetFileDependencies {
  readonly access?: typeof access;
  readonly lstat?: (filePath: string) => Promise<Stats>;
  readonly realpath?: (filePath: string) => Promise<string>;
}

function isInside(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return (
    relative !== "" &&
    relative !== ".." &&
    !relative.startsWith(`..${path.sep}`) &&
    !path.isAbsolute(relative)
  );
}

async function requireDirectoryChain(
  root: string,
  parts: readonly string[],
  stat: (filePath: string) => Promise<Stats>
): Promise<void> {
  let current = root;
  const rootInfo = await stat(current);
  if (!rootInfo.isDirectory() || rootInfo.isSymbolicLink()) {
    throw new TypeError("Bundled resources root is invalid");
  }
  for (const part of parts.slice(0, -1)) {
    current = path.join(current, part);
    const info = await stat(current);
    if (!info.isDirectory() || info.isSymbolicLink()) {
      throw new TypeError("Bundled companion path is invalid");
    }
  }
}

async function requireTargetFile(
  resourcesPath: string,
  canonicalResourcesPath: string,
  parts: readonly string[],
  maximumBytes: number,
  accessMode: number,
  dependencies: TargetFileDependencies
): Promise<string> {
  const stat = dependencies.lstat ?? (lstat as (filePath: string) => Promise<Stats>);
  const resolveRealpath =
    dependencies.realpath ?? (realpath as (filePath: string) => Promise<string>);
  const checkAccess = dependencies.access ?? access;
  await requireDirectoryChain(resourcesPath, parts, stat);
  const lexicalPath = path.join(resourcesPath, ...parts);
  const info = await stat(lexicalPath);
  if (
    !info.isFile() ||
    info.isSymbolicLink() ||
    info.size <= 0 ||
    info.size > maximumBytes ||
    (info.mode & 0o022) !== 0
  ) {
    throw new TypeError("Bundled companion file is invalid");
  }
  const canonicalPath = await resolveRealpath(lexicalPath);
  if (!isInside(canonicalResourcesPath, canonicalPath)) {
    throw new TypeError("Bundled companion file escapes resources");
  }
  await checkAccess(canonicalPath, accessMode);
  return canonicalPath;
}

export async function resolveBundledCompanionTarget(
  resourcesPath: string,
  dependencies: TargetFileDependencies = {}
): Promise<BundledCompanionTarget> {
  if (
    !path.isAbsolute(resourcesPath) ||
    resourcesPath.includes("\0") ||
    path.normalize(resourcesPath) !== resourcesPath
  ) {
    throw new TypeError("Bundled resources path is invalid");
  }
  const resolveRealpath =
    dependencies.realpath ?? (realpath as (filePath: string) => Promise<string>);
  const canonicalResourcesPath = await resolveRealpath(resourcesPath);
  const nodeExecutable = await requireTargetFile(
    resourcesPath,
    canonicalResourcesPath,
    ["qmd", "node", "bin", "node"],
    NODE_MAX_BYTES,
    fsConstants.R_OK | fsConstants.X_OK,
    dependencies
  );
  const companionEntry = await requireTargetFile(
    resourcesPath,
    canonicalResourcesPath,
    ["companion", "index.mjs"],
    COMPANION_MAX_BYTES,
    fsConstants.R_OK,
    dependencies
  );
  return { nodeExecutable, companionEntry };
}

interface McpCommandRunner {
  run(
    executablePath: string,
    arguments_: readonly string[],
    options: {
      readonly environment: NodeJS.ProcessEnv;
      readonly timeoutMs: number;
      readonly outputLimitBytes: number;
      readonly signal?: AbortSignal;
    }
  ): Promise<BoundedProcessResult>;
}

export interface McpOnboardingDependencies {
  readonly resolver: { codex(): Promise<ResolvedCodex> };
  readonly runner?: McpCommandRunner;
  readonly environment?: NodeJS.ProcessEnv;
  readonly packaged: boolean;
  readonly isInApplicationsFolder: () => boolean;
  readonly resourcesPath: string;
  readonly resolveTarget?: (
    resourcesPath: string
  ) => Promise<BundledCompanionTarget>;
  readonly revalidateCodex?: (
    installation: CodexInstallation
  ) => Promise<void>;
}

interface CodexMcpConfig {
  readonly command: string;
  readonly arguments_: readonly string[];
}

interface Inspection {
  readonly status: McpSetupStatus;
  readonly installation?: CodexInstallation;
  readonly target?: BundledCompanionTarget;
}

export class McpOnboardingError extends Error {
  constructor(readonly code: McpSetupErrorCode) {
    super(`MCP onboarding failed (${code})`);
    this.name = "McpOnboardingError";
  }
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return (
    !!value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    (Object.getPrototypeOf(value) === Object.prototype ||
      Object.getPrototypeOf(value) === null)
  );
}

function isEmptyRecord(value: unknown): boolean {
  return (
    value === undefined ||
    value === null ||
    (isPlainRecord(value) && Object.keys(value).length === 0)
  );
}

function isEmptyArray(value: unknown): boolean {
  return value === undefined || value === null || (Array.isArray(value) && value.length === 0);
}

function isUnset(value: unknown): boolean {
  return value === undefined || value === null;
}

function parseCodexMcpConfig(value: unknown): CodexMcpConfig {
  if (
    !isPlainRecord(value) ||
    Object.keys(value).some(
      (key) =>
        ![
          "name",
          "enabled",
          "disabled_reason",
          "transport",
          "startup_timeout_sec",
          "tool_timeout_sec",
          "auth_status"
        ].includes(key)
    ) ||
    value.name !== MCP_SERVER_NAME ||
    value.enabled !== true ||
    !isUnset(value.disabled_reason) ||
    !isUnset(value.startup_timeout_sec) ||
    !isUnset(value.tool_timeout_sec) ||
    typeof value.auth_status !== "string" ||
    value.auth_status.length === 0 ||
    value.auth_status.length > 64 ||
    !isPlainRecord(value.transport) ||
    Object.keys(value.transport).some(
      (key) =>
        !["type", "command", "args", "env", "env_vars", "cwd"].includes(key)
    ) ||
    value.transport.type !== "stdio" ||
    typeof value.transport.command !== "string" ||
    value.transport.command.length === 0 ||
    value.transport.command.length > 8_192 ||
    value.transport.command.includes("\0") ||
    !Array.isArray(value.transport.args) ||
    value.transport.args.length > 16 ||
    !value.transport.args.every(
      (argument) =>
        typeof argument === "string" &&
        argument.length <= 8_192 &&
        !argument.includes("\0")
    ) ||
    !isEmptyRecord(value.transport.env) ||
    !isEmptyArray(value.transport.env_vars) ||
    !isUnset(value.transport.cwd)
  ) {
    throw new McpOnboardingError("invalid-response");
  }
  return {
    command: value.transport.command,
    arguments_: value.transport.args as string[]
  };
}

function parseCodexMcpList(serialized: string): CodexMcpConfig | undefined {
  let value: unknown;
  try {
    value = JSON.parse(serialized);
  } catch {
    throw new McpOnboardingError("invalid-response");
  }
  if (!Array.isArray(value) || value.length > 256) {
    throw new McpOnboardingError("invalid-response");
  }
  const matches = value.filter(
    (entry) => isPlainRecord(entry) && entry.name === MCP_SERVER_NAME
  );
  if (matches.length === 0) {
    return undefined;
  }
  if (matches.length !== 1) {
    throw new McpOnboardingError("invalid-response");
  }
  return parseCodexMcpConfig(matches[0]);
}

function assertSuccessfulCommand(result: BoundedProcessResult): void {
  if (result.cancelled || result.spawnErrorCode) {
    throw new McpOnboardingError("unavailable");
  }
  if (result.timedOut) {
    throw new McpOnboardingError("timeout");
  }
  if (result.outputLimitExceeded) {
    throw new McpOnboardingError("invalid-response");
  }
  if (result.exitCode !== 0) {
    throw new McpOnboardingError("unavailable");
  }
}

function codexState(resolved: ResolvedCodex): McpSetupCodexState {
  switch (resolved.preflight.state) {
    case "not_installed":
      return "not-installed";
    case "not_authenticated":
      return "not-authenticated";
    case "unsupported_installation":
      return "unsupported-installation";
    case "unavailable":
      return "unavailable";
    default:
      return "ready";
  }
}

function configurationState(
  config: CodexMcpConfig | undefined,
  target: BundledCompanionTarget | undefined
): McpSetupConfigurationState {
  if (!config) {
    return "not-configured";
  }
  if (
    target &&
    config.command === target.nodeExecutable &&
    config.arguments_.length === 1 &&
    config.arguments_[0] === target.companionEntry
  ) {
    return "configured";
  }
  if (isRecognizableLcfTarget(config)) {
    return "needs-reconnect";
  }
  return "name-conflict";
}

function isRecognizableLcfTarget(config: CodexMcpConfig): boolean {
  if (
    !path.isAbsolute(config.command) ||
    path.normalize(config.command) !== config.command ||
    config.arguments_.length !== 1
  ) {
    return false;
  }
  const companion = config.arguments_[0];
  if (
    !companion ||
    !path.isAbsolute(companion) ||
    path.normalize(companion) !== companion
  ) {
    return false;
  }
  const nodeResources = path.resolve(config.command, "..", "..", "..", "..");
  const companionResources = path.resolve(companion, "..", "..");
  return (
    nodeResources === companionResources &&
    path.basename(nodeResources) === "Resources" &&
    path.basename(path.dirname(nodeResources)) === "Contents" &&
    path.basename(path.dirname(path.dirname(nodeResources))) ===
      APPLICATION_BUNDLE_NAME &&
    config.command ===
      path.join(nodeResources, "qmd", "node", "bin", "node") &&
    companion === path.join(nodeResources, "companion", "index.mjs")
  );
}

function installState(
  packaged: boolean,
  isInApplicationsFolder: () => boolean
): McpSetupInstallState {
  if (!packaged) {
    return "source-debug";
  }
  try {
    return isInApplicationsFolder() ? "ready" : "move-to-applications";
  } catch {
    return "move-to-applications";
  }
}

export class McpOnboardingService {
  private readonly runner: McpCommandRunner;
  private readonly environment: NodeJS.ProcessEnv;
  private readonly resolveTarget: NonNullable<
    McpOnboardingDependencies["resolveTarget"]
  >;
  private readonly revalidateCodex: NonNullable<
    McpOnboardingDependencies["revalidateCodex"]
  >;
  private active:
    | {
        readonly controller: AbortController;
        readonly promise: Promise<unknown>;
      }
    | undefined;
  private stopping = false;
  private restartRequired = false;

  constructor(private readonly dependencies: McpOnboardingDependencies) {
    this.runner = dependencies.runner ?? new BoundedProcessRunner();
    this.environment = dependencies.environment ?? process.env;
    this.resolveTarget =
      dependencies.resolveTarget ?? resolveBundledCompanionTarget;
    this.revalidateCodex =
      dependencies.revalidateCodex ?? revalidateCodexInstallation;
  }

  status(): Promise<McpSetupStatus> {
    return this.exclusive(async (signal) => (await this.inspect(signal)).status);
  }

  configure(): Promise<McpSetupStatus> {
    return this.exclusive(async (signal) => {
      const inspection = await this.inspect(signal);
      this.assertConfigurable(inspection);
      if (inspection.status.configurationState === "configured") {
        return inspection.status;
      }
      const installation = inspection.installation;
      const target = inspection.target;
      if (!installation || !target) {
        throw new McpOnboardingError("unavailable");
      }
      await this.runCodex(
        installation,
        [
          "mcp",
          "add",
          MCP_SERVER_NAME,
          "--",
          target.nodeExecutable,
          target.companionEntry
        ],
        signal
      );
      const config = await this.getConfig(installation, signal);
      if (configurationState(config, target) !== "configured") {
        throw new McpOnboardingError("invalid-response");
      }
      this.restartRequired = true;
      return this.buildStatus(
        inspection.status.codexState,
        inspection.status.installState,
        "configured",
        false
      );
    });
  }

  clear(): Promise<McpSetupStatus> {
    return this.exclusive(async (signal) => {
      const inspection = await this.inspect(signal);
      const state = inspection.status.configurationState;
      if (!inspection.installation) {
        throw new McpOnboardingError(
          inspection.status.codexState === "not-installed"
            ? "not-installed"
            : inspection.status.codexState === "unsupported-installation"
              ? "unsupported-installation"
              : "unavailable"
        );
      }
      if (state === "name-conflict") {
        throw new McpOnboardingError("name-conflict");
      }
      if (state === "not-configured") {
        return inspection.status;
      }
      if (state !== "configured" && state !== "needs-reconnect") {
        throw new McpOnboardingError("unavailable");
      }
      await this.runCodex(
        inspection.installation,
        ["mcp", "remove", MCP_SERVER_NAME],
        signal
      );
      const config = await this.getConfig(inspection.installation, signal);
      if (config) {
        throw new McpOnboardingError(
          isRecognizableLcfTarget(config)
            ? "invalid-response"
            : "name-conflict"
        );
      }
      this.restartRequired = true;
      return this.buildStatus(
        inspection.status.codexState,
        inspection.status.installState,
        "not-configured",
        false
      );
    });
  }

  async shutdown(): Promise<void> {
    this.stopping = true;
    this.active?.controller.abort();
    await this.active?.promise.catch(() => undefined);
  }

  private exclusive<T>(
    operation: (signal: AbortSignal) => Promise<T>
  ): Promise<T> {
    if (this.stopping) {
      return Promise.reject(new McpOnboardingError("unavailable"));
    }
    if (this.active) {
      return Promise.reject(new McpOnboardingError("busy"));
    }
    const controller = new AbortController();
    const promise = operation(controller.signal);
    this.active = { controller, promise };
    return promise.finally(() => {
      if (this.active?.promise === promise) {
        this.active = undefined;
      }
    });
  }

  private async inspect(signal: AbortSignal): Promise<Inspection> {
    const initialInstallState = installState(
      this.dependencies.packaged,
      this.dependencies.isInApplicationsFolder
    );
    let resolved: ResolvedCodex;
    try {
      resolved = await this.dependencies.resolver.codex();
    } catch {
      return {
        status: this.buildStatus(
          "unavailable",
          initialInstallState,
          "unknown",
          false
        )
      };
    }
    const currentCodexState = codexState(resolved);
    const installation =
      "installation" in resolved ? resolved.installation : undefined;
    let currentInstallState = initialInstallState;
    let target: BundledCompanionTarget | undefined;
    if (currentInstallState === "ready") {
      try {
        target = await this.resolveTarget(this.dependencies.resourcesPath);
      } catch {
        currentInstallState = "bundle-invalid";
      }
    }
    if (!installation) {
      return {
        status: this.buildStatus(
          currentCodexState,
          currentInstallState,
          "unknown",
          false
        )
      };
    }
    const config = await this.getConfig(installation, signal);
    const currentConfigurationState = configurationState(config, target);
    return {
      status: this.buildStatus(
        currentCodexState,
        currentInstallState,
        currentConfigurationState,
        currentCodexState === "ready" &&
          currentInstallState === "ready" &&
          (currentConfigurationState === "not-configured" ||
            currentConfigurationState === "needs-reconnect")
      ),
      installation,
      ...(target ? { target } : {})
    };
  }

  private buildStatus(
    currentCodexState: McpSetupCodexState,
    currentInstallState: McpSetupInstallState,
    currentConfigurationState: McpSetupConfigurationState,
    canConfigure: boolean
  ): McpSetupStatus {
    return {
      provider: "codex_cli",
      codexState: currentCodexState,
      configurationState: currentConfigurationState,
      installState: currentInstallState,
      canConfigure,
      canClear:
        currentConfigurationState === "configured" ||
        currentConfigurationState === "needs-reconnect",
      restartRequired: this.restartRequired
    };
  }

  private assertConfigurable(inspection: Inspection): void {
    const { status } = inspection;
    if (status.installState !== "ready") {
      throw new McpOnboardingError(status.installState);
    }
    if (status.codexState !== "ready") {
      throw new McpOnboardingError(status.codexState);
    }
    if (status.configurationState === "name-conflict") {
      throw new McpOnboardingError("name-conflict");
    }
    if (
      status.configurationState !== "configured" &&
      !status.canConfigure
    ) {
      throw new McpOnboardingError("unavailable");
    }
  }

  private async getConfig(
    installation: CodexInstallation,
    signal: AbortSignal
  ): Promise<CodexMcpConfig | undefined> {
    const result = await this.runCodexRaw(
      installation,
      ["mcp", "list", "--json"],
      signal
    );
    assertSuccessfulCommand(result);
    return parseCodexMcpList(result.stdout);
  }

  private async runCodex(
    installation: CodexInstallation,
    arguments_: readonly string[],
    signal: AbortSignal
  ): Promise<void> {
    assertSuccessfulCommand(
      await this.runCodexRaw(installation, arguments_, signal)
    );
  }

  private async runCodexRaw(
    installation: CodexInstallation,
    arguments_: readonly string[],
    signal: AbortSignal
  ): Promise<BoundedProcessResult> {
    try {
      await this.revalidateCodex(installation);
    } catch {
      throw new McpOnboardingError("unsupported-installation");
    }
    return await this.runner.run(
      installation.executable.canonicalPath,
      arguments_,
      {
        environment: buildProviderEnvironment({
          provider: "codex_cli",
          source: this.environment,
          codex: installation
        }),
        timeoutMs: COMMAND_TIMEOUT_MS,
        outputLimitBytes: COMMAND_OUTPUT_LIMIT_BYTES,
        signal
      }
    );
  }
}

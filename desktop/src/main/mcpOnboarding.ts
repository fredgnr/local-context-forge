import { createHash } from "node:crypto";
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
import {
  FileMcpTargetOwnershipStore,
  MCP_TARGET_OWNER_ENV,
  isMcpTargetOwned,
  type McpOwnedTarget,
  type McpTargetOwnership,
  type McpTargetOwnershipStore
} from "./mcpTargetOwnership";

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
  readonly effectiveUid?: number;
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
  stat: (filePath: string) => Promise<Stats>,
  resolveRealpath: (filePath: string) => Promise<string>,
  effectiveUid: number
): Promise<void> {
  let current = root;
  await requireTrustedDirectory(
    current,
    stat,
    resolveRealpath,
    effectiveUid,
    "Bundled resources root"
  );
  for (const part of parts.slice(0, -1)) {
    current = path.join(current, part);
    await requireTrustedDirectory(
      current,
      stat,
      resolveRealpath,
      effectiveUid,
      "Bundled companion path"
    );
  }
}

async function requireTrustedDirectory(
  directory: string,
  stat: (filePath: string) => Promise<Stats>,
  resolveRealpath: (filePath: string) => Promise<string>,
  effectiveUid: number,
  label: string
): Promise<void> {
  const info = await stat(directory);
  if (
    !info.isDirectory() ||
    info.isSymbolicLink() ||
    (info.uid !== 0 && info.uid !== effectiveUid) ||
    (info.mode & 0o7022) !== 0 ||
    (await resolveRealpath(directory)) !== directory
  ) {
    throw new TypeError(`${label} is invalid`);
  }
}

async function requireTargetFile(
  resourcesPath: string,
  canonicalResourcesPath: string,
  parts: readonly string[],
  maximumBytes: number,
  accessMode: number,
  effectiveUid: number,
  dependencies: TargetFileDependencies
): Promise<string> {
  const stat = dependencies.lstat ?? (lstat as (filePath: string) => Promise<Stats>);
  const resolveRealpath =
    dependencies.realpath ?? (realpath as (filePath: string) => Promise<string>);
  const checkAccess = dependencies.access ?? access;
  await requireDirectoryChain(
    resourcesPath,
    parts,
    stat,
    resolveRealpath,
    effectiveUid
  );
  const lexicalPath = path.join(resourcesPath, ...parts);
  const info = await stat(lexicalPath);
  if (
    !info.isFile() ||
    info.isSymbolicLink() ||
    info.size <= 0 ||
    info.size > maximumBytes ||
    (info.uid !== 0 && info.uid !== effectiveUid) ||
    (info.mode & 0o7022) !== 0
  ) {
    throw new TypeError("Bundled companion file is invalid");
  }
  const canonicalPath = await resolveRealpath(lexicalPath);
  if (
    canonicalPath !== lexicalPath ||
    !isInside(canonicalResourcesPath, canonicalPath)
  ) {
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
  const effectiveUid =
    dependencies.effectiveUid ??
    process.geteuid?.() ??
    process.getuid?.() ??
    -1;
  if (!Number.isSafeInteger(effectiveUid) || effectiveUid < 0) {
    throw new TypeError("Effective uid is unavailable");
  }
  const contentsPath = path.dirname(resourcesPath);
  const bundlePath = path.dirname(contentsPath);
  if (
    path.basename(resourcesPath) !== "Resources" ||
    path.basename(contentsPath) !== "Contents" ||
    path.basename(bundlePath) !== APPLICATION_BUNDLE_NAME
  ) {
    throw new TypeError("Bundled resources layout is invalid");
  }
  const stat = dependencies.lstat ?? (lstat as (filePath: string) => Promise<Stats>);
  await requireTrustedDirectory(
    bundlePath,
    stat,
    resolveRealpath,
    effectiveUid,
    "Application bundle"
  );
  await requireTrustedDirectory(
    contentsPath,
    stat,
    resolveRealpath,
    effectiveUid,
    "Application Contents"
  );
  const canonicalResourcesPath = await resolveRealpath(resourcesPath);
  if (canonicalResourcesPath !== resourcesPath) {
    throw new TypeError("Bundled resources path is not canonical");
  }
  const nodeExecutable = await requireTargetFile(
    resourcesPath,
    canonicalResourcesPath,
    ["qmd", "node", "bin", "node"],
    NODE_MAX_BYTES,
    fsConstants.R_OK | fsConstants.X_OK,
    effectiveUid,
    dependencies
  );
  const companionEntry = await requireTargetFile(
    resourcesPath,
    canonicalResourcesPath,
    ["companion", "index.mjs"],
    COMPANION_MAX_BYTES,
    fsConstants.R_OK,
    effectiveUid,
    dependencies
  );
  return { nodeExecutable, companionEntry };
}

interface McpCommandRunner {
  run(
    executablePath: string,
    arguments_: readonly string[],
    options: {
      readonly cwd?: string;
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
  readonly dataDirectory: string;
  readonly resourcesPath: string;
  readonly ownershipStore?: McpTargetOwnershipStore;
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
  readonly ownerMarker?: string;
}

type OwnershipInspection =
  | { readonly kind: "missing" }
  | {
      readonly kind: "valid";
      readonly state: McpTargetOwnership;
    }
  | { readonly kind: "invalid" };

interface ConfigurationInspection {
  readonly config?: CodexMcpConfig;
  readonly ownership: OwnershipInspection;
}

interface Inspection {
  readonly status: McpSetupStatus;
  readonly installation?: CodexInstallation;
  readonly target?: BundledCompanionTarget;
  readonly configuration?: ConfigurationInspection;
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

function isEmptyArray(value: unknown): boolean {
  return value === undefined || value === null || (Array.isArray(value) && value.length === 0);
}

function isUnset(value: unknown): boolean {
  return value === undefined || value === null;
}

function parseTransportEnvironment(
  value: unknown
): Readonly<Record<string, string>> {
  if (value === undefined || value === null) {
    return {};
  }
  if (!isPlainRecord(value) || Object.keys(value).length > 16) {
    throw new McpOnboardingError("invalid-response");
  }
  const result = Object.create(null) as Record<string, string>;
  for (const [key, entry] of Object.entries(value)) {
    if (
      !/^[A-Za-z_][A-Za-z0-9_]{0,127}$/.test(key) ||
      typeof entry !== "string" ||
      Buffer.byteLength(entry, "utf8") > 8_192 ||
      entry.includes("\0")
    ) {
      throw new McpOnboardingError("invalid-response");
    }
    result[key] = entry;
  }
  return result;
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
    !isEmptyArray(value.transport.env_vars) ||
    !isUnset(value.transport.cwd)
  ) {
    throw new McpOnboardingError("invalid-response");
  }
  const environment = parseTransportEnvironment(value.transport.env);
  const environmentKeys = Object.keys(environment);
  const ownerMarker =
    environmentKeys.length === 1 &&
    environmentKeys[0] === MCP_TARGET_OWNER_ENV
      ? environment[MCP_TARGET_OWNER_ENV]
      : undefined;
  return {
    command: value.transport.command,
    arguments_: value.transport.args as string[],
    ...(ownerMarker === undefined ? {} : { ownerMarker })
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
  target: BundledCompanionTarget | undefined,
  ownership: OwnershipInspection
): McpSetupConfigurationState {
  if (!config) {
    if (ownership.kind === "invalid") {
      return "unknown";
    }
    return "not-configured";
  }
  if (
    ownership.kind !== "valid" ||
    !isOwnedConfiguration(config, ownership.state)
  ) {
    return "name-conflict";
  }
  if (
    target &&
    config.command === target.nodeExecutable &&
    config.arguments_.length === 1 &&
    config.arguments_[0] === target.companionEntry
  ) {
    return "configured";
  }
  return "needs-reconnect";
}

function configuredTarget(
  config: CodexMcpConfig
): McpOwnedTarget | undefined {
  if (
    !path.isAbsolute(config.command) ||
    path.normalize(config.command) !== config.command ||
    config.arguments_.length !== 1
  ) {
    return undefined;
  }
  const companion = config.arguments_[0];
  if (
    !companion ||
    !path.isAbsolute(companion) ||
    path.normalize(companion) !== companion
  ) {
    return undefined;
  }
  return {
    command: config.command,
    arguments_: [companion]
  };
}

function bundledTarget(target: BundledCompanionTarget): McpOwnedTarget {
  return {
    command: target.nodeExecutable,
    arguments_: [target.companionEntry]
  };
}

function isOwnedConfiguration(
  config: CodexMcpConfig,
  ownership: McpTargetOwnership
): boolean {
  const target = configuredTarget(config);
  return (
    target !== undefined &&
    isMcpTargetOwned(ownership, config.ownerMarker, target)
  );
}

function uniqueTargets(
  targets: readonly McpOwnedTarget[]
): readonly McpOwnedTarget[] {
  return targets.filter(
    (target, index) =>
      targets.findIndex(
        (candidate) =>
          candidate.command === target.command &&
          candidate.arguments_[0] === target.arguments_[0]
      ) === index
  );
}

function sameCodexMcpConfig(
  left: CodexMcpConfig | undefined,
  right: CodexMcpConfig | undefined
): boolean {
  if (!left || !right) {
    return left === right;
  }
  return (
    left.command === right.command &&
    left.ownerMarker === right.ownerMarker &&
    left.arguments_.length === right.arguments_.length &&
    left.arguments_.every(
      (argument, index) => argument === right.arguments_[index]
    )
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

function normalizedConfigurationPath(
  value: unknown
): string | undefined {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    Buffer.byteLength(value, "utf8") > 4_096 ||
    value.includes("\0") ||
    !path.isAbsolute(value) ||
    path.normalize(value) !== value ||
    value === path.parse(value).root
  ) {
    return undefined;
  }
  return value;
}

export function resolveCodexOwnershipScope(
  environment: NodeJS.ProcessEnv
): string | undefined {
  const explicit = environment.CODEX_HOME;
  const home = normalizedConfigurationPath(environment.HOME);
  const codexHome =
    explicit === undefined
      ? home
        ? path.join(home, ".codex")
        : undefined
      : normalizedConfigurationPath(explicit);
  if (!codexHome) {
    return undefined;
  }
  return createHash("sha256")
    .update("lcf-codex-config-scope-v1\0", "utf8")
    .update(codexHome, "utf8")
    .digest("hex");
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
  private readonly ownershipStore: McpTargetOwnershipStore;
  private readonly configurationScopeAvailable: boolean;
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
    const scopeId = resolveCodexOwnershipScope(this.environment);
    this.configurationScopeAvailable = scopeId !== undefined;
    this.ownershipStore =
      dependencies.ownershipStore ??
      new FileMcpTargetOwnershipStore(dependencies.dataDirectory, {
        scopeId: scopeId ?? "0".repeat(64)
      });
  }

  status(): Promise<McpSetupStatus> {
    return this.exclusive(async (signal) => (await this.inspect(signal)).status);
  }

  configure(): Promise<McpSetupStatus> {
    return this.exclusive(async (signal) => {
      const inspection = await this.inspect(signal);
      this.assertConfigurable(inspection);
      const installation = inspection.installation;
      const target = inspection.target;
      const configuration = inspection.configuration;
      if (!installation || !target || !configuration) {
        throw new McpOnboardingError("unavailable");
      }
      const currentTarget = bundledTarget(target);
      if (inspection.status.configurationState === "configured") {
        if (configuration.ownership.kind !== "valid") {
          throw new McpOnboardingError("unavailable");
        }
        await this.stageOwnership(
          configuration.ownership.state,
          [currentTarget]
        );
        return inspection.status;
      }
      const previousOwnership =
        configuration.ownership.kind === "valid"
          ? configuration.ownership.state
          : undefined;
      const configured = configuration.config
        ? configuredTarget(configuration.config)
        : undefined;
      const staged = await this.stageOwnership(
        previousOwnership,
        uniqueTargets([
          ...(configured ? [configured] : []),
          currentTarget
        ])
      );
      const rechecked = await this.getConfig(installation, signal);
      if (
        !sameCodexMcpConfig(configuration.config, rechecked) ||
        (rechecked !== undefined &&
          !isOwnedConfiguration(rechecked, staged))
      ) {
        throw new McpOnboardingError("name-conflict");
      }
      await this.runCodex(
        installation,
        [
          "mcp",
          "add",
          MCP_SERVER_NAME,
          "--env",
          `${MCP_TARGET_OWNER_ENV}=${staged.marker}`,
          "--",
          target.nodeExecutable,
          target.companionEntry
        ],
        signal
      );
      this.restartRequired = true;
      const config = await this.getConfig(installation, signal);
      if (
        configurationState(config, target, {
          kind: "valid",
          state: staged
        }) !== "configured"
      ) {
        throw new McpOnboardingError("invalid-response");
      }
      await this.stageOwnership(staged, [currentTarget]);
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
      const configuration = inspection.configuration;
      if (inspection.status.installState !== "ready") {
        throw new McpOnboardingError(inspection.status.installState);
      }
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
        if (configuration?.ownership.kind === "valid") {
          await this.removeOwnership(configuration.ownership.state);
        }
        return inspection.status;
      }
      if (state !== "configured" && state !== "needs-reconnect") {
        throw new McpOnboardingError("unavailable");
      }
      if (
        !configuration ||
        configuration.ownership.kind !== "valid"
      ) {
        throw new McpOnboardingError("unavailable");
      }
      const ownership = configuration.ownership.state;
      const rechecked = await this.getConfig(
        inspection.installation,
        signal
      );
      if (
        !sameCodexMcpConfig(configuration.config, rechecked) ||
        !rechecked ||
        !isOwnedConfiguration(rechecked, ownership)
      ) {
        throw new McpOnboardingError("name-conflict");
      }
      await this.runCodex(
        inspection.installation,
        ["mcp", "remove", MCP_SERVER_NAME],
        signal
      );
      this.restartRequired = true;
      const config = await this.getConfig(inspection.installation, signal);
      if (config) {
        throw new McpOnboardingError(
          isOwnedConfiguration(config, ownership)
            ? "invalid-response"
            : "name-conflict"
        );
      }
      await this.removeOwnership(ownership);
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
    if (!this.configurationScopeAvailable) {
      return {
        status: this.buildStatus(
          "unavailable",
          initialInstallState,
          "unknown",
          false
        )
      };
    }
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
    let ownership = await this.inspectOwnership();
    if (
      target &&
      config &&
      ownership.kind === "valid" &&
      ownership.state.targets.length > 1 &&
      isOwnedConfiguration(config, ownership.state) &&
      config.command === target.nodeExecutable &&
      config.arguments_.length === 1 &&
      config.arguments_[0] === target.companionEntry
    ) {
      ownership = {
        kind: "valid",
        state: await this.stageOwnership(
          ownership.state,
          [bundledTarget(target)]
        )
      };
    }
    const currentConfigurationState = configurationState(
      config,
      target,
      ownership
    );
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
      ...(target ? { target } : {}),
      configuration: {
        ...(config ? { config } : {}),
        ownership
      }
    };
  }

  private async inspectOwnership(): Promise<OwnershipInspection> {
    try {
      const state = await this.ownershipStore.read();
      return state
        ? { kind: "valid", state }
        : { kind: "missing" };
    } catch {
      return { kind: "invalid" };
    }
  }

  private async stageOwnership(
    expected: McpTargetOwnership | undefined,
    targets: readonly McpOwnedTarget[]
  ): Promise<McpTargetOwnership> {
    try {
      return await this.ownershipStore.stage(expected, targets);
    } catch {
      throw new McpOnboardingError("unavailable");
    }
  }

  private async removeOwnership(
    expected: McpTargetOwnership
  ): Promise<void> {
    try {
      await this.ownershipStore.remove(expected);
    } catch {
      throw new McpOnboardingError("unavailable");
    }
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
        currentInstallState === "ready" &&
        currentCodexState === "ready" &&
        (currentConfigurationState === "configured" ||
          currentConfigurationState === "needs-reconnect"),
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
        cwd: this.dependencies.dataDirectory,
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
